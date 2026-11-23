#!/usr/bin/env python3
"""Rebuild the shared figure-asset library from ``manifest.json``.

The library (default ``$OPENLABS_FIG_ASSETS`` or ``/workspace/openlabs/build/figure-assets``)
is not in git. This script restores it: every download goes through the WSL download
bridge (``download-submit --route auto``); nothing is fetched from the container itself.

* npm icon sets (Tabler, Material Symbols, Phosphor) come as one small package tarball
  each from the npmmirror registry (the domestic npm mirror; its per-file endpoint
  answers 403). The tarball is checked against the registry's sha512 ``integrity``
  (the same value registry.npmjs.org publishes) and only the listed icons are extracted.
* Bioicons (pinned git commit) and Reactome icons are fetched one SVG at a time.
* The OpenLabs self-drawn CC0 assets are copied from ``figure-templates/assets``.

Each asset gets ``<name>.license.json`` (source, licence, attribution, licence URL,
download URL, retrieval date, sha256) and the library root gets ``catalog.json``, which
``paper-writing figures assets`` searches. Files are never deleted; an existing asset
whose bytes match the manifest is kept. Total size is a few MB, so the proxy-window rule
for large downloads does not apply; a job that the bridge parks in its window is
reported and left queued, never resubmitted.

    python3 fetch_assets.py [--library DIR] [--field energy] [--dry-run] [--record]
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"
LOCAL_ASSETS = HERE.parent / "figure-templates" / "assets"
DEFAULT_LIBRARY = "/workspace/openlabs/build/figure-assets"
BRIDGE = os.environ.get("OPENLABS_DOWNLOAD_SUBMIT", "/workspace/.download-bridge/download-submit")
LICENSE_DEEDS = {
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC BY 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
}
UNSAFE_SVG = re.compile(r"<script|<foreignObject|\bon[a-z]+\s*=|javascript:|(?:xlink:)?href\s*=\s*[\"'](?!#|data:image/)",
                        re.I)


class FetchError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def svg_problem(text: str) -> str | None:
    """Why an SVG must not be inlined into a rendered figure (scripts, external links)."""
    if "<svg" not in text:
        return "not an SVG document"
    if "viewBox" not in text:
        return "no viewBox"
    match = UNSAFE_SVG.search(text)
    return f"unsafe content {match.group(0)!r}" if match else None


# ---------------------------------------------------------------- bridge
def _last_json(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def quote(url: str) -> str:
    head, sep, path = url.partition("://")
    host, _, rest = path.partition("/")
    return f"{head}{sep}{host}/" + urllib.parse.quote(rest, safe="/@-._~")


def submit(url: str, output: Path, sha: str | None = None, size: int | None = None) -> str:
    command = [BRIDGE, "--url", quote(url), "--output", str(output), "--route", "auto"]
    if sha:
        command += ["--sha256", sha]
    if size:
        command += ["--expected-bytes", str(size)]  # small known size: never parked as a large download
    proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    job = _last_json(proc.stdout)
    if proc.returncode != 0 or not job.get("id"):
        raise FetchError(f"download-submit refused {url}: {proc.stdout[-400:]} {proc.stderr[-400:]}")
    return job["id"]


def status(job: str) -> dict:
    proc = subprocess.run([BRIDGE, "--status", job], capture_output=True, text=True, timeout=60)
    return _last_json(proc.stdout)


def wait_all(jobs: dict[str, str], timeout: float = 900) -> dict[str, dict]:
    """job id -> final record; stops waiting on parked (window) or failed jobs."""
    final: dict[str, dict] = {}
    deadline = time.monotonic() + timeout
    while len(final) < len(jobs) and time.monotonic() < deadline:
        for job in jobs:
            if job in final:
                continue
            record = status(job)
            if record.get("state") in {"completed", "failed", "cancelled", "waiting_window"}:
                final[job] = record
        if len(final) < len(jobs):
            time.sleep(2)
    for job in jobs:
        final.setdefault(job, {"state": "timeout"})
    return final


def fetch(requests: list[tuple], log: list[dict]) -> None:
    """Download (url, output, sha256, bytes) items not yet on disk; raise if any did not complete."""
    pending = {}
    for url, output, sha, size in requests:
        if output.is_file() and (sha is None or sha256(output) == sha):
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        pending[submit(url, output, sha, size)] = (url, output)
    if not pending:
        return
    results = wait_all(pending)
    bad = []
    for job, record in results.items():
        url, output = pending[job]
        log.append({"url": url, "output": str(output), "job": job, "state": record.get("state"),
                    "route": record.get("route"), "routes_attempted": record.get("routes_attempted"),
                    "fallback_reason": record.get("fallback_reason")})
        if record.get("state") != "completed":
            bad.append(f"{url}: {record.get('state')} {record.get('fallback_reason') or record.get('reason') or ''}")
    if bad:
        raise FetchError("downloads not completed (left queued; see the bridge logs):\n  " + "\n  ".join(bad))


# ---------------------------------------------------------------- library
def credit(lib: dict, asset: dict) -> str:
    creator = asset.get("creator")
    if asset["library"] == "bioicons":
        if creator == "Servier":
            return "Servier Medical Art (smart.servier.com), via Bioicons"
        return f"{creator}, via Bioicons" if creator else lib["attribution"]
    return lib["attribution"]


def license_record(lib: dict, asset: dict, digest: str, download_url: str, today: str) -> dict:
    licence = asset.get("license") or lib["license"]
    return {
        "source": f"{lib['title']} {lib['version']} ({lib['homepage']})",
        "license": licence,
        "attribution": credit(lib, asset),
        "url": LICENSE_DEEDS.get(licence, lib["license_url"]),
        "download_url": download_url,
        "upstream_path": asset["upstream"],
        "retrieved": today,
        "modifications": "none (upstream file unchanged; recolour at use)",
        "sha256": digest,
    }


def run(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    library = Path(args.library)
    sources = library / "_sources"
    libs = manifest["libraries"]
    assets = [a for a in manifest["assets"] if not args.field or a["field"] in args.field]
    today = dt.date.today().isoformat()
    log: list[dict] = []
    if args.dry_run:
        for a in assets:
            print(f"{a['path']:55} {a['library']:9} {a.get('license') or libs[a['library']]['license']}")
        print(f"{len(assets)} assets")
        return 0

    # 1. package tarballs and licence texts
    requests = []
    for name, lib in libs.items():
        if lib["kind"] == "npm-tarball" and any(a["library"] == name for a in assets):
            requests.append((lib["url"], sources / lib["tarball"], None, None))
        for fname, url in (lib.get("license_files") or {}).items():
            size = (lib.get("license_file_bytes") or {}).get(fname)
            requests.append((url, sources / "licenses" / f"{name}-{fname}", None, size))
    fetch(requests, log)
    for name, lib in libs.items():
        if lib["kind"] != "npm-tarball" or not any(a["library"] == name for a in assets):
            continue
        tarball = sources / lib["tarball"]
        got = "sha512-" + base64.b64encode(hashlib.sha512(tarball.read_bytes()).digest()).decode()
        if got != lib["integrity"]:
            raise FetchError(f"{tarball.name}: integrity {got[:24]}... does not match the registry value")

    # 2. single-file libraries
    requests = []
    for a in assets:
        lib = libs[a["library"]]
        if lib["kind"] == "file":
            requests.append((lib["base_url"] + a["upstream"], sources / a["library"] / a["upstream"], a.get("sha256"),
                             a.get("bytes")))
    fetch(requests, log)

    # 3. place assets and licence records
    open_tars: dict[str, tarfile.TarFile] = {}
    placed, problems = [], []
    for a in assets:
        lib = libs[a["library"]]
        target = library / a["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if lib["kind"] == "npm-tarball":
            tar = open_tars.setdefault(a["library"], tarfile.open(sources / lib["tarball"]))
            data = tar.extractfile(a["upstream"]).read()
            download_url = lib["official_url"] + "#" + a["upstream"]
            if a["library"] not in {p.get("library") for p in placed}:
                licence_text = tar.extractfile(lib["license_member"]).read()
                (sources / "licenses").mkdir(parents=True, exist_ok=True)
                (sources / "licenses" / f"{a['library']}-LICENSE").write_bytes(licence_text)
        else:
            data = (sources / a["library"] / a["upstream"]).read_bytes()
            download_url = quote(lib["base_url"] + a["upstream"])
        digest = hashlib.sha256(data).hexdigest()
        if a.get("git_blob") and git_blob(data) != a["git_blob"]:
            problems.append(f"{a['path']}: content differs from git blob {a['git_blob']} of the pinned commit")
            continue
        if a.get("sha256") and a["sha256"] != digest:
            problems.append(f"{a['path']}: sha256 differs from the manifest")
            continue
        problem = svg_problem(data.decode("utf-8", errors="replace"))
        if problem:
            problems.append(f"{a['path']}: {problem}")
            continue
        if not target.is_file() or sha256(target) != digest:
            target.write_bytes(data)
        record = license_record(lib, a, digest, download_url, today)
        meta = target.with_name(target.stem + ".license.json")
        if meta.is_file():  # keep the first retrieval date
            record["retrieved"] = json.loads(meta.read_text()).get("retrieved", today)
        meta.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        a["sha256"] = digest
        placed.append({"path": a["path"], "name": a["name"], "field": a["field"], "library": a["library"],
                       "keywords": a["keywords"], "license": record["license"], "attribution": record["attribution"],
                       "credit_required": record["license"] not in ("CC0 1.0",), "sha256": digest})
    for tar in open_tars.values():
        tar.close()

    # 4. OpenLabs self-drawn CC0 assets kept in the repository
    for svg in sorted(LOCAL_ASSETS.glob("*/*.svg")):
        rel = svg.relative_to(LOCAL_ASSETS).as_posix()
        if args.field and svg.parent.name not in args.field:
            continue
        target = library / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or sha256(target) != sha256(svg):
            shutil.copyfile(svg, target)
        meta_src = svg.with_name(svg.stem + ".license.json")
        meta = json.loads(meta_src.read_text()) if meta_src.is_file() else {}
        if meta_src.is_file():
            shutil.copyfile(meta_src, target.with_name(svg.stem + ".license.json"))
        placed.append({"path": rel, "name": svg.stem, "field": svg.parent.name, "library": "openlabs",
                       "keywords": [svg.stem, "openlabs", "self-drawn",
                                    *str(manifest.get("local_keywords", {}).get(rel, "")).split()],
                       "license": meta.get("license", "CC0 1.0"),
                       "attribution": meta.get("attribution", "OpenLabs"),
                       "credit_required": "by" in str(meta.get("license", "")).lower().replace("cc0", ""),
                       "sha256": sha256(svg)})


    catalog_path = library / "catalog.json"
    previous = json.loads(catalog_path.read_text()).get("assets", []) if catalog_path.is_file() else []
    merged = {item["path"]: item for item in previous}
    merged.update({item["path"]: item for item in placed})
    catalog = {"schema_version": "openlabs.figure_assets.catalog.v1", "generated": today,
               "manifest": str(Path(args.manifest).resolve()),
               "libraries": {k: {f: v[f] for f in ("title", "version", "license", "attribution", "homepage")}
                             for k, v in libs.items()},
               "assets": sorted(merged.values(), key=lambda item: item["path"])}
    catalog_path.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (sources / "fetch-log.json").write_text(json.dumps({"date": today, "downloads": log}, indent=1) + "\n")
    if args.record:
        Path(args.manifest).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"placed {len(placed)} assets in {library}; catalog {catalog_path}")
    for p in problems:
        print("PROBLEM", p, file=sys.stderr)
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--library", default=os.environ.get("OPENLABS_FIG_ASSETS") or DEFAULT_LIBRARY)
    parser.add_argument("--field", action="append", help="Only this field (repeatable).")
    parser.add_argument("--dry-run", action="store_true", help="List the assets and exit.")
    parser.add_argument("--record", action="store_true", help="Write the verified sha256 values into the manifest.")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except FetchError as exc:
        print(f"fetch_assets: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
