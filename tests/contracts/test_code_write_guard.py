"""A production seat cannot write the code checkouts (2026-11-26 owner-seat incident)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "packages" / "research-core" / "lab_runner.py"
GUARD_PATH = ROOT / "packages" / "research-core" / "code_write_guard.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load(GUARD_PATH, "openlabs_code_write_guard_test")
needs_landlock = pytest.mark.skipif(
    guard.landlock_abi() < 1, reason="Landlock is not available on this kernel"
)

# What a seat tries; every step reports instead of raising.
PROBE = r"""
import json, os, sys
from pathlib import Path
code, work = Path(sys.argv[1]), Path(sys.argv[2])
out = {}
def attempt(name, action):
    try:
        action()
        out[name] = "ok"
    except OSError as exc:
        out[name] = type(exc).__name__
attempt("code_create", lambda: (code / "new.py").write_text("x"))
attempt("code_append", lambda: open(code / "module.py", "a").write("# edit\n"))
attempt("code_truncate", lambda: open(code / "module.py", "w").write(""))
attempt("code_mkdir", lambda: (code / "pkg").mkdir())
attempt("code_unlink", lambda: os.unlink(code / "module.py"))
attempt("code_rename_out", lambda: os.rename(code / "module.py", work / "moved.py"))
attempt("code_read", lambda: (code / "module.py").read_text())
attempt("work_create", lambda: (work / "patch.diff").write_text("diff"))
attempt("work_mkdir", lambda: (work / "code-fixes").mkdir())
print(json.dumps(out))
"""


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    code = tmp_path / "factory" / "openlabs"
    code.mkdir(parents=True)
    (code / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    work = tmp_path / "factory" / "openlabs-artifacts" / "attempt"
    work.mkdir(parents=True)
    return code, work


def _assert_code_untouched(result: dict[str, str], code: Path) -> None:
    for name in ("code_create", "code_append", "code_truncate", "code_mkdir",
                 "code_unlink", "code_rename_out"):
        assert result[name] == "PermissionError", (name, result)
    assert result["code_read"] == "ok"
    assert (code / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert sorted(path.name for path in code.iterdir()) == ["module.py"]


def test_writable_roots_cover_everything_but_the_protected_checkouts(tmp_path) -> None:
    code, work = _tree(tmp_path)
    worktrees = tmp_path / "factory" / "build" / "worktrees"
    (worktrees / "dev").mkdir(parents=True)
    (tmp_path / "factory" / "build" / "_trash").mkdir()
    protected = [code, worktrees]

    roots = guard.writable_roots(protected)

    for root in roots:
        for path in protected:
            assert not (root == path or root.is_relative_to(path) or path.is_relative_to(root))
    assert work.parent in roots  # openlabs-artifacts, as a whole
    assert tmp_path / "factory" / "build" / "_trash" in roots
    with pytest.raises(ValueError):
        guard.writable_roots([Path("/")])


def test_code_roots_include_registered_worktrees(tmp_path) -> None:
    workspace = tmp_path / "factory"
    code = workspace / "openlabs"
    elsewhere = tmp_path / "elsewhere-wt"
    elsewhere.mkdir(parents=True)
    registry = code / ".git" / "worktrees" / "w1"
    registry.mkdir(parents=True)
    (registry / "gitdir").write_text(f"{elsewhere}/.git\n", encoding="utf-8")
    (workspace / "build" / "worktrees").mkdir(parents=True)

    roots = guard.code_roots(code, workspace)

    assert roots == sorted({code, workspace / "build" / "worktrees", elsewhere})


@needs_landlock
def test_guarded_process_cannot_write_the_checkout(tmp_path) -> None:
    code, work = _tree(tmp_path)
    completed = subprocess.run(
        [sys.executable, str(GUARD_PATH), "--protect", str(code), "--",
         sys.executable, "-c", PROBE, str(code), str(work)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    _assert_code_untouched(result, code)
    assert result["work_create"] == "ok" and result["work_mkdir"] == "ok"


@needs_landlock
def test_seat_launched_by_the_lab_runner_cannot_write_the_checkout(
    tmp_path, monkeypatch
) -> None:
    """The real _transaction_sandbox argv of a Codex seat, run with a fake ``codex``
    that also starts a child shell (sub-agents and helpers inherit the restriction)."""

    runner = _load(RUNNER_PATH, "openlabs_lab_runner_guard_test")
    code, work = _tree(tmp_path)
    workspace = tmp_path / "factory"
    fake = tmp_path / "bin" / "codex"
    fake.parent.mkdir()
    probe = tmp_path / "bin" / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    fake.write_text(
        "#!/bin/sh\n"
        f'exec /bin/sh -c \'"{sys.executable}" "{probe}" "$0" "$1"\' "{code}" "{work}"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    task = {"transaction": {"mode": "isolated_attempt_workspace", "attempt_root": str(work)},
            "agent_workspace": str(work)}

    command, sandbox = runner._transaction_sandbox([str(fake), "exec"], task, workspace)

    assert sandbox == "codex-native-danger-full-access+landlock-code-readonly"
    assert str(code) in command[: command.index("--")]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60,
                               check=False, env={**os.environ})
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    _assert_code_untouched(result, code)
    assert result["work_create"] == "ok"


def test_runner_fails_closed_without_landlock(tmp_path, monkeypatch) -> None:
    runner = _load(RUNNER_PATH, "openlabs_lab_runner_guard_closed")
    _code, work = _tree(tmp_path)
    task = {"transaction": {"mode": "isolated_attempt_workspace", "attempt_root": str(work)}}
    monkeypatch.setattr(runner._code_write_guard_module(), "landlock_abi", lambda: 0)
    with pytest.raises(RuntimeError, match="Landlock is unavailable"):
        runner._transaction_sandbox(["agy", "-p"], task, tmp_path / "factory")


def test_runner_refuses_an_agent_workspace_inside_a_checkout(tmp_path) -> None:
    runner = _load(RUNNER_PATH, "openlabs_lab_runner_guard_inside")
    code, _work = _tree(tmp_path)
    task = {"transaction": {"mode": "isolated_attempt_workspace", "attempt_root": str(code)}}
    with pytest.raises(ValueError, match="inside a code checkout"):
        runner._transaction_sandbox(["codex", "exec"], task, tmp_path / "factory")


def test_guard_refuses_to_run_unprotected(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "landlock_abi", lambda: 0)
    marker = tmp_path / "ran"
    assert guard.main(["--protect", str(tmp_path), "--", "touch", str(marker)]) == (
        guard.EXIT_UNAVAILABLE
    )
    assert not marker.exists()
