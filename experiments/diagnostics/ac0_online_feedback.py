"""Development-only online feedback scaffold. No confirming entry point.

Uses the registered schedule and unchanged FrozenGoalPredictor readout.
A complete protocol audit/confirming implementation manifest is still required.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import pickle
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld, UNKNOWN
from experiments.diagnostics.ac0_kernel_binding import digest
from experiments.diagnostics.ac0_frozen_goal import FrozenGoalPredictor, BoundaryError, select_goal
from experiments.diagnostics.ac0_goal_evaluator import traced_training, prediction_receipts, ensure_fresh_output
from experiments.diagnostics.ac0_online_protocol import DEFAULT, POLICIES, PUBLIC_FIELDS, schedule_layout, validate_protocol
from experiments.diagnostics.ac0_recall_ablation import model_fingerprint

PROTOCOL_SHA = '1e9d406567a5b6a0badb5a127c5457688cd1915b282674a7c54f1511b4f58347'


def protocol():
    raw = DEFAULT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROTOCOL_SHA:
        raise BoundaryError('registered protocol bytes changed')
    config = json.loads(raw)
    validate_protocol(config)
    return config


class Budget:
    def __init__(self, limits, clock=time.perf_counter):
        self.limits, self.clock = limits, clock
        self.started = clock()
        self.counts = dict.fromkeys(('train_actions', 'train_core_tokens',
                                    'evaluation_opportunities', 'evaluation_actions',
                                    'all_core_tokens'), 0)

    def check(self):
        if self.clock() - self.started > self.limits['max_wall_seconds_complete_run']:
            raise BoundaryError('complete-run wall budget exceeded')

    def charge(self, name, count=1):
        self.check()
        proposed = dict(self.counts)
        proposed[name] += count
        if name == 'train_core_tokens':
            proposed['all_core_tokens'] += count
        for key, value in proposed.items():
            if value > self.limits['max_' + key + '_total']:
                raise BoundaryError(key + ' budget exceeded')
        if proposed['train_actions'] + proposed['evaluation_actions'] > self.limits['max_all_world_actions_total']:
            raise BoundaryError('all world actions budget exceeded')
        self.counts = proposed


def gen_state(observer):
    return {g.gen_id: {'feature_chain': list(g.feature_chain),
                      'success_count': g.success_count, 'stop_count': g.stop_count,
                      'variation_count': g.variation_count}
            for g in observer.system.base.all()}


def state_delta(before, after):
    return [{'gen_id': gid, 'before': before.get(gid), 'after': after.get(gid)}
            for gid in sorted(before.keys() | after.keys())
            if before.get(gid) != after.get(gid)]


def validate_delivery(observer, event):
    """All checks precede bookkeeping/native ingestion, including duplicate."""
    if (event.run_id, event.event_id) in observer.seen:
        raise ValueError('duplicate event')
    if (not observer.event_pending or observer.view is None or
            event.channel_id != observer.view['channel_id'] or
            event.observation_id != observer.view['observation_id']):
        raise ValueError('event does not belong to pending cue')
    if event.chosen_operation not in observer.view['available_operations']:
        raise ValueError('operation is not available')
    if event.completion not in UNKNOWN | {'success', 'observed_divergence'}:
        raise ValueError('unsupported completion status')
    if (event.completion in UNKNOWN) != (event.actual_observation is None):
        raise ValueError('completion/actual observation mismatch')


def deliver_feedback(observer, event, *, admitted):
    """Admit actual native transitions or close delivery without fabricating unknown.

    Fingerprint is taken AFTER begin. Receipt seen/pending bookkeeping can change,
    but unknown/withheld feedback cannot change base, features, origins or steps.
    """
    if type(admitted) is not bool:
        raise ValueError('boolean admission required')
    validate_delivery(observer, event)
    before_hash, before_gens = model_fingerprint(observer), gen_state(observer)
    if admitted or event.completion in UNKNOWN:
        steps = observer.complete(event)
    else:
        # No replacement/fake event, no process_token, no reset_context here.
        observer.seen.add((event.run_id, event.event_id))
        observer.event_pending = False
        steps = []
    after_hash, after_gens = model_fingerprint(observer), gen_state(observer)
    assimilated = admitted and event.completion not in UNKNOWN
    if not assimilated and before_hash != after_hash:
        raise BoundaryError('unknown/withheld feedback mutated native snapshot')
    return {'admitted': admitted, 'assimilated': assimilated,
            'actual_completion': event.completion,
            'native_before': before_hash, 'native_after': after_hash,
            'native_unchanged': before_hash == after_hash,
            'tokens': steps, 'gen_deltas': state_delta(before_gens, after_gens)}


class AdaptiveTable:
    def __init__(self, events):
        self.values = {}
        self.seen = set()
        for event in events:
            if event['completion'] not in UNKNOWN:
                self.values[(event['channel_id'], event['observation_id'],
                             event['chosen_operation'])] = event['actual_observation']

    def query(self, view):
        if set(view) != PUBLIC_FIELDS:
            raise ValueError('only public controller view accepted')
        forecasts = [{'operation_id': op, 'predicted_observation': self.values[key]}
                     for op in view['available_operations']
                     if (key := (view['channel_id'], view['observation_id'], op)) in self.values]
        return {'operation_id': select_goal(forecasts, view['available_operations'],
                                           view['goal_observation_id']),
                'forecasts': forecasts, 'table_keys': len(self.values)}

    def update(self, event, *, admitted):
        key = (event.run_id, event.event_id)
        if key in self.seen:
            raise ValueError('duplicate table receipt')
        before = dict(self.values)
        if admitted and event.completion not in UNKNOWN:
            self.values[(event.channel_id, event.observation_id,
                         event.chosen_operation)] = event.actual_observation
        self.seen.add(key)
        return {'admitted': admitted, 'assimilated': before != self.values,
                'table_unchanged': before == self.values}


class NativePolicy:
    def __init__(self, trained, *, online, limits):
        self.observer = deepcopy(trained)
        self.online = online
        self.limits = limits
        self.initial_full_digest = self.full_digest()
        self.receipts = set()

    def full_digest(self):
        return hashlib.sha256(pickle.dumps(self.observer, protocol=5)).hexdigest()

    def query(self, view, budget):
        if set(view) != PUBLIC_FIELDS:
            raise ValueError('only public controller view accepted')
        before = gen_state(self.observer)
        cue, info = None, None
        if self.online:
            budget.charge('all_core_tokens')
            cue, _, info = self.observer.begin(view, recall_policy='exact_learned_prefix')
        after = gen_state(self.observer)
        predictor = FrozenGoalPredictor(
            self.observer,
            max_gen_visits=self.limits['max_gen_records_visited_per_query'],
            max_feature_lookups=self.limits['max_feature_origin_lookups_per_query'],
            max_model_bytes=self.limits['max_serialized_model_bytes_per_instance'])
        query = predictor.query(view)
        return query, {'cue_token': cue, 'recall_info': info,
                       'begin_gen_deltas': state_delta(before, after)}

    def feedback(self, event, *, admitted, budget):
        key = (event.run_id, event.event_id)
        if key in self.receipts:
            raise ValueError('duplicate policy receipt')
        if self.online:
            if admitted and event.completion not in UNKNOWN:
                budget.charge('all_core_tokens', 2)
            result = deliver_feedback(self.observer, event, admitted=admitted)
        else:
            if self.full_digest() != self.initial_full_digest:
                raise BoundaryError('frozen model mutated')
            result = {'admitted': False, 'assimilated': False, 'native_unchanged': True,
                      'native_before': self.initial_full_digest,
                      'native_after': self.initial_full_digest, 'tokens': [], 'gen_deltas': []}
        self.receipts.add(key)
        return result


def window_metrics(records, block, channel):
    rows = [r for r in records if r['case']['block_index'] == block and
            r['case']['channel_index'] == channel and r['event']['completion'] not in UNKNOWN]
    if len(rows) != 10:
        raise BoundaryError('observed window denominator changed')
    return {'observed': len(rows), 'goal_successes': sum(r['goal_reached'] for r in rows),
            'goal_rate': sum(r['goal_reached'] for r in rows) / len(rows),
            'fallback_actions': sum(r['fallback'] for r in rows),
            'nonfallback_successes': sum(r['goal_reached'] and not r['fallback'] for r in rows),
            'fallback_successes': sum(r['goal_reached'] and r['fallback'] for r in rows),
            'raw_abstentions': sum(r['raw_abstention'] for r in rows),
            'stale_nonfallback_choices': sum(r['stale_nonfallback_choice'] for r in rows),
            'stale_nonfallback_fraction': sum(r['stale_nonfallback_choice'] for r in rows) / len(rows)}


def run_seed(seed, budget, result):
    """Evaluator owns hidden state. Policy methods receive only public views/receipts."""
    if seed not in (41, 42):
        raise ValueError('development seeds41/42 only; confirming not implemented')
    training = {'seed': seed, 'events': [], 'tokens': [], 'gen_creation': {}}
    result['training'].append(training)
    trained = traced_training(seed, training, budget)
    run = {'seed': seed, 'schedule_seed': seed + 1000, 'policies': [],
           'paired_initial_native_digest': hashlib.sha256(pickle.dumps(trained, protocol=5)).hexdigest()}
    result['runs'].append(run)
    schedule = schedule_layout(seed + 1000)
    limits = budget.limits
    for name in POLICIES:
        native = NativePolicy(trained, online=name != 'prefix_frozen', limits=limits) if name.startswith('prefix_') else None
        table = AdaptiveTable(training['events']) if name.startswith('table_') else None
        row = {'policy': name, 'records': [], 'windows': {}}
        run['policies'].append(row)
        if native and native.initial_full_digest != run['paired_initial_native_digest']:
            raise BoundaryError('paired native snapshot differs')
        for case in schedule:
            budget.charge('evaluation_opportunities')
            world = TwoChannelWorld(seed, f'online-dev-{seed}-{name}-{case["episode_index"]}')
            channel = world.channels[case['channel_index']]
            world._phase[channel] = case['initial_phase']
            old_correct = world.oracle_operation(channel)
            if case['block_index'] >= 1:
                world._answers = {(ch, phase): next(op for op in world.operations if op != answer)
                                  if ch == world.channels[0] else answer
                                  for (ch, phase), answer in world._answers.items()}
            view = {**world.view(channel), 'goal_observation_id': world._targets[channel]}
            view['available_operations'] = tuple(world.operations[i] for i in case['operation_order'])
            record = {'case': case, 'public_view': view, 'state': 'pending'}
            row['records'].append(record)
            begin = None
            if native:
                query, begin = native.query(view, budget)
            elif table:
                query = table.query(view)
            else:
                op = (view['available_operations'][0] if name == 'fixed_first' else
                      view['available_operations'][case['random_slot']] if name == 'random_uniform'
                      else world.oracle_operation(channel))
                query = {'operation_id': op, 'forecasts': [],
                         'privileged': name == 'oracle_upper_bound'}
            raw_abstention = query['operation_id'] is None
            operation = query['operation_id'] or view['available_operations'][case['fallback_slot']]
            seal = {'public_view': view, 'query': query, 'operation_id': operation,
                    'fallback': raw_abstention}
            record.update(pre_outcome=seal, pre_outcome_digest=digest(seal), begin=begin)
            budget.charge('evaluation_actions')
            event = world.act(channel, operation, forced_status=case['scheduled_status'])
            admitted = name not in ('prefix_frozen', 'table_frozen') and not (
                name in ('prefix_feedback_gate', 'table_feedback_gate') and not case['gated_outcome_admitted'])
            if native:
                feedback = native.feedback(event, admitted=admitted, budget=budget)
                evidence = prediction_receipts(query['forecasts'], operation, event)
            elif table:
                feedback = table.update(event, admitted=admitted)
                evidence = []
            else:
                feedback, evidence = None, []
            observed = event.completion not in UNKNOWN
            record.update(state='finished', event=asdict(event), feedback=feedback,
                          prediction_evidence=evidence, fallback=raw_abstention,
                          raw_abstention=raw_abstention,
                          goal_reached=(event.actual_observation == view['goal_observation_id']) if observed else None,
                          stale_nonfallback_choice=bool(observed and case['block_index'] >= 1 and
                              case['channel_index'] == 0 and not raw_abstention and operation == old_correct))
            budget.check()
        row['windows'] = {f'block{b}_channel{ch}': window_metrics(row['records'], b, ch)
                          for b in range(4) for ch in (0, 1)}
        if native:
            row['final_native_digest'] = native.full_digest()
            if not native.online and row['final_native_digest'] != native.initial_full_digest:
                raise BoundaryError('frozen final digest differs')
    return run


def summarize(runs):
    """Descriptive development metrics only; no confirming threshold verdict."""
    summary = []
    for run in runs:
        for row in run['policies']:
            records = row['records']
            changes = [d for r in records for d in (r['feedback'] or {}).get('gen_deltas', [])]
            summary.append({'seed': run['seed'], 'policy': row['policy'],
                'observed': sum(r['goal_reached'] is not None for r in records),
                'unknown': sum(r['goal_reached'] is None for r in records),
                'observed_negative_forecasts': sum(e['support'] == 'negative' for r in records for e in r['prediction_evidence']),
                'feedback_counter_delta_records': sum(d['before'] is not None and d['after'] is not None for d in changes),
                'feedback_Gen_births': sum(d['before'] is None for d in changes),
                'late_changed': row['windows']['block3_channel0'],
                'late_stable': row['windows']['block3_channel1'],
                'withdrawal_changed': row['windows']['block1_channel0']})
    return summary


def run_development(*, seeds=(41, 42), clock=time.perf_counter):
    # Preflight before any world construction/training; no reserved task can run.
    if tuple(seeds) != (41, 42):
        raise ValueError('only complete development pool41/42 allowed')
    config = protocol()
    budget = Budget(config['budgets'], clock)
    result = {'schema': 'firstagi.ac0-online-development/v0.1', 'status': 'running',
              'scope': 'development_scaffold_partial_protocol_implementation_not_confirming',
              'protocol_sha256': PROTOCOL_SHA, 'training': [], 'runs': [],
              'AC0_gate_pass': False, 'confirming_executed': False,
              'remaining_audit': ['independent recorded-data audit and causal update-to-later-reuse join',
                                  'confirming criteria aggregator and clean implementation manifest']}
    try:
        for seed in seeds:
            run_seed(seed, budget, result)
        result['summary'] = summarize(result['runs'])
        budget.check()
        result['status'] = 'development_execution_complete_pending_write'
    except Exception as error:
        result.update(status='incomplete', error=type(error).__name__ + ': ' + str(error))
    result['budget_counts'] = dict(budget.counts)
    return result, budget


def write_development(path, result, budget):
    ensure_fresh_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(result, indent=2) + '\n').encode('utf-8')
    oversized = len(raw) > budget.limits['max_raw_output_bytes']
    # Preserve failures as well; never overwrite an earlier experiment.
    with path.open('xb') as f:
        f.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    path.with_suffix(path.suffix + '.sha256').write_text(sha + '  ' + path.name + '\n', encoding='utf-8')
    receipt = {'raw_sha256': sha, 'raw_bytes': len(raw),
               'status': 'incomplete' if result['status'] == 'incomplete' or oversized else 'development_complete',
               'elapsed_including_raw_write': budget.clock() - budget.started}
    try:
        budget.check()
    except BoundaryError as error:
        receipt.update(status='incomplete', error=str(error))
    if oversized:
        receipt['error'] = 'raw output budget exceeded'
    path.with_suffix(path.suffix + '.completion.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ensure_fresh_output(args.out)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    result, budget = run_development()
    result.update(source_commit=commit, source_dirty=dirty, python=sys.version, platform=platform.platform())
    receipt = write_development(args.out, result, budget)
    print(json.dumps({'completion': receipt, 'error': result.get('error'),
                      'counts': result['budget_counts'], 'summary': result.get('summary')}, indent=2))


if __name__ == '__main__':
    main()

