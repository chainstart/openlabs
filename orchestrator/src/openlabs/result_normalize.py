"""Registration fixes of a result bundle the control plane makes itself (2026-11-16).

Artifact ids and the claim evidence that points at them are bookkeeping: an owner seat
that wrote artifacts without ``artifact_id`` (attempt 071e990c) and a card repair whose
claim cited the card as ``repaired-topic-card`` although no such artifact was listed
(attempt 3b5a56f4) were both sent back as needs_replan. The content gates (hashes,
data boundary, admission, review) are unchanged; this module only makes ids valid and
unique and keeps every reference resolvable.

- empty or non-string id: ``<file stem>-<sha256[:8]>`` (or ``artifact-<index>``), made legal;
- illegal characters or longer than 128: illegal runs become ``-``, a leading non-alphanumeric
  is dropped, an over-long id is cut and given an 8-hex hash of the original;
- duplicate: the first keeps the id, later ones get ``-2``, ``-3`` ...;
- claim evidence: an id that was renamed once is rewritten; an id shared by several artifacts
  keeps pointing at the first (a warning names the others); an id that matches no artifact is
  matched by file name or stem when that match is unique, else it moves to
  ``claims[].unresolved_evidence`` with a warning. A supported, verified or refuted claim left
  with no evidence becomes ``unsupported`` (``status_before_normalization`` keeps the old one),
  so nothing is promoted on a reference that does not resolve.

:func:`normalize_registration` returns the payload and the list of changes; the ingest
records them (runtime ``registration_normalized``, event ``result_registration_normalized``)
and the Stop hook validates the normalized form, so the agent is not sent back for them.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from .contracts import IDENTIFIER

MAX_ID = 128
_ILLEGAL = re.compile(r"[^A-Za-z0-9._:-]+")
_EVIDENCE_STATUSES = frozenset({"supported", "verified", "refuted"})


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def legal_id(value: str) -> str:
    """``value`` as a legal artifact id (``""`` when nothing usable is left)."""

    text = _ILLEGAL.sub("-", value.strip()).strip("-")
    text = re.sub(r"^[^A-Za-z0-9]+", "", text)
    if len(text) > MAX_ID:
        text = text[: MAX_ID - 9].rstrip("-") + "-" + _short_hash(value)
    return text if IDENTIFIER.fullmatch(text) else ""


def _file_name(uri: Any) -> str:
    parsed = urlparse(str(uri or ""))
    path = unquote(parsed.path) if parsed.scheme else str(uri or "")
    return PurePosixPath(path).name


def _stem(name: str) -> str:
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return PurePosixPath(name).stem


def _generated_id(artifact: Mapping[str, Any], index: int) -> str:
    stem = legal_id(_stem(_file_name(artifact.get("uri") or artifact.get("path"))))
    digest = str(artifact.get("sha256") or "")
    tag = digest[:8] if re.fullmatch(r"[0-9a-f]{64}", digest) else f"{index:03d}"
    base = f"{stem[: MAX_ID - 10]}-{tag}" if stem else f"artifact-{index:03d}-{tag}"
    return legal_id(base) or f"artifact-{index:03d}"


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def normalize_registration(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Valid, unique artifact ids and resolvable claim evidence; the changes made."""

    if not isinstance(payload, Mapping):
        return payload, []  # type: ignore[return-value]
    artifacts = payload.get("artifacts")
    claims = payload.get("claims")
    if not isinstance(artifacts, list):
        return dict(payload), []
    fixed = copy.deepcopy(dict(payload))
    changes: list[dict[str, Any]] = []
    renamed: dict[str, list[str]] = {}  # declared id -> final ids, in order
    final_ids: list[str] = []
    used: set[str] = set()
    for index, artifact in enumerate(fixed["artifacts"]):
        if not isinstance(artifact, dict):
            continue
        declared = artifact.get("artifact_id")
        text = declared if isinstance(declared, str) else ""
        if text.strip() and IDENTIFIER.fullmatch(text):
            candidate, why = text, None
        elif text.strip() and legal_id(text):
            candidate, why = legal_id(text), "illegal_id"
        else:
            candidate, why = _generated_id(artifact, index), "missing_id"
        if candidate in used:
            base, number = candidate, 2
            while True:
                suffix = f"-{number}"
                candidate = f"{base[: MAX_ID - len(suffix)]}{suffix}"
                if candidate not in used:
                    break
                number += 1
            why = why or "duplicate_id"
        used.add(candidate)
        final_ids.append(candidate)
        if text:
            renamed.setdefault(text, []).append(candidate)
        if why is not None:
            artifact["artifact_id"] = candidate
            changes.append({"kind": why, "index": index,
                            "declared": declared if declared is not None else None,
                            "artifact_id": candidate})
    if not isinstance(claims, list):
        return fixed, changes

    by_name: dict[str, list[str]] = {}
    for artifact, final in zip(
        (item for item in fixed["artifacts"] if isinstance(item, dict)), final_ids
    ):
        name = _file_name(artifact.get("uri") or artifact.get("path"))
        for token in {name, _stem(name)} - {""}:
            by_name.setdefault(_key(token), []).append(final)
        by_name.setdefault(_key(final), []).append(final)

    final_set = set(final_ids)
    for claim_index, claim in enumerate(fixed["claims"]):
        if not isinstance(claim, dict) or not isinstance(claim.get("evidence"), list):
            continue
        evidence: list[str] = []
        unresolved: list[Any] = []
        for ref in claim["evidence"]:
            target: str | None = None
            if isinstance(ref, str) and ref in renamed:
                targets = renamed[ref]
                target = targets[0]
                if len(targets) > 1:
                    changes.append({"kind": "ambiguous_evidence", "claim": claim_index,
                                    "reference": ref, "kept": target,
                                    "also_declared_as": targets[1:]})
                elif target != ref:
                    changes.append({"kind": "evidence_renamed", "claim": claim_index,
                                    "reference": ref, "artifact_id": target})
            elif isinstance(ref, str) and ref in final_set:
                target = ref
            elif isinstance(ref, str) and ref.strip():
                matches = sorted(set(by_name.get(_key(ref), [])))
                if len(matches) == 1:
                    target = matches[0]
                    changes.append({"kind": "evidence_matched", "claim": claim_index,
                                    "reference": ref, "artifact_id": target})
            if target is None:
                unresolved.append(ref)
                changes.append({"kind": "evidence_unresolved", "claim": claim_index,
                                "reference": ref})
            elif target not in evidence:
                evidence.append(target)
        if evidence == claim["evidence"] and not unresolved and (
            evidence or claim.get("status") not in _EVIDENCE_STATUSES
        ):
            continue
        claim["evidence"] = evidence
        if unresolved:
            claim["unresolved_evidence"] = [*claim.get("unresolved_evidence", []), *unresolved]
        if not evidence and claim.get("status") in _EVIDENCE_STATUSES:
            claim["status_before_normalization"] = claim["status"]
            claim["status"] = "unsupported"
            changes.append({"kind": "claim_unsupported", "claim": claim_index,
                            "was": claim["status_before_normalization"]})
    return fixed, changes


_TRUE = frozenset({"true", "yes"})
_FALSE = frozenset({"false", "no"})


def _boolean(value: Any) -> bool | None:
    if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
        return value.strip().lower() in _TRUE
    return None


def normalize_admission_shapes(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Shapes of ``candidate_branches[].admission`` the control plane can settle.

    Every admission review after the 2026-11-16 restart was stopped once for
    ``cost_judgement`` written as ``{proportionate: true, agent_time: "...", compute:
    "..."}`` without ``rationale``; the reviewer then copied its own texts into it. The
    texts are joined into ``rationale`` here, and ``"true"``/``"false"`` strings of the
    two boolean fields are read as booleans. A missing verdict or a missing
    ``proportionate`` stays missing: those are the reviewer's judgement.
    """

    branches = payload.get("candidate_branches") if isinstance(payload, Mapping) else None
    if not isinstance(branches, list):
        return dict(payload), []
    fixed = copy.deepcopy(dict(payload))
    changes: list[dict[str, Any]] = []
    for index, branch in enumerate(fixed["candidate_branches"]):
        admission = branch.get("admission") if isinstance(branch, dict) else None
        if not isinstance(admission, dict):
            continue
        confirmed = _boolean(admission.get("data_access_confirmed"))
        if confirmed is not None:
            admission["data_access_confirmed"] = confirmed
            changes.append({"kind": "admission_boolean", "branch": index,
                            "field": "data_access_confirmed"})
        cost = admission.get("cost_judgement")
        if not isinstance(cost, dict):
            continue
        proportionate = _boolean(cost.get("proportionate"))
        if proportionate is not None:
            cost["proportionate"] = proportionate
            changes.append({"kind": "admission_boolean", "branch": index,
                            "field": "cost_judgement.proportionate"})
        rationale = cost.get("rationale")
        if not (isinstance(rationale, str) and rationale.strip()):
            texts = [f"{key.replace('_', ' ')}: {value.strip()}" for key, value in cost.items()
                     if key not in {"proportionate", "rationale"}
                     and isinstance(value, str) and value.strip()]
            if texts:
                cost["rationale"] = "; ".join(texts)
                changes.append({"kind": "admission_rationale_joined", "branch": index,
                                "fields": [key for key, value in cost.items()
                                           if key not in {"proportionate", "rationale"}
                                           and isinstance(value, str) and value.strip()]})
    return fixed, changes


def normalize_result(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """:func:`normalize_registration` and :func:`normalize_admission_shapes` together."""

    fixed, changes = normalize_registration(payload)
    fixed, more = normalize_admission_shapes(fixed)
    return fixed, [*changes, *more]


def warnings_of(changes: list[dict[str, Any]]) -> list[str]:
    """Human-readable warnings for the changes that lose or guess a reference."""

    out: list[str] = []
    for item in changes:
        if item["kind"] == "evidence_unresolved":
            out.append(f"claims[{item['claim']}].evidence {item['reference']!r} matches no "
                       "artifact; kept as unresolved_evidence")
        elif item["kind"] == "ambiguous_evidence":
            out.append(f"claims[{item['claim']}].evidence {item['reference']!r} names several "
                       f"artifacts; kept {item['kept']!r}")
        elif item["kind"] == "claim_unsupported":
            out.append(f"claims[{item['claim']}] has no resolvable evidence; status "
                       f"{item['was']} read as unsupported")
    return out
