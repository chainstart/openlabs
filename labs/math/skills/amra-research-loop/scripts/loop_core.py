"""Independent state machine for mechanism-first mathematics campaigns."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "amra-research-loop.v1"
PHASES = (
    "target_selection",
    "obstruction_analysis",
    "representation_search",
    "mechanism_falsification",
    "survivor_deepening",
    "independent_audit",
    "promotion",
    "frozen",
)
ACTIVE_PHASES = PHASES[:-2]
ARTIFACT_FILES = {
    "closure_contract": "closure_contract.json",
    "information_loss_map": "information_loss_map.json",
    "representations": "representations.json",
    "mechanisms": "mechanisms.json",
    "kill_tests": "kill_tests.json",
    "survivors": "survivors.json",
    "decisive_lemma": "decisive_lemma.json",
    "audit": "audit.json",
    "decision": "decision.json",
}
DEFAULT_GATES = {
    "min_representation_families": 4,
    "min_representations": 8,
    "min_mechanism_families": 4,
    "min_mechanisms": 10,
    "min_kill_ratio": 0.8,
    "max_survivors": 3,
}
ALLOWED_SUCCESS = {
    "original_problem_closed",
    "main_term_improved",
    "main_exponent_improved",
    "global_interface_closed",
    "standalone_decisive_lemma",
}
MECHANISM_STATUSES = {"candidate", "killed", "surviving", "proved", "frozen"}


class CampaignError(RuntimeError):
    """Raised when a campaign operation violates its contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise CampaignError("campaign id must contain an ASCII letter or digit")
    return slug


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CampaignError(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CampaignError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def default_artifacts(*, exact_statement: str, source: str) -> dict[str, Any]:
    return {
        "closure_contract": {
            "exact_statement": exact_statement,
            "source": source,
            "published_comparator": "",
            "admissible_inputs": [],
            "false_world_controls": [],
            "non_cosmetic_consequence": "",
            "success_conditions": sorted(ALLOWED_SUCCESS),
            "non_success_conditions": [
                "additional_local_branch",
                "finite_verification_only",
                "conditional_bridge",
                "another_normal_form",
                "file_or_test_volume",
            ],
            "scope_notes": [],
        },
        "information_loss_map": {"inherited_methods": [], "required_new_information": []},
        "representations": {"representations": []},
        "mechanisms": {"mechanisms": []},
        "kill_tests": {"tests": []},
        "survivors": {"mechanism_ids": [], "selection_rationale": ""},
        "decisive_lemma": {
            "statement": "",
            "status": "unset",
            "exact_scope": "",
            "unconditional_inputs": [],
            "non_cosmetic_consequence": "",
            "closes": [],
            "evidence": [],
            "dependency_gaps": [],
        },
        "audit": {
            "independent_reconstruction": {"status": "not_started", "auditor": "", "evidence": []},
            "statement_match": "unchecked",
            "dependency_check": "unchecked",
            "novelty_check": "unchecked",
            "hypothesis_check": "unchecked",
            "counterexample_check": "unchecked",
            "literature_check": "unchecked",
            "formalization_check": {
                "status": "not_started",
                "reason": "",
                "evidence": [],
            },
        },
        "decision": {
            "outcome": "undecided",
            "success_condition": "",
            "reason": "",
            "evidence": [],
        },
    }


def init_campaign(
    root: Path,
    *,
    campaign_id: str,
    problem_id: str,
    title: str,
    exact_statement: str,
    source: str,
) -> Path:
    campaign_dir = root.expanduser().resolve() / slugify(campaign_id)
    if campaign_dir.exists():
        raise CampaignError(f"campaign already exists: {campaign_dir}")
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "evidence").mkdir()
    (campaign_dir / "audit").mkdir()
    artifacts = default_artifacts(exact_statement=exact_statement.strip(), source=source.strip())
    for name, filename in ARTIFACT_FILES.items():
        write_json(campaign_dir / filename, artifacts[name])
    now = utc_now()
    write_json(
        campaign_dir / "campaign_state.json",
        {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": slugify(campaign_id),
            "problem_id": problem_id.strip(),
            "title": title.strip(),
            "phase": "target_selection",
            "created_at": now,
            "updated_at": now,
            "gates": deepcopy(DEFAULT_GATES),
            "artifacts": deepcopy(ARTIFACT_FILES),
            "history": [{"at": now, "event": "initialized", "phase": "target_selection"}],
        },
    )
    return campaign_dir


def load_campaign(campaign_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign_dir = campaign_dir.expanduser().resolve()
    state = read_json(campaign_dir / "campaign_state.json")
    if not isinstance(state, dict):
        raise CampaignError("campaign_state.json must contain an object")
    artifacts = {name: read_json(campaign_dir / filename) for name, filename in ARTIFACT_FILES.items()}
    return state, artifacts


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value: Any) -> bool:
    return isinstance(value, list)


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_campaign(campaign_dir: Path, *, target_phase: str | None = None) -> list[str]:
    state, a = load_campaign(campaign_dir)
    errors: list[str] = []
    phase = target_phase or state.get("phase")
    _require(state.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version", errors)
    _require(phase in PHASES, f"unknown phase: {phase}", errors)
    _require(_text(state.get("campaign_id")), "campaign_id is required", errors)
    _require(_text(state.get("problem_id")), "problem_id is required", errors)

    contract = a["closure_contract"]
    _require(_text(contract.get("exact_statement")), "closure contract needs an exact statement", errors)
    _require(_text(contract.get("source")), "closure contract needs a source", errors)
    success = set(contract.get("success_conditions", []))
    _require(bool(success & ALLOWED_SUCCESS), "closure contract needs an allowed success condition", errors)
    _require(_list(contract.get("non_success_conditions")), "closure contract needs non-success conditions", errors)
    enhanced_contract = any(
        field in contract
        for field in (
            "published_comparator",
            "admissible_inputs",
            "false_world_controls",
            "non_cosmetic_consequence",
        )
    )
    if enhanced_contract:
        _require(
            _text(contract.get("published_comparator")),
            "closure contract needs a published comparator",
            errors,
        )
        admissible_inputs = contract.get("admissible_inputs")
        _require(
            _list(admissible_inputs)
            and bool(admissible_inputs)
            and all(_text(item) for item in admissible_inputs),
            "closure contract needs explicit admissible inputs",
            errors,
        )
        controls = contract.get("false_world_controls")
        valid_controls = [
            item
            for item in controls or []
            if isinstance(item, dict)
            and _text(item.get("model"))
            and _text(item.get("expected_failure"))
        ]
        _require(
            bool(valid_controls),
            "closure contract needs an explicit false-world control",
            errors,
        )
        _require(
            _text(contract.get("non_cosmetic_consequence")),
            "closure contract needs a non-cosmetic consequence",
            errors,
        )
    if phase == "frozen":
        decision = a["decision"]
        _require(decision.get("outcome") == "freeze", "frozen campaign needs a freeze decision", errors)
        _require(_text(decision.get("reason")), "frozen campaign needs a reason", errors)
        return errors
    if errors or phase == "target_selection":
        return errors

    losses = a["information_loss_map"].get("inherited_methods", [])
    valid_losses = [
        item for item in losses
        if isinstance(item, dict)
        and _text(item.get("method"))
        and _text(item.get("loss_step"))
        and _text(item.get("lost_information"))
        and _text(item.get("consequence"))
    ]
    _require(bool(valid_losses), "record at least one precise inherited information loss", errors)
    if phase == "obstruction_analysis":
        return errors

    gates = {**DEFAULT_GATES, **state.get("gates", {})}
    reps = a["representations"].get("representations", [])
    valid_reps = [
        item for item in reps
        if isinstance(item, dict)
        and _text(item.get("id"))
        and _text(item.get("name"))
        and _text(item.get("family"))
        and _text(item.get("new_information"))
        and _text(item.get("first_test"))
    ]
    rep_families = {item["family"] for item in valid_reps}
    rep_ids = [item["id"] for item in valid_reps]
    _require(len(rep_ids) == len(set(rep_ids)), "representation ids must be unique", errors)
    _require(len(valid_reps) >= gates["min_representations"], f"need at least {gates['min_representations']} valid representations", errors)
    _require(len(rep_families) >= gates["min_representation_families"], f"need at least {gates['min_representation_families']} representation families", errors)
    mechanisms = a["mechanisms"].get("mechanisms", [])
    valid_mechanisms = [
        item for item in mechanisms
        if isinstance(item, dict)
        and _text(item.get("id"))
        and _text(item.get("representation_id"))
        and _text(item.get("family"))
        and _text(item.get("decisive_claim"))
        and _list(item.get("would_close")) and bool(item["would_close"])
        and _text(item.get("kill_test"))
        and item.get("status") in MECHANISM_STATUSES
    ]
    mechanism_families = {item["family"] for item in valid_mechanisms}
    ids = [item["id"] for item in valid_mechanisms]
    _require(len(ids) == len(set(ids)), "mechanism ids must be unique", errors)
    _require(
        all(item["representation_id"] in set(rep_ids) for item in valid_mechanisms),
        "every mechanism must reference a known representation",
        errors,
    )
    _require(len(valid_mechanisms) >= gates["min_mechanisms"], f"need at least {gates['min_mechanisms']} valid mechanisms", errors)
    _require(len(mechanism_families) >= gates["min_mechanism_families"], f"need at least {gates['min_mechanism_families']} mechanism families", errors)
    if phase == "representation_search":
        return errors

    killed = [item for item in valid_mechanisms if item["status"] == "killed"]
    survivors = a["survivors"].get("mechanism_ids", [])
    known_ids = set(ids)
    mechanism_by_id = {item["id"]: item for item in valid_mechanisms}
    _require(all(item in known_ids for item in survivors), "survivors must reference known mechanisms", errors)
    _require(1 <= len(survivors) <= gates["max_survivors"], f"select between 1 and {gates['max_survivors']} survivors", errors)
    _require(
        all(mechanism_by_id[item]["status"] in {"surviving", "proved"} for item in survivors if item in mechanism_by_id),
        "survivors must have surviving or proved status",
        errors,
    )
    denominator = max(1, len(valid_mechanisms) - len(survivors))
    _require(len(killed) / denominator >= gates["min_kill_ratio"], f"kill at least {gates['min_kill_ratio']:.0%} of non-surviving mechanisms", errors)
    killed_ids = {item["mechanism_id"] for item in a["kill_tests"].get("tests", []) if isinstance(item, dict) and item.get("outcome") == "killed" and _text(item.get("evidence"))}
    _require({item["id"] for item in killed}.issubset(killed_ids), "every killed mechanism needs an evidenced kill test", errors)
    if phase == "mechanism_falsification":
        return errors

    lemma = a["decisive_lemma"]
    _require(_text(lemma.get("statement")), "decisive lemma statement is required", errors)
    _require(lemma.get("status") in {"proved", "refuted", "conditional"}, "decisive lemma needs an audited status", errors)
    _require(_list(lemma.get("closes")) and bool(lemma.get("closes")), "decisive lemma must identify what it closes", errors)
    _require(_list(lemma.get("evidence")) and bool(lemma.get("evidence")), "decisive lemma needs evidence", errors)
    enhanced_lemma = any(
        field in lemma
        for field in ("exact_scope", "unconditional_inputs", "non_cosmetic_consequence")
    )
    if enhanced_lemma:
        _require(_text(lemma.get("exact_scope")), "decisive lemma needs an exact scope", errors)
        unconditional_inputs = lemma.get("unconditional_inputs")
        _require(
            _list(unconditional_inputs)
            and bool(unconditional_inputs)
            and all(_text(item) for item in unconditional_inputs),
            "decisive lemma needs explicit unconditional inputs",
            errors,
        )
        _require(
            _text(lemma.get("non_cosmetic_consequence")),
            "decisive lemma needs a non-cosmetic consequence",
            errors,
        )
    if phase == "survivor_deepening":
        return errors

    audit = a["audit"]
    reconstruction = audit.get("independent_reconstruction", {})
    _require(reconstruction.get("status") == "passed", "independent reconstruction must pass", errors)
    _require(_text(reconstruction.get("auditor")), "independent reconstruction needs an auditor", errors)
    _require(_list(reconstruction.get("evidence")) and bool(reconstruction.get("evidence")), "independent reconstruction needs evidence", errors)
    _require(audit.get("statement_match") == "passed", "statement match must pass", errors)
    _require(audit.get("dependency_check") == "passed", "dependency check must pass", errors)
    _require(audit.get("novelty_check") in {"passed", "priority_uncertain"}, "novelty check must pass or be explicitly uncertain", errors)
    enhanced_audit = any(
        field in audit
        for field in (
            "hypothesis_check",
            "counterexample_check",
            "literature_check",
            "formalization_check",
            "computation_checks",
        )
    )
    if enhanced_audit:
        _require(audit.get("hypothesis_check") == "passed", "hypothesis check must pass", errors)
        _require(
            audit.get("counterexample_check") == "passed",
            "counterexample check must pass",
            errors,
        )
        _require(audit.get("literature_check") == "passed", "literature check must pass", errors)
        formalization = audit.get("formalization_check")
        _require(isinstance(formalization, dict), "formalization check must be an object", errors)
        if isinstance(formalization, dict):
            status = formalization.get("status")
            _require(
                status in {"passed", "not_feasible"},
                "formalization check must pass or document infeasibility",
                errors,
            )
            if status == "passed":
                _require(
                    _list(formalization.get("evidence")) and bool(formalization.get("evidence")),
                    "passed formalization needs evidence",
                    errors,
                )
            elif status == "not_feasible":
                _require(
                    _text(formalization.get("reason")),
                    "infeasible formalization needs a reason",
                    errors,
                )
        computation_checks = audit.get("computation_checks", [])
        _require(
            isinstance(computation_checks, list),
            "computation checks must be an array",
            errors,
        )
        if isinstance(computation_checks, list):
            for index, check in enumerate(computation_checks):
                prefix = f"computation check {index}"
                _require(isinstance(check, dict), f"{prefix} must be an object", errors)
                if not isinstance(check, dict):
                    continue
                _require(
                    _text(check.get("profile_id")),
                    f"{prefix} needs a profile_id",
                    errors,
                )
                status = check.get("status")
                _require(
                    status in {"passed", "failed", "not_run"},
                    f"{prefix} has an invalid status",
                    errors,
                )
                if status == "passed":
                    _require(
                        _list(check.get("evidence")) and bool(check.get("evidence")),
                        f"{prefix} needs a replayable receipt",
                        errors,
                    )
                elif status in {"failed", "not_run"}:
                    _require(
                        _text(check.get("reason")),
                        f"{prefix} needs a reason",
                        errors,
                    )
    decision = a["decision"]
    _require(decision.get("outcome") == "promote", "promotion decision must be promote", errors)
    _require(decision.get("success_condition") in success & ALLOWED_SUCCESS, "decision must satisfy the frozen closure contract", errors)
    _require(_text(decision.get("reason")), "promotion decision needs a reason", errors)
    _require(_list(decision.get("evidence")) and bool(decision.get("evidence")), "promotion decision needs evidence", errors)
    return errors


def validate_campaign_integrity(campaign_dir: Path) -> list[str]:
    """Validate durable shape and transition history without requiring phase completion.

    This is the protocol-level commit check.  ``validate_campaign`` remains the
    stronger gate used before an explicit phase transition.
    """

    state, artifacts = load_campaign(campaign_dir)
    errors: list[str] = []
    _require(state.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version", errors)
    _require(state.get("phase") in PHASES, f"unknown phase: {state.get('phase')}", errors)
    for field in ("campaign_id", "problem_id", "title", "created_at", "updated_at"):
        _require(_text(state.get(field)), f"campaign state needs {field}", errors)
    artifact_map = state.get("artifacts")
    _require(isinstance(artifact_map, dict), "campaign artifacts map must be an object", errors)
    if isinstance(artifact_map, dict):
        for name, filename in ARTIFACT_FILES.items():
            _require(
                artifact_map.get(name) == filename,
                f"campaign artifact mapping for {name} must be {filename}",
                errors,
            )
    _require(all(isinstance(value, dict) for value in artifacts.values()),
             "every campaign artifact must be an object", errors)

    history = state.get("history")
    if not isinstance(history, list) or not history:
        errors.append("campaign history must be a nonempty array")
        return errors
    first = history[0]
    if not isinstance(first, dict) or first.get("event") != "initialized" or first.get(
        "phase"
    ) != "target_selection":
        errors.append("campaign history must start with target_selection initialization")
        return errors
    replay_phase = "target_selection"
    for index, event in enumerate(history[1:], start=1):
        if not isinstance(event, dict) or not _text(event.get("at")):
            errors.append(f"campaign history entry {index} is malformed")
            continue
        kind = event.get("event")
        if kind == "advanced":
            if event.get("from") != replay_phase:
                errors.append(f"history entry {index} advanced from the wrong phase")
                continue
            try:
                expected = PHASES[PHASES.index(replay_phase) + 1]
            except (ValueError, IndexError):
                errors.append(f"history entry {index} advances a terminal phase")
                continue
            if event.get("phase") != expected:
                errors.append(f"history entry {index} skips the AMRA phase order")
                continue
            replay_phase = expected
        elif kind == "frozen":
            if event.get("from") != replay_phase or event.get("phase") != "frozen":
                errors.append(f"history entry {index} has an invalid freeze transition")
                continue
            replay_phase = "frozen"
    _require(
        state.get("phase") == replay_phase,
        "campaign phase does not match replayed transition history",
        errors,
    )
    if state.get("phase") == "frozen":
        decision = artifacts["decision"]
        _require(decision.get("outcome") == "freeze", "frozen campaign needs a freeze decision", errors)
        _require(_text(decision.get("reason")), "frozen campaign needs a reason", errors)
    if state.get("phase") == "promotion":
        decision = artifacts["decision"]
        _require(decision.get("outcome") == "promote", "promoted campaign needs a promote decision", errors)
    return errors


def advance_campaign(campaign_dir: Path, target_phase: str) -> dict[str, Any]:
    campaign_dir = campaign_dir.expanduser().resolve()
    state, _ = load_campaign(campaign_dir)
    current = state.get("phase")
    if target_phase not in PHASES:
        raise CampaignError(f"unknown target phase: {target_phase}")
    if current in {"promotion", "frozen"}:
        raise CampaignError(f"terminal campaign cannot advance from {current}")
    expected = PHASES[PHASES.index(current) + 1]
    if target_phase != expected:
        raise CampaignError(f"next phase after {current} is {expected}, not {target_phase}")
    errors = validate_campaign(campaign_dir, target_phase=current)
    if errors:
        raise CampaignError("phase gate failed:\n- " + "\n- ".join(errors))
    now = utc_now()
    state["phase"] = target_phase
    state["updated_at"] = now
    state.setdefault("history", []).append({"at": now, "event": "advanced", "from": current, "phase": target_phase})
    write_json(campaign_dir / "campaign_state.json", state)
    return state


def add_mechanism(campaign_dir: Path, mechanism: dict[str, Any]) -> None:
    campaign_dir = campaign_dir.expanduser().resolve()
    path = campaign_dir / ARTIFACT_FILES["mechanisms"]
    payload = read_json(path)
    mechanisms = payload.setdefault("mechanisms", [])
    if any(item.get("id") == mechanism.get("id") for item in mechanisms):
        raise CampaignError(f"duplicate mechanism id: {mechanism.get('id')}")
    mechanism = {**mechanism, "status": mechanism.get("status", "candidate"), "created_at": utc_now()}
    mechanisms.append(mechanism)
    write_json(path, payload)


def set_mechanism_status(campaign_dir: Path, mechanism_id: str, status: str, evidence: str) -> None:
    if status not in MECHANISM_STATUSES:
        raise CampaignError(f"invalid mechanism status: {status}")
    campaign_dir = campaign_dir.expanduser().resolve()
    path = campaign_dir / ARTIFACT_FILES["mechanisms"]
    payload = read_json(path)
    for item in payload.get("mechanisms", []):
        if item.get("id") == mechanism_id:
            item["status"] = status
            item["status_evidence"] = evidence
            item["updated_at"] = utc_now()
            write_json(path, payload)
            return
    raise CampaignError(f"unknown mechanism: {mechanism_id}")


def freeze_campaign(campaign_dir: Path, reason: str, evidence: list[str]) -> dict[str, Any]:
    campaign_dir = campaign_dir.expanduser().resolve()
    state, _ = load_campaign(campaign_dir)
    if state.get("phase") in {"promotion", "frozen"}:
        raise CampaignError(f"terminal campaign is already {state.get('phase')}")
    decision = read_json(campaign_dir / ARTIFACT_FILES["decision"])
    decision.update({"outcome": "freeze", "success_condition": "", "reason": reason, "evidence": evidence})
    write_json(campaign_dir / ARTIFACT_FILES["decision"], decision)
    now = utc_now()
    previous = state["phase"]
    state["phase"] = "frozen"
    state["updated_at"] = now
    state.setdefault("history", []).append({"at": now, "event": "frozen", "from": previous, "phase": "frozen", "reason": reason})
    write_json(campaign_dir / "campaign_state.json", state)
    return state
