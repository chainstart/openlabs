"""Submitter assignments on the site follow readiness (user rule 2026-11-23)."""

from __future__ import annotations

import copy
import json
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


def test_classify_requires_a_ready_current_package() -> None:
    paper = _paper()
    paper["packages"][0]["status"] = "uploading"
    state, reasons = classify(paper, None)
    assert state == "not_ready" and "current package status uploading" in reasons


def test_cli_command_parses() -> None:
    args = build_parser().parse_args(
        ["program", "sync-site-assignments", "--paper-id", PAPER, "--apply", "--json"])
    assert args.paper_id == [PAPER] and args.apply
