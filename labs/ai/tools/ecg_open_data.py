#!/usr/bin/env python3
"""Free public ECG data for the ``ml-evaluation-protocols`` line (2026-11-25 data onboarding).

Sources (all registration-free; licences checked first-hand, see the line catalogue
``registry/data-catalog/ml-evaluation-protocols.yaml``):

* PhysioNet open projects - PTB-XL 1.0.3 (ingested), PTB-XL+ 1.0.1, PhysioNet/CinC Challenge
  2021 1.0.3, MIMIC-IV-ECG 1.0 (ODbL, open), Chapman-Shaoxing-Ningbo (ecg-arrhythmia 1.0.0),
  CPSC2021 1.0.0, LUDB 1.0.1. PhysioNet serves every file individually at
  ``https://physionet.org/files/<project>/<version>/<path>`` and publishes ``SHA256SUMS.txt``
  per project version. Those sums files are big (MIMIC-IV-ECG: 176 MB), so
  :func:`sha256_lookup` finds one file's line by HTTP Range bisection over the sorted sums
  file (a few 4-64 KB query reads) instead of downloading it. The ``physionet fetch`` command is
  the reusable pattern for any PhysioNet open project: per-file bridge jobs with ``--sha256``.
* Zenodo - CODE-15% (record 4916206) and SaMi-Trop (record 4905618), CC BY 4.0; md5 published.
* figshare - SPH (Shandong Provincial Hospital, collection 5779802), CC0. figshare refuses the
  container's direct route (HTTP 403), so files fall back to the proxy; ``records.tar.gz``
  (2.28 GB) is a large proxy download and is refused outside Beijing 02:00-14:00.

Large batches (a file >= 200 MB or >= 1 GB in all) from PhysioNet and Zenodo are treated as
proxy-bound too: the PTB-XL zip (2026-11-13) and CODE-15% exams.csv (2026-11-25) both fell back
from a failing direct transfer to the proxy, so ``physionet fetch`` / ``zenodo fetch`` refuse such
batches outside the window. Small per-file jobs are not time-limited.

Every network call is explicit: ``list``/``sha256`` read small query answers (directory listings,
Range slices, JSON metadata) through the environment proxy with a byte cap; files only ever go
through the WSL download bridge (``open_data.submit`` / ``open_data.Batch``).

Usage::

    ecg_open_data.py sources
    ecg_open_data.py physionet list ptb-xl-plus [SUBDIR]
    ecg_open_data.py physionet sha256 mimic-iv-ecg files/p1000/p10000032/s40689238/40689238.hea
    ecg_open_data.py physionet fetch challenge-2021 training/cpsc_2018/g1/A0001.hea ... \
        [--paths-file F] [--out DIR] [--limit N] [--sums LOCAL_SHA256SUMS] [--wait]
    ecg_open_data.py physionet sums ptb-xl-plus           # whole SHA256SUMS.txt via the bridge
    ecg_open_data.py zenodo list code-15
    ecg_open_data.py zenodo fetch code-15 exams_part0.hdf5... --allow-large [--limit N]
    ecg_open_data.py sph fetch-records                    # off-peak only (proxy-bound, 2.28 GB)
    ecg_open_data.py sample {ptb-xl-plus,challenge-2021,mimic-iv-ecg,code-15,sami-trop,sph,all}
"""

from __future__ import annotations

import argparse
import array
import csv
import hashlib
import html
import io
import json
import re
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "open-data"))
import open_data as od  # noqa: E402

LINE = "ml-evaluation-protocols"
LINE_DIR = Path("/workspace/openlabs/build/lines") / LINE
SAMPLES = LINE_DIR / "data" / "open-samples"
DOWNLOADS = LINE_DIR / "downloads" / "open-data"
PHYSIONET = "https://physionet.org/files"
ZENODO_API = "https://zenodo.org/api/records"
FIGSHARE_API = "https://api.figshare.com/v2/articles"

PHYSIONET_PROJECTS = {
    # project id -> (version, licence)
    "ptb-xl": ("1.0.3", "CC BY 4.0"),
    "ptb-xl-plus": ("1.0.1", "CC BY 4.0"),
    "challenge-2021": ("1.0.3", "CC BY 4.0"),
    "mimic-iv-ecg": ("1.0", "ODbL 1.0"),
    "ecg-arrhythmia": ("1.0.0", "CC BY 4.0"),
    "cpsc2021": ("1.0.0", "CC BY 4.0"),
    "ludb": ("1.0.1", "ODC-By 1.0"),
    "icentia11k-continuous-ecg": ("1.0", "CC BY-NC-SA 4.0"),
}

ZENODO_RECORDS = {"code-15": 4916206, "sami-trop": 4905618}

# figshare SPH collection 5779802: article id -> file (verified via api.figshare.com 2026-11-25)
SPH_FILES = {
    "metadata.csv": {"article": 17912441, "url": "https://ndownloader.figshare.com/files/34793152",
                     "bytes": 999219, "md5": "8ef8e8789059a585c89c5302c7891909"},
    "code.csv": {"article": 17912507, "url": "https://ndownloader.figshare.com/files/32630954",
                 "bytes": 1839, "md5": "9fafec6cc6e1ef8117e2964116654d05"},
    "rule.pdf": {"article": 19738468, "url": "https://ndownloader.figshare.com/files/35284594",
                 "bytes": 47063, "md5": "8e84772f206d50f0e661c787cd4c905a"},
    "records.tar.gz": {"article": 17912444, "url": "https://ndownloader.figshare.com/files/32630684",
                       "bytes": 2281799680, "md5": "0beef976f54cf0a95fac9f45bb157950"},
}

CODE15_COLUMNS = ["exam_id", "age", "is_male", "nn_predicted_age", "1dAVb", "RBBB", "LBBB", "SB",
                  "ST", "AF", "patient_id", "death", "timey", "normal_ecg", "trace_file"]
MIMIC_MEASUREMENT_COLUMNS = ["subject_id", "study_id", "cart_id", "ecg_time", "report_0",
                             "bandwidth", "filtering", "rr_interval", "p_onset", "p_end",
                             "qrs_onset", "qrs_end", "t_end", "p_axis", "qrs_axis", "t_axis"]
MIMIC_RECORD_LIST_COLUMNS = ["subject_id", "study_id", "file_name", "ecg_time", "path"]

Fetcher = Callable[[str, int, int], bytes]


# --------------------------------------------------------------------------- URL builders


def physionet_url(project: str, path: str = "", version: str | None = None) -> str:
    if project not in PHYSIONET_PROJECTS and version is None:
        raise od.OpenDataError(f"unknown PhysioNet project {project}; pass a version")
    version = version or PHYSIONET_PROJECTS[project][0]
    path = path.lstrip("/")
    if ".." in path.split("/"):
        raise od.OpenDataError("relative path components are refused")
    return f"{PHYSIONET}/{project}/{version}/{path}"


def zenodo_file_url(record: int, key: str) -> str:
    return f"{ZENODO_API}/{record}/files/{key}/content"


# --------------------------------------------------------------------------- small queries


def _retry(call: Callable[[], Any], attempts: int = 3, pause: float = 3.0) -> Any:
    """Small queries through the proxy sometimes hit a TLS EOF; retry a bounded number of times."""

    for attempt in range(attempts):
        try:
            return call()
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause * (attempt + 1))
    return None


def range_fetch(url: str, start: int, end: int) -> bytes:
    """Bytes ``start..end`` (inclusive) of a remote file: a capped Range query, not a download."""

    want = end - start + 1
    return _retry(lambda: od.query(url, headers={"Range": f"bytes={start}-{end}"},
                                   max_bytes=want + 1024))


_ROW = re.compile(r'<a href="([^"?]+)">[^<]*</a>[ \t]+(\S+ \S+)[ \t]+(-|\d+)[ \t]*$')


def parse_listing(text: str) -> list[dict[str, Any]]:
    """Rows of a PhysioNet/nginx autoindex page: name, is_dir, date, bytes."""

    rows = []
    for href, date, size in (m.groups() for m in map(_ROW.search, text.splitlines()) if m):
        name = html.unescape(href)
        if name in {"../", "./"}:
            continue
        rows.append({"name": name.rstrip("/"), "is_dir": name.endswith("/"), "date": date,
                     "bytes": None if size == "-" else int(size)})
    return rows


def listing(project: str, subdir: str = "") -> list[dict[str, Any]]:
    url = physionet_url(project, subdir.rstrip("/") + "/" if subdir else "")
    body = _retry(lambda: od.query(url, max_bytes=8 * 1024 * 1024))
    return parse_listing(body.decode("utf-8", "replace"))


def remote_size(project: str, path: str) -> int | None:
    parent, _, name = path.rpartition("/")
    for row in listing(project, parent):
        if row["name"] == name and not row["is_dir"]:
            return row["bytes"]
    return None


def _first_line_after(block: bytes, offset: int, skip_partial: bool) -> tuple[int, str] | None:
    """Offset (absolute) and text of the first full line in ``block`` (read at ``offset``)."""

    pos = 0
    if skip_partial:
        nl = block.find(b"\n")
        if nl < 0:
            return None
        pos = nl + 1
    end = block.find(b"\n", pos)
    if end < 0:
        return None
    return offset + pos, block[pos:end].decode("utf-8", "replace")


def _sums_path(line: str) -> str:
    parts = line.split(None, 1)
    return parts[1].lstrip("*").strip() if len(parts) == 2 else ""


def sha256_lookup(url: str, path: str, size: int, *, fetch: Fetcher = range_fetch,
                  probe: int = 4096, scan: int = 65536) -> str | None:
    """sha256 of ``path`` from a remote, byte-order-sorted ``SHA256SUMS.txt`` by Range bisection.

    PhysioNet sums files are sorted by path (byte order), so about log2(size/scan) probe reads of
    ``probe`` bytes plus one ``scan`` read find a line; returns ``None`` when the path is absent.
    """

    lo, hi = 0, size
    while hi - lo > scan:
        mid = (lo + hi) // 2
        found = _first_line_after(fetch(url, mid, min(size - 1, mid + probe - 1)), mid, True)
        if found is None:
            hi = mid
            continue
        start, line = found
        name = _sums_path(line)
        if name == path:
            return line.split()[0].lower()
        if name < path:
            lo = start
        else:
            hi = start
    block = fetch(url, lo, min(size - 1, hi + probe))
    for raw in block.split(b"\n"):
        line = raw.decode("utf-8", "replace")
        if _sums_path(line) == path:
            digest = line.split()[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return None


def physionet_sha256(project: str, path: str, *, fetch: Fetcher = range_fetch,
                     sums_size: int | None = None) -> str | None:
    size = sums_size if sums_size is not None else remote_size(project, "SHA256SUMS.txt")
    if not size:
        raise od.OpenDataError(f"{project}: SHA256SUMS.txt size unknown")
    return sha256_lookup(physionet_url(project, "SHA256SUMS.txt"), path, size, fetch=fetch)


def load_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        name = _sums_path(line)
        if name:
            sums[name] = line.split()[0].lower()
    return sums


def csv_header_remote(url: str, nbytes: int = 65536, lines: int = 3) -> str:
    """First ``lines`` complete lines of a remote CSV via one small Range query.

    A trailing partial line is dropped; at least the header line must fit in ``nbytes``.
    """

    block = range_fetch(url, 0, nbytes - 1).decode("utf-8", "replace")
    complete = block.split("\n")[:-1]
    if not complete:
        raise od.OpenDataError(f"header line of {url} is longer than {nbytes} bytes")
    return "\n".join(complete[:lines]) + "\n"


# --------------------------------------------------------------------------- verifiers


def parse_hea(text: str) -> dict[str, Any]:
    """A WFDB single-segment header: record line, signal lines, ``#`` comments (Dx/Age/Sex)."""

    lines = [line.strip() for line in text.splitlines()]
    body = [line for line in lines if line and not line.startswith("#")]
    comments = [line.lstrip("#").strip() for line in lines if line.startswith("#")]
    if not body:
        raise ValueError("empty header")
    head = body[0].split()
    if len(head) < 2:
        raise ValueError(f"bad record line: {body[0]}")
    record = {"record": head[0], "nsig": int(head[1]),
              "fs": float(head[2].split("/")[0]) if len(head) > 2 else 250.0,
              "nsamples": int(head[3]) if len(head) > 3 else None,
              "base_date": head[4] if len(head) > 4 else None,
              "base_time": head[5] if len(head) > 5 else None}
    if re.fullmatch(r"[^/]+/\d+", record["record"]):
        raise ValueError("multi-segment headers are not handled")
    signals = []
    for line in body[1:1 + record["nsig"]]:
        f = line.split()
        fmt, _, offset = f[1].partition("+")
        gain_text = f[2] if len(f) > 2 else "200"
        units = gain_text.split("/", 1)[1] if "/" in gain_text else "mV"
        gain = float(re.split(r"[(/]", gain_text)[0] or 200)
        signals.append({"file": f[0], "fmt": int(fmt.split(":")[0].split("x")[0]),
                        "byte_offset": int(offset or 0), "gain": gain, "units": units,
                        "adc_res": int(f[3]) if len(f) > 3 else None,
                        "adc_zero": int(f[4]) if len(f) > 4 else None,
                        "init": int(f[5]) if len(f) > 5 else None,
                        "checksum": int(f[6]) if len(f) > 6 else None,
                        "desc": " ".join(f[8:]) if len(f) > 8 else None})
    if len(signals) != record["nsig"]:
        raise ValueError(f"{len(signals)} signal lines for nsig={record['nsig']}")
    fields: dict[str, str] = {}
    for comment in comments:
        key, sep, value = comment.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    record["signals"] = signals
    record["leads"] = [s["desc"] for s in signals]
    record["comments"] = comments
    record["fields"] = fields
    dx = fields.get("Dx")
    record["dx"] = [code.strip() for code in dx.split(",") if code.strip()] if dx else []
    return record


_WFDB_FMT = {16: ("h", 2), 32: ("i", 4)}   # little-endian two's complement
_MAT_ELEM = {0: ("d", 8), 1: ("f", 4), 2: ("i", 4), 3: ("h", 2), 4: ("H", 2), 5: ("B", 1)}


def read_mat_v4(data: bytes) -> dict[str, Any]:
    """Header of the first matrix of a MATLAB level-4 file (Challenge 2021 ``.mat``)."""

    if len(data) < 20:
        raise ValueError("too short for a MATLAB v4 header")
    mopt, mrows, ncols, imagf, namlen = struct.unpack("<5i", data[:20])
    m, o, p, t = mopt // 1000, (mopt // 100) % 10, (mopt // 10) % 10, mopt % 10
    if m != 0 or o != 0 or t != 0 or p not in _MAT_ELEM or not (0 < namlen < 64):
        raise ValueError(f"not a little-endian numeric MATLAB v4 matrix (MOPT={mopt})")
    code, width = _MAT_ELEM[p]
    name = data[20:20 + namlen].rstrip(b"\0").decode("ascii", "replace")
    offset = 20 + namlen
    expected = offset + mrows * ncols * width * (2 if imagf else 1)
    return {"mopt": mopt, "name": name, "rows": mrows, "cols": ncols, "imag": bool(imagf),
            "type": code, "elem_bytes": width, "data_offset": offset, "expected_bytes": expected}


def wfdb_checksums(samples: array.array, nsig: int) -> list[int]:
    """WFDB per-signal checksums (sum of samples modulo 2**16, as signed 16-bit).

    Samples are interleaved frame by frame; a MATLAB (nsig x n) matrix is stored column-major,
    which is the same interleaving.
    """

    sums = [0] * nsig
    for index, value in enumerate(samples):
        sums[index % nsig] += value
    return [((s + 32768) % 65536) - 32768 for s in sums]


def verify_record(hea_path: Path, data_path: Path) -> dict[str, Any]:
    """Parse a header and check its signal file: size, matrix shape and the header checksums."""

    header = parse_hea(hea_path.read_text(encoding="utf-8", errors="replace"))
    data = data_path.read_bytes()
    nsig, nsamp = header["nsig"], header["nsamples"]
    fmts = {s["fmt"] for s in header["signals"]}
    if len(fmts) != 1 or not fmts <= set(_WFDB_FMT):
        raise ValueError(f"only WFDB formats 16/32 handled, got {sorted(fmts)}")
    fmt = fmts.pop()
    code, width = _WFDB_FMT[fmt]
    offset = header["signals"][0]["byte_offset"]
    result: dict[str, Any] = {"record": header["record"], "fs": header["fs"], "nsig": nsig,
                              "nsamples": nsamp, "leads": header["leads"], "dx": header["dx"],
                              "fields": header["fields"], "bytes": len(data)}
    if data_path.suffix == ".mat":
        mat = read_mat_v4(data)
        if (mat["rows"], mat["cols"]) != (nsig, nsamp) or mat["type"] != "h":
            raise ValueError(f"mat matrix {mat['rows']}x{mat['cols']} {mat['type']} != "
                             f"{nsig}x{nsamp} int16")
        if len(data) != mat["expected_bytes"]:
            raise ValueError(f"mat size {len(data)} != {mat['expected_bytes']}")
        offset = mat["data_offset"]
        result["mat"] = {k: mat[k] for k in ("mopt", "name", "rows", "cols", "type")}
    expected = offset + nsig * nsamp * width
    if len(data) != expected:
        raise ValueError(f"signal file is {len(data)} bytes, expected {expected}")
    samples = array.array(code)
    samples.frombytes(data[offset:expected])
    if sys.byteorder != "little":
        samples.byteswap()
    sums = wfdb_checksums(samples, nsig)
    want = [s["checksum"] for s in header["signals"]]
    result["format"] = fmt
    # some writers store the checksum unsigned (0..65535): compare modulo 2**16
    result["checksums_match"] = all(w is None or (w - g) % 65536 == 0 for w, g in zip(want, sums))
    if not result["checksums_match"]:
        raise ValueError(f"WFDB checksums {sums} != header {want}")
    return result


def csv_columns(text: str) -> list[str]:
    return [c.strip().lstrip("\ufeff") for c in next(csv.reader(io.StringIO(text)))]


def check_columns(columns: Iterable[str], required: Iterable[str]) -> list[str]:
    have = {c.strip() for c in columns}
    return [c for c in required if c not in have]


def csv_stats(path: Path) -> dict[str, Any]:
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        columns = [c.strip().lstrip("\ufeff") for c in next(reader)]
        rows = sum(1 for _ in reader)
    return {"columns": columns, "rows": rows}


def md5_file(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - publisher checksum, not security
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------- bridge helpers


@dataclass
class Want:
    url: str
    rel: str
    sha256: str | None = None
    md5: str | None = None
    expected_bytes: int | None = None


def fetch_one(want: Want, out_dir: Path, *, task_bytes: int | None = None,
              direct_blocked: bool = False, runner: Any = None,
              wait_seconds: int = 900) -> dict[str, Any]:
    """One bridge job, waited for, then checked (size, md5/sha256, not an HTML page)."""

    out = out_dir / want.rel
    if _verified_on_disk(out, want):
        record = previous_job(out) or {"state": "completed"}
        info = {"file": want.rel, "url": want.url, **od.route_record(record), "reused": True}
        info.update({"bytes": out.stat().st_size, "sha256": od.sha256_file(out), "ok": True,
                     "checksum": "sha256" if want.sha256 else "md5"})
        return info
    record = od.submit(want.url, out, sha256=want.sha256, expected_bytes=want.expected_bytes,
                       task_bytes=task_bytes, direct_blocked=direct_blocked, wait=True,
                       timeout=120, runner=runner)
    if record.get("state") in {"queued", "running"} and record.get("id"):
        record = od.wait_for(record["id"], timeout=wait_seconds, runner=runner)
    info = {"file": want.rel, "url": want.url, **od.route_record(record)}
    if record.get("state") != "completed":
        info["ok"] = False
        info["problem"] = f"bridge state {record.get('state')}"
        return info
    data_head = out.read_bytes()[:512]
    problems = []
    if od.looks_like_html(data_head) and not want.rel.endswith((".htm", ".html")):
        problems.append("HTML page instead of data")
    if want.expected_bytes and out.stat().st_size != want.expected_bytes:
        problems.append(f"size {out.stat().st_size} != {want.expected_bytes}")
    digest = od.sha256_file(out)
    if want.sha256 and digest != want.sha256:
        problems.append("sha256 mismatch")
    if want.md5 and md5_file(out) != want.md5:
        problems.append("md5 mismatch")
    info.update({"bytes": out.stat().st_size, "sha256": digest, "ok": not problems,
                 "checksum": "sha256" if want.sha256 else ("md5" if want.md5 else "none")})
    if problems:
        info["problem"] = "; ".join(problems)
    return info


BRIDGE_STATUS = Path(od.BRIDGE).parent / "status"


def _verified_on_disk(out: Path, want: Want) -> bool:
    """A file already completed earlier and matching the publisher checksum is not re-fetched."""

    if not out.is_file() or not (want.sha256 or want.md5):
        return False
    if want.expected_bytes and out.stat().st_size != want.expected_bytes:
        return False
    if want.sha256 and od.sha256_file(out) != want.sha256:
        return False
    return not (want.md5 and md5_file(out) != want.md5)


_JOB_INDEX: dict[str, dict[str, dict[str, Any]]] = {}


def previous_job(out: Path, status_dir: Path = BRIDGE_STATUS) -> dict[str, Any] | None:
    """The completed bridge status record that wrote ``out`` (for provenance on re-runs)."""

    key = str(status_dir)
    if key not in _JOB_INDEX:
        index: dict[str, dict[str, Any]] = {}
        for path in sorted(status_dir.glob("*.json")) if status_dir.is_dir() else []:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.get("state") == "completed" and record.get("container_output"):
                index[record["container_output"]] = record
        _JOB_INDEX[key] = index
    return _JOB_INDEX[key].get(str(out))


MAX_LISTINGS = 200


def physionet_sizes(project: str, paths: Iterable[str],
                    lister: Callable[[str, str], list[dict[str, Any]]] | None = None) -> dict:
    """Remote sizes of ``paths`` from one directory listing per distinct parent directory."""

    lister = lister or listing
    parents: dict[str, list[str]] = {}
    for path in paths:
        parent, _, name = path.rpartition("/")
        parents.setdefault(parent, []).append(name)
    if len(parents) > MAX_LISTINGS:
        raise od.OpenDataError(f"{len(parents)} directories: fetch in smaller slices "
                               f"(<= {MAX_LISTINGS} directories per call)")
    sizes = {}
    for parent, names in parents.items():
        rows = {row["name"]: row["bytes"] for row in lister(project, parent) if not row["is_dir"]}
        for name in names:
            if rows.get(name) is not None:
                sizes[f"{parent}/{name}" if parent else name] = rows[name]
    return sizes


def physionet_wants(project: str, paths: Iterable[str], *, sums: dict[str, str] | None = None,
                    fetch: Fetcher = range_fetch, sums_size: int | None = None) -> list[Want]:
    wants = []
    if sums is None and sums_size is None:
        sums_size = remote_size(project, "SHA256SUMS.txt")
    for path in paths:
        if path == "SHA256SUMS.txt":
            digest = None
        elif sums is not None:
            digest = sums.get(path)
        else:
            digest = physionet_sha256(project, path, fetch=fetch, sums_size=sums_size)
        if digest is None and path != "SHA256SUMS.txt":
            raise od.OpenDataError(f"{project}: {path} not in SHA256SUMS.txt")
        wants.append(Want(physionet_url(project, path), path, sha256=digest))
    return wants


def write_sample_manifest(out_dir: Path, source_id: str, files: list[dict[str, Any]],
                          checks: dict[str, Any]) -> Path:
    manifest = {"schema": "openlabs.open_data.sample.v1", "line": LINE, "source_id": source_id,
                "fetched_at": od.utc_now(), "files": files, "checks": checks,
                "total_bytes": sum(int(f.get("bytes") or 0) for f in files)}
    path = out_dir / "SAMPLE.json"
    path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def _write_excerpt(out_dir: Path, rel: str, text: str, url: str) -> dict[str, Any]:
    target = out_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"file": rel, "url": url, "channel": "query-proxy (HTTP Range excerpt)",
            "bytes": target.stat().st_size, "sha256": od.sha256_file(target), "ok": True}


PHYSIONET_DOMESTIC = [
    {"candidate": "PhysioNet official mirror list (archive.physionet.org/mirrors/)",
     "result": "mirrors in Bethesda, Sao Paulo, Zaragoza, Ljubljana, Romania, Tallinn (page last "
               "updated 2018); none in China"},
    {"candidate": "web search 'PhysioNet 国内镜像' (2026-11-25)",
     "result": "only CSDN blog posts and Baidu-netdisk re-uploads (not trustworthy sources); no "
               "university mirror (Tsinghua/USTC/SJTU mirror lists do not carry PhysioNet)"},
    {"candidate": "AWS Open Data s3://physionet-open",
     "result": "official PhysioNet mirror, not domestic; physionet.org redirects large files "
               "there (302 to physionet-open.s3.amazonaws.com)"},
]


def _physionet_sample(source_id: str, project: str, paths: list[str],
                      verify: Callable[[Path, list[dict[str, Any]]], dict[str, Any]],
                      excerpts: Iterable[tuple[str, str]] = (), runner: Any = None) -> dict:
    out_dir = SAMPLES / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    sums_size = remote_size(project, "SHA256SUMS.txt")
    wants = physionet_wants(project, paths, sums_size=sums_size)
    subset = "".join(f"{w.sha256}  {w.rel}\n" for w in wants if w.sha256)
    (out_dir / "SHA256SUMS.subset.txt").write_text(subset, encoding="utf-8")
    total = sum(physionet_sizes(project, [w.rel for w in wants]).values())
    files = [fetch_one(w, out_dir, task_bytes=total or None, runner=runner) for w in wants]
    for rel, remote in excerpts:
        files.append(_write_excerpt(out_dir, rel, csv_header_remote(physionet_url(project, remote)),
                                    physionet_url(project, remote)))
    checks = {"sha256sums_size_bytes": sums_size,
              "sha256_source": "publisher SHA256SUMS.txt lines found by HTTP Range bisection; "
                               "kept in SHA256SUMS.subset.txt"}
    if all(f.get("ok") for f in files):
        checks.update(verify(out_dir, files))
    else:
        checks["failed"] = [f for f in files if not f.get("ok")]
    write_sample_manifest(out_dir, source_id, files, checks)
    route = next((f for f in files if f.get("route")), {})
    od.write_selection(out_dir / "source_selection.json", source_id=source_id,
                       original=physionet_url(project), domestic_candidates=PHYSIONET_DOMESTIC,
                       chosen=physionet_url(project), route=route,
                       notes="per-file bridge jobs with publisher sha256; no domestic mirror")
    return {"source": source_id, "files": files, "checks": checks}


def _verify_ptbxl_plus(out_dir: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    desc = csv_stats(out_dir / "features/feature_description.csv")
    checks["feature_description"] = {"rows": desc["rows"], "columns": desc["columns"]}
    for name in ("12sl", "unig", "ecgdeli"):
        cols = csv_columns((out_dir / f"features/{name}_features.head.csv").read_text())
        checks[f"{name}_features_header"] = {"n_columns": len(cols), "first": cols[:6]}
    snomed = csv_stats(out_dir / "labels/snomed_description.csv")
    checks["snomed_description"] = {"rows": snomed["rows"], "columns": snomed["columns"]}
    for name in ("ptbxlToSNOMED", "12slv23ToSNOMED"):
        stats = csv_stats(out_dir / f"labels/mapping/{name}.csv")
        checks[name] = {"rows": stats["rows"], "columns": stats["columns"]}
    beat = verify_record(out_dir / "median_beats/12sl/00000/00001_medians.hea",
                         out_dir / "median_beats/12sl/00000/00001_medians.dat")
    checks["median_beat_00001"] = {k: beat[k] for k in ("fs", "nsig", "nsamples", "leads",
                                                         "checksums_match")}
    atr = (out_dir / "fiducial_points/ecgdeli/00000/00001_points_global.atr").stat().st_size
    checks["fiducial_points_00001_global_atr_bytes"] = atr
    return checks


def sample_ptbxl_plus(runner: Any = None) -> dict:
    paths = ["LICENSE.txt", "features/feature_description.csv", "labels/snomed_description.csv",
             "labels/mapping/ptbxlToSNOMED.csv", "labels/mapping/12slv23ToSNOMED.csv",
             "median_beats/12sl/00000/00001_medians.hea",
             "median_beats/12sl/00000/00001_medians.dat",
             "fiducial_points/ecgdeli/00000/00001_points_global.atr"]
    excerpts = [(f"features/{n}_features.head.csv", f"features/{n}_features.csv")
                for n in ("12sl", "unig", "ecgdeli")]
    return _physionet_sample("ptb-xl-plus", "ptb-xl-plus", paths, _verify_ptbxl_plus, excerpts,
                             runner)


CHALLENGE_RECORDS = ["training/cpsc_2018/g1/A0001", "training/cpsc_2018/g1/A0002",
                     "training/ningbo/g1/JS10647", "training/georgia/g1/E00001"]


def _verify_records(prefixes: list[str], data_ext: str) -> Callable:
    def verify(out_dir: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
        records = {}
        for prefix in prefixes:
            rec = verify_record(out_dir / f"{prefix}.hea", out_dir / f"{prefix}{data_ext}")
            records[prefix] = {k: rec.get(k) for k in ("fs", "nsig", "nsamples", "leads", "dx",
                                                       "fields", "mat", "checksums_match")}
        return {"records": records}
    return verify


def sample_challenge_2021(runner: Any = None) -> dict:
    paths = ["LICENSE.txt", "RECORDS"]
    for prefix in CHALLENGE_RECORDS:
        paths += [f"{prefix}.hea", f"{prefix}.mat"]
    return _physionet_sample("challenge-2021", "challenge-2021", paths,
                             _verify_records(CHALLENGE_RECORDS, ".mat"), runner=runner)


MIMIC_RECORDS = ["files/p1000/p10000032/s40689238/40689238",
                 "files/p1000/p10000032/s44458630/44458630"]


def _verify_mimic(out_dir: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    checks = _verify_records(MIMIC_RECORDS, ".dat")(out_dir, files)
    dictionary = csv_stats(out_dir / "machine_measurements_data_dictionary.csv")
    checks["data_dictionary"] = {"rows": dictionary["rows"], "columns": dictionary["columns"]}
    for name, required in (("machine_measurements", MIMIC_MEASUREMENT_COLUMNS),
                           ("record_list", MIMIC_RECORD_LIST_COLUMNS)):
        cols = csv_columns((out_dir / f"{name}.head.csv").read_text())
        missing = check_columns(cols, required)
        if missing:
            raise ValueError(f"{name}.csv lacks {missing}")
        checks[f"{name}_header"] = {"n_columns": len(cols), "columns": cols}
    return checks


def sample_mimic_iv_ecg(runner: Any = None) -> dict:
    paths = ["LICENSE.txt", "RECORDS", "machine_measurements_data_dictionary.csv"]
    for prefix in MIMIC_RECORDS:
        paths += [f"{prefix}.hea", f"{prefix}.dat"]
    excerpts = [(f"{n}.head.csv", f"{n}.csv") for n in
                ("machine_measurements", "record_list", "waveform_note_links")]
    return _physionet_sample("mimic-iv-ecg", "mimic-iv-ecg", paths, _verify_mimic, excerpts,
                             runner)


# --------------------------------------------------------------------------- Zenodo


ZENODO_SAVED_META = {  # record metadata saved through the bridge on 2026-11-24 (survey refs)
    4916206: Path("/workspace/openlabs/maintenance/20261124-datasources/refs/zenodo_4916206_code15.json"),
    4905618: Path("/workspace/openlabs/maintenance/20261124-datasources/refs/zenodo_4905618_samitrop.json"),
}


def zenodo_files(record: int) -> list[dict[str, Any]]:
    """File keys, sizes and md5 from the Zenodo API (saved record JSON if the API errors)."""

    try:
        meta = od.query_json(f"{ZENODO_API}/{record}", max_bytes=2 * 1024 * 1024)
    except OSError as exc:  # urllib HTTPError/URLError; Zenodo API answered 500 on 2026-11-25
        saved = ZENODO_SAVED_META.get(record)
        if not saved or not saved.is_file():
            raise
        print(f"zenodo API failed ({exc}); using saved metadata {saved}", file=sys.stderr)
        meta = json.loads(saved.read_text(encoding="utf-8"))
    return [{"key": f["key"], "bytes": int(f["size"]),
             "md5": str(f.get("checksum", "")).removeprefix("md5:") or None,
             "url": zenodo_file_url(record, f["key"])} for f in meta.get("files", [])]


ZENODO_DOMESTIC = [
    {"candidate": "web search for a Chinese copy of CODE-15% / SaMi-Trop (ScienceDB, OpenDataLab)",
     "result": "none found; Zenodo is the only publisher copy (direct route works from WSL)"},
]


def sample_zenodo(source_id: str, key: str, required: list[str], runner: Any = None) -> dict:
    record = ZENODO_RECORDS[source_id]
    entry = next(f for f in zenodo_files(record) if f["key"] == key)
    out_dir = SAMPLES / source_id
    want = Want(entry["url"], key, md5=entry["md5"], expected_bytes=entry["bytes"])
    info = fetch_one(want, out_dir, task_bytes=entry["bytes"], runner=runner)
    checks: dict[str, Any] = {"md5_published": entry["md5"]}
    if info.get("ok"):
        stats = csv_stats(out_dir / key)
        missing = check_columns(stats["columns"], required)
        checks.update({"columns": stats["columns"], "rows": stats["rows"], "missing": missing})
        if missing:
            info["ok"] = False
            info["problem"] = f"missing columns {missing}"
    write_sample_manifest(out_dir, source_id, [info], checks)
    od.write_selection(out_dir / "source_selection.json", source_id=source_id,
                       original=f"https://zenodo.org/records/{record}",
                       domestic_candidates=ZENODO_DOMESTIC, chosen=entry["url"],
                       route=info, notes="Zenodo API file URL; publisher md5 verified after download")
    return {"source": source_id, "files": [info], "checks": checks}


# --------------------------------------------------------------------------- SPH (figshare)


SPH_DOMESTIC = [
    {"candidate": "paper data availability statement (Sci Data 9, 272 (2022), "
                  "doi:10.1038/s41597-022-01403-5)",
     "result": "names only the figshare collection doi:10.6084/m9.figshare.c.5779802"},
    {"candidate": "web search for ScienceDB / Chinese hosts ('山东省立医院 心电 数据库', SPH ECG)",
     "result": "no domestic copy found; Mendeley 'SPHDB' (g23n565xh3) is a different dataset "
               "(250 Holter AF recordings), not an equivalent"},
]


def sample_sph(runner: Any = None) -> dict:
    out_dir = SAMPLES / "sph"
    files = []
    small = ["code.csv", "metadata.csv"]
    total = sum(SPH_FILES[k]["bytes"] for k in small)
    for key in small:
        meta = SPH_FILES[key]
        want = Want(meta["url"], key, md5=meta["md5"], expected_bytes=meta["bytes"])
        files.append(fetch_one(want, out_dir, task_bytes=total, runner=runner, wait_seconds=600))
    checks: dict[str, Any] = {}
    if all(f.get("ok") for f in files):
        for key in small:
            stats = csv_stats(out_dir / key)
            checks[key] = {"rows": stats["rows"], "columns": stats["columns"]}
    write_sample_manifest(out_dir, "sph", files, checks)
    od.write_selection(out_dir / "source_selection.json", source_id="sph",
                       original="https://doi.org/10.6084/m9.figshare.c.5779802",
                       domestic_candidates=SPH_DOMESTIC, chosen="ndownloader.figshare.com",
                       route=next((f for f in files if f.get("route")), files[0]),
                       notes="figshare direct HTTP 403 from WSL (2026-11-24); bridge proxy fallback. "
                             "records.tar.gz 2.28 GB is a large proxy download: off-peak only.")
    return {"source": "sph", "files": files, "checks": checks}


def sph_fetch_records(runner: Any = None, now: Any = None) -> dict:
    meta = SPH_FILES["records.tar.gz"]
    od.check_window(route="auto", direct_blocked=True, file_bytes=meta["bytes"], now=now)
    record = od.submit(meta["url"], DOWNLOADS / "sph" / "records.tar.gz",
                       expected_bytes=meta["bytes"], task_bytes=meta["bytes"], large=True,
                       direct_blocked=True, wait=False, runner=runner, now=now)
    return {"submitted": record, "md5_to_check": meta["md5"]}


# --------------------------------------------------------------------------- CLI


SAMPLERS = {
    "ptb-xl-plus": sample_ptbxl_plus,
    "challenge-2021": sample_challenge_2021,
    "mimic-iv-ecg": sample_mimic_iv_ecg,
    "code-15": lambda runner=None: sample_zenodo("code-15", "exams.csv", CODE15_COLUMNS, runner),
    "sami-trop": lambda runner=None: sample_zenodo(
        "sami-trop", "exams.csv", ["exam_id", "age", "is_male", "normal_ecg", "death", "timey"],
        runner),
    "sph": sample_sph,
}


def cmd_physionet(args: argparse.Namespace) -> int:
    if args.action == "list":
        for row in listing(args.project, args.paths[0] if args.paths else ""):
            print(f"{'d' if row['is_dir'] else '-'} {row['bytes'] or '':>12} {row['name']}")
        return 0
    if args.action == "sha256":
        size = remote_size(args.project, "SHA256SUMS.txt")
        for path in args.paths:
            print(f"{physionet_sha256(args.project, path, sums_size=size) or 'NOT-FOUND'}  {path}")
        return 0
    if args.action == "sums":
        out = Path(args.out or DOWNLOADS / args.project) / "SHA256SUMS.txt"
        print(json.dumps(od.submit(physionet_url(args.project, "SHA256SUMS.txt"), out,
                                   wait=args.wait), ensure_ascii=False))
        return 0
    paths = list(args.paths)
    if args.paths_file:
        paths += [line.strip() for line in Path(args.paths_file).read_text().splitlines()
                  if line.strip() and not line.startswith("#")]
    if not paths:
        raise SystemExit("fetch needs paths (no implicit whole-project download)")
    out = Path(args.out or DOWNLOADS / args.project)
    sums = load_sums(Path(args.sums).read_text()) if args.sums else None
    sizes = physionet_sizes(args.project, paths)
    # PhysioNet direct is fine for small files but the 1.84 GB PTB-XL zip fell back to the proxy
    # (curl=28, 2026-11-13): large batches are treated as proxy-bound (window rule applies).
    batch = od.Batch(out / "batch-manifest.json", route="auto", direct_blocked=True)
    for want in physionet_wants(args.project, paths, sums=sums):
        batch.add(want.url, str(out / want.rel), sha256=want.sha256,
                  expected_bytes=sizes.get(want.rel))
    try:
        counts = batch.run(limit=args.limit, wait=args.wait)
    except od.OffPeakRequired as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(counts, ensure_ascii=False))
    return 0


def cmd_zenodo(args: argparse.Namespace) -> int:
    record = ZENODO_RECORDS[args.source]
    files = zenodo_files(record)
    if args.action == "list":
        for f in files:
            print(f"{f['bytes']:>12} md5:{f['md5']} {f['key']}")
        return 0
    chosen = [f for f in files if f["key"] in set(args.keys)]
    if not chosen:
        raise SystemExit("fetch needs file keys from 'zenodo list'")
    big = [f["key"] for f in chosen if od.is_large(f["bytes"])]
    if (big or od.is_large(batch_bytes=sum(f["bytes"] for f in chosen))) and not args.allow_large:
        raise SystemExit(f"large files {big or 'batch'}: pass --allow-large deliberately "
                         "(Zenodo direct route; md5 to be checked after completion)")
    out = Path(args.out or DOWNLOADS / args.source)
    # Zenodo direct dropped mid-transfer on the 35 MB exams.csv (curl=18, 2026-11-25) and the
    # bridge fell back to the proxy: large Zenodo batches are treated as proxy-bound.
    batch = od.Batch(out / "batch-manifest.json", route="auto", direct_blocked=True)
    for f in chosen:
        batch.add(f["url"], str(out / f["key"]), expected_bytes=f["bytes"])
    try:
        counts = batch.run(limit=args.limit, wait=False)
    except od.OffPeakRequired as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(counts, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sources", help="print the projects/records this tool knows")
    phys = sub.add_parser("physionet", help="any PhysioNet open project")
    phys.add_argument("action", choices=["list", "sha256", "fetch", "sums"])
    phys.add_argument("project")
    phys.add_argument("paths", nargs="*")
    phys.add_argument("--paths-file")
    phys.add_argument("--sums", help="local SHA256SUMS.txt (else Range lookup per file)")
    phys.add_argument("--out")
    phys.add_argument("--limit", type=int)
    phys.add_argument("--wait", action="store_true")
    zen = sub.add_parser("zenodo", help="CODE-15%% / SaMi-Trop files")
    zen.add_argument("action", choices=["list", "fetch"])
    zen.add_argument("source", choices=sorted(ZENODO_RECORDS))
    zen.add_argument("keys", nargs="*")
    zen.add_argument("--out")
    zen.add_argument("--limit", type=int)
    zen.add_argument("--allow-large", action="store_true")
    sph = sub.add_parser("sph", help="SPH figshare files")
    sph.add_argument("action", choices=["list", "fetch-records"])
    sample = sub.add_parser("sample", help="fetch and verify the small sample of a source")
    sample.add_argument("source", choices=[*SAMPLERS, "all"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sources":
        for name, (version, licence) in PHYSIONET_PROJECTS.items():
            print(f"physionet {name} {version} [{licence}] {physionet_url(name)}")
        for name, record in ZENODO_RECORDS.items():
            print(f"zenodo {name} record {record} [CC BY 4.0]")
        print("figshare sph collection 5779802 [CC0]")
        return 0
    if args.command == "physionet":
        return cmd_physionet(args)
    if args.command == "zenodo":
        return cmd_zenodo(args)
    if args.command == "sph":
        if args.action == "list":
            for key, meta in SPH_FILES.items():
                print(f"{meta['bytes']:>12} md5:{meta['md5']} {key} {meta['url']}")
            return 0
        try:
            print(json.dumps(sph_fetch_records(), ensure_ascii=False))
        except od.OffPeakRequired as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        return 0
    names = list(SAMPLERS) if args.source == "all" else [args.source]
    failed = 0
    for name in names:
        result = SAMPLERS[name]()
        bad = [f for f in result["files"] if not f.get("ok")]
        failed += bool(bad)
        print(json.dumps({"source": name, "ok": not bad, "files": [
            {k: f.get(k) for k in ("file", "bytes", "id", "state", "route", "problem")}
            for f in result["files"]], "checks": result["checks"]}, ensure_ascii=False,
            default=str)[:4000])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
