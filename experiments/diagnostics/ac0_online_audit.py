"""Read-only stdlib audit of recorded online development receipts.

Does not import a model/world or rerun tasks. Consistency audit, not independent
execution or a recomputation of the complete native snapshot from the hashes.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

UNKNOWN = {'interrupted', 'unavailable', 'cancelled'}
NATIVE = {'prefix_online', 'prefix_feedback_gate', 'prefix_frozen'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def select(forecasts, operations, goal):
    outcomes = {op: set() for op in operations}
    for f in forecasts:
        outcomes[f['operation_id']].add(f['predicted_observation'])
    eligible = [op for op in operations if outcomes[op] == {goal}]
    return eligible[0] if len(eligible) == 1 else None


def audit(data):
    require(data['status'] == 'development_execution_complete_pending_write', 'incomplete data')
    require(not data['confirming_executed'] and not data['AC0_gate_pass'], 'scope')
    require([r['seed'] for r in data['runs']] == [41, 42], 'development pool')
    training = {r['seed']: r for r in data['training']}
    counts = Counter()
    witnesses = []
    conflict_witnesses = []
    table_windows = []
    for run in data['runs']:
        train = training[run['seed']]
        require(len(train['events']) == 96 and len(train['tokens']) == 240, 'training budget')
        initial_table = {(e['channel_id'], e['observation_id'], e['chosen_operation']): e['actual_observation']
                         for e in train['events'] if e['completion'] not in UNKNOWN}
        channels = list(dict.fromkeys(e['channel_id'] for e in train['events']))
        require(len(channels) == 2, 'channels')
        # Derive stable actual transitions from receipts, not a task oracle.
        outcomes = defaultdict(set)
        for (ch, cue, op), actual in initial_table.items():
            outcomes[ch].add(actual)
        require(all(len(x) == 2 for x in outcomes.values()), 'training actual-outcome coverage')
        policy_names = [r['policy'] for r in run['policies']]
        require(len(set(policy_names)) == 9, 'nine distinct policies')
        paired_schedule = None
        for row in run['policies']:
            name = row['policy']
            require(len(row['records']) == 128, 'episode count')
            schedule = [r['case'] for r in row['records']]
            if paired_schedule is None:
                paired_schedule = schedule
            require(schedule == paired_schedule, 'unpaired schedule')
            observed_windows = Counter()
            seen_events = set()
            table = dict(initial_table)
            changed_gens = {}
            known_chains = {gid: g['feature_chain'] for gid, g in train['gen_creation'].items()}
            feature_witnesses = {t['canonical_feature_id'] for t in train['tokens']}
            late_conflicts = 0
            for index, r in enumerate(row['records']):
                require(r['state'] == 'finished' and r['case']['episode_index'] == index, 'record sequence')
                case, view, seal, e = r['case'], r['public_view'], r['pre_outcome'], r['event']
                require(set(view) == {'channel_id', 'observation_id', 'available_operations', 'goal_observation_id'}, 'view leak')
                require(digest(seal) == r['pre_outcome_digest'] and seal['public_view'] == view, 'pre-outcome seal')
                key = (e['run_id'], e['event_id'])
                require(key not in seen_events, 'duplicate recorded event')
                seen_events.add(key)
                require(e['channel_id'] == view['channel_id'] and e['observation_id'] == view['observation_id'], 'event/view mismatch')
                require(e['chosen_operation'] == seal['operation_id'] and e['chosen_operation'] in view['available_operations'], 'executed operation')
                require(e['completion'] == case['scheduled_status'] if case['scheduled_status'] else e['completion'] not in UNKNOWN, 'scheduled completion')
                observed = e['completion'] not in UNKNOWN
                require(observed == (e['actual_observation'] is not None), 'actual/unknown')
                require(r['goal_reached'] == (e['actual_observation'] == view['goal_observation_id']) if observed else r['goal_reached'] is None, 'goal score')
                if observed:
                    observed_windows[(case['block_index'], case['channel_index'])] += 1
                    expected = initial_table[(e['channel_id'], e['observation_id'], e['chosen_operation'])]
                    if case['block_index'] >= 1 and case['channel_index'] == 0:
                        expected = next(x for x in outcomes[e['channel_id']] if x != expected)
                    require(e['actual_observation'] == expected, 'actual outcome disagrees with training-derived rule/change')
                counts['evaluation_records'] += 1
                counts['observed' if observed else 'unknown'] += 1
                q = seal['query']
                if name.startswith(('prefix_', 'table_')):
                    choice = select(q['forecasts'], view['available_operations'], view['goal_observation_id'])
                    require(q['operation_id'] == choice, 'unanimous readout changed')
                    require(r['fallback'] == (choice is None) == r['raw_abstention'], 'fallback label')
                    executed = choice or view['available_operations'][case['fallback_slot']]
                    require(executed == e['chosen_operation'], 'paired fallback')
                expected_admission = name not in ('prefix_frozen', 'table_frozen') and not (
                    name in ('prefix_feedback_gate', 'table_feedback_gate') and not case['gated_outcome_admitted'])
                f = r['feedback']
                if f is not None:
                    require(f['admitted'] == expected_admission, 'admission mismatch')
                if name.startswith('table_'):
                    wanted = [{'operation_id': op, 'predicted_observation': table[k]}
                              for op in view['available_operations']
                              if (k := (view['channel_id'], view['observation_id'], op)) in table]
                    require(q['forecasts'] == wanted, 'table used unavailable/unexecuted information')
                    before = dict(table)
                    if expected_admission and observed:
                        table[(e['channel_id'], e['observation_id'], e['chosen_operation'])] = e['actual_observation']
                    require(f['table_unchanged'] == (before == table), 'table update receipt')
                if name not in NATIVE:
                    continue
                begin = r['begin']
                if begin['cue_token']:
                    feature_witnesses.add(begin['cue_token']['canonical_feature_id'])
                for d in begin['begin_gen_deltas']:
                    if d['after'] is not None:
                        known_chains[d['gen_id']] = d['after']['feature_chain']
                for forecast, evidence in zip(q['forecasts'], r['prediction_evidence']):
                    require(known_chains.get(forecast['gen_id']) == forecast['gen_chain'], 'forecast lacks recorded native chain')
                    require(all(x in feature_witnesses for x in forecast['gen_chain']), 'forecast lacks actual feature witness')
                    expected_support = ('unknown' if not observed or forecast['operation_id'] != e['chosen_operation'] else
                                        'positive' if forecast['predicted_observation'] == e['actual_observation'] else 'negative')
                    require(evidence['gen_id'] == forecast['gen_id'] and evidence['support'] == expected_support, 'forecast evidence')
                    if evidence['support'] == 'negative':
                        counts['negative_forecast_receipts'] += 1
                    if (forecast['gen_id'] in changed_gens and observed and not r['fallback'] and r['goal_reached']
                            and forecast['operation_id'] == e['chosen_operation']):
                        counts['update_then_correct_reuse'] += 1
                        if case['channel_index'] == 0 and case['block_index'] >= 1:
                            counts['changed_channel_update_then_correct_reuse'] += 1
                require(len(q['forecasts']) == len(r['prediction_evidence']), 'evidence cardinality')
                assimilated = name != 'prefix_frozen' and expected_admission and observed
                require(f['assimilated'] == assimilated, 'native assimilation mismatch')
                require(len(f['tokens']) == (2 if assimilated else 0), 'native token budget/guard')
                if not assimilated:
                    require(f['native_unchanged'] and f['native_before'] == f['native_after'] and not f['gen_deltas'], 'unknown/withheld/frozen mutation receipt')
                    counts['native_no_ingest_guard_records'] += 1
                for token in f['tokens']:
                    feature_witnesses.add(token['canonical_feature_id'])
                for d in f['gen_deltas']:
                    require(d['after'] is not None and all(x in feature_witnesses for x in d['after']['feature_chain']), 'delta lacks feature witness')
                    known_chains[d['gen_id']] = d['after']['feature_chain']
                    changed_gens[d['gen_id']] = index
                    neg = next((x for x in r['prediction_evidence'] if x['gen_id'] == d['gen_id'] and x['support'] == 'negative'), None)
                    if neg and d['before'] and d['after']['stop_count'] > d['before']['stop_count']:
                        counts['named_negative_native_stop_delta'] += 1
                        if len(witnesses) < 2:
                            witnesses.append({'seed': run['seed'], 'policy': name, 'episode_index': index,
                                'channel_index': case['channel_index'], 'event_id': e['event_id'],
                                'gen_id': d['gen_id'], 'predicted': next(x['predicted_observation'] for x in q['forecasts'] if x['gen_id'] == d['gen_id']),
                                'actual': e['actual_observation'], 'before': d['before'], 'after': d['after'],
                                'token_steps': [t['core_step'] for t in f['tokens']]})
                if case['block_index'] == 3 and case['channel_index'] == 0 and observed:
                    groups = defaultdict(set)
                    for forecast in q['forecasts']:
                        groups[forecast['operation_id']].add(forecast['predicted_observation'])
                    conflicts = {op: sorted(values) for op, values in groups.items() if len(values) > 1}
                    if conflicts:
                        late_conflicts += 1
                        if len(conflict_witnesses) < 2:
                            conflict_witnesses.append({'seed': run['seed'], 'policy': name,
                                'episode_index': index, 'conflicting_outcomes': conflicts,
                                'raw_choice': q['operation_id'], 'fallback': r['fallback']})
            require(observed_windows == Counter({(b, c): 10 for b in range(4) for c in range(2)}), 'window denominator')
            # Recompute window endpoints from actual records, not summary fields.
            for b in range(4):
                for ch in range(2):
                    items = [r for r in row['records'] if r['case']['block_index'] == b
                             and r['case']['channel_index'] == ch and r['event']['completion'] not in UNKNOWN]
                    successes = sum(r['event']['actual_observation'] == r['public_view']['goal_observation_id'] for r in items)
                    old_stale = 0
                    for r in items:
                        e = r['event']
                        old_outcome = initial_table[(e['channel_id'], e['observation_id'], e['chosen_operation'])]
                        stale = bool(b >= 1 and ch == 0 and not r['fallback'] and old_outcome == r['public_view']['goal_observation_id'])
                        require(stale == r['stale_nonfallback_choice'], 'stale choice label')
                        old_stale += stale
                    metrics = row['windows'][f'block{b}_channel{ch}']
                    require(metrics['observed'] == len(items) and metrics['goal_successes'] == successes
                            and metrics['goal_rate'] == successes / len(items), 'reported window quality')
                    require(metrics['fallback_actions'] == sum(r['fallback'] for r in items)
                            and metrics['nonfallback_successes'] == sum(r['goal_reached'] and not r['fallback'] for r in items)
                            and metrics['fallback_successes'] == sum(r['goal_reached'] and r['fallback'] for r in items)
                            and metrics['raw_abstentions'] == sum(r['raw_abstention'] for r in items), 'reported fallback metrics')
                    require(metrics['stale_nonfallback_choices'] == old_stale
                            and metrics['stale_nonfallback_fraction'] == old_stale / len(items), 'reported cessation metric')
            table_windows.append({'seed': run['seed'], 'policy': name,
                                  'late_changed_conflict_queries': late_conflicts,
                                  'late_changed': row['windows']['block3_channel0'],
                                  'late_stable': row['windows']['block3_channel1']})
    counts.setdefault('changed_channel_update_then_correct_reuse', 0)
    return {'status': 'recorded_data_consistency_audit_pass_not_independent_execution',
            'counts': dict(counts), 'named_negative_delta_witnesses': witnesses,
            'conflict_witnesses': conflict_witnesses, 'windows': table_windows,
            'limitations': ['native hashes not reconstructed from full snapshots',
                            'same author audit, no independent task rerun',
                            'development41/42 only; no confirming criteria or gate verdict']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('raw', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'fresh audit path required')
    raw = args.raw.read_bytes()
    expected = args.raw.with_suffix(args.raw.suffix + '.sha256').read_text().split()[0]
    sha = hashlib.sha256(raw).hexdigest()
    require(sha == expected, 'raw SHA mismatch')
    result = audit(json.loads(raw))
    result.update(raw_sha256=sha, raw_name=args.raw.name)
    encoded = (json.dumps(result, indent=2) + '\n').encode()
    with args.out.open('xb') as f:
        f.write(encoded)
    with args.out.with_suffix(args.out.suffix + '.sha256').open('x') as f:
        f.write(hashlib.sha256(encoded).hexdigest() + '  ' + args.out.name + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('windows', 'named_negative_delta_witnesses', 'conflict_witnesses')}, indent=2))


if __name__ == '__main__':
    main()

