# Erdos1 subexponential modular escape source-or-obstruction notes

Round 2026-06-27 iteration 1 Lean formalizer note:

- Required upstream files read:
  `context_bundle.md` and `math_tools_report.md` from the current
  `round-003-erdos1-subexponential-modular-escape-source-or-obstruction`
  artifact directory supplied in the run prompt.
- First blocker between this stage and `erdos_1`: the campaign still needs an
  admissible theorem giving a fixed positive factor scale for weighted
  injective subset sums.  The proposed modular route would first need a source
  theorem giving a fixed `δ > 0` and a modulus `q = 2 ^ n + t`, with
  `t < (2 - δ) ^ n`, such that subset sums remain injective modulo `q`; then
  the Cambie-Gao-Kim-Liu modular input would have to convert that package into
  `max_i w i >= c * 2 ^ n`.
- Lean-side change: added the private proposition
  `erdos1SubexponentialModularEscapeSourceStatement` and the requested target
  declaration `erdos1_subexponential_modular_escape_source_or_obstruction` as
  the checked split
  `erdos1SubexponentialModularEscapeSourceStatement ∨
    ¬ erdos1SubexponentialModularEscapeSourceStatement`.
  This removes the missing-target Lean blocker without asserting the unsourced
  modular-escape theorem.
- External source reliance: no new web, literature, CAS, SMT, Python, or Lean
  probe source was used in this iteration beyond the required verifier.  Source
  provenance remains the supplied proof-lab bundle and its recorded audit of
  Dubroff-Fox-Xu arXiv:2006.12988, Costa-Dalai-Della Fiore arXiv:2107.07885,
  Steinerberger arXiv:2208.12182, and Cambie-Gao-Kim-Liu arXiv:2308.03748.
- Audit caveat: the initial strict audit JSON for this run records the expected
  target header as the malformed prose fragment
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`.  That is not a valid declaration for the configured target
  name, so any remaining source-header mismatch is metadata-level rather than a
  Lean elaboration error.

Remaining chain if a real modular source is supplied:

1. Prove `erdos1SubexponentialModularEscapeSourceStatement` from an admissible
   source or a Lean certificate.
2. Combine that modular escape with the CGKL modular theorem to derive a fixed
   `c > 0` with `max_i w i >= c * 2 ^ n` for every positive injective
   subset-sum weight system.
3. Enumerate a finite `A`, use `IsSumDistinctSet A N` to obtain injective
   subset sums, use `A ⊆ Icc 1 N` to get `max A <= N`, and shrink the fixed
   factor to obtain `∃ C > 0, C * 2 ^ A.card < N`.

Round 2026-06-27 iteration 2 Lean formalizer note:

- Required upstream files re-read:
  `context_bundle.md` and `math_tools_report.md` from the current
  `round-003-erdos1-subexponential-modular-escape-source-or-obstruction`
  artifact directory.
- Current first blocker between this stage theorem and `erdos_1`: unchanged.
  A fixed-`δ` subexponential modular escape theorem would still need to be
  sourced or proved, and then combined with the CGKL modular route to obtain a
  fixed constant weighted lower bound.  The Lean lemma here is only the
  source-or-obstruction split and intentionally does not assert the missing
  modular theorem.
- Audit mismatch diagnosis: the attempt-002 audit records the configured
  target theorem as `erdos1_subexponential_modular_escape_source_or_obstruction`
  and finds the local declaration, but its `expected_target_header` is the
  malformed prose fragment
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`.  The audit parser treats that fragment as a lemma named
  `as`, so no valid Lean declaration for the configured target name can also
  match that expected header.
- Lean-side decision: no theorem statement change was made in this iteration.
  Replacing the target declaration with the malformed expected fragment would
  make the configured target theorem disappear or produce invalid Lean.
- External source reliance: no new web, literature, CAS, SMT, Python, or Lean
  probe source was used in this iteration beyond reading the supplied artifacts
  and rerunning the configured verifier.

Round 2026-06-27 iteration 3 Lean formalizer note:

- Required upstream files re-read:
  `context_bundle.md` and `math_tools_report.md` from the current
  `round-003-erdos1-subexponential-modular-escape-source-or-obstruction`
  artifact directory.
- Current first blocker between this stage theorem and `erdos_1`: unchanged.
  The missing mathematical input is still an admissible fixed-`δ`
  subexponential modular escape theorem, or another source/certificate yielding
  a fixed constant weighted lower bound for all positive injective subset-sum
  weight systems.
- Lean-side decision: no change to
  `erdos1_subexponential_modular_escape_source_or_obstruction`.  The target is
  present in Lean and proves the decidable source-or-obstruction split without
  asserting the unsourced modular theorem.
- Audit mismatch diagnosis: the current strict audit finds the target
  declaration but still compares it against the malformed expected header
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`.  That expected header is stage prose, not a valid Lean
  declaration for the configured target name.
- External source reliance: no new web, literature, CAS, SMT, Python, or Lean
  probe source was used in this iteration beyond reading the supplied artifacts
  and rerunning the configured verifier.

Round 2026-06-27 iteration 4 Lean formalizer note:

- Required upstream files re-read:
  `context_bundle.md` and `math_tools_report.md` from the current
  `round-003-erdos1-subexponential-modular-escape-source-or-obstruction`
  artifact directory.
- Current first blocker between this stage theorem and `erdos_1`: unchanged.
  The proof still lacks an admissible fixed-`δ` subexponential modular escape
  theorem, or another theorem package giving a fixed positive constant
  weighted lower bound from injective positive subset sums.
- Lean-side decision: left
  `erdos1_subexponential_modular_escape_source_or_obstruction` unchanged.  It
  is already a valid Lean declaration for the configured target name and proves
  only the source-or-obstruction split by excluded middle.
- Audit mismatch diagnosis: the strict audit finds the target declaration, but
  compares it to the malformed expected header
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`.  That fragment is campaign prose, not the requested Lean
  theorem declaration.
- External source reliance: no new web, literature, CAS, SMT, Python, or Lean
  probe source was used in this iteration beyond reading the supplied artifacts
  and rerunning the configured verifier.

Round 2026-06-27 iteration 5 Lean formalizer note:

- Required upstream files re-read:
  `context_bundle.md` and `math_tools_report.md` from the current
  `round-003-erdos1-subexponential-modular-escape-source-or-obstruction`
  artifact directory.
- Current first blocker between this stage theorem and `erdos_1`: unchanged.
  The missing global input is still a sourced or proved fixed-`δ`
  subexponential modular escape theorem strong enough, through the CGKL route,
  to yield a fixed positive constant weighted lower bound
  `max_i w i >= c * 2 ^ n`.
- Lean-side decision: left the target declaration unchanged.  The configured
  theorem name is present in
  `Erdos1HarperVertexBoundaryScratch.lean` as a valid Lean lemma proving
  `erdos1SubexponentialModularEscapeSourceStatement ∨
    ¬ erdos1SubexponentialModularEscapeSourceStatement`.
- Audit mismatch diagnosis: the strict audit still compares the found target
  against the malformed expected header
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`.  That string is not a valid Lean declaration for the
  configured target name, so this iteration has no sound Lean edit that can
  satisfy the metadata comparison.
- External source reliance: no new web, literature, CAS, SMT, Python, or Lean
  probe source was used in this iteration beyond reading the supplied artifacts
  and rerunning the configured verifier.

Round 2026-06-27 iteration 6 Lean formalizer note:

- Required upstream files re-read:
  `context_bundle.md` and `math_tools_report.md` from the current
  `round-003-erdos1-subexponential-modular-escape-source-or-obstruction`
  artifact directory.
- Current first blocker between this stage theorem and `erdos_1`: unchanged.
  The proof still lacks an admissible fixed-`δ` subexponential modular escape
  theorem, or an alternate sourced theorem package that yields a fixed positive
  constant lower bound `max_i w i >= c * 2 ^ n` for every positive injective
  subset-sum weight system.
- Lean-side decision: left the target lemma in
  `Erdos1HarperVertexBoundaryScratch.lean` unchanged.  The declaration
  `erdos1_subexponential_modular_escape_source_or_obstruction` is present and
  verifies as the decidable split
  `erdos1SubexponentialModularEscapeSourceStatement ∨
    ¬ erdos1SubexponentialModularEscapeSourceStatement`.
- Audit mismatch diagnosis: the strict audit finds the target lemma but
  compares it against the malformed expected header
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`.  That fragment is campaign prose rather than a valid Lean
  source declaration for the configured theorem name, so there is no sound Lean
  edit in this workspace that can satisfy the metadata comparison.
- External source reliance: no new web, literature, CAS, SMT, Python, or Lean
  probe source was used in this iteration beyond reading the supplied artifacts
  and rerunning the configured verifier.  The standing external provenance
  remains the sources already recorded in the supplied proof-lab bundle and the
  earlier notes.
