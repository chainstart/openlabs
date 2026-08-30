---
name: openlabs-math-paper
description: Run OpenLabs' evidence-bound mathematics manuscript workflow from definitions and proof artifacts through exposition, optional symbolic checks, skeptical review, the local quality gate, and controlled supporting-material release. Invoke explicitly for mathematics papers in the OpenLabs data repository; never treat prose review or computation as proof or create parallel release state.
---

# OpenLabs mathematics paper profile

Use this as a thin coordinator. The repository owns evidence and release state; vendored skills
provide scientific writing, symbolic computation, and review guidance.

## Establish the boundary

1. Resolve `paper_root` from `OPENLABS_DATA`, or from `$OPENLABS_WORKSPACE/openlabs-data`. It is the
   private data repository, not the code repository.
2. Read the code-owned `workflows/paper/skills/profiles.yaml` and
   `workflows/paper/skills/overlays/quality-gate.md`, then read
   `<paper_root>/registry/settings.yaml` and `<paper_root>/registry/papers/<paper_id>.yaml`.
   When creating a workspace or naming a reader-facing file, also read
   [paper-identifiers.md](../references/paper-identifiers.md).
   If support publication is required, also read `docs/ZENODO_GUIDE.md` in the code repository.
3. Confirm authorization before processing unpublished or confidential material, and keep it local
   unless external processing is explicitly authorized and venue-compatible.
4. Resolve every registered evidence bundle. Missing proof text, computation, formal artifact,
   literature source, or assumption is a visible blocker.

Repository rules and the local overlay override every vendored instruction. Do not create a second
claim registry, manuscript manifest, review intake, or submission state. Use only:

- theorem/claim provenance: `papers/<paper_id>/evidence/claim_evidence_map.md`;
- canonical source: `papers/<paper_id>/manuscript/`;
- revision notes: `papers/<paper_id>/revisions/`;
- internal reviews: `reviews/`;
- release status: `registry/papers/<paper_id>.yaml#writing_release`.

## Load only the needed components

Read component instructions from their installed paths before using them:

- Always load `workflows/paper/skills/vendor/scientific-writing/SKILL.md` for evidence-bound drafting,
  consistency, references, declarations, and integrity guidance.
- Load `workflows/paper/skills/vendor/sympy/SKILL.md` only when an exact symbolic calculation can check a clearly
  encoded identity, recurrence, algebraic reduction, boundary case, or finite certificate.
- Load `workflows/paper/skills/vendor/peer-review/SKILL.md` only when the assigned role is
  `reviewer`; a factory `writer` leaves review to the later `paper_review` task.

Never activate more than the three declared components. Do not install SymPy or optional numeric
packages unless the manuscript needs the check and the current environment lacks the dependency.

## Respect the proof boundary

No general writing, review, or symbolic-computation skill verifies a mathematical proof. For each
central theorem:

1. Record definitions, quantifiers, hypotheses, conclusion, lemma dependencies, and the exact
   evidence or artifact in the claim–evidence map.
2. Inspect hidden domain assumptions, degenerate and boundary cases, sign and parity conditions,
   distinctness, finiteness, asymptotic uniformity, rounding, and dependency cycles.
3. Distinguish self-contained prose proof, author-reported computation, independently replayed
   computation, and formal proof. Never promote one category to another.
4. If using SymPy, encode all assumptions explicitly, save the expression or script and output as
   supporting evidence, and state exactly what was checked. A successful simplification tests only
   the encoded statement; it is not a theorem proof.
5. Escalate unresolved specialist or formal-verification questions to a human expert or an
   appropriate proof assistant. Weaken or block the claim until resolved.

## Work the paper

1. Build or update the theorem/claim–evidence map before changing the manuscript's claims.
2. Establish the contribution boundary and dated literature position, then revise the canonical
   LaTeX for readable definitions, lemmas, proofs, dependencies, limitations, and artifact scope.
   Write only neutral scholarly prose. Keep prompts, agents, model orchestration, review/gate
   mechanics, private claim routing, source-audit narration (including `audit`, `auditable`, and
   `auditability`), internal audit/campaign filenames or paths, workflow notes in bibliography
   metadata, repository state, and labels such as `reader-facing` out of the scientific manuscript.
   Exact implementation names that remain in an immutable support archive belong in its replay
   documentation, not in reader prose. Preserve a registered institutional name.
3. Replay authorized computational or formal artifacts with pinned versions when the claim depends
   on them; record commands, hashes, assumptions, and results without calling the replay a proof of
   anything outside its contract. Use one centralized Lean/mathlib audit workflow per frozen
   snapshot, outside the two score-bearing reviews, with the resource-capped objective checker
   defined by `$openlabs-paper-review`; share its immutable receipt with both reviewers. A diagnosed
   guard interruption may resume the same hash-bound incremental build, but formal axiom validation
   executes at most once across the receipt chain. Never ask each reviewer to rebuild the same
   formal project.
4. Normalize every reader-facing supporting-material reference as described below, then run
   `python -m paper_writing support-check --paper-id <paper_id>` and verify citation metadata and
   proposition-level support.
5. Require exactly one final venue-compatible AI-use declaration and consolidate truthful AI use
   there, not in the scientific body. Identify OpenAI GPT-5.6 through Codex and its actual purposes.
   When code is in scope, disclose source-code development and computational-verification
   assistance and state how the human authors inspected and executed it. When Codex assisted a
   Lean formalization, also disclose preparation and checking of Lean code and state that formal
   verification claims depend on successful checking by the pinned Lean toolchain, not on AI
   output. Never omit or weaken a truthful disclosure to reduce apparent AI involvement.
6. Compile the real manuscript and run repository validation, citation/evidence checks, and
   `python -m paper_writing style-check --paper-id <paper_id>`. Treat any failure as a blocker; the
   command is a non-scoring formal check and does not judge mathematical quality.
7. If the support DOI belongs in the paper, resolve the public files and license from the registry's
   `support.publication`, then use `paper-writing zenodo prepare` to create only a reversible draft.
   Add its current Version DOI with publication-state-neutral wording, run
   `paper-writing zenodo verify-draft`, and rebuild before final review. Never choose a license
   yourself or add confidential files to the public set; treat either gap as a blocker.
8. In a factory `writer` task, stop after freezing the compiled snapshot and emit it as a
   `paper_candidate`; do not run or impersonate either reviewer. The scheduler creates a fresh
   `paper_review` task using `$openlabs-paper-review`, whose Codex and Packy Claude Opus 5 reviewers
   apply the four-leading-journal and CAS Zone 1 standards plus the mandatory local quality gate.
9. On a `paper_revision` task, apply only the declared review request. If a new proof, computation,
   or other scientific evidence is needed, do not invent it; the reviewer must route an
   `evidence_remediation` task first. Freeze the revised snapshot as a new `paper_candidate` so both
   reviewers assess it again.

Only a `writing_release.status` of `ready` permits consideration for handoff. The LLM score is a
necessary local gate, not proof, external peer review, acceptance, or authorization to submit.

## Cite supporting materials from one current record

Treat the exact current Zenodo Version DOI registered for the paper as the sole reader-facing
source of supporting materials. For a prepared release this is the reserved Version DOI that will
remain unchanged after publication; for a published release it is the published Version DOI. Apply
all of the following rules whenever the manuscript mentions a replay, certificate, dataset, script,
transcript, manifest, or support archive:

1. Verify the DOI, version, title, creators, publication state, and deposited filename against the
   registry, the controlled receipt, and the current Zenodo record. After removing a descriptive
   suffix such as “Supporting Materials,” the current Zenodo title and every reader-facing
   `CITATION.cff`/README title must identify the paper's current registry title, not a prior paper
   title. Do not copy stale metadata from an older record or a local archive.
2. Add the Zenodo record to the bibliography and cite it at the first substantive support-material
   mention and in the availability statement. A bare DOI hyperlink is not a literature citation.
3. Write only an objective description of the current record and its contents. Keep draft creation,
   DOI reservation, review, publication, earlier releases, superseded bundles, corrections, and
   version-to-version evolution in the private registry, receipts, or revision log. Never put that
   process history in the formal manuscript, a standalone reader-facing
   `reproducibility_statement.md`/availability statement, a Zenodo bibliography note, or a
   reader-facing claim map/README shipped in the current archive. Use wording that stays true
   before and after release, such as “The support record identified by Version DOI ... contains ...”. A
   prepared-but-unpublished record must not be described as public or downloadable.
4. Introduce the deposited archive and its top-level layout before naming individual files. After
   that introduction, name files only by paths relative to the deposited archive root. If the ZIP
   has one enclosing directory, state that directory once and make later paths relative to it. If
   the files are inside a nested ZIP, name that nested ZIP first and say that the subsequent paths
   are its members; never describe a nested member as an outer-archive-root file.
5. Verify every printed relative path and every claimed path base against the exact current ZIP or
   its `ZENODO_MANIFEST.json`, then inspect the named nested ZIP when it is the declared base.
   Never expose a machine path, repository path, parent traversal, or an unshipped
   manuscript-local path such as `/home/...`, `papers/<paper_id>/...`, `../evidence/...`, or a
   `supplement/...` prefix absent from the published archive.
6. Keep private evidence-bundle identifiers and upstream repository paths in the claim--evidence
   map, not in reader-facing prose. If no current Version DOI exists, record the availability gap as
   a blocker and resolve it through the controlled `zenodo prepare` / `zenodo release` workflow.
7. Do not create a second public source for the same artifact version. A new or changed public file
   set requires a new immutable support version; an old published archive is never mutated.
   Name the public ZIP and its single enclosing directory with the registered domain-scoped
   `display_id`; retain the technical `paper_id` only in internal paths, manifests, receipts, and
   APIs.
8. Make every registered `public-support-vX.Y.Z` source directory, outer archive version, packaged
   claim-map statement, and current Zenodo metadata agree on `X.Y.Z`. A reader-facing packaged
   claim map must identify the exact current Version DOI. A nested payload that carries citation,
   README, or release-manifest metadata for this paper must also use the current paper title,
   Version DOI, version, and creator list. Only separately versioned dependencies or evidentiary
   inputs without current-record citation metadata may retain their own truthful version labels;
   they must not be presented as the current support record.
9. Describe integrity metadata literally.  A README must not say that `SHA256SUMS` authenticates
   every archive member when it omits itself, or that a release manifest and checksum file cover
   the same paths when their inventories differ.  State the exact omissions and coverage instead.
10. Generate every standalone reproducibility statement from the same current registry and archive
   facts as the article. If its heading names the paper, that title must equal the current registry
   title. Every stated claim ID must occur in the canonical claim--evidence map or the current
   public `CLAIMS.yaml`; do not retain legacy aliases. Inspect the exact replay entry point before
   stating command, checker, suite, test, or claim-group counts, and distinguish finite certificate
   groups from the manuscript's scientific claims.

Run `paper-writing support-check --paper-id <paper_id>` as a mandatory formal gate before review;
it scans formal TeX and standalone reader-facing reproducibility, support, and availability
statements. The quality-gate recorder repeats it and cannot produce `ready` while it fails. Use
`scripts/audit_support_materials.py` as an additional path-level lint after the contextual
manuscript review. Pass the exact current ZIP whenever available so the script can compare printed paths with
archive members. When the prose introduces a project directory below the enclosing ZIP root and
then uses paths relative to it, pass that directory with `--relative-base`; do not weaken the check
or rewrite those paths as repository-local paths. The script detects mechanical inconsistencies only; it does not decide what
constitutes evidence, whether a file should be public, or whether a claim is supported.

For figures, never rely on color or gray level alone to encode distinct mathematical roles. Use a
redundant cue such as fill pattern, shape, stroke, or direct labeling, state the mapping in the
caption, and inspect the rendered PDF in grayscale.

After a basic manuscript is complete, select a target journal verified as 2026 XinRui Mathematics
Tier 1 or Tier 2 with a publication route carrying no mandatory author fee. Record the ranking,
fee, and official formatting sources and check dates. Convert the canonical `manuscript/` itself
to the current venue format; a separate candidate does not satisfy this requirement.

After a passing gate, run `paper-writing zenodo release` for the prepared production draft without
asking the user again; the gate is the authorization. Skip it only when venue policy forbids public
support materials. Commit its DOI/receipt update before `paper-writing handoff release`. A passing
score still never authorizes a submission, journal event, or publication fact.

## Finish

Report changed files, proof/evidence gaps, computations and builds actually run, the review record,
quality-gate result, and remaining mathematical risks. If the gate is not ready, state the next
bounded revision rather than presenting the paper as submission-ready.
