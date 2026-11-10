"""Independent exact-arithmetic witness; does not import or execute pymdp."""

from fractions import Fraction as F
from itertools import product
import json


STATES = tuple(product((0, 1), repeat=2))


def independent(px, py):
    return {
        (x, y): (px if x else 1 - px) * (py if y else 1 - py)
        for x, y in STATES
    }


def marginals(joint):
    return tuple(sum(p for s, p in joint.items() if s[f] == 1) for f in (0, 1))


def propagate(joint, transition):
    result = dict.fromkeys(STATES, F(0))
    for state, probability in joint.items():
        result[transition(*state)] += probability
    assert sum(result.values()) == 1
    return result


def coupled(x, y):
    return x, x ^ y


def swap(x, y):
    return y, x


def main():
    # The input to each step is approximated by the product of its marginals.
    initial = independent(F(1, 2), F(0))
    exact_1 = propagate(initial, coupled)
    projected_1 = independent(*marginals(exact_1))
    exact_2 = propagate(exact_1, coupled)
    projected_2 = propagate(projected_1, coupled)
    assert marginals(exact_1) == (F(1, 2), F(1, 2))
    assert exact_1[(0, 0)] == exact_1[(1, 1)] == F(1, 2)
    assert marginals(exact_2) == (F(1, 2), F(0))
    assert marginals(projected_2) == (F(1, 2), F(1, 2))
    # Same one-time marginals, different next-time marginal: marginal-only
    # input cannot recover the answer for every possible correlated joint.
    assert marginals(exact_1) == marginals(projected_1)
    assert marginals(exact_2) != marginals(projected_2)

    grid = (F(0), F(1, 2), F(1))
    for px, py in product(grid, repeat=2):
        joint = independent(px, py)
        # One step from a product prior is exact despite two parents for Y.
        y_next = px * (1 - py) + (1 - px) * py
        assert marginals(propagate(joint, coupled)) == (px, y_next)
        # A non-identity dependency mapping need not destroy independence.
        approx = joint
        for _ in range(4):
            joint = propagate(joint, swap)
            approx = independent(*marginals(propagate(approx, swap)))
            assert joint == approx

    print(json.dumps({
        "kind": "independent_math_witness_not_pymdp_execution",
        "one_step_product_prior_cases": 9,
        "swap_control_cases": 9,
        "swap_control_steps_each": 4,
        "step_1_exact_P_Y1": str(marginals(exact_1)[1]),
        "step_2_exact_P_Y1": str(marginals(exact_2)[1]),
        "step_2_product_projection_P_Y1": str(marginals(projected_2)[1]),
        "step_2_absolute_error": str(abs(marginals(exact_2)[1] - marginals(projected_2)[1])),
    }, indent=2))


if __name__ == "__main__":
    main()
