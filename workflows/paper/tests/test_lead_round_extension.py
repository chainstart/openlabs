"""A lead-authorized extra round on top of an owner round-limit grant."""
import json

import pytest

from paper_writing import review_flow as flow

from tests.test_review_round_limits import BIO, TARGET, authorized_metadata


def extension(root, meta, **overrides):
    auth = meta["review_round_limit_override"]["authorization"]
    record = {"schema": flow.LEAD_EXTENSION_SCHEMA, "authorized_by": "lead (main session)",
              "paper_id": BIO, "target_journal": TARGET, "extra_rounds": 1,
              "reason": "Only a bibliographic correction remains to be checked.",
              "owner_receipt": {"path": auth["path"], "sha256": auth["sha256"]}}
    record.update(overrides)
    path = root / "lead-extension.json"
    path.write_text(json.dumps(record))
    return {"path": path.name, "sha256": flow._sha256(path.read_bytes()), "extra_rounds": record["extra_rounds"]}


def test_lead_extension_adds_one_round(tmp_path):
    meta = authorized_metadata(tmp_path)
    assert flow.review_round_limit_override(meta, tmp_path, BIO)["max_rounds_per_target"] == 20
    meta["review_round_limit_override"]["lead_extension"] = extension(tmp_path, meta)
    result = flow.review_round_limit_override(meta, tmp_path, BIO)
    assert result["max_rounds_per_target"] == 21 and result["owner_max_rounds_per_target"] == 20


@pytest.mark.parametrize("override", [{"authorized_by": "owner"}, {"paper_id": "other"},
    {"target_journal": "Other"}, {"extra_rounds": 2}, {"extra_rounds": 0}, {"reason": " "},
    {"owner_receipt": {"path": "x.json", "sha256": "0" * 64}}, {"schema": "other"}])
def test_invalid_lead_extension_refuses(tmp_path, override):
    meta = authorized_metadata(tmp_path)
    meta["review_round_limit_override"]["lead_extension"] = extension(tmp_path, meta, **override)
    with pytest.raises(ValueError):
        flow.review_round_limit_override(meta, tmp_path, BIO)


def test_changed_lead_extension_refuses(tmp_path):
    meta = authorized_metadata(tmp_path)
    meta["review_round_limit_override"]["lead_extension"] = extension(tmp_path, meta)
    (tmp_path / "lead-extension.json").write_text("{}")
    with pytest.raises(ValueError, match="missing or changed"):
        flow.review_round_limit_override(meta, tmp_path, BIO)
