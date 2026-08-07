#!/usr/bin/env python3
"""Lint reader-facing Zenodo citations and archive-relative paths.

This is deliberately a narrow mechanical check.  The openlabs-math-paper skill remains
responsible for deciding what is evidence and what belongs in the manuscript.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path


PATH_MACROS = re.compile(r"\\(?:path|texttt)\{([^{}]+)\}")
BIB_ENTRY = re.compile(
    r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n\s*@\w+\s*\{|\Z)",
    re.DOTALL,
)
ABSOLUTE_PATH = re.compile(r"(?:^|\s)(?:/(?:home|Users|tmp|var/tmp)/|[A-Za-z]:[\\/])")
LOCAL_PREFIX = re.compile(r"^(?:\.\./|papers/|manuscript/)")
COMMAND_PREFIX = re.compile(r"^(?:python3?|bash|sh|Rscript)\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a manuscript's Zenodo bibliography citation and printed support paths."
    )
    parser.add_argument("sources", nargs="+", type=Path, help="TeX files or directories to scan")
    parser.add_argument("--bib", required=True, type=Path, help="BibTeX database used by the source")
    parser.add_argument("--doi", required=True, help="published Zenodo Version DOI")
    parser.add_argument("--archive", type=Path, help="exact ZIP deposited for this DOI")
    parser.add_argument(
        "--archive-root",
        default="",
        help="optional enclosing directory inside the ZIP, for example package-v1/",
    )
    parser.add_argument(
        "--relative-base",
        action="append",
        default=[],
        help=(
            "archive-relative project directory introduced once in the manuscript; "
            "later printed paths may be relative to this directory"
        ),
    )
    parser.add_argument(
        "--nested-archive",
        action="append",
        default=[],
        help="ZIP member, relative to --archive-root, whose internal paths may also be cited",
    )
    return parser.parse_args()


def source_files(paths: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file():
            files.add(path)
        elif path.is_dir():
            files.update(p for p in path.rglob("*.tex") if "supplement" not in p.parts)
        else:
            raise FileNotFoundError(path)
    return sorted(files)


def normalized_printed_path(value: str) -> str:
    value = value.replace(r"\_", "_").strip()
    value = COMMAND_PREFIX.sub("", value)
    return value.strip("'\"")


def archive_members(
    path: Path, root: str, nested_archives: list[str]
) -> tuple[set[str], str, list[set[str]]]:
    normalized_root = root.strip("/")
    if normalized_root:
        normalized_root += "/"
    nested_members: list[set[str]] = []
    with zipfile.ZipFile(path) as handle:
        members = {name.lstrip("./") for name in handle.namelist()}
        for nested in nested_archives:
            member = f"{normalized_root}{nested.lstrip('./')}"
            try:
                payload = handle.read(member)
            except KeyError as exc:
                raise FileNotFoundError(f"nested ZIP member {member} in {path}") from exc
            with zipfile.ZipFile(io.BytesIO(payload)) as nested_handle:
                nested_members.append(
                    {name.lstrip("./") for name in nested_handle.namelist()}
                )
    return members, normalized_root, nested_members


def member_exists(
    value: str,
    members: set[str],
    root: str,
    relative_bases: list[str],
    nested_members: list[set[str]],
) -> bool:
    if root and value.rstrip("/") == root.rstrip("/"):
        return True
    normalized = value.lstrip("./")
    candidates = [f"{root}{normalized}"]
    candidates.extend(f"{root}{base}{normalized}" for base in relative_bases)
    if any(candidate in members for candidate in candidates):
        return True
    if value.endswith("/"):
        if any(any(name.startswith(candidate) for name in members) for candidate in candidates):
            return True
        return any(
            any(name.startswith(normalized) for name in nested)
            for nested in nested_members
        )
    return any(normalized in nested for nested in nested_members)


def looks_like_path(value: str) -> bool:
    """Separate filenames/directories from ratios and key=value diagnostics."""
    if "/" not in value:
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\d+/\d+", value):
        return False
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?)/(?:\d+(?:\.\d+)?)", value):
        return False
    return True


def main() -> int:
    args = parse_args()
    findings: list[str] = []
    try:
        tex_files = source_files(args.sources)
    except FileNotFoundError as exc:
        print(f"ERROR: source does not exist: {exc.args[0]}", file=sys.stderr)
        return 2

    if not tex_files:
        print("ERROR: no TeX sources found", file=sys.stderr)
        return 2
    if not args.bib.is_file():
        print(f"ERROR: bibliography does not exist: {args.bib}", file=sys.stderr)
        return 2

    doi = args.doi.removeprefix("https://doi.org/").removeprefix("doi:")
    bib_text = args.bib.read_text(encoding="utf-8")
    keys = [key for key, body in BIB_ENTRY.findall(bib_text) if doi.lower() in body.lower()]
    if not keys:
        findings.append(f"{args.bib}: no bibliography entry contains DOI {doi}")

    texts = {path: path.read_text(encoding="utf-8") for path in tex_files}
    combined = "\n".join(texts.values())
    if keys and not any(
        re.search(rf"\\cite\w*\{{[^}}]*\b{re.escape(key)}\b", combined) for key in keys
    ):
        findings.append(
            f"TeX sources do not cite the Zenodo bibliography key(s): {', '.join(keys)}"
        )

    members: set[str] = set()
    archive_root = ""
    nested_members: list[set[str]] = []
    if args.archive:
        if not args.archive.is_file():
            print(f"ERROR: archive does not exist: {args.archive}", file=sys.stderr)
            return 2
        try:
            members, archive_root, nested_members = archive_members(
                args.archive, args.archive_root, args.nested_archive
            )
        except (FileNotFoundError, zipfile.BadZipFile) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    relative_bases = [
        f"{value.strip('/')}/" for value in args.relative_base if value.strip("/")
    ]
    for base in relative_bases:
        prefix = f"{archive_root}{base}"
        if args.archive and not any(name.startswith(prefix) for name in members):
            print(
                f"ERROR: relative base is absent from deposited ZIP: {base.rstrip('/')}",
                file=sys.stderr,
            )
            return 2

    for path, text in texts.items():
        for line_no, line in enumerate(text.splitlines(), start=1):
            if ABSOLUTE_PATH.search(line):
                findings.append(f"{path}:{line_no}: machine-local absolute path")
            for raw_value in PATH_MACROS.findall(line):
                value = normalized_printed_path(raw_value)
                if not value or value.startswith(("http://", "https://", "doi:")):
                    continue
                if ABSOLUTE_PATH.search(value) or LOCAL_PREFIX.search(value):
                    findings.append(f"{path}:{line_no}: repository/local path: {value}")
                    continue
                if args.archive and looks_like_path(value) and not member_exists(
                    value, members, archive_root, relative_bases, nested_members
                ):
                    findings.append(
                        f"{path}:{line_no}: path is absent from deposited ZIP: {value}"
                    )

    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        return 1

    archive_note = f" and {args.archive}" if args.archive else ""
    print(f"PASS: {len(tex_files)} TeX source(s), DOI {doi}{archive_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
