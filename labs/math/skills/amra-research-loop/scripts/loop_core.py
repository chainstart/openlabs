"""Independent state machine for mechanism-first mathematics campaigns."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from hashlib import sha256
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "amra-research-loop.v2"
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
    "scoped_theorem_proved",
    "main_term_improved",
    "main_exponent_improved",
    "global_interface_closed",
    "standalone_decisive_lemma",
}
TARGET_RELATIONS = {"exact", "specialization", "strengthening", "partial"}
MECHANISM_STATUSES = {"candidate", "killed", "surviving", "proved", "frozen"}
SOURCE_AUTHORITY_SCHEMA = "openlabs.amra_source_authority.v1"
SELECTION_RECEIPT_SCHEMA = "openlabs.math_target_selection.v1"
OPEN_SOURCE_STATUSES = {"open_problem", "open_conjecture"}
SELECTION_SCORE_MAXIMA = {
    "novelty": 25, "significance": 25, "closure": 20,
    "auditability": 15, "generality": 10, "venue_fit": 5,
}
CONTROL_PLANE_DATA_ROOT = Path(__file__).resolve().parents[6] / "openlabs-data"


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
    """Atomically replace one JSON artifact after flushing its complete payload."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
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


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _migration_paths(campaign_dir: Path) -> tuple[Path, Path]:
    parent = campaign_dir.parent
    return (
        parent / f".{campaign_dir.name}.migration-backup",
        parent / f".{campaign_dir.name}.migration-journal.json",
    )


def _archive_migration_backup(backup: Path, campaign_dir: Path) -> Path:
    archive_root = campaign_dir.parent / ".migration-archives"
    archive_root.mkdir(exist_ok=True)
    token = utc_now().replace(":", "").replace("+", "-")
    destination = archive_root / f"{campaign_dir.name}-{token}"
    counter = 1
    while destination.exists():
        destination = archive_root / f"{campaign_dir.name}-{token}-{counter}"
        counter += 1
    os.replace(backup, destination)
    _fsync_directory(campaign_dir.parent)
    return destination


def _recover_campaign_migration(campaign_dir: Path) -> None:
    """Recover the two-rename migration window before attempting to load state."""

    backup, journal_path = _migration_paths(campaign_dir)
    if not journal_path.exists():
        if backup.exists() and not campaign_dir.exists():
            os.replace(backup, campaign_dir)
            _fsync_directory(campaign_dir.parent)
        elif backup.exists() and campaign_dir.exists():
            raise CampaignError(f"unresolved migration backup without journal: {backup}")
        return
    journal = read_json(journal_path)
    if not isinstance(journal, dict):
        raise CampaignError(f"invalid migration journal: {journal_path}")
    if journal.get("campaign") != str(campaign_dir):
        raise CampaignError("migration journal campaign binding does not match")
    # The journal's staging path is informational only. Recovery never deletes
    # or writes through a path supplied by journal contents.
    if not campaign_dir.exists() and backup.exists():
        os.replace(backup, campaign_dir)
        _fsync_directory(campaign_dir.parent)
    elif campaign_dir.exists() and backup.exists():
        try:
            state = read_json(campaign_dir / "campaign_state.json")
        except CampaignError:
            state = {}
        identity_matches = (
            isinstance(state, dict)
            and state.get("statement_identity") == journal.get("statement_identity")
        )
        # A matching state file alone is not a committed transaction. The
        # second directory rename can expose a truncated staged tree before
        # the process dies, so validate the complete live candidate before
        # archiving the untouched backup.
        candidate_errors = (
            validate_campaign_integrity(campaign_dir)
            if identity_matches
            else ["statement identity mismatch"]
        )
        if identity_matches and not candidate_errors:
            _archive_migration_backup(backup, campaign_dir)
        else:
            failed_root = campaign_dir.parent / ".migration-failed"
            failed_root.mkdir(exist_ok=True)
            failed = failed_root / f"{campaign_dir.name}-{utc_now().replace(':', '')}"
            os.replace(campaign_dir, failed)
            os.replace(backup, campaign_dir)
            _fsync_directory(campaign_dir.parent)
    journal_path.unlink(missing_ok=True)
    _fsync_directory(campaign_dir.parent)


def _normalized_statement(value: str) -> str:
    """Normalize layout only; mathematical wording remains part of statement identity."""

    return " ".join(value.split())


def _statement_digest(value: str) -> str:
    return sha256(_normalized_statement(value).encode("utf-8")).hexdigest()


def _text_digest(value: str) -> str:
    return sha256(value.strip().encode("utf-8")).hexdigest()


def _json_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _make_statement_identity(
    *,
    source_original_statement: str,
    frozen_target_statement: str,
    target_relation: str,
    success_condition: str,
    source: str,
    problem_id: str,
    title: str,
    gates: dict[str, Any],
    source_authority: dict[str, Any] | None,
) -> dict[str, str]:
    """Freeze both theorem scope and the provenance/policy that guards it."""

    return {
        "source_original_sha256": _statement_digest(source_original_statement),
        "frozen_target_sha256": _statement_digest(frozen_target_statement),
        "target_relation": target_relation,
        "success_condition": success_condition,
        "source_locator_sha256": _text_digest(source),
        "problem_id_sha256": _text_digest(problem_id),
        "title_sha256": _text_digest(title),
        "gate_policy_sha256": _json_digest(gates),
        "source_authority_sha256": _json_digest(source_authority),
    }


def _checked_at_is_fresh(value: Any, errors: list[str], label: str) -> None:
    try:
        checked = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            raise ValueError("timezone required")
        age = datetime.now(timezone.utc) - checked.astimezone(timezone.utc)
        if age.total_seconds() < -86400:
            errors.append(f"{label} is dated in the future")
        elif age.days > 30:
            errors.append(f"{label} is older than 30 days")
    except (TypeError, ValueError):
        errors.append(f"{label} must be a timezone-aware timestamp")


def _checked_at_matches_selection(
    value: Any,
    created_at: Any,
    errors: list[str],
    label: str,
) -> None:
    """Check freshness at selection time without expiring historical campaigns."""

    try:
        checked = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if checked.tzinfo is None or created.tzinfo is None:
            raise ValueError("timezone required")
        age = created.astimezone(timezone.utc) - checked.astimezone(timezone.utc)
        if age.total_seconds() < -86400:
            errors.append(f"{label} postdates campaign selection by more than one day")
        elif age.days > 30:
            errors.append(f"{label} was already older than 30 days at selection")
    except (TypeError, ValueError):
        errors.append(f"{label} and campaign created_at must be timezone-aware timestamps")


def _read_bound_input_file(
    receipt_dir: Path,
    reference: Any,
    label: str,
) -> Path:
    if not isinstance(reference, dict):
        raise CampaignError(f"{label} must be a path/SHA-256 object")
    path_value = reference.get("path")
    digest = reference.get("sha256")
    if not _text(path_value) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CampaignError(f"{label} needs a relative path and lowercase SHA-256")
    relative = Path(str(path_value))
    if relative.is_absolute():
        raise CampaignError(f"{label} path must be relative to the selection receipt")
    resolved = (receipt_dir / relative).resolve()
    try:
        resolved.relative_to(receipt_dir.resolve())
    except ValueError as exc:
        raise CampaignError(f"{label} path escapes the selection bundle") from exc
    if not resolved.is_file() or _file_digest(resolved) != digest:
        raise CampaignError(f"{label} is missing or its SHA-256 does not match")
    return resolved


def _target_card_errors(
    candidate: Any,
    index: int,
    *,
    require_research_front: bool = False,
) -> list[str]:
    """Require each comparison card to be an exact, genuine open-source target."""

    prefix = f"target card {index}"
    if not isinstance(candidate, dict):
        return [f"{prefix} is not an object"]
    required_text = (
        "target_id", "problem_id", "title", "source_original_statement",
        "frozen_target_statement", "source", "source_locator",
        "closest_published_result",
    )
    errors = [
        f"{prefix} needs {field}"
        for field in required_text
        if not _text(candidate.get(field))
    ]
    if candidate.get("target_relation") != "exact":
        errors.append(f"{prefix} must preserve an exact source-original target")
    if candidate.get("public_status") not in OPEN_SOURCE_STATUSES:
        errors.append(f"{prefix} must be an open problem or open conjecture")
    if (
        _text(candidate.get("source_original_statement"))
        and _text(candidate.get("frozen_target_statement"))
        and _normalized_statement(str(candidate["source_original_statement"]))
        != _normalized_statement(str(candidate["frozen_target_statement"]))
    ):
        errors.append(f"{prefix} narrows or changes the source-original statement")
    if candidate.get("blocking_novelty_risk") is not False:
        errors.append(f"{prefix} must clear blocking novelty risk")
    score = candidate.get("score_vector")
    if not isinstance(score, dict) or not all(
        isinstance(score.get(field), int)
        and not isinstance(score.get(field), bool)
        and 0 <= int(score[field]) <= maximum
        for field, maximum in SELECTION_SCORE_MAXIMA.items()
    ) or not isinstance(score.get("total"), int) or isinstance(score.get("total"), bool):
        errors.append(f"{prefix} needs a complete bounded integer score_vector")
    elif score["total"] != sum(int(score[field]) for field in SELECTION_SCORE_MAXIMA):
        errors.append(f"{prefix} score total is inconsistent")
    if require_research_front and not _text(candidate.get("research_front")):
        errors.append(f"{prefix} needs a research_front")
    return errors


def _install_source_authority(
    *,
    receipt_path: Path,
    campaign_dir: Path,
    campaign_id: str,
    problem_id: str,
    title: str,
    source_original_statement: str,
    frozen_target_statement: str,
    target_relation: str,
    source: str,
) -> dict[str, Any]:
    """Copy the selected primary-source evidence into the campaign boundary."""

    receipt_path = receipt_path.expanduser().resolve()
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema") != SELECTION_RECEIPT_SCHEMA:
        raise CampaignError("source authority requires an openlabs.math_target_selection.v1 receipt")
    expected = {
        "target_id": slugify(campaign_id),
        "problem_id": problem_id,
        "title": title,
        "source_original_statement": source_original_statement,
        "frozen_target_statement": frozen_target_statement,
        "target_relation": target_relation,
        "source": source,
    }
    for field, expected_value in expected.items():
        observed = receipt.get(field)
        matches = (
            _normalized_statement(str(observed)) == _normalized_statement(str(expected_value))
            if field.endswith("_statement") and _text(observed)
            else observed == expected_value
        )
        if not matches:
            raise CampaignError(f"selection receipt {field} does not match the AMRA campaign")
    if receipt.get("source_kind") != "primary":
        raise CampaignError("selection receipt must identify a primary source")
    if receipt.get("public_status") not in OPEN_SOURCE_STATUSES:
        raise CampaignError("selection receipt must identify an open problem or conjecture")
    if not _text(receipt.get("source_locator")):
        raise CampaignError("selection receipt needs an exact source locator")
    statement_quote = receipt.get("source_statement_quote")
    status_quote = receipt.get("open_status_quote")
    if not _text(statement_quote) or _normalized_statement(str(statement_quote)) != _normalized_statement(
        source_original_statement
    ):
        raise CampaignError("selection receipt source_statement_quote must equal the source-original statement")
    if not _text(status_quote):
        raise CampaignError("selection receipt needs an open_status_quote")
    if receipt.get("blocking_novelty_risk") is not False:
        raise CampaignError("selection receipt must explicitly clear blocking novelty risk")
    score_vector = receipt.get("score_vector")
    if not isinstance(score_vector, dict) or not all(
        isinstance(score_vector.get(field), int)
        and not isinstance(score_vector.get(field), bool)
        and 0 <= int(score_vector[field]) <= maximum
        for field, maximum in SELECTION_SCORE_MAXIMA.items()
    ) or not isinstance(score_vector.get("total"), int):
        raise CampaignError("selection receipt needs a complete integer score_vector")
    if score_vector.get("total") != sum(
        int(score_vector[field])
        for field in SELECTION_SCORE_MAXIMA
    ):
        raise CampaignError("selection receipt score total is inconsistent")
    selection_gate = receipt.get("selection_gate_snapshot")
    if not isinstance(selection_gate, dict):
        raise CampaignError("selection receipt needs a selection_gate_snapshot")
    for score_name in ("total", "novelty", "significance", "closure"):
        minimum = selection_gate.get(f"minimum_{score_name}")
        if not isinstance(minimum, int) or isinstance(minimum, bool):
            raise CampaignError(f"selection gate needs integer minimum_{score_name}")
        if int(score_vector[score_name]) < minimum:
            raise CampaignError(f"selection score does not pass minimum_{score_name}")
    if not _text(receipt.get("closest_published_result")):
        raise CampaignError("selection receipt needs the closest published result")
    freshness_errors: list[str] = []
    _checked_at_is_fresh(receipt.get("status_checked_at"), freshness_errors, "source status check")
    _checked_at_is_fresh(receipt.get("duplicate_search_checked_at"), freshness_errors, "duplicate search")
    if freshness_errors:
        raise CampaignError("; ".join(freshness_errors))

    receipt_dir = receipt_path.parent
    source_path = _read_bound_input_file(receipt_dir, receipt.get("source_artifact"), "source artifact")
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CampaignError("source artifact must be a UTF-8 primary-source text snapshot") from exc
    normalized_source = _normalized_statement(source_text)
    if _normalized_statement(str(statement_quote)) not in normalized_source:
        raise CampaignError("source_statement_quote is absent from the primary-source snapshot")
    if _normalized_statement(str(status_quote)) not in normalized_source:
        raise CampaignError("open_status_quote is absent from the primary-source snapshot")
    raw_status = receipt.get("status_evidence")
    if not isinstance(raw_status, list) or not raw_status:
        raise CampaignError("selection receipt needs open-status evidence")
    status_paths = [
        _read_bound_input_file(receipt_dir, item, f"status evidence {index}")
        for index, item in enumerate(raw_status)
    ]
    raw_novelty = receipt.get("novelty_evidence")
    if not isinstance(raw_novelty, list) or not raw_novelty:
        raise CampaignError("selection receipt needs novelty/duplicate-search evidence")
    novelty_paths = [
        _read_bound_input_file(receipt_dir, item, f"novelty evidence {index}")
        for index, item in enumerate(raw_novelty)
    ]
    cards_ref = {"path": receipt.get("target_cards"), "sha256": receipt.get("target_cards_sha256")}
    cards_path = _read_bound_input_file(receipt_dir, cards_ref, "target cards")
    cards = read_json(cards_path)
    candidates = cards.get("candidates") if isinstance(cards, dict) else None
    minimum_cards = selection_gate.get(
        "minimum_target_cards",
        selection_gate.get("minimum_target_cards_per_cycle", 4),
    )
    if (
        not isinstance(minimum_cards, int)
        or isinstance(minimum_cards, bool)
        or minimum_cards < 4
    ):
        raise CampaignError("selection gate needs minimum_target_cards >= 4")
    if not isinstance(candidates, list) or len(candidates) < minimum_cards:
        raise CampaignError(
            f"source selection must compare at least {minimum_cards} candidate targets"
        )
    minimum_fronts = selection_gate.get(
        "minimum_distinct_research_fronts",
        selection_gate.get("minimum_distinct_research_fronts_per_cycle", 0),
    )
    if not isinstance(minimum_fronts, int) or isinstance(minimum_fronts, bool) or minimum_fronts < 0:
        raise CampaignError("selection gate minimum distinct research fronts is invalid")
    card_errors = [
        error
        for index, candidate in enumerate(candidates)
        for error in _target_card_errors(
            candidate,
            index,
            require_research_front=minimum_fronts > 0,
        )
    ]
    target_ids = [
        str(candidate.get("target_id"))
        for candidate in candidates
        if isinstance(candidate, dict) and _text(candidate.get("target_id"))
    ]
    if len(target_ids) != len(set(target_ids)):
        card_errors.append("target card ids must be unique")
    if minimum_fronts > 0:
        fronts = {
            str(candidate["research_front"])
            for candidate in candidates
            if isinstance(candidate, dict) and _text(candidate.get("research_front"))
        }
        if len(fronts) < minimum_fronts:
            card_errors.append(
                f"source selection must cover at least {minimum_fronts} research fronts"
            )
    if card_errors:
        raise CampaignError("; ".join(card_errors))
    matching = [
        item for item in candidates
        if isinstance(item, dict) and item.get("target_id") == slugify(campaign_id)
    ]
    if len(matching) != 1:
        raise CampaignError("target cards must contain exactly one selected AMRA target")
    selected_card = matching[0]
    selected_expected = {
        "problem_id": receipt.get("problem_id"),
        "title": receipt.get("title"),
        "source_original_statement": receipt.get("source_original_statement"),
        "frozen_target_statement": receipt.get("frozen_target_statement"),
        "target_relation": receipt.get("target_relation"),
        "source": receipt.get("source"),
        "public_status": receipt.get("public_status"),
        "source_locator": receipt.get("source_locator"),
        "closest_published_result": receipt.get("closest_published_result"),
        "score_vector": receipt.get("score_vector"),
        "blocking_novelty_risk": False,
    }
    for field, expected_value in selected_expected.items():
        observed = selected_card.get(field)
        matches_receipt = (
            _normalized_statement(str(observed))
            == _normalized_statement(str(expected_value))
            if field.endswith("_statement") and _text(observed) and _text(expected_value)
            else observed == expected_value
        )
        if not matches_receipt:
            raise CampaignError(
                f"selected target card {field} does not match the selection receipt"
            )

    evidence_dir = campaign_dir / "evidence" / "source-authority"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    def install(path: Path, name: str) -> dict[str, str]:
        destination = evidence_dir / name
        shutil.copyfile(path, destination)
        return {
            "path": destination.relative_to(campaign_dir).as_posix(),
            "sha256": _file_digest(destination),
        }

    receipt_ref = install(receipt_path, "selection.json")
    source_ref = install(source_path, f"primary-source{source_path.suffix or '.dat'}")
    status_refs = [
        install(path, f"open-status-{index}{path.suffix or '.dat'}")
        for index, path in enumerate(status_paths)
    ]
    novelty_refs = [
        install(path, f"novelty-{index}{path.suffix or '.dat'}")
        for index, path in enumerate(novelty_paths)
    ]
    cards_installed = install(cards_path, "target-cards.json")
    return {
        "schema_version": SOURCE_AUTHORITY_SCHEMA,
        "source_kind": "primary",
        "public_status": receipt["public_status"],
        "source_locator": receipt["source_locator"],
        "source_statement_quote": statement_quote,
        "open_status_quote": status_quote,
        "status_checked_at": receipt["status_checked_at"],
        "selection_receipt": receipt_ref,
        "primary_source": source_ref,
        "status_evidence": status_refs,
        "novelty_evidence": novelty_refs,
        "target_cards": cards_installed,
        "candidate_count": len(candidates),
    }


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_evidence_refs(
    campaign_dir: Path,
    raw_refs: Any,
    label: str,
    errors: list[str],
    *,
    required: bool = True,
) -> list[Path]:
    """Resolve immutable local evidence references and reject path escapes."""

    if not isinstance(raw_refs, list) or (required and not raw_refs):
        errors.append(f"{label} needs at least one hash-bound evidence reference")
        return []
    resolved_paths: list[Path] = []
    for index, reference in enumerate(raw_refs):
        prefix = f"{label}[{index}]"
        if not isinstance(reference, dict):
            errors.append(f"{prefix} must be a path/SHA-256 object")
            continue
        path_value = reference.get("path")
        digest = reference.get("sha256")
        if not _text(path_value):
            errors.append(f"{prefix} needs a relative path")
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"{prefix} needs a lowercase SHA-256 digest")
            continue
        relative = Path(path_value)
        if relative.is_absolute():
            errors.append(f"{prefix} path must be relative to the campaign")
            continue
        resolved = (campaign_dir / relative).resolve()
        try:
            resolved.relative_to(campaign_dir)
        except ValueError:
            errors.append(f"{prefix} path escapes the campaign")
            continue
        if not resolved.is_file():
            errors.append(f"{prefix} evidence file does not exist")
            continue
        if _file_digest(resolved) != digest:
            errors.append(f"{prefix} SHA-256 does not match the evidence file")
            continue
        resolved_paths.append(resolved)
    return resolved_paths


def _validate_reviewer_authority(
    campaign_dir: Path,
    state: dict[str, Any],
    reconstruction: dict[str, Any],
    decision: dict[str, Any],
    review_manifest_sha256: str | None,
    errors: list[str],
) -> None:
    """Verify an original-closure review against the control-plane ledger.

    A JSON file copied into a campaign is not authority: the archived receipt,
    task, attempts and ingested result bundle must agree in the control-plane
    database. The reviewer must be a fresh, successful child of the named
    author attempt and must return an explicit positive AMRA verdict.
    """

    data_root = CONTROL_PLANE_DATA_ROOT.expanduser().resolve()
    try:
        campaign_dir.relative_to(data_root / "workspaces" / "math")
    except ValueError:
        errors.append("original-problem closure campaign is outside the canonical math workspace")
        return
    archive = (data_root / "ledger" / "receipts").resolve()
    database = data_root / "openlabs-database" / "live" / "factory.sqlite"
    reference = reconstruction.get("control_plane_receipt")
    if not isinstance(reference, dict):
        errors.append("independent reviewer needs a control-plane receipt reference")
        return
    path_value = reference.get("path")
    expected_digest = reference.get("sha256")
    if not _text(path_value) or not isinstance(expected_digest, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_digest
    ):
        errors.append("control-plane receipt needs path and lowercase SHA-256")
        return
    raw_path = Path(str(path_value)).expanduser()
    receipt_path = (raw_path if raw_path.is_absolute() else data_root / raw_path).resolve()
    try:
        receipt_path.relative_to(archive)
    except ValueError:
        errors.append("reviewer receipt must be inside the OpenLabs control-plane archive")
        return
    if not receipt_path.is_file():
        errors.append("archived independent reviewer receipt does not exist")
        return
    if _file_digest(receipt_path) != expected_digest:
        errors.append("archived independent reviewer receipt SHA-256 does not match")
        return
    try:
        receipt = read_json(receipt_path)
    except CampaignError as exc:
        errors.append(str(exc))
        return
    _require(
        receipt.get("schema_version") == "openlabs.result_receipt.v2",
        "independent reviewer receipt has an unsupported schema",
        errors,
    )
    _require(receipt.get("agent_role") == "reviewer", "independent receipt must come from a reviewer role", errors)
    _require(receipt.get("domain") == "math", "independent reviewer receipt must be for the math domain", errors)
    _require(_text(receipt.get("task_id")), "independent reviewer receipt needs task_id", errors)
    _require(_text(receipt.get("attempt_id")), "independent reviewer receipt needs attempt_id", errors)
    author_attempt = reconstruction.get("author_attempt_id")
    _require(_text(author_attempt), "independent reconstruction needs author_attempt_id", errors)
    _require(
        _text(author_attempt) and author_attempt != receipt.get("attempt_id"),
        "independent reviewer attempt must differ from the author attempt",
        errors,
    )
    receipt_runtime = receipt.get("runtime")
    _require(isinstance(receipt_runtime, dict), "independent reviewer receipt needs runtime", errors)
    if isinstance(receipt_runtime, dict):
        _require(receipt_runtime.get("exit_code") == 0, "independent reviewer process must exit successfully", errors)
        _require(receipt_runtime.get("heartbeat_lost") is not True, "independent reviewer heartbeat was lost", errors)
    result_value = receipt.get("result_path")
    result_digest = receipt.get("sha256")
    if not _text(result_value) or not isinstance(result_digest, str):
        errors.append("independent reviewer receipt needs result_path and SHA-256")
        return
    result_path = Path(str(result_value)).expanduser().resolve()
    if not result_path.is_file():
        errors.append("independent reviewer result file does not exist")
        return
    if _file_digest(result_path) != result_digest:
        errors.append("independent reviewer result SHA-256 does not match")
        return
    try:
        result = read_json(result_path)
    except CampaignError as exc:
        errors.append(str(exc))
        return
    _require(
        result.get("schema_version") == "openlabs.result_bundle.v1",
        "independent reviewer result has an unsupported schema",
        errors,
    )
    _require(result.get("task_id") == receipt.get("task_id"), "review result task_id does not match receipt", errors)
    _require(
        result.get("campaign_id") == receipt.get("campaign_id"),
        "review result campaign_id does not match the control-plane receipt",
        errors,
    )
    _require(result.get("domain") == "math", "review result must be for the math domain", errors)
    _require(
        result.get("status") in {"completed", "succeeded"},
        "independent reviewer result must complete successfully",
        errors,
    )
    _require(
        result.get("amra_audit_outcome") == "passed",
        "independent reviewer result must explicitly pass the AMRA audit",
        errors,
    )
    _require(
        result.get("amra_review_schema_version") == "openlabs.amra_review.v1",
        "independent reviewer result needs the openlabs.amra_review.v1 extension",
        errors,
    )
    _require(
        result.get("amra_campaign_id") == state.get("campaign_id"),
        "review result is not bound to the AMRA campaign_id",
        errors,
    )
    _require(
        result.get("amra_statement_identity") == state.get("statement_identity"),
        "review result is not bound to the frozen AMRA statement identity",
        errors,
    )
    _require(
        result.get("amra_author_attempt_id") == author_attempt,
        "review result is not bound to the audited author attempt",
        errors,
    )
    _require(
        result.get("amra_resolution_type") == decision.get("resolution_type"),
        "review result resolution type does not match the promotion decision",
        errors,
    )
    _require(
        result.get("amra_success_condition") == decision.get("success_condition"),
        "review result success condition does not match the promotion decision",
        errors,
    )
    _require(
        _text(review_manifest_sha256)
        and result.get("amra_review_manifest_sha256") == review_manifest_sha256,
        "review result is not bound to the current AMRA review manifest",
        errors,
    )
    expected_claim_id = "amra-" + str(decision.get("success_condition") or "").replace("_", "-")
    verified_claims = [
        claim
        for claim in result.get("claims", [])
        if isinstance(claim, dict)
        and claim.get("claim_id") == expected_claim_id
        and claim.get("status") == "verified"
        and isinstance(claim.get("evidence"), list)
        and bool(claim.get("evidence"))
    ]
    _require(
        len(verified_claims) == 1,
        "review result needs one evidenced verified claim for the frozen success condition",
        errors,
    )
    result_artifact_digests = {
        item.get("sha256")
        for item in result.get("artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("sha256"), str)
    }
    reconstruction_digests = {
        item.get("sha256")
        for item in reconstruction.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("sha256"), str)
    }
    _require(
        bool(reconstruction_digests)
        and reconstruction_digests.issubset(result_artifact_digests),
        "review result artifacts do not bind every reconstruction evidence file",
        errors,
    )

    if not database.is_file():
        errors.append("OpenLabs control-plane database is unavailable")
        return
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT tasks.campaign_id, tasks.domain, tasks.agent_role,
                   tasks.session_mode, tasks.parent_task_id,
                   tasks.status AS task_status,
                   tasks.result_path AS task_result_path,
                   tasks.result_sha256 AS task_result_sha256,
                   task_attempts.task_id AS attempt_task_id,
                   task_attempts.status AS attempt_status,
                   task_attempts.result_path AS attempt_result_path,
                   task_attempts.result_sha256 AS attempt_result_sha256,
                   task_attempts.runtime_json AS attempt_runtime_json,
                   result_bundles.attempt_id AS bundle_attempt_id,
                   result_bundles.path AS bundle_path,
                   result_bundles.sha256 AS bundle_sha256,
                   result_bundles.valid AS bundle_valid,
                   result_bundles.gate_passed AS bundle_gate_passed,
                   result_bundles.blockers_json AS bundle_blockers_json,
                   result_bundles.runtime_json AS bundle_runtime_json
            FROM tasks
            JOIN task_attempts
              ON task_attempts.task_id=tasks.task_id
             AND task_attempts.attempt_id=?
            JOIN result_bundles ON result_bundles.task_id=tasks.task_id
                               AND result_bundles.attempt_id=task_attempts.attempt_id
            WHERE tasks.task_id=?
            """,
            (receipt.get("attempt_id"), receipt.get("task_id")),
        ).fetchone()
        author = connection.execute(
            """
            SELECT task_attempts.task_id, task_attempts.status AS attempt_status,
                   tasks.campaign_id, tasks.agent_role, tasks.status AS task_status
            FROM task_attempts
            JOIN tasks ON tasks.task_id=task_attempts.task_id
            WHERE task_attempts.attempt_id=?
            """,
            (author_attempt,),
        ).fetchone()
    except (sqlite3.DatabaseError, OSError) as exc:
        errors.append(f"cannot verify reviewer authority in the control plane: {exc}")
        return
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    if row is None:
        errors.append("reviewer task/attempt is absent from the control-plane database")
        return
    record = dict(row)
    _require(record["campaign_id"] == receipt.get("campaign_id"), "reviewer task campaign does not match receipt", errors)
    _require(record["domain"] == "math", "reviewer task is not a math task", errors)
    _require(record["agent_role"] == "reviewer", "control-plane task is not a reviewer task", errors)
    _require(record["session_mode"] == "fresh", "control-plane reviewer task did not use a fresh session", errors)
    _require(record["task_status"] == "succeeded", "control-plane reviewer task did not succeed", errors)
    _require(record["attempt_status"] == "succeeded", "control-plane reviewer attempt did not succeed", errors)
    _require(record["bundle_attempt_id"] == receipt.get("attempt_id"), "ingested result is from another attempt", errors)
    _require(record["bundle_valid"] == 1 and record["bundle_gate_passed"] == 1, "reviewer result did not pass ingestion gates", errors)
    try:
        blockers = json.loads(str(record["bundle_blockers_json"]))
        runtime = json.loads(str(record["bundle_runtime_json"]))
    except (json.JSONDecodeError, TypeError):
        errors.append("control-plane reviewer bundle has malformed runtime/blockers")
        blockers, runtime = None, None
    _require(blockers == [], "control-plane reviewer result has unresolved blockers", errors)
    if isinstance(runtime, dict):
        _require(runtime.get("exit_code") == 0, "control-plane reviewer runtime did not exit cleanly", errors)
        _require(runtime.get("heartbeat_lost") is not True, "control-plane reviewer runtime lost heartbeat", errors)
        hooks = runtime.get("hooks")
        _require(
            isinstance(hooks, dict)
            and hooks.get("schema_version") == "openlabs.hook_runtime.v1"
            and hooks.get("stop_passed") is True,
            "control-plane reviewer lacks the authoritative Stop-gate lifecycle hook",
            errors,
        )
    result_resolved = result_path.resolve()
    for label, recorded_path, recorded_sha in (
        ("task", record["task_result_path"], record["task_result_sha256"]),
        ("attempt", record["attempt_result_path"], record["attempt_result_sha256"]),
        ("bundle", record["bundle_path"], record["bundle_sha256"]),
    ):
        _require(
            _text(recorded_path) and Path(str(recorded_path)).resolve() == result_resolved,
            f"control-plane {label} result path does not match the receipt",
            errors,
        )
        _require(recorded_sha == result_digest, f"control-plane {label} result SHA-256 does not match", errors)
    if author is None:
        errors.append("audited author attempt is absent from the control-plane database")
    else:
        author_record = dict(author)
        _require(author_record["campaign_id"] == record["campaign_id"], "author and reviewer belong to different control-plane campaigns", errors)
        _require(author_record["agent_role"] != "reviewer", "author attempt may not itself be a reviewer attempt", errors)
        _require(author_record["attempt_status"] == "succeeded" and author_record["task_status"] == "succeeded", "audited author attempt did not succeed", errors)
        _require(record["parent_task_id"] == author_record["task_id"], "reviewer task is not the direct fresh child of the audited author task", errors)


def default_artifacts(
    *,
    source_original_statement: str,
    frozen_target_statement: str,
    target_relation: str,
    source: str,
    source_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    success_conditions = (
        ["original_problem_closed"]
        if target_relation == "exact"
        else ["scoped_theorem_proved"]
    )
    return {
        "closure_contract": {
            "source_original_statement": source_original_statement,
            "frozen_target_statement": frozen_target_statement,
            "target_relation": target_relation,
            "source": source,
            "source_authority": source_authority,
            "published_comparator": "",
            "admissible_inputs": [],
            "false_world_controls": [],
            "non_cosmetic_consequence": "",
            "success_conditions": success_conditions,
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
            "resolution_type": "",
            "reason": "",
            "evidence": [],
            "open_status_recheck": {},
        },
    }


def init_campaign(
    root: Path,
    *,
    campaign_id: str,
    problem_id: str,
    title: str,
    source_original_statement: str,
    frozen_target_statement: str,
    target_relation: str,
    source: str,
    source_authority_receipt: Path | None = None,
) -> Path:
    source_original_statement = source_original_statement.strip()
    frozen_target_statement = frozen_target_statement.strip()
    target_relation = target_relation.strip()
    problem_id = problem_id.strip()
    title = title.strip()
    source = source.strip()
    campaign_slug = slugify(campaign_id)
    if not problem_id:
        raise CampaignError("problem id is required")
    if not title:
        raise CampaignError("campaign title is required")
    if not source:
        raise CampaignError("primary source locator is required")
    if not source_original_statement:
        raise CampaignError("source original statement is required")
    if not frozen_target_statement:
        raise CampaignError("frozen target statement is required")
    if target_relation not in TARGET_RELATIONS:
        raise CampaignError(
            "target relation must be one of: " + ", ".join(sorted(TARGET_RELATIONS))
        )
    statements_match = _normalized_statement(source_original_statement) == _normalized_statement(
        frozen_target_statement
    )
    if target_relation == "exact" and not statements_match:
        raise CampaignError(
            "an exact target must match the source original statement after whitespace normalization"
        )
    if target_relation != "exact" and statements_match:
        raise CampaignError(
            "matching source and target statements must use target_relation=exact"
        )
    resolved_root = root.expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    campaign_dir = resolved_root / campaign_slug
    if campaign_dir.exists():
        raise CampaignError(f"campaign already exists: {campaign_dir}")
    staging_root = Path(tempfile.mkdtemp(prefix=f".{campaign_slug}.init-", dir=resolved_root))
    staged_campaign = staging_root / campaign_slug
    staged_campaign.mkdir()
    (staged_campaign / "evidence").mkdir()
    (staged_campaign / "audit").mkdir()
    try:
        source_authority = (
            _install_source_authority(
                receipt_path=source_authority_receipt,
                campaign_dir=staged_campaign,
                campaign_id=campaign_id,
                problem_id=problem_id,
                title=title,
                source_original_statement=source_original_statement,
                frozen_target_statement=frozen_target_statement,
                target_relation=target_relation,
                source=source,
            )
            if source_authority_receipt is not None
            else None
        )
        if target_relation == "exact" and source_authority is None:
            raise CampaignError(
                "an exact open-problem campaign requires a primary-source selection receipt"
            )
        artifacts = default_artifacts(
            source_original_statement=source_original_statement,
            frozen_target_statement=frozen_target_statement,
            target_relation=target_relation,
            source=source,
            source_authority=source_authority,
        )
        statement_identity = _make_statement_identity(
            source_original_statement=source_original_statement,
            frozen_target_statement=frozen_target_statement,
            target_relation=target_relation,
            success_condition=artifacts["closure_contract"]["success_conditions"][0],
            source=source,
            problem_id=problem_id,
            title=title,
            gates=DEFAULT_GATES,
            source_authority=source_authority,
        )
        for name, filename in ARTIFACT_FILES.items():
            write_json(staged_campaign / filename, artifacts[name])
        now = utc_now()
        write_json(
            staged_campaign / "campaign_state.json",
            {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": campaign_slug,
            "problem_id": problem_id,
            "title": title,
            "phase": "target_selection",
            "created_at": now,
            "updated_at": now,
            "statement_identity": statement_identity,
            "gates": deepcopy(DEFAULT_GATES),
            "artifacts": deepcopy(ARTIFACT_FILES),
            "history": [{
                "at": now,
                "event": "initialized",
                "phase": "target_selection",
                "statement_identity": deepcopy(statement_identity),
            }],
            },
        )
        integrity_errors = validate_campaign_integrity(staged_campaign)
        if integrity_errors:
            raise CampaignError("initialized campaign failed integrity preflight:\n- " + "\n- ".join(integrity_errors))
        os.replace(staged_campaign, campaign_dir)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return campaign_dir


def migrate_campaign_contract(
    campaign_dir: Path,
    *,
    source_original_statement: str,
    frozen_target_statement: str,
    target_relation: str,
    reason: str,
) -> dict[str, Any]:
    """Explicitly migrate one v1 contract without rewriting its legacy local target."""

    campaign_dir = campaign_dir.expanduser().resolve()
    _recover_campaign_migration(campaign_dir)
    state, artifacts = load_campaign(campaign_dir)
    if state.get("schema_version") != "amra-research-loop.v1":
        raise CampaignError("contract migration requires an amra-research-loop.v1 campaign")
    contract = artifacts["closure_contract"]
    legacy_target = contract.get("exact_statement")
    if not _text(legacy_target):
        raise CampaignError("legacy closure contract has no exact_statement to preserve")
    source_original_statement = source_original_statement.strip()
    frozen_target_statement = frozen_target_statement.strip()
    target_relation = target_relation.strip()
    reason = reason.strip()
    if not reason:
        raise CampaignError("contract migration requires a provenance reason")
    if _normalized_statement(legacy_target) != _normalized_statement(frozen_target_statement):
        raise CampaignError(
            "migration may not rewrite the legacy local target; start a new campaign instead"
        )
    if target_relation == "exact":
        raise CampaignError(
            "legacy exact campaigns lack primary-source authority; initialize a new exact "
            "campaign from a verified selection receipt instead of migrating in place"
        )

    success_condition = (
        "original_problem_closed" if target_relation == "exact" else "scoped_theorem_proved"
    )
    migrated_contract = dict(contract)
    migrated_contract.pop("exact_statement", None)
    migrated_contract.update({
        "source_original_statement": source_original_statement,
        "frozen_target_statement": frozen_target_statement,
        "target_relation": target_relation,
        "success_conditions": [success_condition],
        # A primary-source selection receipt authenticates the exact source
        # target, not a later local specialization/partial theorem.
        "source_authority": None,
    })
    scope_errors: list[str] = []
    _validate_closure_scope(migrated_contract, scope_errors)
    if scope_errors:
        raise CampaignError("contract migration failed:\n- " + "\n- ".join(scope_errors))

    statement_identity = _make_statement_identity(
        source_original_statement=source_original_statement,
        frozen_target_statement=frozen_target_statement,
        target_relation=target_relation,
        success_condition=success_condition,
        source=str(migrated_contract.get("source") or ""),
        problem_id=str(state.get("problem_id") or ""),
        title=str(state.get("title") or ""),
        gates={**DEFAULT_GATES, **state.get("gates", {})},
        source_authority=migrated_contract.get("source_authority"),
    )
    now = utc_now()
    decision = artifacts["decision"]
    prior_classification = {
        "outcome": decision.get("outcome"),
        "success_condition": decision.get("success_condition"),
        "reason": decision.get("reason"),
    }
    if decision.get("outcome") == "promote":
        decision.setdefault("classification_history", []).append({
            "at": now,
            "schema_version": "amra-research-loop.v1",
            **prior_classification,
        })
        decision["success_condition"] = success_condition
        decision["reason"] = (
            f"Classification migrated to {success_condition}: {reason}. "
            f"Prior reason: {prior_classification['reason']}"
        )

    prospective_artifacts = deepcopy(artifacts)
    prospective_artifacts["closure_contract"] = migrated_contract
    prospective_artifacts["decision"] = decision
    proof_scope_errors: list[str] = []
    _validate_proof_scope(migrated_contract, prospective_artifacts, proof_scope_errors)
    if proof_scope_errors:
        raise CampaignError(
            "migration would leave proof-scope claims inconsistent; repair the listed "
            "mechanism/lemma tokens before retrying:\n- "
            + "\n- ".join(proof_scope_errors)
        )

    state["schema_version"] = SCHEMA_VERSION
    state["statement_identity"] = statement_identity
    state["updated_at"] = now
    state.setdefault("history", []).append({
        "at": now,
        "event": "closure_contract_migrated_v2",
        "from_schema_version": "amra-research-loop.v1",
        "phase": state.get("phase"),
        "statement_identity": deepcopy(statement_identity),
        "prior_success_condition": prior_classification["success_condition"],
        "success_condition": success_condition,
        "reason": reason,
    })

    # Validate the complete prospective campaign before touching the live
    # three-file contract/state/decision set. This prevents a command from
    # reporting success while leaving a terminal campaign invalid.
    staging_root = Path(tempfile.mkdtemp(prefix=f".{campaign_dir.name}.migration-", dir=campaign_dir.parent))
    staged_campaign = staging_root / campaign_dir.name
    backup, journal_path = _migration_paths(campaign_dir)
    if backup.exists() or journal_path.exists():
        shutil.rmtree(staging_root, ignore_errors=True)
        raise CampaignError("unresolved prior migration transaction exists")
    try:
        shutil.copytree(campaign_dir, staged_campaign)
        write_json(staged_campaign / ARTIFACT_FILES["closure_contract"], migrated_contract)
        write_json(staged_campaign / ARTIFACT_FILES["decision"], decision)
        write_json(staged_campaign / "campaign_state.json", state)
        staged_errors = validate_campaign_integrity(staged_campaign)
        if staged_errors:
            raise CampaignError(
                "migration preflight failed; the live campaign was not changed:\n- "
                + "\n- ".join(staged_errors)
            )
        write_json(journal_path, {
            "schema_version": "openlabs.amra_migration_journal.v1",
            "campaign": str(campaign_dir),
            "staging_root": str(staging_root),
            "statement_identity": statement_identity,
            "status": "prepared",
        })
        _fsync_directory(campaign_dir.parent)
        # Commit the already validated complete tree. If the second rename
        # fails, restore the untouched original directory before returning.
        os.replace(campaign_dir, backup)
        _fsync_directory(campaign_dir.parent)
        try:
            os.replace(staged_campaign, campaign_dir)
        except Exception:
            os.replace(backup, campaign_dir)
            _fsync_directory(campaign_dir.parent)
            journal_path.unlink(missing_ok=True)
            raise
        _fsync_directory(campaign_dir.parent)
        archived_backup = _archive_migration_backup(backup, campaign_dir)
        journal = read_json(journal_path)
        journal.update({"status": "committed", "archived_backup": str(archived_backup)})
        write_json(journal_path, journal)
        journal_path.unlink(missing_ok=True)
        _fsync_directory(campaign_dir.parent)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return state


def load_campaign(campaign_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign_dir = campaign_dir.expanduser().resolve()
    state = read_json(campaign_dir / "campaign_state.json")
    if not isinstance(state, dict):
        raise CampaignError("campaign_state.json must contain an object")
    artifacts: dict[str, Any] = {}
    for name, filename in ARTIFACT_FILES.items():
        value = read_json(campaign_dir / filename)
        if not isinstance(value, dict):
            raise CampaignError(f"{filename} must contain a JSON object")
        artifacts[name] = value
    return state, artifacts


def _collect_hash_references(value: Any) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    if isinstance(value, dict):
        if set(value) >= {"path", "sha256"} and _text(value.get("path")) and isinstance(value.get("sha256"), str):
            collected.append({"path": str(value["path"]), "sha256": str(value["sha256"])})
        else:
            for nested in value.values():
                collected.extend(_collect_hash_references(nested))
    elif isinstance(value, list):
        for nested in value:
            collected.extend(_collect_hash_references(nested))
    return collected


def _review_manifest_payload(
    campaign_dir: Path,
    state: dict[str, Any],
    artifacts: dict[str, Any],
    *,
    author_attempt_id: str,
) -> dict[str, Any]:
    included = (
        "closure_contract", "information_loss_map", "representations", "mechanisms",
        "kill_tests", "survivors", "decisive_lemma", "decision",
    )
    artifact_hashes = {
        name: _file_digest(campaign_dir / ARTIFACT_FILES[name])
        for name in included
    }
    references: dict[str, str] = {}
    for name in included:
        for reference in _collect_hash_references(artifacts[name]):
            references[reference["path"]] = reference["sha256"]
    return {
        "schema_version": "openlabs.amra_review_manifest.v1",
        "campaign_id": state.get("campaign_id"),
        "problem_id": state.get("problem_id"),
        "statement_identity": state.get("statement_identity"),
        "author_attempt_id": author_attempt_id,
        "success_condition": artifacts["decision"].get("success_condition"),
        "resolution_type": artifacts["decision"].get("resolution_type"),
        "artifact_sha256": artifact_hashes,
        "referenced_evidence": [
            {"path": path, "sha256": references[path]} for path in sorted(references)
        ],
    }


def prepare_review_manifest(campaign_dir: Path, author_attempt_id: str) -> dict[str, str]:
    """Freeze the exact author-side bytes a fresh reviewer is asked to audit."""

    campaign_dir = campaign_dir.expanduser().resolve()
    state, artifacts = load_campaign(campaign_dir)
    if state.get("phase") != "independent_audit":
        raise CampaignError("review manifest may be prepared only at independent_audit")
    if not _text(author_attempt_id):
        raise CampaignError("review manifest needs the control-plane author_attempt_id")
    decision = artifacts["decision"]
    if decision.get("outcome") != "promote" or decision.get("resolution_type") not in {"proof", "counterexample"}:
        raise CampaignError("freeze the proposed promotion decision and resolution type before review")
    payload = _review_manifest_payload(
        campaign_dir, state, artifacts, author_attempt_id=author_attempt_id.strip()
    )
    reference_errors: list[str] = []
    _validate_evidence_refs(
        campaign_dir,
        payload["referenced_evidence"],
        "review-manifest evidence",
        reference_errors,
        required=False,
    )
    if reference_errors:
        raise CampaignError("review manifest evidence failed:\n- " + "\n- ".join(reference_errors))
    manifest_path = campaign_dir / "audit" / "review-manifest.json"
    write_json(manifest_path, payload)
    reference = {
        "path": manifest_path.relative_to(campaign_dir).as_posix(),
        "sha256": _file_digest(manifest_path),
    }
    audit = artifacts["audit"]
    audit["review_manifest"] = reference
    reconstruction = audit.setdefault("independent_reconstruction", {})
    reconstruction["author_attempt_id"] = author_attempt_id.strip()
    write_json(campaign_dir / ARTIFACT_FILES["audit"], audit)
    return reference


def _validate_review_manifest(
    campaign_dir: Path,
    state: dict[str, Any],
    artifacts: dict[str, Any],
    reconstruction: dict[str, Any],
    errors: list[str],
) -> str | None:
    audit = artifacts["audit"]
    paths = _validate_evidence_refs(
        campaign_dir,
        [audit.get("review_manifest")],
        "AMRA review manifest",
        errors,
    )
    if not paths:
        return None
    try:
        manifest = read_json(paths[0])
    except CampaignError as exc:
        errors.append(str(exc))
        return None
    expected = _review_manifest_payload(
        campaign_dir,
        state,
        artifacts,
        author_attempt_id=str(reconstruction.get("author_attempt_id") or ""),
    )
    _require(manifest == expected, "AMRA review manifest no longer matches author-side proof bytes", errors)
    return _file_digest(paths[0])


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value: Any) -> bool:
    return isinstance(value, list)


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _validate_source_authority(
    campaign_dir: Path,
    state: dict[str, Any],
    contract: dict[str, Any],
    errors: list[str],
) -> None:
    """Recheck the primary-source bundle frozen when an exact target was selected."""

    authority = contract.get("source_authority")
    if contract.get("target_relation") == "exact":
        _require(isinstance(authority, dict), "exact target needs frozen primary-source authority", errors)
    if authority is None:
        return
    if not isinstance(authority, dict):
        errors.append("source_authority must be an object")
        return
    _require(authority.get("schema_version") == SOURCE_AUTHORITY_SCHEMA, "unsupported source_authority schema", errors)
    _require(authority.get("source_kind") == "primary", "source_authority must identify a primary source", errors)
    _require(authority.get("public_status") in OPEN_SOURCE_STATUSES, "source_authority must identify an open problem or conjecture", errors)
    _require(_text(authority.get("source_locator")), "source_authority needs an exact source locator", errors)
    _require(
        _text(authority.get("source_statement_quote"))
        and _normalized_statement(str(authority.get("source_statement_quote")))
        == _normalized_statement(str(contract.get("source_original_statement") or "")),
        "source_authority quote does not equal the source-original statement",
        errors,
    )
    _require(_text(authority.get("open_status_quote")), "source_authority needs an open-status quote", errors)
    _require(
        isinstance(authority.get("candidate_count"), int)
        and authority.get("candidate_count") >= 4,
        "source selection must compare at least four candidates",
        errors,
    )
    _checked_at_matches_selection(
        authority.get("status_checked_at"),
        state.get("created_at"),
        errors,
        "source status check",
    )
    receipt_paths = _validate_evidence_refs(
        campaign_dir, [authority.get("selection_receipt")], "source selection receipt", errors
    )
    primary_paths = _validate_evidence_refs(campaign_dir, [authority.get("primary_source")], "primary source evidence", errors)
    _validate_evidence_refs(campaign_dir, authority.get("status_evidence"), "open-status evidence", errors)
    _validate_evidence_refs(campaign_dir, authority.get("novelty_evidence"), "novelty-search evidence", errors)
    cards_paths = _validate_evidence_refs(
        campaign_dir, [authority.get("target_cards")], "target-card evidence", errors
    )
    if primary_paths:
        try:
            primary_text = primary_paths[0].read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append("primary-source evidence must be a UTF-8 text snapshot")
        else:
            normalized_primary = _normalized_statement(primary_text)
            for field, label in (
                ("source_statement_quote", "source statement"),
                ("open_status_quote", "open-status"),
            ):
                quote = authority.get(field)
                _require(
                    _text(quote) and _normalized_statement(str(quote)) in normalized_primary,
                    f"{label} quote is absent from primary-source evidence",
                    errors,
                )
    receipt: dict[str, Any] | None = None
    if receipt_paths:
        try:
            receipt = read_json(receipt_paths[0])
        except CampaignError as exc:
            errors.append(str(exc))
        else:
            _require(receipt.get("schema") == SELECTION_RECEIPT_SCHEMA, "unsupported source selection receipt", errors)
            _require(receipt.get("blocking_novelty_risk") is False, "source selection retains a blocking novelty risk", errors)
            score_vector = receipt.get("score_vector")
            score_fields = tuple(SELECTION_SCORE_MAXIMA)
            _require(
                isinstance(score_vector, dict)
                and all(
                    isinstance(score_vector.get(field), int)
                    and not isinstance(score_vector.get(field), bool)
                    and 0 <= int(score_vector[field]) <= SELECTION_SCORE_MAXIMA[field]
                    for field in score_fields
                )
                and isinstance(score_vector.get("total"), int)
                and score_vector.get("total") == sum(int(score_vector[field]) for field in score_fields),
                "source selection receipt has an invalid score_vector",
                errors,
            )
            selection_gate = receipt.get("selection_gate_snapshot")
            _require(isinstance(selection_gate, dict), "source selection receipt lacks a gate snapshot", errors)
            if isinstance(selection_gate, dict) and isinstance(score_vector, dict):
                for score_name in ("total", "novelty", "significance", "closure"):
                    minimum = selection_gate.get(f"minimum_{score_name}")
                    _require(
                        isinstance(minimum, int)
                        and not isinstance(minimum, bool)
                        and isinstance(score_vector.get(score_name), int)
                        and int(score_vector[score_name]) >= minimum,
                        f"source selection score does not pass minimum_{score_name}",
                        errors,
                    )
            _require(_text(receipt.get("closest_published_result")), "source selection receipt lacks a closest published result", errors)
            _checked_at_matches_selection(
                receipt.get("duplicate_search_checked_at"),
                state.get("created_at"),
                errors,
                "duplicate search",
            )
            expected = {
                "target_id": state.get("campaign_id"),
                "problem_id": state.get("problem_id"),
                "title": state.get("title"),
                "source_original_statement": contract.get("source_original_statement"),
                "frozen_target_statement": contract.get("frozen_target_statement"),
                "target_relation": contract.get("target_relation"),
                "source": contract.get("source"),
                "source_kind": authority.get("source_kind"),
                "public_status": authority.get("public_status"),
                "source_locator": authority.get("source_locator"),
                "status_checked_at": authority.get("status_checked_at"),
                "source_statement_quote": authority.get("source_statement_quote"),
                "open_status_quote": authority.get("open_status_quote"),
            }
            for field, expected_value in expected.items():
                observed = receipt.get(field)
                matches = (
                    _text(observed)
                    and _text(expected_value)
                    and _normalized_statement(str(observed))
                    == _normalized_statement(str(expected_value))
                    if field.endswith("_statement")
                    else observed == expected_value
                )
                _require(matches, f"source selection receipt {field} changed or mismatches", errors)
            declared_source = receipt.get("source_artifact")
            installed_source = authority.get("primary_source")
            _require(
                isinstance(declared_source, dict)
                and isinstance(installed_source, dict)
                and declared_source.get("sha256") == installed_source.get("sha256"),
                "installed primary-source digest does not match the selection receipt",
                errors,
            )
            declared_status = receipt.get("status_evidence")
            installed_status = authority.get("status_evidence")
            _require(
                isinstance(declared_status, list)
                and isinstance(installed_status, list)
                and [item.get("sha256") for item in declared_status if isinstance(item, dict)]
                == [item.get("sha256") for item in installed_status if isinstance(item, dict)]
                and len(declared_status) == len(installed_status),
                "installed open-status evidence does not match the selection receipt",
                errors,
            )
            declared_novelty = receipt.get("novelty_evidence")
            installed_novelty = authority.get("novelty_evidence")
            _require(
                isinstance(declared_novelty, list)
                and isinstance(installed_novelty, list)
                and [item.get("sha256") for item in declared_novelty if isinstance(item, dict)]
                == [item.get("sha256") for item in installed_novelty if isinstance(item, dict)]
                and len(declared_novelty) == len(installed_novelty),
                "installed novelty evidence does not match the selection receipt",
                errors,
            )
            installed_cards = authority.get("target_cards")
            _require(
                isinstance(installed_cards, dict)
                and receipt.get("target_cards_sha256") == installed_cards.get("sha256"),
                "installed target-card digest does not match the selection receipt",
                errors,
            )
    if cards_paths:
        try:
            cards = read_json(cards_paths[0])
        except CampaignError as exc:
            errors.append(str(exc))
        else:
            candidates = cards.get("candidates") if isinstance(cards, dict) else None
            _require(isinstance(candidates, list) and len(candidates) >= 4, "target cards need at least four candidates", errors)
            matching = [
                item for item in candidates or []
                if isinstance(item, dict) and item.get("target_id") == state.get("campaign_id")
            ]
            _require(len(matching) == 1, "target cards must contain exactly one selected target", errors)
            if len(matching) == 1:
                card = matching[0]
                for field in (
                    "problem_id", "title", "source_original_statement",
                    "frozen_target_statement", "target_relation", "source",
                    "public_status", "source_locator", "closest_published_result",
                    "score_vector", "blocking_novelty_risk",
                ):
                    expected_value = (
                        state.get(field) if field in {"problem_id", "title"} else contract.get(field)
                    )
                    if field in {
                        "public_status", "source_locator", "closest_published_result",
                        "score_vector", "blocking_novelty_risk",
                    }:
                        expected_value = receipt.get(field) if receipt is not None else None
                    observed = card.get(field)
                    matches = (
                        _text(observed)
                        and _text(expected_value)
                        and _normalized_statement(str(observed))
                        == _normalized_statement(str(expected_value))
                        if field.endswith("_statement")
                        else observed == expected_value
                    )
                    _require(matches, f"selected target card {field} mismatches the campaign", errors)


def _validate_closure_scope(
    contract: dict[str, Any],
    errors: list[str],
    *,
    decision: dict[str, Any] | None = None,
) -> None:
    """Fail closed when a local theorem is mislabeled as source-problem closure."""

    source_statement = contract.get("source_original_statement")
    target_statement = contract.get("frozen_target_statement")
    relation = contract.get("target_relation")
    _require(
        _text(source_statement),
        "closure contract needs source_original_statement; migrate legacy exact_statement",
        errors,
    )
    _require(
        _text(target_statement),
        "closure contract needs frozen_target_statement; migrate legacy exact_statement",
        errors,
    )
    _require(
        relation in TARGET_RELATIONS,
        "closure contract target_relation must be exact, specialization, strengthening, or partial",
        errors,
    )

    statements_match = (
        _text(source_statement)
        and _text(target_statement)
        and _normalized_statement(source_statement) == _normalized_statement(target_statement)
    )
    if relation == "exact":
        _require(
            statements_match,
            "target_relation=exact requires the frozen target to match the source original statement",
            errors,
        )
    elif relation in TARGET_RELATIONS:
        _require(
            not statements_match,
            "a matching source and frozen target must use target_relation=exact",
            errors,
        )

    raw_success = contract.get("success_conditions")
    success = {
        item for item in raw_success if isinstance(item, str)
    } if isinstance(raw_success, list) else set()
    _require(bool(success), "closure contract needs an allowed success condition", errors)
    _require(
        len(success) == 1,
        "closure contract must freeze exactly one success condition",
        errors,
    )
    _require(
        isinstance(raw_success, list)
        and len(success) == len(raw_success)
        and success.issubset(ALLOWED_SUCCESS),
        "closure contract contains an unknown success condition",
        errors,
    )
    if relation == "exact":
        _require(
            success == {"original_problem_closed"},
            "an exact source-problem target must use original_problem_closed",
            errors,
        )
    elif relation in TARGET_RELATIONS:
        _require(
            "original_problem_closed" not in success,
            "only an exact source-statement target may use original_problem_closed",
            errors,
        )
        _require(
            "scoped_theorem_proved" in success,
            "a non-exact target must use scoped_theorem_proved",
            errors,
        )

    if decision is not None and decision.get("outcome") == "promote":
        promoted_as = decision.get("success_condition")
        _require(
            promoted_as in success,
            "promotion decision must satisfy the frozen closure contract",
            errors,
        )
        if promoted_as == "original_problem_closed":
            _require(
                relation == "exact" and statements_match,
                "original_problem_closed promotion requires an exact source-statement match",
                errors,
            )
        if relation != "exact":
            _require(
                promoted_as == "scoped_theorem_proved",
                "a non-exact target may only be promoted as scoped_theorem_proved",
                errors,
            )


def _validate_statement_identity(
    state: dict[str, Any], contract: dict[str, Any], errors: list[str]
) -> None:
    """Bind the mutable contract to the statement identity frozen at initialization."""

    identity = state.get("statement_identity")
    _require(
        isinstance(identity, dict),
        "campaign needs immutable statement_identity; migrate the legacy campaign",
        errors,
    )
    if not isinstance(identity, dict):
        return
    source_statement = contract.get("source_original_statement")
    target_statement = contract.get("frozen_target_statement")
    expected_source = (
        _statement_digest(source_statement) if _text(source_statement) else None
    )
    expected_target = (
        _statement_digest(target_statement) if _text(target_statement) else None
    )
    _require(
        identity.get("source_original_sha256") == expected_source,
        "source_original_statement changed after statement identity was frozen",
        errors,
    )
    _require(
        identity.get("frozen_target_sha256") == expected_target,
        "frozen_target_statement changed after statement identity was frozen",
        errors,
    )
    _require(
        identity.get("target_relation") == contract.get("target_relation"),
        "target_relation changed after statement identity was frozen",
        errors,
    )
    raw_success = contract.get("success_conditions")
    frozen_success = (
        raw_success[0]
        if isinstance(raw_success, list) and len(raw_success) == 1
        else None
    )
    _require(
        identity.get("success_condition") == frozen_success,
        "success condition changed after statement identity was frozen",
        errors,
    )
    _require(
        identity.get("source_locator_sha256")
        == (_text_digest(str(contract.get("source"))) if _text(contract.get("source")) else None),
        "source locator changed after statement identity was frozen",
        errors,
    )
    _require(
        identity.get("problem_id_sha256")
        == (_text_digest(str(state.get("problem_id"))) if _text(state.get("problem_id")) else None),
        "problem_id changed after statement identity was frozen",
        errors,
    )
    _require(
        identity.get("title_sha256")
        == (_text_digest(str(state.get("title"))) if _text(state.get("title")) else None),
        "campaign title changed after statement identity was frozen",
        errors,
    )
    gates = state.get("gates")
    _require(
        isinstance(gates, dict)
        and identity.get("gate_policy_sha256") == _json_digest({**DEFAULT_GATES, **gates}),
        "AMRA gate policy changed after it was frozen",
        errors,
    )
    _require(
        identity.get("source_authority_sha256")
        == _json_digest(contract.get("source_authority")),
        "source authority changed after statement identity was frozen",
        errors,
    )


def _validate_proof_scope(
    contract: dict[str, Any], artifacts: dict[str, Any], errors: list[str]
) -> None:
    """Keep mechanism and lemma closure labels consistent with the frozen contract."""

    relation = contract.get("target_relation")
    success = [
        item for item in contract.get("success_conditions", []) if isinstance(item, str)
    ]
    frozen_success = success[0] if len(success) == 1 else None
    mechanisms = artifacts["mechanisms"].get("mechanisms", [])
    if not isinstance(mechanisms, list):
        mechanisms = []
    if relation != "exact":
        _require(
            all(
                "original_problem_closed" not in item.get("would_close", [])
                for item in mechanisms
                if isinstance(item, dict) and isinstance(item.get("would_close"), list)
            ),
            "a non-exact mechanism may not claim original_problem_closed",
            errors,
        )

    mechanism_by_id = {
        item.get("id"): item
        for item in mechanisms
        if isinstance(item, dict) and _text(item.get("id"))
    }
    survivor_ids = artifacts["survivors"].get("mechanism_ids", [])
    if not isinstance(survivor_ids, list):
        survivor_ids = []
    proved_survivors = [
        mechanism_by_id[item]
        for item in survivor_ids
        if item in mechanism_by_id and mechanism_by_id[item].get("status") == "proved"
    ]
    _require(
        all(
            frozen_success in item.get("would_close", [])
            for item in proved_survivors
            if isinstance(item.get("would_close"), list)
        )
        and all(isinstance(item.get("would_close"), list) for item in proved_survivors),
        "every proved survivor must close the frozen success condition",
        errors,
    )

    lemma = artifacts["decisive_lemma"]
    lemma_closes = lemma.get("closes") if _list(lemma.get("closes")) else []
    if relation != "exact":
        _require(
            "original_problem_closed" not in lemma_closes,
            "a non-exact decisive lemma may not claim original_problem_closed",
            errors,
        )
    if lemma.get("status") == "proved":
        _require(
            frozen_success in lemma_closes,
            "a proved decisive lemma must close the frozen success condition",
            errors,
        )


def validate_campaign(campaign_dir: Path, *, target_phase: str | None = None) -> list[str]:
    campaign_dir = campaign_dir.expanduser().resolve()
    try:
        state, a = load_campaign(campaign_dir)
    except CampaignError as exc:
        return [str(exc)]
    errors: list[str] = []
    phase = target_phase or state.get("phase")
    _require(state.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version", errors)
    _require(phase in PHASES, f"unknown phase: {phase}", errors)
    _require(_text(state.get("campaign_id")), "campaign_id is required", errors)
    _require(_text(state.get("problem_id")), "problem_id is required", errors)

    contract = a["closure_contract"]
    _validate_closure_scope(contract, errors, decision=a["decision"])
    _validate_source_authority(campaign_dir, state, contract, errors)
    _validate_statement_identity(state, contract, errors)
    _validate_proof_scope(contract, a, errors)
    _require(_text(contract.get("source")), "closure contract needs a source", errors)
    success = {
        item for item in contract.get("success_conditions", []) if isinstance(item, str)
    }
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
    if phase in {"survivor_deepening", "independent_audit", "promotion"}:
        _validate_evidence_refs(
            campaign_dir,
            lemma.get("evidence"),
            "decisive lemma evidence",
            errors,
        )
        _require(
            lemma.get("status") == "proved",
            "independent audit requires a proved decisive lemma",
            errors,
        )
        dependency_gaps = lemma.get("dependency_gaps")
        _require(
            isinstance(dependency_gaps, list) and not dependency_gaps,
            "independent audit requires every decisive-lemma dependency gap to be closed",
            errors,
        )
    if phase == "survivor_deepening":
        return errors

    audit = a["audit"]
    reconstruction = audit.get("independent_reconstruction", {})
    _require(reconstruction.get("status") == "passed", "independent reconstruction must pass", errors)
    _require(_text(reconstruction.get("auditor")), "independent reconstruction needs an auditor", errors)
    _require(_list(reconstruction.get("evidence")) and bool(reconstruction.get("evidence")), "independent reconstruction needs evidence", errors)
    _validate_evidence_refs(
        campaign_dir,
        reconstruction.get("evidence"),
        "independent reconstruction evidence",
        errors,
    )
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
                _validate_evidence_refs(
                    campaign_dir,
                    formalization.get("evidence"),
                    "formalization evidence",
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
                    _validate_evidence_refs(
                        campaign_dir,
                        check.get("evidence"),
                        f"{prefix} evidence",
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
    _validate_evidence_refs(
        campaign_dir,
        decision.get("evidence"),
        "promotion decision evidence",
        errors,
    )
    _require(
        decision.get("resolution_type") in {"proof", "counterexample"},
        "promotion decision needs resolution_type proof or counterexample",
        errors,
    )
    if decision.get("success_condition") == "original_problem_closed":
        recheck = decision.get("open_status_recheck")
        _require(isinstance(recheck, dict), "original-problem closure needs a current open-status recheck", errors)
        if isinstance(recheck, dict):
            _require(recheck.get("public_status") in OPEN_SOURCE_STATUSES, "promotion recheck must still classify the source as open", errors)
            _require(recheck.get("source_locator") == contract.get("source_authority", {}).get("source_locator"), "promotion recheck source locator changed", errors)
            _checked_at_is_fresh(recheck.get("status_checked_at"), errors, "promotion open-status recheck")
            _validate_evidence_refs(
                campaign_dir,
                recheck.get("evidence"),
                "promotion open-status recheck evidence",
                errors,
            )
    review_manifest_sha256 = _validate_review_manifest(
        campaign_dir, state, a, reconstruction, errors
    )
    _validate_reviewer_authority(
        campaign_dir,
        state,
        reconstruction,
        decision,
        review_manifest_sha256,
        errors,
    )
    return errors


def validate_campaign_integrity(campaign_dir: Path) -> list[str]:
    """Validate durable shape and transition history without requiring phase completion.

    This is the protocol-level commit check.  ``validate_campaign`` remains the
    stronger gate used before an explicit phase transition.
    """

    try:
        state, artifacts = load_campaign(campaign_dir)
    except CampaignError as exc:
        return [str(exc)]
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
    contract = artifacts["closure_contract"]
    decision = artifacts["decision"]
    _validate_closure_scope(contract, errors, decision=decision)
    _validate_source_authority(campaign_dir.expanduser().resolve(), state, contract, errors)
    _validate_statement_identity(state, contract, errors)
    _validate_proof_scope(contract, artifacts, errors)

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
    if first.get("statement_identity") is not None:
        _require(
            first.get("statement_identity") == state.get("statement_identity"),
            "initial history statement_identity does not match campaign state",
            errors,
        )
    else:
        migrations = [
            event for event in history[1:]
            if isinstance(event, dict)
            and event.get("event") == "closure_contract_migrated_v2"
        ]
        _require(
            len(migrations) == 1
            and migrations[0].get("statement_identity") == state.get("statement_identity"),
            "legacy campaign needs one matching closure_contract_migrated_v2 history binding",
            errors,
        )
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
        _require(decision.get("outcome") == "freeze", "frozen campaign needs a freeze decision", errors)
        _require(_text(decision.get("reason")), "frozen campaign needs a reason", errors)
    if state.get("phase") == "promotion":
        _require(decision.get("outcome") == "promote", "promoted campaign needs a promote decision", errors)
        # A terminal phase label is not authority by itself. Promotion commits
        # must satisfy every mathematical phase gate, including for callers
        # that invoke only the integrity entry point.
        errors.extend(validate_campaign(campaign_dir))
        errors[:] = list(dict.fromkeys(errors))
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
