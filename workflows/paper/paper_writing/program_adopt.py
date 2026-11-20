"""Bring a campaign-workspace paper into the data repository, and waive its public deposit.

Owner-mode research writes and reviews its paper inside the campaign workspace
(``workspaces/<domain>/<campaign>/``, not tracked by Git). The release pipeline,
the commits and the delivery work on the data repository root, so a ready paper
is first *adopted*:

* ``program adopt`` copies the paper's registry record, ``papers/<id>/`` and its
  unified-review and formal-check records from the workspace into the root, plus
  the registered support source files into ``papers/<id>/support-materials/``.
  Nothing that already exists with different bytes is overwritten. Files the
  attempt archive kept out of the workspace (the canonical PDF, the formal-check
  evidence bodies) are restored from the review task's archived result bundle:
  an evidence file only when its bytes match the SHA-256 the formal-check report
  binds, the PDF only when it reproduces the manuscript snapshot the ready
  decision is bound to. Copying changes no reviewed byte.
* ``program waive-support`` records ``support.publication.mode: not_required``
  with its reason (the owner's decision that no Zenodo or other public deposit is
  made). It refuses when a support record already exists or when the manuscript's
  data-availability section names a Zenodo deposit, so the manuscript never cites
  a deposit that will not exist.

Neither command uses the network, a model or Git.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from paper_writing.registry import load_paper_metadata, paper_metadata_path, write_paper_metadata

ADOPT_SCHEMA = "openlabs.paper_adopt.v1"
WAIVE_SCHEMA = "openlabs.support_waiver.v1"
SUPPORT_COPY_DIR = "support-materials"
# Archive members larger than this are not read into memory for restoration.
MAX_RESTORE_MEMBER_BYTES = 256 * 1024 * 1024
_DEPOSIT_PATTERN = re.compile(r"zenodo|10\.5281/", re.IGNORECASE)
_AVAILABILITY_HEADING = re.compile(
    r"\\(?:section|subsection|paragraph)\*?\s*\{[^{}]*availab[^{}]*\}", re.IGNORECASE)
_NEXT_HEADING = re.compile(r"\\(?:section|subsection|paragraph|bibliography|end\{document\})",
                           re.IGNORECASE)


class AdoptError(RuntimeError):
    """The paper cannot be adopted or its support waived as asked."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_relative(value: Any) -> PurePosixPath | None:
    text = str(value or "").strip()
    if not text:
        return None
    relative = PurePosixPath(text)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return relative


def _files_under(base: Path) -> Iterable[Path]:
    if base.is_symlink():
        raise AdoptError(f"refusing to adopt a symbolic link: {base}")
    if base.is_file():
        yield base
        return
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise AdoptError(f"refusing to adopt a symbolic link: {path}")
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def _plan_copies(paper_id: str, metadata: Mapping[str, Any], source: Path,
                 root: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    """``(source file, target file)`` pairs; refuses a target that differs."""

    pairs: list[tuple[Path, Path]] = []
    skipped: list[str] = []
    trees = [f"papers/{paper_id}", f"reviews/unified/{paper_id}",
             f"reviews/formal-check/{paper_id}"]
    for tree in trees:
        for path in _files_under(source / tree):
            pairs.append((path, root / path.relative_to(source)))
    publication = ((metadata.get("support") or {}).get("publication") or {})
    sources = publication.get("source_files") if isinstance(publication, Mapping) else None
    for raw in sources if isinstance(sources, list) else []:
        relative = _safe_relative(raw)
        path = source / relative if relative is not None else None
        if path is None or path.is_symlink() or not path.is_file():
            skipped.append(str(raw))
            continue
        pairs.append((path, root / "papers" / paper_id / SUPPORT_COPY_DIR / relative))
    conflicts = [str(target.relative_to(root)) for origin, target in pairs
                 if target.exists() and (not target.is_file()
                                         or target.read_bytes() != origin.read_bytes())]
    if conflicts:
        raise AdoptError("the data repository already holds different files for this paper: "
                         + ", ".join(conflicts[:10]))
    return pairs, skipped


def _manifest_files(manifests: Iterable[str | Path]) -> list[Path]:
    """Local artifact files listed by archived result-bundle manifests (hash-checked)."""

    files: list[Path] = []
    for raw in manifests:
        manifest = Path(raw)
        if manifest.name != "manifest.json":
            manifest = manifest.with_name("manifest.json")
        if not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for item in data.get("artifacts") or []:
            if not isinstance(item, Mapping):
                continue
            uri = str(item.get("uri") or "")
            parsed = urlparse(uri)
            path = Path(unquote(parsed.path)) if parsed.scheme == "file" else manifest.parent / uri
            if not path.is_file() or path.is_symlink():
                continue
            if item.get("sha256") and _sha256(path.read_bytes()) != item["sha256"]:
                continue  # a changed archive object is never used
            files.append(path)
    return files


def _archived_members(files: Iterable[Path]) -> dict[str, bytes]:
    """SHA-256 -> bytes of every regular file inside the archived tar artifacts."""

    members: dict[str, bytes] = {}
    for path in files:
        if not tarfile.is_tarfile(path):
            continue
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if not member.isreg() or member.size > MAX_RESTORE_MEMBER_BYTES:
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                data = handle.read()
                members.setdefault(_sha256(data), data)
    return members


def _required_evidence(metadata: Mapping[str, Any], root: Path) -> list[tuple[str, str]]:
    """``(root-relative path, sha256)`` of every evidence file the formal check binds."""

    release = metadata.get("writing_release") or {}
    binding = release.get("formal_check") if isinstance(release, Mapping) else None
    if not isinstance(binding, Mapping) or not binding.get("path"):
        return []
    report_path = root / str(binding["path"])
    if not report_path.is_file():
        return []
    report = json.loads(report_path.read_text(encoding="utf-8"))
    required: list[tuple[str, str]] = []
    for source in report.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        for field in ("body", "text"):
            if source.get(f"{field}_path") and source.get(f"{field}_sha256"):
                required.append((str(source[f"{field}_path"]), str(source[f"{field}_sha256"])))
        retrieval = source.get("retrieval")
        if (isinstance(retrieval, Mapping) and retrieval.get("bridge_file")
                and retrieval.get("bridge_file_sha256")):
            required.append((str(retrieval["bridge_file"]), str(retrieval["bridge_file_sha256"])))
    return required


def _restore_evidence(metadata: Mapping[str, Any], root: Path,
                      members: Mapping[str, bytes]) -> tuple[list[str], list[str]]:
    restored, missing = [], []
    for raw, expected in _required_evidence(metadata, root):
        relative = _safe_relative(raw)
        if relative is None:
            continue
        target = root / relative
        if target.is_file():
            continue
        data = members.get(expected)
        if data is None:
            missing.append(raw)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored.append(raw)
    return restored, missing


def _restore_pdf(paper_id: str, metadata: Mapping[str, Any], root: Path,
                 files: Iterable[Path]) -> str | None:
    """Place the archived PDF that reproduces the reviewed manuscript snapshot."""

    from paper_writing.handoff import manuscript_snapshot_sha256

    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    pdf = root / str(metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf")
    release = metadata.get("writing_release") or {}
    decision = root / str((release or {}).get("decision_record") or "")
    if pdf.exists() or not manuscript.is_dir() or not decision.is_file():
        return None
    record = json.loads(decision.read_text(encoding="utf-8"))
    expected = ((record.get("fingerprints") or {}).get("manuscript_snapshot_sha256"))
    if not expected:
        return None
    for candidate in files:
        if candidate.suffix.lower() != ".pdf":
            continue
        shutil.copyfile(candidate, pdf)
        if manuscript_snapshot_sha256(manuscript, pdf) == expected:
            return str(pdf.relative_to(root))
        pdf.unlink()
    return None


def _layout_problems(paper_id: str, metadata: Mapping[str, Any]) -> list[str]:
    """Registry paths that do not live in the canonical ``papers/<id>/`` layout."""

    canonical = f"papers/{paper_id}"
    problems = []
    workspace = str(metadata.get("workspace") or "").strip().strip("/")
    if workspace and workspace != canonical:
        problems.append(f"workspace is {workspace!r}, not {canonical!r}")
    for key in ("manuscript_dir", "latest_pdf", "latest_source", "latest_supplementary_pdf"):
        value = str(metadata.get(key) or "").strip()
        if value and not value.startswith(f"{canonical}/"):
            problems.append(f"{key} is {value!r}, outside {canonical}/")
    return problems


def adopt(paper_id: str, *, root: str | Path, source: str | Path,
          artifact_manifests: Iterable[str | Path] = ()) -> dict[str, Any]:
    """Copy a workspace paper into the data repository (idempotent; never overwrites)."""

    repo_root, workspace = Path(root).resolve(), Path(source).resolve()
    if workspace == repo_root:
        raise AdoptError("the source workspace is the data repository itself")
    source_registry = paper_metadata_path(paper_id, workspace)
    target_registry = paper_metadata_path(paper_id, repo_root)
    if not source_registry.is_file():
        raise AdoptError(f"the workspace has no registry record for {paper_id}")
    if target_registry.exists() and target_registry.read_bytes() != source_registry.read_bytes():
        raise AdoptError(f"the data repository already registers {paper_id} with other content")
    metadata = load_paper_metadata(paper_id, workspace)
    layout = _layout_problems(paper_id, metadata)
    if layout:
        # The paper is laid out relative to the workspace root (e.g. ``workspace: .``,
        # ``manuscript_dir: manuscript``): its registry paths would not resolve in the data
        # repository, and rewriting them would change the reviewed registry. Copy nothing.
        return {"schema_version": ADOPT_SCHEMA, "status": "blocked",
                "reason": "layout_unsupported", "paper_id": paper_id,
                "source": str(workspace), "detail": "; ".join(layout)[:800]}
    pairs, skipped = _plan_copies(paper_id, metadata, workspace, repo_root)
    pairs.insert(0, (source_registry, target_registry))
    copied = []
    for origin, target in pairs:
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
        copied.append(str(target.relative_to(repo_root)))
    files = _manifest_files(artifact_manifests)
    restored, missing = _restore_evidence(metadata, repo_root, _archived_members(files))
    pdf = _restore_pdf(paper_id, metadata, repo_root, files)
    return {"schema_version": ADOPT_SCHEMA, "status": "adopted", "paper_id": paper_id,
            "source": str(workspace), "copied": len(copied),
            "support_sources_copied_to": f"papers/{paper_id}/{SUPPORT_COPY_DIR}",
            "support_sources_missing": skipped, "evidence_restored": len(restored),
            "evidence_missing": missing, "pdf_restored": pdf}


def _availability_text(metadata: Mapping[str, Any], root: Path, paper_id: str) -> str:
    from paper_writing.review_flow import expand_tex

    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    main = manuscript / "main.tex"
    if not main.is_file():
        return ""
    text = expand_tex(main, manuscript)
    sections = []
    for heading in _AVAILABILITY_HEADING.finditer(text):
        end = _NEXT_HEADING.search(text, heading.end())
        sections.append(text[heading.start():end.start() if end else len(text)])
    return "\n".join(sections)


def waive_support(paper_id: str, *, root: str | Path, reason: str,
                  decided_by: str) -> dict[str, Any]:
    """Record ``support.publication.mode: not_required`` (no public deposit) with its reason."""

    repo_root = Path(root).resolve()
    reason = str(reason or "").strip()
    if not reason:
        raise AdoptError("a support waiver needs its reason")
    metadata = load_paper_metadata(paper_id, repo_root)
    support = dict(metadata.get("support") or {})
    publication = dict(support.get("publication") or {})
    result = {"schema_version": WAIVE_SCHEMA, "paper_id": paper_id}
    if str(publication.get("mode") or "") == "not_required":
        return {**result, "status": "unchanged", "mode": "not_required"}
    status = str(publication.get("status") or "planned")
    if status != "planned" or publication.get("version_doi") or publication.get("zenodo"):
        return {**result, "status": "blocked", "reason": "support_record_exists",
                "detail": f"support publication status is {status!r} with a registered record; "
                          "waiving it needs the owner"}
    availability = _availability_text(metadata, repo_root, paper_id)
    if _DEPOSIT_PATTERN.search(availability):
        return {**result, "status": "blocked", "reason": "manuscript_cites_deposit",
                "detail": "the data-availability section names a Zenodo deposit"}
    publication.update({"mode": "not_required", "not_required_reason": reason,
                        "not_required_recorded_by": decided_by,
                        "not_required_recorded_at": _now()})
    support["publication"] = publication
    write_paper_metadata(paper_id, {**metadata, "support": support}, repo_root)
    return {**result, "status": "waived", "mode": "not_required", "reason": reason}


RELEASE_BIND_SCHEMA = "openlabs.release_artifact_binding.v1"


def bind_release_artifacts(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Freeze the ignored release PDF/.bbl through ``papers/<id>/production/release-artifacts.json``.

    Copies the bytes to the content-addressed ``openlabs-artifacts/paper-support`` store
    (``support.write_support_artifact_manifest``) and records
    ``submission_package.artifact_manifest`` in the registry. The manifest and the
    registry still have to be committed before ``handoff release`` accepts them.
    """

    from paper_writing.release_pipeline import unbound_release_artifacts
    from paper_writing.support import write_support_artifact_manifest

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    result = {"schema_version": RELEASE_BIND_SCHEMA, "paper_id": paper_id}
    files = unbound_release_artifacts(paper_id, metadata, repo_root)
    if not files:
        return {**result, "status": "not_needed", "files": []}
    relative = f"papers/{paper_id}/production/release-artifacts.json"
    from paper_writing.support import SupportPackageError

    try:
        manifest = write_support_artifact_manifest(repo_root, files, relative)
    except SupportPackageError as exc:
        raise AdoptError(f"release artifacts could not be bound: {exc}") from exc
    package = dict(metadata.get("submission_package") or {})
    package["artifact_manifest"] = {"path": relative,
                                    "sha256": _sha256(manifest.read_bytes())}
    write_paper_metadata(paper_id, {**metadata, "submission_package": package}, repo_root)
    return {**result, "status": "bound", "files": files, "manifest": relative}
