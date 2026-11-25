"""Deterministic single-file flattening of a LaTeX manuscript (user 2026-11-25).

"一个论文应该整合成一个 tex，最多加一个 bib 的参考文献，不要散乱成很多章节 tex，也不要夹杂很多无关的
文件。"  :func:`flatten` turns a manuscript directory into exactly that:

* ``main.tex`` -- every local ``\\input``/``\\include`` expanded in place (``\\include`` keeps its
  ``\\clearpage`` pair), local ``.sty`` packages loaded without options inlined into the preamble
  between ``\\makeatletter``/``\\makeatother``, the bibliography command pointed at one file;
* ``references.bib`` -- the one bibliography (several local ``.bib`` files are concatenated in
  their declared order);
* only the files the build still needs: the figures the text includes, a journal's own document
  class / bibliography style (``.cls``/``.bst``/``.clo``) and any other local file the last build
  read (``main.fls``) that cannot be inlined (for example a pgfplots data table).

Everything else in the directory (build products, figure sources, notes, unused figures, chapter
files) is left out and listed in the report.  The transformation is pure text: the same inputs
always give the same bytes, so the handoff package stays content-addressed.  :func:`verify`
compiles the original and the flattened copy in scratch directories and compares the PDFs page by
page (text extracted with ``pdftotext``); it never writes into the manuscript directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "openlabs.flatten_tex.v1"
GRAPHIC_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".mps", ".jbig2", ".jb2", ".svg")
# Files a TeX build reads that are never inlined: class/style support the journal requires as
# separate files.
KEEP_SUFFIXES = (".cls", ".bst", ".clo", ".cfg", ".def", ".fd")
BUILD_PRODUCTS = (".aux", ".bbl", ".blg", ".fls", ".log", ".out", ".toc", ".lof", ".lot", ".spl",
                  ".fdb_latexmk", ".synctex.gz", ".run.xml", ".bcf", ".xdv", ".nav", ".snm", ".vrb")

_INPUT = re.compile(r"\\(input|include)\s*(?:\{([^{}]+)\}|(?<=input)\s+([^\s{}\\%]+))")
_USEPACKAGE = re.compile(r"\\(usepackage|RequirePackage)\s*(\[[^\]]*\])?\s*\{([^{}]+)\}")
_GRAPHICS = re.compile(
    r"\\(includegraphics|includepdf|includesvg)\s*\*?\s*(?:<[^>]*>\s*)?(?:\[(?:[^\[\]]|\[[^\]]*\])*\]\s*)*\{([^{}]+)\}")
_GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\}\s*)+)\}")
_BIBLIOGRAPHY = re.compile(r"\\bibliography\s*\{([^{}]+)\}")
_ADDBIBRESOURCE = re.compile(r"\\(addbibresource|addglobalbib)\s*(\[[^\]]*\])?\s*\{([^{}]+)\}")
_DOCUMENTCLASS = re.compile(r"\\documentclass\s*(\[[^\]]*\])?\s*\{([^{}]+)\}")
_BIBSTYLE = re.compile(r"\\bibliographystyle\s*\{([^{}]+)\}")
_UNSUPPORTED = re.compile(r"\\(import|subimport|subfile|includefrom|inputfrom|InputIfFileExists|"
                          r"lstinputlisting|verbatiminput|VerbatimInput)\b")


HEADER = ("% Single-file manuscript: the former \\input/\\include files are inlined between\n"
          "% '---- begin/end <file> ----' comments; the \\relax{} after each one stands where LaTeX's\n"
          "% \\input ran its file hooks, so the typeset output is unchanged.\n")


class FlattenError(RuntimeError):
    """The manuscript cannot be flattened faithfully (reported, never guessed around)."""


@dataclass
class FlatResult:
    main_tex: str
    bib: str | None
    files: dict[str, Path]  # output-relative path -> source file
    report: dict[str, Any] = field(default_factory=dict)


def _code_part(line: str) -> tuple[str, str]:
    """Split a source line into its code and its comment (a ``%`` not escaped)."""
    match = re.search(r"(?<!\\)(?:\\\\)*%", line)
    if not match:
        return line, ""
    cut = match.end() - 1
    return line[:cut], line[cut:]


def _resolve_tex(base: Path, name: str) -> Path | None:
    name = name.strip()
    if not name or "#" in name:
        return None
    candidate = (base / name)
    for path in (candidate, candidate.with_name(candidate.name + ".tex")):
        if path.is_file() and path.resolve().is_relative_to(base.resolve()):
            return path
    return None


def _relative(base: Path, path: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _expand(path: Path, base: Path, report: dict[str, Any], stack: tuple[Path, ...] = ()) -> str:
    resolved = path.resolve()
    if resolved in stack:
        raise FlattenError(f"\\input cycle at {_relative(base, path)}")
    lines = path.read_text(encoding="utf-8", errors="surrogateescape").split("\n")
    out: list[str] = []
    for line in lines:
        code, comment = _code_part(line)
        if _UNSUPPORTED.search(code):
            report.setdefault("unsupported", []).append(
                {"file": _relative(base, path), "command": _UNSUPPORTED.search(code).group(0)})
        endinput = re.search(r"\\endinput\b", code)
        if endinput and stack:  # \endinput of an \input file: TeX finishes this line, then stops
            code = code[:endinput.start()] + code[endinput.end():]
        pieces: list[str] = []
        cursor = 0
        for match in _INPUT.finditer(code):
            name = match.group(2) or match.group(3) or ""
            target = _resolve_tex(base, name)
            if target is None:
                continue  # a TeX-distribution file (e.g. glyphtounicode): left for TeX to find
            pieces.append(code[cursor:match.start()])
            inner = _expand(target, base, report, (*stack, resolved))
            relative = _relative(base, target)
            report.setdefault("inlined_inputs", []).append(relative)
            # TeX reads the file's lines as if they stood here: the text before the command runs
            # straight into the file's first line (the "%" ends the line without a space), the
            # file's last line ends with its own end-of-line space, and the rest of this line
            # follows.  A file ending in a newline does not add an empty line (no \\par).
            if inner.endswith("\n"):
                inner = inner[:-1]
            if match.group(1) == "include":
                pieces.append(f"\\clearpage%\n% ---- begin {relative} (\\include) ----\n{inner}\n"
                              f"% ---- end {relative} ----\n\\clearpage{{}}")
            elif match.group(2) is not None:
                # LaTeX's \\input{...} runs its (non-expandable, no-op) file hooks after the file;
                # \\relax{} stands in their place. In a table they open one more, empty row; in a
                # paragraph the end of this line still adds its space. Either way the typeset
                # output, line breaks and page breaks stay as they were.
                pieces.append(f"%\n% ---- begin {relative} ----\n{inner}\n% ---- end {relative} ----\n"
                              "\\relax{}")
            else:
                # The primitive \\input name: the space or line end after the name ended it.
                pieces.append(f"%\n% ---- begin {relative} ----\n{inner}\n% ---- end {relative} ----\n")
                if not code[match.end():].strip() and not comment:
                    pieces[-1] = pieces[-1][:-1]
            cursor = match.end()
        if pieces:
            out.append("".join(pieces) + code[cursor:] + comment)
        else:
            out.append(code + comment)
        if endinput and stack:
            break
    return "\n".join(out)


def _vendored(base: Path, name: str, text: str) -> bool:
    """A copy of a distribution (CTAN) package kept next to the manuscript, not the paper's macros.

    It stays a separate file: the journal's TeX installation has it anyway, and inlining a
    third-party package would hide its licence header inside the manuscript.
    """
    notice = base / "VENDORED-LICENSES.md"
    if notice.is_file() and re.search(rf"\b{re.escape(name)}\.sty\b", notice.read_text(errors="replace")):
        return True
    return bool(re.search(r"LaTeX Project Public License|\bLPPL\b", text[:6000]))


_SUPPORT_REFERENCE = re.compile(
    r"\\(?:RequirePackage|usepackage|LoadClass|LoadClassWithOptions|RequirePackageWithOptions)\s*"
    r"(?:\[[^\]]*\])?\s*\{([^{}]+)\}|\\input\s*\{?([A-Za-z0-9_.\-/]+\.(?:clo|cfg|def|fd|sty|tex))\}?")


def _support_closure(base: Path, files: dict[str, Path]) -> list[str]:
    """Local support files that kept classes and packages load themselves (e.g. sn-jnl.cls)."""
    added: list[str] = []
    queue = [path for name, path in files.items() if path.suffix in (".cls", ".sty", ".clo")]
    while queue:
        text = _strip_code_comments(queue.pop().read_text(encoding="utf-8", errors="replace"))
        for match in _SUPPORT_REFERENCE.finditer(text):
            names = ([n.strip() for n in match.group(1).split(",")] if match.group(1)
                     else [match.group(2).strip()])
            for name in names:
                for candidate in ((base / name,) if "." in Path(name).name
                                  else (base / f"{name}.sty", base / f"{name}.cls")):
                    if candidate.is_file() and candidate.name not in files \
                            and candidate.resolve().is_relative_to(base):
                        files[_relative(base, candidate)] = candidate
                        added.append(_relative(base, candidate))
                        queue.append(candidate)
    return added


def _strip_sty(text: str) -> str:
    kept = []
    for line in text.split("\n"):
        code, _ = _code_part(line)
        if re.match(r"\s*\\(ProvidesPackage|NeedsTeXFormat)\b", code):
            continue
        if re.search(r"\\endinput\b", code):
            kept.append(code[:re.search(r"\\endinput\b", code).start()])
            break
        kept.append(line)
    return "\n".join(kept).strip("\n")


def _inline_packages(text: str, base: Path, report: dict[str, Any]) -> tuple[str, set[str]]:
    """Inline option-free local packages loaded by ``\\usepackage`` in the preamble."""
    begin = re.search(r"\\begin\s*\{document\}", text)
    preamble_end = begin.start() if begin else len(text)
    kept_sty: set[str] = set()
    out: list[str] = []
    seen: set[str] = set()
    lines = text[:preamble_end].split("\n")
    for line in lines:
        code, comment = _code_part(line)
        replacement = None
        for match in _USEPACKAGE.finditer(code):
            if match.group(1) != "usepackage":
                continue
            names = [item.strip() for item in match.group(3).split(",") if item.strip()]
            local = [n for n in names if (base / f"{n}.sty").is_file()]
            if not local:
                continue
            options = match.group(2)
            if options:
                kept_sty.update(local)  # options cannot be applied to inlined text
                report.setdefault("kept_packages", []).extend(local)
                continue
            inlinable = []
            for name in local:
                sty = (base / f"{name}.sty").read_text(encoding="utf-8", errors="surrogateescape")
                if re.search(r"\\(DeclareOption|ProcessOptions|ProcessKeyvalOptions|"
                             r"DeclareKeys|ProcessKeyOptions)\b", sty) or _vendored(base, name, sty):
                    kept_sty.add(name)
                    report.setdefault("kept_packages", []).append(name)
                else:
                    inlinable.append(name)
            if not inlinable:
                continue
            remaining = [n for n in names if n not in inlinable]
            blocks = []
            for name in inlinable:
                if name in seen:
                    continue
                seen.add(name)
                body = _strip_sty((base / f"{name}.sty").read_text(encoding="utf-8",
                                                                   errors="surrogateescape"))
                blocks.append(f"% ---- inlined package {name}.sty ----\n\\makeatletter\n{body}\n"
                              f"\\makeatother\n% ---- end {name}.sty ----")
                report.setdefault("inlined_packages", []).append(name)
            head = (f"\\usepackage{{{','.join(remaining)}}}" if remaining else "")
            replacement = (code[:match.start()] + head + ("\n" if head else "") + "\n".join(blocks)
                           + code[match.end():] + comment)
            break
        out.append(replacement if replacement is not None else line)
    flattened = "\n".join(out)
    return flattened + text[preamble_end:], kept_sty


def _graphics_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in _GRAPHICSPATH.finditer(text):
        paths.extend(item.strip() for item in re.findall(r"\{([^{}]*)\}", match.group(1)))
    return paths or [""]


def _resolve_graphic(base: Path, name: str, search: list[str]) -> Path | None:
    name = name.strip().strip('"')
    if not name or "#" in name or "\\" in name:
        return None
    for prefix in search:
        candidate = base / prefix / name
        options = [candidate] + [candidate.with_name(candidate.name + ext) for ext in GRAPHIC_EXTENSIONS]
        for path in options:
            if path.is_file() and path.resolve().is_relative_to(base.resolve()):
                return path
    return None


def _fls_inputs(base: Path, main: Path) -> list[Path] | None:
    fls = main.with_suffix(".fls")
    if not fls.is_file():
        return None  # no record of the last build
    pwd = base
    found: list[Path] = []
    for line in fls.read_text(errors="replace").splitlines():
        if line.startswith("PWD "):
            pwd = Path(line[4:].strip())
        elif line.startswith("INPUT "):
            raw = Path(line[6:].strip())
            path = raw if raw.is_absolute() else pwd / raw
            try:
                if path.is_file() and path.resolve().is_relative_to(base.resolve()):
                    found.append(path.resolve())
            except OSError:
                continue
    return found


def _strip_code_comments(text: str) -> str:
    return "\n".join(_code_part(line)[0] for line in text.split("\n"))


def flatten(manuscript: str | Path, main: str = "main.tex", *, bib_name: str = "references.bib",
            use_fls: bool = True) -> FlatResult:
    """Flatten ``manuscript/main`` (pure: reads the directory, writes nothing)."""
    base = Path(manuscript).resolve()
    main_path = base / main
    if not main_path.is_file():
        raise FlattenError(f"{main} is missing in {base}")
    report: dict[str, Any] = {"schema_version": SCHEMA, "main": main}
    text = _expand(main_path, base, report)
    if report.get("inlined_inputs"):
        text = HEADER + text
    text, kept_sty = _inline_packages(text, base, report)
    code = _strip_code_comments(text)
    if report.get("unsupported"):
        raise FlattenError("unsupported file-reading commands: " + ", ".join(
            f"{item['command']} in {item['file']}" for item in report["unsupported"]))

    files: dict[str, Path] = {}
    # Bibliography: one file named bib_name.
    bib_files: list[Path] = []
    for match in _BIBLIOGRAPHY.finditer(code):
        for name in match.group(1).split(","):
            name = name.strip()
            path = base / (name if name.endswith(".bib") else f"{name}.bib")
            if path.is_file():
                bib_files.append(path)
    for match in _ADDBIBRESOURCE.finditer(code):
        path = base / match.group(3).strip()
        if path.is_file():
            bib_files.append(path)
    ordered = list(dict.fromkeys(p.resolve() for p in bib_files))
    bib_text = None
    stem = bib_name[:-4] if bib_name.endswith(".bib") else bib_name
    if ordered:
        if len(ordered) == 1:
            bib_text = ordered[0].read_text(encoding="utf-8", errors="surrogateescape")
        else:
            bib_text = "\n\n".join(f"% ---- from {_relative(base, p)} ----\n"
                                   + p.read_text(encoding="utf-8", errors="surrogateescape").strip("\n")
                                   for p in ordered) + "\n"
        report["bibliography"] = {"sources": [_relative(base, p) for p in ordered], "output": bib_name}

        def bib_replace(match: re.Match[str]) -> str:
            names = [n.strip() for n in match.group(1).split(",") if n.strip()]
            local = [n for n in names if (base / (n if n.endswith(".bib") else f"{n}.bib")).is_file()]
            other = [n for n in names if n not in local]
            return "\\bibliography{" + ",".join([stem, *other] if local else other) + "}"

        def resource_replace(match: re.Match[str]) -> str:
            if (base / match.group(3).strip()).is_file():
                return f"\\{match.group(1)}{match.group(2) or ''}{{{bib_name}}}"
            return match.group(0)

        seen_resource = False

        def resource_once(match: re.Match[str]) -> str:
            nonlocal seen_resource
            if (base / match.group(3).strip()).is_file():
                if seen_resource:
                    return ""
                seen_resource = True
            return resource_replace(match)

        text = _rewrite_code(text, _BIBLIOGRAPHY, bib_replace)
        text = _rewrite_code(text, _ADDBIBRESOURCE, resource_once)
        code = _strip_code_comments(text)

    # Class and bibliography style shipped with the manuscript.
    for match in _DOCUMENTCLASS.finditer(code):
        path = base / f"{match.group(2).strip()}.cls"
        if path.is_file():
            files[path.name] = path
    for match in _BIBSTYLE.finditer(code):
        path = base / f"{match.group(1).strip()}.bst"
        if path.is_file():
            files[path.name] = path
    for name in sorted(kept_sty):
        files[f"{name}.sty"] = base / f"{name}.sty"
    support = _support_closure(base, files)
    # A bibliography style chosen through a class option (sn-jnl: \documentclass[sn-mathphys-ay]).
    kept_text = code + "".join(path.read_text(errors="replace") for path in files.values()
                               if path.suffix in (".cls", ".sty"))
    for path in sorted(base.glob("*.bst")):
        if path.name not in files and re.search(rf"(?<![\w-]){re.escape(path.stem)}(?![\w-])", kept_text):
            files[path.name] = path
            support.append(path.name)
    if support:
        report["support_files"] = support

    # Figures the text includes.
    search = _graphics_paths(code)
    unresolved: list[str] = []
    for match in _GRAPHICS.finditer(code):
        name = match.group(2)
        path = _resolve_graphic(base, name, search)
        if path is None:
            if "#" in name or "\\" in name:
                unresolved.append(name)
            else:
                report.setdefault("missing_graphics", []).append(name)
            continue
        files[_relative(base, path)] = path
    # Whatever else the last build read locally and the text cannot carry.
    fls = _fls_inputs(base, main_path) if use_fls else None
    inlined = {(base / item).resolve() for item in report.get("inlined_inputs", [])}
    inlined |= {(base / f"{name}.sty").resolve() for name in report.get("inlined_packages", [])}
    inlined |= set(ordered) | {main_path.resolve()}
    if fls is not None:
        report["fls_used"] = True
        for path in fls:
            if path in inlined or path.suffix.lower() in BUILD_PRODUCTS or path.suffix.lower() == ".tex":
                continue
            relative = _relative(base, path)
            is_graphic = path.suffix.lower() in GRAPHIC_EXTENSIONS
            if is_graphic and not unresolved:
                continue  # the text names every figure; a stale fls entry is not a reason to ship one
            if relative not in files:
                files[relative] = path
                report.setdefault("fls_files", []).append(relative)
    elif unresolved:
        raise FlattenError("figures named through macros cannot be resolved without a current "
                           f"main.fls: {', '.join(sorted(set(unresolved)))}")
    if report.get("missing_graphics"):
        raise FlattenError("included figures are missing: " + ", ".join(report["missing_graphics"]))
    if bib_text is not None:
        files.pop(bib_name, None)
    report["files"] = sorted(files)
    every = sorted(_relative(base, p) for p in base.rglob("*") if p.is_file())
    shipped = set(report["files"]) | {main} | ({bib_name} if bib_text is not None else set())
    report["excluded"] = [item for item in every if item not in shipped]
    report["main_sha256"] = hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()
    return FlatResult(main_tex=text, bib=bib_text, files=files, report=report)


def _rewrite_code(text: str, pattern: re.Pattern[str], replace) -> str:
    out = []
    for line in text.split("\n"):
        code, comment = _code_part(line)
        out.append(pattern.sub(replace, code) + comment)
    return "\n".join(out)


def write(result: FlatResult, output: str | Path, *, bib_name: str = "references.bib") -> list[str]:
    """Write a flattened manuscript into ``output`` (created; must be empty or absent)."""
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise FlattenError(f"output directory is not empty: {target}")
    (target / "main.tex").write_bytes(result.main_tex.encode("utf-8", errors="surrogateescape"))
    written = ["main.tex"]
    if result.bib is not None:
        (target / bib_name).write_bytes(result.bib.encode("utf-8", errors="surrogateescape"))
        written.append(bib_name)
    for relative, source in sorted(result.files.items()):
        path = target / PurePosixPath(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        written.append(relative)
    return written


# --------------------------------------------------------------------------- verification

def _latexmk() -> str:
    found = shutil.which("latexmk")
    if found:
        return found
    candidate = Path.home() / ".local/opt/texlive/bin/x86_64-linux/latexmk"
    if candidate.is_file():
        return str(candidate)
    raise FlattenError("latexmk is not available (source ~/.local/opt/texenv.sh)")


def engine_flag(text: str, manuscript: Path | None = None) -> str:
    """The latexmk engine the manuscript declares (BUILD.txt / latexmkrc / fontspec)."""
    hints = ""
    if manuscript is not None:
        for name in ("BUILD.txt", "latexmkrc", ".latexmkrc", "README.md"):
            path = manuscript / name
            if path.is_file():
                hints += path.read_text(errors="replace")[:4000]
    if re.search(r"xelatex|-xelatex|\$pdf_mode\s*=\s*5", hints, re.I) or re.search(
            r"\\usepackage(\[[^\]]*\])?\{(fontspec|xeCJK|unicode-math)\}", text):
        return "-xelatex"
    if re.search(r"lualatex|\$pdf_mode\s*=\s*4", hints, re.I):
        return "-lualatex"
    return "-pdf"


def _compile(directory: Path, flag: str, timeout: int) -> Path:
    latexmk = _latexmk()
    env = {**os.environ, "PATH": f"{Path(latexmk).parent}:{os.environ.get('PATH', '')}"}
    completed = subprocess.run(
        [latexmk, flag, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "main.tex"],
        cwd=directory, env=env, capture_output=True, text=True, errors="replace", timeout=timeout,
        check=False)
    pdf = directory / "main.pdf"
    if completed.returncode != 0 or not pdf.is_file():
        log = directory / "main.log"
        errors = re.findall(r"^! .*(?:\n.*){0,2}", log.read_text(errors="replace"), re.M) if log.is_file() else []
        blg = directory / "main.blg"
        if blg.is_file():
            errors += re.findall(r"^.*---.*$|^I couldn't.*$", blg.read_text(errors="replace"), re.M)[:3]
        tail = " | ".join(errors[:4]) or (completed.stdout + completed.stderr)[-1500:]
        raise FlattenError(f"latexmk failed in {directory.name}: {tail}")
    return pdf


def _page_texts(pdf: Path) -> list[str]:
    completed = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True,
                               text=True, errors="replace", check=False)
    if completed.returncode != 0:
        raise FlattenError(f"pdftotext failed: {completed.stderr[-400:]}")
    pages = completed.stdout.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return [re.sub(r"\s+", " ", unicodedata.normalize("NFKC", page)).strip() for page in pages]


def compare_pdfs(left: Path, right: Path) -> dict[str, Any]:
    a, b = _page_texts(left), _page_texts(right)
    differing = [index + 1 for index, (x, y) in enumerate(zip(a, b)) if x != y]
    result: dict[str, Any] = {"pages": [len(a), len(b)], "differing_pages": differing,
                              "equivalent": len(a) == len(b) and not differing}
    if differing:
        page = differing[0] - 1
        x, y = a[page], b[page]
        at = next((i for i, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))
        result["first_difference"] = {"page": page + 1, "original": x[max(0, at - 60):at + 60],
                                      "flattened": y[max(0, at - 60):at + 60]}
    return result


def verify(manuscript: str | Path, main: str = "main.tex", *, timeout: int = 900,
           keep: str | Path | None = None) -> dict[str, Any]:
    """Compile the original and the flattened manuscript and compare them page by page."""
    base = Path(manuscript).resolve()
    result = flatten(base, main)
    flag = engine_flag(result.main_tex, base)
    with tempfile.TemporaryDirectory(prefix="flatten-verify-") as scratch:
        scratch_path = Path(scratch)
        original = scratch_path / "original"
        shutil.copytree(base, original, ignore=shutil.ignore_patterns(
            *[f"*{suffix}" for suffix in BUILD_PRODUCTS], "main.pdf", ".git", "_build*", "build"))
        if main != "main.tex":
            (original / main).rename(original / "main.tex")
        flat = scratch_path / "flat"
        write(result, flat)
        left = _compile(original, flag, timeout)
        right = _compile(flat, flag, timeout)
        comparison = compare_pdfs(left, right)
        if keep:
            target = Path(keep)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(left, target / "original.pdf")
            shutil.copyfile(right, target / "flattened.pdf")
    return {"schema_version": SCHEMA, "manuscript": str(base), "engine": flag,
            "files": ["main.tex", *(["references.bib"] if result.bib is not None else []),
                      *sorted(result.files)],
            "excluded_count": len(result.report.get("excluded", [])),
            "inlined_inputs": result.report.get("inlined_inputs", []),
            "inlined_packages": result.report.get("inlined_packages", []),
            **comparison}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="paper-writing flatten",
                                     description="Flatten a LaTeX manuscript into one main.tex + one .bib")
    parser.add_argument("manuscript", help="manuscript directory")
    parser.add_argument("--main", default="main.tex")
    parser.add_argument("--output", help="write the flattened manuscript here (empty directory)")
    parser.add_argument("--verify", action="store_true",
                        help="compile original and flattened copies and compare page text")
    parser.add_argument("--keep-pdfs", help="with --verify: keep both PDFs in this directory")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            payload = verify(args.manuscript, args.main, keep=args.keep_pdfs)
        else:
            result = flatten(args.manuscript, args.main)
            payload = dict(result.report)
            if args.output:
                payload["written"] = write(result, args.output)
    except FlattenError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": payload.get("equivalent", True), **payload}, ensure_ascii=False, indent=2))
    return 0 if payload.get("equivalent", True) else 2


if __name__ == "__main__":
    sys.exit(main())
