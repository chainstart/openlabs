"""Install the checksum-pinned R annotation archive after a failed conda data hook."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from tools.common import LAB_ROOT, atomic_json, read_json, sha256


def repair(archive: Path, prefix: Path) -> dict:
    lock_path = LAB_ROOT / "environments/r-annotation-lock.json"
    lock = read_json(lock_path)
    if archive.name != lock["filename"] or archive.stat().st_size > 32 * 1024**2:
        raise ValueError("expected annotation filename and archive at most 32 MiB required")
    digest = hashlib.md5(usedforsecurity=False)
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = sha256(archive)
    if digest.hexdigest() != lock["upstream_md5"] or actual_sha256 != lock["sha256"]:
        raise ValueError("annotation archive checksum mismatch")
    prefix = prefix.resolve()
    if not (prefix / "conda-meta/history").is_file():
        raise ValueError("an existing isolated conda prefix is required")
    library = prefix / "lib/R/library"
    environment = {
        **os.environ,
        "R_LIBS": str(library),
        "R_LIBS_USER": str(library),
        "R_LIBS_SITE": str(library),
    }
    commands = [
        [str(prefix / "bin/R"), "CMD", "INSTALL", f"--library={library}", str(archive.resolve())],
        [
            str(prefix / "bin/Rscript"),
            "--vanilla",
            "-e",
            "a<-commandArgs(TRUE);stopifnot(requireNamespace(a[1],quietly=TRUE));"
            "stopifnot(as.character(packageVersion(a[1]))==a[2])",
            lock["package"],
            lock["version"],
        ],
    ]
    for command in commands:
        completed = subprocess.run(
            command, env=environment, capture_output=True, text=True, timeout=180, check=False
        )
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout)[-2000:])
    return {
        "schema_version": "openlabs.biomed_r_annotation_repair.v1",
        "valid": True,
        "package": lock["package"],
        "version": lock["version"],
        "archive_sha256": actual_sha256,
        "lock_sha256": sha256(lock_path),
        "prefix": str(prefix),
        "namespace_and_version_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, default=LAB_ROOT / "environments/bulk-r/.venv")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = repair(args.archive, args.prefix)
        atomic_json(args.output, report)
        print(json.dumps(report))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
