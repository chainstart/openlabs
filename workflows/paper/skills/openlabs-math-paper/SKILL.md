---
name: openlabs-math-paper
description: Run OpenLabs' evidence-bound mathematics manuscript workflow from definitions and proof artifacts through exposition, optional symbolic checks, skeptical review, and the local quality gate. Invoke explicitly for mathematics papers in the OpenLabs data repository; never treat prose review or computation as proof, and never publish or submit as an implicit consequence of a gate.
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
- Load `workflows/paper/skills/vendor/peer-review/SKILL.md` for the dedicated review pass.

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
3. Replay authorized computational or formal artifacts with pinned versions when the claim depends
   on them; record commands, hashes, assumptions, and results without calling the replay a proof of
   anything outside its contract. Use one centralized Lean/mathlib audit workflow per frozen
   snapshot, outside the three score-bearing reviews, with the resource-capped objective checker
   defined by `$openlabs-paper-review`; share its immutable receipt with all three reviewers. A diagnosed
   guard interruption may resume the same hash-bound incremental build, but formal axiom validation
   executes at most once across the receipt chain. Never ask each reviewer to rebuild the same
   formal project.
4. Normalize every reader-facing supporting-material reference as described below, then run
   `python -m paper_writing support-check --paper-id <paper_id>` and verify citation metadata and
   proposition-level support.
5. Compile the real manuscript and run repository validation plus relevant local checks.
6. If public support materials are needed, prepare their local deterministic package and record
   missing metadata as a blocker. Creating even a reversible remote draft requires a separate,
   explicit administrator action with OpenLabs external writes enabled.
7. Hand the compiled, unchanged snapshot to exactly three genuinely fresh agents running in
   parallel and explicitly invoke `$openlabs-paper-review` in each isolated context. They must score
   against the shared standard of *Annals of Mathematics*,
   *Inventiones Mathematicae*, JAMS, and *Acta Mathematica*, assign integer scores, return separate
   simulated four-leading-journal and CAS Zone 1 journal decisions, omit conference decisions, and
   record proof risks and specialist limits. Use the validated median panel result. Do not
   silently edit during scoring.
8. Apply the mandatory local LLM quality gate exactly as specified in
   `workflows/paper/skills/overlays/quality-gate.md`. Any score-bearing edit makes the review stale.

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

A passing gate authorizes only an internal state transition to `ready`. It never authorizes a
Zenodo release, remote handoff, submission, journal event, spending decision, or publication fact.
Those actions require a new explicit administrator instruction and the deterministic external-write
guard.

## Finish

Report changed files, proof/evidence gaps, computations and builds actually run, the review record,
quality-gate result, and remaining mathematical risks. If the gate is not ready, state the next
bounded revision rather than presenting the paper as submission-ready.
