#!/usr/bin/env python3
"""Replay the published rank-six forest example; no graph search or floats.

Source: Huh--Schroeter--Wang, Correlation bounds for fields and matroids,
Example 2 and Figure 1B, https://doi.org/10.4171/JEMS/1119.
Tang--Zhang, https://arxiv.org/html/2603.10738v1, Example 5.5 / Figure 3,
redraw the graph. Vertex labels below follow that redraw: A,B,P1,...,P5,Q;
e=AB and f=AQ. The leaf edge f is NOT a sixth two-edge A--B path.

This refutes the universal *fixed-rank* Rayleigh statement, already at all
weights 1. It says nothing against the all-ranks-mixed forest conjecture.
Run under openlabs-resource-guard. stdout is a deterministic certificate;
--check-certificate compares a stored certificate with a fresh enumeration.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path


VERTICES = ("A", "B", "P1", "P2", "P3", "P4", "P5", "Q")
EDGES = ((0, 1), (0, 7)) + tuple(
    edge for middle in range(2, 7) for edge in ((0, middle), (middle, 1))
)
RANK = 6
MAX_EDGES = 18


def _validate(vertex_count: int, edges: tuple, subset: tuple) -> None:
    if not 1 <= vertex_count <= 20 or len(edges) > MAX_EDGES:
        raise ValueError("This checker is restricted to small finite graphs")
    if any(len(edge) != 2 or any(not 0 <= v < vertex_count for v in edge)
           for edge in edges):
        raise ValueError("Invalid graph endpoint")
    if len(set(subset)) != len(subset) or any(not 0 <= i < len(edges) for i in subset):
        raise ValueError("Invalid selected edge indices")


def forest_union_find(vertex_count: int, edges: tuple, subset: tuple) -> bool:
    """Reject an edge precisely when its endpoints are already connected."""
    _validate(vertex_count, edges, subset)
    parents = list(range(vertex_count))

    def find(v: int) -> int:
        while parents[v] != v:
            v = parents[v]
        return v

    for i in subset:
        left, right = (find(v) for v in edges[i])
        if left == right:
            return False
        parents[left] = right
    return True


def forest_component_count(vertex_count: int, edges: tuple, subset: tuple) -> bool:
    """Independent test: undirected graph is acyclic iff m=n-components.

    Uses adjacency traversal, not disjoint-set union. The edge count retains
    multiplicities, so the equality also rejects loops and parallel cycles.
    Isolated vertices are counted, including the leaf Q when f is absent.
    """
    _validate(vertex_count, edges, subset)
    adjacency = [set() for _ in range(vertex_count)]
    for i in subset:
        left, right = edges[i]
        adjacency[left].add(right)
        adjacency[right].add(left)
    unseen = set(range(vertex_count))
    components = 0
    while unseen:
        components += 1
        stack = [unseen.pop()]
        while stack:
            for other in adjacency[stack.pop()]:
                if other in unseen:
                    unseen.remove(other)
                    stack.append(other)
    return len(subset) == vertex_count - components


def make_certificate() -> dict:
    """Enumerate only C(12,6)=924 subsets of the single published graph."""
    counts = {"00": 0, "01": 0, "10": 0, "11": 0}
    valid_masks = []
    examined = 0
    for subset in itertools.combinations(range(len(EDGES)), RANK):
        examined += 1
        union_find = forest_union_find(len(VERTICES), EDGES, subset)
        component_count = forest_component_count(len(VERTICES), EDGES, subset)
        if union_find != component_count:
            raise RuntimeError(f"Independent forest tests disagree: {subset}")
        if union_find:
            counts[f"{int(0 in subset)}{int(1 in subset)}"] += 1
            valid_masks.append(sum(1 << i for i in subset))
    valid_masks.sort()
    total = sum(counts.values())
    marginal_e = counts["10"] + counts["11"]
    marginal_f = counts["01"] + counts["11"]
    joint = counts["11"]
    covariance_numerator = total * joint - marginal_e * marginal_f
    # Compact, deterministic commitment to the entire enumerated support.
    masks_bytes = json.dumps(valid_masks, separators=(",", ":")).encode("ascii")
    return {
        "schema_version": 1,
        "certificate_type": "exact_published_counterexample_replay",
        "graph": {
            "vertices": list(VERTICES),
            "edges_in_mask_bit_order": [[VERTICES[u], VERTICES[v]] for u, v in EDGES],
            "distinguished_edge_indices": {"e": 0, "f": 1},
            "weights_in_edge_order": [1] * len(EDGES),
            "simple": True,
            "connected": True,
        },
        "sample_space": {
            "kind": "unrooted_spanning_forests_with_exact_edge_count",
            "edge_count": RANK,
            "component_count": len(VERTICES) - RANK,
            "root_multiplicity": False,
            "measure": "uniform_on_edge_subsets",
        },
        "enumeration": {
            "examined_subsets": examined,
            "forest_tests": ["union_find_cycle_detection", "edge_count_equals_vertices_minus_components"],
            "tests_agree_on_every_examined_subset": True,
            "accepted_subset_count": total,
            "sorted_subset_masks_json_sha256": hashlib.sha256(masks_bytes).hexdigest(),
            "mask_digest_serialization": "sorted integer masks; JSON separators comma/colon; ASCII; no newline",
        },
        "counts": {"total": total, "e_present": marginal_e, "f_present": marginal_f,
                   "both_present": joint, "pair_states_e_then_f": counts},
        "rayleigh_difference_at_all_ones": marginal_e * marginal_f - total * joint,
        "covariance_exact_unreduced": {"numerator": covariance_numerator, "denominator": total * total},
        "negative_correlation_violated": covariance_numerator > 0,
        "scope": "Counterexample to all-graph/all-rank weighted forest-layer Rayleigh only; not all-ranks-mixed forest Rayleigh",
    }


def verify_certificate(certificate: dict) -> bool:
    """Recompute every field of this fixed-graph protocol, trusting no counts.

    The graph, edge order, rank, weights and full support digest must match the
    published instance as well as the independent recomputation. JSON equality
    is type-sensitive (unlike Python's equality of True, 1 and 1.0).
    """
    if not isinstance(certificate, dict):
        return False
    try:
        received = json.dumps(certificate, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return False
    recomputed = json.dumps(make_certificate(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return received == recomputed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-certificate", type=Path)
    args = parser.parse_args()
    result = make_certificate()
    if args.check_certificate:
        if args.check_certificate.stat().st_size > 1_000_000:
            parser.error("Certificate exceeds the small-audit size bound")
        saved = json.loads(args.check_certificate.read_text(encoding="utf-8"))
        if not verify_certificate(saved):
            print("Certificate mismatch")
            return 1
        print("Certificate matches exact replay (924 subsets; two independent forest tests)")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
