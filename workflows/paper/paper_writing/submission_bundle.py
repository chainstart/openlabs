"""The submission package (投稿包) prepared at finalization (user 2026-11-25).

"你看一下 nc 初投的时候，出了论文外还要哪些材料 ... 一并在定稿的时候准备好，形成一个投稿包。"
"论文管理网站 ... 它现在叫 latex 源代码，应该叫投稿包，把投稿相关的都打包放进里面。"

One package per delivered version, parameterised by the target journal's profile
(``submission-profiles.json``: Nature Communications, Scientific Reports, Elsevier, Springer
Nature, generic).  Layout of ``submission-package.zip`` (and of the unpacked directory)::

    README.md                      every file, its purpose, its field in the submission system,
                                   and what the submitter still does by hand
    submission-package.json        machine-readable manifest (files, SHA-256, profile, items)
    01-manuscript/manuscript.pdf   the reviewed PDF
    01-manuscript/latex/           one main.tex + one references.bib (+ the journal's .cls/.bst
                                   and the figures the text includes) -- flatten_tex
    02-supplementary/              supplementary PDF (+ its flattened source)
    03-cover-letter/               cover letter drafted by the writing model (number-checked)
    04-declarations/portal-fields.md  title, abstract, keywords and the declarations as plain
                                   text for the submission-system forms
    05-journal-items/              highlights, reporting checklists the manuscript carries
    06-reviewers/                  suggested reviewers (cited authors, verifiable, to be confirmed)
                                   + reviewer-verification.md when each was checked on the web

Two halves:

* :func:`assemble` is deterministic (no model, no network, no compilation, fixed ZIP
  timestamps): ``handoff.build_handoff_package`` calls it, so the package stays
  content-addressed and a rebuild gives the same bytes.
* :func:`prepare` runs once per version before delivery (release pipeline stage
  ``submission_materials``): it drafts the cover letter and the reviewer suggestions with the
  writing model and verifies the flattened LaTeX by compiling both versions.  Its outputs are
  committed under ``papers/<id>/submission/`` and read by :func:`assemble`.

Completeness is advisory (it travels with the package as README items and delivery notes):
everything a missing item needs is a human step before submission, which already has its own
gate (投稿前全面审核与投稿确认).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from paper_writing import flatten_tex

SCHEMA = "openlabs.submission_package.v1"
DRAFT_SCHEMA = "openlabs.submission_draft.v1"
PACKAGE_FILENAME = "submission-package.zip"
LEGACY_SOURCE_FILENAME = "source.zip"
PROFILES_PATH = Path(__file__).with_name("submission-profiles.json")
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
PENDING_HUMAN = "待投稿人核实"
VERIFICATION_SCHEMA = "openlabs.reviewer_verification.v1"
VERIFICATION_FILENAME = "reviewer-verification.json"
IDENTITY_PREFIXES = ("01-manuscript/", "02-supplementary/")


class SubmissionBundleError(RuntimeError):
    """The package cannot be assembled (the caller decides whether to fall back)."""


# --------------------------------------------------------------------------- profiles

def load_profiles() -> dict[str, Any]:
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def _venue_publisher(metadata: Mapping[str, Any], root: Path) -> str:
    try:
        from paper_writing import venue_registry

        venue = venue_registry.find_venue(venue_registry.load_venues(root),
                                          journal=metadata.get("target_journal"),
                                          issn=metadata.get("target_journal_issn"))
    except Exception:  # noqa: BLE001 - the profile then falls back to the generic one
        venue = None
    return str((venue or {}).get("publisher") or metadata.get("target_journal_publisher") or "")


def select_profile(metadata: Mapping[str, Any], root: Path,
                   override: str | None = None) -> tuple[str, dict[str, Any]]:
    profiles = load_profiles()["profiles"]
    if override:
        if override not in profiles:
            raise SubmissionBundleError(f"unknown submission profile {override!r}")
        return override, profiles[override]
    journal = str(metadata.get("target_journal") or "").strip().casefold()
    for name, profile in profiles.items():
        if journal and journal in {j.casefold() for j in profile["match"].get("journals", [])}:
            return name, profile
    publisher = _venue_publisher(metadata, root).casefold()
    for name, profile in profiles.items():
        if any(token.casefold() in publisher for token in profile["match"].get("publisher_contains", [])):
            return name, profile
    return "generic", profiles["generic"]


# --------------------------------------------------------------------------- legacy rule

def legacy_source_required(root: Path, paper_id: str, version: str) -> bool:
    """A version already delivered with the old LaTeX source ZIP keeps that artifact.

    Its committed release receipt names ``source.zip``; rebuilding the package for it must give
    the same bytes, or ``handoff sync-ready`` would see a new package for a delivered version.
    A version whose package was supplemented later (``program supplement-package``, a receipt
    naming ``submission-package.zip`` for the same version) uses the submission package.
    """
    releases = root / "papers" / paper_id / "releases"
    if not releases.is_dir():
        return False
    legacy = False
    for path in sorted(releases.glob("*.json")):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(receipt, Mapping) or str(receipt.get("version")) != version:
            continue
        filename = (receipt.get("source") or {}).get("filename")
        if filename == PACKAGE_FILENAME:
            return False
        legacy = legacy or filename == LEGACY_SOURCE_FILENAME
    return legacy


# --------------------------------------------------------------------------- text helpers

def latex_to_text(tex: str, cite: Callable[[str], str] | None = None) -> str:
    """Plain text of a short LaTeX passage for pasting into a submission form.

    ``cite`` renders the keys of a citation command (for example as the cited record's DOI link);
    without it citations are dropped.
    """
    text = "\n".join(flatten_tex._code_part(line)[0] for line in tex.split("\n"))
    if cite is not None:
        text = re.sub(r"\\cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}",
                      lambda m: cite(m.group(1)), text)
    text = re.sub(r"\\href\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\2 (\1)", text)
    text = re.sub(r"\\url\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:cite[a-zA-Z]*|ref|eqref|autoref|cref|Cref)\*?\s*(?:\[[^\]]*\]\s*)*\{[^{}]*\}", "", text)
    text = re.sub(r"\\(?:label|nocite)\s*\{[^{}]*\}", "", text)
    text = text.replace("\\\\", "\n").replace("~", " ").replace("---", "—").replace("--", "–")
    text = re.sub(r"\\([%&#_$])", r"\1", text)
    # An argument-less command directly before another one (\noindent\textbf{...}) goes first, or
    # the two would merge into one unknown command name below.
    text = re.sub(r"\\[a-zA-Z@]+\*?(?=\s*\\[a-zA-Z@])", "", text)
    for _ in range(4):
        text = re.sub(r"\\[a-zA-Z@]+\*?\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", "", text)
    text = text.replace("{", "").replace("}", "").replace("$", "")
    text = re.sub(r"[ \t]+([.,;:)])", r"\1", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


DECLARATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("competing_interests", r"competing interest|conflicts? of interest|declarations? of (?:competing )?interest"),
    ("author_contributions", r"contribution|credit"),
    ("data_availability", r"data (?:and code )?availability|availability of data|data access"),
    ("code_availability", r"code availability|(?:data and )?code availability|software availability"),
    ("funding", r"^funding|funding$|funding statement|financial support"),
    ("ai_use_statement", r"\bAI\b|generative|artificial intelligence|large language model"),
    ("ethics", r"ethic"),
    ("acknowledgements", r"acknowledg"),
)
# \\bmhead: the run-in heading of the Springer Nature sn-jnl class (Funding, Competing interests).
_HEADING = re.compile(r"\\(section|subsection|subsubsection|paragraph|bmhead)\*?\s*\{([^{}\n]*)\}")


def manuscript_declarations(source: str, bib: Mapping[str, Mapping[str, Any]] | None = None
                            ) -> dict[str, dict[str, str]]:
    """Declaration sections of the (flattened) manuscript, by kind, as LaTeX and plain text.

    Citations become the cited records' DOI/URL links (a data-availability statement usually
    cites the archive), so the form text keeps them.
    """
    def cite(keys: str) -> str:
        links = []
        for key in (k.strip() for k in keys.split(",")):
            entry = (bib or {}).get(key) or {}
            doi = str(entry.get("doi") or "").strip()
            links.append(f"https://doi.org/{doi}" if doi else str(entry.get("url") or entry.get("title") or key))
        return " (" + "; ".join(links) + ")"

    code = "\n".join(flatten_tex._code_part(line)[0] for line in source.split("\n"))
    stop = re.compile(r"\\(?:bibliography\b|bibliographystyle\b|printbibliography\b|begin\{thebibliography\}|"
                      r"end\{document\}|appendix\b|begin\{appendix|begin\{appendices\})")
    headings = list(_HEADING.finditer(code))
    found: dict[str, dict[str, str]] = {}
    for index, heading in enumerate(headings):
        title = heading.group(2).strip()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(code)
        body = stop.split(code[heading.end():end], maxsplit=1)[0].strip()
        for kind, pattern in DECLARATION_PATTERNS:
            if kind in found or not re.search(pattern, title, re.I):
                continue
            if kind == "code_availability" and not re.search(r"code|software", title, re.I):
                continue
            if kind == "data_availability" and not re.search(r"data", title, re.I):
                continue
            found[kind] = {"heading": latex_to_text(title), "latex": body, "text": latex_to_text(body, cite)}
    return found


def _people(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The byline records (``authors`` is a list, or a mapping with ``people``)."""
    authors = metadata.get("authors")
    people = authors.get("people") if isinstance(authors, Mapping) else authors
    return [person for person in people or [] if isinstance(person, Mapping)]


def display_name(name: str) -> str:
    """'Calafat, Antonia M.' -> 'Antonia M. Calafat' (BibTeX order to reading order)."""
    if "," not in name:
        return name.strip()
    family, given = (part.strip() for part in name.split(",", 1))
    return f"{given} {family}".strip()


def _registry_declarations(metadata: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    competing = metadata.get("competing_interests")
    if isinstance(competing, Mapping) and competing.get("statement"):
        out["competing_interests"] = str(competing["statement"])
    funding = metadata.get("funding_statement")
    if isinstance(funding, Mapping) and funding.get("text"):
        out["funding"] = str(funding["text"])
    declarations = metadata.get("declarations") if isinstance(metadata.get("declarations"), Mapping) else {}
    for key, kind in (("author_contributions", "author_contributions"), ("ai_use", "ai_use_statement")):
        record = declarations.get(key)
        if isinstance(record, Mapping) and record.get("text_latex"):
            out[kind] = latex_to_text(str(record["text_latex"]))
    return out


def _front_matter(source: str, metadata: Mapping[str, Any]) -> dict[str, str]:
    code = "\n".join(flatten_tex._code_part(line)[0] for line in source.split("\n"))
    fields: dict[str, str] = {"title": str(metadata.get("title") or "")}
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", code, re.S)
    if match:
        fields["abstract"] = latex_to_text(match.group(1))
    match = re.search(r"\\begin\{keyword\}(.*?)\\end\{keyword\}", code, re.S) or re.search(
        r"\\keywords?\s*\{([^{}]*)\}", code)
    if match:
        fields["keywords"] = ", ".join(latex_to_text(part) for part in re.split(r"\\sep\b|,|;", match.group(1))
                                       if latex_to_text(part))
    elif metadata.get("keywords"):
        keywords = metadata["keywords"]
        fields["keywords"] = ", ".join(map(str, keywords)) if isinstance(keywords, list) else str(keywords)
    return fields


# --------------------------------------------------------------------------- bibliography

_BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,")


def _bib_field(body: str, name: str) -> str:
    match = re.search(rf"(?<![A-Za-z]){name}\s*=\s*", body, re.I)
    if not match:
        return ""
    index = match.end()
    if index < len(body) and body[index] in "{\"":
        opener = body[index]
        depth, start = 0, index
        for position in range(index, len(body)):
            char = body[position]
            if opener == "{":
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return body[start + 1:position].strip()
            elif char == '"' and position > start:
                return body[start + 1:position].strip()
        return ""
    return re.match(r"[^,\n}]*", body[index:]).group(0).strip()


def parse_bib(text: str) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    matches = list(_BIB_ENTRY.finditer(text))
    for index, match in enumerate(matches):
        kind, key = match.group(1).lower(), match.group(2)
        if kind in {"comment", "string", "preamble"}:
            continue
        body = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        authors = [re.sub(r"[{}]", "", item).strip()
                   for item in re.split(r"\s+and\s+", _bib_field(body, "author")) if item.strip()]
        entries[key] = {"key": key, "type": kind, "authors": authors,
                        "title": re.sub(r"[{}]", "", _bib_field(body, "title")),
                        "year": _bib_field(body, "year"),
                        "journal": re.sub(r"[{}]", "", _bib_field(body, "journal") or _bib_field(body, "booktitle")),
                        "doi": _bib_field(body, "doi"), "url": _bib_field(body, "url")}
    return entries


def _name_parts(name: str) -> tuple[str, str]:
    """(family, given) of a BibTeX or display name, accents and case folded."""
    import unicodedata

    def fold(value: str) -> str:
        # TeX accents ({\'c}, \v{s}, {\"o}) name the base letter: Latkovi{\'c} is Latković.
        value = re.sub(r"\\[`'^\"~=.uvHtcdbk]\s*\{?\s*([A-Za-z])\s*\}?", r"\1", value)
        value = latex_to_text(value)
        value = unicodedata.normalize("NFKD", value)
        return "".join(c for c in value if not unicodedata.combining(c)).casefold().strip(" .")

    if "," in name:
        family, given = name.split(",", 1)
    else:
        parts = name.split()
        family, given = (parts[-1], " ".join(parts[:-1])) if parts else ("", "")
    return fold(family), fold(given)


def same_person(left: str, right: str) -> bool:
    lf, lg = _name_parts(left)
    rf, rg = _name_parts(right)
    if not lf or lf != rf:
        return False
    if not lg or not rg:
        return True
    return lg[0] == rg[0]


def _cited_keys(source: str) -> set[str]:
    keys: set[str] = set()
    for match in re.finditer(r"\\(?:cite[a-zA-Z]*|nocite)\*?\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}", source):
        keys.update(item.strip() for item in match.group(1).split(",") if item.strip())
    return keys


def verify_reviewers(candidates: list[Mapping[str, Any]], *, bib: Mapping[str, Mapping[str, Any]],
                     cited: set[str], authors: list[str], affiliations: list[str],
                     limit: int = 5) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep only nominees whose authorship of a cited, DOI/URL-identified work is on record.

    A nominee is dropped when the cited entry is not in the bibliography or not cited in the
    text, has neither DOI nor URL, does not list the nominee among its authors, lists one of
    this paper's authors (a co-authorship: conflict of interest), when the nominee is one of
    this paper's authors, or shares one of this paper's affiliations.
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    own_affiliations = {re.sub(r"\W+", " ", a).casefold().strip() for a in affiliations if a}
    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        key = str(candidate.get("bib_key") or "").strip()
        entry = bib.get(key)
        reason = None
        if not name or not entry:
            reason = "cited work not in the bibliography"
        elif key not in cited:
            reason = "work is in the .bib but not cited in the manuscript"
        elif not (entry.get("doi") or entry.get("url")):
            reason = "cited work has no DOI or URL to verify authorship"
        elif not any(same_person(name, author) for author in entry.get("authors", [])):
            reason = "nominee is not an author of the cited work"
        elif any(same_person(name, author) for author in authors):
            reason = "nominee is an author of this paper"
        elif any(same_person(own, author) for own in authors for author in entry.get("authors", [])):
            reason = "cited work is co-authored by an author of this paper (conflict of interest)"
        elif re.sub(r"\W+", " ", str(candidate.get("institution") or "")).casefold().strip() in own_affiliations \
                and str(candidate.get("institution") or "").strip():
            reason = "nominee shares an affiliation with this paper's authors"
        elif any(same_person(display_name(name), item["name"]) for item in kept):
            reason = "duplicate nominee"
        elif len(kept) >= limit:
            reason = f"more than {limit} nominees"
        if reason:
            dropped.append({"name": name, "bib_key": key, "reason": reason})
            continue
        doi = str(entry.get("doi") or "").strip()
        link = f"https://doi.org/{doi}" if doi else str(entry.get("url"))
        kept.append({
            "name": display_name(name),
            "institution": str(candidate.get("institution") or "").strip() or PENDING_HUMAN,
            "institution_verified": False,
            "evidence": {"bib_key": key, "title": entry.get("title"), "year": entry.get("year"),
                         "venue": entry.get("journal"), "link": link,
                         "listed_authors": entry.get("authors")},
            "email_source": f"Corresponding-author contact on the cited article ({link}) or the "
                            "nominee's current institutional page; use an institutional address.",
            "reason": str(candidate.get("reason") or "").strip(),
            "status": PENDING_HUMAN,
        })
    return kept, dropped


# --------------------------------------------------------------------------- numbers

_NUMBER = re.compile(r"(?<![\w.])[-−–]?\d[\d,]*(?:\.\d+)?%?")


def _numbers(text: str) -> list[str]:
    out = []
    for raw in _NUMBER.findall(text):
        value = raw.replace("−", "-").replace("–", "-").replace(",", "").rstrip("%").lstrip("-")
        if value:
            out.append(value)
    return out


def number_mismatches(letter: str, manuscript_text: str) -> list[str]:
    """Numbers in the letter that the manuscript does not state."""
    known = set(_numbers(manuscript_text))
    return sorted({value for value in _numbers(letter) if value not in known})


# --------------------------------------------------------------------------- paths

def drafts_dir(root: Path, paper_id: str) -> Path:
    return root / "papers" / paper_id / "submission"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _manuscript_paths(paper_id: str, metadata: Mapping[str, Any], root: Path) -> tuple[Path, Path, Path | None]:
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    pdf = root / str(metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf")
    supplement = None
    if metadata.get("latest_supplementary_pdf"):
        supplement = (root / str(metadata["latest_supplementary_pdf"])).resolve()
    return manuscript, pdf, supplement


# --------------------------------------------------------------------------- assemble

def _zip_directory(directory: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(path.relative_to(directory).as_posix(), date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status_label(status: str) -> str:
    return load_profiles()["statuses"].get(status, status)


def _flat_or_canonical(manuscript: Path, main: str, target: Path,
                       verification: Mapping[str, Any] | None, notes: list[str]) -> dict[str, Any]:
    result = flatten_tex.flatten(manuscript, main)
    record: dict[str, Any] = {"main_sha256": result.report["main_sha256"],
                              "inlined_inputs": len(result.report.get("inlined_inputs", [])),
                              "inlined_packages": result.report.get("inlined_packages", [])}
    if verification and verification.get("main_sha256") == record["main_sha256"]:
        record["verification"] = {"equivalent": bool(verification.get("equivalent")),
                                  "pages": verification.get("pages"),
                                  "engine": verification.get("engine")}
        if not verification.get("equivalent"):
            notes.append(f"{main} 扁平化后编译的 PDF 与原稿不一致（第 {verification.get('differing_pages')} 页），"
                         "已改附原多文件源码，投稿前请核对。")
            for path in _canonical_sources(manuscript):
                destination = target / path.relative_to(manuscript)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
            record["assembly"] = "canonical_multi_file"
            return record
    else:
        record["verification"] = None
    flatten_tex.write(result, target)
    record["assembly"] = "flattened"
    record["files"] = ["main.tex", *(["references.bib"] if result.bib is not None else []),
                       *sorted(result.files)]
    return record


def _canonical_sources(manuscript: Path) -> list[Path]:
    """The handoff's clean source allowlist (used only when flattening was not equivalent)."""
    from paper_writing.handoff import CLEAN_SOURCE_SUFFIXES, EXCLUDED_SOURCE_DIRECTORIES

    chosen = []
    for path in sorted(p for p in manuscript.rglob("*") if p.is_file()):
        parts = path.relative_to(manuscript).parts
        if (path.suffix.casefold() not in CLEAN_SOURCE_SUFFIXES or "figure-src" in parts
                or any(part in EXCLUDED_SOURCE_DIRECTORIES or part.startswith(("build-", "_build"))
                       for part in parts[:-1])
                or (len(parts) == 1 and path.suffix.casefold() == ".pdf")):
            continue
        chosen.append(path)
    return chosen


def _journal_items(paper_id: str, metadata: Mapping[str, Any], root: Path, manuscript: Path) -> list[tuple[Path, str, str]]:
    """(source, package name, purpose) of journal items the paper carries."""
    items: list[tuple[Path, str, str]] = []
    for name in ("highlights.txt", "highlights.md"):
        if (manuscript / name).is_file():
            items.append((manuscript / name, name, "Highlights"))
            break
    for path in sorted(manuscript.glob("graphical-abstract.*")):
        items.append((path, path.name, "Graphical abstract"))
    production = root / "papers" / paper_id / "production"
    if production.is_dir():
        for path in sorted(production.rglob("*checklist*.pdf")):
            items.append((path, path.name, "Reporting checklist"))
    extra = metadata.get("submission_files")
    if isinstance(extra, list):
        for item in extra:
            if isinstance(item, Mapping) and item.get("path"):
                path = (root / str(item["path"])).resolve()
                if path.is_file() and path.is_relative_to(root.resolve()):
                    items.append((path, path.name, str(item.get("role") or "Additional file")))
    seen: set[str] = set()
    unique = []
    for source, name, purpose in items:
        if name not in seen:
            seen.add(name)
            unique.append((source, name, purpose))
    return unique


def assemble(paper_id: str, *, root: str | Path, metadata: Mapping[str, Any], output: str | Path,
             profile: str | None = None, demo_note: str | None = None,
             drafts: str | Path | None = None) -> dict[str, Any]:
    """Assemble the package directory ``output`` (deterministic; returns the manifest)."""
    repo = Path(root).resolve()
    target = Path(output)
    if target.exists() and any(target.iterdir()):
        raise SubmissionBundleError(f"package directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    manuscript, pdf, supplement = _manuscript_paths(paper_id, metadata, repo)
    if not (manuscript / "main.tex").is_file() or not pdf.is_file():
        raise SubmissionBundleError("manuscript main.tex or its compiled PDF is missing")
    profile_id, spec = select_profile(metadata, repo, profile)
    drafts = Path(drafts) if drafts else drafts_dir(repo, paper_id)
    version = str(metadata.get("version") or "1.0.0")
    verification = _read_json(drafts / "flatten-verification.json") or {}
    notes: list[str] = []
    files: list[dict[str, str]] = []

    def add(relative: str, purpose: str, portal: str) -> None:
        files.append({"path": relative, "purpose": purpose, "portal": portal})

    # 01 manuscript
    shutil.copyfile(pdf, _mkparent(target / "01-manuscript/manuscript.pdf"))
    add("01-manuscript/manuscript.pdf", "审稿正文 PDF（与评审通过的版本逐字节相同）", _portal(spec, "manuscript_pdf"))
    try:
        latex = _flat_or_canonical(manuscript, "main.tex", target / "01-manuscript/latex",
                                   (verification.get("main") or {}), notes)
    except flatten_tex.FlattenError as exc:
        raise SubmissionBundleError(f"main.tex cannot be flattened: {exc}") from exc
    add("01-manuscript/latex/", "LaTeX 源文件：单个 main.tex + references.bib + 期刊文档类/样式 + 正文引用的图件",
        _portal(spec, "latex_source"))
    policy = metadata.get("target_journal_format")
    if isinstance(policy, Mapping) and policy.get("primary_submission_format") == "docx":
        word = (repo / str(policy.get("primary_submission_asset") or "")).resolve()
        if word.is_file() and word.parent == manuscript.resolve() and word.suffix.casefold() == ".docx":
            shutil.copyfile(word, _mkparent(target / "01-manuscript" / word.name))
            add(f"01-manuscript/{word.name}", "期刊要求的 Word 正文（登记的主投稿文件）", "Manuscript (Word)")
    if latex.get("verification") is None:
        notes.append("扁平化 LaTeX 尚未做编译等价验证（paper-writing submission prepare 会编译比对）；"
                     "上传源文件前请编译一次，与 01-manuscript/manuscript.pdf 对照。")

    # 02 supplementary
    supplement_record = None
    if supplement is not None and supplement.is_file():
        shutil.copyfile(supplement, _mkparent(target / "02-supplementary/supplementary.pdf"))
        add("02-supplementary/supplementary.pdf", "补充材料 PDF", _portal(spec, "supplementary_information"))
        source = supplement.with_suffix(".tex")
        if source.is_file() and source.parent == manuscript.resolve():
            try:
                supplement_record = _flat_or_canonical(manuscript, source.name,
                                                       target / "02-supplementary/latex",
                                                       (verification.get("supplement") or {}), notes)
                add("02-supplementary/latex/", "补充材料 LaTeX 源文件（单文件）", "Supplementary material (source)")
            except flatten_tex.FlattenError as exc:
                notes.append(f"补充材料源文件未能扁平化（{exc}）；仅附 PDF。")

    # 03 cover letter
    letter = drafts / "cover-letter.md"
    receipt = _read_json(drafts / "draft-receipt.json") or {}
    if letter.is_file():
        text = letter.read_text(encoding="utf-8")
        (_mkparent(target / "03-cover-letter/cover-letter.md")).write_text(text, encoding="utf-8")
        (target / "03-cover-letter/cover-letter.txt").write_text(_markdown_to_text(text), encoding="utf-8")
        add("03-cover-letter/cover-letter.md", "Cover letter（写作模型起草，数字已与正文核对；投稿人审阅后签名）",
            _portal(spec, "cover_letter"))
        add("03-cover-letter/cover-letter.txt", "同上，纯文本，便于粘贴到投稿系统", _portal(spec, "cover_letter"))
        if str(receipt.get("version")) != version:
            notes.append(f"Cover letter 起草于 v{receipt.get('version')}，当前为 v{version}；请核对其中的结果与数字。")
        if receipt.get("number_mismatches"):
            notes.append("Cover letter 中有正文未出现的数字，需人工核对：" + ", ".join(receipt["number_mismatches"]))
    else:
        (_mkparent(target / "03-cover-letter/cover-letter-TEMPLATE.md")).write_text(
            _letter_template(metadata, spec), encoding="utf-8")
        add("03-cover-letter/cover-letter-TEMPLATE.md", "Cover letter 模板（尚无模型起草稿，需补写三段）",
            _portal(spec, "cover_letter"))
        notes.append("尚无模型起草的 cover letter（paper-writing submission prepare 未运行或失败），已附模板。")

    # 04 declarations and form fields
    flat_source = (target / "01-manuscript/latex/main.tex").read_text(encoding="utf-8", errors="replace")
    flat_bib = target / "01-manuscript/latex/references.bib"
    found = manuscript_declarations(flat_source, parse_bib(flat_bib.read_text(encoding="utf-8", errors="replace"))
                                    if flat_bib.is_file() else {})
    registry = _registry_declarations(metadata)
    front = _front_matter(flat_source, metadata)
    portal_fields, declaration_record = _portal_fields(spec, metadata, front, found, registry)
    (_mkparent(target / "04-declarations/portal-fields.md")).write_text(portal_fields, encoding="utf-8")
    add("04-declarations/portal-fields.md", "投稿系统表单逐栏文本：标题、摘要、关键词、作者与单位、各项声明", "Online forms")

    # 05 journal items (highlights only where the journal takes them)
    takes_highlights = any(item["id"] == "highlights" and item["status"] != "not_required"
                           for item in spec["items"])
    for source_path, name, purpose in _journal_items(paper_id, metadata, repo, manuscript):
        if purpose == "Highlights" and not takes_highlights:
            continue
        shutil.copyfile(source_path, _mkparent(target / "05-journal-items" / name))
        add(f"05-journal-items/{name}", purpose, purpose)

    # 06 reviewers
    reviewers = _read_json(drafts / "suggested-reviewers.json") or {}
    kept = [item for item in reviewers.get("suggested", []) if isinstance(item, Mapping)]
    checked = _read_json(drafts / VERIFICATION_FILENAME)
    if checked is not None and (checked.get("schema_version") != VERIFICATION_SCHEMA
                                or str(checked.get("version")) != version):
        notes.append(f"建议审稿人核实记录不属于 v{version}，未采用；投稿前请重新核实。")
        checked = None
    if checked is not None:
        (_mkparent(target / "06-reviewers/reviewer-verification.md")).write_text(
            _verification_markdown(checked), encoding="utf-8")
        add("06-reviewers/reviewer-verification.md",
            f"建议审稿人逐人网上核实记录（{checked.get('checked_on')}，含来源 URL）", "—（投稿人参考，不上传）")
    elif kept:
        notes.append("建议审稿人尚未逐人网上核实（无 reviewer-verification.json）；投稿前请核实。")
    if kept:
        (_mkparent(target / "06-reviewers/suggested-reviewers.md")).write_text(
            _reviewers_markdown(kept, checked), encoding="utf-8")
        (target / "06-reviewers/suggested-reviewers.json").write_text(
            json.dumps({"suggested": kept, "status": PENDING_HUMAN}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        add("06-reviewers/suggested-reviewers.md",
            f"建议审稿人 {len(kept)} 名（均为正文引用文献的作者；"
            + (f"{checked.get('checked_on')} 已逐人核实，邮箱{PENDING_HUMAN}）" if checked else f"{PENDING_HUMAN}）"),
            _portal(spec, "suggested_reviewers"))
        add("06-reviewers/suggested-reviewers.json", "同上，机器可读", _portal(spec, "suggested_reviewers"))
        if len(kept) < 3:
            notes.append(f"可核实的建议审稿人只有 {len(kept)} 名，少于 3 名；如期刊要求，请补充。")

    # Item checklist
    present = {"manuscript_pdf": True, "latex_source": True, "figures_separate": True,
               "supplementary_information": supplement is not None and supplement.is_file(),
               "cover_letter": letter.is_file(), "suggested_reviewers": bool(kept),
               "highlights": any(f["path"].startswith("05-journal-items/highlights") for f in files)}
    for kind, record in declaration_record.items():
        present[kind] = record["origin"] != "missing"
    domain = str(metadata.get("domain") or "").casefold()
    items = []
    for item in spec["items"]:
        status = item["status"]
        applies = item.get("applies_to_domains")
        if applies is not None and status == "required_if_applicable":
            status_note = ("本稿领域为 " + (domain or "未登记") + "，"
                           + ("适用" if any(tag in domain or tag in str(metadata.get("subdomain") or "")
                                           for tag in applies) else "一般不适用"))
        else:
            status_note = ""
        provided = present.get(item["id"])
        if item["provided_by"] == "human":
            state = "人工"
        elif provided:
            state = "已提供"
        elif status in {"required", "recommended"}:
            state = "缺"
        else:
            state = "无"
        items.append({"id": item["id"], "label": item["label"], "status": status,
                      "status_label": _status_label(status), "state": state,
                      "portal": item.get("portal"), "source": item.get("source"), "note": status_note})
    missing = [item for item in items if item["state"] == "缺" and item["status"] == "required"]
    manifest = {
        "schema_version": SCHEMA,
        "paper_id": paper_id,
        "version": version,
        "title": metadata.get("title"),
        "target_journal": metadata.get("target_journal"),
        "profile": profile_id,
        "profile_label": spec["label"],
        "latex": latex,
        "supplement_latex": supplement_record,
        "cover_letter": {"present": letter.is_file(), "drafted_for_version": receipt.get("version"),
                         "model": receipt.get("model"), "number_mismatches": receipt.get("number_mismatches") or []},
        "suggested_reviewers": len(kept),
        "reviewers_verified_on": (checked or {}).get("checked_on"),
        "declarations": declaration_record,
        "items": items,
        "missing_required": [item["id"] for item in missing],
        "notes": notes,
    }
    if demo_note:
        manifest["demo"] = demo_note
    readme = _readme(manifest, spec, files, metadata, demo_note)
    (target / "README.md").write_text(readme, encoding="utf-8")
    manifest["files"] = [
        {"path": path.relative_to(target).as_posix(), "sha256": _sha(path), "size": path.stat().st_size}
        for path in sorted(p for p in target.rglob("*") if p.is_file())]
    # The manuscript-bound part (PDF, LaTeX, supplement): what identifies the delivered paper.
    # The rest (README, cover letter, form text, reviewers, profile) follows the registry and
    # may be refreshed without a new manuscript version.
    manifest["identity_sha256"] = hashlib.sha256(json.dumps(
        [[f["path"], f["sha256"]] for f in manifest["files"]
         if f["path"].startswith(IDENTITY_PREFIXES)], separators=(",", ":")).encode()).hexdigest()
    (target / "submission-package.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def build(paper_id: str, *, root: str | Path, metadata: Mapping[str, Any], output: str | Path,
          profile: str | None = None, demo_note: str | None = None,
          drafts: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Assemble ``output/submission-package/`` and ``output/submission-package.zip``."""
    out = Path(output)
    directory = out / "submission-package"
    manifest = assemble(paper_id, root=root, metadata=metadata, output=directory, profile=profile,
                        demo_note=demo_note, drafts=drafts)
    archive = out / PACKAGE_FILENAME
    _zip_directory(directory, archive)
    if archive.stat().st_size > MAX_PACKAGE_BYTES:
        raise SubmissionBundleError(f"submission package exceeds {MAX_PACKAGE_BYTES} bytes")
    return archive, manifest


def _mkparent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _portal(spec: Mapping[str, Any], item_id: str) -> str:
    for item in spec["items"]:
        if item["id"] == item_id:
            return str(item.get("portal") or "")
    return ""


def _markdown_to_text(text: str) -> str:
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    return text


DECLARATION_LABELS = {
    "competing_interests": "Competing interests / Declaration of interest",
    "author_contributions": "Author contributions",
    "data_availability": "Data availability",
    "code_availability": "Code availability",
    "funding": "Funding",
    "ai_use_statement": "AI-use declaration",
    "ethics": "Ethics",
}


def _portal_fields(spec: Mapping[str, Any], metadata: Mapping[str, Any], front: Mapping[str, str],
                   found: Mapping[str, Mapping[str, str]], registry: Mapping[str, str]) -> tuple[str, dict[str, Any]]:
    lines = ["# 投稿系统表单文本", "",
             "以下文本取自评审通过的稿件（文末声明）与论文登记表。粘贴前核对；声明须与正文一致。", ""]
    lines += ["## Title", "", str(front.get("title") or ""), ""]
    if front.get("abstract"):
        lines += ["## Abstract", "", front["abstract"], ""]
    if front.get("keywords"):
        lines += ["## Keywords", "", front["keywords"], ""]
    people = _people(metadata)
    affiliations = {str(a.get("id")): str(a.get("name") or "") for a in metadata.get("affiliations") or []
                    if isinstance(a, Mapping)}
    if isinstance(people, list) and people:
        lines += ["## Authors (byline order)", ""]
        for index, person in enumerate(people, 1):
            if not isinstance(person, Mapping):
                continue
            units = "; ".join(affiliations.get(str(i), str(i)) for i in person.get("affiliation_ids") or [])
            mark = "（通讯作者）" if person.get("corresponding") else ""
            orcid = str(person.get("orcid") or "").strip() or PENDING_HUMAN
            lines.append(f"{index}. {person.get('name')}{mark} — {units}；ORCID：{orcid}")
        lines.append("")
    record: dict[str, Any] = {}
    for kind, label in DECLARATION_LABELS.items():
        manuscript = found.get(kind)
        fallback = registry.get(kind)
        if manuscript and manuscript.get("text"):
            text, origin = manuscript["text"], "manuscript"
        elif fallback:
            text, origin = fallback, "registry"
        else:
            text, origin = "", "missing"
        if kind == "ethics" and origin == "missing":
            continue
        record[kind] = {"origin": origin, "sha256": hashlib.sha256(text.encode()).hexdigest() if text else None}
        lines += [f"## {label}", ""]
        if text:
            lines += [text, "", f"_来源：{'正文文末声明' if origin == 'manuscript' else '论文登记表'}_", ""]
        else:
            lines += ["（稿件与登记表均未找到；如期刊要求，投稿前补写）", ""]
        if kind == "ai_use_statement" and spec.get("ai_statement_location"):
            lines += [f"_位置要求：{spec['ai_statement_location']}_", ""]
    return "\n".join(lines).rstrip() + "\n", record


def _reviewers_markdown(kept: list[Mapping[str, Any]], verification: Mapping[str, Any] | None = None) -> str:
    checked = (verification or {}).get("checked_on")
    intro = (f"以下人选均为本文引用文献的作者，按引用条目核对过作者身份并排除了与本文作者的合作关系。"
             f"机构与邮箱{PENDING_HUMAN}：请打开文献链接或其机构主页取得机构邮箱，核实不了的不要填写。")
    if checked:
        intro = (f"以下人选已于 {checked} 逐人在网上核实（是否真实存在、单位、研究方向、近期论文、利益冲突），"
                 "来源见 reviewer-verification.md；核实不了或有利益冲突的已替换或删去。"
                 f"邮箱{PENDING_HUMAN}：请从其机构主页或近期论文的通讯作者信息取机构邮箱。")
    lines = ["# 建议审稿人", "", intro, ""]
    for index, item in enumerate(kept, 1):
        evidence = item.get("evidence") or {}
        institution_note = (f"已核实 {checked}" if checked and item.get("institution_verified")
                            else PENDING_HUMAN)
        lines += [f"## {index}. {item.get('name')}", "",
                  f"- 机构：{item.get('institution')}（{institution_note}）",
                  f"- 依据文献：{evidence.get('title')}（{evidence.get('venue') or ''} {evidence.get('year') or ''}），"
                  f"{evidence.get('link')}",
                  f"- 邮箱来源：{item.get('email_source')}",
                  f"- 推荐理由：{item.get('reason')}", ""]
    return "\n".join(lines).rstrip() + "\n"


def _verification_markdown(record: Mapping[str, Any]) -> str:
    """The web check of each nominee (user 2026-11-26): identity, affiliation, field, recent work."""
    decisions = {"keep": "保留", "replace": "替换（新人选）", "added": "替换（新人选）", "remove": "删去"}
    lines = ["# 建议审稿人核实记录", "",
             f"- 核实日期：{record.get('checked_on')}",
             f"- 核实人：{record.get('checked_by') or '—'}",
             f"- 方法：{record.get('method') or '网页检索机构主页、论文页与学术档案，逐项核对'}", ""]
    for index, item in enumerate(record.get("reviewers") or [], 1):
        if not isinstance(item, Mapping):
            continue
        lines += [f"## {index}. {item.get('name')}：{decisions.get(str(item.get('decision')), item.get('decision'))}", ""]
        for label, key in (("是否真实存在", "exists"), ("单位", "institution"), ("研究方向", "research_area"),
                           ("利益冲突核查", "conflict_check"), ("结论说明", "note")):
            value = item.get(key)
            if isinstance(value, bool):
                value = "是" if value else "否 / 未能核实"
            if value not in (None, ""):
                lines.append(f"- {label}：{value}")
        papers = [paper for paper in item.get("recent_papers") or [] if isinstance(paper, Mapping)]
        if papers:
            lines.append("- 近期论文：")
            lines += [f"  - {paper.get('title')}（{paper.get('venue') or ''} {paper.get('year') or ''}）"
                      f"{' ' + str(paper['url']) if paper.get('url') else ''}" for paper in papers]
        sources = [str(url) for url in item.get("sources") or [] if url]
        if sources:
            lines.append("- 来源：")
            lines += [f"  - {url}" for url in sources]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _letter_template(metadata: Mapping[str, Any], spec: Mapping[str, Any]) -> str:
    journal = metadata.get("target_journal") or "[Journal]"
    return (f"Dear Editor,\n\nWe submit our manuscript, \"{metadata.get('title')}\", for consideration in {journal}.\n\n"
            "[Significance: one paragraph, restrained, using only results stated in the manuscript.]\n\n"
            "[Novelty: one paragraph.]\n\n[Fit for the journal's readers: one paragraph.]\n\n"
            "This manuscript has not been published and is not under consideration elsewhere. "
            "All authors have approved the submission.\n\nSincerely,\n[Corresponding author]\n")


def _readme(manifest: Mapping[str, Any], spec: Mapping[str, Any], files: list[Mapping[str, str]],
            metadata: Mapping[str, Any], demo_note: str | None) -> str:
    lines = [f"# 投稿包：{manifest['title']}", ""]
    if demo_note:
        lines += [f"> **{demo_note}**", ""]
    latex = manifest["latex"]
    verified = latex.get("verification")
    lines += [
        f"- 论文编号：{manifest['paper_id']}，版本 v{manifest['version']}",
        f"- 目标期刊：{manifest['target_journal']}（材料模板：{spec['label']}）",
        f"- LaTeX：{'单个 main.tex + references.bib' if latex['assembly'] == 'flattened' else '原多文件源码'}"
        + (f"；编译等价验证{'通过' if verified.get('equivalent') else '未通过'}（{verified.get('pages')} 页）"
           if verified else "；尚未做编译等价验证"),
        "",
        "## 文件与投稿系统栏目", "",
        "| 文件 | 用途 | 投稿系统栏目 |", "|---|---|---|",
    ]
    lines += [f"| `{item['path']}` | {item['purpose']} | {item['portal']} |" for item in files]
    lines += ["", "## 期刊初投材料清单", "",
              "| 材料 | 期刊要求 | 本包 | 出处 |", "|---|---|---|---|"]
    for item in manifest["items"]:
        source = f"[官方页面]({item['source']})" if item.get("source") else "—"
        note = f"；{item['note']}" if item.get("note") else ""
        lines.append(f"| {item['label']} | {item['status_label']}{note} | {item['state']} | {source} |")
    todo = list(spec.get("manual_steps") or [])
    for item in manifest["items"]:
        if item["state"] == "人工" and item["status"] in {"required", "required_if_applicable"}:
            todo.append(f"{item['label']}：由投稿人在投稿系统完成。")
        if item["state"] == "缺":
            todo.append(f"缺少：{item['label']}（{item['status_label']}）。")
    todo += list(manifest.get("notes") or [])
    todo += [
        "ORCID：在投稿系统中为通讯作者（及期刊要求的其他作者）登录关联 ORCID。",
        "核对作者顺序、单位、通讯作者与 04-declarations/portal-fields.md 一致后再提交。",
        "提交后在论文管理网站登记稿号与回执。",
    ]
    if manifest["suggested_reviewers"] and manifest.get("reviewers_verified_on"):
        todo.append(f"建议审稿人：已于 {manifest['reviewers_verified_on']} 逐人核实（见 "
                    f"06-reviewers/reviewer-verification.md）；从机构主页取机构邮箱后填写（{PENDING_HUMAN}）。")
    elif manifest["suggested_reviewers"]:
        todo.append(f"建议审稿人：逐人核实机构与机构邮箱（{PENDING_HUMAN}），核实不了的删去。")
    cv = next((item for item in manifest["items"] if item["id"] == "cv"), None)
    if cv and cv["status"] == "not_required":
        todo.append("CV：本刊官方页面未要求提交，无需准备。")
    lines += ["", "## 投稿人需要人工处理的事项", ""]
    lines += [f"{index}. {text}" for index, text in enumerate(dict.fromkeys(todo), 1)]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- status (release pipeline)

def materials_status(paper_id: str, *, root: str | Path,
                     metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """What ``prepare`` still has to do for the current version (read-only)."""
    from paper_writing.registry import load_paper_metadata

    repo = Path(root).resolve()
    metadata = metadata if metadata is not None else load_paper_metadata(paper_id, repo)
    version = str(metadata.get("version") or "1.0.0")
    drafts = drafts_dir(repo, paper_id)
    receipt = _read_json(drafts / "draft-receipt.json") or {}
    verification = _read_json(drafts / "flatten-verification.json") or {}
    manuscript, _, _ = _manuscript_paths(paper_id, metadata, repo)
    reasons = []
    if str(receipt.get("version")) != version:
        reasons.append("draft")
    try:
        current = flatten_tex.flatten(manuscript).report["main_sha256"]
    except (flatten_tex.FlattenError, OSError) as exc:
        return {"pending": False, "reasons": [], "error": f"flatten: {exc}"}
    if (verification.get("main") or {}).get("main_sha256") != current \
            and (verification.get("attempted_sha256") != current):
        reasons.append("verify")
    return {"pending": bool(reasons), "reasons": reasons, "version": version,
            "legacy": legacy_source_required(repo, paper_id, version)}


# --------------------------------------------------------------------------- prepare (model + TeX)

DRAFT_SYSTEM = """You are the corresponding author of a research manuscript, writing the cover letter that
goes to the journal editor. You write in a restrained, factual register: no superlatives, no claims the
manuscript does not make, no numbers the manuscript does not state."""

DRAFT_TASK = """# Task: cover-letter paragraphs and suggested reviewers for {journal}

The letter goes to {audience}. Write exactly three short paragraphs (each 60-130 words):

1. `significance` -- why the question matters and what the paper finds, using only the manuscript's own
   results (copy any number exactly as the manuscript states it, or state no number).
2. `novelty` -- what is new relative to prior work the manuscript cites, without disparaging it.
3. `fit` -- why the work suits this journal's readers ({journal}{article_type}).

{avoid}
Do not repeat the abstract sentence by sentence. Do not mention artificial intelligence, the writing
process, internal reviews or scores. Do not add greetings, signatures or statements about originality,
approval or competing interests: they are added separately.

Then nominate up to five suggested reviewers. Each must be an author of a work listed in the
BIBLIOGRAPHY below AND cited in the manuscript; give that work's key in `bib_key` and the name as
listed there. Prefer senior or corresponding authors of directly relevant, recent work, from
different groups and countries. Never nominate an author of this paper ({authors}) or anyone who
co-authored a cited work with them. `institution`: the affiliation stated on that cited work if you
know it, otherwise an empty string -- never guess. `reason`: one sentence on the expertise that fits.
Return no reviewer rather than an unverifiable one.

# BIBLIOGRAPHY (key | authors | year | title | venue | DOI)
{bibliography}

# MANUSCRIPT (LaTeX, flattened)
{manuscript}
"""

DRAFT_SCHEMA_JSON = {
    "type": "object", "additionalProperties": False,
    "required": ["significance", "novelty", "fit", "suggested_reviewers"],
    "properties": {
        "significance": {"type": "string", "minLength": 1},
        "novelty": {"type": "string", "minLength": 1},
        "fit": {"type": "string", "minLength": 1},
        "suggested_reviewers": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "bib_key", "institution", "reason"],
            "properties": {"name": {"type": "string"}, "bib_key": {"type": "string"},
                           "institution": {"type": "string"}, "reason": {"type": "string"}}}},
    },
}

STATEMENTS = {
    "original_not_elsewhere": "This manuscript is original, has not been published, and is not under consideration elsewhere.",
    "all_authors_approved": "All authors have read and approved the submitted version.",
    "related_manuscripts": "There are no related manuscripts under consideration or in press elsewhere.",
    "preprint": "The manuscript has not been posted as a preprint.",
    "reviewers_in_system": "Suggested reviewers are listed in the submission system.",
    "reviewers_in_letter": None,  # rendered from the verified list
}


def drafter_roles(root: Path) -> list[tuple[str, dict[str, Any]]]:
    from paper_writing.editorial_rewrite import rewrite_config
    from paper_writing.registry import load_review_settings

    settings = load_review_settings(root, required=False)
    configured = ((settings.get("quality_gate") or {}).get("submission_package") or {}).get("drafters")
    if isinstance(configured, Mapping) and configured:
        return [(str(k), dict(v)) for k, v in configured.items()]
    rewriters = rewrite_config(root)["rewriters"]
    order = sorted(rewriters, key=lambda name: (name != "opus", name))
    return [(name, rewriters[name]) for name in order]


def _bibliography_listing(bib: Mapping[str, Mapping[str, Any]], cited: set[str]) -> str:
    rows = []
    for key in sorted(k for k in bib if k in cited):
        entry = bib[key]
        rows.append(" | ".join([key, "; ".join(entry.get("authors") or [])[:400], str(entry.get("year") or ""),
                                str(entry.get("title") or "")[:200], str(entry.get("journal") or "")[:120],
                                str(entry.get("doi") or entry.get("url") or "")]))
    return "\n".join(rows)


def compose_letter(metadata: Mapping[str, Any], spec: Mapping[str, Any], paragraphs: Mapping[str, str],
                   reviewers: list[Mapping[str, Any]], *, demo_note: str | None = None) -> str:
    journal = metadata.get("target_journal") or "the journal"
    article = metadata.get("article_type") or (metadata.get("target_journal_format") or {}).get("article_type")
    people = _people(metadata)
    affiliations = {str(a.get("id")): str(a.get("name") or "") for a in metadata.get("affiliations") or []
                    if isinstance(a, Mapping)}
    corresponding = next((p for p in people or [] if isinstance(p, Mapping) and p.get("corresponding")), None)
    lines = []
    if demo_note:
        lines += [f"> {demo_note}", ""]
    lines += ["Dear Editor,", "",
              f"We submit our manuscript, \"{metadata.get('title')}\", for consideration"
              + (f" as {_article(str(article).split('(')[0].strip())}" if article else "") + f" in {journal}.", ""]
    for name in spec["cover_letter"]["paragraphs"]:
        lines += [paragraphs[name].strip(), ""]
    competing = _registry_declarations(metadata).get("competing_interests")
    statements = [STATEMENTS[s] for s in spec["cover_letter"]["statements"] if STATEMENTS.get(s)]
    if competing and "reviewers_in_system" in spec["cover_letter"]["statements"]:
        statements.append(competing if competing.endswith(".") else competing + ".")
    lines += [" ".join(statements), ""]
    if "reviewers_in_letter" in spec["cover_letter"]["statements"] and reviewers:
        lines += ["Suggested reviewers (names and the cited work that identifies them; contact details are "
                  "given in the submission system):", ""]
        lines += [f"- {r['name']} — {r['evidence']['link']}" for r in reviewers]
        lines += [""]
    lines += ["Sincerely,", ""]
    if corresponding:
        units = "; ".join(affiliations.get(str(i), "") for i in corresponding.get("affiliation_ids") or [])
        lines += [str(corresponding.get("name")), units,
                  str(corresponding.get("email") or "").strip() or "[e-mail]"]
    else:
        lines += ["[Corresponding author]"]
    return "\n".join(lines).rstrip() + "\n"


def _article(kind: str) -> str:
    return ("an " if kind[:1].lower() in "aeiou" else "a ") + kind


def prepare(paper_id: str, *, root: str | Path, runner: Callable[..., Any] | None = None,
            profile: str | None = None, output: str | Path | None = None, demo_note: str | None = None,
            skip_draft: bool = False, skip_verify: bool = False, timeout: int = 1800,
            metadata_overrides: Mapping[str, Any] | None = None, recompose: bool = False) -> dict[str, Any]:
    """Verify the flattened LaTeX and draft the cover letter + reviewers for the current version.

    Writes ``papers/<id>/submission/`` (or ``output``): ``flatten-verification.json``,
    ``cover-letter.md``, ``suggested-reviewers.json`` and ``draft-receipt.json``.  A failed draft
    or compile still writes its receipt (status ``failed``), so the release pipeline does not
    retry it every tick; the package then carries a template and a note instead.
    """
    from paper_writing.registry import load_paper_metadata

    repo = Path(root).resolve()
    metadata = {**load_paper_metadata(paper_id, repo), **dict(metadata_overrides or {})}
    version = str(metadata.get("version") or "1.0.0")
    out = Path(output) if output else drafts_dir(repo, paper_id)
    out.mkdir(parents=True, exist_ok=True)
    manuscript, _, supplement = _manuscript_paths(paper_id, metadata, repo)
    result: dict[str, Any] = {"paper_id": paper_id, "version": version, "output": str(out)}

    if not skip_verify:
        verification: dict[str, Any] = {"schema_version": flatten_tex.SCHEMA, "version": version,
                                        "verified_at": _now()}
        try:
            current = flatten_tex.flatten(manuscript).report["main_sha256"]
            verification["attempted_sha256"] = current
            main = flatten_tex.verify(manuscript)
            main["main_sha256"] = current
            verification["main"] = {k: main[k] for k in ("main_sha256", "equivalent", "pages", "differing_pages",
                                                          "engine", "files", "first_difference") if k in main}
            if supplement is not None and supplement.with_suffix(".tex").is_file():
                name = supplement.with_suffix(".tex").name
                supplement_check = flatten_tex.verify(manuscript, name)
                supplement_check["main_sha256"] = flatten_tex.flatten(manuscript, name).report["main_sha256"]
                verification["supplement"] = {k: supplement_check[k] for k in (
                    "main_sha256", "equivalent", "pages", "differing_pages", "engine") if k in supplement_check}
            verification["status"] = "verified" if main["equivalent"] else "not_equivalent"
        except (flatten_tex.FlattenError, OSError, subprocess.SubprocessError) as exc:
            verification["status"] = "failed"
            verification["error"] = str(exc)[:1500]
        (out / "flatten-verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["flatten"] = {"status": verification["status"],
                             "pages": (verification.get("main") or {}).get("pages"),
                             "error": verification.get("error")}

    if recompose:
        result["draft"] = _recompose(paper_id, repo, metadata, out, profile=profile, demo_note=demo_note)
    elif not skip_draft:
        result["draft"] = _draft(paper_id, repo, metadata, out, runner=runner, profile=profile,
                                 demo_note=demo_note, timeout=timeout)
    return result


def _recompose(paper_id: str, repo: Path, metadata: Mapping[str, Any], out: Path, *, profile,
               demo_note) -> dict[str, Any]:
    """Rebuild cover-letter.md from the receipt's paragraphs (no model): registry byline changed."""
    receipt = _read_json(out / "draft-receipt.json") or {}
    paragraphs = receipt.get("paragraphs")
    if receipt.get("status") != "drafted" or not isinstance(paragraphs, Mapping):
        return {"status": "nothing_to_recompose"}
    _, spec = select_profile(metadata, repo, profile)
    reviewers = (_read_json(out / "suggested-reviewers.json") or {}).get("suggested") or []
    letter = compose_letter(metadata, spec, paragraphs, reviewers, demo_note=demo_note)
    (out / "cover-letter.md").write_text(letter, encoding="utf-8")
    receipt["cover_letter_sha256"] = hashlib.sha256(letter.encode()).hexdigest()
    receipt["recomposed_at"] = _now()
    (out / "draft-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    return {"status": "recomposed"}


def _pdf_text(pdf: Path) -> str:
    try:
        completed = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True,
                                   errors="replace", timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _draft(paper_id: str, repo: Path, metadata: Mapping[str, Any], out: Path, *, runner, profile, demo_note,
           timeout: int) -> dict[str, Any]:
    from paper_writing.review_launcher import LaunchError, run_role

    runner = runner or run_role
    version = str(metadata.get("version") or "1.0.0")
    manuscript, pdf, _ = _manuscript_paths(paper_id, metadata, repo)
    profile_id, spec = select_profile(metadata, repo, profile)
    flat = flatten_tex.flatten(manuscript)
    source = flat.main_tex
    bib = parse_bib(flat.bib or "")
    cited = _cited_keys("\n".join(flatten_tex._code_part(line)[0] for line in source.split("\n")))
    people = _people(metadata)
    authors = [str(p.get("name")) for p in people or [] if isinstance(p, Mapping) and p.get("name")]
    affiliations = [str(a.get("name") or "") for a in metadata.get("affiliations") or [] if isinstance(a, Mapping)]
    article = metadata.get("article_type") or (metadata.get("target_journal_format") or {}).get("article_type")
    prompt = DRAFT_TASK.format(
        journal=metadata.get("target_journal") or "the journal",
        audience=spec["cover_letter"]["audience"],
        article_type=f", article type: {article}" if article else "",
        avoid=spec["cover_letter"].get("avoid") or "",
        authors=", ".join(authors) or "none registered",
        bibliography=_bibliography_listing(bib, cited) or "(no bibliography)",
        manuscript=source[:180_000])
    # The role's prompt and raw output are process files: they stay in a scratch directory and
    # only the receipt (model, checks, hashes) is kept with the paper.
    scratch = tempfile.TemporaryDirectory(prefix=f"submission-draft-{paper_id}-")
    run_dir = Path(scratch.name)
    receipt: dict[str, Any] = {"schema_version": DRAFT_SCHEMA, "paper_id": paper_id, "version": version,
                               "profile": profile_id, "target_journal": metadata.get("target_journal"),
                               "drafted_at": _now(), "status": "failed"}
    manuscript_text = latex_to_text(source) + "\n" + _pdf_text(pdf)
    payload = None
    errors: list[str] = []
    feedback = ""
    try:
        for role_name, role in drafter_roles(repo):
            for attempt in (1, 2):
                try:
                    candidate, _launch = runner(
                        role_name=f"submission_drafter_{role_name}_{attempt}", role=role,
                        system_prompt=DRAFT_SYSTEM, user_prompt=prompt + feedback,
                        schema=DRAFT_SCHEMA_JSON, workdir=run_dir / f"{role_name}-{attempt}",
                        timeout=timeout)
                except (LaunchError, OSError, ValueError) as exc:
                    errors.append(f"{role_name}: {str(exc)[:300]}")
                    break
                letter_text = " ".join(candidate[k] for k in ("significance", "novelty", "fit"))
                mismatches = number_mismatches(letter_text, manuscript_text)
                payload = candidate
                receipt.update({"model": role.get("model"), "provider": role.get("provider"),
                                "attempts": attempt, "number_mismatches": mismatches})
                if not mismatches:
                    break
                feedback = ("\n\n# Correction\nThese numbers in your paragraphs do not occur in the "
                            "manuscript: " + ", ".join(mismatches) + ". Rewrite the paragraphs using only "
                            "numbers the manuscript states exactly, or no number.\n")
            if payload is not None:
                break
    finally:
        scratch.cleanup()
    if payload is None:
        receipt["errors"] = errors
        (out / "draft-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
        return {"status": "failed", "errors": errors}
    kept, dropped = verify_reviewers(payload.get("suggested_reviewers") or [], bib=bib, cited=cited,
                                     authors=authors, affiliations=affiliations)
    letter = compose_letter(metadata, spec, payload, kept, demo_note=demo_note)
    (out / "cover-letter.md").write_text(letter, encoding="utf-8")
    (out / "suggested-reviewers.json").write_text(json.dumps(
        {"schema_version": DRAFT_SCHEMA, "version": version, "suggested": kept, "dropped": dropped,
         "rule": "cited, DOI/URL-identified work lists the nominee; no co-authorship with this paper's authors"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt.update({"status": "drafted", "reviewers_kept": len(kept), "reviewers_dropped": len(dropped),
                    "paragraphs": {k: payload[k] for k in ("significance", "novelty", "fit")},
                    "cover_letter_sha256": hashlib.sha256(letter.encode()).hexdigest()})
    (out / "draft-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    return {"status": "drafted", "model": receipt.get("model"), "number_mismatches": receipt["number_mismatches"],
            "reviewers_kept": len(kept), "reviewers_dropped": len(dropped)}


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    import argparse

    from paper_writing.registry import load_paper_metadata

    parser = argparse.ArgumentParser(prog="paper-writing submission")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("build", "prepare", "status"):
        command = sub.add_parser(name)
        command.add_argument("--paper-id", required=True)
        command.add_argument("--root", required=True)
        command.add_argument("--json", action="store_true", help="accepted for the pipeline; output is JSON")
        if name in {"build", "prepare"}:
            command.add_argument("--profile", help="override the journal profile (e.g. nature_communications)")
            command.add_argument("--output", help="write here instead of papers/<id>/submission/ (prepare) "
                                                  "or a temporary directory (build)")
            command.add_argument("--demo-note", help="banner for a format demonstration (not for submission)")
            command.add_argument("--target-journal", help="with --demo-note: the journal of the demonstration "
                                                          "(the registry is not changed)")
        if name == "build":
            command.add_argument("--drafts", help="read cover letter/reviewers from this directory")
        if name == "prepare":
            command.add_argument("--skip-draft", action="store_true")
            command.add_argument("--skip-verify", action="store_true")
            command.add_argument("--recompose", action="store_true",
                                 help="rebuild the letter from the drafted paragraphs (no model call)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    overrides: dict[str, Any] = {}
    try:
        if getattr(args, "target_journal", None):
            if not args.demo_note or not args.output:
                raise SubmissionBundleError("--target-journal is for demonstrations only "
                                            "(needs --demo-note and --output)")
            overrides["target_journal"] = args.target_journal
            # The registered article type and format belong to the real target journal.
            demo_profile = load_profiles()["profiles"].get(args.profile or "", {})
            overrides["article_type"] = demo_profile.get("article_type") or "Article"
            overrides["target_journal_format"] = {}
        if args.action == "status":
            payload = materials_status(args.paper_id, root=root)
        elif args.action == "prepare":
            payload = prepare(args.paper_id, root=root, profile=args.profile, output=args.output,
                              demo_note=args.demo_note, skip_draft=args.skip_draft,
                              skip_verify=args.skip_verify, metadata_overrides=overrides,
                              recompose=args.recompose)
        else:
            metadata = {**load_paper_metadata(args.paper_id, root), **overrides}
            output = Path(args.output) if args.output else Path(tempfile.mkdtemp(prefix="submission-package-"))
            archive, manifest = build(args.paper_id, root=root, metadata=metadata, output=output,
                                      profile=args.profile, demo_note=args.demo_note, drafts=args.drafts)
            payload = {"archive": str(archive), "directory": str(output / "submission-package"),
                       "sha256": _sha(archive), "size": archive.stat().st_size,
                       "profile": manifest["profile"], "missing_required": manifest["missing_required"],
                       "notes": manifest["notes"]}
    except (SubmissionBundleError, flatten_tex.FlattenError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
