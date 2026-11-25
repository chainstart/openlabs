"""Second-author rotation of new papers (UD-20261125-second-author-rotation)."""
from pathlib import Path

import yaml

from paper_writing import author_rotation
from paper_writing.deliverable import second_author
from paper_writing.operations import create_paper
from paper_writing.registry import load_paper_metadata, write_paper_metadata

ROSTER = [
    {"name": "Zhipeng Chen", "name_zh": "陈智鹏", "affiliation_ids": ["lab"], "corresponding": True,
     "email": "chen@example.org", "orcid": "https://orcid.org/0000-0001-8278-4096",
     "credit_roles": ["Conceptualization", "Supervision"]},
    {"name": "Qisheng Wang", "name_zh": "王琪盛", "affiliation_ids": ["lab"], "email": "wang@example.org",
     "orcid": "https://orcid.org/0009-0009-3923-1969", "credit_roles": ["Software"]},
    {"name": "Zhidong Cheng", "name_zh": "成志东", "affiliation_ids": ["lab"], "email": "cheng@example.org",
     "credit_roles": ["Formal analysis"]},
    {"name": "Jingyi Zhan", "name_zh": "詹静怡", "affiliation_ids": ["lab"], "email": "zhan@example.org",
     "credit_roles": ["Methodology"]},
    {"name": "Zhicheng Sui", "name_zh": "隋志成", "affiliation_ids": ["lab"], "corresponding": True,
     "email": "sui@example.org", "credit_roles": ["Supervision", "Writing – review & editing"]},
]
QUOTE = "未来的默认作者，加一条规则，在王琪盛，詹静怡和成志东之间依次轮转"


def _settings(root: Path, rotation: bool = True) -> None:
    defaults = {"authors": ROSTER, "affiliations": [{"id": "lab", "name": "AI Agent Lab"}]}
    if rotation:
        defaults["second_author_rotation"] = {
            "decision": "UD-20261125-second-author-rotation", "effective_from": "2026-11-25",
            "order": ["Qisheng Wang", "Jingyi Zhan", "Zhidong Cheng"],
            "first_author": "Zhipeng Chen", "last_author": "Zhicheng Sui", "quote": QUOTE}
    (root / "registry" / "papers").mkdir(parents=True, exist_ok=True)
    (root / "registry" / "settings.yaml").write_text(yaml.safe_dump({
        "schema_version": "ara.paper_writing.registry.v1",
        "support_publication": {"default_mode": "zenodo_only", "default_license": "cc-by-4.0",
                                "infer_github_mode_from_existing_url": False},
        "defaults": defaults,
    }, allow_unicode=True), encoding="utf-8")


def _create(root: Path, slug: str, created_at: str = "2026-11-26") -> dict:
    paper_id = f"{created_at.replace('-', '')}-ai-health-{slug}"
    create_paper(root=root, paper_id=paper_id, title=slug, created_at=created_at,
                 domain="ai", subdomain="health", venue_type="journal")
    return load_paper_metadata(paper_id, root)


def _names(record: dict) -> list[str]:
    return [p["name"] for p in record["authors"]]


def test_rotation_order_and_fixed_ends(tmp_path):
    _settings(tmp_path)
    records = [_create(tmp_path, f"paper-{n}") for n in range(4)]
    assert [_names(r) for r in records] == [
        ["Zhipeng Chen", "Qisheng Wang", "Zhidong Cheng", "Jingyi Zhan", "Zhicheng Sui"],
        ["Zhipeng Chen", "Jingyi Zhan", "Qisheng Wang", "Zhidong Cheng", "Zhicheng Sui"],
        ["Zhipeng Chen", "Zhidong Cheng", "Qisheng Wang", "Jingyi Zhan", "Zhicheng Sui"],
        ["Zhipeng Chen", "Qisheng Wang", "Zhidong Cheng", "Jingyi Zhan", "Zhicheng Sui"],
    ]
    assert [r["author_assignment"]["rotation_index"] for r in records] == [0, 1, 2, 3]
    first = records[0]["author_assignment"]
    assert first["source"] == "rotation" and first["quote"] == QUOTE
    assert first["decision"] == "UD-20261125-second-author-rotation"
    assert records[1]["affiliations"] == [{"id": "lab", "name": "AI Agent Lab"}]
    # The default submitter is the byline's second author.
    assert second_author(records[1], ROSTER)[0]["name"] == "Jingyi Zhan"


def test_person_details_follow_the_person(tmp_path):
    _settings(tmp_path)
    _create(tmp_path, "a")
    record = _create(tmp_path, "b")
    by_name = {p["name"]: p for p in ROSTER}
    for person in record["authors"]:
        assert person == by_name[person["name"]]
    wang = record["authors"][2]
    assert wang["orcid"] == "https://orcid.org/0009-0009-3923-1969" and wang["credit_roles"] == ["Software"]


def test_assign_is_idempotent(tmp_path):
    _settings(tmp_path)
    record = _create(tmp_path, "once")
    before = (tmp_path / "registry" / "papers" / f"{record['paper_id']}.yaml").read_bytes()
    for _ in range(3):
        result = author_rotation.assign(record["paper_id"], tmp_path)
        assert result["changed"] is False and result["second_author"] == "Qisheng Wang"
    assert (tmp_path / "registry" / "papers" / f"{record['paper_id']}.yaml").read_bytes() == before
    assert author_rotation.next_index(tmp_path) == 1


def test_existing_papers_untouched_and_not_counted(tmp_path):
    _settings(tmp_path)
    # A paper with its own byline and one without any, both from before the rule.
    own = {"paper_id": "20261113-ai-health-own", "workspace": "papers/20261113-ai-health-own",
           "created_at": "2026-11-13", "authors": [ROSTER[0], ROSTER[3], ROSTER[1]]}
    bare = {"paper_id": "20261120-ai-health-bare", "workspace": "papers/20261120-ai-health-bare",
            "created_at": "2026-11-20"}
    for record in (own, bare):
        (tmp_path / "registry" / "papers" / f"{record['paper_id']}.yaml").write_text(
            yaml.safe_dump(record, allow_unicode=True), encoding="utf-8")
    snapshot = {p.name: p.read_bytes() for p in (tmp_path / "registry" / "papers").glob("*.yaml")}
    assert author_rotation.assign(own["paper_id"], tmp_path)["status"] == "existing_byline"
    assert author_rotation.assign(bare["paper_id"], tmp_path)["status"] == "created_before_rule"
    assert {p.name: p.read_bytes() for p in (tmp_path / "registry" / "papers").glob("*.yaml")} == snapshot
    # The first rotated paper starts at Wang regardless of the existing bylines.
    assert _names(_create(tmp_path, "new"))[1] == "Qisheng Wang"


def test_counts_campaign_workspaces_under_the_data_root(tmp_path):
    _settings(tmp_path)
    (tmp_path / "workspaces").mkdir()
    first = tmp_path / "workspaces" / "ai" / "campaign-a"
    second = tmp_path / "workspaces" / "quant" / "campaign-b"
    # Campaign workspaces carry a stale settings copy without the rotation.
    _settings(first, rotation=False)
    _settings(second, rotation=False)
    a = _create(first, "a")
    b = _create(second, "b")
    c = _create(tmp_path, "c")
    assert [r["author_assignment"]["second_author"] for r in (a, b, c)] == [
        "Qisheng Wang", "Jingyi Zhan", "Zhidong Cheng"]


def test_no_policy_keeps_old_behaviour(tmp_path):
    _settings(tmp_path, rotation=False)
    record = _create(tmp_path, "plain")
    assert "authors" not in record and "author_assignment" not in record


def test_manual_byline_after_assignment_is_kept(tmp_path):
    _settings(tmp_path)
    record = _create(tmp_path, "manual")
    record["authors"] = [ROSTER[0], ROSTER[2], ROSTER[4]]
    write_paper_metadata(record["paper_id"], record, tmp_path)
    assert author_rotation.assign(record["paper_id"], tmp_path)["changed"] is False
    assert _names(load_paper_metadata(record["paper_id"], tmp_path)) == [
        "Zhipeng Chen", "Zhidong Cheng", "Zhicheng Sui"]
