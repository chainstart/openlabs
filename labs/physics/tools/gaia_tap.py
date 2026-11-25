"""Gaia DR3 rows with mirror fallback (2026-11-25; ESA archive down 2026-11-25 to 2026-12-02).

The ESA Gaia archive (gea.esac.esa.int) went into maintenance on 2026-11-25 12:00 CET (Beijing
19:00) and reopens with Gaia DR4 on 2026-12-02 12:00 CET. During maintenance its TAP endpoint
answers **HTTP 200 with an HTML page**, so a client that only checks the status code stores HTML
as if it were a CSV (the astro line's ``baseline/fetch_lc.py`` did exactly that through the
bridge). This module asks the backends below in order and returns rows under the ESA column
names, with a provenance record naming the backend that answered:

1. ``esa``            ESA Gaia TAP, ``gaiadr3.gaia_source`` (ADQL)
2. ``vizier-chinavo`` China-VO (NADC) VizieR mirror, catalogue ``I/355/gaiadr3`` (asu-tsv; http
                      only; answered on 2026-11-25 after one 60 s timeout, so its wait is capped)
3. ``vizier-cfa``     CfA VizieR mirror, same catalogue
4. ``gavo``           GAVO/ARI Heidelberg TAP ``gaia.dr3lite`` (subset of columns; only used when
                      every requested column exists there, or with ``allow_partial``)
5. ``vizier-cds``     CDS VizieR, same catalogue (404 from the container on 2026-11-25)

The VizieR copy of DR3 is the same source table (Gaia Collaboration 2022, I/355); values are
rounded to the printed precision (e.g. Gmag to 1e-6 mag, Plx to 1e-4 mas). VizieR cone searches
are centred on J2000 positions propagated by VizieR; separations here are recomputed from the
epoch-2016.0 RA/Dec, as on the ESA side.

Interface changes of the ESA archive on 2026-10-14 (DataLink product renames, at most 5 parallel
async jobs and 50 queued per user) do not affect this module: it uses synchronous TAP only and no
DataLink. Gaia DR4 (2026-12-02) uses new table names (``gaiadr4.*``); this module stays on DR3.

Small query answers only (od.query caps them); nothing here downloads files.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "open-data"))
import open_data as od  # noqa: E402

ESA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
GAVO_TAP = "https://dc.zah.uni-heidelberg.de/tap/sync"
VIZIER = {
    "vizier-cfa": "https://vizier.cfa.harvard.edu/viz-bin/asu-tsv",
    "vizier-cds": "https://vizier.cds.unistra.fr/viz-bin/asu-tsv",
    "vizier-chinavo": "http://vizier.china-vo.org/viz-bin/asu-tsv",
}
VIZIER_TABLE = "I/355/gaiadr3"
BACKENDS = ("esa", "vizier-chinavo", "vizier-cfa", "gavo", "vizier-cds")
# China-VO first among mirrors (domestic source); it timed out once on 2026-11-25, so its wait is capped.
TIMEOUT_CAP = {"vizier-chinavo": 45.0}
EMPTY_CONE_UNRELIABLE = frozenset({"vizier-chinavo"})

# ESA gaiadr3.gaia_source column -> VizieR I/355/gaiadr3 column
VIZIER_COLUMNS = {
    "source_id": "Source", "ra": "RA_ICRS", "dec": "DE_ICRS", "ra_error": "e_RA_ICRS",
    "dec_error": "e_DE_ICRS", "parallax": "Plx", "parallax_error": "e_Plx",
    "parallax_over_error": "RPlx", "pmra": "pmRA", "pmdec": "pmDE", "pmra_error": "e_pmRA",
    "pmdec_error": "e_pmDE", "ruwe": "RUWE", "phot_g_mean_mag": "Gmag",
    "phot_bp_mean_mag": "BPmag", "phot_rp_mean_mag": "RPmag", "bp_rp": "BP-RP",
    "radial_velocity": "RV", "radial_velocity_error": "e_RV", "teff_gspphot": "Teff",
    "logg_gspphot": "logg", "mh_gspphot": "[Fe/H]", "distance_gspphot": "Dist",
    "ag_gspphot": "AG", "ebpminrp_gspphot": "E(BP-RP)", "phot_variable_flag": "VarFlag",
    "non_single_star": "NSS", "has_epoch_photometry": "EpochPh", "has_xp_continuous": "XPcont",
    "has_rvs": "RVS", "phot_g_n_obs": "o_Gmag", "ipd_frac_multi_peak": "IPDfmp",
}
GAVO_COLUMNS = frozenset({
    "source_id", "ra", "dec", "ra_error", "dec_error", "pmra", "pmdec", "pmra_error",
    "pmdec_error", "parallax", "parallax_error", "phot_g_mean_mag", "phot_rp_mean_mag",
    "phot_bp_mean_mag", "radial_velocity", "radial_velocity_error", "ruwe",
    "visibility_periods_used", "astrometric_excess_noise",
})
INT_COLUMNS = frozenset({"source_id", "non_single_star", "phot_g_n_obs"})
BOOL_COLUMNS = frozenset({"has_epoch_photometry", "has_xp_continuous", "has_rvs"})
TEXT_COLUMNS = frozenset({"phot_variable_flag"})

Fetcher = Callable[..., bytes]


class GaiaUnavailable(RuntimeError):
    """No backend answered."""


# --------------------------------------------------------------------------- parsing


def _value(column: str, text: Any) -> Any:
    if text is None:
        return None
    raw = str(text).strip()
    if raw == "" or raw.lower() in {"nan", "null", "--"}:
        return None
    if column in TEXT_COLUMNS:
        return raw
    if column in BOOL_COLUMNS:
        return raw.lower() in {"1", "true", "t"}
    if column in INT_COLUMNS:
        return int(raw.split(".")[0])
    try:
        return float(raw)
    except ValueError:
        return raw


def parse_csv(body: bytes, columns: Sequence[str]) -> list[dict[str, Any]]:
    """TAP CSV answer -> rows (ESA column names)."""

    if od.looks_like_html(body):
        raise GaiaUnavailable("HTML page instead of CSV (archive maintenance or error page)")
    text = body.decode("utf-8", errors="replace")
    if text.lstrip().startswith("<"):
        raise GaiaUnavailable(f"TAP error document: {text[:300]}")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for record in reader:
        rows.append({column: _value(column, record.get(column)) for column in columns
                     if column in record or column in columns})
    return rows


def parse_vizier_tsv(body: bytes, columns: Sequence[str]) -> list[dict[str, Any]]:
    """VizieR asu-tsv answer (comments, header, units line, dashes line, rows) -> rows."""

    if od.looks_like_html(body):
        raise GaiaUnavailable("HTML page instead of TSV")
    lines = [line for line in body.decode("utf-8", errors="replace").splitlines()
             if line and not line.startswith("#")]
    if not lines:
        return []
    header = lines[0].split("\t")
    data = lines[1:]
    # skip the units line and the dashes line when present
    while data and (not data[0].strip("\t -") or _is_units_line(data[0], header)):
        data = data[1:]
    reverse = {VIZIER_COLUMNS[column]: column for column in columns if column in VIZIER_COLUMNS}
    rows = []
    for line in data:
        cells = line.split("\t")
        record = dict(zip(header, cells))
        if "Source" in record and not record["Source"].strip().isdigit():
            continue   # a units or separator line with units this parser does not know
        rows.append({reverse[name]: _value(reverse[name], record.get(name)) for name in header
                     if name in reverse})
    return rows


def _is_units_line(line: str, header: Sequence[str]) -> bool:
    cells = [cell.strip() for cell in line.split("\t")]
    if len(cells) != len(header):
        return False
    known_units = {"", "deg", "mas", "mas/yr", "mag", "K", "km/s", "pc", "[cm/s2]", "[-]", "%"}
    return all(cell in known_units for cell in cells) and any(cells)


# --------------------------------------------------------------------------- geometry


def separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    hav = (math.sin((d2 - d1) / 2) ** 2
           + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2)
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(hav)))) * 3600.0


# --------------------------------------------------------------------------- backends


def _esa_adql(columns: Sequence[str], where: str, top: int | None, order: str | None) -> str:
    head = f"SELECT {'TOP ' + str(top) + ' ' if top else ''}{', '.join(columns)}"
    tail = f" ORDER BY {order} ASC" if order else ""
    return f"{head} FROM gaiadr3.gaia_source WHERE {where}{tail}"


def _gavo_adql(columns: Sequence[str], where: str, top: int | None, order: str | None) -> str:
    return _esa_adql(columns, where, top, order).replace("gaiadr3.gaia_source", "gaia.dr3lite")


def _tap(endpoint: str, adql: str, fetch: Fetcher, timeout: float) -> bytes:
    params = {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql}
    return fetch(endpoint, params, timeout=timeout)


def _where_id(source_id: int) -> str:
    return f"source_id={int(source_id)}"


def _where_cone(ra: float, dec: float, radius_arcsec: float) -> str:
    return (f"1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.7f},{dec:.7f},"
            f"{radius_arcsec / 3600.0:.7f}))")


def _vizier_params(columns: Sequence[str], *, source_id: int | None = None,
                   ra: float | None = None, dec: float | None = None,
                   radius_arcsec: float | None = None, top: int | None = None) -> dict[str, str]:
    names = [VIZIER_COLUMNS[c] for c in columns]
    params = {"-source": VIZIER_TABLE, "-out": ",".join(names), "-out.max": str(top or 10000)}
    if source_id is not None:
        params["Source"] = str(int(source_id))
    else:
        params["-c"] = f"{ra:.7f} {dec:+.7f}"
        params["-c.rs"] = f"{radius_arcsec:.4f}"
    return params


def run(kind: str, columns: Sequence[str], *, source_id: int | None = None,
        ra: float | None = None, dec: float | None = None, radius_arcsec: float | None = None,
        top: int | None = None, order_by_g: bool = False,
        backends: Iterable[str] = BACKENDS, allow_partial: bool = False,
        fetch: Fetcher | None = None, timeout: float = 120) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rows and provenance for an id lookup (``kind="id"``) or a cone (``kind="cone"``)."""

    fetch = fetch or od.query
    columns = list(dict.fromkeys(["source_id", "ra", "dec", *columns]))
    if order_by_g and "phot_g_mean_mag" not in columns:
        columns.append("phot_g_mean_mag")
    where = _where_id(source_id) if kind == "id" else _where_cone(ra, dec, radius_arcsec)
    attempts: list[dict[str, Any]] = []
    for backend in backends:
        try:
            if backend == "esa":
                adql = _esa_adql(columns, where, top, "phot_g_mean_mag" if order_by_g else None)
                rows = parse_csv(_tap(ESA_TAP, adql, fetch, timeout), columns)
                request = {"endpoint": ESA_TAP, "query": adql}
            elif backend in VIZIER:
                missing = [c for c in columns if c not in VIZIER_COLUMNS]
                if missing:
                    raise GaiaUnavailable(f"columns not mapped to VizieR: {missing}")
                params = _vizier_params(columns, source_id=source_id if kind == "id" else None,
                                        ra=ra, dec=dec, radius_arcsec=radius_arcsec,
                                        top=None if order_by_g else top)
                wait = min(timeout, TIMEOUT_CAP.get(backend, timeout))
                rows = parse_vizier_tsv(fetch(VIZIER[backend], params, timeout=wait), columns)
                if kind == "cone" and not rows and backend in EMPTY_CONE_UNRELIABLE:
                    # 2026-11-25: the China-VO copy of I/355/gaiadr3 answers id lookups but
                    # returns no rows for any cone; an empty cone there is not "no sources".
                    raise GaiaUnavailable("empty cone answer (mirror cone search unreliable)")
                request = {"endpoint": VIZIER[backend], "params": params}
            elif backend == "gavo":
                missing = [c for c in columns if c not in GAVO_COLUMNS]
                if missing and not allow_partial:
                    raise GaiaUnavailable(f"gaia.dr3lite lacks {missing}")
                present = [c for c in columns if c in GAVO_COLUMNS]
                adql = _gavo_adql(present, where, top, "phot_g_mean_mag" if order_by_g else None)
                rows = parse_csv(_tap(GAVO_TAP, adql, fetch, timeout), present)
                for row in rows:
                    for column in missing:
                        row[column] = None
                request = {"endpoint": GAVO_TAP, "query": adql, "missing_columns": missing}
            else:
                raise GaiaUnavailable(f"unknown backend {backend}")
        except Exception as exc:  # noqa: BLE001 - every failure moves to the next backend
            attempts.append({"backend": backend, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            continue
        if kind == "cone":
            for row in rows:
                if row.get("ra") is not None and row.get("dec") is not None:
                    row["sep_arcsec"] = separation_arcsec(ra, dec, row["ra"], row["dec"])
            rows = [r for r in rows if r.get("sep_arcsec") is None
                    or r["sep_arcsec"] <= radius_arcsec + 1e-6]
            if order_by_g:
                rows.sort(key=lambda r: (r.get("phot_g_mean_mag") is None,
                                         r.get("phot_g_mean_mag") or 0.0))
            if top:
                rows = rows[:top]
        provenance = {"backend": backend, "table": VIZIER_TABLE if backend in VIZIER else (
            "gaia.dr3lite" if backend == "gavo" else "gaiadr3.gaia_source"),
            "request": request, "queried_at": od.utc_now(), "failed_before": attempts,
            "release": "Gaia DR3"}
        return rows, provenance
    raise GaiaUnavailable(json.dumps(attempts, ensure_ascii=False))


def source_by_id(source_id: int, columns: Sequence[str], **kwargs: Any):
    return run("id", columns, source_id=source_id, **kwargs)


def cone(ra: float, dec: float, radius_arcsec: float, columns: Sequence[str], **kwargs: Any):
    return run("cone", columns, ra=ra, dec=dec, radius_arcsec=radius_arcsec, **kwargs)


def to_csv(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: ("" if row.get(key) is None else row.get(key)) for key in columns})
    return buffer.getvalue()


def probe(fetch: Fetcher | None = None, timeout: float = 60) -> list[dict[str, Any]]:
    """One id lookup per backend (Gaia DR3 4295806720): which backends answer right now."""

    results = []
    for backend in BACKENDS:
        try:
            rows, prov = source_by_id(4295806720, ["phot_g_mean_mag", "ruwe"], backends=[backend],
                                      fetch=fetch, timeout=timeout)
            results.append({"backend": backend, "ok": bool(rows), "rows": rows[:1]})
        except GaiaUnavailable as exc:
            results.append({"backend": backend, "ok": False, "error": str(exc)[:300]})
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_id = sub.add_parser("id", help="one source by Gaia DR3 source_id")
    p_id.add_argument("source_id", type=int)
    p_cone = sub.add_parser("cone", help="sources within a radius")
    p_cone.add_argument("--ra", type=float, required=True)
    p_cone.add_argument("--dec", type=float, required=True)
    p_cone.add_argument("--radius", type=float, default=5.0, help="arcsec")
    p_cone.add_argument("--top", type=int)
    p_cone.add_argument("--order-by-g", action="store_true")
    for p in (p_id, p_cone):
        p.add_argument("--columns", default="ra,dec,parallax,parallax_error,ruwe,phot_g_mean_mag,"
                       "phot_bp_mean_mag,phot_rp_mean_mag,teff_gspphot,phot_variable_flag")
        p.add_argument("--backends", default=",".join(BACKENDS))
        p.add_argument("--out", help="write CSV here and provenance to <out>.provenance.json")
    sub.add_parser("probe", help="which backends answer now")
    args = parser.parse_args(argv)
    if args.command == "probe":
        print(json.dumps(probe(), indent=1))
        return 0
    columns = [c.strip() for c in args.columns.split(",") if c.strip()]
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    if args.command == "id":
        rows, prov = source_by_id(args.source_id, columns, backends=backends)
    else:
        rows, prov = cone(args.ra, args.dec, args.radius, columns, top=args.top,
                          order_by_g=args.order_by_g, backends=backends)
    header = list(dict.fromkeys(["source_id", "ra", "dec", *columns]
                                + (["sep_arcsec"] if args.command == "cone" else [])))
    text = to_csv(rows, header)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        Path(args.out + ".provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(json.dumps({"backend": prov["backend"], "rows": len(rows),
                      "failed_before": prov["failed_before"]}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
