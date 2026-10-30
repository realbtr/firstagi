"""Design guards and symbolic schedule only; no confirming task/world execution."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

import pytest

from experiments.diagnostics.ac0_online_protocol import ProtocolError, schedule_layout, validate_protocol

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def protocol():
    return json.loads((ROOT / 'experiments/protocols/ac0_online_feedback_v1.json').read_bytes())


def test_registered_budget_arithmetic(protocol):
    counts = validate_protocol(protocol)
    assert counts['evaluation_opportunities_total'] == 9216
    assert counts['all_world_actions_total'] == 9984
    assert counts['train_core_tokens_total'] == 1920
    assert counts['expected_core_tokens_total'] == 6368
    assert counts['validator_executes_task_or_model'] is False


def test_symbolic_schedule_balances_cases_unknowns_and_local_gate():
    # Development schedule only; no world, observations, outcomes or learner.
    rows = schedule_layout(1041)
    assert rows == schedule_layout(1041)
    assert rows != schedule_layout(1042)
    assert len(rows) == 128
    assert sum(r['scheduled_status'] is not None for r in rows) == 48
    for block in range(4):
        sub = [r for r in rows if r['block_index'] == block]
        assert Counter((r['channel_index'], r['initial_phase']) for r in sub) == {(0, 0): 8, (0, 1): 8, (1, 0): 8, (1, 1): 8}
        for channel in (0, 1):
            observed = [r for r in sub if r['channel_index'] == channel and r['scheduled_status'] is None]
            assert len(observed) == 10
            assert all(r['gated_outcome_admitted'] == (block != 1 or channel != 0) for r in observed)
    assert all(set(r['operation_order']) == {0, 1} for r in rows)
    assert all(r['random_slot'] in (0, 1) and r['fallback_slot'] in (0, 1) for r in rows)


@pytest.mark.parametrize('mutation', [
    lambda p: p['confirming_task_seeds'].__setitem__(0, 101),
    lambda p: p['confirming_task_seeds'].__setitem__(0, True),
    lambda p: p['policies'].remove('table_online'),
    lambda p: p['controller_boundary']['allowed_view_fields'].append('block_index'),
    lambda p: p['schedule'].__setitem__('withdraw_feedback_blocks', [1, 2]),
    lambda p: p['schedule'].__setitem__('learner_sees_block_phase_or_gate_before_action', True),
    lambda p: p['native_policy'].__setitem__('query_changes_model', True),
    lambda p: p['feedback_contract'].__setitem__('withheld_observed_receipt_is_unknown', True),
    lambda p: p['feedback_contract'].__setitem__('unknown_or_withheld_can_change_native_snapshot_in_feedback_delivery', True),
    lambda p: p['table_policy'].__setitem__('unknown_or_withheld_updates', True),
    lambda p: p['metrics'].__setitem__('full_AC0_or_twelve_link_gate_pass_allowed', True),
    lambda p: p['budgets'].__setitem__('max_all_core_tokens_total', 6000),
])
def test_design_rejects_information_seed_scope_and_budget_regressions(protocol, mutation):
    changed = deepcopy(protocol)
    mutation(changed)
    with pytest.raises(ProtocolError):
        validate_protocol(changed)
