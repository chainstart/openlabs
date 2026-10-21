"""Read bounded public archive metadata or selected members via validated HTTP ranges.

Preserves downloaded ranges; never claims an archive checksum without its full bytes.
"""

import argparse
import concurrent.futures
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import httpx

URLS = {
    "sanger": "https://cog.sanger.ac.uk/cmp/download/essentiality_matrices.zip",
    "broad": "https://cog.sanger.ac.uk/cmp/download/broad_essentiality_matrices_190724.zip",
}


class RemoteArchive(io.RawIOBase):
    def __init__(self, url, root):
        self.client = httpx.Client(timeout=90, trust_env=False)
        self.url = url
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        head = self.client.head(url)
        head.raise_for_status()
        self.size = int(head.headers["Content-Length"])
        self.etag = head.headers["ETag"]
        if self.etag.startswith("W/") or head.headers.get("Accept-Ranges") != "bytes":
            raise ValueError("Strong ETag and range support required")
        self.pos = 0
        self.records = []
        self.total = 0

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else (self.pos if whence == 1 else self.size) + offset
        if not 0 <= self.pos <= self.size:
            raise ValueError("invalid offset")
        return self.pos

    def read(self, size=-1):
        size = self.size - self.pos if size < 0 else min(size, self.size - self.pos)
        if not size:
            return b""
        if self.total + size > 128 * 1024**2:
            raise ValueError("128 MiB range budget exceeded")
        start = self.pos
        end = start + size - 1

        def fetch(bounds):
            left, right = bounds
            wanted = right - left + 1
            content_range = f"bytes {left}-{right}/{self.size}"
            path = self.root / f"range-{left}-{right}.bin"
            inventory_path = self.root.parent / "archive-inventory.json"
            if (
                path.exists()
                and path.stat().st_size == wanted
                and inventory_path.exists()
                and json.loads(inventory_path.read_text())["archive_etag"] == self.etag
            ):
                data = path.read_bytes()
                self.records.append(
                    {
                        "content_range": content_range,
                        "path": str(path),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "cache_reused_under_same_etag": True,
                    }
                )
                return data
            with self.client.stream(
                "GET", self.url, headers={"Range": f"bytes={left}-{right}", "If-Range": self.etag}
            ) as response:
                if (
                    response.status_code != 206
                    or response.headers.get("Content-Range") != content_range
                ):
                    raise ValueError(
                        f"Range contract failed: {response.status_code}, {dict(response.headers)}"
                    )
                if response.headers.get("ETag") != self.etag:
                    raise ValueError("ETag changed")
                chunks = bytearray()
                for chunk in response.iter_bytes(1024 * 256):
                    if len(chunks) + len(chunk) > wanted:
                        raise ValueError("response exceeds requested range")
                    chunks.extend(chunk)
                if len(chunks) != wanted:
                    raise ValueError("response length changed")
                data = bytes(chunks)
            path = self.root / f"range-{left}-{right}.bin"
            path.write_bytes(data)
            self.records.append(
                {
                    "content_range": content_range,
                    "path": str(path),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            if wanted > 1024**2:
                print(json.dumps({"range_complete": content_range, "bytes": wanted}), flush=True)
            return data

        def fetch_retry(bounds):
            for attempt in range(3):
                try:
                    return fetch(bounds)
                except httpx.TransportError as exc:
                    print(
                        json.dumps(
                            {"range_retry": bounds, "attempt": attempt + 1, "error": str(exc)}
                        ),
                        flush=True,
                    )
                    if attempt == 2:
                        raise

        bounds = [
            (left, min(left + 2 * 1024**2 - 1, end)) for left in range(start, end + 1, 2 * 1024**2)
        ]
        if len(bounds) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                data = b"".join(pool.map(fetch_retry, bounds))
        else:
            data = fetch_retry(bounds[0])
        self.total += size
        self.pos += size
        return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--source", choices=URLS, required=True)
    p.add_argument("--member")
    args = p.parse_args()
    remote = RemoteArchive(URLS[args.source], args.root / args.source / "ranges")
    with zipfile.ZipFile(remote) as archive:
        members = [
            {
                "name": m.filename,
                "size": m.file_size,
                "compressed_size": m.compress_size,
                "crc32": m.CRC,
            }
            for m in archive.infolist()
        ]
        result = {
            "source_url": remote.url,
            "archive_size": remote.size,
            "archive_etag": remote.etag,
            "members": members,
        }
        print(json.dumps(result, indent=2), flush=True)
        if args.member:
            item = archive.getinfo(args.member)
            if item.file_size > 256 * 1024**2 or item.compress_size > 120 * 1024**2:
                raise ValueError("member budget exceeded")
            # zipfile validates CRC of the uncompressed member when reading to EOF.
            payload = archive.read(item)
            target = args.root / args.source / Path(item.filename).name
            target.write_bytes(payload)
            result["extracted_member"] = {
                "name": item.filename,
                "path": str(target),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "crc32_validated": True,
            }
    result["retrieved_at_unix"] = time.time()
    result["downloaded_ranges"] = remote.records
    result["full_archive_downloaded"] = False
    result["full_archive_sha256"] = None
    (
        args.root
        / args.source
        / ("member-manifest.json" if args.member else "archive-inventory.json")
    ).write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
