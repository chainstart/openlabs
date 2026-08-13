from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))

from loop_core import (  # noqa: E402
    CampaignError,
    advance_campaign,
    freeze_campaign,
    init_campaign,
    read_json,
    set_mechanism_status,
    validate_campaign,
    write_json,
)


class ResearchLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.campaign = init_campaign(
            self.root,
            campaign_id="Test Campaign",
            problem_id="problem-1",
            title="Test",
            exact_statement="For every n, prove P(n).",
            source="https://example.test/problem",
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
        self.temporary.cleanup()

    def write(self, filename: str, payload: object) -> None:
        write_json(self.campaign / filename, payload)

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

    def test_new_campaign_requires_false_world_control(self) -> None:
        contract = read_json(self.campaign / "closure_contract.json")
        contract["false_world_controls"] = []
        self.write("closure_contract.json", contract)
        errors = validate_campaign(self.campaign)
        self.assertTrue(any("false-world control" in error for error in errors))
        with self.assertRaises(CampaignError):
            advance_campaign(self.campaign, "obstruction_analysis")

    def test_full_promotion_path(self) -> None:
        advance_campaign(self.campaign, "obstruction_analysis")
        self.populate_obstruction()
        advance_campaign(self.campaign, "representation_search")
        self.populate_representations_and_mechanisms()
        advance_campaign(self.campaign, "mechanism_falsification")
        self.populate_falsification()
        advance_campaign(self.campaign, "survivor_deepening")
        self.write("decisive_lemma.json", {
            "statement": "The global compatibility interface always holds.",
            "status": "proved",
            "exact_scope": "Every object satisfying the frozen unconditional inputs.",
            "unconditional_inputs": ["The declared unconditional base theorem"],
            "non_cosmetic_consequence": "The original global interface is closed.",
            "closes": ["global interface"],
            "evidence": ["evidence/lemma-proof.md"],
            "dependency_gaps": [],
        })
        advance_campaign(self.campaign, "independent_audit")
        self.write("audit.json", {
            "independent_reconstruction": {
                "status": "passed",
                "auditor": "blind-reviewer-1",
                "evidence": ["audit/reconstruction.md"],
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
        self.write("decision.json", {
            "outcome": "promote",
            "success_condition": "global_interface_closed",
            "reason": "The audited lemma closes the frozen global interface.",
            "evidence": ["audit/reconstruction.md"],
        })
        state = advance_campaign(self.campaign, "promotion")
        self.assertEqual(state["phase"], "promotion")
        self.assertEqual(validate_campaign(self.campaign), [])

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


if __name__ == "__main__":
    unittest.main()
