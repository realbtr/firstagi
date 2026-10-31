"""Saved gated seed42 history: locate four forecast gaps, no new world/action."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
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
from experiments.diagnostics.ac0_applicability_on_policy import full_state_fingerprint
from experiments.diagnostics.ac0_applicability_shadow import ActualHistory, digest, require, shadow_queries
from experiments.diagnostics.ac0_event_baseline import TransitionEvent, UNKNOWN
from experiments.diagnostics.ac0_frozen_goal import FrozenGoalPredictor, BoundaryError
from experiments.diagnostics.ac0_goal_evaluator import ensure_fresh_output
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver
from experiments.diagnostics.ac0_online_feedback import deliver_feedback

INPUT_SHA = 'b565e4d6df5f35e1da49ec145b11586054dcee28f408bcb6f7c23547fd771dee'
DEFAULT = ROOT / 'experiments/reports/ac0_debug/online_feedback/v1/on_policy_dev_20261031T0540.json'
POLICY = 'prefix_actual_context_feedback_gate'
TARGETS = (96, 98, 104, 112)


def semantics(rows):
    """Ignore random native IDs and traversal order, retain forecast multiplicity."""
    return sorted(json.dumps([r['gen_chain'], r['operation_id'], r['predicted_observation']], separators=(',', ':'))
                  for r in rows)


def candidate_delta(before, after):
    return [{'chain': list(chain), 'before': before.get(chain, 0), 'after': after.get(chain, 0)}
            for chain in sorted(before.keys() | after.keys()) if before.get(chain, 0) != after.get(chain, 0)]


class ReplayObserver(CodedKernelObserver):
    def __init__(self, started, *, clock=time.perf_counter, max_tokens=508):
        super().__init__()
        self.started, self.clock, self.max_tokens = started, clock, max_tokens
        self.capture = False
        self.stage = 'training'
        self.episode = -1
        self.token_trace = []

    def check(self):
        if self.clock() - self.started > 60:
            raise BoundaryError('whole replay wall budget exceeded')

    def _ingest(self, channel, source, target, role):
        self.check()
        if self.system.engine.step_count >= self.max_tokens:
            raise BoundaryError('replay core token budget exceeded')
        before = dict(self.system.generalizer._candidates) if self.capture else None
        self.last_candidates_before_token = before
        chain_before = list(self.system.generalizer._current_chain) if self.capture else None
        step = super()._ingest(channel, source, target, role)
        if self.capture:
            self.token_trace.append({**step, 'episode_index': self.episode,
                'channel_id': channel, 'source': source, 'target': target,
                'current_chain_before': chain_before,
                'current_chain_after': list(self.system.generalizer._current_chain),
                'candidate_deltas': candidate_delta(before, self.system.generalizer._candidates)})
        return step


def inspect_goal(observer, view, operation, raw_query, selected_query):
    """Read all native chains/candidates for an already prior-actual goal key."""
    before = full_state_fingerprint(observer)
    ch, cue, goal = view['channel_id'], view['observation_id'], view['goal_observation_id']
    descriptions = [(ch, cue, cue, 'cue_anchor'), (ch, cue, operation, 'cue_to_operation'),
                    (ch, operation, goal, 'operation_to_observation')]
    features = []
    wanted = []
    for channel, source, target, role in descriptions:
        canonical = observer.codec.encode_role(channel, source, target, role)
        fid = canonical.feature_id
        wanted.append(fid)
        stored = observer.system.engine._features.get(fid)
        origins = observer.provenance.get(fid, set())
        expected_origin = (role, channel, source, target)
        features.append({'feature_id': fid, 'role': role, 'registered': stored is not None,
            'canonical_match': stored is not None and asdict(stored) == asdict(canonical),
            'origins': [list(x) for x in sorted(origins)],
            'unique_expected_origin': origins == {expected_origin},
            'atomic_Gen_ids': [g.gen_id for g in observer.system.base.search_by_chain([fid])]})
    prefix, interior = [], []
    visited = 0
    for gen in observer.system.base.all():
        visited += 1
        require(visited <= 4096, 'diagnostic full-base scan budget')
        chain = list(gen.feature_chain)
        if chain[:3] == wanted:
            prefix.append({'gen_id': gen.gen_id, 'chain': chain,
                           'success_count': gen.success_count, 'stop_count': gen.stop_count})
        elif any(chain[i:i+3] == wanted for i in range(1, len(chain) - 2)):
            interior.append({'gen_id': gen.gen_id, 'chain': chain})
    raw_matching = [f for f in raw_query['forecasts'] if f['operation_id'] == operation and f['predicted_observation'] == goal]
    selected_matching = [f for f in selected_query['forecasts'] if f['operation_id'] == operation and f['predicted_observation'] == goal]
    encoded = all(f['canonical_match'] and f['unique_expected_origin'] for f in features)
    if not encoded:
        classification = 'feature_encoding_or_provenance_gap'
    elif not prefix:
        classification = 'prefix_position_gap' if interior else 'missing_native_forecast_chain'
    elif not raw_matching:
        classification = 'verified_retrieval_or_decode_gap'
    elif not selected_matching:
        classification = 'actual_context_eligibility_gap'
    else:
        classification = 'forecast_present'
    candidates = [{'chain': list(chain), 'count': count}
                  for chain, count in sorted(observer.system.generalizer._candidates.items())
                  if len(chain) >= 3 and (list(chain[:3]) == wanted or
                     any(list(chain[i:i+3]) == wanted for i in range(1, len(chain) - 2)))]
    result = {'operation_id': operation, 'goal_observation_id': goal, 'desired_chain': wanted,
              'features': features, 'stored_prefix_chains': prefix, 'stored_interior_chains': interior,
              'raw_matching_forecasts': raw_matching, 'selected_matching_forecasts': selected_matching,
              'classification': classification, 'candidate_matches': candidates,
              'desired_candidate_count': observer.system.generalizer._candidates.get(tuple(wanted), 0),
              'min_gen_count': observer.system.generalizer.min_count,
              'current_chain': list(observer.system.generalizer._current_chain),
              'full_base_records_visited': visited}
    require(full_state_fingerprint(observer) == before, 'diagnostic inspection mutated native state')
    return result


def source_rows(data):
    require([r['seed'] for r in data['runs']] == [41, 42] and [t['seed'] for t in data['training']] == [41, 42], 'saved development pool41/42 only')
    require(data['source_commit'] == '50a752ece7a1ebdc4d6827d3d3a7ac7d4ab7547e' and data['source_dirty'] is False, 'saved source manifest')
    training = next(t for t in data['training'] if t['seed'] == 42)
    policy = next(p for p in data['runs'][1]['policies'] if p['policy'] == POLICY)
    require(len(training['events']) == 96 and len(policy['records']) == 128, 'fixed saved trajectory')
    for index in TARGETS:
        row = policy['records'][index]
        require(row['case']['episode_index'] == index and row['fallback'] and row['goal_reached'] is not None, 'declared four observed fallbacks')
    return training, policy


def replay(data, *, clock=time.perf_counter, started=None):
    training, policy = source_rows(data)  # Validate before constructing a learner.
    started = clock() if started is None else started
    observer = ReplayObserver(started, clock=clock)
    history = ActualHistory()
    result = {'schema': 'firstagi.ac0-forecast-gap-replay/v1', 'status': 'running',
              'input_raw_sha256': INPUT_SHA, 'seed': 42, 'policy': POLICY,
              'declared_targets': list(TARGETS), 'records': [], 'inspections': [], 'reset_deltas': [],
              'new_world_constructions': 0, 'new_world_actions': 0, 'new_task_outcomes': 0,
              'confirming_executed': False, 'AC0_gate_pass': False, 'independent_execution': False,
              'original_execution_completion': 'incomplete_raw_size_budget_not_upgraded'}
    past = []
    try:
        for index, e in enumerate(training['events']):
            event = TransitionEvent(**e)
            observer.begin({k: e[k] for k in ('channel_id', 'observation_id', 'available_operations')})
            observer.complete(event)
            history.ingest(e, admitted=True)
            past.append({'stage': 'training', 'event_index': index, 'event': e, 'admitted': True})
        observer.system.reset_context()
        require(observer.system.engine.step_count == 240, 'training replay token count')
        observer.capture = True
        for old in policy['records']:
            observer.check()
            index = old['case']['episode_index']
            observer.episode = index
            seal, e = old['pre_outcome'], old['event']
            view = seal['public_view']
            before_candidates = dict(observer.system.generalizer._candidates)
            chain_before = list(observer.system.generalizer._current_chain)
            # begin calls the existing reset_context (which may finalize a candidate).
            observer.begin(view, recall_policy='exact_learned_prefix')
            result['reset_deltas'].append({'episode_index': index,
                'current_chain_before_reset': chain_before,
                'candidate_deltas_before_cue': candidate_delta(before_candidates, observer.last_candidates_before_token)})
            raw = FrozenGoalPredictor(observer).query(view)
            require(semantics(raw['forecasts']) == semantics(seal['raw_query']['forecasts']) and
                    raw['operation_id'] == seal['raw_query']['operation_id'], 'raw replay semantics mismatch')
            variants, coverage = shadow_queries(view, raw['forecasts'], [], history)
            selected = variants[2]
            require(semantics(selected['forecasts']) == semantics(seal['selected_query']['forecasts']) and
                    selected['operation_id'] == seal['selected_query']['operation_id'], 'masked replay semantics mismatch')
            require(history.fingerprint() == seal['history_before_digest'], 'past own actual history mismatch')
            query_record = {'episode_index': index, 'raw_semantic_digest': digest(semantics(raw['forecasts'])),
                'selected_semantic_digest': digest(semantics(selected['forecasts'])),
                'raw_operation_id': raw['operation_id'], 'selected_operation_id': selected['operation_id'],
                'history_before_digest': history.fingerprint(), 'matched_saved': True}
            if index in TARGETS:
                eligible = [op for op in view['available_operations'] if
                    history.values.get((view['channel_id'], view['observation_id'], op)) == view['goal_observation_id']]
                require(len(eligible) == 1, 'one prior-actual goal key required')
                inspection = inspect_goal(observer, view, eligible[0], raw, selected)
                evidence = [p for p in past if p['admitted'] and p['event']['completion'] not in UNKNOWN and
                    (p['event']['channel_id'], p['event']['observation_id'], p['event']['chosen_operation']) ==
                    (view['channel_id'], view['observation_id'], eligible[0])]
                result['inspections'].append({'episode_index': index, 'public_view': view,
                    'history_before_digest': history.fingerprint(), 'coverage': coverage,
                    'native': inspection, 'past_executed_key_receipts': deepcopy(evidence),
                    'pre_current_feedback_sealed': True})
            # Only now consume the saved current actual event. It is never re-executed.
            admitted = old['feedback']['admitted']
            feedback = deliver_feedback(observer, TransitionEvent(**e), admitted=admitted)
            history.ingest(e, admitted=admitted)
            require(history.fingerprint() == old['feedback']['history_after_digest'], 'saved history update mismatch')
            expected_tokens = old['feedback']['native']['tokens']
            signature = lambda rows: [(t['role'], t['core_step'], t['canonical_feature_id'], t['outcome']) for t in rows]
            require(signature(feedback['tokens']) == signature(expected_tokens), 'saved native token semantics mismatch')
            query_record.update(actual_receipt_id=[e['run_id'], e['event_id']], receipt_admitted=admitted,
                history_after_digest=history.fingerprint(), native_token_semantics_matched=True,
                unknown_withheld_guard=(feedback['native_unchanged'] if not admitted or e['completion'] in UNKNOWN else None))
            result['records'].append(query_record)
            past.append({'stage': 'evaluation', 'event_index': index, 'event': e, 'admitted': admitted})
        require(observer.system.engine.step_count == 508, 'complete replay token count')
        require([r['episode_index'] for r in result['inspections']] == list(TARGETS), 'four target inspections')
        result['token_trace'] = observer.token_trace
        result['classifications'] = dict(Counter(r['native']['classification'] for r in result['inspections']))
        result['status'] = 'saved_receipt_replay_complete_not_new_policy_run'
        observer.check()
    except Exception as error:
        result.update(status='incomplete', error=type(error).__name__ + ': ' + str(error), token_trace=observer.token_trace)
    result['core_tokens'] = observer.system.engine.step_count
    return result


def write_output(path, result, started, *, clock=time.perf_counter):
    ensure_fresh_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(result, separators=(',', ':')) + '\n').encode()
    with path.open('xb') as handle:
        handle.write(raw)
    sha = hashlib.sha256(raw).hexdigest()
    path.with_suffix(path.suffix + '.sha256').write_bytes((sha + '  ' + path.name + '\n').encode())
    elapsed = clock() - started
    receipt = {'raw_sha256': sha, 'raw_bytes': len(raw), 'elapsed_including_write': elapsed,
               'status': 'receipt_replay_complete' if result['status'] != 'incomplete' and len(raw) <= 2097152 and elapsed <= 60 else 'incomplete'}
    path.with_suffix(path.suffix + '.completion.json').write_bytes((json.dumps(receipt, indent=2) + '\n').encode())
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ensure_fresh_output(args.out)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip(), 'clean source required')
    started = time.perf_counter()
    raw = args.input.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == INPUT_SHA, 'pinned saved source bytes changed')
    result = replay(json.loads(raw), started=started)
    result.update(source_commit=commit, source_dirty=False, python=sys.version, platform=platform.platform())
    receipt = write_output(args.out, result, started)
    print(json.dumps({'completion': receipt, 'core_tokens': result['core_tokens'],
                      'classifications': result.get('classifications'), 'error': result.get('error')}, indent=2))


if __name__ == '__main__':
    main()
