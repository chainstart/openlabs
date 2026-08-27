from __future__ import annotations

import importlib.util
import json
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[2]
LAB_ROOT = CODE_ROOT / "labs" / "math"


def _load_protocol():
    path = LAB_ROOT / "protocols" / "autonomous_math_protocol.py"
    spec = importlib.util.spec_from_file_location("autonomous_math_protocol", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_open_math_research_is_registered_as_an_independent_protocol() -> None:
    manifest = json.loads((LAB_ROOT / "lab.json").read_text(encoding="utf-8"))
    skills = {item["skill_id"]: item for item in manifest["skills"]}
    protocols = {item["protocol_id"]: item for item in manifest["protocols"]}

    skill = skills["open-math-research"]
    assert (LAB_ROOT / skill["path"]).is_file()
    protocol = protocols["open-math-research"]
    assert protocol["primary_skill"] == "open-math-research"
    assert protocol["runtime_skills"] == ["open-math-research"]
    assert protocol["validator"]["command"][-2:] == [
        "--protocol-id",
        "open-math-research",
    ]


def test_open_math_research_reuses_the_evidence_envelope(tmp_path: Path) -> None:
    project = tmp_path / "project.json"
    state = tmp_path / "research_state.json"
    project.write_text(
        json.dumps(
            {
                "schema_version": "openlabs.project.v1",
                "project_id": "open-math-trial",
                "domain": "math",
                "protocol": {
                    "id": "open-math-research",
                    "primary_skill": "open-math-research",
                },
                "workstreams": [{"state_path": state.name}],
            }
        ),
        encoding="utf-8",
    )
    state.write_text(
        json.dumps(
            {
                "schema_version": "openlabs.math_research_workspace.v1",
                "project_id": "open-math-trial",
                "workstream_id": "proof-search",
                "mode": "free_exploration",
                "status": "active",
                "research_log": [],
                "verification_receipts": [],
            }
        ),
        encoding="utf-8",
    )

    protocol = _load_protocol()
    assert protocol.validate(
        project,
        state,
        mode="discovery",
        expected_protocol_id="open-math-research",
    ) == []
