"""Adjudicate an author's factual rebuttal of one archived review blocker.

A reviewer sometimes blocks on a statement that the reviewed snapshot itself
contradicts (for example, "the table prints 0.248" where the snapshot prints
0.247--0.298). ``review resynthesize`` replays archived judgments, so such a
blocker could only be cleared by another full review round. This module gives
the author one narrow, recorded channel:

1. The rebuttal names one blocking item of an archived unified decision and
   cites machine-checkable evidence: the reviewed snapshot (SHA-256, line, an
   exact quote) and optional recomputation files (path, SHA-256, value).
2. Deterministic checks run first. Evidence that does not verify rejects the
   rebuttal; the blocker stands. When the snapshot settles the premise without
   interpretation (the value the blocker says is printed is absent from the
   located table or environment, and the cited row prints the value the
   blocker itself derives) the rebuttal is sustained without a model.
3. Otherwise one independent model session (a model other than the role that
   raised the blocker and the writer; another family when one is configured)
   sees only the blocker, the rebuttal, the check results and the cited
   evidence, and returns ``sustained`` or ``rejected`` with its reason.

Every adjudication is written to ``reviews/rebuttals/<paper>/<run>/`` with the
evidence hashes, the deciding party and its reason. It neither consumes a
scientific round nor reviews the manuscript again. A sustained rebuttal takes
effect only when ``review resynthesize`` is given its adjudication record; the
replay then withdraws that single blocker and applies the current gate.
"""

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from paper_writing import review_flow as flow

SCHEMA = "openlabs.review_rebuttal.v1"
RECORD_SCHEMA = "openlabs.review_rebuttal_adjudication.v1"
RULE_VERSION = "rebuttal_v1"
ROLE_NAME = "rebuttal_adjudicator"
FLOAT_ENVIRONMENTS = ("table", "table*", "sidewaystable", "figure", "figure*", "longtable")
EXCERPT_CONTEXT = 12
MAX_FILE_CHARS = 20_000
_PRINT_VERB = re.compile(
    r"\b(print(s|ed)?|reads?|report(s|ed)?|state(s|d)?|list(s|ed)?|show(s|n|ed)?|give(s|n)?|"
    r"quote(s|d)?|display(s|ed)?|written|appears?|starts?|begins?)\b", re.I)
_ERRORS = (ValueError, OSError, KeyError, IndexError, TypeError)
VERDICTS = ("sustained", "rejected")
ADJUDICATOR_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "blocker_premise", "snapshot_reading", "reason"],
    "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)},
                   "blocker_premise": {"type": "string"},
                   "snapshot_reading": {"type": "string"},
                   "reason": {"type": "string"}},
}
SYSTEM_PROMPT = """You adjudicate one factual dispute about an archived journal review.
A reviewer raised one blocking item. The authors say the item rests on a statement that the
reviewed manuscript snapshot contradicts. You see only that item, the authors' rebuttal, the
results of deterministic checks, the cited snapshot lines and the cited recomputation files.

Decide one question: is the factual premise of the blocking item contradicted by the reviewed
snapshot and the cited evidence, so that the item would not have been raised on a correct
reading?
- "sustained": the premise is false on the evidence shown, and nothing else in the item still
  requires a change to the manuscript.
- "rejected": the premise holds, the evidence does not settle it, the cited lines are not the
  ones the item refers to, or the item also raises a separate issue the rebuttal leaves open.
Do not review the paper, propose changes or weigh other issues. When in doubt, reject.
State the item's premise, what the snapshot actually prints, and your reason."""


def runs_dir(root: Path, paper_id: str) -> Path:
    return root / "reviews" / "rebuttals" / paper_id


def _text(record, key):
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Provide a nonempty {key}")
    return value


# --------------------------------------------------------------------------- archived items

def blocking_items(merged):
    """The archived decision's blocking items, as quoted by a rebuttal."""
    items = [dict(text=change["change"], referee=change.get("referee"), location=change.get("location", ""),
                  kind="required_change")
             for change in merged.get("required_changes", []) if not change.get("advisory")]
    items += [dict(text=item["item"], referee=item.get("referee"), location="", kind="unresolved_previous_item")
              for item in merged.get("unresolved_previous_items", []) if not item.get("advisory")]
    items += [dict(text=text, referee=None, location="", kind="scientific_blocker")
              for text in merged.get("scientific_blockers", [])]
    return items


def _followup_detail(row):
    return (f"{row['finding']} Reader could infer: {row['reader_misconclusion']} "
            f"Missed previously: {row['why_missed']}")


def _sources(report, text):
    """Where ``text`` comes from in one archived report, as (collection, index)."""
    found = []
    for index, row in enumerate(report.get("new_findings", [])):
        detail = (_followup_detail(row) if all(key in row for key in ("reader_misconclusion", "why_missed"))
                  else None)
        if text in (row.get("finding"), detail):
            found.append(("new_findings", index))
    for index, row in enumerate(report.get("previous_items", [])):
        if row.get("item") == text and not row.get("resolved"):
            found.append(("previous_items", index))
    for dimension, rows in (report.get("dimension_repairs") or {}).items():
        for index, row in enumerate(rows):
            if (row.get("repair") if isinstance(row, dict) else row) == text:
                found.append((f"dimension_repairs.{dimension}", index))
    for index, row in enumerate(report.get("required_changes", [])):
        if row.get("change") == text:
            found.append(("required_changes", index))
    if text in report.get("scientific_blockers", []):
        found.append(("scientific_blockers", report["scientific_blockers"].index(text)))
    return found


def origin(base, text):
    """The archived role(s) whose report produced a blocking item."""
    reports = {"editor": base["editor_screen"], **base["referee_reports"]}
    return [role for role, report in reports.items() if _sources(report, text)]


def withdraw(report, text, note):
    """Return a copy of ``report`` with the item ``text`` withdrawn to advice, and the hit count."""
    report = copy.deepcopy(report)
    hits = 0
    for collection, index in _sources(report, text):
        hits += 1
        if collection == "new_findings":
            row = report["new_findings"][index]
            row.update(kind="advisory", finding=f"{row['finding']} [{note}]")
        elif collection == "previous_items":
            row = report["previous_items"][index]
            row.update(resolved=True, evidence=f"{row.get('evidence', '')} [{note}]".strip())
        elif collection.startswith("dimension_repairs."):
            rows = report["dimension_repairs"][collection.split(".", 1)[1]]
            row = rows[index]
            if isinstance(row, dict):
                row.update(kind="rebutted")
            else:
                rows.pop(index)
                report.setdefault("optional_suggestions", []).append(f"{row} [{note}]")
        elif collection == "required_changes":
            report["required_changes"][index].update(type="text")
        elif collection == "scientific_blockers":
            report["scientific_blockers"].remove(text)
            report.setdefault("optional_suggestions", []).append(f"{text} [{note}]")
    return report, hits


def withdrawn_view(base, withdrawn):
    """The archived record with each sustained blocker withdrawn (in memory only)."""
    if not withdrawn:
        return base
    view = dict(base)
    reports = {"editor": base["editor_screen"], **base["referee_reports"]}
    for text, digest in withdrawn.items():
        note = f"withdrawn: factual rebuttal sustained, adjudication {digest[:12]}"
        total = 0
        for role, report in reports.items():
            reports[role], hits = withdraw(report, text, note)
            total += hits
        if not total:
            raise ValueError("A sustained rebuttal names an item no archived report raised")
    view["editor_screen"] = reports.pop("editor")
    view["referee_reports"] = reports
    return view


# --------------------------------------------------------------------------- deterministic checks

def _macros(text):
    """Zero-argument macros with literal bodies (\\newcommand{\\x}{v}, \\def\\x{v})."""
    found = {}
    for match in re.finditer(r"\\(?:re)?newcommand\*?\{?\\([A-Za-z]+)\}?\{([^{}]*)\}|\\def\\([A-Za-z]+)\{([^{}]*)\}",
                             text):
        name, body = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        found[name] = body
    return found


def _expand(text, macros):
    for _ in range(3):
        text = re.sub(r"\\([A-Za-z]+)(?![A-Za-z])(\{\})?",
                      lambda m: macros.get(m.group(1), m.group(0)), text)
    return text


def _environments(text):
    spans, stack = [], []
    for match in re.finditer(r"\\(begin|end)\{([^}]+)\}", text):
        if match.group(1) == "begin":
            stack.append((match.group(2), match.start()))
        else:
            for position in range(len(stack) - 1, -1, -1):
                if stack[position][0] == match.group(2):
                    name, start = stack.pop(position)
                    del stack[position:]
                    spans.append((name, start, match.end()))
                    break
    return spans


def _located_scope(snapshot, location, line_start):
    """The labelled environment the blocker's location names, when it encloses the cited line."""
    for match in re.finditer(r"\\label\{([^}]+)\}", snapshot):
        key = match.group(1)
        if not re.search(r"(?<![\w:.-])" + re.escape(key) + r"(?![\w:-])", location):
            continue
        enclosing = [span for span in _environments(snapshot) if span[1] <= match.start() < span[2]]
        floats = [span for span in enclosing if span[0] in FLOAT_ENVIRONMENTS]
        chosen = (floats or enclosing)
        if not chosen:
            continue
        name, start, end = max(chosen, key=lambda span: span[2] - span[1])
        if start <= line_start < end:
            return key, name, start, end
    return None


def _occurs(value, text, *, bounded=False):
    left = r"(?<![\w.])" if bounded else r"(?<!\d)"
    right = r"(?![\w])" if bounded else ""
    return re.search(left + re.escape(value) + right, text) is not None


def _row_key(line):
    if "&" not in line:
        return None
    cell = re.sub(r"\\[A-Za-z]+\*?(\[[^\]]*\])?(\{[^{}]*\})*", " ", line.split("&", 1)[0])
    cell = re.sub(r"[{}$%]", " ", cell).strip()
    return cell or None


def _safe(root, relative, paper_id):
    path = flow.formal_checks._safe_file(root, relative)
    if not relative.startswith((f"papers/{paper_id}/", f"reviews/unified/{paper_id}/")):
        raise ValueError(f"{relative} lies outside this paper's workspace and review archive")
    return path


def check(root, paper_id, base, basis_sha, rebuttal):
    """Deterministic checks: (checks, verdict or None, reason, evidence, packet parts)."""
    root = Path(root).resolve()
    checks = []

    def record(name, passed, detail):
        checks.append(dict(check=name, passed=bool(passed), detail=detail))
        return passed

    if rebuttal.get("schema") != SCHEMA:
        raise ValueError(f"The rebuttal must declare schema {SCHEMA}")
    if rebuttal.get("claim") != "factual_error":
        raise ValueError("Only claim 'factual_error' (the blocker contradicts the reviewed snapshot) is supported")
    for key in ("blocker", "rebuttal", "asserted_text", "expected_text"):
        _text(rebuttal, key)
    blocker = rebuttal["blocker"]
    snapshot_ref = rebuttal.get("snapshot")
    if not isinstance(snapshot_ref, dict):
        raise ValueError("Provide snapshot {sha256, line, quote}")
    files = rebuttal.get("recomputations", [])
    if not isinstance(files, list) or any(not isinstance(row, dict) for row in files):
        raise ValueError("recomputations must be a list of {path, sha256, value}")
    hard = []
    hard.append(record("decision_bound", rebuttal.get("decision_sha256") == basis_sha,
                       "The rebuttal binds the archived decision SHA-256"))
    archived = blocking_items(base["merged"])
    try:  # A formal-check block hides the referees' items from the recorded merge.
        archived += blocking_items(flow._recorded_merge(base, []))
    except _ERRORS:
        pass
    items = [item for item in archived if item["text"] == blocker]
    item = items[0] if items else {"text": blocker, "location": "", "referee": None}
    hard.append(record("blocking_item", bool(items),
                       "The quoted text is a blocking item of the archived decision"))
    roles = origin(base, blocker)
    hard.append(record("item_origin", bool(roles), f"Raised by {', '.join(roles) or 'no archived report'}"))
    expanded, _ = flow._formal_recheck_baseline(base)
    snapshot_sha = flow._sha256(expanded)
    snapshot = expanded.decode()
    hard.append(record("snapshot_bound", snapshot_ref.get("sha256") == snapshot_sha,
                       f"Reviewed snapshot manuscript-expanded.tex has SHA-256 {snapshot_sha}"))
    lines = snapshot.split("\n")
    number = snapshot_ref.get("line")
    in_range = isinstance(number, int) and 1 <= number <= len(lines)
    line = lines[number - 1] if in_range else ""
    quote = snapshot_ref.get("quote")
    hard.append(record("snapshot_quote", in_range and isinstance(quote, str) and quote.strip() and quote in line,
                       f"Line {number} contains the quoted text"))
    asserted, expected = rebuttal["asserted_text"], rebuttal["expected_text"]
    hard.append(record("asserted_in_blocker", asserted in blocker and asserted != expected,
                       f"The blocker states {asserted!r}"))
    evidence = {"snapshot": {"path": base["_path"].parent.relative_to(root).joinpath(
        "manuscript-expanded.tex").as_posix(), "sha256": snapshot_sha, "line": number}, "files": []}
    contents = []
    for row in files:
        try:
            path = _safe(root, row.get("path"), paper_id)
            raw = path.read_bytes()
        except (ValueError, OSError) as exc:
            hard.append(record("recomputation_file", False, f"{row.get('path')}: {exc}"))
            continue
        digest = flow._sha256(raw)
        ok = digest == row.get("sha256")
        value = row.get("value")
        if value is not None:
            ok = ok and isinstance(value, str) and value in raw.decode(errors="replace")
        hard.append(record("recomputation_file", ok,
                           f"{row['path']} has SHA-256 {digest}" + (f" and contains {value!r}" if value else "")))
        evidence["files"].append({"path": row["path"], "sha256": digest})
        contents.append((row["path"], raw.decode(errors="replace")[:MAX_FILE_CHARS]))
    parts = dict(item=item, roles=roles, line=line, lines=lines, number=number, contents=contents)
    if not all(hard):
        return checks, "rejected", "The cited evidence does not verify; the blocker stands.", evidence, parts

    # Content checks: settle the premise only where no interpretation is needed.
    line_start = len("\n".join(lines[:number - 1])) + (1 if number > 1 else 0)
    location = f"{item['location']} {blocker}"
    scope = _located_scope(snapshot, location, line_start)
    macros = _macros(snapshot)
    if scope is None:
        record("located_scope", False, "The blocker's location names no label of an environment enclosing the line")
        region, where = snapshot, "the whole snapshot"
    else:
        key, name, start, end = scope
        record("located_scope", True, f"Line {number} lies in the {name} environment labelled {key}")
        region, where = snapshot[start:end], f"the {name} environment labelled {key}"
    region = _expand(region, macros)
    cited = _expand(line, macros)
    expected_ok = record("expected_in_blocker_and_line", expected in blocker and _occurs(expected, cited),
                         f"The blocker derives {expected!r} and line {number} prints it")
    row = _row_key(line)
    row_ok = record("row_named", row is None or _occurs(row, location, bounded=True),
                    f"The blocker's location names the cited row {row!r}" if row else "Not a table row")
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+", blocker) if asserted in s]
    verb_ok = record("printed_assertion", any(_PRINT_VERB.search(s) for s in sentences),
                     "The blocker states that the manuscript prints the disputed value")
    absent = record("asserted_absent", not _occurs(asserted, region),
                    f"{asserted!r} does not occur in {where} (macros expanded)")
    if _occurs(asserted, cited, bounded=True) and not _occurs(expected, cited, bounded=True):
        return (checks, "rejected", f"Line {number} prints {asserted!r} as the blocker says; the blocker stands.",
                evidence, parts)
    if expected_ok and row_ok and verb_ok and absent:
        return (checks, "sustained",
                f"The blocker says the manuscript prints {asserted!r}; the reviewed snapshot never prints it "
                f"in {where}, and line {number} prints {expected!r}, the value the blocker itself derives.",
                evidence, parts)
    return checks, None, "The deterministic checks cannot settle the premise", evidence, parts


# --------------------------------------------------------------------------- adjudicator

def select_adjudicator(config, base, roles, override=None):
    """A configured role whose model differs from the item's author(s) and the writer.

    Another model family is preferred; with ``cross_model.basis: model`` (a recorded
    authorization for a single-family setup) another model of the same family serves.
    """
    receipts = base.get("receipts") or {}
    excluded = {str((receipts.get(role) or config["roles"].get(role) or {}).get("model") or "").lower()
                for role in roles}
    excluded.add(str(base.get("writer_model") or "").lower())
    families = {flow.model_family(model) for model in excluded if model}
    candidates = []
    for name, role in config["roles"].items():
        model = str(role.get("model") or "")
        if not model or model.lower() in excluded or (override and name != override):
            continue
        family = flow.model_family(model, role.get("provider"))
        independence = "cross_family" if family not in families else "same_family_different_model"
        candidates.append((independence != "cross_family", name, dict(role), independence))
    if override and not candidates:
        raise ValueError(f"Role {override} is not configured or uses the model of the item's author or writer")
    candidates.sort(key=lambda row: row[:2])
    for _, name, role, independence in candidates:
        if independence == "cross_family" or flow.cross_model_basis(config) == "model":
            return name, role, independence
    raise ValueError("No configured review model differs in family from the item's author and the writer "
                     "(another model of the same family needs cross_model.basis 'model')")


def packet(rebuttal, checks, parts):
    lines, number = parts["lines"], parts["number"]
    first, last = max(1, number - EXCERPT_CONTEXT), min(len(lines), number + EXCERPT_CONTEXT)
    excerpt = "\n".join(f"{index:5d}: {lines[index - 1]}" for index in range(first, last + 1))
    files = "\n\n".join(f"### {path}\n{text}" for path, text in parts["contents"]) or "(none)"
    results = "\n".join(f"- {row['check']}: {'pass' if row['passed'] else 'fail'} — {row['detail']}"
                        for row in checks)
    return (f"## Blocking item (raised by {', '.join(parts['roles'])}; location: "
            f"{parts['item'].get('location') or 'not recorded'})\n{rebuttal['blocker']}\n\n"
            f"## Authors' rebuttal\n{rebuttal['rebuttal']}\n\n"
            f"The authors say the item states {rebuttal['asserted_text']!r} where the snapshot prints "
            f"{rebuttal['expected_text']!r}.\n\n## Deterministic checks\n{results}\n\n"
            f"## Reviewed snapshot, lines {first}-{last} (cited line {number})\n{excerpt}\n\n"
            f"## Cited recomputation files\n{files}\n")


# --------------------------------------------------------------------------- command

def run(paper_id, *, root, decision, rebuttal, actor, reason, adjudicator_role=None, allow_model=True):
    """Adjudicate one rebuttal and record it; see the module docstring."""
    _text({"actor": actor}, "actor")
    _text({"reason": reason}, "reason")
    return flow._locked_review(paper_id, root, _run, decision=Path(decision), rebuttal=Path(rebuttal),
                               actor=actor, reason=reason, adjudicator_role=adjudicator_role,
                               allow_model=allow_model)


def _run(paper_id, *, root, decision, rebuttal, actor, reason, adjudicator_role, allow_model):
    from paper_writing.resynthesis import _basis

    base, basis_sha = _basis(root, paper_id, decision)
    raw = rebuttal.read_bytes()
    content = json.loads(raw)
    if not isinstance(content, dict):
        raise ValueError("The rebuttal must be a JSON object")
    checks, verdict, explanation, evidence, parts = check(root, paper_id, base, basis_sha, content)
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = runs_dir(root, paper_id) / started
    sequence = 0
    while directory.exists():
        sequence += 1
        directory = directory.with_name(f"{started}-{sequence:04d}")
    directory.mkdir(parents=True)
    (directory / "rebuttal.json").write_bytes(raw)
    record = {"schema": RECORD_SCHEMA, "rule_version": RULE_VERSION, "paper_id": paper_id,
              "run_id": directory.name, "actor": actor, "reason": reason, "started_at": flow._now(),
              "basis_decision": base["_path"].relative_to(root).as_posix(), "basis_decision_sha256": basis_sha,
              "rebuttal_sha256": flow._sha256(raw), "blocker": content["blocker"],
              "blocker_roles": parts["roles"], "evidence": evidence, "checks": checks,
              "consumes_scientific_round": False}
    if verdict is not None:
        record.update(verdict=verdict, decided_by="deterministic", reason_for_verdict=explanation)
    elif not allow_model:
        record.update(verdict="undetermined", decided_by=None, reason_for_verdict=explanation)
    else:
        config = flow.review_config(root)
        name, role, independence = select_adjudicator(config, base, parts["roles"], adjudicator_role)
        result, receipt = flow.run_role(
            role_name=ROLE_NAME, role=role, system_prompt=SYSTEM_PROMPT,
            user_prompt=packet(content, checks, parts), schema=ADJUDICATOR_SCHEMA,
            workdir=directory / "adjudicator", timeout=config.get("timeout_seconds", 3600))
        record.update(verdict=result["verdict"], decided_by="model", reason_for_verdict=result["reason"],
                      adjudicator={"role": name, "provider": role.get("provider"), "model": role.get("model"),
                                   "family": flow.model_family(role.get("model"), role.get("provider")),
                                   "independence": independence, "receipt": receipt,
                                   "output_sha256": receipt.get("output_sha256")},
                      adjudication=result)
    record["finished_at"] = flow._now()
    digest = flow._json_dump(directory / "adjudication.json", record)
    return record | {"run_dir": directory.relative_to(root).as_posix(), "adjudication_sha256": digest}


# --------------------------------------------------------------------------- replay

def verify(root, paper_id, base, basis_sha, reference):
    """Re-check one adjudication cited by a resynthesis reply: (record, problems)."""
    root = Path(root).resolve()
    try:
        relative = reference["adjudication"]
        path = flow.formal_checks._safe_file(root, relative)
        if path.parent.parent.resolve() != runs_dir(root, paper_id).resolve() or path.name != "adjudication.json":
            raise ValueError("Cite an adjudication.json from this paper's rebuttal archive")
        raw = path.read_bytes()
        if flow._sha256(raw) != reference.get("sha256"):
            raise ValueError("The adjudication record changed")
        record = json.loads(raw)
        if (record.get("schema") != RECORD_SCHEMA or record.get("rule_version") != RULE_VERSION
                or record.get("paper_id") != paper_id or record.get("basis_decision_sha256") != basis_sha):
            raise ValueError("The adjudication is bound to another decision or rule version")
        content_raw = (path.parent / "rebuttal.json").read_bytes()
        if flow._sha256(content_raw) != record["rebuttal_sha256"]:
            raise ValueError("The archived rebuttal changed")
        content = json.loads(content_raw)
        checks, verdict, _, evidence, parts = check(root, paper_id, base, basis_sha, content)
        if checks != record["checks"] or evidence != record["evidence"] or content["blocker"] != record["blocker"]:
            raise ValueError("The deterministic checks no longer reproduce")
        if record["decided_by"] == "deterministic":
            if verdict != record["verdict"]:
                raise ValueError("The deterministic verdict no longer reproduces")
        elif record["decided_by"] == "model":
            if verdict is not None:
                raise ValueError("A model verdict was recorded where the checks decide")
            judge = record["adjudicator"]
            output = (path.parent / "adjudicator" / "output.json").read_bytes()
            if (flow._sha256(output) != judge["output_sha256"] or json.loads(output) != record["adjudication"]
                    or record["adjudication"]["verdict"] != record["verdict"]):
                raise ValueError("The adjudicator output changed")
            receipts = base.get("receipts") or {}
            authors = {str((receipts.get(role) or {}).get("model") or "").lower() for role in parts["roles"]}
            if str(judge["model"]).lower() in authors | {str(base.get("writer_model") or "").lower()}:
                raise ValueError("The adjudicator used the model of the item's author or writer")
        else:
            raise ValueError("The adjudication has no verdict")
        if record["verdict"] != "sustained":
            return record, [f"Rebuttal {record['run_id']} was {record['verdict']}; the blocker stands: "
                            f"{record['blocker']}"]
        return record, []
    except _ERRORS as exc:
        return None, [f"Rebuttal adjudication: {exc}"]


def sustained(root, paper_id, base, basis_sha, references):
    """Blocker text -> adjudication digest for every sustained rebuttal, plus problems."""
    if not isinstance(references, list):
        return {}, ["rebuttals must list {adjudication, sha256} references"], []
    withdrawn, problems, notes = {}, [], []
    for reference in references:
        if not isinstance(reference, dict):
            problems.append("rebuttals must list {adjudication, sha256} references")
            continue
        record, issues = verify(root, paper_id, base, basis_sha, reference)
        problems.extend(issues)
        if record is not None:
            notes.append({"adjudication": reference["adjudication"], "sha256": reference["sha256"],
                          "verdict": record["verdict"], "decided_by": record["decided_by"],
                          "adjudicator": (record.get("adjudicator") or {}).get("model"),
                          "blocker": record["blocker"]})
            if not issues:
                withdrawn[record["blocker"]] = reference["sha256"]
    return withdrawn, problems, notes
