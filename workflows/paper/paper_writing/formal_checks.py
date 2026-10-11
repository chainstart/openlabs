"""Mandatory, evidence-bound bibliography and prerequisite verification.

Coverage and evidence integrity are checked by code. Scientific judgments are
made in fresh verifier processes and checked again by the ordinary referee.
This is not a claim that an entire manuscript has been machine proved.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, unquote, urlsplit
import xml.etree.ElementTree as ET

import httpx

from paper_writing.review_launcher import LaunchError, _validate_against_schema

VERSION = "openlabs.formal_check.v1"
PROMPT = Path(__file__).resolve().parents[1] / "skills/openlabs-paper-review/references/unified/formal.md"
MAX_DOWNLOAD = 20_000_000
MAX_PACKET = 600_000
BATCH_SIZE = 8
STATUSES = ["verified", "error", "gap", "unchecked"]
TEXT = {"type": "string"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def policy() -> dict[str, Any]:
    # A changed implementation or prompt requires a fresh gate, even if an old
    # decision happens to have the same manuscript/source hashes.
    return {"schema": VERSION, "mandatory": True, "implementation_sha256": sha(Path(__file__).read_bytes()),
            "prompt_sha256": sha(PROMPT.read_bytes()), "schema_sha256": digest(REPORT_SCHEMA)}


def object_schema(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(fields), "properties": dict(fields)}


def array(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


EVIDENCE = array(object_schema({"source_id": TEXT, "locator": TEXT, "quote": TEXT}))
STATUS = {"type": "string", "enum": STATUSES}
REFERENCE_SCHEMA = object_schema({"key": TEXT, "status": STATUS,
    "authors_check": TEXT, "title_check": TEXT, "year_check": TEXT,
    "venue_identifier_locator_check": TEXT, "primary_source_check": TEXT,
    "publication_status_check": TEXT, "evidence": EVIDENCE})
FORMULA_SCHEMA = object_schema({"formula_id": TEXT, "status": STATUS,
    "assumptions": TEXT, "derivation_or_source_check": TEXT, "evidence": EVIDENCE})
CITATION_SCHEMA = object_schema({"citation_id": TEXT, "key": TEXT, "status": STATUS,
    "manuscript_claim": TEXT, "support_check": TEXT, "evidence": EVIDENCE})
PREREQUISITE_SCHEMA = object_schema({"statement": TEXT, "status": STATUS,
    "reference_keys": array(TEXT), "original_locator": TEXT, "original_assumptions": TEXT,
    "original_conclusion": TEXT, "manuscript_instantiation": TEXT,
    "condition_check": TEXT, "formula_check": TEXT, "evidence": EVIDENCE})
PASSAGE_SCHEMA = object_schema({"passage_id": TEXT, "status": STATUS,
    "coverage_rationale": TEXT, "prerequisites": array(PREREQUISITE_SCHEMA),
    "formulas": array(FORMULA_SCHEMA), "citations": array(CITATION_SCHEMA)})
REPORT_SCHEMA = object_schema({"references": array(REFERENCE_SCHEMA), "passages": array(PASSAGE_SCHEMA)})


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
        for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.S):
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
            if row["key"] in references and references[row["key"]] != row:
                raise ValueError(f"Conflicting bibliography key across manuscript documents: {row['key']}")
            references[row["key"]] = row
    return documents, "\n\n".join(row["text"] for row in references.values())


def _url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("Formal evidence requires an HTTPS source URL without credentials or fragments")
    return url


def _text_document(body: bytes, content_type: str, directory: Path, sid: str, pages: list[int] | None = None) -> str:
    if body.startswith(b"%PDF-") or "application/pdf" in content_type:
        pdf, text = directory / (sid + ".pdf"), directory / (sid + ".txt")
        pdf.write_bytes(body)
        command = ["pdftotext", "-layout"]
        if pages:
            command += ["-f", str(pages[0]), "-l", str(pages[1])]
        subprocess.run([*command, str(pdf), str(text)], check=True,
                       capture_output=True, timeout=60)
        return text.read_text(errors="replace")
    if pages:
        raise ValueError("PDF page selection requires an actual PDF")
    text = body.decode("utf-8", errors="replace")
    if "html" in content_type:
        text = re.sub(r"<(script|style)\b.*?</\1>", "", text, flags=re.S | re.I)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return text


def source_plan(metadata: Mapping[str, Any]) -> dict[str, Any]:
    value = metadata.get("formal_check", {})
    if not isinstance(value, Mapping) or set(value) - {"sources"}:
        raise ValueError("formal_check accepts only a sources list; the mandatory gate cannot be disabled")
    sources = value.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("formal_check.sources must be a list")
    for source in sources:
        if (not isinstance(source, Mapping) or set(source) - {"reference_keys", "url", "kind", "pages"}
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
    return dict(value)


def collect_sources(inv: Mapping[str, Any], metadata: Mapping[str, Any], root: Path,
                    directory: Path, client: httpx.Client) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch public primary records. Failure is retained as unknown, never success."""
    directory.mkdir(parents=True, exist_ok=True)
    sources, errors, seen = [], [], {}
    plan = source_plan(metadata)
    reference_keys = {r["key"] for r in inv["references"]}
    for item in plan.get("sources", []):
        if set(item["reference_keys"]) - reference_keys:
            raise ValueError("Primary-source plan refers to an absent bibliography key")

    def fetch(url: str, kind: str, keys: list[str], pages: list[int] | None = None) -> dict[str, Any]:
        url = _url(url)
        initial_host = host = urlsplit(url).hostname
        if host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"}:
            kind = "bibliographic_metadata"
        identity = (url, kind, tuple(pages or []))
        if identity in seen:
            source = seen[identity]
            source["reference_keys"] = sorted(set(source["reference_keys"]) | set(keys))
            return source
        with client.stream("GET", url, headers={"User-Agent": "OpenLabs-formal-check/1.0"}) as response:
            response.raise_for_status()
            final_url = _url(str(response.url))
            host = urlsplit(final_url).hostname
            if host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"}:
                kind = "bibliographic_metadata"
            record_url = url if initial_host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"} else final_url
            record_host = host if host in {"api.crossref.org", "api.datacite.org", "export.arxiv.org"} else initial_host
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError("Primary evidence exceeds the download limit; supply a precise official chapter/page endpoint")
                chunks.append(chunk)
            body = b"".join(chunks)
            content_type = response.headers.get("content-type", "")
        sid = "S" + sha(json.dumps(identity).encode())[:20]
        text = _text_document(body, content_type, directory, sid, pages)
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
            "extraction_pages": pages, "text": text}
        sources.append(source); seen[identity] = source
        return source

    # The exact current support record may be an authenticated draft until the
    # post-review publication step. It is never evidence about external theory.
    publication = (metadata.get("support") or {}).get("publication") or {}
    support_key = publication.get("bibliography_key")
    for ref in inv["references"]:
        key, raw = ref["key"], ref["text"]
        doi = re.search(r"10\.\d{4,9}/[^\s{}<>\"]+", raw, re.I)
        arxiv = re.search(r"(?:arxiv(?:\.org/(?:abs|pdf)/|\s*:\s*))((?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?)", raw, re.I)
        if key == support_key and publication.get("status") != "published":
            from paper_writing.support_citations import audit_manuscript_support
            audit = audit_manuscript_support(str(metadata["paper_id"]), root=root)
            receipt_name = publication.get("draft_receipt")
            if not audit["valid"] or not receipt_name:
                errors.append(f"{key}: current prepublication support has no valid authenticated draft evidence")
                continue
            receipt = _safe_file(root, receipt_name)
            body = receipt.read_bytes()
            sid = "S" + sha(body)[:20]
            path = directory / (sid + ".text")
            raw_receipt = json.loads(body)
            # Do not forward authenticated edit/upload links into model inputs.
            text = json.dumps({k: raw_receipt[k] for k in
                ("id", "metadata", "doi", "submitted", "state") if k in raw_receipt}, ensure_ascii=False, indent=2)
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
        failures = []
        for url, kind in candidates:
            try:
                document = fetch(url, kind, [key])
                # Primary full text links are optional discovery aids. Their
                # availability is still judged per actual citation/application.
                if "api.crossref.org" in url:
                    data = json.loads(document["text"]).get("message", {})
                    for link in data.get("link", [])[:2]:
                        if link.get("content-type") == "application/pdf":
                            try:
                                fetch(link["URL"], "primary_text", [key])
                            except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                                pass
                if arxiv:
                    try:
                        fetch("https://arxiv.org/pdf/" + arxiv.group(1), "primary_text", [key])
                    except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                        pass
                break
            except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError) as exc:
                failures.append(f"{url}: {type(exc).__name__}")
        else:
            if candidates:
                errors.append(f"{key}: authoritative identifier lookup unresolved ({'; '.join(failures)})")
    for item in plan.get("sources", []):
        try:
            fetch(item["url"], item["kind"], list(item["reference_keys"]), item.get("pages"))
        except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError) as exc:
            errors.append(f"Declared primary source unavailable: {item['url']} ({type(exc).__name__})")
    for ref in inv["references"]:
        # Official links printed in a bibliography are discovery inputs, not
        # automatically trusted certificates. The verifier still has to check
        # source ownership, exact work identity and substantive support.
        for url in list(dict.fromkeys(re.findall(r"https://[^\s{}<>\"]+", ref["text"])))[:3]:
            url = url.rstrip(".,;)")
            if url.startswith(("https://doi.org/", "https://arxiv.org/abs/")):
                continue
            try:
                fetch(url, "primary_text", [ref["key"]])
            except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError):
                pass
    # A publisher's catalog/primary text can also establish a work without DOI.
    for ref in inv["references"]:
        if not any(ref["key"] in s["reference_keys"] for s in sources):
            errors.append(f"{ref['key']}: no queryable authoritative evidence; register an official primary source URL")
    # Another authoritative primary record may resolve a provider outage. Keep
    # all failed lookups in a separate, immutable attempt log; never silently
    # invent success for those requests.
    attempts_path = directory / "retrieval-failures.json"
    attempts_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2) + "\n")
    errors = [e for e in errors if not ("authoritative identifier lookup unresolved" in e
        and any(e.split(":", 1)[0] in s["reference_keys"] and s["kind"] in {"primary_text", "publisher_catalog"}
                for s in sources))]
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


def report_blockers(report: Mapping[str, Any], inv: Mapping[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    """Check exact coverage and quoted evidence independently of model verdicts."""
    _validate_against_schema(report, REPORT_SCHEMA)
    _exact(report["references"], "key", {r["key"] for r in inv["references"]}, "References")
    _exact(report["passages"], "passage_id", {p["id"] for p in inv["passages"]}, "Passages")
    source_by_id = {s["id"]: s for s in sources}
    if len(source_by_id) != len(sources):
        raise ValueError("Duplicated evidence source IDs")
    blockers = []

    def evidence(items: list[dict[str, str]], keys: set[str], *, primary: bool = False) -> None:
        if not items:
            raise ValueError("Verified external claims require located source evidence")
        represented = set()
        for item in items:
            source = source_by_id.get(item["source_id"])
            if source is None or not item["locator"].strip() or len(item["quote"].strip()) < 12:
                raise ValueError("Evidence has an unknown source, empty locator or insufficient quotation")
            if item["quote"] not in source["text"]:
                raise ValueError("Quoted evidence is absent from the retrieved primary source")
            if primary and source["kind"] != "primary_text":
                raise ValueError("A prerequisite requires original primary text, not metadata or an abstract")
            represented |= set(source["reference_keys"])
        if not keys <= represented:
            raise ValueError("Evidence does not bind every claimed reference key")

    def checked(row: Mapping[str, Any], label: str, fields: tuple[str, ...]) -> bool:
        if row["status"] != "verified":
            blockers.append(f"{label}: {row['status']}")
            return False
        if any(not row[field].strip() for field in fields):
            raise ValueError(f"{label}: a verified item lacks its check rationale")
        return True

    for row in report["references"]:
        if checked(row, row["key"], ("authors_check", "title_check", "year_check", "venue_identifier_locator_check",
                                    "primary_source_check", "publication_status_check")):
            evidence(row["evidence"], {row["key"]})
    inv_passages = {p["id"]: p for p in inv["passages"]}
    for row in report["passages"]:
        unit = inv_passages[row["passage_id"]]
        checked(row, row["passage_id"], ("coverage_rationale",))
        _exact(row["formulas"], "formula_id", {f["id"] for f in unit["formulas"]}, "Formulas")
        _exact(row["citations"], "citation_id", {c["id"] for c in unit["citations"]}, "Citation uses")
        cites = {c["id"]: c["key"] for c in unit["citations"]}
        for item in row["citations"]:
            if item["key"] != cites[item["citation_id"]]:
                raise ValueError("Citation-use report changes the cited reference")
            if checked(item, item["citation_id"], ("manuscript_claim", "support_check")):
                evidence(item["evidence"], {item["key"]})
        for item in row["formulas"]:
            if checked(item, item["formula_id"], ("assumptions", "derivation_or_source_check")) and item["evidence"]:
                evidence(item["evidence"], set(), primary=True)
        for item in row["prerequisites"]:
            if checked(item, row["passage_id"] + ": " + item["statement"],
                       ("statement", "original_locator", "original_assumptions", "original_conclusion",
                        "manuscript_instantiation", "condition_check", "formula_check")):
                keys = set(item["reference_keys"])
                if not keys or keys - {r["key"] for r in inv["references"]}:
                    raise ValueError("External prerequisite has no valid cited source key")
                evidence(item["evidence"], keys, primary=True)
    return blockers


def batch_packet(group: str, batch: list[dict[str, Any]], documents: list[dict[str, str]],
                 inv: Mapping[str, Any], sources: list[dict[str, Any]]) -> str:
    keys = ({r["key"] for r in batch} if group == "references" else
            {c["key"] for p in batch for c in p["citations"]})
    selected = [s for s in sources if set(s["reference_keys"]) & keys
                or (group == "passages" and s["kind"] == "bibliographic_metadata")]
    scoped_urls = {s["url"] for s in selected if s.get("extraction_pages")}
    selected = [s for s in selected if s["url"] not in scoped_urls or s.get("extraction_pages")]
    return json.dumps({"scope": group, "items": batch, "complete_manuscript": documents,
        "complete_bibliography": inv["references"], "retrieved_sources": selected}, ensure_ascii=False)


def run_checks(pre: Mapping[str, Any], root: Path, run: Path, role: Mapping[str, Any],
               timeout: int, runner) -> dict[str, Any]:
    if role.get("provider") != "openai-codex":
        raise ValueError("Formal verification requires an independent Codex role")
    metadata = pre["metadata"]
    documents, bibliography = current_inputs(metadata, root)
    inv = inventory(documents, bibliography)
    directory = run / "formal-check"
    directory.mkdir()
    with httpx.Client(timeout=httpx.Timeout(30, connect=15), follow_redirects=True) as client:
        sources, errors = collect_sources(inv, metadata, root, directory / "evidence", client)
    report = {"references": [], "passages": []}
    receipts = []
    if not errors:
        # Small output batches, full manuscript context, no truncated source.
        for group in ("references", "passages"):
            units = inv[group]
            for start in range(0, len(units), BATCH_SIZE):
                batch = units[start:start + BATCH_SIZE]
                packet = batch_packet(group, batch, documents, inv, sources)
                if len(packet.encode()) > MAX_PACKET:
                    errors.append("Formal-check packet exceeds the context budget; register precise primary chapter/page sources, never truncate evidence")
                    break
                output, receipt = runner(role_name=f"formal_{group}_{start // BATCH_SIZE + 1}", role=role,
                    system_prompt=PROMPT.read_text(), user_prompt=packet, schema=REPORT_SCHEMA,
                    workdir=directory / f"{group}-{start // BATCH_SIZE + 1}", timeout=timeout)
                _validate_against_schema(output, REPORT_SCHEMA)
                _exact(output[group], "key" if group == "references" else "passage_id",
                       {u["key" if group == "references" else "id"] for u in batch}, group)
                if output["passages" if group == "references" else "references"]:
                    raise ValueError("Formal verifier reported items outside its batch")
                report[group].extend(output[group])
                workdir = directory / f"{group}-{start // BATCH_SIZE + 1}"
                receipts.append({"receipt": receipt, "group": group,
                    "workdir": workdir.relative_to(root).as_posix()})
    if not errors:
        try:
            errors.extend(report_blockers(report, inv, sources))
        except (ValueError, LaunchError) as exc:
            errors.append(f"Coverage/evidence verification failed: {exc}")
    result = {"schema": VERSION, "paper_id": metadata["paper_id"], "manuscript_version": str(metadata.get("version") or ""),
        "policy": policy(), "role": dict(role), "inventory": inv,
        "source_plan_sha256": digest(source_plan(metadata)), "sources": sources,
        "report": report, "receipts": receipts, "blockers": errors, "valid": not errors,
        "machine_proof_of_whole_manuscript": False, "verified_at": datetime.now(UTC).isoformat()}
    path = directory / "report.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return {"path": path.relative_to(root).as_posix(), "sha256": sha(path.read_bytes()),
            "valid": result["valid"], "blockers": errors, "schema": VERSION}


def validate_binding(binding: Any, metadata: Mapping[str, Any], root: Path,
                     expected_role: Mapping[str, Any] | None = None) -> list[str]:
    """Revalidate evidence bytes, exact coverage and policy at apply/handoff."""
    try:
        if not isinstance(binding, Mapping) or binding.get("schema") != VERSION or binding.get("valid") is not True:
            raise ValueError("Missing passing mandatory formal check; rerun unified review")
        path = _safe_file(root, binding["path"])
        if sha(path.read_bytes()) != binding["sha256"]:
            raise ValueError("Formal-check report changed")
        result = json.loads(path.read_text())
        if result.get("paper_id") != metadata.get("paper_id") or result.get("manuscript_version") != str(metadata.get("version") or ""):
            raise ValueError("Formal-check paper/version identity mismatch")
        if result["policy"] != policy() or result["valid"] is not True or result["blockers"]:
            raise ValueError("Formal-check policy changed or verification is incomplete")
        if expected_role is not None and result.get("role") != dict(expected_role):
            raise ValueError("Formal verification used a different configured role")
        if result["source_plan_sha256"] != digest(source_plan(metadata)):
            raise ValueError("Registered primary-source plan changed")
        documents, bibliography = current_inputs(metadata, root)
        if result["inventory"] != inventory(documents, bibliography):
            raise ValueError("Formal-check coverage does not match current manuscript and bibliography")
        for source in result["sources"]:
            for field in ("body", "text"):
                evidence_path = _safe_file(root, source[field + "_path"])
                if sha(evidence_path.read_bytes()) != source[field + "_sha256"]:
                    raise ValueError("Retrieved primary evidence changed or is missing")
            if _safe_file(root, source["text_path"]).read_text() != source["text"]:
                raise ValueError("Reported source text differs from the actual evidence file")
        if not result["receipts"]:
            raise ValueError("Formal verification lacks independent actual-model receipts")
        reconstructed = {"references": [], "passages": []}
        expected_batches = [(group, start) for group in ("references", "passages")
                            for start in range(0, len(result["inventory"][group]), BATCH_SIZE)]
        if len(result["receipts"]) != len(expected_batches):
            raise ValueError("Formal role batch coverage is incomplete or duplicated")
        for item, (expected_group, start) in zip(result["receipts"], expected_batches):
            receipt, workdir, group = item["receipt"], item["workdir"], item["group"]
            if group != expected_group:
                raise ValueError("Formal role batch order/scope changed")
            if (receipt.get("independent_context") is not True or receipt.get("provider") != "openai-codex"
                    or receipt.get("model") != result["role"].get("model")
                    or receipt.get("model") not in receipt.get("runtime_reported_models", [])
                    or receipt.get("schema_sha256") != sha(json.dumps(REPORT_SCHEMA, sort_keys=True).encode())
                    or receipt.get("system_prompt_sha256") != sha(PROMPT.read_bytes())):
                raise ValueError("Formal verification lacks matching independent actual-model receipts")
            for filename, expected in (("output.json", receipt["output_sha256"]),
                                       ("prompt.txt", receipt["prompt_sha256"]),
                                       ("system.txt", receipt["system_prompt_sha256"])):
                if sha(_safe_file(root, workdir + "/" + filename).read_bytes()) != expected:
                    raise ValueError("Formal role inputs or actual output changed")
            actual_receipt = json.loads(_safe_file(root, workdir + "/receipt.json").read_text())
            if actual_receipt != receipt:
                raise ValueError("Formal role receipt changed")
            batch = result["inventory"][group][start:start + BATCH_SIZE]
            expected_prompt = PROMPT.read_text() + "\n\n" + batch_packet(group, batch, documents, result["inventory"], result["sources"])
            if _safe_file(root, workdir + "/prompt.txt").read_text() != expected_prompt:
                raise ValueError("Formal role did not inspect the exact bound manuscript, batch and source evidence")
            output = json.loads(_safe_file(root, workdir + "/output.json").read_text())
            _validate_against_schema(output, REPORT_SCHEMA)
            _exact(output[group], "key" if group == "references" else "passage_id",
                   {u["key" if group == "references" else "id"] for u in batch}, group)
            if output["passages" if group == "references" else "references"]:
                raise ValueError("Formal role output contains another scope")
            reconstructed[group].extend(output[group])
        if reconstructed != result["report"]:
            raise ValueError("Formal report differs from the actual independent outputs")
        return report_blockers(result["report"], result["inventory"], result["sources"])
    except (ValueError, KeyError, TypeError, OSError, LaunchError) as exc:
        return [f"Mandatory formal check: {exc}"]


def packet(binding: Mapping[str, Any], root: Path) -> str:
    result = json.loads(_safe_file(root, binding["path"]).read_text())
    return ("\n## Mandatory bibliography and prerequisite verification\n"
            "This is an evidence-bound independent audit, not a machine proof of the entire manuscript. "
            "Check for misclassified or omitted dependencies and any overclaimed verification.\n"
            + json.dumps({"binding": binding, "evidence_root": str(root.resolve()), "report": result["report"],
                          "source_records": [{k: v for k, v in s.items() if k != "text"} for s in result["sources"]]},
                         ensure_ascii=False, indent=2) + "\n")
