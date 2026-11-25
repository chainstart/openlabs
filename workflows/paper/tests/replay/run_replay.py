"""Replay the fixture with whichever ``paper_writing`` is first on ``sys.path``; print verdicts.

    PYTHONPATH=<checkout>/workflows/paper python tests/replay/run_replay.py > verdicts.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(1, str(Path(__file__).resolve().parent))

from replay_lib import EXPECTED, digest, load_fixture, replay, snapshot_key, verdicts  # noqa: E402


def main() -> int:
    """With ``--write-expected`` also rewrite ``expected_verdicts.json`` (after a reviewed change)."""
    out = {}
    for snap in load_fixture():
        try:
            out[snapshot_key(snap)] = verdicts(replay(snap)) | {"archived_outcome": snap.get("archived_outcome")}
        except Exception as exc:  # recorded, not hidden: a replay that cannot run is a finding
            out[snapshot_key(snap)] = {"error": f"{type(exc).__name__}: {exc}"}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
    if "--write-expected" in sys.argv[1:]:
        EXPECTED.write_text(json.dumps({key: digest(value) for key, value in out.items()}, indent=1,
                                       sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
