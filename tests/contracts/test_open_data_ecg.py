"""Contract tests for labs/ai/tools/ecg_open_data.py (no network)."""

from __future__ import annotations

import array
import hashlib
import importlib.util
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "labs" / "ai" / "tools" / "ecg_open_data.py"


def _load():
    spec = importlib.util.spec_from_file_location("ecg_open_data", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ecg_open_data"] = module
    spec.loader.exec_module(module)
    return module


ecg = _load()
od = ecg.od

EVENING = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)   # 20:00 Beijing
MORNING = datetime(2026, 11, 25, 1, 0, tzinfo=timezone.utc)    # 09:00 Beijing


# --------------------------------------------------------------------------- URLs


def test_physionet_url_uses_pinned_versions():
    assert ecg.physionet_url("ptb-xl-plus", "features/x.csv") == \
        "https://physionet.org/files/ptb-xl-plus/1.0.1/features/x.csv"
    assert ecg.physionet_url("challenge-2021").endswith("/challenge-2021/1.0.3/")
    assert ecg.physionet_url("mimic-iv-ecg", "/RECORDS").endswith("/mimic-iv-ecg/1.0/RECORDS")
    with pytest.raises(od.OpenDataError):
        ecg.physionet_url("unknown-project", "a")
    with pytest.raises(od.OpenDataError):
        ecg.physionet_url("ptb-xl", "../secret")


def test_zenodo_url():
    assert ecg.zenodo_file_url(4916206, "exams.csv") == \
        "https://zenodo.org/api/records/4916206/files/exams.csv/content"


# --------------------------------------------------------------------------- listing


LISTING = """<html><body><pre><a href="../">../</a>
<a href="features/">features/</a>                                          23-May-2023 10:44                   -
<a href="LICENSE.txt">LICENSE.txt</a>                                        15-Jun-2023 17:20               14842
<a href="SHA256SUMS.txt">SHA256SUMS.txt</a>                                     27-Jun-2023 20:14            43228032
</pre></body></html>"""


def test_parse_listing():
    rows = ecg.parse_listing(LISTING)
    assert [r["name"] for r in rows] == ["features", "LICENSE.txt", "SHA256SUMS.txt"]
    assert rows[0]["is_dir"] and rows[0]["bytes"] is None
    assert rows[2]["bytes"] == 43228032


# --------------------------------------------------------------------------- sha256 bisection


def _sums_blob(n=3000):
    paths = sorted([f"files/p{i // 100:04d}/rec{i:05d}.hea" for i in range(n)]
                   + ["LICENSE.txt", "RECORDS", "files/p0000/RECORDS"])
    lines = [f"{hashlib.sha256(p.encode()).hexdigest()} {p}\n" for p in paths]
    return "".join(lines).encode(), paths


def _fetcher(blob, calls):
    def fetch(url, start, end):
        calls.append((start, end))
        return blob[start:end + 1]
    return fetch


@pytest.mark.parametrize("target", ["LICENSE.txt", "files/p0000/RECORDS",
                                    "files/p0012/rec01234.hea", "files/p0029/rec02999.hea"])
def test_sha256_lookup_finds_every_kind_of_line(target):
    blob, _ = _sums_blob()
    calls = []
    got = ecg.sha256_lookup("https://x/SHA256SUMS.txt", target, len(blob),
                            fetch=_fetcher(blob, calls), probe=256, scan=2048)
    assert got == hashlib.sha256(target.encode()).hexdigest()
    assert all(end - start < 2048 + 512 for start, end in calls)   # bounded reads only
    assert len(calls) < 20


def test_sha256_lookup_absent_and_load_sums():
    blob, paths = _sums_blob(200)
    assert ecg.sha256_lookup("u", "files/p0001/rec99999.hea", len(blob),
                             fetch=_fetcher(blob, []), probe=128, scan=1024) is None
    sums = ecg.load_sums(blob.decode())
    assert len(sums) == len(paths) and sums["RECORDS"] == hashlib.sha256(b"RECORDS").hexdigest()


def test_physionet_wants_uses_local_sums_and_rejects_unknown():
    sums = {"a/b.hea": "0" * 64}
    wants = ecg.physionet_wants("challenge-2021", ["a/b.hea"], sums=sums)
    assert wants[0].sha256 == "0" * 64 and wants[0].url.endswith("/1.0.3/a/b.hea")
    with pytest.raises(od.OpenDataError):
        ecg.physionet_wants("challenge-2021", ["missing.mat"], sums=sums)


# --------------------------------------------------------------------------- WFDB / MATLAB


HEA = """A0001 3 500 4 05-Feb-2020 11:39:16
A0001.mat 16+24 1000/mV 16 0 28 {c0} 0 I
A0001.mat 16+24 1000/mV 16 0 7 {c1} 0 II
A0001.mat 16+24 1000/mV 16 0 -21 {c2} 0 V1
#Age: 74
#Sex: Male
#Dx: 59118001,164889003
#Rx: Unknown
"""


def _record(tmp_path, ext=".mat"):
    samples = [28, 7, -21, 30, 9, -20, 40000 - 65536, 10, -19, 1, 2, 3]   # 4 frames x 3 leads
    sums = [((sum(samples[i::3]) + 32768) % 65536) - 32768 for i in range(3)]
    hea = tmp_path / f"A0001.hea"
    text = HEA.format(c0=sums[0], c1=sums[1], c2=sums[2])
    payload = array.array("h", samples).tobytes()
    if ext == ".mat":
        data = struct.pack("<5i", 30, 3, 4, 0, 4) + b"val\0" + payload
    else:
        text = text.replace("A0001.mat 16+24", "A0001.dat 16")
        data = payload
    hea.write_text(text)
    (tmp_path / f"A0001{ext}").write_bytes(data)
    return hea, tmp_path / f"A0001{ext}"


def test_parse_hea_fields():
    header = ecg.parse_hea(HEA.format(c0=1, c1=2, c2=3))
    assert header["fs"] == 500 and header["nsig"] == 3 and header["nsamples"] == 4
    assert header["leads"] == ["I", "II", "V1"]
    assert header["signals"][0]["byte_offset"] == 24 and header["signals"][0]["gain"] == 1000
    assert header["dx"] == ["59118001", "164889003"] and header["fields"]["Age"] == "74"


def test_parse_hea_gain_with_baseline():
    header = ecg.parse_hea("40689238 2 500 5000\n40689238.dat 16 200.0(0)/mV 16 0 -5 1 0 I\n"
                           "40689238.dat 16 200.0(0)/mV 16 0 -5 1 0 II\n")
    assert header["signals"][0]["gain"] == 200.0 and header["signals"][0]["units"] == "mV"
    with pytest.raises(ValueError):
        ecg.parse_hea("x 2 500 10\nx.dat 16 200 16 0 0 0 0 I\n")


@pytest.mark.parametrize("ext", [".mat", ".dat"])
def test_verify_record_checks_size_shape_and_checksums(tmp_path, ext):
    hea, data = _record(tmp_path, ext)
    result = ecg.verify_record(hea, data)
    assert result["checksums_match"] and result["nsig"] == 3 and result["dx"]
    if ext == ".mat":
        assert result["mat"]["rows"] == 3 and result["mat"]["name"] == "val"
    data.write_bytes(data.read_bytes()[:-2])
    with pytest.raises(ValueError):
        ecg.verify_record(hea, data)


def test_verify_record_detects_corruption(tmp_path):
    hea, data = _record(tmp_path, ".dat")
    raw = bytearray(data.read_bytes())
    raw[0] ^= 0x01
    data.write_bytes(bytes(raw))
    with pytest.raises(ValueError, match="checksums"):
        ecg.verify_record(hea, data)


def test_read_mat_v4_rejects_other_files():
    with pytest.raises(ValueError):
        ecg.read_mat_v4(b"MATLAB 5.0 MAT-file" + b"\0" * 40)
    info = ecg.read_mat_v4(struct.pack("<5i", 30, 12, 5000, 0, 4) + b"val\0")
    assert info["expected_bytes"] == 24 + 12 * 5000 * 2


# --------------------------------------------------------------------------- CSV checks


def test_columns():
    header = ",".join(ecg.CODE15_COLUMNS) + "\n1,2\n"
    assert ecg.check_columns(ecg.csv_columns(header), ecg.CODE15_COLUMNS) == []
    assert ecg.check_columns(["exam_id"], ["exam_id", "AF"]) == ["AF"]


# --------------------------------------------------------------------------- bridge logic


class FakeRunner:
    def __init__(self, tmp_path, content=b"a,b\n1,2\n", state="completed"):
        self.calls = []
        self.content = content
        self.state = state

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if "--status" in command:
            return SimpleNamespace(stdout=json.dumps({"id": command[-1], "state": self.state}),
                                   stderr="", returncode=0)
        out = Path(command[command.index("--output") + 1])
        if self.state == "completed":
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(self.content)
        record = {"id": "f" * 32, "state": self.state, "route": "direct",
                  "routes_attempted": ["direct"]}
        return SimpleNamespace(stdout=json.dumps(record) + "\n", stderr="", returncode=0)


def _fake_submit(calls, content, state="completed"):
    def submit(url, output, **kwargs):
        calls.append({"url": url, "output": output, **kwargs})
        if state == "completed":
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(content)
        return {"id": "f" * 32, "state": state, "route": "direct", "routes_attempted": ["direct"]}
    return submit


def test_fetch_one_passes_sha256_and_verifies(tmp_path, monkeypatch):
    content = b"a,b\n1,2\n"
    calls = []
    monkeypatch.setattr(od, "submit", _fake_submit(calls, content))
    want = ecg.Want("https://physionet.org/files/x/1/a.csv", "a.csv",
                    sha256=hashlib.sha256(content).hexdigest(), expected_bytes=len(content))
    info = ecg.fetch_one(want, tmp_path)
    assert info["ok"] and info["checksum"] == "sha256" and info["route"] == "direct"
    assert calls[0]["sha256"] == want.sha256 and calls[0]["expected_bytes"] == len(content)


def test_fetch_one_flags_html_and_md5(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "submit", _fake_submit([], b"<!DOCTYPE html><html>denied</html>"))
    want = ecg.Want("https://zenodo.org/api/records/1/files/e.csv/content", "e.csv", md5="0" * 32)
    info = ecg.fetch_one(want, tmp_path)
    assert not info["ok"] and "HTML" in info["problem"] and "md5" in info["problem"]


def test_fetch_one_reports_parked_job(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "submit", _fake_submit([], b"", state="waiting_window"))
    want = ecg.Want("https://ndownloader.figshare.com/files/1", "m.csv")
    info = ecg.fetch_one(want, tmp_path)
    assert not info["ok"] and "waiting_window" in info["problem"]


def test_submit_command_carries_sha256_and_auto_route():
    runner = FakeRunner(None, state="queued")
    od.submit("https://physionet.org/files/ptb-xl-plus/1.0.1/RECORDS",
              ecg.DOWNLOADS / "test-unused" / "RECORDS", sha256="A" * 64, wait=False,
              runner=runner)
    command = runner.calls[0]
    assert command[command.index("--sha256") + 1] == "a" * 64
    assert command[command.index("--route") + 1] == "auto"


def test_sph_records_refused_outside_window():
    runner = FakeRunner(None)
    with pytest.raises(od.OffPeakRequired):
        ecg.sph_fetch_records(runner=runner, now=EVENING)
    assert runner.calls == []


def test_sph_records_submitted_in_window_as_large():
    runner = FakeRunner(None, state="queued")
    result = ecg.sph_fetch_records(runner=runner, now=MORNING)
    command = runner.calls[0]
    assert "--large" in command and command[command.index("--route") + 1] == "auto"
    assert "--wait" not in command
    assert result["md5_to_check"] == ecg.SPH_FILES["records.tar.gz"]["md5"]


def test_cli_fetch_requires_explicit_paths(monkeypatch):
    with pytest.raises(SystemExit):
        ecg.main(["physionet", "fetch", "mimic-iv-ecg"])


def test_zenodo_fetch_large_needs_flag(monkeypatch):
    monkeypatch.setattr(ecg, "zenodo_files", lambda record: [
        {"key": "exams_part0.zip", "bytes": 2672786404, "md5": "a" * 32, "url": "https://z/x"}])
    with pytest.raises(SystemExit, match="allow-large"):
        ecg.main(["zenodo", "fetch", "code-15", "exams_part0.zip"])


def test_verify_record_format32_prefixed_name_and_unsigned_checksum(tmp_path):
    samples = [100000, -5, 70000, -40000, 3, 9]   # 3 frames x 2 leads, int32
    sums = [sum(samples[0::2]) % 65536, sum(samples[1::2]) % 65536]   # stored unsigned
    hea = tmp_path / "00001_medians.hea"
    hea.write_text("ge_median_beats_wfdb/00001_medians 2 500 3\n"
                   f"ge_median_beats_wfdb/00001_medians.dat 32 6344117.125(-1842966025)/mV 32 0 "
                   f"100000 {sums[0]} 0 I\n"
                   f"ge_median_beats_wfdb/00001_medians.dat 32 9481164.0(-2062153171)/mV 32 0 "
                   f"-5 {sums[1]} 0 II\n")
    dat = tmp_path / "00001_medians.dat"
    dat.write_bytes(array.array("i", samples).tobytes())
    result = ecg.verify_record(hea, dat)
    assert result["format"] == 32 and result["checksums_match"] and result["leads"] == ["I", "II"]
    with pytest.raises(ValueError):
        ecg.parse_hea("multi/3 2 500 10\n")


def test_reuse_skips_bridge_when_checksum_matches(tmp_path, monkeypatch):
    content = b"x,y\n"
    (tmp_path / "a.csv").write_bytes(content)
    monkeypatch.setattr(od, "submit", lambda *a, **k: pytest.fail("must not resubmit"))
    monkeypatch.setattr(ecg, "previous_job", lambda out: {"id": "1" * 32, "state": "completed",
                                                          "route": "direct"})
    want = ecg.Want("https://physionet.org/files/x/1/a.csv", "a.csv",
                    sha256=hashlib.sha256(content).hexdigest())
    info = ecg.fetch_one(want, tmp_path)
    assert info["ok"] and info["reused"] and info["id"] == "1" * 32


def test_previous_job_index(tmp_path):
    status = tmp_path / "status"
    status.mkdir()
    (status / "a.json").write_text(json.dumps({"id": "a", "state": "completed",
                                               "container_output": "/workspace/q/f.csv"}))
    (status / "b.json").write_text(json.dumps({"id": "b", "state": "failed",
                                               "container_output": "/workspace/q/g.csv"}))
    assert ecg.previous_job(Path("/workspace/q/f.csv"), status)["id"] == "a"
    assert ecg.previous_job(Path("/workspace/q/g.csv"), status) is None


def test_csv_header_remote_drops_partial_line(monkeypatch):
    monkeypatch.setattr(ecg, "range_fetch", lambda url, a, b: b"\xef\xbb\xbfid,x\n1,2\n3,")
    text = ecg.csv_header_remote("https://physionet.org/files/x/1/a.csv")
    assert text == "﻿id,x\n1,2\n" and ecg.csv_columns(text) == ["id", "x"]
    monkeypatch.setattr(ecg, "range_fetch", lambda url, a, b: b"id,x,y")
    with pytest.raises(od.OpenDataError):
        ecg.csv_header_remote("https://physionet.org/files/x/1/a.csv")


def test_physionet_sizes_one_listing_per_directory():
    calls = []

    def lister(project, parent):
        calls.append(parent)
        return [{"name": "a.hea", "is_dir": False, "bytes": 700},
                {"name": "a.mat", "is_dir": False, "bytes": 180024},
                {"name": "g2", "is_dir": True, "bytes": None}]
    sizes = ecg.physionet_sizes("challenge-2021", ["t/g1/a.hea", "t/g1/a.mat", "t/g1/zz.mat"],
                                lister=lister)
    assert sizes == {"t/g1/a.hea": 700, "t/g1/a.mat": 180024} and calls == ["t/g1"]


def test_large_proxy_bound_batch_refused_in_evening(tmp_path):
    batch = od.Batch(tmp_path / "m.json", route="auto", direct_blocked=True)
    batch.add("https://zenodo.org/api/records/4916206/files/exams_part0.zip/content",
              "/workspace/x/exams_part0.zip", expected_bytes=2672786404)
    runner = FakeRunner(None)
    with pytest.raises(od.OffPeakRequired):
        batch.run(runner=runner, now=EVENING)
    assert runner.calls == []
