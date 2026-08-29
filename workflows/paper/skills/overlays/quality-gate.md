# OpenLabs local LLM quality gate

This overlay is mandatory for every paper profile. `registry/settings.yaml#quality_gate` is the
single source of thresholds. The current minimum LLM self-review score is **5.0/10**. Never round
up, average around, or bypass it inside a profile. Change the threshold policy only with explicit
human authorization and synchronized repository policy, settings, runtime, skill, documentation,
and test updates.

For a journal manuscript beyond its basic draft in a domain configured by
`journal_target_policy`, the registry must identify a verified
2026 XinRui target system (Math Tier 1/2, Medicine Tier 1/2, or Computer Science
Tier 1/2 per domain policy), an official no-mandatory-author-fee publication route, and the
official formatting source. The canonical `manuscript/` must be marked and checked as the
venue-specific edition. A side candidate alone is a blocker. Public Zenodo ZIP names and enclosing
roots must use the registered `display_id`.

## Produce a review record

After drafting, first run
`python -m paper_writing style-check --paper-id <paper_id>`. It scans the compiled TeX tree and its
referenced bibliography metadata and must reject AI/tool narration outside the final AI-use
declaration, agent/reviewer orchestration, private repository and claim-routing terminology,
internal source/audit narration (including `audit`, `auditable`, and `auditability`), internal
audit/campaign filenames or paths, bibliography workflow notes, and preparation chronology that
does not belong in scientific prose. A registered institutional name is allowed.
Exactly one final AI-use declaration is required. It must identify the tool and textual purposes;
manuscripts with computational code must also disclose source-code-development/verification
assistance and human checking, and manuscripts reporting Codex-assisted Lean work must disclose
Lean-code preparation/checking while attributing formal verification to the pinned Lean toolchain
rather than to AI output. The check is non-scoring, but every failure is projected into
`unresolved_review_blockers`; neither score nor decision can override it. It does not authorize
concealing truthful AI use or deleting a disclosure required by the target venue.

Then run
`python -m paper_writing support-check --paper-id <paper_id>`. It must scan both formal TeX and any
standalone reader-facing reproducibility, support, or availability statement and confirm that the
manuscript cites the current Zenodo Version DOI and metadata, that the support-record title
identifies the paper's current title rather than a prior title, uses objective version-stable prose,
contains no draft/release or old/new-version history, and does not claim public access for an
unpublished draft.
For a standalone reproducibility statement, a heading that names the paper must match the current
registry title, and every declared claim identifier must occur in the canonical claim--evidence map
or the current public `CLAIMS.yaml`. Replay-command, checker, suite, test, and certificate-group
counts must be read from the exact current package; a finite certificate group must not be described
as though it were every scientific claim in the manuscript.
It must also inspect the exact registered ZIP: the current `public-support-vX.Y.Z` source label,
outer package version, reader-facing packaged claim map/README, and Version DOI must agree, and
those shipped reader documents must not narrate release or version history. Every printed path
must exist at its declared outer or nested archive base; merely finding the same basename somewhere
inside a nested ZIP does not validate a claim that it is at the outer archive root. Any nested
payload carrying this paper's CFF, release manifest, or reader-facing README must use the same
current paper title, version, Version DOI, and creators as the outer current record.
Reader-facing integrity prose must also match the exact inventories: it may not claim that
`SHA256SUMS` covers every member when it omits itself, or that a manifest and checksum file cover
the same paths when they do not.
The quality-gate recorder repeats this check and projects every failure into
`unresolved_review_blockers`; neither score nor decision can override it.

Then explicitly invoke `$openlabs-paper-review`. Under the default two-reviewer contract, freeze one
judgment from a blank Codex reviewer, then run a new non-persistent Claude Code process through
Packy with model `claude-opus-5`. Claude receives the same frozen scientific inputs but no author
session, prior review, or reviewer-1 content. Take the lower of the two values for every integer
score, including `overall`, and the less favorable of the two simulated decisions. Deterministic
code may verify provider identities, sources, hashes, and aggregation but must not originate a
scientific judgment. If either genuinely independent configured provider is unavailable, leave the
quality gate pending.

The full paper registry contains the projected result of earlier panels and is therefore not safe
review input. The coordinator reads it, but every reviewer receives/reads only an in-memory view
with top-level `ara_llm_self_review`, `writing_release`, and `review_file` removed. Exposure to the
unredacted projection invalidates that reviewer context; replace it rather than asserting
`prior_reviews_hidden: true`.
The same rule applies to historical review/preflight files stored under a paper workspace or
manuscript directory. Reviewers inspect only the canonical PDF, its explicit transitive TeX/Bib
source set, the claim map, redacted-registry evidence, and the exact current support artifact;
recursive searches over the whole paper directory are forbidden. Accidental exposure invalidates
that context even if it came from a filename the coordinator did not intend as review input.

When a paper-local registry explicitly configures the supported one-reviewer contract, the same
isolation rules still apply: launch one fresh ephemeral Codex process, never resume the writer or
coordinator context, mark the reviewer and panel records with the required isolated-process
provenance, and form the validated one-member panel. A same-context self-review is not a weaker
kind of valid review; it is invalid for readiness. The direct `quality-gate` command cannot
substitute for `paper-writing review apply` with a validated panel record.

Formal-tool reconstruction is objective evidence preparation, not a score-bearing review. When a
Lean project is in scope, use one repository resource-capped Lean audit workflow for the frozen
snapshot before starting the panel. Bind the receipt to the manuscript snapshot, support-package
hash, toolchain, manifest, configuration, and Lean sources; give the same receipt to both
reviewers. They must not independently rebuild Lean or mathlib. The single audit is serialized and
must stay within the repository CPU, memory, process-count, disk-headroom, and timeout maxima. A
matching PASS receipt is reused; a resource-limit failure is investigated outside the panel rather
than duplicated across reviewer contexts. A diagnosed interruption may continue the same
incremental build with a hash-linked receipt; the formal validation command may execute at most
once over the complete receipt chain.

Choose Lean validation from the Lean-input delta. When every Lean source, toolchain, Lake
configuration, and dependency-lock hash is unchanged, bind the new manuscript snapshot and current
support-package hash to the earlier PASS receipt with `--reuse-pass-receipt`, or to an exact-input
successful full-build report with `--reuse-build-report`; do not execute Lean. A support archive,
DOI, filename, author-metadata, or manuscript change alone does not invalidate Lean evidence. For a
local Lean-source change with unchanged toolchain, lock file, configuration, and foundational
interfaces, use `--build-mode incremental` so Lake reuses valid earlier build products, then run the
axiom audit. Use `--build-mode full` only for a large Lean change such as a toolchain, dependency,
configuration, or broad foundational/interface change. Supply the resulting receipt to both
reviewers and disclose whether validation was reused, incremental, or full.

Route the registry domain exactly as follows:

- `ai`, `cs`, and `se`: ARA `cs_top_tier`, judged numerically as a top-tier computer-science
  conference submission such as NeurIPS, ICML, or ACL; record both `top_conference` and
  `cas_zone_1_journal` opinions;
- `math`: the shared four-leading-journal benchmark represented by *Annals of Mathematics*,
  *Inventiones Mathematicae*, *Journal of the American Mathematical Society*, and
  *Acta Mathematica*; use rubric ID `ara.paper-writing.math-four-journals.v1` and record
  `four_top_math_journals` plus `cas_zone_1_journal` opinions, with no conference opinion.
- `materials`: a leading selective materials-journal benchmark using rubric ID
  `openlabs.paper-writing.materials-leading-journals.v1`, with `leading_materials_journals` plus
  `cas_zone_1_journal` opinions;
- `physics`: a highest-tier physics benchmark calibrated to the same exceptional selectivity as
  the mathematics four-journal standard, using rubric ID
  `openlabs.paper-writing.physics-math-four-equivalent.v1`, with
  `leading_physics_journals` plus `cas_zone_1_journal` opinions;
- `quant`: a leading quantitative-finance/financial-econometrics journal benchmark using rubric ID
  `openlabs.paper-writing.quant-finance-leading-journals.v1`, with
  `leading_quant_finance_journals` plus `cas_zone_1_journal` opinions.

The CAS Zone 1 view uses the configured major-category scope and a lower selectivity bar than the
domain's high-standard view, while preserving correctness and evidence requirements. Unless a
particular journal's current classification has been verified, use a generic Zone 1 standard and
do not claim that the named target is actually Zone 1. These are internal reviewer recommendations,
not actual venue decisions.

Write the configured number of immutable individual JSON records and one immutable panel result
under the same `reviews/<review_run_id>/<paper_id>/` directory. Include at least:

- `scores.clarity`, `scores.soundness`, `scores.significance`, `scores.novelty`, and
  `scores.overall`, each an integer from 1 to 10; do not use decimals;
- strengths, weaknesses, required changes, unresolved blockers, and role-specific recommendations;
- the two views configured in `skills/profiles.yaml`, each with decision, confidence, and rationale;
- `review_metadata.score_kind: ara_llm_self_review` and
  `review_metadata.not_external_peer_review: true`, plus
  `review_metadata.simulated_venue_decisions: true`;
- the role-specific `review_metadata.rubric_id` required by the review schema;
- model, reasoning effort, UTC review time, paper ID, canonical main-TeX SHA-256, and whether the
  manuscript tree stayed unchanged during review.

Use the panel's conservative `scores.overall` as the gate score. Under the default contract it is
the lower of two independent holistic judgments; under the explicit one-reviewer contract it is
the unchanged isolated reviewer's value. It is not an arithmetic escape hatch: an unsupported
central claim, unresolved scientific/proof flaw, stale build, or unverified critical artifact must
also receive a decision below the configured review threshold or remain blocked.

Validate the completed panel with the helper shipped inside `$openlabs-paper-review`. It checks domain
routing, integer score fields, role-specific recommendation schemas, immutable reviewer hashes,
common manuscript snapshots, frozen-peer binding, and exact conservative aggregation; it never
judges the paper or alters a score.

## Apply the deterministic threshold

Read the actual venue type and completed revision count from the paper record, then apply the
validated review panel. `review apply` invokes the deterministic gate with the panel's CAS Zone 1
journal decision:

```bash
python -m paper_writing review apply \
  --paper-id <paper_id> --review reviews/<run>/<paper_id>/review.json \
  --venue-type <conference|journal> \
  --revision-rounds <completed_rounds>
```

The command requires both conditions:

- score greater than or equal to `quality_gate.minimum_score` (currently 5.0); and
- `cas_zone_1_journal` decision equal to `minor_revision` or `accept`.

A score below 5.0 therefore fails even when the decision label is high enough. The actual
`--venue-type` remains registry metadata and does not change which review view supplies the gate
decision. Treat the command's nonzero exit on a failed gate as the expected blocked/revision
outcome, not as a tooling error.
Do not round a review score before applying the gate. Historical decimal records remain readable,
but all new `$openlabs-paper-review` records use integers.

Any subsequent change to a claim, proof, number, citation, figure, table, abstract, conclusion, or
other score-bearing text invalidates the review. Run a new fresh-context review and record the gate
again. Formatting-only changes still require a build check and an explicit note that the reviewed
content hash did not change.

`writing_release.status=ready` is necessary before handoff or consideration for submission, but is
not sufficient authorization to submit. It is an internal LLM quality gate, not scientific proof,
external peer review, an editorial decision, or a substitute for accountable human approval.

## Keep publication outside the gate

The quality-gate command itself must never upload files, create external records, or publish a
Zenodo draft. If the paper cites a reserved support-material DOI, run `paper-writing zenodo prepare`
and `paper-writing zenodo verify-draft` before the final review, add the DOI with neutral wording
that remains true after publication, rebuild, and then score the resulting snapshot. Keep every
draft, reservation, release, and prior-version fact in registry/receipt history rather than the
formal manuscript. When a prepared
support package exists, the gate records its SHA-256 alongside the manuscript snapshot.

The passing gate is the authorization for support-material publication. Once the gate is `ready`,
run `paper-writing zenodo release` as a separate step without asking the user again; that command
independently revalidates the gate and the exact local/remote package hashes, and it refuses to
publish when the gate is stale, failing, or unbound from the package. Publishing support materials is
the only external action a passing gate authorizes: it never authorizes a submission, a journal
event, or any publication fact, all of which remain the accountable human's decision.
