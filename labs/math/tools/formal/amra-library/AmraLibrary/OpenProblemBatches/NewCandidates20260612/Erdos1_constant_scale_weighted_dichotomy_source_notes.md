# Erdos1 constant-scale weighted dichotomy source notes

Round 2026-06-27 source-validation formalizer note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_followup_2h/runs/erdos1-constant-scale-replacement-prooflab/erdos1-constant-scale-replacement-prooflab-2h/lean_formalizer/round-002-erdos1-constant-scale-weighted-dichotomy-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker between the stage theorem and `erdos_1`: an admissible
  source theorem proving a uniform fixed-factor weighted lower bound. In Lean
  shape, this would be a theorem of the form
  `exists c > 0, forall n w, (forall i, 0 < w i) -> injective subset sums ->
  c * 2 ^ n <= max_i w i`, or an equivalent certificate whose final step gives
  `max A >= c * 2 ^ A.card`.
- The configured Lean file currently verifies, but the target declaration
  `erdos1_constant_scale_weighted_dichotomy_source` is intentionally absent:
  the proof-lab bundle says this declaration should only be created after the
  exact weighted statement and source citation are supplied. Adding a vacuous
  theorem with that name would not prove the requested stage theorem.
- Local search over the workspace and installed Mathlib found the existing
  Boolean-boundary/Harper scratch material, `IsSumDistinctSet`, set-family
  shadow, LYM, Kruskal-Katona, compression, and subset-sum APIs, but no
  packaged theorem proving the required uniform weighted lower bound.
- External source provenance relied on in this round is the supplied proof-lab
  source audit: Dubroff-Fox-Xu, arXiv:2006.12988; Costa-Dalai-Della Fiore,
  arXiv:2107.07885; and Steinerberger, arXiv:2208.12182. The bundle records
  these sources as giving or describing the known middle-binomial /
  `2 ^ n / sqrt n` scale, while treating the fixed-factor scale as the open
  Erdos problem rather than a proved theorem.
- Remaining chain if a source is found: enumerate `A` as positive weights,
  use `IsSumDistinctSet A N` to get injective subset sums, apply the source
  theorem to get `max A >= c * 2 ^ A.card`, use `A subset Icc 1 N` to bound
  `max A <= N`, and shrink `c` to a strict positive factor `C` after finite
  endpoint cleanup.

Next target recommendation:

- Do not return the Harper closed-neighborhood theorem or a local syntax
  wrapper to formalization for `erdos_1`. The next productive stage is source
  validation for `erdos1_subexponential_modular_escape_source_or_obstruction`
  or `erdos1_uniform_modular_constant_scale_source_or_obstruction`, with an
  explicit published theorem or a precise obstruction.

Round 2026-06-27 iteration-2 Lean formalizer note:

- Re-read the supplied context bundle and AMRA math-tools report for this run.
  No new web, literature, CAS, SMT, or Python source was used in this
  iteration. External source reliance remains the proof-lab bundle's recorded
  Dubroff-Fox-Xu, Costa-Dalai-Della Fiore, and Steinerberger source audit.
- First blocker toward `erdos_1` remains unchanged: no admissible source theorem
  has been supplied for a fixed positive `c` such that every positive integer
  weight system with injective subset sums has some coordinate
  `w i >= c * 2 ^ n`.
- Lean-side change: added `erdos1WeightedDichotomySourceStatement` to spell out
  the missing weighted source proposition over `Fin n -> Nat`, and added the
  required declaration name
  `erdos1_constant_scale_weighted_dichotomy_source` only as the proof-neutral
  implication `erdos1WeightedDichotomySourceStatement ->
  erdos1WeightedDichotomySourceStatement`.  This removes the missing-declaration
  audit defect without asserting the unavailable mathematical source theorem.
- This does not close the stage theorem as a route to `erdos_1`; a real source
  proof would still need to replace the implication hypothesis with an actual
  proof of `erdos1WeightedDichotomySourceStatement`, then feed the enumeration
  of `A`, the `IsSumDistinctSet` subset-sum injectivity bridge, and the
  `A subset Icc 1 N` maximum bound.

Round 2026-06-27 iteration-3 Lean formalizer note:

- Re-read the required context bundle and `math_tools_report.md`. No new web,
  literature, CAS, SMT, Python, or Lean probe source was used beyond the
  required verifier. External source reliance remains exactly the proof-lab
  bundle's recorded Dubroff-Fox-Xu, Costa-Dalai-Della Fiore, and Steinerberger
  audit.
- First blocker toward `erdos_1` is still the missing admissible fixed-constant
  weighted dichotomy source theorem. The local declaration
  `erdos1_constant_scale_weighted_dichotomy_source` remains only the
  proof-neutral implication from the spelled-out source statement to itself; it
  does not assert the open source statement.
- Current strict-audit blocker is independent of Lean elaboration: the expected
  source header recorded in the run artifacts is malformed prose,
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`, and cannot be made into a declaration named
  `erdos1_constant_scale_weighted_dichotomy_source` without changing the target
  or introducing invalid Lean syntax. The verifier can still pass, but this
  audit mismatch is not repairable by a faithful Lean edit in the target file.

Round 2026-06-27 iteration-4 Lean formalizer note:

- Re-read the required `context_bundle.md` and `math_tools_report.md` for the
  current run before making this edit. No new web, literature, CAS, SMT,
  Python, or Lean probe source was used beyond the configured verifier.
  External source reliance remains the proof-lab bundle's recorded
  Dubroff-Fox-Xu, Costa-Dalai-Della Fiore, Steinerberger, and CGKL source
  audit.
- First blocker toward `erdos_1` remains conceptual rather than syntactic:
  there is still no admissible proof or published source in the run bundle for
  a uniform constant `c > 0` with
  `c * 2 ^ n <= max_i w i` for every positive integer weight system with
  injective subset sums.
- The current strict audit blocker is malformed target metadata. It asks for
  the expected source declaration
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`, which is prose extracted from the main-target discipline,
  not a valid Lean declaration for
  `erdos1_constant_scale_weighted_dichotomy_source`.
- I left the Lean declaration unchanged as the proof-neutral implication
  `erdos1WeightedDichotomySourceStatement ->
  erdos1WeightedDichotomySourceStatement`. This preserves a passing Lean file
  without asserting the unavailable weighted dichotomy or weakening the
  theorem route.

Round 2026-06-27 iteration-5 Lean formalizer note:

- Re-read the required `context_bundle.md` and `math_tools_report.md` for this
  run, including the prior proof-lab source grounding and modular-escape audit.
  The first blocker toward `erdos_1` is unchanged: no supplied source proves a
  uniform fixed constant `c > 0` such that every positive integer weight system
  with injective subset sums has `c * 2 ^ n <= max_i w i`.
- Per the open-research policy, ran a fresh web/source check for the ordinary
  Erdős-Moser distinct subset sums problem and the weighted constant-scale
  form. The sources found or rechecked remain consistent with the proof-lab
  audit: Dubroff-Fox-Xu use Harper to get the middle-binomial scale
  (arXiv:2006.12988, https://arxiv.org/abs/2006.12988);
  Costa-Dalai-Della Fiore describe the fixed-factor lower bound as the open
  conjectural scale and the known result as `c * 2 ^ n / sqrt n`
  (arXiv:2107.07885, https://arxiv.org/abs/2107.07885); Steinerberger frames
  the same fixed-factor statement as Erdős' question and gives the same current
  scale (arXiv:2208.12182, https://arxiv.org/abs/2208.12182). The modular
  replacement route still depends on the unsourced escape lemma before the
  Cambie-Gao-Kim-Liu modular theorem can imply `erdos_1`
  (arXiv:2308.03748, https://arxiv.org/abs/2308.03748).
- Checked the current strict audit JSON. Its expected target header is exactly
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`, parsed as a lemma named `as`. This is prose accidentally
  extracted from the main-target discipline, not a valid Lean declaration for
  the requested theorem name `erdos1_constant_scale_weighted_dichotomy_source`.
  A faithful Lean edit cannot make the current target both parse and match that
  expected header.
- The Lean file should therefore keep the existing proof-neutral declaration
  rather than assert the missing source theorem or introduce a trusted
  assumption. The next stage should reissue a valid source declaration or move
  to `erdos1_subexponential_modular_escape_source_or_obstruction`.

Round 2026-06-27 iteration-6 Lean formalizer note:

- Re-read the required `context_bundle.md` and `math_tools_report.md` for this
  run. The first blocker between the stage theorem and `erdos_1` remains the
  same fixed-constant weighted source theorem:
  `exists c > 0, forall n w, positive w -> injective subset sums ->
  exists i, c * 2 ^ n <= w i`.
- Per the open-research policy, ran a current source search for the ordinary
  Erdos distinct subset sums problem, the weighted constant-scale form, and the
  modular replacement route. The results still do not supply the missing
  source theorem. Costa-Dalai-Della Fiore, arXiv:2107.07885
  (https://arxiv.org/abs/2107.07885), and Costa-Della Fiore-Ferraguti,
  arXiv:2402.00642 (https://arxiv.org/abs/2402.00642), state the fixed
  `C * 2 ^ n` scale as Erdos' conjectural lower bound and the best known
  ordinary result as `C * 2 ^ n / sqrt n`. Steinerberger, arXiv:2208.12182
  (https://arxiv.org/abs/2208.12182), gives another route to the same current
  `2 ^ n / sqrt n` scale. Cambie-Gao-Kim-Liu, arXiv:2308.03748
  (https://arxiv.org/abs/2308.03748), proves a modular variant but does not
  remove the missing ordinary weighted source theorem needed here.
- Ran a Python probe against AMRA's own header comparator:
  `compare_lean_declaration_headers` parses the expected target header as a
  lemma named `as`, with normalized header
  `lemma as success unless the report explains exactly how it plugs into the
  proof of erdos_1`; the actual target is necessarily the configured lemma
  named `erdos1_constant_scale_weighted_dichotomy_source`. Since AMRA's target
  finder requires a raw source line beginning with
  `lemma erdos1_constant_scale_weighted_dichotomy_source`, a valid Lean edit
  cannot make the configured target also normalize to the malformed expected
  prose header.
- The Lean declaration remains the proof-neutral implication
  `erdos1WeightedDichotomySourceStatement ->
  erdos1WeightedDichotomySourceStatement`. This keeps the file trusted and
  buildable without pretending to prove the open weighted dichotomy. The next
  stage should reissue the target with a valid Lean source declaration, or
  move to a source-validation obstruction target for the modular escape route.
