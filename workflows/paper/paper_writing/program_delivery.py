"""Research-program delivery: provisional escalation, automatic handoff and handler assignment.

The orchestrator (stdlib only) calls these through ``paper-writing program ...``:

* ``register-escalation`` -- a writer registering the paper of a topic the admission
  gate judged ``escalation`` records ``target_escalation`` as ``provisional``
  (approved by the admission task, strength evidence = admission record path and
  hash, fallback = the card's routine venue, whose eligibility evidence -- SCIE, 2025
  CAS major-category zone, fee-free route covering page/colour/submission charges --
  is checked before it is recorded). It may be reviewed on the escalation
  track but not delivered at that target until the unified review's score meets
  ``venue_eligibility.escalation.minimum_internal_score``.
* ``check-fallback`` -- before a paper falls back to its registered fallback venue,
  complete (``--fallback-evidence``) and re-check that venue's eligibility evidence;
  older records registered without it must pass this before the fallback is used.
* ``deliver`` -- the ordinary immutable handoff to the paper-management site. It
  never sends or records a submission handler; after a successful release the
  registry records ``delivery.awaiting_owner_review: true`` and a qualifying
  provisional escalation becomes ``approved``.
* ``assign-handler`` -- after the owner's review, record the default second author
  (``registry/settings.yaml#defaults.authors[1]``) as the paper's submission
  handler. It does not submit anything and does not authorize a journal submission.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from paper_writing.deliverable import second_author
from paper_writing import venue_policy
from paper_writing.registry import (
    load_paper_metadata,
    load_registry_settings,
    settings_path,
    write_paper_metadata,
)

HANDLER_ROLE = "submission_handler"
DEFAULT_HANDLER = "second_author"


class ProgramDeliveryError(RuntimeError):
    """A program delivery step cannot proceed."""


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _policy(root: Path) -> Mapping[str, Any]:
    settings = load_registry_settings(root) if settings_path(root).is_file() else {}
    policy = settings.get("journal_target_policy")
    return policy if isinstance(policy, Mapping) else {}


def _load_fallback_evidence(evidence: Mapping[str, Any] | str | Path | None,
                            repo_root: Path) -> Mapping[str, Any] | None:
    if evidence is None or isinstance(evidence, Mapping):
        return evidence
    path = Path(evidence)
    if not path.is_absolute():
        path = repo_root / path
    if not path.is_file():
        raise ProgramDeliveryError(f"fallback evidence file is missing: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ProgramDeliveryError(f"fallback evidence must be a JSON/YAML object: {path}")
    return data


def _check_fallback(evidence: Any, *, fallback_venue: str, repo_root: Path) -> None:
    problems = venue_policy.fallback_eligibility_problems(
        evidence, fallback_venue=fallback_venue, policy=_policy(repo_root)
    )
    if problems:
        raise ProgramDeliveryError(
            "fallback venue eligibility check failed: " + "; ".join(problems)
        )


def register_provisional_escalation(
    paper_id: str,
    *,
    root: str | Path,
    venue: str,
    admission_task_id: str,
    admission_record: str | Path,
    fallback_venue: str,
    fallback_evidence: Mapping[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    """Record ``target_escalation: provisional`` from an admission-gate escalation verdict.

    The fallback venue must carry the same eligibility evidence as a registered target
    (``venue_policy.fallback_eligibility_problems``); without it nothing is recorded.
    """

    repo_root = Path(root).resolve()
    record_path = Path(admission_record)
    if not record_path.is_absolute():
        record_path = repo_root / record_path
    if not record_path.is_file():
        raise ProgramDeliveryError(f"admission record is missing: {record_path}")
    for name, value in (("venue", venue), ("admission_task_id", admission_task_id),
                        ("fallback_venue", fallback_venue)):
        if not str(value or "").strip():
            raise ProgramDeliveryError(f"{name} is required")
    evidence = _load_fallback_evidence(fallback_evidence, repo_root)
    _check_fallback(evidence, fallback_venue=fallback_venue.strip(), repo_root=repo_root)
    digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
    metadata = load_paper_metadata(paper_id, repo_root)
    existing = metadata.get("target_escalation")
    if isinstance(existing, Mapping) and existing.get("status") == "approved":
        raise ProgramDeliveryError(f"{paper_id} already has an approved target_escalation")
    record = {
        "status": "provisional",
        "venue": venue.strip(),
        "approved_by": f"admission:{admission_task_id.strip()}",
        "approved_at": _today(),
        "strength_evidence": f"{record_path} (sha256 {digest})",
        "strength_evidence_sha256": digest,
        "fallback_venue": fallback_venue.strip(),
    }
    if evidence:
        record["fallback_eligibility"] = dict(evidence)
    metadata["target_escalation"] = record
    write_paper_metadata(paper_id, metadata, repo_root)
    return {"paper_id": paper_id, "target_escalation": record}


def check_fallback(
    paper_id: str,
    *,
    root: str | Path,
    fallback_evidence: Mapping[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    """Gate the fall-back step: the registered fallback venue must be eligible now.

    ``fallback_evidence`` completes or refreshes ``target_escalation.fallback_eligibility``
    (required for records registered before the evidence existed). Only evidence that
    passes is written; the target itself is changed by the retarget step afterwards.
    """

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    record = metadata.get("target_escalation")
    if not isinstance(record, Mapping) or not str(record.get("fallback_venue") or "").strip():
        raise ProgramDeliveryError(f"{paper_id} has no target_escalation with a fallback_venue")
    fallback = str(record["fallback_venue"]).strip()
    evidence = _load_fallback_evidence(fallback_evidence, repo_root)
    if evidence is None:
        evidence = record.get("fallback_eligibility")
    _check_fallback(evidence, fallback_venue=fallback, repo_root=repo_root)
    changed = evidence != record.get("fallback_eligibility")
    if changed:
        updated = dict(record)
        updated["fallback_eligibility"] = dict(evidence)
        metadata["target_escalation"] = updated
        write_paper_metadata(paper_id, metadata, repo_root)
    return {"paper_id": paper_id, "fallback_venue": fallback, "eligible": True,
            "evidence_updated": changed}


def confirm_escalation(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Turn a qualifying provisional escalation into ``approved`` (score from the review)."""

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    record = metadata.get("target_escalation")
    if not isinstance(record, Mapping) or record.get("status") != "provisional":
        return {"paper_id": paper_id, "changed": False,
                "status": record.get("status") if isinstance(record, Mapping) else None}
    policy = _policy(repo_root)
    problems = venue_policy.provisional_escalation_blockers(
        metadata, policy, paper_id=paper_id, root=repo_root
    )
    if problems:
        raise ProgramDeliveryError(problems[0])
    release = metadata.get("writing_release") or {}
    approved = dict(record)
    approved.update({
        "status": "approved",
        "approved_at": _today(),
        "internal_review_score": release.get("score"),
        "internal_review_source": str(release.get("decision_record") or ""),
        "provisional_approved_by": record.get("approved_by"),
    })
    config = venue_policy.eligibility_config(policy)
    configured = config["escalation"]["minimum_internal_score"] if config else None
    score = release.get("score")
    if (configured is not None and isinstance(score, (int, float)) and not isinstance(score, bool)
            and float(score) < configured and isinstance(record.get("score_waiver"), Mapping)):
        # Approved under the owner's score waiver, not by meeting the configured bar.
        approved["score_waiver_applied"] = {"configured_minimum": configured,
                                            "minimum_accepted_score": record["score_waiver"]["minimum_accepted_score"]}
    metadata["target_escalation"] = approved
    write_paper_metadata(paper_id, metadata, repo_root)
    return {"paper_id": paper_id, "changed": True, "target_escalation": approved}


def deliver(
    paper_id: str,
    *,
    root: str | Path,
    client: Any,
    release: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Immutable handoff without a submission handler; mark the paper for the owner's review."""

    from paper_writing.handoff import release_handoff

    repo_root = Path(root).resolve()
    result = dict((release or release_handoff)(paper_id, root=repo_root, client=client))
    escalation = confirm_escalation(paper_id, root=repo_root)
    metadata = load_paper_metadata(paper_id, repo_root)
    metadata["delivery"] = {
        "awaiting_owner_review": True,
        "delivered_at": _now(),
        "package_id": result.get("package_id"),
        "version": result.get("version"),
        "receipt": result.get("receipt"),
        "submission_handler": None,
        "delivered_by": "research_program_auto_handoff",
    }
    write_paper_metadata(paper_id, metadata, repo_root)
    return {
        "schema_version": "openlabs.program_delivery.v1",
        "status": "delivered",
        "paper_id": paper_id,
        "package_id": result.get("package_id"),
        "version": result.get("version"),
        "receipt": result.get("receipt"),
        "awaiting_owner_review": True,
        "submission_handler": None,
        "escalation_confirmed": bool(escalation.get("changed")),
    }


CLOSED_ATTEMPTS = frozenset({"cancelled", "canceled", "abandoned", "withdrawn_before_submission"})


def supplement_submission_package(
    paper_id: str,
    *,
    root: str | Path,
    client: Any,
    release: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Give a delivered, not yet submitted version its submission package (user 2026-11-26).

    Versions delivered before 2026-11-25 carry the LaTeX source.zip. This uploads the same
    version again with the submission package (投稿包) in the source slot -- same PDF, same
    reviewed manuscript, same gate -- so the site lists it under 投稿包. The paper must be the
    delivered version, still carry source.zip, have no submission attempt on the site, and have
    ``paper-writing submission prepare`` drafts for this version. The registry keeps the
    delivery (date, owner review, submitter) and records the new package beside the old one.
    """
    from paper_writing.handoff import release_handoff
    from paper_writing import submission_bundle

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    version = str(metadata.get("version") or "")
    delivery = metadata.get("delivery") if isinstance(metadata.get("delivery"), Mapping) else {}
    if not delivery.get("package_id") or str(delivery.get("version") or "") != version:
        raise ProgramDeliveryError(f"{paper_id}: v{version} is not the delivered version")
    if not submission_bundle.legacy_source_required(repo_root, paper_id, version):
        raise ProgramDeliveryError(f"{paper_id}: v{version} has no source.zip delivery to supplement "
                                   "(already a submission package, or never delivered)")
    external = metadata.get("external_submission")
    if isinstance(external, Mapping) and external.get("status"):
        raise ProgramDeliveryError(f"{paper_id}: registry records an external submission "
                                   f"({external.get('status')})")
    drafts = submission_bundle.drafts_dir(repo_root, paper_id)
    receipt = submission_bundle._read_json(drafts / "draft-receipt.json") or {}
    if str(receipt.get("version")) != version or receipt.get("status") != "drafted":
        raise ProgramDeliveryError(f"{paper_id}: run `paper-writing submission prepare` for v{version} first")
    site = client._request("GET", f"/v1/papers/{paper_id}", allow_not_found=True)
    if not isinstance(site, Mapping):
        raise ProgramDeliveryError(f"{paper_id}: not on the management site")
    current = next((item for item in site.get("packages") or []
                    if item.get("id") == site.get("current_package_id")), {})
    if current.get("package_id") != delivery.get("package_id"):
        raise ProgramDeliveryError(f"{paper_id}: the site's current package {current.get('package_id')} "
                                   f"is not the registry's delivered {delivery.get('package_id')}")
    attempts = [item for item in site.get("submission_attempts") or []
                if str(item.get("status") or "") not in CLOSED_ATTEMPTS]
    if attempts:
        raise ProgramDeliveryError(f"{paper_id}: the site has a submission attempt "
                                   f"({attempts[0].get('status')}); its package stays as submitted")
    result = dict((release or release_handoff)(paper_id, root=repo_root, client=client,
                                               submission_package=True))
    metadata = load_paper_metadata(paper_id, repo_root)
    updated = dict(metadata.get("delivery") or {})
    supplements = list(updated.get("submission_package_supplements") or [])
    supplements.append({"at": _now(), "previous_package_id": updated.get("package_id"),
                        "package_id": result.get("package_id"), "receipt": result.get("receipt"),
                        "rule": "user 2026-11-26: 已交付、未投稿的稿件补投稿包"})
    updated.update({"package_id": result.get("package_id"), "receipt": result.get("receipt"),
                    "submission_package_supplements": supplements})
    metadata["delivery"] = updated
    write_paper_metadata(paper_id, metadata, repo_root)
    return {
        "schema_version": "openlabs.program_delivery.v1",
        "status": "supplemented",
        "paper_id": paper_id,
        "version": result.get("version"),
        "previous_package_id": supplements[-1]["previous_package_id"],
        "package_id": result.get("package_id"),
        "receipt": result.get("receipt"),
        "manage_package_status": result.get("manage_package_status"),
        "site_assignment": result.get("site_assignment"),
    }


def default_handler(root: str | Path, handler: str = DEFAULT_HANDLER,
                    paper: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve ``second_author`` (registry default roster) or a named author."""

    settings = load_registry_settings(Path(root).resolve())
    defaults = settings.get("defaults") if isinstance(settings.get("defaults"), Mapping) else {}
    roster = defaults.get("authors") if isinstance(defaults, Mapping) else None
    if not isinstance(roster, list) or not all(isinstance(item, Mapping) for item in roster):
        raise ProgramDeliveryError("registry/settings.yaml#defaults.authors is missing")
    if handler == DEFAULT_HANDLER:
        # The paper's second author, else the roster's (deliverable.second_author, the rule the
        # site submitter sync uses too). A byline entry without an email takes the roster's.
        found = second_author(paper, roster)
        if found is None:
            raise ProgramDeliveryError("the default author roster has no second author")
        person = found[0]
        if not str(person.get("email") or "").strip():
            names = {str(person.get(key) or "").strip().casefold() for key in ("name", "name_zh")} - {""}
            person = next((dict(person, email=item["email"]) for item in roster
                           if str(item.get("email") or "").strip() and names & {
                               str(item.get(key) or "").strip().casefold()
                               for key in ("name", "name_zh")}), None)
            if person is None:
                # No address for the byline's second author: the roster's, as the site sync
                # falls back when that author has no site account.
                fallback = second_author(None, roster)
                if fallback is None:
                    raise ProgramDeliveryError("the default author roster has no second author")
                person = fallback[0]
    else:
        people = list(roster)
        authors = (paper or {}).get("authors")
        if isinstance(authors, Mapping) and isinstance(authors.get("people"), list):
            people = [*authors["people"], *people]
        matches = [item for item in people if isinstance(item, Mapping)
                   and handler.strip().casefold() in {
                       str(item.get("name") or "").casefold(),
                       str(item.get("name_zh") or "").casefold()}]
        if not matches:
            raise ProgramDeliveryError(f"no author named {handler!r} in the roster or byline")
        person = matches[0]
    if not str(person.get("name") or "").strip() or not str(person.get("email") or "").strip():
        raise ProgramDeliveryError("the selected handler needs a name and an email")
    return {"name": str(person["name"]), "email": str(person["email"])}


def assign_handler(paper_id: str, *, root: str | Path,
                   handler: str = DEFAULT_HANDLER) -> dict[str, Any]:
    """Record the submission handler after the owner's review (no submission, no payment)."""

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    person = default_handler(repo_root, handler, metadata)
    previous = metadata.get("submission_contact")
    metadata["submission_contact"] = {
        **person,
        "role": HANDLER_ROLE,
        "journal_submission_authorized": False,
        "assigned_at": _now(),
        "assigned_after": "owner_review",
        "rule": handler,
    }
    delivery = dict(metadata.get("delivery") or {})
    delivery.update({"awaiting_owner_review": False, "owner_reviewed_at": _now(),
                     "submission_handler": person["name"]})
    metadata["delivery"] = delivery
    write_paper_metadata(paper_id, metadata, repo_root)
    return {
        "schema_version": "openlabs.program_handler_assignment.v1",
        "status": "assigned",
        "paper_id": paper_id,
        "submission_handler": person["name"],
        "rule": handler,
        "previous": dict(previous) if isinstance(previous, Mapping) else None,
        "journal_submission_authorized": False,
    }
