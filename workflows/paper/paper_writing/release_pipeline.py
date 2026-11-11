"""Read-only status of a review-ready paper on its way to delivery.

The orchestrator's release pipeline (stdlib only, no YAML) asks this module once
per step what is left between ``writing_release.status == ready`` and the
management-site handoff, and then calls the existing commands itself:

* the delivery-exit formal problems (``review_flow.delivery_issues``), each with
  a remedy: ``zenodo_prepare`` for support-record identity that ``zenodo
  prepare`` regenerates from the registry (receipt, draft version, packaged
  version/DOI, Zenodo record title), ``writer`` for everything that needs an edit
  of the manuscript or of the support sources, ``human`` when the support record
  is already published and only a new Zenodo version could change it;
* whether the ready decision is still bound to the current manuscript snapshot
  and support package (otherwise ``review unified-run --delta-only``);
* what the support material still needs (``zenodo prepare`` / ``zenodo release``)
  and whether ``registry/settings.yaml#support_publication`` records the
  standing production-release authorization;
* the data-repository paths that belong to this paper (the only paths the
  orchestrator commits) and which of them differ from Git HEAD;
* whether the current version was already delivered (``delivery`` block).

Nothing here writes, builds, calls a model or uses the network.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paper_writing.registry import load_paper_metadata, load_registry_settings, paper_metadata_path
from paper_writing.support_policy import effective_publication_mode, publication_policy

STATUS_SCHEMA = "openlabs.release_status.v1"
# Support-record identity that `zenodo prepare` rebuilds from the registry: the
# draft receipt, the registered draft version, the generated package identity
# (outer version, README/manifest DOI and version) and the Zenodo record title.
# Problems in the support *sources* (CITATION.cff, a public-support-vX directory,
# the reader-facing README text) and every manuscript citation need an edit.
PREPARE_CODES = frozenset({
    "SUPPORT-STATUS-BEFORE-REVIEW", "SUPPORT-DOI-MISSING", "SUPPORT-VERSION-MISSING",
    "SUPPORT-DRAFT-VERSION", "SUPPORT-RECEIPT-MISSING", "SUPPORT-RECEIPT-VERSION",
    "SUPPORT-RECEIPT-ZENODO-VERSION", "SUPPORT-RECEIPT-DOI", "SUPPORT-PACKAGE-MISSING",
    "SUPPORT-PACKAGE-VERSION", "SUPPORT-PACKAGE-HASH", "SUPPORT-PACKAGE-SIDECAR",
    "SUPPORT-RECORD-PAPER-TITLE",
})
# What the writer is told it may touch for each class of problem.
WRITER_SCOPE = (
    "Fix only the listed delivery-exit formal problems: unresolved TODO/draft markers, "
    "internal paths, abstract length or venue format, first-person or voice findings, the "
    "AI-use declaration wording (state exactly the tools and model identifiers registered "
    "under declarations.ai_use.model_usage), the support-material citation (cite the current "
    "Version DOI, version, file name and titles verbatim from the paper registry in the first "
    "mention, the reference list and Data Availability; print a DOI only as "
    "\\url{https://doi.org/<DOI>} or through the bibliography entry, so that the change stays a "
    "text-only delta), support-source README/CITATION "
    "identity, and source files the build does not read (move them to "
    "papers/<paper_id>/retained-sources/, outside the manuscript directory). Do not change any "
    "number, table, figure content, result, claim or conclusion, and do not change the title."
)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True,
                               check=False)
    if completed.returncode != 0:
        raise ValueError((completed.stderr or completed.stdout).strip() or f"git {arguments[0]} failed")
    return completed.stdout


def commit_paths(paper_id: str, metadata: Mapping[str, Any], root: Path) -> list[str]:
    """Data-repository paths owned by one paper (registry, paper tree, review records)."""
    candidates = [paper_metadata_path(paper_id, root).relative_to(root).as_posix(),
                  f"papers/{paper_id}", f"reviews/unified/{paper_id}", f"reviews/formal-check/{paper_id}"]
    for key in ("manuscript_dir", "latest_pdf", "latest_supplementary_pdf"):
        if metadata.get(key):
            candidates.append(str(metadata[key]))
    publication = ((metadata.get("support") or {}).get("publication") or {})
    if isinstance(publication, Mapping):
        for key in ("draft_receipt", "release_receipt"):
            if publication.get(key):
                candidates.append(str(publication[key]))
        for key in ("package_files", "artifact_manifests"):
            if isinstance(publication.get(key), list):
                candidates.extend(str(item) for item in publication[key])
    review = metadata.get("ara_llm_self_review")
    if isinstance(review, Mapping) and review.get("source"):
        candidates.append(str(review["source"]))
    paths: list[str] = []
    for candidate in candidates:
        resolved = (root / candidate).resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            continue  # never commit outside the data repository
        if relative in paths or any(relative.startswith(f"{p}/") for p in paths):
            continue
        paths = [p for p in paths if not p.startswith(f"{relative}/")] + [relative]
    return paths


def _package_stale(metadata: Mapping[str, Any], root: Path) -> str | None:
    """Why the prepared draft package no longer matches its registered sources (None: current)."""
    from paper_writing.support import verify_support_archive
    from paper_writing.zenodo import _verify_archive_sources

    publication = ((metadata.get("support") or {}).get("publication") or {})
    files = [str(item) for item in publication.get("package_files") or [] if str(item).endswith(".zip")]
    sources = publication.get("source_files")
    if len(files) != 1 or not isinstance(sources, list) or not sources:
        return "the prepared package or its source list is not registered"
    try:
        archive = verify_support_archive(root / files[0])
        if str(archive.get("paper_version") or "") != str(metadata.get("version") or ""):
            return "the prepared package was built for another paper version"
        _verify_archive_sources(archive, [root / str(item) for item in sources], root)
    except Exception as exc:  # noqa: BLE001 - any mismatch means "prepare again"
        return str(exc)
    return None


def _support_status(metadata: Mapping[str, Any], settings: Mapping[str, Any],
                    root: Path) -> dict[str, Any]:
    policy = publication_policy(settings)
    raw = settings.get("support_publication")
    raw = raw if isinstance(raw, Mapping) else {}
    publication = ((metadata.get("support") or {}).get("publication") or {})
    publication = publication if isinstance(publication, Mapping) else {}
    zenodo = publication.get("zenodo") if isinstance(publication.get("zenodo"), Mapping) else {}
    mode = effective_publication_mode(publication, policy)
    status = str(publication.get("status") or "planned")
    release = metadata.get("writing_release") or {}
    package = str(publication.get("package_sha256") or "")
    required = mode != "not_required"
    environment = str(zenodo.get("environment") or "")
    stale = _package_stale(metadata, root) if required and status == "draft" else None
    return {
        "mode": mode,
        "required": required,
        "status": status,
        "environment": environment or None,
        "version_doi": publication.get("version_doi"),
        "package_sha256": package or None,
        "bound_to_review": bool(package) and release.get("support_package_sha256") == package,
        # A draft is needed (or must be moved from the sandbox to production).
        # A draft is needed, must move from the sandbox to production, or its
        # package no longer matches the registered sources/version.
        "prepare_needed": required and (status == "planned"
                                        or (status == "draft" and (environment != "production"
                                                                   or stale is not None))),
        "package_stale": stale,
        "release_needed": required and status == "draft",
        "published": required and status == "published",
        "zenodo_environment": str(raw.get("zenodo_environment") or "production"),
        "release_after_ready": raw.get("release_after_ready"),
        "standing_production_release_authorization":
            raw.get("standing_production_release_authorization") is True,
    }


def _review_status(paper_id: str, metadata: Mapping[str, Any], root: Path,
                   support: Mapping[str, Any]) -> dict[str, Any]:
    from paper_writing.handoff import _release_paths, manuscript_snapshot_sha256
    from paper_writing.review_flow import validate_unified_release

    release = metadata.get("writing_release") or {}
    ready = isinstance(release, Mapping) and release.get("status") == "ready"
    problems: list[str] = []
    if ready:
        try:
            manuscript, pdf, _ = _release_paths(paper_id, root, metadata)
            problems = validate_unified_release(paper_id, metadata, root,
                                                manuscript_snapshot_sha256(manuscript, pdf))
        except Exception as exc:  # noqa: BLE001 - any failure means "not current"
            problems = [f"{type(exc).__name__}: {exc}"]
        if support.get("required") and support.get("package_sha256") and not support.get("bound_to_review"):
            problems.append("The ready decision is not bound to the current support package")
    return {"ready": ready, "current": ready and not problems, "problems": problems,
            "review_mode": release.get("review_mode", "full") if ready else None,
            "decision_record": release.get("decision_record"),
            "version": str(metadata.get("version") or "")}


def release_status(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Everything the release pipeline decides its next step from (read-only)."""
    from paper_writing.review_flow import delivery_issues

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    settings = load_registry_settings(repo_root)
    support = _support_status(metadata, settings, repo_root)
    review = _review_status(paper_id, metadata, repo_root, support)
    release = metadata.get("writing_release") or {}
    record = None
    if isinstance(release, Mapping) and release.get("decision_record"):
        path = repo_root / str(release["decision_record"])
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
    notes: list[dict[str, Any]] = []
    try:
        raw_issues = delivery_issues(paper_id, metadata, repo_root, record, notes=notes)
    except Exception as exc:  # noqa: BLE001 - reported, never guessed around
        raw_issues = [{"source": "release_status", "code": "DELIVERY-CHECK-FAILED", "location": "",
                       "message": str(exc), "text": f"Delivery formal check could not run: {exc}"}]
    issues = []
    for item in raw_issues:
        code = str(item.get("code") or "")
        if code in PREPARE_CODES:
            remedy = "zenodo_prepare" if not support["published"] else "human"
        elif code == "DELIVERY-CHECK-FAILED":
            remedy = "human"
        else:
            remedy = "writer"
        issues.append({**item, "remedy": remedy})
    paths = commit_paths(paper_id, metadata, repo_root)
    try:
        head = _git(repo_root, "rev-parse", "HEAD").strip()
        dirty = [line for line in _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all",
                                        "--", *paths).splitlines() if line.strip()]
        git = {"head": head, "dirty": dirty, "clean": not dirty}
    except (OSError, ValueError) as exc:
        git = {"head": None, "dirty": [], "clean": False, "error": str(exc)}
    delivery = metadata.get("delivery") if isinstance(metadata.get("delivery"), Mapping) else {}
    version = str(metadata.get("version") or "")
    return {
        "schema_version": STATUS_SCHEMA,
        "paper_id": paper_id,
        "version": version,
        "title": metadata.get("title"),
        "review": review,
        "support": support,
        "issues": issues,
        "notes": [{"kind": str(note.get("kind") or ""), "code": str(note.get("code") or ""),
                   "message": str(note.get("message") or note.get("note") or "")} for note in notes],
        "writer_scope": WRITER_SCOPE.replace("<paper_id>", paper_id),
        "commit_paths": paths,
        "git": git,
        "delivered": bool(delivery.get("package_id")) and str(delivery.get("version") or "") == version,
        "delivery": dict(delivery) if delivery else None,
    }
