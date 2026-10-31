"""Structural preflight for an unexecuted online AC0 protocol; no learner/world."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random

DEFAULT = Path(__file__).resolve().parents[2] / 'experiments/protocols/ac0_online_feedback_v1.json'
POLICIES = (
    'prefix_online', 'prefix_feedback_gate', 'prefix_frozen',
    'table_online', 'table_feedback_gate', 'table_frozen',
    'fixed_first', 'random_uniform', 'oracle_upper_bound',
)
PUBLIC_FIELDS = {'channel_id', 'observation_id', 'available_operations', 'goal_observation_id'}
UNKNOWN_REPEATS = {1: 'interrupted', 3: 'unavailable', 5: 'cancelled'}


class ProtocolError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ProtocolError(message)


def schedule_layout(schedule_seed):
    """Only evaluator case indices; never construct task IDs, answers or outcomes."""
    rng = random.Random(schedule_seed)
    random_policy = random.Random(schedule_seed + 20000)
    fallback = random.Random(schedule_seed + 30000)
    records = []
    for block in range(4):
        for repeat in range(8):
            pairs = [(0, 0), (0, 1), (1, 0), (1, 1)]
            rng.shuffle(pairs)
            for channel, phase in pairs:
                order = [0, 1]
                rng.shuffle(order)
                records.append({
                    'episode_index': len(records), 'block_index': block,
                    'channel_index': channel, 'initial_phase': phase,
                    'operation_order': order,
                    'random_slot': random_policy.randrange(2),
                    'fallback_slot': fallback.randrange(2),
                    'scheduled_status': UNKNOWN_REPEATS.get(repeat),
                    'gated_outcome_admitted': not (block == 1 and channel == 0),
                })
    return records


def validate_protocol(p):
    """Validate this declared design, not runtime behavior or scientific acceptance."""
    require(p['schema'] == 'firstagi.ac0-online-feedback-protocol/v1', 'schema')
    require(p['status'] == 'registered_design_implementation_pending_not_executed', 'status')
    seeds = p['confirming_task_seeds']
    require(all(type(s) is int for s in seeds), 'integer task seeds')
    require(seeds == list(range(201, 209)), 'reserved fresh task pool 201-208')
    require(p['episode_schedule_seeds'] == [s + 1000 for s in seeds], 'paired schedule pool')
    require(p['development_task_seeds'] == [41, 42], 'development-only pool')
    require(not set(seeds) & set(p['previous_consumed_confirming_task_seeds']), 'consumed pool overlap')
    require(tuple(p['policies']) == POLICIES, 'matched adaptive and frozen comparators')
    require(set(p['controller_boundary']['allowed_view_fields']) == PUBLIC_FIELDS, 'controller information boundary')
    s = p['schedule']
    require(s['blocks'] == ['stable', 'changed_feedback_withdrawal', 'feedback_restored', 'late_recovery'], 'block order')
    require(s['repeats_per_block'] == 8 and s['actions_per_episode'] == 1, 'episode budget')
    require(s['channel_phase_pairs'] == [[0, 0], [0, 1], [1, 0], [1, 1]], 'paired cases')
    require(s['unknown_repeat_indices'] == {str(k): v for k, v in UNKNOWN_REPEATS.items()}, 'balanced unknown cases')
    require(s['flip_channel_index'] == 0 and s['flip_from_block'] == 1, 'local rule change')
    require(s['withdraw_feedback_channel_index'] == 0 and s['withdraw_feedback_blocks'] == [1], 'local withdrawal')
    require(s['withdrawal_applies_to'] == ['prefix_feedback_gate', 'table_feedback_gate'], 'paired withdrawal comparator')
    require(s['learner_sees_block_phase_or_gate_before_action'] is False, 'evaluator leak')
    require(s['random_policy_rng_offset'] == 20000 and s['fallback_rng_offset'] == 30000, 'independent policy streams')
    n = p['native_policy']
    require(n['query_changes_model'] is False and n['direct_Gen_confirm_refute_or_counter_assignment'] is False, 'native update route')
    require(n['tie_break_with_significance_or_UUID'] is False, 'preserve old conflict readout')
    require(n['fallback_is_learned_action'] is False and n['frozen_arm_ingests_evaluation_tokens'] is False, 'fallback/frozen scope')
    t = p['training']
    require(t['attempts_per_seed'] == 96 and t['unknown_modulo'] == 12, 'training budget')
    require(t['unknown_slots'] == {'3': 'interrupted', '5': 'unavailable', '7': 'cancelled'}, 'training unknowns')
    require(t['extend_training_for_coverage'] is False, 'no training extension')
    f = p['feedback_contract']
    require(f['withheld_observed_receipt_is_unknown'] is False, 'withheld is not an unknown outcome')
    require(f['unknown_or_withheld_can_change_native_snapshot_in_feedback_delivery'] is False, 'unknown feedback mutation')
    require(f['task_success_is_Gen_confirmation'] is False, 'task truth is not native support')
    require(p['table_policy']['unknown_or_withheld_updates'] is False, 'table information parity')
    m = p['metrics']
    require(m['full_AC0_or_twelve_link_gate_pass_allowed'] is False, 'bounded interpretation')
    require(m['require_beating_adaptive_table'] is False, 'do not force architectural advantage')
    require(m['recovery_cessation_and_trace_verdicts_separate'] is True, 'separate endpoints')
    require(m['late_changed_channel_goal_min'] == 0.8 and m['late_stable_channel_goal_min'] == 0.8, 'quality thresholds')
    require(m['late_advantage_over_each_prefix_frozen_and_random_min'] == 0.15, 'paired quality threshold')
    require(m['positive_seed_differences_min'] == 6, 'paired seed threshold')
    require(m['withdrawal_changed_channel_advantage_min'] == 0.15 and m['withdrawal_stable_channel_absolute_gap_max'] == 0.1, 'local causal thresholds')
    require(m['late_gate_restored_changed_goal_min'] == 0.8 and m['late_stale_nonfallback_choice_fraction_max'] == 0.2, 'recovery/cessation thresholds')
    require(m['named_Gen_observed_negative_trace_min'] == 1 and m['named_Gen_update_then_correct_nonfallback_reuse_trace_min'] == 1, 'named trace thresholds')
    require(m['all_unknown_withheld_duplicate_query_integrity_guards_required'] is True, 'integrity guards')
    seed_count, episodes, policies = len(seeds), 4 * 8 * 4, len(POLICIES)
    train_actions = seed_count * 96
    train_tokens = seed_count * (96 + 72 * 2)
    # Two online native arms: 128 cues each, 80/70 admitted actual outcomes.
    expected_native_tokens = train_tokens + seed_count * (2 * episodes + 2 * (80 + 70))
    derived = {
        'task_seeds': seed_count, 'policies': policies,
        'episodes_per_policy_seed': episodes,
        'observed_per_policy_seed': 80, 'unknown_per_policy_seed': 48,
        'observed_per_block_channel_seed': 10,
        'train_actions_total': train_actions, 'train_core_tokens_total': train_tokens,
        'evaluation_opportunities_total': seed_count * policies * episodes,
        'all_world_actions_total': train_actions + seed_count * policies * episodes,
        'expected_core_tokens_total': expected_native_tokens,
        'validator_executes_task_or_model': False,
    }
    b = p['budgets']
    for name, minimum in (
        ('max_train_actions_total', train_actions),
        ('max_train_core_tokens_total', train_tokens),
        ('max_evaluation_opportunities_total', seed_count * policies * episodes),
        ('max_evaluation_actions_total', seed_count * policies * episodes),
        ('max_all_world_actions_total', derived['all_world_actions_total']),
        ('max_all_core_tokens_total', expected_native_tokens),
    ):
        require(type(b[name]) is int and b[name] >= minimum, 'insufficient ' + name)
    require(b['max_wall_seconds_complete_run'] == 300, 'complete wall budget')
    require(b['equal_compute_claim_allowed'] is False, 'equal opportunity is not equal compute')
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, default=DEFAULT)
    args = parser.parse_args()
    raw = args.protocol.read_bytes()
    result = validate_protocol(json.loads(raw))
    print(json.dumps({'status': 'structural_validation_only_not_experiment',
                      'protocol_sha256': hashlib.sha256(raw).hexdigest(), **result}, indent=2))


if __name__ == '__main__':
    main()
