"""Known-task on-policy development of an explicit actual-context sidecar.

No confirming mode; no native-policy, heterarchy-advantage or AC0-gate claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
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
from experiments.diagnostics.ac0_applicability_shadow import ActualHistory, shadow_queries, require, digest
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld, UNKNOWN
from experiments.diagnostics.ac0_frozen_goal import BoundaryError, select_goal
from experiments.diagnostics.ac0_goal_evaluator import traced_training, prediction_receipts, ensure_fresh_output
from experiments.diagnostics.ac0_online_feedback import NativePolicy, window_metrics
from experiments.diagnostics.ac0_online_protocol import schedule_layout, PUBLIC_FIELDS

PROTOCOL = ROOT / 'experiments/protocols/ac0_applicability_on_policy_dev_v1.json'
PROTOCOL_SHA = '047058453db47b6229365b1929ab53066bed1a8c64544d96ed867fee58aaf29c'
POLICIES = ('prefix_online', 'prefix_actual_context_online',
            'prefix_actual_context_feedback_gate', 'table_online',
            'table_feedback_gate', 'random_uniform')


def protocol():
    raw = PROTOCOL.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == PROTOCOL_SHA, 'declared design bytes changed')
    result = json.loads(raw)
    require(result['task_seeds'] == [41, 42] and tuple(result['policies']) == POLICIES, 'development design')
    return result


class Budget:
    """Precharge tokens/actions before the corresponding operation."""
    def __init__(self, limits, clock=time.perf_counter):
        self.design_limits = limits
        self.clock, self.started = clock, clock()
        self.counts = dict.fromkeys(('train_actions', 'train_core_tokens',
                                    'evaluation_actions', 'all_core_tokens'), 0)
        # Existing NativePolicy expects these names; the declared values are unchanged.
        self.limits = {'max_gen_records_visited_per_query': limits['max_gen_visits_per_query'],
                       'max_feature_origin_lookups_per_query': limits['max_feature_lookups_per_query'],
                       'max_serialized_model_bytes_per_instance': limits['max_serialized_model_bytes_per_instance']}

    def check(self):
        if self.clock() - self.started > self.design_limits['max_wall_seconds_complete_run']:
            raise BoundaryError('complete wall budget exceeded')

    def charge(self, name, count=1):
        self.check()
        proposed = dict(self.counts)
        proposed[name] += count
        if name == 'train_core_tokens':
            proposed['all_core_tokens'] += count
        for key, value in proposed.items():
            if value > self.design_limits['max_' + key]:
                raise BoundaryError(key + ' budget exceeded')
        if proposed['train_actions'] + proposed['evaluation_actions'] > self.design_limits['max_all_world_actions']:
            raise BoundaryError('all world actions budget exceeded')
        self.counts = proposed


class Controller:
    """Receives public views and own past actual receipts, never evaluator cases."""
    def __init__(self, name, trained, training, budget):
        require(name in POLICIES, 'unknown policy')
        self.name, self.budget = name, budget
        self.native = NativePolicy(trained, online=True, limits=budget.limits) if name.startswith('prefix_') else None
        self.history = ActualHistory() if name != 'random_uniform' else None
        if self.history is not None:
            for event in training['events']:
                self.history.ingest(event, admitted=True)
        self.receipts = set()  # Includes unknown/withheld, explicitly accounted below.

    def storage(self):
        parts = {'observer_bytes': len(pickle.dumps(self.native.observer, protocol=5)) if self.native else 0,
                 'native_receipt_ids_bytes': len(pickle.dumps(self.native.receipts, protocol=5)) if self.native else 0,
                 'actual_history_bytes_including_ids': len(pickle.dumps(self.history, protocol=5)),
                 'delivery_receipt_ids_bytes': len(pickle.dumps(self.receipts, protocol=5))}
        parts['serialized_all_stores_bytes'] = sum(parts.values())
        parts['actual_context_keys'] = len(self.history.values) if self.history is not None else 0
        parts['delivery_receipt_ids'] = len(self.receipts)
        parts['history_receipt_ids'] = len(self.history.seen) if self.history is not None else 0
        parts['native_receipt_ids'] = len(self.native.receipts) if self.native else 0
        parts['observer_receipt_ids'] = len(self.native.observer.seen) if self.native else 0
        require(parts['actual_context_keys'] <= self.budget.design_limits['max_actual_context_keys'], 'context key budget')
        require(parts['serialized_all_stores_bytes'] <= self.budget.design_limits['max_serialized_model_bytes_per_instance'], 'all-store model budget')
        return parts

    def query(self, view):
        require(set(view) == PUBLIC_FIELDS, 'only four public fields allowed')
        before = self.history.fingerprint() if self.history is not None else None
        begin, coverage = None, None
        if self.native:
            raw, begin = self.native.query(view, self.budget)
            variants, coverage = shadow_queries(view, raw['forecasts'], [], self.history)
            selected = variants[2] if self.name.startswith('prefix_actual_context_') else variants[0]
        elif self.history is not None:
            forecasts = [{'operation_id': op, 'predicted_observation': self.history.values[key]}
                         for op in view['available_operations']
                         if (key := (view['channel_id'], view['observation_id'], op)) in self.history.values]
            raw = {'operation_id': select_goal(forecasts, view['available_operations'], view['goal_observation_id']),
                   'forecasts': forecasts}
            selected = deepcopy(raw)
        else:
            raw = selected = {'operation_id': None, 'forecasts': []}
        require(before == (self.history.fingerprint() if self.history is not None else None), 'query changed history')
        return {'raw_query': raw, 'selected_query': selected, 'history_before_digest': before,
                'begin': begin, 'coverage': coverage}

    def feedback(self, event, *, admitted):
        require(type(admitted) is bool, 'boolean admission required')
        key = (event.run_id, event.event_id)
        require(key not in self.receipts, 'duplicate controller receipt')
        # Validate in a temporary history BEFORE any native mutation/bookkeeping.
        trial = deepcopy(self.history) if self.history is not None else ActualHistory()
        trial.ingest(asdict(event), admitted=admitted)
        native = self.native.feedback(event, admitted=admitted, budget=self.budget) if self.native else None
        before = self.history.fingerprint() if self.history is not None else None
        if self.history is not None:
            self.history = trial
        self.receipts.add(key)
        after = self.history.fingerprint() if self.history is not None else None
        if not admitted or event.completion in UNKNOWN:
            require(before == after, 'unknown/withheld changed history')
        return {'admitted': admitted, 'native': native,
                'history_before_digest': before, 'history_after_digest': after,
                'history_changed': before != after}


def register_changes(updates, deltas, *, episode, stage, witnesses):
    """Creation/positive support updates only; stop increments are not learning success."""
    for d in deltas:
        before, after = d['before'], d['after']
        if after is None or (before is not None and after['success_count'] <= before['success_count']):
            continue
        chain = after['feature_chain']
        require(all(fid in witnesses for fid in chain), 'Gen creation/update lacks actual-token witness')
        updates.append({'gen_id': d['gen_id'], 'episode_index': episode, 'stage': stage,
                        'kind': 'creation' if before is None else 'positive_support_update',
                        'state_delta': d, 'feature_witnesses': [deepcopy(witnesses[fid]) for fid in chain]})


def causal_links(records, updates):
    """Join only own earlier updates to actually executed correct nonfallback reuse."""
    links = []
    for row in records:
        if not row['goal_reached'] or row['fallback']:
            continue
        seal, event = row['pre_outcome'], row['event']
        index = row['case']['episode_index']
        for f in seal['selected_query']['forecasts']:
            if f['operation_id'] != event['chosen_operation'] or f['predicted_observation'] != event['actual_observation']:
                continue
            candidates = [u for u in updates if u['gen_id'] == f['gen_id'] and u['episode_index'] < index
                          and u['state_delta']['after']['feature_chain'] == f['gen_chain']]
            if not candidates:
                continue
            update = candidates[-1]
            outcome_witness = next((w for w in update['feature_witnesses']
                                    if w['canonical_feature_id'] == f['outcome_feature_id']), None)
            changed = bool(row['case']['channel_index'] == 0 and row['case']['block_index'] >= 1 and
                           outcome_witness and outcome_witness['episode_index'] >= 0 and
                           records[outcome_witness['episode_index']]['case']['block_index'] >= 1 and
                           outcome_witness['channel_id'] == event['channel_id'] and
                           outcome_witness['source'] == event['chosen_operation'] and
                           outcome_witness['target'] == event['actual_observation'])
            links.append({'gen_id': f['gen_id'], 'update_episode_index': update['episode_index'],
                          'update_stage': update['stage'], 'reuse_episode_index': index,
                          'changed_channel_actual_witness': changed,
                          'outcome_feature_witness': outcome_witness})
    return links


def run_seed(seed, result, budget, config):
    training = {'seed': seed, 'events': [], 'tokens': [], 'gen_creation': {}}
    result['training'].append(training)
    trained = traced_training(seed, training, budget)
    initial = hashlib.sha256(pickle.dumps(trained, protocol=5)).hexdigest()
    run = {'seed': seed, 'paired_initial_native_digest': initial, 'policies': []}
    result['runs'].append(run)
    for name in POLICIES:
        controller = Controller(name, trained, training, budget)
        row = {'policy': name, 'records': [], 'updates': [], 'initial_storage': controller.storage()}
        run['policies'].append(row)
        if controller.native:
            require(controller.native.initial_full_digest == initial, 'paired training copy changed')
        witnesses = {t['canonical_feature_id']: {**t, 'episode_index': -1} for t in training['tokens']}
        for case in schedule_layout(seed + 1000):
            budget.check()
            index = case['episode_index']
            world = TwoChannelWorld(seed, f'actual-context-dev-{seed}-{name}-{index}')
            channel = world.channels[case['channel_index']]
            world._phase[channel] = case['initial_phase']
            old_correct = world.oracle_operation(channel)
            if case['block_index'] >= 1:
                world._answers = {(ch, phase): next(op for op in world.operations if op != answer)
                                  if ch == world.channels[0] else answer
                                  for (ch, phase), answer in world._answers.items()}
            view = {**world.view(channel), 'goal_observation_id': world._targets[channel]}
            view['available_operations'] = tuple(world.operations[i] for i in case['operation_order'])
            record = {'case': case, 'state': 'pending'}
            row['records'].append(record)
            query = controller.query(view)
            if query['begin']:
                cue = query['begin']['cue_token']
                witnesses[cue['canonical_feature_id']] = {**cue, 'episode_index': index,
                    'channel_id': channel, 'source': view['observation_id'], 'target': view['observation_id']}
                register_changes(row['updates'], query['begin']['begin_gen_deltas'], episode=index,
                                 stage='begin', witnesses=witnesses)
            raw_abstention = query['selected_query']['operation_id'] is None and name != 'random_uniform'
            fallback = raw_abstention and name != 'random_uniform'
            operation = (view['available_operations'][case['random_slot']] if name == 'random_uniform' else
                         query['selected_query']['operation_id'] or view['available_operations'][case['fallback_slot']])
            seal = {**query, 'public_view': view, 'operation_id': operation, 'fallback': fallback}
            record.update(pre_outcome=seal, pre_outcome_digest=digest(seal))
            budget.charge('evaluation_actions')
            event = world.act(channel, operation, forced_status=case['scheduled_status'])
            admitted = not (name in config['schedule']['gated_policies'] and not case['gated_outcome_admitted'])
            feedback = controller.feedback(event, admitted=admitted)
            if controller.native:
                for t in feedback['native']['tokens']:
                    source, target = ((event.observation_id, operation) if t['role'] == 'cue_to_operation' else
                                      (operation, event.actual_observation))
                    witnesses[t['canonical_feature_id']] = {**t, 'episode_index': index,
                        'channel_id': channel, 'source': source, 'target': target}
                register_changes(row['updates'], feedback['native']['gen_deltas'], episode=index,
                                 stage='feedback', witnesses=witnesses)
            observed = event.completion not in UNKNOWN
            record.update(state='finished', event=asdict(event), feedback=feedback,
                          fallback=fallback, raw_abstention=raw_abstention,
                          goal_reached=(event.actual_observation == view['goal_observation_id']) if observed else None,
                          prediction_evidence=prediction_receipts(query['selected_query']['forecasts'], operation, event)
                            if controller.native else [],
                          stale_nonfallback_choice=bool(observed and case['block_index'] >= 1 and
                              case['channel_index'] == 0 and not raw_abstention and operation == old_correct),
                          storage=controller.storage())
        row['windows'] = {f'block{b}_channel{ch}': window_metrics(row['records'], b, ch)
                          for b in range(4) for ch in (0, 1)}
        row['causal_links'] = causal_links(row['records'], row['updates']) if controller.native else []


def summarize(result):
    summaries, checks = [], {}
    for run in result['runs']:
        for row in run['policies']:
            name, records = row['policy'], row['records']
            changed = sum(x['changed_channel_actual_witness'] for x in row['causal_links'])
            summaries.append({'seed': run['seed'], 'policy': name,
                'late_changed': row['windows']['block3_channel0'],
                'late_stable': row['windows']['block3_channel1'],
                'withdrawal_changed': row['windows']['block1_channel0'],
                'changed_channel_causal_links': changed,
                'observed': sum(r['goal_reached'] is not None for r in records),
                'unknown': sum(r['goal_reached'] is None for r in records),
                'max_all_stores_bytes': max(r['storage']['serialized_all_stores_bytes'] for r in records),
                'forecast_support': dict(Counter(e['support'] for r in records for e in r['prediction_evidence']))})
            if name in ('prefix_actual_context_online', 'prefix_actual_context_feedback_gate', 'table_online', 'table_feedback_gate'):
                for ch in (0, 1):
                    checks[f'{run["seed"]}_{name}_late_channel{ch}'] = row['windows'][f'block3_channel{ch}']['goal_rate'] >= .8
            if name == 'prefix_actual_context_feedback_gate':
                checks[f'{run["seed"]}_{name}_restored_changed'] = row['windows']['block3_channel0']['goal_rate'] >= .8
    checks['changed_channel_named_update_reuse'] = any(s['changed_channel_causal_links'] for s in summaries
        if s['policy'].startswith('prefix_actual_context_'))
    return summaries, checks


def run_development(*, seeds=(41, 42), clock=time.perf_counter):
    require(tuple(seeds) == (41, 42), 'only complete development pool41/42 allowed')
    config = protocol()
    budget = Budget(config['budgets'], clock)
    result = {'schema': 'firstagi.ac0-applicability-on-policy-development/v1', 'status': 'running',
              'protocol_sha256': PROTOCOL_SHA, 'training': [], 'runs': [],
              'AC0_gate_pass': False, 'confirming_executed': False, 'independent_execution': False,
              'scope': config['scope']}
    try:
        for seed in seeds:
            run_seed(seed, result, budget, config)
        require(budget.counts == {'train_actions': 192, 'train_core_tokens': 480,
                                 'evaluation_actions': 1536, 'all_core_tokens': 2168}, 'complete nominal counts')
        result['summary'], result['development_checks'] = summarize(result)
        budget.check()
        result['status'] = 'development_execution_complete_pending_write'
    except Exception as error:
        result.update(status='incomplete', error=type(error).__name__ + ': ' + str(error))
    result['budget_counts'] = dict(budget.counts)
    return result, budget


def write_output(path, result, budget):
    ensure_fresh_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(result, indent=2) + '\n').encode()
    with path.open('xb') as handle:
        handle.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with path.with_suffix(path.suffix + '.sha256').open('x', encoding='utf-8') as handle:
        handle.write(sha + '  ' + path.name + '\n')
    receipt = {'raw_sha256': sha, 'raw_bytes': len(raw), 'elapsed_including_write': budget.clock() - budget.started,
               'status': 'incomplete' if result['status'] == 'incomplete' else 'development_complete'}
    try:
        require(len(raw) <= budget.design_limits['max_raw_bytes'], 'raw bytes budget exceeded')
        budget.check()
    except Exception as error:
        receipt.update(status='incomplete', error=str(error))
    with path.with_suffix(path.suffix + '.completion.json').open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ensure_fresh_output(args.out)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip(), 'clean source required')
    result, budget = run_development()
    result.update(source_commit=commit, source_dirty=False, python=sys.version, platform=platform.platform())
    receipt = write_output(args.out, result, budget)
    print(json.dumps({'completion': receipt, 'error': result.get('error'), 'counts': result['budget_counts'],
                      'checks': result.get('development_checks'), 'summary': result.get('summary')}, indent=2))


if __name__ == '__main__':
    main()
