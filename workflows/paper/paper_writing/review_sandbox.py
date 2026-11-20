"""Where a Codex review role may read the registered materials.

Codex's ``-s read-only`` sandbox is built on bubblewrap. A container whose seccomp
policy forbids unprivileged user namespaces cannot start it: every shell command of
the role fails before it runs ("bwrap: No permissions to create new namespace"), so a
referee can read the packet but cannot open or run the registered replication files.

Mode selection (:func:`select_mode`):

``read-only`` (native)
    bubblewrap works (probed once per process with ``codex sandbox -- true``). The
    role runs exactly as before: ``-s read-only`` with the absolute material paths.
``readonly-copy`` (fallback)
    bubblewrap does not work. The registered materials are copied into a fresh
    directory outside the campaign workspace, write permission is removed
    (``a-w`` on every file and directory), and the role runs there with
    ``-s danger-full-access``: its working directory is the copy, the prompt names the
    copied paths, and its only writable place is a separate output directory. The copy
    is hashed before and after the run; the registered ``support_sources_sha256`` is
    recomputed over the copy, and the original files are re-hashed after the run. Any
    difference makes the run invalid (:class:`ReadonlyCopyViolation`).

``OPENLABS_REVIEW_SANDBOX`` = ``auto`` (default) | ``native`` | ``readonly_copy``
forces a mode (tests, operators). When the container later allows user namespaces
the probe succeeds and the native sandbox is used again without any change.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

NATIVE = "read-only"
READONLY_COPY = "readonly-copy"
MODE_ENV = "OPENLABS_REVIEW_SANDBOX"
COPY_ROOT_ENV = "OPENLABS_REVIEW_COPY_ROOT"
MANIFEST_FILE = "readonly-copy.json"
SCHEMA = "openlabs.review_readonly_copy.v1"
PROBE_TIMEOUT = 60

_probe_lock = threading.Lock()
_probe_cache: dict[str, dict[str, Any]] = {}


class ReadonlyCopyViolation(RuntimeError):
    """The read-only copy or the registered originals changed: the review run is invalid."""


@dataclass(frozen=True)
class ReviewMaterials:
    """Registered files a review role may inspect.

    ``files`` maps the logical name used by ``support_sources_sha256`` to the original
    file; ``relative`` maps the same names to the path below ``root`` (the copy keeps
    that layout so relative references between the files still resolve).
    """

    root: Path
    files: Mapping[str, Path]
    relative: Mapping[str, str]
    registered_sha256: str | None = None
    interpreter: str | None = None
    notes: Sequence[str] = field(default_factory=tuple)
    # Registered directory entries as listed in the packet: {absolute original: relative}.
    directories: Mapping[str, str] = field(default_factory=dict)
    # Names in ``files`` that are copied and hashed but are not registered support sources
    # (e.g. a frozen attachment); they are left out of the ``support_sources_sha256`` check.
    extras: frozenset[str] = frozenset()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict[str, str]:
    """``{relative path: sha256}`` of every entry below ``root`` (symlinks recorded as such)."""
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            manifest[relative] = "symlink:" + os.readlink(path)
        elif path.is_file():
            manifest[relative] = sha256_file(path)
        elif path.is_dir():
            manifest[relative + "/"] = "dir"
        else:
            manifest[relative] = "special"
    return manifest


def probe_native(codex: str) -> dict[str, Any]:
    """Whether Codex's bubblewrap sandbox starts here (cached per executable)."""
    with _probe_lock:
        if codex in _probe_cache:
            return _probe_cache[codex]
        try:
            proc = subprocess.run([codex, "sandbox", "--", "true"], capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=PROBE_TIMEOUT)
            result = {"available": proc.returncode == 0, "exit_code": proc.returncode,
                      "detail": (proc.stderr or proc.stdout).strip()[-400:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"available": False, "exit_code": None, "detail": f"{type(exc).__name__}: {exc}"[:400]}
        result["probe"] = "codex sandbox -- true"
        _probe_cache[codex] = result
        return result


def select_mode(codex: str) -> tuple[str, dict[str, Any]]:
    """(mode, probe record). The native sandbox wins whenever it works."""
    forced = (os.environ.get(MODE_ENV) or "auto").strip().lower().replace("-", "_")
    if forced == "native":
        return NATIVE, {"forced": "native"}
    if forced == "readonly_copy":
        return READONLY_COPY, {"forced": "readonly_copy"}
    probe = probe_native(codex)
    return (NATIVE if probe["available"] else READONLY_COPY), probe


def _copy_base(workspace: Path) -> Path:
    """Where the copy goes: an operator/scratch directory, else the system temp directory.

    Never inside the campaign workspace (a copy there could be committed or promoted).
    """
    candidates = [os.environ.get(COPY_ROOT_ENV), os.environ.get("OPENLABS_SCRATCH_DIR"),
                  tempfile.gettempdir(), "/tmp"]
    workspace = workspace.resolve()
    for value in candidates:
        if not value:
            continue
        path = Path(value).resolve()
        if path == workspace or workspace in path.parents:
            continue
        path.mkdir(parents=True, exist_ok=True)
        return path
    raise ReadonlyCopyViolation(f"no copy location outside the workspace {workspace}")


def _lock(path: Path) -> None:
    """Remove every write bit below ``path`` (files first, then directories bottom-up)."""
    entries = sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    for entry in entries + [path]:
        if entry.is_symlink():
            continue
        mode = entry.stat().st_mode
        entry.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _unlock(path: Path) -> None:
    for entry in [path, *path.rglob("*")]:
        if entry.is_symlink() or not entry.exists():
            continue
        entry.chmod(entry.stat().st_mode | stat.S_IWUSR)


class ReadonlyCopy:
    """One role's write-protected copy of the registered materials and its output directory."""

    def __init__(self, materials: ReviewMaterials, role_name: str):
        self.materials = materials
        self.base = Path(tempfile.mkdtemp(prefix=f"openlabs-review-{role_name}-", dir=_copy_base(materials.root)))
        self.inputs = self.base / "inputs"
        self.output = self.base / "output"
        self.output.mkdir()
        (self.output / "tmp").mkdir()
        self.original: dict[str, str] = {}
        self.before: dict[str, str] = {}
        self.record: dict[str, Any] = {}

    # ----------------------------------------------------------------- set up
    def create(self) -> dict[str, Any]:
        materials = self.materials
        for name, source in sorted(materials.files.items()):
            if source.is_symlink() or not source.is_file():
                raise ReadonlyCopyViolation(f"registered material is not a regular file: {source}")
            target = self.inputs / materials.relative[name]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            self.original[name] = sha256_file(source)
        _lock(self.inputs)
        self.before = tree_manifest(self.inputs)
        problems = []
        for name, digest in self.original.items():
            if self.before.get(materials.relative[name]) != digest:
                problems.append(f"copy of {name} differs from the original")
        for entry in self.inputs.rglob("*"):
            if entry.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                problems.append(f"write bit still set on {entry.relative_to(self.inputs)}")
        registered = self._registered_check()
        if registered["matches"] is False:
            problems.append(f"registered support_sources_sha256 {materials.registered_sha256} does not "
                            f"match the copy ({registered['copy_sha256']})")
        self.record = {
            "schema_version": SCHEMA,
            "mode": READONLY_COPY,
            "copy_dir": str(self.inputs),
            "output_dir": str(self.output),
            "source_root": str(materials.root),
            "files": [{"name": name, "path": materials.relative[name], "sha256": digest,
                       "registered": name not in materials.extras}
                      for name, digest in sorted(self.original.items())],
            "file_count": len(self.original),
            "write_protected": not any("write bit" in p for p in problems),
            "registered_sources": registered,
            "pre_run": {"ok": not problems, "problems": problems},
        }
        if problems:
            raise ReadonlyCopyViolation("read-only copy preflight failed: " + "; ".join(problems))
        return self.record

    def _registered_check(self) -> dict[str, Any]:
        from paper_writing.support import support_sources_digest

        copied = {name: self.inputs / rel for name, rel in self.materials.relative.items()
                  if name not in self.materials.extras}
        digest = support_sources_digest(copied)
        expected = self.materials.registered_sha256
        return {"registered_sha256": expected, "copy_sha256": digest,
                "matches": None if expected is None else digest == expected,
                "checked_files": len(copied)}

    # ----------------------------------------------------------------- run
    def prompt(self, prompt: str) -> str:
        """The prompt with every original material path replaced by its copy, plus the rules."""
        materials = self.materials
        replacements = {str(source): str(self.inputs / materials.relative[name])
                        for name, source in materials.files.items()}
        replacements.update({original: str(self.inputs / relative)
                             for original, relative in materials.directories.items()})
        for original in sorted(replacements, key=len, reverse=True):
            prompt = prompt.replace(original, replacements[original])
        lines = [
            "## Review execution environment (read-only copy mode)",
            "The Codex bubblewrap sandbox is unavailable on this host, so the registered materials "
            f"were copied to {self.inputs} and made read-only (no write permission on any file or "
            "directory). Your working directory is that copy. Read and run the registered files only "
            "there; the paths listed above already point into it.",
            f"Write anything you need (outputs, caches, temporary files) only below {self.output}; "
            "TMPDIR and OPENLABS_OUTPUT_DIR point there. Do not write to, chmod or move anything in "
            "the copy, the campaign workspace or the data repositories. The copy is hashed before and "
            "after your run, and any change invalidates this review.",
        ]
        if materials.interpreter:
            lines.append(f"Python with the research line's locked environment: {materials.interpreter}")
        lines.extend(str(note) for note in materials.notes)
        return prompt + "\n\n" + "\n".join(lines) + "\n"

    def env(self, env: Mapping[str, str]) -> dict[str, str]:
        result = dict(env)
        result.update({"TMPDIR": str(self.output / "tmp"), "OPENLABS_OUTPUT_DIR": str(self.output),
                       "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPYCACHEPREFIX": str(self.output / "pycache")})
        return result

    # ----------------------------------------------------------------- verify
    def verify(self) -> dict[str, Any]:
        """Re-hash the copy and the originals; raise :class:`ReadonlyCopyViolation` on change."""
        problems: list[str] = []
        after = tree_manifest(self.inputs) if self.inputs.is_dir() else {}
        for key in sorted(set(self.before) | set(after)):
            if self.before.get(key) != after.get(key):
                state = ("added" if key not in self.before else
                         "removed" if key not in after else "modified")
                problems.append(f"copy {state}: {key}")
        for entry in self.inputs.rglob("*") if self.inputs.is_dir() else []:
            if not entry.is_symlink() and entry.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                problems.append(f"copy write permission restored: {entry.relative_to(self.inputs)}")
        for name, source in sorted(self.materials.files.items()):
            current = sha256_file(source) if source.is_file() else None
            if current != self.original[name]:
                problems.append(f"original registered file changed: {self.materials.relative[name]}")
        registered = self._registered_check() if not problems else {"skipped": "copy changed"}
        if registered.get("matches") is False:
            problems.append("registered support_sources_sha256 no longer matches the copy")
        outputs = []
        for path in sorted(self.output.rglob("*")):
            if path.is_file() and not path.is_symlink() and len(outputs) < 200:
                outputs.append({"path": path.relative_to(self.output).as_posix(),
                                "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        self.record["post_run"] = {"ok": not problems, "problems": problems[:50],
                                   "registered_sources": registered}
        self.record["outputs"] = outputs
        self.record["valid"] = not problems
        if problems:
            raise ReadonlyCopyViolation("read-only copy changed during the review run (run invalid): "
                                        + "; ".join(problems[:10]))
        return self.record

    def write_record(self, workdir: Path) -> str:
        text = json.dumps(self.record, indent=2, ensure_ascii=False) + "\n"
        (workdir / MANIFEST_FILE).write_text(text)
        return hashlib.sha256(text.encode()).hexdigest()

    def release(self) -> None:
        """Discard the copy and the scratch output (the manifest in the run directory stays)."""
        if self.base.exists():
            _unlock(self.base)
            shutil.rmtree(self.base, ignore_errors=True)


def materials_from_support(metadata: Mapping[str, Any], root: Path, *,
                           registered_sha256: str | None) -> ReviewMaterials | None:
    """The registered support sources of a paper as review materials (None when there are none)."""
    from paper_writing.support import SupportPackageError, support_sources_logical_paths

    files = ((metadata.get("support") or {}).get("publication") or {}).get("source_files")
    if not isinstance(files, list) or not files:
        return None
    base = root.resolve()
    try:
        logical = support_sources_logical_paths(metadata, repo_root=base)
    except (SupportPackageError, ValueError, OSError):
        return None
    directories = {}
    for value in files:
        if isinstance(value, str) and (base / value).is_dir():
            resolved = (base / value).resolve()
            directories[str(resolved)] = resolved.relative_to(base).as_posix()
    return ReviewMaterials(root=base, files=logical,
                           relative={name: path.relative_to(base).as_posix() for name, path in logical.items()},
                           registered_sha256=registered_sha256,
                           interpreter=line_interpreter(metadata, base), directories=directories)


def line_interpreter(metadata: Mapping[str, Any], root: Path) -> str | None:
    """The research line's Python (``environment.activate`` in research-lines.yaml), if it exists."""
    line = str(metadata.get("research_line") or "").strip()
    path = root / "registry" / "research-lines.yaml"
    if not line or not path.is_file():
        return None
    try:
        import yaml

        document = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001 - a hint only
        return None
    entries = document.get("lines") if isinstance(document, Mapping) else None
    if isinstance(entries, Mapping):
        entry = entries.get(line)
    elif isinstance(entries, list):
        entry = next((item for item in entries if isinstance(item, Mapping)
                      and line in (item.get("id"), item.get("line_id"), item.get("name"))), None)
    else:
        entry = None
    environment = entry.get("environment") if isinstance(entry, Mapping) else None
    activate = str((environment or {}).get("activate") or "").split()
    if activate and Path(activate[0]).is_file():
        return activate[0]
    return None
