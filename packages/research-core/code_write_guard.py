#!/usr/bin/env python3
"""Keep a production agent from writing the OpenLabs code checkouts (Landlock).

2026-11-26: an owner seat edited ``workflows/paper/paper_writing/formal_checks.py`` in
the live code checkout (the tick loads code from it, so the edit went live unreviewed).
Inside the cc-sg container bubblewrap cannot create a namespace, Codex runs with its
native ``danger-full-access`` and Antigravity with ``--dangerously-skip-permissions``,
so nothing below the agent stopped writes to the code repository.

Landlock needs no namespace (only ``no_new_privs``), is inherited by every child (shells,
sub-agents, ``codex exec`` helpers, review panels) and cannot be lifted by them. Its rules
are allow-lists, so the protected roots are expressed as their complement: write access
is granted beneath every existing directory entry that neither is nor contains a
protected root. Reads and execution are not restricted. A seat proposes a code fix as a
patch in its own attempt workspace; the operator reviews and commits it.

Usage (the lab runner does this): ``code_write_guard.py --protect DIR... -- COMMAND...``.
The command is exec'd under the restriction; if Landlock is unavailable the guard
refuses to start it (exit 126) instead of running it unprotected.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

# linux/landlock.h (syscall numbers are shared by all architectures).
_SYS_CREATE_RULESET = 444
_SYS_ADD_RULE = 445
_SYS_RESTRICT_SELF = 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38
_O_PATH = 0o10000000
_O_CLOEXEC = 0o2000000

_WRITE_FILE = 1 << 1
_REMOVE_DIR = 1 << 4
_REMOVE_FILE = 1 << 5
_MAKE_CHAR = 1 << 6
_MAKE_DIR = 1 << 7
_MAKE_REG = 1 << 8
_MAKE_SOCK = 1 << 9
_MAKE_FIFO = 1 << 10
_MAKE_BLOCK = 1 << 11
_MAKE_SYM = 1 << 12
_REFER = 1 << 13  # ABI 2
_TRUNCATE = 1 << 14  # ABI 3

_FILE_WRITE_RIGHTS = _WRITE_FILE | _TRUNCATE

EXIT_UNAVAILABLE = 126


class GuardUnavailable(RuntimeError):
    """Landlock cannot be applied on this kernel or in this process."""


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def landlock_abi() -> int:
    """The kernel's Landlock ABI version, 0 when Landlock is unavailable."""

    libc = _libc()
    version = libc.syscall(_SYS_CREATE_RULESET, None, ctypes.c_size_t(0),
                           ctypes.c_uint32(_CREATE_RULESET_VERSION))
    return int(version) if version > 0 else 0


def write_rights(abi: int) -> int:
    rights = (
        _WRITE_FILE | _REMOVE_DIR | _REMOVE_FILE | _MAKE_CHAR | _MAKE_DIR | _MAKE_REG
        | _MAKE_SOCK | _MAKE_FIFO | _MAKE_BLOCK | _MAKE_SYM
    )
    if abi >= 2:
        rights |= _REFER
    if abi >= 3:
        rights |= _TRUNCATE
    return rights


def code_roots(code_root: Path, workspace: Path | None = None) -> list[Path]:
    """The code checkouts a production agent may read but never write.

    The checkout this runner was loaded from, ``<workspace>/openlabs``, the development
    worktree area ``<workspace>/build/worktrees`` and every worktree registered in those
    checkouts' ``.git/worktrees/*/gitdir`` (read as files; no git process).
    """

    candidates: list[Path] = [code_root]
    if workspace is not None:
        candidates += [workspace / "openlabs", workspace / "build" / "worktrees"]
    for checkout in list(candidates[:2]):
        registry = checkout / ".git" / "worktrees"
        try:
            entries = sorted(registry.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                gitdir = (entry / "gitdir").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if gitdir:
                candidates.append(Path(gitdir).parent)
    return _minimal(path for path in candidates)


def _minimal(paths: Iterable[Path]) -> list[Path]:
    resolved = sorted({Path(os.path.realpath(path)) for path in paths if path.exists()})
    kept: list[Path] = []
    for path in resolved:
        if path == Path("/"):
            raise ValueError("Refusing to protect the whole filesystem")
        if not any(path.is_relative_to(parent) for parent in kept):
            kept.append(path)
    return kept


def writable_roots(protected: Sequence[Path]) -> list[Path]:
    """Existing entries that together cover the filesystem minus ``protected``.

    Directories on the way to a protected root are not writable themselves (no new
    entries directly in them); symlinks are skipped because Landlock checks the
    resolved path and the target is covered at its real location.
    """

    protected = _minimal(protected)
    roots: list[Path] = []

    def visit(directory: Path) -> None:
        if directory in protected:
            return
        if not any(path.is_relative_to(directory) for path in protected):
            roots.append(directory)
            return
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for entry in children:
            if entry.is_symlink():
                continue
            child = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                visit(child)
            elif child not in protected:
                roots.append(child)

    visit(Path("/"))
    return roots


def restrict(protected: Sequence[Path]) -> int:
    """Forbid writes beneath ``protected`` for this process and its future children.

    Returns the number of Landlock rules added. Raises GuardUnavailable when the
    kernel cannot enforce it.
    """

    abi = landlock_abi()
    if abi < 1:
        raise GuardUnavailable("Landlock is not available on this kernel")
    libc = _libc()
    handled = write_rights(abi)
    attr = _RulesetAttr(handled_access_fs=handled)
    ruleset = libc.syscall(_SYS_CREATE_RULESET, ctypes.byref(attr),
                           ctypes.c_size_t(ctypes.sizeof(attr)), ctypes.c_uint32(0))
    if ruleset < 0:
        raise GuardUnavailable(f"landlock_create_ruleset: {os.strerror(ctypes.get_errno())}")
    added = 0
    try:
        for root in writable_roots(protected):
            try:
                descriptor = os.open(root, _O_PATH | _O_CLOEXEC)
            except OSError:
                continue  # vanished, or unreachable: stays unwritable
            try:
                is_dir = os.path.isdir(root) and not os.path.islink(root)
                rule = _PathBeneathAttr(
                    allowed_access=handled if is_dir else handled & _FILE_WRITE_RIGHTS,
                    parent_fd=descriptor,
                )
                if rule.allowed_access and libc.syscall(
                    _SYS_ADD_RULE, ctypes.c_int(ruleset), ctypes.c_int(_RULE_PATH_BENEATH),
                    ctypes.byref(rule), ctypes.c_uint32(0),
                ) == 0:
                    added += 1
            finally:
                os.close(descriptor)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise GuardUnavailable(f"prctl(no_new_privs): {os.strerror(ctypes.get_errno())}")
        if libc.syscall(_SYS_RESTRICT_SELF, ctypes.c_int(ruleset), ctypes.c_uint32(0)) != 0:
            raise GuardUnavailable(
                f"landlock_restrict_self: {os.strerror(ctypes.get_errno())}"
            )
    finally:
        os.close(ruleset)
    return added


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--protect", action="append", default=[], required=True,
                        help="directory the command may read but not write (repeatable)")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    try:
        restrict([Path(path) for path in args.protect])
    except (GuardUnavailable, OSError, ValueError) as exc:
        print(f"code_write_guard: refusing to start the agent: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    os.execvp(command[0], command)
    return EXIT_UNAVAILABLE  # pragma: no cover - execvp does not return


if __name__ == "__main__":
    raise SystemExit(main())
