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
import subprocess
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
                 root: Path, *, relocated: list[str] | None = None,
                 ) -> tuple[list[tuple[Path, Path]], list[str]]:
    """``(source file, target file)`` pairs; refuses a target that differs.

    ``relocated``: top-level workspace entries moved under ``papers/<id>/``.
    """

    pairs: list[tuple[Path, Path]] = []
    skipped: list[str] = []
    # The editor-facing rewrite record is a unified-review preflight requirement for the
    # target; without it a later delta review stops in preflight.
    trees = [f"papers/{paper_id}", f"reviews/unified/{paper_id}",
             f"reviews/formal-check/{paper_id}", f"reviews/editorial-rewrite/{paper_id}"]
    for tree in trees:
        for path in _files_under(source / tree):
            pairs.append((path, root / path.relative_to(source)))
    for segment in relocated or []:
        for path in _files_under(source / segment):
            pairs.append((path, root / "papers" / paper_id / path.relative_to(source)))
    publication = ((metadata.get("support") or {}).get("publication") or {})
    sources = publication.get("source_files") if isinstance(publication, Mapping) else None
    for raw in sources if isinstance(sources, list) else []:
        if str(raw).startswith(f"papers/{paper_id}/"):
            continue  # inside the paper tree, copied above
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


class _ArchiveIndex:
    """Regular files inside archived tar artifacts, by SHA-256 and by archive.

    Only hashes and locations are kept; bytes are read again when a file is restored.
    """

    def __init__(self, files: Iterable[Path]):
        self.by_sha: dict[str, tuple[Path, str]] = {}
        self.archives: list[tuple[Path, list[tuple[str, str]]]] = []
        for path in files:
            if not tarfile.is_tarfile(path):
                continue
            entries: list[tuple[str, str]] = []
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    if not member.isreg() or member.size > MAX_RESTORE_MEMBER_BYTES:
                        continue
                    handle = archive.extractfile(member)
                    if handle is None:
                        continue
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                    sha = digest.hexdigest()
                    self.by_sha.setdefault(sha, (path, member.name))
                    entries.append((member.name, sha))
            self.archives.append((path, entries))

    def read(self, sha: str) -> bytes | None:
        location = self.by_sha.get(sha)
        if location is None:
            return None
        with tarfile.open(location[0]) as archive:
            handle = archive.extractfile(location[1])
            return handle.read() if handle is not None else None

    def get(self, sha: str) -> bytes | None:  # mapping-style access for evidence restore
        return self.read(sha)


def _archived_members(files: Iterable[Path]) -> _ArchiveIndex:
    return _ArchiveIndex(files)


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
                      members: Any) -> tuple[list[str], list[str]]:
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


def _archive_manuscript_files(entries: list[tuple[str, str]]) -> dict[str, str]:
    """``manuscript-relative name -> sha256`` for the members under a ``manuscript/`` directory."""

    found: dict[str, str] = {}
    for name, sha in entries:
        parts = PurePosixPath(name).parts
        if "manuscript" not in parts:
            continue
        index = len(parts) - 1 - parts[::-1].index("manuscript")
        relative = PurePosixPath(*parts[index + 1:]) if index + 1 < len(parts) else None
        if relative is not None and ".." not in relative.parts:
            found.setdefault(relative.as_posix(), sha)
    return found


def _restore_pdf(paper_id: str, metadata: Mapping[str, Any], root: Path,
                 files: Iterable[Path], index: _ArchiveIndex | None = None) -> str | None:
    """Restore what reproduces the reviewed manuscript snapshot; anything else is undone.

    First the archived PDFs alone. Then, for each archived review root (a tar with a
    ``manuscript/`` directory), its manuscript files that are missing here (figures,
    ``.bbl``/``.aux`` build products, never a file that exists), together with each
    archived PDF. Only a combination whose snapshot equals the decision's
    ``manuscript_snapshot_sha256`` is kept.
    """

    from paper_writing.handoff import manuscript_snapshot_sha256

    files = list(files)
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
    pdf_name = pdf.relative_to(manuscript).as_posix() if pdf.is_relative_to(manuscript) else None
    candidates = [candidate for candidate in files if candidate.suffix.lower() == ".pdf"]

    def matches_with_pdfs(extra_pdfs: list[bytes]) -> bool:
        for candidate in candidates:
            shutil.copyfile(candidate, pdf)
            if manuscript_snapshot_sha256(manuscript, pdf) == expected:
                return True
            pdf.unlink()
        for data in extra_pdfs:
            pdf.write_bytes(data)
            if manuscript_snapshot_sha256(manuscript, pdf) == expected:
                return True
            pdf.unlink()
        return False

    if matches_with_pdfs([]):
        return str(pdf.relative_to(root))
    for _, entries in (index.archives if index is not None else []):
        members = _archive_manuscript_files(entries)
        missing = {name: sha for name, sha in members.items()
                   if name != pdf_name and not (manuscript / name).exists()}
        if not missing:
            continue
        written: list[Path] = []
        for name, sha in sorted(missing.items()):
            data = index.read(sha)
            if data is None:
                continue
            target = manuscript / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(target)
        own_pdf = index.read(members[pdf_name]) if pdf_name in members else None
        if matches_with_pdfs([own_pdf] if own_pdf else []):
            return str(pdf.relative_to(root))
        for target in written:
            target.unlink()
    return None


def _layout_problems(paper_id: str, metadata: Mapping[str, Any]) -> list[str]:
    """Registry paths that do not live in the canonical ``papers/<id>/`` layout."""

    from paper_writing.registry import paper_layout_problems

    return paper_layout_problems(paper_id, metadata)


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
    metadata = load_paper_metadata(paper_id, workspace)
    relocation: dict[str, Any] | None = None
    registry_bytes = source_registry.read_bytes()
    if _layout_problems(paper_id, metadata):
        plan = _relocation_plan(paper_id, metadata, workspace)
        if plan.get("blocked"):
            # Not the one layout we can move without touching a reviewed byte: copy nothing.
            return {"schema_version": ADOPT_SCHEMA, "status": "blocked",
                    "reason": "layout_unsupported", "paper_id": paper_id,
                    "source": str(workspace), "detail": str(plan["blocked"])[:800]}
        relocation = plan
        metadata = plan["metadata"]
        registry_bytes = _registry_yaml(paper_id, metadata).encode("utf-8")
    publication = (metadata.get("support") or {}).get("publication") or {}
    from paper_writing.registry import load_registry_settings
    from paper_writing.support_policy import effective_publication_mode, publication_policy

    settings = load_registry_settings(repo_root) if (repo_root / "registry/settings.yaml").is_file() else {}
    if (effective_publication_mode(publication, publication_policy(settings)) == "zenodo_only"
            and publication.get("status", "planned") == "planned"
            and not publication.get("source_files")):
        from paper_writing.support import resolve_support_sources
        from paper_writing.support_upload_policy import validate_upload_sources

        paper = workspace / "papers" / paper_id
        dedicated = paper / SUPPORT_COPY_DIR
        if dedicated.is_dir() and not dedicated.is_symlink():
            candidates = [path for path in sorted(dedicated.iterdir())
                          if path.name != "zenodo" and not path.name.startswith(".")]
        else:
            # Owner workspaces keep the analysis outside the manuscript, including
            # private receipts and raw inputs. Only select analysis source and
            # named small result tables from these conventional locations.
            candidates = []
            for directory in (workspace / "analysis", workspace / "grid", workspace / "grid/analysis",
                              workspace / "decisive", paper / "analysis"):
                if directory.is_dir() and directory.resolve() == directory:
                    candidates.extend(sorted(directory.glob("*.py")))
                    candidates.extend(path for name in ("primary.json", "ranks.csv", "PROTOCOL.md")
                                      if (path := directory / name).is_file())
        if candidates:
            selected = resolve_support_sources(metadata, candidates, repo_root=workspace)
            validate_upload_sources(selected, repo_root=workspace)
            publication = {**publication, "source_files": [str(path.relative_to(workspace)) for path in selected]}
            metadata = {**metadata, "support": {**(metadata.get("support") or {}), "publication": publication}}
            registry_bytes = _registry_yaml(paper_id, metadata).encode("utf-8")
        elif (reason := str(metadata.get("support_none_reason") or publication.get("not_required_reason") or "").strip()):
            # A recorded paper-specific decision is required. An absent manifest
            # by itself cannot establish that the owner has no public materials.
            if not publication.get("zenodo") and not publication.get("version_doi") and not _DEPOSIT_PATTERN.search(
                    _availability_text(metadata, workspace, paper_id)):
                publication = {**publication, "mode": "not_required", "not_required_reason": reason,
                               "not_required_recorded_by": "program:adopt"}
                metadata = {**metadata, "support": {**(metadata.get("support") or {}), "publication": publication}}
                registry_bytes = _registry_yaml(paper_id, metadata).encode("utf-8")
    if target_registry.exists() and target_registry.read_bytes() != registry_bytes:
        raise AdoptError(f"the data repository already registers {paper_id} with other content")
    pairs, skipped = _plan_copies(paper_id, metadata, workspace, repo_root,
                                  relocated=relocation["segments"] if relocation else None)
    copied = []
    for origin, target in pairs:
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
        copied.append(str(target.relative_to(repo_root)))
    if relocation is not None:
        record = repo_root / relocation["record_path"]
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(relocation["record"], indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        _verify_relocated_bytes(repo_root, relocation["record"])
    if not target_registry.exists():
        target_registry.parent.mkdir(parents=True, exist_ok=True)
        target_registry.write_bytes(registry_bytes)
        copied.insert(0, str(target_registry.relative_to(repo_root)))
    files = _manifest_files(artifact_manifests)
    index = _archived_members(files)
    restored, missing = _restore_evidence(metadata, repo_root, index)
    pdf = _restore_pdf(paper_id, metadata, repo_root, files, index)
    result = {"schema_version": ADOPT_SCHEMA, "status": "adopted", "paper_id": paper_id,
              "source": str(workspace), "copied": len(copied),
              "support_sources_copied_to": f"papers/{paper_id}/{SUPPORT_COPY_DIR}",
              "support_sources_missing": skipped, "evidence_restored": len(restored),
              "evidence_missing": missing, "pdf_restored": pdf}
    if relocation is not None:
        result["relocated"] = {"record": relocation["record_path"],
                               "segments": relocation["segments"],
                               "files": len(relocation["record"]["files"]),
                               "fields": len(relocation["record"]["rewritten_fields"])}
    return result


# --------------------------------------------------------------------------- relocation
#
# An owner seat that registered its paper in a private review root may lay it out
# relative to the workspace root (``workspace: .``, ``manuscript_dir: manuscript``,
# ``evidence/...``). Adoption then moves exactly the top-level workspace entries the
# registry refers to under ``papers/<id>/`` and rewrites only those path values. Every
# moved file is listed with its SHA-256 in ``papers/<id>/production/workspace-relocation.json``
# and checked after the copy; manuscript bytes are unchanged, so the ready decision's
# manuscript snapshot (paths relative to the manuscript directory) still matches.

RELOCATION_SCHEMA = "openlabs.paper_relocation.v1"
# Workspace entries that are already repository-shaped and never relocated.
_SHARED_TOPS = frozenset({"registry", "reviews", "papers"})


def _registry_yaml(paper_id: str, metadata: Mapping[str, Any]) -> str:
    import yaml

    return yaml.safe_dump({**dict(metadata), "paper_id": paper_id}, allow_unicode=True,
                          sort_keys=False, width=1000)


def _path_like(value: str) -> PurePosixPath | None:
    if not value or len(value) > 400 or any(c.isspace() for c in value) or "://" in value:
        return None
    if value.startswith(("/", "doi:", "10.")):
        return None
    return _safe_relative(value)


def _relocation_plan(paper_id: str, metadata: Mapping[str, Any], workspace: Path) -> dict[str, Any]:
    canonical = f"papers/{paper_id}"
    if str(metadata.get("workspace") or "").strip().strip("/") not in {"", "."}:
        return {"blocked": f"workspace is {metadata.get('workspace')!r}; only '.' can be relocated"}
    rewritten: list[dict[str, str]] = []
    segments: set[str] = set()

    def walk(value: Any, pointer: str) -> Any:
        if isinstance(value, Mapping):
            return {key: walk(item, f"{pointer}/{key}") for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, f"{pointer}/{index}") for index, item in enumerate(value)]
        if isinstance(value, str) and pointer != "/workspace":
            relative = _path_like(value)
            # A bare word (``photometry``) is a path only in a ``*_dir`` field.
            if (relative is not None and relative.parts[0] not in _SHARED_TOPS
                    and (len(relative.parts) > 1 or pointer.endswith("_dir"))
                    and (workspace / relative).exists()):
                segments.add(relative.parts[0])
                new = f"{canonical}/{relative.as_posix()}"
                rewritten.append({"field": pointer, "from": value, "to": new})
                return new
        return value

    relocated = walk(dict(metadata), "")
    manuscript = str(metadata.get("manuscript_dir") or "")
    if not manuscript or PurePosixPath(manuscript).parts[0] not in segments:
        return {"blocked": f"manuscript_dir {manuscript!r} does not name a workspace directory"}
    for key in ("manuscript_dir", "latest_pdf", "latest_source", "latest_supplementary_pdf"):
        value = str(relocated.get(key) or "")
        if value and not value.startswith(f"{canonical}/"):
            relocated[key] = f"{canonical}/{value}"  # a not-yet-built PDF/supplement
            rewritten.append({"field": f"/{key}", "from": value, "to": relocated[key]})
    relocated["workspace"] = canonical
    rewritten.append({"field": "/workspace", "from": str(metadata.get("workspace") or ""),
                      "to": canonical})
    files = []
    for segment in sorted(segments):
        for path in _files_under(workspace / segment):
            relative = path.relative_to(workspace).as_posix()
            target = f"{canonical}/{relative}"
            if (workspace / target).exists():
                return {"blocked": f"{target} already exists in the workspace"}
            files.append({"from": relative, "to": target, "sha256": _sha256(path.read_bytes()),
                          "size": path.stat().st_size})
    record_path = f"{canonical}/production/workspace-relocation.json"
    relocated["relocation"] = {"record": record_path, "from_workspace": ".",
                               "segments": sorted(segments)}
    record = {"schema_version": RELOCATION_SCHEMA, "paper_id": paper_id,
              "source_workspace": str(workspace), "from_workspace": ".",
              "to_workspace": canonical,
              "segments": {segment: f"{canonical}/{segment}" for segment in sorted(segments)},
              "rewritten_fields": rewritten, "files": files,
              "note": "Only locations changed: every listed file is copied byte for byte."}
    return {"metadata": relocated, "segments": sorted(segments), "record": record,
            "record_path": record_path}


def _verify_relocated_bytes(root: Path, record: Mapping[str, Any]) -> None:
    for item in record["files"]:
        target = root / item["to"]
        if not target.is_file() or _sha256(target.read_bytes()) != item["sha256"]:
            raise AdoptError(f"relocated file differs from its source bytes: {item['to']}")


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

    from paper_writing.release_pipeline import release_artifact_candidates, unbound_release_artifacts
    from paper_writing.support import write_support_artifact_manifest

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    result = {"schema_version": RELEASE_BIND_SCHEMA, "paper_id": paper_id}
    if not unbound_release_artifacts(paper_id, metadata, repo_root):
        return {**result, "status": "not_needed", "files": []}
    # A stale manifest (a new build after an earlier delivery) is rewritten for every
    # current candidate, not only the changed ones, so no old binding survives.
    files = release_artifact_candidates(paper_id, metadata, repo_root)
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


SUPPORT_RELOCATE_SCHEMA = "openlabs.support_source_relocation.v1"


def unadopted_support_sources(paper_id: str, metadata: Mapping[str, Any],
                              root: Path) -> list[tuple[str, str]]:
    """``(registered, copy)`` for support sources that only exist as adopt's copy.

    ``program adopt`` copies a support source registered outside the paper tree
    (``decisive/solve.py``, relative to the campaign workspace) to
    ``papers/<id>/support-materials/<path>``; the registry still names the workspace
    path, which does not exist in the data repository (2026-11-20: PMB-13B's
    ``zenodo prepare`` stopped on ``decisive/dispatch-stability.json``).
    """

    publication = ((metadata.get("support") or {}).get("publication") or {})
    sources = publication.get("source_files") if isinstance(publication, Mapping) else None
    found = []
    for raw in sources if isinstance(sources, list) else []:
        text = str(raw)
        relative = _safe_relative(text)
        if relative is None or text.startswith(f"papers/{paper_id}/"):
            continue
        if (root / relative).exists():
            continue
        copy = PurePosixPath("papers") / paper_id / SUPPORT_COPY_DIR / relative
        target = root / copy
        if target.is_file() and not target.is_symlink():
            found.append((text, copy.as_posix()))
    return found


def relocate_support_sources(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Point ``support.publication.source_files`` at the copies ``program adopt`` made.

    Each rewritten entry is recorded in ``support.publication.adopted_sources``
    (current path -> registered path), which ``support_sources_snapshot_sha256`` uses as
    the logical name: the same bytes under their reviewed names give the same digest,
    so the ready decision stays bound. Reports whether the digest equals the one the
    ready decision recorded. Writes only the registry record.
    """

    from paper_writing.support import SupportPackageError, support_sources_snapshot_sha256

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    result = {"schema_version": SUPPORT_RELOCATE_SCHEMA, "paper_id": paper_id}
    moves = unadopted_support_sources(paper_id, metadata, repo_root)
    if not moves:
        return {**result, "status": "not_needed", "relocated": []}
    support = dict(metadata.get("support") or {})
    publication = dict(support.get("publication") or {})
    mapping = dict(moves)
    publication["source_files"] = [mapping.get(str(item), item)
                                   for item in publication.get("source_files") or []]
    aliases = dict(publication.get("adopted_sources") or {})
    aliases.update({copy: registered for registered, copy in moves})
    publication["adopted_sources"] = aliases
    support["publication"] = publication
    updated = {**metadata, "support": support}
    try:
        digest = support_sources_snapshot_sha256(updated, repo_root=repo_root)
    except (SupportPackageError, OSError, ValueError) as exc:
        raise AdoptError(f"relocated support sources do not resolve: {exc}") from exc
    write_paper_metadata(paper_id, updated, repo_root)
    release = metadata.get("writing_release") or {}
    reviewed = (release.get("support_sources_sha256")
                if isinstance(release, Mapping) else None)
    return {**result, "status": "relocated",
            "relocated": [{"from": registered, "to": copy} for registered, copy in moves],
            "support_sources_sha256": digest, "reviewed_support_sources_sha256": reviewed,
            "matches_review": (digest == reviewed) if reviewed else None}


PAYLOAD_BIND_SCHEMA = "openlabs.oversize_payload_binding.v1"
_IGNORE_HEADER = ("# Over the Git payload limit: bound by path, size and SHA-256 in "
                  "papers/{paper_id}/production/payload-artifacts.json (openlabs-artifacts).")


def _ignore_next_to(root: Path, relative: str, paper_id: str) -> str:
    """Add an anchored entry for ``relative`` to the .gitignore in its own directory."""

    path = root / relative
    ignore = path.parent / ".gitignore"
    entry = "/" + path.name.replace("\\", "\\\\").replace("*", "\\*").replace(
        "?", "\\?").replace("[", "\\[")
    lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.is_file() else []
    if entry not in lines:
        if not lines:
            lines.append(_IGNORE_HEADER.format(paper_id=paper_id))
        lines.append(entry)
        ignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ignore.relative_to(root).as_posix()


def bind_oversize_payloads(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Keep a paper's over-limit files out of Git; bind them to the artifact store instead.

    The data repository refuses blobs over 5 MiB (pre-commit hook). Each file
    ``release_pipeline.oversize_payloads`` lists (a formal-check evidence body, a large
    record) is copied to the content-addressed ``openlabs-artifacts/paper-support/
    sha256/<SHA-256>/<name>`` store and recorded with its path, size, SHA-256 and
    artifact URI in ``papers/<id>/production/payload-artifacts.json``; an anchored
    entry in the .gitignore of its own directory keeps the local copy out of Git, and
    an index entry an earlier refused commit left staged is dropped. The bytes on disk
    are not touched, so every check that reads them (formal-check evidence hashes,
    adopt) sees exactly what was reviewed. The manifest and the .gitignore files are
    committed by the next release commit; nothing here commits.
    """

    from paper_writing.release_pipeline import (PAYLOAD_MANIFEST_TEMPLATE, _bound_payloads,
                                                commit_paths, oversize_payloads)
    from paper_writing.support import SupportPackageError, write_support_artifact_manifest

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    result = {"schema_version": PAYLOAD_BIND_SCHEMA, "paper_id": paper_id}
    files = oversize_payloads(paper_id, commit_paths(paper_id, metadata, repo_root), repo_root)
    if not files:
        return {**result, "status": "not_needed", "files": []}
    for name in files:
        relative = _safe_relative(name)
        if relative is None or (repo_root / relative).is_symlink():
            raise AdoptError(f"refusing to bind an unsafe payload path: {name}")
    # Earlier bindings that still exist stay in the manifest (rewritten as a whole).
    keep = [name for name in _bound_payloads(paper_id, repo_root)
            if name not in files and (repo_root / name).is_file()]
    manifest_name = PAYLOAD_MANIFEST_TEMPLATE.format(paper_id=paper_id)
    try:
        manifest = write_support_artifact_manifest(repo_root, sorted({*keep, *files}),
                                                   manifest_name)
    except SupportPackageError as exc:
        raise AdoptError(f"oversize payloads could not be bound: {exc}") from exc
    ignores = sorted({_ignore_next_to(repo_root, name, paper_id) for name in files})
    unstaged = []
    for name in files:
        staged = subprocess.run(["git", "ls-files", "--cached", "--", name], cwd=repo_root,
                                capture_output=True, text=True, check=False)
        if staged.stdout.strip():
            dropped = subprocess.run(["git", "update-index", "--force-remove", "--", name],
                                     cwd=repo_root, capture_output=True, text=True, check=False)
            if dropped.returncode != 0:
                raise AdoptError(f"could not unstage {name}: {dropped.stderr.strip()[-300:]}")
            unstaged.append(name)
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", name], cwd=repo_root,
                                 capture_output=True, check=False)
        if ignored.returncode != 0:
            raise AdoptError(f"{name} is still not ignored by Git after binding")
    content = json.loads(manifest.read_text(encoding="utf-8"))
    entries = {item["path"]: item for item in content.get("files") or []}
    return {**result, "status": "bound", "manifest": manifest_name,
            "manifest_sha256": _sha256(manifest.read_bytes()),
            "files": [{key: entries[name][key] for key in ("path", "size", "sha256",
                                                           "artifact_uri")}
                      for name in files],
            "gitignore": ignores, "unstaged": unstaged}


UNWAIVE_SCHEMA = "openlabs.support_unwaiver.v1"


def unwaive_support(paper_id: str, *, root: str | Path, reason: str, by: str,
                    mode: str | None = None) -> dict[str, Any]:
    """Undo a ``not_required`` support waiver: the paper goes back to a public deposit.

    ``mode`` defaults to ``registry/settings.yaml#support_publication.default_mode``.
    The waiver (reason, who, when) and this reversal are kept in
    ``support.publication.waiver_history``; the support status is left as it is
    (a waived paper is still ``planned``), so ``zenodo prepare`` runs next.
    """

    from paper_writing.registry import load_registry_settings
    from paper_writing.support_policy import SUPPORT_PUBLICATION_MODES, publication_policy

    repo_root = Path(root).resolve()
    reason, by = str(reason or "").strip(), str(by or "").strip()
    if not reason or not by:
        raise AdoptError("undoing a support waiver needs --reason and --by")
    metadata = load_paper_metadata(paper_id, repo_root)
    support = dict(metadata.get("support") or {})
    publication = dict(support.get("publication") or {})
    result = {"schema_version": UNWAIVE_SCHEMA, "paper_id": paper_id}
    if str(publication.get("mode") or "") != "not_required":
        return {**result, "status": "unchanged", "mode": publication.get("mode")}
    target = str(mode or publication_policy(load_registry_settings(repo_root)).get("default_mode")
                 or "").strip()
    if target not in SUPPORT_PUBLICATION_MODES - {"not_required"}:
        raise AdoptError(f"cannot restore support mode {target!r}")
    entry = {"waived_reason": publication.pop("not_required_reason", None),
             "waived_by": publication.pop("not_required_recorded_by", None),
             "waived_at": publication.pop("not_required_recorded_at", None),
             "reverted_by": by, "reverted_at": _now(), "reason": reason, "restored_mode": target}
    publication["mode"] = target
    publication["waiver_history"] = [*list(publication.get("waiver_history") or []), entry]
    support["publication"] = publication
    write_paper_metadata(paper_id, {**metadata, "support": support}, repo_root)
    return {**result, "status": "restored", "mode": target}


def adopt_revision(paper_id, *, root, source, previous_package, artifact_manifests=()):
    """Stage and verify a successor, then promote its registry last for restartability."""
    from tempfile import TemporaryDirectory
    from paper_writing.handoff import manuscript_snapshot_sha256
    from paper_writing.review_flow import validate_unified_release

    data = Path(root).resolve()
    baseline = load_paper_metadata(paper_id, data)
    candidate = load_paper_metadata(paper_id, source)
    delivery = baseline.get("delivery") or {}
    if (delivery.get("package_id") != previous_package or delivery.get("submission_handler")
            or candidate.get("delivery") != delivery or not delivery.get("version")):
        raise AdoptError("revision does not descend from the expected delivery")
    release = candidate.get("writing_release") or {}
    version = candidate.get("version")
    if (version == delivery["version"] or not version or release.get("status") != "ready"
            or release.get("manuscript_version") != version):
        raise AdoptError("expected a ready unified review of a successor version")
    old_support = (baseline.get("support") or {}).get("publication") or {}
    new_support = (candidate.get("support") or {}).get("publication") or {}
    if old_support.get("zenodo") != new_support.get("zenodo"):
        raise AdoptError("revision changed the published Zenodo identity")
    registry = paper_metadata_path(paper_id, data)
    if baseline.get("version") != delivery["version"]:
        if (baseline.get("version") == version
                and baseline.get("writing_release", {}).get("decision_record_sha256")
                == release.get("decision_record_sha256")):
            return {"status": "adopted", "copied": 0}
        raise AdoptError("canonical paper already has another successor")
    with TemporaryDirectory(prefix="openlabs-revision-") as directory:
        stage = Path(directory)
        result = adopt(paper_id, root=stage, source=source, artifact_manifests=artifact_manifests)
        if result["status"] != "adopted":
            return result
        for name in ("settings.yaml", "verified-venues.yaml", "journal-rejections.json"):
            if (data / "registry" / name).is_file():
                shutil.copy2(data / "registry" / name, stage / "registry" / name)
        manuscript = stage / str(candidate["manuscript_dir"])
        pdf = stage / str(candidate.get("latest_pdf") or (Path(candidate["manuscript_dir"]) / "main.pdf"))
        if not manuscript.resolve().is_relative_to(stage) or not pdf.resolve().is_relative_to(manuscript):
            raise AdoptError("revision manuscript paths escape the staged paper")
        problems = validate_unified_release(paper_id, candidate, stage,
                                           manuscript_snapshot_sha256(manuscript, pdf))
        if problems:
            raise AdoptError("successor review is not current: " + "; ".join(problems))
        # The final manuscript must have exactly the reviewed inputs. Stale source
        # files left by an older version would change the snapshot after promotion.
        live_manuscript = data / manuscript.relative_to(stage)
        from paper_writing.handoff import _source_files
        if live_manuscript.is_dir():
            extras = [p for p in _source_files(live_manuscript, data / pdf.relative_to(stage))
                      if not (manuscript / p.relative_to(live_manuscript)).is_file()]
            if extras:
                raise AdoptError("reviewed successor omits previous manuscript inputs: "
                                 + ", ".join(p.name for p in extras[:8]))
        copies = []
        for tree in (stage / "papers", stage / "reviews"):
            for path in _files_under(tree):
                relative = path.relative_to(stage)
                target = data / relative
                if target.resolve() != target:
                    raise AdoptError(f"revision target is a symlink: {relative}")
                if target.is_file() and target.read_bytes() == path.read_bytes():
                    continue
                if relative.is_relative_to(Path("papers") / paper_id / "releases"):
                    raise AdoptError("revision cannot change delivery receipts")
                if target.exists() and relative.parts[:2] == ("reviews", "unified"):
                    raise AdoptError("revision cannot overwrite an earlier unified review")
                copies.append((path, target))
        # Keep the committed baseline available. Stop on a concurrent local edit.
        for path, target in copies:
            if target.exists():
                clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--",
                                        str(target.relative_to(data))], cwd=data)
                if clean.returncode:
                    raise AdoptError(f"uncommitted canonical change at {target.relative_to(data)}")
        for path, target in copies:
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_name("." + target.name + ".revision-pending")
            shutil.copy2(path, pending)
            pending.replace(target)
        staged_registry = paper_metadata_path(paper_id, stage)
        pending = registry.with_suffix(".revision-pending")
        shutil.copy2(staged_registry, pending)
        pending.replace(registry)
        return {**result, "copied": len(copies) + 1}
