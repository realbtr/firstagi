"""Replay saved41/42 receipts to locate context loss. No world/action generation.

Same implementation replay is not independent replication or a new skill run.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.diagnostics.ac0_event_baseline import TransitionEvent, UNKNOWN
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver
from experiments.diagnostics.ac0_frozen_goal import FrozenGoalPredictor, BoundaryError
from experiments.diagnostics.ac0_online_feedback import deliver_feedback
from experiments.diagnostics.ac0_goal_evaluator import ensure_fresh_output

INPUT_SHA = '04039391fb7a1bd46598e90b7665d11b529dcb9bce9217c080f088b81ebe4829'
DEFAULT = ROOT / 'experiments/reports/ac0_debug/online_feedback/v1/development_41_42_20261030T2334.json'


def frontier_census(observer, view):
    """All compatible stored forecast chains in LIVE context, at their real cursor.

    No activation, cursor advance, counter update, selection or prediction creation.
    Completed active entries have no expected feature and remain distinguishable.
    """
    ch, cue = view['channel_id'], view['observation_id']
    anchor = observer.codec.encode_role(ch, cue, cue, 'cue_anchor').feature_id
    rows = []
    for gid, active in observer.system.engine.context._active.items():
        gen = observer.system.base.get(gid)
        chain = gen.feature_chain
        if len(chain) < 3 or chain[0] != anchor:
            continue
        operations = observer.provenance.get(chain[1], set())
        outcomes = observer.provenance.get(chain[2], set())
        if len(operations) != 1 or len(outcomes) != 1:
            continue
        role, channel, source, op = next(iter(operations))
        role2, channel2, source2, actual = next(iter(outcomes))
        if (role != 'cue_to_operation' or channel != ch or source != cue or
                op not in view['available_operations'] or role2 != 'operation_to_observation'
                or channel2 != ch or source2 != op):
            continue
        fid = active.current_feature_id(gen)
        rows.append({'gen_id': gid, 'gen_chain': list(chain), 'operation_id': op,
                     'predicted_observation': actual, 'cursor': active.current_feature_index,
                     'expected_feature_id': fid, 'completed': active.is_complete(gen),
                     'success_count': gen.success_count, 'stop_count': gen.stop_count})
    return rows


def forecast_signatures(rows):
    return Counter(json.dumps([r['gen_chain'], r['operation_id'], r['predicted_observation']])
                   for r in rows)


class ReplayObserver(CodedKernelObserver):
    def __init__(self, clock=time.perf_counter):
        super().__init__()
        self.capture = False
        self.steps = []
        self.clock = clock
        self.started = clock()

    def _ingest(self, channel, source, target, role):
        if self.clock() - self.started > 45 or self.system.engine.step_count >= 600:
            raise BoundaryError('bounded replay budget exceeded')
        before = frontier_census(self, self.view) if self.capture else None
        step = super()._ingest(channel, source, target, role)
        if self.capture:
            self.steps.append({**step, 'frontier_before': before,
                               'frontier_after': frontier_census(self, self.view)})
        return step


def replay(data):
    if [r['seed'] for r in data['runs']] != [41, 42]:
        raise ValueError('only saved development41/42 receipts accepted')
    result = {'schema': 'firstagi.ac0-context-receipt-replay/v0.1',
              'status': 'running', 'input_raw_sha256': INPUT_SHA,
              'new_world_constructions': 0, 'new_world_actions': 0,
              'new_task_outcomes': 0, 'confirming_executed': False,
              'independent_execution': False, 'AC0_gate_pass': False,
              'runs': [], 'counts': {}, 'witnesses': {}}
    counts, witnesses = Counter(), {}
    try:
        for seed in (41, 42):
            training = next(x for x in data['training'] if x['seed'] == seed)
            saved = next(x for x in data['runs'] if x['seed'] == seed)
            row = next(x for x in saved['policies'] if x['policy'] == 'prefix_online')
            if len(training['events']) != 96 or len(row['records']) != 128:
                raise ValueError('saved trajectory length changed')
            observer = ReplayObserver()
            for event_row in training['events']:
                event = TransitionEvent(**event_row)
                observer.begin({k: event_row[k] for k in
                    ('channel_id', 'observation_id', 'available_operations')})
                observer.complete(event)
            observer.system.reset_context()
            observer.capture = True
            run = {'seed': seed, 'policy': 'prefix_online_saved_action_replay', 'records': []}
            result['runs'].append(run)
            removed_retained = {}
            for old in row['records']:
                view, event = old['public_view'], TransitionEvent(**old['event'])
                episode = old['case']['episode_index']
                observer.steps = []
                observer.begin(view, recall_policy='exact_learned_prefix')
                live = frontier_census(observer, view)
                query = FrozenGoalPredictor(observer).query(view)
                if forecast_signatures(query['forecasts']) != forecast_signatures(old['pre_outcome']['query']['forecasts']):
                    raise BoundaryError('replayed forecast semantics differ from saved trajectory')
                if query['operation_id'] != old['pre_outcome']['query']['operation_id']:
                    raise BoundaryError('replayed choice differs from saved trajectory')
                counts['matched_saved_queries'] += 1
                live_op_ids = {r['gen_id'] for r in live if r['cursor'] == 1 and not r['completed']}
                forecast_ids = {r['gen_id'] for r in query['forecasts']}
                if forecast_ids - live_op_ids:
                    counts['queries_with_frozen_forecasts_outside_live_operation_frontier'] += 1
                # Once observed after a removal, record only the first later reappearance.
                for gid in forecast_ids & removed_retained.keys():
                    origin = removed_retained.pop(gid)
                    counts['removed_retained_later_readout_reappearances'] += 1
                    witnesses.setdefault('reappearance', {'seed': seed, 'gen_id': gid,
                        'removed_episode': origin, 'reappeared_episode': episode,
                        'in_live_operation_frontier': gid in live_op_ids,
                        'still_stored': observer.system.base.get(gid) is not None})
                before = {r['gen_id']: r for r in live}
                feedback = deliver_feedback(observer, event, admitted=True)
                after = {r['gen_id']: r for r in frontier_census(observer, view)}
                negatives = []
                if event.completion not in UNKNOWN:
                    for forecast in query['forecasts']:
                        if forecast['operation_id'] != event.chosen_operation or forecast['predicted_observation'] == event.actual_observation:
                            continue
                        gid = forecast['gen_id']
                        gen = observer.system.base.get(gid)
                        item = {'gen_id': gid, 'in_live_before': gid in before,
                                'active_after_feedback': gid in after,
                                'still_stored': gen is not None,
                                'stop_before': before.get(gid, {}).get('stop_count'),
                                'stop_after': gen.stop_count if gen else None,
                                'predicted': forecast['predicted_observation'],
                                'actual': event.actual_observation}
                        negatives.append(item)
                        counts['executed_negative_forecasts'] += 1
                        if gid in before and gid not in after and gen is not None:
                            counts['negative_removed_from_live_retained_in_base'] += 1
                            removed_retained[gid] = episode
                            witnesses.setdefault('removed', {'seed': seed, 'episode': episode, **item})
                        if gid in after:
                            counts['negative_still_live_after_feedback'] += 1
                            if after[gid]['cursor'] == 2 and not after[gid]['completed']:
                                counts['negative_still_waiting_for_old_outcome'] += 1
                            if item['stop_before'] == item['stop_after']:
                                counts['negative_still_live_stop_unchanged'] += 1
                            witnesses.setdefault('mixed_match_survivor', {'seed': seed,
                                'episode': episode, **item, 'after_frontier': after[gid],
                                'native_outcomes': [s['outcome'] for s in observer.steps]})
                run['records'].append({'episode_index': episode, 'case': old['case'],
                    'public_view': view, 'saved_event': asdict(event),
                    'saved_action_replayed_not_selected': True,
                    'semantic_query_matches_saved': True,
                    'live_after_cue': live, 'readout_query': query,
                    'steps': observer.steps, 'feedback': feedback,
                    'negative_forecast_classification': negatives})
            run['total_core_tokens'] = observer.system.engine.step_count
            counts['replayed_core_tokens'] += observer.system.engine.step_count
        result['status'] = 'receipt_replay_complete_not_new_skill_run'
    except Exception as error:
        result.update(status='incomplete', error=type(error).__name__ + ': ' + str(error))
    result['counts'] = dict(counts)
    result['witnesses'] = witnesses
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ensure_fresh_output(args.out)
    raw = args.input.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUT_SHA:
        parser.error('saved input SHA mismatch')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    started = time.perf_counter()
    result = replay(json.loads(raw))
    result.update(source_commit=commit, source_dirty=dirty,
        python=sys.version, platform=platform.platform())
    encoded = (json.dumps(result, indent=2) + '\n').encode()
    if len(encoded) > 32 * 1024 * 1024:
        raise BoundaryError('replay raw budget exceeded')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('xb') as f:
        f.write(encoded)
    sha = hashlib.sha256(encoded).hexdigest()
    with args.out.with_suffix(args.out.suffix + '.sha256').open('x') as f:
        f.write(sha + '  ' + args.out.name + '\n')
    elapsed = time.perf_counter() - started
    receipt = {'status': 'incomplete' if elapsed > 60 or result['status'] == 'incomplete' else 'receipt_replay_complete',
               'raw_sha256': sha, 'raw_bytes': len(encoded), 'elapsed_including_raw_write': elapsed}
    with args.out.with_suffix(args.out.suffix + '.completion.json').open('x') as f:
        json.dump(receipt, f, indent=2)
        f.write('\n')
    print(json.dumps({'completion': receipt, 'counts': result['counts'],
                      'witnesses': result['witnesses'], 'error': result.get('error')}, indent=2))


if __name__ == '__main__':
    main()

