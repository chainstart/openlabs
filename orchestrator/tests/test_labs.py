from __future__ import annotations

from pathlib import Path

from openlabs.labs import discover_labs

CODE_ROOT = Path(__file__).resolve().parents[2]


def test_five_labs_are_discoverable() -> None:
    labs = discover_labs(CODE_ROOT)
    assert set(labs) == {"ai", "materials", "math", "physics", "quant"}
    for lab in labs.values():
        assert lab.command
        assert lab.skill_path() is not None
        assert lab.skill_path().is_file()


def test_math_state_machine_registers_an_optional_continuation_hook() -> None:
    math = discover_labs(CODE_ROOT)["math"]
    protocol = math.protocol("math-state-machine")

    assert protocol is not None
    assert protocol.primary_skill == "math-research-state-machine"
    hook = protocol.hook("continuation")
    assert hook is not None
    assert hook.timeout_seconds == 30
    assert "{project_config}" in hook.command
    assert "{workstream_state}" in hook.command
