"""Default byline of a new paper: the second author rotates (UD-20261125-second-author-rotation).

User rule (2026-11-25): "未来的默认作者，加一条规则，在王琪盛，詹静怡和成志东之间依次轮转".

``paper-writing paper create`` registers the byline of every new paper from
``registry/settings.yaml#defaults``: the first and last authors of
``defaults.second_author_rotation`` stay in place (corresponding authors), the second author
is the next person of ``order`` and the remaining roster authors keep their relative order in
between. Each person is copied whole from ``defaults.authors`` (ORCID, email, affiliation ids,
CRediT roles follow the person). The second author is also the default submitter
(``deliverable.second_author``), so the site assignment follows without further change.

No extra state file: the paper record keeps ``author_assignment`` (``source: rotation``, the
rotation index, the decision id and the user's words), and the next index is one more than
the largest index recorded in any paper record of the data repository -- its own registry and
every campaign workspace under ``workspaces/`` (papers are created there and adopted later).
The scan and the write run under an exclusive lock on the data repository's settings file, so
two seats creating papers at the same time do not take the same index. Assigning is
idempotent: a record that already has ``author_assignment`` or any registered byline is never
changed, so papers that existed before the rule are untouched.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from paper_writing.registry import load_paper_metadata, write_paper_metadata

SOURCE = "rotation"
RULE = "registry/settings.yaml#defaults.second_author_rotation"
# Paper records under workspaces/: <domain>/<campaign>/ and nested review or publication roots.
_WORKSPACE_GLOBS = tuple("workspaces/" + "*/" * depth + "registry/papers/*.yaml" for depth in (1, 2, 3, 4))


class AuthorRotationError(ValueError):
    """The rotation policy cannot build a byline from the default roster."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_root(root: str | Path) -> Path:
    """The data repository holding ``root``: the nearest ancestor with registry and workspaces."""
    root = Path(root).resolve()
    for candidate in (root, *root.parents):
        if (candidate / "registry" / "settings.yaml").is_file() and (candidate / "workspaces").is_dir():
            return candidate
    return root


def _load_settings(root: Path) -> Mapping[str, Any]:
    path = root / "registry" / "settings.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, Mapping) else {}


def policy(settings: Mapping[str, Any]) -> Mapping[str, Any] | None:
    defaults = settings.get("defaults")
    rotation = defaults.get("second_author_rotation") if isinstance(defaults, Mapping) else None
    if not isinstance(rotation, Mapping) or rotation.get("enabled", True) is False:
        return None
    return rotation if rotation.get("order") else None


def _key(person: Mapping[str, Any]) -> set[str]:
    return {str(person.get(k) or "").strip().casefold() for k in ("name", "name_zh")} - {""}


def _find(roster: list[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    wanted = str(name or "").strip().casefold()
    matches = [person for person in roster if wanted in _key(person)]
    if len(matches) != 1:
        raise AuthorRotationError(f"defaults.authors has {len(matches)} entries named {name!r}")
    return matches[0]


def byline(settings: Mapping[str, Any], index: int) -> tuple[list[dict[str, Any]], str]:
    """The registered byline for rotation ``index`` and the second author's name."""
    rotation = policy(settings)
    if rotation is None:
        raise AuthorRotationError("defaults.second_author_rotation is not configured")
    defaults = settings.get("defaults") or {}
    roster = [p for p in defaults.get("authors") or [] if isinstance(p, Mapping)]
    order = [_find(roster, name) for name in rotation["order"]]
    first = _find(roster, rotation["first_author"]) if rotation.get("first_author") else roster[0]
    last = _find(roster, rotation["last_author"]) if rotation.get("last_author") else roster[-1]
    if first is last or any(person is first or person is last for person in order):
        raise AuthorRotationError("the rotation order must not contain the first or last author")
    second = order[index % len(order)]
    middle = [p for p in roster if p is not first and p is not last and p is not second]
    people = [deepcopy(dict(p)) for p in (first, second, *middle, last)]
    return people, str(second.get("name"))


def _paper_records(root: Path) -> Iterator[Path]:
    yield from sorted((root / "registry" / "papers").glob("*.yaml"))
    for pattern in _WORKSPACE_GLOBS:
        yield from sorted(root.glob(pattern))


def recorded_indices(root: str | Path) -> dict[str, int]:
    """``paper_id -> rotation index`` for every rotation-assigned paper under the data root."""
    found: dict[str, int] = {}
    for path in _paper_records(Path(root)):
        try:
            text = path.read_text(encoding="utf-8")
            if "rotation_index" not in text:
                continue
            record = yaml.safe_load(text)
        except (OSError, yaml.YAMLError):
            continue
        assignment = record.get("author_assignment") if isinstance(record, Mapping) else None
        if (isinstance(assignment, Mapping) and assignment.get("source") == SOURCE
                and isinstance(assignment.get("rotation_index"), int)):
            paper_id = str(record.get("paper_id") or path.stem)
            found[paper_id] = max(found.get(paper_id, -1), assignment["rotation_index"])
    return found


def next_index(root: str | Path) -> int:
    return max(recorded_indices(root).values(), default=-1) + 1


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    path = root / "registry" / "settings.yaml"
    with path.open("rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def assign(paper_id: str, root: str | Path) -> dict[str, Any]:
    """Register the rotated default byline of a new paper once; later calls change nothing."""
    root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, root)
    existing = metadata.get("author_assignment")
    if isinstance(existing, Mapping):
        return {"changed": False, "status": "already_assigned", **dict(existing)}
    raw = metadata.get("authors")
    people = raw.get("people") if isinstance(raw, Mapping) else raw
    if isinstance(people, list) and people:
        return {"changed": False, "status": "existing_byline"}
    pool = data_root(root)
    settings = _load_settings(pool) or _load_settings(root)
    rotation = policy(settings)
    if rotation is None:
        return {"changed": False, "status": "no_rotation_policy"}
    effective_from = str(rotation.get("effective_from") or "")
    if effective_from and str(metadata.get("created_at") or "") < effective_from:
        return {"changed": False, "status": "created_before_rule"}
    lock_root = pool if (pool / "registry" / "settings.yaml").is_file() else root
    with _locked(lock_root):
        # The create root is usually a campaign workspace under the pool; scan it as well in
        # case it lies outside the pool's workspace globs.
        index = max(next_index(pool), next_index(root))
        authors, second = byline(settings, index)
        used = {str(ref) for person in authors for ref in person.get("affiliation_ids") or []}
        affiliations = [deepcopy(dict(item)) for item in (settings.get("defaults") or {}).get("affiliations") or []
                        if isinstance(item, Mapping) and str(item.get("id")) in used]
        assignment = {
            "source": SOURCE,
            "rule": RULE,
            "decision": rotation.get("decision"),
            "quote": rotation.get("quote"),
            "rotation_index": index,
            "second_author": second,
            "assigned_at": _now(),
        }
        metadata["authors"] = authors
        if not metadata.get("affiliations"):
            metadata["affiliations"] = affiliations
        metadata["author_assignment"] = assignment
        write_paper_metadata(paper_id, metadata, root)
    return {"changed": True, "status": "assigned", **assignment}
