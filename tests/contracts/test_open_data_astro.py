"""Offline contract tests for labs/physics/tools/astro_open_data.py (no network)."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("astro_open_data", ROOT / "labs/physics/tools/astro_open_data.py")
astro = importlib.util.module_from_spec(spec)
sys.modules["astro_open_data"] = astro
spec.loader.exec_module(astro)
od = astro.od

EVENING = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)   # 20:00 Beijing
MORNING = datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc)    # 09:00 Beijing


# ----------------------------------------------------------------------------- ZTF

def test_ztf_url_converts_arcsec_to_degrees():
    url = astro.ztf_url(298.0025, 29.87147, 1.4)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://irsa.ipac.caltech.edu/cgi-bin/ZTF/nph_light_curves?")
    assert q["POS"] == ["CIRCLE 298.002500 29.871470 0.000389"]
    assert q["BAD_CATFLAGS_MASK"] == ["32768"] and q["FORMAT"] == ["csv"]
    assert "%20" in url and "+" not in url
    q2 = urllib.parse.parse_qs(urllib.parse.urlparse(astro.ztf_url(1, 2, 1, bands=["zg", "zr"])).query)
    assert q2["BANDNAME"] == ["g,r"]
    with pytest.raises(ValueError):
        astro.ztf_url(400, 0, 1)
    with pytest.raises(ValueError):
        astro.ztf_url(10, 0, 0)


ZTF_CSV = """oid,expid,hjd,mjd,mag,magerr,catflags,filtercode,ra,dec
686103400034440,1,2458205.01,58204.51,17.72,0.029,0,zg,298.0025,29.8715
686103400034440,2,2458206.01,58205.51,17.66,0.028,0,zg,298.0025,29.8715
686203400034441,3,2458207.01,58206.51,16.90,0.020,2048,zr,298.0025,29.8715
"""


def test_parse_ztf_csv_counts_bands_and_flags():
    s = astro.parse_ztf_csv(ZTF_CSV)
    assert s["rows"] == 3
    assert s["rows_per_band"] == {"zg": 2, "zr": 1}
    assert s["oids"] == {"zg": ["686103400034440"], "zr": ["686203400034441"]}
    assert s["catflags_nonzero"] == 1
    assert s["mjd_range"] == [58204.51, 58206.51]


def test_parse_ztf_csv_rejects_html_and_missing_columns():
    with pytest.raises(od.OpenDataError):
        astro.parse_ztf_csv("<!DOCTYPE html><html>maintenance</html>")
    with pytest.raises(od.OpenDataError):
        astro.parse_ztf_csv("oid,mag\n1,2\n")


# ----------------------------------------------------------------------------- LAMOST

def test_lamost_urls():
    assert astro.lamost_spectrum_url(837111229) == "https://www.lamost.org/dr12/v2.0/spectrum/fits/837111229"
    assert astro.lamost_spectrum_url("665911200", mrs=True).endswith("/dr12/v2.0/medspectrum/fits/665911200")
    cone = astro.lamost_cone_url(290.67, 44.5, 0.05, dr="dr10")
    assert cone.startswith("https://www.lamost.org/dr10/v2.0/voservice/conesearch?") and "SR=0.05" in cone
    assert "/medvoservice/ssap?" in astro.lamost_ssap_url(1, 2, 0.01, mrs=True)
    with pytest.raises(ValueError):
        astro.lamost_spectrum_url("123;ls")
    with pytest.raises(ValueError):
        astro.lamost_cone_url(0, 0, 5)
    # spectrum URLs carry no (empty) token parameter, which od.public_url would refuse
    od.public_url(astro.lamost_spectrum_url(1))


VOTABLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.3" version="1.4"><RESOURCE type="results">
<INFO name="QUERY_STATUS" value="OK"/><TABLE>
<FIELD name="obsid" datatype="long"/><FIELD name="snrg" datatype="double"/><FIELD name="class" datatype="char"/>
<DATA><TABLEDATA><TR><TD>837111229</TD><TD>170.8</TD><TD>STAR</TD></TR><TR><TD>2</TD><TD>15</TD><TD>STAR</TD></TR>
</TABLEDATA></DATA></TABLE></RESOURCE></VOTABLE>"""


def test_parse_votable():
    fields, rows, info = astro.parse_votable(VOTABLE)
    assert fields == ["obsid", "snrg", "class"]
    assert rows[0] == {"obsid": "837111229", "snrg": "170.8", "class": "STAR"} and len(rows) == 2
    assert info["QUERY_STATUS"] == "OK"
    with pytest.raises(od.OpenDataError):
        astro.parse_votable(b"<html><body>login</body></html>")


def test_lamost_dr13_refused():
    with pytest.raises(SystemExit):
        astro.main(["lamost", "list", "--dr", "dr13", "--version", "v1.0"])


# ----------------------------------------------------------------------------- TESS FFI

def test_ffi_paths():
    key = "tess/public/ffi/s0033/2020/360/1-1/tess2020360000910-s0033-1-1-0203-s_ffic.fits"
    assert astro.ffi_prefix(33, 2020, 360, 1, 1) == "tess/public/ffi/s0033/2020/360/1-1/"
    assert astro.ffi_prefix(33) == "tess/public/ffi/s0033/"
    assert astro.ffi_https(key) == "https://stpubdata.s3.amazonaws.com/" + key
    assert astro.ffi_mast_url(key) == ("https://archive.stsci.edu/missions/tess/ffi/s0033/2020/360/1-1/"
                                       "tess2020360000910-s0033-1-1-0203-s_ffic.fits")
    m = astro.FFI_NAME.search(key)
    assert m and m["sector"] == "0033" and m["camera"] == "1" and m["kind"] == "ffic"
    assert [astro.ffi_cadence_s(s) for s in (1, 33, 70)] == [1800, 600, 200]
    with pytest.raises(ValueError):
        astro.ffi_prefix(33, 2020, 360, 5, 1)
    assert "sector=33" in astro.tesscut_url(90.0, -15.8, size=10, sector=33)
    assert astro.sector_script_url(33).endswith("tesscurl_sector_33_ffic.sh")


S3_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>stpubdata</Name>
<IsTruncated>true</IsTruncated>
<Contents><Key>tess/public/ffi/s0033/2020/360/1-1/a-s_ffic.fits</Key><Size>35547840</Size><ETag>"abc"</ETag></Contents>
<Contents><Key>tess/public/ffi/s0033/2020/360/1-1/a-s_ffir.fits</Key><Size>17775360</Size></Contents>
<CommonPrefixes><Prefix>tess/public/ffi/s0033/2021/</Prefix></CommonPrefixes></ListBucketResult>"""


def test_parse_s3_listing():
    out = astro.parse_s3_listing(S3_XML)
    assert out["truncated"] is True
    assert out["keys"][0] == {"key": "tess/public/ffi/s0033/2020/360/1-1/a-s_ffic.fits", "bytes": 35547840,
                              "etag": "abc"}
    assert out["prefixes"] == ["tess/public/ffi/s0033/2021/"]
    url = astro.s3_list_url("https://stpubdata.s3.amazonaws.com/", "tess/public/ffi/s0033/", delimiter="/")
    assert "list-type=2" in url and "delimiter=%2F" in url


# ----------------------------------------------------------------------------- Kepler / K2 / KEBC

def test_kepler_urls():
    assert astro.kepler_dir_url(11244501) == \
        "https://archive.stsci.edu/missions/kepler/lightcurves/0112/011244501/"
    assert astro.kepler_lc_url(11244501, 3).endswith("/0112/011244501/kplr011244501-2009350155506_llc.fits")
    assert len(astro.KEPLER_LC_QUARTERS) == 18
    with pytest.raises(ValueError):
        astro.kepler_lc_url(1, 3, cadence="slc")
    assert astro.k2_lc_url(211401234, 5) == \
        "https://archive.stsci.edu/missions/k2/lightcurves/c5/211400000/01000/ktwo211401234-c05_llc.fits"


def test_parse_dir_listing():
    html = ('<a href="?C=N;O=D">Name</a><a href="/missions/kepler/">Parent</a>'
            '<a href="kplr011244501-2009350155506_llc.fits">x</a><a href="kplr011244501_lc_Q1111.tar">t</a>')
    assert astro.parse_dir_listing(html) == ["kplr011244501-2009350155506_llc.fits"]
    assert len(astro.parse_dir_listing(html, r"\.(fits|tar)$")) == 2


VIZ_TSV = """#
#Table	J_AJ_151_68_catalog:
KIC	Per	Morph
 	d
--------	---------	-----
06699679	0.2012033	1.00
11244501	0.2966790	0.84

#Table	other:
a	b
"""


def test_kebc_url_and_tsv():
    url = astro.kebc_url(morph_min=0.7, per="0.2..0.6", kp_max=12)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["-source"] == ["J/AJ/151/68/catalog"] and q["Morph"] == [">=0.7"] and q["Kpmag"] == ["<12"]
    assert astro.kebc_url(mirror="china-vo").startswith("http://vizier.china-vo.org/")
    header, rows = astro.parse_vizier_tsv(VIZ_TSV)
    assert header == ["KIC", "Per", "Morph"]
    assert rows == [{"KIC": "06699679", "Per": "0.2012033", "Morph": "1.00"},
                    {"KIC": "11244501", "Per": "0.2966790", "Morph": "0.84"}]


# ----------------------------------------------------------------------------- ASAS-SN

def test_asassn_parsers():
    html = ('<a href="/variables/9e5a0679-7375-5753-b1b5-abed53bce682">x</a>'
            '<a href="/variables/9e5a0679-7375-5753-b1b5-abed53bce682">dup</a>')
    assert astro.parse_asassn_lookup(html) == ["9e5a0679-7375-5753-b1b5-abed53bce682"]
    assert astro.asassn_lc_url("9e5a0679-7375-5753-b1b5-abed53bce682").endswith(".json")
    with pytest.raises(ValueError):
        astro.asassn_lc_url("../etc")
    body = json.dumps({"count": 2, "results": [
        {"hjd": 2456599.9, "camera": "bb", "mag": 11.9, "mag_err": 0.02, "flux": 61.6, "flux_err": 1.1},
        {"hjd": 2456600.9, "camera": "bc", "mag": 12.0, "mag_err": 0.02, "flux": 56.5, "flux_err": 1.0}]})
    assert astro.parse_asassn_json(body) == {"rows": 2, "cameras": ["bb", "bc"], "hjd_range": [2456599.9, 2456600.9]}
    with pytest.raises(od.OpenDataError):
        astro.parse_asassn_json(json.dumps({"count": 5, "results": []}))


# ----------------------------------------------------------------------------- FITS reader

def _card(key, value=None):
    if value is None:
        return f"{key:<80}".encode()
    if isinstance(value, bool):
        text = "T" if value else "F"
        return f"{key:<8}= {text:>20}".ljust(80).encode()
    if isinstance(value, str):
        return f"{key:<8}= '{value:<8}'".ljust(80).encode()
    return f"{key:<8}= {value:>20}".ljust(80).encode()


def _hdu(cards, data_bytes=0):
    block = b"".join(_card(k, v) for k, v in cards) + _card("END")
    block += b" " * (-len(block) % 2880)
    return block + b"\0" * (-(-data_bytes // 2880) * 2880)


def _kepler_like(path: Path, gz=False):
    primary = _hdu([("SIMPLE", True), ("BITPIX", 8), ("NAXIS", 0), ("EXTEND", True), ("OBJECT", "KIC 11244501"),
                    ("KEPLERID", 11244501), ("QUARTER", 3), ("TELESCOP", "Kepler")])
    ext = _hdu([("XTENSION", "BINTABLE"), ("BITPIX", 8), ("NAXIS", 2), ("NAXIS1", 12), ("NAXIS2", 300),
                ("PCOUNT", 0), ("GCOUNT", 1), ("TFIELDS", 3), ("TTYPE1", "TIME"), ("TTYPE2", "SAP_FLUX"),
                ("TTYPE3", "PDCSAP_FLUX"), ("EXTNAME", "LIGHTCURVE")], data_bytes=3600)
    raw = primary + ext + _hdu([("XTENSION", "IMAGE"), ("BITPIX", 32), ("NAXIS", 0), ("EXTNAME", "APERTURE")])
    path.write_bytes(gzip.compress(raw) if gz else raw)
    return path


def test_fits_reader_and_kepler_check(tmp_path):
    for gz in (False, True):
        p = _kepler_like(tmp_path / f"k{gz}.fits", gz=gz)
        hdus = astro.read_fits_headers(p)
        assert len(hdus) == 3 and hdus[2]["EXTNAME"] == "APERTURE"
        chk = astro.check_kepler_fits(p)
        assert chk["KEPLERID"] == 11244501 and chk["QUARTER"] == 3 and chk["rows"] == 300
        assert chk["columns"] == ["TIME", "SAP_FLUX", "PDCSAP_FLUX"] and chk["EXTNAME"] == "LIGHTCURVE"
    bad = tmp_path / "bad.fits"
    bad.write_bytes(b"<!DOCTYPE html>" + b" " * 3000)
    with pytest.raises(od.OpenDataError):
        astro.read_fits_headers(bad)


def test_ffi_check(tmp_path):
    p = tmp_path / "ffi.fits"
    p.write_bytes(_hdu([("SIMPLE", True), ("BITPIX", 8), ("NAXIS", 0), ("TELESCOP", "TESS"), ("SECTOR", 33),
                        ("CAMERA", 1), ("CCD", 1)])
                  + _hdu([("XTENSION", "IMAGE"), ("BITPIX", -32), ("NAXIS", 2), ("NAXIS1", 2136),
                          ("NAXIS2", 2078), ("EXTNAME", "CAMERA.CCD 1.1 cal"), ("CTYPE1", "RA---TAN-SIP")]))
    chk = astro.check_ffi_fits(p)
    assert chk["SECTOR"] == 33 and chk["NAXIS1"] == 2136 and chk["has_wcs"] is True


# ----------------------------------------------------------------------------- window / batch

def test_guard_large_refuses_auto_batch_in_evening():
    with pytest.raises(od.OffPeakRequired):
        astro.guard_large("auto", 2 * 1024 ** 3, now=EVENING)
    astro.guard_large("auto", 2 * 1024 ** 3, now=MORNING)
    astro.guard_large("direct", 2 * 1024 ** 3, now=EVENING)
    astro.guard_large("auto", 50 * 1024 ** 2, now=EVENING)


def test_batch_with_fake_runner(tmp_path):
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"SIMPLE  =                    T")
        rec = {"id": f"job{len(calls)}", "state": "completed", "route": "direct", "routes_attempted": ["direct"]}
        return SimpleNamespace(stdout=json.dumps(rec) + "\n", stderr="", returncode=0)

    # od.submit only accepts /workspace outputs; stub it so the batch can write into tmp_path.
    batch = od.Batch(tmp_path / "b.json", route="auto")
    for q in (3, 4, 5):
        batch.add(astro.kepler_lc_url(11244501, q), str(tmp_path / f"q{q}.fits"))
    orig = od.submit

    def submit(url, output, **kw):
        kw.pop("runner", None)
        rec = runner([od.BRIDGE, "--url", url, "--output", str(output)])
        return json.loads(rec.stdout)

    try:
        od.submit = submit
        counts = batch.run(limit=2, runner=runner, now=EVENING)
        assert counts["submitted_now"] == 2 and counts["completed"] == 2 and counts["pending"] == 1
        counts = batch.run(runner=runner, now=EVENING)
        assert counts["submitted_now"] == 1 and counts["completed"] == 3
    finally:
        od.submit = orig
    assert len(calls) == 3


def test_submit_command_line_with_fake_runner():
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout='{"id": "j1", "state": "completed", "route": "direct"}\n', stderr="",
                               returncode=0)

    out = "/workspace/openlabs/build/lines/astro-survey-photometry/data/open-samples/tess-ffi/x.fits"
    rec = od.submit(astro.ffi_https(astro.FFI_SAMPLE_KEY), out, expected_bytes=astro.FFI_SAMPLE_BYTES,
                    task_bytes=astro.FFI_SAMPLE_BYTES, runner=runner)
    cmd = seen["cmd"]
    assert rec["state"] == "completed"
    assert cmd[cmd.index("--route") + 1] == "auto" and "--large" not in cmd
    assert cmd[cmd.index("--expected-bytes") + 1] == str(astro.FFI_SAMPLE_BYTES)


def test_run_batch_is_a_dry_run_unless_submit(tmp_path):
    batch = od.Batch(tmp_path / "b.json", route="auto")
    for i in range(12):
        batch.add(f"https://stpubdata.s3.amazonaws.com/tess/public/ffi/s0033/x{i}-s_ffic.fits",
                  str(tmp_path / f"x{i}.fits"), expected_bytes=35547840)

    def runner(cmd, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("dry run submitted something")

    args = SimpleNamespace(submit=False, limit=None, wait=False)
    plan = astro.run_batch(batch, args, runner=runner)
    assert plan["pending"] == 12 and plan["total_expected_bytes"] == 12 * 35547840 and "dry_run" in plan
    with pytest.raises(SystemExit):
        astro.run_batch(batch, SimpleNamespace(submit=True, limit=None, wait=False), runner=runner)
