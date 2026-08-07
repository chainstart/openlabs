# Erdos1 half-cube boundary notes

Iteration 2 target:

```lean
theorem setFamilyOuterBoundary_card_ge_central_of_card_half
    (n : ℕ) (𝒜 : Finset (Finset (Fin n)))
    (hn : 0 < n)
    (h𝒜 : 𝒜.card = 2 ^ (n - 1)) :
    Nat.choose n (n / 2) ≤ (setFamilyOuterBoundary 𝒜).card
```

First blocker: the target theorem was absent, and the existing
`setFamilyClosedNeighborhood_card_ge_half_cube_add_central_of_card_half`
wrapper referred to it.

Finite tool check: exhaustive Python search over all half-sized Boolean-cube
families for `n ≤ 4` found minimum outer-boundary sizes `1, 2, 3, 6`, matching
`Nat.choose n (n / 2)`. Two canonical `n = 5` samples also matched `10`.

Local library search:

- mathlib has `Mathlib.Combinatorics.SetFamily.Shadow`,
  `Mathlib.Combinatorics.SetFamily.LYM`, and
  `Mathlib.Combinatorics.SetFamily.KruskalKatona`.
- The available theorem-level APIs cover lower/upper shadows, local LYM,
  Sperner, Kruskal-Katona, and EKR.
- No packaged Harper or Boolean-cube vertex-isoperimetric theorem with an
  arbitrary half-sized family conclusion was found.

Current reduction:

The target declaration is now present with the exact requested header and is
reduced to the missing theorem-level Harper statement
`harper_outer_boundary_card_ge_central_of_card_half`.

Next proof route:

Formalize a Harper vertex-isoperimetric theorem for `Finset (Finset (Fin n))`,
or derive it from a symmetric-chain/compression argument. Once that lemma is
available, the closed-neighborhood wrapper closes by
`setFamilyClosedNeighborhood_card` and `h𝒜`.

Round 2026-06-25 scratch formalizer note:

- Local Mathlib source checked in workspace: `SetFamily.Shadow`, `SetFamily.LYM`,
  `SetFamily.KruskalKatona`, `SetFamily.Compression.Down`,
  `SetFamily.Compression.UV`, `SetFamily.AhlswedeZhang`, and SimpleGraph
  neighbor/bipartite APIs. These provide shadows, LYM, Kruskal-Katona, and
  compression cardinality/shadow monotonicity for uniform layers, but no
  packaged Harper/Boolean-cube vertex-isoperimetric theorem for arbitrary
  half-sized families.
- External provenance still rests on the upstream context's Harper/Raty route:
  Raty, arXiv:1806.11061, for simplicial-order neighborhood minimization. No
  new web source text was consulted in this round.
- Python exhaustive check rerun for `n = 1,2,3,4` over all half-sized Boolean
  cube families found minimum external boundary sizes `1,2,3,6`, matching
  `Nat.choose n (n / 2)`.
- Scratch file progress: added the checked support lemma
  `central_binomial_le_cube_card`, recording the easy ambient-cube upper bound
  `Nat.choose n (n / 2) <= 2 ^ n`. A stronger attempted factoring of the
  exact boundary expression was backed out because the configured Lean process
  crashed with exit code 139 even before producing diagnostics; an `import
  Mathlib` probe showed the crash was not specific to the target theorem.
- The remaining theorem-level gap is still Harper's half-cube
  vertex-isoperimetric inequality for arbitrary `A` with
  `A.card = 2 ^ (n - 1)`.

Round 2026-06-25 iteration-2 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/erdos1-harper-vertex-boundary-scratch-lean/erdos1-harper-vertex-boundary-scratch-lean-2h/lean_formalizer/round-001-boolean-half-family-vertexboundary-card-ge-middle/context_bundle.md`
  and `math_tools_report.md` in the same run directory.
- Local search rerun with `rg` over Mathlib combinatorics/data/order sources
  found no packaged Harper, simplicial-order, or Boolean-cube vertex
  isoperimetric theorem. No new web source text was consulted; the only
  external provenance relied on remains the upstream context's Raty
  arXiv:1806.11061 Harper/simplicial-order route.
- Scratch file progress: introduced `booleanVertexBoundary` and proved the
  disjointness/cardinality bookkeeping
  `boolean_boundary_card_ge_middle_of_closed_neighborhood`. The target theorem
  is now reduced exactly to the missing closed-neighborhood Harper
  specialization
  `2 ^ (n - 1) + Nat.choose n (n / 2) <=
    (A ∪ booleanVertexBoundary n A).card`.
- Required verifier command passed after this edit, still with one unfinished
  proof warning at the Harper input site.

Round 2026-06-25 closed-neighborhood iteration-1 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/erdos1-harper-vertex-boundary-scratch-lean/erdos1-harper-vertex-boundary-scratch-lean-2h/lean_formalizer/round-004-boolean-half-family-closedneighborhood-card-ge-middle/context_bundle.md`
  and `math_tools_report.md` in the same run directory.
- Current first blocker restated: the only remaining Lean gap is the
  theorem-level Harper/Raty closed-neighborhood half-cube inequality
  `boolean_half_family_closedNeighborhood_card_ge_middle`.
- Local Mathlib search rerun over `Combinatorics.SetFamily` and related
  combinatorics/order files found shadows, LYM, Kruskal-Katona, Kleitman, and
  compression APIs, but no packaged Harper/simplicial-order or Boolean-cube
  vertex-isoperimetric theorem that implies the arbitrary half-family closed
  neighborhood bound.
- External search checked for a Lean/Mathlib Harper theorem. No Lean
  formalization was found. The source-level mathematical input remains
  Harper's theorem that Hamming balls minimize closed neighborhoods in the
  Boolean cube; provenance kept attached to Raty, arXiv:1806.11061, and the
  web search result `https://arxiv.org/abs/1808.02572`, whose abstract states
  the same Harper closed-neighborhood minimization form.
- A Python exhaustive probe was started for `n = 1..6`, but the `n = 6`
  search is too large (`choose 64 32`) and was interrupted before producing
  results. No proof-critical conclusion relies on that interrupted probe.

Round 2026-06-25 closed-neighborhood iteration-2 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/erdos1-harper-vertex-boundary-scratch-lean/erdos1-harper-vertex-boundary-scratch-lean-2h/lean_formalizer/round-004-boolean-half-family-closedneighborhood-card-ge-middle/context_bundle.md`
  and `math_tools_report.md` in the same run directory.
- Current first blocker restated: the only remaining Lean gap is still
  the theorem-level Harper/Raty closed-neighborhood half-cube inequality
  `boolean_half_family_closedNeighborhood_card_ge_middle`.
- Python exhaustive check over all half-sized Boolean-cube families for
  `n = 1,2,3,4` found minimum closed-neighborhood sizes `2,4,7,14`, matching
  `2 ^ (n - 1) + Nat.choose n (n / 2)` in each case.
- Local Mathlib search was rerun over `Combinatorics.SetFamily`, compression,
  shadow, Kruskal-Katona, LYM, and SimpleGraph neighborhood APIs. The available
  results still cover shadows, compression cardinal preservation/shadow
  monotonicity, local LYM, and graph neighborhood bookkeeping, but not Harper's
  Boolean-cube closed-neighborhood minimization theorem.
- No new external source text was consulted in this iteration. The external
  provenance relied on remains the previously recorded Raty/Harper route:
  Raty, arXiv:1806.11061, and the prior web note
  `https://arxiv.org/abs/1808.02572`.

Round 2026-06-25 half-initial-segment iteration-1 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/erdos1-harper-vertex-boundary-scratch-lean/erdos1-harper-vertex-boundary-scratch-lean-2h/lean_formalizer/round-007-harper-boolean-half-initialsegment-minimizes-closedneighborhood/context_bundle.md`
  and `math_tools_report.md` in the same run directory.
- Current first blocker restated: the selected stage theorem
  `harper_boolean_half_initialSegment_minimizes_closedNeighborhood` is absent
  from the Lean workspace, while the full proof still requires Harper's
  closed-neighborhood minimization theorem for the Boolean cube.
- Scratch file progress: introduced the checked helper definition
  `booleanHalfInitialSegment`, matching the proof-lab half-initial-segment
  predicate so that later theorem statements can share one model of the
  proposed minimizer.
- No new external source text was consulted in this iteration. The external
  provenance relied on remains the previously recorded Raty/Harper route:
  Raty, arXiv:1806.11061, and the prior web note
  `https://arxiv.org/abs/1808.02572`.

Round 2026-06-25 half-initial-segment iteration-2 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/erdos1-harper-vertex-boundary-scratch-lean/erdos1-harper-vertex-boundary-scratch-lean-2h/lean_formalizer/round-007-harper-boolean-half-initialsegment-minimizes-closedneighborhood/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the selected stage theorem
  `harper_boolean_half_initialSegment_minimizes_closedNeighborhood` is still
  absent from the Lean workspace. Adding it without a proof would reintroduce
  forbidden trusted content, and the proof obligation is exactly Harper's
  Boolean-cube closed-neighborhood minimization theorem.
- Lean probe: appended the intended declaration shape over the existing file
  and tried local `omega`/`simp` normalization. The remaining goal was precisely
  the cardinal inequality comparing the half initial segment's closed
  neighborhood with the arbitrary family's closed neighborhood; no local
  arithmetic or definition unfolding closes it.
- Local Mathlib search again found no theorem named or documented as Harper,
  simplicial-order minimization, Hamming-ball closed-neighborhood
  minimization, or Boolean-cube vertex isoperimetry.
- No new external source text was consulted in this iteration. The external
  provenance relied on remains the previously recorded Raty/Harper route:
  Raty, arXiv:1806.11061, and the prior web note
  `https://arxiv.org/abs/1808.02572`.

Round 2026-06-25 round-008 iteration-1 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/erdos1-harper-vertex-boundary-scratch-lean/erdos1-harper-vertex-boundary-scratch-lean-2h/lean_formalizer/round-008-harper-boolean-halfinitialsegment-minimizes-closedneighborhood/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood` is absent
  from `Erdos1HarperVertexBoundaryScratch.lean`. Adding the declaration with
  an unfinished proof marker or trusted assumption is forbidden by the run
  objective, while the proof obligation is exactly Harper's Boolean-cube
  closed-neighborhood minimization theorem.
- Local Mathlib search was rerun over combinatorics, set-family, finset, and
  order sources. It found the existing shadow, LYM, Kruskal-Katona, and
  compression APIs, but no packaged Harper/simplicial-order/Boolean-cube
  closed-neighborhood minimization theorem that implies the arbitrary
  half-family bound.
- No new external source text was consulted in this iteration. The external
  provenance relied on remains the previously recorded Harper/Raty route:
  Raty, arXiv:1806.11061, and the prior web note
  `https://arxiv.org/abs/1808.02572`.

Round 2026-06-25 round-008 iteration-2 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/erdos1-harper-vertex-boundary-scratch-lean/erdos1-harper-vertex-boundary-scratch-lean-2h/lean_formalizer/round-008-harper-boolean-halfinitialsegment-minimizes-closedneighborhood/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood` remains
  absent from `Erdos1HarperVertexBoundaryScratch.lean`. The exact theorem
  statement compares the closed neighborhood of `booleanHalfInitialSegment`
  with the closed neighborhood of an arbitrary half-sized Boolean-cube family,
  which is precisely Harper's closed-neighborhood minimization theorem.
- Local Mathlib search was rerun over the available set-family, finset, and
  combinatorics sources. It again found shadow, LYM, Kruskal-Katona, and
  compression APIs, but no packaged Harper/simplicial-order/Boolean-cube
  closed-neighborhood minimization theorem.
- No new external source text was consulted in this iteration. The external
  provenance relied on remains the previously recorded Harper/Raty route:
  Raty, arXiv:1806.11061, and the prior web note
  `https://arxiv.org/abs/1808.02572`.

Round 2026-06-26 boolean half-initial-segment card iteration-2 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-003-boolean-halfinitialsegment-closedneighborhood-card/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the target theorem was present, but the final
  parity split failed because `rw [hn_eq] at hn |-` tried to rewrite `n` inside
  terms depending on `hn : 0 < n`, producing a dependent motive type error.
- Lean repair: replaced the modulo split and dependent rewrite with
  `Nat.evenOddRec`, so the even and odd branches have definitional dimensions
  `2 * m` and `2 * m + 1` and can directly use the proved card lemmas.
- Verifier command
  `lake env lean AmraLibrary/OpenProblemBatches/NewCandidates20260612/Erdos1HarperVertexBoundaryScratch.lean`
  passed without diagnostics after expanding the one warning-producing
  `by_cases` proof into explicit branches.
- No new external source text was consulted in this iteration. The external
  provenance remains the previously recorded Harper/Raty route: Raty,
  arXiv:1806.11061, and Przykucki-Roberts, arXiv:1808.02572.

Round 2026-06-26 Harper/Raty source declaration iteration-1 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  absent from `Erdos1HarperVertexBoundaryScratch.lean`. The exact statement is
  Harper's Boolean-cube closed-neighborhood minimization specialized to the
  local `booleanHalfInitialSegment`; adding it without a proof would require a
  trusted assumption, which is forbidden by this run.
- Python exhaustive sanity check over all half-sized Boolean-cube families for
  `n = 1,2,3,4` found minimum closed-neighborhood sizes `2,4,7,14`, matching
  the closed neighborhood of the local half initial segment in each dimension.
  An attempted naive exhaustive run including `n = 5` was interrupted before
  producing output and is not used as evidence.
- Local search over the workspace and installed Mathlib found shadow, LYM,
  Kruskal-Katona, and permutation/Boolean-support transfer tools, but no
  packaged Harper/simplicial-order Boolean-cube closed-neighborhood
  minimization theorem that can close the target declaration.
- External source provenance relied on remains Raty, arXiv:1806.11061, for
  Harper's simplicial-order Boolean-cube neighborhood minimization, and
  Przykucki-Roberts, arXiv:1808.02572, for the closed-neighborhood/Hamming-ball
  formulation used by the transfer package.

Round 2026-06-26 Harper/Raty source declaration iteration-2 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  not present as a Lean declaration. Its statement is exactly Harper's
  Boolean-cube closed-neighborhood minimization for the already formalized
  `booleanHalfInitialSegment`.
- Workspace and Mathlib search was rerun for Harper, simplicial-order,
  vertex-isoperimetric, shadow, compression, Kruskal-Katona, and LYM keywords.
  The available formal material still covers shadows, local LYM,
  Kruskal-Katona, and compression tools, but no packaged theorem directly
  implies the arbitrary half-family closed-neighborhood minimization target.
- External source provenance for this route remains Raty, arXiv:1806.11061,
  and Przykucki-Roberts, arXiv:1808.02572. Web/arXiv page checks in this
  iteration were used only to re-identify those source records; no additional
  mathematical input was taken from a new source.

Round 2026-06-26 Harper/Raty source declaration iteration-3 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  absent. Adding the exact declaration with a completed proof would require
  Harper's Boolean-cube closed-neighborhood minimization for arbitrary
  half-sized families; adding it as trusted content or as an unfinished theorem
  is forbidden by the current audit.
- Local Mathlib inspection was rerun for the relevant set-family API. The
  available `Combinatorics.SetFamily.KruskalKatona`, `Shadow`, and `LYM`
  theorems provide fixed-layer shadow minimization, iterated shadows, local
  LYM, and Sperner-style antichain bounds. They do not provide the non-uniform
  simplicial-order closed-neighborhood minimization theorem needed to compare
  `booleanHalfInitialSegment n hn` against an arbitrary `A` with
  `A.card = 2 ^ (n - 1)`.
- No new mathematical source was used beyond the already recorded external
  provenance: Raty, arXiv:1806.11061, for Harper's simplicial-order
  minimization theorem, and Przykucki-Roberts, arXiv:1808.02572, for the
  closed-neighborhood/Hamming-ball formulation.

Round 2026-06-26 Harper/Raty source declaration iteration-4 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  still absent from the Lean file. The exact requested theorem is the
  arbitrary half-family Boolean-cube closed-neighborhood minimization theorem;
  proving it locally is precisely the missing Harper/Raty source theorem, while
  adding it as trusted content or as an unfinished theorem is forbidden by the
  audit.
- Local search over the workspace and installed Mathlib was rerun for Harper,
  simplicial order, vertex isoperimetry, Hamming balls, Kruskal-Katona, LYM,
  shadows, and compression APIs. The available formal APIs still provide only
  fixed-layer shadow and compression material, not the non-uniform
  closed-neighborhood minimization theorem needed here.
- Python exhaustive sanity check over all half-sized Boolean-cube families for
  `n = 1,2,3,4` found minimum closed-neighborhood sizes `2,4,7,14`, matching
  the local `booleanHalfInitialSegment` closed-neighborhood sizes in those
  dimensions. This is only bounded evidence and is not used as a Lean proof.
- External source pages checked this iteration:
  Raty, `https://arxiv.org/abs/1806.11061`, whose abstract states Harper's
  theorem as minimization of Boolean-cube neighborhoods by simplicial-order
  initial segments; and Przykucki-Roberts,
  `https://arxiv.org/abs/1808.02572`, whose abstract states the closed
  neighborhood/Hamming-ball formulation of Harper's theorem.

Round 2026-06-26 Harper/Raty source declaration iteration-5 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  absent from `Erdos1HarperVertexBoundaryScratch.lean`. Its exact statement is
  the arbitrary half-family Boolean-cube closed-neighborhood minimization
  theorem comparing the local `booleanHalfInitialSegment n hn` to every
  `A : Finset (Finset (Fin n))` with `A.card = 2 ^ (n - 1)`.
- The configured verifier still passes for the scratch file, but only because
  the requested theorem is not declared. Adding the declaration without a proof
  would require forbidden trusted or unfinished proof content.
- Local search over the workspace and installed Mathlib was rerun for Harper,
  vertex isoperimetry, Hamming balls, simplicial initial segments, Kleitman,
  Harris-Kleitman, Kruskal-Katona, LYM, shadows, and compression APIs. The
  search found colex initial segments, fixed-layer shadow minimization,
  Harris-Kleitman correlation, and Kleitman's intersecting-family theorem, but
  no non-uniform Boolean-cube closed-neighborhood minimization theorem that
  implies the target.
- No new external source text was consulted in this iteration. The external
  provenance relied on remains the already recorded Harper/Raty package:
  Raty, arXiv:1806.11061, and Przykucki-Roberts, arXiv:1808.02572.

Round 2026-06-26 Harper/Raty source declaration iteration-6 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  absent. Its proof obligation is still the non-uniform Harper/Raty
  Boolean-cube closed-neighborhood minimization theorem for arbitrary
  half-sized families.
- Lean progress: added and verified
  `booleanHalfInitialSegment_card`, proving that the explicit local
  `booleanHalfInitialSegment n hn` has cardinality `2 ^ (n - 1)`. The proof
  splits odd dimensions into all layers up to the middle and even dimensions
  into lower layers plus the half of the middle layer containing coordinate
  `0`.
- Local search over the workspace and installed Mathlib again found no
  packaged Harper, simplicial-order, Hamming-ball, or Boolean-cube
  vertex-isoperimetric theorem strong enough to prove the target declaration.
- External source records checked for provenance remain Raty,
  `https://arxiv.org/abs/1806.11061`, and Przykucki-Roberts,
  `https://arxiv.org/abs/1808.02572`.

Round 2026-06-26 Harper source declaration iteration-7 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: strict audit fails because
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  not declared in `Erdos1HarperVertexBoundaryScratch.lean`.
- The local file already verifies the half-initial-segment cardinal theorem
  `booleanHalfInitialSegment_card` and the closed-neighborhood count
  `boolean_halfInitialSegment_closedNeighborhood_card`. These support the
  downstream composition but do not prove the arbitrary-family minimization
  statement.
- Local Mathlib search was rerun over set-family shadow, LYM,
  Kruskal-Katona, compression, order partition, and related Boolean-lattice
  files. It found no packaged Harper/simplicial-order/Boolean-cube
  closed-neighborhood minimization theorem and no symmetric-chain
  decomposition API suitable for a short local derivation.
- I did not add the requested theorem with an unfinished proof, trusted
  assumption, or altered definition, because the run forbids unfinished proof
  markers, trusted declarations, and theorem-weakening. The
  remaining Lean obligation is exactly the external Harper/Raty theorem:
  among all half-sized families in the Boolean cube, the simplicial-order half
  initial segment minimizes closed-neighborhood cardinality.
- External provenance relied on remains Raty, arXiv:1806.11061, and
  Przykucki--Roberts, arXiv:1808.02572, as already recorded by proof-lab for
  the Harper/simplicial-order route.

Round 2026-06-26 Harper source declaration iteration-8 note:

- Required upstream files read:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/erdos1-harper-package-prooflab/erdos1-harper-package-prooflab-2h/lean_formalizer/round-005-harper-boolean-halfinitialsegment-minimizes-closedneighborhood-source/context_bundle.md`
  and `math_tools_report.md` in the same round directory.
- Current first blocker restated: the strict audit target
  `harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source` is
  still absent from `Erdos1HarperVertexBoundaryScratch.lean`. The exact
  missing proof is the Harper/Raty Boolean-cube closed-neighborhood
  minimization theorem for arbitrary half-sized families.
- Local Mathlib search was rerun for Harper, vertex isoperimetry, simplicial
  order, Hamming balls, closed neighborhoods, set-family shadows,
  Kruskal-Katona, LYM, compression, Harris-Kleitman, Kleitman, and
  symmetric-chain-style APIs. The search again found only fixed-layer shadow
  and compression tools, plus intersecting-family results, not the required
  non-uniform closed-neighborhood minimization theorem.
- The scratch Lean file already proves the minimizer-side facts
  `booleanHalfInitialSegment_card` and
  `boolean_halfInitialSegment_closedNeighborhood_card`. These are insufficient
  to prove the target without the arbitrary-family minimization input.
- No new external source text was consulted in this iteration. The durable
  provenance remains the proof-lab Harper/Raty package: Raty,
  arXiv:1806.11061, and Przykucki--Roberts, arXiv:1808.02572.
