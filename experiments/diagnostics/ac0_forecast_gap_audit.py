"""Cross-check saved replay observations against original own-action records.

No learner/world construction, token replay or fresh task outcomes.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.diagnostics.ac0_applicability_shadow import ActualHistory, digest, require
from experiments.diagnostics.ac0_forecast_gap_replay import INPUT_SHA, POLICY, TARGETS, semantics, source_rows
from experiments.diagnostics.ac0_event_baseline import UNKNOWN
from experiments.diagnostics.ac0_operation_codec import OperationCodec

REPLAY_SHA = '1ca4c73dac76915f43a7a292e40d4a87f2d4b89766c1b9999234302290a5a054'


def audit(replay, source):
    training, policy = source_rows(source)
    require(replay['status'] == 'saved_receipt_replay_complete_not_new_policy_run', 'incomplete replay')
    require(replay['input_raw_sha256'] == INPUT_SHA and replay['source_dirty'] is False and
            replay['source_commit'] == 'ecb0660f45c2dfc13825be3c64a7332cef04e129', 'source/hash manifest')
    require(replay['original_execution_completion'] == 'incomplete_raw_size_budget_not_upgraded', 'original failure scope')
    require(replay['seed'] == 42 and replay['policy'] == POLICY and replay['declared_targets'] == list(TARGETS), 'scope')
    require(replay['core_tokens'] == 508 and len(replay['records']) == 128, 'complete replay counts')
    require(all(replay[k] == 0 for k in ('new_world_constructions', 'new_world_actions', 'new_task_outcomes')), 'new task work')
    require(not replay['confirming_executed'] and not replay['AC0_gate_pass'] and not replay['independent_execution'], 'claim boundary')
    inspections = {x['episode_index']: x for x in replay['inspections']}
    require(sorted(inspections) == list(TARGETS) and len(replay['inspections']) == 4, 'four inspections')
    resets = {x['episode_index']: x for x in replay['reset_deltas']}
    require(sorted(resets) == list(range(128)), 'reset trace coverage')
    trace = {}
    for token in replay['token_trace']:
        trace.setdefault(token['episode_index'], []).append(token)
    require(sorted(trace) == list(range(128)) and len(replay['token_trace']) == 268, 'evaluation token trace count')
    chains = {gid: c['feature_chain'] for gid, c in training['gen_creation'].items()}
    wanted = {tuple(x['native']['desired_chain']) for x in inspections.values()}
    require(len(wanted) == 2, 'two underlying forecast keys')
    counts = dict.fromkeys(wanted, 0)
    crossings, births, first_forecast, first_correct = {}, {}, {}, {}
    history = ActualHistory()
    past = []
    origins = {}

    def add_origin(token, channel, start, end):
        origins.setdefault(token['canonical_feature_id'], set()).add((token['role'], channel, start, end))

    for t in training['tokens']:
        add_origin(t, t['channel_id'], t['source'], t['target'])
    for index, event in enumerate(training['events']):
        history.ingest(event, admitted=True)
        past.append({'stage': 'training', 'event_index': index, 'event': event, 'admitted': True})

    def apply_gens(deltas, episode, stage):
        for d in deltas:
            if d['after'] is None:
                chains.pop(d['gen_id'], None)
                continue
            chain = d['after']['feature_chain']
            chains[d['gen_id']] = chain
            if tuple(chain) in wanted and d['before'] is None:
                births.setdefault(tuple(chain), {'episode': episode, 'stage': stage,
                                                'gen_id': d['gen_id'], 'success_count': d['after']['success_count']})

    def apply_candidates(deltas, episode, stage):
        for d in deltas:
            chain = tuple(d['chain'])
            if chain not in wanted:
                continue
            require(d['before'] == counts[chain], 'candidate transition discontinuity')
            counts[chain] = d['after']
            if d['before'] < 2 <= d['after']:
                crossings.setdefault(chain, {'episode': episode, 'stage': stage,
                                            'before': d['before'], 'after': d['after']})

    for index, (row, old) in enumerate(zip(replay['records'], policy['records'])):
        view, seal, event = old['pre_outcome']['public_view'], old['pre_outcome'], old['event']
        require(row['episode_index'] == index and row['matched_saved'] is True, 'saved query index')
        apply_gens(seal['begin']['begin_gen_deltas'], index, 'begin')
        cue = seal['begin']['cue_token']
        add_origin(cue, view['channel_id'], view['observation_id'], view['observation_id'])
        tokens = trace[index]
        old_tokens = [cue, *old['feedback']['native']['tokens']]
        signature = lambda t: (t['role'], t['canonical_feature_id'], t['core_step'], t['outcome'])
        require([signature(t) for t in tokens] == [signature(t) for t in old_tokens], 'invented or omitted native token')
        apply_candidates(resets[index]['candidate_deltas_before_cue'], index, 'reset_before_cue')
        apply_candidates(tokens[0]['candidate_deltas'], index, 'cue')
        require(row['raw_semantic_digest'] == digest(semantics(seal['raw_query']['forecasts'])) and
                row['selected_semantic_digest'] == digest(semantics(seal['selected_query']['forecasts'])), 'semantic readout agreement')
        require(row['raw_operation_id'] == seal['raw_query']['operation_id'] and
                row['selected_operation_id'] == seal['selected_query']['operation_id'], 'query choice agreement')
        require(row['history_before_digest'] == history.fingerprint() == seal['history_before_digest'], 'future/foreign receipt before query')
        for f in seal['raw_query']['forecasts']:
            key = tuple(f['gen_chain'])
            if key in wanted:
                first_forecast.setdefault(key, index)
                if old['goal_reached'] is True and not old['fallback'] and f['operation_id'] == event['chosen_operation'] and f['predicted_observation'] == event['actual_observation']:
                    first_correct.setdefault(key, index)
        if index in inspections:
            inspect = inspections[index]
            native = inspect['native']
            require(inspect['public_view'] == view and inspect['history_before_digest'] == history.fingerprint() and
                    inspect['pre_current_feedback_sealed'] is True, 'inspection timing')
            op, goal = native['operation_id'], view['goal_observation_id']
            require(history.values.get((view['channel_id'], view['observation_id'], op)) == goal, 'missing prior actual goal')
            codec = OperationCodec()
            descriptions = [(view['observation_id'], view['observation_id'], 'cue_anchor'),
                            (view['observation_id'], op, 'cue_to_operation'), (op, goal, 'operation_to_observation')]
            expected = [codec.encode_role(view['channel_id'], start, end, role).feature_id for start,end,role in descriptions]
            require(native['desired_chain'] == expected, 'wrong desired feature chain')
            require(len(native['features']) == 3, 'three features')
            for feature, fid, (start,end,role) in zip(native['features'], expected, descriptions):
                expected_origin = (role, view['channel_id'], start, end)
                require(feature['feature_id'] == fid and feature['registered'] and feature['canonical_match'] and
                        feature['unique_expected_origin'] and origins.get(fid) == {expected_origin} and
                        feature['origins'] == [list(expected_origin)], 'encoding/origin source witness')
            require(not any(chain[:3] == expected or any(chain[i:i+3] == expected for i in range(1,len(chain)-2))
                            for chain in chains.values()), 'forecast chain already exists in original state')
            require(native['stored_prefix_chains'] == [] and native['stored_interior_chains'] == [] and
                    native['raw_matching_forecasts'] == [] and native['selected_matching_forecasts'] == [], 'fabricated missing-chain evidence')
            require(counts[tuple(expected)] == native['desired_candidate_count'] == 1 and
                    native['min_gen_count'] == 2 and native['classification'] == 'missing_native_forecast_chain', 'candidate threshold evidence')
            expected_past = [p for p in past if p['admitted'] and p['event']['completion'] not in UNKNOWN and
                (p['event']['channel_id'],p['event']['observation_id'],p['event']['chosen_operation']) ==
                (view['channel_id'],view['observation_id'],op)]
            require(inspect['past_executed_key_receipts'] == expected_past, 'past evidence provenance')
            require(sum(p['event']['actual_observation'] == goal for p in expected_past) == 1, 'exactly one prior admitted goal receipt')
        for t in tokens[1:]:
            apply_candidates(t['candidate_deltas'], index, t['role'])
            start,end = (view['observation_id'],event['chosen_operation']) if t['role'] == 'cue_to_operation' else (event['chosen_operation'],event['actual_observation'])
            add_origin(t,view['channel_id'],start,end)
        apply_gens(old['feedback']['native']['gen_deltas'],index,'feedback')
        admitted = old['feedback']['admitted']
        history.ingest(event,admitted=admitted)
        require(row['receipt_admitted'] == admitted and row['history_after_digest'] == history.fingerprint() ==
                old['feedback']['history_after_digest'] and row['actual_receipt_id'] == [event['run_id'],event['event_id']], 'actual receipt update')
        if not admitted or event['completion'] in UNKNOWN:
            require(row['unknown_withheld_guard'] is True and not old['feedback']['native']['tokens'], 'unknown/withheld mutation')
        past.append({'stage':'evaluation','event_index':index,'event':event,'admitted':admitted})
    require(replay['classifications'] == {'missing_native_forecast_chain':4}, 'classification summary')
    summaries=[]
    for key in sorted(wanted):
        crossing, birth = crossings[key],births[key]
        require(crossing['episode'] == birth['episode'] and crossing['stage'] == 'operation_to_observation' and
                birth['stage'] == 'feedback' and crossing['after'] == 2, 'threshold-to-creation source join')
        require(first_forecast[key] > birth['episode'] and first_correct[key] >= first_forecast[key], 'later actual reuse')
        summaries.append({'chain':list(key), 'threshold_crossing':crossing, 'original_Gen_birth':birth,
                          'first_later_forecast_episode':first_forecast[key],
                          'first_later_correct_nonfallback_episode':first_correct[key]})
    return {'status':'recorded_data_consistent','matched_queries':128,'missing_chain_cases':4,
            'distinct_chains':2,'threshold_then_creation_then_reuse':summaries,
            'new_world_actions':0,'new_model_tokens':0,'independent_execution':False,
            'AC0_gate_pass':False,'original_rollout_status':'incomplete_unchanged'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--replay',type=Path,required=True)
    args=parser.parse_args()
    original,raw=args.source.read_bytes(),args.replay.read_bytes()
    require(hashlib.sha256(original).hexdigest()==INPUT_SHA,'original raw hash')
    require(hashlib.sha256(raw).hexdigest()==REPLAY_SHA,'replay raw hash')
    completion=json.loads(args.replay.with_suffix(args.replay.suffix+'.completion.json').read_bytes())
    require(completion['status']=='receipt_replay_complete' and completion['raw_sha256']==REPLAY_SHA and
            completion['raw_bytes']==len(raw)<=2097152 and completion['elapsed_including_write']<=60,'replay completion')
    print(json.dumps(audit(json.loads(raw),json.loads(original)),indent=2))


if __name__=='__main__':
    main()
