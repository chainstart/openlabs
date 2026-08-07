WOWII16 finite check notes, 2026-06-13

The configured run artifact directory was read-only from the Lean workspace
sandbox, so this note records the finite sanity check locally.

Command summary:

- Exhaustively enumerated connected simple graphs on 2 through 7 labelled
  vertices.
- Computed graph radius, diameter, maximum independent neighbourhood size, and
  largest induced bipartite subgraph size by brute force.
- Checked `2 * (radius - 1) + maxL <= b`.

Result:

- No failure was found through 7 vertices.
- The high-radius/small-diameter branch is nonempty at 6 vertices.
- First sample found:
  edges `[(0, 4), (0, 5), (1, 3), (1, 5), (2, 3), (2, 4)]`,
  radius `3`, diameter `3`, maxL `2`, b `6`, left side `6`.
- At 7 vertices, the same check found 7920 high-radius/small-diameter
  examples and no failure.

This is only route evidence. The Lean blocker remains a source-backed proof of
the high-radius/small-diameter branch, or an equivalent construction of the
needed induced bipartite witness from the original graph hypotheses.

Additional fixed-color extension check, 2026-06-13:

- Randomly sampled 18,000 labelled simple graphs on 7 through 12 vertices.
- Among those, 506 connected graphs satisfied `2 < radius` and
  `diameter + 1 < 2 * radius`.
- For each strict-branch graph, checked every vertex whose independent
  neighbourhood number equals the graph maximum and every maximum independent
  neighbourhood set `A` at that vertex.
- Exhaustively searched all 3-state assignments (omit / left / right) with
  `A` forced left to maximize a fixed-color induced bipartite witness.
- No counterexample to `|A| + 2 * (radius - 1)` was found.

This randomized check is route evidence only. It supports the current target
but does not replace the missing Lean construction.

Round 2 checks, 2026-06-13:

- Re-ran an exact NetworkX atlas check over connected graphs through 7 vertices.
- For every strict-branch graph and every maximum independent neighborhood set
  `A` at a vertex attaining the maximum, exhaustively searched fixed-color
  assignments with `A` forced left.
- Checked 33 strict-branch maximum-`A` atlas cases; no counterexample to
  `|A| + 2 * (radius - 1)` was found.
- Added the Lean-verified base fixed-color extension `A` left, `{v}` right.
  This proves the star foothold but does not supply the missing `2r - 2`
  metric count.
- Targeted web search for an existing WOWII16 fixed-color proof did not yield a
  source used in the Lean development; no external source was relied on.

Round 3 exact fixed-color check, 2026-06-13:

- Exhaustively enumerated all connected labelled simple graphs on 2 through 7
  vertices using NetworkX.
- For strict-branch graphs (`2 < radius` and `diameter + 1 < 2 * radius`),
  checked every vertex `v`, every independent neighbour set `A` with
  `|A| = max_l`, and every maximum fixed-colour pair with `A` forced left.
- Counts: strict-branch graphs were 0 through 5 vertices, 60 at 6 vertices,
  and 7920 at 7 vertices; anchored maximum-`A` cases checked were 360 at
  6 vertices and 39060 at 7 vertices.
- No counterexample was found to
  `2 * (radius - 1) <= |(L union R) \\ A|`.

This is finite route evidence only. The Lean proof is now factored so the
remaining mathematical blocker is the radius/diameter padding construction
`fixed_color_blocking_core_metric_padding_exists`.

Round 4 quick padding-pattern probe, 2026-06-13:

- Re-ran a NetworkX atlas probe over the strict branch and searched optimal
  fixed-color assignments with `A` forced left and `v` forced right.
- Checked 33 atlas cases; no counterexample to the padding target was found.
- The first cases include cycle-like radius-3/diameter-3 graphs where the
  optimum fixed-color witness has exactly the target size 6.

Lean formalizer iteration 3 selector probe, 2026-06-27:

- Ran a Python brute-force search for the exact existential selector condition
  in `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector`.
- Enumerated all connected labelled simple graphs on 2 through 7 vertices.
- For strict-branch graphs (`2 < radius` and `not 2 * radius <= diameter + 1`),
  checked every base vertex attaining `maxIndepNeighborsCard`, every maximum
  independent neighbourhood set `A`, all diametral shortest paths, and all
  finite choices of `P0`, `P1`, `Q0`, and `Q1` satisfying the stated
  independence, disjointness, off-path, distance, forbidden-adjacency, fixed
  cardinality, and safe-pool demand clauses.
- Results: no strict-branch graphs through 5 vertices; 60 strict-branch graphs
  and 360 anchored maximum-`A` cases on 6 vertices; 7920 strict-branch graphs
  and 39060 anchored maximum-`A` cases on 7 vertices. No counterexample to the
  existential selector was found.
- This is route evidence only. The Lean blocker remains the general theorem
  constructing a compatible diametral path and disjoint safe pools, likely via
  the blocker-to-augmentation dichotomy described in the proof-lab context.
- This confirms that the existing WOWII13 diameter-window lower bound is too
  weak for the strict branch, even though its independence/disjointness shape is
  the right local model.
- No external web/literature source was used in this round.

Round 4 iteration 2 Lean support note, 2026-06-14:

- Added and prefix-checked
  `geodesic_opposite_parity_path_vertices_disjoint`, a reusable consequence of
  `Walk.IsPath.getVert_injOn`.
- Prefix command:
  `awk 'NR<888{print} END{print "end Wowii16CentralCore20260609"}' ... > /tmp/wowii16_prefix.lean && env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean /tmp/wowii16_prefix.lean`
- Result: passed with no Lean diagnostics.
- The full configured verifier still exits with `std::bad_alloc` before
  printing the expected unknown-identifier diagnostic for the absent
  `fixed_color_blocking_core_metric_padding_core`.
- No external source was used.

Round 5 exact padding-core check, 2026-06-14:

- Exhaustively enumerated connected labelled simple graphs on 1 through 7
  vertices with a direct Python script.
- For every strict-branch graph satisfying `2 < radius` and
  `diameter + 1 < 2 * radius`, checked every vertex `v` and every independent
  neighbourhood set `A` with `|A| = max_l`.
- Exhaustively searched all candidate `P0, P1` for the exact target shape:
  `A union P1` independent, `insert v P0` independent, disjoint, and union
  size at least `|A| + 2 * (radius - 1)`.
- Counts: strict-branch graphs were 0 on 1 through 5 vertices, 60 on 6
  vertices, and 7920 on 7 vertices.
- No counterexample to `fixed_color_blocking_core_metric_padding_core` was
  found through 7 vertices.

This is finite route evidence only. The Lean blocker remains the radius-scale
construction of the padding sets.

Round 5 iteration 2 Lean support note, 2026-06-14:

- Added and prefix-probed two support lemmas in
  `Wowii16CentralCore.lean`:
  `indepNeighborsCard_le_maxIndepNeighborsCard` and
  `exists_radius_geodesic_from`.
- Added the wrapper
  `fixed_color_blocking_core_metric_padding_from_radius_layers`, reducing the
  previous absent-name blocker to a geodesic/radius-layer construction.
- Prefix command isolating the current blocker:
  `awk 'NR<949{print} END{print "end Wowii16CentralCore20260609"}' AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean > /tmp/wowii_prefix_wrapper.lean && env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean /tmp/wowii_prefix_wrapper.lean`
- Prefix result:
  `/tmp/wowii_prefix_wrapper.lean:946:4: error(lean.unknownIdentifier): Unknown identifier fixed_color_blocking_core_metric_padding_from_radius_geodesic`
- The full configured verifier exits with `std::bad_alloc` after the edit, so
  the prefix check is the reliable diagnostic for the next Lean blocker.
- No external web or literature source was used.

Round 6 iteration 2 cycle fixed-color check, 2026-06-14:

- Checked odd cycles `C_7` through `C_17`, the self-centered strict-branch
  examples where a radius geodesic alone is visibly too short for larger
  radius values.
- For every vertex and every maximum independent neighbour set `A`, exhaustively
  searched fixed-color assignments with `A` forced left and `v` forced right.
- Found witnesses of exactly `|A| + 2 * (radius - 1)` vertices in every case
  checked; for `C_(2r+1)` the witness size was `2r`.
- This confirms the current theorem is still plausible, but the construction
  must use more than the vertices of a single deleted-window radius geodesic.
- No external web or literature source was used.

Round 7 iteration 1 Lean note, 2026-06-14:

- Added the target declaration
  `fixed_color_blocking_core_metric_padding_from_radius_geodesic_cardinal_construction`
  to `Wowii16CentralCore.lean`.
- The proof now constructs the Conjecture 13 style deleted-window parity sets
  `P0` and `P1`, and verifies the two fixed-color independent sets plus their
  disjointness.
- Configured verifier result:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  failed at the final cardinal step:
  `hRadiusScale : 2 * (G.radius.toNat - 1) ≤ p.length - 2`.
- This isolates the remaining blocker: the radius-scale padding cannot be
  obtained from the selected single geodesic length lower bound
  `G.radius.toNat ≤ p.length` alone.
- No external web or literature source was used.

Round 7 iteration 2 Lean note, 2026-06-14:

- Rechecked the current blocker in
  `fixed_color_blocking_core_metric_padding_from_radius_geodesic_cardinal_construction`.
- The failing local subgoal
  `2 * (G.radius.toNat - 1) ≤ p.length - 2` is not derivable from
  `G.radius.toNat ≤ p.length`; for example, the numeric shape
  `radius = 3, p.length = 3` satisfies the hypothesis and falsifies the
  subgoal.
- This means the existing single-radius-geodesic deleted-window construction
  can only prove the path-scale bound `A.card + (p.length - 2) ≤ ...`.
  The target cardinality needs an additional radius-scale construction using
  vertices not supplied by this one path, as seen in the odd-cycle sanity
  checks from the previous note.
- A bounded exact Python search for the full fixed-color target was started,
  but it did not complete quickly enough to be useful for this Lean iteration.
- No external web or literature source was used.

Round 5 central-deficit safe-pool Hall bridge, 2026-06-25:

- Added `central_deficit_component_shadow_coloring_from_safe_pool_hall` to
  `Wowii16CentralCore.lean`.
- Used the local Mathlib Hall theorem
  `Fintype.all_card_le_filter_rel_iff_exists_injective` from
  `Mathlib.Combinatorics.Hall.Basic` to convert the safe-pool Hall inequality
  into an injective colored selector on `D`.
- The resulting selector is unfolded directly into `Q0 = Comp.biUnion B0` and
  `Q1 = Comp.biUnion B1`, reusing the same extraction pattern as the verified
  certificate lemma.
- Required verifier:
  `lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed.
- No external web or literature source was used.

Round 2 central-deficit decoupled assigned package audit, 2026-06-27:

- Current first blocker remains
  `central_deficit_decoupled_base_oriented_component_shadow_local_capacity_from_base_parity`.
  The requested lower theorem
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall` is not
  present in the Lean file, and the proof-lab bundle says the full existence
  and safe-capacity package is still a mathematical gap.
- The exact bridge after this blocker is unchanged: use the package to feed
  `central_deficit_component_shadow_coloring_from_component_capacity`, obtain
  `Q0/Q1` of size `2*r - 2 - e`, combine them with the path-side sets
  `A ∪ P1` and `insert b P0`, and then apply
  `conjecture16_source_bound_of_radius_gt_two_of_diam_small_of_max_star_extension`
  followed by `conjecture16_from_radius_gt_two_diam_small_branch`.
- Lean assets currently prove the Hall/capacity bridge, but not the upstream
  existence of a base-compatible diameter path, assigned off-path shadows, and
  safe pools measured from the unrelated max-local base `b`.
- Exact Python probe on the existing `Fin 9` obstruction graph checked the
  target's weakest global-package shape for `b = 5`, `A = {2,6,7}`,
  `radius = 4`, and `diam = 5`. It found a feasible diameter path
  `(4,3,1,2,5,6)` with path-side sets `P0 = {0,1}`, `P1 = {8,3}`, and safe
  candidates `B0 = {0}`, `B1 = {8}`. This does not prove the theorem, but it
  means the known same-base obstruction does not refute this weaker
  existential target.

Lean formalizer iteration 5 off-path refinement audit, 2026-06-27:

- Re-read the stage context and the checked Lean declarations in
  `Wowii16CentralCore.lean`.
- The requested positive declaration
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness` is the
  unrestricted universal refinement over arbitrary already-chosen
  `u w p e D P0 P1`.
- The file already proves
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness_refuted`,
  instantiating the same universal shape on the certified C6 graph with
  `P0 = {1,2}`, `P1 = {3}`, and the bad diametral path. The off-path distance
  thresholds force both `Q0` and `Q1` empty while `D = {2}`.
- Therefore the positive unrestricted theorem cannot be added without
  contradicting the existing Lean C6 certificate. The viable next target is the
  existential selector
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector`, or
  a compatibility-restricted refinement/dichotomy that constructs
  `Q0/Q1` only for a compatible choice of diametral path and fixed-color sides.
- No external web or literature source was used.
- No external web or literature source was used.

Round 2 formalizer reduction note, 2026-06-27:

- Added the proved Lean reduction
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_safe_candidates`.
  It packages the requested existential data from explicit inputs:
  a diameter path, fixed-color sets `P0/P1`, demand set `D`, and off-path safe
  candidate pools `Q0/Q1` with enough colored capacity.  It uses the one-component
  package `Comp = {Q0 ∪ Q1}`, `shadow = D`, `B0 = Q0`, and `B1 = Q1`.
- This closes the Lean bookkeeping part of the assigned-shadow package:
  component off-pathness, component-local capacity, inter-component disjointness,
  same-color independence, distance thresholds from `b`, and forbidden
  adjacencies all reduce to the corresponding explicit `Q0/Q1` hypotheses.
- Bounded Python route check: enumerated all connected six-vertex graphs in the
  hard branch `2 < radius` and `¬ 2*radius ≤ diam + 1`, and for every
  max-local base case searched the reduced package shape
  (fixed-color extension of size `A.card + diam` plus off-path safe colored
  candidates of size `2*radius - 2 - diam`).  Result: no counterexample among
  60 hard graphs and 360 max-base cases.  This is only route evidence, not a
  Lean proof.

Round 2 central-deficit off-path refinement audit, 2026-06-27:

- Re-read the proof-lab context bundle and math tools report for the selected
  stage target
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness`.
- The selected target is not merely absent from the Lean namespace: its
  universal statement over arbitrary fixed-color witness inputs is refuted by
  the already Lean-checked theorem
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness_refuted`.
- The refutation uses `centralDeficitC6Graph`, base `0`, `A = {4,5}`,
  the bad diametral path `[1,3,2,4]`, `P0 = {1,2}`, `P1 = {3}`, and
  `D = {2}`.  All fixed-color hypotheses of the proposed refinement hold, but
  every off-path vertex has distance `< 2` from the base, so both safe pools
  must be empty while `D.card = 1`.
- Therefore the next theorem-level target cannot be this unrestricted
  refinement.  The parent selector still needs either a direct existential
  compatible witness construction or the blocker-to-augmentation dichotomy:
  insufficient disjoint off-path safe capacity for a compatible diametral path
  must force a larger fixed-color extension or an independent neighbourhood
  larger than `A`.
- No external web, literature, or source lookup was used in this audit.
  Lean proof.
- Required verifier:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed with only the existing `simpa` linter suggestions.
- No external web or literature source was used.

Round 3 formalizer support note, 2026-06-27:

- Added the proved Lean support lemma
  `central_deficit_diametral_path_radius_tail_demand`.
  Under the hard branch hypotheses it constructs a diametral path
  `p : G.Walk u w`, sets `e = G.diam`, and proves the central demand interval
  cardinality
  `(Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1)).card =
   2 * G.radius.toNat - 2 - e`.
- Lean probe before editing checked the proof shape using
  `SimpleGraph.exists_dist_eq_diam`, `G.Connected.exists_path_of_dist`,
  `SimpleGraph.radius_le_ediam`, and `Nat.card_Icc`; the arithmetic requires
  the genuine graph fact `G.radius.toNat <= G.diam`, not only the small-diameter
  branch.
- This removes the diametral path and demand-cardinality bookkeeping from the
  requested target.  The remaining first blocker is still the construction of
  fixed-color path-side sets `P0/P1` and off-path safe pools `B0/B1` satisfying
  local component capacity from the unrelated max-local base `b`.
- No external web or literature source was used.

Round 4 formalizer reduction note, 2026-06-27:

- Added the proved Lean reduction
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_diametral_safe_candidates`.
  It first invokes the verified diametral path/demand lemma
  `central_deficit_diametral_path_radius_tail_demand`, then packages explicit
  `P0/P1/Q0/Q1` candidate data through
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_safe_candidates`.
- This isolates the remaining theorem-level blocker to the following candidate
  existence statement for every hard-branch graph and max-local base `b, A`:
  for the constructed diametral path `p` and demand interval `D`, produce
  fixed-color sets `P0/P1` with
  `A.card + G.diam <= ((A union P1) union insert b P0).card`, plus off-path
  independent safe pools `Q0/Q1` with colored capacity at least `D.card`.
- The exact bridge to `conjecture16` is unchanged. Once those candidates are
  supplied, the new reduction gives the requested assigned component package;
  the existing component-capacity bridge gives `Q0/Q1` of size
  `2*r - 2 - e`; combining with the path-side witness yields a bipartite
  witness of size `maxIndepNeighborsCard G + 2*(r - 1)`, which feeds
  `conjecture16_source_bound_of_radius_gt_two_of_diam_small_of_max_star_extension`
  and then `conjecture16_from_radius_gt_two_diam_small_branch`.
- Required verifier:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed with only the existing unnecessary-`simpa` warnings.
- Final scan found no forbidden Lean proof-gap tokens in the target file. The
  exact target declaration
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall` remains
  absent; the next missing theorem is the explicit candidate-existence input
  required by the new reduction.
- No external web or literature source was used.

Round 5 formalizer support note, 2026-06-27:

- Added the named Lean predicate
  `centralDeficitDiametralSafeCandidateData` for the remaining exact
  candidate-existence input: every certified diametral path and central demand
  interval must allow fixed-color path-side sets `P0/P1` and off-path safe
  pools `Q0/Q1` with enough colored capacity.
- Added the proved wrapper
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_candidate_data`,
  showing that this named candidate predicate closes the requested assigned
  component package through the existing diametral-demand and one-component
  safe-candidate reductions.
- Bounded Python route check: used NetworkX graph atlas connected hard-branch
  graphs through seven vertices, and for every max-local base case exhaustively
  searched the reduced package shape with the stronger path-side count
  `A.card + diam` and off-path safe colored capacity
  `2 * radius - 2 - diam`.  Result: no counterexample among six atlas
  hard-branch graphs and 33 max-base cases.  This is route evidence only.
- No external web or literature source was used.

Round 6 final formalizer audit, 2026-06-27:

- Re-read the proof-lab context bundle and math-tools report before editing.
  The first blocker is still
  `central_deficit_decoupled_base_oriented_component_shadow_local_capacity_from_base_parity`.
  In Lean terms this is exactly the missing proof of
  `centralDeficitDiametralSafeCandidateData G b A` under the hard branch
  hypotheses.
- The existing Lean reductions already construct the requested assigned
  component package from explicit candidate data:
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_candidate_data`
  invokes the verified diametral path/demand construction and the
  one-component safe-candidate package.
- I did not add the exact declaration
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall`, because
  doing so honestly would require proving `centralDeficitDiametralSafeCandidateData`.
  Adding the declaration by assuming that predicate, weakening the theorem, or
  reusing the commented radius-geodesic construction would violate the target
  discipline.  The old radius-geodesic route remains mathematically blocked by
  the false arithmetic step
  `2 * (G.radius.toNat - 1) <= p.length - 2` from only
  `G.radius.toNat <= p.length`.
- Required verifier:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed with only the existing unnecessary-`simpa` warnings.
- No external web or literature source was used.

Round 7 C6 obstruction audit note, 2026-06-27:

- Re-read the stage context bundle and math-tools report from the current run
  artifact directory before taking action.  No web or literature search was
  used.
- The Lean stage theorem
  `central_deficit_diametral_safe_candidate_data_c6_obstruction` is present
  with the formal statement requested by the proof-lab decision: a connected
  `Fin 6` graph, base `0`, max independent neighbor set `{4,5}`, radius `3`,
  diameter `3`, hard-branch inequality, and failure of
  `centralDeficitDiametralSafeCandidateData`.
- The companion theorem
  `central_deficit_diametral_safe_candidate_data_universal_refuted` packages
  the universal refutation clearly.  This closes the stage goal as a route
  obstruction, not as progress toward a universal candidate-data theorem.
- The remaining first blocker toward `conjecture16` is conceptual, not local
  Lean syntax: replace the false universal `centralDeficitDiametralSafeCandidateData`
  route with an existential or compatibility-restricted two-base candidate
  package that still feeds
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_candidate_data`
  and then the existing small-diameter branch bridge.
- The strict audit's expected-source header is malformed.  It extracted the
  prose sentence fragment
  `lemma as success unless the report explains exactly how it plugs into the proof of conjecture16`
  instead of the formal theorem block.  This cannot be made into the named Lean
  declaration without weakening, renaming, or replacing the valid stage theorem.

Round 8 C6 obstruction audit note, 2026-06-27:

- Re-read the current run context bundle and math-tools report.  No external
  web, literature, CAS, SMT, or Python source was used in this iteration.
- First blocker toward `conjecture16`: the universal
  `centralDeficitDiametralSafeCandidateData G b A` route remains false; the
  checked C6 package is only an obstruction certificate.  The next mathematical
  route must be an existential or compatibility-restricted two-base candidate
  package feeding
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_candidate_data`.
- Lean-side status: the target declaration
  `central_deficit_diametral_safe_candidate_data_c6_obstruction` is present as
  the proof-lab requested theorem and the required verifier command passes.
- Audit-side status: the current strict audit compares that theorem header
  against the malformed expected declaration
  `lemma as success unless the report explains exactly how it plugs into the proof of conjecture16`.
  A previous `theorem`-to-`lemma` trial still failed the archived after-audit
  because the expected declaration name was parsed as `as`; therefore this is
  not fixable by changing the Lean declaration kind while preserving the target
  theorem.

Round 9 C6 obstruction audit note, 2026-06-27:

- Re-read the current context bundle and math-tools report.  No external web,
  literature, CAS, SMT, or Python source was used.
- Current first blocker between the stage theorem and `conjecture16`: the C6
  theorem certifies that the universal
  `centralDeficitDiametralSafeCandidateData G b A` package is false, so the
  route to `conjecture16` must be repaired by replacing it with an existential
  or compatibility-restricted two-base package that can still feed
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_candidate_data`.
- Lean-side status remains complete for the stage theorem:
  `central_deficit_diametral_safe_candidate_data_c6_obstruction` has the
  proof-lab requested C6 witness statement, and the universal-refutation
  corollary is also present.
- Audit-side blocker remains external to Lean proof construction.  The archived
  audit compares the real target theorem header against the malformed extracted
  header
  `lemma as success unless the report explains exactly how it plugs into the proof of conjecture16`.
  This string is not a valid declaration for the configured target theorem and
  cannot be matched without renaming/weakening/replacing the certified C6
  theorem.

Round 10 existential-disjoint selector note, 2026-06-27:

- Re-read the current selector run `context_bundle.md` and
  `math_tools_report.md` before attempting repairs.  No web or literature
  search was used; relied sources were the supplied local context, local tools
  report, local Lean source, existing local proof notes, and verifier output.
- Current first blocker toward `conjecture16`:
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector` is
  absent.  The existing wrappers
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_of_untagged`
  and
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_of_exists_untagged`
  already package the exact untagged selector witnesses into
  `centralDeficitExistsDiametralSafeCandidateDataDisjoint`.
- The old universal selector route remains formally refuted by the C6 bad
  path; the C6 compatible existential witness is present and checks the
  intended replacement shape on the obstruction graph.  Thus the next Lean
  blocker is not a tagged-cardinality conversion, a C6 audit repair, or a
  wrapper theorem.  It is the graph-theoretic capacity selector: construct one
  compatible diametral path plus `P0 P1 Q0 Q1` with the fixed-side
  independence, off-path safety, untagged `D.card <= (Q0 union Q1).card`, and
  final fixed-side disjointness clauses.
- A core Lean syntax probe confirmed that the prompt's ASCII fragment
  `not P` is Boolean negation syntax in Lean, not proposition negation.  Any
  real Lean theorem must use the existing file style with `¬` and membership
  symbols; the strict route issue remains the missing selector proof, not the
  spelling of this prompt fragment.

Round 11 existential-disjoint selector note, 2026-06-27:

- Re-read the current selector run `context_bundle.md` and
  `math_tools_report.md`.  No web or literature source was used.  Relied
  sources were the supplied local context bundle, local math-tools report,
  local Lean source, existing local proof notes, a Python finite-search probe,
  a throwaway Lean temp-file probe, and the required verifier output.
- Current first blocker toward `conjecture16`: the theorem
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector` is
  still absent.  Its parent wrapper
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_of_exists_untagged`
  is already present and packages exactly the requested witnesses into
  `centralDeficitExistsDiametralSafeCandidateDataDisjoint`, which then feeds
  the safe-Hall/component-capacity chain.
- Finite sanity check: exhaustively searched all connected simple graphs on up
  to 7 vertices satisfying `2 < radius`, `¬ 2 * radius <= diam + 1`, and all
  choices of `b,A` where `A` is an independent neighbor set of `b` with maximum
  `SimpleGraph.maxIndepNeighborsCard` size.  The exact existential selector
  predicate had no counterexample in this range.
- Lean route probe: uncommenting the dormant fixed-color metric-padding block
  in a temp copy fails.  The concrete failed subgoal is the arithmetic claim
  `2 * (G.radius.toNat - 1) <= p.length - 2` from only
  `G.radius.toNat <= p.length`, which is false at `p.length = radius = 3`.
  Thus that block cannot be revived as the selector proof without a new
  argument splitting the `2 * radius - 2` demand between fixed path vertices
  and disjoint off-path safe pools.
- Next useful theorem-level target remains the blocker-to-augmentation
  dichotomy: insufficient disjoint safe capacity for one compatible diametral
  path must force either a larger fixed-color bipartite extension or an
  independent neighborhood larger than `A`.

Round 12 selector equivalence note, 2026-06-27:

- Re-read the current selector run `context_bundle.md`, `math_tools_report.md`,
  local Lean source, and existing proof notes before editing.  No external web
  or literature source was used.
- Added the proved Lean interface
  `central_deficit_untagged_selector_iff_exists_diametral_safe_candidate_data_disjoint`.
  It packages both directions between the target theorem's untagged witness
  conclusion and `centralDeficitExistsDiametralSafeCandidateDataDisjoint`,
  reusing the previously verified tagged-cardinality conversion lemmas.
- Required verifier:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed with only the existing unnecessary-`simpa` linter suggestions.
- Current first blocker toward `conjecture16` is now isolated to the graph
  construction itself: prove the hard-branch disjoint existential package, or
  equivalently the target selector witnesses.  Wrapper, tagged/untagged
  cardinality, diametral path/demand-cardinality, C6 obstruction, and safe-Hall
  packaging are not the remaining issue.

Round 13 selector arithmetic note, 2026-06-27:

- Re-read the current selector run `context_bundle.md`, `math_tools_report.md`,
  local Lean source, imported WOWII13 support source, and existing proof notes.
  No web or literature source was used.
- Random finite probe: sampled connected hard-branch graphs on 8-10 vertices
  and checked the exact untagged selector predicate for maximum independent
  neighbour sets.  The probe found witnesses in 425/425 sampled applicable
  cases and no counterexample.  This remains route evidence only, not part of
  the trusted proof.
- Added checked hard-branch arithmetic support:
  `central_deficit_diam_le_two_radius_sub_two` and
  `central_deficit_deficit_card_le_radius_sub_two`.  These normalize
  `¬ (2 * radius ≤ diam + 1)` into the bound `diam ≤ 2 * radius - 2` and bound
  the deficit cardinality by `radius - 2`.
- Required verifier:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed with only existing unnecessary-`simpa` linter suggestions.
- Current first blocker toward `conjecture16` remains the missing theorem
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector`.
  The concrete mathematical gap is not arithmetic normalization: it is the
  construction of one compatible fixed-color package with
  `A.card + G.diam` vertices together with at least
  `2 * G.radius.toNat - 2 - G.diam` disjoint off-path safe vertices.

Round 14 fixed-color selector half note, 2026-06-27:

- Re-read the current selector run `context_bundle.md`, `math_tools_report.md`,
  local Lean source, and existing proof notes before editing.  No web or
  literature source was used.
- A throwaway Lean syntax probe confirmed that textual `not P` is Boolean
  negation syntax in Lean, not Prop negation; the formal theorem must keep the
  file's `¬ P` spelling for the hard-branch hypothesis.
- Added
  `central_deficit_diametral_fixed_color_witness_of_hard_branch`.
  It combines the existing diametral path/demand theorem with the verified
  fixed-color padding theorem to prove the selector's path/demand clauses and
  all fixed-color clauses through
  `A.card + e <= ((A ∪ P1) ∪ insert b P0).card`.
- Required verifier:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed with only existing unnecessary-`simpa` linter suggestions.
- Current first blocker toward `conjecture16` is now sharper: upgrade the
  fixed-color witness into the exact selector by constructing `Q0/Q1` disjoint
  from the chosen diametral path and fixed-color vertices, with independence,
  distance thresholds, forbidden adjacencies, and
  `D.card <= (Q0 ∪ Q1).card`.

Round 15 off-path refinement obstruction note, 2026-06-27:

- Re-read the current run `context_bundle.md`, `math_tools_report.md`, local
  Lean source, and existing proof notes before editing.  No web or literature
  source was used.
- Added the checked refutation
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness_refuted`.
  It specializes the proposed off-path refinement to the certified C6 graph
  with bad diametral path `[1,3,2,4]`, base `0`, `A = {4,5}`,
  `P0 = {1,2}`, `P1 = {3}`, and `D = {2}`.  The fixed-color hypotheses hold,
  but all vertices outside the path have distance `< 2` from the base, so both
  safe pools are forced empty and cannot cover `D.card = 1`.
- Required verifier:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/Attack1680866_20260608/Wowii16CentralCore.lean`
  passed with only existing unnecessary-`simpa` linter suggestions.
- Current first blocker toward `conjecture16`: the retargeted theorem
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness` is
  false without an additional compatibility condition tying the selected
  diametral path and fixed-color sides to the off-path safe pools.  The next
  proof-lab target should be a compatibility-restricted refinement or the
  blocker-to-augmentation dichotomy.

Round 16 formalizer audit note, 2026-06-27:

- Re-read the current run `context_bundle.md`, `math_tools_report.md`, local
  Lean wrappers, and existing proof notes before making any source-level
  change.  No web or literature source was used.
- The selected stage target
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness`
  remains blocked for a mathematical reason, not a missing local helper: its
  unrestricted statement is exactly the positive universal statement negated by
  the checked theorem
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness_refuted`.
- Adding the positive declaration under that name would contradict the existing
  C6 certificate.  The first viable theorem-level target remains the exact
  existential selector
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector`, or
  a compatibility-restricted safe-pool refinement strong enough to assemble
  that selector via
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_of_exists_untagged`.

Round 17 target audit note, 2026-06-27:

- Re-read the selector context bundle, math tools report, local Lean wrappers,
  C6 obstruction/refutation block, and existing notes before editing.  No web
  or literature source was used.
- Current first blocker between the stage route and `conjecture16`: the
  theorem-level construction of one compatible diametral selector package.
  The parent theorem it closes is
  `centralDeficitExistsDiametralSafeCandidateDataDisjoint`, which then feeds
  `central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_exists_disjoint_candidate_data`,
  component capacity, the max-star bipartite witness bound, the small-diameter
  bridge, and finally `conjecture16`.
- The configured stage target
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness`
  is not a viable positive declaration in its unrestricted form.  The checked
  theorem
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness_refuted`
  gives the C6 specialization with valid fixed-color witness data but empty
  eligible off-path safe pools, so asserting the unrestricted positive theorem
  would conflict with the existing certificate.
- Next viable Lean target: prove the exact existential selector
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector`, or
  first prove a compatibility-restricted refinement/dichotomy that supplies
  `Q0/Q1` only for a compatible choice of path and fixed-color sides.

Round 18 final off-path refinement audit, 2026-06-27:

- Re-read the requested context bundle, AMRA math-tools report, local Lean
  source, C6 obstruction/refutation block, and existing durable notes before
  taking action.  No external web or literature source was used.
- Current first blocker between this stage and `conjecture16`: the selected
  theorem `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness`
  is still absent, but it cannot be added as an unrestricted positive theorem.
  The checked theorem
  `central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness_refuted`
  negates exactly that universal refinement shape.
- The refutation specializes the proposed theorem to the certified C6 graph,
  base `0`, `A = {4,5}`, bad diametral path `[1,3,2,4]`,
  `P0 = {1,2}`, `P1 = {3}`, and `D = {2}`.  The fixed-color premises hold,
  while all off-path vertices have distance `< 2` from the base, forcing
  `Q0 = Q1 = empty` and contradicting `D.card = 1`.
- Therefore the viable next theorem is not this unrestricted refinement, but
  the exact existential compatible selector
  `central_deficit_exists_diametral_safe_candidate_data_disjoint_selector`, or
  a compatibility-restricted safe-pool refinement/dichotomy that constructs
  `Q0/Q1` only for a compatible selected path and fixed-color witness.
