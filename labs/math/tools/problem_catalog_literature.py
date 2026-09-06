"""Bounded arXiv searches with exact query logs, raw Atom and no status promotion."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = Path("registry/math-problems")
IDENTIFIER = r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})"
ARXIV_ID = re.compile(r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(" + IDENTIFIER + r")(v[1-9]\d*)?(?:\.pdf)?")
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}


def parse_feed(raw):
    entries = []
    root = ET.fromstring(raw)
    if root.tag != "{" + NS["a"] + "}feed":
        raise ValueError("arXiv response is not an Atom feed")
    for entry in root.findall("a:entry", NS):
        url = entry.findtext("a:id", "", NS)
        if "api/errors" in url:
            raise ValueError("arXiv API error feed: " + entry.findtext("a:summary", "unspecified error", NS))
        match = ARXIV_ID.fullmatch(url)
        if not match:
            continue
        entries.append({"id": match.group(1), "version_url": url,
            "title": " ".join(entry.findtext("a:title", "", NS).split()),
            "summary": " ".join(entry.findtext("a:summary", "", NS).split()),
            "updated": entry.findtext("a:updated", "", NS),
            "published": entry.findtext("a:published", "", NS),
            "authors": [a.findtext("a:name", "", NS) for a in entry.findall("a:author", NS)],
            "doi": entry.findtext("x:doi", None, NS), "references": [url]})
    return entries


def search_plan(paths, value, fetch, immutable_bytes, atomic_write_json, now):
    path = Path(value)
    path = path if path.is_absolute() else paths.data / path
    if not path.resolve().is_relative_to((paths.data / ROOT / "literature-plans").resolve()) or path.stat().st_size > 1024 * 1024:
        raise ValueError("literature query plan outside bounded catalog plan directory")
    plan = json.loads(path.read_text())
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", plan["plan_id"]) or len(plan["queries"]) > 12:
        raise ValueError("invalid plan ID or too many requests")
    results, last_request = [], None
    for query in plan["queries"]:
        limit = query.get("max_results", 30)
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("query must request 1-100 results")
        params = {"max_results": limit}
        if query.get("id_list"):
            params["id_list"] = ",".join(query["id_list"])
        elif query.get("search_query"):
            params.update(search_query=query["search_query"], sortBy="lastUpdatedDate", sortOrder="descending")
        else:
            raise ValueError("query requires arXiv IDs or search expression")
        endpoint = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
        item = {**query, "endpoint": endpoint, "queried_at": now(), "entries": [],
                "scope": "bibliographic query candidates; no automatic relevance or problem-closure judgment"}
        if last_request is not None:
            time.sleep(max(0, 3.2 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        try:
            raw, provenance = fetch(endpoint, max_bytes=8*1024*1024)
            artifact = Path("math-problem-catalog/literature") / (hashlib.sha256(raw).hexdigest() + ".atom.xml")
            immutable_bytes(paths.artifacts / artifact, raw)
            item["artifact_path"] = str(artifact)
            item["provenance"] = provenance
            item["entries"] = [{**entry, "problem_ids": query.get("problem_ids", []),
                                "query_id": query["query_id"], "relevance": "query_candidate_unassessed",
                                "artifact_path": str(artifact), "provenance": provenance}
                               for entry in parse_feed(raw)]
            item["status"] = "results_returned" if item["entries"] else "no_results"
            item["artifact_path"] = str(artifact)
            item["provenance"] = provenance
            if query.get("id_list"):
                returned = set()
                for entry in item["entries"]:
                    returned.add(entry["id"])
                    match = ARXIV_ID.fullmatch(entry["version_url"])
                    if match and match.group(2):
                        returned.add(entry["id"] + match.group(2))
                item["missing_ids"] = sorted(set(query["id_list"]) - returned)
        except (OSError, ValueError, ET.ParseError) as exc:
            item["status"], item["error"] = "lookup_failed", str(exc)
        results.append(item)
        print(json.dumps({"query_id": query["query_id"], "status": item["status"], "entries": len(item["entries"])}, ensure_ascii=False), flush=True)
    result = {"schema_version": "openlabs.math_literature_search_plan_result.v1", "plan_id": plan["plan_id"],
              "queried_at": now(), "plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "queries": results, "automatically_closes_problems": False}
    # Preserve each run. A failed rerun must not erase an earlier successful search.
    stamp = result["queried_at"].replace(":", "").replace(".", "-").replace("+", "_")
    target = paths.data / ROOT / "literature-searches" / (plan["plan_id"] + "-" + stamp + ".json")
    atomic_write_json(target, result)
    return {"path": str(target.relative_to(paths.data)), "queries": len(results),
            "entries": sum(len(q["entries"]) for q in results),
            "failures": sum(q["status"] == "lookup_failed" for q in results)}
