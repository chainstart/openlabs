"""Read research declarations from a *local*, immutable Formal Conjectures tree.

This is a lexical catalogue adapter, not a Lean elaborator or proof checker.  It
does not import or execute anything in the source tree.  Exact declaration text
and the complete original file are retained so that dependencies, notation and
parser boundaries can be reviewed independently.  In particular, ``sorry`` is
never interpreted as evidence that a mathematical question remains open.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from urllib.parse import quote


UPSTREAM = "https://github.com/google-deepmind/formal-conjectures"
_NAME_PART = r"(?:«[^»\n]+»|[^\s.():\[\]{},=]+)"
_NAME = rf"{_NAME_PART}(?:\.{_NAME_PART})*"
_MODIFIERS = r"(?:(?:private|protected|noncomputable|unsafe|partial|nonrec)\s+)*"
_DECL = re.compile(
    rf"{_MODIFIERS}(?P<kind>theorem|lemma|def|abbrev|opaque|axiom|constant|instance|example|structure|class)\b"
    rf"(?:\s+(?P<name>{_NAME}))?"
)
_SCOPE = re.compile(
    rf"(?m)^[ \t]*(?:(?:noncomputable|public)\s+)?"
    rf"(?P<kind>namespace|section|end)\b(?:[ \t]+(?P<name>{_NAME}))?"
)
# Command boundaries, not tactic identifiers.  Indentation additionally prevents
# a local theorem/let inside a proof from terminating the surrounding declaration.
_COMMAND = re.compile(
    rf"(?m)^(?P<indent>[ \t]*)(?:@\[|#\w+\b|"
    rf"{_MODIFIERS}(?:theorem|lemma|def|abbrev|opaque|axiom|constant|instance|example|structure|class)\b|"
    r"(?:namespace|section|end|import|open|export|variable|variables|include|omit|"
    r"universe|universes|set_option|attribute|local|scoped|notation|infix|infixl|infixr|"
    r"prefix|postfix|syntax|macro|macro_rules|elab|elab_rules|declare_syntax_cat|"
    r"initialize|builtin_initialize|noncomputable|public)\b)"
)
_CATEGORY = re.compile(
    r"\bcategory\s+(?P<category>[A-Za-z_][\w-]*)"
    r"(?:\s+(?:\(\s*(?P<parenthesized>[\w-]+)\s*\)|(?P<plain>[\w-]+)))?"
)


def _masked_source(source: str) -> str:
    """Mask comments/string contents while preserving all offsets and newlines.

    Lean block comments nest.  String quote delimiters remain significant to
    preserve a declaration whose final expression is a string.  Quoted Lean
    identifiers are left intact; apostrophes are valid identifier characters.
    """
    chars = list(source)
    i, size = 0, len(source)
    while i < size:
        if source.startswith("--", i):
            stop = source.find("\n", i)
            stop = size if stop < 0 else stop
            chars[i:stop] = " " * (stop - i)
            i = stop
        elif source.startswith("/-", i):
            start, depth = i, 1
            i += 2
            while i < size and depth:
                if source.startswith("/-", i):
                    depth += 1
                    i += 2
                elif source.startswith("-/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError("Unterminated Lean block comment")
            for index in range(start, i):
                if chars[index] not in "\r\n":
                    chars[index] = " "
        elif source[i] == '"':
            i += 1
            while i < size:
                if source[i] == '"':
                    i += 1
                    break
                if source[i] == "\\" and i + 1 < size:
                    chars[i] = " "
                    i += 1
                if chars[i] not in "\r\n":
                    chars[i] = " "
                i += 1
            else:
                raise ValueError("Unterminated Lean string")
        elif source[i] == "«":
            stop = source.find("»", i + 1)
            if stop < 0:
                raise ValueError("Unterminated Lean quoted identifier")
            i = stop + 1
        else:
            i += 1
    return "".join(chars)


def _attribute_end(masked: str, start: int) -> int:
    depth, pos = 1, start + 2
    while pos < len(masked):
        if masked[pos] == "[":
            depth += 1
        elif masked[pos] == "]":
            depth -= 1
            if not depth:
                return pos + 1
        pos += 1
    raise ValueError("Unterminated Lean attribute block")


def _qualified(namespace: str, name: str) -> str:
    if name.startswith("_root_."):
        return name[len("_root_.") :]
    return f"{namespace}.{name}" if namespace else name


def _namespace_at(masked: str, stop: int) -> str:
    namespace = ""
    stack: list[tuple[str, str | None]] = []
    for scope in _SCOPE.finditer(masked, 0, stop):
        kind, name = scope.group("kind", "name")
        if kind in {"namespace", "section"}:
            stack.append((namespace, name))
            if kind == "namespace" and name:
                namespace = _qualified(namespace, name)
        elif stack:
            namespace, _ = stack.pop()
    return namespace


def _references(source: str) -> list[str]:
    return sorted(
        {url.rstrip(".,;:)") for url in re.findall(r'https?://[^\s<>"\]\}]+', source)}
    )


def _parse_file(path: Path, source_file: str, revision: str, retrieved_at: str) -> list[dict]:
    raw = path.read_bytes()
    source = raw.decode("utf-8")
    masked = _masked_source(source)
    digest = hashlib.sha256(raw).hexdigest()
    commands = list(_COMMAND.finditer(masked))
    imports = [
        module
        for line in re.findall(r"(?m)^[ \t]*import[ \t]+([^\n]+)", masked)
        for module in line.split()
    ]
    erdos_match = re.fullmatch(r"FormalConjectures/ErdosProblems/(\d+)\.lean", source_file)
    erdos_id = str(int(erdos_match.group(1))) if erdos_match else None
    references = _references(source)
    entries: list[dict] = []
    seen_offsets: set[int] = set()
    for attr in re.finditer(r"@\[", masked):
        attr_end = _attribute_end(masked, attr.start())
        category = _CATEGORY.search(masked, attr.start(), attr_end)
        if category is None or category.group("category") != "research":
            continue
        status = category.group("parenthesized") or category.group("plain") or "unknown"
        pos, attributes_end = attr_end, attr_end
        # Other attributes and doc comments can sit between category and theorem.
        while True:
            while pos < len(masked) and masked[pos].isspace():
                pos += 1
            if not masked.startswith("@[", pos):
                break
            pos = _attribute_end(masked, pos)
            attributes_end = pos
        declaration = _DECL.match(masked, pos)
        if declaration is None:
            line = source.count("\n", 0, attr.start()) + 1
            raise ValueError(f"Unsupported research declaration at {source_file}:{line}")
        if pos in seen_offsets:
            continue
        seen_offsets.add(pos)
        kind, name = declaration.group("kind", "name")
        line = source.count("\n", 0, pos) + 1
        anonymous = kind == "example" or not name or name in {":", "("}
        namespace = _namespace_at(masked, pos)
        line_start = masked.rfind("\n", 0, pos) + 1
        prefix = masked[line_start:pos]
        indent = len(prefix) - len(prefix.lstrip(" \t"))
        stop = len(masked)
        for command in commands:
            if command.start() <= pos:
                continue
            if len(command.group("indent")) <= indent:
                stop = command.start()
                break
        # Exclude following declaration docs, preserving internal comments and
        # all significant tokens.  Full context remains available separately.
        end = pos + len(masked[pos:stop].rstrip())
        exact_raw = source[pos:end]
        if not exact_raw:
            raise ValueError(f"Empty research declaration at {source_file}:{line}")
        if anonymous:
            # Anonymous examples have no Lean declaration identifier.  Use exact
            # declaration content, not its line number: adding a module comment
            # or moving the unchanged example must not create a new identity.
            # Do not normalize interior whitespace (it can be significant in
            # strings).  Changed anonymous source needs a new reviewed identity.
            content_id = hashlib.sha256(exact_raw.encode("utf-8")).hexdigest()
            name = f"anonymous_{kind}@sha256-{content_id}"
        full_name = _qualified(namespace, name)
        if erdos_id:
            relation = "formalization_of" if name == f"erdos_{erdos_id}" else "variant_of"
        else:
            relation = "unclassified"
        entries.append(
            {
                "source_id": "formal-conjectures",
                "source_item_id": f"{source_file}::{full_name}",
                "title": full_name,
                "statement_text": exact_raw,
                "statement_language": "lean4",
                "source_url": f"{UPSTREAM}/blob/{revision}/{quote(source_file, safe='/')}#L{line}",
                "source_file": source_file,
                "source_line": line,
                "source_end_line": source.count("\n", 0, end) + 1,
                "source_revision": revision,
                "retrieved_at": retrieved_at,
                "source_status": status,
                "source_category": "research",
                "source_category_raw": source[category.start():category.end()],
                "canonical_erdos_id": erdos_id,
                "relation": relation,
                "namespace": namespace,
                "declaration_name": name,
                "declaration_full_name": full_name,
                "declaration_kind": kind,
                "anonymous_declaration": anonymous,
                "identity_strategy": "source_path_namespace_exact_content_sha256" if anonymous else "source_path_fully_qualified_declaration",
                "declaration_exact_raw": exact_raw,
                "declaration_attributes_text": source[attr.start():attributes_end],
                "file_sha256": digest,
                "contains_sorry": bool(re.search(r"\bsorry\b", masked[pos:end])),
                "source_imports": imports,
                "references": references,
                "verified": False,
                "statement_quality": "lean_source_unverified",
                "context_path": source_file,
                "source_context_text": source,
                "parser": "formal-conjectures-lexical-v1",
                "status_note": "Mathematical status is copied from category research; sorry is only a lexical proof-hole marker. No Lean verification was executed.",
            }
        )
    return entries


def parse_formal_tree(root: Path, revision: str, retrieved_at: str) -> list[dict]:
    """Extract each upstream research declaration; do not deduplicate variants.

    ``root`` may be the repository root or its ``FormalConjectures`` directory.
    ``revision`` must be a full Git commit SHA; mutable branch URLs are rejected.
    Category ``test``, API and textbook declarations are excluded.  An unfamiliar
    research label is retained verbatim, rather than guessed to mean open.
    """
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise ValueError("revision must be a full, immutable 40-character Git commit SHA")
    revision = revision.lower()
    root = Path(root).resolve(strict=True)
    tree = root if root.name == "FormalConjectures" else root / "FormalConjectures"
    if not tree.is_dir():
        raise ValueError(f"Missing FormalConjectures source directory under {root}")
    entries: list[dict] = []
    for path in sorted(tree.rglob("*.lean")):
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"Source symlink escapes snapshot root: {path}")
        source_file = "FormalConjectures/" + path.relative_to(tree).as_posix()
        entries.extend(_parse_file(path, source_file, revision, retrieved_at))
    ids = [entry["source_item_id"] for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate fully qualified research declarations in source snapshot")
    return entries
