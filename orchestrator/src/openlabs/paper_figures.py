"""Pre-review figure repair for owner-mode manuscripts."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import unquote, urlparse
from zipfile import BadZipFile, ZipFile

from .contracts import atomic_write_json, sha256_file
from .resources import default_task_resources


TASK_TYPE = "paper_figure_repair"
SKILL = "openlabs-paper-figures"
MAX_ROUNDS = 2
MAX_BYTES = 32 * 1024 * 1024


def _editable(relative: Path) -> bool:
    if relative == Path("figure-plan.json"):
        return True
    if relative.parts[0] == "figures":
        return len(relative.parts) == 2 and relative.suffix == ".pdf"
    if relative.parts[0] == "figure-src":
        return relative.suffix in {".py", ".tex", ".svg", ".html", ".json"}
    return relative.suffix == ".tex"


def _snapshot(manuscript: Path) -> dict[str, str]:
    return {
        p.relative_to(manuscript).as_posix(): sha256_file(p)
        for p in manuscript.rglob("*")
        if p.is_file() and p.resolve() == p and _editable(p.relative_to(manuscript))
    }


def _draft_roots(paths, campaign):
    state_path = campaign.get("state_path")
    if not state_path:
        return []
    root = Path(state_path).resolve()
    if root.is_relative_to(paths.data.resolve()) and root != paths.data.resolve():
        return [root, root / "review-data", root / "publication"]
    return []


def draft_paper_id(paths, campaign):
    ids = {
        path.stem for root in _draft_roots(paths, campaign)
        for path in (root / "registry" / "papers").glob("*.yaml")
        if path.is_file() and path.resolve() == path
    }
    return next(iter(ids)) if len(ids) == 1 else None


def paper_root(paths, campaign, paper_id, *, include_shared=True):
    """Find the review draft in the campaign before considering the data repository."""
    roots = _draft_roots(paths, campaign)
    if include_shared:
        roots.append(paths.data.resolve())
    return next((root for root in roots if root.resolve() == root and (
        (root / "registry" / "papers" / f"{paper_id}.yaml").is_file()
        or (root / "papers" / paper_id / "manuscript" / "main.tex").is_file()
    )), None)


def check(paths, settings, paper_id, root):
    from .program_autonomy import DeliveryError, _run_paper_command

    try:
        return _run_paper_command(
            replace(paths, data=root), settings, ["figures", "check", paper_id, "--no-rebuild"],
            accept=(0, 1), timeout=35,
        )
    except DeliveryError as exc:
        return {"blocking": [{"figure": "manuscript", "code": "FIG-CHECK-FAILED",
                              "message": str(exc)}], "repair_required": []}


def queue(db, paths, settings, report, *, task, packet, result_path, paper_id, root, audit, round_number):
    campaign_id = str(task["campaign_id"])
    key = hashlib.sha256(f"{task['task_id']}:{round_number}".encode()).hexdigest()[:32]
    task_id = f"figure-repair:{key}"
    if db.task(task_id):
        return task_id
    runner = next((name for name, spec in sorted(settings.runners.items())
                   if spec.tier == "worker" and spec.provider == "openai-codex"), None)
    if runner is None:
        return None
    manuscript = Path(audit.get("manuscript") or root / "papers" / paper_id / "manuscript")
    if (not manuscript.is_absolute() or not manuscript.is_relative_to(root)
            or not manuscript.is_dir() or manuscript.resolve() != manuscript):
        return None
    input_path = paths.program_control / "figure-repairs" / f"{key}.json"
    atomic_write_json(input_path, {
        "paper_id": paper_id,
        "manuscript": str(manuscript),
        "draft_root": str(root),
        "original_ready_task": task["task_id"],
        "original_ready_result": str(result_path),
        "ready_packet": dict(packet),
        "round": round_number,
        "baseline": _snapshot(manuscript),
        "findings": [*audit.get("blocking", []), *audit.get("repair_required", [])],
    })
    campaign = db.campaign(campaign_id) or {}
    db.enqueue_task(
        task_id=task_id, campaign_id=campaign_id, domain=str(task["domain"]),
        task_type=TASK_TYPE, routing_reason=TASK_TYPE, runner=runner,
        parent_task_id=str(task["task_id"]), input_path=str(input_path),
        agent_role="writer", session_mode="fresh", skill_path=SKILL,
        priority=int(campaign.get("priority") or 0) + 1, max_attempts=1,
        max_wall_seconds=min(3600, settings.max_task_wall_seconds),
        objective=(
            "Read the figure-repair packet. Copy its manuscript to your workspace. Fix the named "
            "figure issues on that copy, following the figure skill and templates. Preserve the "
            "registered endpoint, results and claims. Use real registered data for result plots. "
            "Build vector figures and inspect every rendered PNG, then run figures check on the "
            "copy. Update only the plan, figure code, vector PDFs and figure-related TeX "
            "(figure environments and standalone sentences starting with Figure and citing it "
            "with a TeX reference). Leave canonical files untouched. Return changed "
            "files only, in one ZIP artifact with artifact_id figure-edits, with paths relative "
            "to manuscript/ and no enclosing directory. Set the result status to completed when "
            "returning a repair, even if some findings remain. Describe the PNG inspection and "
            "remaining check findings in the result summary. Do not review or submit the paper."
        ),
        **default_task_resources(settings).to_dict(),
    )
    report.enqueued.append(task_id)
    return task_id


_FIGURE_ENV = re.compile(r"\\begin\{(figure\*?|wrapfigure|SCfigure)\}.*?\\end\{\1\}", re.S)
_FIGURE_REFERENCE = re.compile(r"\\(?:ref|cref|autoref)\{[^{}]+\}")


def _validate_tex(before: bytes, after: bytes, relative: Path) -> None:
    """Keep the scientific manuscript text intact outside figure environments."""
    original = _FIGURE_ENV.sub("", before.decode("utf-8")).splitlines()
    revised = _FIGURE_ENV.sub("", after.decode("utf-8")).splitlines()
    for operation, _, _, start, end in SequenceMatcher(a=original, b=revised, autojunk=False).get_opcodes():
        if operation == "equal":
            continue
        if operation != "insert" or any(
            line.strip() and (not line.lstrip().startswith("Figure") or not _FIGURE_REFERENCE.search(line))
            for line in revised[start:end]
        ):
            raise ValueError(f"Figure repair changed text outside its scope: {relative}")


def apply(db, paths, task, packet, read_json):
    """Import bounded figure edits from a successfully ingested, hash-bound bundle."""
    bundle = Path(db.result_bundle_path(str(task["task_id"])) or "")
    manuscript = Path(packet["manuscript"])
    if (not manuscript.is_relative_to(paths.data.resolve()) or manuscript.resolve() != manuscript
            or not manuscript.is_dir()):
        raise ValueError("Figure repair manuscript moved")
    outputs = [a for a in read_json(bundle).get("artifacts", []) if a.get("artifact_id") == "figure-edits"]
    if len(outputs) != 1:
        raise ValueError("Expected one figure-edits ZIP")
    artifact = outputs[0]
    uri = urlparse(artifact["uri"])
    source = Path(unquote(uri.path)).resolve()
    if (uri.scheme != "file" or uri.netloc or not source.is_relative_to(bundle.parent / "artifacts")
            or not source.is_file() or source.stat().st_size > MAX_BYTES
            or sha256_file(source) != artifact.get("sha256")):
        raise ValueError("Unsafe or changed figure-edits artifact")
    baseline = packet["baseline"]
    current = _snapshot(manuscript)
    changes = {}
    with ZipFile(source) as archive:
        files = archive.infolist()
        if len(files) > 80 or sum(item.file_size for item in files) > MAX_BYTES:
            raise ValueError("Figure-edits ZIP exceeds limits")
        for item in files:
            relative = Path(item.filename)
            target = manuscript / relative
            if (item.is_dir() or relative.is_absolute() or not relative.parts or ".." in relative.parts
                    or relative.as_posix() != item.filename or target.resolve() != target
                    or target in changes or not _editable(relative)):
                raise ValueError(f"Unexpected figure edit: {item.filename}")
            replacement = archive.read(item)
            if relative.suffix == ".tex" and relative.parts[0] != "figure-src":
                if relative.as_posix() not in baseline or not target.is_file():
                    raise ValueError(f"Figure repair cannot introduce a new manuscript text file: {relative}")
                _validate_tex(target.read_bytes(), replacement, relative)
            changes[target] = replacement
    if not changes:
        raise ValueError("Figure-edits ZIP is empty")
    for relative in current.keys() | baseline.keys():
        if current.get(relative) != baseline.get(relative):
            value = changes.get(manuscript / relative)
            if value is None or current.get(relative) != hashlib.sha256(value).hexdigest():
                raise ValueError(f"Manuscript changed during figure repair: {relative}")
    # Prepare every replacement before publishing. Replaying the same result accepts
    # bytes already published, including after an interrupted replacement.
    with tempfile.TemporaryDirectory(prefix=".figure-edits-", dir=manuscript) as name:
        stage = Path(name)
        for index, (target, content) in enumerate(changes.items()):
            target.parent.mkdir(parents=True, exist_ok=True)
            (stage / str(index)).write_bytes(content)
        for index, target in enumerate(changes):
            os.replace(stage / str(index), target)


IMPORT_ERRORS = (BadZipFile, OSError, ValueError, RuntimeError, KeyError)
