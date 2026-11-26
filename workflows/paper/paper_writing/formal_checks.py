"""Mandatory bibliographic accuracy and core mathematical verification.

Coverage and evidence integrity are checked by code. Scientific judgments are
made in fresh verifier processes and checked again by the ordinary referee.
This is not a claim that an entire manuscript has been machine proved.
"""
from __future__ import annotations

import difflib
import hashlib
import html
import json
import os
import re
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, unquote, urlsplit
import xml.etree.ElementTree as ET

import httpx

from paper_writing import materiality
from paper_writing.review_launcher import FORMAL_PROVIDERS, LaunchError, _validate_against_schema

VERSION = "openlabs.formal_check.v2"
PROMPT = Path(__file__).resolve().parents[1] / "skills/openlabs-paper-review/references/unified/formal.md"
MAX_DOWNLOAD = 20_000_000
MAX_PACKET = 600_000
BATCH_SIZE = 16
STATUSES = ["verified", "error", "gap", "unchecked"]
TEXT = {"type": "string"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


# Explicit policy version of the mandatory reference/core verification. Increment
# it by hand when a change must invalidate earlier passing checks (for example a
# stricter verification rule). Ordinary code, launcher or prompt edits no longer
# invalidate every passed manuscript, as the former file-hash policy did.
POLICY_VERSION = 1
# The file-hash policy used before POLICY_VERSION existed; such records are
# treated as POLICY_VERSION 1 and expire when the version is incremented.
_LEGACY_POLICY_KEYS = frozenset({"schema", "mandatory", "implementation_sha256", "launcher_sha256",
                                 "prompt_sha256", "schema_sha256"})
_LEGACY_EQUIVALENT_VERSION = 1


def policy() -> dict[str, Any]:
    return {"schema": VERSION, "mandatory": True, "policy_version": POLICY_VERSION}


def policy_accepted(recorded: Any) -> bool:
    """The current policy, or the legacy file-hash policy while it is still equivalent."""
    if recorded == policy():
        return True
    return (POLICY_VERSION == _LEGACY_EQUIVALENT_VERSION and isinstance(recorded, Mapping)
            and set(recorded) == _LEGACY_POLICY_KEYS and recorded.get("schema") == VERSION
            and recorded.get("mandatory") is True)


def recorded_policy(binding: Any, root: Path) -> dict[str, Any] | None:
    """The policy stored in a bound formal report, without validating anything else."""
    try:
        result = json.loads(_safe_file(root, binding["path"]).read_text())
        value = result["policy"]
    except (KeyError, TypeError, ValueError, OSError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def object_schema(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(fields), "properties": dict(fields)}


def array(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


EVIDENCE = array(object_schema({"source_id": TEXT, "locator": TEXT,
    "quote": TEXT}))
STATUS = {"type": "string", "enum": STATUSES}
REFERENCE_SCHEMA = object_schema({"key": TEXT, "status": STATUS,
    "authors_check": TEXT, "title_check": TEXT, "year_check": TEXT,
    "venue_identifier_locator_check": TEXT, "primary_source_check": TEXT,
    "publication_status_check": TEXT, "evidence": EVIDENCE})
FORMULA_SCHEMA = object_schema({"formula_id": TEXT, "status": STATUS,
    "assumptions": TEXT, "derivation_or_source_check": TEXT, "evidence": EVIDENCE})
CITATION_SCHEMA = object_schema({"citation_id": TEXT, "key": TEXT, "status": STATUS,
    "mathematical_support": {"type": "boolean"}, "scope_rationale": TEXT,
    "manuscript_claim": TEXT, "support_check": TEXT, "evidence": EVIDENCE})
PREREQUISITE_SCHEMA = object_schema({"statement": TEXT, "status": STATUS,
    "kind": {"type": "string", "enum": ["external", "internal_derivation"]},
    "reference_keys": array(TEXT), "original_locator": TEXT, "original_assumptions": TEXT,
    "original_conclusion": TEXT, "manuscript_instantiation": TEXT,
    "condition_check": TEXT, "formula_check": TEXT, "evidence": EVIDENCE})
PASSAGE_SCHEMA = object_schema({"passage_id": TEXT, "status": STATUS,
    "coverage_rationale": TEXT, "prerequisites": array(PREREQUISITE_SCHEMA),
    "formulas": array(FORMULA_SCHEMA), "citations": array(CITATION_SCHEMA)})
REPORT_SCHEMA = object_schema({"references": array(REFERENCE_SCHEMA), "passages": array(PASSAGE_SCHEMA)})


def _nonmathematical_unchecked_citation(row: Mapping[str, Any]) -> bool:
    """Retain an independent out-of-scope assessment without claiming verification."""
    return (isinstance(row.get("citation_id"), str)
            and row.get("status") == "unchecked"
            and row.get("mathematical_support") is False
            and all(isinstance(row.get(key), str) and row[key].strip()
                    for key in ("scope_rationale", "manuscript_claim", "support_check")))


def _strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", text)


def _braced(text: str, start: int, opening: str = "{", closing: str = "}") -> tuple[str, int]:
    if start >= len(text) or text[start] != opening:
        raise ValueError("Expected a balanced LaTeX argument")
    depth = 1
    for i in range(start + 1, len(text)):
        if i and text[i - 1] == "\\":
            continue
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if not depth:
                return text[start + 1:i], i + 1
    raise ValueError("Unbalanced LaTeX argument")


def bibliography_entries(text: str) -> list[dict[str, str]]:
    """Parse the bibliography actually printed, never unused .bib records."""
    text = _strip_comments(text)
    starts = []
    for match in re.finditer(r"\\(?:bibitem|entry)\b\s*", text):
        pos = match.end()
        if pos < len(text) and text[pos] == "[":
            _, pos = _braced(text, pos, "[", "]")
            while pos < len(text) and text[pos].isspace():
                pos += 1
        key, end = _braced(text, pos)
        if not key.strip() or re.search(r"[\s{},\\]", key):
            raise ValueError("Dynamic or malformed bibliography key")
        starts.append((match.start(), end, key))
    rows = []
    for i, (start, _, key) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        raw = re.split(r"\\end\{(?:thebibliography|refsection)\}", text[start:end], maxsplit=1)[0]
        rows.append({"key": key, "text": raw.strip()})
    if len({r["key"] for r in rows}) != len(rows):
        raise ValueError("Duplicate bibliography keys")
    if text.strip() and not rows:
        raise ValueError("No printed bibliography entries could be parsed; a fresh BBL or inline bibliography is required")
    return rows


_CITE = re.compile(r"\\([A-Za-z]*[Cc]ite[A-Za-z]*|nocite)\*?\s*(?:\[[^\]]*\]\s*)*\{")
_MATH = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$(?!\$).*?(?<!\\)\$"
                   r"|\\\[.*?\\\]|\\\(.*?\\\)"
                   r"|\\begin\{(equation\*?|align\*?|alignat\*?|gather\*?|multline\*?|displaymath|math|eqnarray\*?)\}.*?\\end\{\1\}", re.S)


def inventory(documents: list[dict[str, str]], bibliography: str) -> dict[str, Any]:
    references = bibliography_entries(bibliography)
    keys = {r["key"] for r in references}
    passages = []
    for document in documents:
        text = _strip_comments(document["text"])
        # Bibliographic prose is audited separately. Keep definitions/preamble
        # and every remaining source passage, including uncited dependencies.
        text = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", text, flags=re.S)
        for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\s*\Z)", text, re.S):
            raw = match.group()
            pid = f"{document['id']}:L{text[:match.start()].count(chr(10)) + 1}:{sha(raw.encode())[:12]}"
            citations = []
            for j, cite in enumerate(_CITE.finditer(raw)):
                if cite.group(1).lower().endswith("cites"):
                    raise ValueError(f"Multiple-argument citation commands require explicit separate citations at {pid}")
                names, _ = _braced(raw, cite.end() - 1)
                for key in names.split(","):
                    key = key.strip()
                    if cite.group(1) == "nocite" and key == "*":
                        continue
                    if key not in keys:
                        raise ValueError(f"Undefined or unsupported citation key {key!r} at {pid}")
                    if cite.group(1) != "nocite":
                        citations.append({"id": f"{pid}:C{j}:{key}", "key": key, "text": cite.group() + names + "}"})
            formulas = [{"id": f"{pid}:F{i}", "text": m.group()} for i, m in enumerate(_MATH.finditer(raw))]
            for match_math in re.finditer(r"\\ensuremath\s*\{", raw):
                value, _ = _braced(raw, match_math.end() - 1)
                formulas.append({"id": f"{pid}:F{len(formulas)}", "text": "\\ensuremath{" + value + "}"})
            passages.append({"id": pid, "document": document["id"], "text": raw,
                             "formulas": formulas, "citations": citations})
    if not passages:
        raise ValueError("The manuscript has no auditable source passages")
    return {"references": references, "passages": passages,
            "documents_sha256": digest(documents), "bibliography_sha256": sha(bibliography.encode())}


def verification_inventory(documents: list[dict[str, str]], bibliography: str) -> dict[str, Any]:
    """All printed references, but only mathematical statements and derivations.

    Selection is deterministic, never an author-controlled exemption. Entire
    theorem/definition/proof environments and displayed mathematics are retained;
    isolated inline variable names, preamble and ordinary prose are not tasks.
    Full documents remain available to the scientific referee and verifier.
    """
    full = inventory(documents, bibliography)
    selected = []
    relation = re.compile(r"[=<>/^]|\\(?:leq?|geq?|neq|equiv|sim|approx|rightarrow|to|mapsto|coloneqq|sum|prod|int|[dt]?frac|binom|sqrt|lim|Theta|Omega)\b")
    def display(text: str) -> bool:
        return text.startswith(('$$', r'\[', r'\begin{'))
    for document in documents:
        text = _strip_comments(document['text'])
        text = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", text, flags=re.S)
        envs = {'theorem', 'lemma', 'proposition', 'corollary', 'definition', 'proof', 'conjecture'}
        envs.update(re.findall(r"\\newtheorem\*?\s*\{([^}]+)\}", text))
        spans, stack = [], []
        for token in re.finditer(r"\\(begin|end)\{([^}]+)\}", text):
            name = token.group(2).rstrip('*')
            if name not in envs:
                continue
            if token.group(1) == 'begin':
                stack.append((name, token.start()))
            else:
                for i in range(len(stack)-1, -1, -1):
                    if stack[i][0] == name:
                        _, start = stack.pop(i); spans.append((start, token.end())); break
        # An unmatched theorem/proof is still included, not silently skipped.
        spans.extend((start, len(text)) for _, start in stack)
        begin = re.search(r"\\begin\{document\}", text)
        body_start = begin.end() if begin else 0
        end = re.search(r"\\end\{document\}", text)
        body_end = end.start() if end else len(text)
        cursor = 0
        for passage in (p for p in full['passages'] if p['document'] == document['id']):
            start = text.find(passage['text'], cursor)
            if start < 0:
                raise ValueError('Cannot locate a mathematical scope candidate')
            stop = start + len(passage['text']); cursor = stop
            if stop <= body_start or start >= body_end:
                continue
            in_statement = any(a < stop and start < b for a, b in spans)
            formulas = [f for f in passage['formulas'] if display(f['text']) or relation.search(f['text'])]
            if in_statement or formulas:
                selected.append(dict(passage, formulas=formulas))
    return dict(full, passages=selected, scope={
        'name': 'all_references_and_core_mathematics',
        'full_passage_count': len(full['passages']),
        'core_passage_count': len(selected),
        'full_formula_count': sum(len(p['formulas']) for p in full['passages']),
        'core_formula_count': sum(len(p['formulas']) for p in selected),
        'excluded_passage_ids': [p['id'] for p in full['passages'] if p['id'] not in {q['id'] for q in selected}],
        'ordinary_prose_empirical_and_author_facts_reviewed_by': 'scientific_referee',
    })


def verification_source_metadata(metadata: Mapping[str, Any], inv: Mapping[str, Any]) -> dict[str, Any]:
    """Bibliographic catalogs, not the previous all-evidence replay campaign."""
    refs = {r['key']: r['text'] for r in inv['references']}
    plan = source_plan(metadata)
    sources = [s for s in plan.get('sources', []) if s['kind'] == 'publisher_catalog' or any(
        not re.search(r'10\.\d{4,9}/|arxiv', refs.get(key, ''), re.I) for key in s['reference_keys'])]
    if inv.get("followup"):
        keys = set(inv["task_reference_keys"]) | {c["key"] for p in inv["passages"] for c in p["citations"]}
        sources = [dict(source, reference_keys=[key for key in source["reference_keys"] if key in keys])
                   for source in sources if set(source["reference_keys"]) & keys]
    sources = [{k: v for k, v in s.items() if k != 'passage_patterns'} for s in sources]
    return dict(metadata, formal_check={'sources': sources, 'local_evidence': []})


def current_inputs(metadata: Mapping[str, Any], root: Path) -> tuple[list[dict[str, str]], str]:
    if not metadata.get("paper_id"):
        raise ValueError("Formal verification requires the exact registered paper ID")
    manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{metadata['paper_id']}/manuscript")
    def expand(path: Path, stack: tuple[Path, ...] = ()) -> str:
        path = (path if path.suffix else path.with_suffix(".tex")).resolve()
        if not path.is_file():
            raise ValueError(f"Required manuscript source is missing: {path}")
        if path in stack:
            raise ValueError(f"Recursive manuscript source: {path}")
        text = _strip_comments(path.read_text(errors="strict"))
        pattern = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
        def include(match):
            name = match.group(1).strip()
            if not name or any(c in name for c in "\\#{}"):
                raise ValueError("Dynamic manuscript input cannot be audited")
            return expand(manuscript / name, (*stack, path))
        text = pattern.sub(include, text)
        if re.search(r"\\(?:input|include)\b", text):
            raise ValueError("Unsupported manuscript input syntax")
        return text

    documents = [{"id": "main", "text": expand(manuscript / "main.tex")}]
    supplement = metadata.get("latest_supplementary_pdf")
    path = (root / str(supplement)).with_suffix(".tex") if supplement else manuscript / "supplementary.tex"
    if supplement and not path.is_file():
        raise ValueError("Registered supplementary source is missing")
    if path.is_file():
        documents.append({"id": "supplement", "text": expand(path)})
    references = {}
    for document, source_path in zip(documents, [manuscript / "main.tex", path]):
        inline = re.findall(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", document["text"], re.S)
        bbl = source_path.with_suffix(".bbl")
        text = "\n\n".join(inline) if inline else (bbl.read_text(errors="strict") if bbl.is_file() else "")
        if not text and re.search(r"\\(?:bibliography|printbibliography)\b", document["text"]):
            raise ValueError(f"Printed bibliography is missing for {document['id']}")
        for row in bibliography_entries(text):
            if row["key"] in references:
                # BibTeX assigns author-year display suffixes separately for
                # each document's cited subset (e.g. n.d.a versus n.d.d).
                # They are not part of the reference identity. Keep the first
                # printed entry for auditing, and still reject content changes.
                def identity(value: str) -> str:
                    return " ".join(re.sub(r"\\natexlab\{[a-z]+\}", "", value).split())
                if identity(references[row["key"]]["text"]) != identity(row["text"]):
                    raise ValueError(f"Conflicting bibliography key across manuscript documents: {row['key']}")
                continue
            references[row["key"]] = row
    return documents, "\n\n".join(row["text"] for row in references.values())


def _url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("Formal evidence requires an HTTPS source URL without credentials or fragments")
    return url


def _normalized_url(url: str) -> str:
    """Scheme/host case and default port do not change the record a URL names."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port != 443 else ""
    return f"{parts.scheme.lower()}://{host}{port}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")


def _text_document(body: bytes, content_type: str, directory: Path, sid: str,
                   pages: list[int] | None = None, method: str = "text") -> str:
    if body.startswith(b"%PDF-") or "application/pdf" in content_type:
        pdf, text = directory / (sid + ".pdf"), directory / (sid + ".txt")
        pdf.write_bytes(body)
        if method == "ocr":
            if not pages or pages[1] - pages[0] >= 30:
                raise ValueError("OCR requires an explicit range of at most 30 original PDF pages")
            ocr = directory / (sid + "-ocr")
            ocr.mkdir(exist_ok=False)
            subprocess.run(["pdftoppm", "-f", str(pages[0]), "-l", str(pages[1]), "-r", "180", "-png",
                            str(pdf), str(ocr / "page")], check=True, capture_output=True, timeout=180)
            images = sorted(ocr.glob("page-*.png"))
            if len(images) != pages[1] - pages[0] + 1:
                raise ValueError("OCR rendered a different original page range")
            output = []
            for page in images:
                result = subprocess.run(["tesseract", str(page), "stdout", "-l", "eng"],
                                        check=True, capture_output=True, timeout=120)
                output.append(f"\n[Original PDF page {int(page.stem.split('-')[-1])}; OCR transcription]\n"
                              + result.stdout.decode("utf-8", errors="strict"))
            return "\n".join(output)
        # Reading order, not -layout: -layout interleaves the lines of multi-column
        # pages, so a sentence the verifier reads and quotes verbatim would not be
        # contiguous in the bound text and the verbatim-quote check would fail.
        command = ["pdftotext"]
        if pages:
            command += ["-f", str(pages[0]), "-l", str(pages[1])]
        subprocess.run([*command, str(pdf), str(text)], check=True,
                       capture_output=True, timeout=60)
        return text.read_text(errors="replace")
    if pages:
        raise ValueError("PDF page selection requires an actual PDF")
    if method != "text":
        raise ValueError("OCR requires an actual PDF")
    text = body.decode("utf-8", errors="replace")
    if "html" in content_type:
        text = re.sub(r"<(script|style)\b.*?</\1>", "", text, flags=re.S | re.I)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return text


def source_plan(metadata: Mapping[str, Any]) -> dict[str, Any]:
    value = metadata.get("formal_check", {})
    if not isinstance(value, Mapping) or set(value) - {"sources", "local_evidence"}:
        raise ValueError("formal_check accepts only source/evidence lists; the mandatory gate cannot be disabled")
    sources = value.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("formal_check.sources must be a list")
    for source in sources:
        if (not isinstance(source, Mapping) or set(source) - {"reference_keys", "url", "kind", "pages", "passage_patterns", "extraction_method", "transcript"}
                or not {"reference_keys", "url", "kind"} <= set(source)
                or source["kind"] not in {"primary_text", "publisher_catalog"}
                or not isinstance(source["reference_keys"], list)
                or not source["reference_keys"] or any(not isinstance(k, str) or not k for k in source["reference_keys"])):
            raise ValueError("Invalid primary-source declaration")
        _url(source["url"])
        if "pages" in source and (not isinstance(source["pages"], list) or len(source["pages"]) != 2
                or any(type(p) is not int for p in source["pages"])
                or source["pages"][0] < 1 or source["pages"][1] < source["pages"][0]):
            raise ValueError("pages must be inclusive PDF page numbers [first, last]")
        _patterns(source)
        if source.get("extraction_method", "text") not in {"text", "ocr", "ocr_transcript"}:
            raise ValueError("Unknown primary document extraction method")
        if ("transcript" in source) != (source.get("extraction_method") == "ocr_transcript"):
            raise ValueError("A transcript is declared only with extraction_method ocr_transcript")
        if source.get("extraction_method") == "ocr_transcript":
            # A registered OCR transcription of a scanned original PDF: the original
            # is still retrieved and must match original_sha256; the transcript is a
            # hash-bound file whose first line declares it an OCR transcription.
            t = source["transcript"]
            if (source["kind"] != "primary_text" or not source.get("pages")
                    or source["pages"][1] - source["pages"][0] >= 30
                    or not isinstance(t, Mapping)
                    or set(t) != {"path", "sha256", "original_sha256", "tool", "tool_version"}
                    or not isinstance(t["path"], str) or not t["path"].startswith(f"papers/{metadata.get('paper_id')}/")
                    or any(not isinstance(t[k], str) or not re.fullmatch(r"[0-9a-f]{64}", t[k])
                           for k in ("sha256", "original_sha256"))
                    or any(not isinstance(t[k], str) or not t[k].strip() for k in ("tool", "tool_version"))):
                raise ValueError("Invalid OCR transcript declaration")
        if source.get("extraction_method") == "ocr" and (not source.get("pages") or source["pages"][1] - source["pages"][0] >= 30):
            raise ValueError("OCR requires an explicit range of at most 30 original PDF pages")
    local = value.get("local_evidence", [])
    if not isinstance(local, list):
        raise ValueError("formal_check.local_evidence must be a list")
    for item in local:
        if (not isinstance(item, Mapping) or set(item) - {"path", "sha256", "kind", "passage_patterns", "reference_keys"}
                or not {"path", "sha256", "kind", "passage_patterns"} <= set(item)
                or item["kind"] not in {"manuscript_code", "execution_record", "author_attestation", "research_record"}
                or not isinstance(item["path"], str) or not item["path"].startswith(f"papers/{metadata.get('paper_id')}/")
                or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                or not isinstance(item.get("reference_keys", []), list)
                or any(not isinstance(k, str) or not k for k in item.get("reference_keys", []))):
            raise ValueError("Invalid local evidence declaration")
        _patterns(item, required=True)
    return dict(value)


def _patterns(item: Mapping[str, Any], *, required: bool = False) -> None:
    patterns = item.get("passage_patterns", [])
    if (not isinstance(patterns, list) or (required and not patterns)
            or any(not isinstance(p, str) or not p.strip() or len(p) > 500 for p in patterns)):
        raise ValueError("passage_patterns must contain nonempty literal source substrings")


def _whitespace(text: str) -> str:
    """Only whitespace is equivalent: retain case, symbols and hyphenation."""
    return " ".join(text.split())


def _json_string_values(text: str) -> list[str]:
    """Decoded string values of a JSON record (e.g. Crossref ``message.abstract``).

    Quotes are written from the decoded record, so ``QT\\/RR`` or ``\\u2005`` JSON
    escapes in the raw body must not defeat an exact quote. Each value is matched
    on its own (no cross-field joining); the raw text and its hashes are unchanged.
    """
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return []
    out, stack = [], [value]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


_XML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s+[^<>]*)?/?>")
_INLINE_MATH = re.compile(r"(?<!\\)\$([^$\n]+?)(?<!\\)\$")
_LINEBREAK_HYPHEN = re.compile(r"([A-Za-z])-\r?\n[ \t]*([a-z])")
_LIGATURES = str.maketrans({
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\u2010": "-", "\u2011": "-", "\u00ad": "",
})


def _xml_element_texts(text: str) -> list[str]:
    """Decoded text of leaf XML elements (e.g. arXiv Atom ``<summary>`` or ``<title>``),
    never joining across sibling fields."""
    stripped = text.lstrip()
    if not stripped.startswith("<"):
        return []
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError:
        return []
    return [elem.text for elem in root.iter() if not len(elem) and elem.text and elem.text.strip()]


def _plain_markup(text: str) -> str:
    """Decode HTML/XML entities and strip XML/JATS inline tags (e.g. Crossref ``<jats:italic>``),
    collapsing pretty-print whitespace introduced around tags next to punctuation."""
    decoded = html.unescape(html.unescape(text))
    if _XML_TAG.search(decoded):
        decoded = re.sub(r"([(\[])\s+<[A-Za-z][A-Za-z0-9:_-]*(?:\s+[^<>]*)?>", r"\1", decoded)
        decoded = re.sub(r"</[A-Za-z][A-Za-z0-9:_-]*>\s+([,.;:?!)\]])", r"\1", decoded)
        decoded = _XML_TAG.sub(" ", decoded)
    return decoded


def _quote_norm(text: str, *, strip_math: bool = False) -> str:
    """Normalize PDF line-break hyphens, ligatures, Unicode hyphens and whitespace.

    Retains case, intra-line hyphenation and wording. With ``strip_math`` also unwraps
    inline single-dollar TeX delimiters (e.g. arXiv ``$n$-site`` -> ``n-site``).
    """
    text = _LINEBREAK_HYPHEN.sub(r"\1\2", text).translate(_LIGATURES)
    if strip_math:
        text = _INLINE_MATH.sub(r"\1", text)
    return _whitespace(text)


def _quote_present(quote: str, text: str) -> bool:
    needle = _whitespace(quote)
    if needle in _whitespace(text):
        return True
    # Check each JSON string value or XML leaf element on its own (no cross-field joining).
    # Inline markup stripping (e.g. Crossref JATS tags) runs only inside individual field values
    # when the source is a structured JSON/XML envelope, never across the whole envelope.
    field_vals = _json_string_values(text) or _xml_element_texts(text)
    norm_candidates = [text, *field_vals]
    markup_candidates = field_vals if field_vals else [text]
    for strip_math in (False, True):
        q_norm = _quote_norm(quote, strip_math=strip_math)
        q_plain = _quote_norm(_plain_markup(quote), strip_math=strip_math)
        for cand in norm_candidates:
            if q_norm in _quote_norm(cand, strip_math=strip_math):
                return True
        for cand in markup_candidates:
            if ("<" in cand or "&" in cand) and q_plain in _quote_norm(_plain_markup(cand), strip_math=strip_math):
                return True
    return False


# Route findings that no verification or delivery path consumes any more. Since the
# formal gate was narrowed to bibliography and core mathematics (2026-10-12),
# ``verification_source_metadata`` strips ``passage_patterns`` and drops
# ``local_evidence`` before ``run_checks``/``validate_binding``; a stale selector
# or a changed local evidence file therefore binds nothing. They are reported as
# preparation advisories (review) and delivery notes (handoff), never blockers.
# An absent bibliography key still blocks: a declared source routed to a key the
# manuscript does not print stops the reference verification.
ADVISORY_ROUTE_KINDS = frozenset({"stale_selector", "local_evidence_file"})


def route_findings(metadata: Mapping[str, Any], inv: Mapping[str, Any], root: Path) -> list[dict[str, str]]:
    """Declared-route problems as {kind, route, message[, selector]}; see ADVISORY_ROUTE_KINDS."""
    findings = []
    plan = source_plan(metadata)
    keys = {r['key'] for r in inv['references']}
    for item in plan.get('sources', []) + plan.get('local_evidence', []):
        label = item.get('path') or item.get('url')
        if set(item.get('reference_keys', [])) - keys:
            findings.append({'kind': 'absent_key', 'route': label,
                             'message': f"Source routing: {label}: absent bibliography key"})
        for pattern in item.get('passage_patterns', []):
            if not any(pattern in p['text'] for p in inv['passages']):
                findings.append({'kind': 'stale_selector', 'route': label, 'selector': pattern,
                                 'message': f"Source routing: {label}: selector matches no current passage: {pattern}"})
    for item in plan.get('local_evidence', []):
        try:
            body = _safe_file(root, item['path']).read_bytes()
            if sha(body) != item['sha256'] or len(body) > MAX_DOWNLOAD:
                raise ValueError('hash mismatch or size limit exceeded')
            text = body.decode('utf-8', errors='strict')
            if not text.strip() or '\x00' in text:
                raise ValueError('not nonempty UTF-8 evidence')
        except (ValueError, OSError) as exc:
            findings.append({'kind': 'local_evidence_file', 'route': item['path'],
                             'message': f"Source routing: {item['path']}: {exc}"})
    return findings


def local_route_preflight(metadata: Mapping[str, Any], inv: Mapping[str, Any], root: Path) -> list[str]:
    """Every declared-route problem (the formal stage passes route-free source metadata)."""
    return [f['message'] for f in route_findings(metadata, inv, root)]


def artifact_inventory(metadata: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Deterministic preparation facts, never evidence of scientific correctness."""
    paths = [('main_pdf', metadata.get('latest_pdf') or
              f"papers/{metadata['paper_id']}/manuscript/main.pdf", None)]
    if metadata.get('latest_supplementary_pdf'):
        paths.append(('supplement_pdf', metadata['latest_supplementary_pdf'], None))
    package = metadata.get('submission_package') or {}
    if package.get('source_archive'):
        paths.append(('journal_source_archive', package['source_archive'], package.get('source_archive_sha256')))
    publication = ((metadata.get('support') or {}).get('publication') or {})
    for rel in publication.get('package_files', []) or []:
        if str(rel).lower().endswith('.zip'):
            paths.append(('support_archive', rel, publication.get('package_sha256')))
    records, errors = [], []
    for name, rel, expected in paths:
        record = {'id': name, 'path': str(rel), 'status': 'missing', 'scientific_correctness_established': False}
        if name == 'journal_source_archive':
            record.update(registered_package_version=str(package.get('version') or ''),
                          current_manuscript_version=str(metadata.get('version') or ''),
                          current_version_identity=(str(package.get('version') or '') ==
                                                    str(metadata.get('version') or '')),
                          current_source_correspondence_requires_official_handoff=True)
        try:
            p = _safe_file(root, str(rel)); body = p.read_bytes()
            record.update(status='present', bytes=len(body), sha256=sha(body))
            if p.suffix.lower() == '.pdf' and not body.startswith(b'%PDF-'):
                raise ValueError('not an actual PDF')
            if p.suffix.lower() == '.zip':
                with zipfile.ZipFile(p) as z:
                    if z.testzip() is not None: raise ValueError('ZIP member checksum failed')
            if expected is not None and record['sha256'] != expected:
                raise ValueError('registered artifact hash mismatch')
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            record.update(status='invalid', error=str(exc))
            errors.append(f"Artifact preparation: {name}: {exc}")
        records.append(record)
    return {'records': records, 'blockers': errors,
            'unregistered_final_journal_zip_checked_at_handoff': not bool(package.get('source_archive'))}


def _local_records(plan: Mapping[str, Any], inv: Mapping[str, Any], root: Path,
                   directory: Path) -> list[dict[str, Any]]:
    records = []
    for item in plan.get("local_evidence", []):
        path = _safe_file(root, item["path"])
        body = path.read_bytes()
        if sha(body) != item["sha256"] or len(body) > MAX_DOWNLOAD:
            raise ValueError("Local evidence hash mismatch or size limit exceeded")
        text = body.decode("utf-8", errors="strict")
        if not text.strip() or "\x00" in text:
            raise ValueError("Local evidence must be a nonempty UTF-8 text record")
        # Only deliberately selected scientific files enter a model packet.
        # Private correspondence, runtime environments, signed upload links and
        # service credentials must remain outside this interface.
        if re.search(r"(?i)(?:authorization\s*:\s*bearer|ara-paper-manage-api|(?:api_key|api-key|access_token|edit_url|upload_url)\s*[=:]|[?&](?:x-amz-(?:signature|credential|security-token)|x-goog-(?:signature|credential)|signature|sig|token)=)", text):
            raise ValueError("Local evidence contains private service material")
        if set(item.get("reference_keys", [])) - {r["key"] for r in inv["references"]}:
            raise ValueError("Local evidence refers to an absent bibliography key")
        if not any(pattern in p["text"] for pattern in item["passage_patterns"] for p in inv["passages"]):
            raise ValueError("Local evidence passage selector matches no current manuscript passage")
        sid = "L" + digest(item)[:20]
        text_path = directory / (sid + ".text")
        text_path.write_text(text)
        records.append({"id": sid, "kind": item["kind"], "reference_keys": item.get("reference_keys", []),
            "passage_patterns": item["passage_patterns"], "url": "", "retrieved_at": datetime.now(UTC).isoformat(),
            "body_path": item["path"], "body_sha256": sha(body),
            "text_path": text_path.relative_to(root).as_posix(), "text_sha256": sha(text.encode()), "text": text})
    return records


class SourceAccessError(ValueError):
    """The provider answered with an access/challenge page instead of the record."""


# Retrieval fallback through the host-side download bridge. When this environment
# cannot reach a public source (access failure: 401/403/429/5xx, timeout,
# connection error or challenge page), the same URL is fetched by the bridge
# worker on the host and the returned bytes go through exactly the same checks.
# A bridge that is absent, times out or fails leaves the original failure in
# place: obtaining nothing is never treated as verification.
DEFAULT_BRIDGE = "/workspace/.download-bridge/download-submit"
BRIDGE_ENV = "OPENLABS_FORMAL_BRIDGE"
BRIDGE_TIMEOUT_ENV = "OPENLABS_FORMAL_BRIDGE_TIMEOUT"
DEFAULT_BRIDGE_TIMEOUT = 300
_CHALLENGE = re.compile(rb"<title[^>]*>\s*(?:Client Challenge|Access Denied|Just a moment|Security Check)", re.I)


def bridge_command() -> str | None:
    """The bridge executable, or ``None`` when the fallback is disabled or unavailable.

    ``OPENLABS_FORMAL_BRIDGE`` = ``off``/``0``/``false`` disables it; another value names the
    executable. Unset: the default bridge, only if it exists and is executable."""
    value = os.environ.get(BRIDGE_ENV)
    if value is not None and value.strip().lower() in {"", "0", "off", "false", "no", "disabled"}:
        return None
    path = Path(value.strip()) if value else Path(DEFAULT_BRIDGE)
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def bridge_timeout() -> int:
    try:
        value = int(os.environ.get(BRIDGE_TIMEOUT_ENV, DEFAULT_BRIDGE_TIMEOUT))
    except ValueError:
        return DEFAULT_BRIDGE_TIMEOUT
    return max(10, min(value, 3600))


def _sniff_content_type(body: bytes) -> str:
    head = body[:2048].lstrip().lower()
    if body.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith((b"<!doctype html", b"<html")) or b"<html" in head[:512]:
        return "text/html"
    if head.startswith((b"{", b"[")):
        return "application/json"
    if head.startswith(b"<?xml") or head.startswith(b"<feed"):
        return "application/xml"
    return "text/plain"


def bridge_fetch(url: str, directory: Path, root: Path, sid: str) -> tuple[bytes, dict[str, Any]]:
    """Fetch a public HTTPS URL through the download bridge; raise SourceAccessError on failure."""
    command = bridge_command()
    if command is None:
        raise SourceAccessError("Download bridge unavailable")
    target_dir = directory / "bridge"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = target_dir / f"{sid}-{stamp}.download"
    timeout = bridge_timeout()
    try:
        completed = subprocess.run([command, "--url", url, "--output", str(target.resolve()), "--wait",
                                    "--timeout", str(timeout)], capture_output=True, text=True,
                                   timeout=timeout + 60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceAccessError(f"Download bridge failed: {type(exc).__name__}") from exc
    status: dict[str, Any] = {}
    for line in reversed(completed.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            status = candidate
            break
    if completed.returncode != 0 or status.get("state") != "completed" or not target.is_file():
        raise SourceAccessError(f"Download bridge did not obtain the source (state {status.get('state')!r}, "
                                f"exit {completed.returncode}; {str(status.get('error') or '')[:200]})")
    if target.stat().st_size > MAX_DOWNLOAD:
        raise ValueError("Primary evidence exceeds the download limit; supply a precise official chapter/page endpoint")
    body = target.read_bytes()
    record = {"method": "download_bridge", "bridge_job_id": status.get("id"),
              "bridge_route": status.get("route"), "bridge_routes_attempted": status.get("routes_attempted"),
              "bridge_fallback_reason": status.get("fallback_reason"),
              "bridge_file": target.relative_to(root).as_posix(), "bridge_file_sha256": sha(body),
              "retrieved_at": datetime.now(UTC).isoformat()}
    return body, record


# HTTP statuses that say nothing about the record itself: authentication,
# blocking, rate limiting, timeouts and server failures.
ACCESS_STATUSES = frozenset({401, 403, 407, 408, 425, 429})
ABSENT_STATUSES = frozenset({404, 410})


def failure_kind(exc: BaseException) -> str:
    """Classify a failed lookup: ``access`` (could not obtain the record),
    ``absent`` (the service answered that no such record exists) or
    ``mismatch`` (a record was obtained but does not identify the cited work)."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in ACCESS_STATUSES or status >= 500:
            return "access"
        return "absent" if status in ABSENT_STATUSES else "mismatch"
    if isinstance(exc, (httpx.TransportError, SourceAccessError)):
        return "access"  # timeouts, DNS/connect/proxy failures, challenge pages
    return "mismatch"


def collect_sources(inv: Mapping[str, Any], metadata: Mapping[str, Any], root: Path,
                    directory: Path, client: httpx.Client,
                    unverifiable: dict[str, list[str]] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch public primary records. Failure is retained as unknown, never success.

    A reference whose every identifier lookup failed for network/access reasons
    (and none returned a different record) is not a manuscript defect: it is put in
    ``unverifiable`` (key -> failed lookups) instead of ``errors``, for manual review
    or a run from another environment. A lookup that returned a different or
    malformed record, or that no service knows, still yields an error.
    """
    unverifiable = {} if unverifiable is None else unverifiable
    access_log: list[str] = []
    directory.mkdir(parents=True, exist_ok=True)
    sources, errors, seen = [], [], {}
    # One retrieval per URL in a run: a URL already obtained (for example as a
    # registered primary source) is reused, with its bytes and hashes, when the
    # same URL is requested again under another kind; a failure is not retried.
    by_url: dict[tuple[str, tuple[int, ...], str], dict[str, Any]] = {}
    failed_urls: dict[tuple[str, tuple[int, ...], str], BaseException] = {}
    plan = source_plan(metadata)
    transcripts = {(_normalized_url(item["url"]), tuple(item.get("pages") or [])): item["transcript"]
                   for item in plan.get("sources", []) if item.get("extraction_method") == "ocr_transcript"}
    reference_keys = {r["key"] for r in inv["references"]}
    for item in plan.get("sources", []):
        if set(item["reference_keys"]) - reference_keys:
            raise ValueError("Primary-source plan refers to an absent bibliography key")

    def fetch(url: str, kind: str, keys: list[str], pages: list[int] | None = None, method: str = "text") -> dict[str, Any]:
        url = _url(url)
        initial_host = host = urlsplit(url).hostname
        if host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"}:
            kind = "bibliographic_metadata"
        identity = (url, kind, tuple(pages or []), method)
        if identity in seen:
            source = seen[identity]
            source["reference_keys"] = sorted(set(source["reference_keys"]) | set(keys))
            return source
        url_identity = (_normalized_url(url), tuple(pages or []), method)
        if url_identity in by_url:
            source = by_url[url_identity]
            source["reference_keys"] = sorted(set(source["reference_keys"]) | set(keys))
            return source
        if url_identity in failed_urls:
            raise failed_urls[url_identity]
        try:
            return _fetch_new(url, kind, keys, pages, method, identity, url_identity, initial_host)
        except Exception as exc:
            failed_urls[url_identity] = exc
            raise

    def _fetch_new(url: str, kind: str, keys: list[str], pages: list[int] | None, method: str,
                   identity: tuple[Any, ...], url_identity: tuple[str, tuple[int, ...], str],
                   initial_host: str | None) -> dict[str, Any]:
        sid = "S" + sha(json.dumps(identity).encode())[:20]
        try:
            with client.stream("GET", url, headers={"User-Agent": "OpenLabs-formal-check/1.0"}) as response:
                response.raise_for_status()
                final_url = _url(str(response.url))
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise ValueError("Primary evidence exceeds the download limit; supply a precise official chapter/page endpoint")
                    chunks.append(chunk)
                body = b"".join(chunks)
                content_type = response.headers.get("content-type", "")
            if _CHALLENGE.search(body[:20_000]):
                raise SourceAccessError("Provider returned a challenge or access page, not the requested source")
            retrieval: dict[str, Any] = {"method": "direct"}
        except (httpx.HTTPError, SourceAccessError) as direct_exc:
            # Only access failures fall back; an absent record (404/410) or any
            # content problem keeps its original classification.
            if failure_kind(direct_exc) != "access" or bridge_command() is None:
                raise
            try:
                body, retrieval = bridge_fetch(url, directory, root, sid)
            except SourceAccessError as bridge_exc:
                access_log.append(f"{url}: direct {type(direct_exc).__name__}"
                                  + (f" {direct_exc.response.status_code}" if isinstance(direct_exc, httpx.HTTPStatusError) else "")
                                  + f"; bridge fallback failed: {bridge_exc}")
                raise direct_exc from bridge_exc
            retrieval["direct_failure"] = type(direct_exc).__name__ + (
                f" {direct_exc.response.status_code}" if isinstance(direct_exc, httpx.HTTPStatusError) else "")
            # The bridge returns the bytes of the requested URL; redirects are not reported.
            final_url, content_type = url, _sniff_content_type(body)
        host = urlsplit(final_url).hostname
        if host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"}:
            kind = "bibliographic_metadata"
        record_url = url if initial_host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"} else final_url
        record_host = host if host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"} else initial_host
        if urlsplit(url).path.lower().endswith(".pdf") and not body.startswith(b"%PDF-"):
            raise ValueError("An original PDF endpoint returned a non-PDF response")
        if _CHALLENGE.search(body[:20_000]):
            raise SourceAccessError("Provider returned a challenge or access page, not the requested source")
        transcript = None
        if method == "ocr_transcript":
            transcript = transcripts.get((url_identity[0], url_identity[1]))
            if transcript is None or not body.startswith(b"%PDF-") or sha(body) != transcript["original_sha256"]:
                raise ValueError("OCR transcript is not bound to the retrieved original PDF")
            transcript_bytes = _safe_file(root, transcript["path"]).read_bytes()
            if sha(transcript_bytes) != transcript["sha256"]:
                raise ValueError("OCR transcript missing or changed")
            text = transcript_bytes.decode("utf-8", errors="strict")
            if not text or "OCR transcription" not in text.splitlines()[0]:
                raise ValueError("An OCR transcript must declare itself in its first line")
            pdf_copy = directory / (sid + ".pdf")
            pdf_copy.write_bytes(body)
        else:
            text = _text_document(body, content_type, directory, sid, pages, method)
        if not text.strip():
            raise ValueError("Empty or unextractable primary document")
        if record_host == "api.crossref.org":
            message = json.loads(text).get("message", {})
            requested = unquote(urlsplit(record_url).path.removeprefix("/works/").removeprefix("/dois/"))
            if str(message.get("DOI", "")).lower() != requested.lower() or not message.get("title") or not message.get("author"):
                raise ValueError("Crossref record lacks title/authors or returns a different DOI")
        elif record_host == "api.datacite.org":
            attributes = json.loads(text).get("data", {}).get("attributes", {})
            requested = unquote(urlsplit(record_url).path.removeprefix("/dois/").removeprefix("/works/"))
            if str(attributes.get("doi", "")).lower() != requested.lower() or not attributes.get("titles") or not attributes.get("creators"):
                raise ValueError("DataCite record lacks title/authors or returns a different DOI")
        elif record_host == "export.arxiv.org":
            try:
                entry = ET.fromstring(text).find("{http://www.w3.org/2005/Atom}entry")
            except ET.ParseError as exc:
                raise ValueError("Malformed arXiv response") from exc
            if entry is None or not entry.findtext("{http://www.w3.org/2005/Atom}title", "").strip():
                raise ValueError("arXiv did not return an identified paper")
            requested = parse_qs(urlsplit(record_url).query).get("id_list", [""])[0]
            returned = entry.findtext("{http://www.w3.org/2005/Atom}id", "").split("/abs/")[-1]
            if not requested or (returned != requested and (re.search(r"v\d+$", requested) or re.sub(r"v\d+$", "", returned) != requested)):
                raise ValueError("arXiv returned a different paper/version")
        body_path, text_path = directory / (sid + ".body"), directory / (sid + ".text")
        body_path.write_bytes(body); text_path.write_text(text)
        source = {"id": sid, "url": url, "final_url": final_url, "kind": kind,
            "reference_keys": keys, "retrieved_at": datetime.now(UTC).isoformat(),
            "body_path": body_path.relative_to(root).as_posix(), "body_sha256": sha(body),
            "text_path": text_path.relative_to(root).as_posix(), "text_sha256": sha(text.encode()),
            "extraction_pages": pages, "extraction_method": method, "retrieval": retrieval, "text": text}
        if transcript is not None:
            source["ocr_transcript"] = dict(transcript)
        sources.append(source); seen[identity] = source
        by_url[url_identity] = source
        final_identity = (_normalized_url(final_url), tuple(pages or []), method)
        by_url.setdefault(final_identity, source)
        return source

    # The exact current support record may be an authenticated draft until the
    # post-review publication step. It is never evidence about external theory.
    publication = (metadata.get("support") or {}).get("publication") or {}
    support_key = publication.get("bibliography_key")
    audit = None
    if not support_key and publication.get("status") == "draft" and publication.get("draft_receipt"):
        from paper_writing.support_citations import audit_manuscript_support
        audit = audit_manuscript_support(str(metadata["paper_id"]), root=root)
        if audit.get("valid"):
            support_key = audit.get("bibliography_key")
    for ref in inv["references"]:
        key, raw = ref["key"], ref["text"]
        doi = re.search(r"10\.\d{4,9}/[^\s{}<>\"]+", raw, re.I)
        arxiv = re.search(r"(?:arxiv(?:\.org/(?:abs|pdf)/|\s*:\s*))((?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?)", raw, re.I)
        if key == support_key and publication.get("status") != "published":
            from paper_writing.support_citations import audit_manuscript_support, support_review_findings
            if audit is None:
                audit = audit_manuscript_support(str(metadata["paper_id"]), root=root)
            receipt_name = publication.get("draft_receipt")
            # Identifier-presentation findings are preparation advisories at review
            # time; the authenticated draft evidence itself must still be intact.
            if support_review_findings(audit)[0] or not receipt_name:
                errors.append(f"{key}: current prepublication support has no valid authenticated draft evidence")
                continue
            receipt = _safe_file(root, receipt_name)
            body = receipt.read_bytes()
            sid = "S" + sha(body)[:20]
            path = directory / (sid + ".text")
            raw_receipt = json.loads(body)
            # Do not forward authenticated edit/upload links into model inputs.
            text = json.dumps({k: raw_receipt[k] for k in
                ("id", "metadata", "doi", "submitted", "state", "schema_version", "paper_id",
                 "paper_version", "environment", "deposition_id", "reserved_version_doi",
                 "prepared_at", "submitted_metadata", "verified_remote_metadata")
                if k in raw_receipt}, ensure_ascii=False, indent=2)
            path.write_text(text)
            sources.append({"id": sid, "kind": "current_support_draft", "reference_keys": [key],
                "url": str((publication.get("zenodo") or {}).get("metadata_source") or ""),
                "retrieved_at": datetime.now(UTC).isoformat(), "body_path": str(receipt_name),
                "body_sha256": sha(body), "text_path": path.relative_to(root).as_posix(),
                "text_sha256": sha(text.encode()), "text": text, "support_audit_sha256": digest(audit)})
            continue
        candidates = []
        if doi:
            value = doi.group().rstrip(".,;)")
            candidates = [("https://api.crossref.org/works/" + quote(value, safe=""), "bibliographic_metadata"),
                          ("https://api.datacite.org/dois/" + quote(value, safe=""), "bibliographic_metadata")]
        elif arxiv:
            value = arxiv.group(1)
            candidates = [("https://export.arxiv.org/api/query?id_list=" + quote(value), "bibliographic_metadata")]
        failures, kinds = [], []
        for url, kind in candidates:
            try:
                document = fetch(url, kind, [key])
                # Bibliographic verification needs identified authoritative
                # metadata, not a downloaded original. Full texts are optional
                # explicitly declared aids; do not automatically fetch PDFs.
                break
            except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError) as exc:
                kinds.append(failure_kind(exc))
                status = getattr(getattr(exc, "response", None), "status_code", None)
                failures.append(f"{url}: {type(exc).__name__}" + (f" {status}" if status else ""))
        else:
            if candidates and "access" in kinds and "mismatch" not in kinds:
                unverifiable[key] = failures
                access_log.append(f"{key}: authoritative identifier lookup unresolved ({'; '.join(failures)}) "
                                  "[unverifiable_source_access]")
            elif candidates:
                errors.append(f"{key}: authoritative identifier lookup unresolved ({'; '.join(failures)})")
    for item in plan.get("sources", []):
        try:
            source = fetch(item["url"], item["kind"], list(item["reference_keys"]), item.get("pages"), item.get("extraction_method", "text"))
            if item.get("passage_patterns"):
                source["passage_patterns"] = sorted(set(source.get("passage_patterns", [])) | set(item["passage_patterns"]))
        except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError) as exc:
            errors.append(f"Declared primary source unavailable: {item['url']} ({type(exc).__name__})")
    for ref in inv["references"]:
        # Official links printed in a bibliography are discovery inputs, not
        # automatically trusted certificates. The verifier still has to check
        # source ownership, exact work identity and substantive support.
        if any(ref["key"] in source["reference_keys"] and source["kind"] in {
                "bibliographic_metadata", "publisher_catalog", "current_support_draft"}
                for source in sources):
            continue
        for url in list(dict.fromkeys(re.findall(r"https://[^\s{}<>\"]+", ref["text"])))[:3]:
            url = url.rstrip(".,;)")
            if (url.startswith(("https://doi.org/", "https://arxiv.org/abs/"))
                    or urlsplit(url).path.lower().endswith(".pdf")):
                continue
            try:
                fetch(url, "publisher_catalog", [ref["key"]])
            except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                pass
    # A publisher's catalog/primary text can also establish a work without DOI.
    for key in list(unverifiable):
        if any(key in s["reference_keys"] for s in sources):
            del unverifiable[key]  # another route obtained the record
    for ref in inv["references"]:
        if ref["key"] in unverifiable:
            continue
        if not any(ref["key"] in s["reference_keys"] for s in sources):
            errors.append(f"{ref['key']}: no queryable authoritative bibliographic evidence; register an official catalog URL")
    if unverifiable and not any(s["kind"] in {"bibliographic_metadata", "publisher_catalog", "primary_text"}
                                for s in sources):
        # Nothing at all was reachable: that is an environment outage, not a set of
        # individually unverifiable references. Fail as a technical retry instead of
        # passing a verification that checked no external record.
        errors.append("No external bibliographic service was reachable from this environment "
                      f"({len(unverifiable)} lookups failed on access); rerun the verification "
                      "where the services are reachable")
    # Another authoritative primary record may resolve a provider outage. Keep
    # all failed lookups in a separate, immutable attempt log; never silently
    # invent success for those requests.
    attempts_path = directory / "retrieval-failures.json"
    attempts_path.write_text(json.dumps(access_log + errors, ensure_ascii=False, indent=2) + "\n")
    errors = [e for e in errors if not e.startswith("Declared primary source unavailable:") and not ("authoritative identifier lookup unresolved" in e
        and any(e.split(":", 1)[0] in s["reference_keys"] and s["kind"] in {"primary_text", "publisher_catalog"}
                for s in sources))]
    sources.extend(_local_records(plan, inv, root, directory))
    return sources, errors


def _safe_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Unsafe formal evidence path")
    path = root / relative
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Formal evidence paths cannot be symlinks")
    if not path.is_file():
        raise ValueError("Formal evidence file is missing")
    return path


def _exact(rows: list[dict[str, Any]], field: str, expected: set[str], name: str) -> None:
    identifiers = [row[field] for row in rows]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != expected:
        raise ValueError(f"{name}: omitted, duplicated or invented coverage items")


def report_blockers(report: Mapping[str, Any], inv: Mapping[str, Any], sources: list[dict[str, Any]],
                    *, findings: list[dict[str, Any]] | None = None,
                    artifacts: Mapping[str, Any] | None = None,
                    unverifiable_keys: Any = (),
                    unverifiable_out: list[dict[str, Any]] | None = None,
                    followup: bool = False) -> list[str]:
    """Check exact coverage and whitespace-equivalent evidence without changing raw text.

    ``unverifiable_keys`` are references whose authoritative record could not be
    obtained for network/access reasons. An ``unchecked`` verdict on such a
    reference or on a citation of it (and a ``verified`` verdict that therefore has
    no evidence) is recorded in ``unverifiable_out`` instead of blocking. ``error``
    and ``gap`` verdicts, and every other item, are judged as before.
    """
    unverifiable_keys = frozenset(unverifiable_keys or ())
    unverifiable_out = [] if unverifiable_out is None else unverifiable_out

    def unverifiable(row: Mapping[str, Any], label: str, key: str) -> bool:
        if key not in unverifiable_keys or row.get("status") not in {"unchecked", "verified"}:
            return False
        if row["status"] == "verified" and row.get("evidence"):
            return False
        unverifiable_out.append({"item": label, "reference_key": key, "status": row["status"],
                                 "classification": "unverifiable_source_access"})
        return True
    _validate_against_schema(report, report_schema(followup))
    _exact(report["references"], "key", {r["key"] for r in _task_references(inv)}, "References")
    _exact(report["passages"], "passage_id", {p["id"] for p in inv["passages"]}, "Passages")
    source_by_id = {s["id"]: s for s in sources}
    if len(source_by_id) != len(sources):
        raise ValueError("Duplicated evidence source IDs")
    blockers = []
    context = {'root': '', 'label': ''}
    def add(message: str, category: str = 'technical', *, aggregate: bool = False,
            reason: str = '', status: str | None = None) -> None:
        if category != "advisory":
            blockers.append(message)
        if findings is not None:
            findings.append({'category': category, 'root': context['root'], 'location': context['label'],
                             'message': message, 'aggregate': aggregate, 'reason': reason, 'status': status})

    def evidence(items: list[dict[str, str]], keys: set[str], *, primary: bool = False,
                 kinds: set[str] | None = None) -> None:
        if not items:
            add("Verified external claims require located source evidence")
            return
        represented = set()
        for item in items:
            source = source_by_id.get(item["source_id"])
            if source is None or not item["locator"].strip():
                add("Evidence has an unknown source or empty locator")
                continue
            if item['quote'] and not _quote_present(item["quote"], source["text"]):
                add(f"Quoted evidence is absent from source {item['source_id']} at {item['locator']}")
            if primary and source["kind"] != "primary_text":
                add("A prerequisite requires original primary text, not metadata or an abstract")
            if kinds is not None and source["kind"] not in kinds:
                add("Evidence type cannot establish this claim")
            represented |= set(source["reference_keys"])
        if not keys <= represented:
            add("Evidence does not bind every claimed reference key")

    def checked(row: Mapping[str, Any], label: str, fields: tuple[str, ...]) -> bool:
        context['label'] = label
        if row["status"] != "verified":
            category = 'preparation' if row.get('kind') == 'artifact_preparation' else 'scientific'
            if followup:
                consequence = row["reader_misconclusion"].strip()
                rationale = "\n".join(str(row.get(field, "")) for field in fields)
                late = ("previous_blocker_roots" in inv and context["root"] not in inv["previous_blocker_roots"])
                if (row["finding_kind"] == "advisory" or not consequence or
                        (late and not re.search(r"(?im)^Why missed:[ \t]*\S", rationale))):
                    category = "advisory"
                fields = (*fields, "reader_misconclusion")
                # A gap or unchecked result must still identify a concrete
                # validity defect. An error can be in numbers, citations or formulas.
            reason = "\n".join(str(row.get(f, '')) for f in fields)
            message = f"{label}: {row['status']}"
            if followup:
                message += f" — {reason.strip()}"
            add(message, category,
                aggregate='passage_id' in row, status=row['status'],
                reason=reason)
            return False
        if any(not row[field].strip() for field in fields):
            add(f"{label}: a verified item lacks its check rationale")
            return False
        return True

    for row in report["references"]:
        context['root'] = row['key']
        if unverifiable(row, row["key"], row["key"]):
            continue
        if checked(row, row["key"], ("authors_check", "title_check", "year_check", "venue_identifier_locator_check",
                                    "primary_source_check", "publication_status_check")):
            evidence(row["evidence"], {row["key"]}, kinds={"primary_text", "publisher_catalog", "bibliographic_metadata", "current_support_draft"})
    inv_passages = {p["id"]: p for p in inv["passages"]}
    proof_context = {**inv_passages, **inv.get("proof_context", {})}
    for row in report["passages"]:
        context['root'] = row['passage_id']
        unit = inv_passages[row["passage_id"]]
        # A passage left unchecked only because some of its citations point to
        # unreachable records is unverifiable, not defective.
        pending = [item for group in ("formulas", "prerequisites", "citations") for item in row[group]
                   if item.get("status") != "verified"
                   and not (group == "citations" and _nonmathematical_unchecked_citation(item))]
        if (row["status"] == "unchecked" and pending
                and all(item.get("key") in unverifiable_keys and item.get("status") == "unchecked"
                        and "citation_id" in item for item in pending)):
            unverifiable_out.append({"item": row["passage_id"], "reference_key": ", ".join(
                sorted({item["key"] for item in pending})), "status": "unchecked",
                "classification": "unverifiable_source_access"})
        else:
            checked(row, row["passage_id"], ("coverage_rationale",))
        _exact(row["formulas"], "formula_id", {f["id"] for f in unit["formulas"]}, "Formulas")
        _exact(row["citations"], "citation_id", {c["id"] for c in unit["citations"]}, "Citation uses")
        cites = {c["id"]: c["key"] for c in unit["citations"]}
        for item in row["citations"]:
            if item["key"] != cites[item["citation_id"]]:
                raise ValueError("Citation-use report changes the cited reference")
            # Mathematical paragraphs can also cite apparatus descriptions,
            # datasets or code. The independent verifier must classify each
            # use explicitly; the raw unchecked assessment remains in the
            # report. Reference identity, mathematical prerequisites, and any
            # actual error/gap are still checked without this exception.
            if _nonmathematical_unchecked_citation(item):
                continue
            if unverifiable(item, item["citation_id"], item["key"]):
                continue
            if checked(item, item["citation_id"], ("manuscript_claim", "support_check")):
                if item["evidence"]:
                    evidence(item["evidence"], {item["key"]}, kinds={"primary_text", "publisher_catalog", "bibliographic_metadata", "current_support_draft"})
        for item in row["formulas"]:
            if checked(item, item["formula_id"], ("assumptions", "derivation_or_source_check")) and item["evidence"]:
                evidence(item["evidence"], set(), kinds={"primary_text", "manuscript_code", "execution_record", "research_record"})
        for item in row["prerequisites"]:
            if checked(item, row["passage_id"] + ": " + item["statement"],
                       ("statement", "original_locator", "original_assumptions", "original_conclusion",
                        "manuscript_instantiation", "condition_check", "formula_check")):
                keys = set(item["reference_keys"])
                if item["kind"] == "external":
                    if not keys or keys - {r["key"] for r in inv["references"]}:
                        add("External prerequisite has no valid cited source key")
                    # Check the theoretical statement and application directly.
                    # Original full-text retrieval is not a gate requirement.
                    # If a quotation is supplied, it must still be genuine and
                    # substantive; metadata cannot masquerade as theorem text.
                    if item["evidence"]:
                        evidence(item["evidence"], keys, primary=True)
                elif item["kind"] == "internal_derivation":
                    if keys or item["evidence"]:
                        add("Internal derivation must be reconstructed from located manuscript proof, not external evidence")
                    locator = item["original_locator"].strip()
                    if locator not in proof_context and not (len(_whitespace(locator)) >= 12 and any(
                            _whitespace(locator) in _whitespace(p["text"]) for p in proof_context.values())):
                        add("Internal derivation locator is not an actual manuscript passage ID or literal proof excerpt")
    return blockers


# Owner rule 2026-11-23 ("抓大放小 ... 只要数据和结论都是真实正确有效的就行，一些语句上不是那么精确，
# 不要过于纠结"): only wrong data or numbers, conclusions contradicted by the evidence, references
# that do not exist or cannot be verified, and hard formal errors block. A scientific ``gap`` -- the
# statement is not fully supported *as worded* and could be stated more rigorously -- is advice
# that travels with the delivery package. Errors, unchecked claims, reference rows and technical,
# source-routing and preparation problems still block. Applied when the review is synthesized
# (the verifier's report, prompt and schema are unchanged, so archived reports stay verifiable).
PRECISION_RULE = "gate1_precision_v1"
# Finding kinds that concern the wording or support of a sentence rather than wrong data, numbers,
# formulas, figures or a preregistered rule; the referees' science dimension judges conclusions.
PRECISION_KINDS = materiality.FORMAL_PRECISION_KINDS


def finding_kinds(report: Mapping[str, Any] | None) -> dict[str, str]:
    """Map each verified-item label of a formal report to the verifier's ``finding_kind``."""
    kinds: dict[str, str] = {}
    if not isinstance(report, Mapping):
        return kinds

    def note(label: Any, row: Mapping[str, Any]) -> None:
        if isinstance(row.get("finding_kind"), str):
            kinds[str(label)] = row["finding_kind"]

    for row in report.get("references") or []:
        note(row.get("key"), row)
    for row in report.get("passages") or []:
        note(row.get("passage_id"), row)
        for item in row.get("citations") or []:
            note(item.get("citation_id"), item)
        for item in row.get("formulas") or []:
            note(item.get("formula_id"), item)
        for item in row.get("prerequisites") or []:
            note(f"{row.get('passage_id')}: {item.get('statement')}", item)
    return kinds


_DOWNGRADED_FORMAL_RULES = frozenset({"formal_source_routing", "formal_precision", "formal_accepting_technical"})


def _verdict(finding: Mapping[str, Any], kinds: Mapping[str, str] | None, *,
             accepting: bool = False) -> materiality.Decision:
    return materiality.decide(finding, source="formal",
                              context=materiality.Context(formal_kinds=dict(kinds or {}), accepting=accepting))


def precision_finding(finding: Mapping[str, Any], kinds: Mapping[str, str] | None = None, *,
                      accepting: bool = False) -> bool:
    """A formal finding that does not block: a scientific precision ``gap`` or sentence-level
    unsupported-claim/citation-support finding, a ``source_routing`` problem (checked at
    delivery), or — when every referee recommends minor revision or accept — a verifier
    ``technical`` failure (reported as advice / needs-rerun).

    Decided by the materiality table (``formal_source_routing``, ``formal_precision``,
    ``formal_accepting_technical``)."""
    return _verdict(finding, kinds, accepting=accepting).rule in _DOWNGRADED_FORMAL_RULES


def precision_view(summary: Mapping[str, Any] | None, kinds: Mapping[str, str] | None = None, *,
                   accepting: bool = False) -> dict[str, Any] | None:
    """``summary`` with downgraded findings recategorized as advice (``precision_downgraded``)."""
    if not isinstance(summary, Mapping):
        return summary
    if "raw_findings" not in summary:
        if not accepting or not isinstance(summary.get("by_category"), Mapping):
            return dict(summary)
        cats = {k: list(v) for k, v in summary["by_category"].items()}
        tech = cats.get("technical") or []
        if not tech:
            return dict(summary)
        cats["technical"] = []
        cats["advisory"] = [*cats.get("advisory", []), *tech]
        return {**summary, "by_category": cats}
    raw = []
    for f in summary["raw_findings"]:
        decision = _verdict(f, kinds, accepting=accepting)
        if decision.rule in _DOWNGRADED_FORMAL_RULES:
            row = dict(f, category="advisory", precision_downgraded=True, downgrade_reason=decision.rule)
            if decision.rule == "formal_accepting_technical":
                row["needs_rerun"] = True
            raw.append(row)
        else:
            raw.append(dict(f))
    return issue_summary(raw)


def material_blockers(blockers: list[str], summary: Mapping[str, Any] | None,
                      kinds: Mapping[str, str] | None = None, *,
                      accepting: bool = False) -> tuple[list[str], list[str]]:
    """Split formal blockers into (still blocking, downgraded to advice) under ``PRECISION_RULE``."""
    findings = (summary or {}).get("raw_findings") if isinstance(summary, Mapping) else None
    if not findings:
        cats = (summary or {}).get("by_category") if isinstance(summary, Mapping) else None
        if accepting and isinstance(cats, Mapping) and cats.get("technical"):
            non_tech = set(cats.get("scientific") or []) | set(cats.get("preparation") or [])
            tech = {m for m in cats.get("technical") or [] if m not in non_tech}
            material = [b for b in blockers if b not in tech]
            return material, [b for b in blockers if b not in material]
        return list(blockers), []
    verdicts = [(f["message"], _verdict(f, kinds, accepting=accepting)) for f in findings]
    downgraded = {message for message, d in verdicts if d.rule in _DOWNGRADED_FORMAL_RULES}
    kept = {message for message, d in verdicts if d.blocks}
    material = [b for b in blockers if b not in downgraded or b in kept]
    return material, [b for b in blockers if b not in material]


def issue_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Preserve raw coverage; collapse only a parent's nested failure aggregation."""
    nested = {(f['root'], f['category']) for f in findings if not f['aggregate'] and f.get('status') is not None}
    roots = []
    for finding in findings:
        if finding['aggregate'] and (finding['root'], finding['category']) in nested:
            continue
        # Do not merge different checks because they share only gap/error.
        key = (finding['category'], finding['root'], finding['location'], finding['message'], finding['reason'])
        if not any(r['_key'] == key for r in roots):
            roots.append(dict(finding, _key=key))
    roots = [{k: v for k, v in r.items() if k != '_key'} for r in roots]
    return {'raw_findings': findings, 'root_causes': roots,
            'by_category': {k: [r['message'] for r in roots if r['category'] == k]
                            for k in ['scientific', 'technical', 'source_routing', 'preparation',
                                      *(['advisory'] if any(r['category'] == 'advisory' for r in roots) else [])]}}


def batch_packet(group: str, batch: list[dict[str, Any]], documents: list[dict[str, str]],
                 inv: Mapping[str, Any], sources: list[dict[str, Any]], *, root: Path | None = None,
                 artifacts: Mapping[str, Any] | None = None,
                 evidence_root: str | None = None) -> str:
    """One formal-role batch prompt.

    ``evidence_root`` replaces the ``root`` label only (re-verification of a review that
    ran in another checkout); it never changes what is read.
    """
    keys = ({r["key"] for r in batch} if group == "references" else
            {c["key"] for p in batch for c in p["citations"]})
    # Route bodies by cited keys or explicit implicit-dependency selectors.
    # Unrelated metadata remains in the complete bibliography/source catalog;
    # broadcasting its full text to every math batch can overflow even a
    # singleton. Every reference still receives its full identity evidence.
    selected = [s for s in sources if set(s["reference_keys"]) & keys
                or (group == "passages" and any(pattern in p["text"]
                    for pattern in s.get("passage_patterns", []) for p in batch))]
    scoped_urls = {s["url"] for s in selected if s.get("extraction_pages")}
    selected = [s for s in selected if s["url"] not in scoped_urls or s.get("extraction_pages")]
    instructions = {}
    if inv.get("followup"):
        instructions["followup_scope"] = (
            "Check only the listed prior blockers and changed passages or bibliography entries. "
            "Use the manuscript as context. Keep all findings within the listed items.")
    if "previous_blocker_roots" in inv:
        instructions["previous_blocker_roots"] = inv["previous_blocker_roots"]
        instructions["new_blockers"] = ("For a negative finding outside these prior roots, include a line "
            "starting with 'Why missed:' in its check rationale explaining the previous omission.")
    if inv.get("materiality") or inv.get("followup"):
        instructions["materiality"] = (
            "For each negative verdict provide finding_kind and the concrete reader_misconclusion. "
            "Use advisory for wording, style, caption details and issues without a validity consequence. "
            "For verified items use advisory and an empty reader_misconclusion.")
    return json.dumps({**instructions, "scope": group, "items": batch, "complete_manuscript": documents,
        "evidence_root": evidence_root if evidence_root is not None else (str(root.resolve()) if root else None),
        "deterministic_preparation_inventory": artifacts or {},
        "complete_bibliography": inv["references"], "retrieved_sources": selected,
        "available_source_catalog": [{k: v for k, v in s.items() if k != "text"} for s in sources]},
        ensure_ascii=False, separators=(',', ':'))


def _recorded_evidence_root(prompt: str, system_text: str) -> str | None:
    """The ``evidence_root`` a stored batch prompt was built with (None: not readable)."""
    prefix = system_text + "\n\n"
    if not prompt.startswith(prefix):
        return None
    try:
        value = json.loads(prompt[len(prefix):]).get("evidence_root")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def packet_batches(group: str, documents: list[dict[str, str]], inv: Mapping[str, Any],
                   sources: list[dict[str, Any]], *, root: Path | None = None,
                   artifacts: Mapping[str, Any] | None = None) -> list[list[dict[str, Any]]]:
    """Split oversized batches without dropping context, evidence or scope items.

    A singleton that still exceeds the budget is returned intact so run_checks
    fails closed with the existing source-routing error. Validation reconstructs
    the same deterministic partition rather than trusting recorded batch sizes.
    """
    def size(batch: list[dict[str, Any]]) -> int:
        return len(batch_packet(group, batch, documents, inv, sources, root=root, artifacts=artifacts).encode())

    def split(batch: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        if size(batch) <= MAX_PACKET:
            return [batch]
        if len(batch) == 1:
            return evidence_parts(batch[0]) if group == "passages" else [batch]
        middle = len(batch) // 2
        return split(batch[:middle]) + split(batch[middle:])

    def evidence_parts(unit: dict[str, Any]) -> list[list[dict[str, Any]]]:
        """One passage whose cited evidence exceeds the budget: verify it in parts.

        Each part carries the whole passage text, all its formulas and the
        citation uses of a subset of cited keys (all uses of a key stay together),
        with exactly those keys' sources. The passage verdict is the conjunction
        of the parts (merge_evidence_parts). A key whose evidence alone exceeds
        the budget stays an oversized part, so the run fails closed as before.
        """
        keys = list(dict.fromkeys(c["key"] for c in unit["citations"]))
        if len(keys) < 2:
            return [[unit]]
        def part(selected: list[str]) -> dict[str, Any]:
            return dict(unit, citations=[c for c in unit["citations"] if c["key"] in selected])
        groups: list[list[str]] = []
        current: list[str] = []
        for key in keys:
            if current and size([part(current + [key])]) > MAX_PACKET:
                groups.append(current)
                current = [key]
            else:
                current = current + [key]
        groups.append(current)
        if len(groups) == 1:
            return [[unit]]
        return [[dict(part(selected), evidence_part={"part": number, "of": len(groups),
                                                    "citation_keys": selected})]
                for number, selected in enumerate(groups, 1)]

    units = _task_references(inv) if group == "references" else inv[group]
    return [batch for start in range(0, len(units), BATCH_SIZE)
            for batch in split(units[start:start + BATCH_SIZE])]


def report_schema(followup: bool) -> dict[str, Any]:
    if not followup:
        return REPORT_SCHEMA
    schema = json.loads(json.dumps(REPORT_SCHEMA))

    def add_fields(node):
        for child in node.get("properties", {}).values():
            add_fields(child)
        if "items" in node:
            add_fields(node["items"])
        if "status" in node.get("properties", {}):
            node["properties"].update(
                finding_kind={"type": "string", "enum": [
                    "advisory", "numeric_or_statistical_error", "citation_error_or_unsupported",
                    "formula_error", "unsupported_claim", "preregistration_violation", "figure_result_mismatch"]},
                reader_misconclusion=TEXT)
            node["required"].extend(["finding_kind", "reader_misconclusion"])

    add_fields(schema)
    return schema


def batch_schema(group: str, batch: list[dict[str, Any]], inv: Mapping[str, Any],
                 sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Constrain output identities and locations, never scientific judgments."""
    schema = json.loads(json.dumps(report_schema(bool(inv.get("followup") or inv.get("materiality")))))
    for scope, identifier in (("references", "key"), ("passages", "passage_id")):
        rows = schema['properties'][scope]
        rows['minItems'] = rows['maxItems'] = len(batch) if scope == group else 0
        if scope == group and batch:
            rows['items']['properties'][identifier]['enum'] = [
                unit['key' if scope == 'references' else 'id'] for unit in batch]
    choices = {
        'source_id': [source['id'] for source in sources],
        'formula_id': [formula['id'] for unit in batch for formula in unit.get('formulas', [])],
        'citation_id': [citation['id'] for unit in batch for citation in unit.get('citations', [])],
    }
    def constrain(node: dict[str, Any], field: str = '') -> None:
        if node.get('type') == 'string' and field not in {'quote', 'reader_misconclusion'}:
            node['minLength'] = 1
        properties = node.get('properties', {})
        for identifier, ids in choices.items():
            if identifier in properties and ids:
                properties[identifier]['enum'] = ids
        for name, child in properties.items():
            constrain(child, name)
        if node.get('type') == 'array':
            child = node['items']
            fields = child.get('properties', {})
            if any(identifier in fields and not ids for identifier, ids in choices.items()):
                node['maxItems'] = 0
            constrain(child)
    constrain(schema)
    prerequisites = schema['properties']['passages']['items']['properties']['prerequisites']
    external = json.loads(json.dumps(prerequisites['items']))
    internal = json.loads(json.dumps(prerequisites['items']))
    external['properties']['kind']['enum'] = ['external']
    internal['properties']['kind']['enum'] = ['internal_derivation']
    keys = [reference['key'] for reference in inv['references']]
    if keys:
        external['properties']['reference_keys']['items']['enum'] = keys
    internal['properties']['reference_keys']['maxItems'] = 0
    internal['properties']['evidence']['maxItems'] = 0
    ids = list(dict.fromkeys([unit['id'] for unit in inv['passages']] + list(inv.get('proof_context', {}))))
    if ids:
        internal['properties']['original_locator']['enum'] = ids
    prerequisites['items'] = {'anyOf': [external, internal]}
    if group == 'references' and batch:
        # A valid source ID for another work is not evidence for this key.
        # Keep all statuses and allow empty evidence, including honest gaps.
        rows = schema['properties']['references']
        branches = []
        for unit in batch:
            branch = json.loads(json.dumps(rows['items']))
            branch['properties']['key']['enum'] = [unit['key']]
            evidence = branch['properties']['evidence']
            ids = [source['id'] for source in sources
                   if unit['key'] in source['reference_keys']]
            if ids:
                evidence['items']['properties']['source_id']['enum'] = ids
            else:
                evidence['maxItems'] = 0
            branches.append(branch)
        rows['items'] = {'anyOf': branches}
    return schema


_STATUS_ORDER = {"error": 0, "gap": 1, "unchecked": 2, "verified": 3}


def evidence_splits(batches: list[list[dict[str, Any]]],
                    sources: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Record which passages were verified in evidence parts and with which sources."""
    splits: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        for unit in batch:
            info = unit.get("evidence_part")
            if info:
                keys = set(info["citation_keys"])
                splits.setdefault(unit["id"], []).append({
                    "part": info["part"], "of": info["of"], "citation_keys": list(info["citation_keys"]),
                    "source_ids": [s["id"] for s in sources if set(s["reference_keys"]) & keys]})
    return splits


def merge_evidence_parts(rows: list[dict[str, Any]], splits: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Combine the part rows of a split passage into one row; the verdict is their conjunction.

    Citation uses are disjoint across parts and are concatenated; every formula is
    judged in every part and keeps its least favourable verdict; prerequisites are
    concatenated. A missing part leaves its citation uses absent, which the exact
    coverage check then refuses.
    """
    def rank(row):
        status = row.get("status")
        advisory = ("finding_kind" in row and
                    (row["finding_kind"] == "advisory" or not row["reader_misconclusion"].strip()))
        # A cosmetic error in one part must not mask a material gap in another.
        return (status == "verified", advisory, _STATUS_ORDER.get(status, 0))

    merged: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for row in rows:
        pid = row.get("passage_id")
        if pid not in splits or pid not in index:
            if pid in splits:
                index[pid] = len(merged)
                merged.append(dict(row, coverage_rationale=f"[evidence part 1] {row.get('coverage_rationale', '')}",
                                   formulas=list(row.get("formulas", [])),
                                   citations=list(row.get("citations", [])),
                                   prerequisites=list(row.get("prerequisites", []))))
                merged[-1]["_parts"] = 1
            else:
                merged.append(row)
            continue
        target = merged[index[pid]]
        target["_parts"] += 1
        if rank(row) < rank(target):
            for field in ("status", "finding_kind", "reader_misconclusion"):
                if field in row:
                    target[field] = row[field]
        target["coverage_rationale"] += f"\n[evidence part {target['_parts']}] {row.get('coverage_rationale', '')}"
        target["citations"].extend(row.get("citations", []))
        target["prerequisites"].extend(row.get("prerequisites", []))
        formulas = {f.get("formula_id"): i for i, f in enumerate(target["formulas"])}
        for formula in row.get("formulas", []):
            i = formulas.get(formula.get("formula_id"))
            if i is None:
                target["formulas"].append(formula)
            elif rank(formula) < rank(target["formulas"][i]):
                target["formulas"][i] = formula
    for row in merged:
        parts = row.pop("_parts", None)
        if parts is not None and parts != len(splits[row["passage_id"]]):
            # A part produced no row: never report the passage as verified.
            row["status"] = "unchecked" if row.get("status") == "verified" else row.get("status")
    return merged


def batch_coverage(output: Mapping[str, Any], group: str, batch: list[dict[str, Any]],
                   *, followup: bool = False) -> None:
    """Refuse malformed nested IDs before accepting a provider's batch."""
    _validate_against_schema(output, report_schema(followup))
    _exact(output[group], "key" if group == "references" else "passage_id",
           {u["key" if group == "references" else "id"] for u in batch}, group)
    if output["passages" if group == "references" else "references"]:
        raise ValueError("Formal verifier reported items outside its batch")
    if group == "passages":
        units = {u["id"]: u for u in batch}
        for row in output[group]:
            unit = units[row["passage_id"]]
            _exact(row["formulas"], "formula_id", {f["id"] for f in unit["formulas"]}, "Formulas")
            _exact(row["citations"], "citation_id", {c["id"] for c in unit["citations"]}, "Citation uses")


# Follow-up scope names: the original one widened to every passage after an incomplete prior
# run and rescanned everything after a source-plan change; the targeted one (2026-11-23 audit)
# adds only the items that failed or whose primary source changed.
FOLLOWUP_SCOPE = "prior_blockers_and_changed_passages"
TARGETED_FOLLOWUP_SCOPE = "prior_blockers_failed_items_and_changed_passages"


def _delta_inventory(documents, bibliography, prior_documents, prior_inventory, blocked_roots, late=False,
                     scope=FOLLOWUP_SCOPE):
    """Map unchanged paragraphs across line moves and select prior negatives and edits."""
    inv = inventory(documents, bibliography)
    core = {p["id"]: p for p in verification_inventory(documents, bibliography)["passages"]}
    selected = set()
    tracked = set(blocked_roots)
    for doc in documents:
        current = [p for p in inv["passages"] if p["document"] == doc["id"]]
        previous = [p for p in prior_documents["passages"] if p["document"] == doc["id"]]
        matcher = difflib.SequenceMatcher(None, [p["text"] for p in previous],
                                         [p["text"] for p in current], autojunk=False)
        for tag, old_start, old_stop, start, stop in matcher.get_opcodes():
            if tag == "equal":
                tracked.update(p["id"] for old, p in zip(previous[old_start:old_stop], current[start:stop])
                               if old["id"] in blocked_roots)
                selected.update(p["id"] for old, p in zip(previous[old_start:old_stop], current[start:stop])
                                if old["id"] in blocked_roots)
            elif start == stop and current:
                # Review the surviving neighbors when a deletion changes context.
                selected.update(p["id"] for p in current[max(0, start - 1):start + 1])
            else:
                selected.update(p["id"] for p in current[start:stop])
    old_refs = {r["key"]: r for r in prior_inventory["references"]}
    changed_refs = {r["key"] for r in inv["references"]
                    if r != old_refs.get(r["key"]) or r["key"] in blocked_roots}
    # A bibliographic change also warrants checking its use.
    passages = [p for p in inv["passages"] if p["id"] in selected
                or any(c["key"] in changed_refs for c in p["citations"])]
    passages = [core.get(p["id"], dict(p, formulas=[])) for p in passages]
    return dict(inv, **({"previous_blocker_roots": sorted(tracked)} if late else {}), followup=True, passages=passages,
                task_reference_keys=sorted(changed_refs),
                proof_context={pid: {"text": p["text"]} for pid, p in core.items()},
                scope={"name": scope})


def _source_plan_changes(prior: Mapping[str, Any], metadata: Mapping[str, Any]) -> set[str] | None:
    """Reference keys whose declared primary source differs from the one the prior run used.

    None when the prior run's sources cannot be compared (then the whole run repeats)."""
    try:
        plan = source_plan(metadata).get("sources") or []
    except ValueError:
        return None
    used = prior.get("sources")
    if not isinstance(used, list):
        return None

    def ident(source: Mapping[str, Any]) -> tuple:
        return (str(source.get("url")), tuple(sorted(source.get("reference_keys") or [])),
                tuple(source.get("pages") or ()), str(source.get("kind")),
                str(source.get("extraction_method", "text")))

    old = {ident(source) for source in used if isinstance(source, Mapping)}
    new = {ident(source) for source in plan}
    return {key for source in old ^ new for key in source[1]}


def _followup_inventory(binding, metadata, root, role, documents, bibliography, late=False, targeted=True):
    if not binding:
        return None
    path = _safe_file(root, binding["path"])
    raw = path.read_bytes()
    if sha(raw) != binding["sha256"]:
        raise ValueError("Previous formal-check report changed")
    prior = json.loads(raw)
    if prior["paper_id"] != metadata["paper_id"] or prior["role"] != dict(role) or not policy_accepted(prior["policy"]):
        return None
    plan_changed: set[str] = set()
    if prior["source_plan_sha256"] != digest(source_plan(metadata)):
        changed = _source_plan_changes(prior, metadata) if targeted else None
        if changed is None:
            return None
        plan_changed = changed
    findings = prior["issue_summary"]["raw_findings"]
    old_inv = prior["inventory"]
    failed = [f for f in findings if f["category"] in {"technical", "source_routing", "preparation"}]
    incomplete = bool(failed)
    if incomplete and not old_inv.get("followup") and not targeted:
        return None
    old_docs = prior.get("documents")
    if old_docs is None:
        if not prior["receipts"]:
            return None
        # Legacy receipts already bind the complete manuscript in their packet.
        first = prior["receipts"][0]
        prompt = _safe_file(root, first["workdir"] + "/prompt.txt").read_bytes()
        system = _safe_file(root, first["workdir"] + "/system.txt").read_bytes()
        if sha(prompt) != first["receipt"]["prompt_sha256"] or not prompt.startswith(system + b"\n\n"):
            raise ValueError("Previous formal-check manuscript evidence changed")
        old_docs = json.loads(prompt[len(system) + 2:])["complete_manuscript"]
    if digest(old_docs) != old_inv["documents_sha256"]:
        raise ValueError("Previous formal-check manuscript does not match its inventory")
    old_bib = "\n\n".join(r["text"] for r in old_inv["references"])
    roots = {f["root"] for f in findings if f["category"] == "scientific"}
    if incomplete and not targeted:
        roots.update(p["id"] for p in old_inv["passages"])
        roots.update(r["key"] for r in _task_references(old_inv))
    elif incomplete:
        # Only what failed: its root, or the passages and references its message names.
        full = inventory(old_docs, old_bib)
        known = {p["id"] for p in full["passages"]} | {r["key"] for r in old_inv["references"]}
        for finding in failed:
            text = f"{finding.get('message') or ''} {finding.get('location') or ''}"
            named = {name for name in known
                     if name and re.search(r"(?<![\w:.-])" + re.escape(name) + r"(?![\w-])", text)}
            if finding.get("root") in known:
                named.add(finding["root"])
            if not named and not old_inv.get("followup"):
                return None  # the first complete scan failed somewhere unknown: repeat it once
            roots.update(named)
    roots.update(plan_changed)
    return _delta_inventory(documents, bibliography, inventory(old_docs, old_bib), old_inv, roots, late,
                            scope=TARGETED_FOLLOWUP_SCOPE if targeted else FOLLOWUP_SCOPE)


def _task_references(inv):
    keys = inv.get("task_reference_keys")
    return inv["references"] if keys is None else [r for r in inv["references"] if r["key"] in keys]


def run_checks(pre: Mapping[str, Any], root: Path, run: Path, role: Mapping[str, Any],
               timeout: int, runner) -> dict[str, Any]:
    if role.get("provider") not in FORMAL_PROVIDERS:
        raise ValueError("Formal verification requires an independent Codex or Antigravity role")
    metadata = pre["metadata"]
    documents, bibliography = current_inputs(metadata, root)
    prior = pre.get("previous_formal_check")
    inv = _followup_inventory(prior, metadata, root, role, documents, bibliography, pre.get("require_late_reason", False))
    if inv is None:
        inv = verification_inventory(documents, bibliography)
        prior = None
        if pre.get("materiality"):
            inv["materiality"] = True
    directory = run / "formal-check"
    directory.mkdir()
    findings = []
    source_inv = inv
    if inv.get("followup"):
        keys = set(inv["task_reference_keys"]) | {c["key"] for p in inv["passages"] for c in p["citations"]}
        source_inv = dict(inv, references=[ref for ref in inv["references"] if ref["key"] in keys])
    source_metadata = verification_source_metadata(metadata, inv)
    routes = local_route_preflight(source_metadata, inventory(documents, bibliography), root)
    # PDF/ZIP identity is enforced by preflight/release, not a mathematical premise.
    artifacts = {}
    with httpx.Client(timeout=httpx.Timeout(30, connect=15), follow_redirects=True) as client:
        unreachable: dict[str, list[str]] = {}
        sources, errors = ([], routes) if routes else collect_sources(source_inv, source_metadata, root, directory / "evidence",
                                                                     client, unreachable)
    for message in errors:
        findings.append({'category': 'source_routing', 'root': '', 'location': '', 'message': message,
                         'aggregate': False, 'reason': message, 'status': None})
    report = {"references": [], "passages": []}
    materiality = bool(inv.get("followup") or inv.get("materiality"))
    receipts = []
    splits: dict[str, list[dict[str, Any]]] = {}
    # A lookup problem of single references (no catalog URL; an identifier no service knows or
    # that names another record) stays a blocker of that reference but no longer stops the
    # verifier for the rest of the manuscript (2026-11-26, slimming batch 2: one such reference
    # left every batch unrun, a coverage failure blocked the round and the next round audited
    # everything again; 9 of 25 formal_check_blocked rounds since 2026-11-22). Its items are
    # judged as before (no evidence: not verified). Declared-route problems and an outage of
    # every service still stop the run.
    reference_keys = {r["key"] for r in inv["references"]}
    scoped = [] if routes else [e for e in errors if e.split(":", 1)[0] in reference_keys]
    if len(scoped) == len(errors):
        # Small output batches, full manuscript context, no truncated source.
        for group in ("references", "passages"):
            batches = packet_batches(group, documents, inv, sources, root=root, artifacts=artifacts)
            if group == "passages":
                splits = evidence_splits(batches, sources)
            for batch_number, batch in enumerate(batches, 1):
                packet = batch_packet(group, batch, documents, inv, sources, root=root, artifacts=artifacts)
                if len(packet.encode()) > MAX_PACKET:
                    message = "Formal-check packet exceeds the context budget; register precise primary chapter/page sources, never truncate evidence"
                    errors.append(message)
                    findings.append({'category':'source_routing','root':'','location':'','message':message,'aggregate':False,'reason':message,'status':None})
                    break
                try:
                    output, receipt = runner(role_name=f"formal_{group}_{batch_number}", role=role,
                        system_prompt=PROMPT.read_text(), user_prompt=packet, schema=batch_schema(group, batch, inv, sources),
                        workdir=directory / f"{group}-{batch_number}", timeout=timeout)
                except (LaunchError, ValueError, OSError) as exc:
                    message = f"{group} batch {batch_number}: actual verifier failed: {exc}"
                    errors.append(message)
                    findings.append({'category':'technical','root':'','location':'','message':message,'aggregate':False,'reason':message,'status':None})
                    continue
                try:
                    batch_coverage(output, group, batch, followup=materiality)
                except (LaunchError, ValueError, OSError) as exc:
                    message = f"{group} batch {batch_number}: coverage protocol failure: {exc}"
                    errors.append(message)
                    findings.append({'category':'technical','root':'','location':'','message':message,'aggregate':False,'reason':message,'status':None})
                    # Retain the actual JSON and receipt; never rewrite IDs or
                    # discard a negative role in favor of a passing retry.
                    if not isinstance(output, dict) or not isinstance(output.get(group), list):
                        continue
                report[group].extend(output[group])
                workdir = directory / f"{group}-{batch_number}"
                receipts.append({"receipt": receipt, "group": group,
                    "workdir": workdir.relative_to(root).as_posix()})
    report["passages"] = merge_evidence_parts(report["passages"], splits)
    unverifiable_items: list[dict[str, Any]] = []
    try:
        errors.extend(report_blockers(report, inv, sources, findings=findings, artifacts=artifacts,
                                      unverifiable_keys=unreachable, unverifiable_out=unverifiable_items,
                                      followup=materiality))
    except (ValueError, LaunchError) as exc:
        message = f"Coverage/evidence verification failed: {exc}"
        errors.append(message)
        findings.append({'category':'technical','root':'','location':'','message':message,'aggregate':False,'reason':message,'status':None})
        # A malformed batch must not hide actual scientific negatives already
        # returned elsewhere, or turn a mixed run into a free technical retry.
        for group in ('references', 'passages'):
            for row in report[group]:
                root_id = str(row.get('passage_id', row.get('key', '')))
                def retain(value, location):
                    if isinstance(value, dict):
                        if (value.get('status') in {'error','gap','unchecked'}
                                and not _nonmathematical_unchecked_citation(value)):
                            if not any(f['root']==root_id and f['location']==location and f.get('status') for f in findings):
                                findings.append({'category':'scientific','root':root_id,'location':location,
                                    'message':f"{location}: {value['status']}",'aggregate':location==root_id,
                                    'reason':json.dumps(value,ensure_ascii=False),'status':value['status']})
                        for k,v in value.items(): retain(v,location+'/'+k)
                    elif isinstance(value,list):
                        for i,v in enumerate(value):retain(v,location+'/'+str(i))
                retain(row,root_id)
    summary = issue_summary(findings)
    result = {"schema": VERSION, "paper_id": metadata["paper_id"], "manuscript_version": str(metadata.get("version") or ""),
        "policy": policy(), "role": dict(role), "inventory": inv,
        "source_plan_sha256": digest(source_plan(metadata)), "sources": sources,
        "evidence_splits": splits, "report": report, "receipts": receipts, "blockers": errors, "valid": not errors,
        "issue_summary": summary, "artifact_inventory": artifacts,
        # Not manuscript defects: records that could not be obtained here. They do
        # not block readiness or consume a review round; verify them manually or
        # from another environment before delivery.
        "unverifiable_source_access": {"references": dict(sorted(unreachable.items())),
                                       "items": unverifiable_items},
        "machine_proof_of_whole_manuscript": False, "verified_at": datetime.now(UTC).isoformat()}
    result["documents"] = documents
    if prior:
        result["previous_formal_check"] = {key: prior[key] for key in ("path", "sha256")}
    path = directory / "report.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    binding = {"path": path.relative_to(root).as_posix(), "sha256": sha(path.read_bytes()),
               "valid": result["valid"], "blockers": errors, "schema": VERSION,
               "issue_summary": summary}
    if unreachable or unverifiable_items:
        binding["unverifiable_source_access"] = result["unverifiable_source_access"]
    return binding


def archived_inputs(result: Mapping[str, Any], root: Path) -> tuple[list[dict[str, str]], str]:
    """Recover the exact documents and bibliography from a bound formal packet."""
    documents = result.get("documents")
    if documents is None:
        first = result["receipts"][0]
        prompt = _safe_file(root, first["workdir"] + "/prompt.txt").read_bytes()
        system = _safe_file(root, first["workdir"] + "/system.txt").read_bytes()
        if sha(prompt) != first["receipt"]["prompt_sha256"] or not prompt.startswith(system + b"\n\n"):
            raise ValueError("Archived formal-check packet changed")
        documents = json.loads(prompt[len(system) + 2:])["complete_manuscript"]
    return documents, "\n\n".join(row["text"] for row in result["inventory"]["references"])


def validate_binding(binding: Any, metadata: Mapping[str, Any], root: Path,
                     expected_role: Mapping[str, Any] | None = None, *,
                     archived_version: str | None = None, precision: bool = False,
                     accepting: bool = False) -> list[str]:
    """Revalidate evidence bytes, exact coverage and policy at apply/handoff.

    With ``precision`` (a decision synthesized under ``PRECISION_RULE``) an invalid report is
    accepted when every blocker it records is a downgraded scientific gap or source-routing
    note; the remaining (material) blockers are returned. With ``accepting`` (both referees
    at minor revision or accept, UD-20261126-review-pass-two-minor) a verifier technical
    failure (as opposed to a verified manuscript error) also does not block.
    """
    strict = archived_version is None and not precision and not accepting
    try:
        if not isinstance(binding, Mapping) or binding.get("schema") != VERSION or (strict and binding.get("valid") is not True):
            raise ValueError("Missing passing mandatory formal check; rerun unified review")
        if accepting and "path" not in binding:
            # Stage exception before a report file was written (e.g. verifier outage): allow
            # only when the recorded summary carries technical failure(s) and no scientific or
            # preparation blocker.
            cats = (binding.get("issue_summary") or {}).get("by_category") or {}
            if cats.get("scientific") or cats.get("preparation") or not cats.get("technical"):
                raise ValueError("Missing passing mandatory formal check; rerun unified review")
            return []
        path = _safe_file(root, binding["path"])
        if sha(path.read_bytes()) != binding["sha256"]:
            raise ValueError("Formal-check report changed")
        result = json.loads(path.read_text())
        if result.get("paper_id") != metadata.get("paper_id") or result.get("manuscript_version") != (archived_version if archived_version is not None else str(metadata.get("version") or "")):
            raise ValueError("Formal-check paper/version identity mismatch")
        if not policy_accepted(result["policy"]) or (strict and (
                result["valid"] is not True or result["blockers"])):
            raise ValueError("Formal-check policy changed or verification is incomplete")
        if expected_role is not None and result.get("role") != dict(expected_role):
            raise ValueError("Formal verification used a different configured role")
        if result["source_plan_sha256"] != digest(source_plan(metadata)):
            raise ValueError("Registered primary-source plan changed")
        documents, bibliography = (archived_inputs(result, root) if archived_version is not None
                                   else current_inputs(metadata, root))
        prior = result.get("previous_formal_check")
        if prior and _safe_file(root, prior["path"]).parent.parent >= path.parent.parent:
            raise ValueError("Previous formal check must precede this run")
        targeted = (result["inventory"].get("scope") or {}).get("name") == TARGETED_FOLLOWUP_SCOPE
        expected_inv = (_followup_inventory(prior, metadata, root, result["role"], documents, bibliography,
                                            "previous_blocker_roots" in result["inventory"], targeted=targeted)
                        if prior else verification_inventory(documents, bibliography))
        if not prior and result["inventory"].get("materiality") is True:
            expected_inv["materiality"] = True
        if result["inventory"] != expected_inv:
            raise ValueError("Formal-check coverage does not match current manuscript and bibliography")
        if result.get('artifact_inventory') != {}:
            raise ValueError('Preparation artifacts are outside the mathematical scope')
        if local_route_preflight(verification_source_metadata(metadata, result['inventory']), inventory(documents, bibliography), root):
            raise ValueError('Current local source routing is invalid')
        for source in result["sources"]:
            for field in ("body", "text"):
                evidence_path = _safe_file(root, source[field + "_path"])
                if sha(evidence_path.read_bytes()) != source[field + "_sha256"]:
                    raise ValueError("Retrieved primary evidence changed or is missing")
            retrieval = source.get("retrieval")
            if isinstance(retrieval, Mapping) and retrieval.get("method") == "download_bridge":
                bridged = _safe_file(root, str(retrieval.get("bridge_file") or ""))
                if (sha(bridged.read_bytes()) != retrieval.get("bridge_file_sha256")
                        or retrieval.get("bridge_file_sha256") != source["body_sha256"]):
                    raise ValueError("Bridge-retrieved evidence changed or differs from the bound body")
            # Publisher text may contain CRLF/CR. Preserve the same UTF-8
            # bytes whose SHA was just checked; read_text translates newlines.
            if _safe_file(root, source["text_path"]).read_bytes().decode("utf-8") != source["text"]:
                raise ValueError("Reported source text differs from the actual evidence file")
        recorded_cats = (result.get("issue_summary") or {}).get("by_category") or {}
        if accepting and recorded_cats.get("technical") and (
                not result["receipts"] or len(result["receipts"]) != len(
                    [(g, b) for g in ("references", "passages")
                     for b in packet_batches(g, documents, result["inventory"],
                                             result["sources"], root=root, artifacts=result['artifact_inventory'])])):
            # A batch/coverage technical failure left the formal run incomplete; still verify
            # every recorded receipt's integrity and block on any retained scientific/preparation error.
            for item in result["receipts"]:
                receipt, workdir = item["receipt"], item["workdir"]
                for filename, expected in (("output.json", receipt["output_sha256"]),
                                           ("prompt.txt", receipt["prompt_sha256"]),
                                           ("system.txt", receipt["system_prompt_sha256"])):
                    if sha(_safe_file(root, workdir + "/" + filename).read_bytes()) != expected:
                        raise ValueError("Formal role inputs or actual output changed")
                if json.loads(_safe_file(root, workdir + "/receipt.json").read_text()) != receipt:
                    raise ValueError("Formal role receipt changed")
            if binding.get("issue_summary", result["issue_summary"]) != result["issue_summary"]:
                raise ValueError("Formal verdict differs from the independently verified outputs")
            return material_blockers(result["blockers"], result["issue_summary"],
                                     finding_kinds(result["report"]), accepting=True)[0]
        if not result["receipts"] and not prior:
            raise ValueError("Formal verification lacks independent actual-model receipts")
        materiality = bool(prior or result["inventory"].get("materiality"))
        reconstructed = {"references": [], "passages": []}
        expected_batches = [(group, batch) for group in ("references", "passages")
                            for batch in packet_batches(group, documents, result["inventory"],
                                result["sources"], root=root, artifacts=result['artifact_inventory'])]
        if len(result["receipts"]) != len(expected_batches):
            raise ValueError("Formal role batch coverage is incomplete or duplicated")
        for item, (expected_group, batch) in zip(result["receipts"], expected_batches):
            receipt, workdir, group = item["receipt"], item["workdir"], item["group"]
            if group != expected_group:
                raise ValueError("Formal role batch order/scope changed")
            schema = batch_schema(group, batch, result['inventory'], result['sources'])
            if (receipt.get("independent_context") is not True
                    or receipt.get("provider") != result["role"].get("provider")
                    or receipt.get("provider") not in FORMAL_PROVIDERS
                    or receipt.get("model") != result["role"].get("model")
                    or receipt.get("model") not in receipt.get("runtime_reported_models", [])
                    or receipt.get("schema_sha256") != sha(json.dumps(schema, sort_keys=True).encode())):
                raise ValueError("Formal verification lacks matching independent actual-model receipts")
            for filename, expected in (("output.json", receipt["output_sha256"]),
                                       ("prompt.txt", receipt["prompt_sha256"]),
                                       ("system.txt", receipt["system_prompt_sha256"])):
                if sha(_safe_file(root, workdir + "/" + filename).read_bytes()) != expected:
                    raise ValueError("Formal role inputs or actual output changed")
            actual_receipt = json.loads(_safe_file(root, workdir + "/receipt.json").read_text())
            if actual_receipt != receipt:
                raise ValueError("Formal role receipt changed")
            # The stored system prompt is bound by its receipt hash above. It is
            # not compared with today's prompt file: prompt edits are governed by
            # POLICY_VERSION, while the manuscript batch must still match exactly.
            system_text = _safe_file(root, workdir + "/system.txt").read_text()
            stored_prompt = _safe_file(root, workdir + "/prompt.txt").read_text()
            expected_prompt = system_text + "\n\n" + batch_packet(group, batch, documents, result["inventory"], result["sources"], root=root, artifacts=result['artifact_inventory'])
            recorded_root = _recorded_evidence_root(stored_prompt, system_text)
            if stored_prompt != expected_prompt and recorded_root not in (None, str(root.resolve())):
                # The review ran in another checkout (an attempt's review scratch root) and the
                # paper was then adopted into this one: only the evidence-root label may differ;
                # every manuscript, batch and source byte must still match exactly.
                expected_prompt = system_text + "\n\n" + batch_packet(group, batch, documents, result["inventory"], result["sources"], root=root, artifacts=result['artifact_inventory'], evidence_root=recorded_root)
            if stored_prompt != expected_prompt:
                raise ValueError("Formal role did not inspect the exact bound manuscript, batch and source evidence")
            output = json.loads(_safe_file(root, workdir + "/output.json").read_text())
            _validate_against_schema(output, schema)
            batch_coverage(output, group, batch, followup=materiality)
            reconstructed[group].extend(output[group])
        expected_splits = evidence_splits([batch for group, batch in expected_batches if group == "passages"],
                                          result["sources"])
        if result.get("evidence_splits", {}) != expected_splits:
            raise ValueError("Formal evidence parts differ from the deterministic partition")
        reconstructed["passages"] = merge_evidence_parts(reconstructed["passages"], expected_splits)
        if reconstructed != result["report"]:
            raise ValueError("Formal report differs from the actual independent outputs")
        findings = []
        access = result.get("unverifiable_source_access") or {}
        if not isinstance(access, Mapping) or not isinstance(access.get("references", {}), Mapping):
            raise ValueError("Malformed unverifiable-source record")
        if access and binding.get("unverifiable_source_access", access) != access:
            raise ValueError("Formal binding misreports unverifiable sources")
        keys = set(access.get("references", {}))
        if keys & {k for s in result["sources"] for k in s["reference_keys"]}:
            raise ValueError("A reference is recorded both as retrieved and as unverifiable")
        blockers = report_blockers(result["report"], result["inventory"], result["sources"],
                                   findings=findings, artifacts=result['artifact_inventory'],
                                   unverifiable_keys=keys, followup=materiality)
        if result.get('issue_summary') != issue_summary(findings):
            raise ValueError('Formal issue summary differs from actual raw findings')
        if archived_version is not None:
            if (blockers != result["blockers"] or binding.get("blockers") != blockers
                    or result["valid"] != (not blockers) or binding.get("valid") != result["valid"]
                    or binding.get("issue_summary") != result["issue_summary"]):
                raise ValueError("Archived formal verdict differs from the independently verified outputs")
            return []
        if precision or accepting:
            if (blockers != result["blockers"] or binding.get("blockers", blockers) != blockers
                    or binding.get("issue_summary", result["issue_summary"]) != result["issue_summary"]):
                raise ValueError("Formal verdict differs from the independently verified outputs")
            return material_blockers(blockers, result["issue_summary"], finding_kinds(result["report"]),
                                     accepting=accepting)[0]
        return blockers
    except (ValueError, KeyError, IndexError, TypeError, OSError, LaunchError) as exc:
        return [f"Mandatory formal check: {exc}"]


def packet(binding: Mapping[str, Any], root: Path) -> str:
    result = json.loads(_safe_file(root, binding["path"]).read_text())
    return ("\n## Mandatory bibliography and prerequisite verification\n"
            "This is an evidence-bound independent audit, not a machine proof of the entire manuscript. "
            "Check for misclassified or omitted dependencies and any overclaimed verification.\n"
            + json.dumps({"binding": binding, "evidence_root": str(root.resolve()), "report": result["report"],
                          "source_records": [{k: v for k, v in s.items() if k != "text"} for s in result["sources"]]},
                         ensure_ascii=False, indent=2) + "\n")
