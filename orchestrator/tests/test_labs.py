from __future__ import annotations

from pathlib import Path

from openlabs.labs import discover_labs

CODE_ROOT = Path(__file__).resolve().parents[2]


def test_three_labs_are_discoverable() -> None:
    labs = discover_labs(CODE_ROOT)
    assert set(labs) == {"ai", "materials", "math"}
    for lab in labs.values():
        assert lab.command
        assert lab.skill_path() is not None
        assert lab.skill_path().is_file()
