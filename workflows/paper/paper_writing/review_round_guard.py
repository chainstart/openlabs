"""Deterministic admission checks for a new full review at the same venue."""
from __future__ import annotations

import difflib
import json
import math
import re
from datetime import timedelta
from pathlib import Path

from paper_writing.support import (
    resolve_support_sources, sha256_file, support_sources_digest, support_sources_logical_paths,
)

EVIDENCE_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".parquet", ".fits", ".npy", ".npz",
                     ".ecsv", ".h5", ".hdf5", ".arrow", ".rds", ".mat", ".dat", ".vot"}
NEW_WORK = re.compile(
    r"(?i)\b(?:new|additional|independent|external|fresh)\s+(?:\w+\s+){0,2}"
    r"(?:data(?:set)?s?|calculations?|analys[ie]s|experiments?|simulations?|"
    r"validations?|tests?|observations?|runs?|fits?|checks?|estimates?)\b"
    r"|\b(?:re[- ]?(?:run|fit|compute|analys[ez]e|estimate|calculate)|compute|calculate|"
    r"collect|quantify|simulate|bootstrap)\b"
    r"|\b(?:run|perform|conduct|repeat)\s+(?:\w+\s+){0,3}"
    r"(?:analys[ie]s|tests?|checks?|fits?|simulations?|validations?|experiments?)\b"
    r"|新(?:的)?(?:计算|数据|分析|实验)|(?:重跑|重新计算|补做|重算)"
)


def settings(review):
    hours = review.get("round_cooldown_hours", 3)
    grants = review.get("round_cooldown_overrides", [])
    if type(hours) not in {int, float} or not math.isfinite(hours) or not 0 <= hours <= 8760:
        raise ValueError("review.round_cooldown_hours must be between 0 and 8760")
    if not isinstance(grants, list):
        raise ValueError("review.round_cooldown_overrides must be a list of owner grants")
    for grant in grants:
        if (not isinstance(grant, dict)
                or any(not isinstance(grant.get(key), str) or not grant[key].strip()
                       for key in ("paper_id", "target_journal", "decision_sha256", "actor", "reason"))
                or not re.fullmatch(r"[0-9a-f]{64}", grant["decision_sha256"])):
            raise ValueError("Each review cooldown override needs paper_id, target_journal, "
                             "decision_sha256, actor and reason")
    return {"cooldown_hours": hours, "cooldown_overrides": grants}


def evidence_snapshot(root, pre):
    """Hash the actual registered data files rather than their package or version label."""
    metadata = pre["metadata"]
    publication = (metadata.get("support") or {}).get("publication") or {}
    if not publication.get("source_files"):
        return {}
    return {path.relative_to(root).as_posix(): sha256_file(path)
            for path in resolve_support_sources(metadata, repo_root=root)
            if path.suffix.lower() in EVIDENCE_SUFFIXES}


def artifact_jobs(root, data):
    jobs = {}
    for path in data:
        if Path(path).suffix.lower() != ".json":
            continue
        source = root / path
        if source.stat().st_size > 2_000_000:
            continue
        try:
            payload = json.loads(source.read_text())
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("job_id"), str):
            jobs[path] = payload["job_id"]
    return jobs


def legacy_new_data(root, last, pre, current, raw, jobs):
    """For older decisions, prove additions by reproducing the previous aggregate digest."""
    fingerprints = last.get("fingerprints") or {}
    if "support_sources_sha256" not in fingerprints:
        return {}
    previous = fingerprints["support_sources_sha256"]
    if previous is None:
        return current
    if not current or not raw:
        return {}
    try:
        response = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(response, dict) or not isinstance(response.get("items"), list):
        return {}
    cited = {ref for row in response["items"] if isinstance(row, dict)
             and isinstance(row.get("evidence"), list) for ref in row["evidence"] if isinstance(ref, str)}
    candidates = {p: h for p, h in current.items()
                  if f"sha256:{h}" in cited or (p in jobs and f"job:{jobs[p]}" in cited)}
    if not candidates:
        return {}
    logical = support_sources_logical_paths(pre["metadata"], repo_root=root)
    retained = {name: path for name, path in logical.items()
                if path.relative_to(root).as_posix() not in candidates}
    if support_sources_digest(retained) != previous:
        return {}
    retained_hashes = {sha256_file(path) for path in retained.values()}
    return {p: h for p, h in candidates.items() if h not in retained_hashes}


def new_artifacts(root, last, pre, current, raw, jobs):
    if "round_evidence_files" in last:
        old_hashes = set(last["round_evidence_files"].values())
        new_data = {p: h for p, h in current.items() if h not in old_hashes}
    else:
        new_data = legacy_new_data(root, last, pre, current, raw, jobs)
    old_figures = {row["sha256"] for row in last.get("figure_files", [])}
    new_figures = {row["sha256"] for row in pre.get("figure_files", []) if row["sha256"] not in old_figures}
    return new_data, new_figures if "figure_files" in last else set()


def changed_words(old, new):
    def words(text):
        text = re.sub(r"(?<!\\)%[^\n]*", "", text)
        text = re.sub(r"\\(?:cite\w*|label|ref|includegraphics)(?:\[[^\]]*\])*\{[^}]*\}", "", text)
        text = re.sub(r"\\[A-Za-z]+|[^\w\s]", " ", text.lower())
        return text.split()

    matcher = difflib.SequenceMatcher(None, words(old), words(new))
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes()
               if tag != "equal")


def evidence_location(root, value, hashes, jobs):
    if not isinstance(value, str):
        return False
    if value.startswith("sha256:"):
        return value[7:] in hashes
    if value.startswith("job:"):
        return value[4:] in jobs
    match = re.fullmatch(r"(.+):([1-9][0-9]*)", value)
    if not match or Path(match[1]).is_absolute():
        return False
    try:
        path = (root / match[1]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return False
        with path.open(encoding="utf-8") as handle:
            return any(index == int(match[2]) for index, _ in enumerate(handle, 1))
    except (OSError, ValueError):
        return False


def response_blockers(root, raw, digest, items, needs_work, hashes, jobs, new_hashes, new_jobs):
    if not items and not raw:
        return []
    try:
        letter = json.loads(raw) if raw else None
    except ValueError:
        letter = None
    if not isinstance(letter, dict) or letter.get("decision_sha256", digest) != digest:
        return ["Provide --response with a JSON response bound to decision_sha256"]
    entries = letter.get("items")
    if not isinstance(entries, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("item"), str) for row in entries):
        return ["Response items must be an array of objects with item strings"]
    indexed = {row["item"]: row for row in entries}
    if len(indexed) != len(entries) or set(indexed) - set(items):
        return ["Response items contain duplicate or unknown previous requirements"]
    blockers = []
    for item in items:
        row = indexed.get(item, {})
        status, explanation = row.get("status"), row.get("explanation")
        locations = row.get("evidence", [])
        if status not in ("addressed", "unaddressed", "rebutted") or not isinstance(explanation, str) or not explanation.strip():
            blockers.append(f"Specify addressed, unaddressed or rebutted and explain the handling of {item}")
            continue
        if not isinstance(locations, list) or any(not evidence_location(root, ref, hashes, jobs) for ref in locations):
            blockers.append(f"Supply valid evidence locations for {item}")
            continue
        if status == "rebutted":
            if not locations:
                blockers.append(f"Supply an evidence location for the rebuttal of {item}")
            continue
        if item in needs_work:
            if status != "addressed" or not any(
                    (ref.startswith("sha256:") and ref[7:] in new_hashes)
                    or (ref.startswith("job:") and ref[4:] in new_jobs) for ref in locations):
                blockers.append(f"Cite a new registered data/analysis artifact hash or job for {item}")
        elif status == "addressed" and not locations:
            blockers.append(f"Supply an evidence location for {item}")
    return blockers


def check(root, paper_id, target, last, pre, current, jobs, raw, items, explicit, digest, finished, now, policy):
    problems = []
    cooldown_blocker = None
    hours = policy["cooldown_hours"]
    retry_at = finished + timedelta(hours=hours) if finished is not None else None
    override = None
    if retry_at is None or now < retry_at:
        override = next((grant for grant in policy["cooldown_overrides"]
                         if (grant["paper_id"], grant["target_journal"], grant["decision_sha256"])
                         == (paper_id, target, digest)), None)
        if override is None:
            cooldown_blocker = (f"Cooldown until {retry_at.isoformat()}" if retry_at else
                                "Previous decision time is missing; a scoped owner cooldown grant is required")

    new_data, new_figures = new_artifacts(root, last, pre, current, raw, jobs)
    snapshot = last["_path"].with_name("manuscript-expanded.tex")
    if not snapshot.is_file():
        problems.append("Previous expanded manuscript snapshot is missing")
    old_text = snapshot.read_text() if snapshot.is_file() else None
    words = changed_words(old_text, pre["expanded"]) if old_text is not None else 0
    removed_data = (set(last.get("round_evidence_files", {}).values()) - set(current.values()))
    removed_figures = ({row["sha256"] for row in last.get("figure_files", [])}
                       - {row["sha256"] for row in pre.get("figure_files", [])})
    repeated = old_text == pre["expanded"] and not (new_data or new_figures or removed_data or removed_figures)
    if repeated:
        problems.append("Previous manuscript and evidence snapshot is unchanged")
    else:
        cooldown_blocker = None
        retry_at = None
    needs_work = [item for item in items if explicit.get(item, bool(NEW_WORK.search(item)))]
    current_hashes = set(current.values()) | {row["sha256"] for row in pre.get("figure_files", [])}
    problems.extend(response_blockers(root, raw, digest, items, needs_work, current_hashes,
                                      set(jobs.values()), set(new_data.values()),
                                      {jobs[path] for path in new_data if path in jobs}
                                      - set(last.get("round_evidence_jobs", {}).values())))
    cooldown_only = bool(cooldown_blocker and retry_at and repeated and len(problems) == 1)
    if cooldown_blocker:
        problems.append(cooldown_blocker)
    return {"paper_id": paper_id, "target_journal": target, "previous_decision_sha256": digest, "required_items": items,
            "requires_new_artifact": needs_work, "blockers": problems, "cooldown_only": cooldown_only,
            "changed_words": words, "new_data": new_data, "new_figure_sha256": sorted(new_figures),
            "retry_at": retry_at.isoformat() if retry_at else None, "cooldown_override": override}
