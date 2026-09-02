#!/usr/bin/env python3
"""Validate and atomically update an adaptive mathematics production lane."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from hashlib import sha256
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PLAN_SCHEMA = "openlabs.math_production_plan.v1"
LANE_SCHEMA = "openlabs.math_production_lane.v1"
STAGES = {"radar", "research", "terminal"}
NODE_OUTCOMES = {"progress", "no_progress", "promotion", "freeze"}
SELECTION_MODES = {"radar_scored", "operator_locked_route"}
TARGET_RELATIONS = {"exact", "specialization", "strengthening", "partial"}
SELECTION_RECEIPT_SCHEMA = "openlabs.math_target_selection.v1"
OPEN_SOURCE_STATUSES = {"open_problem", "open_conjecture"}
SEARCH_DELTAS = {
    "blocker_reduced",
    "mechanism_killed",
    "survivor_strengthened",
    "promotion_gate_advanced",
}
THEOREM_DELTAS = {
    "theorem_statement_strengthened",
    "hypothesis_removed",
    "public_frontier_improved",
    "standalone_no_go_closed",
}
EPISTEMIC_DELTAS = SEARCH_DELTAS | THEOREM_DELTAS
DEFAULT_NODE_POLICY = {
    "consecutive_no_progress_limit": 3,
    "max_radar_nodes_per_cycle": 3,
    "max_nodes_without_theorem_delta": 8,
    "max_research_nodes_per_target": 12,
    "max_frozen_branches_without_promotion": 2,
}
SCORE_MAXIMA = {
    "novelty": 25,
    "significance": 25,
    "closure": 20,
    "auditability": 15,
    "generality": 10,
    "venue_fit": 5,
}
PLAN_SELECTION_GATE_MAP = {
    "minimum_total": "minimum_total",
    "minimum_novelty": "minimum_novelty",
    "minimum_significance": "minimum_significance",
    "minimum_closure": "minimum_closure",
    "minimum_target_cards_per_cycle": "minimum_target_cards",
    "minimum_distinct_research_fronts_per_cycle": "minimum_distinct_research_fronts",
}
_AMRA_PRIVATE_MODULE_NAME = "_openlabs_math_production_amra_loop_core"
_AMRA_LOOP_CORE_PATH = (
    Path(__file__).resolve().parents[2]
    / "amra-research-loop"
    / "scripts"
    / "loop_core.py"
).resolve()
_AMRA_LOOP_CORE_MODULE: Any | None = None


class StateError(RuntimeError):
    """Raised when a plan or lane violates its contract."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StateError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise StateError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError(f"expected an object in {path}")
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _prospective_lane_errors(path: Path, payload: dict[str, Any]) -> list[str]:
    """Validate a complete candidate lane before replacing the live file."""

    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.preflight-", suffix=".json", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return validate_lane(temporary_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized_statement(value: str) -> str:
    return " ".join(value.split())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise StateError("target_id must contain an ASCII letter or digit")
    return slug


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_amra_loop_core() -> Any:
    """Load the repository AMRA core without consulting the global loop_core name."""

    global _AMRA_LOOP_CORE_MODULE
    if _AMRA_LOOP_CORE_MODULE is not None:
        loaded_path = Path(str(getattr(_AMRA_LOOP_CORE_MODULE, "__file__", ""))).resolve()
        if loaded_path != _AMRA_LOOP_CORE_PATH:
            raise StateError("cached AMRA module does not come from the repository authority path")
        return _AMRA_LOOP_CORE_MODULE
    if not _AMRA_LOOP_CORE_PATH.is_file():
        raise StateError(f"missing AMRA authority module: {_AMRA_LOOP_CORE_PATH}")
    spec = importlib.util.spec_from_file_location(
        _AMRA_PRIVATE_MODULE_NAME,
        _AMRA_LOOP_CORE_PATH,
    )
    if spec is None or spec.loader is None:
        raise StateError(f"cannot load AMRA authority module: {_AMRA_LOOP_CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(_AMRA_PRIVATE_MODULE_NAME)
    sys.modules[_AMRA_PRIVATE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        if previous is None:
            sys.modules.pop(_AMRA_PRIVATE_MODULE_NAME, None)
        else:
            sys.modules[_AMRA_PRIVATE_MODULE_NAME] = previous
        raise StateError(f"cannot load AMRA authority module: {exc}") from exc
    loaded_path = Path(str(getattr(module, "__file__", ""))).resolve()
    if loaded_path != _AMRA_LOOP_CORE_PATH:
        raise StateError("loaded AMRA module does not come from the repository authority path")
    _AMRA_LOOP_CORE_MODULE = module
    return module


def _lane_authority_plan(
    lane_path: Path, lane: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    plan_reference = lane.get("plan_path")
    if not _text(plan_reference):
        raise StateError("lane plan_path is required")
    plan_path = (lane_path.parent / str(plan_reference)).resolve()
    return plan_path, read_json(plan_path)


def _effective_selection_gate(
    lane_path: Path,
    lane: dict[str, Any],
    *,
    authority_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the lane gate with plan minima mapped onto canonical lane keys."""

    lane_gate = lane.get("selection_gate")
    effective = dict(lane_gate) if isinstance(lane_gate, dict) else {}
    effective.setdefault("minimum_target_cards", 4)
    effective.setdefault("minimum_distinct_research_fronts", 1)
    if authority_plan is None:
        _, authority_plan = _lane_authority_plan(lane_path, lane)
    plan_gate = authority_plan.get("selection_gate")
    if not isinstance(plan_gate, dict):
        return effective
    for plan_key, canonical_key in PLAN_SELECTION_GATE_MAP.items():
        plan_value = plan_gate.get(plan_key)
        if not isinstance(plan_value, int) or isinstance(plan_value, bool):
            continue
        lane_value = effective.get(canonical_key)
        if not isinstance(lane_value, int) or isinstance(lane_value, bool):
            effective[canonical_key] = plan_value
        else:
            effective[canonical_key] = max(int(lane_value), int(plan_value))
    return effective


def _declared_research_fronts(authority_plan: dict[str, Any]) -> set[str]:
    program = authority_plan.get("program")
    fronts = program.get("research_fronts") if isinstance(program, dict) else None
    if not isinstance(fronts, list):
        return set()
    return {
        str(item["name"])
        for item in fronts
        if isinstance(item, dict) and _text(item.get("name"))
    }


def _bound_local_file(
    *,
    workspace: Path,
    base: Path,
    reference: object,
    label: str,
    errors: list[str],
) -> Path | None:
    if not isinstance(reference, dict):
        errors.append(f"{label} must be a path/SHA-256 object")
        return None
    path_value = reference.get("path")
    digest = reference.get("sha256")
    if not _text(path_value) or not isinstance(digest, str) or len(digest) != 64:
        errors.append(f"{label} needs path and lowercase SHA-256")
        return None
    resolved = (base / str(path_value)).resolve()
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError:
        errors.append(f"{label} must stay inside the lane workspace")
        return None
    if not resolved.is_file():
        errors.append(f"{label} does not exist: {resolved}")
        return None
    if _sha256_file(resolved) != digest:
        errors.append(f"{label} SHA-256 does not match")
        return None
    return resolved


def _target_card_errors(candidate: object, index: int) -> list[str]:
    """Require one comparison card to describe an exact, genuine open target."""

    prefix = f"target_cards candidate {index}"
    if not isinstance(candidate, dict):
        return [f"{prefix} must be an object"]
    required_text = (
        "target_id",
        "problem_id",
        "title",
        "source_original_statement",
        "frozen_target_statement",
        "source",
        "source_locator",
        "closest_published_result",
        "research_front",
    )
    errors = [
        f"{prefix} needs {field}"
        for field in required_text
        if not _text(candidate.get(field))
    ]
    if candidate.get("target_relation") != "exact":
        errors.append(f"{prefix} must use target_relation=exact")
    if candidate.get("public_status") not in OPEN_SOURCE_STATUSES:
        errors.append(f"{prefix} must be an open problem or open conjecture")
    source_statement = candidate.get("source_original_statement")
    frozen_statement = candidate.get("frozen_target_statement")
    if (
        _text(source_statement)
        and _text(frozen_statement)
        and _normalized_statement(str(source_statement))
        != _normalized_statement(str(frozen_statement))
    ):
        errors.append(f"{prefix} narrows or changes the source-original statement")
    if candidate.get("blocking_novelty_risk") is not False:
        errors.append(f"{prefix} must clear blocking novelty risk")
    score = candidate.get("score_vector")
    score_fields = set(SCORE_MAXIMA) | {"total"}
    if (
        not isinstance(score, dict)
        or set(score) != score_fields
        or any(
            not isinstance(score.get(field), int)
            or isinstance(score.get(field), bool)
            or not 0 <= int(score[field]) <= maximum
            for field, maximum in SCORE_MAXIMA.items()
        )
        or not isinstance(score.get("total"), int)
        or isinstance(score.get("total"), bool)
    ):
        errors.append(f"{prefix} needs a complete bounded integer score_vector")
    elif score["total"] != sum(int(score[field]) for field in SCORE_MAXIMA):
        errors.append(f"{prefix} score total is inconsistent")
    return errors


def _selection_receipt_errors(
    lane_path: Path,
    selected: dict[str, Any],
    *,
    selection_gate: dict[str, Any] | None = None,
    declared_research_fronts: set[str] | None = None,
) -> list[str]:
    """Verify a fresh, hash-bound primary-source receipt for radar selection."""

    errors: list[str] = []
    gate = selection_gate if isinstance(selection_gate, dict) else selected.get(
        "selection_gate_snapshot"
    )
    gate = gate if isinstance(gate, dict) else {}
    minimum_cards = gate.get("minimum_target_cards", 4)
    if not _positive_int(minimum_cards):
        errors.append("selection gate minimum_target_cards must be a positive integer")
        minimum_cards = 4
    required_cards = max(4, int(minimum_cards))
    minimum_fronts = gate.get("minimum_distinct_research_fronts", 1)
    if not _positive_int(minimum_fronts):
        errors.append(
            "selection gate minimum_distinct_research_fronts must be a positive integer"
        )
        minimum_fronts = 1
    required_fronts = int(minimum_fronts)
    allowed_fronts = declared_research_fronts or set()
    receipt_ref = selected.get("selection_receipt")
    recorded_digest = selected.get("selection_receipt_sha256")
    if not _text(receipt_ref):
        return ["radar-scored selected_target needs a hash-bound selection_receipt"]
    receipt_path = (lane_path.parent / str(receipt_ref)).resolve()
    try:
        receipt_path.relative_to(lane_path.parent.resolve())
    except ValueError:
        return ["selection_receipt must stay inside the lane workspace"]
    if receipt_path.name != "selection.json":
        errors.append("selection receipt must be named selection.json")
    if not receipt_path.is_file():
        return errors + [f"selection receipt does not exist: {receipt_path}"]
    actual_digest = _sha256_file(receipt_path)
    if recorded_digest != actual_digest:
        errors.append("selection_receipt SHA-256 does not match the selected target")
    try:
        receipt = read_json(receipt_path)
    except StateError as exc:
        return errors + [str(exc)]
    if receipt.get("schema") != SELECTION_RECEIPT_SCHEMA:
        errors.append("selection receipt has an unsupported schema")

    for field in (
        "target_id",
        "problem_id",
        "title",
        "source_original_statement",
        "frozen_target_statement",
        "target_relation",
        "source",
        "research_front",
        "selection_plan_sha256",
    ):
        expected = selected.get(field)
        observed = receipt.get(field)
        if field.endswith("_statement"):
            matches = (
                _text(expected)
                and _text(observed)
                and _normalized_statement(str(expected))
                == _normalized_statement(str(observed))
            )
        else:
            matches = expected == observed
        if not matches:
            errors.append(f"selection receipt {field} does not match the selected target")

    if receipt.get("source_kind") != "primary":
        errors.append("selection receipt must identify a primary source")
    if receipt.get("public_status") not in OPEN_SOURCE_STATUSES:
        errors.append("selection receipt must classify the source as an open problem or conjecture")
    if not _text(receipt.get("source_locator")):
        errors.append("selection receipt needs an exact source locator")
    if not _text(receipt.get("research_front")):
        errors.append("selection receipt needs a research_front")
    elif allowed_fronts and str(receipt["research_front"]).strip() not in allowed_fronts:
        errors.append("selection receipt research_front is not declared by the production plan")
    if not isinstance(receipt.get("selection_plan_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", str(receipt.get("selection_plan_sha256"))
    ):
        errors.append("selection receipt needs the production plan SHA-256")
    if receipt.get("blocking_novelty_risk") is not False:
        errors.append("selection receipt must explicitly clear blocking novelty risk")
    if receipt.get("score_vector") != selected.get("scores"):
        errors.append("selection receipt score_vector does not match the scored selection")
    if receipt.get("selection_gate_snapshot") != selected.get("selection_gate_snapshot"):
        errors.append("selection receipt selection_gate_snapshot does not match the lane gate")
    if not _text(receipt.get("closest_published_result")):
        errors.append("selection receipt needs the closest published result")
    novelty_evidence = receipt.get("novelty_evidence")
    if not isinstance(novelty_evidence, list) or not novelty_evidence:
        errors.append("selection receipt needs duplicate/novelty-search evidence")
    else:
        for index, reference in enumerate(novelty_evidence):
            _bound_local_file(
                workspace=lane_path.parent,
                base=receipt_path.parent,
                reference=reference,
                label=f"selection receipt novelty_evidence[{index}]",
                errors=errors,
            )
    duplicate_checked_at = receipt.get("duplicate_search_checked_at")
    try:
        duplicate_checked = datetime.fromisoformat(str(duplicate_checked_at).replace("Z", "+00:00"))
        if duplicate_checked.tzinfo is None:
            raise ValueError("timezone required")
        duplicate_age = datetime.now(UTC) - duplicate_checked.astimezone(UTC)
        if duplicate_age.total_seconds() < -86400 or duplicate_age.days > 30:
            errors.append("selection receipt duplicate search is not current")
    except (TypeError, ValueError):
        errors.append("selection receipt needs a timezone-aware duplicate_search_checked_at")
    source_artifact = _bound_local_file(
        workspace=lane_path.parent,
        base=receipt_path.parent,
        reference=receipt.get("source_artifact"),
        label="selection receipt source_artifact",
        errors=errors,
    )
    statement_quote = receipt.get("source_statement_quote")
    status_quote = receipt.get("open_status_quote")
    if not _text(statement_quote) or not (
        _text(receipt.get("source_original_statement"))
        and _normalized_statement(str(statement_quote))
        == _normalized_statement(str(receipt["source_original_statement"]))
    ):
        errors.append("selection receipt source_statement_quote must equal the exact source statement")
    if not _text(status_quote):
        errors.append("selection receipt needs an open_status_quote from the primary source")
    status_evidence = receipt.get("status_evidence")
    if not isinstance(status_evidence, list) or not status_evidence:
        errors.append("selection receipt needs primary-source open-status evidence")
    else:
        for index, reference in enumerate(status_evidence):
            _bound_local_file(
                workspace=lane_path.parent,
                base=receipt_path.parent,
                reference=reference,
                label=f"selection receipt status_evidence[{index}]",
                errors=errors,
            )
    checked_at = receipt.get("status_checked_at")
    try:
        checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            raise ValueError("timezone required")
        age = datetime.now(UTC) - checked.astimezone(UTC)
        if age.total_seconds() < -86400:
            errors.append("selection receipt status check is dated in the future")
        elif age.days > 30:
            errors.append("selection receipt open-status check is older than 30 days")
    except (TypeError, ValueError):
        errors.append("selection receipt needs a timezone-aware status_checked_at")

    cards_ref = receipt.get("target_cards")
    cards_digest = receipt.get("target_cards_sha256")
    if not _text(cards_ref) or not isinstance(cards_digest, str):
        errors.append("selection receipt needs target_cards and target_cards_sha256")
    else:
        cards_path = (receipt_path.parent / str(cards_ref)).resolve()
        try:
            cards_path.relative_to(lane_path.parent.resolve())
        except ValueError:
            errors.append("target_cards must stay inside the lane workspace")
        else:
            if not cards_path.is_file():
                errors.append(f"target_cards does not exist: {cards_path}")
            elif _sha256_file(cards_path) != cards_digest:
                errors.append("target_cards SHA-256 does not match the selection receipt")
            else:
                try:
                    cards_payload = read_json(cards_path)
                except StateError as exc:
                    errors.append(str(exc))
                else:
                    candidates = cards_payload.get("candidates")
                    if not isinstance(candidates, list) or len(candidates) < required_cards:
                        errors.append(
                            "target_cards must compare at least "
                            f"{required_cards} candidates"
                        )
                    candidate_items = candidates if isinstance(candidates, list) else []
                    target_ids: list[str] = []
                    research_fronts: set[str] = set()
                    for index, candidate in enumerate(candidate_items):
                        card_errors = _target_card_errors(candidate, index)
                        errors.extend(card_errors)
                        if not isinstance(candidate, dict):
                            continue
                        if _text(candidate.get("target_id")):
                            target_ids.append(str(candidate["target_id"]).strip())
                        if not _text(candidate.get("research_front")):
                            continue
                        research_front = str(candidate["research_front"]).strip()
                        research_fronts.add(research_front)
                        if allowed_fronts and research_front not in allowed_fronts:
                            errors.append(
                                f"target_cards candidate {index} uses an undeclared research_front"
                            )
                    if len(target_ids) != len(set(target_ids)):
                        errors.append("target_cards target_id values must be distinct")
                    if len(research_fronts) < required_fronts:
                        errors.append(
                            "target_cards must cover at least "
                            f"{required_fronts} distinct research fronts"
                        )
                    matching = [
                        item
                        for item in candidate_items
                        if isinstance(item, dict)
                        and item.get("target_id") == selected.get("target_id")
                    ]
                    if len(matching) != 1:
                        errors.append(
                            "target_cards must contain exactly one selected target card"
                        )
                    else:
                        card = matching[0]
                        for field in (
                            "problem_id",
                            "title",
                            "source_original_statement",
                            "frozen_target_statement",
                            "target_relation",
                            "source",
                            "public_status",
                            "source_locator",
                            "score_vector",
                            "blocking_novelty_risk",
                            "research_front",
                        ):
                            expected = (
                                receipt.get(field)
                                if field in {
                                    "public_status",
                                    "source_locator",
                                    "score_vector",
                                    "blocking_novelty_risk",
                                    "research_front",
                                }
                                else selected.get(field)
                            )
                            observed = card.get(field)
                            if field.endswith("_statement"):
                                matches = (
                                    _text(expected)
                                    and _text(observed)
                                    and _normalized_statement(str(expected))
                                    == _normalized_statement(str(observed))
                                )
                            else:
                                matches = expected == observed
                            if not matches:
                                errors.append(
                                    f"selected target card {field} does not match the receipt"
                                )
    if source_artifact is not None and source_artifact.stat().st_size == 0:
        errors.append("selection receipt source_artifact must not be empty")
    elif source_artifact is not None:
        try:
            source_text = source_artifact.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append("selection receipt source_artifact must be a UTF-8 primary-source text snapshot")
        else:
            normalized_source = _normalized_statement(source_text)
            if _text(statement_quote) and _normalized_statement(str(statement_quote)) not in normalized_source:
                errors.append("source_statement_quote is absent from the primary-source snapshot")
            if _text(status_quote) and _normalized_statement(str(status_quote)) not in normalized_source:
                errors.append("open_status_quote is absent from the primary-source snapshot")
    return errors


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _effective_node_policy(lane_path: Path, lane: dict[str, Any]) -> dict[str, Any]:
    """Merge safe defaults, plan-level theorem policy, and lane overrides."""

    policy: dict[str, Any] = dict(DEFAULT_NODE_POLICY)
    plan_path = lane.get("plan_path")
    if _text(plan_path):
        plan = read_json((lane_path.parent / str(plan_path)).resolve())
        program = plan.get("program")
        if isinstance(program, dict):
            theorem_policy = program.get("theorem_target_policy")
            if isinstance(theorem_policy, dict):
                policy.update(theorem_policy)
    lane_policy = lane.get("node_policy")
    if isinstance(lane_policy, dict):
        policy.update(lane_policy)
    return policy


def _selected_amra_phase(lane_path: Path, lane: dict[str, Any]) -> str:
    campaign_path = _selected_amra_path(lane_path, lane)
    return str(read_json(campaign_path / "campaign_state.json").get("phase"))


def _selected_amra_path(lane_path: Path, lane: dict[str, Any]) -> Path:
    selected = lane.get("selected_target")
    if not isinstance(selected, dict) or not _text(selected.get("amra_campaign")):
        raise StateError("research outcome requires a selected AMRA campaign")
    raw = Path(str(selected["amra_campaign"]))
    if raw.is_absolute():
        raise StateError("selected AMRA campaign path must be relative to the lane workspace")
    resolved = (lane_path.parent / raw).resolve()
    try:
        resolved.relative_to(lane_path.parent.resolve())
    except ValueError as exc:
        raise StateError("selected AMRA campaign must stay inside the lane workspace") from exc
    cycle = selected.get("cycle")
    target_id = selected.get("target_id")
    if _positive_int(cycle) and _text(target_id):
        expected = (
            lane_path.parent
            / "research"
            / f"cycle-{int(cycle):03d}"
            / _slugify(str(target_id))
        ).resolve()
        if resolved != expected:
            raise StateError("selected AMRA campaign path does not match its cycle and target_id")
    return resolved


def _amra_validation_errors(
    campaign_path: Path, *, require_promotion_gate: bool = False
) -> list[str]:
    """Run the nested AMRA authority gates instead of trusting its phase field."""

    try:
        amra = _load_amra_loop_core()
        errors = list(amra.validate_campaign_integrity(campaign_path))
        if require_promotion_gate:
            errors.extend(amra.validate_campaign(campaign_path))
            audit = read_json(campaign_path / "audit.json")
            if audit.get("novelty_check") != "passed":
                errors.append("production promotion requires novelty_check=passed")
    except (StateError, OSError, ValueError, KeyError, TypeError) as exc:
        return [f"AMRA validation failed: {exc}"]
    return list(dict.fromkeys(errors))


def _research_budget_metrics(
    lane: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    cycle = lane.get("cycle")
    cycle_nodes = [
        node
        for node in lane.get("nodes", [])
        if isinstance(node, dict)
        if node.get("cycle") == cycle
        and node.get("outcome") in {"progress", "no_progress"}
    ]
    consecutive_no_progress = 0
    for node in reversed(cycle_nodes):
        if node.get("outcome") != "no_progress":
            break
        consecutive_no_progress += 1
    without_theorem = 0
    for node in reversed(cycle_nodes):
        progress_class = node.get("progress_class")
        if progress_class == "theorem" or node.get("delta_kind") in THEOREM_DELTAS:
            break
        without_theorem += 1
    reasons: list[str] = []
    if consecutive_no_progress >= int(policy["consecutive_no_progress_limit"]):
        reasons.append("consecutive_no_progress_limit")
    if without_theorem >= int(policy["max_nodes_without_theorem_delta"]):
        reasons.append("max_nodes_without_theorem_delta")
    if (
        len(cycle_nodes) >= int(policy["max_research_nodes_per_target"])
        and without_theorem > 0
    ):
        reasons.append("max_research_nodes_per_target")
    return {
        "research_nodes": len(cycle_nodes),
        "consecutive_no_progress": consecutive_no_progress,
        "consecutive_without_theorem_delta": without_theorem,
        "freeze_reasons": reasons,
    }


def _valid_timestamp(value: object) -> bool:
    if not _text(value):
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _node_validation_errors(nodes: list[object], lane_cycle: object) -> list[str]:
    """Validate the canonical node shape and the delta/outcome reducer inputs."""

    errors: list[str] = []
    previous_cycle = 0
    terminal_cycles: set[int] = set()
    maximum_cycle = int(lane_cycle) if _positive_int(lane_cycle) else 0
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"lane node {index} must be an object")
            continue
        cycle_value = node.get("cycle")
        if not _positive_int(cycle_value) or int(cycle_value) > maximum_cycle:
            errors.append(f"lane node {index} has an invalid cycle")
            cycle = 0
        else:
            cycle = int(cycle_value)
            if cycle < previous_cycle:
                errors.append(f"lane node {index} is out of cycle order")
            if cycle in terminal_cycles:
                errors.append(f"lane node {index} follows a terminal node in the same cycle")
            previous_cycle = max(previous_cycle, cycle)
        if not _valid_timestamp(node.get("at")):
            errors.append(f"lane node {index} needs a timezone-aware at timestamp")
        outcome = node.get("outcome")
        valid_outcome = isinstance(outcome, str) and outcome in NODE_OUTCOMES
        if not valid_outcome:
            errors.append(f"lane node {index} has an invalid outcome")
        if not _text(node.get("summary")):
            errors.append(f"lane node {index} has an invalid summary")
        evidence = node.get("evidence")
        if not isinstance(evidence, list) or any(not _text(item) for item in evidence):
            errors.append(f"lane node {index} evidence must be a list of nonempty paths")

        delta_kind = node.get("delta_kind")
        valid_delta_kind = isinstance(delta_kind, str)
        if outcome == "progress":
            if not valid_delta_kind or delta_kind not in EPISTEMIC_DELTAS:
                errors.append(f"lane node {index} progress lacks an epistemic delta_kind")
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"lane node {index} progress requires evidence")
        elif valid_outcome and delta_kind != "none":
            errors.append(f"lane node {index} non-progress outcome must use delta_kind=none")

        if outcome == "promotion":
            expected_progress_class = "promotion"
        elif outcome == "progress" and valid_delta_kind and delta_kind in THEOREM_DELTAS:
            expected_progress_class = "theorem"
        elif outcome == "progress":
            expected_progress_class = "search"
        else:
            expected_progress_class = "none"
        if node.get("progress_class") != expected_progress_class:
            errors.append(f"lane node {index} has an inconsistent progress_class")

        theorem = node.get("theorem")
        if outcome == "progress" and valid_delta_kind and delta_kind in THEOREM_DELTAS:
            theorem_fields = {"statement", "scope", "consequence"}
            if not isinstance(theorem, dict) or set(theorem) != theorem_fields or any(
                not _text(theorem.get(field)) for field in theorem_fields
            ):
                errors.append(f"lane node {index} has incomplete theorem metadata")
        elif theorem is not None:
            errors.append(f"lane node {index} has theorem metadata without a theorem delta")

        if cycle and outcome in {"promotion", "freeze"}:
            terminal_cycles.add(cycle)
    return errors


def _expected_continuation_gate(
    lane: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any] | None:
    """Reduce current-cycle nodes to the one authoritative continuation gate."""

    if lane.get("stage") != "research":
        return None
    cycle = lane.get("cycle")
    cycle_nodes = [
        node
        for node in lane.get("nodes", [])
        if isinstance(node, dict) and node.get("cycle") == cycle
    ]
    if not cycle_nodes:
        return None
    last = cycle_nodes[-1]
    if last.get("outcome") == "freeze":
        return {
            "status": "branch_or_terminal_required",
            "set_at": last.get("at"),
            "cycle": cycle,
        }
    if last.get("outcome") == "promotion":
        return None
    budget = _research_budget_metrics(lane, policy)
    freeze_reasons = budget["freeze_reasons"]
    if freeze_reasons:
        return {
            "status": "freeze_required",
            "set_at": last.get("at"),
            "cycle": cycle,
            "reasons": freeze_reasons,
        }
    for node in reversed(cycle_nodes):
        if (
            node.get("outcome") == "progress"
            and node.get("delta_kind") in THEOREM_DELTAS
        ):
            return {
                "status": "independent_audit_required",
                "set_at": node.get("at"),
                "cycle": cycle,
                "theorem_delta": node.get("delta_kind"),
            }
    return None


def _continuation_transition_errors(
    lane: dict[str, Any], policy: dict[str, Any]
) -> list[str]:
    """Reject node sequences that bypassed an earlier continuation gate."""

    if lane.get("stage") != "research":
        return []
    cycle = lane.get("cycle")
    indexed_nodes = [
        (index, node)
        for index, node in enumerate(lane.get("nodes", []))
        if isinstance(node, dict) and node.get("cycle") == cycle
    ]
    prefix_lane = {"stage": "research", "cycle": cycle, "nodes": []}
    gate: dict[str, Any] | None = None
    errors: list[str] = []
    for index, node in indexed_nodes:
        if isinstance(gate, dict):
            status = gate.get("status")
            terminal = node.get("outcome") in {"promotion", "freeze"}
            theorem_salvage = (
                status == "freeze_required"
                and node.get("outcome") == "progress"
                and node.get("delta_kind") in THEOREM_DELTAS
            )
            if not terminal and not theorem_salvage:
                errors.append(
                    f"lane node {index} bypasses prior continuation gate {status}"
                )
        prefix_lane["nodes"].append(node)
        gate = _expected_continuation_gate(prefix_lane, policy)
    return errors


def validate_plan(path: Path) -> list[str]:
    plan = read_json(path)
    errors: list[str] = []
    if plan.get("schema_version") != PLAN_SCHEMA:
        errors.append("unsupported plan schema_version")
    for field in ("plan_id", "status", "objective"):
        if not _text(plan.get(field)):
            errors.append(f"plan {field} is required")
    for field in (
        "autonomy",
        "scheduler",
        "portfolio",
        "selection_gate",
        "paper_shadow_gate",
        "observation_policy",
    ):
        if not isinstance(plan.get(field), dict):
            errors.append(f"plan {field} must be an object")
    program = plan.get("program")
    if program is not None:
        if not isinstance(program, dict):
            errors.append("plan program must be an object")
        else:
            north_star = program.get("north_star")
            if not isinstance(north_star, dict):
                errors.append("program north_star must be an object")
            else:
                for field in ("statement", "source", "public_status"):
                    if not _text(north_star.get(field)):
                        errors.append(f"program north_star {field} is required")
            for field in (
                "research_fronts",
                "invalid_progress",
                "seed_maturation",
                "summary_policy",
                "north_star_claim_gate",
            ):
                expected = list if field in {"research_fronts", "invalid_progress"} else dict
                if not isinstance(program.get(field), expected):
                    errors.append(f"program {field} must be a {expected.__name__}")
            theorem_policy = program.get("theorem_target_policy")
            if theorem_policy is not None:
                if not isinstance(theorem_policy, dict):
                    errors.append("program theorem_target_policy must be an object")
                else:
                    for field in (
                        "max_nodes_without_theorem_delta",
                        "max_research_nodes_per_target",
                        "max_frozen_branches_without_promotion",
                    ):
                        if not _positive_int(theorem_policy.get(field)):
                            errors.append(
                                f"program theorem_target_policy {field} must be a positive integer"
                            )
    lanes = plan.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        errors.append("plan lanes must be a nonempty list")
        return errors
    seen: set[str] = set()
    active_lanes = 0
    for index, item in enumerate(lanes):
        if not isinstance(item, dict):
            errors.append(f"lane entry {index} must be an object")
            continue
        lane_id = item.get("lane_id")
        lane_path = item.get("config_path")
        if not _text(lane_id) or not _text(lane_path):
            errors.append(f"lane entry {index} needs lane_id and config_path")
            continue
        startup = item.get("startup", "active")
        if startup not in {"active", "paused"}:
            errors.append(f"lane entry {index} has unknown startup state: {startup}")
        elif startup == "active":
            active_lanes += 1
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            errors.append(f"lane entry {index} priority must be an integer")
        if lane_id in seen:
            errors.append(f"duplicate lane_id: {lane_id}")
        seen.add(str(lane_id))
        resolved = (path.parent / str(lane_path)).resolve()
        if not resolved.is_file():
            errors.append(f"missing lane config: {resolved}")
            continue
        lane_errors = validate_lane(
            resolved,
            expected_plan_id=str(plan.get("plan_id") or ""),
            expected_plan_path=path.resolve(),
        )
        errors.extend(f"{lane_id}: {error}" for error in lane_errors)
    portfolio = plan.get("portfolio")
    maximum_lanes = (
        portfolio.get("maximum_research_lanes")
        if isinstance(portfolio, dict)
        else None
    )
    if not _positive_int(maximum_lanes):
        errors.append("portfolio maximum_research_lanes must be a positive integer")
    elif active_lanes > int(maximum_lanes):
        errors.append(
            f"active lanes {active_lanes} exceed maximum_research_lanes {maximum_lanes}"
        )
    return errors


def validate_lane(
    path: Path,
    *,
    expected_plan_id: str | None = None,
    expected_plan_path: Path | None = None,
) -> list[str]:
    lane = read_json(path)
    errors: list[str] = []
    if lane.get("schema_version") != LANE_SCHEMA:
        errors.append("unsupported lane schema_version")
    for field in ("plan_id", "lane_id", "plan_path"):
        if not _text(lane.get(field)):
            errors.append(f"lane {field} is required")
    if expected_plan_id and lane.get("plan_id") != expected_plan_id:
        errors.append("lane plan_id does not match the production plan")
    if expected_plan_path is not None and _text(lane.get("plan_path")):
        if (path.parent / str(lane["plan_path"])).resolve() != expected_plan_path.resolve():
            errors.append("lane plan_path does not point to the validating production plan")
    resolved_plan: Path | None = None
    authority_plan: dict[str, Any] | None = None
    if _text(lane.get("plan_path")):
        resolved_plan = (path.parent / str(lane["plan_path"])).resolve()
        if not resolved_plan.is_file():
            errors.append(f"lane plan_path does not exist: {resolved_plan}")
        else:
            try:
                authority_plan = read_json(resolved_plan)
            except StateError as exc:
                errors.append(str(exc))
            else:
                if authority_plan.get("plan_id") != lane.get("plan_id"):
                    errors.append("lane plan_id does not match its plan_path authority")
    if lane.get("stage") not in STAGES:
        errors.append(f"unknown lane stage: {lane.get('stage')}")
    selection_mode = lane.get("selection_mode", "radar_scored")
    if selection_mode not in SELECTION_MODES:
        errors.append(f"unknown lane selection_mode: {selection_mode}")
    if not _positive_int(lane.get("cycle")):
        errors.append("lane cycle must be a positive integer")
    if not isinstance(lane.get("theme"), dict):
        errors.append("lane theme must be an object")
    for field in ("selection_gate", "node_policy"):
        if not isinstance(lane.get(field), dict):
            errors.append(f"lane {field} must be an object")
    lane_selection_gate = lane.get("selection_gate")
    if isinstance(lane_selection_gate, dict):
        for field in (
            "minimum_total",
            "minimum_novelty",
            "minimum_significance",
            "minimum_closure",
        ):
            value = lane_selection_gate.get(field)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                errors.append(f"lane selection_gate {field} must be a nonnegative integer")
        for field in ("minimum_target_cards", "minimum_distinct_research_fronts"):
            value = lane_selection_gate.get(field)
            if value is not None and not _positive_int(value):
                errors.append(f"lane selection_gate {field} must be a positive integer")
    effective_selection_gate = (
        _effective_selection_gate(path, lane, authority_plan=authority_plan)
        if authority_plan is not None
        else dict(lane_selection_gate) if isinstance(lane_selection_gate, dict) else {}
    )
    declared_research_fronts = (
        _declared_research_fronts(authority_plan)
        if authority_plan is not None
        else set()
    )
    if authority_plan is not None:
        plan_selection_gate = authority_plan.get("selection_gate")
        planned_front_minimum = (
            plan_selection_gate.get("minimum_distinct_research_fronts_per_cycle")
            if isinstance(plan_selection_gate, dict)
            else None
        )
        if _positive_int(planned_front_minimum) and len(declared_research_fronts) < int(
            planned_front_minimum
        ):
            errors.append(
                "production plan declares fewer research_fronts than its distinct-front minimum"
            )
    node_policy = lane.get("node_policy")
    if isinstance(node_policy, dict):
        for field in DEFAULT_NODE_POLICY:
            value = node_policy.get(field)
            if value is not None and not _positive_int(value):
                errors.append(f"lane node_policy {field} must be a positive integer")
    for field in ("archived_targets", "nodes", "history"):
        if not isinstance(lane.get(field), list):
            errors.append(f"lane {field} must be a list")
    history = lane.get("history") if isinstance(lane.get("history"), list) else []
    known_events = {
        "target_selected", "operator_route_locked", "post_result_route_branch_started",
        "lane_recycled", "radar_exhausted_without_selection",
    }
    for index, event in enumerate(history):
        if not isinstance(event, dict) or not _text(event.get("at")):
            errors.append(f"lane history entry {index} is malformed")
        elif event.get("event") not in known_events:
            errors.append(f"lane history entry {index} has an unknown event")
    replay_stage = "radar"
    replay_cycle = 1
    replay_target_id: str | None = None
    replay_archives: list[tuple[str, str]] = []
    for index, event in enumerate(history):
        if not isinstance(event, dict) or event.get("event") not in known_events:
            continue
        kind = event["event"]
        if kind in {"target_selected", "operator_route_locked"}:
            if replay_stage != "radar" or event.get("cycle") != replay_cycle or not _text(event.get("target_id")):
                errors.append(f"lane history entry {index} cannot select from the replayed state")
                continue
            replay_stage = "research"
            replay_target_id = str(event["target_id"])
        elif kind == "lane_recycled":
            if (
                replay_stage != "research"
                or event.get("previous_cycle") != replay_cycle
                or event.get("next_cycle") != replay_cycle + 1
                or event.get("archived_target_id") != replay_target_id
                or not _text(event.get("archive_snapshot_sha256"))
            ):
                errors.append(f"lane history entry {index} cannot recycle from the replayed state")
                continue
            replay_archives.append((str(event["archived_target_id"]), str(event["archive_snapshot_sha256"])))
            replay_cycle += 1
            replay_stage = "radar"
            replay_target_id = None
        elif kind == "post_result_route_branch_started":
            if (
                replay_stage != "research"
                or event.get("previous_cycle") != replay_cycle
                or event.get("cycle") != replay_cycle + 1
                or event.get("archived_target_id") != replay_target_id
                or not _text(event.get("archive_snapshot_sha256"))
                or not _text(event.get("target_id"))
            ):
                errors.append(f"lane history entry {index} cannot branch from the replayed state")
                continue
            replay_archives.append((str(event["archived_target_id"]), str(event["archive_snapshot_sha256"])))
            replay_cycle += 1
            replay_target_id = str(event["target_id"])
        elif kind == "radar_exhausted_without_selection":
            if replay_stage != "radar" or event.get("cycle") != replay_cycle:
                errors.append(f"lane history entry {index} cannot exhaust the replayed radar")
                continue
            replay_stage = "terminal"
    if lane.get("cycle") != replay_cycle or lane.get("stage") != replay_stage:
        errors.append("lane cycle/stage does not match replayed history")
    selected_for_replay = lane.get("selected_target")
    if replay_stage == "research":
        if not isinstance(selected_for_replay, dict) or selected_for_replay.get("target_id") != replay_target_id:
            errors.append("selected target does not match replayed lane history")
    elif selected_for_replay is not None:
        errors.append("replayed non-research lane may not retain a selected target")
    nodes = lane.get("nodes") if isinstance(lane.get("nodes"), list) else []
    errors.extend(_node_validation_errors(nodes, lane.get("cycle")))
    program_id = lane.get("program_id")
    if program_id is not None:
        if not _text(program_id):
            errors.append("lane program_id must be nonempty text")
        for field in ("program_summary", "paper_seed_registry"):
            value = lane.get(field)
            if not _text(value):
                errors.append(f"lane {field} is required for a flagship program")
                continue
            resolved = (path.parent / str(value)).resolve()
            if not resolved.is_file():
                errors.append(f"lane {field} does not exist: {resolved}")
    selected = lane.get("selected_target")
    if lane.get("stage") in {"radar", "terminal"} and selected is not None:
        errors.append(f"{lane.get('stage')} stage must not retain a selected_target")
    if lane.get("stage") == "research":
        if not isinstance(selected, dict):
            errors.append("research stage requires selected_target")
        else:
            if selected.get("cycle") != lane.get("cycle"):
                errors.append("selected_target cycle does not match the lane cycle")
            for field in (
                "target_id",
                "problem_id",
                "title",
                "source_original_statement",
                "frozen_target_statement",
                "target_relation",
                "source",
            ):
                if not _text(selected.get(field)):
                    errors.append(f"selected_target needs {field}")
            relation = selected.get("target_relation")
            valid_relation = isinstance(relation, str) and relation in TARGET_RELATIONS
            if not valid_relation:
                errors.append("selected_target has an invalid target_relation")
            if selection_mode == "radar_scored" and relation != "exact":
                errors.append(
                    "radar-scored selected_target must retain the exact source-original statement"
                )
            if selection_mode == "radar_scored" and relation == "exact":
                if selected.get("selection_gate_snapshot") != effective_selection_gate:
                    errors.append(
                        "selected target selection_gate_snapshot does not match the effective production plan gate"
                    )
                if resolved_plan is None or not resolved_plan.is_file():
                    errors.append("selected target cannot bind a missing production plan")
                elif selected.get("selection_plan_sha256") != _sha256_file(resolved_plan):
                    errors.append("selected target production plan SHA-256 does not match")
                errors.extend(
                    _selection_receipt_errors(
                        path,
                        selected,
                        selection_gate=effective_selection_gate,
                        declared_research_fronts=declared_research_fronts,
                    )
                )
                selection_events = [
                    event for event in history
                    if isinstance(event, dict)
                    and event.get("event") == "target_selected"
                    and event.get("target_id") == selected.get("target_id")
                    and event.get("research_front") == selected.get("research_front")
                    and event.get("cycle") == selected.get("cycle")
                    and event.get("selection_receipt_sha256") == selected.get("selection_receipt_sha256")
                    and event.get("selection_gate_snapshot") == selected.get("selection_gate_snapshot")
                    and event.get("selection_plan_sha256") == selected.get("selection_plan_sha256")
                ]
                if len(selection_events) != 1:
                    errors.append("selected target lacks one matching target_selected history event")
            source_statement = selected.get("source_original_statement")
            target_statement = selected.get("frozen_target_statement")
            if _text(source_statement) and _text(target_statement):
                statements_match = _normalized_statement(
                    str(source_statement)
                ) == _normalized_statement(str(target_statement))
                if relation == "exact" and not statements_match:
                    errors.append(
                        "selected_target exact relation does not match its source statement"
                    )
                elif valid_relation and relation != "exact" and statements_match:
                    errors.append(
                        "selected_target matching statements must use target_relation=exact"
                    )
            if not _text(selected.get("amra_campaign")):
                errors.append("selected_target needs amra_campaign")
            else:
                try:
                    campaign_path = _selected_amra_path(path, lane)
                except StateError as exc:
                    errors.append(str(exc))
                    campaign_path = None
                if campaign_path is None:
                    contract_path = None
                else:
                    contract_path = campaign_path / "closure_contract.json"
                if contract_path is None:
                    pass
                elif not contract_path.is_file():
                    errors.append(f"selected AMRA closure contract does not exist: {contract_path}")
                else:
                    try:
                        contract = read_json(contract_path)
                    except StateError as exc:
                        errors.append(str(exc))
                    else:
                        for field in (
                            "source_original_statement",
                            "frozen_target_statement",
                            "target_relation",
                            "source",
                        ):
                            selected_value = selected.get(field)
                            contract_value = contract.get(field)
                            if field.endswith("_statement"):
                                matches = (
                                    _text(selected_value)
                                    and _text(contract_value)
                                    and _normalized_statement(str(selected_value))
                                    == _normalized_statement(str(contract_value))
                                )
                            else:
                                matches = selected_value == contract_value
                            if not matches:
                                errors.append(
                                    f"selected_target {field} does not match AMRA closure contract"
                                )
                        if selected.get("selection_basis") not in {
                            "operator_locked_route", "post_result_route_branch"
                        }:
                            authority = contract.get("source_authority")
                            internal_receipt = authority.get("selection_receipt") if isinstance(authority, dict) else None
                            if not isinstance(internal_receipt, dict) or internal_receipt.get("sha256") != selected.get("selection_receipt_sha256"):
                                errors.append("selected target receipt SHA-256 does not match AMRA source authority")
                        for error in _amra_validation_errors(campaign_path):
                            errors.append(f"selected AMRA integrity: {error}")
                        state_path = campaign_path / "campaign_state.json"
                        if not state_path.is_file():
                            errors.append(f"selected AMRA campaign state does not exist: {state_path}")
                        else:
                            try:
                                amra_state = read_json(state_path)
                            except StateError as exc:
                                errors.append(str(exc))
                            else:
                                expected_identity = {
                                    "campaign_id": (
                                        _slugify(str(selected["target_id"]))
                                        if _text(selected.get("target_id")) else None
                                    ),
                                    "problem_id": selected.get("problem_id"),
                                    "title": selected.get("title"),
                                }
                                for field, expected_value in expected_identity.items():
                                    if amra_state.get(field) != expected_value:
                                        errors.append(
                                            f"selected_target {field} does not match AMRA campaign state"
                                        )
            if (
                selection_mode == "operator_locked_route"
                and selected.get("selection_basis") != "operator_locked_route"
                and selected.get("selection_basis") != "post_result_route_branch"
            ):
                errors.append("operator-locked research needs a route selection_basis")
            if selection_mode == "operator_locked_route" and _text(lane.get("plan_path")):
                plan = read_json((path.parent / str(lane["plan_path"])).resolve())
                program = plan.get("program")
                north_star = program.get("north_star") if isinstance(program, dict) else None
                if isinstance(north_star, dict):
                    north_statement = north_star.get("statement")
                    if not (
                        _text(north_statement)
                        and _text(selected.get("source_original_statement"))
                        and _normalized_statement(str(north_statement))
                        == _normalized_statement(str(selected["source_original_statement"]))
                    ):
                        errors.append(
                            "operator route source statement does not match the plan north star"
                        )
                    if _text(north_star.get("source")) and north_star.get("source") != selected.get("source"):
                        errors.append("operator route source does not match the plan north star")
                    if _text(north_star.get("problem_id")) and north_star.get("problem_id") != selected.get("problem_id"):
                        errors.append("operator route problem_id does not match the plan north star")
            if selection_mode == "operator_locked_route" and isinstance(lane.get("route"), dict):
                route = lane["route"]
                if route.get("problem_id") != selected.get("problem_id"):
                    errors.append("operator selected target changed the route problem_id")
                if route.get("source") != selected.get("source"):
                    errors.append("operator selected target changed the route primary source")
                if not (
                    _text(route.get("source_original_statement"))
                    and _text(selected.get("source_original_statement"))
                    and _normalized_statement(str(route["source_original_statement"]))
                    == _normalized_statement(str(selected["source_original_statement"]))
                ):
                    errors.append("operator selected target changed the route source statement")
                event_name = (
                    "post_result_route_branch_started"
                    if selected.get("selection_basis") == "post_result_route_branch"
                    else "operator_route_locked"
                )
                route_events = [
                    event for event in history
                    if isinstance(event, dict)
                    and event.get("event") == event_name
                    and event.get("target_id") == selected.get("target_id")
                    and event.get("cycle") == selected.get("cycle")
                ]
                if len(route_events) != 1:
                    errors.append("operator selected target lacks one matching route history event")
    if selection_mode == "operator_locked_route" and not isinstance(lane.get("route"), dict):
        errors.append("operator-locked lane requires a route object")
    for index, archived in enumerate(lane.get("archived_targets", [])):
        if not isinstance(archived, dict):
            continue
        required_archive_fields = (
            "cycle", "target_id", "problem_id", "title", "source_original_statement",
            "frozen_target_statement", "target_relation", "source", "amra_campaign",
            "terminal_phase", "archive_snapshot_sha256",
        )
        for field in required_archive_fields:
            if field == "cycle":
                if not _positive_int(archived.get(field)):
                    errors.append(f"archived target {index}: {field} is required")
            elif not _text(archived.get(field)):
                errors.append(f"archived target {index}: {field} is required")
        archive_payload = dict(archived)
        recorded_archive_digest = archive_payload.pop("archive_snapshot_sha256", None)
        if recorded_archive_digest != _sha256_json(archive_payload):
            errors.append(f"archived target {index}: snapshot SHA-256 does not match")
        try:
            archived_path = _selected_amra_path(path, {"selected_target": archived})
        except StateError as exc:
            errors.append(f"archived target {index}: {exc}")
            continue
        state_path = archived_path / "campaign_state.json"
        if not state_path.is_file():
            errors.append(f"archived target {index}: missing AMRA campaign state")
            continue
        try:
            archived_state = read_json(state_path)
        except StateError as exc:
            errors.append(f"archived target {index}: {exc}")
            continue
        terminal_phase = archived.get("terminal_phase")
        if terminal_phase not in {"promotion", "frozen"} or archived_state.get("phase") != terminal_phase:
            errors.append(f"archived target {index}: terminal phase does not match AMRA state")
        if _text(archived.get("target_id")) and archived_state.get("campaign_id") != _slugify(str(archived["target_id"])):
            errors.append(f"archived target {index}: campaign_id does not match target_id")
        for field in ("problem_id", "title"):
            if archived_state.get(field) != archived.get(field):
                errors.append(f"archived target {index}: {field} does not match AMRA state")
        contract_path = archived_path / "closure_contract.json"
        if contract_path.is_file():
            try:
                archived_contract = read_json(contract_path)
            except StateError as exc:
                errors.append(f"archived target {index}: {exc}")
            else:
                for field in (
                    "source_original_statement", "frozen_target_statement",
                    "target_relation", "source",
                ):
                    observed = archived.get(field)
                    expected = archived_contract.get(field)
                    matches = (
                        _text(observed) and _text(expected)
                        and _normalized_statement(str(observed)) == _normalized_statement(str(expected))
                        if field.endswith("_statement") else observed == expected
                    )
                    if not matches:
                        errors.append(f"archived target {index}: {field} does not match AMRA contract")
                if archived.get("selection_basis") not in {
                    "operator_locked_route", "post_result_route_branch"
                }:
                    authority = archived_contract.get("source_authority")
                    internal_receipt = authority.get("selection_receipt") if isinstance(authority, dict) else None
                    if not isinstance(internal_receipt, dict) or internal_receipt.get("sha256") != archived.get("selection_receipt_sha256"):
                        errors.append(f"archived target {index}: selection receipt does not match AMRA authority")
        for error in _amra_validation_errors(
            archived_path,
            require_promotion_gate=terminal_phase == "promotion",
        ):
            errors.append(f"archived target {index}: {error}")
        archive_events = [
            event for event in history
            if isinstance(event, dict)
            and event.get("event") in {"post_result_route_branch_started", "lane_recycled"}
            and event.get("archived_target_id") == archived.get("target_id")
            and event.get("archive_snapshot_sha256") == recorded_archive_digest
        ]
        if len(archive_events) != 1:
            errors.append(f"archived target {index}: missing matching archive history event")
    archived_pairs = [
        (str(item.get("target_id")), str(item.get("archive_snapshot_sha256")))
        for item in lane.get("archived_targets", []) if isinstance(item, dict)
    ]
    if archived_pairs != replay_archives:
        errors.append("archived_targets do not match replayed archive history")
    target_by_cycle: dict[int, dict[str, Any]] = {
        int(item["cycle"]): item
        for item in lane.get("archived_targets", [])
        if isinstance(item, dict) and _positive_int(item.get("cycle"))
    }
    if isinstance(selected, dict) and _positive_int(selected.get("cycle")):
        target_by_cycle[int(selected["cycle"])] = selected
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        expected_phase = (
            "promotion" if node.get("outcome") == "promotion"
            else "frozen" if node.get("outcome") == "freeze"
            else None
        )
        if expected_phase is None:
            if node.get("progress_class") == "promotion":
                errors.append(f"lane node {index} uses promotion class without promotion outcome")
            continue
        if not _positive_int(node.get("cycle")):
            continue
        target = target_by_cycle.get(int(node["cycle"]))
        if target is None:
            errors.append(f"lane node {index} terminal outcome has no cycle target")
            continue
        try:
            target_path = _selected_amra_path(path, {"selected_target": target})
            target_state = read_json(target_path / "campaign_state.json")
        except StateError as exc:
            errors.append(f"lane node {index}: {exc}")
            continue
        if target_state.get("phase") != expected_phase:
            errors.append(f"lane node {index} terminal outcome does not match AMRA phase")
    if lane.get("stage") == "radar" and int(lane.get("cycle") or 0) > 1:
        recycle_events = [
            event for event in history
            if isinstance(event, dict)
            and event.get("event") == "lane_recycled"
            and event.get("next_cycle") == lane.get("cycle")
        ]
        if len(recycle_events) != 1:
            errors.append("radar cycle lacks one matching lane_recycled history event")
    if lane.get("stage") == "terminal":
        terminal_events = [
            event for event in history
            if isinstance(event, dict)
            and event.get("event") == "radar_exhausted_without_selection"
            and event.get("cycle") == lane.get("cycle")
        ]
        if len(terminal_events) != 1:
            errors.append("terminal lane lacks one matching exhaustion history event")
    if authority_plan is not None:
        plan_gate = authority_plan.get("selection_gate")
        lane_gate = lane.get("selection_gate")
        if isinstance(plan_gate, dict) and isinstance(lane_gate, dict):
            for plan_key, canonical_key in PLAN_SELECTION_GATE_MAP.items():
                plan_value = plan_gate.get(plan_key)
                if plan_value is None:
                    continue
                count_gate = canonical_key in {
                    "minimum_target_cards",
                    "minimum_distinct_research_fronts",
                }
                valid_plan_value = (
                    _positive_int(plan_value)
                    if count_gate
                    else isinstance(plan_value, int)
                    and not isinstance(plan_value, bool)
                    and plan_value >= 0
                )
                if not valid_plan_value:
                    errors.append(f"production plan selection_gate {plan_key} is invalid")
                    continue
                lane_value = lane_gate.get(canonical_key)
                if lane_value is not None and (
                    not isinstance(lane_value, int)
                    or isinstance(lane_value, bool)
                    or int(lane_value) < int(plan_value)
                ):
                    errors.append(
                        f"lane selection_gate {canonical_key} weakens the production plan"
                    )
                elif not count_gate and lane_value is None:
                    errors.append(
                        f"lane selection_gate {canonical_key} weakens the production plan"
                    )
        program = authority_plan.get("program")
        theorem_policy = (
            program.get("theorem_target_policy") if isinstance(program, dict) else None
        )
        if isinstance(theorem_policy, dict) and isinstance(lane.get("node_policy"), dict):
            for key in DEFAULT_NODE_POLICY:
                if isinstance(theorem_policy.get(key), int) and (
                    not isinstance(lane["node_policy"].get(key), int)
                    or int(lane["node_policy"][key]) > int(theorem_policy[key])
                ):
                    errors.append(f"lane node_policy {key} weakens the production plan")

    try:
        effective_node_policy = _effective_node_policy(path, lane)
        if not all(
            _positive_int(effective_node_policy.get(field))
            for field in DEFAULT_NODE_POLICY
        ):
            raise ValueError("effective node policy contains a non-positive limit")
        expected_continuation_gate = _expected_continuation_gate(
            lane, effective_node_policy
        )
    except (StateError, TypeError, ValueError) as exc:
        errors.append(f"cannot reduce continuation gate: {exc}")
    else:
        errors.extend(_continuation_transition_errors(lane, effective_node_policy))
        if lane.get("continuation_gate") != expected_continuation_gate:
            expected_status = (
                expected_continuation_gate.get("status")
                if isinstance(expected_continuation_gate, dict)
                else "absent"
            )
            errors.append(
                "lane continuation_gate does not match the node-derived state "
                f"(expected {expected_status})"
            )
    return errors


def _score_payload(args: argparse.Namespace) -> dict[str, int]:
    scores = {name: int(getattr(args, name)) for name in SCORE_MAXIMA}
    for name, maximum in SCORE_MAXIMA.items():
        if not 0 <= scores[name] <= maximum:
            raise StateError(f"{name} score must be between 0 and {maximum}")
    scores["total"] = sum(scores.values())
    return scores


def _check_selection_gate(gate: dict[str, Any], scores: dict[str, int]) -> None:
    for key in ("total", "novelty", "significance", "closure"):
        minimum = gate.get(f"minimum_{key}")
        if not isinstance(minimum, int):
            raise StateError(f"selection gate minimum_{key} must be an integer")
        if scores[key] < minimum:
            raise StateError(f"selection failed: {key} {scores[key]} < {minimum}")


def select_target(args: argparse.Namespace) -> dict[str, Any]:
    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane["stage"] != "radar" or lane.get("selected_target") is not None:
        raise StateError("target selection requires an empty radar-stage lane")
    if lane.get("selection_mode", "radar_scored") != "radar_scored":
        raise StateError("score-based select is forbidden for an operator-locked route")
    if args.blocking_novelty_risk:
        raise StateError("a target with blocking novelty risk cannot be selected")
    if args.target_relation != "exact":
        raise StateError(
            "radar-scored open-problem selection requires target_relation=exact; "
            "use an explicitly scoped route or post-result branch for a non-exact theorem"
        )
    if args.selection_receipt is None:
        raise StateError(
            "radar-scored open-problem selection requires a hash-bound selection.json receipt"
        )
    receipt_path = args.selection_receipt.resolve()
    receipt_binding = {
        "selection_receipt": os.path.relpath(receipt_path, lane_path.parent),
        "selection_receipt_sha256": (
            _sha256_file(receipt_path) if receipt_path.is_file() else ""
        ),
    }
    plan_path, authority_plan = _lane_authority_plan(lane_path, lane)
    effective_selection_gate = _effective_selection_gate(
        lane_path,
        lane,
        authority_plan=authority_plan,
    )
    selection_plan_sha256 = _sha256_file(plan_path)
    declared_research_fronts = _declared_research_fronts(authority_plan)
    receipt_payload = read_json(receipt_path)
    research_front = receipt_payload.get("research_front")
    scores = _score_payload(args)
    receipt_expected = {
        "target_id": args.target_id,
        "problem_id": args.problem_id,
        "title": args.title,
        "source_original_statement": args.source_statement,
        "frozen_target_statement": args.target_statement,
        "target_relation": args.target_relation,
        "source": args.source,
        "research_front": research_front,
        "selection_plan_sha256": selection_plan_sha256,
        "scores": scores,
        "selection_gate_snapshot": effective_selection_gate,
        **receipt_binding,
    }
    receipt_errors = _selection_receipt_errors(
        lane_path,
        receipt_expected,
        selection_gate=effective_selection_gate,
        declared_research_fronts=declared_research_fronts,
    )
    if receipt_errors:
        raise StateError("selection receipt failed: " + "; ".join(receipt_errors))
    _check_selection_gate(effective_selection_gate, scores)

    amra = _load_amra_loop_core()

    research_root = lane_path.parent / "research" / f"cycle-{int(lane['cycle']):03d}"
    try:
        campaign = amra.init_campaign(
            research_root,
            campaign_id=args.target_id,
            problem_id=args.problem_id,
            title=args.title,
            source_original_statement=args.source_statement,
            frozen_target_statement=args.target_statement,
            target_relation=args.target_relation,
            source=args.source,
            source_authority_receipt=receipt_path,
        )
    except amra.CampaignError as exc:
        raise StateError(str(exc)) from exc

    now = utc_now()
    lane["stage"] = "research"
    lane["selected_target"] = {
        "cycle": lane["cycle"],
        "target_id": args.target_id,
        "problem_id": args.problem_id,
        "title": args.title,
        "source_original_statement": args.source_statement,
        "frozen_target_statement": args.target_statement,
        "target_relation": args.target_relation,
        "source": args.source,
        "research_front": research_front,
        **receipt_binding,
        "first_kill_test": args.first_kill_test,
        "scores": scores,
        "selection_gate_snapshot": effective_selection_gate,
        "selection_plan_sha256": selection_plan_sha256,
        "selected_at": now,
        "amra_campaign": campaign.relative_to(lane_path.parent).as_posix(),
    }
    lane.setdefault("history", []).append(
        {
            "at": now,
            "event": "target_selected",
            "cycle": lane["cycle"],
            "target_id": args.target_id,
            "research_front": research_front,
            "scores": scores,
            "selection_receipt_sha256": receipt_binding["selection_receipt_sha256"],
            "selection_gate_snapshot": effective_selection_gate,
            "selection_plan_sha256": selection_plan_sha256,
        }
    )
    preflight_errors = _prospective_lane_errors(lane_path, lane)
    if preflight_errors:
        shutil.rmtree(campaign, ignore_errors=True)
        raise StateError("selected lane preflight failed: " + "; ".join(preflight_errors))
    try:
        atomic_write_json(lane_path, lane)
    except Exception:
        shutil.rmtree(campaign, ignore_errors=True)
        raise
    return lane["selected_target"]


def lock_route(args: argparse.Namespace) -> dict[str, Any]:
    """Initialize an administrator-chosen research route without candidate scoring."""

    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane.get("selection_mode") != "operator_locked_route":
        raise StateError("lock-route requires selection_mode=operator_locked_route")
    if lane["stage"] != "radar" or lane.get("selected_target") is not None:
        raise StateError("lock-route requires an empty initialization-stage lane")
    if args.target_relation == "exact" and args.selection_receipt is None:
        raise StateError("an exact operator route requires a primary-source selection receipt")

    amra = _load_amra_loop_core()

    research_root = lane_path.parent / "research" / f"cycle-{int(lane['cycle']):03d}"
    try:
        campaign = amra.init_campaign(
            research_root,
            campaign_id=args.target_id,
            problem_id=args.problem_id,
            title=args.title,
            source_original_statement=args.source_statement,
            frozen_target_statement=args.target_statement,
            target_relation=args.target_relation,
            source=args.source,
            source_authority_receipt=args.selection_receipt,
        )
    except amra.CampaignError as exc:
        raise StateError(str(exc)) from exc

    now = utc_now()
    lane["stage"] = "research"
    lane.setdefault("route", {}).update(
        {
            "problem_id": args.problem_id,
            "source_original_statement": args.source_statement,
            "source": args.source,
        }
    )
    lane["selected_target"] = {
        "cycle": lane["cycle"],
        "target_id": args.target_id,
        "problem_id": args.problem_id,
        "title": args.title,
        "source_original_statement": args.source_statement,
        "frozen_target_statement": args.target_statement,
        "target_relation": args.target_relation,
        "source": args.source,
        "route_frontier": args.frontier,
        "first_kill_test": args.first_kill_test,
        "selection_basis": "operator_locked_route",
        "selected_at": now,
        "amra_campaign": campaign.relative_to(lane_path.parent).as_posix(),
    }
    lane.setdefault("history", []).append(
        {
            "at": now,
            "event": "operator_route_locked",
            "cycle": lane["cycle"],
            "target_id": args.target_id,
            "candidate_scoring": "not_performed",
        }
    )
    lane["updated_at"] = now
    preflight_errors = _prospective_lane_errors(lane_path, lane)
    if preflight_errors:
        shutil.rmtree(campaign, ignore_errors=True)
        raise StateError("operator route preflight failed: " + "; ".join(preflight_errors))
    try:
        atomic_write_json(lane_path, lane)
    except Exception:
        shutil.rmtree(campaign, ignore_errors=True)
        raise
    return lane["selected_target"]


def record_node(args: argparse.Namespace) -> dict[str, Any]:
    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane["stage"] == "terminal":
        raise StateError("cannot record work on a terminal lane")
    node_policy = _effective_node_policy(lane_path, lane)
    continuation_gate = lane.get("continuation_gate")
    if isinstance(continuation_gate, dict):
        gate_status = continuation_gate.get("status")
        if (
            gate_status == "freeze_required"
            and args.outcome not in {"promotion", "freeze"}
            and args.delta_kind not in THEOREM_DELTAS
        ):
            raise StateError("the lane requires AMRA freeze before any further research node")
        if gate_status == "independent_audit_required" and args.outcome not in {
            "promotion",
            "freeze",
        }:
            raise StateError(
                "the theorem delta requires an independent audit before further research"
            )
    if (
        lane["stage"] == "research"
        and args.outcome not in {"promotion", "freeze"}
        and args.delta_kind not in THEOREM_DELTAS
    ):
        existing_budget = _research_budget_metrics(lane, node_policy)
        if existing_budget["freeze_reasons"]:
            raise StateError(
                "the existing lane history requires AMRA freeze before further research: "
                + ", ".join(existing_budget["freeze_reasons"])
            )
    if lane["stage"] == "radar" and lane.get("selected_target") is None:
        if args.outcome != "no_progress":
            raise StateError("an unselected radar pass can only be recorded as no_progress")
    if lane["stage"] == "research" and args.outcome in {"promotion", "freeze"}:
        expected_phase = "promotion" if args.outcome == "promotion" else "frozen"
        actual_phase = _selected_amra_phase(lane_path, lane)
        if actual_phase != expected_phase:
            raise StateError(
                f"cannot record {args.outcome}: selected AMRA campaign is {actual_phase}, "
                f"not {expected_phase}"
            )
        terminal_errors = _amra_validation_errors(
            _selected_amra_path(lane_path, lane),
            require_promotion_gate=args.outcome == "promotion",
        )
        if terminal_errors:
            raise StateError(
                f"cannot record {args.outcome}: AMRA gate failed: "
                + "; ".join(terminal_errors)
            )
    if args.outcome == "progress":
        if args.delta_kind not in EPISTEMIC_DELTAS:
            raise StateError(
                "progress requires an epistemic delta-kind: "
                + ", ".join(sorted(EPISTEMIC_DELTAS))
            )
        if not args.evidence:
            raise StateError("progress requires at least one evidence path")
    theorem_fields = {
        "statement": getattr(args, "theorem_statement", None),
        "scope": getattr(args, "theorem_scope", None),
        "consequence": getattr(args, "theorem_consequence", None),
    }
    if args.delta_kind in THEOREM_DELTAS:
        missing = [name for name, value in theorem_fields.items() if not _text(value)]
        if missing:
            raise StateError(
                "theorem delta requires --theorem-statement, --theorem-scope, and "
                "--theorem-consequence"
            )
    elif any(_text(value) for value in theorem_fields.values()):
        raise StateError("theorem metadata is only valid for a theorem delta-kind")
    if args.outcome == "promotion":
        progress_class = "promotion"
    elif args.outcome == "progress" and args.delta_kind in THEOREM_DELTAS:
        progress_class = "theorem"
    elif args.outcome == "progress":
        progress_class = "search"
    else:
        progress_class = "none"
    now = utc_now()
    entry = {
        "at": now,
        "cycle": lane["cycle"],
        "outcome": args.outcome,
        "delta_kind": args.delta_kind,
        "progress_class": progress_class,
        "summary": args.summary,
        "evidence": list(args.evidence or []),
    }
    if progress_class == "theorem":
        entry["theorem"] = theorem_fields
    lane.setdefault("nodes", []).append(entry)
    consecutive = 0
    for node in reversed(lane["nodes"]):
        if node.get("cycle") != lane["cycle"] or node.get("outcome") != "no_progress":
            break
        consecutive += 1
    limit = int(
        node_policy.get(
            "consecutive_no_progress_limit",
            DEFAULT_NODE_POLICY["consecutive_no_progress_limit"],
        )
    )
    radar_nodes = sum(
        1
        for node in lane["nodes"]
        if node.get("cycle") == lane["cycle"] and node.get("stage", "radar") == "radar"
    ) if lane["stage"] == "radar" else 0
    radar_limit = int(
        node_policy.get(
            "max_radar_nodes_per_cycle",
            DEFAULT_NODE_POLICY["max_radar_nodes_per_cycle"],
        )
    )
    radar_exhausted = lane["stage"] == "radar" and radar_nodes >= radar_limit
    if radar_exhausted:
        lane["stage"] = "terminal"
        lane.setdefault("history", []).append(
            {
                "at": now,
                "event": "radar_exhausted_without_selection",
                "cycle": lane["cycle"],
                "radar_nodes": radar_nodes,
            }
        )
    research_nodes = 0
    consecutive_without_theorem_delta = 0
    if lane["stage"] == "research":
        budget_metrics = _research_budget_metrics(lane, node_policy)
        research_nodes = int(budget_metrics["research_nodes"])
        consecutive_without_theorem_delta = int(
            budget_metrics["consecutive_without_theorem_delta"]
        )
    theorem_limit = int(
        node_policy.get(
            "max_nodes_without_theorem_delta",
            DEFAULT_NODE_POLICY["max_nodes_without_theorem_delta"],
        )
    )
    research_limit = int(
        node_policy.get(
            "max_research_nodes_per_target",
            DEFAULT_NODE_POLICY["max_research_nodes_per_target"],
        )
    )
    theorem_stalled = (
        lane["stage"] == "research"
        and consecutive_without_theorem_delta >= theorem_limit
    )
    target_budget_exhausted = (
        lane["stage"] == "research"
        and research_nodes >= research_limit
        and progress_class != "theorem"
    )
    no_progress_freeze = lane["stage"] == "research" and consecutive >= limit
    audit_required = lane["stage"] == "research" and progress_class == "theorem"
    freeze_reasons: list[str] = []
    if no_progress_freeze:
        freeze_reasons.append("consecutive_no_progress_limit")
    if theorem_stalled:
        freeze_reasons.append("max_nodes_without_theorem_delta")
    if target_budget_exhausted:
        freeze_reasons.append("max_research_nodes_per_target")
    if args.outcome == "freeze":
        lane["continuation_gate"] = {
            "status": "branch_or_terminal_required",
            "set_at": now,
            "cycle": lane["cycle"],
        }
    elif freeze_reasons:
        lane["continuation_gate"] = {
            "status": "freeze_required",
            "set_at": now,
            "cycle": lane["cycle"],
            "reasons": freeze_reasons,
        }
    elif audit_required:
        lane["continuation_gate"] = {
            "status": "independent_audit_required",
            "set_at": now,
            "cycle": lane["cycle"],
            "theorem_delta": args.delta_kind,
        }
    elif args.outcome == "promotion":
        lane.pop("continuation_gate", None)
    lane["consecutive_no_progress"] = consecutive
    lane["consecutive_without_theorem_delta"] = consecutive_without_theorem_delta
    lane["updated_at"] = now
    preflight_errors = _prospective_lane_errors(lane_path, lane)
    if preflight_errors:
        raise StateError("research-node lane preflight failed: " + "; ".join(preflight_errors))
    atomic_write_json(lane_path, lane)
    return {
        "node": entry,
        "consecutive_no_progress": consecutive,
        "limit": limit,
        "freeze_required": bool(freeze_reasons),
        "freeze_reasons": freeze_reasons,
        "progress_class": progress_class,
        "audit_required": audit_required,
        "consecutive_without_theorem_delta": consecutive_without_theorem_delta,
        "theorem_delta_limit": theorem_limit,
        "research_nodes": research_nodes,
        "research_node_limit": research_limit,
        "target_budget_exhausted": target_budget_exhausted,
        "radar_nodes": radar_nodes,
        "radar_limit": radar_limit,
        "radar_exhausted": radar_exhausted,
        "stage": lane["stage"],
    }


def branch_route(args: argparse.Namespace) -> dict[str, Any]:
    """Start a new evidence-driven target inside an already locked route."""

    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane.get("selection_mode") != "operator_locked_route":
        raise StateError("branch-route requires an operator-locked route")
    selected = lane.get("selected_target")
    if not isinstance(selected, dict):
        raise StateError("branch-route requires a current selected target")
    amra_path = _selected_amra_path(lane_path, lane)
    state = read_json(amra_path / "campaign_state.json")
    if state.get("phase") not in {"frozen", "promotion"}:
        raise StateError("finish, freeze, or promote the current AMRA target before branching")
    terminal_errors = _amra_validation_errors(
        amra_path, require_promotion_gate=state.get("phase") == "promotion"
    )
    if terminal_errors:
        raise StateError("current AMRA terminal gate failed: " + "; ".join(terminal_errors))
    if _normalized_statement(args.target_statement) == _normalized_statement(
        str(selected.get("frozen_target_statement", ""))
    ):
        raise StateError("a route branch must change the exact target statement")
    route = lane.get("route", {})
    if args.problem_id != route.get("problem_id"):
        raise StateError("a route branch must retain the original problem_id")
    if _normalized_statement(args.source_statement) != _normalized_statement(
        str(route.get("source_original_statement", ""))
    ):
        raise StateError("a route branch must retain the source-original statement")
    if args.source != route.get("source"):
        raise StateError("a route branch must retain the original primary source")
    if state.get("phase") == "frozen":
        if not _text(args.amendment) or not _text(args.defect_addressed):
            raise StateError(
                "branching after freeze requires --amendment and --defect-addressed"
            )
        consecutive_frozen = 1
        for prior in reversed(lane.get("archived_targets", [])):
            if prior.get("terminal_phase") == "promotion":
                break
            if prior.get("terminal_phase") != "frozen":
                break
            consecutive_frozen += 1
        branch_limit = int(
            _effective_node_policy(lane_path, lane)[
                "max_frozen_branches_without_promotion"
            ]
        )
        if consecutive_frozen >= branch_limit:
            raise StateError(
                "route branch limit reached after consecutive frozen targets; "
                "close the lane or obtain an independently audited promotion"
            )

    amra = _load_amra_loop_core()

    now = utc_now()
    archived = dict(selected)
    archived.update(
        {
            "terminal_phase": state["phase"],
            "branched_at": now,
            "branch_reason": args.reason,
        }
    )
    archived["archive_snapshot_sha256"] = _sha256_json(archived)
    lane.setdefault("archived_targets", []).append(archived)
    lane["cycle"] = int(lane["cycle"]) + 1
    research_root = lane_path.parent / "research" / f"cycle-{int(lane['cycle']):03d}"
    try:
        campaign = amra.init_campaign(
            research_root,
            campaign_id=args.target_id,
            problem_id=args.problem_id,
            title=args.title,
            source_original_statement=args.source_statement,
            frozen_target_statement=args.target_statement,
            target_relation=args.target_relation,
            source=args.source,
            source_authority_receipt=args.selection_receipt,
        )
    except amra.CampaignError as exc:
        raise StateError(str(exc)) from exc
    lane["stage"] = "research"
    lane["consecutive_no_progress"] = 0
    lane["consecutive_without_theorem_delta"] = 0
    lane.pop("continuation_gate", None)
    lane["selected_target"] = {
        "cycle": lane["cycle"],
        "target_id": args.target_id,
        "problem_id": args.problem_id,
        "title": args.title,
        "source_original_statement": args.source_statement,
        "frozen_target_statement": args.target_statement,
        "target_relation": args.target_relation,
        "source": args.source,
        "route_frontier": lane.get("route", {}).get("frontier", ""),
        "first_kill_test": args.first_kill_test,
        "selection_basis": "post_result_route_branch",
        "predecessor_target_id": selected.get("target_id"),
        "branch_amendment": args.amendment,
        "defect_addressed": args.defect_addressed,
        "selected_at": now,
        "amra_campaign": campaign.relative_to(lane_path.parent).as_posix(),
    }
    lane["updated_at"] = now
    lane.setdefault("history", []).append(
        {
            "at": now,
            "event": "post_result_route_branch_started",
            "cycle": lane["cycle"],
            "previous_cycle": archived.get("cycle"),
            "target_id": args.target_id,
            "reason": args.reason,
            "amendment": args.amendment,
            "defect_addressed": args.defect_addressed,
            "candidate_scoring": "not_performed",
            "archived_target_id": archived.get("target_id"),
            "archive_snapshot_sha256": archived["archive_snapshot_sha256"],
        }
    )
    preflight_errors = _prospective_lane_errors(lane_path, lane)
    if preflight_errors:
        shutil.rmtree(campaign, ignore_errors=True)
        raise StateError("route branch preflight failed: " + "; ".join(preflight_errors))
    try:
        atomic_write_json(lane_path, lane)
    except Exception:
        shutil.rmtree(campaign, ignore_errors=True)
        raise
    return lane["selected_target"]


def recycle_lane(args: argparse.Namespace) -> dict[str, Any]:
    lane_path = args.lane.resolve()
    lane = read_json(lane_path)
    errors = validate_lane(lane_path)
    if errors:
        raise StateError("; ".join(errors))
    if lane.get("selection_mode", "radar_scored") == "operator_locked_route":
        raise StateError(
            "operator-locked routes cannot recycle into candidate radar; "
            "start a post-result branch inside the same route"
        )
    selected = lane.get("selected_target")
    if not isinstance(selected, dict):
        raise StateError("cannot recycle a lane without a selected target")
    amra_path = (lane_path.parent / str(selected["amra_campaign"])).resolve()
    state = read_json(amra_path / "campaign_state.json")
    if state.get("phase") not in {"frozen", "promotion"}:
        raise StateError("freeze or promote the AMRA campaign before recycling the lane")
    terminal_errors = _amra_validation_errors(
        amra_path, require_promotion_gate=state.get("phase") == "promotion"
    )
    if terminal_errors:
        raise StateError("current AMRA terminal gate failed: " + "; ".join(terminal_errors))
    now = utc_now()
    archived = dict(selected)
    archived.update({"terminal_phase": state["phase"], "recycled_at": now, "reason": args.reason})
    archived["archive_snapshot_sha256"] = _sha256_json(archived)
    lane.setdefault("archived_targets", []).append(archived)
    lane["selected_target"] = None
    lane["stage"] = "radar"
    lane["cycle"] = int(lane["cycle"]) + 1
    lane["consecutive_no_progress"] = 0
    lane["consecutive_without_theorem_delta"] = 0
    lane.pop("continuation_gate", None)
    lane["updated_at"] = now
    lane.setdefault("history", []).append({
        "at": now,
        "event": "lane_recycled",
        "reason": args.reason,
        "previous_cycle": archived.get("cycle"),
        "next_cycle": lane["cycle"],
        "archived_target_id": archived.get("target_id"),
        "archive_snapshot_sha256": archived["archive_snapshot_sha256"],
    })
    preflight_errors = _prospective_lane_errors(lane_path, lane)
    if preflight_errors:
        raise StateError("lane recycle preflight failed: " + "; ".join(preflight_errors))
    atomic_write_json(lane_path, lane)
    return {"stage": lane["stage"], "cycle": lane["cycle"], "archived_target": archived}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--plan", type=Path)
    validate.add_argument("--lane", type=Path)

    status = commands.add_parser("status")
    status.add_argument("--lane", type=Path, required=True)

    select = commands.add_parser("select")
    select.add_argument("--lane", type=Path, required=True)
    select.add_argument("--target-id", required=True)
    select.add_argument("--problem-id", required=True)
    select.add_argument("--title", required=True)
    select.add_argument("--source-statement", required=True)
    select.add_argument("--target-statement", required=True)
    select.add_argument(
        "--target-relation",
        choices=("exact", "specialization", "strengthening", "partial"),
        required=True,
    )
    select.add_argument("--source", required=True)
    select.add_argument("--selection-receipt", type=Path)
    select.add_argument("--first-kill-test", required=True)
    for name in SCORE_MAXIMA:
        select.add_argument(f"--{name.replace('_', '-')}", dest=name, type=int, required=True)
    select.add_argument("--blocking-novelty-risk", action="store_true")

    lock = commands.add_parser("lock-route")
    lock.add_argument("--lane", type=Path, required=True)
    lock.add_argument("--target-id", required=True)
    lock.add_argument("--problem-id", required=True)
    lock.add_argument("--title", required=True)
    lock.add_argument("--source-statement", required=True)
    lock.add_argument("--target-statement", required=True)
    lock.add_argument(
        "--target-relation",
        choices=("exact", "specialization", "strengthening", "partial"),
        required=True,
    )
    lock.add_argument("--source", required=True)
    lock.add_argument("--selection-receipt", type=Path)
    lock.add_argument("--frontier", required=True)
    lock.add_argument("--first-kill-test", required=True)

    branch = commands.add_parser("branch-route")
    branch.add_argument("--lane", type=Path, required=True)
    branch.add_argument("--target-id", required=True)
    branch.add_argument("--problem-id", required=True)
    branch.add_argument("--title", required=True)
    branch.add_argument("--source-statement", required=True)
    branch.add_argument("--target-statement", required=True)
    branch.add_argument(
        "--target-relation",
        choices=("exact", "specialization", "strengthening", "partial"),
        required=True,
    )
    branch.add_argument("--source", required=True)
    branch.add_argument("--selection-receipt", type=Path)
    branch.add_argument("--first-kill-test", required=True)
    branch.add_argument("--reason", required=True)
    branch.add_argument("--amendment")
    branch.add_argument("--defect-addressed")

    record = commands.add_parser("record-node")
    record.add_argument("--lane", type=Path, required=True)
    record.add_argument("--outcome", choices=sorted(NODE_OUTCOMES), required=True)
    record.add_argument("--delta-kind", default="none")
    record.add_argument("--summary", required=True)
    record.add_argument("--evidence", action="append", default=[])
    record.add_argument("--theorem-statement")
    record.add_argument("--theorem-scope")
    record.add_argument("--theorem-consequence")

    recycle = commands.add_parser("recycle")
    recycle.add_argument("--lane", type=Path, required=True)
    recycle.add_argument("--reason", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            if bool(args.plan) == bool(args.lane):
                raise StateError("provide exactly one of --plan or --lane")
            errors = validate_plan(args.plan.resolve()) if args.plan else validate_lane(args.lane.resolve())
            payload = {"valid": not errors, "errors": errors}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        if args.command == "status":
            lane = read_json(args.lane.resolve())
            errors = validate_lane(args.lane.resolve())
            budget = None
            if not errors and lane.get("stage") == "research":
                policy = _effective_node_policy(args.lane.resolve(), lane)
                budget = _research_budget_metrics(lane, policy)
            print(
                json.dumps(
                    {
                        "valid": not errors,
                        "errors": errors,
                        "research_budget": budget,
                        "lane": lane,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1 if errors else 0
        if args.command == "select":
            payload = select_target(args)
        elif args.command == "lock-route":
            payload = lock_route(args)
        elif args.command == "branch-route":
            payload = branch_route(args)
        elif args.command == "record-node":
            payload = record_node(args)
        elif args.command == "recycle":
            payload = recycle_lane(args)
        else:  # pragma: no cover
            raise AssertionError(args.command)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except StateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
