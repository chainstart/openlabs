from pathlib import Path
import argparse
import copy
import json
import sys

import pytest

LAB = Path(__file__).resolve().parents[2] / "labs/math"
sys.path.insert(0, str(LAB / "skills/722/scripts"))
sys.path.insert(0, str(LAB / "protocols"))
import discovery  # noqa: E402
import discovery_math_protocol as protocol  # noqa: E402


@pytest.fixture
def trial(tmp_path):
    card = dict(source="test fixture", source_statement="All integers n satisfy P(n)", target_statement="All integers n satisfy P(n)", target_relation="exact", known_frontier="P(0)", remaining_gap="nonzero n", success_criterion="proof or counterexample", boundary_tests=["n=0", "n=-1"])
    root = tmp_path / "trial"
    discovery.initialize(root, "trial", card)
    ledger = root / "workstreams/discovery/discovery-ledger.json"
    (ledger.parent / "evidence.txt").write_text("n=-1 refutes this route, not the target")
    entry = dict(id="round-1", source_task_id="task-1", mechanism="parity", new_evidence="route falsified", remaining_gap="target open", next_test="test symmetry", losses=[], evidence=["evidence.txt"], disposition="refuted", usage=dict(model="fixture", reasoning_effort="max", mode="unknown", agent_seconds=10, input_tokens=None, output_tokens=50, reasoning_tokens=20, cost=None, measurement_source="fixture receipt"))
    return root, ledger, entry


def test_inactive_project_and_profile_validate(trial):
    from openlabs.labs import load_lab
    from openlabs.projects import load_project
    root, ledger, _ = trial
    project = discovery.read(root / "project.json")
    assert project["status"] == project["workstreams"][0]["startup"] == "paused"
    assert load_project(root / "project.json").protocol_id == "math-discovery"
    registered = load_lab(LAB / "lab.json").protocol("math-discovery")
    assert registered.primary_skill == "722"
    assert registered.hook("continuation") is not None
    args = argparse.Namespace(project=root / "project.json", workstream=ledger.parent / "research_state.json", mode="discovery")
    assert protocol.ledger_errors(args) == []
    project, state, policy, digest = discovery.machine._load_validated(args.project, args.workstream, require_evidence_files=True)
    assert state["stage"] == "intake"
    assert policy["stages"]["independent_reconstruction"]["task"]["session_mode"] == "fresh"
    with pytest.raises(FileExistsError):
        discovery.initialize(root, "trial", discovery.read(ledger.parent / "statement.json"))


def test_unknown_usage_and_duplicate_rejected(trial):
    _, ledger, entry = trial
    discovery.checkpoint(ledger, entry)
    status = discovery.status(ledger)
    assert status["usage"]["input_tokens"] is None
    assert status["usage"]["cost"] is None
    assert status["usage"]["output_tokens"] == 50
    with pytest.raises(ValueError, match="duplicate"):
        discovery.checkpoint(ledger, entry)


@pytest.mark.parametrize("change", ["statement", "evidence", "history"])
def test_tampering_rejected(trial, change):
    _, ledger, entry = trial
    discovery.checkpoint(ledger, entry)
    if change == "statement":
        card = discovery.read(ledger.parent / "statement.json")
        card["remaining_gap"] = "changed"
        discovery.write(ledger.parent / "statement.json", card)
    elif change == "evidence":
        (ledger.parent / "evidence.txt").write_text("rewritten")
    else:
        data = discovery.read(ledger)
        data["entries"][0]["remaining_gap"] = "rewritten"
        discovery.write(ledger, data)
    with pytest.raises(ValueError):
        discovery.validate(ledger)


@pytest.mark.parametrize("name", ["../outside.txt", "/etc/passwd", "escape.txt"])
def test_evidence_escape_rejected(trial, name):
    _, ledger, entry = trial
    (ledger.parent / "escape.txt").symlink_to("/etc/passwd")
    entry["evidence"] = [name]
    with pytest.raises(ValueError):
        discovery.checkpoint(ledger, entry)
    assert discovery.validate(ledger)["entries"] == []


def test_staged_workflow_and_budget(trial, monkeypatch, capsys):
    import io
    import subprocess
    root, ledger, _ = trial
    state = ledger.parent / "research_state.json"
    script = LAB / "protocols/research_state_machine.py"
    def run(*arguments):
        return subprocess.run([sys.executable, str(script), *arguments, "--project", str(root / "project.json"), "--workstream", str(state)], capture_output=True, text=True)
    for index, (kind, target) in enumerate((("statement_checked", "representation_exploration"), ("progress_established", "mechanism_search"), ("candidate_ready", "independent_reconstruction"))):
        observed = run("observe", "--observation-id", f"o{index}", "--kind", kind, "--verdict", "accepted", "--actor-role", "researcher", "--source-task-id", "task-1", "--summary", "fixture evidence", "--evidence", "evidence.txt")
        assert observed.returncode == 0, observed.stderr
        moved = run("transition", "--to", target, "--reason", "fixture", "--observation", f"o{index}")
        assert moved.returncode == 0, moved.stderr
    args = argparse.Namespace(project=root / "project.json", workstream=state)
    context = {"schema_version":"openlabs.protocol_hook_context.v1", "event":"continuation", "campaign":{"campaign_id":"discovery", "domain":"math", "max_agent_seconds":50000, "agent_seconds_used":0}, "routing_usage":{}, "project_workstreams":[]}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    assert discovery.machine._decision_command(args) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "continue"
    assert decision["action"]["session_mode"] == "fresh"
    assert decision["action"]["agent_role"] == "reviewer"
    context["routing_usage"] = {"protocol_hook:math-discovery-v1:independent_reconstruction":{"task_count":2, "agent_seconds":14400}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(context)))
    assert discovery.machine._decision_command(args) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "defer"
    observed = run("observe", "--observation-id", "fake-pass", "--kind", "reconstruction_passed", "--verdict", "accepted", "--actor-role", "researcher", "--source-task-id", "task-1", "--summary", "fixture", "--evidence", "evidence.txt")
    assert observed.returncode == 0
    assert run("transition", "--to", "reconstructed_result", "--reason", "fixture", "--observation", "fake-pass").returncode != 0
    assert discovery.validate(ledger)["entries"] == []


def test_commit_requires_current_task_and_canonical_prefix(trial, tmp_path, monkeypatch):
    root, ledger, entry = trial
    import shutil
    staged = tmp_path / "staged"
    shutil.copytree(root, staged)
    staged_ledger = staged / "workstreams/discovery/discovery-ledger.json"
    args = argparse.Namespace(project=staged / "project.json", workstream=staged_ledger.parent / "research_state.json", mode="commit")
    context = {"schema_version":"openlabs.protocol_validation_context.v1", "event":"attempt_commit", "canonical":{"workstream_state":str(ledger.parent / "research_state.json")}, "task":{"task_id":"task-2"}}
    monkeypatch.setenv("OPENLABS_PROTOCOL_VALIDATION_CONTEXT", json.dumps(context))
    assert protocol.ledger_errors(args)
    discovery.checkpoint(staged_ledger, entry)
    assert protocol.ledger_errors(args)
    context["task"]["task_id"] = "task-1"
    monkeypatch.setenv("OPENLABS_PROTOCOL_VALIDATION_CONTEXT", json.dumps(context))
    assert protocol.ledger_errors(args) == []
    discovery.checkpoint(ledger, entry)
    changed = copy.deepcopy(discovery.read(staged_ledger))
    changed["entries"] = []
    discovery.write(staged_ledger, changed)
    assert "history" in protocol.ledger_errors(args)[0]


def test_exact_target_and_invalid_usage_fail_before_writing(trial, tmp_path):
    _, ledger, entry = trial
    card = discovery.read(ledger.parent / "statement.json")
    card["target_statement"] = "Only positive n"
    with pytest.raises(ValueError, match="exact"):
        discovery.initialize(tmp_path / "bad", "bad", card)
    assert not (tmp_path / "bad").exists()
    entry["usage"]["agent_seconds"] = float("nan")
    with pytest.raises(ValueError):
        discovery.checkpoint(ledger, entry)
