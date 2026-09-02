from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

import jsonschema


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "orchestrator" / "src"))

import loop_core  # noqa: E402
from openlabs.contracts import validate_receipt, validate_result_bundle  # noqa: E402
from openlabs.gates import evaluate_result_bundle  # noqa: E402
from loop_core import (  # noqa: E402
    CampaignError,
    advance_campaign,
    freeze_campaign,
    init_campaign,
    migrate_campaign_contract,
    prepare_review_manifest,
    read_json,
    set_mechanism_status,
    validate_campaign,
    validate_campaign_integrity,
    write_json,
)


class ResearchLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name) / "openlabs-data"
        self.original_control_plane_root = loop_core.CONTROL_PLANE_DATA_ROOT
        loop_core.CONTROL_PLANE_DATA_ROOT = self.data_root
        self.root = self.data_root / "workspaces" / "math"
        self.root.mkdir(parents=True)
        selection_dir = self.root / "selection-bundle"
        selection_dir.mkdir()
        source_artifact = selection_dir / "source.html"
        source_artifact.write_text("Primary source: For every n, prove P(n). Open Problem.\n", encoding="utf-8")
        status_artifact = selection_dir / "open-status.md"
        status_artifact.write_text("Checked against the primary source on 2026-08-31.\n", encoding="utf-8")
        novelty_artifact = selection_dir / "duplicate-search.md"
        novelty_artifact.write_text("No published closure of the exact statement was found.\n", encoding="utf-8")
        score_vector = {
            "novelty": 20,
            "significance": 20,
            "closure": 15,
            "auditability": 10,
            "generality": 8,
            "venue_fit": 4,
            "total": 77,
        }
        target_cards = selection_dir / "target-cards.json"
        selected_card = {
            "target_id": "test-campaign",
            "problem_id": "problem-1",
            "title": "Test",
            "source_original_statement": "For every n, prove P(n).",
            "frozen_target_statement": "For every n, prove P(n).",
            "target_relation": "exact",
            "source": "https://example.test/problem",
            "public_status": "open_problem",
            "source_locator": "https://example.test/problem#open-problem",
            "closest_published_result": "A finite-range special case only.",
            "score_vector": score_vector,
            "blocking_novelty_risk": False,
        }
        write_json(target_cards, {
            "candidates": [selected_card] + [
                {
                    "target_id": f"comparison-{index}",
                    "problem_id": f"comparison-{index}",
                    "title": f"Comparison {index}",
                    "source_original_statement": f"Comparison statement {index}",
                    "frozen_target_statement": f"Comparison statement {index}",
                    "target_relation": "exact",
                    "source": f"https://example.test/comparison-{index}",
                    "public_status": "open_problem",
                    "source_locator": f"https://example.test/comparison-{index}#problem",
                    "score_vector": score_vector,
                    "blocking_novelty_risk": False,
                    "closest_published_result": f"Closest comparison result {index}.",
                }
                for index in range(1, 4)
            ]
        })
        self.selection_receipt = selection_dir / "selection.json"
        write_json(self.selection_receipt, {
            "schema": "openlabs.math_target_selection.v1",
            **selected_card,
            "source_kind": "primary",
            "source_statement_quote": "For every n, prove P(n).",
            "open_status_quote": "Open Problem.",
            "status_checked_at": "2026-08-31T12:00:00+00:00",
            "score_vector": score_vector,
            "selection_gate_snapshot": {
                "minimum_total": 70,
                "minimum_novelty": 15,
                "minimum_significance": 15,
                "minimum_closure": 10,
            },
            "blocking_novelty_risk": False,
            "closest_published_result": "A finite-range special case only.",
            "duplicate_search_checked_at": "2026-08-31T12:00:00+00:00",
            "source_artifact": {
                "path": source_artifact.name,
                "sha256": sha256(source_artifact.read_bytes()).hexdigest(),
            },
            "status_evidence": [{
                "path": status_artifact.name,
                "sha256": sha256(status_artifact.read_bytes()).hexdigest(),
            }],
            "novelty_evidence": [{
                "path": novelty_artifact.name,
                "sha256": sha256(novelty_artifact.read_bytes()).hexdigest(),
            }],
            "target_cards": target_cards.name,
            "target_cards_sha256": sha256(target_cards.read_bytes()).hexdigest(),
        })
        self.campaign = init_campaign(
            self.root,
            campaign_id="Test Campaign",
            problem_id="problem-1",
            title="Test",
            source_original_statement="For every n, prove P(n).",
            frozen_target_statement="For every n, prove P(n).",
            target_relation="exact",
            source="https://example.test/problem",
            source_authority_receipt=self.selection_receipt,
        )
        contract = read_json(self.campaign / "closure_contract.json")
        contract.update({
            "published_comparator": "The best published result proves P(n) for n up to N.",
            "admissible_inputs": ["The declared unconditional base theorem"],
            "false_world_controls": [{
                "model": "A planted countermodel where global compatibility fails",
                "expected_failure": "The proposed interface certificate must reject the model",
            }],
            "non_cosmetic_consequence": "The theorem closes the global compatibility interface.",
        })
        write_json(self.campaign / "closure_contract.json", contract)

    def tearDown(self) -> None:
        loop_core.CONTROL_PLANE_DATA_ROOT = self.original_control_plane_root
        self.temporary.cleanup()

    def write(self, filename: str, payload: object) -> None:
        write_json(self.campaign / filename, payload)

    def evidence(self, filename: str, content: str) -> dict[str, str]:
        path = self.campaign / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": filename, "sha256": sha256(path.read_bytes()).hexdigest()}

    def control_plane_review(self, state: dict[str, object]) -> dict[str, str]:
        """Install an archived, DB-ingested fresh reviewer lineage."""

        author_task = "author-task-1"
        author_attempt = "author-attempt-1"
        reviewer_task = "independent-review-task"
        reviewer_attempt = "reviewer-attempt-2"
        control_campaign = "control-plane-campaign-1"
        reconstruction_path = self.campaign / "audit" / "reconstruction.md"
        reconstruction_digest = sha256(reconstruction_path.read_bytes()).hexdigest()
        result_path = self.data_root / "reviewer-result.json"
        result = {
            "schema_version": "openlabs.result_bundle.v1",
            "task_id": reviewer_task,
            "campaign_id": control_campaign,
            "lab_id": "math",
            "domain": "math",
            "status": "completed",
            "summary": "Independent reconstruction passed and verifies exact closure.",
            "artifacts": [{
                "artifact_id": "amra-audit-reconstruction",
                "uri": reconstruction_path.as_uri(),
                "sha256": reconstruction_digest,
                "kind": "audit",
            }],
            "claims": [{
                "claim_id": "amra-original-problem-closed",
                "text": "The exact source-original problem is closed by a proof.",
                "status": "verified",
                "evidence": ["amra-audit-reconstruction"],
                "limitations": [],
            }],
            "next_actions": [],
            "paper_candidate": False,
            "amra_review_schema_version": "openlabs.amra_review.v1",
            "amra_audit_outcome": "passed",
            "amra_campaign_id": state["campaign_id"],
            "amra_statement_identity": state["statement_identity"],
            "amra_author_attempt_id": author_attempt,
            "amra_resolution_type": "proof",
            "amra_success_condition": "original_problem_closed",
            "amra_review_manifest_sha256": sha256(
                (self.campaign / "audit" / "review-manifest.json").read_bytes()
            ).hexdigest(),
        }
        self.assertTrue(validate_result_bundle(result).valid)
        self.assertTrue(evaluate_result_bundle(result, allowed_roots=(self.data_root,)).passed)
        write_json(result_path, result)
        result_digest = sha256(result_path.read_bytes()).hexdigest()
        runtime = {
            "adapter": "codex",
            "duration_seconds": 1.0,
            "exit_code": 0,
            "heartbeat_lost": False,
            "session_id": "fresh-review-session",
            "hooks": {
                "schema_version": "openlabs.hook_runtime.v1",
                "events": [],
                "stop_passed": True,
                "session_start_count": 1,
            },
        }
        archive = self.data_root / "ledger" / "receipts"
        archive.mkdir(parents=True)
        receipt_path = archive / f"{reviewer_task}-{reviewer_attempt}-archived.json"
        receipt = {
            "schema_version": "openlabs.result_receipt.v2",
            "task_id": reviewer_task,
            "attempt_id": reviewer_attempt,
            "campaign_id": control_campaign,
            "lab_id": "math",
            "domain": "math",
            "agent_role": "reviewer",
            "result_path": str(result_path),
            "sha256": result_digest,
            "runtime": runtime,
        }
        self.assertTrue(validate_receipt(receipt).valid)
        write_json(receipt_path, receipt)
        database = self.data_root / "openlabs-database" / "live" / "factory.sqlite"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        connection.executescript("""
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY, campaign_id TEXT, domain TEXT,
                agent_role TEXT, session_mode TEXT, parent_task_id TEXT,
                status TEXT, result_path TEXT, result_sha256 TEXT
            );
            CREATE TABLE task_attempts (
                attempt_id TEXT PRIMARY KEY, task_id TEXT, status TEXT,
                result_path TEXT, result_sha256 TEXT, runtime_json TEXT
            );
            CREATE TABLE result_bundles (
                task_id TEXT PRIMARY KEY, attempt_id TEXT, path TEXT,
                sha256 TEXT, valid INTEGER, gate_passed INTEGER,
                blockers_json TEXT, runtime_json TEXT
            );
        """)
        connection.executemany(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (author_task, control_campaign, "math", "researcher", "resume", None,
                 "succeeded", None, None),
                (reviewer_task, control_campaign, "math", "reviewer", "fresh", author_task,
                 "succeeded", str(result_path), result_digest),
            ],
        )
        connection.executemany(
            "INSERT INTO task_attempts VALUES (?, ?, ?, ?, ?, ?)",
            [
                (author_attempt, author_task, "succeeded", None, None, json.dumps({})),
                (reviewer_attempt, reviewer_task, "succeeded", str(result_path), result_digest,
                 json.dumps(runtime)),
            ],
        )
        connection.execute(
            "INSERT INTO result_bundles VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (reviewer_task, reviewer_attempt, str(result_path), result_digest, 1, 1,
             json.dumps([]), json.dumps(runtime)),
        )
        connection.commit()
        connection.close()
        return {
            "path": receipt_path.relative_to(self.data_root).as_posix(),
            "sha256": sha256(receipt_path.read_bytes()).hexdigest(),
        }

    def migrate_self_to_specialization(self) -> None:
        legacy_target = "For every even n, prove P(n)."
        contract = read_json(self.campaign / "closure_contract.json")
        contract["exact_statement"] = legacy_target
        contract.pop("source_original_statement")
        contract.pop("frozen_target_statement")
        contract.pop("target_relation")
        self.write("closure_contract.json", contract)
        state = read_json(self.campaign / "campaign_state.json")
        state["schema_version"] = "amra-research-loop.v1"
        state.pop("statement_identity")
        state["history"][0].pop("statement_identity")
        self.write("campaign_state.json", state)
        migrate_campaign_contract(
            self.campaign,
            source_original_statement="For every n, prove P(n).",
            frozen_target_statement=legacy_target,
            target_relation="specialization",
            reason="Separate the published conjecture from the legacy local target.",
        )

    def populate_obstruction(self) -> None:
        self.write("information_loss_map.json", {
            "inherited_methods": [{
                "method": "fixed projection",
                "loss_step": "average over fibers",
                "lost_information": "fiber provenance",
                "consequence": "the global compatibility condition disappears",
            }],
            "required_new_information": ["fiber provenance"],
        })

    def populate_representations_and_mechanisms(self) -> None:
        families = ["potential", "algebraic", "spectral", "probabilistic"]
        reps = [{
            "id": f"R{index:03d}",
            "name": f"representation {index}",
            "family": families[(index - 1) % len(families)],
            "new_information": f"retained datum {index}",
            "first_test": f"adversarial model {index}",
        } for index in range(1, 9)]
        mechanisms = [{
            "id": f"M{index:03d}",
            "representation_id": reps[(index - 1) % len(reps)]["id"],
            "family": families[(index - 1) % len(families)],
            "decisive_claim": f"decisive claim {index}",
            "would_close": ["global interface"],
            "kill_test": f"kill test {index}",
            "status": "candidate",
        } for index in range(1, 11)]
        self.write("representations.json", {"representations": reps})
        self.write("mechanisms.json", {"mechanisms": mechanisms})

    def populate_falsification(self) -> None:
        tests = []
        for index in range(1, 9):
            mechanism_id = f"M{index:03d}"
            set_mechanism_status(self.campaign, mechanism_id, "killed", f"certificate {index}")
            tests.append({
                "mechanism_id": mechanism_id,
                "test": f"test {index}",
                "outcome": "killed",
                "evidence": f"evidence/certificate-{index}.json",
            })
        for index in (9, 10):
            set_mechanism_status(self.campaign, f"M{index:03d}", "surviving", "passed first kill test")
        self.write("kill_tests.json", {"tests": tests})
        self.write("survivors.json", {
            "mechanism_ids": ["M009", "M010"],
            "selection_rationale": "Only these survived the hostile models.",
        })

    def test_initial_campaign_is_valid_and_fail_closed(self) -> None:
        self.assertEqual(validate_campaign(self.campaign), [])
        advance_campaign(self.campaign, "obstruction_analysis")
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("information loss" in error for error in errors))
        with self.assertRaises(CampaignError):
            advance_campaign(self.campaign, "representation_search")

    def test_initialized_contract_and_state_match_published_schemas(self) -> None:
        schemas = PACKAGE_ROOT / "schemas"
        state_schema = json.loads((schemas / "campaign-state.schema.json").read_text(encoding="utf-8"))
        contract_schema = json.loads((schemas / "closure-contract.schema.json").read_text(encoding="utf-8"))
        resolver = jsonschema.RefResolver(base_uri=(schemas.as_uri() + "/"), referrer=contract_schema)
        jsonschema.validate(read_json(self.campaign / "campaign_state.json"), state_schema)
        jsonschema.validate(
            read_json(self.campaign / "closure_contract.json"),
            contract_schema,
            resolver=resolver,
        )

    def test_new_campaign_requires_false_world_control(self) -> None:
        contract = read_json(self.campaign / "closure_contract.json")
        contract["false_world_controls"] = []
        self.write("closure_contract.json", contract)
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("false-world control" in error for error in errors))
        with self.assertRaises(CampaignError):
            advance_campaign(self.campaign, "obstruction_analysis")

    def test_exact_relation_requires_source_statement_match(self) -> None:
        with self.assertRaisesRegex(CampaignError, "exact target must match"):
            init_campaign(
                self.root,
                campaign_id="Mismatched exact target",
                problem_id="problem-2",
                title="Mismatch",
                source_original_statement="Prove P for every graph.",
                frozen_target_statement="Prove P for every planar graph.",
                target_relation="exact",
                source="https://example.test/problem-2",
            )

    def test_exact_campaign_requires_primary_source_selection_receipt(self) -> None:
        with self.assertRaisesRegex(CampaignError, "primary-source selection receipt"):
            init_campaign(
                self.root / "missing-source-authority-rejection",
                campaign_id="Missing Authority",
                problem_id="problem-missing-authority",
                title="Missing source authority",
                source_original_statement="For every n, prove R(n).",
                frozen_target_statement="For every n, prove R(n).",
                target_relation="exact",
                source="https://example.test/missing-authority",
            )

    def test_selection_cards_cannot_use_narrowed_targets(self) -> None:
        receipt = read_json(self.selection_receipt)
        cards_path = self.selection_receipt.parent / receipt["target_cards"]
        cards = read_json(cards_path)
        cards["candidates"][1]["frozen_target_statement"] = (
            "Comparison statement 1, restricted to a finite range"
        )
        write_json(cards_path, cards)
        receipt["target_cards_sha256"] = sha256(cards_path.read_bytes()).hexdigest()
        write_json(self.selection_receipt, receipt)

        with self.assertRaisesRegex(CampaignError, "narrows or changes"):
            init_campaign(
                self.root / "narrow-card-rejection",
                campaign_id="Test Campaign",
                problem_id="problem-1",
                title="Test",
                source_original_statement="For every n, prove P(n).",
                frozen_target_statement="For every n, prove P(n).",
                target_relation="exact",
                source="https://example.test/problem",
                source_authority_receipt=self.selection_receipt,
            )

    def test_selected_card_identity_must_match_selection_receipt(self) -> None:
        receipt = read_json(self.selection_receipt)
        cards_path = self.selection_receipt.parent / receipt["target_cards"]
        cards = read_json(cards_path)
        cards["candidates"][0]["source_original_statement"] = (
            "For every n, prove a different exact open statement Q(n)."
        )
        cards["candidates"][0]["frozen_target_statement"] = (
            "For every n, prove a different exact open statement Q(n)."
        )
        write_json(cards_path, cards)
        receipt["target_cards_sha256"] = sha256(cards_path.read_bytes()).hexdigest()
        write_json(self.selection_receipt, receipt)

        with self.assertRaisesRegex(CampaignError, "selected target card .* does not match"):
            init_campaign(
                self.root / "selected-card-identity-rejection",
                campaign_id="Test Campaign",
                problem_id="problem-1",
                title="Test",
                source_original_statement="For every n, prove P(n).",
                frozen_target_statement="For every n, prove P(n).",
                target_relation="exact",
                source="https://example.test/problem",
                source_authority_receipt=self.selection_receipt,
            )

    def test_non_exact_target_cannot_claim_original_problem_closure(self) -> None:
        contract = read_json(self.campaign / "closure_contract.json")
        contract["frozen_target_statement"] = "For every even n, prove P(n)."
        contract["target_relation"] = "specialization"
        contract["success_conditions"] = [
            "scoped_theorem_proved",
            "original_problem_closed",
        ]
        self.write("closure_contract.json", contract)
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("only an exact source-statement target" in error for error in errors))

        decision = read_json(self.campaign / "decision.json")
        decision.update({
            "outcome": "promote",
            "success_condition": "original_problem_closed",
            "reason": "Incorrectly promote a specialization as the source problem.",
            "evidence": ["evidence/proof.md"],
        })
        self.write("decision.json", decision)
        integrity_errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(
            any("original_problem_closed promotion requires" in error for error in integrity_errors)
        )

    def test_non_exact_target_must_use_scoped_theorem_type(self) -> None:
        contract = read_json(self.campaign / "closure_contract.json")
        contract["frozen_target_statement"] = "Prove P(n) with a stronger quantitative bound."
        contract["target_relation"] = "strengthening"
        contract["success_conditions"] = ["main_term_improved"]
        self.write("closure_contract.json", contract)
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("must use scoped_theorem_proved" in error for error in errors))

    def test_frozen_statement_identity_blocks_in_place_scope_reduction(self) -> None:
        contract = read_json(self.campaign / "closure_contract.json")
        narrowed = "For every even n, prove P(n)."
        contract["source_original_statement"] = narrowed
        contract["frozen_target_statement"] = narrowed
        contract["target_relation"] = "exact"
        self.write("closure_contract.json", contract)
        errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(any("source_original_statement changed" in error for error in errors))
        self.assertTrue(any("frozen_target_statement changed" in error for error in errors))

    def test_frozen_statement_identity_blocks_success_downgrade(self) -> None:
        contract = read_json(self.campaign / "closure_contract.json")
        contract["success_conditions"] = ["scoped_theorem_proved"]
        self.write("closure_contract.json", contract)
        errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(
            any("success condition changed" in error for error in errors)
        )

    def test_integrity_replays_full_gate_for_promotion(self) -> None:
        state = read_json(self.campaign / "campaign_state.json")
        phases = [
            "target_selection",
            "obstruction_analysis",
            "representation_search",
            "mechanism_falsification",
            "survivor_deepening",
            "independent_audit",
            "promotion",
        ]
        state["history"] = [state["history"][0]] + [
            {
                "at": state["updated_at"],
                "event": "advanced",
                "from": previous,
                "phase": current,
            }
            for previous, current in zip(phases, phases[1:])
        ]
        state["phase"] = "promotion"
        self.write("campaign_state.json", state)
        self.write(
            "decision.json",
            {
                "outcome": "promote",
                "success_condition": "original_problem_closed",
                "reason": "Syntactically complete but mathematically empty promotion.",
                "evidence": ["missing-proof.md"],
            },
        )
        errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(any("information loss" in error for error in errors))
        self.assertTrue(any("independent reconstruction" in error for error in errors))

    def test_conditional_decisive_lemma_cannot_enter_audit(self) -> None:
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        advance_campaign(self.campaign, "mechanism_falsification")
        self.populate_falsification()
        advance_campaign(self.campaign, "survivor_deepening")
        self.write(
            "decisive_lemma.json",
            {
                "statement": "The target follows if the missing bridge Q holds.",
                "status": "conditional",
                "exact_scope": "Every object satisfying Q and the frozen inputs.",
                "unconditional_inputs": ["The declared unconditional base theorem"],
                "non_cosmetic_consequence": "Would close the target if Q were proved.",
                "closes": ["original_problem_closed"],
                "evidence": ["evidence/conditional-derivation.md"],
                "dependency_gaps": ["Missing bridge Q"],
            },
        )
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("requires a proved decisive lemma" in error for error in errors))
        self.assertTrue(any("dependency gap" in error for error in errors))
        with self.assertRaises(CampaignError):
            advance_campaign(self.campaign, "independent_audit")

    def test_missing_decisive_proof_file_blocks_audit(self) -> None:
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        advance_campaign(self.campaign, "mechanism_falsification")
        self.populate_falsification()
        advance_campaign(self.campaign, "survivor_deepening")
        self.write(
            "decisive_lemma.json",
            {
                "statement": "The global compatibility interface always holds.",
                "status": "proved",
                "exact_scope": "Every object satisfying the frozen inputs.",
                "unconditional_inputs": ["The declared unconditional base theorem"],
                "non_cosmetic_consequence": "The target follows.",
                "closes": ["original_problem_closed"],
                "evidence": [
                    {"path": "evidence/missing-proof.md", "sha256": "0" * 64}
                ],
                "dependency_gaps": [],
            },
        )
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("evidence file does not exist" in error for error in errors))
        with self.assertRaises(CampaignError):
            advance_campaign(self.campaign, "independent_audit")

    def test_legacy_exact_statement_contract_fails_closed(self) -> None:
        contract = read_json(self.campaign / "closure_contract.json")
        contract["exact_statement"] = contract.pop("frozen_target_statement")
        contract.pop("source_original_statement")
        contract.pop("target_relation")
        self.write("closure_contract.json", contract)
        errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(any("migrate legacy exact_statement" in error for error in errors))

    def test_explicit_migration_preserves_local_target_and_scopes_result(self) -> None:
        self.migrate_self_to_specialization()
        migrated = read_json(self.campaign / "campaign_state.json")
        self.assertEqual(migrated["schema_version"], "amra-research-loop.v2")
        migrated_contract = read_json(self.campaign / "closure_contract.json")
        self.assertEqual(migrated_contract["success_conditions"], ["scoped_theorem_proved"])
        self.assertEqual(validate_campaign_integrity(self.campaign), [])

    def test_non_exact_mechanism_cannot_claim_original_closure(self) -> None:
        self.migrate_self_to_specialization()
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        mechanisms = read_json(self.campaign / "mechanisms.json")
        mechanisms["mechanisms"][0]["would_close"] = ["original_problem_closed"]
        self.write("mechanisms.json", mechanisms)
        errors = validate_campaign(self.campaign)
        self.assertTrue(
            any("non-exact mechanism may not claim original_problem_closed" in error for error in errors)
        )
        integrity_errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(
            any(
                "non-exact mechanism may not claim original_problem_closed" in error
                for error in integrity_errors
            )
        )

    def test_proved_scoped_lemma_must_close_scoped_success(self) -> None:
        self.migrate_self_to_specialization()
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        advance_campaign(self.campaign, "mechanism_falsification")
        self.populate_falsification()
        set_mechanism_status(
            self.campaign,
            "M009",
            "proved",
            "evidence/scoped-mechanism-proof.md",
        )
        errors = validate_campaign(self.campaign)
        self.assertTrue(
            any("proved survivor must close the frozen success condition" in error for error in errors)
        )
        integrity_errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(
            any(
                "proved survivor must close the frozen success condition" in error
                for error in integrity_errors
            )
        )
        mechanisms = read_json(self.campaign / "mechanisms.json")
        for mechanism in mechanisms["mechanisms"]:
            if mechanism["id"] == "M009":
                mechanism["would_close"] = ["scoped_theorem_proved"]
        self.write("mechanisms.json", mechanisms)
        advance_campaign(self.campaign, "survivor_deepening")
        self.write("decisive_lemma.json", {
            "statement": "The specialized compatibility interface always holds.",
            "status": "proved",
            "exact_scope": "Every object satisfying the scoped unconditional inputs.",
            "unconditional_inputs": ["The declared unconditional base theorem"],
            "non_cosmetic_consequence": "The specialization follows.",
            "closes": ["original_problem_closed"],
            "evidence": ["evidence/scoped-proof.md"],
            "dependency_gaps": [],
        })
        errors = validate_campaign(self.campaign)
        self.assertTrue(
            any("non-exact decisive lemma may not claim original_problem_closed" in error for error in errors)
        )
        self.assertTrue(
            any("proved decisive lemma must close the frozen success condition" in error for error in errors)
        )
        integrity_errors = validate_campaign_integrity(self.campaign)
        self.assertTrue(
            any(
                "non-exact decisive lemma may not claim original_problem_closed" in error
                for error in integrity_errors
            )
        )

    def test_full_promotion_path(self) -> None:
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        advance_campaign(self.campaign, "mechanism_falsification")
        self.populate_falsification()
        advance_campaign(self.campaign, "survivor_deepening")
        lemma_evidence = self.evidence(
            "evidence/lemma-proof.md", "A complete symbolic proof of the decisive lemma.\n"
        )
        self.write("decisive_lemma.json", {
            "statement": "The global compatibility interface always holds.",
            "status": "proved",
            "exact_scope": "Every object satisfying the frozen unconditional inputs.",
            "unconditional_inputs": ["The declared unconditional base theorem"],
            "non_cosmetic_consequence": "The original global interface is closed.",
            "closes": ["original_problem_closed"],
            "evidence": [lemma_evidence],
            "dependency_gaps": [],
        })
        advance_campaign(self.campaign, "independent_audit")
        reconstruction_evidence = self.evidence(
            "audit/reconstruction.md",
            "An independent line-by-line reconstruction with hostile checks.\n",
        )
        state_before_audit = read_json(self.campaign / "campaign_state.json")
        self.write("decision.json", {
            "outcome": "promote",
            "success_condition": "original_problem_closed",
            "resolution_type": "proof",
            "reason": "The audited proof closes the exact source-original statement.",
            "evidence": [lemma_evidence],
            "open_status_recheck": {
                "public_status": "open_problem",
                "source_locator": "https://example.test/problem#open-problem",
                "status_checked_at": "2026-08-31T12:00:00+00:00",
                "evidence": [self.evidence(
                    "audit/current-open-status.md",
                    "Primary source still labels the exact statement as open.\n",
                )],
            },
        })
        prepare_review_manifest(self.campaign, "author-attempt-1")
        reviewer_receipt = self.control_plane_review(state_before_audit)
        audit = read_json(self.campaign / "audit.json")
        audit.update({
            "independent_reconstruction": {
                "status": "passed",
                "auditor": "blind-reviewer-1",
                "author_attempt_id": "author-attempt-1",
                "control_plane_receipt": reviewer_receipt,
                "evidence": [reconstruction_evidence],
            },
            "statement_match": "passed",
            "dependency_check": "passed",
            "novelty_check": "priority_uncertain",
            "hypothesis_check": "passed",
            "counterexample_check": "passed",
            "literature_check": "passed",
            "formalization_check": {
                "status": "not_feasible",
                "reason": "The imported analytic library is not available in the prover.",
                "evidence": [],
            },
        })
        self.write("audit.json", audit)
        state = advance_campaign(self.campaign, "promotion")
        self.assertEqual(state["phase"], "promotion")
        self.assertEqual(validate_campaign(self.campaign), [])

        lemma = read_json(self.campaign / "decisive_lemma.json")
        lemma["status"] = "conditional"
        lemma["dependency_gaps"] = ["Post-promotion missing bridge Q"]
        self.write("decisive_lemma.json", lemma)
        self.assertTrue(
            any("requires a proved decisive lemma" in error for error in validate_campaign(self.campaign))
        )
        self.assertTrue(
            any(
                "requires a proved decisive lemma" in error
                for error in validate_campaign_integrity(self.campaign)
            )
        )

    def test_killed_mechanisms_need_evidence(self) -> None:
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        advance_campaign(self.campaign, "mechanism_falsification")
        for index in range(1, 9):
            set_mechanism_status(self.campaign, f"M{index:03d}", "killed", "claimed only")
        self.write("survivors.json", {
            "mechanism_ids": ["M009", "M010"],
            "selection_rationale": "Two candidates remain.",
        })
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("evidenced kill test" in error for error in errors))

    def test_mechanisms_must_reference_known_representations(self) -> None:
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        mechanisms = read_json(self.campaign / "mechanisms.json")
        mechanisms["mechanisms"][0]["representation_id"] = "R999"
        self.write("mechanisms.json", mechanisms)
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("known representation" in error for error in errors))

    def test_freeze_is_terminal_and_valid(self) -> None:
        state = freeze_campaign(self.campaign, "No mechanism survives the base countermodel.", ["evidence/no-go.md"])
        self.assertEqual(state["phase"], "frozen")
        self.assertEqual(validate_campaign(self.campaign), [])
        decision = read_json(self.campaign / "decision.json")
        self.assertEqual(decision["outcome"], "freeze")
        with self.assertRaises(CampaignError):
            advance_campaign(self.campaign, "obstruction_analysis")

    def test_migration_recovery_rejects_truncated_live_tree(self) -> None:
        backup, journal = loop_core._migration_paths(self.campaign)
        shutil.copytree(self.campaign, backup)
        state = read_json(self.campaign / "campaign_state.json")
        write_json(journal, {
            "schema_version": "openlabs.amra_migration_journal.v1",
            "campaign": str(self.campaign.resolve()),
            "staging_root": str(self.root / "untrusted-informational-path"),
            "statement_identity": state["statement_identity"],
            "status": "prepared",
        })
        (self.campaign / "closure_contract.json").unlink()

        loop_core._recover_campaign_migration(self.campaign.resolve())

        self.assertFalse(journal.exists())
        self.assertFalse(backup.exists())
        self.assertTrue((self.campaign / "closure_contract.json").is_file())
        self.assertEqual(validate_campaign_integrity(self.campaign), [])
        failed_root = self.campaign.parent / ".migration-failed"
        self.assertEqual(len(list(failed_root.glob("test-campaign-*"))), 1)


if __name__ == "__main__":
    unittest.main()
