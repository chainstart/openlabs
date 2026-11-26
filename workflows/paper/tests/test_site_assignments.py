"""Submitter assignments on the site follow readiness (user rule 2026-11-23)."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from paper_writing.__main__ import build_parser
from paper_writing.site_assignments import classify, sync_site_assignments

ADMIN = "7efafef2-0359-4eca-927e-cb9d6f24558e"
SECOND = "21e32580-f174-492e-999c-cb55df3033b5"
OTHER = "46e4ec0b-c99f-4d5a-a96e-4c9e154e066b"
USERS = [
    {"id": ADMIN, "display_name": "ARA 管理员", "role": "admin", "active": True, "email": None},
    {"id": SECOND, "display_name": "詹静怡", "role": "submitter", "active": True,
     "email": "second@example.test", "author_aliases": []},
    {"id": OTHER, "display_name": "成志东", "role": "submitter", "active": True,
     "email": "other@example.test", "author_aliases": []},
]
PAPER = "20261113-biology-genetics-example"
AUTHORS = [{"name": "First Author", "email": "first@example.test"},
           {"name": "Jingyi Zhan", "name_zh": "詹静怡", "email": "second@example.test"}]


class FakeSite:
    def __init__(self, papers: dict[str, dict]) -> None:
        self.papers = papers
        self.posts: list[tuple[str, dict, str]] = []
        self.counter = 0

    def _request(self, method, path, *, json=None, params=None, idempotency_key=None,
                 allow_not_found=False):
        if path == "/v1/me":
            return {"id": ADMIN, "role": "admin"}
        if path == "/v1/users":
            return copy.deepcopy(USERS)
        if path == "/v1/papers" and method == "GET":
            return [{k: v for k, v in p.items() if k not in {"assignments", "packages"}}
                    for p in self.papers.values()]
        parts = path.strip("/").split("/")
        paper = self.papers.get(parts[2])
        if paper is None:
            if allow_not_found:
                return None
            raise AssertionError(path)
        if method == "GET":
            return copy.deepcopy(paper)
        assert method == "POST" and parts[3:] == ["assignments"] and idempotency_key
        self.posts.append((parts[2], dict(json), idempotency_key))
        for row in paper["assignments"]:
            if row["active"]:
                row.update(active=False, unassigned_at="2026-11-23T21:00:00+08:00")
        self.counter += 1
        paper["assignments"].insert(0, {
            "id": f"00000000-0000-4000-8000-{self.counter:012d}",
            "submitter_id": json["submitter_id"], "active": True, "notes": json["notes"],
            "assigned_at": f"2026-11-23T21:0{self.counter}:00+08:00", "unassigned_at": None})
        return paper["assignments"][0]


def _paper(*, ready=True, lifecycle="assigned", version="0.1.12", attempts=(), assignments=None):
    return {
        "paper_id": PAPER, "lifecycle_status": lifecycle, "current_package_id": "pkg-uuid",
        "packages": [{"id": "pkg-uuid", "version": version, "status": "ready"}],
        "submission_attempts": list(attempts),
        "writing_metadata": {"readiness": {"ready_for_submission": ready},
                             "llm_revision": {"status": "passed" if ready else "draft"}},
        "assignments": assignments if assignments is not None else [
            {"id": "acb74f5d-b7ff-40c7-9155-2d2030196c62", "submitter_id": SECOND, "active": True,
             "notes": "Automatically assigned to the second declared author",
             "assigned_at": "2026-11-15T23:29:35+08:00"}],
    }


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "registry" / "papers").mkdir(parents=True)
    (tmp_path / "registry" / "settings.yaml").write_text(
        yaml.safe_dump({"defaults": {"authors": AUTHORS}}), encoding="utf-8")
    _registry(tmp_path, status="ready", version="0.1.12")
    return tmp_path


def _registry(root: Path, *, status: str, version: str, authors=AUTHORS) -> None:
    (root / "registry" / "papers" / f"{PAPER}.yaml").write_text(yaml.safe_dump({
        "version": version, "writing_release": {"status": status}, "authors": authors,
    }), encoding="utf-8")


def _active(site: FakeSite) -> list[str]:
    return [row["submitter_id"] for row in site.papers[PAPER]["assignments"] if row["active"]]


def test_not_ready_paper_assignment_is_parked_with_the_default_recorded(repo: Path) -> None:
    site = FakeSite({PAPER: _paper(ready=False)})
    plan = sync_site_assignments(site, root=repo)
    assert [e["action"] for e in plan["papers"]] == ["park"] and not site.posts
    result = sync_site_assignments(site, root=repo, apply=True)
    assert result["ok"] and _active(site) == [ADMIN]
    notes = site.posts[0][1]["notes"]
    assert f"default_submitter_id={SECOND}" in notes
    # Idempotent: a second run changes nothing.
    again = sync_site_assignments(site, root=repo, apply=True)
    assert again["changed"] == [] and len(site.posts) == 1


def test_ready_paper_restores_the_recorded_submitter(repo: Path) -> None:
    site = FakeSite({PAPER: _paper(ready=False)})
    sync_site_assignments(site, root=repo, apply=True)
    # A different second author now: the recorded original still wins.
    _registry(repo, status="ready", version="0.1.12",
              authors=[AUTHORS[0], {"name": "Zhidong Cheng", "name_zh": "成志东",
                                    "email": "other@example.test"}])
    paper = site.papers[PAPER]
    paper["writing_metadata"] = {"readiness": {"ready_for_submission": True},
                                 "llm_revision": {"status": "passed"}}
    result = sync_site_assignments(site, root=repo, apply=True)
    assert _active(site) == [SECOND]
    assert result["changed"][0]["target"]["source"] == "placeholder_notes"


def test_ready_paper_without_history_gets_the_second_author(repo: Path) -> None:
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", assignments=[])})
    result = sync_site_assignments(site, root=repo, paper_ids=[PAPER], apply=True)
    assert _active(site) == [SECOND]
    assert result["changed"][0]["target"]["source"] == "byline_second_author"


def test_park_receipt_names_the_original_submitter(repo: Path) -> None:
    revisions = repo / "papers" / PAPER / "revisions"
    revisions.mkdir(parents=True)
    (revisions / "SUBMITTER-HIDE-site-receipt-20261123.json").write_text(json.dumps(
        {"original_assignment": {"submitter_id": OTHER}}), encoding="utf-8")
    site = FakeSite({PAPER: _paper(assignments=[
        {"id": "p1", "submitter_id": ADMIN, "active": True, "notes": "占位",
         "assigned_at": "2026-11-23T20:17:08+08:00"}])})
    sync_site_assignments(site, root=repo, apply=True)
    assert _active(site) == [OTHER]


def test_registry_revision_in_progress_rolls_back_a_ready_site_paper(repo: Path) -> None:
    _registry(repo, status="blocked", version="0.1.13")
    site = FakeSite({PAPER: _paper(ready=True)})
    result = sync_site_assignments(site, root=repo, apply=True)
    entry = result["papers"][0]
    assert entry["state"] == "not_ready" and entry["action"] == "park"
    assert any("revision in progress" in reason for reason in entry["reasons"])
    assert _active(site) == [ADMIN]


def test_ready_paper_without_assignment_stays_unassigned_when_rolled_back(repo: Path) -> None:
    _registry(repo, status="blocked", version="0.2.8")
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", version="0.2.7", assignments=[])})
    result = sync_site_assignments(site, root=repo, apply=True)
    assert result["papers"][0]["action"] == "none" and site.posts == []


@pytest.mark.parametrize("paper", [
    _paper(ready=False, attempts=[{"id": "a", "status": "submitted"}]),
    _paper(ready=False, lifecycle="active"),
    _paper(ready=False, lifecycle="closed"),
])
def test_submitted_or_closed_papers_are_never_touched(repo: Path, paper: dict) -> None:
    site = FakeSite({PAPER: paper})
    result = sync_site_assignments(site, root=repo, paper_ids=[PAPER], apply=True)
    assert result["papers"][0]["state"] == "untouched" and site.posts == []


def test_a_recall_of_an_older_package_does_not_block_a_new_one() -> None:
    paper = _paper()
    paper["writing_metadata"]["polish_recall"] = {"status": "recalled_for_revision",
                                                  "recalled_package_id": "old-pkg"}
    assert classify(paper, None)[0] == "ready"
    paper["writing_metadata"]["polish_recall"]["recalled_package_id"] = "pkg-uuid"
    assert classify(paper, None) == ("not_ready", ["recalled for revision"])


def test_classify_requires_a_ready_current_package() -> None:
    paper = _paper()
    paper["packages"][0]["status"] = "uploading"
    state, reasons = classify(paper, None)
    assert state == "not_ready" and "current package status uploading" in reasons


def test_cli_command_parses() -> None:
    args = build_parser().parse_args(
        ["program", "sync-site-assignments", "--paper-id", PAPER, "--apply", "--json"])
    assert args.paper_id == [PAPER] and args.apply


def test_stale_local_registry_does_not_take_a_site_ready_assignment_away(repo: Path) -> None:
    # TIC 421871796, 2026-11-23 14:07Z: the shared data checkout still had the older
    # revision_required record while the site showed the delivered 0.1.13 package as
    # ready_to_submit; the sync parked the submitter. A lagging registry now only skips.
    _registry(repo, status="revision_required", version="0.1.12")
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", version="0.1.13", assignments=[
        {"id": "a1", "submitter_id": OTHER, "active": True, "notes": "",
         "assigned_at": "2026-11-23T20:00:00+08:00"}])})
    result = sync_site_assignments(site, root=repo, apply=True)
    entry = result["papers"][0]
    assert entry["action"] == "skip" and entry["state"] == "stale_registry"
    assert "older than the site's current package 0.1.13" in entry["why"]
    assert not site.posts and _active(site) == [OTHER]
    assert result["blocked"] == [entry] and result["ok"]


def test_registry_ahead_of_the_site_still_parks(repo: Path) -> None:
    # A revision in progress (local version newer than the delivered package) keeps the rule.
    _registry(repo, status="revision_required", version="0.1.14")
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", version="0.1.13")})
    result = sync_site_assignments(site, root=repo, apply=True)
    assert result["papers"][0]["action"] == "park" and _active(site) == [ADMIN]


def _hold_registry(root: Path) -> None:
    path = root / "registry" / "papers" / f"{PAPER}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["manual_assignment"] = {"hold": True, "by": "owner", "date": "2026-11-24",
                                 "reason": "submitter withdrawn; a person assigns"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_manual_hold_in_the_registry_blocks_the_automatic_assignment(repo: Path) -> None:
    """2026-11-24: the owner withdrew the submitter; a ready paper must stay unassigned."""
    _hold_registry(repo)
    parked = [{"id": "11111111-1111-4111-8111-111111111111", "submitter_id": ADMIN, "active": True,
               "notes": "[openlabs-site-assignment] withdrawn", "assigned_at": "2026-11-24T01:00:00+08:00"},
              {"id": "acb74f5d-b7ff-40c7-9155-2d2030196c62", "submitter_id": SECOND, "active": False,
               "notes": "Automatically assigned", "assigned_at": "2026-11-15T23:29:35+08:00"}]
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", assignments=parked)})
    result = sync_site_assignments(site, root=repo, apply=True)
    assert not site.posts and _active(site) == [ADMIN]
    assert [e["action"] for e in result["papers"]] == ["hold"] and result["held"] == [PAPER]
    assert result["papers"][0]["manual_assignment"]["source"] == "registry"
    assert result["pending"] == [] and result["blocked"] == []
    # Without any active assignment, and when the paper is not ready: still untouched.
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", assignments=[])})
    sync_site_assignments(site, root=repo, paper_ids=[PAPER], apply=True)
    assert not site.posts and _active(site) == []
    site = FakeSite({PAPER: _paper(ready=False)})
    sync_site_assignments(site, root=repo, apply=True)
    assert not site.posts and _active(site) == [SECOND]


def test_manual_hold_note_on_the_site_also_counts(repo: Path) -> None:
    """A lagging data checkout without the registry hold still sees the site's hold note."""
    parked = [{"id": "11111111-1111-4111-8111-111111111111", "submitter_id": ADMIN, "active": True,
               "notes": "[openlabs-site-assignment] 撤回投稿负责人 manual_assignment=hold",
               "assigned_at": "2026-11-24T01:00:00+08:00"}]
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", assignments=parked)})
    result = sync_site_assignments(site, root=repo, apply=True)
    assert not site.posts and result["papers"][0]["action"] == "hold"
    assert result["papers"][0]["manual_assignment"]["source"] == "site_assignment_notes"
    # Lifting the hold (a person assigns, or the note is gone) restores the normal rule.
    site.papers[PAPER]["assignments"][0]["notes"] = "[openlabs-site-assignment] parked"
    result = sync_site_assignments(site, root=repo, apply=True)
    assert result["changed"] and _active(site) == [SECOND]


def test_released_hold_assigns_the_named_submitter_not_the_withdrawn_one(repo: Path) -> None:
    """2026-11-25: the owner named the submitter (now second author) after the 11-24 hold."""
    second = {"name": "Zhidong Cheng", "name_zh": "成志东", "email": "other@example.test"}
    _registry(repo, status="ready", version="0.1.12", authors=[AUTHORS[0], second, AUTHORS[1]])
    path = repo / "registry" / "papers" / f"{PAPER}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["manual_assignment"] = {"hold": False, "by": "owner", "date": "2026-11-25",
                                 "submitter": "Zhidong Cheng", "submitter_zh": "成志东"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    # The placeholder still carries the hold note and records the withdrawn submitter.
    parked = [{"id": "11111111-1111-4111-8111-111111111111", "submitter_id": ADMIN, "active": True,
               "notes": f"[openlabs-site-assignment] 撤回 manual_assignment=hold "
                        f"default_submitter_id={SECOND}",
               "assigned_at": "2026-11-24T01:00:00+08:00"},
              {"id": "acb74f5d-b7ff-40c7-9155-2d2030196c62", "submitter_id": SECOND, "active": False,
               "notes": "Automatically assigned", "assigned_at": "2026-11-15T23:29:35+08:00"}]
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", assignments=copy.deepcopy(parked))})
    plan = sync_site_assignments(site, root=repo)
    entry = plan["papers"][0]
    assert entry["action"] == "assign" and entry["target"]["submitter_id"] == OTHER
    assert entry["target"]["source"] == "manual_assignment" and not site.posts
    result = sync_site_assignments(site, root=repo, apply=True)
    assert result["changed"] and _active(site) == [OTHER]
    # Without a named submitter the byline's second author is used.
    data["manual_assignment"].pop("submitter")
    data["manual_assignment"].pop("submitter_zh")
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", assignments=copy.deepcopy(parked))})
    entry = sync_site_assignments(site, root=repo)["papers"][0]
    assert entry["action"] == "assign" and entry["target"]["submitter_id"] == OTHER


# 2026-11-26: a paper rejected and back before submission (retargeted) was left out of the rule
# because it "has submission attempts" (20260414aiuncertainty0002, 20260415aiuncertainty0004).
REJECTED = {"id": "a1", "attempt_no": 1, "status": "rejected", "journal_name": "PRICAI 2026"}


def test_rejected_and_not_ready_paper_loses_its_submitter(repo: Path) -> None:
    site = FakeSite({PAPER: _paper(ready=False, attempts=[REJECTED])})
    result = sync_site_assignments(site, root=repo, apply=True)
    entry = result["papers"][0]
    assert entry["state"] == "not_ready" and entry["action"] == "park"
    assert _active(site) == [ADMIN]


def test_rejected_and_retargeted_ready_paper_gets_a_submitter(repo: Path) -> None:
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", attempts=[REJECTED], assignments=[])})
    result = sync_site_assignments(site, root=repo, paper_ids=[PAPER], apply=True)
    assert result["papers"][0]["action"] == "assign" and _active(site) == [SECOND]


@pytest.mark.parametrize("attempts", [
    [REJECTED, {"id": "a2", "attempt_no": 2, "status": "preparing"}],
    [REJECTED, {"id": "a2", "attempt_no": 2, "status": "revision_preparing"}],
    [{"id": "a1", "attempt_no": 1, "status": "resubmitted"}],
])
def test_a_later_attempt_in_progress_is_never_touched(repo: Path, attempts: list) -> None:
    site = FakeSite({PAPER: _paper(ready=False, attempts=attempts)})
    result = sync_site_assignments(site, root=repo, paper_ids=[PAPER], apply=True)
    assert result["papers"][0]["state"] == "untouched" and site.posts == []


# 2026-11-26: protections. Any of these keeps the submitter although the latest attempt ended.
NOW = datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)


def _rejected_paper(**extra) -> dict:
    paper = _paper(ready=False, attempts=[REJECTED])
    paper.update(extra)
    return paper


def _plan(repo: Path, paper: dict, **kwargs) -> dict:
    site = FakeSite({PAPER: paper})
    result = sync_site_assignments(site, root=repo, paper_ids=[PAPER], apply=True, **kwargs)
    assert result["ok"]
    return result | {"posts": site.posts, "active": _active(site)}


@pytest.mark.parametrize("lifecycle", ["revision_requested", "active"])
def test_protection_1_journal_lifecycle_keeps_the_submitter(repo: Path, lifecycle: str) -> None:
    result = _plan(repo, _rejected_paper(lifecycle_status=lifecycle))
    entry = result["papers"][0]
    assert entry["state"] == "untouched" and "the journal holds the paper" in entry["reasons"][0]
    assert result["posts"] == [] and result["active"] == [SECOND]


@pytest.mark.parametrize("status", ["open", "claimed"])
def test_protection_2_open_revision_request_keeps_the_submitter(repo: Path, status: str) -> None:
    paper = _rejected_paper(revision_requests=[
        {"id": "r1", "request_id": "rrq_x", "review_round_id": "rnd1", "status": status}])
    result = _plan(repo, paper)
    assert result["papers"][0]["state"] == "untouched" and result["posts"] == []
    assert f"revision request rrq_x is {status}" in result["papers"][0]["reasons"]


def _round(**extra) -> dict:
    return {"id": "rnd1", "attempt_id": "a1", "round_no": 1, "decision": "major_revision",
            "received_at": "2026-11-09T22:02:35+08:00", "due_at": "2026-12-07T08:00:00+08:00",
            "response_submitted_at": None} | extra


@pytest.mark.parametrize("decision", ["major_revision", "minor_revision", "revise_resubmit"])
def test_protection_2_live_revision_round_keeps_the_submitter_despite_a_rejected_attempt(
        decision: str) -> None:
    # The attempt reads "rejected" (a mis-read letter), but the round awaits the revision.
    paper = _rejected_paper(review_rounds=[_round(decision=decision)])
    state, reasons = classify(paper, None, now=NOW)
    assert state == "untouched" and "awaits a response" in reasons[0]


@pytest.mark.parametrize("round_, requests", [
    (_round(due_at="2026-11-01T08:00:00+08:00"), []),                     # deadline passed
    (_round(response_submitted_at="2026-11-20T10:00:00+08:00"), []),      # answered
    (_round(), [{"id": "r1", "review_round_id": "rnd1", "status": "fulfilled"}]),
    (_round(), [{"id": "r1", "review_round_id": "rnd1", "status": "cancelled"}]),
    (_round(decision="reject"), []),
    (_round(due_at=None, received_at="2026-05-01T00:00:00+08:00"), []),   # no deadline, old
])
def test_protection_2_a_closed_round_does_not_protect(round_: dict, requests: list) -> None:
    paper = _rejected_paper(review_rounds=[round_], revision_requests=requests)
    assert classify(paper, None, now=NOW)[0] == "not_ready"


def test_protection_2_round_without_deadline_is_open_for_a_while() -> None:
    paper = _rejected_paper(review_rounds=[_round(due_at=None,
                                                  received_at="2026-10-08T14:51:11+08:00")])
    assert classify(paper, None, now=NOW)[0] == "untouched"


def _transfer(due: str) -> dict:
    return {"event_type": "rejected", "attempt_id": "a1", "to_status": "rejected",
            "payload": {"decision": "reject_with_transfer_offer", "transfer_accepted": False,
                        "journal_name": "Journal of Physics and Chemistry of Solids",
                        "transfer_response_due_date": due}}


def test_protection_3_transfer_offer_in_force_keeps_the_submitter(repo: Path) -> None:
    # 20261027-materials-screening-ordering-reliability: "Please confirm by Mar 11, 2027".
    paper = _rejected_paper(submission_events=[_transfer("2027-03-11")])
    state, reasons = classify(paper, None, now=NOW)
    assert state == "untouched"
    assert reasons == ["transfer offer from Journal of Physics and Chemistry of Solids open "
                       "until 2027-03-11"]
    # The deadline day itself still counts; the day after it does not.
    assert classify(paper, None, now=datetime(2027, 3, 11, 23, 0, tzinfo=timezone.utc))[0] == "untouched"
    assert classify(paper, None, now=datetime(2027, 3, 12, 1, 0, tzinfo=timezone.utc))[0] == "not_ready"
    # An offer recorded without a deadline cannot be judged and does not protect.
    paper = _rejected_paper(submission_events=[{"event_type": "rejected", "payload": {
        "transfer_service_offered": True}}])
    assert classify(paper, None, now=NOW)[0] == "not_ready"


def test_protection_4_registry_ahead_of_the_site_keeps_the_submitter(repo: Path) -> None:
    path = repo / "registry" / "papers" / f"{PAPER}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["external_submission"] = {"status": "submitted", "journal": "Next Journal"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _plan(repo, _rejected_paper())
    assert result["papers"][0]["state"] == "untouched" and result["posts"] == []
    assert result["papers"][0]["reasons"] == ["registry external_submission is submitted (Next Journal)"]
    # An ended registry submission does not protect.
    data["external_submission"] = {"status": "rejected", "journal": "PRICAI 2026"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert _plan(repo, _rejected_paper())["papers"][0]["action"] == "park"


def _mail_state(root: Path, rows: list[tuple[str, str, int]]) -> Path:
    state = root / "journal-mail"
    state.mkdir(mode=0o700)
    with sqlite3.connect(state / "events.sqlite") as db:
        db.execute("CREATE TABLE events (message_key TEXT PRIMARY KEY, paper_id TEXT, payload TEXT)")
        db.execute("CREATE TABLE progress (message_key TEXT PRIMARY KEY, round_no INTEGER, "
                   "notified INTEGER DEFAULT 0, complete INTEGER DEFAULT 0)")
        for key, paper_id, complete in rows:
            db.execute("INSERT INTO events VALUES (?,?,?)", (key, paper_id, "{}"))
            db.execute("INSERT INTO progress(message_key, complete) VALUES (?,?)", (key, complete))
    return state


def test_protection_4_journal_mail_letter_not_on_the_site_keeps_the_submitter(
        repo: Path, tmp_path: Path) -> None:
    state = _mail_state(tmp_path, [("a" * 64, PAPER, 0), ("b" * 64, "other-paper", 0)])
    result = _plan(repo, _rejected_paper(), journal_mail_state=state)
    entry = result["papers"][0]
    assert entry["state"] == "untouched" and result["posts"] == []
    assert entry["reasons"] == ["1 journal_mail event(s) not yet on the site (aaaaaaaaaaaa)"]
    # Once the letter is carried to the site (complete), the rule applies again.
    with sqlite3.connect(state / "events.sqlite") as db:
        db.execute("UPDATE progress SET complete=1")
    assert _plan(repo, _rejected_paper(), journal_mail_state=state)["papers"][0]["action"] == "park"


def test_cli_passes_the_journal_mail_state() -> None:
    args = build_parser().parse_args(
        ["program", "sync-site-assignments", "--journal-mail-state", "/x/state/journal-mail"])
    assert str(args.journal_mail_state) == "/x/state/journal-mail"


@pytest.mark.parametrize("metadata", [
    {"legacy_metadata": {"submission_screening": {"disposition": "abandon",
                                                  "campaign_id": "target7_triage_20260724"},
                         "submission": {"status": "abandoned"}}},
    {"writing_metadata_extra": {"submission": {"status": "abandoned"}}},
])
def test_protection_5_site_abandoned_paper_is_left_for_a_person(repo: Path, metadata: dict) -> None:
    # 20260525mathgraph0004: abandoned on the site (07-24 triage), kept on in the registry.
    paper = _rejected_paper()
    paper["legacy_metadata"] = metadata.get("legacy_metadata", {})
    paper["writing_metadata"].update(metadata.get("writing_metadata_extra", {}))
    result = _plan(repo, paper)
    entry = result["papers"][0]
    assert entry["action"] == "manual_decision" and entry["proposed_action"] == "park"
    assert result["posts"] == [] and result["active"] == [SECOND]
    assert result["manual_decision"] == [{"paper_id": PAPER, "proposed_action": "park",
                                          "why": entry["why"], "active": ["詹静怡"]}]
    assert "abandon" in entry["why"]


def test_protection_5_writing_metadata_overrides_a_legacy_abandon(repo: Path) -> None:
    paper = _rejected_paper(legacy_metadata={"submission_screening": {"disposition": "abandon"}})
    paper["writing_metadata"]["submission_screening"] = {"disposition": "retain_candidate"}
    assert _plan(repo, paper)["papers"][0]["action"] == "park"


def test_protection_5_frozen_registry_paper_is_left_for_a_person(repo: Path) -> None:
    path = repo / "registry" / "papers" / f"{PAPER}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["freeze_decision"] = {"status": "frozen", "decided_at": "2026-11-26"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _plan(repo, _rejected_paper())
    assert result["papers"][0]["action"] == "manual_decision" and result["posts"] == []
    assert "is frozen" in result["papers"][0]["why"]
    # A ready frozen paper without a submitter is not given one either.
    site = FakeSite({PAPER: _paper(lifecycle="ready_to_submit", attempts=[REJECTED], assignments=[])})
    data["writing_release"] = {"status": "ready"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    entry = sync_site_assignments(site, root=repo, apply=True)["papers"][0]
    assert entry["action"] == "manual_decision" and entry["proposed_action"] == "assign"
    assert site.posts == []


def test_protection_5_already_parked_abandoned_paper_is_not_listed(repo: Path) -> None:
    parked = [{"id": "11111111-1111-4111-8111-111111111111", "submitter_id": ADMIN, "active": True,
               "notes": f"[openlabs-site-assignment] parked default_submitter_id={SECOND}",
               "assigned_at": "2026-11-24T01:00:00+08:00"}]
    paper = _rejected_paper(assignments=parked,
                            legacy_metadata={"submission_screening": {"disposition": "abandon"}})
    result = _plan(repo, paper)
    assert result["papers"][0]["action"] == "none" and result["manual_decision"] == []


def test_park_and_restore_returns_the_original_user_chosen_submitter(repo: Path) -> None:
    # 20260522mathgraph0002: the owner chose 詹静怡 (09-15), not the byline's second author.
    _registry(repo, status="draft", version="0.1.12",
              authors=[AUTHORS[0], {"name": "Zhidong Cheng", "name_zh": "成志东",
                                    "email": "other@example.test"}])
    site = FakeSite({PAPER: _paper(ready=False, attempts=[REJECTED])})
    parked = sync_site_assignments(site, root=repo, apply=True)
    assert parked["changed"][0]["default_submitter"]["submitter_id"] == SECOND
    assert parked["changed"][0]["second_author"]["submitter_id"] == OTHER
    assert _active(site) == [ADMIN]
    _registry(repo, status="ready", version="0.1.12",
              authors=[AUTHORS[0], {"name": "Zhidong Cheng", "name_zh": "成志东",
                                    "email": "other@example.test"}])
    paper = site.papers[PAPER]
    paper["lifecycle_status"] = "ready_to_submit"
    paper["writing_metadata"] = {"readiness": {"ready_for_submission": True},
                                 "llm_revision": {"status": "passed"}}
    restored = sync_site_assignments(site, root=repo, apply=True)
    assert restored["changed"][0]["target"] == {"submitter_id": SECOND, "name": "詹静怡",
                                                "source": "placeholder_notes"}
    assert _active(site) == [SECOND]
