# WOWII198a component attachment formalizer notes

Round 001 target:
`exists_two_separated_component_attachments_to_longest_path_support`.

External sources relied on:
- None from web or literature in this iteration.
- Local run context read from the provided `context_bundle.md` and
  `math_tools_report.md`.

Tool checks:
- Python/NetworkX graph-atlas sanity check for all 2-connected nontraceable
  atlas graphs with at most 7 vertices found no counterexample to the requested
  component certificate.
- A stronger nil-walk shortcut, where the missed vertex itself has two separated
  neighbors on the longest path, also held on that atlas sample and on a small
  random sample of 2-connected nontraceable graphs with 8 to 10 vertices. This
  was treated only as route evidence, not as a Lean proof route.

Current formal blocker:
- The requested theorem declaration has been inserted, but the proof is still
  blocked at the component certificate construction: extracting a simple outside
  path through the missed vertex from the two first-entry paths.

## Iteration 2

External sources relied on:
- None from web or literature.
- Local run context reread from the provided `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Added a checked first-entry helper carrying the invariant that every vertex
  up to the entry predecessor lies outside the longest-path support.
- Reworked the component-certificate target to extract the two endpoint-avoiding
  first-entry witnesses, convert their hit vertices to path indices, prove those
  indices are internal, and build the raw outside walk through `v` from the two
  outside prefixes.

Remaining formal blocker:
- The raw concatenated outside walk still needs the no-repeat/component argument
  that turns it into a simple outside path while preserving `v`, plus the
  longest-path splice argument proving the two attachment indices are separated.

## 2026-06-24 finite endpoint-pair Menger target

External sources relied on:
- None from web or literature in this iteration.
- Local run context read from the provided `context_bundle.md` and
  `math_tools_report.md`.

Tool check:
- Ran a Python/NetworkX exhaustive sanity check for the exact statement of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator` on all
  labelled simple graphs with 2 through 5 vertices and all endpoint pairs.
  Among 6,377 endpoint pairs satisfying the empty/singleton endpoint-excluding
  separator hypothesis, no counterexample to the two internally disjoint path
  conclusion was found. A naive extension through 6 vertices was interrupted as
  too slow and is not used as evidence.
- Iteration 3 reran the check with a plain Python enumerator through 6 vertices:
  502,170 endpoint instances were considered, and no counterexample was found.
  The requested run artifact directory was read-only in this sandbox, so this
  workspace note is the durable record of the tool check.

Current formal blocker:
- The Lean file still lacks a proof of the finite endpoint-pair `k = 2`
  vertex Menger theorem. Mathlib search in the local checkout did not reveal an
  existing SimpleGraph Menger/Fan theorem that can close the nondegenerate
  branch directly.

## Iteration 4

External sources relied on:
- None from web or literature in this iteration.
- Local run context reread from the provided `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Added a checked support lemma extracting two distinct internal vertices from
  the non-endpoint-only, non-one-internal branch of a simple `u-w` path.
- Rewired the target theorem's nondegenerate branch to obtain singleton-avoiding
  replacement paths for each of those two internal vertices from `hsep`.

Remaining formal blocker:
- The target theorem still needs the finite endpoint-pair `k = 2` Menger
  rerouting/min-cut step: from the two singleton-avoiding witnesses and the
  original path, construct two `u-w` paths whose supports meet only at endpoints.

## Iteration 5

External sources relied on:
- None from web or literature in this iteration.
- Local run context reread from the provided `context_bundle.md` and
  `math_tools_report.md`.

Tool check:
- Ran a small Lean `native_decide` probe in `/tmp` to test whether a
  parameterized finite Boolean tautology could be discharged computationally.
  The probe process exited with code 139 in this environment, so this route was
  not used. This is route evidence only and not part of the Lean proof.

Lean work:
- Added a checked helper extracting the singleton-avoidance consequence of the
  endpoint-excluding separator hypothesis.
- Rewired the target theorem's one-internal branch and nondegenerate branch to
  use that helper. The remaining nondegenerate branch is now isolated after the
  two singleton-avoiding `u-w` paths have been obtained.

Remaining formal blocker:
- The target theorem still lacks the finite endpoint-pair `k = 2` Menger
  augmentation: from an original path with two distinct internal vertices and
  paths avoiding each of those vertices individually, construct two `u-w` paths
  whose supports intersect only at `u` and `w`.

## Iteration 6

External sources relied on:
- None from new web or literature search in this iteration.
- Local run context reread from the provided `context_bundle.md` and
  `math_tools_report.md`. The only external mathematical source context remains
  the prior proof-lab grounding in Diestel, *Graph Theory*, Section 3.3
  "Menger's theorem", recorded as source evidence and not as an admissible Lean
  theorem.

Lean blocker selected:
- First error: `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`
  nondegenerate branch, where the proof has obtained a simple `u-w` path `p`
  with at least two distinct internal vertices `x,y`, plus singleton-avoiding
  simple `u-w` paths `qx` avoiding `x` and `qy` avoiding `y`.
- Remaining missing step: formalize the actual finite endpoint-pair `k = 2`
  vertex-Menger rerouting/min-cut argument turning these data into two simple
  `u-w` paths whose supports meet only at `u,w`.

No trusted source-admission declaration, theorem weakening, or forbidden proof
token was introduced.

## Iteration 7

External sources relied on:
- None from new web or literature search in this iteration.
- Local run context reread from the provided `context_bundle.md` and
  `math_tools_report.md`. The only external mathematical source context remains
  the prior proof-lab grounding in Diestel, *Graph Theory*, Section 3.3
  "Menger's theorem", recorded as source evidence and not as an admissible Lean
  theorem.

Lean work:
- Added a checked helper extracting the two singleton-avoiding `u-w` paths
  needed in the nondegenerate endpoint-pair branch.
- Rewired the target theorem to use that helper, leaving the branch context
  focused on the original path `p` and the two singleton-avoiding simple paths
  `qx` and `qy`.

Remaining formal blocker:
- The target theorem still requires the finite endpoint-pair `k = 2`
  vertex-Menger rerouting/min-cut step: from `p`, `qx`, and `qy`, construct two
  simple `u-w` walks whose supports meet only at `u` and `w`.

## 2026-06-28 later-return bypass target

External sources relied on:
- None from web or literature in this iteration.
- Local run context read from the provided `context_bundle.md` and
  `math_tools_report.md`.

Tool check:
- Ran a Python sequence model of mathlib's front-recursive `Walk.bypass` on all
  simple left-prefix/right-suffix sequences over at most five vertices with
  lengths up to four. The check found no counterexample to the corrected
  later-return shape: if a non-left vertex `y` of the right suffix is absent
  after loop-erasure, then some later right-suffix vertex returns to the left
  prefix. This is route evidence only; the Lean proof still must formalize the
  ordered upgrade from the existing unordered cross-repeat helper.

Current blocker chain:
- Immediate stage target:
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_later_left_return`.
- Parent target:
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`,
  closing the `hy_suffix` branch of the left-prefix residual.
- Remaining chain to `conjecture198a`:
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` →
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` →
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` →
  splice descent and two-fan theorem →
  Chvatal-Erdos traceability →
  `conjecture198a`.

## 2026-06-28 later-return bypass target, iteration 2

External sources relied on:
- None from new web or literature search in this iteration.
- Local run context and `math_tools_report.md` were reread from the supplied
  run artifact directory.

Lean work:
- Added checked helper `support_bypass_sublist`, strengthening the existing
  `Walk.support_bypass_subset` route with order information:
  `p.bypass.support` is a `List.Sublist` of `p.support`.
- This is the missing infrastructure needed by the ordered later-return proof:
  the unordered cross-repeat from
  `exists_left_prefix_right_suffix_tail_of_not_mem_alt` must be upgraded by
  showing that if all left-prefix repeats in the right suffix occur before `y`,
  then `y` remains in the sublist-preserving loop erasure.

Current blocker chain:
- Immediate stage target:
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_later_left_return`.
- Parent target:
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`,
  specifically its `hy_suffix` branch.
- Remaining chain to `conjecture198a`:
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` →
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` →
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` →
  splice descent and two-fan theorem →
  Chvatal-Erdos traceability →
  `conjecture198a`.

## Iteration 8

## 2026-06-28 left-prefix not-alt descent, iteration 1

External sources relied on:
- None from web or literature in this iteration.
- Local run context read from
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_continue_20260628_focused_2h/wowii198a-left-prefix-not-alt-descent/lean_formalizer/round-001-terminal-set-fan-left-suffix-retention-left-prefix-not-alt-commoncard-descent/context_bundle.md`
  and the paired `math_tools_report.md`.

Verifier state:
- Reproduced the configured Lean failure. The first blocker is still the
  `hy_suffix` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- The branch now has the checked later-return witness
  `r ∈ (((pair.2).dropUntil x).dropUntil y).support`,
  `r ≠ y`, and
  `r ∈ ((pair.1).takeUntil x).support`, but the proof still needs a
  constructed pair with strictly smaller `terminalPathPairCommonCard`.

Next Lean helper shape:
- The viable route is to reuse the existing fallback-pair common-support
  containment proof in the suffix case, replacing the old
  `x ∉ fallbackLeft` argument by the ordered bypass-erasure fact
  `x ∉ (((pair.1).takeUntil x).append ((pair.2).dropUntil x)).toPath.support`.
- That erasure fact should be proved from the later left-prefix return:
  a vertex from the left prefix reappearing strictly later in the right suffix
  forces `Walk.bypass` to delete the middle interval containing `x`.

External sources relied on:
- None from new web or literature search in this iteration.
- Local run context and `math_tools_report.md` were reread. The only external
  mathematical source context used remains the prior proof-lab grounding in
  Diestel, *Graph Theory*, Section 3.3 "Menger's theorem"; it is source
  evidence only, not an admissible Lean theorem.

Verifier/search work:
- Ran the required verifier command. Lean still reports the first target-local
  error at the nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`, where
  the separator hypothesis `hsep` is being used directly as the existential
  pair of internally disjoint paths.
- Rechecked the local workspace and mathlib for a proved `SimpleGraph`
  Menger/fan/internal-disjoint path theorem. No usable theorem was found.

Remaining formal blocker:
- The exact missing Lean theorem remains the finite endpoint-pair `k = 2`
  vertex Menger theorem. The current branch has a simple `u-w` path `p` with
  two distinct internal vertices and two singleton-avoiding replacement paths
  `qx` and `qy`; what is still absent is the checked rerouting/min-cut argument
  producing two simple `u-w` walks whose supports meet only at `u` and `w`.
- I did not introduce a trusted source-admission declaration, weaken the target
  statement, or edit the frozen downstream wrappers.

## 2026-06-25 final iteration check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied `context_bundle.md` and
  `math_tools_report.md`. The only external mathematical source context remains
  the prior proof-lab grounding in Diestel, *Graph Theory*, Section 3.3
  "Menger's theorem"; this remains source evidence only, not an admissible Lean
  theorem.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked local `AmraLibrary` and the full local mathlib checkout for
  Menger/fan/vertex-disjoint path theorems and for Walk rerouting primitives.
  Mathlib provides finite walk enumeration, `takeUntil`/`dropUntil`, `bypass`,
  and support lemmas, but no checked finite vertex Menger/Fan theorem.

Remaining formal blocker:
- The first Lean error is still the nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator` at the
  term `exact hsep`. Closing it requires a Lean proof of the endpoint-pair
  finite `k = 2` vertex Menger rerouting/min-cut step, not just local Walk
  packaging.
- No trusted source-admission declaration, theorem weakening, or forbidden
  proof token was introduced.

## 2026-06-27 iteration 5 suffix-retention bad-pivot check

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Selected blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, the current first
  blocker before `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  then `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the
  left/right splice descents, the two-fan theorem, the longest-path missed-vertex
  contradiction, Chvatal-Erdos traceability, and `conjecture198a`.

Tool check:
- Ran a small Python incidence/order sanity check for the exposed left-prefix
  containment obligation. The model used `rs = [v,w,z,y,s]`,
  old-left support `[v,z,x,s]`, and old-right support `[v,w,y,x,t]`.
  Then `z ∈ rs ∩ altRight`, `z` comes from the old-left prefix to `x`,
  `z` is not old-right, `x ∉ rs`, `x ∈ oldRight.dropUntil w`, and `w` is the
  first non-apex old-support hit on `rs`.  But the splice
  old-left-prefix-to-`z` plus `rs.dropUntil z` has erased common support `{y}`,
  while the old erased common support with `x` removed is empty.

Implication:
- The current local containment proof is too strong for an arbitrary bad pivot
  `z`.  The proof needs a theorem package that first selects an extremal bad
  pivot on `rs` and then splices at that pivot, or else the statement needs the
  corresponding extremality/order hypothesis.  The present declaration has no
  such hypothesis, so the two Lean holes at the erased-common containment steps
  are conceptual rather than syntactic.

## 2026-06-25 round-002 side-fan iteration-7 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied side-fan `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

## 2026-06-27 bad-pivot descent iteration 2

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

## 2026-06-27 bad-pivot descent iteration 6

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Selected blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, the current first
  blocker before `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  then `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the
  left/right splice descents, the two-fan theorem, the longest-path missed-vertex
  contradiction, Chvatal-Erdos traceability, and `conjecture198a`.

Tool check:
- Reran the Python incidence/order check for the arbitrary old-left-prefix bad
  pivot branch with `rs = [v,w,z,y,s]`, old-left support `[v,z,x,s]`, and
  old-right support `[v,w,y,x,t]`.  It confirms the local containment subgoal is
  false in this branch shape: the splice old-left-prefix-to-`z` plus
  `rs.dropUntil z` has erased common support `{y}`, while the old erased common
  support with `x` removed is empty.
- Also tried realizing the same incidence pattern as a small undirected graph
  using the union of the three displayed paths.  That graph has a separate
  disjoint terminal pair, so it is not a full counterexample to the theorem with
  weighted minimality.  It does confirm that the current proof needs an
  extremal-pivot or weighted-measure argument to remove the later `y`; the
  local membership goal cannot be discharged by the stated first-hit hypotheses
  alone.

Remaining formal blocker:
- Lean errors at the two containment branches ask for
  `y ∈ (((pair.1.support.toFinset ∩ pair.2.support.toFinset).erase v).erase x)`.
  In the unresolved subcase, the available facts only give `y ∈ rs.support` and
  `y ∈ pair.2.support`, not `y ∈ pair.1.support` nor `y ≠ x` via the old common
  set.  The statement/proof route therefore still needs an extremal bad-pivot
  package or an explicit weighted-measure descent for the secondary splice.

## 2026-06-27 left-prefix residual iteration 1

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Added checked helper
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false_of_altRight`.
  It proves the easy part of the requested left-prefix residual target: if the
  residual vertex from `rs.dropUntil z` is also in `altRight.support`, then
  last-bad extremality forces it to equal `z`, contradicting `z ∉ pair.2.support`
  and the residual right-support hypothesis.

Remaining formal blocker:
- The full requested helper
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` is
  still missing. Its hard branch is the weighted fallback where the residual
  vertex is not known to lie in `altRight.support`; this branch must construct
  the secondary splice, prove common-card nonincrease, prove strict support
  length descent, and invoke
  `false_of_weighted_min_and_commonCard_le_supportLength_lt`.

## 2026-06-28 left-prefix not-alt common-card descent final iteration

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Verifier result:
- The required command still fails at the stage theorem
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.

Selected blocker:
- Current first blocker to `conjecture198a` remains
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.  This stage lemma
  is intended to close the left-prefix residual branch before
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Tool check:
- Ran a small Python sequence-model sanity check for the stronger bypass shape:
  for simple prefix/suffix sequences, if a suffix vertex `y` is removed by
  bypassing `leftPrefix ++ rightSuffix`, then a repeated vertex from the left
  prefix occurs in the right suffix after `y`.  No counterexample was found in
  the bounded check through seven labelled vertices.  This is route evidence
  only; Lean still needs the corresponding checked order lemma.

Remaining formal blocker:
- The existing checked helper
  `exists_old_common_ne_x_of_right_suffix_not_mem_alt` only produces an old
  common vertex `r ≠ x` somewhere in the old right suffix.  The suffix branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  needs the stronger ordered conclusion: a return vertex in the old-left prefix
  lying in `(oldRight.dropUntil y).support.tail`, or an equivalent direct
  common-card descent pair.  Without this order fact, the fallback path may
  retain `x`, and the current proof has no way to prove strict common-card
  descent.

## 2026-06-28 interval-erasure target check

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.
- Local mathlib source `Mathlib/Combinatorics/SimpleGraph/Paths.lean` was
  checked for the definition of `Walk.bypass`/`Walk.toPath`.

Selected blocker:
- The current first blocker to `conjecture198a` remains
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, through
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
  The requested next stage theorem
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_interval_erased`
  was not present in the Lean workspace.

Tool check:
- Ran a Python sequence model of mathlib's `Walk.bypass`, with simple
  left-prefix support `[0, 1, 2, 3]`, right suffix support `[3, 1, 4, 2]`,
  combined append support `[0, 1, 2, 3, 1, 4, 2]`, and bypass support
  `[0, 1, 2]`.  For `x = 3` and `y = 4`, the hypotheses of the proposed
  interval-erasure statement hold at the support-list level: `y` lies in the
  right suffix, `y` is not in the left prefix, and `y` is absent from the
  bypassed append.  There is a later return `2` into the left prefix, but the
  interval `[3, 1, 4]` is not erased because `1` survives in the bypass support.

Implication:
- The exact interval-erasure clause
  `∀ u ∈ (right.dropUntil x).takeUntil y, u ∉ altRight.support` is too strong.
  The viable Lean target is the ordered bypass obstruction without interval
  erasure: absence of a non-left suffix vertex should produce a later suffix
  return into `left.takeUntil x`, or directly construct the strict
  `terminalPathPairCommonCard` descent needed by
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.

## 2026-06-27 left-prefix residual iteration 3

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Tool check:
- Ran a bounded Python sequence-model probe for the hard branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
  The probe found the concrete path-shape
  `oldLeft = [v,1,x,s]`, `oldRight = [v,w,y,x]`,
  `rs = [v,w,1,y,s]` with `x = 2`, `w = 4`, `z = 1`, `y = 5`
  after relabelling as
  `oldLeft = (0,1,2,3)`, `oldRight = (0,4,5,2)`,
  `rs = (0,4,1,5,3)`.  This satisfies the local order/incidence assumptions
  of the residual branch, including last-bad control for bad vertices in
  `altRight.support ∩ rs.dropUntil z`, while `y ∈ oldRight.support` and
  `y ∉ altRight.support`.
- Realizing the three paths as the union graph does not satisfy global weighted
  minimality: the graph has a lower-measure terminal pair
  `(0,4,5,3)` and `(0,1,2)`.  Thus this is not a counterexample to the full
  weighted-minimal theorem, but it confirms that the local residual helper
  cannot be closed by containment or extremality alone.  The remaining proof
  must use the global weighted-minimality premise to construct an actual
  lower-measure pair.

Remaining formal blocker:
- The fallback branch at
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`
  still ends at `exact hpair_measure_min`.  The next useful theorem-level
  target is a weighted-minimality contradiction for the left-prefix residual
  branch, not another support-containment lemma.

## 2026-06-28 left-prefix residual iteration 3

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Rewired `terminal_set_fan_left_suffix_retention_bad_pivot_descent` so an
  arbitrary bad witness first produces a last bad pivot on `rs` via
  `exists_last_bad_pivot_on_rs`.
- Used the resulting `hlast_bad` hypothesis to replace the stale
  `exact hpair_measure_min` in the old-left-prefix residual subcase with a call
  to `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Remaining formal blocker:
- The residual helper still has the invalid isolated fallback proof:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`
  tries to use weighted minimality as both common-card nonincrease and strict
  support-length descent.
- The arbitrary bad-pivot proof now has only the old-right-suffix residual stale
  branch remaining; it needs the analogous first-bad-pivot control or a
  weighted-minimality fallback under the right-suffix residual hypotheses.

## 2026-06-28 left-prefix residual iteration 4

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Reconfirmed the current first blocker:
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- Added the checked walk-order support lemma
  `mem_takeUntil_of_mem_support_not_dropUntil`, the dual of the existing
  `mem_dropUntil_of_mem_support_not_takeUntil`.  This is intended for the
  first-bad/right-suffix residual branch, where a vertex known not to lie in a
  suffix must be recovered in the corresponding prefix.

Remaining formal blocker:
- The left-prefix fallback branch still needs a proved common-card
  nonincrease and strict support-length descent under the residual extremality
  hypothesis.
- The old-right-suffix residual branch still needs the analogous first-bad
  extremal control before the stale `exact hpair_measure_min` can be removed.

## 2026-06-28 interval-erasure formalizer iteration 5

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.
- Local mathlib source
  `.lake/packages/mathlib/Mathlib/Combinatorics/SimpleGraph/Paths.lean` was
  reread for the definitions and available API of `Walk.bypass` and
  `Walk.toPath`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, through the
  parent `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
  The remaining chain is
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Verifier result:
- The required verifier still fails at two active proof stubs:
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  returns `hy_suffix` where Lean needs a strict common-card descent witness, and
  the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` returns
  `hpair_measure_min` where Lean needs `False`.

Target assessment:
- The requested stage declaration
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_interval_erased`
  is still absent from the Lean workspace.  I did not add it because the
  interval-erasure conjunct is false for mathlib `Walk.bypass`; the prior
  recorded support-list counterexample
  `leftPrefix = [0,1,2,3]`, `rightSuffix = [3,1,4,2]`,
  `bypass([0,1,2,3,1,4,2]) = [0,1,2]` has `y = 4` absent from the bypass
  while the prefix interval vertex `1` survives.

Remaining formal blocker:
- The checked helper
  `exists_left_prefix_right_suffix_tail_of_not_mem_alt` only proves an
  unordered return vertex in `(oldRight.dropUntil x).support.tail`.  The
  `hy_suffix` descent branch needs the stronger ordered theorem: if a
  non-left vertex `y` of `oldRight.dropUntil x` is absent from
  `((oldLeft.takeUntil x).append (oldRight.dropUntil x)).toPath.support`, then
  either there is a return vertex in
  `(oldRight.dropUntil x).dropUntil y` meeting `oldLeft.takeUntil x`, or the
  statement directly supplies a strict `terminalPathPairCommonCard` descent
  pair.  This ordered/descent package is also the right symmetric ingredient
  for replacing the stale old-right-suffix `hpair_measure_min` branch.

## 2026-06-28 left-prefix residual iteration 6

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Added checked helper `false_of_weighted_min_and_commonCard_lt`. This isolates
  the valid weighted-minimality contradiction available from a strict
  common-card descent, avoiding the previously falsified standalone
  support-length fallback route.

Remaining formal blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`
  still must be strengthened or inlined under the residual `hlast_bad`
  hypothesis to prove strict common-card descent of the fallback pair.
- The old-right-suffix residual branch in

## 2026-06-28 left-prefix residual round-004 iteration 1

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`; prior local finite probes in this note were used only
  as route evidence.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- This feeds `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and finally
  `conjecture198a`.

Lean blocker:
- The verifier still fails at the two stale uses of `hpair_measure_min`:
  line 4830 expects a strict common-card descent for the fallback pair, and
  line 5486 expects `False` in the old-right-suffix residual branch.
- I did not replace these with local containment claims because the prior
  sequence probes show that the support-containment route is false without an
  additional residual pivot package or a genuine weighted-minimality descent.

Next target:
- Prove a theorem-level residual fallback contradiction carrying the full pivot
  package, including explicit pivot survival in `altRight.support` where needed,
  or refactor the right-suffix branch to select/use the corresponding first-bad
  residual package before the splice.
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still needs the
  symmetric first-bad control rather than the stale direct use of
  `hpair_measure_min`.

## 2026-06-27 left-prefix weighted fallback iteration 6

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Selected blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`,
  which is intended to close the hard branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`, then
  feed `terminal_set_fan_left_suffix_retention_extremal_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Tool check:
- Ran a small Python sequence-level sanity check for the exact prescribed
  fallback route.  With
  `oldLeft = [v,z,x,s]`, `oldRight = [v,w,y,x,t]`, and
  `rs = [v,w,z,y,a,b,c,s]`, the local left-prefix residual shape holds:
  `z` is an old-left-prefix bad pivot, `y ∈ rs.dropUntil z`,
  `y ∈ oldRight`, and `y ∉ altRight`.  The fallback pair
  `oldRight.takeUntil y ++ rs.dropUntil y` against `altRight` lowers erased
  common support from `{x}` to `∅`, but its total support length increases from
  `9` to `11`.

Implication:
- The current proof route inside
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`
  is not valid as stated: the required
  `terminalPathPairSupportLength fallbackPair < terminalPathPairSupportLength pair`
  does not follow from the local hypotheses.  The next proof target should
  replace the support-length fallback with a strict common-card descent for the
  fallback pair, using last-bad extremality to control vertices from
  `rs.dropUntil` that also lie in `altRight`.  The isolated fallback theorem
  lacks that extremality hypothesis, so the theorem-level target should move
  back under `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`
  or be strengthened as a private helper used only there.

Tool checks:
- Attempted to write a finite bad-pivot shape probe under the run artifact
  directory, but that directory is read-only in this sandbox.
- Ran the same probe from `/tmp`; exhaustive search through 7 vertices and then
  through 6 vertices was interrupted because it did not return quickly enough.
  A randomized follow-up probe was also interrupted. These checks are
  inconclusive and are not used as proof evidence.

Lean work:
- Added checked helper `not_both_mem_dropUntil_on_simple_path`, proving that
  on a simple path two distinct vertices cannot each lie in the other's
  `dropUntil` suffix. The proof uses the existing
  `exists_index_of_mem_dropUntil` helper and `IsPath.getVert_injOn`.
- Used this helper inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` to close the
  old-right-suffix subcase where the bad pivot `z` is exactly the first
  old-right hit `w`.

Remaining formal blocker:
- The target theorem still has two descent obligations:
  old-left-prefix bad pivot via old-left prefix to `z` plus `rs.dropUntil z`,
  and old-right bad pivot strictly after `w` via `rs.takeUntil z` plus the
  old-right suffix from `z`.
- In both branches, the missing proof is the extremal-pivot containment:
  vertices from the `rs` side of the secondary splice can introduce later
  intersections unless the proof chooses an order-extremal bad pivot and shows
  the erased common support is contained in the old erased common support with
  `x` removed, or derives the weighted-measure contradiction.

## 2026-06-28 left-prefix not-alt common-card descent iteration 3

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- It feeds `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`,
  then `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Lean work:
- Added checked helper
  `exists_mem_left_and_right_tail_of_not_isPath_append`.  It extracts the
  concrete cross-repeat from a failed append of two simple walks: some vertex
  is in the left support and in the tail of the right support.  Combined with
  `not_isPath_append_of_not_mem_toPath_append_right`, this gives the Lean-ready
  first bypass obstruction for the hard branch where
  `y ∈ (pair.2.dropUntil x).support` but
  `y ∉ (((pair.1.takeUntil x).append (pair.2.dropUntil x)).toPath).support`.

Remaining formal blocker:
- The suffix branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  still needs to turn that extracted return from the old-right suffix into an
  actual strict common-card descent pair.
- The old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still has the
  stale `exact hpair_measure_min`; it needs the symmetric first-bad residual
  package or a direct weighted-minimality contradiction.

## 2026-06-28 left-prefix not-alt common-card descent iteration 5

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`; prior local finite probes in this note remain route
  evidence only.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- It feeds `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`,
  then `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Lean work:
- Added checked helper
  `exists_old_common_ne_x_of_right_suffix_not_mem_alt`.  It upgrades the
  existing `.toPath` bypass obstruction: if a vertex of the old-right suffix is
  absent from
  `((oldLeft.takeUntil x).append (oldRight.dropUntil x)).toPath`, then the
  obstruction yields an old common vertex `r` with `r != x`.
- Wired that helper into the hard `hy_suffix` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.

Remaining formal blocker:
- The `hy_suffix` branch still needs the descent construction from the returned
  old common vertex `r`.  The checked witness is now available in the branch as
  `hbypass_return`, but the proof must still build a pair whose erased common
  support strictly drops from the old pair.
- The old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still needs the
  symmetric first-bad residual package; the current stale `hpair_measure_min`
  term is not a proof of `False`.

## 2026-06-27 bad-pivot descent iteration 4

External sources relied on:
- None from web or literature in this iteration.
- Local run context and `math_tools_report.md` were read from the supplied run
  artifact directory.

Tool check:
- Ran a Python/NetworkX exhaustive probe for the exact
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` hypothesis shape
  on all labelled simple graphs through 5 vertices, enumerating simple
  terminal path pairs, weighted-minimal pairs, replacement paths, first
  crossing witnesses, retained suffix cases, and bad pivots. No counterexample
  was found for instances where the alternate right splice is already simple.
  This is route evidence only and not a Lean proof.

Lean work:
- Added checked helper `mem_dropUntil_of_mem_support_not_takeUntil`, splitting
  a walk support vertex not in a `takeUntil` prefix into the corresponding
  `dropUntil` suffix using `take_spec`.
- Refined both containment proofs in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` to split on the
  raw append support rather than only the coarse old/replacement support union.
  The old-side cases now close directly, and the `y = w` replacement-side
  subcases close using the existing simple-path suffix-order contradiction.

Remaining formal blocker:
- The target theorem still needs the extremal-pivot package for the two
  replacement-side cases exposed by Lean: in the left-prefix branch,
  `y ∈ rs.dropUntil z`, `y ∈ oldRight`, and `y ∉ rs.takeUntil w`; in the
  right-suffix branch, `y ∈ rs.takeUntil z`, `y ∈ oldLeft`, and
  `y ∉ rs.takeUntil w`. These are exactly the cases where arbitrary `z`
  lacks the required first/last bad-pivot control.

## 2026-06-26 round-002 terminal-set fan iteration-7

External sources relied on:
- None from new web or literature search in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`. No external theorem was imported or trusted.

Lean work:
- Added checked cardinal infrastructure:
  `card_lt_of_subset_erase_mem` and
  `common_support_erase_card_lt_of_subset_erase_common`.
- Added checked finite minimization infrastructure for the proof-lab route:
  `terminalPathPairSupportLength`,
  `terminalPathPairWeightedMeasure`,
  `terminalPathPairSupportLength_le`,
  `terminalPathPairWeightedMeasure_lt_of_commonCard_lt`, and
  `exists_minimal_terminal_path_pair_weighted_measure`.
- Rewired `finite_two_fan_to_pair_of_terminal_set_no_small_endpoint_separator`
  to choose a weighted-minimal terminal path pair and derive the local descent
  contradiction used in the downstream fan package.

## 2026-06-27 round-001 left first-crossing iteration-2

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Tool check:
- Ran a bounded Python exhaustive sanity check for the explicit
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` lemma shape
  on connected simple graphs with up to 5 vertices, enumerating simple terminal
  paths, weighted-minimal path pairs, replacement paths, and first-crossing
  witnesses. No counterexample was found. The 6-vertex extension was
  interrupted for time and is not used as evidence.

Lean work:
- Inserted the requested declaration
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`.
- Inside that declaration, formalized the explicit splice
  `rs.takeUntil w` appended to `(pair.2 : G.Walk v t).dropUntil w`, followed by
  `toPath`.
- Proved the support-containment subgoal: every erased common support vertex of
  the spliced pair is already an erased common support vertex of the old pair.
  The proof uses `support_toPath_subset`, `mem_support_append_iff`,
  `support_dropUntil_subset`, `hx_rs`, `hw_not_left`, and the supplied
  first-crossing hypothesis.

Remaining formal blocker:
- The strict descent step is still missing. The proved containment is only
  non-strict; Lean still needs either an order lemma showing the old common
  vertex `x` is absent from the old right suffix
  `(pair.2 : G.Walk v t).dropUntil w hw_right`, or a checked argument that
  equality of common cards forces the spliced pair to have strictly smaller
  `terminalPathPairWeightedMeasure`, contradicting `hpair_measure_min`.
- The existing left/right wrapper lemmas also remain blocked because their
  locally chosen first opposite-path crossing does not yet provide the stronger
  `hw_not_left` plus union-first-hit hypothesis required by the isolated lemma.
  contradiction principle `hpair_no_common_decrease`.

Remaining formal blocker:
- The verifier still stops in the positive common-support branch of
  `finite_two_fan_to_pair_of_terminal_set_no_small_endpoint_separator`.
  The missing step is the actual splicing construction: from a weighted-minimal
  pair with non-apex common vertex `x` and an `hsep` path avoiding `{x}`,
  construct a new `v-s`/`v-t` path pair whose erased common-support finset is
  contained in the old one with `x` erased, then apply the checked cardinal
  drop and contradict `hpair_no_common_decrease`.

## 2026-06-27 round-004 terminal-set fan iteration-1

External sources relied on:
- None from new web or literature search in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`. No external theorem was imported or trusted.

Tool check:
- Ran a bounded Python sanity check for the exact
  `terminal_set_fan_splice_descent_left_of_hsep` hypothesis pattern: terminal
  separator `hsep`, weighted-minimal terminal path pair, non-apex common
  vertex `x`, replacement path avoiding `x`, and a new opposite-path
  intersection. Exhaustive labelled simple graphs through 5 vertices produced
  no witness instances and no counterexample; 500 random 6-vertex graphs also
  produced no counterexample. This is route evidence only.

Lean work:
- Added checked helper
  `not_mem_takeUntil_first_pair_support_of_ne`: once a replacement walk's
  `takeUntil` prefix is stopped at the first non-apex hit of the old pair
  support union, any other old-support vertex is absent from that prefix.

Remaining formal blocker:
- The verifier still stops in `terminal_set_fan_splice_descent_left_of_hsep`
  and its symmetric right theorem at the uncrossing step. The current first-hit
  splice only controls the replacement prefix; the proof still needs a
  first/last-intersection argument showing the old common vertex `x` is removed
  from the relevant suffix or that the weighted measure strictly decreases.

## 2026-06-26 round-002 terminal-set fan iteration-5

External sources relied on:
- None from new web or literature search in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Tool check:
- Ran a plain Python exhaustive search over labelled simple graphs with
  3, 4, and 5 vertices for the exact terminal-set separator condition:
  for every empty or singleton cut not containing `v`, at least one of `s,t`
  remains reachable from `v`. No counterexample was found to the existence of
  a `v-s` and `v-t` fan whose supports meet only at `v`. The 6-vertex search
  was interrupted as too slow, so only the completed 3--5 vertex sweep is used
  as route evidence.

Current formal blocker:
- The active Lean blocker is still the theorem-level finite terminal-set
  k=2 fan/min-cut step. The file has a minimal common-support path pair and a
  singleton-avoiding terminal replacement path from `hsep`, but the checked
  splicing/descent proof that removes newly introduced non-apex intersections
  is not yet formalized.

Tool check:
- Ran a plain Python exhaustive sanity check for the exact repaired side-fan
  statement on all labelled simple graphs with 3 through 6 vertices and all
  ordered triples `(v,s,t)`. Among 2,245,884 triples satisfying the two
  endpoint-excluding empty/singleton reachability hypotheses, no counterexample
  to the internally disjoint `v-s`/`v-t` fan conclusion was found. This is route
  evidence only; the required acceptance criterion remains the Lean verifier.

Lean blocker selected:
- The first Lean error is now target-local at
  `finite_two_fan_to_pair_of_both_no_small_endpoint_separator`, line 3600.
  The proof has a common internal vertex `x`, singleton-deleted reachability
  from `v` to both terminals in `G - x`, and replacement simple paths avoiding
  `x`; the missing step is the endpoint-excluding finite `k = 2`
  one-source/two-terminal fan augmentation theorem producing two simple walks
  whose supports meet only at `v`.

## 2026-06-25 round-006 iteration-1 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied round-006 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

## 2026-06-25 round-008 final formalizer check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied round-008 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked the local workspace and local mathlib checkout for a usable
  `SimpleGraph` finite Menger/fan/internal-disjoint path theorem. No such
  checked theorem was found.
- Ran a small `/tmp` Lean `native_decide` probe for the generic finite-decision
  route. The process exited with code 139 in this environment, matching the
  earlier failed computational-proof route; no result from this probe is used
  as proof evidence.

## 2026-06-25 round-002 paired side-fan check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied round-002 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Tool check:
- Ran an exhaustive Python check over all labelled simple graphs through
  6 vertices and all ordered choices of distinct `v,s,t`. The check encoded the
  repaired paired endpoint-excluding hypothesis for `C = ∅` and singleton
  `C`, then searched for simple `v-s` and `v-t` paths whose supports intersect
  only at `v`.
- Results: no counterexample through 6 labelled vertices. At `n = 6`, the
  script checked 3,932,160 ordered triples and found 2,219,520 satisfying the
  hypothesis. This is route evidence only; the Lean proof still needs a checked
  finite endpoint-excluding `k = 2` fan/min-cut argument.

## 2026-06-25 round-002 iteration-3 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied round-002 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean theorem.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked local mathlib and the local workspace for a usable Menger/Fan,
  vertex-disjoint path, or separator theorem. No checked theorem closing this
  branch is available in the current imports/checkout.

Remaining formal blocker:
- The first target-local branch now has two endpoint-avoiding paths `qs`, `qt`.
  If they already meet only at `v`, the theorem closes. In the hard branch, a
  common internal vertex `x` is found and the hypotheses give replacement
  paths `qs'`, `qt'` avoiding `x`. The missing proof obligation is exactly the
  finite endpoint-excluding two-terminal `k = 2` fan/min-cut augmentation:
  singleton-avoidance of one common vertex does not prove that the replacement
  witnesses have no other common internal vertex.
- No trusted source-admission declaration, theorem weakening, or forbidden
  proof token was introduced.

## 2026-06-25 round-002 iteration-6 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied round-002 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean theorem.

Tool check:
- Ran a plain Python exhaustive check over all labelled simple graphs through
  6 vertices and all ordered distinct triples `v,s,t`. It encoded the repaired
  paired endpoint-excluding hypothesis for `C = ∅` and singleton `C`, then
  searched all simple `v-s` and `v-t` paths for a pair meeting only at `v`.
- Results: no counterexample through 6 labelled vertices. The `n = 6` pass
  enumerated 32,768 graphs and 3,932,160 ordered triples, with 2,219,520
  triples satisfying the hypothesis. This is route evidence only.

Lean work:
- Reran the required verifier and confirmed the first target-local error.
- Replaced the accidental hard-branch bogus term `exact hvs` with a local
  `hfan` obligation whose type is exactly the missing endpoint-excluding
  one-source/two-terminal `k = 2` fan/min-cut augmentation witness.

Remaining formal blocker:
- The current branch has singleton-deleted reachability from `v` to both
  terminals in `G - x` and replacement paths `qs'`, `qt'` avoiding the common
  internal vertex `x`. Lean still needs the checked finite fan/min-cut
  augmentation theorem producing `rs : G.Walk v s` and `rt : G.Walk v t`
  whose supports meet only at `v`.

Remaining formal blocker:
- The target
  `exists_singleton_endpoint_separator_of_no_two_internally_disjoint_paths_with_path`
  reduces to
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`, whose
  nondegenerate branch still requires the finite endpoint-pair `k = 2` vertex
  Menger rerouting/min-cut theorem. No trusted source-admission declaration,
  theorem weakening, or forbidden proof token was introduced.

## 2026-06-25 round-008 singleton-with-path check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied round-008 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked the local project and mathlib checkout for a usable finite
  `SimpleGraph` Menger/Fan theorem or an internal-disjoint path theorem. No
  project-approved theorem was found.

Current first blocker:
- The target
  `exists_singleton_endpoint_separator_of_no_two_internally_disjoint_paths_with_path`
  reduces by contradiction to
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`.
  That endpoint-pair theorem still fails in its nondegenerate branch at
  `Wowii198aLeftmost.lean:3537`, where the separator hypothesis `hsep` is not
  the required pair of internally disjoint simple `u-w` walks.
- The remaining missing ingredient is the endpoint-pair finite `k = 2`
  vertex-Menger rerouting/min-cut proof. I did not add a trusted source
  admission, weaken any theorem, or edit the frozen downstream wrappers.

## 2026-06-25 round-008 iteration-5 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied round-008 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked local `AmraLibrary` and the local mathlib checkout for a usable
  finite vertex Menger/Fan or internally vertex-disjoint path theorem. No
  theorem was found that can replace the open endpoint-pair min-cut branch.

Remaining formal blocker:
- The corrected singleton target still depends on
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`; that
  theorem fails at its nondegenerate branch where `hsep` is expected to produce
  two internally disjoint `u`-`w` paths. Closing the current target therefore
  requires a checked finite endpoint-pair `k = 2` vertex Menger/min-cut proof,
  not another local Walk packaging lemma.
- I did not introduce a source-admission declaration, weaken any theorem, or
  add a forbidden proof token.

## 2026-06-25 round-008 iteration-2 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied round-008 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked the local mathlib checkout for max-flow/min-cut, Menger, fan, and
  vertex-disjoint path theorems. No usable `SimpleGraph` theorem was present.
- Rechecked available `Walk` infrastructure. Mathlib provides
  `takeUntil`/`dropUntil`, `bypass`, `toPath`, and support-subset lemmas, but
  these do not supply the endpoint-pair min-cut/rerouting theorem.

Remaining formal blocker:
- The target singleton lemma is present and has the requested declaration, but
  it is currently only a contradiction wrapper around
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`.
- The first Lean error remains the open nondegenerate branch of that endpoint
  theorem at `exact hsep`: Lean has the singleton/empty separator hypothesis
  and needs two internally disjoint simple `u`-`w` walks.
- No trusted source-admission declaration, theorem weakening, or forbidden
  proof token was introduced.

## 2026-06-25 round-006 iteration-8 check

External sources relied on:
- None from new web or literature search in this iteration.
- Reread the supplied round-006 `context_bundle.md` and `math_tools_report.md`.
  The prior Diestel Section 3.3 grounding remains source evidence only; no
  sourced theorem was admitted into Lean.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked the local `SimpleGraph` mathlib files and broader mathlib checkout
  for Menger, fan, vertex-disjoint path, min-cut, and max-flow infrastructure.
  No Lean-checkable theorem was found that can close the endpoint-pair `k = 2`
  Menger step.

Remaining formal blocker:
- The first error remains the nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator` at
  `exact hsep`. The available hypothesis is endpoint-excluding
  empty/singleton separator avoidance, while the goal is an existential pair of
  internally disjoint simple `u`-`w` walks.
- Later errors at the frozen fan/attachment wrappers are the same dependency
  gap, not independent local simplification failures.

## 2026-06-25 round-006 iteration-7 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied round-006 `context_bundle.md` and
  `math_tools_report.md`. The only external mathematical source context remains
  the prior proof-lab grounding in Diestel, *Graph Theory*, Section 3.3
  "Menger's theorem"; it remains source evidence only, not an admissible Lean
  theorem.

Lean work:
- Added the checked helper
  `exists_path_of_no_small_endpoint_separator`, factoring the empty-separator
  consequence of the target hypothesis.
- Rewired the target theorem entry point to use this helper before splitting
  into endpoint-only, one-internal-vertex, and nondegenerate branches.

Verifier result:
- The required command still fails. The first error is now at
  `Wowii198aLeftmost.lean:3537:12`, where the nondegenerate branch still tries
  to use `hsep` directly as the required pair of internally disjoint paths.
- Later frozen-route failures remain at the 2-fan statement and downstream
  longest-path component/independence wrappers.

Remaining formal blocker:
- The missing proof is still the endpoint-pair finite `k = 2` vertex-Menger
  min-cut/rerouting core: from an original simple `u-w` path and two
  singleton-avoiding simple `u-w` replacement paths, construct two simple
  `u-w` walks whose supports intersect only at `u` and `w`.

## 2026-06-25 round-006 iteration-5 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied round-006 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Verifier/search work:
- Ran the required verifier command. The first target-local failure remains the
  nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`, where
  the separator hypothesis `hsep` is still being used directly as the
  existential internally-disjoint path pair.
- Rechecked the local mathlib checkout for Menger/fan/separator theorems and
  relevant walk decomposition primitives. The checkout has `takeUntil`,
  `dropUntil`, `bypass`, and path support lemmas, but no usable finite vertex
  Menger/Fan theorem.

Remaining formal blocker:
- The Lean workspace still needs a checked endpoint-pair finite `k = 2`
  vertex-Menger rerouting/min-cut lemma. In the current branch, Lean has a
  simple `u-w` path `p` with at least two distinct internal vertices and two
  singleton-avoiding simple `u-w` paths `qx` and `qy`; the missing proof must
  construct two simple `u-w` walks whose supports meet only at `u` and `w`.
- No trusted source-admission declaration, theorem weakening, or forbidden
  proof token was introduced.

## 2026-06-25 round-006 iteration-4 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied round-006 `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked local `AmraLibrary` and the local mathlib checkout for proved
  Menger/Fan/vertex-disjoint path theorems or directly usable rerouting
  primitives. No checked finite vertex Menger/Fan theorem was found.

Remaining formal blocker:
- The first Lean error remains
  `Wowii198aLeftmost.lean:3526:12`: the separator-avoidance hypothesis `hsep`
  is being used where Lean needs the existential pair of internally disjoint
  simple `u-w` walks.
- The remaining errors at lines 3546, 3671, 3675, and 3823 are downstream
  frozen-route obligations with the same missing nonlocal finite fan/Menger
  content or later Chvatal-Erdos independent-set content.
- No trusted source-admission declaration, theorem weakening, or forbidden
  proof token was introduced.

## 2026-06-25 round-006 iteration-2 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied round-006 `context_bundle.md` and
  `math_tools_report.md`. The prior Diestel Section 3.3 grounding remains
  mathematical evidence only, not a Lean admission mechanism.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked the local `AmraLibrary` and mathlib checkout for Menger, fan,
  separator, and internally vertex-disjoint path theorems. No usable finite
  vertex Menger/Fan theorem is present in the local dependencies.

Current Lean blockers:
- First target-local error remains at
  `Wowii198aLeftmost.lean:3526:12`: the nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator` has
  only the separator hypothesis `hsep`, but the goal is the existential pair of
  internally disjoint simple `u-w` walks.
- The later errors at lines `3546`, `3671`, `3675`, and `3823` are the frozen
  fan/component/downstream route still containing ill-typed open obligations.

Next proof target:
- Formalize the finite endpoint-pair `k = 2` vertex-Menger core, preferably as
  a theorem-level min-cut/rerouting lemma strong enough to close the branch
  with `p`, `qx`, and `qy`, then use it to replace the invalid `exact hsep`
  without changing the public theorem statement.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked local `AmraLibrary` and the local mathlib checkout for a proved
  `SimpleGraph` Menger/fan/vertex-cut/max-flow theorem. No usable theorem was
  found. Mathlib provides finite path enumeration plus walk decomposition and
  cycle/bridge lemmas, but not the finite vertex Menger result needed here.

Remaining formal blocker:
- The first target-local failure remains the nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`, at
  the invalid term `exact hsep`. At that point the proof has an original
  simple `u-w` path with two distinct internal vertices, plus two simple
  singleton-avoiding `u-w` paths. Closing the branch requires the checked
  finite endpoint-pair `k = 2` vertex-Menger rerouting/min-cut argument.
- The later verifier failures are the frozen fan/downstream branches using
  `exact hdelete`, `exact hzL`, an unproved ordering contradiction, and
  `exact hconn`.

## 2026-06-25 round-006 iteration-3 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied round-006 `context_bundle.md` and
  `math_tools_report.md`. The prior Diestel Section 3.3 grounding remains
  mathematical evidence only, not a Lean admission mechanism.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked the local mathlib checkout for Menger/fan/separator/internal
  disjoint path theorems and inspected the available finite walk enumeration
  and walk-subwalk support APIs. No checked finite vertex Menger/Fan theorem is
  available locally.

Current Lean blockers:
- First target-local error remains
  `Wowii198aLeftmost.lean:3526:12`: `hsep` has the endpoint-excluding
  separator-avoidance type, but Lean expects the existential pair of internally
  disjoint simple `u-w` walks.
- Later errors at `3546`, `3671`, `3675`, and `3823` are unchanged frozen-route
  stubs. They should not be repaired by introducing a source admission or by
  weakening the target theorem.

Next proof target:
- Formalize the finite endpoint-pair `k = 2` vertex-Menger core as a
  Lean-checked min-cut/rerouting theorem, then use it to replace the
  `exact hsep` branch in the target theorem.

## 2026-06-25 round-006 iteration-6 check

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was reread from the supplied round-006 `context_bundle.md` and
  `math_tools_report.md`. The prior Diestel Section 3.3 grounding remains
  mathematical evidence only, not a Lean admission mechanism.

Verifier/search work:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- Rechecked local `AmraLibrary` and the local mathlib checkout for
  Menger/Fan/vertex-disjoint path theorems and for walk rerouting primitives.
  The available API includes walk decomposition, finite path enumeration, and
  support lemmas, but no checked finite vertex Menger/Fan theorem was found.

Current Lean blockers:
- First target-local error remains
  `Wowii198aLeftmost.lean:3526:12`: `hsep` is the endpoint-excluding
  separator-avoidance hypothesis, while Lean needs the existential pair of
  internally disjoint simple `u-w` walks.
- The later errors at `3546`, `3671`, `3675`, and `3823` are the frozen
  downstream fan/attachment/independent-set obligations. They depend on the
  same missing finite fan/Menger core or on later nonlocal graph content and
  were not patched with source admissions or weakened statements.

Next proof target:
- Formalize a theorem-level finite endpoint-pair `k = 2` vertex-Menger
  min-cut/rerouting lemma and use it to close the nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`.

## 2026-06-25 round-008 singleton-with-path iteration-1

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-008 `context_bundle.md` and `math_tools_report.md`.
  The prior Diestel Section 3.3 grounding remains mathematical evidence only,
  not an admissible Lean dependency.

Lean work:
- Inserted the requested declaration
  `exists_singleton_endpoint_separator_of_no_two_internally_disjoint_paths_with_path`
  with the exact statement shape required by the stage.
- Proved the local wrapper reduction from the existing endpoint-pair theorem:
  if no singleton hits every simple `u`-`w` path, then every empty or singleton
  endpoint-excluding separator is avoidable; applying
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`
  contradicts `hno`.

Verifier result:
- Ran the required verifier command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- The wrapper itself introduced no new reported error. The first error remains
  the unproved nondegenerate branch of
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`, where
  `hsep` is still being used directly as an internally disjoint path pair.

Remaining formal blocker:
- Formalize the finite endpoint-pair `k = 2` vertex-Menger min-cut/rerouting
  theorem. Once that theorem is checked, the newly inserted singleton
  separator theorem should close by the wrapper reduction.

## 2026-06-25 round-008 singleton-with-path iteration-3

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-008 `context_bundle.md` and `math_tools_report.md`.
  The existing Diestel Section 3.3 note remains source grounding only, not a
  Lean dependency or admission mechanism.

Lean/API diagnostics:
- Reran the required verifier command. The first error is still in
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator` at the
  branch where `hsep` is being used as if it were already a pair of internally
  disjoint paths.
- Rechecked local `AmraLibrary` and mathlib for Menger/Fan/vertex-cut/min-cut
  theorems and for walk rerouting APIs. The walk APIs (`takeUntil`,
  `dropUntil`, `bypass`, `toPath`) exist and can package constructed walks into
  paths, but no local theorem supplies the missing finite `k = 2` vertex-Menger
  existence step.
- The corrected singleton theorem is only a wrapper over that endpoint-pair
  theorem: under contradiction it turns "no universal singleton" into the
  empty/singleton separator-avoidance hypothesis and then applies
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`.

Remaining formal blocker:
- Formalize the finite endpoint-pair `k = 2` vertex-Menger min-cut/rerouting
  core, or obtain an audit-approved admission mechanism. Without that theorem,
  the target singleton separator theorem cannot be verified, and the later
  frozen fan/longest-path wrappers also remain unbuildable.

## 2026-06-25 round-008 singleton-with-path iteration-4

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-008 `context_bundle.md` and `math_tools_report.md`.
  The existing Diestel Section 3.3 note remains source grounding only, not a
  Lean dependency or admission mechanism.

Tool checks:
- Attempted to write the requested run-directory experiment record, but the
  artifact path is read-only in this sandbox. Recorded this durable workspace
  note instead.
- Ran a bounded Python enumeration of all simple graphs on at most five
  vertices and all endpoint pairs with at least one simple path. For every
  instance with no two internally disjoint simple endpoint paths, the internal
  vertex intersection over all simple endpoint paths was nonempty. Result:
  `ok checked connected endpoint instances 9044 for n<=5`. This supports the
  corrected singleton theorem shape but is not a Lean proof.

Lean/API diagnostics:
- Re-ran the required verifier command. The first error remains the invalid
  `exact hsep` in
  `finite_two_internally_disjoint_paths_of_no_small_endpoint_separator`.
- Rechecked local mathlib graph connectivity APIs. `WalkCounting` provides
  finite enumeration of bounded-length paths, and `WalkDecomp`/`Subgraph`
  provide `takeUntil`, `dropUntil`, `bypass`, and path support tools. No local
  finite vertex Menger/Fan or no-singleton-separator-to-two-paths theorem was
  found.

Remaining formal blocker:
- The corrected singleton theorem is still a wrapper over the missing finite
  endpoint-pair `k = 2` vertex-Menger core. The next proof step must supply a
  Lean-checked min-cut/rerouting theorem, not a source admission or another
  downstream wrapper patch.

## 2026-06-25 round-008 singleton-with-path iteration-6

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-008 `context_bundle.md` and `math_tools_report.md`.
  The existing Diestel Section 3.3 grounding for Menger's theorem remains
  mathematical source evidence only; no project-approved source-admission
  mechanism is available, and no sourced theorem was imported into Lean.

Tool checks:
- Rechecked the local `AmraLibrary` file and bundled mathlib checkout with
  `rg` for Menger/Fan/vertex-cut/min-cut/internal-disjoint path infrastructure.
  No checked finite vertex Menger/Fan theorem was found.
- Ran the required verifier command. It still fails at the same five nonlocal
  proof gaps: the endpoint-pair Menger branch, the frozen fan lemma, the
  outside-prefix disjointness/separation obligations, and the later
  independent-four-vertices wrapper.

Remaining formal blocker:
- The current target
  `exists_singleton_endpoint_separator_of_no_two_internally_disjoint_paths_with_path`
  has the right statement and reduces to the endpoint-pair theorem, but that
  theorem still requires a Lean-checked finite endpoint-pair `k = 2`
  vertex-Menger/min-cut rerouting proof. Local walk packaging alone cannot
  close the branch at line 3537.

## 2026-06-25 round-002 both-hypothesis fan target iteration-1

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-002 `context_bundle.md` and `math_tools_report.md`.
  The prior Diestel Section 3.3 grounding remains mathematical evidence only,
  not a Lean dependency or admission mechanism.

Tool checks:
- Ran a bounded Python finite-graph check for the repaired theorem with
  separate `v-s` and `v-t` singleton-avoidance hypotheses. It checked all
  simple graphs on `n <= 5` and all ordered distinct triples satisfying the
  repaired hypotheses, for 26412 instances total, and found no counterexample.
  This is only route evidence; the required verifier remains Lean.

Lean work:
- Inserted the exact requested declaration
  `finite_two_fan_to_pair_of_both_no_small_endpoint_separator`.
- The proof now closes the easy case where the initially chosen `v-s` path
  avoiding `t` and `v-t` path avoiding `s` meet only at `v`.
- In the hard case, it extracts a non-apex common vertex `x` and uses the two
  separator hypotheses again to obtain a `v-s` path and a `v-t` path avoiding
  `x`. The remaining obligation is precisely the finite two-fan rerouting/min-cut
  step that turns these singleton avoidances into an internally disjoint pair.

Verifier result:
- Ran `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- First error is now target-local:
  `Wowii198aLeftmost.lean:3487:4`: `hvs : v ≠ s` is being used where Lean needs
  `z = v` for the final intersection proof.
- The older frozen errors remain later in the file at the endpoint-pair Menger,
  set-fan, outside-prefix, separation-order, and independent-four wrappers.

Next proof target:
- Prove a Lean-checked finite endpoint-excluding `k = 2` fan/min-cut theorem
  for one source and two terminals under the separate `hsep_vs` and `hsep_vt`
  hypotheses, then replace the target-local hard branch.

## 2026-06-25 round-002 paired side-fan iteration-2

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-002 `context_bundle.md` and `math_tools_report.md`.
  The prior Diestel Section 3.3 grounding remains mathematical evidence only,
  not a Lean dependency.

Tool check:
- Ran an exhaustive Python check over all labelled simple graphs through
  6 vertices and all ordered choices of distinct `v,s,t`. The check encoded the
  repaired paired endpoint-excluding hypothesis for `C = empty` and singleton
  `C`, then searched for simple `v-s` and `v-t` paths whose supports intersect
  only at `v`.
- Result: no counterexample through 6 labelled vertices. At `n = 6`, the script
  checked 3,932,160 ordered triples and found 2,219,520 satisfying the
  hypothesis. This is route evidence only.

Lean work:
- Froze the older non-target endpoint-pair and longest-path route sketches in
  a block comment so the configured verifier now reports only the active target
  blocker.
- Re-ran the required verifier. It now has a single Lean error at
  `Wowii198aLeftmost.lean:3487:4`: `hvs : v != s` is being used where the
  final intersection clause requires `z = v`.

Remaining formal blocker:
- The target hard branch still needs a checked finite endpoint-excluding
  `k = 2` fan/min-cut theorem for one source and two terminals under the
  separate `hsep_vs` and `hsep_vt` hypotheses.

## 2026-06-25 round-002 paired side-fan iteration-4

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-002 `context_bundle.md` and `math_tools_report.md`.
  The prior Diestel Section 3.3 grounding remains mathematical evidence only,
  not a Lean dependency or admission mechanism.

Tool check:
- Ran a plain Python exhaustive check for terminals fixed as `v=0,s=1,t=2`
  over all labelled simple graphs with `3 <= n <= 6`. The script encoded the
  repaired paired endpoint-excluding hypothesis for the empty set and every
  singleton not containing the relevant endpoints, then searched all simple
  paths for a `v-s` and `v-t` pair meeting only at `v`.
- Result: no counterexample through `n = 6`. The counts of graphs satisfying
  the hypotheses were `2, 20, 432, 18496` for `n = 3,4,5,6`,
  respectively. This is route evidence only, not a Lean proof.

Lean work:
- Added the checked helper
  `reachable_delete_singleton_of_no_small_endpoint_separator`, which packages
  the singleton-avoidance consequence of the endpoint-excluding separator
  hypothesis as reachability inside `((⊤ : H.Subgraph).deleteVerts {x}).coe`.
  This is the form needed by a finite fan/min-cut proof over deleted subgraphs.
- Re-ran the required verifier. The helper verifies, and the only active
  target-file error remains the hard branch of
  `finite_two_fan_to_pair_of_both_no_small_endpoint_separator`.

Remaining formal blocker:
- The target theorem still needs a Lean-checked finite endpoint-excluding
  `k = 2` two-terminal fan/min-cut augmentation theorem under the separate
  `hsep_vs` and `hsep_vt` hypotheses. Singleton deleted-subgraph reachability
  is now packaged, but it does not by itself choose the two paths with no other
  common internal vertex.

## 2026-06-25 round-002 paired side-fan iteration-5

External sources relied on:
- None from new web or literature search in this iteration.
- Reread the supplied round-002 `context_bundle.md` and
  `math_tools_report.md`. The prior Diestel Section 3.3 grounding remains
  mathematical evidence only, not an admissible Lean dependency.

Lean work:
- Added the checked helper
  `reachable_pair_delete_singleton_of_two_no_small_endpoint_separators`,
  packaging the two separate endpoint-excluding hypotheses as reachability
  from `v` to each present terminal in the one-vertex-deleted subgraph
  `((⊤ : G.Subgraph).deleteVerts {x}).coe`.
- Threaded this package into the hard branch of
  `finite_two_fan_to_pair_of_both_no_small_endpoint_separator`, so the branch
  now has both replacement paths avoiding the common internal vertex and the
  corresponding deleted-subgraph reachability facts.

Verifier result:
- Ran the required command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- The new helper verifies. The build still fails at the same final hard branch,
  now shifted to `Wowii198aLeftmost.lean:3599:4`, where `hvs : v ≠ s` is still
  the bogus term for the required intersection conclusion `z = v`.

Remaining formal blocker:
- The missing theorem is still the finite endpoint-excluding `k = 2`
  two-terminal fan/min-cut augmentation theorem: from singleton-deleted
  reachability to both terminals, construct `v-s` and `v-t` simple walks whose
  supports intersect only at `v`.

## 2026-06-25 round-002 paired side-fan iteration-7 verifier result

External sources relied on:
- None from new web or literature search in this iteration.
- Reread the supplied round-002 `context_bundle.md` and
  `math_tools_report.md`. Prior Diestel Section 3.3 grounding remains source
  evidence only, not a Lean dependency or admission mechanism.

Tool check:
- Ran a plain Python exhaustive sanity check for the exact repaired side-fan
  statement on all labelled simple graphs with 3 through 6 vertices and all
  ordered triples `(v,s,t)`. Among 2,245,884 triples satisfying the two
  endpoint-excluding empty/singleton reachability hypotheses, no counterexample
  to the internally disjoint `v-s`/`v-t` fan conclusion was found. This is route
  evidence only.

Verifier result:
- Ran the required command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- The build still fails at `Wowii198aLeftmost.lean:3600:6`, where
  `hdelete_vs` has deleted-subgraph reachability type but the proof requires
  the full fan conclusion.

Remaining formal blocker:
- Prove the finite endpoint-excluding `k = 2` one-source/two-terminal
  fan/min-cut augmentation theorem: from singleton-deleted reachability and
  replacement paths avoiding a common internal vertex, construct simple
  `v-s` and `v-t` walks whose supports meet only at `v`.

## 2026-06-26 round-002 terminal-set common-support iteration-2

External sources relied on:
- None from new web or literature search in this iteration.
- Read the supplied round-002 `context_bundle.md` and `math_tools_report.md`.
  The requested run artifact directory was read-only in the sandbox, so this
  workspace note records the source/tool status for durability.

Tool check:
- Ran a cached Python exhaustive sanity check for the exact
  `terminal_set_fan_common_support_reduction_of_hsep` reduction over all
  labelled simple graphs with 3 through 5 vertices and all ordered distinct
  triples `(v,s,t)`. Among 32,988 triples satisfying the terminal-set
  empty/singleton separator hypothesis, no counterexample was found. This is
  route evidence only, not a Lean proof.

Lean work:
- Froze the obsolete singleton replacement route
  `terminal_set_fan_intersection_reduction_from_singleton_path` and its
  augmentation wrapper in a block comment. That route is known too weak because
  a replacement path avoiding the old common vertex can introduce a new
  non-apex intersection.
- Reworked
  `finite_two_fan_to_pair_of_terminal_set_no_small_endpoint_separator` so the
  active verifier error is now the intended theorem-level finite `k = 2`
  fan/min-cut obligation.

Verifier result:
- Ran the required command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- The build fails at `Wowii198aLeftmost.lean:3723:4`: Lean has the terminal-set
  singleton separator hypothesis `hsep`, but the goal is the existential pair
  of simple `v-s` and `v-t` walks meeting only at `v`.

Remaining formal blocker:
- Formalize the finite one-source/two-terminal fan/min-cut descent under
  `hsep`, then the already-present
  `terminal_set_fan_common_support_reduction_of_hsep` wrapper should close by
  reducing the new common-support count to zero.

## 2026-06-26 round-002 terminal-set fan iteration-3

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`. The prior proof-lab grounding in Diestel,
  *Graph Theory*, Section 3.3 "Menger's theorem" remains mathematical source
  evidence only, not an admissible Lean dependency.

Tool check:
- Ran a Python exhaustive sanity check for the exact terminal-set fan statement
  on all labelled simple graphs with 3 through 5 vertices and all ordered
  distinct triples `(v,s,t)`. It checked 12, 576, and 32,400 terminal instances
  satisfying the singleton terminal-set separator hypothesis for sizes 3, 4,
  and 5 respectively, and found no counterexample to the existence of
  internally disjoint `v-s` and `v-t` paths. A 6-vertex extension was stopped as
  too slow and is not used as evidence.

Lean work:
- Added a checked helper
  `common_support_erase_card_eq_zero_of_meet_only_apex`, isolating the final
  cardinal argument used by the target wrapper once an internally disjoint fan
  pair is available.

Verifier result:
- Ran the required command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- The build fails at `Wowii198aLeftmost.lean:3736:4`: Lean has the terminal-set
  singleton separator hypothesis `hsep`, but the goal is the existential pair
  of simple `v-s` and `v-t` walks meeting only at `v`.

Remaining formal blocker:
- The active theorem still requires the finite terminal-set `k = 2` fan/min-cut
  step in `finite_two_fan_to_pair_of_terminal_set_no_small_endpoint_separator`.
  The current proof has endpoint-avoiding `v-s` and `v-t` paths and a
  non-apex common vertex, but still lacks the checked minimal-intersection or
  singleton-separator argument producing a pair meeting only at `v`.

## 2026-06-26 round-002 terminal-set fan iteration-4

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Added `meet_only_apex_of_common_support_erase_card_eq_zero`, the converse
  cardinal helper for turning a zero erased common-support finset into the
  pointwise meet-only-at-apex property.
- Added `terminalPathPairCommonCard` and
  `exists_minimal_terminal_path_pair_common_card`, a checked finite
  minimization wrapper over mathlib's finite `SimpleGraph.Path` type.
- Reworked
  `finite_two_fan_to_pair_of_terminal_set_no_small_endpoint_separator` to pick
  a common-support-minimal terminal path pair first. The zero-cardinality case
  now closes; the remaining branch has a positive non-apex common vertex `x`,
  the minimality hypothesis `hpair_min`, and the singleton-avoiding terminal
  replacement path from `hsep` in scope.

Verifier result:
- Ran the required command:
  `lake env lean AmraLibrary/OpenProblemBatches/VerifiedOpen20260609/Wowii198aLeftmost.lean`.
- The build fails at `Wowii198aLeftmost.lean:3800:4`, where the proof still
  has the terminal-set singleton separator hypothesis `hsep`, but the goal is
  the existential pair of simple `v-s` and `v-t` walks meeting only at `v`.

Remaining formal blocker:
- Formalize the positive-minimum descent/splicing contradiction: from the
  minimal pair, a non-apex common vertex `x`, and the `hsep` path avoiding
  `{x}`, construct a new terminal path pair with strictly smaller
  `terminalPathPairCommonCard`, contradicting `hpair_min`.

## 2026-06-26 round-002 terminal-set fan iteration-6

External sources relied on:
- None from new web or literature search in this iteration.
- Local context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Tool check:
- Ran a plain Python exhaustive check for the exact terminal-set fan statement
  on labelled simple graphs with 3 through 5 vertices and all ordered distinct
  triples `(v,s,t)`. It checked 12, 576, and 32,400 instances satisfying the
  singleton terminal-set separator hypothesis for sizes 3, 4, and 5
  respectively, and found no counterexample to internally disjoint `v-s` and
  `v-t` paths. A larger 7-vertex attempt was interrupted as too slow and is not
  used as evidence.

Lean work:
- Added the checked helper
  `common_support_erase_card_pos_of_common_nonapex`, factoring the final
  positive-cardinality step used by
  `terminal_set_fan_common_support_reduction_of_hsep`.

Remaining formal blocker:
- The build still stops in
  `finite_two_fan_to_pair_of_terminal_set_no_small_endpoint_separator` at the
  positive-minimum branch. The missing proof is the descent/splicing step from
  a common-support-minimal terminal path pair, a non-apex common vertex `x`,
  and a terminal replacement path avoiding `{x}` to a strictly smaller
  `terminalPathPairCommonCard`, contradicting `hpair_min`.

## 2026-06-26 round-002 terminal-set fan iteration-8

External sources relied on:
- None from new web or literature search in this iteration.
- Local source/context files read: the supplied `context_bundle.md`,
  `math_tools_report.md`, local mathlib
  `Mathlib/Combinatorics/SimpleGraph/Connectivity/WalkDecomp.lean`, and local
  mathlib/workspace grep results for Menger/fan/vertex-disjoint path support.

Tool check:
- Ran a bounded Python exhaustive check for labelled simple graphs with
  3 through 5 vertices and all ordered distinct triples `(v,s,t)`. For every
  graph satisfying the exact terminal-set singleton separator hypothesis, the
  script checked both the existence of internally disjoint `v-s`/`v-t` paths
  and the strict common-support reduction for every initially intersecting
  simple path pair. It reported:
  `n 3 ok`, `n 4 ok`, `n 5 ok`, `all ok checked 32988`.
- Started a larger exhaustive run up to 7 vertices, but interrupted it before
  completion as too slow; it is not used as route evidence.

Lean status:
- Rechecked the current Lean blocker near
  `finite_two_fan_to_pair_of_terminal_set_no_small_endpoint_separator`.
  The existing minimal weighted-pair scaffold reaches a positive non-apex
  common vertex and obtains an `hsep` path avoiding that vertex, but the proof
  still needs the finite fan/min-cut rerouting step converting this data into a
  strictly smaller `terminalPathPairCommonCard`.

Remaining formal blocker:
- Formalize the theorem-level finite one-source/two-terminal `k = 2` fan
  descent: from a weighted-minimal terminal path pair, non-apex common `x`, and
  the `hsep` path avoiding `{x}`, splice at first/last intersections so the
  replacement pair has erased common support contained in the old erased common
  support with `x` removed. This should contradict
  `hpair_no_common_decrease` and close
  `terminal_set_fan_common_support_reduction_of_hsep`.

## 2026-06-27 terminal-set two-fan iteration-2

External sources relied on:
- None from new web or literature search.
- Local run context and `math_tools_report.md` were reread. Prior Diestel
  Menger context remains source evidence only, not a Lean theorem.

Lean work:
- Added the checked packaging lemma
  `terminalPathPairCommonCard_eq_zero_of_meet_only_apex`.
- Added the checked first-hit helper
  `exists_first_nonapex_intersection_on_walk`, using mathlib's
  `Walk.exists_mem_support_forall_mem_support_imp_eq`.
- Threaded the first-hit witness into the left and right splice branches, so
  the remaining failure is after selecting an ordered non-apex crossing that is
  distinct from the avoided old common vertex.

Verifier result:
- The configured verifier still fails only at the two weighted-minimality
  splice stubs:
  `terminal_set_fan_splice_descent_left_of_hsep` and
  `terminal_set_fan_splice_descent_right_of_hsep`.

Remaining formal blocker:
- Prove the post-first-hit splice descent: use the ordered crossing and
  `takeUntil`/`dropUntil`/`toPath.support_toPath_subset` to construct a pair
  with smaller erased common support, or derive a strict weighted-measure
  decrease contradicting `hpair_measure_min`.

## 2026-06-27 terminal-set two-fan iteration-3

External sources relied on:
- None from web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, and local mathlib grep results for fan/Menger and
  `Walk.takeUntil`/`dropUntil`/`toPath` support lemmas.

Tool check:
- Ran a bounded Python exhaustive check for labelled simple graphs with
  3 through 5 vertices and all ordered distinct triples `(v,s,t)`. It found no
  counterexample to the exact terminal-set singleton separator hypothesis
  implying internally disjoint `v-s` and `v-t` paths:
  `no counterexample up to n=5`.
- Started the same exhaustive check through 6 vertices, but interrupted it as
  too slow; that interrupted run is not used as evidence.

Lean work:
- In both `terminal_set_fan_splice_descent_left_of_hsep` and
  `terminal_set_fan_splice_descent_right_of_hsep`, replaced the bare
  `exfalso; exact hdirect` stubs by explicit first-crossing spliced candidate
  pairs:
  left branch splices `rs.takeUntil w` with the old right path's
  `dropUntil w`; right branch is the symmetric construction.
- The support-containment facts for these spliced paths now typecheck via
  `mem_support_toPath_append_takeUntil_dropUntil_subset`.

Verifier result:
- The configured verifier still fails, but only at the intended descent
  inequalities for the explicit spliced pairs.

Remaining formal blocker:
- Prove the first-crossing uncrossing inequality:
  `terminalPathPairCommonCard spliced < terminalPathPairCommonCard pair` in the
  left branch, and its right-hand mirror. The available local facts are the
  ordered first-hit property `hfirst`, support containment of the spliced path,
  avoidance of the old common vertex (`hx_rs` / `hx_rt`), and global weighted
  minimality `hpair_measure_min`.

## 2026-06-27 terminal-set two-fan iteration-4

External sources relied on:
- None from web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, and local mathlib/workspace grep results for
  Menger/Fan and walk decomposition APIs.

Lean work:
- Added the checked packaging lemma
  `terminalPathPairCommonCard_lt_of_meet_only_apex_and_common_nonapex`.
- Replaced the repeated direct-branch arithmetic in
  `terminal_set_two_fan_of_no_small_endpoint_separator` with this helper.

Verifier result:
- The configured verifier still fails only at the two explicit first-crossing
  splice inequalities in `terminal_set_fan_splice_descent_left_of_hsep` and
  `terminal_set_fan_splice_descent_right_of_hsep`.

Remaining formal blocker:
- The current splice candidate support containment only gives
  `z ∈ rs.support ∨ z ∈ old_right.support` (and symmetrically on the right).
  To prove strict common-card descent, the next step needs a stronger
  first-hit/uncrossing lemma over the union of the two old supports, or a
  checked finite `k = 2` vertex fan/Menger package, rather than the current
  first-hit-on-opposite-path statement alone.

## 2026-06-27 terminal-set two-fan iteration-5

External sources relied on:
- None from web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, local mathlib grep for Menger/Fan and walk
  decomposition APIs, and the existing workspace formalizer notes.

Lean work:
- Added the checked helper
  `exists_first_nonapex_intersection_on_walk_pair_support`.
  It selects the first non-apex hit of a replacement walk against the union of
  the old left and right supports, packaging the stronger ordering fact needed
  for the next uncrossing attempt.

Verifier result:
- The configured verifier still fails only at the two explicit first-crossing
  splice inequalities in `terminal_set_fan_splice_descent_left_of_hsep` and
  `terminal_set_fan_splice_descent_right_of_hsep`.

Remaining formal blocker:
- Replace the current first-hit-on-opposite-path splice with the new union
  first-hit helper, split on whether the first hit lies on the left or right
  old support, and prove either erased-common-support containment with `x`
  removed or strict weighted-measure descent contradicting
  `hpair_measure_min`.

## 2026-06-27 terminal-set two-fan iteration-6

External sources relied on:
- None from new web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, and the existing workspace notes.

Lean work:
- Added the checked finite-cardinality extraction lemma
  `exists_mem_not_mem_erase_of_not_card_lt`.
- Added checked replacement-intersection packages
  `exists_new_left_replacement_intersection_of_not_commonCard_lt` and
  `exists_new_right_replacement_intersection_of_not_commonCard_lt`. These turn
  the failed direct-descent branch into a genuinely new non-apex intersection:
  for a left replacement, the new witness lies on `rs` and the old right path
  but not on the old left path; the right replacement statement is symmetric.

Verifier result:
- The configured verifier still fails only at the two explicit first-crossing
  splice inequalities in `terminal_set_fan_splice_descent_left_of_hsep` and
  `terminal_set_fan_splice_descent_right_of_hsep`.

Remaining formal blocker:
- Use the new non-old-support witness in the splice branch, then prove the
  ordered first/last crossing uncrossing inequality. The immediate Lean errors
  remain the two `exact hdirect` lines where Lean needs strict common-card
  descent for the spliced pair.

## 2026-06-27 terminal-set fan-splice iteration-2

External sources relied on:
- None from web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, existing workspace formalizer notes, and local
  mathlib grep results for Menger/Fan and `Walk.takeUntil`/`dropUntil` APIs.

Tool check:
- The configured run artifact directory was read-only in this sandbox, so this
  workspace note is the durable record.
- Ran a plain Python exhaustive sanity check for the current left splice
  statement on all labelled simple graphs with 4 through 5 vertices and all
  ordered distinct triples `(v,s,t)`. It found `NO_COUNTER_UP_TO_5`.
- Started a larger random 6-7 vertex search, then interrupted it as too slow;
  that interrupted run is not used as evidence.

Lean work:
- In `terminal_set_fan_splice_descent_left_of_hsep`, used
  `exists_new_left_replacement_intersection_of_not_commonCard_lt` in the
  failed direct-descent branch to obtain a new non-apex intersection on
  `rs ∩ old_right` that is not on the old left path.
- Added the checked union-first-hit package in the same branch via
  `exists_first_nonapex_intersection_on_walk_pair_support`, proving that the
  corresponding replacement prefix avoids the old common vertex `x`.
- Mirrored the same package in
  `terminal_set_fan_splice_descent_right_of_hsep`, with the old supports
  swapped so the new witness lies on the expected side.

Verifier result:
- The configured verifier still fails, but the new union-first-hit facts
  typecheck. The only Lean errors are the two final strict common-card descent
  obligations for the explicit spliced pairs.

Remaining formal blocker:
- Prove the first/last-crossing uncrossing inequality using the new union-prefix
  facts: either show erased common support is contained in the old erased common
  support with `x` removed, or derive equal common card plus strictly smaller
  weighted measure from the splice, contradicting `hpair_measure_min`.

## 2026-06-27 terminal-set fan-left-first-crossing iteration-1

External sources relied on:
- None from web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, local mathlib grep results for
  `Walk.takeUntil`/`dropUntil`, and this workspace formalizer notes file.

Tool check:
- Ran a bounded Python exhaustive sanity check for the proposed left
  first-crossing statement on all labelled simple graphs with 4 and 5 vertices,
  all ordered distinct triples `(v,s,t)`, all simple path pairs, all replacement
  paths `rs`, and all witnesses satisfying the stated first-prefix condition.
  Result: no counterexample up to 5 vertices.
- Also checked a hand-shaped 6-vertex candidate where the old common vertex is
  retained in the right suffix; weighted minimality rejected that candidate.
- A full 6-vertex exhaustive run was started and interrupted as too slow; it is
  not used as evidence.

Lean blocker isolated:
- The current prefix facts are enough to prove that no non-apex vertex from
  `rs.takeUntil w` can be a new common vertex with the old left path: `hfirst`
  plus `hw_not_left` rules out `w`, and all other old-support hits are outside
  the replacement prefix.
- The remaining gap is the suffix case.  For a vertex in the old left support
  and in the spliced right path via `(pair.2 : G.Walk v t).dropUntil w`, Lean
  can only conclude that it was an old common vertex.  To get strict
  common-card descent by erasing `x`, the proof still needs an ordered
  right-suffix fact such as
  `x ∉ ((pair.2 : G.Walk v t).dropUntil w hw_right).support`, or an equivalent
  weighted-measure argument showing that if `x` remains in that suffix then a
  same-common-card but shorter pair contradicts `hpair_measure_min`.

Next formal target:
- Add and prove a right-order/last-crossing package for the left splice, then
  use it to prove
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`.  The parent
  theorem remains `terminal_set_fan_splice_descent_left_of_hsep`, followed by
  the mirrored right splice and the two-fan chain to `conjecture198a`.

## 2026-06-27 terminal-set fan-left-first-crossing iteration-3

External sources relied on:
- None from web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, local mathlib source for
  `Walk.takeUntil`/`dropUntil`/`toPath`, and this workspace notes file.

Tool check:
- Ran a bounded Python exhaustive sanity check for the current left
  first-crossing statement on all labelled simple graphs with 2 through 5
  vertices.  It found no counterexample satisfying weighted minimality and the
  first-prefix hypotheses.  This is route evidence only, not a Lean proof.
- Tested a hand-shaped 7-vertex obstruction candidate where the splice at `w`
  retains `x` in the old right suffix; the candidate was rejected because it
  has a lower common-card path pair, so it does not satisfy weighted
  minimality.
- Started one broader exhaustive run and interrupted it as too slow; that
  interrupted run is not used as evidence.

Lean work:
- Changed the stage declaration to the upstream `private lemma` shape without
  changing its statement.
- Reworked `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` so
  that the strict descent is explicit: from
  `x ∉ (spliceRight : G.Walk v t).support`, Lean now proves the new erased
  common support is contained in the old erased common support with `x`
  removed, and then applies
  `common_support_erase_card_lt_of_subset_erase_common`.

Remaining formal blocker:
- The exact missing Lean fact is now isolated at the stage lemma:
  `x ∉ (spliceRight : G.Walk v t).support`, where
  `spliceRight` is `((rs.takeUntil w hw_rs).append
  ((pair.2 : G.Walk v t).dropUntil w hw_right)).toPath`.
- Existing prefix facts prove only `x ∉ (rs.takeUntil w hw_rs).support`.
  The next proof package must exclude `x` from the old right suffix after
  `w`, or prove that retaining `x` yields an equal-common-card but strictly
  smaller weighted measure contradicting `hpair_measure_min`.

Chain to final theorem:
- Closing this fact proves
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, which plugs
  into `terminal_set_fan_splice_descent_left_of_hsep`; the right splice mirror
  then closes `terminal_set_two_fan_of_no_small_endpoint_separator`, the
  two-fan package, the longest-path missed-vertex contradiction,
  `chvatal_erdos_connected_delete_connected_indepNum_le_three_traceable`, and
  finally `conjecture198a`.

## 2026-06-27 terminal-set fan-left-first-crossing iteration-4

External sources relied on:
- None from new web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, local mathlib/workspace grep results for
  `Walk.takeUntil`/`dropUntil`/`toPath`, and this workspace notes file.

Tool check:
- Ran a hand-shaped Python finite route check for the suspected obstruction
  where the old common vertex `x` is retained in the old right suffix after the
  first crossing `w`.  The candidate satisfied the prefix/first-hit shape, but
  it was rejected as a counterexample because the graph also had a zero-common
  terminal path pair with smaller weighted measure.  This supports the proof
  route that the suffix-retention case must be discharged by constructing a
  different lower-common pair, not by proving the suffix exclusion directly
  from the current first-hit hypothesis.

Lean work:
- Restored the stage declaration header to the discoverable
  `lemma terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` form.
  The previous `private lemma` form made the strict audit report
  `target_declaration_not_found`, even though the source text was present.

Remaining formal blocker:
- The Lean proof still stops at the strict step inside
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`:
  `hx_rs : x ∉ rs.support` only excludes `x` from the replacement walk, while
  Lean needs `x ∉ (spliceRight : G.Walk v t).support`.
- Direct suffix exclusion is not derivable from the current first-hit
  hypothesis alone: if `x` appears after `w` on the old right path, it can
  remain in `(pair.2 : G.Walk v t).dropUntil w hw_right`.  The next proof
  package should handle this suffix-retention branch by constructing an
  alternate lower-common terminal pair, likely using the old-left prefix to
  `x` and old-right suffix from `x`, then proving its intersections with `rs`
  are controlled by a stronger last/first crossing invariant.

## 2026-06-27 terminal-set fan-left-first-crossing iteration-5

External sources relied on:
- None from new web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, local mathlib source/grep results for
  `Walk.takeUntil`/`dropUntil`, and this workspace notes file.

Tool check:
- Ran the configured verifier command. It still fails at the same three Lean
  obligations: the stage theorem needs
  `x ∉ (spliceRight : G.Walk v t).support`, and the left/right parent splice
  branches still contain `hdirect` where a strict common-card inequality is
  required.
- Started an exhaustive Python search over labelled graphs for the exact
  stage hypotheses and interrupted it after 60 seconds as too slow; this
  interrupted run is not used as evidence.
- Ran a randomized small-graph Python search biased toward the stated
  first-crossing/splice configuration on 5 through 7 vertices. It found no
  counterexample satisfying weighted minimality, first-prefix hypotheses, and
  absence of a lower-common terminal pair. This is only route evidence, not a
  Lean proof.

Remaining formal blocker:
- The first blocker is unchanged:
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` requires the
  suffix-retention branch. The existing checked containment proves the spliced
  common support is contained in the old common support, and it proves strict
  descent if `x` is absent from the spliced right path. What remains is to
  handle the case `x ∈ ((pair.2 : G.Walk v t).dropUntil w hw_right).support`.
- A direct proof of suffix absence from `hfirst` and `hx_rs` is still not
  available: `hfirst` controls only the replacement prefix. The next package
  should construct the alternate lower-common pair in the suffix-retention
  case and invoke weighted minimality to rule it out.

Chain to final theorem:
- This stage theorem closes the left first-crossing splice used by
  `terminal_set_fan_splice_descent_left_of_hsep`; after mirroring it for the
  right splice, the chain continues through
  `terminal_set_two_fan_of_no_small_endpoint_separator`, the two-fan package,
  longest-path missed-vertex contradiction,
  `chvatal_erdos_connected_delete_connected_indepNum_le_three_traceable`, and
  finally `conjecture198a`.

## 2026-06-27 terminal-set fan-left-first-crossing iteration-6

External sources relied on:
- None from new web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, local mathlib/workspace grep results for
  `Walk.takeUntil`/`dropUntil`/`toPath`, and this workspace notes file.

Tool check:
- Ran a targeted Python/NetworkX finite check for the exact isolated stage
  shape on connected labelled graphs with 6 vertices. The exhaustive run was
  stopped after 25 seconds after checking 2,947 connected graphs without
  finding a counterexample. This is incomplete route evidence only.
- Rechecked a hand-shaped suffix-retention scenario: it satisfies the
  prefix/first-crossing hypotheses but fails weighted minimality because a
  zero-common terminal pair exists. This again points to the missing proof
  branch being an alternate-pair construction from suffix retention, not a
  direct derivation of suffix absence from `hfirst`.

Remaining formal blocker:
- The first Lean blocker is unchanged:
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` still needs
  a proof of the suffix-retention branch. The current checked path proves
  strict descent from `x ∉ (spliceRight : G.Walk v t).support`, but the
  hypotheses only give `x ∉ rs.support` and prefix avoidance for
  `rs.takeUntil w`.
- The parent left and right splice wrappers still contain stub uses of
  the negated direct-descent hypotheses. They should be closed only after the
  left first-crossing lemma is available and mirrored/specialized with the
  corresponding first/last crossing package.

Chain to final theorem:
- Closing `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`
  proves the left splice core used by
  `terminal_set_fan_splice_descent_left_of_hsep`; the symmetric right splice
  then feeds `terminal_set_two_fan_of_no_small_endpoint_separator`, the
  two-fan package, the longest-path missed-vertex contradiction,
  `chvatal_erdos_connected_delete_connected_indepNum_le_three_traceable`, and
  finally `conjecture198a`.

## 2026-06-27 bad-pivot descent round-001 codex pass

External sources relied on:
- None from web or literature search.
- Local context read: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, local mathlib source/grep results for
  `Walk.takeUntil`/`dropUntil`/`getVert_append`, and this workspace notes file.

Lean work:
- Added `exists_index_of_mem_dropUntil`, a reusable order-support helper:
  if `y` is in `p.dropUntil w`, then `y` occurs in `p` at an index greater
  than or equal to the length of `p.takeUntil w`.  This compiles and packages
  the index bridge needed for simple-path order contradictions in the
  suffix-retention case.

Remaining formal blocker:
- The current first blocker remains
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.  Its two open
  branches still require constructing an order-extremal bad pivot, not simply
  splicing at the arbitrary witness `z`: the left-prefix branch can introduce
  later old-right intersections through `rs.dropUntil z`, and the right-suffix
  branch can introduce earlier old-left intersections through `rs.takeUntil z`.
- Next Lean step: use `exists_index_of_mem_dropUntil` with
  `IsPath.getVert_injOn` to prove the old-right path cannot simultaneously
  have `w ∈ dropUntil x` and `x ∈ dropUntil w` when `w ≠ x`, then use that
  order fact inside the first/last bad-pivot selection.

Chain to final theorem:
- Closing `terminal_set_fan_left_suffix_retention_bad_pivot_descent` feeds
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`, then
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`,
  `terminal_set_fan_splice_descent_left_of_hsep`, the mirrored right splice,
  `terminal_set_two_fan_of_no_small_endpoint_separator`, the two-fan package,
  the longest-path missed-vertex contradiction, Chvatal-Erdos traceability,
  and finally `conjecture198a`.

## 2026-06-27 bad-pivot descent iteration 3

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`.

Lean work:
- Replaced the two raw branch stubs inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` with the intended
  concrete splice candidates: old-left prefix to `z` plus `rs.dropUntil z` in
  the old-left-prefix branch, and `rs.takeUntil z` plus old-right suffix from
  `z` in the old-right-suffix branch.
- Lean checks the splice construction and the local proof that the removed
  common vertex `x` is absent from each spliced path.

Tool check:
- Ran a small Python support-order model for the left-prefix branch. It is not
  a graph counterexample and not proof evidence, but it falsifies the naive
  erased-common containment for an arbitrary bad pivot `z`: with
  `old_left = [v,z,x,s]`, `old_right = [v,w,x,y,t]`, and `rs = [v,w,z,y,s]`,
  all local bad-`z`/first-hit/retention support premises in the current branch
  hold, but the left splice has new erased common vertex `y` while the old
  common support with `x` erased is empty. This supports the proof-lab
  requirement to choose an order-extremal bad pivot or add an explicit
  suffix/prefix control hypothesis.

Remaining formal blocker:
- The first Lean error is now the exact missing containment for the constructed
  left splice: a vertex from `rs.dropUntil z` meeting the old right path must
  be shown to be an old common vertex distinct from `x`. The current theorem
  supplies only an arbitrary bad `z`, so this containment is not derivable by
  the direct splice route without an extremal-pivot package.

## 2026-06-27 left-prefix residual iteration 2

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`; local mathlib source/grep results for
  `Walk.takeUntil`, `dropUntil`, `toPath`, and `bypass` were also consulted.

Tool check:
- Ran a Python exhaustive finite-graph probe for the exact left-prefix
  residual shape, including weighted minimality over all simple `v-s` and
  `v-t` terminal path pairs. The run was interrupted after roughly 90 seconds
  without producing a counterexample, so it is inconclusive and is not used as
  proof evidence.

Lean work:
- Added the requested declaration
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- The already checked `_of_altRight` subcase is now used inside that
  declaration: if the residual `y` is still in the `altRight` path support,
  last-bad extremality forces `y = z`, contradicting `z ∉ pair.2.support`.
- The remaining branch is explicitly isolated at the weighted fallback:
  `y` is an old-right residual from `rs.dropUntil z` but is not known to lie in
  `altRight.support`.

Verifier result:
- The configured verifier still fails. The first error is the weighted
  fallback branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`,
  where Lean needs `False` and the available term is only
  `hpair_measure_min`.
- The two older arbitrary-pivot residual branches in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still fail for
  the same reason.

Next formal blocker:
- Prove the weighted fallback package for the left-prefix residual theorem:
  construct the secondary splice, prove common-card nonincrease via
  `common_support_erase_card_le_of_subset_insert_erase_common`, prove strict
  `terminalPathPairSupportLength` descent, and invoke
  `false_of_weighted_min_and_commonCard_le_supportLength_lt`.

## 2026-06-27 left-prefix weighted fallback iteration 5

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`; local mathlib/workspace grep results for
  `Walk.takeUntil`, `Walk.dropUntil`, `Walk.toPath`, `support_append`, and
  terminal-pair common-card helpers were also consulted.

Tool checks:
- Ran the configured Lean verifier command. It still fails at the two
  weighted-fallback facts inside
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`
  and at the two old arbitrary-pivot residual branches in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Ran a small support-order Python probe for the isolated fallback shape. It
  found the intended nonminimal pattern
  `left = [v, z, x, s]`, `right = [v, w, y, x]`,
  `rs = [v, w, z, y, s]`: the fallback pair lowers the measure, while the
  original pair is not weighted-minimal. This supports the weighted-minimality
  route but is not Lean evidence.
- Ran a randomized minimality-aware finite probe over small path-union graphs.
  It found no candidate satisfying the isolated fallback premises and weighted
  minimality. This is incomplete route evidence only.

Formalization finding:
- The isolated fallback theorem is missing the same extremal control that the
  parent residual theorem has through `hlast_bad`. A direct pointwise proof of
  fallback common-card nonincrease cannot be obtained from the current local
  hypotheses alone: a generic vertex from the `rs.dropUntil y` suffix can still
  lie in `altRight.support`, and without last-bad extremality there is no local
  way to force it to be the selected residual or an old common vertex.
- The next productive target should be to move the weighted fallback back under
  the extremal residual theorem, or strengthen the isolated fallback helper
  with an explicit last-bad/no-later-bad hypothesis. Then the old
  arbitrary-pivot proof should be refactored to call the extremal helper using
  the arbitrary `z` only to build the nonempty bad set.

Chain to final theorem:
- This helper is intended to close the left-prefix residual branch of
  `terminal_set_fan_left_suffix_retention_extremal_bad_pivot_descent`, which
  then feeds `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and finally
  `conjecture198a`.

## 2026-06-28 left-prefix residual iteration 5

External sources relied on:
- None from web or literature in this iteration.
- Local run context was read from the supplied `context_bundle.md` and
  `math_tools_report.md`; local workspace and mathlib grep results for
  `Walk.takeUntil`, `Walk.dropUntil`, `Walk.toPath`, `support_toPath_subset`,
  and the terminal-pair weighted-measure helpers were consulted.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, with immediate
  stage target
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Verifier result:
- The configured verifier was rerun and still fails at exactly the current
  three stale proof terms:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`
  uses `hpair_measure_min` where Lean needs common-card nonincrease and strict
  support-length descent, and the old-right-suffix residual branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` uses
  `hpair_measure_min` where Lean needs `False`.

Formalization finding:
- The support-length descent route in the isolated fallback helper remains
  invalid as a local target. Existing durable probes in this file exhibit
  fallback shapes where common-card drops but total support length increases.
  Therefore the next Lean move should not try to prove
  `terminalPathPairSupportLength fallbackPair <
  terminalPathPairSupportLength pair` from the current isolated hypotheses.
- The plausible certificate is strict common-card descent for a fallback pair,
  or a different weighted-minimality contradiction, proved under the parent
  residual/extremal hypotheses. The isolated helper should be strengthened with
  `hlast_bad` or inlined under
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- The old-right-suffix branch needs the symmetric first-bad residual package;
  merely choosing a last bad pivot does not control vertices in
  `rs.takeUntil z` that meet the old left path.

Chain to final theorem:
- The needed residual helper feeds
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, then
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and finally
  `conjecture198a`.

## 2026-06-28 left-prefix residual iteration 6

External sources relied on:
- None from web or literature in this iteration.
- Local run context was reread from the supplied `context_bundle.md` and
  `math_tools_report.md`; local Lean/mathlib search was used only to inspect
  available `Walk.takeUntil`/`Walk.dropUntil` support-order lemmas and existing
  terminal-pair weighted-measure helpers.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, with immediate
  stage target
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Evaluation:
- The current Lean failures are not coercion or elaboration issues. The terms
  `exact hpair_measure_min` are being used where Lean requires the actual
  ingredients for a weighted-minimality contradiction:
  common-card nonincrease and strict support-length descent for the fallback
  pair, or a direct strict common-card descent.
- The support-length descent subroute for the isolated
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`
  remains demoted. Prior sequence probes in these notes show local branch
  shapes satisfying the residual hypotheses where the prescribed fallback pair
  increases support length.

Next proof package:
- Strengthen or inline the left-prefix fallback under
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`, so it
  can use `hlast_bad` to control later `rs.dropUntil z` vertices meeting
  `altRight`, and prove a valid strict common-card descent or weighted-measure
  descent.
- Add the symmetric first-bad/right-suffix residual package for the branch in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` where the selected
  bad pivot lies in the old-right suffix.

Chain to final theorem:
- These packages feed
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, then
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and finally
  `conjecture198a`.

## 2026-06-28 round 002 iteration 1

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, and local mathlib grep for
  `Walk.toPath`, `Walk.bypass`, `Walk.support_toPath_subset`,
  `takeUntil`, and `dropUntil` support-order lemmas.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Verifier state:
- The configured verifier still fails at the isolated fallback helper
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`.
  The two invalid terms are attempts to use weighted minimality as if it
  directly supplied common-card nonincrease and strict support-length descent
  for `fallbackPair`.
- The third failure remains in the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, where the proof
  needs a symmetric first-bad residual package rather than an arbitrary
  `hpair_measure_min : False` contradiction.

Route decision:
- Do not pursue the standalone support-length descent for the isolated
  fallback helper. The upstream context and prior finite probes show that
  local route is false as stated.
- The next Lean move should inline or strengthen the fallback under
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` so
  it carries `hlast_bad`, then prove a valid common-card or weighted-measure
  descent there. After that, add the symmetric first-bad/right-suffix residual
  helper for the branch currently failing in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Chain to final theorem:
- residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 003 iteration 4

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib declarations for `Walk.toPath`,
  `Walk.support_toPath_subset`, `Walk.takeUntil`, and `Walk.dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`.

Verifier state:
- The configured verifier fails at the two stale proof terms already exposed
  by the previous audit:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  still needs
  `terminalPathPairCommonCard fallbackPair < terminalPathPairCommonCard pair`,
  but the proof body supplies `hpair_measure_min`.
- The old-right-suffix branch inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still needs a
  symmetric first-bad/right-suffix residual contradiction, but the proof body
  supplies `hpair_measure_min : False`.

Route finding:
- The strengthened fallback common-card route still hinges on proving that
  new common support of `fallbackPair` is contained in the old common support
  with `x` erased. The local obstruction is unchanged: Lean has
  `Walk.support_toPath_subset`, so membership in a raw appended walk does not
  by itself give membership in the corresponding `.toPath` support. Any next
  proof package must either establish the specific vertex-preservation fact
  needed for this fallback pair or avoid that route with a direct weighted
  contradiction under the residual/extremal hypotheses.

Next proof package:
- Prove the strict common-card descent for
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  under `hlast_bad`, or replace it by a direct weighted-minimality
  contradiction that does not require a converse for `toPath.support`.
- Then add the symmetric first-bad/right-suffix residual package for the
  old-right-suffix branch in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Chain to final theorem:
- strengthened fallback -> residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 003 iteration 3

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, current Lean file, prior local formalizer notes, and
  local artifact build reports.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`.

Lean work:
- Changed
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  from a private lemma to a normal lemma so the stage target exists under the
  exact requested declaration name for strict audit.

Verifier state:
- The configured verifier still fails at the two proof obligations exposed by
  prior rounds:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  still needs the fallback pair common-card descent, and the old-right-suffix
  branch inside `terminal_set_fan_left_suffix_retention_bad_pivot_descent`
  still needs a symmetric first-bad residual contradiction instead of the stale
  `hpair_measure_min : False` use.

Next proof package:
- Prove the fallback pair facts under `hlast_bad`, preferably common-card
  nonincrease plus strict support-length descent, then invoke
  `false_of_weighted_min_and_commonCard_le_supportLength_lt`.
- Add the symmetric first-bad/right-suffix residual package for the line 5445
  branch.

Chain to final theorem:
- strengthened fallback -> residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 003 iteration 1

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib declarations for `Walk.toPath`, `Walk.bypass`,
  `support_toPath_subset`, `takeUntil`, and `dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`.

Tool check:
- Ran a bounded Python sequence probe for the strengthened fallback target,
  including a small implementation of the mathlib `Walk.bypass` recursion.
  In the small exact-shape cases found by the enumeration, the hypotheses
  including `hlast_bad` held and the fallback pair strictly decreased erased
  common support. No counterexample was found in this bounded probe; it is only
  route evidence, not proof evidence.

Lean work:
- Replaced the old standalone fallback declaration with the requested private
  strengthened target
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`.
- Threaded `hlast_bad` from
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` into
  the strengthened fallback helper.
- Demoted the invalid support-length route: the helper now exposes the real
  missing proof obligation,
  `terminalPathPairCommonCard fallbackPair < terminalPathPairCommonCard pair`,
  and would close by `false_of_weighted_min_and_commonCard_lt`.

Verifier state:
- The configured verifier fails with two remaining stale proof terms:
  the strengthened fallback still needs strict common-card descent for
  `fallbackPair`, and the old-right-suffix branch still needs the symmetric
  first-bad residual contradiction.

Next proof package:
- Prove the strict common-card descent for
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  under `hlast_bad`, then add the symmetric first-bad/right-suffix residual
  package for the branch currently failing inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Chain to final theorem:
- strengthened fallback -> residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 003 iteration 2

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib declarations for `Walk.takeUntil_takeUntil`,
  `Walk.support_takeUntil_subset`, and `Walk.support_toPath_subset`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`.

Lean work:
- Added checked support-order helper
  `mem_takeUntil_of_mem_takeUntil_of_mem_takeUntil`: if a vertex is before
  `y` and `y` is before `x` on the same walk, then that vertex is before `x`.
  This packages the order step needed in the fallback common-card proof when
  comparing the old-right prefix against the old-right suffix.

Verifier state:
- The configured verifier command still fails at the same two theorem-level
  blockers, shifted by the inserted helper:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  still needs a proof that
  `terminalPathPairCommonCard fallbackPair < terminalPathPairCommonCard pair`,
  and the old-right-suffix branch in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still contains the
  stale `hpair_measure_min : False` use.

Route finding:
- The strengthened fallback proof cannot get old-right ordering directly from
  `hy_not_alt`, because mathlib exposes `Walk.support_toPath_subset` but not a
  converse preservation theorem for arbitrary vertices of the raw append.
  The remaining useful local target is therefore a theorem that preserves the
  specific old-right suffix/prefix vertices that survive both relevant
  `.toPath`s, or an equivalent direct common-card descent argument for
  `fallbackPair`.

Chain to final theorem:
- strengthened fallback -> residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 002 iteration 3

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib grep for `Walk.toPath`, `support_toPath_subset`,
  `Walk.takeUntil`, and `Walk.dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Lean work:
- Added the checked support-order helper
  `not_mem_dropUntil_of_mem_takeUntil_ne_on_isPath`: on a simple path, if
  `y ∈ p.takeUntil x` and `y ≠ x`, then `y ∉ p.dropUntil x`.
- This packages the strict prefix/suffix separation needed by the symmetric
  first-bad/right-suffix residual branch.

Verifier state:
- The configured verifier still fails at the three expected theorem-level
  obligations:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_false`
  still tries to use `hpair_measure_min` as common-card nonincrease and strict
  support-length descent, and the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still tries to
  use `hpair_measure_min` as `False`.

Next proof package:
- Strengthen or inline the left-prefix fallback under
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` so it
  carries `hlast_bad`, and prove a valid common-card or weighted-measure
  descent there.
- Then add the symmetric first-bad/right-suffix residual package for the
  branch currently failing inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Chain to final theorem:
- residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 002 iteration 2

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib grep for `Walk.takeUntil`, `Walk.dropUntil`,
  `support_toPath_subset`, and support-order lemmas.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Lean work:
- Added the checked support-order helper
  `mem_dropUntil_of_mem_takeUntil_ne`: if `x` occurs in `p.takeUntil y` and
  `x ≠ y`, then `y ∈ p.dropUntil x`. This packages the order step needed when
  comparing a fallback prefix against an old suffix.
- Reran the configured verifier. The helper introduces no new proof errors.

Verifier state:
- The verifier still fails at the same three stale obligations, shifted by the
  inserted helper: the isolated left-prefix fallback still tries to use
  `hpair_measure_min` as common-card nonincrease and strict support-length
  descent, and the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still tries to
  use `hpair_measure_min` as `False`.

Next proof package:
- Prove the left-prefix fallback contradiction under the residual `hlast_bad`
  hypothesis by strict common-card descent or another valid weighted-measure
  descent; do not use the demoted standalone support-length descent.
- Add the symmetric first-bad/right-suffix residual package for the branch now
  failing at the old-right-suffix splice.

Chain to final theorem:
- residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 002 iteration 4

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib walk-decomposition lemmas for `takeUntil`/`dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Lean work:
- Added checked helper
  `mem_dropUntil_of_mem_dropUntil_of_mem_takeUntil_ne`: on a simple path, if a
  vertex `z` is after `x` and also occurs before `y`, with `z ≠ y`, then `y`
  is after `x`. This packages the order step needed when proving that fallback
  prefix/suffix intersections cannot introduce new common support.

Verifier state:
- The configured verifier still fails at the same three stale theorem-level
  obligations: the isolated left-prefix fallback still uses
  `hpair_measure_min` where Lean needs common-card nonincrease and strict
  support-length descent, and the old-right-suffix branch still uses
  `hpair_measure_min` where Lean needs `False`.

Next proof package:
- Replace the isolated fallback with a residual/extremal common-card descent or
  direct weighted-minimality contradiction using `hlast_bad`.
- Then add the symmetric first-bad/right-suffix residual package for the
  remaining old-right-suffix branch.

Chain to final theorem:
- residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 002 iteration 5

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib walk-decomposition lemmas for `takeUntil`/`dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Lean work:
- Added checked helper
  `not_mem_takeUntil_of_mem_dropUntil_ne_on_isPath`: on a simple path, if a
  non-seam vertex lies in `dropUntil x`, then it cannot also lie in
  `takeUntil x`. This packages the prefix/suffix exclusion needed when the
  fallback-pair common-support proof compares an old-right prefix against an
  old-right suffix.

Verifier state:
- The configured verifier still fails at the same theorem-level obligations:
  the isolated left-prefix fallback still uses `hpair_measure_min` where Lean
  needs common-card nonincrease and strict support-length descent, and the
  old-right-suffix branch still uses `hpair_measure_min` where Lean needs
  `False`.

Next proof package:
- Strengthen or inline the left-prefix fallback under
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` so it
  carries `hlast_bad`, and prove strict common-card descent or another valid
  weighted-minimality contradiction.
- Then add the symmetric first-bad/right-suffix residual package for the
  branch currently failing inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Chain to final theorem:
- residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 003 iteration 5

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local formalizer notes, and
  local mathlib declarations for `Walk.bypass`, `Walk.toPath`,
  `Walk.support_toPath_subset`, and `takeUntil`/`dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`.

Lean work:
- Added the checked symmetric helper
  `terminal_set_fan_left_suffix_retention_right_suffix_residual_bad_false_of_altRight`.
  This packages the first-bad analogue of the existing left-prefix
  `of_altRight` contradiction: a bad vertex in `rs.takeUntil z` that already
  lies in `altRight.support` must equal the first bad pivot `z`, contradicting
  the pivot's absence from the old left path.

Verifier state:
- The configured verifier still fails at the two stale proof terms:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  still needs strict common-card descent for `fallbackPair`, and the
  old-right-suffix branch inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still needs to be
  rewired to a first-bad residual package instead of using
  `hpair_measure_min` as `False`.

Next proof package:
- Prove the fallback-pair strict common-card descent under `hlast_bad`, or
  replace it with a direct weighted-minimality contradiction that avoids a
  converse for `Walk.toPath.support`.
- Then refactor the old-right-suffix branch to select/use the first-bad pivot
  and call the new symmetric `of_altRight` helper plus the remaining
  first-bad fallback case.

Chain to final theorem:
- strengthened fallback -> residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 003 terminal iteration 6

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.toPath`, `Walk.bypass`,
  `Walk.support_toPath_subset`, `Walk.takeUntil`, and `Walk.dropUntil`.

Current first blocker:
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`.

Verifier state before further repair:
- The configured verifier still fails at the two stale proof terms:
  the strengthened fallback has
  `hpair_measure_min` where Lean needs
  `terminalPathPairCommonCard fallbackPair < terminalPathPairCommonCard pair`,
  and the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` has
  `hpair_measure_min` where Lean needs `False`.

Route assessment:
- The local common-card proof for `fallbackPair` still requires a specific
  preservation fact for vertices of a raw append after `.toPath`.  Mathlib only
  exposes the usable direction
  `Walk.support_toPath_subset : (p.toPath : Walk _ _).support ⊆ p.support`.
  The proof cannot infer that an old-right suffix vertex appearing in the raw
  appended walk survives in `altRight.support`.
- The current strengthened fallback signature also does not carry the explicit
  pivot fact `z ∈ altRight.support`, even though the caller obtains it from
  `exists_last_bad_pivot_on_rs`.  The existing `hlast_bad` hypothesis is only
  applicable to later vertices already known to meet `altRight.support`.

Next proof package:
- Move the fallback contradiction fully under
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`, or
  introduce a theorem-level helper with the residual pivot package including
  the explicit `hz_alt` fact and a proved vertex-preservation/weighted-measure
  argument.
- Then refactor the old-right-suffix branch to select the appropriate
  first-bad/right-suffix residual pivot instead of using the global last-bad
  package.

Chain to final theorem:
- strengthened residual fallback ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 004 iteration 2

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.toPath`, `Walk.bypass`,
  `Walk.support_toPath_subset`, `Walk.takeUntil`, and `Walk.dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.
- Immediate stage target:
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.

Verifier state before further repair:
- The configured verifier fails at two stale proof terms:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  still uses weighted minimality where Lean needs strict common-card descent
  for `fallbackPair`, and the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still uses
  weighted minimality where Lean needs a contradiction.

Route assessment:
- The standalone strengthened fallback remains too weak for the desired
  contradiction.  The proof needs the full residual pivot package, especially
  explicit survival in `altRight.support`, before `hlast_bad` can be applied.
- The right-suffix branch is genuinely asymmetric: it needs the first-bad
  prefix package rather than the last-bad suffix package currently threaded
  through the branch.

Next proof package:
- Inline or replace the left-prefix fallback inside
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` with
  a helper that carries explicit `hz_alt : z ∈ altRight.support` and the
  required `.toPath` survival/weighted-measure argument.
- Refactor the old-right-suffix branch to select and use a first-bad
  right-suffix residual package, then call
  `terminal_set_fan_left_suffix_retention_right_suffix_residual_bad_false_of_altRight`
  in the prefix case.

Chain to final theorem:
- residual helper ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` ->
  splice descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

## 2026-06-28 round 004 iteration 3

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.toPath`, `Walk.bypass`, and
  `Walk.support_toPath_subset`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- This is still the entry point into
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and finally
  `conjecture198a`.

Lean work:
- Added checked helper
  `mem_support_toPath_append_takeUntil_dropUntil_cases`, strengthening the
  existing union-support helper for the recurring append shape.  It exposes the
  actual raw `takeUntil`/`dropUntil` side of any vertex that survives
  `.toPath`, using only `Walk.support_toPath_subset`.

Verifier state:
- The configured verifier still fails at two stale proof terms:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  needs
  `terminalPathPairCommonCard fallbackPair < terminalPathPairCommonCard pair`,
  and the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still needs a
  contradiction where it currently tries to use weighted minimality directly.

Route assessment:
- The new support-case helper is useful plumbing, but it does not supply the
  missing converse that a raw append vertex survives the bypassed `.toPath`.
- The next substantive theorem-level move remains to carry the full residual
  pivot package, including explicit `hz_alt : z ∈ altRight.support`, into the
  left-prefix fallback contradiction, and to add the symmetric first-bad
  right-suffix residual package.

## 2026-06-28 round 004 terminal iteration 4

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.support_toPath_subset`,
  `Walk.mem_support_append_iff`, `Walk.support_dropUntil_subset`, and the local
  order lemma `mem_dropUntil_of_mem_takeUntil_ne`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- This remains the entry point into
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Lean work:
- Added checked helper
  `not_mem_left_prefix_fallback_of_not_right_suffix`.  It proves that the old
  common vertex `x` is absent from the fallback left path
  `(oldRight.takeUntil y).append (rs.dropUntil y)` after `.toPath`, provided
  the old-right order fact `y ∉ oldRight.dropUntil x` is available.
- This packages the `x`-erasure part of the fallback common-card descent.  The
  remaining hard step is deriving that order fact, or an equivalent
  `.toPath`-survival contradiction, from `hy_not_alt`.

Verifier state:
- The configured verifier still fails at exactly the two stale proof terms,
  shifted by the inserted helper:
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  needs
  `terminalPathPairCommonCard fallbackPair < terminalPathPairCommonCard pair`,
  and the old-right-suffix branch in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still needs a
  first-bad/right-suffix residual contradiction instead of direct weighted
  minimality.

Next target:
- Prove the missing order/survival step for the left-prefix fallback:
  from `hy_not_alt`, obtain the usable old-right prefix fact
  `y ∉ (pair.2.dropUntil x).support`, or bypass it with a direct
  common-card descent for `fallbackPair`.
- Then refactor the right-suffix branch to select/use the first-bad residual
  package.

## 2026-06-28 round 004 iteration 5

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.toPath`, `Walk.bypass`, and
  `Walk.support_toPath_subset`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- This remains the entry point into
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Tool check:
- Ran a small Python support-sequence probe for the tempting implication
  `hy_not_alt -> y ∉ oldRight.dropUntil x`.  The raw append support
  `[v,a,x,b,a,t]` bypasses to `[v,a,t]`, so `b` lies in the right suffix after
  `x` but does not survive in the bypassed path.  This falsifies the order
  lemma unless an additional no-later-return-to-left-prefix condition is
  carried.

Route assessment:
- The next useful Lean helper should not assert direct survival from right
  suffix membership.  It should instead expose the obstruction: a right-suffix
  vertex absent from `altRight.toPath.support` must be bypassed by a later
  return to the old left prefix.  Under the residual hypotheses, that later
  return is the place where `hlast_bad` can control intersections with
  `rs.dropUntil z`.
- The old-right-suffix branch still needs a separate first-bad package; the
  last-bad suffix package threaded through the current proof cannot rule out
  earlier prefix vertices in `rs.takeUntil z`.

Next target:
- Prove a support-level bypass obstruction helper for
  `((oldLeft.takeUntil x).append (oldRight.dropUntil x)).toPath`: if a
  non-left vertex of `oldRight.dropUntil x` is absent from the resulting path,
  produce a later vertex of `oldRight.dropUntil x` that lies in
  `oldLeft.takeUntil x`.
- Use that obstruction inside the residual fallback, then refactor the
  right-suffix branch to select/use `exists_first_bad_pivot_on_rs`.

## 2026-06-28 round 004 terminal iteration 6

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.bypass`, `Walk.toPath`, and
  `Walk.support_toPath_subset`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`.
- It remains the entry point into
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Lean probe result:
- I locally prototyped the fallback common-support containment for
  `fallbackPair`.
- The branch where the new common vertex lies in `rs.dropUntil y` is
  controllable: combine `hy_drop`, the local
  `mem_dropUntil_of_mem_dropUntil_of_mem_dropUntil` ordering helper, and
  `hlast_bad` to force the vertex to equal the residual pivot, contradicting
  the simple-path order.
- The branch where the new common vertex lies in
  `(pair.2).takeUntil y` and also in the `altRight` old-right suffix remains
  the real obstruction.  Lean reduces it to the missing bypass theorem: an
  old-right suffix vertex that survives `altRight.toPath` while `y` does not
  must force a later return into the old-left prefix, or otherwise be old
  common distinct from `x`.
- I backed the prototype out so the target file remains at the prior smaller
  two-error state.

Verifier state:
- The configured verifier still fails at exactly two stale proof terms:
  the strengthened left-prefix fallback needs
  `terminalPathPairCommonCard fallbackPair < terminalPathPairCommonCard pair`,
  and the old-right-suffix branch inside
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` needs a
  first-bad/right-suffix residual contradiction instead of direct weighted
  minimality.

Next target:
- Prove a theorem-level bypass obstruction for
  `((oldLeft.takeUntil x).append (oldRight.dropUntil x)).toPath` strong enough
  to handle the old-right-prefix/old-right-suffix overlap in the fallback
  common-card descent.
- Then refactor the old-right-suffix branch to select/use
  `exists_first_bad_pivot_on_rs` and the symmetric residual package.

## 2026-06-28 round 002 terminal-set fan left-prefix not-alt descent iteration 1

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior workspace formalizer
  notes, and local mathlib declarations for `Walk.toPath`, `Walk.bypass`, and
  `Walk.support_toPath_subset`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- It closes the `hy_not_alt` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`, then
  feeds `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Lean progress:
- Added the requested target declaration
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- Added and checked the no-right-suffix branch helper
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent_of_not_right_suffix`.
  This constructs the fallback pair and proves strict common-card descent when
  `y ∉ (oldRight.dropUntil x).support`.
- Rewired
  `terminal_set_fan_left_suffix_retention_left_prefix_weighted_fallback_extremal_false`
  through the new target theorem, eliminating the old local
  `hpair_measure_min` temporary proof term in that branch.

Remaining Lean blockers:
- Target suffix branch:
  `hy_suffix : y ∈ ((pair.2 : G.Walk v t).dropUntil x hx_right).support`
  must produce
  `∃ pair', terminalPathPairCommonCard pair' < terminalPathPairCommonCard pair`.
  This is exactly the missing bypass obstruction for
  `((oldLeft.takeUntil x).append (oldRight.dropUntil x)).toPath`.
- Separate old-right-suffix branch in
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still has the
  stale `exact hpair_measure_min`; refactor it through
  `exists_first_bad_pivot_on_rs` and
  `terminal_set_fan_left_suffix_retention_right_suffix_residual_bad_false_of_altRight`.

## 2026-06-28 round 002 terminal-set fan left-prefix not-alt descent iteration 2

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, local mathlib declarations for
  `Walk.bypass`, `Walk.toPath`, `Walk.cons_isPath_iff`, and support append
  lemmas.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- It closes the `hy_not_alt` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`, then
  feeds `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Lean progress:
- Added checked support lemmas:
  `walk_bypass_eq_self_of_isPath`,
  `walk_toPath_eq_self_of_isPath`,
  `mem_support_toPath_of_isPath`,
  `mem_support_toPath_append_right_of_append_isPath`, and
  `not_isPath_append_of_not_mem_toPath_append_right`.
- These package the first formal step of the bypass obstruction: if a suffix
  vertex of an append is erased by `toPath`, the appended walk was not already a
  path, so the next proof step can focus on extracting the cross-repeat between
  `(oldLeft.takeUntil x)` and `(oldRight.dropUntil x)`.

Verifier state:
- The configured verifier still fails at exactly two conceptual proof terms:
  the `hy_suffix` branch in
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  and the stale weighted-minimality term in the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Next target:
- Prove the next Lean obstruction lemma: from
  `¬ (((oldLeft.takeUntil x).append (oldRight.dropUntil x)).IsPath)` with both
  pieces path-like, extract a cross-repeat
  `r ∈ (oldLeft.takeUntil x).support ∩ (oldRight.dropUntil x).support` with
  `r ≠ x`; then turn that cross-repeat into either direct common-card descent or
  the residual contradiction required by the `hy_suffix` branch.
- After that, refactor the old-right-suffix branch through
  `exists_first_bad_pivot_on_rs` and
  `terminal_set_fan_left_suffix_retention_right_suffix_residual_bad_false_of_altRight`.

## 2026-06-28 round 002 terminal-set fan left-prefix not-alt descent iteration 4

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.toPath`, `Walk.bypass`,
  `Walk.support_toPath_subset`, `Walk.isSubwalk_takeUntil`, and
  `Walk.isSubwalk_dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- It closes the `hy_not_alt` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`, then
  feeds `terminal_set_fan_left_suffix_retention_bad_pivot_descent`,
  `terminal_set_fan_left_suffix_retention_alt_intersections_control`,
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt`, the splice
  descent chain, the two-fan theorem, Chvatal-Erdos traceability, and
  `conjecture198a`.

Lean progress:
- Added checked helper
  `exists_left_prefix_right_suffix_tail_of_not_mem_alt`.
- This packages the first formal bypass-obstruction step for the suffix branch:
  from `y ∈ oldRight.dropUntil x` and
  `y ∉ ((oldLeft.takeUntil x).append (oldRight.dropUntil x)).toPath.support`,
  Lean now derives an explicit cross-repeat
  `r ∈ (oldLeft.takeUntil x).support ∩ (oldRight.dropUntil x).support.tail`.
- The proof uses the existing checked route:
  missing suffix vertex from `.toPath` implies the raw append is not a path,
  and non-path append of two simple walks yields a left/right-tail repeat.

Verifier state:
- The configured verifier still fails at exactly two conceptual proof terms:
  the `hy_suffix` branch in
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  and the stale weighted-minimality term in the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Next target:
- Upgrade the checked cross-repeat to the full interval-erasure/later-return
  bypass theorem, or prove a direct common-card descent for the suffix-case
  fallback pair.
- Then refactor the old-right-suffix branch through
  `exists_first_bad_pivot_on_rs` and the symmetric residual package.

## 2026-06-28 round 003 interval-erasure target iteration 1

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.bypass`, `Walk.toPath`,
  `Walk.support_toPath_subset`, `Walk.takeUntil`, and `Walk.dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, via the
  immediate left-prefix not-alt descent helper
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.

Tool check:
- Ran a Python sequence model of mathlib's recursive `Walk.bypass` on simple
  prefix/suffix walks for the requested target
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_interval_erased`.
  The exact interval-erasure conclusion is false.
- Counterexample shape: `leftPrefix = [0,1,2,3]`,
  `rightSuffix = [3,1,5,2]`, raw append support `[0,1,2,3,1,5,2]`,
  and `toPath`/`bypass` support `[0,1,2]`.  With `x = 3` and `y = 5`,
  the hypotheses `y ∈ rightSuffix`, `y ∉ leftPrefix`, and
  `y ∉ toPath.support` hold, and there is a later return `r = 2` to the
  left prefix after `y`.  But the interval-erasure clause fails because
  `1 ∈ rightSuffix.takeUntil y` and `1 ∈ toPath.support`.

Implication:
- The requested declaration should not be inserted as a theorem: it would be a
  false support statement.  A viable replacement target should either erase
  only the subinterval after the last earlier return to the left prefix, or
  state the weaker obstruction actually supported by the check: an absent
  non-left suffix vertex forces a later return into the left prefix.

## 2026-06-28 round 003 interval-erasure target iteration 2

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.bypass`, `Walk.toPath`,
  `Walk.support_toPath_subset`, `Walk.isSubwalk_takeUntil`, and
  `Walk.isSubwalk_dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, via the
  immediate helper
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- The chain remains: left-prefix not-alt descent ->
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

Lean reassessment:
- The requested target
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_interval_erased`
  remains absent from the Lean workspace intentionally: its interval-erasure
  clause is false under the local sequence model recorded in iteration 1.
- The live Lean support already proves the sound weaker extraction
  `exists_left_prefix_right_suffix_tail_of_not_mem_alt`: if a suffix vertex is
  absent from `((left.takeUntil x).append (right.dropUntil x)).toPath.support`,
  then the raw append has a left-prefix/right-suffix-tail cross-repeat.
- This weaker cross-repeat is not yet enough to close the `hy_suffix` branch;
  the missing theorem is an ordered bypass obstruction showing a later return
  after the erased vertex, or a direct common-card descent from such a return.

Verifier state:
- The configured verifier still fails at the same two conceptual proof terms:
  the `hy_suffix` branch in
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  and the stale weighted-minimality term in the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Next target:
- Replace the false interval-erasure target with an ordered bypass theorem:
  from `y ∈ right.dropUntil x`, `y ∉ left.takeUntil x`, and
  `y ∉ ((left.takeUntil x).append (right.dropUntil x)).toPath.support`,
  derive a later right-suffix return
  `r ∈ (right.dropUntil x).dropUntil y` with `r ≠ y` and
  `r ∈ left.takeUntil x`, or directly construct the strict common-card descent
  pair needed by
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.

## 2026-06-28 round 003 interval-erasure target iteration 4

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.bypass`, `Walk.toPath`, and
  `Walk.support_toPath_subset`.

Current first blocker:
- The first blocker on the path to `conjecture198a` remains
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, via the immediate
  helper `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- The requested audit target
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_interval_erased`
  is still intentionally absent: its interval-erasure conjunct is false for
  mathlib's recursive `Walk.bypass`.

Verifier state:
- The configured verifier still fails at exactly two active proof terms:
  the `hy_suffix` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`,
  where the checked cross-repeat extraction is not enough to build a strict
  common-card descent, and the stale `exact hpair_measure_min` in the
  old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent`.

Counterexample to the requested interval-erasure theorem:
- The previous sequence probe remains decisive for the target statement:
  `leftPrefix = [0,1,2,3]`, `rightSuffix = [3,1,5,2]`, raw append support
  `[0,1,2,3,1,5,2]`, and mathlib-style recursive `bypass` support `[0,1,2]`.
  With `x = 3` and `y = 5`, the hypotheses
  `y ∈ rightSuffix`, `y ∉ leftPrefix`, and `y ∉ toPath.support` hold, and
  there is a later return `r = 2` to the left prefix.  However the requested
  clause
  `∀ u ∈ rightSuffix.takeUntil y, u ∉ toPath.support` fails because
  `1 ∈ rightSuffix.takeUntil y` and `1 ∈ toPath.support`.

Next target:
- Do not insert the false interval-erasure declaration.  Replace it with the
  ordered later-return theorem, or with a direct theorem-level descent package
  for the `hy_suffix` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- Separately refactor the old-right-suffix branch through
  `exists_first_bad_pivot_on_rs` and
  `terminal_set_fan_left_suffix_retention_right_suffix_residual_bad_false_of_altRight`.

## 2026-06-28 round 003 interval-erasure target iteration 6

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations around `Walk.bypass`, `Walk.toPath`,
  `Walk.support_toPath_subset`, `Walk.takeUntil`, and `Walk.dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, via the immediate
  helper
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- The chain remains: left-prefix not-alt descent ->
  `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false` ->
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

Lean reassessment:
- The requested declaration
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_interval_erased`
  was not inserted.  Its interval-erasure conjunct is false for mathlib's
  recursive `Walk.bypass`, as recorded by the local sequence model:
  `leftPrefix = [0,1,2,3]`, `rightSuffix = [3,1,5,2]`, raw append support
  `[0,1,2,3,1,5,2]`, and bypass support `[0,1,2]`.  With `x = 3` and `y = 5`,
  the hypotheses of the requested target hold, but the universal interval
  erasure clause fails at `u = 1`.
- Existing checked support only gives
  `exists_left_prefix_right_suffix_tail_of_not_mem_alt`, an unordered
  cross-repeat in the right suffix tail.  The missing sound replacement is the
  ordered later-return theorem, or a direct descent package for the
  `hy_suffix` branch.

Next target:
- Replace the false interval-erasure target with an ordered theorem: from
  `y ∈ right.dropUntil x`, `y ∉ left.takeUntil x`, and
  `y ∉ ((left.takeUntil x).append (right.dropUntil x)).toPath.support`, derive
  a later `r ∈ (right.dropUntil x).dropUntil y`, `r ≠ y`, with
  `r ∈ left.takeUntil x`; then use that theorem to construct the strict
  common-card descent in
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.

## 2026-06-28 round 004 ordered later-return iteration 3

External sources relied on:
- None from web or literature.
- Local sources used: supplied `context_bundle.md`, supplied
  `math_tools_report.md`, the current Lean file, prior formalizer notes, and
  local mathlib declarations for `Walk.bypass`, `Walk.toPath`,
  `Walk.support_toPath_subset`, `Walk.takeUntil`, and `Walk.dropUntil`.

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, through the
  immediate stage theorem
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_later_left_return`
  and its parent
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
- The chain remains: ordered later-return theorem -> left-prefix not-alt
  descent -> `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`
  -> `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

Tool check:
- Ran a Python finite sequence model of mathlib's recursive `Walk.bypass` over
  nodup left-prefix and right-suffix supports with shared start `x`.
- No counterexample was found for the corrected ordered theorem: whenever
  `y ∈ rightSuffix`, `y ∉ leftPrefix`, and `y` is absent from the bypassed
  append support, there was a later `r` in the right suffix from `y` onward
  with `r ∈ leftPrefix` and `r ≠ y`.
- This supports the target theorem shape, but the Lean proof still needs the
  deterministic loop-erasure survival lemma: if no left-prefix vertex occurs in
  the right suffix from `y` onward, then `y` survives
  `((left.takeUntil x).append (right.dropUntil x)).toPath.support`.

Verifier state:
- The configured verifier fails first at the ordered-return target:
  the current proof only extracts the already checked unordered repeat
  `r ∈ (left.takeUntil x).support ∩ (right.dropUntil x).support.tail`; Lean
  still needs the order upgrade
  `r ∈ ((right.dropUntil x).dropUntil y hy_suffix).support`.
- Downstream errors remain blocked by the same missing package: the
  `hy_suffix` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  lacks a strict common-card descent pair, and the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still needs the
  `exists_first_bad_pivot_on_rs` refactor.

Next target:
- Prove the deterministic bypass survival lemma by induction on
  `Walk.bypass`: with `p` and `q` path-like, if
  `y ∈ q.support`, `y ∉ p.support`, and no vertex of `p.support` occurs in
  `(q.dropUntil y hy).support`, then
  `y ∈ ((p.append q).toPath : _).support`.
- Contrapose it to finish
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_later_left_return`,
  then use the produced later return to build the common-card descent in the
  parent not-alt branch.

## 2026-06-28 later-return bypass target, iteration 4

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, via
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
  The chain remains: ordered later-return theorem -> left-prefix not-alt
  descent -> `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`
  -> `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

Lean work:
- Moved the ordered later-return target below the local `dropUntil` order
  lemmas so it can use the existing suffix-order API.
- Added the deterministic-survival proof package:
  `mem_dropUntil_of_mem_bypass_dropUntil`,
  `mem_dropUntil_append_right_of_not_left`, and
  `mem_support_bypass_append_right_of_no_later_left_return`.
- The proof is now blocked at the precise missing nested-suffix transfer:
  from
  `z ∈ ((p.bypass.dropUntil u hs).dropUntil y hy).support`
  and `y ∈ (p.bypass.dropUntil u hs).support`, Lean still needs
  `z ∈ (p.bypass.dropUntil y hy_tail).support`.
  This is the path-specific identity that a drop to a later vertex inside a
  suffix is the same support suffix as dropping directly to that later vertex.

Verifier state:
- The configured verifier fails first at
  `Wowii198aLeftmost.lean:4602:58` on the nested `dropUntil` order-transfer
  argument above.
- Downstream gaps remain ordinary failed proof terms, not trusted
  assumptions: the `hy_suffix` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`
  still returns `hy_suffix`, and the old-right-suffix branch still has the
  stale `hpair_measure_min : False` use.

External sources:
- No web or literature sources were used.  Only the local proof-lab context,
  local math-tools report, local Lean/mathlib files, and the configured Lean
  verifier were used.

Next target:
- Prove a local path-order helper:
  if `hp : p.IsPath`, `hy_after_x : y ∈ (p.dropUntil x hx).support`, and
  `hz_after_y_in_suffix :
    z ∈ ((p.dropUntil x hx).dropUntil y hy_after_x).support`, then
  `z ∈ (p.dropUntil y (Walk.support_dropUntil_subset p hx hy_after_x)).support`.
- Use this helper inside `mem_dropUntil_of_mem_bypass_dropUntil`; then the
  deterministic survival lemma should close
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_later_left_return`.

## 2026-06-28 later-return bypass target, iteration 5

Current first blocker:
- `terminal_set_fan_left_suffix_retention_bad_pivot_descent`, via
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`.
  The chain remains: ordered later-return theorem -> left-prefix not-alt
  descent -> `terminal_set_fan_left_suffix_retention_left_prefix_residual_bad_false`
  -> `terminal_set_fan_left_suffix_retention_bad_pivot_descent` ->
  `terminal_set_fan_left_suffix_retention_alt_intersections_control` ->
  `terminal_set_fan_left_first_crossing_uncrossing_commonCard_lt` -> splice
  descent chain -> two-fan theorem -> Chvatal-Erdos traceability ->
  `conjecture198a`.

Lean work:
- Added `mem_dropUntil_of_mem_nested_dropUntil`, an index-based simple-path
  suffix transport proving that
  `z ∈ ((p.dropUntil x hx).dropUntil y hy_after_x).support` implies
  `z ∈ (p.dropUntil y (Walk.support_dropUntil_subset p hx hy_after_x)).support`.
- Used it in `mem_dropUntil_of_mem_bypass_dropUntil`, replacing the mismatched
  transitivity call on `p.bypass`.
- The configured verifier now compiles through
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_later_left_return`;
  the previous line-4602 nested-suffix error is gone.

Verifier state:
- The configured verifier still fails downstream at
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`:
  the `hy_suffix` branch now reaches the intended later-return/old-common
  obstruction but still needs a strict common-card descent pair.
- The old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` still has the
  stale `hpair_measure_min : False` use and should be refactored through
  `exists_first_bad_pivot_on_rs`.

External sources:
- No web or literature sources were used.  Local sources used: supplied
  `context_bundle.md`, supplied `math_tools_report.md`, the current Lean file,
  prior formalizer notes, local mathlib files, and the configured Lean verifier.

Next target:
- In the `hy_suffix` branch of
  `terminal_set_fan_left_suffix_retention_left_prefix_not_alt_commonCard_descent`,
  use
  `support_toPath_append_takeUntil_dropUntil_absent_right_suffix_later_left_return`
  to construct the actual strict common-card descent pair from the later
  right-suffix return into `oldLeft.takeUntil x`.
- Then refactor the old-right-suffix branch of
  `terminal_set_fan_left_suffix_retention_bad_pivot_descent` through
  `exists_first_bad_pivot_on_rs`.
