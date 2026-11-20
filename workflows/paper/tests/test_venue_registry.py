"""Verified-venue registry: lookup first, pending instead of a human stop, alternatives."""

from __future__ import annotations

import json

import pytest
import yaml

from paper_writing import venue_registry as vr
from paper_writing.__main__ import main


def _charges(**mandatory):
    return {name: {"mandatory": mandatory.get(name, False), "note": None, "source": "https://x"}
            for name in vr.CHARGES}


def _entry(journal, zone, *, status="verified", fee_free=True, issn=None, aliases=(),
           category="Physics", **charges):
    return {"journal": journal, "aliases": list(aliases), "issn": issn, "eissn": None,
            "status": status, "indexes": {"list": ["SCIE"], "source": "https://idx"},
            "cas_2025": {"zone": zone, "major_category": category, "scope": "major_category",
                         "source": "https://cas"},
            "charges": _charges(**charges), "fee_free_route": fee_free,
            "evidence": [{"url": "https://x", "accessed_at": "2026-11-19"}],
            "verified_at": "2026-11-19", "verified_by": "test-model"}


@pytest.fixture
def root(tmp_path):
    venues = [
        _entry("Astrophysics and Space Science", 4, issn="0004-640X", aliases=["Ap&SS"]),
        _entry("Advances in Space Research", 3, status="pending_verification",
               submission_fee=None),
        _entry("Paid Zone One", 1, fee_free=False, apc=True),
        _entry("Paid Zone Three", 3, fee_free=False, page_charge=True),
        _entry("Medicine Four", 4, category="Medicine"),
    ]
    path = tmp_path / vr.REGISTRY_PATH
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"schema_version": vr.SCHEMA, "venues": venues}))
    return tmp_path


def test_lookup_by_name_alias_and_issn(root):
    for query in ({"journal": "Astrophysics and Space Science"}, {"journal": "ap&ss"},
                  {"issn": "0004640x"}):
        result = vr.lookup(root, **query)
        assert result["found"] and result["eligible"] and result["problems"] == []
        assert result["venue"]["journal"] == "Astrophysics and Space Science"


def test_owner_rule_paid_routes_only_in_zone_one(root):
    assert vr.lookup(root, journal="Paid Zone One")["eligible"] is True
    zone_three = vr.lookup(root, journal="Paid Zone Three")
    assert zone_three["eligible"] is False
    assert any("outside CAS zone 1" in p for p in zone_three["problems"])
    pending = vr.lookup(root, journal="Advances in Space Research")
    assert pending["eligible"] is False and pending["status"] == "pending_verification"
    assert "do not stop for a human" in pending["next"]
    unknown = vr.lookup(root, journal="Some Other Journal")
    assert unknown["found"] is False and "mark-pending" in unknown["next"]


def test_alternatives_lists_only_verified_eligible_journals(root):
    names = [v["journal"] for v in vr.alternatives(root)["venues"]]
    assert names == ["Paid Zone One", "Astrophysics and Space Science", "Medicine Four"]
    assert [v["journal"] for v in vr.alternatives(root, zones=[4], category="phys")["venues"]] == [
        "Astrophysics and Space Science"]
    assert "Astrophysics and Space Science" not in [
        v["journal"] for v in vr.alternatives(root, exclude="Ap&SS")["venues"]]


def test_mark_pending_records_the_refusal_and_never_downgrades(root):
    added = vr.mark_pending(root, journal="New Astronomy", by="gpt-6.1-sol",
                            reason="author guide refused", url="https://www.elsevier.com/x",
                            http_status=403)
    assert added["outcome"] == "added_pending" and added["status"] == "pending_verification"
    entry = vr.lookup(root, journal="New Astronomy")["venue"]
    assert entry["access_failures"][0]["http_status"] == 403
    assert entry["access_failures"][0]["url"] == "https://www.elsevier.com/x"
    assert "HTTP 403" in entry["open_items"][0]
    kept = vr.mark_pending(root, journal="Ap&SS", by="m", reason="guide 406", http_status=406)
    assert kept["outcome"] == "recorded_on_verified" and kept["status"] == "verified"
    assert vr.lookup(root, journal="Ap&SS")["eligible"] is True
    again = vr.mark_pending(root, journal="Advances in Space Research", by="m", reason="403")
    assert again["outcome"] == "pending"
    document = vr.load_venues(root)
    assert [v["journal"] for v in document["venues"]] == sorted(
        (v["journal"] for v in document["venues"]), key=vr._key)


def test_cli_exit_codes(root, capsys):
    assert main(["venue", "lookup", "--journal", "Ap&SS", "--root", str(root)]) == 0
    assert main(["venue", "lookup", "--journal", "Paid Zone Three", "--root", str(root)]) == 1
    assert main(["venue", "lookup", "--journal", "Nowhere", "--root", str(root)]) == 3
    capsys.readouterr()
    assert main(["venue", "alternatives", "--zone", "4", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 2
    assert main(["venue", "mark-pending", "--journal", "X", "--reason", "406", "--by", "m",
                 "--http-status", "406", "--root", str(root)]) == 0


def test_a_missing_registry_is_empty_and_a_malformed_one_is_refused(tmp_path):
    assert vr.lookup(tmp_path, journal="Any")["found"] is False
    (tmp_path / "registry").mkdir()
    (tmp_path / vr.REGISTRY_PATH).write_text("venues: {}\n")
    with pytest.raises(vr.VenueRegistryError):
        vr.load_venues(tmp_path)
