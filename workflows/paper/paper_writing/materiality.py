"""Materiality of review findings: one classifier for 抓大放小 (B6, 2026-11-25).

The owner's rule (2026-11-22/23, skeleton rules D08 and D09): the data must be real and the
conclusions correct and valid; a paper that also looks like a paper passes. A finding
blocks only when it says what wrong conclusion a reader would draw if it were left as is;
wording that is merely imprecise is advice; new checks are advice by default; and the hard
kinds -- numeric or statistical errors, formula errors, figure/result mismatches,
preregistration breaches and nonexistent references -- always block.

Pass rule (user 2026-11-26, UD-20261126-review-pass-two-minor: "2个评审，只要都是小修以上就过关"):
when every referee recommends minor revision or accept (``Context.accepting``), nothing but a
hard error (``hard_error``) blocks; the editor, the delivery reader and the referees' own items
travel as advice. A referee at major revision or reject keeps the paper in revision only through
its material (substantive) items; its wording, style and detail items are advice as before.

Before B6 this rule lived in seven separate downgrade paths in ``review_flow``,
``formal_checks`` and ``presentation``, ten of them keyword patterns. Here it is one table,
``RULES``, read top to bottom: the first rule that applies to a finding decides it. Every
review role reaches it through ``decide``:

* editor and referees (``dimension_repairs`` of a first-round report, ``new_findings`` and
  ``previous_items`` of a follow-up report),
* the delivery reader (its ``repairs``),
* the formal verifier (the raw findings of its issue summary),
* the presentation reviewer (its light-review ``findings``).

Reviewers now classify each finding themselves in structured fields: ``kind`` (the error
type, ``FINDING_KINDS``), ``category`` (what it concerns, ``CATEGORIES``),
``reader_misconclusion``, ``location``, ``in_changed_region`` and ``requests`` (what the
repair asks for, ``REQUESTS``). Records written before these fields existed are classified by
the legacy fallback at the end of this module (the old keyword patterns, kept only there).
A finding with the structured fields is never re-judged by a keyword pattern.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any, Callable, Iterable, Mapping

# --------------------------------------------------------------------------- vocabulary

# Kinds that are wrong data, numbers, formulas, figure/result mismatches, preregistration
# breaches or references that do not exist: these block wherever they are found (D09).
HARD_KINDS = frozenset({"numeric_or_statistical_error", "formula_error", "figure_result_mismatch",
                        "preregistration_violation", "citation_nonexistent"})
# Every error type a reviewer can assign; ``advisory`` means "no effect on validity".
FINDING_KINDS = ("numeric_or_statistical_error", "formula_error", "figure_result_mismatch",
                 "preregistration_violation", "citation_nonexistent", "citation_error_or_unsupported",
                 "unsupported_claim", "advisory")
# The follow-up ``new_findings`` enum before B6 (kept for the schema; B6 adds citation_nonexistent).
MATERIAL_KINDS = tuple(kind for kind in FINDING_KINDS if kind != "advisory")
# What a finding concerns. The first four can carry a validity problem; the rest are form.
CATEGORIES = ("headline_claim", "body_claim", "method_or_data", "figure_or_table",
              "wording", "definition_detail", "caption_detail", "style", "length",
              "archive_or_response_format")
FORM_CATEGORIES = frozenset({"wording", "definition_detail", "caption_detail", "style"})
# What the repair asks for. Only the last two change a verdict: a request that concerns
# nothing but length, or nothing but the archive or the form of the response, is advice.
REQUESTS = ("text_edit", "figure_edit", "citation_fix", "new_analysis", "new_artifact",
            "length", "archive_or_response_format")
# The classification of DIMENSION_FINDING.kind before B6 (it is ``category`` now).
LEGACY_DIMENSION_KINDS = ("substantive", "wording", "definition_detail", "caption_detail", "length", "style")
# Formal verifier: finding kinds about the wording or support of a sentence rather than
# wrong data, numbers, formulas, figures or a preregistered rule (gate1_precision_v1).
FORMAL_PRECISION_KINDS = frozenset({"advisory", "unsupported_claim", "citation_error_or_unsupported"})
# Presentation light review (2026-11-23): only these categories can stop a paper.
PRESENTATION_BLOCKING = frozenset({"claim_or_data_mismatch", "figure_missing_or_unreadable",
                                   "venue_hard_requirement"})

_FORM_REQUESTS = frozenset({"length", "archive_or_response_format"})
# Author approval is out of scope (UD-20261126-no-author-approval-audit, user 2026-11-26 "1":
# 作者签字确认不再列为必改项，最多作为提醒；作者同意由投稿前的人工审核和期刊投稿系统负责).
# A request whose substance is that the authors approved the manuscript, consented to
# submission, signed, confirmed authorship or delegated that authority is at most advice.
# Narrow on purpose: ethics approval and participants' informed consent do not match, and
# AI-disclosure or contribution-statement accuracy requests (no approval wording) still block.
_AUTHOR_APPROVAL = re.compile(
    r"\b(?:approv\w*|consent\w*|sign(?:ed|atures?|[- ]?off)|endorse\w*)\s+"
    r"(?:\w+\s+){0,3}?(?:by|from|of)\s+(?:all|each|every|the)\s+(?:\w+\s+){0,2}?(?:co-?)?authors?\b"
    r"|\b(?:confirm\w*|authori[sz]\w*)\s+(?:\w+\s+){0,3}?(?:by|from)\s+(?:all|each|every)\s+"
    r"(?:\w+\s+){0,2}?(?:co-?)?authors?\b"
    r"|\b(?:traceable|attributable)\s+to\s+(?:all|each|every)\s+(?:\w+\s+){0,2}?(?:co-?)?authors?\b"
    r"|\b(?:co-?)?authors?'?s?\s+(?:collective\s+|written\s+|individual\s+)?(?:approv\w*|consent\w*|signatures?|"
    r"sign-?off|endorsement)\b"
    r"|\b(?:approval|approved)\s+(?:of|for)\s+(?:the\s+)?(?:\w+\s+){0,3}?(?:manuscript|submission|version|"
    r"article|paper)\b"
    r"|\bconsent\s+(?:to|for)\s+(?:the\s+)?(?:submission|submit\w*|publication|publish\w*)\b"
    r"|\b(?:delegat\w*\s+(?:\w+\s+){0,3}?(?:authority|by\s+(?:each|every|all)\s+(?:co-?)?authors?)"
    r"|authority\s+delegated)\b"
    r"|\bauthorship\s+(?:confirmation|approval|consent|sign-?off)\b"
    r"|作者(?:签字|签名|同意|授权)|投稿同意|同意投稿", re.I)
_NOT_AUTHOR_APPROVAL = re.compile(r"\b(?:ethic\w*|IRB|institutional\s+review|committee|participants?|patients?|"
                                  r"human\s+subjects?|informed\s+consent|licen[cs]\w*|permission\s+to\s+reproduce)\b"
                                  r"|伦理|知情同意", re.I)
SOURCES = ("dimension", "new_finding", "previous", "reader", "formal", "presentation")
BLOCK, ADVICE = "block", "advice"


@dataclasses.dataclass(frozen=True)
class Context:
    """What the verdict on one finding may depend on besides the finding itself."""
    # A previous round exists: a new finding must say why the previous round missed it.
    followup: bool = False
    # The previous round's mandatory items (None: no list, nothing to link to).
    prior_items: frozenset[str] | None = None
    # The text added this round, normalised (None: unknown, everything counts as inside).
    changed_text: str | None = None
    # Every referee recommends accept or minor revision.
    accepting: bool = False
    # Formal-verification or rejection-history blockers stand (the decision is not about text).
    formal_or_history: bool = False
    # No science or formal-accuracy finding blocks (set once those have been decided).
    dimensions_clear: bool = False
    # ``dimensions_clear`` and nothing else scientific or technical blocks.
    science_clear: bool = False
    # The one check after a final ruling (定稿裁定): only must-fix items and hard errors block.
    final_check: bool = False
    # The previous items come from the follow-up protocol, which requires evidence and a
    # reader misconclusion for every unresolved item.
    followup_protocol: bool = False
    # Formal verifier: finding kinds of the bound report, by item label.
    formal_kinds: Mapping[str, str] = dataclasses.field(default_factory=dict)
    # Presentation follow-up: the previous light review's blocking items (None: first review).
    presentation_previous: tuple | None = None


@dataclasses.dataclass(frozen=True)
class Finding:
    """One finding of any role, in the fields the decision table reads."""
    source: str
    role: str = ""
    kind: str | None = None             # FINDING_KINDS; None: not stated (legacy)
    category: str | None = None         # CATEGORIES (presentation: its own categories)
    misconclusion: str = ""
    why_missed: str = ""
    previous_item: str = ""
    dimension: str | None = None
    location: str = ""
    in_changed_region: bool = True
    requests: frozenset[str] = frozenset()
    structured: bool = False
    complete: bool = True               # every field the source protocol requires is filled
    # formal verifier
    formal_category: str = ""
    formal_status: str = ""
    # presentation
    blocking_flag: bool = False
    previous_index: Any = None
    # The request is about author approval or consent (out of scope; UD-20261126).
    author_approval: bool = False
    # Legacy previous item (no structured kind) whose evidence states an error still present.
    present_error: bool = False

    @property
    def new(self) -> bool:
        return not self.previous_item

    def linked(self, context: Context) -> bool:
        return bool(self.previous_item) and (context.prior_items is None
                                             or self.previous_item in context.prior_items)

    @property
    def only_length(self) -> bool:
        """The repair asks for nothing but length (and possibly the response form)."""
        return "length" in self.requests and self.requests <= _FORM_REQUESTS

    @property
    def only_archive(self) -> bool:
        """The repair asks for nothing but the archive or the response form (and possibly length)."""
        return (self.category == "archive_or_response_format" or "archive_or_response_format" in self.requests) \
            and self.requests <= _FORM_REQUESTS


@dataclasses.dataclass(frozen=True)
class Rule:
    id: str
    verdict: str
    applies: Callable[[Finding, Context], bool]
    why: str


@dataclasses.dataclass(frozen=True)
class Decision:
    verdict: str
    rule: str

    @property
    def blocks(self) -> bool:
        return self.verdict == BLOCK


def _sources(*names: str) -> Callable[[Finding], bool]:
    return lambda f: f.source in names


_REVIEW = _sources("dimension", "new_finding", "reader")
_NEW_TEXT = _sources("new_finding", "reader")


def hard_error(f: Finding) -> bool:
    """A genuine hard error: the paper is wrong as written, whatever the panel recommends
    (UD-20261126-review-pass-two-minor). Kept narrow on purpose:

    * ``numeric_or_statistical_error``, ``formula_error``: a reported number, statistic, bound or
      formula is wrong -- a proven-wrong result cannot be submitted;
    * ``figure_result_mismatch``: a claim or figure contradicts the paper's own data;
    * ``preregistration_violation``: the verdict does not follow from the registered rule, so the
      headline result is wrong under the paper's own protocol;
    * ``citation_nonexistent``: a fabricated reference is an integrity problem;
    * a previous item that tracks a formal verifier ``error`` (a formula, number or citation the
      verifier found wrong against its source), or a previous item written before the structured
      kinds whose evidence states that an error is still present (the legacy fallback's
      ``_states_present_error``);
    * an ``unsupported_claim`` in a headline claim (title, abstract, highlights, conclusions)
      raised by the editor or a referee: the main claim says what the evidence does not show,
      which is the claim--data mismatch an editor reads first (kept from rule
      ``accepting_unsupported``). The delivery reader's headline items stay advice.

    Unverifiable references and the verifier's other blocking findings are decided by the formal
    rules (source ``formal``); mandatory declarations, the AI-use disclosure and hard venue limits
    are checked deterministically at delivery (``delivery_floor``). Neither depends on the panel.
    """
    return (f.kind in HARD_KINDS
            or (f.source == "previous" and (": error —" in f.previous_item or f.present_error))
            or (f.kind == "unsupported_claim" and f.category == "headline_claim" and f.source != "reader"))


def _accepting_panel(f: Finding, c: Context) -> bool:
    return c.accepting and not hard_error(f)


def _presentation_blocks(f: Finding, c: Context) -> bool:
    if not f.blocking_flag or f.category not in PRESENTATION_BLOCKING:
        return False
    if f.structured and not f.misconclusion.strip():
        return False
    if c.presentation_previous is None:
        return True
    index = f.previous_index
    return isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= len(c.presentation_previous)


# --------------------------------------------------------------------------- decision table
#
# Read top to bottom; the first rule that applies decides. ``advice`` rules only downgrade;
# ``hard_kind`` sits above every downgrade that must not touch a hard error. A finding that
# no rule downgrades blocks (``material``).
RULES: tuple[Rule, ...] = (
    # Out of scope for every role (UD-20261126-no-author-approval-audit): above every blocking rule.
    Rule("author_approval_out_of_scope", ADVICE, lambda f, c: f.author_approval,
         "author approval, consent to submit, signatures and delegated authority are handled by the "
         "pre-submission human review and the journal's submission system"),
    # Formal verifier (gate1_precision_v1, 2026-11-23; source routing 2026-11-23 audit item 12).
    Rule("formal_advisory", ADVICE, lambda f, c: f.source == "formal" and f.formal_category == "advisory",
         "the verifier itself classified the item as advice"),
    Rule("formal_source_routing", ADVICE, lambda f, c: f.source == "formal" and f.formal_category == "source_routing",
         "reaching a source (catalogue URL, publisher 403) is checked at delivery, not a manuscript error"),
    Rule("formal_precision", ADVICE, lambda f, c: f.source == "formal" and f.formal_category == "scientific" and (
        f.formal_status == "gap" or f.kind in FORMAL_PRECISION_KINDS),
         "a sentence not fully supported as worded (gap, unsupported claim, citation support) is advice"),
    Rule("formal_material", BLOCK, lambda f, c: f.source == "formal",
         "errors, unchecked claims, reference rows, technical and preparation problems block"),
    # Presentation light review (2026-11-23: claim/data mismatch, missing figure, hard venue rule).
    Rule("presentation_material", BLOCK, lambda f, c: f.source == "presentation" and _presentation_blocks(f, c),
         "a blocking category marked blocking, with its consequence stated (records since B6); on "
         "follow-up only an unresolved previous blocking item"),
    Rule("presentation_form", ADVICE, lambda f, c: f.source == "presentation",
         "layout, typography, wording and style travel with the package"),
    # Both referees at minor or better (UD-20261126-review-pass-two-minor): an error that lives only
    # in the archive, the supporting files or the response (a stale claim-evidence map row) does not
    # make the paper wrong; it travels with the package. The only narrowing of D09.
    Rule("accepting_archive_only", ADVICE, lambda f, c: c.accepting and f.source in (
        "dimension", "new_finding", "reader", "previous") and f.structured and f.only_archive and hard_error(f),
         "with both referees at minor revision or better, a finding about the archive, supporting files or "
         "response alone is advice, even when typed as an error"),
    # Previous items (the item already met the materiality threshold when it was raised).
    Rule("previous_incomplete", ADVICE, lambda f, c: f.source == "previous" and c.followup_protocol and not f.complete,
         "an unresolved item needs its evidence and the wrong conclusion a reader would still draw"),
    Rule("previous_hard_kind", BLOCK, lambda f, c: f.source == "previous" and f.kind in HARD_KINDS,
         "a hard error that is still present blocks"),
    Rule("previous_accepting_documentation", ADVICE, lambda f, c: f.source == "previous" and c.accepting
         and c.science_clear and f.only_archive,
         "with the science clear, how the response is written or what the archive shows is advice"),
    Rule("previous_accepting_panel", ADVICE, lambda f, c: f.source == "previous" and _accepting_panel(f, c),
         "both referees recommend minor revision or better: the paper passes; an open item that is not a "
         "hard error travels as advice (UD-20261126-review-pass-two-minor)"),
    Rule("previous_open", BLOCK, lambda f, c: f.source == "previous", "an unresolved previous blocker"),
    # Review findings (editor, referees, delivery reader).
    Rule("classified_advisory", ADVICE, lambda f, c: _REVIEW(f) and (f.kind == "advisory" or not f.complete),
         "the reviewer classified it as advice, or left a required field empty"),
    Rule("no_reader_misconclusion", ADVICE, lambda f, c: _REVIEW(f) and not f.misconclusion.strip(),
         "a blocker must say what wrong conclusion a reader would draw (D08)"),
    Rule("new_without_why_missed", ADVICE, lambda f, c: _REVIEW(f) and c.followup and not f.linked(c)
         and not f.why_missed.strip(), "a new issue in a follow-up must say why the previous round missed it"),
    Rule("hard_kind", BLOCK, lambda f, c: _REVIEW(f) and f.kind in HARD_KINDS,
         "numeric, statistical, formula, figure/result, preregistration and nonexistent-reference errors (D09)"),
    Rule("form_category", ADVICE, lambda f, c: _REVIEW(f) and (f.category in FORM_CATEGORIES or f.category == "length"),
         "wording, definitions, captions, style and length are advice"),
    Rule("final_check_new", ADVICE, lambda f, c: _NEW_TEXT(f) and c.final_check,
         "after a final ruling only its must-fix items and hard errors block"),
    Rule("length_only", ADVICE, lambda f, c: _REVIEW(f) and f.dimension != "science" and not c.formal_or_history
         and f.only_length, "a request only about length (hard limits are enforced at delivery)"),
    Rule("reader_cannot_see", ADVICE, lambda f, c: f.source == "reader" and f.only_archive,
         "the reader sees the manuscript only: archive contents and response format are not its to block"),
    Rule("outside_changed_region", ADVICE, lambda f, c: _NEW_TEXT(f) and f.new and not f.in_changed_region,
         "a new non-hard finding in a follow-up must concern text changed this round"),
    Rule("accepting_reader", ADVICE, lambda f, c: f.source == "reader" and c.accepting,
         "with every referee at accept or minor revision the reader's items are advice"),
    Rule("accepting_unsupported", ADVICE, lambda f, c: f.source == "new_finding" and c.accepting
         and f.kind == "unsupported_claim" and f.category != "headline_claim",
         "with every referee at accept or minor revision, a body sentence not fully supported as worded is "
         "advice; a headline conclusion (title, abstract, highlights, conclusions) the evidence does not "
         "support still blocks"),
    Rule("accepting_documentation", ADVICE, lambda f, c: _REVIEW(f) and c.accepting and c.science_clear
         and f.dimension not in ("science", "formal_accuracy")
         and f.only_archive,
         "with the science clear, a request about the response, citation form, documents or displays is advice"),
    Rule("accepting_readability", ADVICE, lambda f, c: f.source == "dimension" and f.dimension == "readability"
         and c.accepting and c.dimensions_clear,
         "with every referee at accept or minor revision and no science finding, readability repairs are advice"),
    # User 2026-11-26: "2个评审，只要都是小修以上就过关". The editor, the delivery reader and the
    # referees' own items add advice; only a hard error (``hard_error``) still blocks.
    Rule("accepting_panel", ADVICE, lambda f, c: _REVIEW(f) and _accepting_panel(f, c),
         "both referees recommend minor revision or better: the paper passes; editor, reader and referee "
         "items that are not hard errors are advice (UD-20261126-review-pass-two-minor)"),
    Rule("material", BLOCK, lambda f, c: True, "a complete finding with a stated reader misconclusion"),
)
RULE_IDS = tuple(rule.id for rule in RULES)


def decide(raw: Mapping[str, Any] | Finding, *, source: str, context: Context, role: str = "",
           dimension: str | None = None) -> Decision:
    """The verdict on one finding: the single entry point of the materiality rule."""
    finding = raw if isinstance(raw, Finding) else normalize(raw, source=source, role=role,
                                                               dimension=dimension, context=context)
    for rule in RULES:
        if rule.applies(finding, context):
            return Decision(rule.verdict, rule.id)
    raise AssertionError("the decision table ends with a catch-all rule")


def question_finding(recall: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The delivery reader's cold read as a headline finding (pipeline slimming 2026-11-26).

    ``question_stated_in_title_abstract.stated`` false: the title and abstract do not say what
    problem the paper solves. It goes through the table like any reader repair (category
    ``headline_claim`` with its reader misconclusion); a record without the field adds nothing.
    """
    cold = recall.get("question_stated_in_title_abstract")
    if not isinstance(cold, Mapping) or cold.get("stated") is not False:
        return []
    quote = _text(cold.get("quote"))
    return [{"repair": "State the research problem in the title and abstract: whose decision or "
                       "understanding is at stake and what gap the paper closes.",
             "category": "headline_claim", "requests": ["text_edit"], "in_changed_region": True,
             "reader_misconclusion": "The reader does not know what problem the paper solves.",
             "location": "Title and abstract" + (f': "{quote}"' if quote else "")}]


# --------------------------------------------------------------------------- normalisation

def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _requests(value: Any) -> frozenset[str]:
    return frozenset(v for v in value if v in REQUESTS) if isinstance(value, (list, tuple)) else frozenset()


def structured(raw: Mapping[str, Any]) -> bool:
    """Whether a finding carries the B6 fields (``category`` and ``requests``)."""
    return isinstance(raw.get("category"), str) and isinstance(raw.get("requests"), list)


def normalize(raw: Mapping[str, Any], *, source: str, context: Context, role: str = "",
              dimension: str | None = None) -> Finding:
    if source not in SOURCES:
        raise ValueError(f"unknown finding source: {source}")
    if source == "formal":
        location = _text(raw.get("location"))
        return Finding(source=source, role=role or "formal", location=location,
                       kind=context.formal_kinds.get(location), formal_category=_text(raw.get("category")),
                       formal_status=_text(raw.get("status")))
    if source == "presentation":
        return Finding(source=source, role=role or "delivery_reader", category=presentation_category(raw),
                       location=_text(raw.get("location")), blocking_flag=bool(raw.get("blocking")),
                       previous_index=raw.get("previous_item"), misconclusion=_text(raw.get("reader_misconclusion")),
                       structured="reader_misconclusion" in raw)
    if source == "previous":
        finding = _previous(raw, role, context)
        text = _text(raw.get("item"))
    else:
        finding = _review_finding(raw, source, role, dimension, context)
        text = _text(raw.get("repair")) or _text(raw.get("finding")) or _text(raw.get("change"))
    return dataclasses.replace(finding, author_approval=author_approval_request(text)) if text else finding


def _previous(raw: Mapping[str, Any], role: str, context: Context) -> Finding:
    item = _text(raw.get("item"))
    evidence = _text(raw.get("evidence"))
    misconclusion = _text(raw.get("reader_misconclusion"))
    if structured(raw):
        requests, category = _requests(raw.get("requests")), raw["category"]
        kind = raw.get("kind") if raw.get("kind") in FINDING_KINDS else None
    else:
        category, kind = None, None
        requests = frozenset({"archive_or_response_format"}) if documentation_request(evidence, misconclusion) \
            else frozenset()
    if category == "archive_or_response_format":
        requests = requests | {"archive_or_response_format"}
    present = not structured(raw) and _states_present_error(_sentences(evidence, misconclusion))
    return Finding(source="previous", role=role, kind=kind, category=category, misconclusion=misconclusion,
                   previous_item=item, location="Previous decision", requests=requests,
                   structured=structured(raw), complete=bool(evidence.strip() and misconclusion.strip()),
                   present_error=present)


def _review_finding(raw, source, role, dimension, context) -> Finding:
    text = _text(raw.get("repair")) or _text(raw.get("finding")) or _text(raw.get("change"))
    misconclusion = _text(raw.get("reader_misconclusion")) or _text(raw.get("wrong_conclusion"))
    location = _text(raw.get("location"))
    previous_item = _text(raw.get("previous_item"))
    if structured(raw):
        kind = raw.get("kind") if raw.get("kind") in FINDING_KINDS else None
        category = raw["category"] if raw["category"] in CATEGORIES else None
        requests = _requests(raw.get("requests"))
        flag = raw.get("in_changed_region")
        inside = context.changed_text is None or (flag is True and _quotes_changed(f"{text} {location}",
                                                                                   context.changed_text))
        complete = bool(text.strip())
        return Finding(source=source, role=role, kind=kind, category=category, misconclusion=misconclusion,
                       why_missed=_text(raw.get("why_missed")), previous_item=previous_item, dimension=dimension,
                       location=location, in_changed_region=inside, requests=requests, structured=True,
                       complete=complete)
    return _legacy_finding(raw, source, role, dimension, context, text, misconclusion, location, previous_item)


# --------------------------------------------------------------------------- legacy fallback
#
# Records written before B6 carry no ``category``/``requests``. Their classification uses the
# patterns below, exactly as the synthesis applied them on 2026-11-23/24. New records never
# reach this code: a structured finding is judged by its fields only.

_QUOTED = re.compile(r"[“\"‘]([^”\"’]{12,600})[”\"’]")
# Owner rule 2026-11-23 (抓大放小): a request about how the response is written (quote an
# entry verbatim, cite a line), about citation form, about supplying a document or script, or
# about showing something the reviewer could not see. A text stating a data, conclusion or
# citation error that is still present keeps the item blocking.
_DOCUMENT_REQUEST = re.compile(
    r"\b(?:in|into|to)\s+the\s+(?:author'?s?\s+)?(?:response|rebuttal|reply)\b|\bresponse\s+letter\b|"
    r"\bquot(?:e|ed|ing)\b|\bverbatim\b|\bcitation\s+(?:style|format|form|key)s?\b|\bcite\s+(?:it|this|the\s+line)\b|"
    r"\b(?:not|never)\s+(?:been\s+)?(?:included|supplied|provided|shown|attached|submitted|uploaded|visible|"
    r"available|quoted)\b|\bcould\s+not\s+(?:be\s+)?(?:retriev|inspect|see|access|open|verif|independently\s+verif)\w*|"
    r"\b(?:remains?|is|was)\s+unverified\b|\bdiff\s+(?:is|was)\s+empty\b|\bempty\s+diff\b|"
    r"\b(?:include|attach|supply|provide|upload|submit|show)\s+(?:the\s+)?(?:revised\s+|corrected\s+|updated\s+|"
    r"regenerated\s+|fixed\s+)?(?:script|code|file|output|json|diff|archive|log|notebook|entry)\b|"
    r"\bnot\s+yet\s+checkable\b|\bhas\s+not\s+been\s+shown\b|"
    r"回复|逐字|引用方式|补交|未提供|看不到|未展示", re.I)
_PRESENT_ERROR = re.compile(
    r"\b(?:still|remains?|continues?\s+to)\s+(?:\w+\s+){0,2}?(?:wrong|incorrect|erroneous|inconsistent|"
    r"contradict\w*|misstat\w*|mismatch\w*|overstat\w*)\b|\b(?:is|are)\s+(?:wrong|incorrect|erroneous)\b|"
    r"\bcontradicts?\b|\bdoes\s+not\s+match\b|\bdisagrees?\s+with\b|\bnon-?existent\s+(?:reference|citation)\b|"
    r"数据错误|结论错误|仍然错误|仍有错误|矛盾", re.I)
_HEDGE = re.compile(r"\b(?:if|unless|whether|would|could|might)\b|如果|若", re.I)
# Small length requests are advice (2026-11-23 audit item 13); hard limits are checked at delivery.
_LENGTH_REQUEST = re.compile(
    r"\b(?:shorten|condense|compress|trim|tighten|abridge|cut\s+(?:\w+\s+){0,3}?(?:words?|sentences?|paragraphs?|"
    r"length|by\s+\d+)|reduce\s+(?:the\s+)?(?:length|word\s+count|main[- ]text)|word\s+count|too\s+long|lengthy|"
    r"verbose|net\s+growth|over\s+length|page\s+count)\b|篇幅|字数|压缩|精简|删减", re.I)
# A follow-up finding located in a headline conclusion (the ``headline_claim`` category).
_HEADLINE_LOCATION = re.compile(r"\b(?:title|abstract|highlights?|conclusions?)\b|标题|摘要|结论", re.I)
_ARCHIVE_LOCATION = re.compile(r"\b(?:archiv\w*|readme|supporting|claim[- ]evidence\s+map|response\s+letter)\b",
                               re.I)
# Presentation records written before categories existed: only an explicit mismatch, a
# missing/unreadable figure or a hard venue rule counts; collisions, italics and the like
# are layout.
_LEGACY_BLOCKING = re.compile(
    r"does not match|do not match|mismatch|contradict|inconsistent with the (?:text|data|table|caption)"
    r"|(?:wrong|incorrect|erroneous) (?:value|number|unit|sign)|figure (?:is )?missing|missing figure"
    r"|unreadable|illegible|cannot be read|not embedded|font embedding|exceeds the (?:page|word|size) limit",
    re.I)


def plain(text: Any) -> str:
    text = re.sub(r"\\[A-Za-z]+\*?", " ", str(text or ""))
    text = re.sub(r"[{}~$]", " ", text)
    return " ".join(text.lower().split())


def changed_text(diff: str | None) -> str | None:
    """The added lines of a follow-up diff, normalised for quote matching (None: unknown)."""
    if diff is None:
        return None
    lines = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    return plain(" ".join(lines))


def _quotes_changed(text: str, changed: str) -> bool:
    for span in _QUOTED.findall(str(text or "")):
        for piece in re.split(r"\.\.\.|…|\[\.\.\.\]", span):
            piece = plain(piece).strip(" .,;:")
            if len(piece) >= 12 and piece in changed:
                return True
    return False


def in_changed_region(text: str, changed: str | None) -> bool:
    """Whether a finding quotes (at least 12 characters of) text added this round; with the
    change unknown (records before 2026-11-23) everything counts as inside."""
    return True if changed is None else _quotes_changed(text, changed)


def finding_key(change: Mapping[str, Any]) -> str:
    """One location or quotation: the same new finding raised by several roles is one item."""
    quoted = _QUOTED.findall(str(change.get("change") or "") + " " + str(change.get("location") or ""))
    return plain(quoted[0])[:120] if quoted else plain(change.get("location") or "")[:120]


def _sentences(*texts: Any) -> list[str]:
    return [s for text in texts if isinstance(text, str)
            for s in re.split(r"\n+|(?<=[.!?;。；])\s+", text) if s.strip()]


def _states_present_error(sentences: Iterable[str]) -> bool:
    return any(_PRESENT_ERROR.search(s) and not _HEDGE.search(s) for s in sentences)


def documentation_request(*texts: Any) -> bool:
    """Legacy: the text only asks for a response, citation form, document or display, with no
    data, conclusion or citation error stated as present."""
    sentences = _sentences(*texts)
    return any(_DOCUMENT_REQUEST.search(s) for s in sentences) and not _states_present_error(sentences)


def author_approval_request(text: Any) -> bool:
    """Whether a request's substance is author approval, consent to submit, signatures or
    delegated authority (out of scope since UD-20261126; ethics approval and participant consent
    are not). Only the request itself is read, not its rationale or quoted evidence."""
    body = str(text or "")
    return bool(_AUTHOR_APPROVAL.search(body)) and not _NOT_AUTHOR_APPROVAL.search(body)


def length_request(*texts: Any) -> bool:
    """Legacy: a request only about length."""
    text = " ".join(t for t in texts if isinstance(t, str))
    return bool(_LENGTH_REQUEST.search(text)) and not _states_present_error(re.split(r"(?<=[.!?;。；])\s+", text))


def presentation_category(item: Mapping[str, Any]) -> str:
    from paper_writing.presentation import CATEGORIES as PRESENTATION_CATEGORIES

    value = item.get("category")
    if value in PRESENTATION_CATEGORIES:
        return value
    text = f"{item.get('location', '')} {item.get('repair', item.get('change', ''))}"
    return "claim_or_data_mismatch" if _LEGACY_BLOCKING.search(text) else "layout"


def _legacy_finding(raw, source, role, dimension, context, text, misconclusion, location, previous_item) -> Finding:
    kind = raw.get("kind")
    if source == "new_finding":
        # Follow-up protocol: kind is the error type, all four rationale fields are required.
        complete = kind in MATERIAL_KINDS and all(
            _text(raw.get(field)).strip() for field in ("location", "finding", "reader_misconclusion", "why_missed"))
        detail = (f"{_text(raw.get('finding'))} Reader could infer: {misconclusion} "
                  f"Missed previously: {_text(raw.get('why_missed'))}")
        category = ("headline_claim" if _HEADLINE_LOCATION.search(location) and not _ARCHIVE_LOCATION.search(location)
                    else None)
        texts = (detail,)
        region = f"{_text(raw.get('finding'))} {location}"
        error_kind = kind if kind in FINDING_KINDS else None
    else:
        # DIMENSION_FINDING before B6: kind was the category, only "substantive" could block.
        complete = kind == "substantive"
        category = None if kind == "substantive" else (kind if kind in CATEGORIES else None)
        texts = (text, misconclusion)
        region = text
        error_kind = None
    requests = set()
    if documentation_request(*texts):
        requests.add("archive_or_response_format")
    if length_request(texts[0]):
        requests.add("length")
    inside = in_changed_region(region, context.changed_text)
    return Finding(source=source, role=role, kind=error_kind, category=category, misconclusion=misconclusion,
                   why_missed=_text(raw.get("why_missed")), previous_item=previous_item, dimension=dimension,
                   location=location, in_changed_region=inside, requests=frozenset(requests), structured=False,
                   complete=complete)


def explain() -> list[dict[str, str]]:
    """The decision table in readable form (for records and the prompts' documentation)."""
    return [{"rule": rule.id, "verdict": rule.verdict, "why": rule.why} for rule in RULES]
