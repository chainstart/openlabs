"""Fast-forward the shared data checkout at the start of every tick.

Agents commit and push the data repository from their own worktrees; nobody pulled the shared
checkout (``paths.data``), so it fell a dozen commits behind origin and the tick's readers
(site assignment sync, release, ...) judged stale registry records (TIC 421871796 lost its
site submitter on 2026-11-23 14:07Z). Each tick now runs ``git fetch`` and ``git merge
--ff-only`` there, but only when that is safe: a checkout with uncommitted tracked changes, an
operation in progress (rebase, merge, cherry-pick), a detached HEAD, no upstream, or history
that cannot fast-forward is left exactly as it is. The outcome goes into the tick report
(``data_sync``); a skip is never a tick error.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

FETCH_TIMEOUT_SECONDS = 120
_IN_PROGRESS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
                "BISECT_LOG")


def _git(root: Path, *arguments: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    return subprocess.run(["git", *arguments], cwd=str(root), capture_output=True, text=True,
                          timeout=timeout, check=False, env=environment)


def _detail(completed: subprocess.CompletedProcess[str]) -> str:
    return (completed.stderr or completed.stdout or "").strip()[-300:]


def sync_data_checkout(root: Path, *, fetch: bool = True) -> dict[str, Any]:
    """``{"outcome": ..., ...}``; outcomes other than ``fast_forwarded``/``up_to_date`` are skips."""

    root = Path(root)
    if os.environ.get("OPENLABS_DATA_SYNC", "1") == "0":
        return {"outcome": "skipped", "reason": "disabled (OPENLABS_DATA_SYNC=0)"}
    try:
        top = _git(root, "rev-parse", "--show-toplevel")
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
            return {"outcome": "skipped", "reason": "not_a_git_checkout"}
        for name in _IN_PROGRESS:
            marker = _git(root, "rev-parse", "--git-path", name).stdout.strip()
            if marker and (root / marker).exists():
                return {"outcome": "skipped", "reason": f"operation_in_progress:{name}"}
        branch = _git(root, "symbolic-ref", "-q", "--short", "HEAD")
        if branch.returncode != 0:
            return {"outcome": "skipped", "reason": "detached_head"}
        upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if upstream.returncode != 0:
            return {"outcome": "skipped", "reason": "no_upstream", "branch": branch.stdout.strip()}
        info: dict[str, Any] = {"branch": branch.stdout.strip(), "upstream": upstream.stdout.strip()}
        dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
        if dirty.returncode != 0 or dirty.stdout.strip():
            changed = [line[3:] for line in dirty.stdout.splitlines() if line.strip()]
            return {**info, "outcome": "skipped", "reason": "uncommitted_changes",
                    "files": changed[:10]}
        if fetch:
            remote = info["upstream"].split("/", 1)[0]
            fetched = _git(root, "fetch", "--quiet", remote, timeout=FETCH_TIMEOUT_SECONDS)
            if fetched.returncode != 0:
                return {**info, "outcome": "skipped", "reason": "fetch_failed",
                        "detail": _detail(fetched)}
        counts = _git(root, "rev-list", "--left-right", "--count", "HEAD...@{u}")
        if counts.returncode != 0:
            return {**info, "outcome": "skipped", "reason": "compare_failed", "detail": _detail(counts)}
        ahead, behind = (int(value) for value in counts.stdout.split())
        info.update(ahead=ahead, behind=behind)
        if behind == 0:
            return {**info, "outcome": "up_to_date"}
        if ahead:
            return {**info, "outcome": "skipped", "reason": "diverged"}
        before = _git(root, "rev-parse", "HEAD").stdout.strip()
        merged = _git(root, "merge", "--ff-only", "--quiet", "@{u}")
        if merged.returncode != 0:
            return {**info, "outcome": "skipped", "reason": "fast_forward_refused",
                    "detail": _detail(merged)}
        after = _git(root, "rev-parse", "HEAD").stdout.strip()
        return {**info, "outcome": "fast_forwarded", "from": before[:12], "to": after[:12]}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"outcome": "skipped", "reason": "git_unavailable", "detail": str(exc)[:300]}
