"""Read-only status of a review-ready paper on its way to delivery.

The orchestrator's release pipeline (stdlib only, no YAML) asks this module once
per step what is left between ``writing_release.status == ready`` and the
management-site handoff, and then calls the existing commands itself:

* the delivery-exit formal problems (``review_flow.delivery_issues``), each with
  a remedy: ``zenodo_prepare`` for support-record identity that ``zenodo
  prepare`` regenerates from the registry (receipt, draft version, packaged
  version/DOI, Zenodo record title), a control-plane retry for mechanical
  discrepancies, and ``human`` when the support record
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

from paper_writing.registry import (freeze_block_reason, load_paper_metadata, load_registry_settings, paper_layout_problems,
                                    paper_metadata_path)
from paper_writing.support import _record_version
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
    # A selected claim-evidence map not (or not identically) in the current-version ZIP.
    "SUPPORT-CLAIM-MAP-UNPACKAGED", "SUPPORT-CLAIM-MAP-PACKAGE-MISMATCH",
})
# Release build products Git ignores; delivery freezes them through
# papers/<id>/production/release-artifacts.json (``program bind-release-artifacts``).
RELEASE_ARTIFACT_SUFFIXES = frozenset({".pdf", ".bbl"})
# Paper files over the Git payload limit (formal-check evidence bodies, large records):
# kept out of Git by an anchored .gitignore entry next to each file and bound here by
# path, size, SHA-256 and content-addressed artifact URI (``program bind-oversize-payloads``).
PAYLOAD_MANIFEST_TEMPLATE = "papers/{paper_id}/production/payload-artifacts.json"
# What the writer is told it may touch for each class of problem.
WRITER_SCOPE = (
    "Fix only the listed delivery checks, including the body-text minimum, approved byline and "
    "affiliations, missing design schematic or result figures, and unresolved TODO/draft markers. "
    "Use only previously verified results in figures. Add needed methodological or result context "
    "from the supplement and run paper-writing delivery-floor --author before returning the draft. Fix "
    "internal paths, abstract length or venue format, first-person or voice findings, the "
    "AI-use declaration wording (state exactly the tools and model identifiers registered "
    "under declarations.ai_use.model_usage), the support-material citation (cite the current "
    "Version DOI, version, file name and titles verbatim from the paper registry in the first "
    "mention, the reference list and Data Availability; print a DOI only as "
    "\\url{https://doi.org/<DOI>} or through the bibliography entry, so that the change stays a "
    "text-only delta), support-source README/CITATION "
    "identity, and source files the build does not read (move them to "
    "papers/<paper_id>/retained-sources/, outside the manuscript directory). Do not change any "
    "number, table, result, claim, conclusion or title. Preserve existing figure results."
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


def release_artifact_candidates(paper_id: str, metadata: Mapping[str, Any], root: Path) -> list[str]:
    """Every current release build product (PDF/.bbl) that Git ignores and does not track."""
    from paper_writing.handoff import _release_paths

    try:
        manuscript, _, files = _release_paths(paper_id, root, metadata)
    except Exception:  # noqa: BLE001 - reported by the review/issue checks instead
        return []
    candidates = sorted({path.resolve().relative_to(root).as_posix() for path in files
                         if path.resolve().is_relative_to(manuscript.resolve())
                         and path.suffix.lower() in RELEASE_ARTIFACT_SUFFIXES})
    if not candidates:
        return []
    tracked = set(_git(root, "ls-files", "--cached", "-z", "--", *candidates).split("\0"))
    untracked = [item for item in candidates if item not in tracked]
    if not untracked:
        return []
    completed = subprocess.run(["git", "check-ignore", "--", *untracked], cwd=root,
                               capture_output=True, text=True, check=False)
    ignored = set(completed.stdout.split())
    return [item for item in untracked if item in ignored]


def _bound_release_artifacts(paper_id: str, pointer: Any, root: Path) -> dict[str, str]:
    """``{path: sha256}`` recorded in the release artifact manifest (empty when unreadable)."""
    name = (pointer.get("path") if isinstance(pointer, Mapping) else None) \
        or f"papers/{paper_id}/production/release-artifacts.json"
    manifest = root / str(name)
    try:
        content = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = content.get("files") if isinstance(content, Mapping) else None
    return {str(item.get("path")): str(item.get("sha256"))
            for item in files or [] if isinstance(item, Mapping)}


def unbound_release_artifacts(paper_id: str, metadata: Mapping[str, Any], root: Path) -> list[str]:
    """Release build products (PDF/.bbl) Git ignores and the artifact manifest does not freeze.

    ``handoff release`` requires every release file to be in Git or bound through
    ``submission_package.artifact_manifest``; an empty list means nothing to bind.
    With a manifest already recorded (an earlier delivery), a candidate is unbound
    when the manifest lacks it or records other bytes (a new build after a revision).
    """
    from paper_writing.support import sha256_file

    candidates = release_artifact_candidates(paper_id, metadata, root)
    pointer = (metadata.get("submission_package") or {}).get("artifact_manifest")
    if not pointer or not candidates:
        return candidates
    bound = _bound_release_artifacts(paper_id, pointer, root)
    stale = []
    for item in candidates:
        try:
            current = sha256_file(root / item)
        except OSError:
            current = None
        if bound.get(item) != current:
            stale.append(item)
    return stale


def _bound_payloads(paper_id: str, root: Path) -> dict[str, str]:
    """``{path: sha256}`` of ``papers/<id>/production/payload-artifacts.json`` (empty: none)."""
    manifest = root / PAYLOAD_MANIFEST_TEMPLATE.format(paper_id=paper_id)
    try:
        content = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = content.get("files") if isinstance(content, Mapping) else None
    return {str(item.get("path")): str(item.get("sha256"))
            for item in files or [] if isinstance(item, Mapping)}


def _unadopted_support_sources(paper_id: str, metadata: Mapping[str, Any],
                               root: Path) -> list[tuple[str, str]]:
    from paper_writing.program_adopt import unadopted_support_sources

    try:
        return unadopted_support_sources(paper_id, metadata, root)
    except Exception:  # noqa: BLE001 - a malformed record is reported by other checks
        return []


def oversize_payloads(paper_id: str, paths: list[str], root: Path) -> list[str]:
    """Files of this paper the release commit would take in but the data repository refuses.

    The data repository's pre-commit hook refuses any blob over the Git payload limit
    (5 MiB). A file under the paper's commit paths that is new to Git (untracked and
    not ignored, or staged but absent from HEAD) and larger than that limit cannot be
    committed (2026-11-20: an 8 MB formal-check evidence body stopped the PMB-13B
    release three times). ``program bind-oversize-payloads`` moves such files out of
    Git into the content-addressed artifact store. A bound file whose bytes changed
    afterwards is listed again so its binding is renewed.
    """
    from paper_writing.support import GIT_PAYLOAD_LIMIT_BYTES, sha256_file

    if not paths:
        return []
    try:
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *paths)
    except (OSError, ValueError):
        return []
    try:
        # Left staged by an earlier commit attempt the pre-commit hook refused.
        staged_new = _git(root, "diff", "--cached", "--name-only", "--diff-filter=A", "-z",
                          "HEAD", "--", *paths)
    except (OSError, ValueError):
        staged_new = ""  # no HEAD yet: everything is untracked
    names = {item for item in (untracked + "\0" + staged_new).split("\0") if item}
    found = []
    for name in sorted(names):
        path = root / name
        if path.is_file() and not path.is_symlink() and path.stat().st_size > GIT_PAYLOAD_LIMIT_BYTES:
            found.append(name)
    bound = _bound_payloads(paper_id, root)
    for name, digest in sorted(bound.items()):
        path = root / name
        if name in found or not path.is_file():
            continue
        try:
            if sha256_file(path) != digest:
                found.append(name)
        except OSError:
            continue
    return found


def _package_stale(metadata: Mapping[str, Any], root: Path) -> str | None:
    """Why the package no longer matches its registered sources (None: current)."""
    from paper_writing.support import resolve_support_sources, verify_support_archive
    from paper_writing.zenodo import _verify_archive_sources

    publication = ((metadata.get("support") or {}).get("publication") or {})
    files = [str(item) for item in publication.get("package_files") or [] if str(item).endswith(".zip")]
    sources = publication.get("source_files")
    if len(files) != 1 or not isinstance(sources, list) or not sources:
        return "the prepared package or its source list is not registered"
    try:
        archive = verify_support_archive(root / files[0])
        if archive.get("paper_version") != _record_version(metadata):
            return "the package was built for another support release version"
        if archive.get("paper_id") != metadata.get("paper_id"):
            return "the package belongs to another paper"
        if archive.get("archive_sha256") != publication.get("package_sha256"):
            return "the package SHA-256 differs from the registry"
        _verify_archive_sources(archive, resolve_support_sources(metadata, repo_root=root), root)
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
    previous_version = (status == "published" and zenodo.get("version")
                        and str(zenodo["version"]) != _record_version(metadata))
    pinned_version = publication.get("release_version")
    reusing_published = (status == "published" and not previous_version
                         and isinstance(pinned_version, str) and bool(pinned_version.strip()))
    stale = _package_stale(metadata, root) if required and (
        status == "draft" or reusing_published) else None
    return {
        "mode": mode,
        "required": required,
        "status": status,
        "environment": environment or None,
        "version_doi": publication.get("version_doi"),
        "package_sha256": package or None,
        "bound_to_review": bool(package) and release.get("support_package_sha256") == package,
        # A draft is needed, must move from the sandbox to production, or its
        # package no longer matches the registered sources/version.
        "prepare_needed": required and (status == "planned" or bool(previous_version)
                                        or (status == "draft" and (environment != "production"
                                                                   or stale is not None))),
        "package_stale": stale,
        "release_needed": required and status == "draft",
        "published": required and status == "published" and not previous_version and stale is None,
        "published_package_stale": stale if reusing_published else None,
        "zenodo_environment": str(raw.get("zenodo_environment") or "production"),
        "release_after_ready": raw.get("release_after_ready"),
        "standing_production_release_authorization":
            raw.get("standing_production_release_authorization") is True,
    }


def _review_status(paper_id: str, metadata: Mapping[str, Any], root: Path,
                   support: Mapping[str, Any]) -> dict[str, Any]:
    from paper_writing.handoff import _release_paths, manuscript_snapshot_sha256
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.review_flow import validate_unified_release

    release = metadata.get("writing_release") or {}
    ready = isinstance(release, Mapping) and release.get("status") == "ready"
    problems: list[str] = []
    decision_current = False
    if ready:
        try:
            manuscript, pdf, _ = _release_paths(paper_id, root, metadata)
            problems = validate_unified_release(paper_id, metadata, root,
                                                manuscript_snapshot_sha256(manuscript, pdf))
            if not problems:
                record = json.loads((root / release["decision_record"]).read_bytes())
                if (record.get("paper_id") != paper_id
                        or record.get("manuscript_version") != str(metadata.get("version") or "")):
                    problems.append("The unified decision belongs to another paper or version")
                elif not support.get("prepare_needed") and not release.get("publication_metadata"):
                    fingerprints = _review_workspace_fingerprints(paper_id, metadata, root)
                    for key, value in fingerprints.items():
                        if record["fingerprints"].get(key) != value or release.get(key) != value:
                            problems.append(f"Reviewed input changed: {key}")
        except Exception as exc:  # noqa: BLE001 - any failure means "not current"
            problems = [f"{type(exc).__name__}: {exc}"]
        if str(release.get("manuscript_version") or "") != str(metadata.get("version") or ""):
            problems.append("The ready decision is for a different manuscript version")
        decision_current = not problems
        if support.get("required") and support.get("package_sha256") and not support.get("bound_to_review"):
            problems.append("The ready decision is not bound to the current support package")
    cap = None
    target = metadata.get("target_journal")
    if target and not ready:
        from paper_writing import review_flow
        rounds = review_flow.scientific_rounds(root, paper_id, target)
        if rounds:
            override = review_flow.review_round_limit_override(metadata, root, paper_id, target)
            maximum = (override or review_flow.review_config(root))["max_rounds_per_target"]
            cap = review_flow.exhausted_review(root, paper_id, target, rounds, maximum)
    return {"exhausted_review": cap, "ready": ready, "current": ready and not problems, "problems": problems,
            "decision_current": decision_current,
            "decision_sha256": release.get("decision_record_sha256"),
            "review_mode": release.get("review_mode", "full") if ready else None,
            "decision_record": release.get("decision_record"),
            "version": str(metadata.get("version") or "")}


def release_status(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Everything the release pipeline decides its next step from (read-only)."""
    from paper_writing.declarations import missing_default_contributions
    from paper_writing.deliverable import delivered as current_version_delivered
    from paper_writing.deliverable import exit_issues, summarize
    from paper_writing.publication_metadata import CODES

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
        raw_issues = exit_issues(paper_id, metadata, repo_root, record, notes=notes)
    except Exception as exc:  # noqa: BLE001 - reported, never guessed around
        raw_issues = [{"source": "release_status", "code": "DELIVERY-CHECK-FAILED", "location": "",
                       "message": str(exc), "text": f"Delivery formal check could not run: {exc}"}]
    manuscript_dir = repo_root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    manuscript_missing = not manuscript_dir.is_dir() or not (manuscript_dir / "main.tex").is_file()
    issues = []
    if manuscript_missing:
        # A writer cannot repair a manuscript that is not where the registry points; every
        # text finding is then a consequence of the missing source.
        issues.append({"source": "release_status", "code": "MANUSCRIPT-SOURCE-MISSING",
                       "location": str(metadata.get("manuscript_dir") or ""),
                       "message": f"the registered manuscript source is missing: {manuscript_dir}",
                       "text": "MANUSCRIPT-SOURCE-MISSING: the registered manuscript directory "
                               f"or its main.tex is missing ({manuscript_dir})",
                       "remedy": "control_plane"})
    for item in raw_issues:
        code = str(item.get("code") or "")
        if code in CODES and support["prepare_needed"] and review.get("decision_current"):
            remedy = "zenodo_prepare"
        elif code in CODES and support["release_needed"] and review.get("decision_current"):
            remedy = "publication_metadata"
        elif (code in CODES and support["release_needed"] and not support["prepare_needed"]
              and review.get("ready")):
            # Projection requires the ready decision to cover the current inputs.
            remedy = "delta_review"
        elif code in {"FIGURES-NOT-REVIEWED", "SCHEMATIC-ROUTE-UNREVIEWED"}:
            remedy = "delta_review"
            if review.get("ready"):
                review["current"] = False
        elif item.get("source") == "delivery_floor" and code != "FLOOR-SOURCE-MISSING":
            remedy = "writer"
        elif code in PREPARE_CODES:
            remedy = "zenodo_prepare" if not support["published"] else "human"
        else:
            remedy = "control_plane"
        issues.append({**item, "remedy": remedy})
    # These diagnostics go through the existing delta-only gate, which can refuse
    # the carry-forward and route the paper back to independent review.
    if review.get("ready") and not review.get("current") and not support.get("prepare_needed"):
        issues.extend(dict(source="review_binding", code="REVIEW-SNAPSHOT-MISMATCH", location="registry",
                           message=problem, text=problem, remedy="delta_review")
                      for problem in review.get("problems", []))
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
    status = {
        "schema_version": STATUS_SCHEMA,
        "paper_id": paper_id,
        "version": version,
        "title": metadata.get("title"),
        "target_journal": metadata.get("target_journal"),
        # Non-null for a frozen paper: the pipeline must take no step for it.
        "frozen": freeze_block_reason(metadata, paper_id),
        # Non-empty for a record still laid out relative to a private root; `program adopt`
        # relocates it (reported, not blocking).
        "layout_problems": paper_layout_problems(paper_id, metadata),
        "review": review,
        "support": support,
        "issues": issues,
        "notes": [{"kind": str(note.get("kind") or ""), "code": str(note.get("code") or ""),
                   "message": str(note.get("message") or note.get("note") or "")} for note in notes],
        "publication_metadata_pending": bool(release.get("publication_metadata"))
                                        and review.get("decision_current", False)
                                        and support["release_needed"] and not support["bound_to_review"],
        "missing_default_contributions": missing_default_contributions(metadata, repo_root),
        "writer_scope": WRITER_SCOPE.replace("<paper_id>", paper_id),
        "release_artifacts_unbound": ([] if manuscript_missing
                                      else unbound_release_artifacts(paper_id, metadata, repo_root)),
        "figure_review_binding": {"field": metadata.get("field"),
                                 "decision": release.get("decision_record"),
                                 "sha256": release.get("decision_record_sha256")},
        "commit_paths": paths,
        # Files the release commit would refuse (over the Git payload limit); the
        # pipeline binds them to the artifact store before its next commit.
        "oversize_payloads_unbound": oversize_payloads(paper_id, paths, repo_root),
        # Support sources still registered at their campaign-workspace path although
        # adopt copied them under papers/<id>/support-materials/ (program
        # relocate-support-sources rewrites them before zenodo prepare).
        "support_sources_unadopted": [registered for registered, _copy in
                                      _unadopted_support_sources(paper_id, metadata, repo_root)],
        "git": git,
        # The current version is delivered: delivery block plus its receipt (deliverable.py).
        "delivered": current_version_delivered(metadata, repo_root, paper_id),
        "delivery": dict(delivery) if delivery else None,
    }
    # The submission package's model/TeX inputs for this version (submission_bundle.prepare):
    # the release pipeline runs `paper-writing submission prepare` once before delivery.
    try:
        from paper_writing.submission_bundle import materials_status

        status["submission_materials"] = (None if manuscript_missing
                                          else materials_status(paper_id, root=repo_root, metadata=metadata))
    except Exception as exc:  # noqa: BLE001 - advisory; never blocks delivery
        status["submission_materials"] = {"pending": False, "error": str(exc)[:300]}
    # The one deliverability verdict (deliverable.py, B5): what queue_registered_ready and the
    # site submitter rule read.
    status["deliverable"] = summarize(status)
    return status
