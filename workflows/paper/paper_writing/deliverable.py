"""One deliverability verdict: ``deliverable(paper)`` (2026-11-25, B5).

Before this module "can this paper be delivered" was decided in nine places with their own
copies of the same tests (architecture report 2026-11-24, problem 5 and P28/P32/F02). They now
share these definitions:

* :func:`deliverable` -- the verdict, built on ``release_pipeline.release_status`` (whose
  ``issues`` are the delivery-exit problems, each with its remedy): ``deliverable`` is true when
  the review is ready and current, the paper is not frozen and no issue is open. ``paper-writing
  program release-status`` prints it under ``deliverable``; the orchestrator's
  ``queue_registered_ready`` reads it from there.
* :func:`exit_issues` -- the delivery-exit problems themselves (``review_flow.delivery_issues``:
  the mechanical floor, venue and support checks). ``release_status`` and
  ``handoff.validate_release_preconditions`` both take them from here.
* :func:`stage_issues` -- the floor as the author seat and the presentation precheck see it.
* :func:`registry_ready` -- what the registry says about a delivered package (the site
  submitter rule, ``site_assignments.classify``).
* :func:`delivered` -- "the current version is delivered" (``openlabs.delivery_facts``, also
  used by ``program reconcile``).
* :func:`second_author` -- the default submitter: the paper's second author, else the default
  roster's (user 2026-11-15; ``program_delivery.default_handler`` and
  ``site_assignments.default_submitter``).

:data:`STAGE_EFFECTS` declares, for the checks that act at more than one stage, what each one
does at review, at the presentation precheck and at delivery. Nothing here changes an effect;
the table states the ones in force so a difference is a recorded choice, not an accident.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "openlabs.deliverable.v1"

# What each check does at each stage. "blocking" stops that stage; "advisory" is recorded and
# travels with the package; "-" the check does not run there.
STAGE_EFFECTS: tuple[dict[str, str], ...] = (
    {"check": "hard kinds: numbers/statistics, formulas, figure-text mismatch, preregistration, "
              "nonexistent citation (review_flow.HARD_KINDS)",
     "review": "blocking", "presentation": "blocking", "delivery": "-",
     "why": "user 2026-11-23: always material"},
    {"check": "mechanical floor: byline and registry byline, body length, figure counts, "
              "schematic present, AI-use declaration (delivery_floor, author view)",
     "review": "advisory (preparation_advisories)", "presentation": "blocking (precheck)",
     "delivery": "blocking", "why": "GQ1 2026-11-22: form is checked at the exit, not judged"},
    {"check": "schematic route: vector source (SCHEMATIC-ROUTE-NOT-VECTOR)",
     "review": "advisory (preparation_advisories)", "presentation": "blocking (precheck)",
     "delivery": "blocking", "why": "user 2026-11-23/25: no delivery before the figures are done"},
    {"check": "delivery reader saw the current figures (FIGURES-NOT-REVIEWED, "
              "SCHEMATIC-ROUTE-UNREVIEWED)",
     "review": "-", "presentation": "-", "delivery": "blocking (remedy: delta review)",
     "why": "user 2026-11-25: the presentation review ready decision is the figure gate"},
    {"check": "figure float placement (FIG-FLOAT-*)",
     "review": "advisory (presentation layout category)", "presentation": "blocking (precheck)",
     "delivery": "blocking", "why": "float_placement 2026-11-23; recorded conflict P08"},
    {"check": "venue abstract format (ABSTRACT-VENUE-FORMAT)",
     "review": "advisory (editorial_rewrite_advisory)", "presentation": "-",
     "delivery": "blocking", "why": "editorial rewrite optional since P2 2026-11-22"},
    {"check": "provisional escalation score 7.0 (venue_policy)",
     "review": "advisory (apply_review_track)", "presentation": "-",
     "delivery": "blocking (validate_release_preconditions)", "why": "user 2026-11-07; D14"},
    {"check": "verified target venue (TARGET-UNVERIFIED), registered venue body limit",
     "review": "-", "presentation": "-", "delivery": "blocking", "why": "venue_eligibility"},
    {"check": "support citations: process narrative, first/availability citation",
     "review": "-", "presentation": "-", "delivery": "advisory (preparation notes)",
     "why": "GATE1 2026-11-22"},
    {"check": "submission package (投稿包): cover letter, suggested reviewers, declarations as "
              "form text, single-file LaTeX equivalence (submission_bundle)",
     "review": "-", "presentation": "-",
     "delivery": "advisory (README items and release_metadata.source_artifact.missing_required)",
     "why": "user 2026-11-25; the human pre-submission gate decides; new checks default to advice"},
    {"check": "review ready and current, support bound, snapshot unchanged, Git committed",
     "review": "-", "presentation": "-", "delivery": "blocking", "why": "E06"},
)


# Standard-library-only modules of the orchestrator package that paper_writing reads.
PURE_OPENLABS_MODULES = frozenset({"holds", "delivery_facts"})


def openlabs_module(name: str):
    """A pure module of the orchestrator package (openlabs.holds, openlabs.delivery_facts),
    importable from this checkout without the orchestrator's dependencies.

    The paper-writing environment does not put ``orchestrator/src`` on the path. Appending it
    and importing ``openlabs.<name>`` was not enough (2026-11-26): from a working directory that
    holds the code checkout as ``openlabs/`` (``/workspace/openlabs``) Python had already bound
    ``openlabs`` to that directory as a namespace package, so ``openlabs.holds`` was not found
    and the site-assignment sync after an upload failed. The file is now loaded from this
    checkout by path when the package import does not provide it.
    """
    if name not in PURE_OPENLABS_MODULES:
        raise ValueError(f"openlabs.{name} is not a pure orchestrator module")
    import importlib
    import importlib.util

    try:
        module = importlib.import_module(f"openlabs.{name}")
    except ImportError:
        module = None
    if module is not None and getattr(module, "__file__", None):
        return module
    key = f"paper_writing._openlabs_{name}"
    if key in sys.modules:
        return sys.modules[key]
    path = Path(__file__).resolve().parents[3] / "orchestrator" / "src" / "openlabs" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None or not path.is_file():
        raise ImportError(f"openlabs.{name} is missing from this checkout: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    return module


def orchestrator_module(name: str):
    """``openlabs.<name>`` of this checkout's orchestrator package, for modules that are not
    pure (``program_autonomy``, ``config``: relative imports, the whole package).

    Same cause as :func:`openlabs_module` (2026-11-26): in the paper-writing environment
    ``orchestrator/src`` is not on the path, and from ``/workspace/openlabs`` the code checkout
    binds ``openlabs`` (and ``openlabs.config``, the checkout's ``config/`` directory) as
    namespace packages, so ``journal_mail`` failed on ``openlabs.program_autonomy`` and
    ``journal-history sync`` on ``openlabs.config``. This puts the checkout's
    ``orchestrator/src`` on the path and drops namespace bindings of ``openlabs`` (modules
    without a file, or from outside that directory) before importing the real package.
    """
    import importlib

    source = Path(__file__).resolve().parents[3] / "orchestrator" / "src"
    if not (source / "openlabs" / "__init__.py").is_file():
        raise ImportError(f"the orchestrator package is missing from this checkout: {source}")
    package = sys.modules.get("openlabs")
    if package is None or not getattr(package, "__file__", None):
        for key in [k for k in sys.modules if k == "openlabs" or k.startswith("openlabs.")]:
            origin = getattr(sys.modules[key], "__file__", None)
            if not origin or not Path(origin).resolve().is_relative_to(source.resolve()):
                del sys.modules[key]
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    importlib.invalidate_caches()
    return importlib.import_module(f"openlabs.{name}")


def delivered(metadata: Mapping[str, Any] | None, root: str | Path, paper_id: str) -> bool:
    """The current version is delivered: registry delivery block plus its receipt."""
    return openlabs_module("delivery_facts").delivered(metadata, root, paper_id)


def registry_ready(registry: Mapping[str, Any] | None,
                   package: Mapping[str, Any] | None) -> list[str]:
    """Why the registry says a delivered package is not submittable (empty: it is)."""
    if registry is None:
        return []
    reasons = []
    release = registry.get("writing_release") or {}
    if release.get("status") != "ready":
        reasons.append(f"registry writing_release {release.get('status')}")
    version = str(registry.get("version") or "")
    if package is not None and version and version != str(package.get("version") or ""):
        reasons.append(f"registry version {version} is not the delivered "
                       f"{package.get('version')} (revision in progress)")
    return reasons


def _byline(metadata: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    authors = (metadata or {}).get("authors")
    if isinstance(authors, Mapping):
        authors = authors.get("people")
    return [item for item in authors or [] if isinstance(item, Mapping)]


def second_author(metadata: Mapping[str, Any] | None,
                  roster: list[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], str] | None:
    """The default submitter: the paper's second author, else the default roster's."""
    for source, people in (("byline_second_author", _byline(metadata)),
                           ("default_roster_second_author",
                            [p for p in roster or [] if isinstance(p, Mapping)])):
        if len(people) >= 2:
            return people[1], source
    return None


def exit_issues(paper_id: str, metadata: Mapping[str, Any], root: Path,
                record: Mapping[str, Any] | None = None, *,
                notes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The delivery-exit problems (the one computation release_status and handoff share)."""
    from paper_writing.review_flow import delivery_issues

    return delivery_issues(paper_id, metadata, root, record, notes=notes)


def stage_issues(paper_id: str, metadata: Mapping[str, Any], root: Path,
                 record: Mapping[str, Any] | None = None, *, stage: str) -> list[dict[str, Any]]:
    """The floor at ``author``/``presentation`` (author view), or the exit at ``delivery``."""
    if stage == "delivery":
        return exit_issues(paper_id, metadata, root, record)
    if stage not in {"author", "presentation"}:
        raise ValueError(f"unknown stage {stage!r}")
    from paper_writing.delivery_floor import check

    return check(paper_id, metadata, root, author=True)["issues"]


def _effect(code: str) -> str:
    if code in {"FIGURES-NOT-REVIEWED", "SCHEMATIC-ROUTE-UNREVIEWED"}:
        return "delivery reader saw the current figures"
    if code.startswith("SCHEMATIC-ROUTE"):
        return "schematic route"
    if code.startswith("FIG-FLOAT"):
        return "figure float placement"
    if code == "ABSTRACT-VENUE-FORMAT":
        return "venue abstract format"
    if code in {"TARGET-UNVERIFIED", "VENUE-BODY-LENGTH"}:
        return "verified target venue"
    if code.startswith("SUPPORT-"):
        return "support citations"
    if code.startswith("REVIEW-") or code in {"MANUSCRIPT-SOURCE-MISSING", "DELIVERY-CHECK-FAILED"}:
        return "review ready and current"
    return "mechanical floor"


def summarize(status: Mapping[str, Any]) -> dict[str, Any]:
    """The verdict from a ``release_status`` result (no I/O)."""
    review = status.get("review") or {}
    issues = [{"code": str(item.get("code") or ""), "remedy": item.get("remedy"),
               "source": item.get("source"), "message": str(item.get("message") or "")[:300],
               "stage_check": _effect(str(item.get("code") or ""))}
              for item in status.get("issues") or []]
    ready, current = bool(review.get("ready")), bool(review.get("current"))
    frozen = status.get("frozen")
    return {"schema_version": SCHEMA, "paper_id": status.get("paper_id"),
            "version": status.get("version"),
            "deliverable": ready and current and not frozen and not issues,
            "ready": ready, "current": current, "decision_current": bool(review.get("decision_current")),
            "review_mode": review.get("review_mode"), "frozen": frozen,
            "delivered": bool(status.get("delivered")), "issues": issues}


def deliverable(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """The deliverability verdict of one paper (read-only)."""
    from paper_writing.release_pipeline import release_status

    return summarize(release_status(paper_id, root=root))
