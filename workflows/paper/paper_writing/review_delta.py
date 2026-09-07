"""Cumulative editorial re-review anchored to an immutable full scientific review.

No score is generated here. A fresh process judges the *complete cumulative*
delta and resolves a stable issue list. Syntax checks can require escalation;
passing them never proves semantic equivalence. Old full reviews stay immutable.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

BASELINE = "openlabs.paper_writing.delta_baseline.v1"
PACKET = "openlabs.paper_writing.delta_packet.v1"
RESULT = "openlabs.paper_writing.delta_result.v1"
RECEIPT = "openlabs.paper_writing.delta_receipt.v1"
LIMIT = 64 * 1024 * 1024
FIELD = "review_delta"
CONTEXT_SUFFIXES = {".tex", ".bib", ".bbl", ".cls", ".sty", ".pdf", ".png", ".jpg", ".jpeg", ".eps"}


def require(ok, message):
    if not ok:
        raise ValueError("Delta review: " + message)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def safe_path(root, name):
    require(isinstance(name, str) and bool(name), "missing relative path")
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and ".." not in relative.parts
            and "\\" not in name and relative.as_posix() == name, "unsafe path")
    path = Path(root) / name
    require(path.resolve() == path and path.is_relative_to(root), "symlink or escaping path")
    return path


def read(path):
    require(path.is_file() and path.stat().st_size <= LIMIT, "missing/oversized record")
    def unique(pairs):
        output = {}
        for key, value in pairs:
            require(key not in output, "duplicate JSON key")
            output[key] = value
        return output
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    require(isinstance(value, dict), "record must be an object")
    return value


def binding(path, root):
    safe_path(root, path.relative_to(root).as_posix())
    require(path.stat().st_size <= LIMIT, "oversized binding")
    return {"path": path.relative_to(root).as_posix(), "sha256": digest(path.read_bytes())}


def bound(item, root):
    require(isinstance(item, dict) and set(item) == {"path", "sha256"}, "invalid binding")
    path = safe_path(root, item["path"])
    require(path.is_file() and binding(path, root) == item, "binding changed: " + item["path"])
    return path


def save(value, directory, root):
    content = encoded(value)
    require(len(content) <= LIMIT, "oversized snapshot")
    path = directory / (digest(content) + ".json")
    safe_path(root, path.relative_to(root).as_posix())
    directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == content, "immutable record collision")
    else:
        with path.open("xb") as handle:
            handle.write(content)
    return binding(path, root)


def settings(root):
    from paper_writing.registry import load_registry_settings
    gate = load_registry_settings(root).get("quality_gate", {})
    config = gate.get("incremental_review", {})
    require(isinstance(config, dict), "invalid incremental_review settings")
    return gate, config


def policy(root):
    gate, config = settings(root)
    require(config.get("enabled") is True, "incremental review disabled")
    require(config.get("scope", "editorial_only") == "editorial_only", "unsupported scope")
    require(gate.get("review_panel_size", 1) == 1, "v1 requires a single full reviewer")
    require(gate.get("decision_standard", "cas_zone_1_journal") == "cas_zone_1_journal",
            "v1 requires the CAS journal gate")
    return digest(encoded(gate))


def workspace(paper_id, metadata, root):
    from paper_writing.handoff import _source_files
    from paper_writing.operations import _review_workspace_fingerprints
    manuscript = safe_path(root, metadata.get("manuscript_dir", f"papers/{paper_id}/manuscript"))
    pdf = safe_path(root, metadata.get("latest_pdf", f"papers/{paper_id}/manuscript/main.pdf"))
    require(pdf == manuscript / "main.pdf" and pdf.is_file(), "canonical main.pdf required")
    files = [*_source_files(manuscript, pdf), pdf]
    require(len(files) <= 10000 and sum(p.stat().st_size for p in files) <= LIMIT // 2,
            "snapshot exceeds bounded v1 scope")
    content = {}
    for path in files:
        safe_path(root, path.relative_to(root).as_posix())
        content[path.relative_to(manuscript).as_posix()] = path.read_bytes()
    return content, _review_workspace_fingerprints(paper_id, metadata, root)


def snapshot(content):
    h = hashlib.sha256()
    for name, value in sorted(content.items()):
        h.update(len(name.encode()).to_bytes(8, "big")); h.update(name.encode())
        h.update(len(value).to_bytes(8, "big")); h.update(value)
    return h.hexdigest()


def decode_sources(baseline):
    try:
        content = {name: base64.b64decode(value, validate=True)
                   for name, value in baseline["sources"].items()}
    except (ValueError, TypeError) as exc:
        raise ValueError("Delta review: invalid frozen sources") from exc
    require(snapshot(content) == baseline["fingerprints"]["manuscript_snapshot_sha256"],
            "baseline sources do not reconstruct reviewed snapshot")
    return content


def issue_list(review):
    issues = []
    for index, row in enumerate(review["change_requests"]):
        optional = (review["publishability_summary"]["text_ready"] is True
                    and row.get("priority") == "low" and row["request"].startswith("Optionally "))
        if optional:
            continue
        require(row.get("text_only") is True, "scientific change request requires full review")
        issues.append({"id": f"change:{index}", "request": row["request"],
                       "targets": row.get("targets", [])})
    for index, text in enumerate(review["required_changes"]):
        issues.append({"id": f"required:{index}", "request": text, "targets": []})
    return issues


def validate_baseline(item, paper_id, root):
    from paper_writing.review import validate_review_panel_files, reviewer_role_for_domain
    baseline = read(bound(item, root))
    require(baseline.get("schema_version") == BASELINE and baseline.get("paper_id") == paper_id,
            "baseline identity mismatch")
    require(baseline["policy_sha256"] == policy(root), "review policy changed; full review required")
    review_path = bound(baseline["review"], root)
    review = read(review_path)
    errors = validate_review_panel_files(review, review_path=review_path, repo_root=root,
        expected_paper_id=paper_id, expected_role=reviewer_role_for_domain(baseline["domain"]))
    require(not errors, "invalid full review: " + "; ".join(errors))
    require(review["review_metadata"]["review_panel"]["panel_size"] == 1, "single reviewer required")
    require(review["publishability_summary"]["scientific_ready"] is True
            and not review["unresolved_blockers"], "scientific readiness/blockers forbid delta review")
    gate, _ = settings(root)
    from paper_writing.review import decision_meets_standard_threshold
    require(review["scores"]["overall"] >= float(gate.get("minimum_score", 5)), "baseline score too low")
    require(decision_meets_standard_threshold(
        review["recommendations"]["cas_zone_1_journal"]["decision"],
        gate.get("cas_zone_1_minimum_decision", "minor_revision"), "cas_zone_1_journal", venue_type="journal"),
        "baseline decision below gate")
    issue_list(review)
    content = decode_sources(baseline)
    require(baseline["fingerprints"]["manuscript_snapshot_sha256"] ==
            review["review_metadata"]["manuscript_snapshot_sha256_before"], "baseline review mismatch")
    require(digest(content["main.tex"]) == review["review_metadata"]["main_tex_sha256"], "main.tex mismatch")
    require(type(baseline["full_rounds"]) is int and baseline["full_rounds"] >= 0, "invalid round count")
    return baseline, review


def capture_baseline(paper_id, metadata, root):
    """Called before editing; failure means ordinary full review, never a waiver."""
    root = Path(root).resolve()
    policy_hash = policy(root)
    release = metadata.get("writing_release", {})
    state = release.get(FIELD)
    if state:
        validate_state(paper_id, state, metadata, root, require_ready=False)
        return state
    content, fingerprints = workspace(paper_id, metadata, root)
    review_path = safe_path(root, metadata.get("ara_llm_self_review", {}).get("source"))
    require(release.get("manuscript_snapshot_sha256") == fingerprints["manuscript_snapshot_sha256"]
            and release.get("manuscript_version") == metadata["version"], "full review is not current")
    require(all(release.get(k) == value for k, value in fingerprints.items()),
            "reviewed metadata/support fingerprint is stale")
    baseline = {"schema_version": BASELINE, "paper_id": paper_id, "domain": metadata["domain"],
        "version": metadata["version"], "policy_sha256": policy_hash,
        "review": binding(review_path, root), "full_rounds": release.get("revision_rounds_completed"),
        "fingerprints": fingerprints,
        "sources": {k: base64.b64encode(v).decode() for k, v in content.items()}}
    item = save(baseline, root / "reviews/delta-baselines" / paper_id, root)
    validate_baseline(item, paper_id, root)
    return {"baseline": item, "history": []}


# Deliberately conservative syntactic tripwires. A fresh referee must still
# assess scientific meaning, attribution, and downstream impact for every hunk.
PROTECTED = re.compile(r"\\(?:begin|end)\{(?:theorem|lemma|proposition|corollary|proof|definition|assumption|equation\*?|align\*?|gather\*?)\}|\$[^$]*\$|\\\[.*?\\\]|\\\(.*?\\\)", re.S)
ENV = re.compile(r"\\begin\{(theorem|lemma|proposition|corollary|proof|definition|assumption|equation\*?|align\*?|gather\*?)\}.*?\\end\{\1\}", re.S)
GLOBAL = re.compile(r"\\(?:newcommand|renewcommand|providecommand|def|gdef|let|input|include|includegraphics|usepackage|documentclass|catcode|csname|write18)\b")
QUANTIFIERS = re.compile(r"\b(?:all|every|each|any|some|exists?|forall|only|not|never|at\s+least|at\s+most|if|unless|assuming|assume|hypothesis|hypotheses)\b", re.I)


def dependency_reasons(content):
    """V1 refuses unbound/dynamic scientific inputs, even if the import line is unchanged."""
    reasons = []
    imports = re.compile(r"\\(input|include|includegraphics|bibliography|addbibresource)\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}")
    for name, value in content.items():
        if PurePosixPath(name).suffix != ".tex":
            continue
        source = value.decode("utf-8")
        if re.search(r"\\(?:openin|read|IfFileExists|inputminted|lstinputlisting)\b", source):
            reasons.append(f"dynamic/external input needs full review: {name}")
        if len(re.findall(r"\\(?:input|include|includegraphics|bibliography|addbibresource)\b", source)) != len(imports.findall(source)):
            reasons.append(f"unresolved TeX input syntax: {name}")
        for kind, argument in imports.findall(source):
            for target in argument.split(","):
                path = PurePosixPath(target.strip())
                if path.is_absolute() or ".." in path.parts or "\\" in target:
                    reasons.append(f"unbound TeX input: {name}: {target}"); continue
                extensions = ("", ".tex") if kind in {"input", "include"} else ("", ".bib") if kind in {"bibliography", "addbibresource"} else ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps")
                if not any(str(prefix / (str(path) + ext)) in content for prefix in (PurePosixPath("."), PurePosixPath(name).parent) for ext in extensions):
                    reasons.append(f"missing bound TeX input: {name}: {target}")
    return sorted(set(reasons))


def scope_reasons(before, after):
    reasons = []
    if set(before) != set(after):
        reasons.append("source files added or deleted")
    for name in sorted(set(before) & set(after)):
        if before[name] == after[name] or name == "main.pdf":
            continue
        if PurePosixPath(name).suffix not in {".tex", ".bib", ".bbl"}:
            reasons.append(f"non-editorial input changed: {name}"); continue
        try:
            old, new = before[name].decode(), after[name].decode()
        except UnicodeDecodeError:
            reasons.append(f"non-UTF8 input: {name}"); continue
        if PurePosixPath(name).suffix == ".tex":
            if [m.group() for m in ENV.finditer(old)] != [m.group() for m in ENV.finditer(new)] or PROTECTED.findall(old) != PROTECTED.findall(new):
                reasons.append(f"mathematical statement, proof or formula changed: {name}")
            for tag, i, j, k, l in difflib.SequenceMatcher(None, old.splitlines(), new.splitlines(), autojunk=False).get_opcodes():
                if tag == "equal":
                    continue
                a, b = "\n".join(old.splitlines()[i:j]), "\n".join(new.splitlines()[k:l])
                if GLOBAL.search(a + "\n" + b):
                    reasons.append(f"global TeX/dependency change: {name}")
                # Compare changed-line quantifiers, retaining newlines as whitespace.
                if QUANTIFIERS.findall(a.casefold()) != QUANTIFIERS.findall(b.casefold()):
                    reasons.append(f"assumption/quantifier change: {name}")
    return sorted(set(reasons))


def prepare_delta(paper_id, *, root):
    from paper_writing.registry import load_paper_metadata
    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    state = metadata.get("writing_release", {}).get(FIELD)
    packet = build_packet(paper_id, metadata, state, root)
    return {"packet": packet, "binding": save(packet, root / "reviews/delta-packets" / paper_id, root)}


def build_packet(paper_id, metadata, state, root):
    require(isinstance(state, dict), "no frozen baseline; start revision before editing")
    baseline, review = validate_baseline(state["baseline"], paper_id, root)
    history, extra_issues = validate_history(state, baseline, root)
    require(not history or history[-1]["result"]["verdict"] != "escalate", "previous reviewer required full review")
    content, fingerprints = workspace(paper_id, metadata, root)
    before = decode_sources(baseline)
    reasons = scope_reasons(before, content) + dependency_reasons(before) + dependency_reasons(content)
    for key in ("registry_review_content_sha256", "support_sources_sha256"):
        if fingerprints[key] != baseline["fingerprints"][key]:
            reasons.append(key + " changed")
    from paper_writing.revision_policy import delta_round_policy
    rounds = delta_round_policy(paper_id, metadata, settings(root)[0], baseline["full_rounds"], len(history) + 1, root=root)
    require(not reasons, "full review required: " + "; ".join(reasons))
    changes = []
    for name in sorted(before):
        if before[name] == content[name] or name == "main.pdf":
            continue
        old, new = before[name].decode(), content[name].decode()
        changes.append({"path": name, "before_sha256": digest(before[name]), "after_sha256": digest(content[name]),
            "diff": "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="old/" + name, tofile="new/" + name, n=12))})
    packet = {"schema_version": PACKET, "paper_id": paper_id, "baseline": state["baseline"],
        "history": state["history"], "version": metadata["version"], "policy_sha256": policy(root),
        "fingerprints": fingerprints, "rounds": rounds,
        "source_hashes": {k: digest(v) for k, v in content.items()},
        "changes": changes, "issues": issue_list(review) + extra_issues}
    return packet


def check_result(result, packet):
    require(set(result) == {"schema_version", "packet_sha256", "verdict", "scientific_content_unchanged",
        "changes", "issues", "new_blockers", "optional_suggestions", "build_check", "visual_check"}, "invalid result fields")
    require(result["schema_version"] == RESULT and result["packet_sha256"] == digest(encoded(packet)), "result packet mismatch")
    require(result["verdict"] in {"resolved", "unresolved", "escalate"}, "invalid verdict")
    require(type(result["scientific_content_unchanged"]) is bool, "semantic judgment missing")
    for field, key, expected in (("changes", "path", [r["path"] for r in packet["changes"]]),
                                 ("issues", "id", [r["id"] for r in packet["issues"]])):
        rows = result[field]
        require(isinstance(rows, list) and [r.get(key) for r in rows] == expected, "incomplete " + field)
        for row in rows:
            require(set(row) == {key, "status", "evidence"} and row["status"] in {"resolved", "unresolved", "escalate"}
                    and isinstance(row["evidence"], str) and bool(row["evidence"].strip()), "missing concrete resolution evidence")
    for field in ("new_blockers", "optional_suggestions"):
        require(isinstance(result[field], list) and all(isinstance(x, str) and x.strip() for x in result[field]), "invalid " + field)
    for field in ("build_check", "visual_check"):
        row = result[field]
        require(isinstance(row, dict) and set(row) == {"status", "evidence"}
                and row["status"] in {"PASS", "FAIL", "UNVERIFIED"}
                and isinstance(row["evidence"], str) and row["evidence"].strip(), "missing " + field)
    if result["verdict"] == "resolved":
        require(result["scientific_content_unchanged"] and not result["new_blockers"]
                and all(r["status"] == "resolved" for field in ("changes", "issues") for r in result[field])
                and all(result[f]["status"] == "PASS" for f in ("build_check", "visual_check")), "unresolved work cannot pass")
    require(result["scientific_content_unchanged"] or result["verdict"] == "escalate", "scientific change must escalate")
    if any(r["status"] == "escalate" for field in ("changes", "issues") for r in result[field]):
        require(result["verdict"] == "escalate", "an escalated finding requires full review")


def validate_receipt(item, root):
    receipt = read(bound(item, root))
    require(receipt.get("schema_version") == RECEIPT, "invalid runtime receipt")
    packet = read(bound(receipt["packet"], root))
    result = read(bound(receipt["output"], root))
    require(type(receipt["exit_code"]) is int and receipt["exit_code"] == 0 and receipt["ephemeral"] is True
            and receipt["author_conversation_supplied"] is False
            and receipt["prior_scores_supplied"] is False
            and receipt["prior_issue_list_supplied"] is True
            and "--ephemeral" in receipt["command"] and "resume" not in receipt["command"], "fresh runtime evidence required")
    require(receipt["snapshot_before"] == receipt["snapshot_after"] == packet["fingerprints"]["manuscript_snapshot_sha256"], "snapshot changed during review")
    for field in ("prompt", "events", "stderr"):
        bound(receipt[field], root)
    build = read(bound(receipt["build"], root))
    require(build.get("schema_version") == "openlabs.paper_writing.delta_build.v1"
            and build.get("status") == "PASS" and type(build.get("exit_code")) is int
            and build["exit_code"] == 0 and build.get("canonical_text_matches_clean_build") is True
            and build.get("snapshot_sha256") == receipt["snapshot_before"], "matching clean build required")
    for field in ("log", "canonical_pdf", "rebuilt_pdf"):
        bound(build[field], root)
    require(build["canonical_pdf"]["sha256"] == packet["source_hashes"]["main.pdf"], "build PDF mismatch")
    require(receipt.get("inputs_unchanged") is True and isinstance(receipt.get("input_hashes"), dict)
            and bool(receipt["input_hashes"]), "frozen reviewer input manifest required")
    inputs = bound(receipt["prompt"], root).parent / "inputs"
    actual_inputs = {p.relative_to(inputs).as_posix(): binding(p, root)["sha256"]
                     for p in inputs.rglob("*") if p.is_file()}
    require(actual_inputs == receipt["input_hashes"], "reviewer context changed")
    expected_input = {key: packet[key] for key in ("paper_id", "version", "changes", "issues")}
    expected_input["packet_sha256"] = receipt["packet"]["sha256"]
    require(read(inputs / "delta.json") == expected_input, "reviewer received a different delta/issue list")
    baseline = read(bound(packet["baseline"], root))
    old_hashes = {k: digest(v) for k, v in decode_sources(baseline).items()}
    for side, hashes in (("old", old_hashes), ("new", packet["source_hashes"])):
        expected_context = {side + "/" + name: sha for name, sha in hashes.items()
                            if PurePosixPath(name).suffix in CONTEXT_SUFFIXES}
        require({k: v for k, v in actual_inputs.items() if k.startswith(side + "/")} == expected_context,
                "reviewer manuscript context differs from bound sources")
    require(isinstance(receipt.get("model"), str) and receipt["model"].strip(), "actual model missing")
    check_result(result, packet)
    return {"receipt": receipt, "packet": packet, "result": result}


def validate_history(state, baseline, root):
    require(set(state) == {"baseline", "history"} and isinstance(state["history"], list)
            and len(state["history"]) <= 32, "invalid/bounded history")
    history, extra = [], []
    original_issues = issue_list(read(bound(baseline["review"], root)))
    for index, item in enumerate(state["history"]):
        require(not history or history[-1]["result"]["verdict"] != "escalate", "scientific escalation cannot be bypassed")
        checked = validate_receipt(item, root)
        packet = checked["packet"]
        require(packet["schema_version"] == PACKET and packet["paper_id"] == baseline["paper_id"]
                and packet["baseline"] == state["baseline"] and packet["history"] == state["history"][:index]
                and packet["policy_sha256"] == baseline["policy_sha256"], "broken delta chain")
        require(packet["issues"] == original_issues + extra, "historical issue coverage changed")
        for n, text in enumerate(checked["result"]["new_blockers"]):
            extra.append({"id": f"delta:{index}:{n}", "request": text, "targets": []})
        history.append(checked)
    return history, extra


def validate_state(paper_id, state, metadata, root, *, require_ready):
    baseline, review = validate_baseline(state["baseline"], paper_id, root)
    history, _ = validate_history(state, baseline, root)
    require(bool(history), "no completed delta review")
    latest = history[-1]
    # Reconstruct preparation with all preceding receipts; compare every field.
    from paper_writing.registry import load_paper_metadata
    current = load_paper_metadata(paper_id, root)
    require(current.get("writing_release", {}).get(FIELD) == state, "registry state mismatch")
    content, fingerprints = workspace(paper_id, metadata, root)
    packet = latest["packet"]
    expected = build_packet(paper_id, metadata,
        {"baseline": state["baseline"], "history": state["history"][:-1]}, root)
    require(packet == expected, "incomplete cumulative diff or issue resolutions")
    require(packet["fingerprints"] == fingerprints and packet["version"] == metadata["version"]
            and packet["source_hashes"] == {k: digest(v) for k, v in content.items()}, "current inputs differ from delta review")
    require(not scope_reasons(decode_sources(baseline), content), "cumulative scope changed")
    for key in ("registry_review_content_sha256", "support_sources_sha256"):
        require(fingerprints[key] == baseline["fingerprints"][key], "evidence/metadata changed")
    from paper_writing.revision_policy import delta_round_policy
    counts = delta_round_policy(paper_id, metadata, settings(root)[0], baseline["full_rounds"], len(history), root=root)
    require(packet["rounds"] == counts, "stale round budget")
    release = metadata["writing_release"]
    if require_ready:
        require(latest["result"]["verdict"] == "resolved" and release["status"] == "ready", "delta not resolved")
        require(release["score"] == review["scores"]["overall"] and release["decision"] == review["recommendations"]["cas_zone_1_journal"]["decision"], "old score/decision altered")
        require(release["revision_rounds_completed"] == counts["total"] and release["max_revision_rounds"] == counts["maximum"], "release round count changed")
        require(not release.get("unresolved_review_blockers"), "release blockers remain")
        require(metadata.get("ara_llm_self_review", {}).get("source") == baseline["review"]["path"], "full review projection was replaced")
        require(all(release.get(k) == value for k, value in fingerprints.items())
                and release.get("reviewed_at") == review["review_metadata"]["reviewed_at_utc"], "release fingerprints/full review timestamp changed")
        deterministic_checks(paper_id, root)
    paths = [bound(state["baseline"], root), bound(baseline["review"], root)]
    for record in review["review_metadata"]["review_panel"]["reviewer_records"]:
        paths.append(bound({"path": record["source"], "sha256": record["sha256"]}, root))
    for item, checked in zip(state["history"], history):
        paths.append(bound(item, root))
        # Freeze review records in Git. Rebuildable renders, PDFs and execution
        # logs remain private runtime artifacts: validate_receipt verifies every
        # bound byte at each release check without requiring them in Git.
        for field in ("packet", "output", "prompt"):
            paths.append(bound(checked["receipt"][field], root))
        build_path = bound(checked["receipt"]["build"], root)
        paths.append(build_path)
    return paths


def deterministic_checks(paper_id, root):
    from paper_writing.manuscript_style import audit_manuscript_style, manuscript_style_blockers
    from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers
    gate, _ = settings(root)
    blockers = support_audit_blockers(audit_manuscript_support(paper_id, root=root))
    if gate.get("require_manuscript_style_check", False):
        blockers += manuscript_style_blockers(audit_manuscript_style(paper_id, root=root,
            require_ai_declaration=gate.get("require_ai_use_declaration", True)))
    require(not blockers, "deterministic checks failed: " + "; ".join(blockers))


def apply_delta(paper_id, *, receipt, root):
    from paper_writing.registry import load_paper_metadata, write_paper_metadata
    from paper_writing.revision_policy import EXCEPTION_FIELD, revision_round_policy
    root = Path(root).resolve()
    item = binding(safe_path(root, receipt), root)
    checked = validate_receipt(item, root)
    prepared = prepare_delta(paper_id, root=root)
    require(checked["packet"] == prepared["packet"], "receipt does not cover current complete delta")
    deterministic_checks(paper_id, root)
    metadata = load_paper_metadata(paper_id, root)
    state = metadata["writing_release"][FIELD]
    baseline, review = validate_baseline(state["baseline"], paper_id, root)
    packet, result = checked["packet"], checked["result"]
    passed = result["verdict"] == "resolved"
    gate, _ = settings(root)
    maximum, exception = revision_round_policy(paper_id, metadata, gate, root=root)
    state = {"baseline": state["baseline"], "history": state["history"] + [item]}
    release = {"status": "ready" if passed else "blocked" if packet["rounds"]["total"] >= maximum else "revision_required",
        "target_score": float(gate.get("minimum_score", 5)), "score": review["scores"]["overall"],
        "venue_type": "journal", "decision_standard": "cas_zone_1_journal",
        "decision": review["recommendations"]["cas_zone_1_journal"]["decision"],
        "minimum_decision": gate.get("cas_zone_1_minimum_decision", "minor_revision"),
        "revision_rounds_completed": packet["rounds"]["total"], "max_revision_rounds": maximum,
        "revision_rounds_at_full_baseline": baseline["full_rounds"], "delta_review_rounds_completed": len(state["history"]),
        "reviewed_at": review["review_metadata"]["reviewed_at_utc"],
        "manuscript_version": metadata["version"], **packet["fingerprints"], FIELD: state}
    support_sha = metadata.get("support", {}).get("publication", {}).get("package_sha256")
    if support_sha:
        release["support_package_sha256"] = support_sha
    if exception:
        release[EXCEPTION_FIELD] = exception
    if not passed:
        release["unresolved_review_blockers"] = result["new_blockers"] or ["Incremental review " + result["verdict"]]
    metadata["writing_release"] = release
    metadata["status_updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    write_paper_metadata(paper_id, metadata, root)
    return {"paper_id": paper_id, "passed": passed, "status": release["status"], "scores_changed": False,
            "review_scope": "cumulative_editorial_delta", "quality_gate": release}


def route_review(paper_id, *, root):
    """One routing entry point shared by CLI and reviewer-task instructions."""
    from paper_writing.operations import reuse_review_for_metadata_only_revision
    from paper_writing.registry import load_paper_metadata
    from paper_writing.revision_policy import ReviewBudgetExceeded
    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    # Never let the older metadata mechanism carry an unvalidated delta chain.
    try:
        reused = reuse_review_for_metadata_only_revision(paper_id, root=root)
        return {"route": "metadata_reuse", "result": reused}
    except (ValueError, OSError):
        pass
    try:
        prepared = prepare_delta(paper_id, root=root)
        return {"route": "delta", "packet": prepared["binding"]}
    except ReviewBudgetExceeded as exc:
        return {"route": "blocked", "reason": str(exc)}
    except (ValueError, OSError, KeyError) as exc:
        return {"route": "full", "reason": str(exc)}
