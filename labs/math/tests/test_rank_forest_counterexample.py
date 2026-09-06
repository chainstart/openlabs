"""Regression checks for the single published fixed-rank counterexample."""

import copy
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "check_rank_forest_counterexample.py"
SPEC = importlib.util.spec_from_file_location("rank_forest_checker", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def test_published_counts_replayed_exactly():
    certificate = CHECKER.make_certificate()
    assert certificate["enumeration"]["examined_subsets"] == 924
    assert certificate["enumeration"]["tests_agree_on_every_examined_subset"]
    assert certificate["counts"] == {
        "total": 384, "e_present": 112, "f_present": 272, "both_present": 80,
        "pair_states_e_then_f": {"00": 80, "01": 192, "10": 32, "11": 80},
    }
    assert certificate["rayleigh_difference_at_all_ones"] == -256
    assert certificate["covariance_exact_unreduced"] == {"numerator": 256, "denominator": 147456}
    assert certificate["negative_correlation_violated"]
    assert certificate["sample_space"]["component_count"] == 2
    assert certificate["sample_space"]["root_multiplicity"] is False


@pytest.mark.parametrize("method", [CHECKER.forest_union_find, CHECKER.forest_component_count])
@pytest.mark.parametrize("n,edges,subset,expected", [
    (3, ((0, 1), (1, 2), (2, 0)), (), True),
    (3, ((0, 1), (1, 2), (2, 0)), (0, 1), True),
    (3, ((0, 1), (1, 2), (2, 0)), (0, 1, 2), False),
    (3, ((0, 1),), (0,), True),  # An isolated vertex still counts.
    (2, ((0, 1), (0, 1)), (0, 1), False),
    (1, ((0, 0),), (0,), False),
])
def test_independent_forest_predicates(method, n, edges, subset, expected):
    assert method(n, edges, subset) is expected


@pytest.mark.parametrize("method", [CHECKER.forest_union_find, CHECKER.forest_component_count])
def test_rejects_large_or_malformed_inputs(method):
    with pytest.raises(ValueError):
        method(2, ((0, 1),) * 19, ())
    with pytest.raises(ValueError):
        method(2, ((0, 2),), (0,))
    with pytest.raises(ValueError):
        method(2, ((0, 1),), (0, 0))


def test_certificate_is_deterministic():
    assert CHECKER.make_certificate() == CHECKER.make_certificate()


def test_verifier_recomputes_and_rejects_mutated_protocol_fields():
    certificate = CHECKER.make_certificate()
    assert CHECKER.verify_certificate(certificate)
    assert not CHECKER.verify_certificate(None)
    for path, value in [
        (("counts", "both_present"), 79),
        (("counts", "total"), 384.0),
        (("sample_space", "edge_count"), 7),
        (("graph", "edges_in_mask_bit_order"), [["A", "B"]]),
        (("graph", "weights_in_edge_order"), [2] * 12),
        (("graph", "distinguished_edge_indices"), {"e": 1, "f": 0}),
        (("enumeration", "sorted_subset_masks_json_sha256"), "0" * 64),
        (("enumeration", "tests_agree_on_every_examined_subset"), False),
    ]:
        changed = copy.deepcopy(certificate)
        changed[path[0]][path[1]] = value
        assert not CHECKER.verify_certificate(changed), path
