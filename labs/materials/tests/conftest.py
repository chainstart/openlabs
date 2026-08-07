"""OpenLabs-specific separation of code tests from legacy repository evidence checks."""

from __future__ import annotations

import os

import pytest


LEGACY_EVIDENCE_TESTS = {
    "tests/test_dft_domain_queue.py::test_frozen_domain_supervisor_protocol_hashes_both_snapshot_sets",
    "tests/test_dft_numerical_queue.py::test_frozen_numerical_supervisor_protocol_hashes_and_conditional_branches",
    "tests/test_dft_numerical_queue.py::test_medium_io_resource_amendment_freezes_probes_without_changing_physics",
    "tests/test_final_queue.py::test_frozen_final_supervisor_declares_existing_immutable_inputs",
    "tests/test_finetune.py::test_repository_contingency_protocol_locks_disjoint_templates_and_sources",
    "tests/test_finetune.py::test_contingency_queue_closes_without_training_after_universal_pass",
    "tests/test_literature_audit.py::test_current_llzto_novelty_audit_preserves_narrow_claim_boundary",
    "tests/test_research_final_queue.py::test_repository_final_protocol_freezes_one_branch_outcome_aware_dossier",
    "tests/test_research_final_queue.py::test_universal_derivation_has_twelve_outputs_and_negative_result_semantics",
    "tests/test_source_equivalence.py::test_committed_source_equivalence_certificate_is_hash_bound_and_exact",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip checks whose immutable payloads intentionally live outside the code repo."""

    if os.environ.get("OPENLABS_RUN_MATFACTORY_LEGACY_EVIDENCE") == "1":
        return
    marker = pytest.mark.skip(
        reason=(
            "requires the external legacy matfactory evidence tree and its historical lock; "
            "set OPENLABS_RUN_MATFACTORY_LEGACY_EVIDENCE=1 after hydrating it"
        )
    )
    for item in items:
        if item.nodeid.split("[")[0] in LEGACY_EVIDENCE_TESTS:
            item.add_marker(marker)
