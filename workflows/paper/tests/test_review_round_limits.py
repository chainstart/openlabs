import copy
import hashlib
import json

import pytest

from paper_writing import operations, review_flow as flow


BIO = "20261005-biology-genetics-reference-orientation-depth"
TARGET = "Computational Biology and Chemistry"


def authorized_metadata(root):
    grant = {"paper_id": BIO, "target_journal": TARGET, "max_rounds_per_target": 20,
             "authorization": "The user authorizes 20 rounds only for this paper and target."}
    receipt = {"schema": "openlabs.actual_author_instruction.v1",
               "source": "actual user message in this session", "user_text": "Bio only: 20 rounds.",
               "review_round_limit": grant}
    path = root / "authorization.json"
    path.write_text(json.dumps(receipt))
    policy = dict(grant, authorization={"path": path.name, "sha256": flow._sha256(path.read_bytes()),
                                       "json_pointer": "/review_round_limit", "summary": grant["authorization"]})
    return {"paper_id": BIO, "target_journal": TARGET, "version": "0.1.21",
            "review_round_limit_override": policy}


def config():
    return {"process": flow.PROCESS, "roles": {"editor": {"provider": "openai-codex"},
            "referee_b": {"provider": "openai-codex"}}, "referee_roles": ["referee_b"],
            "rejection_clearance_required": True, "max_rounds_per_target": 15, "timeout_seconds": 1}


def screen():
    return {"decision": "send_to_review", "desk_reject_category": "none"}


def report(ready=True):
    return {"recommendation": "accept" if ready else "major_revision",
            "scientific_blockers": [] if ready else ["Unproved claim"], "required_changes": [],
            "previous_items": [], "scores": {"overall": 6},
            "formal_check_assessment": {"coverage_complete": True, "omissions_or_errors": []}}


@pytest.mark.parametrize("used,override,allowed", [(14, False, True), (15, False, False),
                                                   (15, True, True), (19, True, True), (20, True, False)])
def test_official_run_enforces_effective_paper_target_cap(tmp_path, monkeypatch, used, override, allowed):
    monkeypatch.setattr(flow.formal_checks, 'run_checks', lambda *args: {'valid': True, 'blockers': []})
    monkeypatch.setattr(flow.formal_checks, 'validate_binding', lambda *args: [])
    monkeypatch.setattr(flow.formal_checks, 'packet', lambda *args: 'Formal audit fixture')
    meta = authorized_metadata(tmp_path)
    if not override:
        meta.pop("review_round_limit_override")
    monkeypatch.setattr(flow, "review_config", lambda root: config())
    monkeypatch.setattr(flow, "preflight", lambda *args: {"metadata": meta, "target": TARGET,
        "expanded": "Current complete manuscript", "bibliography": "", "fingerprints": {}, "blockers": []})
    monkeypatch.setattr(flow, "completed_rounds", lambda *args: [{"stage_reached": "decision"}] * used)
    monkeypatch.setattr(flow, "_previous_round", lambda *args: None)
    calls = []
    def role(**kwargs):
        calls.append(kwargs["role_name"])
        return ({"editor": screen(), "referee_b": report(), "decision_letter": {"letter": "Internal decision"}}
                [kwargs["role_name"]], {})
    monkeypatch.setattr(flow, "run_role", role)
    if not allowed:
        with pytest.raises(ValueError, match=f"used all {20 if override else 15} review rounds"):
            flow.run_review(BIO, root=tmp_path, apply=False)
        assert calls == []
    else:
        result = flow.run_review(BIO, root=tmp_path, apply=False)
        assert result["round_for_target"] == used + 1
        assert calls == ["editor", "referee_b", "decision_letter"]
        assert ("review_round_limit_override" in result) == override


@pytest.mark.parametrize("mutation", ["other_paper", "other_target", "forged_grant_paper",
    "forged_grant_target", "cap", "bool_cap", "missing", "changed", "digest", "traversal",
    "absolute", "symlink", "pointer", "summary", "fake_source", "empty_user_text", "oversized"])
def test_override_fails_closed(tmp_path, mutation):
    meta = authorized_metadata(tmp_path)
    policy = meta["review_round_limit_override"]
    auth = policy["authorization"]
    path = tmp_path / "authorization.json"
    paper, target = BIO, TARGET
    if mutation == "other_paper": paper = "unrelated"
    elif mutation == "other_target": target = "Another Journal"
    elif mutation == "cap": policy["max_rounds_per_target"] = 21
    elif mutation == "bool_cap": policy["max_rounds_per_target"] = True
    elif mutation == "missing": path.unlink()
    elif mutation == "changed": path.write_text("changed")
    elif mutation == "digest": auth["sha256"] = "invalid"
    elif mutation == "traversal": auth["path"] = "../authorization.json"
    elif mutation == "absolute": auth["path"] = str(path)
    elif mutation == "symlink":
        link = tmp_path / "link.json"; link.symlink_to(path); auth["path"] = link.name
    elif mutation == "pointer": auth["json_pointer"] = "/absent"
    elif mutation == "summary": auth["summary"] = "Unrecorded instruction"
    elif mutation == "oversized": path.write_bytes(b" " * 2_000_001); auth["sha256"] = flow._sha256(path.read_bytes())
    else:
        receipt = json.loads(path.read_text())
        if mutation == "forged_grant_paper": receipt["review_round_limit"]["paper_id"] = "unrelated"
        elif mutation == "forged_grant_target": receipt["review_round_limit"]["target_journal"] = "Another Journal"
        elif mutation == "fake_source": receipt["source"] = "configuration default"
        elif mutation == "empty_user_text": receipt["user_text"] = ""
        path.write_text(json.dumps(receipt)); auth["sha256"] = flow._sha256(path.read_bytes())
    with pytest.raises(ValueError):
        flow.review_round_limit_override(meta, tmp_path, paper, target)


def test_formal_upgrade_changes_legacy_policy_but_cap_still_only_changes_opted_in_paper(tmp_path):
    conf = config()
    old_policy = {k: conf[k] for k in ("process", "roles", "referee_roles", "rejection_clearance_required")}
    expected = hashlib.sha256(json.dumps(old_policy, sort_keys=True).encode()).hexdigest()
    assert flow.review_round_limit_override({"target_journal": "K"}, tmp_path, "other") is None
    assert flow.review_policy_sha256(conf) != expected
    new_policy = dict(old_policy, formal_check=flow.formal_checks.policy())
    new_policy['stage_order'] = 'editor_scientific_referee_core_verification_decision'
    assert flow.review_policy_sha256(conf) == hashlib.sha256(json.dumps(new_policy, sort_keys=True).encode()).hexdigest()
    policy = flow.review_round_limit_override(authorized_metadata(tmp_path), tmp_path, BIO)
    assert flow.review_policy_sha256(conf, None, policy) != expected
    changed = copy.deepcopy(policy); changed["max_rounds_per_target"] = 21
    assert flow.review_policy_sha256(conf, None, changed) != flow.review_policy_sha256(conf, None, policy)


def test_override_does_not_change_existing_workspace_fingerprint_components(tmp_path):
    meta = authorized_metadata(tmp_path)
    manuscript = tmp_path / "papers" / BIO / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(r"\documentclass{article}\begin{document}Fixed theorem.\end{document}")
    strict = copy.deepcopy(meta); strict.pop("review_round_limit_override")
    assert operations._review_workspace_fingerprints(BIO, meta, tmp_path) == operations._review_workspace_fingerprints(
        BIO, strict, tmp_path)


@pytest.mark.parametrize("ready,round_number,status", [(False, 16, "revision_required"),
                                                       (False, 20, "blocked"), (True, 16, "ready")])
def test_apply_and_release_revalidate_cap_and_authenticated_policy(tmp_path, monkeypatch, ready, round_number, status):
    monkeypatch.setattr(flow.formal_checks, 'validate_binding', lambda *args: [])
    meta = authorized_metadata(tmp_path)
    monkeypatch.setattr(flow, "review_config", lambda root: config())
    monkeypatch.setattr(flow, "load_paper_metadata", lambda *args: meta)
    monkeypatch.setattr(flow, "write_paper_metadata", lambda *args: None)
    fingerprints = {"manuscript_snapshot_sha256": "a" * 64}
    monkeypatch.setattr(operations, "_review_workspace_fingerprints", lambda *args: fingerprints)
    policy = flow.review_round_limit_override(meta, tmp_path, BIO)
    reports = {"referee_b": report(ready)}
    record = {"paper_id": BIO, "target_journal": TARGET, "manuscript_version": "0.1.21",
              "finished_at": "2026-10-11T00:00:00Z", "round_for_target": round_number,
              "review_policy_sha256": flow.review_policy_sha256(config(), None, policy),
              "review_round_limit_override": policy, "prior_decisions": [], "editor_screen": screen(),
              "referee_reports": reports, "merged": flow.merge(screen(), reports), "fingerprints": fingerprints}
    path = tmp_path / "decision.json"; path.write_text(json.dumps(record))
    digest = flow._sha256(path.read_bytes())
    release = flow.apply_decision(BIO, root=tmp_path, decision_path=path, digest=digest)
    assert release["status"] == status and release["max_rounds_per_target"] == 20
    if ready:
        assert flow.validate_unified_release(BIO, meta, tmp_path, "a" * 64) == []
        release["max_rounds_per_target"] = 15
        assert flow.validate_unified_release(BIO, meta, tmp_path, "a" * 64)
        release["max_rounds_per_target"] = 20
        removed = copy.deepcopy(meta); removed.pop("review_round_limit_override")
        assert flow.validate_unified_release(BIO, removed, tmp_path, "a" * 64)
        (tmp_path / "authorization.json").write_text("Changed actual grant")
        assert flow.validate_unified_release(BIO, meta, tmp_path, "a" * 64)
        with pytest.raises(ValueError, match="authorization missing or changed"):
            flow.apply_decision(BIO, root=tmp_path, decision_path=path, digest=digest)
