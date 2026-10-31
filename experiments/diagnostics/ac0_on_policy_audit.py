"""Recorded-data integrity audit; no model/world execution or independent replication."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.diagnostics.ac0_applicability_on_policy import POLICIES, PROTOCOL_SHA
from experiments.diagnostics.ac0_applicability_shadow import digest, require, UNKNOWN
from experiments.diagnostics.ac0_online_protocol import schedule_layout, PUBLIC_FIELDS


def choose(forecasts, view):
    outcomes = {op: set() for op in view['available_operations']}
    for f in forecasts:
        require(f['operation_id'] in outcomes, 'forecast unavailable operation')
        outcomes[f['operation_id']].add(f['predicted_observation'])
    eligible = [op for op, values in outcomes.items() if values == {view['goal_observation_id']}]
    return eligible[0] if len(eligible) == 1 else None


def audit(result):
    require(result['status'] == 'development_execution_complete_pending_write', 'incomplete execution')
    require(result['protocol_sha256'] == PROTOCOL_SHA and result['source_dirty'] is False, 'source/protocol')
    require(result['AC0_gate_pass'] is False and result['confirming_executed'] is False, 'gate/confirming claim')
    require([r['seed'] for r in result['runs']] == [41, 42] == [t['seed'] for t in result['training']], 'development pool')
    require(result['budget_counts'] == {'train_actions': 192, 'train_core_tokens': 480,
                                      'evaluation_actions': 1536, 'all_core_tokens': 2168}, 'budget counts')
    all_ids, counters = set(), Counter()
    for run, training in zip(result['runs'], result['training']):
        require([p['policy'] for p in run['policies']] == list(POLICIES), 'six policies')
        require(len(training['events']) == 96 and len(training['tokens']) == 240, 'training budget')
        for policy in run['policies']:
            name, records = policy['policy'], policy['records']
            native = name.startswith('prefix_')
            if native:
                require(policy['initial_native_state_digest'] == run['paired_initial_native_state_digest'], 'paired complete state')
            history = {(e['channel_id'], e['observation_id'], e['chosen_operation']): e['actual_observation']
                       for e in training['events'] if e['completion'] not in UNKNOWN}
            if name == 'random_uniform':
                history = None
            known_chains = {gid: c['feature_chain'] for gid, c in training['gen_creation'].items()}
            tokens = {(t['canonical_feature_id'], t['core_step']): {**t, 'episode_index': -1} for t in training['tokens']}
            require(len(records) == 128, '128 own episodes')
            observed = 0
            for row, case in zip(records, schedule_layout(run['seed'] + 1000)):
                counters['records'] += 1
                index = case['episode_index']
                require(row['state'] == 'finished' and row['case'] == case, 'schedule/state')
                seal, event, feedback = row['pre_outcome'], row['event'], row['feedback']
                require(digest(seal) == row['pre_outcome_digest'], 'pre-action seal changed')
                view, raw, selected = seal['public_view'], seal['raw_query'], seal['selected_query']
                require(set(view) == PUBLIC_FIELDS, 'hidden controller input')
                before_digest = digest(sorted([*k, v] for k, v in history.items())) if history is not None else None
                require(seal['history_before_digest'] == before_digest == feedback['history_before_digest'], 'future/foreign receipt')
                if native:
                    for d in seal['begin']['begin_gen_deltas']:
                        if d['after'] is not None:
                            known_chains[d['gen_id']] = d['after']['feature_chain']
                    cue = seal['begin']['cue_token']
                    tokens[(cue['canonical_feature_id'], cue['core_step'])] = {**cue, 'episode_index': index,
                        'channel_id': view['channel_id'], 'source': view['observation_id'], 'target': view['observation_id']}
                    for f in raw['forecasts']:
                        require(known_chains.get(f['gen_id']) == f['gen_chain'], 'forecast has no own Gen chain')
                    expected = [f for f in raw['forecasts'] if not name.startswith('prefix_actual_context_') or
                        (key := (view['channel_id'], view['observation_id'], f['operation_id'])) not in history or
                        history[key] == f['predicted_observation']]
                    require(selected['forecasts'] == expected, 'mask synthesized/removed wrong forecast')
                    require(raw['operation_id'] == choose(raw['forecasts'], view), 'raw selector')
                    expected_coverage = {'table_known_keys': 0, 'Gen_covered_table_keys': 0,
                                         'table_goal_eligible_keys': 0, 'Gen_covered_table_goal_keys': 0}
                    for op in view['available_operations']:
                        key = (view['channel_id'], view['observation_id'], op)
                        if key not in history:
                            continue
                        covered = any(f['operation_id'] == op and f['predicted_observation'] == history[key] for f in raw['forecasts'])
                        goal = history[key] == view['goal_observation_id']
                        expected_coverage['table_known_keys'] += 1
                        expected_coverage['Gen_covered_table_keys'] += covered
                        expected_coverage['table_goal_eligible_keys'] += goal
                        expected_coverage['Gen_covered_table_goal_keys'] += goal and covered
                    require(seal['coverage'] == expected_coverage, 'coverage/eligibility conflation')
                elif history is not None:
                    expected = [{'operation_id': op, 'predicted_observation': history[key]}
                                for op in view['available_operations']
                                if (key := (view['channel_id'], view['observation_id'], op)) in history]
                    require(raw['forecasts'] == selected['forecasts'] == expected, 'own-history table')
                else:
                    require(raw['forecasts'] == selected['forecasts'] == [], 'random forecasts')
                require(selected['operation_id'] == choose(selected['forecasts'], view), 'selected goal rule')
                abstention = selected['operation_id'] is None and name != 'random_uniform'
                operation = (view['available_operations'][case['random_slot']] if name == 'random_uniform' else
                             selected['operation_id'] or view['available_operations'][case['fallback_slot']])
                require(seal['operation_id'] == event['chosen_operation'] == operation, 'execution changed sealed choice')
                require(row['fallback'] == seal['fallback'] == abstention == row['raw_abstention'], 'fallback labeling')
                require(event['channel_id'] == view['channel_id'] and event['observation_id'] == view['observation_id'] and
                        set(event['available_operations']) == set(view['available_operations']), 'event public cue')
                receipt_id = (event['run_id'], event['event_id'])
                require(receipt_id not in all_ids, 'duplicate/cross-policy actual receipt')
                all_ids.add(receipt_id)
                admitted = not (name in ('prefix_actual_context_feedback_gate', 'table_feedback_gate') and
                                not case['gated_outcome_admitted'])
                require(feedback['admitted'] == admitted, 'withdrawal schedule')
                is_observed = event['completion'] not in UNKNOWN
                require((event['actual_observation'] is not None) == is_observed, 'unknown observation')
                if case['scheduled_status']:
                    require(event['completion'] == case['scheduled_status'], 'unknown schedule')
                else:
                    require(is_observed, 'missing scheduled observation')
                observed += is_observed
                goal = event['actual_observation'] == view['goal_observation_id'] if is_observed else None
                require(row['goal_reached'] == goal, 'actual task grade')
                expected_evidence = []
                if native:
                    n = feedback['native']
                    require(n['admitted'] == admitted and n['assimilated'] == (admitted and is_observed), 'native admission')
                    require(len(n['tokens']) == (2 if admitted and is_observed else 0), 'native token budget')
                    if not admitted or not is_observed:
                        require(n['native_before'] == n['native_after'] and n['native_unchanged'] and not n['gen_deltas'], 'unknown/withheld native mutation')
                    for t in n['tokens']:
                        source, target = ((event['observation_id'], operation) if t['role'] == 'cue_to_operation' else (operation, event['actual_observation']))
                        tokens[(t['canonical_feature_id'], t['core_step'])] = {**t, 'episode_index': index,
                            'channel_id': event['channel_id'], 'source': source, 'target': target}
                    for d in n['gen_deltas']:
                        if d['after'] is not None:
                            known_chains[d['gen_id']] = d['after']['feature_chain']
                    for f in selected['forecasts']:
                        support, reason = ('unknown', 'not_executed') if f['operation_id'] != operation else (
                            ('unknown', event['completion']) if not is_observed else (
                            'positive' if f['predicted_observation'] == event['actual_observation'] else 'negative', 'observed'))
                        expected_evidence.append({'gen_id': f['gen_id'], 'operation_id': f['operation_id'], 'support': support, 'reason': reason})
                    counters['unknown_withheld_native_guards'] += not admitted or not is_observed
                require(row['prediction_evidence'] == expected_evidence, 'unexecuted forecast grading')
                if history is not None and admitted and is_observed:
                    history[(event['channel_id'], event['observation_id'], operation)] = event['actual_observation']
                after_digest = digest(sorted([*k, v] for k, v in history.items())) if history is not None else None
                require(feedback['history_after_digest'] == after_digest and
                        feedback['history_changed'] == (before_digest != after_digest), 'own-history update')
                storage = row['storage']
                require(storage['delivery_receipt_ids'] == index + 1, 'delivery bookkeeping')
                require(storage['history_receipt_ids'] == (96 + index + 1 if history is not None else 0), 'history bookkeeping')
                require(storage['native_receipt_ids'] == (index + 1 if native else 0) and
                        storage['observer_receipt_ids'] == (96 + index + 1 if native else 0), 'native bookkeeping')
                require(storage['serialized_all_stores_bytes'] == sum(storage[k] for k in (
                    'observer_bytes', 'native_receipt_ids_bytes', 'actual_history_bytes_including_ids', 'delivery_receipt_ids_bytes')), 'all-store accounting')
                require(storage['actual_context_keys'] == (len(history) if history is not None else 0) <= 8, 'actual keys')
                require(storage['serialized_all_stores_bytes'] <= 33554432, 'storage budget')
            require(observed == 80, 'observed denominator')
            for update in policy['updates']:
                idx, stage = update['episode_index'], update['stage']
                original = records[idx]['pre_outcome']['begin']['begin_gen_deltas'] if stage == 'begin' else records[idx]['feedback']['native']['gen_deltas']
                require(update['state_delta'] in original, 'invented Gen update')
                d = update['state_delta']
                require(d['before'] is None or d['after']['success_count'] > d['before']['success_count'], 'stop-only reuse source')
                require([w['canonical_feature_id'] for w in update['feature_witnesses']] == d['after']['feature_chain'], 'chain witness order')
                for witness in update['feature_witnesses']:
                    require(tokens.get((witness['canonical_feature_id'], witness['core_step'])) == witness, 'invented/nonadmitted token witness')
                    require(witness['episode_index'] <= idx, 'future update witness')
            for link in policy['causal_links']:
                source, target = link['update_episode_index'], link['reuse_episode_index']
                require(source < target, 'update must precede later choice')
                reuse = records[target]
                require(reuse['goal_reached'] is True and reuse['fallback'] is False, 'fallback/incorrect causal reuse')
                updates = [u for u in policy['updates'] if u['gen_id'] == link['gen_id'] and
                           u['episode_index'] == source and u['stage'] == link['update_stage']]
                require(updates, 'missing named update')
                forecasts = [f for f in reuse['pre_outcome']['selected_query']['forecasts'] if f['gen_id'] == link['gen_id'] and
                             f['operation_id'] == reuse['event']['chosen_operation'] and f['predicted_observation'] == reuse['event']['actual_observation']]
                require(forecasts and any(u['state_delta']['after']['feature_chain'] == forecasts[0]['gen_chain'] for u in updates), 'named forecast mismatch')
                witness = link['outcome_feature_witness']
                require(witness is not None and any(witness in u['feature_witnesses'] for u in updates), 'outcome witness absent')
                changed = bool(reuse['case']['channel_index'] == 0 and reuse['case']['block_index'] >= 1 and
                    witness['episode_index'] >= 0 and records[witness['episode_index']]['case']['block_index'] >= 1 and
                    witness['channel_id'] == reuse['event']['channel_id'] and witness['source'] == reuse['event']['chosen_operation'] and
                    witness['target'] == reuse['event']['actual_observation'])
                require(link['changed_channel_actual_witness'] == changed, 'stable/changed witness conflation')
                counters['changed_channel_causal_links'] += changed
                counters['causal_links'] += 1
    require(counters['records'] == 1536, 'complete audit count')
    return {'status': 'recorded_data_consistent', 'counts': dict(counters),
            'new_world_actions': 0, 'independent_execution': False, 'AC0_gate_pass': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    args = parser.parse_args()
    raw = args.raw.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    receipt = json.loads(args.raw.with_suffix(args.raw.suffix + '.completion.json').read_text())
    require(receipt['status'] == 'development_complete' and receipt['raw_sha256'] == sha and
            receipt['raw_bytes'] == len(raw) <= 33554432 and receipt['elapsed_including_write'] <= 60, 'completion receipt')
    result = audit(json.loads(raw))
    print(json.dumps({'raw_sha256': sha, **result}, indent=2))


if __name__ == '__main__':
    main()
