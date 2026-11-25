#!/usr/bin/env python3
"""Free public data for the astronomy line ``astro-survey-photometry`` (data onboarding 2026-11-25).

One sub-command per source, each with ``list`` / ``sample`` / ``fetch`` (and ``query`` where the
source is a cone-search API)::

    astro_open_data.py ztf    query  --ra 298.0025 --dec 29.87147 --radius 1.4 --out FILE.csv
    astro_open_data.py ztf    sample
    astro_open_data.py ztf    fetch  --targets targets.csv --out-dir DIR --limit 20
    astro_open_data.py lamost list | query --ra .. --dec .. [--mrs] | sample | fetch --obsids .. --out-dir DIR
    astro_open_data.py tess-ffi list --sector 33 --camera 1 --ccd 1 [--day 360] | sample | fetch ..
    astro_open_data.py tess-ffi tesscut-url --ra .. --dec .. --sector 33 --size 20
    astro_open_data.py kepler list --kic 11244501 | sample | fetch --kic .. --quarters 3,4 --out-dir DIR
    astro_open_data.py kebc   query [--morph-min 0.7 --per 0.2..0.6 --kp-max 12] | sample
    astro_open_data.py asassn lookup --ra .. --dec .. | sample | fetch --uuid .. --out FILE.json

Network rules (``packages/open-data/open_data.py``): files go through the WSL download bridge
(``od.submit`` / ``od.Batch``, route ``auto``); small query APIs (ZTF light-curve API, LAMOST cone
search / SSAP, VizieR, the ASAS-SN light-curve JSON, S3/HTTP directory listings) are read with
``od.query`` through the environment proxy with a byte cap. Large batches (>= 200 MB file or
>= 1 GB batch) that may use the proxy are refused outside Beijing 02:00-14:00.

The ZTF light-curve API is never sent through the bridge: on 2026-11-25 the bridge's direct route
timed out on it and then parked the job as an unknown-size proxy download.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "open-data"))
import open_data as od  # noqa: E402

LINE = "astro-survey-photometry"
LINE_DIR = Path("/workspace/openlabs/build/lines") / LINE
SAMPLES = LINE_DIR / "data" / "open-samples"

# --------------------------------------------------------------------------- ZTF (IRSA)

ZTF_LC_API = "https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves"
ZTF_RELEASE = "DR24"
ZTF_REQUIRED = ("oid", "hjd", "mjd", "mag", "magerr", "catflags", "filtercode")
ZTF_BANDS = ("zg", "zr", "zi")
ZTF_SAMPLE = {"ra": 298.0025, "dec": 29.87147, "radius_arcsec": 1.4}
ZTF_CITATION = ("Masci et al. 2019, PASP 131, 018003 (doi:10.1088/1538-3873/aae8ac); "
                "Bellm et al. 2019, PASP 131, 018002 (doi:10.1088/1538-3873/aaecbe)")


def ztf_url(ra: float, dec: float, radius_arcsec: float = 1.5, *, bad_catflags_mask: int | None = 32768,
            bands: Iterable[str] | None = None, fmt: str = "csv", mjd_range: tuple[float, float] | None = None) -> str:
    """IRSA ZTF light-curve API URL for a cone (radius in arcsec; the API wants degrees)."""

    if not (0 <= ra < 360 and -90 <= dec <= 90):
        raise ValueError("ra/dec out of range")
    if not 0 < radius_arcsec <= 600:
        raise ValueError("radius must be in (0, 600] arcsec")
    params: dict[str, str] = {"POS": f"CIRCLE {ra:.6f} {dec:.6f} {radius_arcsec / 3600.0:.6f}"}
    if bands:
        params["BANDNAME"] = ",".join(b.lstrip("z") for b in bands)
    if bad_catflags_mask is not None:
        params["BAD_CATFLAGS_MASK"] = str(int(bad_catflags_mask))
    if mjd_range:
        params["TIME"] = f"{mjd_range[0]} {mjd_range[1]}"
    params["FORMAT"] = fmt
    return ZTF_LC_API + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def parse_ztf_csv(text: str) -> dict[str, Any]:
    """Verify a ZTF light-curve CSV answer: required columns, rows per band, oids, time range."""

    if od.looks_like_html(text):
        raise od.OpenDataError("ZTF answer is an HTML page, not CSV")
    reader = csv.DictReader(io.StringIO(text))
    columns = list(reader.fieldnames or [])
    missing = [c for c in ZTF_REQUIRED if c not in columns]
    if missing:
        raise od.OpenDataError(f"ZTF CSV lacks columns {missing}")
    per_band: dict[str, int] = {}
    oids: dict[str, str] = {}
    flagged = 0
    mjd_min, mjd_max = float("inf"), float("-inf")
    rows = 0
    for row in reader:
        rows += 1
        band = row["filtercode"]
        per_band[band] = per_band.get(band, 0) + 1
        oids[row["oid"]] = band
        if row["catflags"] not in ("0", ""):
            flagged += 1
        mjd = float(row["mjd"])
        mjd_min, mjd_max = min(mjd_min, mjd), max(mjd_max, mjd)
    unknown = sorted(set(per_band) - set(ZTF_BANDS))
    if unknown:
        raise od.OpenDataError(f"unexpected filtercode values {unknown}")
    return {"columns": columns, "rows": rows, "rows_per_band": per_band,
            "oids": {band: sorted(o for o, b in oids.items() if b == band) for band in per_band},
            "catflags_nonzero": flagged,
            "mjd_range": [mjd_min, mjd_max] if rows else None}


def ztf_query(ra: float, dec: float, radius_arcsec: float, *, timeout: float = 240,
              max_bytes: int = 20 * 1024 * 1024, **kwargs: Any) -> tuple[str, bytes]:
    url = ztf_url(ra, dec, radius_arcsec, **kwargs)
    return url, od.query(url, timeout=timeout, max_bytes=max_bytes)


# --------------------------------------------------------------------------- LAMOST (NAOC)

LAMOST_BASE = "https://www.lamost.org"
LAMOST_DEFAULT = ("dr12", "v2.0")   # global public release 2026-09-11; DR13 needs China-VO login
LAMOST_PUBLIC = {("dr10", "v2.0"), ("dr11", "v2.0"), ("dr12", "v2.0")}
VOT = "{http://www.ivoa.net/xml/VOTable/v1.3}"


def lamost_cone_url(ra: float, dec: float, sr_deg: float, *, dr: str = "dr12", version: str = "v2.0",
                    mrs: bool = False) -> str:
    if not 0 < sr_deg <= 1:
        raise ValueError("cone radius must be in (0, 1] deg")
    service = "medvoservice" if mrs else "voservice"
    return (f"{LAMOST_BASE}/{dr}/{version}/{service}/conesearch?"
            + urllib.parse.urlencode({"RA": f"{ra:.6f}", "DEC": f"{dec:.6f}", "SR": f"{sr_deg:g}"}))


def lamost_ssap_url(ra: float, dec: float, size_deg: float, *, dr: str = "dr12", version: str = "v2.0",
                    mrs: bool = False, maxrec: int | None = None) -> str:
    service = "medvoservice" if mrs else "voservice"
    params = {"REQUEST": "queryData", "POS": f"{ra:.6f},{dec:.6f}", "SIZE": f"{size_deg:g}"}
    if maxrec:
        params["MAXREC"] = str(int(maxrec))
    return f"{LAMOST_BASE}/{dr}/{version}/{service}/ssap?" + urllib.parse.urlencode(params)


def lamost_spectrum_url(obsid: int | str, *, dr: str = "dr12", version: str = "v2.0", mrs: bool = False) -> str:
    """Anonymous FITS URL of one public spectrum (SSAP gives the same path with an empty token)."""

    if not str(obsid).isdigit():
        raise ValueError("obsid must be an integer")
    kind = "medspectrum" if mrs else "spectrum"
    return f"{LAMOST_BASE}/{dr}/{version}/{kind}/fits/{int(obsid)}"


def parse_votable(body: bytes | str) -> tuple[list[str], list[dict[str, str | None]], dict[str, str]]:
    """Fields, rows and INFO values of a (single-table, TABLEDATA) VOTable."""

    if od.looks_like_html(body):
        raise od.OpenDataError("VOTable answer is an HTML page")
    root = ET.fromstring(body if isinstance(body, bytes) else body.encode("utf-8"))
    ns = VOT if root.tag.startswith(VOT) else ""
    fields = [f.get("name") or "" for f in root.iter(ns + "FIELD")]
    rows = [dict(zip(fields, [td.text for td in tr.findall(ns + "TD")])) for tr in root.iter(ns + "TR")]
    info = {i.get("name") or "": i.get("value") or "" for i in root.iter(ns + "INFO")}
    return fields, rows, info


# --------------------------------------------------------------------------- TESS FFI (MAST / AWS)

STPUBDATA = "s3://stpubdata"
TESS_FFI_PREFIX = "tess/public/ffi"
MAST_TESS_FFI = "https://archive.stsci.edu/missions/tess/ffi"
TESSCUT_API = "https://mast.stsci.edu/tesscut/api/v0.1/astrocut"
FFI_NAME = re.compile(r"tess(?P<stamp>\d{13})-s(?P<sector>\d{4})-(?P<camera>[1-4])-(?P<ccd>[1-4])-"
                      r"(?P<scid>\d{4})-s_(?P<kind>ffic|ffir)\.fits$")
# Cadence of the FFIs: 1800 s (S1-26), 600 s (S27-55), 200 s (S56 on).


def ffi_cadence_s(sector: int) -> int:
    return 1800 if sector <= 26 else (600 if sector <= 55 else 200)


def ffi_prefix(sector: int, year: int | None = None, day: int | None = None,
               camera: int | None = None, ccd: int | None = None) -> str:
    """Bucket key prefix ``tess/public/ffi/s0033/2020/360/1-1/`` (as deep as the arguments go)."""

    parts = [TESS_FFI_PREFIX, f"s{int(sector):04d}"]
    if year is not None:
        parts.append(f"{int(year):04d}")
        if day is not None:
            parts.append(f"{int(day):03d}")
            if camera is not None and ccd is not None:
                if not (1 <= camera <= 4 and 1 <= ccd <= 4):
                    raise ValueError("camera and ccd are 1..4")
                parts.append(f"{camera}-{ccd}")
    return "/".join(parts) + "/"


def ffi_https(key: str) -> str:
    return od.s3_https(f"{STPUBDATA}/{key}")


def ffi_mast_url(key: str) -> str:
    if not key.startswith(TESS_FFI_PREFIX + "/"):
        raise ValueError("not a TESS FFI key")
    return MAST_TESS_FFI + "/" + key[len(TESS_FFI_PREFIX) + 1:]


def sector_script_url(sector: int, kind: str = "ffic") -> str:
    return f"https://archive.stsci.edu/missions/tess/download_scripts/sector/tesscurl_sector_{int(sector)}_{kind}.sh"


def tesscut_url(ra: float, dec: float, *, size: int = 20, sector: int | None = None) -> str:
    if not 1 <= size <= 100:
        raise ValueError("cutout size 1..100 pixels")
    params = {"ra": f"{ra:.6f}", "dec": f"{dec:.6f}", "y": str(size), "x": str(size)}
    if sector is not None:
        params["sector"] = str(int(sector))
    return TESSCUT_API + "?" + urllib.parse.urlencode(params)


def s3_list_url(bucket_https: str, prefix: str, *, delimiter: str | None = None, max_keys: int = 1000,
                token: str | None = None) -> str:
    params = {"list-type": "2", "prefix": prefix, "max-keys": str(int(max_keys))}
    if delimiter:
        params["delimiter"] = delimiter
    if token:
        params["start-after"] = token
    return bucket_https.rstrip("/") + "/?" + urllib.parse.urlencode(params)


def parse_s3_listing(body: bytes | str) -> dict[str, Any]:
    root = ET.fromstring(body if isinstance(body, bytes) else body.encode("utf-8"))
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    keys = [{"key": c.findtext(ns + "Key"), "bytes": int(c.findtext(ns + "Size") or 0),
             "etag": (c.findtext(ns + "ETag") or "").strip('"')} for c in root.findall(ns + "Contents")]
    prefixes = [p.findtext(ns + "Prefix") for p in root.findall(ns + "CommonPrefixes")]
    return {"keys": keys, "prefixes": prefixes,
            "truncated": (root.findtext(ns + "IsTruncated") or "false") == "true"}


def s3_list(prefix: str, *, delimiter: str | None = None, max_keys: int = 1000) -> dict[str, Any]:
    base = od.s3_https(STPUBDATA + "/")
    return parse_s3_listing(od.query(s3_list_url(base, prefix, delimiter=delimiter, max_keys=max_keys),
                                     max_bytes=2 * 1024 * 1024, timeout=120))


# --------------------------------------------------------------------------- Kepler / K2 (MAST)

KEPLER_LC = "https://archive.stsci.edu/missions/kepler/lightcurves"
K2_LC = "https://archive.stsci.edu/missions/k2/lightcurves"
# Long-cadence file timestamps per quarter (identical for every target; read from the MAST listing).
KEPLER_LC_QUARTERS = {
    0: "2009131105131", 1: "2009166043257", 2: "2009259160929", 3: "2009350155506",
    4: "2010078095331", 5: "2010174085026", 6: "2010265121752", 7: "2010355172524",
    8: "2011073133259", 9: "2011177032512", 10: "2011271113734", 11: "2012004120508",
    12: "2012088054726", 13: "2012179063303", 14: "2012277125453", 15: "2013011073258",
    16: "2013098041711", 17: "2013131215648"}
KEPLER_COLUMNS = ("TIME", "SAP_FLUX", "PDCSAP_FLUX")


def kepler_dir_url(kic: int) -> str:
    kic9 = f"{int(kic):09d}"
    return f"{KEPLER_LC}/{kic9[:4]}/{kic9}/"


def kepler_lc_url(kic: int, quarter: int, cadence: str = "llc", stamp: str | None = None) -> str:
    if cadence not in ("llc", "slc"):
        raise ValueError("cadence llc or slc")
    if stamp is None:
        if cadence != "llc":
            raise ValueError("short-cadence timestamps differ per month: pass stamp= from the listing")
        stamp = KEPLER_LC_QUARTERS[int(quarter)]
    return f"{kepler_dir_url(kic)}kplr{int(kic):09d}-{stamp}_{cadence}.fits"


def k2_lc_url(epic: int, campaign: int) -> str:
    epic9 = f"{int(epic):09d}"
    return f"{K2_LC}/c{int(campaign)}/{epic9[:4]}00000/{epic9[4:6]}000/ktwo{epic9}-c{int(campaign):02d}_llc.fits"


def parse_dir_listing(html_text: str, pattern: str = r"\.fits$") -> list[str]:
    names = re.findall(r'href="([^"?/][^"]*)"', html_text)
    return sorted({n for n in names if re.search(pattern, n)})


# --------------------------------------------------------------------------- KEBC (Villanova / VizieR)

VIZIER = {"cfa": "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv",
          "china-vo": "http://vizier.china-vo.org/viz-bin/asu-tsv",
          "cds": "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"}
KEBC_TABLE = "J/AJ/151/68/catalog"     # Kirk+2016 third revision, 2878 EBs
KEBC_DR2_TABLE = "J/AJ/142/160/table3"  # Slawson+2011 (DR2), named in the survey
KEBC_COLUMNS = "KIC,Per,e_Per,BJD0,Morph,Kpmag,Teff,SC,_RA,_DE"


def kebc_url(*, mirror: str = "cfa", table: str = KEBC_TABLE, morph_min: float | None = None,
             per: str | None = None, kp_max: float | None = None, max_rows: int = 5000,
             columns: str = KEBC_COLUMNS) -> str:
    params = {"-source": table, "-out": columns, "-out.max": str(int(max_rows))}
    if morph_min is not None:
        params["Morph"] = f">={morph_min:g}"
    if per:
        params["Per"] = per
    if kp_max is not None:
        params["Kpmag"] = f"<{kp_max:g}"
    return VIZIER[mirror] + "?" + urllib.parse.urlencode(params)


def parse_vizier_tsv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """ASU-TSV: comment lines '#', then header, units, dashes, rows (first table only)."""

    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if not lines:
        return [], []
    header = lines[0].split("\t")
    rows = []
    for ln in lines[3:]:
        if ln.startswith("-") or not ln.strip():
            continue
        cells = ln.split("\t")
        if len(cells) != len(header):
            break  # next table
        rows.append({h: c.strip() for h, c in zip(header, cells)})
    return header, rows


# --------------------------------------------------------------------------- ASAS-SN (OSU)

ASASSN = "https://asas-sn.osu.edu"
ASASSN_FIELDS = ("hjd", "camera", "mag", "mag_err", "flux", "flux_err")
UUID_RE = re.compile(r"/variables/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
ASASSN_SAMPLE = {"uuid": "9e5a0679-7375-5753-b1b5-abed53bce682", "name": "ASASSN-V J060010.92-154944.5",
                 "tic": 318015356, "ra": 90.045663, "dec": -15.829143}


def asassn_lookup_url(ra: float, dec: float, radius_arcmin: float = 0.5) -> str:
    return f"{ASASSN}/variables?" + urllib.parse.urlencode({"ra": f"{ra:.6f}", "dec": f"{dec:.6f}",
                                                             "radius": f"{radius_arcmin:g}"})


def asassn_lc_url(uuid: str) -> str:
    if not re.fullmatch(r"[0-9a-f-]{36}", uuid):
        raise ValueError("ASAS-SN variable uuid expected")
    return f"{ASASSN}/variables/{uuid}.json"


def parse_asassn_lookup(html_text: str) -> list[str]:
    seen: list[str] = []
    for uuid in UUID_RE.findall(html_text):
        if uuid not in seen:
            seen.append(uuid)
    return seen


def parse_asassn_json(body: bytes | str) -> dict[str, Any]:
    data = json.loads(body)
    results = data.get("results")
    if not isinstance(results, list):
        raise od.OpenDataError("ASAS-SN JSON lacks results")
    if data.get("count") != len(results):
        raise od.OpenDataError(f"ASAS-SN JSON count {data.get('count')} != {len(results)} rows (paged?)")
    missing = [f for f in ASASSN_FIELDS if results and f not in results[0]]
    if missing:
        raise od.OpenDataError(f"ASAS-SN rows lack {missing}")
    hjd = [r["hjd"] for r in results]
    return {"rows": len(results), "cameras": sorted({r["camera"] for r in results}),
            "hjd_range": [min(hjd), max(hjd)] if hjd else None}


# --------------------------------------------------------------------------- FITS header reader


def _cards(block: bytes) -> Iterable[tuple[str, str]]:
    for i in range(0, len(block), 80):
        card = block[i:i + 80].decode("ascii", "replace")
        yield card[:8].strip(), card[8:]


def _value(raw: str) -> Any:
    if not raw.startswith("= "):
        return None
    text = raw[2:]
    if text.strip().startswith("'"):
        m = re.match(r"\s*'((?:[^']|'')*)'", text)
        return m.group(1).replace("''", "'").rstrip() if m else text.strip()
    text = text.split("/")[0].strip()
    if text in ("T", "F"):
        return text == "T"
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def read_fits_headers(path: str | Path, max_hdus: int = 4) -> list[dict[str, Any]]:
    """Headers of the first HDUs of a (possibly gzipped) FITS file, pure python."""

    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if not raw.startswith(b"SIMPLE  ="):
        raise od.OpenDataError(f"{path}: not a FITS file")
    hdus: list[dict[str, Any]] = []
    pos = 0
    while pos < len(raw) and len(hdus) < max_hdus:
        header: dict[str, Any] = {}
        ended = False
        while pos + 2880 <= len(raw) and not ended:
            for key, rest in _cards(raw[pos:pos + 2880]):
                if key == "END":
                    ended = True
                    break
                if key and key not in header:
                    header[key] = _value(rest)
            pos += 2880
        if not ended:
            break
        hdus.append(header)
        naxis = int(header.get("NAXIS") or 0)
        size = 0
        if naxis:
            size = abs(int(header.get("BITPIX") or 8)) // 8
            for n in range(1, naxis + 1):
                size *= int(header.get(f"NAXIS{n}") or 0)
            size = (size + int(header.get("PCOUNT") or 0)) * int(header.get("GCOUNT") or 1)
        pos += -(-size // 2880) * 2880
    return hdus


def table_columns(header: Mapping[str, Any]) -> list[str]:
    return [str(header[f"TTYPE{i}"]) for i in range(1, int(header.get("TFIELDS") or 0) + 1)
            if f"TTYPE{i}" in header]


def check_kepler_fits(path: str | Path) -> dict[str, Any]:
    hdus = read_fits_headers(path, max_hdus=2)
    if len(hdus) < 2:
        raise od.OpenDataError("Kepler light curve lacks the LIGHTCURVE extension")
    cols = table_columns(hdus[1])
    missing = [c for c in KEPLER_COLUMNS if c not in cols]
    if missing:
        raise od.OpenDataError(f"Kepler light curve lacks {missing}")
    p, e = hdus[0], hdus[1]
    return {"OBJECT": p.get("OBJECT"), "KEPLERID": p.get("KEPLERID"), "QUARTER": p.get("QUARTER"),
            "MISSION": p.get("MISSION") or p.get("TELESCOP"), "DATA_REL": p.get("DATA_REL"),
            "EXTNAME": e.get("EXTNAME"), "rows": e.get("NAXIS2"), "columns": cols}


def check_ffi_fits(path: str | Path) -> dict[str, Any]:
    hdus = read_fits_headers(path, max_hdus=2)
    p = hdus[0]
    img = hdus[1] if len(hdus) > 1 else {}
    if not (p.get("SECTOR") and p.get("CAMERA") and p.get("CCD")):
        raise od.OpenDataError("FFI primary header lacks SECTOR/CAMERA/CCD")
    return {key: p.get(key) for key in ("TELESCOP", "SECTOR", "CAMERA", "CCD", "DATE-OBS", "DATE-END")} | {
        "image_extname": img.get("EXTNAME"), "NAXIS1": img.get("NAXIS1"), "NAXIS2": img.get("NAXIS2"),
        "BITPIX": img.get("BITPIX"), "has_wcs": "CTYPE1" in img}


def check_lamost_fits(path: str | Path) -> dict[str, Any]:
    hdus = read_fits_headers(path, max_hdus=3)
    p = hdus[0]
    if not p.get("OBSID") and "LAMOST" not in str(p.get("TELESCOP", "")):
        raise od.OpenDataError("not a LAMOST spectrum")
    out = {key: p.get(key) for key in ("TELESCOP", "OBSID", "DESIG", "OBJNAME", "RA", "DEC", "CLASS",
                                         "SUBCLASS", "Z", "SNRG", "DATA_V", "MJD")}
    out["extensions"] = [{"EXTNAME": h.get("EXTNAME"), "columns": table_columns(h), "rows": h.get("NAXIS2")}
                         for h in hdus[1:]]
    return out


# --------------------------------------------------------------------------- shared helpers


def _sample_dir(source_id: str) -> Path:
    path = SAMPLES / source_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _keep_answer(path: Path, body: bytes, url: str, seconds: float, check: Mapping[str, Any]) -> dict[str, Any]:
    # Query answers carry their own request timestamp, so a re-run simply replaces the answer.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    record = {"path": str(path), "bytes": len(body), "sha256": od.sha256_file(path), "url": url,
              "fetched_at": od.utc_now(), "channel": "query-proxy", "seconds": round(seconds, 1),
              "check": dict(check)}
    path.with_name(path.name + ".provenance.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def _bridge_sample(url: str, output: Path, check_fn: Any, *, expected_bytes: int | None = None,
                   task_bytes: int | None = None, timeout: int = 600, runner: Any = None) -> dict[str, Any]:
    if output.is_file():
        record = {"state": "completed", "note": "already on disk, not re-downloaded"}
    else:
        record = od.submit(url, output, expected_bytes=expected_bytes, task_bytes=task_bytes,
                           wait=True, timeout=min(timeout, 120), runner=runner)
        if record.get("state") in {"queued", "running"} and record.get("id"):
            record = od.wait_for(record["id"], timeout=timeout, runner=runner)
    out: dict[str, Any] = {"url": url, "bridge": od.route_record(record), "state": record.get("state")}
    if record.get("state") != "completed" or not output.is_file():
        out["error"] = record.get("error") or f"bridge state {record.get('state')}"
        return out
    head = output.read_bytes()[:512]
    if od.looks_like_html(head):
        raise od.OpenDataError(f"{output}: HTML page instead of data")
    out.update({"path": str(output), "bytes": output.stat().st_size, "sha256": od.sha256_file(output),
                "fetched_at": od.utc_now(), "check": check_fn(output)})
    return out


def guard_large(route: str, total_bytes: int, direct_blocked: bool = False, now: Any = None) -> None:
    """``auto`` may fall back to the proxy: treat a large auto batch as proxy-bound outside the window."""

    od.check_window(route=route, direct_blocked=direct_blocked, batch_bytes=total_bytes)
    if route == "auto" and od.is_large(batch_bytes=total_bytes) and not od.offpeak_open(now):
        raise od.OffPeakRequired(
            f"batch of {total_bytes} bytes with route auto may fall back to the proxy; run it Beijing "
            f"02:00-14:00 (next {od.next_offpeak_start(now).isoformat()}) or pass --route direct")


def run_batch(batch: Any, args: argparse.Namespace, runner: Any = None) -> dict[str, Any]:
    """Dry run unless ``--submit``: print what would be sent (count, bytes, first URLs)."""

    pending = [item for item in batch.items if not item.done_on_disk()]
    plan = {"manifest": str(batch.manifest), "files": len(batch.items), "pending": len(pending),
            "total_expected_bytes": batch.total_bytes(), "limit": args.limit, "route": batch.route,
            "first": [item.url for item in pending[:3]]}
    if not args.submit:
        plan["dry_run"] = "nothing submitted; add --submit (and usually --limit N) to send to the bridge"
        return plan
    if args.limit is None and len(pending) > 10:
        raise SystemExit(f"{len(pending)} files pending: pass --limit N to submit in slices")
    return {**plan, "result": batch.run(limit=args.limit, wait=args.wait, runner=runner)}


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False, default=str))


# --------------------------------------------------------------------------- domestic-mirror records

DOMESTIC = {
    "ztf-dr24-lc": [
        {"candidate": "NADC data browse (https://nadc.china-vo.org/data/)", "checked": "2026-11-25",
         "result": "lists LAMOST, BASS, Gaia DR1-DR3 source, Pan-STARRS, SkyMapper, WISE, SDSS; no ZTF"},
        {"candidate": "China-VO VizieR mirror (http://vizier.china-vo.org)", "checked": "2026-11-25",
         "result": "VizieR catalogues only (e.g. Chen+2020 J/ApJS/249/18); no ZTF light-curve service"}],
    "lamost-dr12": [
        {"candidate": "www.lamost.org (NAOC, operated with NADC/China-VO)", "checked": "2026-11-25",
         "result": "this is the domestic official source itself"}],
    "tess-ffi": [
        {"candidate": "NADC data browse", "checked": "2026-11-25", "result": "no TESS holdings"},
        {"candidate": "MAST archive.stsci.edu vs AWS stpubdata", "checked": "2026-11-25",
         "result": "two official copies (same files); no Chinese mirror found"}],
    "kepler-lc": [
        {"candidate": "NADC data browse", "checked": "2026-11-25", "result": "no Kepler/K2 holdings"}],
    "kebc": [
        {"candidate": "China-VO VizieR mirror", "checked": "2026-11-25",
         "result": "2026-11-25: timed out (lead, earlier), answered a 2-row J/AJ/142/160 probe in 23 s, then "
                   "reset the connection on the J/AJ/151/68 query; same CDS content but unreliable today. "
                   "Chosen: CfA mirror (1.3 s); --mirror china-vo kept as an option"}],
    "asassn-vsd": [
        {"candidate": "NADC data browse / China-VO VizieR", "checked": "2026-11-25",
         "result": "VizieR has the ASAS-SN variable catalogue (II/366) but no light curves; no mirror of asas-sn.osu.edu"}],
}


def _selection(source_id: str, original: str, chosen: str, route: Mapping[str, Any], notes: str = "") -> str:
    path = _sample_dir(source_id) / "source_selection.json"
    od.write_selection(path, source_id=source_id, original=original,
                       domestic_candidates=DOMESTIC.get(source_id, []), chosen=chosen, route=route, notes=notes)
    return str(path)


# --------------------------------------------------------------------------- commands: ZTF


def cmd_ztf(args: argparse.Namespace) -> int:
    if args.action == "list":
        _print({"api": ZTF_LC_API, "release": ZTF_RELEASE, "bands": ZTF_BANDS, "columns_required": ZTF_REQUIRED,
                "example": ztf_url(**ZTF_SAMPLE), "citation": ZTF_CITATION,
                "note": "one cone per call; answers ~0.5-1 MB per well-sampled star; read via od.query, not the bridge"})
        return 0
    if args.action in ("query", "sample"):
        ra, dec, radius = ((args.ra, args.dec, args.radius) if args.action == "query"
                           else (ZTF_SAMPLE["ra"], ZTF_SAMPLE["dec"], ZTF_SAMPLE["radius_arcsec"]))
        if ra is None or dec is None:
            raise SystemExit("--ra/--dec required")
        t0 = time.time()
        url, body = ztf_query(ra, dec, radius)
        summary = parse_ztf_csv(body.decode("utf-8"))
        summary.pop("columns")
        out = Path(args.out) if args.out else _sample_dir("ztf-dr24-lc") / "ztf_dr24_cone.csv"
        record = _keep_answer(out, body, url, time.time() - t0, summary)
        if args.action == "sample":
            record["selection"] = _selection("ztf-dr24-lc", ZTF_LC_API, ZTF_LC_API,
                                             {"route": "clash-query", "seconds": record["seconds"]},
                                             "small query API read through the Clash proxy (not the bridge)")
        _print(record)
        return 0
    if args.action == "fetch":
        targets = list(csv.DictReader(open(args.targets, encoding="utf-8")))
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        done = 0
        for row in targets:
            name = re.sub(r"[^A-Za-z0-9_.+-]", "_", row.get("name") or f"{row['ra']}_{row['dec']}")
            out = out_dir / f"{name}.ztf_dr24.csv"
            if out.is_file():
                continue
            if args.limit is not None and done >= args.limit:
                break
            t0 = time.time()
            url, body = ztf_query(float(row["ra"]), float(row["dec"]), float(row.get("radius") or args.radius))
            record = _keep_answer(out, body, url, time.time() - t0, parse_ztf_csv(body.decode("utf-8")))
            print(json.dumps({"target": name, "rows": record["check"]["rows"],
                              "per_band": record["check"]["rows_per_band"]}))
            done += 1
            time.sleep(args.pause)
        return 0
    raise SystemExit(f"unknown action {args.action}")


# --------------------------------------------------------------------------- commands: LAMOST


def cmd_lamost(args: argparse.Namespace) -> int:
    dr, ver = args.dr, args.version
    if (dr, ver) not in LAMOST_PUBLIC:
        raise SystemExit(f"{dr} {ver} is not a verified anonymous public release ({sorted(LAMOST_PUBLIC)}); "
                         "DR13 needs a China-VO real-name login")
    if args.action == "list":
        _print({"release": f"{dr} {ver}", "home": f"{LAMOST_BASE}/{dr}/{ver}/",
                "cone_lrs": lamost_cone_url(0, 0, 0.01, dr=dr, version=ver),
                "cone_mrs": lamost_cone_url(0, 0, 0.01, dr=dr, version=ver, mrs=True),
                "ssap_lrs": lamost_ssap_url(0, 0, 0.01, dr=dr, version=ver),
                "spectrum_lrs": lamost_spectrum_url(123, dr=dr, version=ver),
                "spectrum_mrs": lamost_spectrum_url(123, dr=dr, version=ver, mrs=True),
                "tap": f"{LAMOST_BASE}/{dr}/{ver}/voservice/tap",
                "catalogue_files": f"{LAMOST_BASE}/{dr}/{ver}/catalogue (whole-survey catalogues are large)",
                "openapi": "https://www.lamost.org/openapi/docs (token required: LAMOSTTokenAuth)"})
        return 0
    if args.action in ("query", "sample"):
        ra, dec, sr = ((args.ra, args.dec, args.radius / 3600.0) if args.action == "query"
                       else (290.67, 44.5, 0.05))
        mrs = bool(getattr(args, "mrs", False)) and args.action == "query"
        url = lamost_cone_url(ra, dec, sr, dr=dr, version=ver, mrs=mrs)
        t0 = time.time()
        body = od.query(url, max_bytes=10 * 1024 * 1024, timeout=120)
        fields, rows, info = parse_votable(body)
        if info.get("QUERY_STATUS") != "OK":
            raise od.OpenDataError(f"cone search status {info.get('QUERY_STATUS')}")
        check = {"fields": len(fields), "rows": len(rows), "query_status": info.get("QUERY_STATUS"),
                 "first": {k: rows[0].get(k) for k in ("obsid", "designation", "obsdate", "class", "subclass",
                                                        "snrg", "teff", "logg", "feh", "rv", "file")} if rows else None}
        sdir = _sample_dir("lamost-dr12")
        out = Path(args.out) if getattr(args, "out", None) else sdir / f"cone_{'mrs' if mrs else 'lrs'}_{dr}{ver}.xml"
        record = _keep_answer(out, body, url, time.time() - t0, check)
        if args.action == "sample" and rows:
            pick = max(rows, key=lambda r: float(r.get("snrg") or 0))
            spec_url = lamost_spectrum_url(pick["obsid"], dr=dr, version=ver)
            record["spectrum"] = _bridge_sample(spec_url, sdir / f"lamost_{dr}_{pick['obsid']}.fits",
                                                check_lamost_fits, task_bytes=1_000_000, timeout=args.timeout)
            record["selection"] = _selection(
                "lamost-dr12", f"{LAMOST_BASE}/{dr}/{ver}/", spec_url,
                {"cone": "clash-query", **record["spectrum"].get("bridge", {})},
                "anonymous: cone search, SSAP and spectrum FITS need no login for DR10-DR12 v2.0")
        _print(record)
        return 0
    if args.action == "fetch":
        obsids = [o.strip() for o in args.obsids.split(",") if o.strip()]
        batch = od.Batch(Path(args.out_dir) / "lamost_batch.json", route=args.route)
        for obsid in obsids:
            batch.add(lamost_spectrum_url(obsid, dr=dr, version=ver, mrs=args.mrs),
                      str(Path(args.out_dir) / f"lamost_{dr}_{'mrs' if args.mrs else 'lrs'}_{obsid}.fits"))
        guard_large(args.route, 400_000 * len(batch.items))
        _print(run_batch(batch, args))
        return 0
    raise SystemExit(f"unknown action {args.action}")


# --------------------------------------------------------------------------- commands: TESS FFI

FFI_SAMPLE_KEY = "tess/public/ffi/s0033/2020/360/1-1/tess2020360000910-s0033-1-1-0203-s_ffic.fits"
FFI_SAMPLE_BYTES = 35547840


def _ffi_keys(sector: int, camera: int, ccd: int, day: int | None, max_keys: int) -> list[dict[str, Any]]:
    years = [p.rstrip("/").split("/")[-1] for p in s3_list(ffi_prefix(sector), delimiter="/")["prefixes"]]
    keys: list[dict[str, Any]] = []
    for year in years:
        days = [p.rstrip("/").split("/")[-1] for p in
                s3_list(ffi_prefix(sector, int(year)), delimiter="/")["prefixes"]]
        for d in days:
            if day is not None and int(d) != day:
                continue
            listing = s3_list(ffi_prefix(sector, int(year), int(d), camera, ccd), max_keys=max_keys)
            keys += [k for k in listing["keys"] if k["key"].endswith("_ffic.fits")]
            if len(keys) >= max_keys:
                return keys[:max_keys]
    return keys


def cmd_tess_ffi(args: argparse.Namespace) -> int:
    if args.action == "list":
        keys = _ffi_keys(args.sector, args.camera, args.ccd, args.day, args.max_keys)
        per_file = keys[0]["bytes"] if keys else None
        cadence = ffi_cadence_s(args.sector)
        est = int(27.4 * 86400 / cadence) if per_file else None
        _print({"sector": args.sector, "camera": args.camera, "ccd": args.ccd, "listed": len(keys),
                "first": [{"key": k["key"], "bytes": k["bytes"], "https": ffi_https(k["key"]),
                           "mast": ffi_mast_url(k["key"])} for k in keys[:5]],
                "cadence_s": cadence, "ffic_bytes_each": per_file,
                "estimate_per_ccd_bytes": est * per_file if est else None,
                "estimate_sector_ffic_bytes": est * per_file * 16 if est else None,
                "sector_script": sector_script_url(args.sector),
                "note": "a full sector is TB scale: large, Beijing 02:00-14:00 only if proxy-bound; "
                        "single targets: use tesscut-url"})
        return 0
    if args.action == "tesscut-url":
        print(tesscut_url(args.ra, args.dec, size=args.size, sector=args.sector))
        return 0
    if args.action == "sample":
        out = _sample_dir("tess-ffi") / FFI_SAMPLE_KEY.rsplit("/", 1)[-1]
        url = ffi_https(FFI_SAMPLE_KEY)
        record = _bridge_sample(url, out, check_ffi_fits, expected_bytes=FFI_SAMPLE_BYTES,
                                task_bytes=FFI_SAMPLE_BYTES, timeout=args.timeout)
        record["selection"] = _selection("tess-ffi", ffi_mast_url(FFI_SAMPLE_KEY), url,
                                         record.get("bridge", {}),
                                         "AWS Open Data copy of the MAST FFI (no AWS account; HTTPS form of s3://)")
        _print(record)
        return 0
    if args.action == "fetch":
        keys = _ffi_keys(args.sector, args.camera, args.ccd, args.day, args.max_keys)
        batch = od.Batch(Path(args.out_dir) / f"ffi_s{args.sector:04d}_{args.camera}-{args.ccd}.json", route=args.route)
        for k in keys:
            batch.add(ffi_https(k["key"]), str(Path(args.out_dir) / k["key"].rsplit("/", 1)[-1]),
                      expected_bytes=k["bytes"])
        guard_large(args.route, batch.total_bytes())
        _print(run_batch(batch, args))
        return 0
    raise SystemExit(f"unknown action {args.action}")


# --------------------------------------------------------------------------- commands: Kepler

KEPLER_SAMPLE = {"kic": 11244501, "quarter": 3}


def cmd_kepler(args: argparse.Namespace) -> int:
    if args.action == "list":
        body = od.query(kepler_dir_url(args.kic), max_bytes=1024 * 1024)
        names = parse_dir_listing(body.decode("utf-8", "replace"), r"\.(fits|tar)$")
        _print({"kic": args.kic, "dir": kepler_dir_url(args.kic), "files": names,
                "k2_example": k2_lc_url(211400000, 5)})
        return 0
    if args.action == "sample":
        kic, q = KEPLER_SAMPLE["kic"], KEPLER_SAMPLE["quarter"]
        url = kepler_lc_url(kic, q)
        out = _sample_dir("kepler-lc") / url.rsplit("/", 1)[-1]
        record = _bridge_sample(url, out, check_kepler_fits, task_bytes=1_000_000, timeout=args.timeout)
        record["selection"] = _selection("kepler-lc", url, url, record.get("bridge", {}),
                                         "MAST mission archive (KEBC overcontact KIC 11244501, Q3 long cadence)")
        _print(record)
        return 0
    if args.action == "fetch":
        quarters = [int(q) for q in args.quarters.split(",")] if args.quarters else sorted(KEPLER_LC_QUARTERS)
        batch = od.Batch(Path(args.out_dir) / f"kepler_{args.kic}.json", route=args.route)
        for q in quarters:
            url = kepler_lc_url(args.kic, q)
            batch.add(url, str(Path(args.out_dir) / url.rsplit("/", 1)[-1]))
        guard_large(args.route, 500_000 * len(batch.items))
        _print(run_batch(batch, args))
        return 0
    raise SystemExit(f"unknown action {args.action}")


# --------------------------------------------------------------------------- commands: KEBC


def cmd_kebc(args: argparse.Namespace) -> int:
    if args.action == "list":
        _print({"table": KEBC_TABLE, "dr2_table": KEBC_DR2_TABLE, "mirrors": VIZIER,
                "villanova": "https://keplerebs.villanova.edu/", "example": kebc_url(morph_min=0.7)})
        return 0
    if args.action in ("query", "sample"):
        if args.action == "sample":
            morph, per, kp, out = 0.7, "0.2..0.6", 12.0, _sample_dir("kebc") / "kebc_contact_kp12.tsv"
        else:
            morph, per, kp = args.morph_min, args.per, args.kp_max
            out = Path(args.out) if args.out else None
        url = kebc_url(mirror=args.mirror, morph_min=morph, per=per, kp_max=kp)
        t0 = time.time()
        body = od.query(url, max_bytes=5 * 1024 * 1024, timeout=120)
        header, rows = parse_vizier_tsv(body.decode("utf-8", "replace"))
        if "KIC" not in header:
            raise od.OpenDataError("VizieR answer has no KIC column")
        check = {"columns": header, "rows": len(rows), "first": rows[0] if rows else None}
        if out is None:
            _print(check)
            return 0
        record = _keep_answer(out, body, url, time.time() - t0, check)
        if args.action == "sample":
            record["selection"] = _selection("kebc", "https://keplerebs.villanova.edu/", url,
                                             {"route": "clash-query", "mirror": args.mirror})
        _print(record)
        return 0
    raise SystemExit(f"unknown action {args.action}")


# --------------------------------------------------------------------------- commands: ASAS-SN


def cmd_asassn(args: argparse.Namespace) -> int:
    if args.action == "lookup":
        body = od.query(asassn_lookup_url(args.ra, args.dec, args.radius), max_bytes=2 * 1024 * 1024)
        _print({"uuids": parse_asassn_lookup(body.decode("utf-8", "replace")),
                "lc_json": "https://asas-sn.osu.edu/variables/<uuid>.json"})
        return 0
    if args.action in ("sample", "fetch"):
        uuid = ASASSN_SAMPLE["uuid"] if args.action == "sample" else args.uuid
        if not uuid:
            raise SystemExit("--uuid required")
        url = asassn_lc_url(uuid)
        t0 = time.time()
        body = od.query(url, max_bytes=10 * 1024 * 1024, timeout=120)
        check = parse_asassn_json(body)
        out = (_sample_dir("asassn-vsd") / f"asassn_{uuid}.json" if args.action == "sample" else Path(args.out))
        record = _keep_answer(out, body, url, time.time() - t0, check)
        if args.action == "sample":
            record["selection"] = _selection("asassn-vsd", f"{ASASSN}/variables", url,
                                             {"route": "clash-query"},
                                             f"{ASASSN_SAMPLE['name']} = TIC {ASASSN_SAMPLE['tic']}")
        _print(record)
        return 0
    raise SystemExit(f"unknown action {args.action}")


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="source", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--route", default="auto", choices=("auto", "direct"))
        p.add_argument("--limit", type=int, default=None, help="submit at most N new files this run")
        p.add_argument("--wait", action="store_true")
        p.add_argument("--submit", action="store_true", help="fetch: actually submit (default: dry run)")
        p.add_argument("--timeout", type=int, default=600)
        p.add_argument("--out", default=None)
        p.add_argument("--out-dir", default=None)

    z = sub.add_parser("ztf", help="ZTF DR24 light-curve API (IRSA)")
    z.add_argument("action", choices=("list", "query", "sample", "fetch"))
    z.add_argument("--ra", type=float)
    z.add_argument("--dec", type=float)
    z.add_argument("--radius", type=float, default=1.5, help="arcsec")
    z.add_argument("--targets", help="CSV with name,ra,dec[,radius]")
    z.add_argument("--pause", type=float, default=2.0)
    common(z)
    z.set_defaults(func=cmd_ztf)

    lm = sub.add_parser("lamost", help="LAMOST public DR (DR10-DR12 v2.0)")
    lm.add_argument("action", choices=("list", "query", "sample", "fetch"))
    lm.add_argument("--dr", default=LAMOST_DEFAULT[0])
    lm.add_argument("--version", default=LAMOST_DEFAULT[1])
    lm.add_argument("--ra", type=float)
    lm.add_argument("--dec", type=float)
    lm.add_argument("--radius", type=float, default=3.0, help="arcsec")
    lm.add_argument("--mrs", action="store_true", help="medium-resolution survey")
    lm.add_argument("--obsids", default="")
    common(lm)
    lm.set_defaults(func=cmd_lamost)

    t = sub.add_parser("tess-ffi", help="TESS full-frame images (MAST / AWS stpubdata)")
    t.add_argument("action", choices=("list", "sample", "fetch", "tesscut-url"))
    t.add_argument("--sector", type=int, default=33)
    t.add_argument("--camera", type=int, default=1)
    t.add_argument("--ccd", type=int, default=1)
    t.add_argument("--day", type=int, default=None, help="day-of-year directory")
    t.add_argument("--max-keys", type=int, default=20)
    t.add_argument("--ra", type=float)
    t.add_argument("--dec", type=float)
    t.add_argument("--size", type=int, default=20)
    common(t)
    t.set_defaults(func=cmd_tess_ffi)

    k = sub.add_parser("kepler", help="Kepler/K2 light curves (MAST)")
    k.add_argument("action", choices=("list", "sample", "fetch"))
    k.add_argument("--kic", type=int, default=KEPLER_SAMPLE["kic"])
    k.add_argument("--quarters", default="")
    common(k)
    k.set_defaults(func=cmd_kepler)

    e = sub.add_parser("kebc", help="Kepler Eclipsing Binary Catalog (VizieR)")
    e.add_argument("action", choices=("list", "query", "sample"))
    e.add_argument("--mirror", default="cfa", choices=sorted(VIZIER))
    e.add_argument("--morph-min", type=float, default=None)
    e.add_argument("--per", default=None, help="VizieR range, e.g. 0.2..0.6")
    e.add_argument("--kp-max", type=float, default=None)
    common(e)
    e.set_defaults(func=cmd_kebc)

    a = sub.add_parser("asassn", help="ASAS-SN variable-star database light curves (V band)")
    a.add_argument("action", choices=("lookup", "sample", "fetch"))
    a.add_argument("--ra", type=float)
    a.add_argument("--dec", type=float)
    a.add_argument("--radius", type=float, default=0.5, help="arcmin")
    a.add_argument("--uuid", default=None)
    common(a)
    a.set_defaults(func=cmd_asassn)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "action", None) == "fetch" and args.source not in ("ztf", "asassn") and not args.out_dir:
        raise SystemExit("fetch needs --out-dir")
    try:
        return int(args.func(args) or 0)
    except od.OffPeakRequired as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
