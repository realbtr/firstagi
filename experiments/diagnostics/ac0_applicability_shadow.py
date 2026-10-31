"""Stdlib-only applicability shadows on fixed saved receipts, never a rollout."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'experiments/reports/ac0_debug/online_feedback/v1'
PROTOCOL = ROOT / 'experiments/protocols/ac0_applicability_shadow_v1.json'
PROTOCOL_SHA = '738b96c253066651c026028d15eb030ed4faf7b542db11c20adc22c300a8c925'
SOURCE = DIRECTORY / 'development_41_42_20261030T2334.json'
REPLAY = DIRECTORY / 'context_replay_20261031T0135.json'
PUBLIC = {'channel_id', 'observation_id', 'available_operations', 'goal_observation_id'}
UNKNOWN = {'interrupted', 'unavailable', 'cancelled'}
POLICIES = ('recorded_all_prefix', 'recorded_query_intersect_live_operation_frontier',
            'last_admitted_actual_compatible_Gen_forecasts', 'adaptive_last_actual_table')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_checked(path, sha):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == sha, 'pinned input bytes changed')
    return json.loads(raw)


def validate_view(view):
    require(set(view) == PUBLIC, 'only four public fields allowed')
    require(len(view['available_operations']) == 2 and len(set(view['available_operations'])) == 2, 'two public operations required')


def key(view, operation):
    return view['channel_id'], view['observation_id'], operation


class ActualHistory:
    """Latest prior observed/admitted receipt per executed key, not Gen support."""
    def __init__(self):
        self.values = {}
        self.seen = set()

    def ingest(self, event, *, admitted):
        require(type(admitted) is bool, 'boolean admission required')
        receipt_id = (event['run_id'], event['event_id'])
        require(receipt_id not in self.seen, 'duplicate receipt')
        require(event['chosen_operation'] in event['available_operations'], 'unavailable operation')
        status = event['completion']
        require(status in UNKNOWN | {'success', 'observed_divergence'}, 'unsupported completion')
        require((status in UNKNOWN) == (event['actual_observation'] is None), 'unknown/actual mismatch')
        before = self.fingerprint()
        if admitted and status not in UNKNOWN:
            self.values[(event['channel_id'], event['observation_id'], event['chosen_operation'])] = event['actual_observation']
        self.seen.add(receipt_id)
        return before != self.fingerprint()

    def fingerprint(self):
        return digest(sorted([*k, v] for k, v in self.values.items()))


def project_forecasts(rows):
    return [{'gen_id': r['gen_id'], 'operation_id': r['operation_id'],
             'predicted_observation': r['predicted_observation']} for r in rows]


def shadow_queries(view, forecasts, live_rows, history):
    """No current event, case/block or future outcome argument is available."""
    validate_view(view)
    require(all(f['operation_id'] in view['available_operations'] for f in forecasts), 'unavailable forecast')
    live_ids = {r['gen_id'] for r in live_rows if r['cursor'] == 1 and not r['completed']}
    eligible = [f for f in forecasts if key(view, f['operation_id']) not in history.values or
                history.values[key(view, f['operation_id'])] == f['predicted_observation']]
    table = [{'operation_id': op, 'predicted_observation': history.values[key(view, op)]}
             for op in view['available_operations'] if key(view, op) in history.values]
    variants = (forecasts, [f for f in forecasts if f['gen_id'] in live_ids], eligible, table)
    outputs = []
    for name, rows in zip(POLICIES, variants):
        outcomes = {op: set() for op in view['available_operations']}
        for f in rows:
            outcomes[f['operation_id']].add(f['predicted_observation'])
        options = [op for op, values in outcomes.items() if values == {view['goal_observation_id']}]
        q = {'policy': name, 'operation_id': options[0] if len(options) == 1 else None,
             'forecasts': deepcopy(rows),
             'conflicting_operations': sum(len(values) > 1 for values in outcomes.values())}
        q['raw_abstention'] = q['operation_id'] is None
        outputs.append(q)
    coverage = {'table_known_keys': len(table),
                'Gen_covered_table_keys': sum(any(f['operation_id'] == t['operation_id'] and
                    f['predicted_observation'] == t['predicted_observation'] for f in forecasts) for t in table),
                'table_goal_eligible_keys': sum(t['predicted_observation'] == view['goal_observation_id'] for t in table),
                'Gen_covered_table_goal_keys': sum(t['predicted_observation'] == view['goal_observation_id'] and
                    any(f['operation_id'] == t['operation_id'] and f['predicted_observation'] == t['predicted_observation']
                        for f in forecasts) for t in table)}
    return outputs, coverage


def grade_saved_execution(query, event):
    observed = event['completion'] not in UNKNOWN
    support = ['unknown' if not observed or f['operation_id'] != event['chosen_operation'] else
               'positive' if f['predicted_observation'] == event['actual_observation'] else 'negative'
               for f in query['forecasts']]
    if query['operation_id'] is None:
        outcome = {'status': 'unknown', 'reason': 'shadow_abstention', 'actual_observation': None}
    elif query['operation_id'] != event['chosen_operation']:
        outcome = {'status': 'unknown', 'reason': 'not_executed', 'actual_observation': None}
    elif not observed:
        outcome = {'status': 'unknown', 'reason': event['completion'], 'actual_observation': None}
    else:
        outcome = {'status': 'observed_saved_action', 'actual_observation': event['actual_observation']}
    return {'forecast_support': support, 'choice_matches_saved_action': query['operation_id'] == event['chosen_operation'],
            'choice_outcome': outcome}


def summarize(runs):
    rows = []
    for run in runs:
        for name in POLICIES:
            cells = [p for r in run['records'] for p in r['policies'] if p['query']['policy'] == name]
            counts = Counter(s for p in cells for s in p['grade']['forecast_support'])
            rows.append({'seed': run['seed'], 'policy': name, 'queries': len(cells),
                         'raw_abstentions': sum(p['query']['raw_abstention'] for p in cells),
                         'conflicting_operations': sum(p['query']['conflicting_operations'] for p in cells),
                         'matches_saved_action': sum(p['grade']['choice_matches_saved_action'] for p in cells),
                         'unexecuted_shadow_choices': sum(p['grade']['choice_outcome'].get('reason') == 'not_executed' for p in cells),
                         'forecast_support': {s: counts[s] for s in ('positive', 'negative', 'unknown')}})
    return rows


def analyze(source, replay, config, *, clock=time.perf_counter):
    # Pool validation precedes use of any training/evaluation receipt.
    require([r['seed'] for r in source['runs']] == [41, 42] ==
            [r['seed'] for r in replay['runs']] == config['task_seeds'], 'development pool41/42 only')
    require(tuple(config['policies']) == POLICIES, 'declared policy set changed')
    started = clock()
    limits = config['budgets']
    result = {'schema': 'firstagi.ac0-applicability-shadow/v1', 'status': 'running',
              'protocol_sha256': PROTOCOL_SHA, 'runs': [], 'counts': {'saved_cases': 0, 'shadow_queries': 0},
              'new_world_actions': 0, 'new_task_outcomes': 0, 'core_tokens': 0,
              'on_policy_recovery_claim': False, 'AC0_gate_pass': False,
              'confirming_executed': False, 'independent_execution': False}
    try:
        for seed in (41, 42):
            training = next(x for x in source['training'] if x['seed'] == seed)
            input_run = next(x for x in replay['runs'] if x['seed'] == seed)
            require(len(training['events']) == 96 and len(input_run['records']) == 128, 'fixed saved trajectory length')
            history = ActualHistory()
            for event in training['events']:
                history.ingest(event, admitted=True)
            run = {'seed': seed, 'initial_history_keys': len(history.values), 'records': []}
            result['runs'].append(run)
            for old in input_run['records']:
                require(clock() - started <= limits['max_wall_seconds'], 'shadow wall budget exceeded')
                require(result['counts']['saved_cases'] < limits['max_saved_cases'], 'saved case budget')
                view = old['public_view']
                before = history.fingerprint()
                forecasts = project_forecasts(old['readout_query']['forecasts'])
                queries, coverage = shadow_queries(view, forecasts, old['live_after_cue'], history)
                require(queries[0]['operation_id'] == old['readout_query']['operation_id'], 'unchanged original choice')
                require(history.fingerprint() == before, 'query mutated contextual history')
                record = {'episode_index': old['episode_index'], 'case': old['case'],
                          'public_view': view, 'history_before_digest': before,
                          'coverage': coverage, 'policies': [], 'state': 'pending'}
                run['records'].append(record)
                # All four seals exist BEFORE reading/consuming this current event.
                for query in queries:
                    require(result['counts']['shadow_queries'] < limits['max_shadow_queries'], 'query budget')
                    record['policies'].append({'query': query, 'pre_outcome_digest': digest(query)})
                    result['counts']['shadow_queries'] += 1
                event = old['saved_event']
                record['saved_event'] = event
                for policy in record['policies']:
                    policy['grade'] = grade_saved_execution(policy['query'], event)
                admitted = old['feedback']['admitted']
                record['receipt_admitted'] = admitted
                record['history_changed'] = history.ingest(event, admitted=admitted)
                record['history_after_digest'] = history.fingerprint()
                record['state'] = 'finished'
                result['counts']['saved_cases'] += 1
        require(result['counts'] == {'saved_cases': 256, 'shadow_queries': 1024}, 'complete declared budget')
        result['summary'] = summarize(result['runs'])
        result['coverage_totals'] = {name: sum(r['coverage'][name] for run in result['runs'] for r in run['records'])
            for name in ('table_known_keys', 'Gen_covered_table_keys', 'table_goal_eligible_keys', 'Gen_covered_table_goal_keys')}
        result['comparisons'] = {
            'original_live_queries_identical': all(r['policies'][0]['query']['operation_id'] == r['policies'][1]['query']['operation_id']
                and r['policies'][0]['query']['forecasts'] == r['policies'][1]['query']['forecasts']
                for run in result['runs'] for r in run['records']),
            'mask_table_choices_identical': all(r['policies'][2]['query']['operation_id'] == r['policies'][3]['query']['operation_id']
                for run in result['runs'] for r in run['records'])}
        result['status'] = 'shadow_analysis_complete_not_policy_rollout'
    except Exception as error:
        result.update(status='incomplete', error=type(error).__name__ + ': ' + str(error))
    return result


def audit_output(result, source, replay):
    """Rebuild past receipt map and check provenance/grading; no world/model."""
    require(result['status'] == 'shadow_analysis_complete_not_policy_rollout', 'incomplete output')
    require(result['counts'] == {'saved_cases': 256, 'shadow_queries': 1024}, 'audit budget counts')
    require(all(result[k] == 0 for k in ('new_world_actions', 'new_task_outcomes', 'core_tokens')), 'nonzero world/core work')
    for run in result['runs']:
        seed = run['seed']
        train = next(r for r in source['training'] if r['seed'] == seed)
        saved = next(r for r in replay['runs'] if r['seed'] == seed)['records']
        latest = {(e['channel_id'], e['observation_id'], e['chosen_operation']): e['actual_observation']
                  for e in train['events'] if e['completion'] not in UNKNOWN}
        require(len(run['records']) == len(saved) == 128, 'audit case count')
        for row, old in zip(run['records'], saved):
            require(row['episode_index'] == old['episode_index'] and row['saved_event'] == old['saved_event'], 'audit trajectory')
            require(row['public_view'] == old['public_view'], 'audit public view')
            view = row['public_view']
            require(row['history_before_digest'] == digest(sorted([*k, v] for k, v in latest.items())), 'current/future receipt leak')
            originals = {f['gen_id']: (f['operation_id'], f['predicted_observation']) for f in old['readout_query']['forecasts']}
            live = {r['gen_id'] for r in old['live_after_cue'] if r['cursor'] == 1 and not r['completed']}
            require(len(row['policies']) == 4 and row['state'] == 'finished', 'four finished policies')
            for p, name in zip(row['policies'], POLICIES):
                q, grade = p['query'], p['grade']
                require(q['policy'] == name and digest(q) == p['pre_outcome_digest'], 'query seal/policy')
                if name != POLICIES[3]:
                    expected = {gid: pair for gid, pair in originals.items() if name == POLICIES[0] or
                        (name == POLICIES[1] and gid in live) or
                        (name == POLICIES[2] and ((view['channel_id'], view['observation_id'], pair[0]) not in latest or
                          latest[(view['channel_id'], view['observation_id'], pair[0])] == pair[1]))}
                    require({f['gen_id']: (f['operation_id'], f['predicted_observation']) for f in q['forecasts']} == expected,
                            'Gen forecast provenance/eligibility')
                else:
                    expected = {(op, latest[(view['channel_id'], view['observation_id'], op)])
                                for op in view['available_operations'] if (view['channel_id'], view['observation_id'], op) in latest}
                    require({(f['operation_id'], f['predicted_observation']) for f in q['forecasts']} == expected, 'table provenance')
                outcomes = {op: set() for op in view['available_operations']}
                for f in q['forecasts']:
                    outcomes[f['operation_id']].add(f['predicted_observation'])
                options = [op for op, values in outcomes.items() if values == {view['goal_observation_id']}]
                require(q['operation_id'] == (options[0] if len(options) == 1 else None), 'selector consistency')
                require(q['raw_abstention'] == (q['operation_id'] is None) and
                        q['conflicting_operations'] == sum(len(v) > 1 for v in outcomes.values()), 'query metric labels')
                e = row['saved_event']
                observed = e['completion'] not in UNKNOWN
                supports = ['unknown' if not observed or f['operation_id'] != e['chosen_operation'] else
                            'positive' if f['predicted_observation'] == e['actual_observation'] else 'negative' for f in q['forecasts']]
                require(grade['forecast_support'] == supports, 'executed-only forecast evidence')
                require(grade['choice_matches_saved_action'] == (q['operation_id'] == e['chosen_operation']), 'saved-action agreement')
                if q['operation_id'] != e['chosen_operation'] or not observed:
                    reason = ('shadow_abstention' if q['operation_id'] is None else
                              'not_executed' if q['operation_id'] != e['chosen_operation'] else e['completion'])
                    require(grade['choice_outcome'] == {'status': 'unknown', 'reason': reason,
                            'actual_observation': None}, 'counterfactual outcome leak')
                else:
                    require(grade['choice_outcome'] == {'status': 'observed_saved_action', 'actual_observation': e['actual_observation']}, 'saved actual mismatch')
            e = row['saved_event']
            require(row['receipt_admitted'] == old['feedback']['admitted'], 'admission tamper')
            if row['receipt_admitted'] and e['completion'] not in UNKNOWN:
                latest[(e['channel_id'], e['observation_id'], e['chosen_operation'])] = e['actual_observation']
            require(row['history_after_digest'] == digest(sorted([*k, v] for k, v in latest.items())), 'history update mismatch')
    require(result['summary'] == summarize(result['runs']), 'summary mismatch')
    return {'status': 'recorded_data_audit_pass_not_independent_execution', 'checked_cases': 256,
            'checked_queries': 1024, 'no_new_model_execution': True}


def fresh(path):
    require(not any(p.exists() for p in (path, path.with_suffix(path.suffix + '.sha256'),
                                        path.with_suffix(path.suffix + '.completion.json'))), 'fresh output/companions required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    fresh(args.out)
    started = time.perf_counter()
    config = load_checked(PROTOCOL, PROTOCOL_SHA)
    source = load_checked(SOURCE, config['source_receipts_sha256'])
    replay = load_checked(REPLAY, config['source_frontier_replay_sha256'])
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    result = analyze(source, replay, config)
    try:
        result['recorded_data_audit'] = audit_output(result, source, replay)
    except Exception as error:
        result.update(status='incomplete', audit_error=str(error))
    result.update(source_commit=commit, source_dirty=dirty, python=sys.version, platform=platform.platform())
    encoded = (json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode()
    if len(encoded) > config['budgets']['max_raw_bytes']:
        result = {'status': 'incomplete', 'error': 'raw budget exceeded; oversized details omitted',
                  'source_commit': commit, 'counts': result['counts']}
        encoded = (json.dumps(result) + '\n').encode()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('xb') as f:
        f.write(encoded)
    sha = hashlib.sha256(encoded).hexdigest()
    with args.out.with_suffix(args.out.suffix + '.sha256').open('x') as f:
        f.write(sha + '  ' + args.out.name + '\n')
    elapsed = time.perf_counter() - started
    receipt = {'status': 'incomplete' if elapsed > config['budgets']['max_wall_seconds'] or result['status'] == 'incomplete' else 'shadow_complete',
               'raw_sha256': sha, 'raw_bytes': len(encoded), 'elapsed_including_raw_write': elapsed}
    with args.out.with_suffix(args.out.suffix + '.completion.json').open('x') as f:
        json.dump(receipt, f, indent=2)
        f.write('\n')
    print(json.dumps({'completion': receipt, 'counts': result.get('counts'),
                      'comparisons': result.get('comparisons'), 'coverage': result.get('coverage_totals'),
                      'summary': result.get('summary'), 'error': result.get('error') or result.get('audit_error')}, indent=2))
    if receipt['status'] == 'incomplete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

