"""Deterministic checks for reader-facing supporting-material citations.

The repository keeps Zenodo draft/release history in the paper registry and
receipts.  A manuscript, by contrast, must use publication-state-neutral,
version-stable prose and cite only the current support Version DOI.  This
module enforces that separation without making network requests.
"""

from __future__ import annotations

import json
import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from paper_writing.registry import load_paper_metadata, load_registry_settings
from paper_writing.support import sha256_file, verify_support_archive
from paper_writing.support_policy import (
    SUPPORT_PUBLICATION_MODES,
    effective_publication_license,
    effective_publication_mode,
    lifecycle_gate,
    publication_policy,
    require_not_required_reason,
    status_meets_minimum,
)


CITE_PATTERN = re.compile(r"\\cite\w*\s*\{([^}]*)\}")
INPUT_PATTERN = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
PATH_PATTERN = re.compile(r"\\path\s*\{([^}]+)\}")
ARCHIVE_ROOT_CLAIM = re.compile(
    r"\b(?:at|in)\s+(?:the|its|this)\s+(?:outer\s+)?archive\s+root\b|"
    r"\brelative\s+to\s+(?:that|the|its)\s+(?:archive\s+)?root\b",
    re.IGNORECASE,
)
CHECKSUM_EVERY_MEMBER_CLAIM = re.compile(
    r"SHA256SUMS.{0,120}(?:authenticates|covers|verifies|checks)\s+"
    r"(?:every|all)\s+(?:archive\s+)?members?",
    re.IGNORECASE | re.DOTALL,
)
CHECKSUM_SELF_EXCLUSION = re.compile(
    r"^\s+(?:(?:except|other\s+than)(?:\s+for)?\s+)"
    r"(?:`?SHA256SUMS`?|itself)\b",
    re.IGNORECASE,
)
MANIFEST_SAME_COVERAGE_CLAIM = re.compile(
    r"ZENODO_MANIFEST\.json.{0,120}(?:records?|contains?)\s+(?:the\s+)?same\s+paths?",
    re.IGNORECASE | re.DOTALL,
)
SHA256SUM_LINE = re.compile(r"^[0-9a-fA-F]{64}\s+\*?(.+?)\s*$")
BIB_ENTRY_START = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,", re.IGNORECASE)
BIB_FIELD_START = re.compile(r"(?m)^\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*")
SUPPORT_MENTION = re.compile(
    r"(?:support(?:ing)?[- ]materials?|support(?:ing)?[- ]material\s+source|"
    r"support\s+archive|reproducibility\s+archive|Zenodo\s+(?:record|archive)|"
    r"cited\s+Zenodo\s+archive|reader-facing\s+support\s+source|"
    r"支撑材料|支持材料|Zenodo\s*版本记录|Zenodo\s*归档)",
    re.IGNORECASE,
)
AVAILABILITY_HEADING = re.compile(
    r"\\(?:section|subsection|subsubsection|paragraph)\*?\s*"
    r"\{[^}]*(?:availability|可用性|获取)[^}]*\}",
    re.IGNORECASE,
)
SUPPORT_CONTEXT = re.compile(
    r"(?:support|Zenodo|archive|reproduc|availability|attachment|Version DOI|"
    r"支撑|支持材料|归档|版本 DOI|预发布|草稿)",
    re.IGNORECASE,
)
ARCHIVE_FILENAME = re.compile(
    r"[A-Za-z0-9_-]+-support-v[0-9A-Za-z.+_-]+\.zip", re.IGNORECASE
)
SEMANTIC_VERSION = re.compile(r"(?<![0-9A-Za-z])v?(\d+\.\d+\.\d+)(?![0-9A-Za-z])")
PUBLIC_SUPPORT_DIRECTORY = re.compile(r"^public-support-v(\d+\.\d+\.\d+)$", re.IGNORECASE)
RECORD_VERSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bZenodo(?:\s+(?:record|archive))?\s+(?:version\s+)?v?(\d+\.\d+\.\d+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:current|reader-facing|source-of-record)\b.{0,80}\bversion\s+"
        r"v?(\d+\.\d+\.\d+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bthis\s+directory\b.{0,120}\bversion\s+v?(\d+\.\d+\.\d+)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:当前|本)(?:支撑材料|支持材料|归档|记录|目录).{0,80}版本\s*v?(\d+\.\d+\.\d+)", re.IGNORECASE),
)

PROCESS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "draft-state",
        re.compile(
            r"\b(?:production|unpublished|Zenodo)\s+draft\b|"
            r"\bdraft\s+(?:record|receipt|deposition)\b|生产草稿|Zenodo\s*草稿",
            re.IGNORECASE,
        ),
    ),
    (
        "reservation-state",
        re.compile(
            r"\bprepublication\b|\breserved\s+(?:production\s+)?(?:Version\s+)?DOI\b|"
            r"\bDOI\s+(?:is|was)\s+reserved\b|need\s+not\s+resolve|预发布|预留状态|"
            r"DOI\s*为预留",
            re.IGNORECASE,
        ),
    ),
    (
        "release-transition",
        re.compile(
            r"\b(?:after|before|during)\s+(?:explicit(?:ly)?\s+)?"
            r"(?:authorized\s+)?release\b|\bafter\s+release\b|"
            r"获得明确授权发布后|授权发布后|发布后.*(?:DOI|记录)|才指向.*公开记录",
            re.IGNORECASE,
        ),
    ),
    (
        "workflow-narrative",
        re.compile(
            r"\bcontrolled\s+Zenodo\s+(?:release\s+)?workflow\b|"
            r"\bDOI\s+assigned\s+during\b|\b(?:has\s+been|is|was)\s+assigned\b.{0,80}\bDOI\b|"
            r"受控工作流.*(?:分配|指派)|分配\s*Version DOI",
            re.IGNORECASE,
        ),
    ),
    (
        "prepared-state",
        re.compile(
            r"\bprepared\s+(?:outer\s+)?(?:ZIP|archive|attachment|record|sidecar)\b|"
            r"\bprepared\s+(?:source-of-record|computational-support)\b|"
            r"已准备的?(?:归档|压缩包|附件)",
            re.IGNORECASE,
        ),
    ),
    (
        "version-history",
        re.compile(
            r"\b(?:earlier|previous|old|new|superseded|historical)\b.{0,100}"
            r"\b(?:support|archive|record|version|release|bundle)\b|"
            r"\bversion\s+v?\d+(?:\.\d+){1,2}\s+(?:additionally\s+)?"
            r"(?:adds?|added|replaces?|supersedes?|retains?)\b|"
            r"\bsuperseded\s+version[- ]?\d+\b|"
            r"旧版本|新版本|历史版本|被取代的?版本|已替代版本|版本演变",
            re.IGNORECASE,
        ),
    ),
    (
        "release-provenance-heading",
        re.compile(r"support[- ]release\s+provenance|支撑材料发布沿革", re.IGNORECASE),
    ),
    (
        "internal-evaluation",
        re.compile(
            r"PASS[_ -]*INTERNAL|"
            r"\binternal\b.{0,40}\b(?:audit|review|reconstruction|QA)\b|"
            r"\b(?:audit|review|reconstruction|QA)\b.{0,40}\binternal\b|"
            r"内部(?:对抗性)?(?:审查|评审|复核)|内部\s*QA|内部证据审查",
            re.IGNORECASE,
        ),
    ),
    (
        "review-history",
        re.compile(
            r"\bstatus\s+audit\s+(?:was\s+)?(?:repeated|completed|updated)\b|"
            r"状态审查.*(?:重复|完成|更新)|两次仓库审查",
            re.IGNORECASE,
        ),
    ),
    (
        "discovery-history",
        re.compile(
            r"\bhistorical\s+discovery\b|\bunpublished\s+discovery\s+material\b|"
            r"历史发现测试|未发布的发现材料",
            re.IGNORECASE,
        ),
    ),
)

ARCHIVE_EVALUATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("internal-verdict", re.compile(r"PASS[_ -]*INTERNAL|FAIL[_ -]*INTERNAL", re.IGNORECASE)),
    (
        "publishability-projection",
        re.compile(
            r"publishable[_ -]*stage|publishability[_ -]*(?:note|verdict)|"
            r"\bpaperability\b|plausible[-_ ]standalone|SCI[-_ ]?Q\d?[-_ ]*stop[-_ ]gate",
            re.IGNORECASE,
        ),
    ),
    (
        "review-verdict-field",
        re.compile(
            r'"(?:qa_status|headline_candidate_verdict|corollary_verdict|independent_qa)"\s*:',
            re.IGNORECASE,
        ),
    ),
)

ARCHIVE_TEXT_SUFFIXES = {
    ".bib",
    ".cff",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".tex",
    ".txt",
    ".yaml",
    ".yml",
}

DRAFT_PUBLIC_CLAIM = re.compile(
    r"\b(?:publicly\s+archived|public\s+source|anonymous\s+access|openly\s+available|"
    r"available\s+(?:at|from|on)\s+Zenodo|downloadable\s+(?:at|from)|"
    r"archived\s+(?:at|on)\s+Zenodo|becomes?\s+public)\b|公开归档|公开记录|匿名访问|可公开下载",
    re.IGNORECASE,
)
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.\d+", re.IGNORECASE)


@dataclass(frozen=True)
class SourceParagraph:
    path: Path
    line: int
    text: str


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _issue(code: str, message: str, *, path: Path | None = None, line: int | None = None, root: Path) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        issue["path"] = _relative(path, root)
    if line is not None:
        issue["line"] = line
    return issue


def _strip_tex_comment(line: str) -> str:
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


def _paragraphs(path: Path) -> list[SourceParagraph]:
    paragraphs: list[SourceParagraph] = []
    parts: list[str] = []
    start = 1
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = _strip_tex_comment(raw).strip()
        if not line:
            if parts:
                paragraphs.append(SourceParagraph(path, start, " ".join(parts)))
                parts = []
            continue
        if not parts:
            start = line_number
        parts.append(line)
    if parts:
        paragraphs.append(SourceParagraph(path, start, " ".join(parts)))
    return paragraphs


def _formal_tex_files(manuscript: Path) -> list[Path]:
    return sorted(
        path
        for path in manuscript.rglob("*.tex")
        if "supplement" not in path.relative_to(manuscript).parts
    )


READER_FACING_STATEMENT_NAMES = {
    "code_availability.md",
    "code_availability_statement.md",
    "data_availability.md",
    "data_availability_statement.md",
    "reproducibility.md",
    "reproducibility_statement.md",
    "support_statement.md",
    "supporting_materials_statement.md",
}

REPRODUCIBILITY_TITLE_HEADING = re.compile(
    r"^\s*#\s+Reproducibility\s+Statement\s+for\s+(.+?)\s*$",
    re.IGNORECASE,
)
CLAIM_ROUTING_PREFIX = re.compile(
    r"^\s*(?:Admitted\s+claim\s+IDs|Claim\s+routing)\s*:",
    re.IGNORECASE,
)
INLINE_CODE = re.compile(r"`([^`]+)`")
CLAIM_IDENTIFIER = re.compile(
    r"\b[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)+\b"
)
CLAIM_MAP_ROW = re.compile(r"^\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def _reader_facing_manuscript_files(manuscript: Path) -> list[Path]:
    """Return formal TeX plus standalone availability/support statements.

    Several venue packages ship a Markdown reproducibility or availability
    statement beside the canonical TeX even when it is not ``\\input`` into
    the PDF.  It is still reader-facing manuscript prose and must obey the
    same current-record and no-process-history rules.
    """

    files = set(_formal_tex_files(manuscript))
    files.update(
        path
        for path in manuscript.rglob("*.md")
        if "supplement" not in path.relative_to(manuscript).parts
        and path.name.casefold() in READER_FACING_STATEMENT_NAMES
    )
    return sorted(files)


def _current_claim_ids(
    metadata: Mapping[str, Any],
    publication: Mapping[str, Any],
    *,
    root: Path,
) -> set[str]:
    """Return canonical and current-public claim identifiers.

    Standalone reproducibility statements are often copied into venue portals
    even though they are not included by the canonical TeX.  Their claim IDs
    therefore need a deterministic check against the current claim map and the
    public ``CLAIMS.yaml`` selected for the registered support record.
    """

    workspace_value = str(metadata.get("workspace") or "").strip()
    workspace = root / workspace_value if workspace_value else None
    claim_map = workspace / "evidence" / "claim_evidence_map.md" if workspace else None
    identifiers: set[str] = set()
    if claim_map is not None and claim_map.is_file():
        identifiers.update(CLAIM_MAP_ROW.findall(claim_map.read_text(encoding="utf-8")))

    source_values = publication.get("source_files")
    if not isinstance(source_values, list):
        return identifiers
    for value in source_values:
        if not isinstance(value, str):
            continue
        path = root / value
        if path.name.casefold() not in {"claims.yaml", "claims.yml"} or not path.is_file():
            continue
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        claims = payload.get("claims") if isinstance(payload, Mapping) else None
        if not isinstance(claims, list):
            continue
        identifiers.update(
            str(item.get("id") or "").strip()
            for item in claims
            if isinstance(item, Mapping) and str(item.get("id") or "").strip()
        )
    return identifiers


def _standalone_statement_checks(
    *,
    prose_files: list[Path],
    metadata: Mapping[str, Any],
    publication: Mapping[str, Any],
    paper_title: str,
    root: Path,
) -> list[dict[str, Any]]:
    """Check paper identity and claim routing in standalone Markdown prose."""

    issues: list[dict[str, Any]] = []
    current_claim_ids = _current_claim_ids(metadata, publication, root=root)
    expected_title_tokens = _plain_tokens(paper_title)
    for path in prose_files:
        if path.suffix.casefold() != ".md":
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            title_match = REPRODUCIBILITY_TITLE_HEADING.fullmatch(line)
            if title_match and _plain_tokens(title_match.group(1)) != expected_title_tokens:
                issues.append(
                    _issue(
                        "SUPPORT-STATEMENT-PAPER-TITLE",
                        "standalone reproducibility statement identifies a different paper title",
                        path=path,
                        line=line_number,
                        root=root,
                    )
                )
            if not CLAIM_ROUTING_PREFIX.match(line):
                continue
            referenced = {
                identifier
                for code_span in INLINE_CODE.findall(line)
                for identifier in CLAIM_IDENTIFIER.findall(code_span)
            }
            for identifier in sorted(referenced - current_claim_ids):
                issues.append(
                    _issue(
                        "SUPPORT-STATEMENT-CLAIM-ID",
                        f"standalone reproducibility statement cites unknown current claim ID {identifier!r}",
                        path=path,
                        line=line_number,
                        root=root,
                    )
                )
    return issues


def _expand_tex(path: Path, manuscript: Path, stack: tuple[Path, ...] = ()) -> list[SourceParagraph]:
    resolved = path.resolve()
    if resolved in stack or not resolved.is_file():
        return []
    expanded: list[SourceParagraph] = []
    for paragraph in _paragraphs(resolved):
        cursor = 0
        matches = list(INPUT_PATTERN.finditer(paragraph.text))
        if not matches:
            expanded.append(paragraph)
            continue
        for match in matches:
            prefix = paragraph.text[cursor:match.start()].strip()
            if prefix:
                expanded.append(SourceParagraph(resolved, paragraph.line, prefix))
            target = match.group(1).strip()
            target_path = (manuscript / target)
            if target_path.suffix == "":
                target_path = target_path.with_suffix(".tex")
            expanded.extend(_expand_tex(target_path, manuscript, (*stack, resolved)))
            cursor = match.end()
        suffix = paragraph.text[cursor:].strip()
        if suffix:
            expanded.append(SourceParagraph(resolved, paragraph.line, suffix))
    return expanded


def _bib_entries(text: str) -> list[tuple[str, str]]:
    starts = list(BIB_ENTRY_START.finditer(text))
    entries: list[tuple[str, str]] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        entries.append((match.group(1), text[match.end():end]))
    return entries


def _balanced_value(text: str, start: int) -> str:
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text):
        return ""
    opener = text[cursor]
    if opener == '"':
        cursor += 1
        output: list[str] = []
        escaped = False
        while cursor < len(text):
            character = text[cursor]
            if character == '"' and not escaped:
                break
            output.append(character)
            escaped = character == "\\" and not escaped
            if character != "\\":
                escaped = False
            cursor += 1
        return "".join(output).strip()
    if opener != "{":
        end = text.find(",", cursor)
        return text[cursor : len(text) if end < 0 else end].strip()
    depth = 1
    cursor += 1
    output = []
    while cursor < len(text) and depth:
        character = text[cursor]
        if character == "{" and (cursor == 0 or text[cursor - 1] != "\\"):
            depth += 1
        elif character == "}" and (cursor == 0 or text[cursor - 1] != "\\"):
            depth -= 1
            if depth == 0:
                break
        output.append(character)
        cursor += 1
    return "".join(output).strip()


def _bib_fields(body: str) -> dict[str, str]:
    return {
        match.group(1).casefold(): _balanced_value(body, match.end())
        for match in BIB_FIELD_START.finditer(body)
    }


def _plain_tokens(value: str) -> tuple[str, ...]:
    value = re.sub(r"\\(?:H|['`^\"~=\.uvckbdtr])\s*\{\s*([A-Za-z])\s*\}", r"\1", value)
    value = re.sub(r"\\(?:H|['`^\"~=\.uvckbdtr])\s*([A-Za-z])", r"\1", value)
    value = re.sub(r"\\(?:text|mathrm|mathit|mathbf|operatorname|emph|texorpdfstring)\s*", "", value)
    value = value.replace("\\(", " ").replace("\\)", " ")
    value = value.replace("{", "").replace("}", "").replace("\\", " ")
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_like = "".join(character for character in decomposed if not unicodedata.combining(character))
    return tuple(re.findall(r"[0-9A-Za-z]+", ascii_like.casefold()))


SUPPORT_TITLE_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("computational", "supporting", "materials"),
    ("computational", "support", "materials"),
    ("supporting", "materials"),
    ("support", "materials"),
)


def _support_title_core_tokens(value: str) -> tuple[str, ...]:
    """Return the paper-title part of a reader-facing support-record title."""

    tokens = _plain_tokens(value)
    for suffix in SUPPORT_TITLE_SUFFIXES:
        if len(tokens) >= len(suffix) and tokens[-len(suffix) :] == suffix:
            return tokens[: -len(suffix)]
    return tokens


def _person_key(value: str) -> tuple[str, ...]:
    return tuple(sorted(_plain_tokens(value)))


def _expected_metadata(publication: Mapping[str, Any], root: Path) -> dict[str, Any]:
    receipt_value = publication.get("draft_receipt")
    if isinstance(receipt_value, str) and receipt_value.strip():
        receipt_path = root / receipt_value
        if receipt_path.is_file():
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            verified = payload.get("verified_remote_metadata")
            if isinstance(verified, Mapping):
                return dict(verified)
    zenodo = publication.get("zenodo")
    zenodo = zenodo if isinstance(zenodo, Mapping) else {}
    metadata: dict[str, Any] = {}
    for field in ("title", "version", "license"):
        if zenodo.get(field) is not None:
            metadata[field] = zenodo[field]
    if isinstance(zenodo.get("creators"), list):
        metadata["creators"] = zenodo["creators"]
    return metadata


def _registry_creators(metadata: Mapping[str, Any]) -> list[str]:
    authors = metadata.get("authors")
    if not isinstance(authors, list):
        return []
    return [str(item.get("name") or "").strip() for item in authors if isinstance(item, Mapping) and str(item.get("name") or "").strip()]


def _current_identity(metadata: Mapping[str, Any]) -> tuple[str, str, str]:
    publication = metadata.get("support")
    publication = publication.get("publication") if isinstance(publication, Mapping) else {}
    publication = publication if isinstance(publication, Mapping) else {}
    zenodo = publication.get("zenodo")
    zenodo = zenodo if isinstance(zenodo, Mapping) else {}
    status = str(publication.get("status") or "planned")
    if status == "draft":
        doi = str(zenodo.get("reserved_version_doi") or publication.get("version_doi") or "").strip()
    else:
        doi = str(publication.get("version_doi") or zenodo.get("version_doi") or "").strip()
    version = str(zenodo.get("version") or "").strip()
    return status, doi.removeprefix("https://doi.org/"), version


def _citations(text: str) -> set[str]:
    keys: set[str] = set()
    for match in CITE_PATTERN.finditer(text):
        keys.update(value.strip() for value in match.group(1).split(",") if value.strip())
    return keys


def _receipt_checks(
    *,
    paper_id: str,
    paper_version: str,
    publication: Mapping[str, Any],
    status: str,
    doi: str,
    version: str,
    root: Path,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    receipt_field = "draft_receipt" if status == "draft" else "release_receipt"
    receipt_value = publication.get(receipt_field)
    if not isinstance(receipt_value, str) or not receipt_value.strip():
        return issues
    receipt_path = root / receipt_value
    if not receipt_path.is_file():
        return [_issue("SUPPORT-RECEIPT-MISSING", f"registered {receipt_field} does not exist", path=receipt_path, root=root)]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [_issue("SUPPORT-RECEIPT-INVALID", f"cannot read {receipt_field}: {exc}", path=receipt_path, root=root)]
    if str(receipt.get("paper_id") or "") != paper_id:
        issues.append(_issue("SUPPORT-RECEIPT-PAPER", "receipt paper_id does not match the registry", path=receipt_path, root=root))
    receipt_version = str(receipt.get("paper_version") or "")
    if status == "draft" and receipt_version != paper_version:
        issues.append(_issue("SUPPORT-RECEIPT-VERSION", f"draft receipt version {receipt_version!r} does not match manuscript version {paper_version!r}", path=receipt_path, root=root))
    if version and receipt_version and receipt_version != version:
        issues.append(_issue("SUPPORT-RECEIPT-ZENODO-VERSION", f"receipt version {receipt_version!r} does not match current Zenodo version {version!r}", path=receipt_path, root=root))
    receipt_doi = str(receipt.get("reserved_version_doi") if status == "draft" else receipt.get("version_doi") or "").removeprefix("https://doi.org/")
    if doi and receipt_doi and receipt_doi != doi:
        issues.append(_issue("SUPPORT-RECEIPT-DOI", f"receipt DOI {receipt_doi!r} does not match current Version DOI {doi!r}", path=receipt_path, root=root))
    return issues


def _registered_source_checks(
    publication: Mapping[str, Any], *, version: str, root: Path
) -> list[dict[str, Any]]:
    """Reject a current release assembled from a differently labelled public source tree."""

    if not version:
        return []
    issues: list[dict[str, Any]] = []
    values = publication.get("source_files")
    if not isinstance(values, list):
        return issues
    for value in values:
        if not isinstance(value, str):
            continue
        path = root / value
        for part in Path(value).parts:
            match = PUBLIC_SUPPORT_DIRECTORY.fullmatch(part)
            if match and match.group(1) != version.lstrip("v"):
                issues.append(
                    _issue(
                        "SUPPORT-SOURCE-VERSION",
                        f"current support version {version!r} is assembled from source directory {part!r}",
                        path=path,
                        root=root,
                    )
                )
                break
    return issues


def _reader_facing_archive_members(payload: zipfile.ZipFile) -> list[str]:
    """Return only public prose that describes the outer support record.

    Nested legacy archives and tool manifests may truthfully retain their own
    component versions.  The outer claim map and the current public-support
    README, however, describe the record cited by the manuscript and must not
    leak release history or a stale record identity.
    """

    selected: list[str] = []
    for name in payload.namelist():
        parts = Path(name).parts
        if len(parts) >= 3 and parts[-2:] == ("evidence", "claim_evidence_map.md"):
            selected.append(name)
            continue
        if not parts or parts[-1] != "README.md":
            continue
        if any(PUBLIC_SUPPORT_DIRECTORY.fullmatch(part) for part in parts[:-1]):
            selected.append(name)
    return sorted(set(selected))


def _archive_reader_checks(
    archive: Path,
    *,
    status: str,
    doi: str,
    version: str,
    root: Path,
) -> list[dict[str, Any]]:
    """Audit the record-facing prose inside the exact deposited ZIP."""

    issues: list[dict[str, Any]] = []
    if not version:
        return issues
    with zipfile.ZipFile(archive) as payload:
        for member in payload.namelist():
            if member.endswith("/") or Path(member).suffix.casefold() not in ARCHIVE_TEXT_SUFFIXES:
                continue
            try:
                artifact_text = payload.read(member).decode("utf-8")
            except UnicodeDecodeError:
                continue
            for label, pattern in ARCHIVE_EVALUATION_PATTERNS:
                match = pattern.search(artifact_text)
                if match is None:
                    continue
                line_number = artifact_text.count("\n", 0, match.start()) + 1
                issues.append(
                    _issue(
                        "SUPPORT-ARCHIVE-EVALUATION-PROJECTION",
                        f"{member}:{line_number} contains a prior evaluative projection ({label})",
                        path=archive,
                        root=root,
                    )
                )
        for member in _reader_facing_archive_members(payload):
            for part in Path(member).parts:
                directory_match = PUBLIC_SUPPORT_DIRECTORY.fullmatch(part)
                if directory_match and directory_match.group(1) != version.lstrip("v"):
                    issues.append(
                        _issue(
                            "SUPPORT-ARCHIVE-SOURCE-VERSION",
                            f"reader-facing archive member uses source directory {part!r}, not current support version {version}: {member}",
                            path=archive,
                            root=root,
                        )
                    )
                    break
            try:
                text = payload.read(member).decode("utf-8")
            except UnicodeDecodeError:
                issues.append(
                    _issue(
                        "SUPPORT-ARCHIVE-PROSE-ENCODING",
                        f"reader-facing archive member is not UTF-8: {member}",
                        path=archive,
                        root=root,
                    )
                )
                continue
            is_claim_map = member.endswith("/evidence/claim_evidence_map.md")
            if is_claim_map and doi and doi.casefold() not in text.casefold():
                issues.append(
                    _issue(
                        "SUPPORT-ARCHIVE-DOI",
                        f"reader-facing archive member does not identify current Version DOI {doi}: {member}",
                        path=archive,
                        root=root,
                    )
                )
            if is_claim_map and version.lstrip("v") not in {
                match.group(1) for match in SEMANTIC_VERSION.finditer(text)
            }:
                issues.append(
                    _issue(
                        "SUPPORT-ARCHIVE-VERSION-MISSING",
                        f"reader-facing archive member does not identify current support version {version}: {member}",
                        path=archive,
                        root=root,
                    )
                )
            for line_number, line in enumerate(text.splitlines(), start=1):
                if SUPPORT_CONTEXT.search(line):
                    for label, pattern in PROCESS_PATTERNS:
                        if pattern.search(line):
                            issues.append(
                                _issue(
                                    "SUPPORT-ARCHIVE-PROCESS-NARRATIVE",
                                    f"{member}:{line_number} contains internal release/version process narrative ({label})",
                                    path=archive,
                                    root=root,
                                )
                            )
                    if status == "draft" and DRAFT_PUBLIC_CLAIM.search(line):
                        issues.append(
                            _issue(
                                "SUPPORT-ARCHIVE-DRAFT-PUBLIC-CLAIM",
                                f"{member}:{line_number} describes an unpublished draft as public",
                                path=archive,
                                root=root,
                            )
                        )
                found_versions = {
                    match.group(1)
                    for pattern in RECORD_VERSION_PATTERNS
                    for match in pattern.finditer(line)
                }
                for found in sorted(found_versions):
                    if found == version.lstrip("v"):
                        continue
                    issues.append(
                        _issue(
                            "SUPPORT-ARCHIVE-STALE-VERSION",
                            f"{member}:{line_number} identifies reader-facing support as version {found}, not current version {version}",
                            path=archive,
                            root=root,
                        )
                    )
    return issues


def _contains_token_sequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[index : index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


def _archive_identity_checks(
    archive: Path,
    *,
    paper_id: str,
    paper_title: str,
    doi: str,
    version: str,
    expected_creators: list[str],
    root: Path,
) -> list[dict[str, Any]]:
    """Check reader-facing current-record identity in outer and nested ZIPs."""

    issues: list[dict[str, Any]] = []
    expected_title_tokens = _plain_tokens(paper_title)

    def add(code: str, message: str, source: str) -> None:
        issues.append(
            _issue(code, f"{source}: {message}", path=archive, root=root)
        )

    def check_zip(payload: zipfile.ZipFile, source: str, depth: int) -> None:
        names = set(payload.namelist())
        identity_directories: set[str] = set()
        for name in sorted(names):
            if name.endswith("/"):
                continue
            basename = Path(name).name
            if basename == "CITATION.cff":
                try:
                    cff = yaml.safe_load(payload.read(name).decode("utf-8"))
                except (UnicodeDecodeError, yaml.YAMLError) as exc:
                    add("SUPPORT-ARCHIVE-IDENTITY-INVALID", f"cannot parse CITATION.cff: {exc}", f"{source}!{name}")
                    continue
                if not isinstance(cff, Mapping):
                    continue
                message = str(cff.get("message") or "")
                cff_doi = str(cff.get("doi") or "").removeprefix("https://doi.org/")
                is_support_identity = bool(cff_doi or re.search(r"Zenodo|support", message, re.IGNORECASE))
                if not is_support_identity:
                    continue
                parent = Path(name).parent.as_posix()
                identity_directories.add("" if parent == "." else parent)
                cff_version = str(cff.get("version") or "").lstrip("v")
                if version and cff_version != version.lstrip("v"):
                    add("SUPPORT-ARCHIVE-IDENTITY-VERSION", f"CITATION.cff version {cff_version!r} does not match current version {version!r}", f"{source}!{name}")
                if doi and cff_doi != doi:
                    add("SUPPORT-ARCHIVE-IDENTITY-DOI", f"CITATION.cff DOI {cff_doi!r} does not match current Version DOI {doi!r}", f"{source}!{name}")
                cff_title = str(cff.get("title") or "")
                if paper_title and _support_title_core_tokens(cff_title) != expected_title_tokens:
                    add("SUPPORT-ARCHIVE-IDENTITY-TITLE", "CITATION.cff identifies a different paper title", f"{source}!{name}")
                authors = cff.get("authors")
                if isinstance(authors, list) and expected_creators:
                    cff_creators = [
                        " ".join(
                            part
                            for part in (
                                str(item.get("given-names") or "").strip(),
                                str(item.get("family-names") or "").strip(),
                            )
                            if part
                        )
                        for item in authors
                        if isinstance(item, Mapping)
                    ]
                    if [_person_key(value) for value in cff_creators] != [
                        _person_key(value) for value in expected_creators
                    ]:
                        add("SUPPORT-ARCHIVE-IDENTITY-CREATORS", "CITATION.cff creators do not match the paper registry", f"{source}!{name}")
            elif basename == "ZENODO_MANIFEST.json":
                try:
                    manifest = json.loads(payload.read(name).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    add("SUPPORT-ARCHIVE-IDENTITY-INVALID", f"cannot parse ZENODO_MANIFEST.json: {exc}", f"{source}!{name}")
                    continue
                if not isinstance(manifest, Mapping) or str(manifest.get("paper_id") or "") != paper_id:
                    continue
                manifest_version = str(
                    manifest.get("release_version")
                    or manifest.get("paper_version")
                    or ""
                ).lstrip("v")
                manifest_doi = str(
                    manifest.get("version_doi")
                    or manifest.get("reserved_version_doi")
                    or ""
                ).removeprefix("https://doi.org/")
                manifest_title = str(
                    manifest.get("title") or manifest.get("paper_title") or ""
                )
                if version and manifest_version and manifest_version != version.lstrip("v"):
                    add("SUPPORT-ARCHIVE-IDENTITY-VERSION", f"manifest version {manifest_version!r} does not match current version {version!r}", f"{source}!{name}")
                if doi and manifest_doi and manifest_doi != doi:
                    add("SUPPORT-ARCHIVE-IDENTITY-DOI", f"manifest DOI {manifest_doi!r} does not match current Version DOI {doi!r}", f"{source}!{name}")
                if paper_title and manifest_title and _plain_tokens(manifest_title) != expected_title_tokens:
                    add("SUPPORT-ARCHIVE-IDENTITY-TITLE", "manifest identifies a different paper title", f"{source}!{name}")

        for directory in sorted(identity_directories):
            prefix = f"{directory}/" if directory else ""
            for readme_name in (f"{prefix}README.md", f"{prefix}README_REPRODUCE.md"):
                if readme_name not in names:
                    continue
                try:
                    text = payload.read(readme_name).decode("utf-8")
                except UnicodeDecodeError:
                    add("SUPPORT-ARCHIVE-IDENTITY-INVALID", "reader-facing README is not UTF-8", f"{source}!{readme_name}")
                    continue
                found_dois = {match.group(0) for match in ZENODO_DOI.finditer(text)}
                if doi and found_dois != {doi}:
                    add("SUPPORT-ARCHIVE-IDENTITY-DOI", f"README DOI set {sorted(found_dois)!r} does not equal current Version DOI {doi!r}", f"{source}!{readme_name}")
                found_versions = {match.group(1) for match in SEMANTIC_VERSION.finditer(text)}
                if version and version.lstrip("v") not in found_versions:
                    add("SUPPORT-ARCHIVE-IDENTITY-VERSION", f"README does not identify current version {version!r}", f"{source}!{readme_name}")
                if paper_title and not _contains_token_sequence(_plain_tokens(text), expected_title_tokens):
                    add("SUPPORT-ARCHIVE-IDENTITY-TITLE", "README does not identify the current paper title", f"{source}!{readme_name}")

                sums_name = f"{prefix}SHA256SUMS"
                sums_targets: set[str] = set()
                if sums_name in names:
                    try:
                        sums_text = payload.read(sums_name).decode("utf-8")
                    except UnicodeDecodeError:
                        sums_text = ""
                    for line in sums_text.splitlines():
                        match = SHA256SUM_LINE.fullmatch(line)
                        if match is None:
                            continue
                        target = match.group(1).strip().lstrip("./")
                        sums_targets.add(target if target.startswith(prefix) else f"{prefix}{target}")

                checksum_claim = CHECKSUM_EVERY_MEMBER_CLAIM.search(text)
                if checksum_claim:
                    scoped_members = {
                        member
                        for member in names
                        if member.startswith(prefix) and not member.endswith("/")
                    }
                    claimed_members = set(scoped_members)
                    claim_suffix = text[checksum_claim.end() : checksum_claim.end() + 80]
                    if CHECKSUM_SELF_EXCLUSION.search(claim_suffix):
                        claimed_members.discard(sums_name)
                    missing = sorted(claimed_members - sums_targets)
                    if not sums_targets or missing:
                        detail = ", ".join(missing[:3]) or "no parseable checksum entries"
                        add(
                            "SUPPORT-ARCHIVE-CHECKSUM-COVERAGE",
                            f"README claims SHA256SUMS covers every member, but it omits {detail}",
                            f"{source}!{readme_name}",
                        )

                if MANIFEST_SAME_COVERAGE_CLAIM.search(text):
                    manifest_name = f"{prefix}ZENODO_MANIFEST.json"
                    manifest_targets: set[str] = set()
                    if manifest_name in names:
                        try:
                            manifest = json.loads(payload.read(manifest_name).decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            manifest = None
                        if isinstance(manifest, Mapping) and isinstance(manifest.get("files"), list):
                            for entry in manifest["files"]:
                                if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
                                    continue
                                target = str(entry["path"]).strip().lstrip("./")
                                manifest_targets.add(
                                    target if target.startswith(prefix) else f"{prefix}{target}"
                                )
                    if not manifest_targets or manifest_targets != sums_targets:
                        add(
                            "SUPPORT-ARCHIVE-MANIFEST-COVERAGE",
                            "README claims the manifest and SHA256SUMS cover the same paths, but their inventories differ",
                            f"{source}!{readme_name}",
                        )

        if depth >= 2:
            return
        for name in sorted(names):
            if not name.casefold().endswith(".zip"):
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(payload.read(name))) as nested:
                    check_zip(nested, f"{source}!{name}", depth + 1)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                continue

    with zipfile.ZipFile(archive) as payload:
        check_zip(payload, archive.name, 0)
    return issues


def _archive_path_exists(
    printed: str,
    *,
    archive_name: str,
    checksum_name: str,
    members: tuple[str, ...],
) -> bool:
    """Resolve a manuscript's archive-relative ``\\path`` against the exact ZIP."""

    candidate = printed.strip().replace("\\_", "_").strip("/")
    if not candidate:
        return True
    if (
        "/" not in candidate
        and "." not in candidate
        and candidate not in {"SHA256SUMS", "ZENODO_MANIFEST.json", "ARA_SUPPORT_README.md"}
    ):
        return True
    if candidate in {archive_name, checksum_name}:
        return True
    if candidate == ".zip.sha256" and checksum_name.endswith(candidate):
        return True
    for member in members:
        normalized = member.strip("/")
        if normalized == candidate or normalized.endswith(f"/{candidate}"):
            return True
        if f"/{candidate}/" in f"/{normalized}/":
            return True
    return False


def _archive_member_inventory(archive: Path) -> tuple[str, ...]:
    """Index outer and one-level nested ZIP paths for printed-path checks."""

    names: set[str] = set()
    with zipfile.ZipFile(archive) as payload:
        for member in payload.namelist():
            names.add(member)
            if not member.casefold().endswith(".zip"):
                continue
            try:
                nested_bytes = payload.read(member)
                with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
                    names.update(nested.namelist())
            except (OSError, RuntimeError, zipfile.BadZipFile):
                continue
    return tuple(sorted(names))


def _outer_archive_member_inventory(archive: Path) -> tuple[str, ...]:
    """Return outer-ZIP paths relative to its optional enclosing directory."""

    with zipfile.ZipFile(archive) as payload:
        names = [name.strip("/") for name in payload.namelist() if name.strip("/")]
    first_parts = {Path(name).parts[0] for name in names}
    if len(first_parts) == 1:
        prefix = f"{next(iter(first_parts))}/"
        names = [name[len(prefix) :] if name.startswith(prefix) else name for name in names]
    return tuple(sorted(set(names)))


def _path_exists_in_outer_archive(printed: str, members: tuple[str, ...]) -> bool:
    candidate = printed.strip().replace("\\_", "_").strip("/")
    if not candidate:
        return True
    return any(
        member == candidate or member.startswith(f"{candidate}/")
        for member in members
    )


def _archive_filename_is_registered(
    printed: str,
    *,
    outer_archive_name: str,
    outer_members: tuple[str, ...],
) -> bool:
    """Accept the current outer ZIP or a ZIP actually shipped inside it."""

    if printed == outer_archive_name:
        return True
    return any(Path(member).name == printed for member in outer_members)


def _verify_legacy_published_archive(path: Path) -> dict[str, Any]:
    """Verify the bounded legacy v1 archive format used by one frozen release."""

    with zipfile.ZipFile(path) as payload:
        names = payload.namelist()
        if len(names) != len(set(names)):
            raise ValueError("legacy archive contains duplicate paths")
        for name in names:
            pure = Path(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"unsafe legacy archive path: {name}")
        pairs: list[tuple[str, str]] = []
        for name in names:
            if name != "ZENODO_MANIFEST.json" and not name.endswith("/ZENODO_MANIFEST.json"):
                continue
            prefix = name[: -len("ZENODO_MANIFEST.json")]
            sums = f"{prefix}SHA256SUMS"
            if sums in names:
                pairs.append((name, sums))
        if pairs:
            depth = min(len(Path(manifest).parts) for manifest, _ in pairs)
            pairs = [pair for pair in pairs if len(Path(pair[0]).parts) == depth]
        if len(pairs) != 1:
            raise ValueError("legacy archive has no unique top-level manifest/checksum pair")
        manifest_name, sums_name = pairs[0]
        manifest = json.loads(payload.read(manifest_name).decode("utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported legacy archive manifest")
        expected: dict[str, str] = {}
        for line in payload.read(sums_name).decode("utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                raise ValueError("malformed legacy SHA256SUMS")
            expected[match.group(2)] = match.group(1)
        prefix = manifest_name[: -len("ZENODO_MANIFEST.json")]
        for relative, digest in expected.items():
            member = f"{prefix}{relative}"
            if member not in names:
                raise ValueError(f"legacy checksum member is missing: {relative}")
            if hashlib.sha256(payload.read(member)).hexdigest() != digest:
                raise ValueError(f"legacy checksum mismatch: {relative}")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise ValueError("legacy manifest has no file list")
        for item in entries:
            if not isinstance(item, Mapping):
                raise ValueError("legacy manifest contains an invalid file entry")
            relative = str(item.get("path") or "")
            member = f"{prefix}{relative}"
            if not relative or member not in names:
                raise ValueError(f"legacy manifest member is missing: {relative}")
            content = payload.read(member)
            if item.get("bytes") != len(content) or item.get("sha256") != hashlib.sha256(content).hexdigest():
                raise ValueError(f"legacy manifest mismatch: {relative}")
    return {
        "schema_version": 1,
        "paper_id": manifest.get("paper_id"),
        "paper_version": manifest.get("paper_version"),
    }


def audit_manuscript_support(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Audit one manuscript against its current registered Zenodo support record."""

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    settings = load_registry_settings(repo_root)
    policy = publication_policy(settings)
    manuscript = repo_root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    support = metadata.get("support")
    publication = support.get("publication") if isinstance(support, Mapping) else {}
    publication = publication if isinstance(publication, Mapping) else {}
    mode = effective_publication_mode(publication, policy)
    license_id = effective_publication_license(publication, policy)
    status, doi, version = _current_identity(metadata)
    paper_version = str(metadata.get("version") or "")
    review_gate = lifecycle_gate(policy, "before_review")
    minimum_status = str(review_gate.get("minimum_status") or "").strip()
    require_version_doi = bool(review_gate.get("require_version_doi", False))
    require_manuscript_citation = bool(
        review_gate.get("require_manuscript_citation", False)
    )

    if mode == "not_required":
        if require_not_required_reason(policy) and not str(
            publication.get("not_required_reason") or ""
        ).strip():
            issues.append(
                _issue(
                    "SUPPORT-NOT-REQUIRED-REASON",
                    "support publication is exempted without an explicit reason",
                    root=repo_root,
                )
            )
        return {
            "paper_id": paper_id,
            "valid": not issues,
            "mode": mode,
            "status": status,
            "current_version_doi": None,
            "current_support_version": None,
            "bibliography_key": None,
            "errors": issues,
            "warnings": [],
        }
    if mode and mode not in SUPPORT_PUBLICATION_MODES:
        issues.append(
            _issue(
                "SUPPORT-MODE-INVALID",
                f"support publication mode {mode!r} is not supported",
                root=repo_root,
            )
        )
    if minimum_status and not status_meets_minimum(status, minimum_status):
        issues.append(
            _issue(
                "SUPPORT-STATUS-BEFORE-REVIEW",
                f"support publication status {status!r} does not meet the configured "
                f"pre-review minimum {minimum_status!r}",
                root=repo_root,
            )
        )
    if minimum_status in {"draft", "published"}:
        if not license_id:
            issues.append(
                _issue(
                    "SUPPORT-LICENSE-MISSING",
                    "no paper-level or configured default support-material license is available",
                    root=repo_root,
                )
            )
        source_files = publication.get("source_files")
        if not isinstance(source_files, list) or not source_files:
            issues.append(
                _issue(
                    "SUPPORT-SOURCES-MISSING",
                    "the complete public support source set must be declared before review",
                    root=repo_root,
                )
            )
    if not manuscript.is_dir():
        issues.append(_issue("SUPPORT-MANUSCRIPT-MISSING", "canonical manuscript directory is missing", path=manuscript, root=repo_root))
        return {
            "paper_id": paper_id,
            "valid": False,
            "mode": mode,
            "status": status,
            "current_version_doi": doi or None,
            "current_support_version": version or None,
            "bibliography_key": None,
            "errors": issues,
            "warnings": warnings,
        }

    tex_files = _formal_tex_files(manuscript)
    prose_files = _reader_facing_manuscript_files(manuscript)
    paragraphs = [paragraph for path in prose_files for paragraph in _paragraphs(path)]
    support_is_mentioned = any(SUPPORT_MENTION.search(paragraph.text) for paragraph in paragraphs)
    if require_manuscript_citation and not support_is_mentioned:
        issues.append(
            _issue(
                "SUPPORT-MANUSCRIPT-CITATION-REQUIRED",
                "configured policy requires the manuscript to identify and cite its supporting-material record",
                root=repo_root,
            )
        )
    expected = _expected_metadata(publication, repo_root)
    paper_title = str(metadata.get("title") or "").strip()
    issues.extend(
        _standalone_statement_checks(
            prose_files=prose_files,
            metadata=metadata,
            publication=publication,
            paper_title=paper_title,
            root=repo_root,
        )
    )
    support_title = str(expected.get("title") or "").strip()
    if (
        status in {"draft", "published"}
        and paper_title
        and support_title
        and _support_title_core_tokens(support_title) != _plain_tokens(paper_title)
    ):
        issues.append(
            _issue(
                "SUPPORT-RECORD-PAPER-TITLE",
                "current Zenodo support-record title does not identify the current paper title",
                root=repo_root,
            )
        )
    if not doi and (
        status in {"draft", "published"}
        or support_is_mentioned
        or require_version_doi
    ):
        issues.append(
            _issue(
                "SUPPORT-DOI-MISSING",
                "no current Zenodo Version DOI is registered for the required support record",
                root=repo_root,
            )
        )
    if status in {"draft", "published"} and not version:
        issues.append(_issue("SUPPORT-VERSION-MISSING", f"{status} support record has no current support version", root=repo_root))
    if status == "draft" and version and paper_version and version != paper_version:
        issues.append(_issue("SUPPORT-DRAFT-VERSION", f"prepared support version {version!r} does not match manuscript version {paper_version!r}", root=repo_root))

    issues.extend(
        _receipt_checks(
            paper_id=paper_id,
            paper_version=paper_version,
            publication=publication,
            status=status,
            doi=doi,
            version=version,
            root=repo_root,
        )
    )
    issues.extend(_registered_source_checks(publication, version=version, root=repo_root))

    package_values = publication.get("package_files")
    package_paths = [repo_root / str(value) for value in package_values] if isinstance(package_values, list) else []
    verification_values = publication.get("verification_files")
    verification_paths = [repo_root / str(value) for value in verification_values] if isinstance(verification_values, list) else []
    local_package_paths = [*package_paths, *verification_paths]
    archive_paths = [path for path in local_package_paths if path.suffix.casefold() == ".zip"]
    checksum_paths = [path for path in local_package_paths if path.name.casefold().endswith(".zip.sha256")]
    archive_name: str | None = None
    checksum_name: str | None = None
    archive_member_names: tuple[str, ...] = ()
    outer_archive_member_names: tuple[str, ...] = ()
    if status in {"draft", "published"}:
        if len(archive_paths) != 1 or len(checksum_paths) != 1 or len(local_package_paths) != 2:
            issues.append(_issue("SUPPORT-PACKAGE-SET", "current support record must register exactly one ZIP and its local .zip.sha256 verification sidecar", root=repo_root))
        elif not archive_paths[0].is_file() or not checksum_paths[0].is_file():
            missing = archive_paths[0] if not archive_paths[0].is_file() else checksum_paths[0]
            issues.append(_issue("SUPPORT-PACKAGE-MISSING", "registered support package file is missing", path=missing, root=repo_root))
        else:
            archive = archive_paths[0]
            checksum = checksum_paths[0]
            archive_name = archive.name
            checksum_name = checksum.name
            expected_hash = str(publication.get("package_sha256") or "")
            actual_hash = sha256_file(archive)
            if actual_hash != expected_hash:
                issues.append(_issue("SUPPORT-PACKAGE-HASH", "support archive SHA-256 does not match the registry", path=archive, root=repo_root))
            if checksum.read_text(encoding="utf-8") != f"{actual_hash}  {archive.name}\n":
                issues.append(_issue("SUPPORT-PACKAGE-SIDECAR", "support archive checksum sidecar is stale or malformed", path=checksum, root=repo_root))
            try:
                verified = verify_support_archive(archive)
            except Exception as exc:  # The verifier exposes bounded structural failures.
                if status == "published":
                    try:
                        verified = _verify_legacy_published_archive(archive)
                    except Exception:
                        issues.append(_issue("SUPPORT-PACKAGE-INVALID", f"support archive verification failed: {exc}", path=archive, root=repo_root))
                        verified = None
                else:
                    issues.append(_issue("SUPPORT-PACKAGE-INVALID", f"support archive verification failed: {exc}", path=archive, root=repo_root))
                    verified = None
            if verified is not None:
                archive_member_names = _archive_member_inventory(archive)
                outer_archive_member_names = _outer_archive_member_inventory(archive)
                if str(verified.get("paper_id") or "") != paper_id:
                    issues.append(_issue("SUPPORT-PACKAGE-PAPER", "support archive paper_id does not match the registry", path=archive, root=repo_root))
                archive_version = str(verified.get("paper_version") or "")
                if version and archive_version and archive_version != version:
                    issues.append(_issue("SUPPORT-PACKAGE-VERSION", f"support archive version {archive_version!r} does not match current Zenodo version {version!r}", path=archive, root=repo_root))
                try:
                    issues.extend(
                        _archive_reader_checks(
                            archive,
                            status=status,
                            doi=doi,
                            version=version,
                            root=repo_root,
                        )
                    )
                    issues.extend(
                        _archive_identity_checks(
                            archive,
                            paper_id=paper_id,
                            paper_title=paper_title,
                            doi=doi,
                            version=version,
                            expected_creators=_registry_creators(metadata),
                            root=repo_root,
                        )
                    )
                except (OSError, zipfile.BadZipFile) as exc:
                    issues.append(
                        _issue(
                            "SUPPORT-ARCHIVE-PROSE-INVALID",
                            f"cannot inspect reader-facing archive prose: {exc}",
                            path=archive,
                            root=repo_root,
                        )
                    )

    bib_path = manuscript / "references.bib"
    bibliography_key: str | None = None
    if doi and (support_is_mentioned or require_manuscript_citation):
        if not bib_path.is_file():
            issues.append(_issue("SUPPORT-BIB-MISSING", "canonical bibliography is missing", path=bib_path, root=repo_root))
        else:
            bib_text = bib_path.read_text(encoding="utf-8")
            entries = [(key, body, _bib_fields(body)) for key, body in _bib_entries(bib_text)]
            matched = [(key, body, fields) for key, body, fields in entries if doi.casefold() in body.casefold()]
            if len(matched) != 1:
                issues.append(_issue("SUPPORT-BIB-DOI", f"bibliography must contain exactly one entry for current Version DOI {doi}; found {len(matched)}", path=bib_path, root=repo_root))
            else:
                bibliography_key, body, fields = matched[0]
                if version and fields.get("version", "").strip().lstrip("v") != version.lstrip("v"):
                    issues.append(_issue("SUPPORT-BIB-VERSION", f"Zenodo bibliography version {fields.get('version')!r} does not match {version!r}", path=bib_path, root=repo_root))
                expected_title = str(expected.get("title") or "").strip()
                if expected_title and _plain_tokens(fields.get("title", "")) != _plain_tokens(expected_title):
                    issues.append(_issue("SUPPORT-BIB-TITLE", "Zenodo bibliography title does not match the verified current record title", path=bib_path, root=repo_root))
                expected_creator_items = expected.get("creators")
                expected_creators = [str(item.get("name") or "") for item in expected_creator_items if isinstance(item, Mapping)] if isinstance(expected_creator_items, list) else _registry_creators(metadata)
                bib_creators = [value.strip() for value in re.split(r"\s+and\s+", fields.get("author", ""), flags=re.IGNORECASE) if value.strip()]
                if expected_creators and [_person_key(value) for value in bib_creators] != [_person_key(value) for value in expected_creators]:
                    issues.append(_issue("SUPPORT-BIB-CREATORS", "Zenodo bibliography creators do not match the verified current record", path=bib_path, root=repo_root))

    for paragraph in paragraphs:
        has_support_context = bool(SUPPORT_CONTEXT.search(paragraph.text))
        if archive_name:
            for printed in ARCHIVE_FILENAME.findall(paragraph.text):
                if not _archive_filename_is_registered(
                    printed,
                    outer_archive_name=archive_name,
                    outer_members=outer_archive_member_names,
                ):
                    issues.append(_issue("SUPPORT-ARCHIVE-FILENAME", f"printed support archive {printed!r} is not the current deposited filename {archive_name!r}", path=paragraph.path, line=paragraph.line, root=repo_root))
        if archive_name and checksum_name and archive_member_names:
            printed_paths = PATH_PATTERN.findall(paragraph.text)
            for printed in printed_paths:
                normalized = printed.strip().replace("\\_", "_").lstrip("./")
                is_support_path = has_support_context or normalized.startswith(
                    ("result_bundle/", "evidence/", "proof_sources/", "code/")
                )
                if is_support_path and not _archive_path_exists(
                    printed,
                    archive_name=archive_name,
                    checksum_name=checksum_name,
                    members=archive_member_names,
                ):
                    issues.append(
                        _issue(
                            "SUPPORT-ARCHIVE-PATH-MISSING",
                            f"printed support path {printed!r} is absent from the current deposited archive",
                            path=paragraph.path,
                            line=paragraph.line,
                            root=repo_root,
                        )
                    )
            for sentence in re.split(r"(?<=[.!?])\s+", paragraph.text):
                if not ARCHIVE_ROOT_CLAIM.search(sentence):
                    continue
                for printed in PATH_PATTERN.findall(sentence):
                    if _path_exists_in_outer_archive(printed, outer_archive_member_names):
                        continue
                    issues.append(
                        _issue(
                            "SUPPORT-ARCHIVE-PATH-NOT-AT-ROOT",
                            f"printed support path {printed!r} is not at the declared outer archive root",
                            path=paragraph.path,
                            line=paragraph.line,
                            root=repo_root,
                        )
                    )
        if version:
            for printed_match in re.finditer(
                r"public-support-v(\d+\.\d+\.\d+)", paragraph.text, re.IGNORECASE
            ):
                printed_version = printed_match.group(1)
                if printed_version != version.lstrip("v"):
                    issues.append(
                        _issue(
                            "SUPPORT-PUBLIC-DIRECTORY-VERSION",
                            f"printed public-support directory version {printed_version!r} does not match current support version {version!r}",
                            path=paragraph.path,
                            line=paragraph.line,
                            root=repo_root,
                        )
                    )
        if not has_support_context:
            continue
        for label, pattern in PROCESS_PATTERNS:
            if pattern.search(paragraph.text):
                issues.append(_issue("SUPPORT-PROCESS-NARRATIVE", f"reader-facing prose contains internal Zenodo/version process narrative ({label})", path=paragraph.path, line=paragraph.line, root=repo_root))
        if status == "draft" and DRAFT_PUBLIC_CLAIM.search(paragraph.text):
            issues.append(_issue("SUPPORT-DRAFT-PUBLIC-CLAIM", "an unpublished draft is described as publicly accessible", path=paragraph.path, line=paragraph.line, root=repo_root))

    if bibliography_key:
        combined = "\n".join(paragraph.text for paragraph in paragraphs)
        if bibliography_key not in _citations(combined):
            issues.append(_issue("SUPPORT-CITATION-MISSING", f"manuscript does not cite Zenodo bibliography key {bibliography_key}", root=repo_root))
        main_candidates = sorted(manuscript.glob("main*.tex"))
        for main_path in main_candidates:
            expanded = _expand_tex(main_path, manuscript)
            first_mention = next((paragraph for paragraph in expanded if SUPPORT_MENTION.search(paragraph.text)), None)
            if first_mention and bibliography_key not in _citations(first_mention.text):
                issues.append(_issue("SUPPORT-FIRST-CITATION", f"first substantive support-material mention in {main_path.name} must cite {bibliography_key}", path=first_mention.path, line=first_mention.line, root=repo_root))
        for path in tex_files:
            file_paragraphs = _paragraphs(path)
            for index, paragraph in enumerate(file_paragraphs):
                if not AVAILABILITY_HEADING.search(paragraph.text):
                    continue
                window = " ".join(item.text for item in file_paragraphs[index : index + 3])
                if bibliography_key not in _citations(window):
                    issues.append(_issue("SUPPORT-AVAILABILITY-CITATION", f"availability statement must cite {bibliography_key}", path=path, line=paragraph.line, root=repo_root))

    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in issues:
        marker = (item.get("code"), item.get("path"), item.get("line"), item.get("message"))
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return {
        "paper_id": paper_id,
        "valid": not unique,
        "mode": mode,
        "status": status,
        "current_version_doi": doi or None,
        "current_support_version": version or None,
        "bibliography_key": bibliography_key,
        "errors": unique,
        "warnings": warnings,
    }


def support_audit_blockers(result: Mapping[str, Any]) -> list[str]:
    """Project audit failures into stable quality-gate blocker strings."""

    blockers: list[str] = []
    for issue in result.get("errors", []):
        if not isinstance(issue, Mapping):
            continue
        location = str(issue.get("path") or "")
        if issue.get("line") is not None:
            location = f"{location}:{issue['line']}"
        prefix = f"{issue.get('code')}: "
        if location:
            prefix += f"{location}: "
        blockers.append(prefix + str(issue.get("message") or "support-material formal check failed"))
    return blockers
