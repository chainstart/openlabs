"""Offline contract tests for labs/quant/tools/power_open_data.py (no network)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "labs" / "quant" / "tools" / "power_open_data.py"
spec = importlib.util.spec_from_file_location("power_open_data", TOOL)
pod = importlib.util.module_from_spec(spec)
sys.modules["power_open_data"] = pod
spec.loader.exec_module(pod)
od = pod.od


def test_settlement_periods_handle_clock_changes():
    assert pod.settlement_periods(date(2025, 11, 1)) == 48
    assert pod.settlement_periods(date(2025, 3, 30)) == 46
    assert pod.settlement_periods(date(2025, 10, 26)) == 50


def test_elexon_urls():
    assert pod.elexon_url("system-prices", date(2025, 11, 1)) == (
        "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/2025-11-01?format=json")
    assert pod.elexon_url("mid", date(2025, 12, 31)).endswith("from=2025-12-31&to=2026-01-01&format=json")
    with pytest.raises(od.OpenDataError):
        pod.elexon_url("boalf", date(2025, 11, 1))
    with pytest.raises(od.OpenDataError):
        pod.elexon_url("boalf", date(2025, 3, 30), 47)
    with pytest.raises(od.OpenDataError):
        pod.elexon_url("nope", date(2025, 11, 1))
    reqs = pod.elexon_requests("bod", date(2025, 10, 26))
    assert len(reqs) == 50 and reqs[-1][1] == "bod_2025-10-26_sp50.json"
    assert len(pod.elexon_requests("fuelhh", date(2025, 10, 26))) == 1


def test_oe_market_url_and_limits():
    url = pod.oe_market_url(date(2026, 11, 1), date(2026, 11, 2))
    q = parse_qs(urlparse(url).query)
    assert q["metrics"] == ["price", "demand"] and q["interval"] == ["5m"]
    assert q["primary_grouping"] == ["network_region"]
    with pytest.raises(od.OpenDataError):
        pod.oe_market_url(date(2026, 1, 1), date(2026, 1, 20))
    assert pod.oe_community_window_ok(date(2025, 6, 1), today=date(2026, 11, 25))
    assert not pod.oe_community_window_ok(date(2023, 1, 1), today=date(2026, 11, 25))


def test_nasa_and_ercot_urls():
    url = pod.nasa_power_url(-34.93, 138.6, date(2025, 1, 1), date(2025, 1, 31))
    q = parse_qs(urlparse(url).query)
    assert q["parameters"] == ["ALLSKY_SFC_SW_DWN,T2M,WS10M"] and q["start"] == ["20250101"]
    with pytest.raises(od.OpenDataError):
        pod.nasa_power_url(95, 0, date(2025, 1, 1), date(2025, 1, 2))
    assert pod.ercot_doclist_url("NP4-190-CD").endswith("reportTypeId=12331")
    assert pod.ercot_download_url("123").endswith("doclookupId=123")


def _sys_rows(day, n):
    return {"data": [{"settlementDate": day, "settlementPeriod": i, "systemSellPrice": 50.0 + i,
                      "systemBuyPrice": 50.0 + i, "netImbalanceVolume": -10.0} for i in range(1, n + 1)]}


def test_verify_system_prices():
    msg = pod.verify_system_prices(_sys_rows("2025-11-01", 48), date(2025, 11, 1))
    assert "48 settlement periods" in msg and "48/48" in msg
    with pytest.raises(od.OpenDataError):
        pod.verify_system_prices(_sys_rows("2025-11-01", 47), date(2025, 11, 1))
    assert "50 settlement" in pod.verify_system_prices(_sys_rows("2025-10-26", 50), date(2025, 10, 26))


def test_verify_fuelhh():
    rows = [{"dataset": "FUELHH", "settlementDate": "2025-11-01", "settlementPeriod": sp,
             "fuelType": f, "generation": 100} for sp in range(1, 49) for f in ("WIND", "CCGT")]
    assert "96 rows = 48 periods x 2 fuel types" in pod.verify_fuelhh({"data": rows}, date(2025, 11, 1))
    with pytest.raises(od.OpenDataError):
        pod.verify_fuelhh({"data": rows[:-1]}, date(2025, 11, 1))


def test_verify_boalf():
    row = {"settlementDate": "2025-11-01", "bmUnit": "T_X-1", "acceptanceNumber": 1,
           "acceptanceTime": "t", "levelFrom": 0, "levelTo": 5, "timeFrom": "a", "timeTo": "b",
           "soFlag": True}
    assert "1 acceptance rows" in pod.verify_boalf({"data": [row]}, date(2025, 11, 1), 20)
    bad = dict(row)
    bad.pop("bmUnit")
    with pytest.raises(od.OpenDataError):
        pod.verify_boalf({"data": [bad]}, date(2025, 11, 1), 20)


def test_verify_oe_market():
    def block(metric):
        return {"metric": metric, "results": [
            {"name": f"{metric}_{r}", "columns": {"region": r}, "data": [["t", 1.0]] * 3}
            for r in ("NSW1", "SA1")]}
    obj = {"success": True, "version": "4", "data": [block("price"), block("demand")]}
    assert "3 points" in pod.verify_oe_market(obj, ("price", "demand"), ("NSW1", "SA1"), 3)
    with pytest.raises(od.OpenDataError):
        pod.verify_oe_market(obj, ("price",), ("VIC1",), 3)
    with pytest.raises(od.OpenDataError):
        pod.verify_oe_market({"success": False}, ("price",), ("NSW1",), 3)


def test_verify_nasa_power_csv():
    head = "-BEGIN HEADER-\nx\n-END HEADER-\nYEAR,MO,DY,HR,ALLSKY_SFC_SW_DWN,T2M,WS10M\n"
    rows = "".join(f"2025,1,1,{h},{h * 10},20.0,3.0\n" for h in range(24))
    assert "24 hourly rows" in pod.verify_nasa_power_csv(head + rows, date(2025, 1, 1), date(2025, 1, 1))
    with pytest.raises(od.OpenDataError):
        pod.verify_nasa_power_csv(head + rows, date(2025, 1, 1), date(2025, 1, 2))
    with pytest.raises(od.OpenDataError):
        pod.verify_nasa_power_csv(rows, date(2025, 1, 1), date(2025, 1, 1))


def test_verify_ercot_doclist():
    obj = {"ListDocsByRptTypeRes": {"DocumentList": [
        {"Document": {"DocID": "1", "FriendlyName": "DAMSPNP4190_csv", "PublishDate": "x"}}]}}
    assert "1 documents" in pod.verify_ercot_doclist(obj)
    with pytest.raises(od.OpenDataError):
        pod.verify_ercot_doclist({"ListDocsByRptTypeRes": {"DocumentList": []}})


def test_html_denial_page_is_rejected(tmp_path):
    page = tmp_path / "x.json"
    page.write_text("<html><body>Request unsuccessful. Incapsula</body></html>")
    with pytest.raises(od.OpenDataError):
        pod._load_json_file(page)


class FakeRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, *args, **kwargs):
        self.commands.append(list(command))
        if "--status" in command:
            return SimpleNamespace(stdout="", stderr="", returncode=1)
        rec = {"id": f"job{len(self.commands)}", "state": "completed", "route": "proxy",
               "routes_attempted": ["direct", "proxy"], "fallback_reason": "HTTP=403"}
        return SimpleNamespace(stdout=json.dumps(rec) + "\n", stderr="", returncode=0)


def test_with_task_bytes_injects_estimate_into_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "BRIDGE", "/fake/download-submit")
    fake = FakeRunner()
    batch = od.Batch(tmp_path / "BATCH.json", route="auto", direct_blocked=True)
    for url, name in pod.elexon_requests("boalf", date(2025, 11, 1))[:3]:
        batch.add(url, f"/workspace/_pytest_fake_never_written/{name}")
    # od.submit creates the output's parent directory; the fake bridge writes nothing.
    monkeypatch.setattr(od.Path, "mkdir", lambda self, *a, **k: None)
    counts = batch.run(limit=2, runner=pod.with_task_bytes(400_000, fake),
                       now=datetime(2026, 11, 25, 12, tzinfo=timezone.utc))
    assert counts["submitted_now"] == 2
    submits = [c for c in fake.commands if "--url" in c]
    assert len(submits) == 2
    assert all(c[c.index("--task-bytes") + 1] == "400000" for c in submits)
    assert all(c.count("--task-bytes") == 1 for c in submits)


def test_large_elexon_batch_refused_outside_window():
    evening = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)   # 20:00 Beijing
    morning = datetime(2026, 11, 25, 2, tzinfo=timezone.utc)    # 10:00 Beijing
    year_bod = pod.ELEXON_DATASETS["bod"]["bytes"] * 48 * 365
    with pytest.raises(od.OffPeakRequired):
        od.check_window(route="auto", direct_blocked=True, batch_bytes=year_bod, now=evening)
    od.check_window(route="auto", direct_blocked=True, batch_bytes=year_bod, now=morning)
    od.check_window(route="auto", direct_blocked=True,
                    batch_bytes=pod.ELEXON_DATASETS["system-prices"]["bytes"] * 365, now=evening)


def test_elexon_fetch_dry_run_refuses_large_batch(capsys, tmp_path):
    rc = pod.main(["elexon", "fetch", "--dataset", "system-prices", "--start", "2025-01-01",
                   "--end", "2025-01-03", "--dry-run", "--out", str(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["requests"] == 3 and out["large"] is False
