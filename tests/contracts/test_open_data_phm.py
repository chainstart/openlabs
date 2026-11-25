"""Contract tests for labs/ai/tools/phm_open_data.py (no network)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "labs" / "ai" / "tools" / "phm_open_data.py"
spec = importlib.util.spec_from_file_location("phm_open_data", TOOL)
phm = importlib.util.module_from_spec(spec)
sys.modules["phm_open_data"] = phm
spec.loader.exec_module(phm)
od = phm.od



@pytest.fixture
def wdir(request):
    """A scratch dir under /workspace (bridge outputs must live there); reused and reset per test."""

    path = ROOT / ".pytest_cache" / "phm_open_data" / request.node.name
    path.mkdir(parents=True, exist_ok=True)
    for manifest in path.rglob("batch_manifest.json"):
        manifest.write_text('{"items": []}', encoding="utf-8")
    for report in path.rglob("sample_report.json"):
        report.write_text('{"files": []}', encoding="utf-8")
    return path


EVENING = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)  # 20:00 Beijing, outside window


def fake_runner(state="completed", writer=None):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--output" in command and writer:
            writer(Path(command[command.index("--output") + 1]))
        rec = {"id": f"job{len(calls)}", "state": state, "route": "direct",
               "routes_attempted": ["direct"]}
        return types.SimpleNamespace(stdout=json.dumps(rec) + "\n", stderr="", returncode=0)

    run.calls = calls
    return run


def test_zenodo_files_parses_md5_and_url():
    record = {"id": 5841834, "files": [
        {"key": "Kelmarsh_WT_static.csv", "size": 807, "checksum": "md5:af3a",
         "links": {"self": "https://zenodo.org/api/records/5841834/files/Kelmarsh_WT_static.csv/content"}},
        {"key": "a b.zip", "size": 10, "checksum": "sha1:zz", "links": {}}]}
    files = phm.zenodo_files(record)
    assert files[0] == {"name": "Kelmarsh_WT_static.csv", "bytes": 807, "md5": "af3a", "sha256": None,
                        "url": "https://zenodo.org/api/records/5841834/files/Kelmarsh_WT_static.csv/content"}
    assert files[1]["md5"] is None
    assert files[1]["url"] == "https://zenodo.org/records/5841834/files/a%20b.zip?download=1"


def test_mendeley_files_keeps_sha256():
    answer = [{"filename": "acoustic.zip", "content_details": {
        "size": 47205730, "sha256_hash": "5dd1", "download_url": "https://data.mendeley.com/x"}}]
    assert phm.mendeley_files(answer) == [{"name": "acoustic.zip", "bytes": 47205730, "md5": None,
                                           "sha256": "5dd1", "url": "https://data.mendeley.com/x"}]


def test_s3_md5_only_for_single_part_etags():
    assert phm.s3_md5('"4da3afb0aa50cb3dcdd8e20ed1ed1c7c"') == "4da3afb0aa50cb3dcdd8e20ed1ed1c7c"
    assert phm.s3_md5('"d97c40652800c2cce87ad16b0ff15dff-13"') is None
    assert phm.s3_md5(None) is None


def test_nasa_urls_are_s3_https():
    names = dict(phm.SOURCES["nasa-pcoe"]["files"])
    assert names["3. Milling.zip"] == "https://phm-datasets.s3.amazonaws.com/NASA/3.+Milling.zip"
    for _, url in phm.SOURCES["nasa-pcoe"]["files"]:
        od.public_url(url)


def test_list_static_uses_head(monkeypatch):
    heads = {"https://www02.smt.ufrj.br/~offshore/mfs/database/mafaulda/normal.zip":
             {"bytes": 325307137, "etag": '"x"'}}
    files, meta = phm.list_files("mafaulda", head_fn=lambda url: heads.get(url, {"bytes": 1, "etag": None}))
    assert files[0]["name"] == "normal.zip" and files[0]["bytes"] == 325307137
    assert files[0]["md5"] is None  # not an S3 host
    assert meta["landing"].startswith("https://www02.smt.ufrj.br/")


def test_check_csv_and_html_refusal():
    assert "2 data rows x 3 columns" in phm.check_csv(b"a,b,c\n1,2,3\n4,5,6\n")
    with pytest.raises(od.OpenDataError):
        phm.check_csv(b"<!DOCTYPE html><html>denied</html>")
    with pytest.raises(od.OpenDataError):
        phm.check_csv(b"justone\n1\n")


def test_verify_zip_md5_and_size(tmp_path):
    target = tmp_path / "s.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("d/x.csv", "t,v\n0,1\n1,2\n")
    md5 = hashlib.md5(target.read_bytes()).hexdigest()
    result = phm.verify(target, md5=md5, size=target.stat().st_size)
    assert "zip CRC ok, 1 members" in result["check"] and "t,v" in result["check"]
    with pytest.raises(od.OpenDataError):
        phm.verify(target, md5="0" * 32)
    with pytest.raises(od.OpenDataError):
        phm.verify(target, size=1)


def test_sample_submits_only_listed_small_files(wdir):
    payload = b"Turbine,Lat,Lon\nT1,1,2\n"

    def lister(source_id):
        return ([{"name": "Kelmarsh_WT_static.csv", "bytes": len(payload),
                  "md5": hashlib.md5(payload).hexdigest(), "sha256": None, "url": "https://zenodo.org/a"},
                 {"name": "Kelmarsh_WT_dataSignalMapping.csv", "bytes": len(payload),
                  "md5": None, "sha256": None, "url": "https://zenodo.org/b"},
                 {"name": "Kelmarsh_SCADA_2020_3086.zip", "bytes": 473677799, "md5": None,
                  "sha256": None, "url": "https://zenodo.org/c"}], {"id": 1})

    runner = fake_runner(writer=lambda p: p.write_bytes(payload))

    def submit(url, output, **kw):
        return od.submit(url, output, runner=runner, **kw)

    report = phm.cmd_sample("kelmarsh", out_root=wdir, submit=submit, lister=lister)
    assert len(runner.calls) == 2
    assert all("SCADA" not in " ".join(c) for c in runner.calls)
    assert all(c[c.index("--route") + 1] == "auto" for c in runner.calls)
    assert report["files"][0]["check"].startswith("CSV 1 data rows x 3 columns")
    assert (wdir / "kelmarsh" / "metadata.json").is_file()
    assert report["total_bytes"] == 473677799 + 2 * len(payload)


def test_sample_refuses_big_file(tmp_path):
    def lister(source_id):
        return ([{"name": "acoustic.zip", "bytes": 300 * 1024 * 1024, "md5": None, "sha256": "ab",
                  "url": "https://data.mendeley.com/a"}], {})

    with pytest.raises(od.OpenDataError):
        phm.cmd_sample("kaist-varying-load", out_root=tmp_path, submit=None, lister=lister)


def test_fetch_batch_limit_and_sha(wdir):
    def lister(source_id):
        return ([{"name": n, "bytes": 1000, "md5": None, "sha256": "ab" * 32,
                  "url": f"https://data.mendeley.com/{n}"} for n in ("a.zip", "b.zip", "c.zip")], {})

    runner = fake_runner(state="queued")
    counts = phm.cmd_fetch("kaist-varying-load", wdir / "dest", names=None, limit=2, wait=False,
                           lister=lister, runner=runner, now=EVENING)
    assert counts["submitted_now"] == 2 and len(runner.calls) == 2
    assert "--sha256" in runner.calls[0]
    manifest = json.loads((wdir / "dest" / "batch_manifest.json").read_text())
    assert [i["state"] for i in manifest["items"]] == ["queued", "queued", "pending"]


def test_fetch_large_proxy_bound_batch_refused_in_evening(wdir):
    def lister(source_id):
        return ([{"name": "part1.zip", "bytes": 10350759860, "md5": None, "sha256": "ab" * 32,
                  "url": "https://data.mendeley.com/p"}], {})

    runner = fake_runner()
    with pytest.raises(od.OffPeakRequired):
        phm.cmd_fetch("kaist-varying-speed", wdir, names=None, limit=None, wait=False,
                      direct_blocked=True, lister=lister, runner=runner, now=EVENING)
    assert runner.calls == []
    # auto route with direct not proven blocked is not time-limited
    phm.cmd_fetch("kaist-varying-speed", wdir, names=None, limit=None, wait=False,
                  lister=lister, runner=runner, now=EVENING)
    assert "--large" in runner.calls[0]


def test_select_rejects_unknown_names():
    with pytest.raises(od.OpenDataError):
        phm.select([{"name": "a"}], ["b"])
    assert phm.select([{"name": "a"}], []) == []
    assert phm.select([{"name": "a"}], None) == [{"name": "a"}]
    assert phm.safe_name("3. Milling.zip") == "3._Milling.zip"


def test_sample_rerun_polls_running_job_instead_of_resubmitting(wdir):
    payload = b"a,b\n1,2\n"
    out = wdir / "nasa-pcoe"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample_report.json").write_text(json.dumps({"files": [
        {"name": "3. Milling.zip", "bridge": {"id": "job-old", "state": "running"}}]}))

    def lister(source_id):
        return ([{"name": "3. Milling.zip", "bytes": len(payload), "md5": None, "sha256": None,
                  "url": "https://phm-datasets.s3.amazonaws.com/NASA/3.+Milling.zip"}], {})

    def no_submit(*a, **k):
        raise AssertionError("must not resubmit")

    report = phm.cmd_sample("nasa-pcoe", out_root=wdir, submit=no_submit, lister=lister,
                            status=lambda job: {"state": "running"})
    assert report["files"][0]["bridge"]["id"] == "job-old"
    assert "re-run later" in report["files"][0]["error"]


def test_check_zip_reads_one_nested_zip(tmp_path):
    import io as _io
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as inner:
        inner.writestr("mill.mat", b"MATLAB 5.0")
    outer = tmp_path / "o.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("3. Milling/mill.zip", buf.getvalue())
    assert "nested 3. Milling/mill.zip CRC ok, 1 members ['mill.mat']" in phm.check_zip(outer)


def test_sample_rerun_reverifies_completed_file_without_download(wdir):
    payload = b"Name,Description\nA,B\n"
    out = wdir / "hill-of-towie"
    out.mkdir(parents=True, exist_ok=True)
    (out / "Hill_of_Towie_tables_description.csv").write_bytes(payload)
    (out / "sample_report.json").write_text(json.dumps({"files": [
        {"name": "Hill_of_Towie_tables_description.csv", "bridge": {"id": "j1", "state": "completed"}}]}))

    def lister(source_id):
        return ([{"name": "Hill_of_Towie_tables_description.csv", "bytes": len(payload),
                  "md5": hashlib.md5(payload).hexdigest(), "sha256": None, "url": "https://zenodo.org/x"}], {})

    def no_submit(*a, **k):
        raise AssertionError("must not resubmit")

    spec = dict(phm.SOURCES["hill-of-towie"])
    phm.SOURCES["hill-of-towie"]["sample"] = ["Hill_of_Towie_tables_description.csv"]
    try:
        report = phm.cmd_sample("hill-of-towie", out_root=wdir, submit=no_submit, lister=lister)
    finally:
        phm.SOURCES["hill-of-towie"] = spec
    assert report["files"][0]["check"].startswith("CSV 1 data rows x 2 columns")
