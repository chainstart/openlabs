"""Mechanical card checks a research line declares, run before admission (2026-11-16).

``admission_precheck`` (a research-line entry field; draft schema of 2026-11-16, written by
the astro line) names, per paper template, a command the control plane runs on every new
card of that template before the card is registered for the admission review. No model
call, no download: the line's own script on its cached data::

    admission_precheck:
      schema: draft-2026-11-16
      model_calls: none
      network: none
      per_template:
        contact-binary-solution:
          command: /abs/venv/bin/python /abs/enumerate/admission_precheck.py {entry_id} --json
          inputs: [...]                  # documentation
          pass_condition: exit code 0 and JSON verdict == "pass"
          hard_checks: [...]             # documentation
          soft_checks: [...]             # documentation
          typical_seconds: 0.1-1
          output: JSON {verdict, failed, warnings, checks[...]}
          timeout_seconds: 60            # optional (default 120, capped by
                                         # [program].card_precheck_max_seconds)

The command is a string (split like a shell word list, never run through a shell) or an
argv list. Placeholders: ``{entry_id}`` (the card's ``candidate_queue_entry.entry_id``, the
queue entry or batch id), ``{tic}`` (digits of a ``TIC...`` entry id), ``{card}`` (the
stored card JSON), ``{line}``, ``{template}``, ``{data}`` (data repository root). Outcome,
read from the exit code and the JSON object the command prints on stdout:

* ``pass``: exit code 0 and ``verdict == "pass"``;
* ``fail``: a JSON verdict other than pass (``fail``, ``not_found``) with exit code 0, 1 or
  2, or a card without the entry id the command needs. The card is recorded as rejected
  (``card_precheck_failed``, not repaired, not a judgement on the topic; the failed checks
  in ``card_errors``) and never reaches the admission review;
* ``error``: timeout, the command cannot start, stdout is not a JSON object with a verdict,
  or an unexpected exit code. This is an infrastructure problem, neither a pass nor a
  fail: the card waits as proposed but is not sent to the admission review, the precheck
  is retried on later ticks, and every tick reports it (``report.errors``) until it passes
  or fails.

``card_compute_floor`` -- the least compute a card of the line or template may register::

    card_compute_floor:
      ailab_core_hours: 60          # cpus x hours of cost_estimate.compute_plan.ailab
      agent_hours: 6                # cost_estimate.agent_seconds / 3600
      gpu_hours: 40                 # cost_estimate.gpu_hours of a card that uses the GPU

Without it the lower bound of ``per_paper_cost`` is used when it is a plain number or
range (``ailab_core_hours``/``cpu_core_hours``: "60-120 ..." -> 60; ``agent_hours``:
"6-10" -> 6; ``gpu_hours_lower_bound``/``gpu_hours``: "40-200 ..." -> 40; "< 5" and 0
set no floor). A tighter card is corrected (hours raised, agent seconds raised, GPU
hours raised when the card's compute plan names ``container_gpu`` or it already
declares GPU hours) and the correction is recorded in ``card_check.normalized``, so the
topic does not freeze at execution for a budget the line already knew was too small.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import sha256_file

FIELD = "admission_precheck"
DEFAULT_TIMEOUT_SECONDS = 120
PLACEHOLDERS = ("entry_id", "tic", "card", "line", "template", "data")
FAIL_VERDICTS = frozenset({"fail", "failed", "not_found"})
_LEADING_NUMBER = re.compile(r"\s*(\d+(?:\.\d+)?)")


def _template(document: Mapping[str, Any] | None, line: str,
              template: str) -> dict[str, Any]:
    from .research_lines import line_templates

    if not template:
        return {}
    for item in line_templates(document, line):
        if str(item.get("id") or "") == template:
            return item
    return {}


def line_specs(document: Mapping[str, Any] | None,
               card: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(line entry, template entry)`` of a card (empty dicts when unknown)."""

    from .research_lines import line_entry

    line = str(card.get("research_line") or "").strip()
    if not line:
        return {}, {}
    entry = line_entry(document, line) or {}
    return entry, _template(document, line, str(card.get("paper_template") or "").strip())


def precheck_spec(line_entry: Mapping[str, Any], template_id: str) -> dict[str, Any] | None:
    """The line's ``admission_precheck`` command block for a card's template (None: none)."""

    block = line_entry.get(FIELD)
    if not isinstance(block, Mapping):
        return None
    per_template = block.get("per_template")
    spec = per_template.get(template_id) if isinstance(per_template, Mapping) and (
        template_id) else None
    if not isinstance(spec, Mapping):
        spec = block if block.get("command") else None  # one command for every template
    if not isinstance(spec, Mapping) or not spec.get("command"):
        return None
    return {**dict(spec), "schema": block.get("schema")}


def entry_id_of(card: Mapping[str, Any]) -> str:
    entry = card.get("candidate_queue_entry")
    if isinstance(entry, Mapping):
        return str(entry.get("entry_id") or "").strip()
    return str(entry or "").strip() if isinstance(entry, str) else ""


def _parse_stdout(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except ValueError:
        # A script may log a line before its JSON: take the last top-level object.
        start = stripped.rfind("\n{")
        try:
            value = json.loads(stripped[start + 1:]) if start >= 0 else None
        except ValueError:
            value = None
    return value if isinstance(value, dict) else None


def _failed_checks(detail: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    checks = detail.get("checks")
    for item in checks if isinstance(checks, list) else []:
        if isinstance(item, Mapping) and item.get("pass") is False and item.get(
                "hard", True) is not False:
            reasons.append(f"{item.get('name')}: {json.dumps(item.get('value'), default=str)[:120]}"
                           f" (rule {item.get('rule')})")
    if not reasons:
        failed = detail.get("failed") or detail.get("failed_members") or []
        reasons = [json.dumps(item, default=str)[:200] if not isinstance(item, str) else item
                   for item in (failed if isinstance(failed, list) else [failed])]
    return reasons[:10]


def run_precheck(
    spec: Mapping[str, Any],
    *,
    card: Mapping[str, Any],
    card_path: Path,
    output_dir: Path,
    data_root: Path,
    max_seconds: int,
) -> dict[str, Any]:
    """Run one declared precheck; ``status`` is pass, fail or error (never raises)."""

    output_dir.mkdir(parents=True, exist_ok=True)
    line = str(card.get("research_line") or "")
    template = str(card.get("paper_template") or "")
    entry_id = entry_id_of(card)
    values = {"entry_id": entry_id, "tic": entry_id[3:] if entry_id.upper().startswith("TIC")
              else entry_id, "card": str(card_path), "line": line, "template": template,
              "data": str(data_root)}
    raw = spec.get("command")
    argv = [str(item) for item in raw] if isinstance(raw, list) else shlex.split(str(raw or ""))
    base: dict[str, Any] = {"schema": spec.get("schema"), "entry_id": entry_id or None}
    if any("{entry_id}" in item or "{tic}" in item for item in argv) and not entry_id:
        return {**base, "status": "fail",
                "reasons": ["the card names no candidate_queue_entry.entry_id; the template's "
                            "admission precheck needs the queue entry (copy card_fields)"]}
    try:
        command = [item.format(**values) for item in argv]
    except (KeyError, IndexError, ValueError) as exc:
        return {**base, "status": "error", "error": f"command placeholder {exc} (allowed: "
                                                    f"{', '.join(PLACEHOLDERS)})"}
    try:
        timeout = int(spec.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    timeout = max(1, min(timeout, max_seconds))
    base.update(command=command, timeout_seconds=timeout)
    environment = {**os.environ, "OPENLABS_CARD_PATH": str(card_path),
                   "OPENLABS_RESEARCH_LINE": line, "OPENLABS_PAPER_TEMPLATE": template,
                   "OPENLABS_QUEUE_ENTRY_ID": entry_id}
    cwd = str(spec.get("cwd") or "") or str(output_dir)
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - the line's own declared command, no shell
            command, cwd=cwd, env=environment, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {**base, "status": "error", "error": f"timed out after {timeout} s",
                "seconds": round(time.monotonic() - started, 1)}
    except OSError as exc:
        return {**base, "status": "error", "error": f"could not start: {exc}"}
    result: dict[str, Any] = {**base, "exit_code": completed.returncode,
                              "seconds": round(time.monotonic() - started, 2)}
    output = output_dir / "precheck.json"
    output.write_text(completed.stdout, encoding="utf-8")
    result["output_path"] = str(output)
    result["output_sha256"] = sha256_file(output)
    if completed.stderr:
        result["stderr_tail"] = completed.stderr[-600:]
    detail = _parse_stdout(completed.stdout)
    verdict = str((detail or {}).get("verdict") or "").strip().lower()
    if detail is None or not verdict:
        return {**result, "status": "error",
                "error": "stdout is not a JSON object with a verdict"}
    result["verdict"] = verdict
    warnings = detail.get("warnings")
    if isinstance(warnings, list) and warnings:
        result["warnings"] = [str(item)[:200] for item in warnings[:10]]
    if verdict == "pass" and completed.returncode == 0:
        return {**result, "status": "pass"}
    if completed.returncode in (0, 1, 2) and verdict != "pass":
        return {**result, "status": "fail",
                "reasons": _failed_checks(detail) or [f"verdict {verdict}"]}
    return {**result, "status": "error",
            "error": f"exit code {completed.returncode} with verdict {verdict!r}"}


def precheck_reasons(result: Mapping[str, Any]) -> str:
    reasons = result.get("reasons") or []
    if reasons:
        return "; ".join(str(item) for item in reasons)
    return str(result.get("error") or result.get("stderr_tail") or "").strip()[-300:] or (
        f"exit code {result.get('exit_code')}")


# --------------------------------------------------------------------------- compute floor


def _lower_bound(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    match = _LEADING_NUMBER.match(str(value or ""))
    if not match:
        return None
    number = float(match.group(1))
    return number if number > 0 else None


def compute_floor(line_entry: Mapping[str, Any],
                  template_entry: Mapping[str, Any]) -> dict[str, Any]:
    """``{"core_hours", "agent_seconds", "gpu_hours", "source"}`` the line asks of a card.

    Any key may be missing (the result may be empty).
    """

    for source_name, source in (("template", template_entry), ("line", line_entry)):
        explicit = source.get("card_compute_floor")
        if isinstance(explicit, Mapping):
            floor: dict[str, Any] = {"source": f"{source_name} card_compute_floor"}
            core = _lower_bound(explicit.get("ailab_core_hours", explicit.get("core_hours")))
            agent = _lower_bound(explicit.get("agent_hours"))
            gpu = _lower_bound(explicit.get("gpu_hours"))
            if core:
                floor["core_hours"] = core
            if agent:
                floor["agent_seconds"] = int(agent * 3600)
            if gpu:
                floor["gpu_hours"] = gpu
            return floor
    for source_name, source in (("template", template_entry), ("line", line_entry)):
        cost = source.get("per_paper_cost")
        if not isinstance(cost, Mapping):
            continue
        floor = {"source": f"{source_name} per_paper_cost"}
        core = _lower_bound(cost.get("ailab_core_hours")) or _lower_bound(
            cost.get("cpu_core_hours"))
        agent = _lower_bound(cost.get("agent_hours"))
        gpu = _lower_bound(cost.get("gpu_hours_lower_bound")) or _lower_bound(
            cost.get("gpu_hours"))
        if core:
            floor["core_hours"] = core
        if agent:
            floor["agent_seconds"] = int(agent * 3600)
        if gpu:
            floor["gpu_hours"] = gpu
        if len(floor) > 1:
            return floor
    return {}


def apply_compute_floor(card: Mapping[str, Any],
                        floor: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """``card`` with its compute plan raised to ``floor``; the notes of what changed."""

    import copy

    fixed = copy.deepcopy(dict(card))
    notes: list[str] = []
    cost = fixed.get("cost_estimate")
    if not isinstance(cost, dict) or not floor:
        return fixed, notes
    source = str(floor.get("source") or "line")
    core = floor.get("core_hours")
    plan = cost.get("compute_plan") if isinstance(cost.get("compute_plan"), dict) else None
    ailab = plan.get("ailab") if plan is not None and isinstance(plan.get("ailab"), dict) else None
    locations = plan.get("locations") if plan is not None else None
    if core and ailab is not None and isinstance(locations, list) and "ailab" in locations:
        cpus, hours = ailab.get("cpus"), ailab.get("hours")
        if (isinstance(cpus, int) and not isinstance(cpus, bool) and cpus > 0
                and isinstance(hours, (int, float)) and not isinstance(hours, bool)
                and cpus * hours < core):
            raised = math.ceil(core / cpus * 10) / 10
            ailab["hours"] = int(raised) if float(raised).is_integer() else raised
            notes.append(
                f"cost_estimate.compute_plan.ailab.hours raised from {hours} to "
                f"{ailab['hours']} ({cpus} CPUs): the {source} floor is {core:g} core-hours"
            )
    gpu = floor.get("gpu_hours")
    declared = cost.get("gpu_hours")
    uses_gpu = (isinstance(locations, list) and "container_gpu" in locations) or (
        isinstance(declared, (int, float)) and not isinstance(declared, bool) and declared > 0)
    if gpu and uses_gpu and (
        declared is None or (isinstance(declared, (int, float))
                             and not isinstance(declared, bool) and declared < gpu)
    ):
        cost["gpu_hours"] = int(gpu) if float(gpu).is_integer() else gpu
        notes.append(f"cost_estimate.gpu_hours raised from {declared} to {cost['gpu_hours']} "
                     f"(the {source} floor is {gpu:g} GPU hours)")
    agent = floor.get("agent_seconds")
    seconds = cost.get("agent_seconds")
    if agent and isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and (
        seconds < agent
    ):
        cost["agent_seconds"] = int(agent)
        notes.append(f"cost_estimate.agent_seconds raised from {seconds} to {int(agent)} "
                     f"(the {source} floor)")
    return fixed, notes


PRECHECK_BUDGET_FIELD = "feasibility_precheck_budget"


def fill_precheck_budget(card: Mapping[str, Any], line_entry: Mapping[str, Any],
                         template_entry: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A line card's missing ``feasibility_precheck.budget`` from the line's own spec.

    The template (else the line) may declare ``feasibility_precheck_budget`` (text, or
    an object rendered as text). It fills only an absent or empty budget; a budget the
    card states is never replaced. Without that field nothing is invented and a missing
    budget stays an error.
    """

    import copy

    from .contracts import budget_text

    fixed = copy.deepcopy(dict(card))
    precheck = fixed.get("feasibility_precheck")
    if not isinstance(precheck, dict) or budget_text(precheck.get("budget")):
        return fixed, []
    for source_name, source in (("template", template_entry), ("line", line_entry)):
        text = budget_text(source.get(PRECHECK_BUDGET_FIELD))
        if text:
            precheck["budget"] = text
            return fixed, [f"feasibility_precheck.budget filled from the {source_name} "
                           f"{PRECHECK_BUDGET_FIELD}"]
    return fixed, []


__all__ = [
    "FIELD",
    "PRECHECK_BUDGET_FIELD",
    "apply_compute_floor",
    "compute_floor",
    "entry_id_of",
    "fill_precheck_budget",
    "line_specs",
    "precheck_reasons",
    "precheck_spec",
    "run_precheck",
]
