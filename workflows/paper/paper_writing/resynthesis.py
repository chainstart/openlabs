"""Replay a bound review under the current gate without launching review roles."""

import difflib
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from paper_writing import formal_checks as formal, review_flow as flow

RULE_VERSION = "materiality_v1/archive_replay_v1"
INPUT_FINGERPRINTS = ("registry_review_content_sha256", "support_sources_sha256")
_ARCHIVE_ERRORS = (ValueError, OSError, KeyError, IndexError, TypeError)


def _basis(root, paper_id, path):
    if not path.is_absolute():
        path = root / path
    if path.is_dir():
        path /= "decision.json"
    path = path.resolve()
    if path.parent.parent != flow.runs_dir(root, paper_id).resolve() or path.name != "decision.json":
        raise ValueError("Use a decision from this paper's unified review archive")
    raw = path.read_bytes()
    base = json.loads(raw)
    if (base.get("paper_id") != paper_id or base.get("run_id") != path.parent.name
            or base.get("process") != flow.PROCESS or base.get("stage_reached") != "decision"
            or base.get("review_mode", "full") != "full"):
        raise ValueError("Use an original completed unified decision for this paper")
    return base | {"_path": path}, flow._sha256(raw)


def _text(record, key):
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Provide a nonempty {key}")
    return value


def change_inventory(old, new):
    """Identify exact changed source paragraphs, with stable IDs for the reply."""
    before, after = (re.split(r"(\n[ \t]*\n)", source) for source in (old, new))
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    edits = [(i, j, k, l) for tag, i, j, k, l in matcher.get_opcodes() if tag != "equal"]
    return [dict(id=f"change-{index}", before="".join(before[i:j]), after="".join(after[k:l]))
            for index, (i, j, k, l) in enumerate(edits, 1)]


def _check_changes(old, new, response, items):
    changes = change_inventory(old, new)
    rows = response.get("changes", [])
    if not isinstance(rows, list) or len(rows) != len(changes):
        raise ValueError("Provide one response entry for every changed source paragraph group")
    for change, row in zip(changes, rows):
        if (not isinstance(row, dict) or any(row.get(key) != value for key, value in change.items())
                or row.get("item") not in items):
            raise ValueError(f"{change['id']} must quote the exact edit and name an archived review item")
        _text(row, "author_response")
        _text(row, "verification")
        before, after = change["before"], change["after"]
        if flow.substantive_parts(before)["numbers"] != flow.substantive_parts(after)["numbers"]:
            raise ValueError(f"{change['id']} changes numeric results or other non-reference numbers")
    main = [text.split(r"\appendix", 1)[0] for text in (old, new)]
    main_reasons = flow.substantive_delta(*main, reviewed_deletions=True)["reasons"]
    full_reasons = flow.substantive_delta(old, new, reviewed_deletions=True)["reasons"]
    return list(dict.fromkeys(
        [reason for reason in main_reasons if "of lines changed" not in reason]
        + [reason for reason in full_reasons if not reason.startswith("conclusion-bearing sections changed:")]))


def _replay(paper_id, root, base, basis_sha, response, metadata, current, *, as_basis=False, notes=None):
    from paper_writing import rebuttal
    from paper_writing.operations import _review_workspace_fingerprints

    if not isinstance(response, dict):
        raise ValueError("The response must be a JSON object")
    if response.get("decision_sha256") != basis_sha or response.get("manuscript_sha256") != flow._sha256(current.encode()):
        raise ValueError("Reply must bind decision_sha256 and manuscript_sha256 to the archived and current source")
    _text(response, "explanation")
    flow._check_recheck_preregistration(metadata, response)
    config = flow.policy_for_record(base, flow.review_config(root))
    history_policy = flow.rejection_history_policy(metadata, root, paper_id)
    round_limit = flow.review_round_limit_override(metadata, root, paper_id)
    track = flow.review_track(metadata, root)
    history = flow.rejection_clearance_blockers(base["editor_screen"], base.get("prior_decisions", []), history_policy)
    # Sustained factual rebuttals (rebuttal.py) withdraw single archived blockers in memory.
    withdrawn, reasons, rebuttal_notes = rebuttal.sustained(root, paper_id, base, basis_sha,
                                                            response.get("rebuttals", []))
    if notes is not None:
        notes["rebuttals"] = rebuttal_notes
    view = rebuttal.withdrawn_view(base, withdrawn)
    pre = {"metadata": metadata, "journal_response": flow._journal_response_packet(metadata, root, paper_id),
           "active_revision_context": flow.active_revision_context(metadata, root)}
    reasons += flow._delta_context_reasons(base, pre, config, track, root, history_policy, round_limit)
    target = metadata.get("target_conference" if metadata.get("venue_type") == "conference" else "target_journal")
    if base["target_journal"] != target:
        reasons.append("The target venue changed")
    if any(row["_path"] > base["_path"] and row.get("review_mode", "full") == "full"
           and row["stage_reached"] == "decision"
           for row in flow.completed_rounds(root, paper_id, base["target_journal"])):
        reasons.append("A later full decision supersedes this archive")
    fingerprints = _review_workspace_fingerprints(paper_id, metadata, root)
    for key in INPUT_FINGERPRINTS:
        if key not in base["fingerprints"] or fingerprints[key] != base["fingerprints"][key]:
            reasons.append(f"Reviewed inputs changed: {key}")
    old, _ = flow._formal_recheck_baseline(base)
    binding = base["formal_check"]
    errors = formal.validate_binding(binding, metadata, root, flow.formal_role(config["roles"]),
                                     archived_version=base["manuscript_version"])
    if errors:
        raise ValueError("\n".join(errors))
    report = json.loads(formal._safe_file(root, binding["path"]).read_bytes())
    if not as_basis:  # The delta review verifies its own current inputs.
        old_docs, old_bib = formal.archived_inputs(report, root)
        documents, bibliography = formal.current_inputs(metadata, root)
        if old_bib != bibliography:
            reasons.append("Printed bibliography changed; independent reference verification is required")
        if [doc["id"] for doc in old_docs] != [doc["id"] for doc in documents]:
            reasons.append("Formal verification document list changed")
        inventory = formal.inventory(documents, bibliography)
        reasons.extend(formal.local_route_preflight(
            formal.verification_source_metadata(metadata, inventory), inventory, root))

    findings = report["issue_summary"]["raw_findings"]
    annotations = response.get("formal_findings", {})
    if not isinstance(annotations, dict):
        raise ValueError("formal_findings must map archived finding IDs to materiality explanations")
    eligible = {f"formal-{index}": finding for index, finding in enumerate(findings, 1)
                if finding["category"] == "scientific" and finding.get("status") == "gap"
                and not (report["inventory"].get("followup") or report["inventory"].get("materiality"))}
    if set(annotations) - set(eligible):
        raise ValueError("Only legacy scientific gaps without a recorded materiality judgment can be annotated")
    revised = []
    archived_science = flow._recorded_merge(view, history)
    items = {change["change"] for change in archived_science.get("required_changes", [])}
    items.update(item["item"] for item in archived_science.get("unresolved_previous_items", []))
    items.update(withdrawn)
    for index, finding in enumerate(findings, 1):
        item = f"formal-{index}"
        items.add(item)
        note = annotations.get(item)
        if note is not None:
            if not isinstance(note, dict) or note.get("reader_misconclusion") != "":
                raise ValueError(f"{item} needs an explicit empty reader_misconclusion to classify as advice")
            revised.append(dict(finding, category="advisory", reason=_text(note, "evidence")))
        else:
            revised.append(finding)
    reasons.extend(_check_changes(old.decode(), current, response, items))

    summary = formal.issue_summary(revised)
    blockers = [m for category, messages in summary["by_category"].items()
                if category != "advisory" for m in messages]
    editor, referees = view["editor_screen"], view["referee_reports"]
    if editor.get("review_standard") != "materiality_v1" and "followup_items" not in base:
        # Legacy findings have no structured account of the wrong conclusion.
        # Carry the scientific judgment below, and feed its advice into the
        # current synthesizer without altering the archived reports.
        def materiality_view(report):
            return dict(report, dimension_repairs={}, review_standard="materiality_v1",
                        previous_items=[], optional_suggestions=report.get("optional_suggestions", []))

        editor = materiality_view(editor)
        referees = {name: materiality_view(report) for name, report in referees.items()}
    merged = flow.apply_review_track(flow.merge(
        editor, referees, history, formal_blockers=blockers, formal_summary=summary,
        followup_items=base.get("followup_items")), referees, track)
    # Legacy prose without structured materiality retains its original scientific weight.
    old_merged = base["merged"]
    rebutted = (old_merged.get("outcome") == "revision_required" and bool(withdrawn)
                and {item["text"] for item in rebuttal.blocking_items(old_merged)} <= set(withdrawn))
    if ((old_merged.get("outcome") not in {"ready", "formal_check_blocked"} and not rebutted)
            or archived_science["outcome"] != "ready"):
        reasons.extend(archived_science.get("scientific_blockers") or
                       [f"The archived scientific judgments require {archived_science['outcome']}"])
    # Preserve legacy verdicts on journal fit and editorial clearance.
    if not base.get("followup_items") and base["editor_screen"]["decision"] != "send_to_review":
        reasons.append("The archived editor did not clear the manuscript for referee review")
    if any(not change.get("advisory") and change.get("referee") == "delivery_reader"
           for change in old_merged.get("required_changes", [])) or old_merged.get("technical_blockers"):
        reasons.append("Archived delivery reader or technical blockers still require verification")
    if any((r.get("formal_check_assessment") or {}).get("coverage_complete") is not True
           for r in base["referee_reports"].values()):
        reasons.append("The archived referees did not confirm scientific coverage")
    if merged["outcome"] != "ready":
        reasons.extend(blockers or merged.get("scientific_blockers") or
                       [f"Archived judgments require {merged['outcome']}"])
    merged["required_changes"] += [change for change in old_merged.get("required_changes", [])
                                    if change.get("referee") == "delivery_reader" and change.get("advisory")]
    advice = [dict(referee="formal", change=row["message"], location=row["location"],
                   evidence=row["reason"]) for row in revised if row["category"] == "advisory"]
    merged["advisory_items"] = [item for item in merged.get("advisory_items", [])
                                if item["referee"] != "formal"] + advice
    return merged, reasons, fingerprints, config, history_policy, round_limit


def run(paper_id, *, root, decision, response, actor, reason, apply=True):
    """Record an operator's bound replay and apply it through the unified decision gate."""
    _text({"actor": actor}, "actor")
    _text({"reason": reason}, "reason")
    return flow._locked_review(paper_id, root, _run, decision=Path(decision),
                               response=Path(response), actor=actor, reason=reason, apply=apply)


def _run(paper_id, *, root, decision, response, actor, reason, apply):
    base, basis_sha = _basis(root, paper_id, decision)
    metadata = flow.load_paper_metadata(paper_id, root)
    raw = response.read_bytes()
    target = base["target_journal"]
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = flow.runs_dir(root, paper_id) / started
    sequence = 0
    while directory.exists():
        sequence += 1
        directory = directory.with_name(f"{started}-{sequence:04d}")
    directory.mkdir()
    record = {key: value for key, value in base.items() if key != "_path"}
    record.update(receipts_from_run=base["run_id"], run_id=directory.name, review_mode="resynthesize",
                  consumes_scientific_round=False, round_count_basis="archived review replay",
                  round_for_target=len(flow.scientific_rounds(root, paper_id, target)),
                  stage_reached="decision", manuscript_version=str(metadata.get("version") or ""),
                  resynthesis={"actor": actor, "reason": reason, "rule_version": RULE_VERSION,
                               "basis_decision": base["_path"].relative_to(root).as_posix(),
                               "basis_decision_sha256": basis_sha, "response_sha256": flow._sha256(raw)})
    (directory / "resynthesis-response.json").write_bytes(raw)
    try:
        response = json.loads(raw)
        with tempfile.TemporaryDirectory(prefix="review-resynthesis-") as scratch:
            pre = flow.preflight(paper_id, root, Path(scratch), update_manuscript=False)
        current = pre["expanded"]
        (directory / "manuscript-expanded.tex").write_text(current)
        notes = {}
        merged, reasons, fingerprints, config, history, limit = _replay(
            paper_id, root, base, basis_sha, response, metadata, current, notes=notes)
        if notes.get("rebuttals"):
            record["resynthesis"]["rebuttals"] = notes["rebuttals"]
        reasons.extend(pre["blockers"])
        if ("figure_files" not in base or flow.figure_changes(base, pre)
                or any(a["code"] == "FIGURE-FILES-UNREADABLE" for a in pre["preparation_advisories"])):
            reasons.append("Reviewed figure files changed or cannot be compared")
        if pre["fingerprints"] != fingerprints:
            reasons.append("Review inputs changed during resynthesis")
        record.update(fingerprints=fingerprints, figure_files=pre["figure_files"],
                      build_inputs=pre["build_inputs"], preparation_advisories=pre["preparation_advisories"],
                      body_length=flow.body_length_block(paper_id, root),
                      review_policy_sha256=flow.review_policy_sha256(config, history, limit))
    except _ARCHIVE_ERRORS as exc:
        reasons = [str(exc)]
    if reasons:
        record.update(stage_reached="delta_check")
        merged = dict(outcome="full_review_required", next_action="full_review", full_review_reasons=reasons)
    record.update(merged=merged, finished_at=flow._now(),
                  letter="\n".join(reasons or [f"Archived review resynthesized by {actor}.", reason]))
    path = directory / "decision.json"
    staged = directory / "decision.json.pending"
    digest = flow._json_dump(staged, record)
    staged.replace(path)
    if apply and merged["outcome"] == "ready":
        flow.apply_decision(paper_id, root=root, decision_path=path, digest=digest)
    return record | {"run_dir": str(directory.relative_to(root)), "decision_sha256": digest}


def validate(record, path, root, metadata, *, as_basis=False):
    """Check the replay receipts at apply and delivery, including the original formal evidence."""
    if record.get("review_mode") != "resynthesize":
        return []
    try:
        proof = record["resynthesis"]
        if proof["rule_version"] != RULE_VERSION:
            raise ValueError("Resynthesis rule version changed")
        _text(proof, "actor")
        _text(proof, "reason")
        paper_id = metadata["paper_id"]
        base, basis_sha = _basis(root, paper_id, Path(proof["basis_decision"]))
        if basis_sha != proof["basis_decision_sha256"]:
            raise ValueError("Archived decision changed")
        raw = (path.parent / "resynthesis-response.json").read_bytes()
        if flow._sha256(raw) != proof["response_sha256"]:
            raise ValueError("Archived response changed")
        manuscript = root / str(metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript")
        current = (path.parent / "manuscript-expanded.tex").read_text()
        if not as_basis and current != flow.expanded_review_documents(manuscript):
            raise ValueError("The resynthesized manuscript snapshot changed")
        merged, reasons, fingerprints, _, _, _ = _replay(
            paper_id, root, base, basis_sha, json.loads(raw), metadata, current, as_basis=as_basis)
        if reasons:
            return reasons
        for key in ("editor_screen", "referee_reports", "formal_check", "prior_decisions", "receipts"):
            if base.get(key) != record.get(key):
                raise ValueError(f"Archived {key} differs from the replay")
        keys = INPUT_FINGERPRINTS if as_basis else fingerprints.keys()
        if merged != record["merged"] or any(fingerprints[key] != record["fingerprints"][key] for key in keys):
            raise ValueError("Changed resynthesis outcome or reviewed workspace")
        return []
    except _ARCHIVE_ERRORS as exc:
        return [f"Resynthesis provenance: {exc}"]


def validate_delta_basis(record, root, metadata):
    delta = record.get("delta_review") or {}
    if delta.get("basis_mode") != "resynthesize":
        return []
    try:
        path = formal._safe_file(root, delta["basis_decision"])
        raw = path.read_bytes()
        base = json.loads(raw)
        if (flow._sha256(raw) != delta["basis_decision_sha256"]
                or path.parent.parent != flow.runs_dir(root, metadata["paper_id"]).resolve()
                or base.get("run_id") != delta["basis_run_id"]
                or base.get("review_mode") != "resynthesize" or base["merged"]["outcome"] != "ready"
                or any(base.get(key) != record.get(key) for key in
                       ("editor_screen", "referee_reports", "prior_decisions", "followup_items"))):
            raise ValueError("The resynthesized basis or carried judgments changed")
        return validate(base, path, root, metadata, as_basis=True)
    except _ARCHIVE_ERRORS as exc:
        return [f"Resynthesized delta basis: {exc}"]


def science_view(record, root, metadata):
    """``record`` with the blockers its resynthesis (or resynthesized delta basis) withdrew
    on sustained factual rebuttals; unchanged when none apply or they no longer verify."""
    from paper_writing import rebuttal

    root = Path(root).resolve()
    paper_id = metadata.get("paper_id") or record.get("paper_id")
    try:
        source = record
        delta = record.get("delta_review") or {}
        if record.get("review_mode") != "resynthesize" and delta.get("basis_mode") == "resynthesize":
            source = json.loads(formal._safe_file(root, delta["basis_decision"]).read_bytes())
        if source.get("review_mode") != "resynthesize" or not (source.get("resynthesis") or {}).get("rebuttals"):
            return record
        reply = json.loads((flow.runs_dir(root, paper_id) / source["run_id"] / "resynthesis-response.json").read_bytes())
        base, basis_sha = _basis(root, paper_id, Path(source["resynthesis"]["basis_decision"]))
        withdrawn, problems, _ = rebuttal.sustained(root, paper_id, base, basis_sha, reply.get("rebuttals", []))
        return record if problems else rebuttal.withdrawn_view(record, withdrawn)
    except _ARCHIVE_ERRORS:
        return record
