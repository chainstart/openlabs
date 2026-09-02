from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from openlabs.contracts import atomic_write_json
from openlabs.db import FactoryDB

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "labs"
    / "math"
    / "protocols"
    / "research_state_machine.py"
)
AMRA_SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "labs"
    / "math"
    / "skills"
    / "amra-research-loop"
    / "scripts"
)
sys.path.insert(0, str(AMRA_SCRIPTS))

import loop_core as amra_loop_core  # noqa: E402
from loop_core import (  # noqa: E402
    advance_campaign,
    init_campaign,
    prepare_review_manifest,
    read_json as read_amra_json,
    slugify,
    validate_campaign,
    validate_campaign_integrity,
    write_json as write_amra_json,
)

sys.path.insert(0, str(SCRIPT.parent))
import research_state_machine as generic_state_machine  # noqa: E402


def test_amra_loader_ignores_wrong_sys_path_module(tmp_path, monkeypatch) -> None:
    fake = SimpleNamespace(__file__=str(tmp_path / "loop_core.py"))
    monkeypatch.setitem(sys.modules, "loop_core", fake)
    generic_state_machine._amra_api.cache_clear()
    try:
        load_campaign, _, _, _ = generic_state_machine._amra_api()
        expected = (AMRA_SCRIPTS / "loop_core.py").resolve()
        assert Path(load_campaign.__code__.co_filename).resolve() == expected
    finally:
        generic_state_machine._amra_api.cache_clear()


def _run(
    *args: str,
    stdin: dict | None = None,
    validation_context: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("OPENLABS_PROTOCOL_VALIDATION_CONTEXT", None)
    if validation_context is not None:
        environment["OPENLABS_PROTOCOL_VALIDATION_CONTEXT"] = json.dumps(
            validation_context
        )
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=(json.dumps(stdin) if stdin is not None else None),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def _project(tmp_path: Path, *, binding: dict | None = None) -> tuple[Path, Path]:
    project_path = tmp_path / "project.json"
    state_path = tmp_path / "workstreams" / "candidate-one" / "research_state.json"
    atomic_write_json(
        tmp_path / "research_policy.json",
        binding
        or {
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {"profile": "open-problem-closure-v1"},
        },
    )
    atomic_write_json(
        project_path,
        {
            "schema_version": "openlabs.project.v1",
            "project_id": "policy-test",
            "domain": "math",
            "status": "active",
            "objective": "Test a configured mathematics research policy.",
            "protocol": {
                "id": "math-state-machine",
                "primary_skill": "math-research-state-machine",
            },
            "domain_config": {"path": "research_policy.json"},
            "workstreams": [
                {
                    "workstream_id": "candidate-one",
                    "state_path": "workstreams/candidate-one/research_state.json",
                    "startup": "active",
                }
            ],
        },
    )
    initialized = _run(
        "init",
        "--project",
        str(project_path),
        "--workstream",
        str(state_path),
        "--workstream-id",
        "candidate-one",
    )
    assert initialized.returncode == 0, initialized.stderr
    return project_path, state_path


def _context(*, task_count: int = 0, agent_seconds: float = 0) -> dict:
    return {
        "schema_version": "openlabs.protocol_hook_context.v1",
        "event": "continuation",
        "campaign": {
            "campaign_id": "candidate-one",
            "domain": "math",
            "project_id": "policy-test",
            "workstream_id": "candidate-one",
            "agent_seconds_used": agent_seconds,
            "max_agent_seconds": 200000,
            "production_epoch": 1,
        },
        "latest_task": None,
        "latest_result": None,
        "routing_usage": {
            "protocol_hook:open-problem-closure-v1:admission_probe": {
                "task_count": task_count,
                "agent_seconds": agent_seconds,
            }
        },
        "project_workstreams": [],
    }


def _attempt_context(project: Path, state: Path) -> dict:
    return {
        "schema_version": "openlabs.protocol_validation_context.v1",
        "event": "attempt_commit",
        "task": {
            "task_id": "actual-task",
            "attempt_id": "attempt-one",
            "agent_role": "researcher",
            "session_mode": "fresh",
            "routing_reason": (
                "protocol_hook:open-problem-closure-v1:admission_probe"
            ),
        },
        "canonical": {
            "project_config": str(project),
            "workstream_state": str(state),
        },
    }


def _amra_evidence(campaign: Path, relative: str, content: str) -> dict[str, str]:
    path = campaign / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": relative, "sha256": sha256(path.read_bytes()).hexdigest()}


def _source_authority_receipt(
    root: Path,
    *,
    campaign_id: str,
    problem_id: str,
    title: str,
    statement: str,
    source: str,
) -> Path:
    bundle = root / "source-selection" / slugify(campaign_id)
    bundle.mkdir(parents=True)
    source_artifact = bundle / "primary-source.html"
    open_status_quote = "Open Problem."
    source_artifact.write_text(
        f"<p>{statement}</p><p>{open_status_quote}</p>\n",
        encoding="utf-8",
    )
    status_artifact = bundle / "open-status.md"
    status_artifact.write_text(
        "The cited primary source identifies this exact statement as open.\n",
        encoding="utf-8",
    )
    novelty_artifact = bundle / "duplicate-search.md"
    novelty_artifact.write_text(
        "No published closure of the exact statement was found.\n",
        encoding="utf-8",
    )
    score_vector = {
        "novelty": 20,
        "significance": 20,
        "closure": 15,
        "auditability": 10,
        "generality": 8,
        "venue_fit": 4,
        "total": 77,
    }
    target_id = slugify(campaign_id)
    candidates = [
        {
            "target_id": target_id,
            "problem_id": problem_id,
            "title": title,
            "source_original_statement": statement,
            "frozen_target_statement": statement,
            "target_relation": "exact",
            "source": source,
            "public_status": "open_conjecture",
            "source_locator": "Problem 1.1",
            "closest_published_result": "A finite-range special case only.",
            "score_vector": score_vector,
            "blocking_novelty_risk": False,
        }
    ]
    candidates.extend(
        {
            "target_id": f"comparison-{index}",
            "problem_id": f"comparison-{index}",
            "title": f"Comparison target {index}",
            "source_original_statement": f"Comparison statement {index}.",
            "frozen_target_statement": f"Comparison statement {index}.",
            "target_relation": "exact",
            "source": f"https://example.test/comparison-{index}",
            "public_status": "open_problem",
            "source_locator": f"Problem {index + 1}.1",
            "closest_published_result": f"Closest comparison result {index}.",
            "score_vector": score_vector,
            "blocking_novelty_risk": False,
        }
        for index in range(1, 4)
    )
    cards = bundle / "target-cards.json"
    write_amra_json(cards, {"candidates": candidates})
    receipt = bundle / "selection.json"
    write_amra_json(
        receipt,
        {
            "schema": "openlabs.math_target_selection.v1",
            "target_id": target_id,
            "problem_id": problem_id,
            "title": title,
            "source_original_statement": statement,
            "frozen_target_statement": statement,
            "target_relation": "exact",
            "source": source,
            "source_kind": "primary",
            "source_locator": "Problem 1.1",
            "public_status": "open_conjecture",
            "source_statement_quote": statement,
            "open_status_quote": open_status_quote,
            "status_checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "score_vector": score_vector,
            "selection_gate_snapshot": {
                "minimum_total": 70,
                "minimum_novelty": 15,
                "minimum_significance": 15,
                "minimum_closure": 10,
            },
            "blocking_novelty_risk": False,
            "closest_published_result": "A finite-range special case only.",
            "duplicate_search_checked_at": datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat(),
            "source_artifact": {
                "path": source_artifact.name,
                "sha256": sha256(source_artifact.read_bytes()).hexdigest(),
            },
            "status_evidence": [
                {
                    "path": status_artifact.name,
                    "sha256": sha256(status_artifact.read_bytes()).hexdigest(),
                }
            ],
            "novelty_evidence": [
                {
                    "path": novelty_artifact.name,
                    "sha256": sha256(novelty_artifact.read_bytes()).hexdigest(),
                }
            ],
            "target_cards": cards.name,
            "target_cards_sha256": sha256(cards.read_bytes()).hexdigest(),
        },
    )
    return receipt


def _control_plane_review(
    campaign: Path,
    *,
    campaign_state: dict,
    author_attempt_id: str,
    resolution_type: str,
    reconstruction: dict[str, str],
) -> dict[str, str]:
    data_root = next(parent for parent in campaign.parents if parent.name == "openlabs-data")
    database = data_root / "openlabs-database" / "live" / "factory.sqlite"
    factory = FactoryDB(database)
    factory.initialize()
    suffix = campaign_state["campaign_id"]
    control_campaign_id = f"control-{suffix}"
    author_task_id = f"author-{suffix}"
    reviewer_task_id = f"review-{suffix}"
    reviewer_attempt_id = f"review-attempt-{suffix}"
    result_path = data_root / "ledger" / "results" / f"{reviewer_task_id}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    review_manifest_digest = sha256(
        (campaign / "audit" / "review-manifest.json").read_bytes()
    ).hexdigest()
    write_amra_json(
        result_path,
        {
            "schema_version": "openlabs.result_bundle.v1",
            "task_id": reviewer_task_id,
            "campaign_id": control_campaign_id,
            "domain": "math",
            "status": "completed",
            "summary": "The independent AMRA reconstruction passed.",
            "artifacts": [
                {
                    "artifact_id": "amra-audit-reconstruction",
                    "uri": (campaign / reconstruction["path"]).as_uri(),
                    "sha256": reconstruction["sha256"],
                    "kind": "audit",
                }
            ],
            "amra_review_schema_version": "openlabs.amra_review.v1",
            "amra_audit_outcome": "passed",
            "amra_success_condition": "original_problem_closed",
            "amra_campaign_id": campaign_state["campaign_id"],
            "amra_statement_identity": campaign_state["statement_identity"],
            "amra_author_attempt_id": author_attempt_id,
            "amra_resolution_type": resolution_type,
            "amra_review_manifest_sha256": review_manifest_digest,
            "claims": [
                {
                    "claim_id": "amra-original-problem-closed",
                    "status": "verified",
                    "evidence": ["amra-audit-reconstruction"],
                }
            ],
        },
    )
    result_digest = sha256(result_path.read_bytes()).hexdigest()
    receipt_path = (
        data_root
        / "ledger"
        / "receipts"
        / f"{reviewer_task_id}-{reviewer_attempt_id}.json"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = {
        "duration_seconds": 1.0,
        "exit_code": 0,
        "heartbeat_lost": False,
    }
    write_amra_json(
        receipt_path,
        {
            "schema_version": "openlabs.result_receipt.v2",
            "task_id": reviewer_task_id,
            "attempt_id": reviewer_attempt_id,
            "campaign_id": control_campaign_id,
            "domain": "math",
            "agent_role": "reviewer",
            "result_path": str(result_path),
            "sha256": result_digest,
            "runtime": runtime,
        },
    )
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    bundle_runtime = {
        **runtime,
        "hooks": {
            "schema_version": "openlabs.hook_runtime.v1",
            "stop_passed": True,
            "session_start_count": 1,
        },
    }
    with factory.connect() as connection:
        connection.execute(
            "INSERT INTO campaigns(campaign_id, domain, title, created_at, updated_at) "
            "VALUES (?, 'math', ?, ?, ?)",
            (control_campaign_id, control_campaign_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO tasks(
                task_id, campaign_id, domain, task_type, objective, agent_role,
                session_mode, status, created_at, updated_at
            ) VALUES (?, ?, 'math', 'research', 'Author the proof', 'researcher',
                      'resume', 'succeeded', ?, ?)
            """,
            (author_task_id, control_campaign_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO task_attempts(
                attempt_id, task_id, attempt_number, status, lease_owner,
                started_at, finished_at, created_at
            ) VALUES (?, ?, 1, 'succeeded', 'test-worker', ?, ?, ?)
            """,
            (author_attempt_id, author_task_id, now, now, now),
        )
        connection.execute(
            """
            INSERT INTO tasks(
                task_id, campaign_id, domain, task_type, objective, parent_task_id,
                agent_role, session_mode, status, result_path, result_sha256,
                created_at, updated_at
            ) VALUES (?, ?, 'math', 'review', 'Independently audit the proof', ?,
                      'reviewer', 'fresh', 'succeeded', ?, ?, ?, ?)
            """,
            (
                reviewer_task_id,
                control_campaign_id,
                author_task_id,
                str(result_path),
                result_digest,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO task_attempts(
                attempt_id, task_id, attempt_number, status, lease_owner,
                started_at, finished_at, result_path, result_sha256, runtime_json,
                created_at
            ) VALUES (?, ?, 1, 'succeeded', 'test-worker', ?, ?, ?, ?, ?, ?)
            """,
            (
                reviewer_attempt_id,
                reviewer_task_id,
                now,
                now,
                str(result_path),
                result_digest,
                json.dumps(runtime),
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO result_bundles(
                task_id, attempt_id, path, sha256, valid, gate_passed,
                blockers_json, runtime_json, ingested_at
            ) VALUES (?, ?, ?, ?, 1, 1, '[]', ?, ?)
            """,
            (
                reviewer_task_id,
                reviewer_attempt_id,
                str(result_path),
                result_digest,
                json.dumps(bundle_runtime),
                now,
            ),
        )
    return {
        "path": receipt_path.relative_to(data_root).as_posix(),
        "sha256": sha256(receipt_path.read_bytes()).hexdigest(),
    }


def _complete_exact_amra_campaign(
    workstream: Path, *, campaign_id: str, resolution_type: str
) -> str:
    root = workstream.parent
    problem_id = "open-problem-1"
    title = "Exact source problem closure"
    statement = "For every n, prove P(n)."
    source = "https://example.test/open-problem-1"
    authority = _source_authority_receipt(
        root,
        campaign_id=campaign_id,
        problem_id=problem_id,
        title=title,
        statement=statement,
        source=source,
    )
    campaign = init_campaign(
        root / "amra",
        campaign_id=campaign_id,
        problem_id=problem_id,
        title=title,
        source_original_statement=statement,
        frozen_target_statement=statement,
        target_relation="exact",
        source=source,
        source_authority_receipt=authority,
    )
    contract = read_amra_json(campaign / "closure_contract.json")
    contract.update(
        {
            "published_comparator": "The published frontier proves only a finite range.",
            "admissible_inputs": ["The declared unconditional base theorem"],
            "false_world_controls": [
                {
                    "model": "A planted object where global compatibility fails",
                    "expected_failure": "The proposed certificate rejects the object",
                }
            ],
            "non_cosmetic_consequence": "The exact public statement follows.",
        }
    )
    write_amra_json(campaign / "closure_contract.json", contract)
    advance_campaign(campaign, "obstruction_analysis")
    write_amra_json(
        campaign / "information_loss_map.json",
        {
            "inherited_methods": [
                {
                    "method": "fixed projection",
                    "loss_step": "average over fibers",
                    "lost_information": "fiber provenance",
                    "consequence": "global compatibility disappears",
                }
            ],
            "required_new_information": ["fiber provenance"],
        },
    )
    advance_campaign(campaign, "representation_search")
    families = ["potential", "algebraic", "spectral", "probabilistic"]
    representations = [
        {
            "id": f"R{index:03d}",
            "name": f"representation {index}",
            "family": families[(index - 1) % len(families)],
            "new_information": f"retained datum {index}",
            "first_test": f"adversarial model {index}",
        }
        for index in range(1, 9)
    ]
    mechanisms = [
        {
            "id": f"M{index:03d}",
            "representation_id": representations[(index - 1) % len(representations)][
                "id"
            ],
            "family": families[(index - 1) % len(families)],
            "decisive_claim": f"decisive claim {index}",
            "would_close": ["original_problem_closed"],
            "kill_test": f"kill test {index}",
            "status": "candidate",
        }
        for index in range(1, 11)
    ]
    write_amra_json(
        campaign / "representations.json", {"representations": representations}
    )
    write_amra_json(campaign / "mechanisms.json", {"mechanisms": mechanisms})
    advance_campaign(campaign, "mechanism_falsification")
    kill_tests = []
    for index, mechanism in enumerate(mechanisms, start=1):
        if index <= 8:
            mechanism["status"] = "killed"
            relative = f"evidence/kill-{index}.md"
            (campaign / relative).write_text("Decisive countermodel.\n", encoding="utf-8")
            kill_tests.append(
                {
                    "mechanism_id": mechanism["id"],
                    "test": f"test {index}",
                    "outcome": "killed",
                    "evidence": relative,
                }
            )
        else:
            mechanism["status"] = "surviving"
    write_amra_json(campaign / "mechanisms.json", {"mechanisms": mechanisms})
    write_amra_json(campaign / "kill_tests.json", {"tests": kill_tests})
    write_amra_json(
        campaign / "survivors.json",
        {
            "mechanism_ids": ["M009", "M010"],
            "selection_rationale": "Only these mechanisms survived every kill test.",
        },
    )
    advance_campaign(campaign, "survivor_deepening")
    lemma_evidence = _amra_evidence(
        campaign,
        "evidence/lemma-proof.md",
        "A complete proof of the exact decisive lemma.\n",
    )
    write_amra_json(
        campaign / "decisive_lemma.json",
        {
            "statement": "The global compatibility interface always holds.",
            "status": "proved",
            "exact_scope": "Every object satisfying the frozen inputs.",
            "unconditional_inputs": ["The declared unconditional base theorem"],
            "non_cosmetic_consequence": "The exact source statement follows.",
            "closes": ["original_problem_closed"],
            "evidence": [lemma_evidence],
            "dependency_gaps": [],
        },
    )
    advance_campaign(campaign, "independent_audit")
    reconstruction = _amra_evidence(
        campaign,
        "audit/reconstruction.md",
        "A fresh line-by-line reconstruction with hostile checks.\n",
    )
    state = read_amra_json(campaign / "campaign_state.json")
    author_attempt_id = f"author-attempt-{state['campaign_id']}"
    status_recheck = _amra_evidence(
        campaign,
        "evidence/promotion-open-status.md",
        "The primary source still lists the exact conjecture as open.\n",
    )
    write_amra_json(
        campaign / "decision.json",
        {
            "outcome": "promote",
            "success_condition": "original_problem_closed",
            "resolution_type": resolution_type,
            "open_status_recheck": {
                "public_status": "open_conjecture",
                "source_locator": "Problem 1.1",
                "status_checked_at": datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat(),
                "evidence": [status_recheck],
            },
            "reason": "The independent audit closes the exact source statement.",
            "evidence": [reconstruction],
        },
    )
    prepare_review_manifest(campaign, author_attempt_id)
    reviewer_receipt = _control_plane_review(
        campaign,
        campaign_state=state,
        author_attempt_id=author_attempt_id,
        resolution_type=resolution_type,
        reconstruction=reconstruction,
    )
    audit = read_amra_json(campaign / "audit.json")
    audit.update(
        {
            "independent_reconstruction": {
                "status": "passed",
                "auditor": "blind-reviewer-1",
                "author_attempt_id": author_attempt_id,
                "control_plane_receipt": reviewer_receipt,
                "evidence": [reconstruction],
            },
            "statement_match": "passed",
            "dependency_check": "passed",
            "novelty_check": "priority_uncertain",
            "hypothesis_check": "passed",
            "counterexample_check": "passed",
            "literature_check": "passed",
            "formalization_check": {
                "status": "not_feasible",
                "reason": (
                    "The imported analytic library is unavailable in the prover."
                ),
                "evidence": [],
            },
        }
    )
    write_amra_json(campaign / "audit.json", audit)
    advance_campaign(campaign, "promotion")
    assert validate_campaign(campaign) == []
    assert validate_campaign_integrity(campaign) == []
    return campaign.relative_to(root).as_posix()


def test_closure_profile_initializes_and_returns_a_bounded_admission_task(tmp_path) -> None:
    project, state = _project(tmp_path)

    validation = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--mode",
        "discovery",
    )
    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=_context(),
    )

    assert validation.returncode == 0, validation.stdout + validation.stderr
    payload = json.loads(decision.stdout)
    assert payload["decision"] == "continue"
    assert payload["routing_key"] == "open-problem-closure-v1:admission_probe"
    assert payload["action"]["runner"] == "balanced"
    assert payload["action"]["wall_seconds"] == 1800
    assert payload["action"]["resources"]["memory_mib"] == 4096


def test_closure_observations_reject_arbitrary_evidence_text(tmp_path) -> None:
    for kind in ("original_problem_closed", "counterexample_closed"):
        case = tmp_path / kind
        case.mkdir()
        project, state = _project(case)
        evidence = state.parent / "evidence" / "claimed-proof.md"
        evidence.parent.mkdir()
        evidence.write_text("This text alone claims a complete proof.\n", encoding="utf-8")

        rejected = _run(
            "observe",
            "--project",
            str(project),
            "--workstream",
            str(state),
            "--observation-id",
            f"claim-{kind}",
            "--kind",
            kind,
            "--verdict",
            "accepted",
            "--actor-role",
            "researcher",
            "--source-task-id",
            "deep-proof-task",
            "--summary",
            "Claim closure from an arbitrary text file.",
            "--evidence",
            "evidence/claimed-proof.md",
        )

        assert rejected.returncode == 2
        assert "requires --amra-campaign and --closure-receipt" in rejected.stderr
        forged = json.loads(state.read_text(encoding="utf-8"))
        assert forged["observations"] == []
        forged["observations"].append(
            {
                "observation_id": f"forged-{kind}",
                "kind": kind,
                "verdict": "accepted",
                "actor_role": "researcher",
                "source_task_id": "deep-proof-task",
                "stage": "admission_probe",
                "summary": "Directly append the unsupported closure claim.",
                "evidence": ["evidence/claimed-proof.md"],
                "created_at": forged["created_at"],
            }
        )
        atomic_write_json(state, forged)
        validated = _run(
            "validate",
            "--project",
            str(project),
            "--workstream",
            str(state),
            "--mode",
            "commit",
        )
        assert validated.returncode == 1
        assert "requires a safe JSON closure_receipt" in validated.stdout


def test_closure_observations_require_full_exact_amra_and_hash_receipt(
    tmp_path, monkeypatch
) -> None:
    project_root = (
        tmp_path / "openlabs-data" / "workspaces" / "math" / "closure-gate"
    )
    project_root.mkdir(parents=True)
    monkeypatch.setattr(
        amra_loop_core,
        "CONTROL_PLANE_DATA_ROOT",
        tmp_path / "openlabs-data",
    )
    project, state = _project(project_root)
    proof_campaign = _complete_exact_amra_campaign(
        state, campaign_id="Exact Proof Closure", resolution_type="proof"
    )
    counterexample_campaign = _complete_exact_amra_campaign(
        state,
        campaign_id="Exact Counterexample Closure",
        resolution_type="counterexample",
    )

    campaigns = {
        "original_problem_closed": proof_campaign,
        "counterexample_closed": counterexample_campaign,
    }

    def observe(
        *, observation_id: str, kind: str, task_id: str, campaign: str, receipt: str
    ) -> int:
        return generic_state_machine._observe_command(
            SimpleNamespace(
                project=project,
                workstream=state,
                observation_id=observation_id,
                kind=kind,
                verdict="accepted",
                actor_role="researcher",
                source_task_id=task_id,
                summary=(
                    "Bind the closure claim to the independently audited AMRA promotion."
                ),
                evidence=[],
                amra_campaign=campaign,
                closure_receipt=receipt,
            )
        )

    for kind, campaign_reference in campaigns.items():
        observed = observe(
            observation_id=f"claim-{kind}",
            kind=kind,
            task_id=f"task-{kind}",
            campaign=campaign_reference,
            receipt=f"evidence/{kind}-receipt.json",
        )
        assert observed == 0

    with pytest.raises(
        generic_state_machine.StateMachineError,
        match="resolution_type=counterexample",
    ):
        observe(
            observation_id="counterexample-from-proof",
            kind="counterexample_closed",
            task_id="wrong-polarity-task",
            campaign=proof_campaign,
            receipt="evidence/wrong-polarity-receipt.json",
        )

    current = json.loads(state.read_text(encoding="utf-8"))
    assert len(current["verification_receipts"]) == 2
    for observation in current["observations"]:
        receipt = state.parent / observation["closure_receipt"]
        assert receipt.is_file()
        assert sha256(receipt.read_bytes()).hexdigest() == observation[
            "closure_receipt_sha256"
        ]
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        assert payload["schema_version"] == (
            "openlabs.amra_closure_observation_receipt.v1"
        )
        assert payload["statement_identity"]["target_relation"] == "exact"
        assert payload["artifact_sha256"]["campaign_state.json"]
        manifest_path = payload["reviewer_authority"]["review_manifest_path"]
        assert payload["artifact_sha256"][manifest_path] == payload[
            "reviewer_authority"
        ]["review_manifest_sha256"]

    project_payload, policy, digest, _policy_path = generic_state_machine._load_policy(
        project
    )
    accepted = generic_state_machine.validate_state(
        project_payload,
        generic_state_machine._read(state),
        policy,
        digest,
        state_path=state,
        require_evidence_files=True,
    )
    assert accepted == []

    proof = state.parent / proof_campaign / "evidence" / "lemma-proof.md"
    proof.write_text("The proof file was changed after receipt creation.\n", encoding="utf-8")
    rejected = generic_state_machine.validate_state(
        project_payload,
        generic_state_machine._read(state),
        policy,
        digest,
        state_path=state,
        require_evidence_files=True,
    )
    assert any("SHA-256" in error for error in rejected)


def test_commit_binds_new_observations_to_the_authenticated_task_and_role(tmp_path) -> None:
    project, canonical = _project(tmp_path)
    context = _attempt_context(project, canonical)

    def staged_state(name: str) -> Path:
        candidate = tmp_path / name / "research_state.json"
        candidate.parent.mkdir(parents=True)
        shutil.copy2(canonical, candidate)
        evidence = candidate.parent / "evidence" / "statement.md"
        evidence.parent.mkdir()
        evidence.write_text("The exact statement is frozen.\n", encoding="utf-8")
        return candidate

    forged = staged_state("forged-attempt")
    observed = _run(
        "observe",
        "--project",
        str(project),
        "--workstream",
        str(forged),
        "--observation-id",
        "forged-observation",
        "--kind",
        "statement_frozen",
        "--verdict",
        "accepted",
        "--actor-role",
        "reviewer",
        "--source-task-id",
        "invented-task",
        "--summary",
        "A forged role and task identity must not pass the commit gate.",
        "--evidence",
        "evidence/statement.md",
    )
    assert observed.returncode == 0, observed.stderr
    rejected = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(forged),
        "--mode",
        "commit",
        validation_context=context,
    )
    rejected_errors = json.loads(rejected.stdout)["errors"]
    assert rejected.returncode == 1
    assert any("current task_id" in item for item in rejected_errors)
    assert any("current agent role" in item for item in rejected_errors)

    authentic = staged_state("authentic-attempt")
    observed = _run(
        "observe",
        "--project",
        str(project),
        "--workstream",
        str(authentic),
        "--observation-id",
        "authentic-observation",
        "--kind",
        "statement_frozen",
        "--verdict",
        "accepted",
        "--actor-role",
        "researcher",
        "--source-task-id",
        "actual-task",
        "--summary",
        "The scheduled researcher froze the exact statement.",
        "--evidence",
        "evidence/statement.md",
    )
    assert observed.returncode == 0, observed.stderr
    accepted = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(authentic),
        "--mode",
        "commit",
        validation_context=context,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_transition_requires_all_configured_evidence_then_unlocks_bridge(tmp_path) -> None:
    project, state = _project(tmp_path)
    evidence_dir = state.parent / "evidence"
    evidence_dir.mkdir(parents=True)
    evidence_kinds = (
        "statement_frozen",
        "authoritative_source_verified",
        "open_status_verified",
        "duplicate_risk_cleared",
        "decisive_kill_test_defined",
        "bridge_relevance_established",
    )
    observation_ids: list[str] = []
    for index, kind in enumerate(evidence_kinds, start=1):
        evidence = evidence_dir / f"{kind}.md"
        evidence.write_text(f"evidence for {kind}\n", encoding="utf-8")
        observation_id = f"admission-{index}"
        observation_ids.append(observation_id)
        observed = _run(
            "observe",
            "--project",
            str(project),
            "--workstream",
            str(state),
            "--observation-id",
            observation_id,
            "--kind",
            kind,
            "--verdict",
            "accepted",
            "--actor-role",
            "researcher",
            "--source-task-id",
            "admission-task",
            "--summary",
            f"Established {kind}.",
            "--evidence",
            f"evidence/{kind}.md",
        )
        assert observed.returncode == 0, observed.stderr

    incomplete = _run(
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "bridge_search",
        "--reason",
        "Try to advance with incomplete evidence.",
        "--observation",
        observation_ids[0],
    )
    assert incomplete.returncode == 2
    assert "evidence gate did not pass" in incomplete.stderr

    arguments = [
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "bridge_search",
        "--reason",
        "All admission facts and the closure bridge are now evidence-bound.",
    ]
    for observation_id in observation_ids:
        arguments.extend(("--observation", observation_id))
    advanced = _run(*arguments)
    assert advanced.returncode == 0, advanced.stderr
    current = json.loads(state.read_text(encoding="utf-8"))
    assert current["stage"] == "bridge_search"
    assert current["status"] == "active"


def test_actual_routing_usage_exhausts_stage_without_a_scientific_verdict(tmp_path) -> None:
    project, state = _project(tmp_path)
    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=_context(task_count=2, agent_seconds=1200),
    )

    assert decision.returncode == 0, decision.stderr
    payload = json.loads(decision.stdout)
    assert payload == {
        "schema_version": "openlabs.protocol_hook_decision.v1",
        "decision": "defer",
        "reason": "math_stage_budget_exhausted:admission_probe",
    }


def test_project_stage_capacity_defers_without_marking_math_failure(tmp_path) -> None:
    project, state = _project(
        tmp_path,
        binding={
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {
                "profile": "open-problem-closure-v1",
                "overrides": {
                    "portfolio": {
                        "max_concurrent_tasks_by_stage": {"admission_probe": 1}
                    }
                },
            },
        },
    )
    peer_path = tmp_path / "workstreams" / "candidate-two" / "research_state.json"
    peer = json.loads(state.read_text(encoding="utf-8"))
    peer["workstream_id"] = "candidate-two"
    atomic_write_json(peer_path, peer)
    context = _context()
    context["project_workstreams"] = [
        {
            "campaign_id": "candidate-two",
            "priority": 1,
            "status": "active",
            "workstream_state_path": str(peer_path),
            "has_active_tasks": False,
            "has_queued_tasks": True,
        }
    ]

    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=context,
    )

    assert decision.returncode == 0, decision.stderr
    assert json.loads(decision.stdout) == {
        "schema_version": "openlabs.protocol_hook_decision.v1",
        "decision": "defer",
        "reason": "math_stage_capacity_wait:admission_probe",
    }
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "active"


def test_inline_policy_accepts_arbitrary_stage_and_observation_names(tmp_path) -> None:
    policy = {
        "schema_version": "openlabs.math_research_policy.v1",
        "policy_id": "conjecture-garden-v1",
        "description": "A deliberately different configured research graph.",
        "initial_stage": "conjecture_garden",
        "observation_types": {
            "fruit_found": {
                "description": "A useful theorem-shaped result exists.",
                "evidence_required": True,
            }
        },
        "stages": {
            "conjecture_garden": {
                "description": "Explore freely.",
                "task": {
                    "objective": "Explore and choose the mathematics autonomously.",
                    "agent_role": "researcher",
                    "session_mode": "resume",
                    "handoff_kind": "role_handoff",
                    "runner": "cheap",
                    "wall_seconds": 600,
                },
                "budget": {"max_tasks": 3, "on_exhaustion": "pause"},
                "transitions": [
                    {
                        "to": "harvest",
                        "requires": {"all": [{"kind": "fruit_found"}]},
                    }
                ],
            },
            "harvest": {
                "description": "Preserve the result.",
                "terminal": True,
                "completion": "completed",
                "transitions": [],
            },
        },
    }
    project, state = _project(
        tmp_path,
        binding={
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {"inline": policy},
        },
    )
    context = _context()
    context["routing_usage"] = {}
    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=context,
    )

    assert decision.returncode == 0, decision.stderr
    payload = json.loads(decision.stdout)
    assert payload["routing_key"] == "conjecture-garden-v1:conjecture_garden"
    assert payload["action"]["runner"] == "cheap"
    assert payload["action"]["wall_seconds"] == 600


def test_compatible_policy_change_requires_an_audited_rebind(tmp_path) -> None:
    project, state = _project(tmp_path)
    old_state = json.loads(state.read_text(encoding="utf-8"))
    binding_path = tmp_path / "research_policy.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["policy"]["overrides"] = {
        "stages": {"admission_probe": {"task": {"wall_seconds": 900}}}
    }
    atomic_write_json(binding_path, binding)

    rejected = _run(
        "validate",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--mode",
        "commit",
    )
    assert rejected.returncode == 1
    assert "policy_digest" in rejected.stdout

    rebound = _run(
        "rebind-policy",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--expected-old-digest",
        old_state["policy_digest"],
        "--reason",
        "Reduce only the admission episode ceiling for this project.",
    )
    assert rebound.returncode == 0, rebound.stderr
    current = json.loads(state.read_text(encoding="utf-8"))
    assert current["policy_digest"] != old_state["policy_digest"]
    assert current["policy_rebindings"][-1]["old_digest"] == old_state["policy_digest"]

    decision = _run(
        "decide",
        "--project",
        str(project),
        "--workstream",
        str(state),
        stdin=_context(),
    )
    assert json.loads(decision.stdout)["action"]["wall_seconds"] == 900


def test_pause_requires_an_explicit_audited_resume(tmp_path) -> None:
    project, state = _project(tmp_path)

    paused = _run(
        "pause",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--reason",
        "The current route needs operator review before more allocation.",
    )
    assert paused.returncode == 0, paused.stderr
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "paused"

    resumed = _run(
        "resume",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--reason",
        "The review approved another bounded research episode.",
    )
    assert resumed.returncode == 0, resumed.stderr
    current = json.loads(state.read_text(encoding="utf-8"))
    assert current["status"] == "active"
    assert [item["decision"] for item in current["dispositions"]] == [
        "paused_by_research_agent",
        "resumed",
    ]


def test_gate_can_require_independent_observations_from_distinct_tasks(tmp_path) -> None:
    policy = {
        "schema_version": "openlabs.math_research_policy.v1",
        "policy_id": "double-audit-v1",
        "description": "Require two task-distinct reviewer observations.",
        "initial_stage": "audit",
        "observation_types": {
            "audit_passed": {
                "description": "One independent reconstruction passed.",
                "evidence_required": False,
            }
        },
        "stages": {
            "audit": {
                "description": "Run independent audits.",
                "task": {
                    "objective": "Reconstruct the result independently.",
                    "agent_role": "reviewer",
                    "session_mode": "fresh",
                    "handoff_kind": "adversarial_review",
                    "runner": "frontier",
                    "wall_seconds": 600,
                },
                "transitions": [
                    {
                        "to": "done",
                        "requires": {
                            "all": [
                                {
                                    "kind": "audit_passed",
                                    "actor_role": "reviewer",
                                    "min_count": 2,
                                    "distinct_source_tasks": True,
                                }
                            ]
                        },
                    }
                ],
            },
            "done": {
                "description": "Two audits passed.",
                "terminal": True,
                "completion": "completed",
                "transitions": [],
            },
        },
    }
    project, state = _project(
        tmp_path,
        binding={
            "schema_version": "openlabs.math_research_policy_binding.v1",
            "policy": {"inline": policy},
        },
    )

    def observe(observation_id: str, source_task_id: str) -> None:
        result = _run(
            "observe",
            "--project",
            str(project),
            "--workstream",
            str(state),
            "--observation-id",
            observation_id,
            "--kind",
            "audit_passed",
            "--verdict",
            "accepted",
            "--actor-role",
            "reviewer",
            "--source-task-id",
            source_task_id,
            "--summary",
            "The reconstruction passed.",
        )
        assert result.returncode == 0, result.stderr

    observe("audit-one", "review-task-one")
    observe("audit-two", "review-task-one")
    repeated = _run(
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "done",
        "--reason",
        "Two labels from only one task are insufficient.",
        "--observation",
        "audit-one",
        "--observation",
        "audit-two",
    )
    assert repeated.returncode == 2

    observe("audit-three", "review-task-two")
    independent = _run(
        "transition",
        "--project",
        str(project),
        "--workstream",
        str(state),
        "--to",
        "done",
        "--reason",
        "Two fresh task lineages reconstructed the result.",
        "--observation",
        "audit-one",
        "--observation",
        "audit-three",
    )
    assert independent.returncode == 0, independent.stderr
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "completed"
