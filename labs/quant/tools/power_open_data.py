"""Free, registration-free power-market data for the ``power-market-backtest`` line (2026-11-25).

Sub-commands (every network call is explicit and bounded):

* ``elexon list | sample | fetch``  - Elexon Insights / BMRS REST API (GB; no key; BMRS licence,
  attribution "Contains BMRS data (c) Elexon Limited copyright and database right [year]").
  The WSL direct route gets HTTP 403 from data.elexon.co.uk (2026-11-25), so the bridge falls
  back to the proxy: Elexon is treated as ``direct_blocked`` and large batches (>= 1 GB, e.g. a
  year of BOD) are refused outside Beijing 02:00-14:00.
* ``ercot probe``                    - checks whether the anonymous MIS listing answers. On
  2026-11-25 www.ercot.com and api.ercot.com returned HTTP 403 (Incapsula) to the container
  proxy and to the bridge (direct and proxy), so ``sample`` refuses unless ``probe`` succeeds.
* ``openelectricity list | sample | fetch`` - Open Electricity v4 API without a key ("Anonymous
  requests are treated as Community": last 2 years, 5-minute ranges <= 8 days; CC BY-NC 4.0).
* ``nasapower sample``               - NASA POWER hourly point API (no key).

Samples go under ``/workspace/openlabs/build/lines/power-market-backtest/data/open-samples/<id>/``
with a ``SAMPLES.json`` (url, bridge job, route, sha256, check) and ``source_selection.json``.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "open-data"))
import open_data as od  # noqa: E402

LINE = "power-market-backtest"
LINE_DIR = Path("/workspace/openlabs/build/lines") / LINE
SAMPLES = LINE_DIR / "data" / "open-samples"
LONDON = ZoneInfo("Europe/London")

ELEXON_BASE = "https://data.elexon.co.uk/bmrs/api/v1"
ELEXON_LICENCE = ("https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/"
                  "copyright-licence-bmrs-data/")
ELEXON_ATTRIBUTION = "Contains BMRS data © Elexon Limited copyright and database right {year}"
OE_BASE = "https://api.openelectricity.org.au/v4"
OE_ATTRIBUTION = "Data sourced from Open Electricity (The Superpower Institute), licensed under CC BY-NC 4.0"
NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/hourly/point"
ERCOT_DOCLIST = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS"
ERCOT_DOWNLOAD = "https://www.ercot.com/misdownload/servlets/mirDownload"

# Elexon datasets: path template, whether one request covers one settlement period (``sp``)
# or one settlement day (``day``), and the measured answer size of one request (2026-11-25,
# settlement day 2025-11-01; JSON).
ELEXON_DATASETS: dict[str, dict[str, Any]] = {
    "system-prices": {"path": "/balancing/settlement/system-prices/{date}", "per": "day",
                      "bytes": 42_224, "what": "SSP/SBP, NIV, accepted volumes per period"},
    "fuelhh": {"path": "/datasets/FUELHH?settlementDateFrom={date}&settlementDateTo={date}",
               "per": "day", "bytes": 174_192, "what": "half-hourly generation by fuel type"},
    "mid": {"path": "/datasets/MID?from={date}&to={next}", "per": "day", "bytes": 15_724,
            "what": "market index price and volume"},
    "disbsad": {"path": "/datasets/DISBSAD?from={date}&to={next}", "per": "day",
                "bytes": 38_331, "what": "disaggregated balancing services adjustment data"},
    "boalf": {"path": "/balancing/acceptances/all?settlementDate={date}&settlementPeriod={sp}",
              "per": "sp", "bytes": 203_844, "what": "bid-offer acceptances (all BM units)"},
    "bod": {"path": "/balancing/bid-offer/all?settlementDate={date}&settlementPeriod={sp}",
            "per": "sp", "bytes": 358_402, "what": "bid-offer pairs submitted (all BM units)"},
    "b1610": {"path": "/datasets/B1610?settlementDate={date}&settlementPeriod={sp}",
              "per": "sp", "bytes": 1_924_284, "what": "actual generation per BM unit"},
}

ERCOT_REPORTS = {
    "NP4-190-CD": {"reportTypeId": 12331, "what": "DAM settlement point prices (daily zip)"},
    "NP6-905-CD": {"reportTypeId": 12301, "what": "RTM settlement point prices (15-min, daily)"},
    "NP3-965-ER": {"reportTypeId": 13052,
                   "what": "60-day SCED disclosure (large zips; listing only)"},
}

SELECTION_FACTS: dict[str, dict[str, Any]] = {
    "elexon-bmrs": {
        "original": ELEXON_BASE + "/",
        "candidates": [
            {"candidate": "Chinese official/endorsed mirrors (TUNA, USTC, Aliyun, Huawei, ScienceDB, "
                          "NMDC)", "result": "software/scientific mirrors only; no GB market data"},
            {"candidate": "web search 2026-11-25 'Elexon BMRS ERCOT ENTSO-E 电力市场数据 国内镜像'",
             "result": "only the official API and third-party tools (MCP servers, entsoe-py); "
                       "no equivalent mirror"},
        ],
    },
    "open-electricity": {
        "original": OE_BASE + "/",
        "candidates": [
            {"candidate": "Chinese mirrors (TUNA, USTC, ScienceDB)", "result": "none host NEM data"},
            {"candidate": "AEMO NEMWEB (already ingested by the line)",
             "result": "the upstream raw source, not a mirror of the Open Electricity product"},
        ],
    },
    "nasa-power": {
        "original": NASA_POWER_BASE,
        "candidates": [
            {"candidate": "Chinese mirrors (TUNA, USTC, NMDC, National Meteorological Information Center)",
             "result": "no NASA POWER mirror; point API answers are computed on demand"},
        ],
    },
    "ercot-mis": {
        "original": "https://www.ercot.com/misapp/GetReports.do",
        "candidates": [
            {"candidate": "Chinese mirrors / web search 2026-11-25",
             "result": "no equivalent mirror of ERCOT MIS reports"},
        ],
    },
}


# --------------------------------------------------------------------------- dates


def parse_day(text: str) -> date:
    return date.fromisoformat(text)


def settlement_periods(day: date) -> int:
    """GB settlement periods in a settlement day: 48, 46 (spring forward) or 50 (fall back)."""

    start = datetime(day.year, day.month, day.day, tzinfo=LONDON)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=LONDON)
    hours = (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 3600
    return int(round(hours * 2))


def days(start: date, end: date) -> list[date]:
    if end < start:
        raise od.OpenDataError("end before start")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# --------------------------------------------------------------------------- URL builders


def elexon_url(dataset: str, day: date, sp: int | None = None) -> str:
    spec = ELEXON_DATASETS.get(dataset)
    if spec is None:
        raise od.OpenDataError(f"unknown Elexon dataset {dataset}; one of {sorted(ELEXON_DATASETS)}")
    if spec["per"] == "sp":
        if sp is None or not 1 <= sp <= settlement_periods(day):
            raise od.OpenDataError(f"{dataset} needs a settlement period 1..{settlement_periods(day)}")
    path = spec["path"].format(date=day.isoformat(), next=(day + timedelta(days=1)).isoformat(),
                               sp=sp)
    url = ELEXON_BASE + path
    return od.public_url(url + ("&" if "?" in url else "?") + "format=json")


def elexon_requests(dataset: str, day: date) -> list[tuple[str, str]]:
    """``(url, file name)`` of every request that covers one settlement day."""

    spec = ELEXON_DATASETS[dataset]
    if spec["per"] == "day":
        return [(elexon_url(dataset, day), f"{dataset}_{day.isoformat()}.json")]
    return [(elexon_url(dataset, day, sp), f"{dataset}_{day.isoformat()}_sp{sp:02d}.json")
            for sp in range(1, settlement_periods(day) + 1)]


OE_MAX_RANGE_DAYS = {"5m": 8, "30m": 16, "1h": 32, "1d": 366}


def oe_market_url(day_from: date, day_to: date, *, metrics: Iterable[str] = ("price", "demand"),
                  interval: str = "5m", network: str = "NEM") -> str:
    """Open Electricity ``/market/network/{network}`` grouped by region (no key)."""

    span = (day_to - day_from).days
    limit = OE_MAX_RANGE_DAYS.get(interval)
    if limit is None:
        raise od.OpenDataError(f"interval {interval} not supported here")
    if span < 1 or span > limit:
        raise od.OpenDataError(f"{interval} range must be 1..{limit} days (got {span})")
    params = [("metrics", m) for m in metrics] + [
        ("interval", interval), ("date_start", f"{day_from.isoformat()}T00:00:00"),
        ("date_end", f"{day_to.isoformat()}T00:00:00"), ("primary_grouping", "network_region")]
    return od.public_url(f"{OE_BASE}/market/network/{network}?" + urllib.parse.urlencode(params))


def oe_community_window_ok(day_from: date, today: date | None = None) -> bool:
    """Anonymous (Community) requests reach back two years only."""

    today = today or date.today()
    return day_from >= today - timedelta(days=730)


NASA_PARAMETERS = ("ALLSKY_SFC_SW_DWN", "T2M", "WS10M")


def nasa_power_url(lat: float, lon: float, start: date, end: date,
                   parameters: Iterable[str] = NASA_PARAMETERS) -> str:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise od.OpenDataError("latitude/longitude out of range")
    if (end - start).days > 366:
        raise od.OpenDataError("keep NASA POWER point requests to <= 1 year")
    params = {"parameters": ",".join(parameters), "community": "RE",
              "longitude": f"{lon:.2f}", "latitude": f"{lat:.2f}",
              "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
              "format": "CSV", "time-standard": "UTC"}
    return od.public_url(NASA_POWER_BASE + "?" + urllib.parse.urlencode(params, safe=","))


def ercot_doclist_url(report: str) -> str:
    rtid = ERCOT_REPORTS[report]["reportTypeId"] if report in ERCOT_REPORTS else int(report)
    return od.public_url(f"{ERCOT_DOCLIST}?reportTypeId={int(rtid)}")


def ercot_download_url(doc_id: int | str) -> str:
    return od.public_url(f"{ERCOT_DOWNLOAD}?doclookupId={int(doc_id)}")


# --------------------------------------------------------------------------- verifiers


def _rows(obj: Any) -> list[Mapping[str, Any]]:
    rows = obj.get("data") if isinstance(obj, Mapping) else obj
    if not isinstance(rows, list):
        raise od.OpenDataError("expected a JSON list or {'data': [...]}")
    return rows


def verify_system_prices(obj: Any, day: date) -> str:
    rows = _rows(obj)
    want = settlement_periods(day)
    periods = sorted(int(r["settlementPeriod"]) for r in rows)
    if periods != list(range(1, want + 1)):
        raise od.OpenDataError(f"system prices: periods {periods[:3]}.. ({len(periods)}), want 1..{want}")
    for row in rows:
        if row.get("settlementDate") != day.isoformat():
            raise od.OpenDataError("system prices: wrong settlementDate")
        for key in ("systemSellPrice", "systemBuyPrice", "netImbalanceVolume"):
            if not isinstance(row.get(key), (int, float)):
                raise od.OpenDataError(f"system prices: {key} missing in period {row.get('settlementPeriod')}")
    ssp = [float(r["systemSellPrice"]) for r in rows]
    single = sum(1 for r in rows if r["systemSellPrice"] == r["systemBuyPrice"])
    return (f"{len(rows)} settlement periods 1..{want} on {day}; systemSellPrice "
            f"{min(ssp):.2f}..{max(ssp):.2f} GBP/MWh; SSP==SBP in {single}/{len(rows)} (single price)")


def verify_fuelhh(obj: Any, day: date) -> str:
    rows = _rows(obj)
    want = settlement_periods(day)
    fuels = sorted({r["fuelType"] for r in rows})
    by_sp: dict[int, int] = {}
    for row in rows:
        if row.get("dataset") != "FUELHH" or row.get("settlementDate") != day.isoformat():
            raise od.OpenDataError("FUELHH: wrong dataset or settlementDate")
        if not isinstance(row.get("generation"), (int, float)):
            raise od.OpenDataError("FUELHH: generation missing")
        by_sp[int(row["settlementPeriod"])] = by_sp.get(int(row["settlementPeriod"]), 0) + 1
    if sorted(by_sp) != list(range(1, want + 1)) or set(by_sp.values()) != {len(fuels)}:
        raise od.OpenDataError(f"FUELHH: incomplete grid ({len(by_sp)} periods x {len(fuels)} fuels)")
    total = sum(float(r["generation"]) for r in rows) / 2 / 1000
    return (f"{len(rows)} rows = {want} periods x {len(fuels)} fuel types ({', '.join(fuels)}); "
            f"fields dataset/settlementPeriod/fuelType/generation[MW]; day total ~{total:.0f} GWh")


def verify_boalf(obj: Any, day: date, sp: int) -> str:
    rows = _rows(obj)
    if not rows:
        raise od.OpenDataError("acceptances: empty answer")
    for row in rows:
        for key in ("bmUnit", "acceptanceNumber", "acceptanceTime", "levelFrom", "levelTo",
                    "timeFrom", "timeTo", "soFlag"):
            if key not in row:
                raise od.OpenDataError(f"acceptances: {key} missing")
        if row.get("settlementDate") != day.isoformat():
            raise od.OpenDataError("acceptances: wrong settlementDate")
    units = {r["bmUnit"] for r in rows}
    so = sum(1 for r in rows if r.get("soFlag"))
    return (f"{len(rows)} acceptance rows for SP{sp} on {day}, {len(units)} BM units, "
            f"{so} with soFlag; fields bmUnit/acceptanceNumber/"
            "acceptanceTime/levelFrom/levelTo/soFlag/storFlag/rrFlag")


def verify_oe_market(obj: Any, metrics: Iterable[str], regions: Iterable[str], points: int) -> str:
    if not isinstance(obj, Mapping) or obj.get("success") is not True:
        raise od.OpenDataError("Open Electricity: success != true")
    got: dict[str, dict[str, int]] = {}
    for block in obj.get("data") or []:
        for result in block.get("results") or []:
            region = (result.get("columns") or {}).get("region")
            got.setdefault(block["metric"], {})[region] = len(result.get("data") or [])
            for item in result.get("data") or []:
                if not (isinstance(item, list) and len(item) == 2):
                    raise od.OpenDataError("Open Electricity: data points are [time, value]")
    for metric in metrics:
        for region in regions:
            if got.get(metric, {}).get(region) != points:
                raise od.OpenDataError(f"Open Electricity: {metric}/{region} has "
                                       f"{got.get(metric, {}).get(region)} points, want {points}")
    return (f"metrics {sorted(got)} x regions {sorted(regions)}, {points} points each "
            f"(version {obj.get('version')})")


def verify_nasa_power_csv(text: str, start: date, end: date,
                          parameters: Iterable[str] = NASA_PARAMETERS) -> str:
    parameters = tuple(parameters)
    if "-END HEADER-" not in text:
        raise od.OpenDataError("NASA POWER: header block missing")
    body = text.split("-END HEADER-", 1)[1].strip()
    reader = csv.DictReader(io.StringIO(body))
    want_cols = ["YEAR", "MO", "DY", "HR", *parameters]
    if reader.fieldnames != want_cols:
        raise od.OpenDataError(f"NASA POWER: columns {reader.fieldnames}, want {want_cols}")
    rows = list(reader)
    want = ((end - start).days + 1) * 24
    if len(rows) != want:
        raise od.OpenDataError(f"NASA POWER: {len(rows)} rows, want {want}")
    missing = sum(1 for r in rows for p in parameters if float(r[p]) <= -999)
    ghi = [float(r[parameters[0]]) for r in rows] if parameters else []
    return (f"{len(rows)} hourly rows ({start}..{end} UTC), columns {','.join(want_cols)}; "
            f"{missing} missing (-999) values; {parameters[0]} max {max(ghi):.0f} Wh/m2")


def verify_ercot_doclist(obj: Any) -> str:
    docs = (obj.get("ListDocsByRptTypeRes") or {}).get("DocumentList") if isinstance(obj, Mapping) else None
    if not isinstance(docs, list) or not docs:
        raise od.OpenDataError("ERCOT: no ListDocsByRptTypeRes.DocumentList")
    first = docs[0].get("Document", {})
    for key in ("DocID", "FriendlyName", "PublishDate"):
        if key not in first:
            raise od.OpenDataError(f"ERCOT: document field {key} missing")
    return f"{len(docs)} documents listed; first {first.get('FriendlyName')} (DocID {first.get('DocID')})"


# --------------------------------------------------------------------------- sample bookkeeping


def _load_json_file(path: Path) -> Any:
    raw = path.read_bytes()
    if od.looks_like_html(raw):
        raise od.OpenDataError(f"{path}: HTML page instead of data (denial/maintenance page)")
    return json.loads(raw.decode("utf-8"))


def _channel(record: Mapping[str, Any]) -> str:
    route = record.get("route")
    return f"bridge-{route}" if route in {"direct", "proxy"} else "bridge"


def fetch_sample(source_id: str, url: str, name: str, verify: Callable[[Path], str], *,
                 task_bytes: int, direct_blocked: bool = False, runner: Any = None) -> dict[str, Any]:
    """One sample file through the bridge (kept if already completed), verified, logged."""

    out_dir = SAMPLES / source_id
    out = out_dir / name
    manifest = out_dir / "SAMPLES.json"
    log = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {"files": {}}
    entry = dict(log["files"].get(name) or {})
    if not out.is_file():
        record = od.submit(url, out, task_bytes=task_bytes, direct_blocked=direct_blocked,
                           runner=runner, timeout=240)
        if record.get("state") != "completed":
            raise od.OpenDataError(f"bridge job {record.get('id')} for {url}: state "
                                   f"{record.get('state')} {record.get('error') or ''}")
        entry = {"url": url, "fetched_at": od.utc_now(), "bridge_job": record.get("id"),
                 "channel": _channel(record), **od.route_record(record)}
    entry["check"] = verify(out)
    entry["bytes"] = out.stat().st_size
    entry["sha256"] = od.sha256_file(out)
    log["files"][name] = entry
    log["source_id"] = source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
    return entry


def record_selection(source_id: str, chosen: str, entries: Iterable[Mapping[str, Any]],
                     notes: str = "") -> None:
    facts = SELECTION_FACTS[source_id]
    routes = [od.route_record(e) for e in entries]
    od.write_selection(SAMPLES / source_id / "source_selection.json", source_id=source_id,
                       original=facts["original"], domestic_candidates=facts["candidates"],
                       chosen=chosen, route={"jobs": routes}, notes=notes)


# --------------------------------------------------------------------------- task-bytes runner


def with_task_bytes(task_bytes: int, runner: Any = None) -> Callable[..., Any]:
    """Wrap ``subprocess.run`` so bridge submits carry an honest ``--task-bytes`` estimate.

    ``od.Batch`` only knows publisher-verified ``expected_bytes``; Elexon/Open Electricity
    answers have no published size, and without a size the bridge parks direct-failed jobs in
    ``waiting_window``. The estimate here comes from the measured sizes in ``ELEXON_DATASETS``.
    """

    import subprocess

    base = runner or subprocess.run

    def run(command: list[str], *args: Any, **kwargs: Any) -> Any:
        if "--url" in command and "--task-bytes" not in command and "--status" not in command:
            command = [*command, "--task-bytes", str(int(task_bytes))]
        return base(command, *args, **kwargs)

    return run


# --------------------------------------------------------------------------- commands


def cmd_elexon_list(_: argparse.Namespace) -> int:
    print(f"Elexon Insights BMRS API {ELEXON_BASE}/  (no key; licence {ELEXON_LICENCE})")
    for name, spec in ELEXON_DATASETS.items():
        per_day = spec["bytes"] * (48 if spec["per"] == "sp" else 1)
        print(f"  {name:14s} per {spec['per']:3s} ~{spec['bytes'] / 1e3:8.0f} kB/request, "
              f"~{per_day / 1e6:7.2f} MB/day, ~{per_day * 365 / 1e9:6.2f} GB/year  {spec['what']}")
    return 0


def cmd_elexon_sample(args: argparse.Namespace) -> int:
    day = parse_day(args.date)
    sp = args.sp
    entries = []
    for dataset, verify in (("system-prices", lambda p: verify_system_prices(_load_json_file(p), day)),
                            ("fuelhh", lambda p: verify_fuelhh(_load_json_file(p), day))):
        url, name = elexon_requests(dataset, day)[0]
        entries.append(fetch_sample("elexon-bmrs", url, name, verify,
                                    task_bytes=ELEXON_DATASETS[dataset]["bytes"] * 2,
                                    direct_blocked=True))
    url = elexon_url("boalf", day, sp)
    entries.append(fetch_sample("elexon-bmrs", url, f"boalf_{day.isoformat()}_sp{sp:02d}.json",
                                lambda p: verify_boalf(_load_json_file(p), day, sp),
                                task_bytes=ELEXON_DATASETS["boalf"]["bytes"] * 2, direct_blocked=True))
    record_selection("elexon-bmrs", ELEXON_BASE + "/", entries,
                     notes="WSL direct gets HTTP 403 from data.elexon.co.uk; bridge proxy fallback "
                           "per job (fallback_reason recorded). Attribution: "
                           + ELEXON_ATTRIBUTION.format(year=day.year))
    for entry in entries:
        print(json.dumps(entry, ensure_ascii=False))
    return 0


def cmd_elexon_fetch(args: argparse.Namespace) -> int:
    span = days(parse_day(args.start), parse_day(args.end))
    spec = ELEXON_DATASETS[args.dataset]
    out_dir = Path(args.out) if args.out else LINE_DIR / "data" / "elexon" / args.dataset
    batch = od.Batch(out_dir / "BATCH.json", route="auto", direct_blocked=True)
    for day in span:
        for url, name in elexon_requests(args.dataset, day):
            batch.add(url, str(out_dir / day.strftime("%Y") / name))
    estimate = spec["bytes"] * len(batch.items)
    # Elexon direct is HTTP 403 from WSL: the batch is proxy-bound, so the window rule applies.
    od.check_window(route="auto", direct_blocked=True, batch_bytes=estimate)
    if args.dry_run:
        print(json.dumps({"requests": len(batch.items), "estimated_bytes": estimate,
                          "large": od.is_large(batch_bytes=estimate)}))
        return 0
    counts = batch.run(limit=args.limit, wait=args.wait,
                       runner=with_task_bytes(spec["bytes"] * 2))
    print(json.dumps({"estimated_bytes": estimate, **counts}))
    return 0


def cmd_ercot_probe(args: argparse.Namespace) -> int:
    url = ercot_doclist_url(args.report)
    try:
        body = od.query(url, timeout=60, max_bytes=2_000_000)
    except Exception as exc:  # noqa: BLE001 - report every failure mode as evidence
        print(json.dumps({"url": url, "channel": "query-proxy", "ok": False, "error": str(exc)[:300]}))
        return 2
    if od.looks_like_html(body):
        print(json.dumps({"url": url, "channel": "query-proxy", "ok": False,
                          "error": "HTML answer (Incapsula challenge/denial)"}))
        return 2
    print(json.dumps({"url": url, "channel": "query-proxy", "ok": True,
                      "check": verify_ercot_doclist(json.loads(body))}))
    return 0


def cmd_ercot_sample(args: argparse.Namespace) -> int:
    if cmd_ercot_probe(args) != 0:
        print("ERCOT anonymous MIS route is blocked (HTTP 403); not submitting bridge jobs. "
              "The Public API (api.ercot.com) needs a subscription key - see REGISTER-LIST.md.")
        return 2
    url = ercot_doclist_url(args.report)
    entry = fetch_sample("ercot-mis", url, f"doclist_{args.report}.json",
                         lambda p: verify_ercot_doclist(_load_json_file(p)), task_bytes=500_000)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


def cmd_oe_list(_: argparse.Namespace) -> int:
    print(f"Open Electricity API {OE_BASE}  (no key = Community: last 2 years; CC BY-NC 4.0)")
    for interval, limit in OE_MAX_RANGE_DAYS.items():
        print(f"  /market/network/NEM interval={interval}: <= {limit} days per request")
    print("  /data/network/NEM?metrics=energy|power|emissions|market_value (fueltech groupings)")
    print("  Academic plan (account) for full history from 1999; Enterprise for commercial use")
    return 0


def cmd_oe_sample(args: argparse.Namespace) -> int:
    day = parse_day(args.date)
    url = oe_market_url(day, day + timedelta(days=1))
    regions = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
    entry = fetch_sample("open-electricity", url, f"market_NEM_price_demand_{day.isoformat()}.json",
                         lambda p: verify_oe_market(_load_json_file(p), ("price", "demand"),
                                                    regions, 288), task_bytes=300_000)
    record_selection("open-electricity", OE_BASE + "/market/network/NEM", [entry],
                     notes="No API key: 'Anonymous requests are treated as Community' "
                           "(docs api-reference/data-limits, read 2026-11-25). " + OE_ATTRIBUTION)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


def cmd_oe_fetch(args: argparse.Namespace) -> int:
    start, end = parse_day(args.start), parse_day(args.end)
    if not oe_community_window_ok(start):
        raise od.OpenDataError("anonymous (Community) access reaches back 2 years only")
    out_dir = Path(args.out) if args.out else LINE_DIR / "data" / "openelectricity" / "market_5m"
    batch = od.Batch(out_dir / "BATCH.json", route="auto")
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=OE_MAX_RANGE_DAYS["5m"]), end + timedelta(days=1))
        batch.add(oe_market_url(cursor, stop), str(out_dir / f"NEM_{cursor}_{stop}.json"))
        cursor = stop
    counts = batch.run(limit=args.limit, wait=args.wait, runner=with_task_bytes(1_000_000))
    print(json.dumps(counts))
    return 0


def cmd_nasa_sample(args: argparse.Namespace) -> int:
    start, end = parse_day(args.start), parse_day(args.end)
    url = nasa_power_url(args.lat, args.lon, start, end)
    name = args.name or f"point_{args.lat:.2f}_{args.lon:.2f}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    entry = fetch_sample("nasa-power", url, name,
                         lambda p: verify_nasa_power_csv(p.read_text(encoding="utf-8"), start, end),
                         task_bytes=200_000)
    record_selection("nasa-power", NASA_POWER_BASE, [entry])
    print(json.dumps(entry, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="source", required=True)

    el = sub.add_parser("elexon").add_subparsers(dest="action", required=True)
    el.add_parser("list").set_defaults(func=cmd_elexon_list)
    s = el.add_parser("sample")
    s.add_argument("--date", default="2025-11-01")
    s.add_argument("--sp", type=int, default=20)
    s.set_defaults(func=cmd_elexon_sample)
    f = el.add_parser("fetch")
    f.add_argument("--dataset", required=True, choices=sorted(ELEXON_DATASETS))
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--out")
    f.add_argument("--limit", type=int, default=None)
    f.add_argument("--wait", action="store_true")
    f.add_argument("--dry-run", action="store_true")
    f.set_defaults(func=cmd_elexon_fetch)

    er = sub.add_parser("ercot").add_subparsers(dest="action", required=True)
    for action, func in (("probe", cmd_ercot_probe), ("sample", cmd_ercot_sample)):
        p = er.add_parser(action)
        p.add_argument("--report", default="NP4-190-CD")
        p.set_defaults(func=func)

    oe = sub.add_parser("openelectricity").add_subparsers(dest="action", required=True)
    oe.add_parser("list").set_defaults(func=cmd_oe_list)
    s = oe.add_parser("sample")
    s.add_argument("--date", default="2026-11-01")
    s.set_defaults(func=cmd_oe_sample)
    f = oe.add_parser("fetch")
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--out")
    f.add_argument("--limit", type=int, default=None)
    f.add_argument("--wait", action="store_true")
    f.set_defaults(func=cmd_oe_fetch)

    na = sub.add_parser("nasapower").add_subparsers(dest="action", required=True)
    s = na.add_parser("sample")
    s.add_argument("--lat", type=float, default=-34.93)
    s.add_argument("--lon", type=float, default=138.60)
    s.add_argument("--start", default="2025-01-01")
    s.add_argument("--end", default="2025-01-31")
    s.add_argument("--name", default=None)
    s.set_defaults(func=cmd_nasa_sample)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except od.OpenDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
