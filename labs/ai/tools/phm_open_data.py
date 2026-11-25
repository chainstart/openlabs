"""Free public PHM / reliability data sources for the ``phm-evaluation-audit`` line (2026-11-25).

Sub-commands (every network call is explicit and bounded)::

    python3 labs/ai/tools/phm_open_data.py sources
    python3 labs/ai/tools/phm_open_data.py list   <source>          # files + sizes + checksums
    python3 labs/ai/tools/phm_open_data.py sample <source>          # small sample via the bridge
    python3 labs/ai/tools/phm_open_data.py fetch  <source> --dest DIR [--files NAME ...] [--limit N] [--wait]
    python3 labs/ai/tools/phm_open_data.py verify <file> [--md5 HEX] [--sha256 HEX]

File listings come from small metadata APIs (Zenodo records API, Mendeley Data public API) or
HEAD requests (OpenEI, UFRJ MAFAULDA, NASA phm-datasets S3) read through the Clash proxy. Files
go through the WSL download bridge (``od.submit`` / ``od.Batch``), route ``auto``; a large batch
that is known to go over the proxy is refused outside Beijing 02:00-14:00 (``od.check_window``).
Zenodo publishes md5 only and S3 single-part ETags are md5 too: those are checked after the
download (``verify``); Mendeley publishes sha256, which is passed to the bridge.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "open-data"))
import open_data as od  # noqa: E402

LINE = "phm-evaluation-audit"
LINE_DIR = Path("/workspace/openlabs/build/lines") / LINE
SAMPLES = LINE_DIR / "data" / "open-samples"
ZENODO_API = "https://zenodo.org/api/records/{record}"
MENDELEY_FILES = ("https://data.mendeley.com/public-api/datasets/{dataset}/files"
                  "?folder_id=root&version={version}")
MENDELEY_META = "https://data.mendeley.com/public-api/datasets/{dataset}?version={version}"
SAMPLE_MAX_BYTES = 50 * 1024 * 1024  # a sample file is never larger than this

DOMESTIC_SEARCH = [
    {"candidate": "ScienceDB (scidb.cn)", "result": "no record of this dataset found (web search 2026-11-25)"},
    {"candidate": "Aliyun Tianchi / Baidu AI Studio / CSDN / Baidu netdisk reposts",
     "result": "only unofficial reposts (e.g. Tianchi CALCE repost labelled CC-BY-SA-NC, netdisk "
               "copies of NASA battery sets); version/licence not equivalent - not used"},
    {"candidate": "Chinese university mirrors (TUNA/USTC/SJTUG)",
     "result": "they mirror software, not Zenodo/Mendeley/OpenEI/NASA data records"},
]

# kind: zenodo | mendeley | static. ``sample`` names the small files (by key) a sample fetches;
# an empty list means metadata only. ``files`` (static kinds) are (name, url) pairs.
SOURCES: dict[str, dict[str, Any]] = {
    "care-to-compare": {"kind": "zenodo", "record": "15846963", "sample": [],
                        "note": "one 5.5 GB zip (CARE_To_Compare.zip): sample is the record metadata only"},
    "kelmarsh": {"kind": "zenodo", "record": "5841834",
                 "sample": ["Kelmarsh_WT_static.csv", "Kelmarsh_WT_dataSignalMapping.csv"]},
    "penmanshiel": {"kind": "zenodo", "record": "5946808", "sample": ["Penmanshiel_WT_static.csv"]},
    "hill-of-towie": {"kind": "zenodo", "record": "22662930",
                      "sample": ["Hill_of_Towie_turbine_metadata.csv",
                                 "Hill_of_Towie_tables_description.csv"]},
    "nasa-randomized-battery-zenodo": {"kind": "zenodo", "record": "15277374", "sample": []},
    "kaist-varying-load": {"kind": "mendeley", "dataset": "ztmf3m7h5x", "version": 6,
                           "sample": ["acoustic.zip"]},
    "kaist-varying-speed": {"kind": "mendeley", "dataset": "vxkj334rzv", "version": 7, "sample": [],
                            "note": "one 10.35 GB zip (part1.zip): sample is the file list only"},
    "nrel-grc-gearbox": {
        "kind": "static", "landing": "https://data.openei.org/submissions/738",
        "files": [
            ("WindTurbineConditionMonitoringLicenseInfo.txt",
             "https://data.openei.org/files/738/WindTurbineConditionMonitoringLicenseInfo.txt"),
            ("Vibration Condition Monitoring Benchmarking Datasets.pdf",
             "https://data.openei.org/files/738/Vibration%20Condition%20Monitoring%20Benchmarking%20Datasets.pdf"),
            ("Healthy.zip", "https://data.openei.org/files/738/Healthy.zip"),
            ("Damaged.zip", "https://data.openei.org/files/738/Damaged.zip"),
        ],
        "sample": ["WindTurbineConditionMonitoringLicenseInfo.txt",
                   "Vibration Condition Monitoring Benchmarking Datasets.pdf"]},
    "mafaulda": {
        "kind": "static", "landing": "https://www02.smt.ufrj.br/~offshore/mfs/page_01.html",
        "files": [(name, f"https://www02.smt.ufrj.br/~offshore/mfs/database/mafaulda/{name}")
                  for name in ("normal.zip", "horizontal-misalignment.zip", "vertical-misalignment.zip",
                               "imbalance.zip", "overhang.zip", "underhang.zip", "full.zip")],
        "sample": [], "note": "smallest per-class zip is 325 MB: listing only, no sample file"},
    "nasa-pcoe": {
        "kind": "static",
        "landing": "https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/",
        "files": [(name, "https://phm-datasets.s3.amazonaws.com/NASA/" + urllib.parse.quote_plus(name))
                  for name in ("1. Algae Raceway.zip", "2. Composites.zip", "3. Milling.zip",
                               "4. Bearings.zip", "5. Battery Data Set.zip",
                               "6. Turbofan Engine Degradation Simulation Data Set.zip",
                               "8. IGBT Accelerated Aging.zip", "10. FEMTO Bearing.zip",
                               "11. Randomized Battery Usage Data Set.zip",
                               "12. Capacitor Electrical Stress.zip",
                               "13. MOSFET Thermal Overstress Aging.zip", "15. HIRF Battery Data Set.zip",
                               "17. Turbofan Engine Degradation Simulation Data Set 2.zip")],
        "sample": ["3. Milling.zip"]},
}


# --------------------------------------------------------------------------- listing


def zenodo_files(record: dict[str, Any], base: str = "https://zenodo.org") -> list[dict[str, Any]]:
    """Files of a Zenodo record API answer: name, bytes, md5, download URL."""

    rec_id = str(record.get("id") or record.get("recid") or "")
    out = []
    for item in record.get("files") or []:
        key = item.get("key") or item.get("filename")
        checksum = str(item.get("checksum") or "")
        md5 = checksum.split(":", 1)[1] if checksum.startswith("md5:") else None
        url = (item.get("links") or {}).get("self") or (
            f"{base}/records/{rec_id}/files/{urllib.parse.quote(key)}?download=1")
        out.append({"name": key, "bytes": int(item.get("size") or 0), "md5": md5, "sha256": None,
                    "url": url})
    return out


def mendeley_files(answer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in answer:
        details = item.get("content_details") or {}
        out.append({"name": item.get("filename"), "bytes": int(details.get("size") or 0), "md5": None,
                    "sha256": details.get("sha256_hash"), "url": details.get("download_url")})
    return out


def s3_md5(etag: str | None) -> str | None:
    """A single-part S3 ETag is the object's md5; a multipart one (``...-N``) is not."""

    value = (etag or "").strip().strip('"')
    if len(value) == 32 and all(c in "0123456789abcdef" for c in value.lower()):
        return value.lower()
    return None


def head(url: str, timeout: float = 30) -> dict[str, Any]:
    """HEAD request (headers only, no body) through the environment proxy."""

    od.public_url(url)
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": od.USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return {"status": response.status, "bytes": int(response.headers.get("Content-Length") or 0),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified")}


def list_files(source_id: str, *, query_json: Callable[..., Any] = od.query_json,
               head_fn: Callable[[str], dict[str, Any]] = head) -> tuple[list[dict[str, Any]], Any]:
    """(files, raw metadata answer) for a source."""

    spec = SOURCES[source_id]
    if spec["kind"] == "zenodo":
        record = query_json(ZENODO_API.format(record=spec["record"]), max_bytes=5 * 1024 * 1024)
        return zenodo_files(record), record
    if spec["kind"] == "mendeley":
        answer = query_json(MENDELEY_FILES.format(dataset=spec["dataset"], version=spec["version"]),
                            max_bytes=5 * 1024 * 1024)
        meta = query_json(MENDELEY_META.format(dataset=spec["dataset"], version=spec["version"]),
                          max_bytes=5 * 1024 * 1024)
        return mendeley_files(answer), {"dataset": meta, "files": answer}
    files = []
    for name, url in spec["files"]:
        info = head_fn(url)
        files.append({"name": name, "bytes": info.get("bytes"), "md5": s3_md5(info.get("etag"))
                      if "amazonaws.com" in url else None, "sha256": None, "url": url,
                      "etag": info.get("etag"), "last_modified": info.get("last_modified")})
    return files, {"landing": spec.get("landing"), "files": files, "listed_at": od.utc_now()}


# --------------------------------------------------------------------------- verification


def md5_file(path: str | Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - publisher checksum, not security
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_csv(data: bytes, max_rows: int = 5) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    if od.looks_like_html(text):
        raise od.OpenDataError("CSV sample is an HTML page")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        raise od.OpenDataError("CSV sample has no multi-column header")
    return f"CSV {len(rows) - 1} data rows x {len(rows[0])} columns; header {rows[0][:6]}"


def check_zip(path: str | Path, peek: int = 3) -> str:
    """List a zip's members and read the first lines of a CSV/TXT member (untrusted: read only)."""

    with zipfile.ZipFile(path) as archive:
        names = [info for info in archive.infolist() if not info.is_dir()]
        if not names:
            raise od.OpenDataError("zip has no members")
        bad = archive.testzip()
        if bad:
            raise od.OpenDataError(f"zip CRC error in {bad}")
        text_member = next((i for i in names if i.filename.lower().endswith((".csv", ".txt"))), None)
        detail = ""
        if text_member is not None:
            with archive.open(text_member) as handle:
                lines = [handle.readline().decode("utf-8", errors="replace").strip() for _ in range(peek)]
            detail = f"; {text_member.filename} first lines {lines}"
        nested = next((i for i in names if i.filename.lower().endswith(".zip")), None)
        if nested is not None and nested.file_size <= SAMPLE_MAX_BYTES:
            with zipfile.ZipFile(io.BytesIO(archive.read(nested))) as inner:
                inner_names = [i.filename for i in inner.infolist() if not i.is_dir()]
                if inner.testzip():
                    raise od.OpenDataError(f"nested zip CRC error in {nested.filename}")
            detail += f"; nested {nested.filename} CRC ok, {len(inner_names)} members {inner_names[:5]}"
        total = sum(i.file_size for i in names)
        return (f"zip CRC ok, {len(names)} members, {total} bytes uncompressed; first members "
                f"{[i.filename for i in names[:5]]}{detail}")


def check_file(path: str | Path) -> str:
    path = Path(path)
    with open(path, "rb") as handle:
        head_bytes = handle.read(1024)
    if od.looks_like_html(head_bytes):
        raise od.OpenDataError(f"{path.name} is an HTML page, not the data file")
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return check_zip(path)
    if suffix == ".csv":
        return check_csv(path.read_bytes())
    if suffix == ".pdf":
        if not head_bytes.startswith(b"%PDF-"):
            raise od.OpenDataError("not a PDF")
        return f"PDF header {head_bytes[:8].decode(errors='replace')!r}"
    text = path.read_bytes()[:4000].decode("utf-8", errors="replace")
    return f"text, first line {text.splitlines()[0][:160] if text else ''!r}"


def verify(path: str | Path, *, md5: str | None = None, sha256: str | None = None,
           size: int | None = None) -> dict[str, Any]:
    path = Path(path)
    result: dict[str, Any] = {"path": str(path), "bytes": path.stat().st_size,
                              "sha256": od.sha256_file(path)}
    if size is not None and result["bytes"] != int(size):
        raise od.OpenDataError(f"{path.name}: {result['bytes']} bytes, publisher says {size}")
    if sha256 and result["sha256"] != sha256.lower():
        raise od.OpenDataError(f"{path.name}: sha256 mismatch")
    if md5:
        result["md5"] = md5_file(path)
        if result["md5"] != md5.lower():
            raise od.OpenDataError(f"{path.name}: md5 mismatch")
    result["check"] = check_file(path)
    return result


# --------------------------------------------------------------------------- commands


def safe_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in name).strip("._")
    if not cleaned:
        raise od.OpenDataError(f"unusable file name {name!r}")
    return cleaned


def select(files: list[dict[str, Any]], names: list[str] | None) -> list[dict[str, Any]]:
    if names is None:
        return list(files)
    wanted = set(names)
    chosen = [f for f in files if f["name"] in wanted]
    missing = wanted - {f["name"] for f in chosen}
    if missing:
        raise od.OpenDataError(f"not in the listing: {sorted(missing)}")
    return chosen


def cmd_sample(source_id: str, *, out_root: Path = SAMPLES, submit: Callable[..., Any] = od.submit,
               lister: Callable[..., Any] = list_files,
               status: Callable[[str], dict[str, Any]] = od.status) -> dict[str, Any]:
    """Fetch and verify the source's sample files. A re-run re-polls a bridge job left running by
    an earlier run (from ``sample_report.json``) instead of submitting a duplicate."""

    spec = SOURCES[source_id]
    out_dir = out_root / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    previous: dict[str, Any] = {}
    report_path = out_dir / "sample_report.json"
    if report_path.is_file():
        previous = {f.get("name"): f for f in json.loads(report_path.read_text(encoding="utf-8")).get("files", [])}
    files, meta = lister(source_id)
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    report: dict[str, Any] = {"source": source_id, "fetched_at": od.utc_now(),
                              "metadata": str(out_dir / "metadata.json"),
                              "listing": [{k: f.get(k) for k in ("name", "bytes", "md5", "sha256")}
                                          for f in files],
                              "total_bytes": sum(int(f.get("bytes") or 0) for f in files),
                              "files": [], "note": spec.get("note", "")}
    for item in select(files, list(spec.get("sample") or [])):
        if int(item.get("bytes") or 0) > SAMPLE_MAX_BYTES:
            raise od.OpenDataError(f"{item['name']} is {item['bytes']} bytes: too big for a sample")
        target = out_dir / safe_name(item["name"])
        earlier = previous.get(item["name"]) or {}
        job = (earlier.get("bridge") or {}).get("id")
        if job and (earlier.get("bridge") or {}).get("state") == "completed" and target.is_file():
            record = dict(earlier["bridge"])  # already fetched: re-verify, never re-download
        elif job and (earlier.get("bridge") or {}).get("state") in {"queued", "running", "waiting_window"}:
            record = {**status(job), "id": job}
            if record.get("state") in {"queued", "running", "waiting_window"}:
                report["files"].append({"name": item["name"], "url": item["url"],
                                        "bridge": od.route_record(record),
                                        "error": f"bridge state {record.get('state')} (re-run later)"})
                continue
        else:
            record = submit(item["url"], target, sha256=item.get("sha256"), route="auto",
                            expected_bytes=item.get("bytes") or None, task_bytes=item.get("bytes") or None,
                            wait=True, timeout=600)
        entry: dict[str, Any] = {"name": item["name"], "url": item["url"], "bridge": od.route_record(record)}
        if record.get("state") == "completed" and target.is_file():
            entry.update(verify(target, md5=item.get("md5"), sha256=item.get("sha256"),
                                size=item.get("bytes") or None))
        else:
            entry["error"] = record.get("error") or f"bridge state {record.get('state')}"
        report["files"].append(entry)
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def cmd_fetch(source_id: str, dest: Path, *, names: list[str] | None, limit: int | None, wait: bool,
              direct_blocked: bool = False, lister: Callable[..., Any] = list_files,
              runner: Any = None, now: Any = None) -> dict[str, int]:
    files, _ = lister(source_id)
    batch = od.Batch(dest / "batch_manifest.json", route="auto", direct_blocked=direct_blocked)
    for item in select(files, names):
        batch.add(item["url"], str(dest / safe_name(item["name"])), sha256=item.get("sha256"),
                  expected_bytes=item.get("bytes") or None)
    return batch.run(limit=limit, wait=wait, runner=runner, now=now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sources")
    for name in ("list", "sample"):
        p = sub.add_parser(name)
        p.add_argument("source", choices=sorted(SOURCES))
    p = sub.add_parser("fetch")
    p.add_argument("source", choices=sorted(SOURCES))
    p.add_argument("--dest", type=Path, required=True)
    p.add_argument("--files", nargs="*", help="file names from `list` (default: all)")
    p.add_argument("--limit", type=int, help="submit at most N new files this run")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--direct-blocked", action="store_true",
                   help="the source's direct route is proven blocked (window rule then applies)")
    p = sub.add_parser("verify")
    p.add_argument("file", type=Path)
    p.add_argument("--md5")
    p.add_argument("--sha256")
    args = parser.parse_args(argv)
    if args.command == "sources":
        for key, spec in SOURCES.items():
            print(f"{key}\t{spec['kind']}\t{spec.get('record') or spec.get('dataset') or spec.get('landing')}")
        return 0
    if args.command == "list":
        files, _ = list_files(args.source)
        for item in files:
            print(f"{item['bytes'] or 0:>14}  {item.get('md5') or item.get('sha256') or '-':<64}  {item['name']}")
        print(f"total {sum(int(f['bytes'] or 0) for f in files)} bytes in {len(files)} files")
        return 0
    if args.command == "sample":
        report = cmd_sample(args.source)
        print(json.dumps({k: report[k] for k in ("source", "total_bytes", "files", "note")}, indent=1,
                         ensure_ascii=False))
        return 0 if all("error" not in f for f in report["files"]) else 1
    if args.command == "fetch":
        try:
            counts = cmd_fetch(args.source, args.dest, names=args.files or None, limit=args.limit, wait=args.wait,
                               direct_blocked=args.direct_blocked)
        except od.OffPeakRequired as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(counts))
        return 0
    print(json.dumps(verify(args.file, md5=args.md5, sha256=args.sha256), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
