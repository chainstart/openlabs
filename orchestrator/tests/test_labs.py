from __future__ import annotations

from pathlib import Path

from openlabs.labs import discover_labs, lab_for_domain

CODE_ROOT = Path(__file__).resolve().parents[2]


def test_six_labs_are_discoverable() -> None:
    labs = discover_labs(CODE_ROOT)
    assert set(labs) == {"ai", "biomed", "materials", "math", "physics", "quant"}
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


def test_biology_routes_to_biomed_and_its_registered_research_and_paper_skills() -> None:
    from openlabs.engine import _paper_skill, _research_skill

    lab = lab_for_domain(discover_labs(CODE_ROOT), "biology")
    assert lab.lab_id == "biomed"
    assert lab.protocol("biomed-public-data-pilot").primary_skill == _research_skill("biology")
    assert lab.skill_path(_paper_skill("biology")).is_file()
