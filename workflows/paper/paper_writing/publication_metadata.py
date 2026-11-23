"""Project the registered Zenodo identity onto an already reviewed release."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from paper_writing.handoff import (
    _source_files, manuscript_review_content_sha256, manuscript_snapshot_sha256,
)
from paper_writing.operations import _registry_review_content_sha256
from paper_writing.registry import load_paper_metadata, write_paper_metadata
from paper_writing.support import (
    _record_version, support_sources_digest, support_sources_logical_paths,
    support_sources_snapshot_sha256,
)
from paper_writing.support_citations import AVAILABILITY_HEADING, SUPPORT_MENTION, _expand_tex

CODES = frozenset({
    "SUPPORT-BIB-DOI", "SUPPORT-ARCHIVE-DOI", "SUPPORT-ARCHIVE-VERSION-MISSING",
    "SUPPORT-CITATION-MISSING", "SUPPORT-FIRST-CITATION", "SUPPORT-AVAILABILITY-CITATION",
})
KEY = "openlabsSupportArchive"


def _identity(publication):
    zenodo = publication["zenodo"]
    doi = zenodo.get("reserved_version_doi") or zenodo["version_doi"]
    version = zenodo["version"]
    author = " and ".join(item["name"] for item in zenodo["creators"])
    title = zenodo["title"]
    year = str(zenodo["publication_date"])[:4]
    if (not re.fullmatch(r"10\.5281/zenodo\.\d+", doi)
            or not re.fullmatch(r"v?\d+\.\d+\.\d+", version)
            or not re.fullmatch(r"\d{4}", year)
            or any(not value or re.search(r"[{}\\%\x00-\x1f]", value) for value in (author, title))):
        raise ValueError("The Zenodo identity cannot be represented safely")
    return doi, version, author, title, year


def _edits(manuscript, publication):
    doi, version, author, title, year = _identity(publication)
    main = manuscript / "main.tex"
    bib = manuscript / "references.bib"
    original = bib.read_bytes()
    if re.search(rb"\{\s*openlabsSupportArchive\s*,", original, re.I) or doi.encode() in original:
        raise ValueError("The support DOI or reserved citation key already occurs in the bibliography")
    entry = (f"\n@misc{{{KEY},\n  author = {{{author}}},\n  title = {{{{{title}}}}},\n"
             f"  year = {{{year}}},\n  publisher = {{Zenodo}},\n  version = {{{version}}},\n"
             f"  doi = {{{doi}}},\n}}\n")
    edits = {bib: original + entry.encode()}
    paragraphs = _expand_tex(main, manuscript)
    headings = [item for item in paragraphs if AVAILABILITY_HEADING.search(item.text)]
    if not headings:
        raise ValueError("No TeX availability section")
    first = next((item for item in paragraphs if SUPPORT_MENTION.search(item.text)), None)
    inserts = {}
    for paragraph in [*headings, first]:
        if paragraph is None:
            continue
        lines = paragraph.path.read_text().splitlines(keepends=True)
        if paragraph in headings:
            start = next(i for i in range(paragraph.line - 1, len(lines))
                         if AVAILABILITY_HEADING.search(lines[i])) + 1
        else:
            start = paragraph.line - 1
        end = start
        while end < len(lines) and lines[end].strip() and not re.match(
            r"\s*\\(?:end|section|subsection|subsubsection|appendix|bibliography|input|include)\b",
            lines[end],
        ):
            end += 1
        inserts.setdefault(paragraph.path, set()).add(end)
    sentence = f"The supporting materials are described in the Zenodo record~\\cite{{{KEY}}}.\n"
    for path, offsets in inserts.items():
        lines = path.read_text().splitlines(keepends=True)
        for offset in sorted(offsets, reverse=True):
            if offset and not lines[offset - 1].endswith("\n"):
                lines[offset - 1] += "\n"
            lines.insert(offset, sentence)
        edits[path] = "".join(lines).encode()
    return edits


def _claim_suffix(publication):
    doi, version, *_ = _identity(publication)
    return f"\n\nSupporting materials (version {version}): https://doi.org/{doi}\n".encode()


def _paper_paths(root, metadata):
    paper_id = metadata["paper_id"]
    paper = root / "papers" / paper_id
    # The same defaults as release_status/_release_paths: a registry may omit both fields.
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    pdf = root / str(metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf")
    if (manuscript.resolve() != paper.resolve() / "manuscript"
            or pdf.resolve().parent != manuscript.resolve()):
        raise ValueError("Publication metadata requires a canonical manuscript tree")
    return paper, manuscript, pdf


def _history(root, metadata, decision):
    paper, _, _ = _paper_paths(root, metadata)
    if not re.fullmatch(r"[0-9a-f]{64}", decision):
        raise ValueError("Invalid source decision hash")
    return paper / "revisions" / "pdf-history" / decision


def _old_pdfs(manuscript, pdf, paper_id):
    pattern = re.compile(re.escape(paper_id) + r"-v\d+\.\d+\.\d+\.pdf")
    return {pdf, *(p for p in manuscript.glob("*.pdf") if pattern.fullmatch(p.name))}


def _copy_sources(manuscript, pdf, destination):
    for source in _source_files(manuscript, pdf):
        target = destination / source.relative_to(manuscript)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _archive_claim_maps(metadata, root):
    if not metadata["support"]["publication"].get("source_files"):
        return {}
    return {name: path for name, path in support_sources_logical_paths(metadata, repo_root=root).items()
            if path.name == "claim_evidence_map.md" and path.parent.name == "evidence"}


def baseline_fingerprints(root, metadata, release):
    """Reverse the exact generated edits and verify the original review fingerprints."""
    proof = release["publication_metadata"]
    _, manuscript, pdf = _paper_paths(root, metadata)
    history = _history(root, metadata, release["decision_record_sha256"])
    publication = metadata["support"]["publication"]
    if (proof["identity"] != list(_identity(publication))
            or proof["version"] != str(metadata["version"])
            or pdf != manuscript / "main.pdf"):
        raise ValueError("Publication metadata identity changed")
    original_pdf = proof["original_pdf"]
    if Path(original_pdf).name != original_pdf:
        raise ValueError("Invalid original PDF name")
    with tempfile.TemporaryDirectory(prefix="openlabs-citation-check-") as temp:
        baseline = Path(temp) / "manuscript"
        baseline.mkdir()
        _copy_sources(manuscript, pdf, baseline)
        originals = history / "sources"
        for old in originals.rglob("*"):
            if old.is_file():
                relative = old.relative_to(originals)
                if relative.suffix not in {".tex", ".bib", ".bbl"}:
                    raise ValueError("Unexpected publication history source")
                target = baseline / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old, target)
        prior_pdf = baseline / original_pdf
        for old in history.glob("*.pdf"):
            shutil.copyfile(old, baseline / old.name)
        edits = _edits(baseline, publication)
        backups = {p.relative_to(originals) for p in originals.rglob("*") if p.is_file()}
        if backups - {p.relative_to(baseline) for p in edits} - {Path("main.bbl")}:
            raise ValueError("Publication history contains an unexpected source")
        for edited, expected in edits.items():
            if (manuscript / edited.relative_to(baseline)).read_bytes() != expected:
                raise ValueError("Publication metadata differs from the deterministic edit")
        if not proof["had_bbl"]:
            (baseline / "main.bbl").unlink(missing_ok=True)
        support_sha = support_sources_snapshot_sha256(metadata, repo_root=root)
        maps = _archive_claim_maps(metadata, root)
        if maps:
            logical = support_sources_logical_paths(metadata, repo_root=root)
            suffix = _claim_suffix(publication)
            for index, (name, path) in enumerate(sorted(maps.items())):
                content = path.read_bytes()
                if not content.endswith(suffix):
                    raise ValueError("Claim map differs from the deterministic publication edit")
                backup = Path(temp) / f"claim-map-{index}"
                backup.write_bytes(content[:-len(suffix)])
                logical[name] = backup
            support_sha = support_sources_digest(logical)
        return {
            "manuscript_snapshot_sha256": manuscript_snapshot_sha256(baseline, prior_pdf),
            "review_content_sha256": manuscript_review_content_sha256(baseline, prior_pdf),
            "registry_review_content_sha256": _registry_review_content_sha256(metadata),
            "support_sources_sha256": support_sha,
        }


def _prepare(paper_id, *, root):
    from paper_writing.operations import _review_workspace_fingerprints
    from paper_writing.release_pipeline import _package_stale
    from paper_writing.review_flow import validate_unified_release

    metadata = load_paper_metadata(paper_id, root)
    release = metadata["writing_release"]
    publication = metadata["support"]["publication"]
    if release.get("status") != "ready" or publication.get("status") != "draft":
        raise ValueError("Publication metadata requires a ready manuscript and a Zenodo draft")
    if str(release.get("manuscript_version")) != str(metadata.get("version")):
        raise ValueError("The ready decision is for a different manuscript version")
    if publication["zenodo"]["version"] != _record_version(metadata):
        raise ValueError("The Zenodo draft is for a different support version")
    _, manuscript, pdf = _paper_paths(root, metadata)
    snapshot = manuscript_snapshot_sha256(manuscript, pdf)
    problems = validate_unified_release(paper_id, metadata, root, snapshot)
    if problems:
        raise ValueError(problems[0])
    if release.get("publication_metadata"):
        if _package_stale(metadata, root):
            raise ValueError("Rebuild the package before binding it to the ready release")
        release["support_package_sha256"] = publication["package_sha256"]
        write_paper_metadata(paper_id, metadata, root)
        return {"status": "bound"}

    fingerprints = _review_workspace_fingerprints(paper_id, metadata, root)
    if any(release.get(key) != value for key, value in fingerprints.items()):
        raise ValueError("Current inputs differ from the ready decision")
    history = _history(root, metadata, release["decision_record_sha256"])
    if history.exists():
        raise ValueError(f"Publication history already exists: {history}")
    edits = _edits(manuscript, publication)
    maps = _archive_claim_maps(metadata, root)
    suffix = _claim_suffix(publication)
    old_pdfs = _old_pdfs(manuscript, pdf, paper_id)
    if supplement := metadata.get("latest_supplementary_pdf"):
        old_pdfs.discard(root / supplement)
    bbl = manuscript / "main.bbl"
    had_bbl = bbl.is_file()
    with tempfile.TemporaryDirectory(prefix="openlabs-publication-") as temp:
        build = Path(temp)
        _copy_sources(manuscript, pdf, build)
        for path, content in edits.items():
            (build / path.relative_to(manuscript)).write_bytes(content)
        latexmk = shutil.which("latexmk") or str(
            Path.home() / ".local/opt/texlive/bin/x86_64-linux/latexmk")
        result = subprocess.run(
            [latexmk, "-pdf", "-g", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "main.tex"],
            cwd=build, env={**os.environ,
                            "PATH": f"{Path(latexmk).parent}:{__import__('os').environ.get('PATH', '')}"},
            capture_output=True, text=True, timeout=180,
        )
        bibliography = build / "main.bbl"
        if (result.returncode or not bibliography.is_file() or not (build / "main.pdf").is_file()
                or not re.search(r"\\bibitem(?:\[[^\]]*\])?\s*\{" + KEY + r"\}",
                                 bibliography.read_text(errors="replace"), re.S)):
            raise ValueError(f"Publication PDF build failed: {result.stdout[-1400:]}")
        for source in [*edits, *([bbl] if had_bbl else [])]:
            backup = history / "sources" / source.relative_to(manuscript)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, backup)
        (history / ".gitignore").write_text("!/*.pdf\n!/sources/**/*.bbl\n")
        for old in old_pdfs:
            old.rename(history / old.name)
        for path, content in edits.items():
            path.write_bytes(content)
        for path in maps.values():
            path.write_bytes(path.read_bytes() + suffix)
        for name in ("main.pdf", "main.bbl"):
            shutil.copyfile(build / name, manuscript / name)
    metadata["latest_pdf"] = (manuscript / "main.pdf").relative_to(root).as_posix()
    release["publication_metadata"] = {
        "identity": list(_identity(publication)), "original_pdf": pdf.name,
        "had_bbl": had_bbl, "version": str(metadata["version"]),
    }
    release["manuscript_snapshot_sha256"] = manuscript_snapshot_sha256(manuscript, manuscript / "main.pdf")
    write_paper_metadata(paper_id, metadata, root)
    return {"status": "projected", "repack": bool(maps)}


def prepare(paper_id, *, root):
    from paper_writing.review_flow import _locked_review

    return _locked_review(paper_id, root, _prepare)
