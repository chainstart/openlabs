"""Shared open-data client and the Gaia DR3 mirror fallback (no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "open-data"))
import open_data as od  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gaia_tap = _load(ROOT / "labs/physics/tools/gaia_tap.py", "gaia_tap")

EVENING = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)   # Beijing 20:00
MORNING = datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc)    # Beijing 09:00


class FakeBridge:
    """subprocess.run stand-in that records commands and answers with bridge-style JSON lines."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = list(answers or [])

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        answer = self.answers.pop(0) if self.answers else {"id": "job1", "state": "completed",
                                                           "route": "direct",
                                                           "routes_attempted": ["direct"]}
        lines = [json.dumps({"id": answer.get("id"), "state": "queued"}), json.dumps(answer)]
        return SimpleNamespace(stdout="\n".join(lines), stderr="", returncode=answer.pop("rc", 0))


# --------------------------------------------------------------------------- policy


def test_offpeak_window_is_beijing_02_to_14():
    assert not od.offpeak_open(EVENING) and od.offpeak_open(MORNING)
    assert od.next_offpeak_start(EVENING).isoformat() == "2026-11-26T02:00:00+08:00"
    assert od.is_large(file_bytes=200 * 2**20) and od.is_large(batch_bytes=2**30)
    assert not od.is_large(file_bytes=199 * 2**20, batch_bytes=2**30 - 1)


def test_large_proxy_downloads_wait_for_the_window_but_auto_does_not():
    with pytest.raises(od.OffPeakRequired):
        od.check_window(route="proxy", file_bytes=300 * 2**20, now=EVENING)
    with pytest.raises(od.OffPeakRequired):
        od.check_window(route="auto", direct_blocked=True, batch_bytes=2 * 2**30, now=EVENING)
    od.check_window(route="auto", batch_bytes=50 * 2**30, now=EVENING)       # direct first
    od.check_window(route="proxy", file_bytes=2**20, now=EVENING)            # small
    od.check_window(route="proxy", file_bytes=300 * 2**20, now=MORNING)      # in window


def test_credentials_and_non_http_urls_are_refused():
    for url in ("ftp://host/x", "https://user:pw@host/x", "https://host/x?api_key=1",
                "https://host/x?token=abc", "https://host/x?Subscription-Key=1"):
        with pytest.raises(od.OpenDataError):
            od.public_url(url)
    assert od.public_url("https://zenodo.org/api/records/1?format=json")
    assert od.s3_https("s3://stpubdata/tess/public/ffi/s0001/a b.fits") == (
        "https://stpubdata.s3.amazonaws.com/tess/public/ffi/s0001/a%20b.fits")


def test_submit_builds_the_bridge_command_and_reads_the_last_record():
    bridge = FakeBridge()
    record = od.submit("https://zenodo.org/f.csv", "/workspace/x/f.csv", sha256="AB" * 32,
                       expected_bytes=10, runner=bridge, now=EVENING)
    command = bridge.calls[0]
    assert command[0] == od.BRIDGE and command[command.index("--route") + 1] == "auto"
    assert command[command.index("--sha256") + 1] == "ab" * 32
    assert "--wait" in command and "--large" not in command
    assert record["state"] == "completed" and record["id"] == "job1"
    with pytest.raises(od.OpenDataError):
        od.submit("https://h/f", "/tmp/f", runner=bridge)
    with pytest.raises(od.OffPeakRequired):
        od.submit("https://h/f", "/workspace/x/big", route="proxy", expected_bytes=2**31,
                  runner=bridge, now=EVENING)
    od.submit("https://h/f", "/workspace/x/big", expected_bytes=2**31, runner=bridge, now=EVENING)
    assert "--large" in bridge.calls[-1]


def test_batch_resumes_skips_done_files_and_limits_new_submissions(tmp_path, monkeypatch):
    out = Path("/workspace/x")
    done = tmp_path / "done.bin"
    done.write_bytes(b"abc")
    batch = od.Batch(tmp_path / "batch.json")
    batch.add("https://h/a", str(done), sha256=od.sha256_file(done))
    batch.add("https://h/b", str(out / "b"))
    batch.add("https://h/c", str(out / "c"))
    bridge = FakeBridge([{"id": "jb", "state": "queued"}, {"id": "jc", "state": "completed"}])
    counts = batch.run(limit=1, runner=bridge, now=EVENING)
    assert counts["completed"] == 1 and counts["submitted_now"] == 1
    assert [c[c.index("--url") + 1] for c in bridge.calls] == ["https://h/b"]
    # second run: b is polled (still queued), c is submitted
    reloaded = od.Batch(tmp_path / "batch.json")
    assert [i.state for i in reloaded.items] == ["completed", "queued", "pending"]
    bridge2 = FakeBridge([{"id": "jb", "state": "queued"}, {"id": "jc", "state": "completed"}])
    reloaded.run(runner=bridge2, now=EVENING)
    assert bridge2.calls[0][1:3] == ["--status", "jb"]
    assert bridge2.calls[1][bridge2.calls[1].index("--url") + 1] == "https://h/c"


def test_query_refuses_oversized_answers(monkeypatch):
    class Response:
        headers = {"Content-Length": str(10 * 2**20)}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n):
            return b"x" * n

    monkeypatch.setattr(od.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(od.OpenDataError):
        od.query("https://h/q", {"a": 1}, max_bytes=2**20)
    Response.headers = {}
    with pytest.raises(od.OpenDataError):
        od.query("https://h/q", max_bytes=100)
    assert od.looks_like_html(b"\n <!DOCTYPE html><html>") and not od.looks_like_html(b"a,b\n1,2")


# --------------------------------------------------------------------------- Gaia fallback

MAINTENANCE = b"<!doctype html>\n<html lang=\"en\"><head><title>Gaia Archive maintenance</title>"
VIZIER_TSV = (
    "#\n#   VizieR Astronomical Server vizier.cfa.harvard.edu\n#\n"
    "Source\tRA_ICRS\tDE_ICRS\tGmag\tRUWE\tVarFlag\tNSS\tEpochPh\n"
    " \tdeg\tdeg\tmag\t \t \t \t \n"
    "-------------------\t---------------\t---------------\t---------\t-------\t----\t-\t-\n"
    "2028869231302243712\t298.00253626238\t+29.87146268202\t14.821778\t  1.039\tNOT_AVAILABLE\t0\t0\n"
    "2028869231302207104\t297.99685096002\t+29.86885916810\t13.965077\t  1.005\tVARIABLE\t1\t1\n"
).encode()
ESA_CSV = b"source_id,ra,dec,phot_g_mean_mag,ruwe\n4295806720,44.996155,0.005615,17.641426,1.1429516\n"


def _fetcher(answers):
    calls = []

    def fetch(url, params=None, timeout=None):
        calls.append((url, dict(params or {}), timeout))
        answer = answers[url] if url in answers else answers.get("*")
        if isinstance(answer, Exception):
            raise answer
        return answer

    return fetch, calls


def test_esa_maintenance_page_falls_back_to_a_mirror_with_esa_column_names():
    fetch, calls = _fetcher({gaia_tap.ESA_TAP: MAINTENANCE,
                             gaia_tap.VIZIER["vizier-chinavo"]: b"#\n#\n",
                             gaia_tap.VIZIER["vizier-cfa"]: VIZIER_TSV})
    rows, prov = gaia_tap.cone(298.0025, 29.87147, 20.0,
                               ["phot_g_mean_mag", "ruwe", "phot_variable_flag",
                                "non_single_star", "has_epoch_photometry"],
                               order_by_g=True, top=5, fetch=fetch)
    assert prov["backend"] == "vizier-cfa"
    assert [a["backend"] for a in prov["failed_before"]] == ["esa", "vizier-chinavo"]
    assert "HTML page" in prov["failed_before"][0]["error"]
    assert "empty cone" in prov["failed_before"][1]["error"]
    assert [r["source_id"] for r in rows] == [2028869231302207104, 2028869231302243712]
    bright = rows[0]
    assert bright["phot_variable_flag"] == "VARIABLE" and bright["non_single_star"] == 1
    assert bright["has_epoch_photometry"] is True and rows[1]["has_epoch_photometry"] is False
    assert rows[1]["sep_arcsec"] < 0.2 and 19 < bright["sep_arcsec"] < 20.1
    params = calls[-1][1]
    assert params["-source"] == "I/355/gaiadr3" and params["-c.rs"] == "20.0000"
    assert params["-out"].split(",")[:3] == ["Source", "RA_ICRS", "DE_ICRS"]
    assert calls[1][2] == 45.0                       # China-VO wait is capped


def test_esa_answers_first_when_it_is_up_and_id_lookups_accept_china_vo():
    fetch, calls = _fetcher({gaia_tap.ESA_TAP: ESA_CSV})
    rows, prov = gaia_tap.source_by_id(4295806720, ["phot_g_mean_mag", "ruwe"], fetch=fetch)
    assert prov["backend"] == "esa" and len(calls) == 1
    assert "FROM gaiadr3.gaia_source WHERE source_id=4295806720" in calls[0][1]["QUERY"]
    assert rows == [{"source_id": 4295806720, "ra": 44.996155, "dec": 0.005615,
                     "phot_g_mean_mag": 17.641426, "ruwe": 1.1429516}]
    fetch, _ = _fetcher({gaia_tap.ESA_TAP: OSError("down"),
                         gaia_tap.VIZIER["vizier-chinavo"]: VIZIER_TSV})
    rows, prov = gaia_tap.source_by_id(2028869231302243712, ["phot_g_mean_mag"], fetch=fetch)
    assert prov["backend"] == "vizier-chinavo" and rows[0]["phot_g_mean_mag"] == 14.821778


def test_gavo_is_used_only_when_it_has_every_column():
    fetch, calls = _fetcher({"*": OSError("down"), gaia_tap.GAVO_TAP: ESA_CSV})
    with pytest.raises(gaia_tap.GaiaUnavailable):
        gaia_tap.source_by_id(4295806720, ["teff_gspphot"], fetch=fetch)
    rows, prov = gaia_tap.source_by_id(4295806720, ["phot_g_mean_mag", "ruwe"], fetch=fetch)
    assert prov["backend"] == "gavo" and "gaia.dr3lite" in prov["request"]["query"]
    rows, prov = gaia_tap.source_by_id(4295806720, ["ruwe", "teff_gspphot"], fetch=fetch,
                                       allow_partial=True)
    assert prov["request"]["missing_columns"] == ["teff_gspphot"] and rows[0]["teff_gspphot"] is None


def test_every_mapped_column_round_trips_through_csv_output():
    rows = [{"source_id": 1, "ra": 1.5, "dec": -2.0, "ruwe": None}]
    text = gaia_tap.to_csv(rows, ["source_id", "ra", "dec", "ruwe"])
    assert text.splitlines() == ["source_id,ra,dec,ruwe", "1,1.5,-2.0,"]
    assert set(gaia_tap.GAVO_COLUMNS) - set(gaia_tap.VIZIER_COLUMNS) <= {
        "visibility_periods_used", "astrometric_excess_noise"}
