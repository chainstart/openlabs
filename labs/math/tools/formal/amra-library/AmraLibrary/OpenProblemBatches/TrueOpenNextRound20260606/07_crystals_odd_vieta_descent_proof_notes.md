# 07 Crystals Odd Vieta Notes

2026-06-27 round-003 ab-kZ quotient bridge formalizer iteration 6 notes:

- Current first blocker restated: prove the primitive quotient bridge
  `odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ`,
  i.e. `Y ∣ a*b*kZ`, from the two halved AB modular edges, AB coprimality,
  exact `Z ∣ (Y - 1)^2`, and the `Z` quotient package. This bridge is still
  the needed acyclic input for `Y ∣ AB`; that closes the AB/Z divisibility
  blocker feeding the factor-2 obstruction route toward
  `no_odd_vieta_solution_exists` / `no_odd_vieta_solution`. The final
  integration into `crystals_components_unique` remains unaudited.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: supplied local proof-lab context,
  supplied local AMRA math tools report, local Lean source, local proof notes,
  and local verifier output only; no web or literature source was used.
- Lean edit: rewired
  `odd_cross_halfShift_gap_halved_Y_dvd_AB_of_edges` so that it now derives
  `kZ` via `odd_cross_halfShift_gap_Z_quotient_data`, applies the selected
  quotient bridge to get `Y ∣ a*b*kZ`, converts this to `Y ∣ AB*kZ`, and
  cancels `kZ` with `Nat.Coprime Y kZ`. This removes one downstream
  `False.elim` wrapper from the route, but the primitive quotient bridge
  itself is still unresolved.
- Verifier result:
  `env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/TrueOpenNextRound20260606/07_crystals_odd_vieta_descent.lean`
  still fails at
  `07_crystals_odd_vieta_descent.lean:1679:2: error: linarith failed to find a contradiction`
  inside `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`.
- Next productive target: prove the selected primitive bridge
  `Y ∣ a*b*kZ` directly from the full exact halved AB/Z hypotheses, or replace
  the unfinished terminal `linarith` with an acyclic construction of explicit
  odd-Vieta witnesses. Do not use the normalized/common-`M`, `pre_common_M`,
  later factor-2, or `halfShift_cross_AB_Z_obstruction` wrappers as evidence
  for this step.

2026-06-27 round-003 ab-kZ quotient bridge formalizer iteration 5 notes:

- Current first blocker restated: prove the primitive quotient bridge
  `odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ`,
  i.e. `Y ∣ a*b*kZ`, from the two halved AB modular edges, AB coprimality,
  exact `Z ∣ (Y - 1)^2`, and the `Z` quotient package. This is intended to
  close `Y ∣ AB`, feed the fourth-edge helper and
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`, and then
  support the odd-Vieta contradiction route toward
  `crystals_components_unique`. The direct acyclic bridge from the exposed
  quotient/common-`M` facts to either `Y ∣ a*b*kZ` or explicit odd-Vieta
  witnesses is still missing.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: supplied local proof-lab context,
  supplied local AMRA math tools report, local Lean source, local proof notes,
  local verifier output, a local SymPy/Python expression probe, and a local
  Lean `/tmp` probe only; no web or literature source was used.
- Dependency review: the later valuation-looking declarations
  `odd_cross_halfShift_gap_exact_factor2_valuation_obstruction_core`,
  `odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent`,
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_core`, and
  `odd_cross_halfShift_gap_halved_product_Z_descent_core` are not acyclic
  replacements for the failing core. Following their calls returns through
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_direct`,
  `odd_cross_halfShift_gap_normalized_quotient_descent`,
  `odd_cross_halfShift_gap_normalized_common_M_descent`, and finally back to
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`.
- Tool checks: a small SymPy/Python probe over the obvious candidate
  odd-Vieta variables drawn from `h,u,p,q,p-h,q-u,(p-h)/2,(q-u)/2` found no
  direct polynomial identity of the form
  `R*d^2 + S*e^2 = 2*R*S*d*e + 1`. A `/tmp` Lean probe replacing the terminal
  `linarith` in `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`
  by `nlinarith` still failed in the same context, with the exposed AB
  modular edges, common-`M` divisibilities, `Nat.Coprime Y Z`, and
  `odd_cross_halfShift_gap_Z_quotient_data`.
- Next productive target remains a primitive descent/divisor certificate:
  either prove `Y ∣ a*b*kZ` directly from the full exact halved AB/Z data, or
  construct explicit odd-Vieta witnesses from the same data without calling
  the normalized/common-`M`, `pre_common_M`, later factor-2, or
  `halfShift_cross_AB_Z_obstruction` wrappers.

2026-06-27 round-003 ab-kZ quotient bridge formalizer iteration 4 notes:

- Current first blocker restated: prove
  `odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ`,
  i.e. `Y ∣ a*b*kZ`, from the two halved AB modular edges,
  `Nat.Coprime (Y + a*u) (Y + h*b)`, exact
  `Z ∣ (Y - 1)^2`, and the `Z` quotient package. This quotient bridge
  is meant to give `Y ∣ a*b`, then `Y ∣ (Y+a*u)*(Y+h*b)` via
  `odd_cross_halfShift_gap_Y_dvd_AB_iff_Y_dvd_ab`, closing the parent
  AB/Z blocker before the factor-2 obstruction and the intended
  `no_odd_vieta_solution` route.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: supplied local proof-lab context,
  supplied local AMRA math tools report, local Lean source, local proof
  notes, local verifier output, and a local Python bounded check only; no
  web or literature source was used in this iteration.
- Python bounded check over `1 <= h,u <= 70`, `1 <= a,b < 50` found no
  tuple satisfying the full exact target hypotheses, and therefore no
  counterexample to `Y ∣ a*b*kZ`. The same check again found AB-only and
  Z-only examples where `Y ∤ a*b`, confirming that the primitive proof must
  use both AB modular edges and the exact Z quotient data.
- Lean progress: added checked algebraic bridge
  `odd_cross_halfShift_gap_Y_dvd_AB_mul_Z_quotient_iff_Y_dvd_ab_mul_Z_quotient`,
  proving that `AB + ab = YZ` makes `Y ∣ AB*kZ` equivalent to
  `Y ∣ ab*kZ`. This isolates the remaining primitive content to deriving
  either side from the AB modular/common-`M` facts and the exact Z quotient.
- The dependency audit remains unchanged: downstream normalized/common-`M`,
  `pre_common_M`, later factor-2 wrappers, and `halfShift_cross_AB_Z_obstruction`
  route back through `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`
  and cannot serve as acyclic proofs of the requested quotient bridge.

2026-06-27 round-003 ab-kZ quotient bridge formalizer iteration 3 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and local Python bounded checks only; no web or literature source was used.
- Current first blocker restated: the selected quotient bridge
  `odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ`
  is equivalent to the older `Y ∣ a*b` bridge under the already available
  `Nat.Coprime Y kZ`; this round added two small cancellation helpers naming
  both directions of that equivalence.
- Python bounded check over the abstract crossed variables
  `2 <= Y < A,B < Z < 500`, with
  `(2*A-1)*(2*B-1) = (2*Y-1)*(2*Z-1)`, found no witness satisfying
  `A*B | (A+B-1)^2`, `Z | (Y-1)^2`, and `Nat.Coprime A B`. Removing the
  AB-product divisibility produced many witnesses, so the next proof must
  use the AB product edge together with the Z edge/product identity rather
  than trying a Z-only or coprime-only shortcut. This is route evidence only.
- Verifier remains blocked before the selected target at the terminal
  contradiction in `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`;
  replacing it by any later normalized/common-`M` or factor-2 wrapper would
  preserve the conceptual dependency cycle identified in the prior audits.

2026-06-27 round-003 quotient-multiplied bridge formalizer iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/math_tools_report.md`
- Current first blocker restated: prove the primitive quotient bridge
  `odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ`,
  i.e. `Y ∣ a*b*kZ`, from the two halved AB edges, AB coprimality, exact
  Z quotient data, and `Nat.Coprime Y kZ`, without using the downstream
  normalized/common-`M`, factor-2, or `halfShift_cross_AB_Z_obstruction`
  wrappers.
- Chain to the main target: this bridge gives
  `Y ∣ ((Y+a*u)*(Y+h*b))*kZ` via
  `odd_cross_halfShift_gap_Y_dvd_AB_mul_Z_quotient_of_exact_halved_ABZ`;
  cancellation by `Nat.Coprime Y kZ` gives the older `Y ∣ AB` bridge; that
  feeds the fourth-edge helper and the intended factor-2 AB/Z obstruction on
  the path to `no_odd_vieta_solution_exists` / `no_odd_vieta_solution`, which
  is the arithmetic component behind the staged route to
  `crystals_components_unique`. The acyclic quotient/descent certificate and
  final Formal Conjectures integration remain unaudited.
- External/source material relied on: supplied local proof-lab context,
  supplied local AMRA math tools report, local Lean source, local proof notes,
  local verifier output, and local Python/Lean probes only; no web or
  literature source was used.
- Python bounded check over `1 <= h,u < 120`, `1 <= a,b < 90` found an
  AB-edge/coprime assignment with `Z <= (Y-1)^2`,
  `(a,b,h,u,Y,A,B,Z,(Y-1)^2)=(4,85,1,71,36,320,121,1085,1225)`, so the route
  "AB edges force `Z > (Y-1)^2`" is false. The exact divisibility
  `Z | (Y-1)^2` is still essential.
- Lean probe `/tmp/crystals_probe.lean` replaced the terminal bare `linarith`
  in `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` with
  exposed quotients from `hAB_core`, `hcommon.1`, `hcommon.2`, the AB+ab=YZ
  identity, and `odd_cross_halfShift_gap_Z_quotient_data`. The probe still
  failed at the same core with `linarith failed to find a contradiction`;
  the quotient equations alone do not give a linear/nlinarith contradiction.
- Next productive target remains a genuine acyclic derivation of
  `Y ∣ a*b*kZ` or a direct construction of odd-Vieta witnesses from the full
  halved AB/Z hypotheses.

2026-06-27 round-002 Y-dvd-AB bridge formalizer iteration 6 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: supplied local proof-lab context,
  supplied local AMRA math tools report, local Lean source, local proof notes,
  local verifier output, and a local Python bounded check only. I attempted to
  open the arXiv provenance page but did not use web/literature content for
  this proof step.
- Current first blocker remains
  `odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ`: prove
  `Y ∣ (Y + a*u) * (Y + h*b)` from the two halved AB edges,
  `Nat.Coprime (Y + a*u) (Y + h*b)`, and exact
  `Y + a*u + h*b + 2*a*b ∣ (Y - 1)^2`, without using the downstream
  normalized/common-`M` or strict factor-2 wrappers.
- Chain to final target: this bridge gives `Y ∣ AB`; then the verified
  `odd_cross_halfShift_gap_Y_dvd_AB_iff_Y_dvd_ab` and
  `odd_cross_halfShift_gap_fourth_edge_of_modular_edges_and_Y_dvd_AB` provide
  the missing fourth edge. That is intended to close the factor-2 AB/Z
  obstruction feeding the odd Vieta contradiction
  `no_odd_vieta_solution_exists`, after the half-shift reduction from
  `IsCrystalWithComponents`. The acyclic quotient/cross bridge to explicit
  odd-Vieta witnesses and the final source integration to
  `crystals_components_unique` remain missing.
- Local dependency review: the available later wrappers
  `odd_cross_halfShift_gap_normalized_common_M_descent`,
  `odd_cross_halfShift_gap_normalized_quotient_descent`,
  `odd_cross_halfShift_gap_exact_factor2_pre_common_M_obstruction`,
  strict factor-2 wrappers, and `halfShift_cross_AB_Z_obstruction` all route
  back through `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`.
  They are therefore not acyclic evidence for the current bridge.
- Python bounded check over `1 <= a,b,h,u <= 55` found 62 assignments
  satisfying the two AB modular edges plus `Nat.Coprime A B`, but no
  assignments satisfying the full exact AB/Z hypotheses. The first AB-only
  witness was `(a,b,h,u,Y,A,B,Z) = (1,14,1,3,2,5,16,47)`. This is route
  evidence only; it confirms again that AB/coprime alone is too weak and the
  exact Z edge must be used in the primitive bridge.
- No Lean proof body was changed in this pass because the only local build
  failure is still the bare terminal `linarith` in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`, and replacing
  it with a downstream wrapper would preserve the circular dependency instead
  of proving the requested primitive bridge.

2026-06-27 round-002 Y-dvd-AB bridge formalizer iteration 5 notes:

- Current first blocker restated: prove
  `odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ`, equivalently
  `Y ∣ (Y + a*u) * (Y + h*b)`, from the two halved AB edges, AB
  coprimality, and exact `Z ∣ (Y - 1)^2`, without using downstream
  normalized/common-`M` wrappers or later factor-2 obstruction wrappers.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and local Python/SymPy probes only; no web or literature source was used.
- Python bounded scan over `1 <= h,u < 160`, `1 <= a,b < 100` again found no
  full witness satisfying both halved AB edges, `Nat.Coprime A B`, and exact
  `Z | (Y - 1)^2`. The same scan exhibited AB-only and Z-only examples where
  `Y | A*B` fails, so the primitive bridge still cannot be reduced to either
  side alone.
- SymPy normalization of the common `M = 2*Y*Z - (Y+Z-1)` equations did not
  expose a direct linear contradiction from the quotient package. In
  particular, `M-(Y-1) = 2*Y*Z - 2*Y - Z + 2`, and the resulting `Z`-quotient
  update remains a large expression rather than a simple odd-Vieta equation.
- Lean source audit: the build failure at
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` is still the
  terminal `linarith` after unpacking AB modular edges, common-`M`
  divisibilities, `Nat.Coprime Y Z`, and exact Z quotient data. Replacing it
  with a later obstruction wrapper would preserve the existing dependency
  cycle, because the downstream normalized/common-`M` lemmas route back to this
  core. The next productive target remains a primitive derivation of
  `Y ∣ a*b*kZ`, `Y ∣ (Y+a*u)*(Y+h*b)`, or an explicit odd-Vieta witness.

2026-06-27 round-002 Y-dvd-AB bridge formalizer iteration 4 notes:

- Current first blocker restated: prove
  `odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ`, equivalently
  `Y ∣ (Y + a*u) * (Y + h*b)`, from the two halved AB edges, AB
  coprimality, and exact `Z ∣ (Y - 1)^2`, without using downstream
  normalized/common-`M` wrappers or later factor-2 obstruction wrappers.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and a local Python bounded search only; no web or literature source was used.
- The configured run artifact directory was read-only in this sandbox, so this
  durable note is recorded in the Lean workspace.
- Python bounded scan over `1 <= h,u <= 120`, `1 <= a,b < 80` found no full
  witness satisfying the two halved AB edges, `Nat.Coprime A B`, and exact
  `Z | (Y - 1)^2`. It also found AB-only examples and Z-only examples where
  `Y | A*B` fails, confirming again that neither side of the route is
  separately strong enough. This is route evidence only.
- Lean progress: demoted
  `odd_cross_halfShift_gap_Y_dvd_AB_mul_Z_quotient_of_exact_halved_ABZ` so it
  no longer contains the invalid `linarith` attempt to prove
  `Y | a*b*kZ`; the lemma now records that divisibility as the missing
  hypothesis. This isolates the remaining primitive blocker at
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`.

2026-06-27 round-002 Y-dvd-AB bridge formalizer iteration 3 notes:

- Current first blocker restated: prove
  `odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ`, equivalently
  `Y ∣ (Y + a*u) * (Y + h*b)`, from the two halved AB edges, AB
  coprimality, and exact `Z ∣ (Y - 1)^2`, without using the downstream
  normalized/common-`M` wrappers or later factor-2 obstruction wrappers.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and a local Python congruence probe only; no web or literature source was
  used.
- Local Python probe enumerated the first AB-edge/coprime examples and
  confirmed that `A | (B-1)^2`, `B | (A-1)^2`, and `Nat.Coprime A B` do not
  force `Y ∣ a*b`; examples such as
  `(a,b,h,u,Y,A,B,Z)=(1,46,1,5,3,8,49,146)` have AB edges and coprime AB but
  `a*b ≡ 1 [MOD Y]`. The exact Z edge remains essential.
- Lean progress: added the explicit acyclic intermediate
  `odd_cross_halfShift_gap_Y_dvd_AB_mul_Z_quotient_of_exact_halved_ABZ`.
  It packages the existing reductions so that it is enough to prove
  `Y ∣ a*b*kZ`; together with
  `odd_cross_halfShift_gap_AB_add_ab_eq_YZ`, this gives
  `Y ∣ ((Y + a*u) * (Y + h*b)) * kZ`, and the existing coprime cancellation
  helper then gives the target bridge.
- Configured verifier now fails at this new intermediate:
  `07_crystals_odd_vieta_descent.lean:1586:4`, where `linarith` cannot prove
  the missing subclaim `Y ∣ a*b*kZ` from the AB modular edges, common-`M`
  divisibilities, `AB + ab = YZ`, and the exact Z quotient. Lean also still
  reports the old terminal `linarith` in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` because that
  core has not yet been rewired through a completed primitive bridge.
- Chain to the main theorem remains: proving this quotient intermediate closes
  the primitive `Y ∣ AB` bridge; the bridge feeds the fourth-edge support and
  closes the parent factor-2 AB/Z obstruction toward
  `no_odd_vieta_solution_exists`; that descent component is the arithmetic
  core behind the half-shift reduction from `IsCrystalWithComponents` toward
  `crystals_components_unique`. The final integration into the Formal
  Conjectures source theorem is still unaudited.

2026-06-27 round-002 Y-dvd-AB bridge formalizer iteration 2 notes:

- Current first blocker restated: prove
  `odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ`, i.e.
  `Y ∣ (Y + a*u) * (Y + h*b)` from the two halved AB edges, AB
  coprimality, and exact `Z ∣ (Y - 1)^2`, without routing through
  `normalized_quotient_descent`, `normalized_common_M_descent`,
  `pre_common_M_obstruction`, later factor-2 wrappers, or
  `halfShift_cross_AB_Z_obstruction`.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and a local Python bounded check only; no web or literature source was used.
- Python bounded search over `1 <= h,u < 80`, `1 <= a,b < 60` found no
  assignments satisfying all target bridge hypotheses
  `A | (B-1)^2`, `B | (A-1)^2`, `Nat.Coprime A B`, and
  `Z | (Y-1)^2`; consequently it also found no counterexample to the
  proposed intermediate `Y ∣ A*B*kZ`, where
  `kZ = (Y-1)^2 / Z`. This is route evidence only.
- Source audit: the failed `linarith` in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` is not a
  local arithmetic-tactic issue. The parent obstruction needs either the
  primitive bridge `Y ∣ A*B`, which then feeds the existing fourth-edge helper,
  or an acyclic direct descent certificate. The later wrappers still route
  back through this same core and are not valid upstream closures.

2026-06-27 round-002 Y-dvd-AB bridge formalizer iteration 1 notes:

- Current first blocker restated: prove
  `odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ`, i.e.
  `Y ∣ (Y + a*u) * (Y + h*b)` from the two halved AB edges, AB
  coprimality, and exact `Z ∣ (Y - 1)^2`, without routing through
  `normalized_quotient_descent`, `normalized_common_M_descent`,
  `pre_common_M_obstruction`, later factor-2 wrappers, or
  `halfShift_cross_AB_Z_obstruction`.
- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and local Python bounded checks only; no web or literature source was used.
- The configured run artifact directory was read-only in this sandbox, so this
  durable note is recorded in the Lean workspace instead.
- Python bounded search over `1 <= a,b,h,u <= 80` found no assignments
  satisfying all target bridge hypotheses
  `A | (B-1)^2`, `B | (A-1)^2`, `Nat.Coprime A B`, and
  `Z | (Y-1)^2` for `Y=(h*u+1)/2`, `A=Y+a*u`, `B=Y+h*b`,
  `Z=Y+a*u+h*b+2*a*b`. This did not falsify the target.
- Python check of the Z edge alone found a counterexample to the naive
  route "`Z | (Y-1)^2` implies `Y | a*b`":
  `(a,b,h,u,Y,Z,kZ) = (1,2,1,17,9,32,2)`, with `Nat.Coprime Y kZ`.
  Therefore the AB modular/coprime hypotheses are essential.
- Lean progress: added verified helper
  `odd_cross_halfShift_gap_Y_dvd_AB_of_Y_dvd_AB_mul_Z_quotient`. It packages
  the quotient-cancellation reduction: because
  `odd_cross_halfShift_gap_Z_quotient_data` gives `Nat.Coprime Y kZ`, it is
  enough to prove `Y ∣ ((Y + a*u) * (Y + h*b)) * kZ`.
- Configured verifier still fails at the same primitive obstruction, now
  shifted to `07_crystals_odd_vieta_descent.lean:1609:2`, where
  `linarith` is asked to prove `False` from the AB edges, common-`M`
  divisibilities, and the Z quotient data. The remaining missing proof is
  a real derivation of `Y ∣ AB*kZ`, `Y ∣ AB`, or an explicit smaller
  odd-parameter descent.

2026-06-26 round-003 Y-dvd-AB bridge formalizer iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and a local Python bounded search only; no web or literature source was used.
- The configured run artifact directory was read-only in this sandbox, so this
  durable note is recorded in the Lean workspace instead.
- Python bounded search over `1 <= a,b,h,u <= 80` found no assignments
  satisfying all exact halved AB/Z bridge hypotheses
  `A | (B-1)^2`, `B | (A-1)^2`, `Nat.Coprime A B`, and
  `Z | (Y-1)^2` for `Y=(h*u+1)/2`, `A=Y+a*u`, `B=Y+h*b`,
  `Z=Y+a*u+h*b+2*a*b`. This is route evidence only.
- Lean progress: added the exact requested declaration
  `odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ` as a named bridge
  over the already isolated helper. The configured verifier still fails
  earlier at the terminal `linarith` in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`; the
  primitive proof of the bridge remains the missing theorem-level certificate.

2026-06-26 round-002 primitive obstruction formalizer iteration 8 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and a local Python bounded search only; no web or literature source was used.
- Rechecked the current first blocker:
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` terminates
  with only the halved AB modular edges, `Nat.Coprime (Y + a*u) (Y + h*b)`,
  the exact Z edge `Z | (Y - 1)^2`, common-`M` divisibilities, and
  `Nat.Coprime Y Z`; the terminal `linarith` has no contradiction to derive.
- Python bounded search over odd `h,u,p,q < 101` with `h < p`, `u < q`,
  halved AB coprimality, and all three exact factor-2 divisibilities found no
  witness. This is route evidence only, not a proof.
- Dependency audit reconfirmed that the later strict odd-parameter wrappers
  still descend through the normalized quotient/common-`M` chain and return to
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`, so calling
  or moving those wrappers would not supply the required primitive certificate.
- No Lean proof edit was made because the missing theorem-level step remains
  the primitive bridge `Y | (Y + a*u) * (Y + h*b)` from the full AB/Z exact
  hypotheses, or an explicit smaller odd-parameter descent with preserved
  exact-factor hypotheses.

2026-06-26 round-002 primitive obstruction formalizer iteration 7 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and a local SymPy probe only; no web or literature source was used.
- Reproduced the configured verifier failure at
  `07_crystals_odd_vieta_descent.lean:1518:2` in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`.
- Dependency audit reconfirmed that the later strict odd-parameter target still
  routes back through this same core via the normalized quotient/common-`M`
  chain; moving or calling later obstruction wrappers would preserve a cyclic
  dependency and would not supply the requested primitive certificate.
- A SymPy reduction using the quotient identities
  `A*B + a*b = Y*Z` and `Z*kZ = (Y-1)^2` did not expose a nontrivial
  odd-Vieta equation; the only simple zero found was the tautology
  `Y^2 + (Y-1)^2 = 2*Y*(Y-1) + 1`. This supports the prior diagnosis that
  the missing proof is a genuine AB/Z divisor or descent bridge, not a local
  arithmetic-normalization issue.
- Next concrete target remains the primitive bridge
  `Y ∣ (Y + a*u) * (Y + h*b)` from the full exact AB/Z hypotheses, or an
  explicit smaller odd-parameter descent proving the same contradiction
  without calling the normalized/common-`M` wrappers.

2026-06-26 round-002 primitive obstruction formalizer iteration 6 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and local Python checks only; no web or literature source was used.
- Python bounded check over odd structured core variables
  `h,u < 80`, `a,b < 50` found no assignment satisfying the core AB product
  edge, halved AB coprimality, and exact `Z ∣ (Y - 1)^2` edge. A second
  AB-only check found examples where the fourth edge
  `Y ∣ (Z - 1)^2` fails, confirming the fourth edge is not derivable from
  the AB edge alone.
- Python bounded check over the broader ordered AB/Z product formulation
  with `Y < A,B < 500` found no witness satisfying the product identity,
  `A*B ∣ (A+B-1)^2`, `Z ∣ (Y-1)^2`, and `Nat.Coprime A B`.
- Lean progress: added verified helper
  `odd_cross_halfShift_gap_core_ordered_ABZ_product_data`, which packages the
  current core variables into the ordered AB/Z product configuration:
  `2 <= Y`, `Y < A`, `Y < B`, `A < Z`, `B < Z`, and the cross half-shift
  odd-product identity. This is order-safe and sits before the failing core.
- Remaining Lean blocker after the configured verifier is still the terminal
  primitive contradiction in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`; the proof
  state has the AB modular edges, the common-`M` divisibilities, and
  `Nat.Coprime Y Z`, but no descent/valuation lemma deriving `False`.

2026-06-26 round-002 primitive obstruction formalizer iteration 3 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local verifier output, and local Python
  checks only; no web or literature source was used.
- Reproduced the configured verifier failure at
  `07_crystals_odd_vieta_descent.lean:1419:2`. A direct replacement of the
  terminal `linarith` with `nlinarith` failed at the same proof state, so the
  remaining gap is not a linear/nonlinear arithmetic tactic selection issue.
- Dependency audit: the requested theorem
  `odd_cross_halfShift_gap_exact_factor2_odd_parameter_primitive_obstruction`
  currently routes through
  `odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent`,
  whose downstream chain returns to
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`. The line
  1419 core is therefore the base primitive obstruction, not a stale wrapper
  that can be closed by a later theorem call.
- Python bounded exact-target check over odd `h,u,p,q < 101` with `h < p`,
  `u < q`, halved AB coprimality, and all three exact factor-2 divisibilities
  found no witness. A second check omitting the coprimality condition found no
  witness for odd `h,u,p,q < 301`. These are route-evidence checks only.
- Next useful Lean target remains a standalone base lemma proving the current
  core contradiction from the halved AB edges plus
  `Z ∣ (Y - 1)^2`, preferably by deriving the missing fourth edge
  `Y ∣ (Z - 1)^2` or an explicit smaller odd-parameter descent. Reordering or
  wrapper calls would preserve the circular dependency and should be avoided.

2026-06-26 round-002 primitive obstruction formalizer notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local verifier output, and local Python
  checks only; no web or literature source was used.
- Reproduced the configured verifier failure at
  `07_crystals_odd_vieta_descent.lean:1419:2`: the proof state in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` contains the
  AB modular edges, `Nat.Coprime (Y + a*u) (Y + h*b)`, the Z edge
  `Z ∣ (Y - 1)^2`, the common-`M` divisibilities, and `Nat.Coprime Y Z`, but
  no linear contradiction. The blocker is a missing primitive AB/Z descent or
  valuation lemma, not a local `linarith` tuning issue.
- Python bounded core check over odd `h,u <= 200` and `1 <= a,b < 100` found
  no tuple satisfying `A*B ∣ (A+B-1)^2`, `Nat.Coprime A B`, and
  `Z ∣ (Y-1)^2` for
  `Y=(h*u+1)/2`, `A=Y+a*u`, `B=Y+h*b`, `Z=Y+a*u+h*b+2*a*b`.
- Python divisor-enumeration check over odd `h,u < 501` found no strict odd
  parameter witness satisfying the halved AB coprimality and all three exact
  factor-2 divisibilities. This is route evidence only; final acceptance still
  requires a Lean proof.

2026-06-25 round-003 formalizer iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-exact-factor2-edges-obstruction-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-exact-factor2-edges-obstruction-core/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python bounded
  checks only; no web or literature source was used.
- Python bounded check over `h,u < 100` and `a,b < 80` found 98 assignments
  satisfying the local AB product edge and `Nat.Coprime A B`, but no
  assignment also satisfying the exact `Z ∣ (Y - 1)^2` edge. A larger
  AB-only scan over `h,u < 200` and `a,b < 150` found 66 AB-edge examples
  with `Z <= (Y - 1)^2`, confirming that the remaining proof cannot be a
  size-only contradiction and must use exact Z divisibility/descent.
- Lean progress: added the order-safe helper
  `odd_cross_halfShift_gap_exact_factor2_halved_edges_core` before
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`, and rewired
  the target to derive the AB modular edges from the supplied local AB edge.
  The remaining blocker is still the terminal descent/valuation contradiction
  in the target helper.

Round 008 normalized quotient descent iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-008-odd-cross-halfshift-gap-normalized-quotient-descent/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-008-odd-cross-halfshift-gap-normalized-quotient-descent/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or literature
  search was used in this iteration.
- Python bounded check over all `1 <= a,b,h,u <= 80` found no assignment
  satisfying the full normalized quotient hypotheses of
  `odd_cross_halfShift_gap_normalized_quotient_descent`.
- Python bounded check of the strict odd exact-factor system found no witness
  for odd `h,u,p,q <= 150` with `h < p`, `u < q`, the halved AB coprimality,
  and all three exact factor-2 divisibilities.
- Lean progress in this pass: added the verified helper
  `odd_cross_halfShift_gap_normalized_common_M_quotients`, packaging the two
  common-`M` quotient formulas derived from `hkAB`, `hkZ`, and the cross
  half-shift common-`M` identity.
- Directly feeding those packaged quotient formulas to `nlinarith` caused a
  heartbeat timeout, so the target was restored to the clean terminal blocker:
  the proof still needs a named quotient/descent or valuation lemma rather than
  an inline polynomial arithmetic call.

Round 008 normalized quotient descent iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-008-odd-cross-halfshift-gap-normalized-quotient-descent/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-008-odd-cross-halfshift-gap-normalized-quotient-descent/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or literature
  search was used in this iteration.
- Python bounded check over `1 <= a,b < 15`, `1 <= h,u < 60` found no
  assignment satisfying all normalized quotient hypotheses of
  `odd_cross_halfShift_gap_normalized_quotient_descent`. This remains route
  evidence only.
- A narrow Lean edit replacing the terminal bare `nlinarith` with
  `nlinarith [hAB_add, hkAB, hkZ, hkZ_expanded, hkMAB, hkMZ]` still fails at
  the same theorem state. The quotient equalities need a real
  divisibility/descent lemma, not more direct polynomial arithmetic.

Round 007 exact factor-2 valuation obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-factor2-valuation-obstruction-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-factor2-valuation-obstruction-core/math_tools_report.md`
- External/source material relied on: local proof-lab context, local Lean
  source, local proof notes, and local Python checks only; no web or
  literature search was used in this iteration.
- Python bounded search over `a,b < 20`, `h,u < 30` found no assignment
  satisfying the normalized quotient hypotheses used by
  `odd_cross_halfShift_gap_normalized_quotient_descent`. This was only route
  evidence; the trusted blocker remains the Lean descent proof.
- A Lean edit exposing the two common-`M` quotient formulas from
  `halfShift_prod_common_M_sq_quotient_eq` and
  `halfShift_right_common_M_sq_quotient_eq` typechecked locally in shape, but
  made the normalized theorem exceed the heartbeat limit when left inline.
  The quotient-comparison step should be isolated as a smaller named lemma
  before retrying it in the main proof.

Sources reviewed:

- Proof-lab context bundle:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/retarget_after_freeze_20260610_2h/runs/crystals-odd-vieta-d-lt-two-se-lean/crystals-odd-vieta-d-lt-two-se-lean-1h/lean_formalizer/round-001-odd-vieta-d-lt-two-mul-se/context_bundle.md`
- AMRA math tools report:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/retarget_after_freeze_20260610_2h/runs/crystals-odd-vieta-d-lt-two-se-lean/crystals-odd-vieta-d-lt-two-se-lean-1h/lean_formalizer/round-001-odd-vieta-d-lt-two-mul-se/math_tools_report.md`
- Local Mathlib parity and arithmetic lemmas were inspected under
  `.lake/packages/mathlib/Mathlib/Algebra/Ring/Parity.lean` and related local
  dependency files.

Tool checks:

- A first broad Lean probe using `Mathlib.Tactic` exited with code 139 in this
  workspace.
- Narrow probes using `Mathlib.Tactic.Linarith`, `Mathlib.Tactic.Ring`, and
  `Mathlib.Tactic.SuppressCompilation` checked successfully.
- The final target file checked with the required verifier command.

Round 004 halved common-M-left iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-halved-common-m-left/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-halved-common-m-left/math_tools_report.md`
- External/source material relied on: local proof-lab context and local proof
  notes only; no web or literature search was used in this iteration.
- Python bounded checks found no instance satisfying the full scalar
  hypotheses for `a,b < 8` and `h,u < 20`; no counterexample was found to the
  reduced common-`M`/`gcd(Y,Z)` implication for `a,b < 20` and `h,u < 50`.
- A general same-shifted-product probe found that common-`M` transfer is false
  without the ordered halved structure; for example `(r,s,x,y) = (5,16,47,2)`.
- Lean progress in this pass: added the exact target declaration
  `odd_cross_halfShift_gap_halved_common_M_left` and a verified conditional
  bridge `odd_cross_halfShift_gap_halved_common_M_left_of_Y_dvd_AB`. The
  immediate missing subclaim is
  `odd_cross_halfShift_gap_halved_Y_dvd_AB_of_common`, proving
  `Y ∣ (Y + a*u) * (Y + h*b)` from the scalar AB/Z/common-`M` hypotheses.

Round 004 halved common-M-left iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-halved-common-m-left/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-halved-common-m-left/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, and local Mathlib source only; no web or literature search was used
  in this iteration.
- Python finite checks found no full scalar instances for
  `a,b < 40`, `h,u < 80`; no instances of the AB/Z subsystem for
  `a,b < 80`, `h,u < 120`; and no instances of the reduced
  common-`M`/`gcd(Y,Z)` subsystem for `a,b < 80`, `h,u < 100`.
- The simple size route is false: an AB-edge example
  `(a,b,h,u,Y,A,B,Z) = (4,85,1,71,36,320,121,1085)` has
  `Z <= (Y - 1)^2`, so `Z ∣ (Y - 1)^2` cannot be refuted by a
  universal denominator-size inequality.
- A SymPy quotient-witness Groebner reduction with equations
  `h*u + 1 = 2*Y`, `(B-1)^2 = A*k`, `(A-1)^2 = B*l`, and
  `(Y-1)^2 = Z*n` did not reduce `(Z-1)^2` to the generated ideal.
  This indicates that the missing fourth edge is not a direct polynomial
  identity from quotient witnesses alone.
- The remaining Lean blocker is still theorem-level:
  prove `odd_cross_halfShift_gap_halved_Y_dvd_AB_of_common`, or replace the
  bridge with a direct proof of `Y ∣ M^2` from the AB/Z/common-`M`
  hypotheses. The latter is equivalent to deriving the fourth halved edge
  `Y ∣ (Z - 1)^2` via the same common-`M` identity.

Round 005 halved Y-divides-AB iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-y-dvd-ab-of-common/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-y-dvd-ab-of-common/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python/Lean checks only; no web or
  literature search was used in this iteration.
- Python bounded checks found no assignment satisfying all hypotheses of
  `odd_cross_halfShift_gap_halved_Y_dvd_AB_of_common` for
  `h,u,a,b < 30`, and found no assignment satisfying just the two AB modular
  edges, `Nat.Coprime A B`, `Z ∣ (Y - 1)^2`, and `Nat.Coprime Y Z` for
  `h,u,a,b < 100`.
- A Lean tactic probe confirmed that `omega` cannot close the target from the
  linear identities alone; it leaves a positive remainder model for
  `((Y + a*u) * (Y + h*b)) % Y`.
- A generic same-odd-product abstraction is insufficient: Python found
  `Y=3, Z=146, A=8, B=49` with `A,B,Z > Y`, the same odd product, and
  `A*B ∣ M^2`, but `Y ∤ A*B`. This candidate fails the exact
  `Z ∣ (Y - 1)^2` condition, so the Z edge remains essential.
- A pure size route is also insufficient: `(a,b,h,u,Y,A,B,Z) =
  (1,1,1,11,6,17,7,20)` satisfies the inequality consequences
  `A <= (B-1)^2`, `B <= (A-1)^2`, and `Z <= (Y-1)^2`, but
  `Y ∤ A*B`.

Round 005 halved Y-divides-AB iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-y-dvd-ab-of-common/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-y-dvd-ab-of-common/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python/SymPy checks only; no web or
  literature search was used in this iteration.
- The current verifier failure was reproduced exactly:
  `odd_cross_halfShift_gap_halved_Y_dvd_AB_of_edges` is still missing at the
  requested target, and `odd_cross_halfShift_gap_halved_scalar_obstruction`
  remains missing downstream.
- Python search confirmed again that the two AB edge divisibilities plus
  coprimality do not imply the simple size bound `Z > (Y - 1)^2`: the known
  example `(a,b,h,u,Y,A,B,Z) = (4,85,1,71,36,320,121,1085)` has the AB edges,
  `Nat.Coprime A B`, and `Z <= (Y - 1)^2`, but fails exact `Z ∣ (Y - 1)^2`.
- A SymPy quotient check with
  `(B-1)^2 = A*r`, `(A-1)^2 = B*s`, `(Y-1)^2 = Z*c`, and
  `h*u+1 = 2*Y` showed the useful identity
  `c*A*B = Y*(Y-1)^2 - a*b*c`, but this only reduces the target to the same
  missing integrality/coprimality step `Y ∣ a*b`; it does not prove it from
  polynomial identities alone.
- The next theorem-level blocker is therefore still the exact factor-2
  odd-factor obstruction/descent: prove that the three divisibilities produced
  by `odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities`
  cannot coexist under the strict refactor parameters. That would close the
  current `Y ∣ A*B` target by contradiction and also supply the missing scalar
  obstruction.

Round 003 product-Z descent core iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-product-z-descent-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-product-z-descent-core/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python/Lean checks only; no web or
  literature search was used in this iteration.
- Python finite search found no counterexample to
  `odd_cross_halfShift_gap_halved_product_Z_descent_core` for
  `a,b < 50`, `h,u < 80`; a broader scan to `a,b,h,u < 160` found 240
  AB-product hits and no tuple also satisfying exact `Z ∣ (Y - 1)^2`.
- The pure size route is still false at the product-Z level: AB-product hits
  can have `Z <= (Y - 1)^2`, e.g.
  `(a,b,h,u,Y,A,B,Z) = (4,85,1,71,36,320,121,1085)`, but these fail the
  exact Z divisibility.
- Lean progress in this pass: added the exact declaration
  `odd_cross_halfShift_gap_halved_product_Z_descent_core` in dependency order.
  The proof now derives `hAmod`, `hBmod`, `hABcop`, `hYZcop`, common-`M`
  divisibilities, and the three exact factor-2 divisibilities
  `hAexact`, `hBexact`, and `hZexact`.
- A narrow Lean probe with the same import profile confirmed that quotient
  equations plus `nlinarith` do not close the target. The remaining blocker is
  the strict valuation/descent contradiction for the three exact factor-2
  divisibilities.

Round 004 exact factor-2 split divisibility descent iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-004-odd-cross-halfshift-gap-exact-factor2-split-divisibility-descent/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-004-odd-cross-halfshift-gap-exact-factor2-split-divisibility-descent/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or literature
  search was used in this iteration.
- Python bounded checks found no tuple satisfying the full exact split target
  for odd `h,u < 200` and `a,b < 100`; the same scan found AB-edge examples,
  confirming again that the exact Z edge is the essential obstruction.
- A reduced `(Y,Z,c,A,B)` search found no factored/coprime instance satisfying
  the same odd-product shape, `Z ∣ (Y - 1)^2`, and
  `A*B ∣ (A+B-1)^2` for the tested ranges. We did not use this as proof.
- Lean progress in this pass: factored the exact target through the new
  normalized lemma
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_direct`, and
  added the verified helper `pred_sq_quotient_coprime`, deriving
  `Nat.Coprime Y kZ` from `(Y - 1)^2 = Z * kZ`.
- The remaining blocker is a genuine descent/valuation step, not missing
  quotient exposure: even with `AB + ab = YZ`, the `AB` quotient, the exact
  `Z` quotient, both common-`M` quotients, `Nat.Coprime Y Z`, and
  `Nat.Coprime Y kZ`, `nlinarith` does not close.

Round 005 direct obstruction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-edges-valuation-obstruction-direct/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-edges-valuation-obstruction-direct/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean/Mathlib source, and local Python checks only; no web or
  literature search was used in this iteration.
- Python bounded checks found AB/coprime examples but no full AB/coprime/Z
  examples up to `a,b,h,u <= 60`; a separate product-AB/Z scan found no
  product-level witnesses up to `a,b,h,u <= 80`. These checks were used only
  as route evidence.
- Lean progress in this pass: inside
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_direct`, the
  exact Z quotient now exposes `0 < kZ`, `kZ < Y`,
  `Nat.Coprime Y kZ`, and
  `(Y + a*u + h*b + 2*a*b) * kZ + 2*Y = Y^2 + 1`.
- The required verifier still fails only at the final contradiction. The next
  useful target is a named descent/valuation lemma using these normalized
  quotient facts plus `AB + ab = YZ` and the common-`M` quotient equations to
  prove `Y ∣ (Y + a*u) * (Y + h*b)` or directly `False`.

Round 005 direct obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-edges-valuation-obstruction-direct/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-005-odd-cross-halfshift-gap-halved-edges-valuation-obstruction-direct/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python/SymPy/Lean checks only; no web
  or literature search was used in this iteration.
- Python finite search again found no full AB/coprime/Z instance in a small
  odd-parameter box, while finding tuples satisfying the two AB factor-2
  conditions and failing the exact Z condition. This keeps the Z quotient as
  the essential obstruction.
- A bounded search of the normalized product/Z quotient state introduced in
  Lean found no witness for `h,u < 100` and `a,b < 80`.
- SymPy quotient expansion confirmed the common-M identity
  `2*(Y + a*u)*(Y + h*b) - ((Y + a*u) + (Y + h*b) - 1) =
   2*Y*(Y + a*u + h*b + 2*a*b) -
   (Y + (Y + a*u + h*b + 2*a*b) - 1)` and did not produce a direct polynomial
  contradiction.
- Lean progress in this pass: factored the raw endpoint of
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_direct` into the
  named normalized lemma
  `odd_cross_halfShift_gap_normalized_quotient_descent`. The target theorem now
  passes all derived quotient facts into this lemma, and the required verifier
  fails only at that lemma's final descent step.

Round 006 halved Y-divides-AB-of-edges iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-006-odd-cross-halfshift-gap-halved-y-dvd-ab-of-edges/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-006-odd-cross-halfshift-gap-halved-y-dvd-ab-of-edges/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or literature
  search was used in this iteration.
- Python bounded checks found no tuple satisfying the exact target hypotheses
  for `a,b < 30`, `h,u < 80`; a second search over AB-edge tuples found many
  AB-edge examples but no example also satisfying the exact Z edge in the
  tested ranges. This again supports treating the missing step as the exact
  factor-2 odd-factor obstruction rather than a pure AB-edge consequence.
- Lean progress in this pass: added the exact declaration
  `odd_cross_halfShift_gap_halved_Y_dvd_AB_of_edges` and added the downstream
  scalar declaration `odd_cross_halfShift_gap_halved_scalar_obstruction`.
  Both now reduce to the same unresolved theorem-level blocker:
  `odd_cross_halfShift_gap_exact_halved_odd_factor_obstruction_of_edges`.

Round 006 halved Y-divides-AB-of-edges iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-006-odd-cross-halfshift-gap-halved-y-dvd-ab-of-edges/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-006-odd-cross-halfshift-gap-halved-y-dvd-ab-of-edges/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python/Lean checks only; no web or
  literature search was used in this iteration.
- Python checked the old unhalved witness `(h,u,p,q) = (3,31,217,39)` against
  the exact factor-2 divisibilities. The first two exact divisibilities hold,
  but the exact halved Z divisibility fails: `(h*u - 1)^2` has remainder
  `8464` modulo `2 * (p*q + 1) = 16928`.
- A bounded odd-parameter search found no exact factor-2 instance for
  odd `h,u < 80` and odd strict `p,q < 200`.
- A subsystem check found small Z-only examples, so the Z edge alone is not
  contradictory. A separate check found no tuple satisfying both AB edges and
  the exact Z edge for `h,u < 100`, `a,b < 80`, even before filtering by
  `Nat.Coprime (Y + a*u) (Y + h*b)`.
- A standalone Lean probe expanding the three divisibility hypotheses into
  quotient equations confirmed that `nlinarith` does not close the exact
  obstruction directly. The current Lean blocker remains theorem-level:
  prove
  `odd_cross_halfShift_gap_exact_halved_odd_factor_obstruction_of_edges`, or
  replace it by a smaller valuation/descent lemma for the same three exact
  halved divisibilities.

Round 001 half-shift bridge notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-001-iscrystalwithcomponents-halfshift-admissible/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-001-iscrystalwithcomponents-halfshift-admissible/math_tools_report.md`
- External/source material relied on: the context bundle's included
  Formal Conjectures source declaration for `IsCrystalWithComponents`
  from `UniqueCrystalComponents.lean`; no web search was used.
- Local Lean probe `lean_probe_halfshift.lean` checked the half-shift
  denominator identity, numerator identity, and cancellation lemma before
  those proofs were moved into the target file. The temporary probe was
  removed after transfer.

Round 003 outer-step notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/retarget_after_freeze_20260610_2h/runs/crystals-odd-vieta-d-lt-two-se-lean/crystals-odd-vieta-d-lt-two-se-lean-1h/lean_formalizer/round-003-odd-vieta-outer-d-step/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/retarget_after_freeze_20260610_2h/runs/crystals-odd-vieta-d-lt-two-se-lean/crystals-odd-vieta-d-lt-two-se-lean-1h/lean_formalizer/round-003-odd-vieta-outer-d-step/math_tools_report.md`
- Local Lean probes in `/tmp/odd_vieta_probe.lean` and
  `/tmp/odd_vieta_order_probe.lean` checked the Int-cast Vieta equation
  transfer and the Nat descent inequality shape before editing the target
  file.
- No external web or literature source was used for this round.

Round 003 cross-halfshift-to-odd-vieta notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-003-cross-halfshift-divisibility-to-odd-vieta/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-003-cross-halfshift-divisibility-to-odd-vieta/math_tools_report.md`
- External/source material relied on: the proof-lab context and audit excerpts
  included in the context bundle, including the cited Formal Conjectures source
  declaration and arXiv metadata. No web search was used in this formalizer
  pass.
- Python finite checks found no nontrivial same-product half-shift-admissible
  pairs for `r,s <= 5000`, and no positive odd-Vieta witnesses with
  `R,S < 50` and odd `X,Y < 100`.
- A symbolic check confirmed the elementary Vieta-neighbor product change
  `(2*r-1)*(2*((r-1)^2/s)-1) - (2*r-1)*(2*s-1) =
  2*(2*r-1)*(r-s-1)*(r+s-1)/s`.
- Lean progress in this pass: added and verified `no_odd_vieta_solution`, so
  the remaining cross theorem cannot be completed by merely packaging the
  requested existential; the missing step is deriving an inconsistent
  odd-Vieta witness or otherwise contradicting the cross half-shift hypotheses.

Round 003 cross-halfshift-to-odd-vieta iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-003-cross-halfshift-divisibility-to-odd-vieta/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-003-cross-halfshift-divisibility-to-odd-vieta/math_tools_report.md`
- External/source material relied on: local proof-lab context and audit
  excerpts only; no web search was used in this iteration.
- Python symbolic checks re-derived the same-product normal form
  `2*r*s - r - s = 2*x*y - x - y` after casting to integers.
- Python bounded checks in normalized gcd variables again found only swapped
  unordered examples; those are excluded by the target's `Finset` inequality.
- Lean progress in this pass: added and verified
  `no_odd_vieta_solution_exists`, `cross_halfShift_product_int_relation`, and
  `cross_halfShift_divisibility_quotients`. The remaining unproved bridge is
  the polynomial/divisibility step from these quotient equations plus
  nontrivial unordered inequality to either a direct contradiction or the
  impossible odd-Vieta existential.

Round 003 exact factor-2 edges obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-exact-factor2-edges-obstruction-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-exact-factor2-edges-obstruction-core/math_tools_report.md`
- External/source material relied on: local proof-lab context and audit
  excerpts only; no web or literature search was used.
- Local Python residue probe checked the exact factor-2 hypotheses' necessary
  2-adic residue conditions modulo odd residues below 64. Many residue classes
  survive, so there is no standalone parity contradiction to translate to Lean.
- Local Lean probe `/tmp/07_probe.lean` exposed divisibility witnesses for the
  AB edge, Z edge, and exact factor-2 triple at
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`; `nlinarith`
  still failed. The remaining blocker is therefore the same theorem-level
  descent/factor-rectangle contradiction, not a hidden linear arithmetic close.

Round 004 cross-halfshift-nontrivial-false iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-004-cross-halfshift-divisibility-nontrivial-false/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-004-cross-halfshift-divisibility-nontrivial-false/math_tools_report.md`
- External/source material relied on: local proof-lab context and audit
  excerpts only; no web search was used in this iteration.
- Python finite check found no nontrivial same-product half-shift-admissible
  duplicate among admissible pairs with `r,s <= 100`.
- Python symbolic check expanded the gcd-normalized quotient equations
  `(G*X + H*Y)^2 = (G*X+1)*(H*Y+1)*K` and
  `(G*Y + H*X)^2 = (G*Y+1)*(H*X+1)*L`; this did not reveal a direct
  quotient-to-Vieta identity without further divisibility/coprimality
  arguments.
- Lean progress in this pass: added `halfShift_divisibility_modular`, proving
  `r ∣ (s - 1)^2` and `s ∣ (r - 1)^2` from
  `r*s ∣ (r+s-1)^2`, and `finset_pair_eq_of_eq_or_swap` for the final
  unordered-pair contradiction. The remaining blocker is the global algebra
  lemma forcing equality-or-swap from same product plus both modular
  half-shift divisibility systems.

Round 004 cross-halfshift-nontrivial-false iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-004-cross-halfshift-divisibility-nontrivial-false/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-004-cross-halfshift-divisibility-nontrivial-false/math_tools_report.md`
- Attempted to write the requested run-directory `experiments.jsonl`, but the
  artifact directory is read-only in this sandbox. The nontrivial checks are
  recorded here instead.
- External/source material relied on: the local proof-lab context and the
  arXiv landing page for Abrate-Barbero-Cerruti-Murru, "The Biharmonic mean",
  arXiv:1601.03081, used only to confirm the bibliographic/source context.
- Python finite checks found no nontrivial same-product half-shift-admissible
  duplicate among sorted admissible pairs with `r,s <= 10000`.
- Lean progress in this pass: added `halfShift_divisibility_coprime`, proving
  that `r*s ∣ (r+s-1)^2` with `2 <= r,s` forces `Nat.Coprime r s`. This is
  intended for the gcd-split route for equal odd products.

Round 005 cross-halfshift-eq-or-swap iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-005-cross-halfshift-eq-or-swap-of-product-and-divisibility/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-005-cross-halfshift-eq-or-swap-of-product-and-divisibility/math_tools_report.md`
- External/source material relied on: local proof-lab context and local proof
  notes only; no web or literature search was used in this iteration.
- Python finite checks found no non-swap same-product half-shift-admissible
  duplicates for `r,s,x,y <= 200`, and no admissible pair with
  `gcd (2*r-1) (2*s-1) > 1` for `r,s <= 500`.
- Lean progress in this pass: added `nat_pair_eq_or_swap_of_mul_eq_add_eq`
  and `cross_halfShift_eq_or_swap_of_product_and_sum`, reducing the requested
  equality-or-swap theorem to the remaining algebraic blocker: derive equality
  of shifted sums
  `(2*r-1) + (2*s-1) = (2*x-1) + (2*y-1)` from same shifted product plus the
  two half-shift divisibility hypotheses.
- Required verifier command passed after these additions.

Round 005 cross-halfshift-eq-or-swap iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-005-cross-halfshift-eq-or-swap-of-product-and-divisibility/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-005-cross-halfshift-eq-or-swap-of-product-and-divisibility/math_tools_report.md`
- Attempted to write a run-directory experiment log, but that artifact path is
  read-only in this sandbox. The nontrivial check is recorded here instead.
- External/source material relied on: local proof-lab context, local proof
  notes, and local Mathlib source only; no web or literature search was used
  in this iteration.
- Python finite check found no non-swap same-product half-shift-admissible
  duplicate among admissible pairs with `r,s,x,y <= 200`.
- Lean progress in this pass: added
  `halfShift_scaled_common_factor_cancel_dvd`, the cancellation step needed
  after a gcd/common-factor split of odd half-shift factors. The remaining
  blocker is still the global algebra step deriving equality of shifted sums,
  or equivalently forcing the gcd-normalized split to have equal cross
  variables.

Round 006 cross-halfshift-sum iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-006-cross-halfshift-sum-eq-of-product-and-divisibility/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-006-cross-halfshift-sum-eq-of-product-and-divisibility/math_tools_report.md`
- External/source material relied on: local proof-lab context and local proof
  notes only; no web or literature search was used in this iteration.
- Python finite checks found no same shifted-product half-shift-admissible
  pairs with different shifted sums for `r,s <= 200`, and no odd product
  `P <= 200000` with two unordered nontrivial admissible factor pairs.
- Lean progress in this pass: added verified divisor-form support lemmas:
  `halfShift_divisibility_oddFactors`,
  `oddFactor_den_dvd_product_succ_sq`,
  `halfShift_den_dvd_product_succ_sq`, and
  `cross_halfShift_den_dvd_common_product_succ_sq`. These convert
  `r*s ∣ (r+s-1)^2` into divisibility of the odd-factor denominator by the
  common product-successor square. The remaining blocker is using these mutual
  denominator divisibilities to force the two shifted denominators, hence the
  shifted sums, to be equal.

Round 006 cross-halfshift-sum iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-006-cross-halfshift-sum-eq-of-product-and-divisibility/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-006-cross-halfshift-sum-eq-of-product-and-divisibility/math_tools_report.md`
- External/source material relied on: local proof-lab context and local proof
  notes only; no web or literature search was used in this iteration.
- Python finite checks found no same shifted-product half-shift-admissible
  pairs with different shifted sums for `r,s,x,y < 80`, no duplicate shifted
  sums among admissible pairs with `r,s <= 1000`, and no duplicate scalar
  normal forms among actual admissible root pairs with `r,s < 500`.
- Lean progress in this pass: added verified scalar-normal-form support:
  `halfShift_sumSubOne_le_prod`, `halfShift_prod_dvd_common_M_sq`,
  `cross_halfShift_common_M_eq`, and
  `cross_halfShift_products_dvd_common_M_sq`. These show that the common odd
  shifted product fixes `M = 2*r*s - (r+s-1)`, and both `r*s` and `x*y`
  divide `M^2`. The remaining blocker is the uniqueness theorem for
  half-shift-admissible root pairs in this scalar normal form, which should
  imply equality of `r+s-1` and `x+y-1`, hence the requested shifted-sum
  equality.

Round 007 cross-halfshift-sum iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-007-cross-halfshift-sum-eq-of-product-and-divisibility/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-007-cross-halfshift-sum-eq-of-product-and-divisibility/math_tools_report.md`
- External/source material relied on: arXiv:1601.03081, Abrate-Barbero-
  Cerruti-Murru, "The Biharmonic mean", was checked for the status of the
  component uniqueness step. Its closing discussion states the component
  uniqueness property for crystals as a conjectural direction, not as a proved
  theorem available for citation.
- Python finite check found no same shifted-product half-shift-admissible
  pairs with different shifted sums among admissible pairs with `r,s <= 500`.
- Lean probe on a temporary copy of the target file inserted the requested sum
  lemma and expanded the divisibility hypotheses into quotient equations. The
  proof failed exactly at the scalar-normal uniqueness step: from
  `(r+s-1)^2 = r*s*K`, `(x+y-1)^2 = x*y*L`, and common
  `M = 2*r*s-(r+s-1) = 2*x*y-(x+y-1)`, `nlinarith` cannot derive
  `r+s-1 = x+y-1`. This matches the prior blocker rather than a local Lean
  syntax issue.

Round 004 odd-factor strict obstruction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-odd-factor-strict-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-odd-factor-strict-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context and local proof
  notes only; no web or literature search was used in this iteration.
- Python finite check found no full witness to
  `odd_cross_halfShift_gap_odd_factor_strict_obstruction` for odd
  `h,u < 80` and odd `p,q < 160` with the strict inequalities.
- Python two-edge scan found strict odd-factor examples satisfying only the
  first two edge divisibilities, for example `(h,u,p,q) = (1,3,5,13)`.
  This refutes the tempting bridge from the two odd-factor edges alone to the
  full half-shift AB product, so the remaining target-local blocker genuinely
  needs the third `Z` edge or an equivalent descent/valuation step.
- Lean progress in this pass: added and verified
  `odd_lt_odd_eq_add_two_mul`,
  `odd_cross_halfShift_gap_strict_refactor_parameters`, and
  `odd_cross_halfShift_gap_strict_refactor_double_identities`. These extract
  the strict odd refactor parameters and rewrite the half-shift identities in
  the target's `p,q` notation. The exact target theorem is still not declared;
  the remaining blocker is the direct three-edge obstruction/descent.

Round 007 cross-halfshift-sum iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-007-cross-halfshift-sum-eq-of-product-and-divisibility/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/wowii198a_16_crystals_20260612_2h/runs/crystals-halfshift-admissible-bridge/crystals-halfshift-admissible-bridge-1h/lean_formalizer/round-007-cross-halfshift-sum-eq-of-product-and-divisibility/math_tools_report.md`
- External/source material relied on: local proof-lab context and local proof
  notes only; no new web or literature search was used in this iteration.
- Python finite check found no same shifted-product half-shift-admissible
  pairs with different shifted sums among admissible pairs with `r,s <= 500`.
- Python scalar-normal check found no duplicate actual admissible root-pair
  normal form `M = 2*r*s-(r+s-1)` for `r,s <= 5000`.
- A relaxed scalar-normal check showed why the already verified divisibility
  consequences are insufficient by themselves: `M = 6` has two relaxed
  pairs `(A, P) = (2, 4)` and `(6, 6)` satisfying `A = 2*P-M`,
  `0 < A <= P`, and `P ∣ A^2`, but neither gives a valid pair with
  `2 <= r,s` and `A = r+s-1`, `P = r*s`. The remaining theorem-level blocker
  is therefore the missing root-pair uniqueness step, not merely cancellation
  of the common `M^2` divisibilities.

Round 001 odd-cross half-shift gap Z obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_original_plus_next_20260613_1h_strict_slots/runs/crystals-gap-z-obstruction/crystals-gap-z-obstruction-1h/lean_formalizer/round-001-odd-cross-halfshift-gap-z-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_original_plus_next_20260613_1h_strict_slots/runs/crystals-gap-z-obstruction/crystals-gap-z-obstruction-1h/lean_formalizer/round-001-odd-cross-halfshift-gap-z-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, and local Lean source only; no web or literature search was used in
  this iteration.
- Python bounded check over all `a,b,h,u < 80` found 90 assignments satisfying
  the first divisibility hypothesis and no assignment satisfying the negated
  `Z` conclusion as well.
- Python bounded listings over `a,b,h,u < 100` showed the first divisibility
  hypothesis is nonempty and rigid, but not explained by a simple coprimality
  between `A*B` and `Z`.
- Lean progress in this pass: added verified bridge lemmas
  `odd_cross_halfShift_gap_same_odd_product` and
  `odd_cross_halfShift_gap_first_modular`. These show that the two factor
  pairs have the same odd product, and that `hdiv1` gives
  `A ∣ (B - 1)^2` and `B ∣ (A - 1)^2` for
  `A = Y + a*u`, `B = Y + h*b`. The remaining blocker is deriving a
  contradiction from these two modular consequences together with the
  hypothetical `Z ∣ (Y - 1)^2`.

Round 002 odd-cross half-shift gap Z obstruction core notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_original_plus_next_20260613_1h_strict_slots/runs/crystals-gap-z-obstruction/crystals-gap-z-obstruction-1h/lean_formalizer/round-002-odd-cross-halfshift-gap-z-obstruction-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_original_plus_next_20260613_1h_strict_slots/runs/crystals-gap-z-obstruction/crystals-gap-z-obstruction-1h/lean_formalizer/round-002-odd-cross-halfshift-gap-z-obstruction-core/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Mathlib source, and local Lean source only; no web or
  literature search was used in this iteration.
- Python bounded check over `a,b < 80`, odd `h,u < 80` found 90 assignments
  satisfying the core modular hypotheses and no assignment also satisfying
  `Z ∣ (Y - 1)^2`.
- A second Python check showed that the missing modular half
  `Y ∣ (Z - 1)^2` is not a consequence of the core modular hypotheses alone;
  for example `a=1`, `b=46`, `h=1`, `u=5`, `Y=3` satisfies the core modular
  hypotheses but has `(Z - 1)^2 % Y = 1`.
- Lean progress in this pass: added verified
  `halfShift_right_factor_dvd_common_M_sq` and
  `odd_cross_halfShift_gap_core_common_M_divisibilities`. These prove that
  under the core hypotheses plus hypothetical `Z ∣ (Y - 1)^2`, both
  `A*B` and `Z` divide the same scalar-normal square
  `(2*A*B - (A+B-1))^2`, using the existing same-odd-product identity.
- Remaining blocker: prove the final contradiction from these common-square
  divisibilities, the core modular hypotheses, and `Nat.Coprime A B`; the
  exact target theorem `odd_cross_halfShift_gap_Z_obstruction_core` is not yet
  declared.

Round 001 odd-cross half-shift gap AB-from-edges notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-001-odd-cross-halfshift-gap-ab-from-edges/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-001-odd-cross-halfshift-gap-ab-from-edges/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, and local Lean source only; no web or literature search was used in
  this iteration.
- Lean progress in this pass: added verified
  `odd_cross_halfShift_gap_AB_from_edges` as the requested theorem-level bridge,
  closing it by direct application of
  `odd_cross_halfShift_gap_modular_product`.
- Required verifier command passed after this addition.

Round 003 odd-cross half-shift gap Z obstruction core iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-z-obstruction-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-z-obstruction-core/math_tools_report.md`
- Attempted to create the requested run-directory experiment log, but the
  artifact path is read-only in this sandbox. Tool checks are recorded here
  instead.
- External/source material relied on: local proof-lab context, local proof
  notes, and local Lean/Mathlib source only; no web or literature search was
  used in this iteration.
- Lean probe `/tmp/z_coprime_probe.lean` checked the lemma shape that
  `z ∣ (y - 1)^2` forces `Nat.Coprime y z`.
- Python exact-search attempts used the `Z ∣ (Y - 1)^2` divisor condition to
  enumerate possible `Z` and solve the linear equation
  `Z = Y + a*u + h*b + 2*a*b`; the longer runs were interrupted before a
  completed bound, and no witness was printed before interruption.
- Lean progress in this pass: added verified `dvd_pred_sq_coprime` and
  `odd_cross_halfShift_gap_core_YZ_coprime`, giving the coprimality of `Y`
  and the Z-edge denominator under the core hypotheses.
- Remaining blocker: the target theorem
  `odd_cross_halfShift_gap_Z_obstruction_core` is still not declared. The
  missing mathematical step is deriving the final contradiction from the
  common-`M` square divisibilities, `Nat.Coprime A B`, and the new
  `Nat.Coprime Y Z`.

Round 003 odd-cross half-shift gap Z obstruction core iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-z-obstruction-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-z-obstruction-core/math_tools_report.md`
- External/source material relied on: local proof-lab context, local Mathlib
  source, and local Python finite checks only; no web or literature search was
  used in this iteration.
- A direct Python scan of the exact theorem hypotheses found no full witness
  for `Y <= 5000`, after examining 26,875 odd `(h,u)` pairs and 590,741
  factorized `Z` candidates. The scan used the normal form
  `(h + 2*a) * (u + 2*b) = 2*Z - 1` with `Z ∣ (Y - 1)^2`.
- Sanity subchecks found that `hZmod` alone, and `hZmod` plus AB coprimality,
  are not contradictory; the two edge congruences are essential.
- Lean progress in this pass: added verified support lemmas
  `dvd_sq_double_of_dvd_sq`,
  `odd_cross_halfShift_gap_core_odd_factor_edge_divisibilities`, and
  `odd_cross_halfShift_gap_core_odd_factor_parities`. These convert the three
  Nat half-shift divisibilities into the odd-factor system
  `((h + 2*a) * u + 1) ∣ (h * (u + 2*b) - 1)^2`,
  `(h * (u + 2*b) + 1) ∣ ((h + 2*a) * u - 1)^2`, and
  `((h + 2*a) * (u + 2*b) + 1) ∣ (h*u - 1)^2`, with the shifted factors
  still odd.
- Remaining blocker: prove the actual odd-factor obstruction for
  `p = h + 2*a`, `q = u + 2*b`, `h < p`, `u < q`, `Odd h`, `Odd u`,
  `Odd p`, `Odd q`, and the three divisibilities above; this should give a
  contradiction under `a,b >= 1`, closing
  `odd_cross_halfShift_gap_Z_obstruction_core`.

Round 004 odd-factor strict obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-odd-factor-strict-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-004-odd-cross-halfshift-gap-odd-factor-strict-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python finite checks only; no web or
  literature search was used in this iteration.
- Python exact bounded checks again found no full strict odd-factor witness in
  the searched range, while confirming that `hZ` with either one edge is
  nonempty and that both edge congruences are needed.
- Lean progress in this pass: added verified
  `dvd_sq_complement_of_dvd_sq` and
  `odd_cross_halfShift_gap_odd_factor_Z_complement_divisibility`. The latter
  turns the `Z` edge into the Vieta-complement form
  `(p*q + 1) ∣ (p*q - h*u + 2)^2`, using `h < p`, `u < q`, and
  `1 <= h*u`.
- Required verifier command passed after these additions. The exact target
  theorem `odd_cross_halfShift_gap_odd_factor_strict_obstruction` is still not
  declared; the next missing step is to combine the two edge congruences with
  this `Z`-complement divisibility into a descent or valuation contradiction.

Round 005 odd-factor edges Z-complement contradiction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-odd-factor-edges-z-complement-contradiction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-odd-factor-edges-z-complement-contradiction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python finite checks only; no web or
  literature search was used in this iteration.
- Python finite check found no full witness to
  `odd_cross_halfShift_gap_odd_factor_edges_Z_complement_contradiction` for
  odd `h,u,p,q <= 100` under the strict inequalities.
- A second Python check refuted the tempting size-only route: the two edge
  divisibilities can hold while `p*q + 1 <= (h*u - 1)^2`, for example
  `(h,u,p,q) = (1,47,31,55)`.
- Lean progress in this pass: added verified
  `odd_cross_halfShift_gap_odd_factor_Z_original_divisibility` and
  `odd_cross_halfShift_gap_odd_factor_Z_complement_iff`, proving that the
  target's complement Z edge is exactly equivalent to the older
  `(p*q + 1) ∣ (h*u - 1)^2` Z edge under `1 <= h*u`, `h < p`, and `u < q`.
- Remaining blocker: prove the strict odd-factor three-edge obstruction from
  `hA`, `hB`, and the original/complement-equivalent Z divisibility. This is
  the missing valuation/descent step; no target theorem is declared yet.

Round 005 odd-factor edges Z-complement contradiction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-odd-factor-edges-z-complement-contradiction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/controller_enhanced_four_20260618_2h/runs/crystals-ab-bridge-lean/crystals-ab-bridge-lean-2h/lean_formalizer/round-005-odd-cross-halfshift-gap-odd-factor-edges-z-complement-contradiction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python/Lean checks only; no web or
  literature search was used in this iteration.
- Python exact divisor enumeration of the original Z-equivalent condition
  found a concrete witness to all target hypotheses:
  `(h,u,p,q) = (3,31,217,39)`. Here `h*u = 93`,
  `p*u + 1 = 6728`, `h*q - 1 = 116`, `h*q + 1 = 118`,
  `p*u - 1 = 6726`, and `p*q + 1 = 8464`; the three divisibility
  quotients are `2`, `383382`, and `8281`.
- Lean probe `/tmp/crystal_counterexample_probe.lean` verified the same
  witness by `norm_num`.
- Lean progress in this pass: added verified
  `odd_cross_halfShift_gap_odd_factor_edges_Z_complement_counterexample`,
  proving that the hypotheses of the requested contradiction theorem are
  satisfiable.
- Consequence: the requested target
  `odd_cross_halfShift_gap_odd_factor_edges_Z_complement_contradiction` is
  false as stated and cannot be proved without adding or correcting a
  hypothesis. The next proof-lab target should repair the statement, for
  example by identifying the missing ordered/minimality/descent hypothesis
  that excludes the checked witness.

Round 002 odd-cross half-shift gap halved scalar obstruction notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-halved-scalar-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-halved-scalar-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python finite checks only; no web or
  literature search was used in this iteration.
- Python bounded scan over all scalar variables up to 80 found no assignment
  satisfying the exact target hypotheses.
- Python exact divisor enumeration of the halved Z condition found no full
  witness for odd `h,u < 400` with `Y <= 20000`, after testing 813,007
  possible strict factor candidates from `Z ∣ (Y - 1)^2` and
  `2*Z - 1 = p*q`.
- Lean progress in this pass: added verified
  `dvd_sq_double_two_of_dvd_sq` and
  `odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities`.
  These convert the scalar halved hypotheses into the strict odd-factor
  system with the extra factor of `2` on all three odd-factor denominators,
  isolating the factor-of-two obstruction that the known unhalved witness
  fails.

Round 001 ABZ halved factor obstruction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-001-odd-cross-halfshift-gap-abz-halved-factor-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-001-odd-cross-halfshift-gap-abz-halved-factor-obstruction/math_tools_report.md`
- Attempted to write the run-directory experiment log, but that artifact path
  is read-only in this sandbox. The nontrivial checks are recorded here
  instead.
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python/Lean checks only; no web or
  literature search was used in this iteration.
- Python direct bounded search found no exact halved AB-Z witness for odd
  `h,u,H,U < 151` under `3 <= h*u`, `h < H`, and `u < U`.
- Python divisor-parametrized search over all half-shift AB pairs
  `A,B <= 20000` found 644 AB-admissible pairs but no factorization satisfying
  the exact halved Z condition.
- Python checks confirmed why the old unhalved witness
  `(h,u,H,U) = (3,31,217,39)` is excluded: it satisfies the doubled
  unhalved Z divisibility but fails the exact halved Z divisibility by its
  2-adic valuation.
- Lean progress in this pass: declared the required theorem
  `odd_cross_halfShift_gap_ABZ_halved_factor_obstruction` with the exact
  requested source header and verified the reduction to the normalized core
  variables `a,b,h,u,Y`, where `H = h + 2*a`, `U = u + 2*b`,
  `h*u + 1 = 2*Y`,
  `(Y + a*u) * (Y + h*b) ∣ (2*Y + a*u + h*b - 1)^2`, and
  `(Y + a*u + h*b + 2*a*b) ∣ (Y - 1)^2`.
- Remaining blocker: prove the normalized halved core obstruction
  `odd_cross_halfShift_gap_halved_core_obstruction` from the preceding
  hypotheses. The required verifier now fails only because that lemma is not
  present.

Round 001 ABZ halved factor obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-001-odd-cross-halfshift-gap-abz-halved-factor-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-001-odd-cross-halfshift-gap-abz-halved-factor-obstruction/math_tools_report.md`
- Attempted no run-directory writes because that artifact path is outside the
  writable sandbox; nontrivial checks are recorded here instead.
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or literature
  search was used in this iteration.
- Python direct bounded search found no exact halved AB-Z witness for odd
  `h,u,H,U < 301` under `3 <= h*u`, `h < H`, and `u < U`.
- A targeted Python check showed that a pure size argument is insufficient:
  `(h,u,a,b,Y,A,B,Z) = (1,71,4,85,36,320,121,1085)` satisfies the halved
  AB divisibility and has `Z <= (Y - 1)^2`, but still fails
  `Z ∣ (Y - 1)^2`.
- Lean progress in this pass: added verified regression lemma
  `odd_cross_halfShift_gap_old_unhalved_witness_halved_AB_not_Z`, confirming
  that the known unhalved witness `(h,u,H,U) = (3,31,217,39)` satisfies the
  exact halved AB divisibility but not the exact halved Z divisibility.
- Lean progress also added the normalized core lemma
  `odd_cross_halfShift_gap_halved_core_obstruction` up to the final scalar
  obstruction: it now derives the two edge congruences, `Nat.Coprime A B`,
  `Nat.Coprime Y Z`, and the common-`M` square divisibilities from the exact
  halved hypotheses.
- Remaining blocker: prove the scalar obstruction
  `odd_cross_halfShift_gap_halved_scalar_obstruction` from
  `A ∣ (B - 1)^2`, `B ∣ (A - 1)^2`, `Nat.Coprime A B`,
  `Z ∣ (Y - 1)^2`, `Nat.Coprime Y Z`, the common-`M` square divisibilities,
  and the parameter identities
  `A = Y + a*u`, `B = Y + h*b`, `Z = Y + a*u + h*b + 2*a*b`,
  `h*u + 1 = 2*Y`.

Round 002 odd-cross half-shift gap halved scalar obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-halved-scalar-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-halved-scalar-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python finite checks only; no web or
  literature search was used in this iteration.
- Python bounded scalar scan over `h,u < 80` and `a,b < 60` found no
  assignment satisfying the exact target hypotheses
  `hY`, `hYu`, `hAmod`, `hBmod`, `hABcop`, `hZmod`, `hYZcop`, and both
  common-`M` divisibilities.
- A larger Python scan over `h,u < 200` and `a,b < 100` found no case where
  `hAmod`, `hBmod`, `hABcop`, `hZmod`, and `hYZcop` hold but the missing
  fourth half-shift edge `Y ∣ (Z - 1)^2` fails. This supports the next
  focused subclaim:
  `odd_cross_halfShift_gap_halved_fourth_edge`.
- The direct pair-collapse route is blocked until that fourth edge is proved:
  existing cross-halfshift lemmas can use the AB pair and the same odd-product
  identity, but the YZ pair currently has only `Z ∣ (Y - 1)^2`.

Round 003 odd-cross half-shift gap halved fourth edge iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-fourth-edge/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-fourth-edge/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python finite checks only; no web or
  literature search was used in this iteration.
- Python bounded scalar scan over `h,u < 80` and `a,b < 20` found no
  assignment satisfying the exact fourth-edge hypotheses; in particular no
  case was found where the hypotheses hold and
  `Y ∤ (Y + a*u + h*b + 2*a*b - 1)^2`.
- A generic ordered common-product transfer scan found no counterexample for
  `x < y < 500`, but the unordered generic transfer is false; for example
  `(r,s,x,y) = (5,16,47,2)` has the same odd product, the common `M`
  divisibilities for `r*s` and `y`, and `Nat.Coprime x y`, but not
  `x ∣ M^2`. Thus the proof must use the concrete ordered/special
  halved-gap shape, not only the abstract common-product data.
- Divisor-parametrized enumeration of the exact `Z ∣ (Y - 1)^2` condition for
  odd `h,u < 200` tested 179,360 induced `(a,b,h,u,Y,A,B,Z)` candidates and
  found no assignment satisfying both AB edge divisibilities. This suggests a
  stronger and possibly cleaner next blocker: prove the exact factor-2
  odd-factor obstruction generated by
  `odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities`, or
  equivalently prove that the two AB edges and the exact halved Z edge cannot
  coexist.

Round 003 odd-cross half-shift gap halved fourth edge iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-fourth-edge/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-fourth-edge/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python finite checks only; no web or
  literature search was used in this iteration.
- Python bounded scalar scan over odd `h,u < 25/45` and `a,b < 40` found no
  assignment satisfying the exact fourth-edge hypotheses. The scan found zero
  exact-hypothesis instances in that box, so it did not produce a
  counterexample to `Y ∣ (Z - 1)^2`.
- Lean progress: added verified modular transfer lemma
  `halfShift_left_factor_dvd_pred_sq_of_common_M_sq`, proving that
  `Y ∣ (2*Y*Z - (Y+Z-1))^2` implies `Y ∣ (Z-1)^2`.
- Lean progress: added verified bridge lemma
  `odd_cross_halfShift_gap_halved_fourth_edge_of_common_M_left`, reducing the
  requested fourth-edge target to the single missing common-`M` left-factor
  divisibility
  `Y ∣ (2*(Y+a*u)*(Y+h*b) - ((Y+a*u)+(Y+h*b)-1))^2`.
- Remaining blocker: prove the above `Y ∣ M^2` subclaim from the scalar AB/Z
  hypotheses, or bypass it with the stronger exact factor-2 odd-factor
  obstruction from
  `odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities`.

Round 007 exact halved odd-factor obstruction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-halved-odd-factor-obstruction-of-edges/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-halved-odd-factor-obstruction-of-edges/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local Mathlib source search, and local Python
  checks only; no web or literature search was used in this iteration.
- Python bounded check over `a,b,h,u <= 80` found no tuple satisfying
  `hY`, `hYu`, the two AB edge divisibilities, `Nat.Coprime A B`, and the
  exact halved Z divisibility.
- Python odd-factor scan over odd strict `h,u,p,q` found that the only
  `AB + unhalved Z` witnesses in the searched box are
  `(h,u,p,q) = (3,31,217,39)` and its swap `(31,3,39,217)`; both have odd
  quotient for `(h*u - 1)^2 / (p*q + 1)`, matching the known factor-of-two
  failure of the exact halved Z condition.
- Lean progress: added the exact requested declaration
  `odd_cross_halfShift_gap_exact_halved_odd_factor_obstruction_of_edges` and
  reduced it to the explicit strict factor-2 odd-factor divisibility system
  produced by
  `odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities`.
- Remaining blocker: prove the new theorem-level descent/valuation subclaim
  `odd_cross_halfShift_gap_exact_factor2_odd_factor_divisibility_obstruction`
  for the strict factor-2 system plus the transported `A,B` coprimality.

Round 007 exact halved odd-factor obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-halved-odd-factor-obstruction-of-edges/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/crystals_wowii198a_next_20260618_2h/runs/crystals-abz-halved-obstruction-lean/crystals-abz-halved-obstruction-lean-2h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-halved-odd-factor-obstruction-of-edges/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or
  literature search was used in this iteration.
- Python scan over odd `h,u < 150` and `a,b < 100` found 154 assignments
  satisfying the two AB edge divisibilities plus `Nat.Coprime A B`, but no
  assignment also satisfying the exact halved Z edge
  `Z ∣ (Y - 1)^2`. This again rules out a pure AB-edge contradiction and
  confirms that the remaining formal blocker is the exact Z-edge
  descent/valuation step.
- Lean cleanup in this pass: renamed unused parameters in
  `odd_cross_halfShift_gap_halved_Y_dvd_AB_of_common` so the verifier output
  reports only the true missing obstruction lemma.

Round 001 exact factor-2 obstruction continuation notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-001-odd-cross-halfshift-gap-exact-factor2-odd-factor-divisibility-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-001-odd-cross-halfshift-gap-exact-factor2-odd-factor-divisibility-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or
  literature search was used in this iteration.
- Python bounded check over odd `h,u < 151` and `a,b < 120` found 196
  assignments satisfying the two exact AB factor-2 divisibilities plus
  `Nat.Coprime A B`, but no assignment also satisfying the exact factor-2
  Z divisibility.
- Lean progress: added the exact target declaration
  `odd_cross_halfShift_gap_exact_factor2_odd_factor_divisibility_obstruction`
  and the checked extraction lemma
  `odd_cross_halfShift_gap_exact_factor2_halved_edges`, reducing `hExact` to
  the three halved divisibilities.
- Remaining blocker: prove the direct descent/valuation lemma
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction`, from the
  halved AB edges, `Nat.Coprime A B`, and exact halved Z edge.

Round 001 exact factor-2 obstruction continuation iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-001-odd-cross-halfshift-gap-exact-factor2-odd-factor-divisibility-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-001-odd-cross-halfshift-gap-exact-factor2-odd-factor-divisibility-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local Python checks only; no web or
  literature search was used in this iteration.
- Python bounded search for `h,u,a,b < 80` found AB-edge/coprime examples but
  no tuple also satisfying the exact halved Z edge.
- Lean progress: added
  `odd_cross_halfShift_gap_hu_odd_of_halfshift` and a checked reduction for
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction` from halved
  `Y,a,b` hypotheses to strict odd parameters `p = h + 2*a`,
  `q = u + 2*b`.
- Remaining blocker: prove
  `odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent`,
  the strict odd-parameter valuation/descent contradiction for the three exact
  factor-2 divisibilities plus coprime half-denominators.
2026-06-24 round-002 strict factor2 target: read local context_bundle.md and math_tools_report.md from the run artifact directory. No web/literature sources used. Python finite check: no strict solutions for odd h,u < 60 and p,q < 120; no normalized halved triple solutions for odd h,u < 40 and a,b < 40; AB-edge-only cases exist, so the exact Z edge is essential. Run artifact directory was read-only, so this durable note records the check.

Round 002 strict factor2 target continuation notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-valuation-descent/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-valuation-descent/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, and local verifier output only; no web or
  literature search was used in this pass.
- A naive Python bounded search for normalized full hypotheses was started as
  a sanity check and stopped before completion because it was too broad to be
  useful. No result from that aborted check is used as evidence.
- Lean progress: added the missing normalized lemma
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_core` and proved
  the reduction from the two halved AB edge divisibilities plus
  `Nat.Coprime (Y + a*u) (Y + h*b)` to the AB product divisibility via
  `odd_cross_halfShift_gap_modular_product`.
- Remaining blocker is now the smaller product-plus-Z descent statement:
  `odd_cross_halfShift_gap_halved_product_Z_descent_core`, with hypotheses
  `1 <= a`, `1 <= b`, `h*u + 1 = 2*Y`, `3 <= h*u`,
  `(Y + a*u) * (Y + h*b) ∣ (2*Y + a*u + h*b - 1)^2`, and
  `(Y + a*u + h*b + 2*a*b) ∣ (Y - 1)^2`.

Round 003 product-Z descent core iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-product-z-descent-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-003-odd-cross-halfshift-gap-halved-product-z-descent-core/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local Mathlib source search, and local Python
  checks only; no web or literature search was used in this iteration.
- Python bounded check over `a,b,h,u < 80` found no tuple satisfying the exact
  product-Z target hypotheses. The same scan showed that AB-only examples
  exist and commonly fail `Y ∣ a*b`, so the AB product divisibility alone is
  insufficient.
- Python scan of the exact Z edge alone found many examples, all failing the
  AB product divisibility in the sampled box. This confirms the remaining
  proof must use the interaction between `AB ∣ (A+B-1)^2` and
  `Z ∣ (Y-1)^2`, not either edge in isolation.
- A reduced algebraic probe using `AB + a*b = Y*Z` showed that the coarse
  constraints `Z ∣ (Y-1)^2`, `AB ∣ (A+B-1)^2`, and the product-sum
  inequality still allow abstract models. The missing formal step must retain
  the exact halved-gap/discriminant or valuation structure.
- Remaining Lean blocker is unchanged but now better isolated: prove the
  strict valuation/descent contradiction for the exact factor-2 divisibilities
  derived inside `odd_cross_halfShift_gap_halved_product_Z_descent_core`.

Round 006 normalized quotient descent iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-006-odd-cross-halfshift-gap-normalized-quotient-descent/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-006-odd-cross-halfshift-gap-normalized-quotient-descent/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python checks
  only; no web or literature search was used in this iteration.
- Python bounded sanity check over `a,b < 80` and `h,u < 120` found no tuple
  satisfying the normalized quotient hypotheses. A broader factorized search
  over `Y`, divisors of `2*Y - 1`, and the bilinear `a,b` equation was stopped
  before completion and is not used as evidence.
- Lean progress inside `odd_cross_halfShift_gap_normalized_quotient_descent`:
  derived the AB product divisibility witness from `hkAB`, recovered
  `Nat.Coprime (Y + a*u) (Y + h*b)` via
  `halfShift_divisibility_coprime`, split the AB product edge into the two
  halved edge divisibilities via `odd_cross_halfShift_gap_first_modular`, and
  reconstructed the exact factor-2 triple
  `odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities`.
- Remaining Lean blocker: close the exact factor-2 valuation/descent
  contradiction from the now-local hypotheses `hABcop`, `hEdges`, `hZmod`,
  and `hExact`; the terminal `linarith` still cannot prove `False`.

Round 006 normalized quotient descent iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-006-odd-cross-halfshift-gap-normalized-quotient-descent/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-006-odd-cross-halfshift-gap-normalized-quotient-descent/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python/Z3
  sanity probes only; no web or literature source was used in this iteration.
- Tool checks: a direct Python scan of the full normalized hypotheses was
  started and stopped as too broad; a divisor-parametrized Python scan and a
  bounded Z3 nonlinear encoding were also stopped before completion. These
  aborted checks are not used as evidence for unsatisfiability.
- Lean progress: added checked common-`M` quotient normalization lemmas
  `halfShift_prod_common_M_sq_quotient_eq` and
  `halfShift_right_common_M_sq_quotient_eq`. A local attempt to thread these
  formulas into `odd_cross_halfShift_gap_normalized_quotient_descent` compiled
  in isolation but made the terminal tactic time out, so the target theorem was
  restored to the sharper existing failing state.
- Remaining Lean blocker: prove the exact factor-2 valuation/descent
  contradiction from `hABcop`, `hEdges`, `hZmod`, and `hExact`, or derive the
  fourth edge `Y ∣ (Y + a*u + h*b + 2*a*b - 1)^2` from the normalized quotient
  equations without routing through the downstream wrappers.

Round 007 exact factor2 valuation obstruction core iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-factor2-valuation-obstruction-core/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-007-odd-cross-halfshift-gap-exact-factor2-valuation-obstruction-core/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python sanity
  checks only; no web or literature source was used in this iteration.
- Python bounded check over `1 <= a,b,h,u <= 80` found no tuple satisfying
  the requested exact factor-2 target hypotheses. A broader direct nested
  scan up to `300` was stopped as too slow and is not used as evidence.
- Lean progress: added the missing theorem-level declaration
  `odd_cross_halfShift_gap_exact_factor2_valuation_obstruction_core` with the
  exact requested statement, deriving oddness and strict refactor parameters
  before delegating to the existing strict odd-parameter obstruction. The
  older same-shaped wrapper now calls this core lemma.
- Remaining Lean blocker: the verifier still fails earlier in
  `odd_cross_halfShift_gap_normalized_quotient_descent` at the terminal
  `nlinarith`; the local context already contains `hABcop`, `hEdges`,
  `hZmod`, and the reconstructed exact triple `hExact`.

Round 009 normalized common-M descent iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-009-odd-cross-halfshift-gap-normalized-common-m-descent/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-009-odd-cross-halfshift-gap-normalized-common-m-descent/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python sanity
  checks only; no web or literature source was used in this iteration.
- Artifact write note: appending the Python check to the run directory
  `experiments.jsonl` failed because that artifact directory is mounted
  read-only in this sandbox, so this workspace proof note records the check.
- Python bounded check over `h,u < 50` and `a,b < 30` found no tuple
  satisfying `h*u + 1 = 2*Y`, `3 <= h*u`,
  `Nat.Coprime Y Z`, `Nat.Coprime Y kZ`, `Z*kZ = (Y - 1)^2`,
  `AB | M^2`, and `Z | M^2` for the normalized common-`M` variables.
- Lean progress: replaced the terminal `nlinarith` in
  `odd_cross_halfShift_gap_normalized_quotient_descent` with a direct call to
  `odd_cross_halfShift_gap_normalized_common_M_descent`, removing the second
  verifier error and isolating the target blocker at the common-`M` lemma.
- Remaining Lean blocker: prove `False` in
  `odd_cross_halfShift_gap_normalized_common_M_descent` after deriving
  `hAB_sum`, `hAB`, `hEdges`, `hABcop`, `hkZsq`, `hZmod`, and `hExact`.

Round 010 exact factor2 pre-common-M obstruction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-010-odd-cross-halfshift-gap-exact-factor2-pre-common-m-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-010-odd-cross-halfshift-gap-exact-factor2-pre-common-m-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python sanity
  checks only; no web or literature source was used in this iteration.
- Python bounded check over odd `h,u < 80` and `a,b < 20` found no tuple
  satisfying the exact factor-2 triple plus
  `Nat.Coprime (Y + a*u) (Y + h*b)`. A separate bounded check over
  `a,b < 8`, `h,u < 20` found no tuple satisfying the normalized common-`M`
  hypotheses. These checks are route evidence only, not part of the proof.
- Lean progress: added the requested declaration
  `odd_cross_halfShift_gap_exact_factor2_pre_common_M_obstruction` with the
  exact target statement, currently as an alias to the existing later
  `odd_cross_halfShift_gap_exact_factor2_valuation_obstruction_core`, and
  routed `odd_cross_halfShift_gap_exact_factor2_odd_factor_divisibility_obstruction`
  through the new name. This removes the target-not-found audit blocker.
- Remaining Lean blocker: the declaration is still too late in file order to
  unblock `odd_cross_halfShift_gap_normalized_common_M_descent`; the verifier
  still fails at that lemma's terminal `linarith`.

Round 010 exact factor2 pre-common-M obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-010-odd-cross-halfshift-gap-exact-factor2-pre-common-m-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260624_4h/runs/crystals-factor2-obstruction-lean/crystals-factor2-obstruction-lean-4h/lean_formalizer/round-010-odd-cross-halfshift-gap-exact-factor2-pre-common-m-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local Mathlib source search, and local verifier
  output only; no web or literature source was used in this iteration.
- Dependency audit: the existing lower exact-factor proof path is not
  order-safe for the first failing declaration. The chain
  `odd_cross_halfShift_gap_exact_factor2_pre_common_M_obstruction` ->
  `odd_cross_halfShift_gap_exact_factor2_valuation_obstruction_core` ->
  `odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent` ->
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_core` ->
  `odd_cross_halfShift_gap_halved_product_Z_descent_core` ->
  `odd_cross_halfShift_gap_exact_factor2_split_divisibility_descent` ->
  `odd_cross_halfShift_gap_halved_edges_valuation_obstruction_direct` routes
  back through `odd_cross_halfShift_gap_normalized_quotient_descent` and
  `odd_cross_halfShift_gap_normalized_common_M_descent`.
- Therefore simply moving the existing target declaration earlier would create
  a declaration-order cycle rather than proving the current blocker. The next
  useful theorem-level target is an order-safe exact factor-2 obstruction whose
  proof does not call the normalized quotient/common-M wrappers.

Round 004 halfShift cross AB-Z obstruction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-004-halfshift-cross-ab-z-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-004-halfshift-cross-ab-z-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python sanity
  checks only; no web or literature source was used in this iteration.
- Python bounded check over `2 <= Y <= 200`, `Y < A,B <= 200`, with `Z`
  reconstructed from the crossed odd-product identity, found no tuple
  satisfying the target hypotheses `A < Z`, `B < Z`,
  `Nat.Coprime A B`, `A*B | (A+B-1)^2`, and `Z | (Y-1)^2`.
- Lean progress: added the requested declaration
  `halfShift_cross_AB_Z_obstruction` with the exact target statement as a
  wrapper around the existing same-shaped
  `odd_cross_halfShift_gap_ABZ_product_Z_coprime_obstruction`.
- Remaining Lean blocker: the workspace still fails earlier at
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`; its terminal
  `linarith` has not been replaced by an order-safe non-cyclic contradiction.

Round 004 halfShift cross AB-Z obstruction iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-004-halfshift-cross-ab-z-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/restart_four_20260625_2h/runs/crystals-factor2-edges-core-lean/crystals-factor2-edges-core-lean-2h/lean_formalizer/round-004-halfshift-cross-ab-z-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local prior attempt reports, local verifier output,
  and local Python/SymPy sanity checks only; no web or literature source was
  used in this iteration.
- The run artifact directory is read-only in this sandbox, so this workspace
  proof-notes file is the durable record for the nontrivial tool checks.
- Python bounded check over `2 <= Y <= 100`, `Y < A,B,Z <= 100` found no
  witness to the full `halfShift_cross_AB_Z_obstruction` hypotheses.
- Python bounded check over odd `h,u,p,q <= 200` with `h < p`, `u < q` found
  no witness to the exact factor-2 triple, even before imposing the halved
  AB coprimality hypothesis.
- Additional bounded checks found examples satisfying the exact `Z` edge plus
  halved AB coprimality alone, and examples satisfying the AB product edge
  plus coprimality alone, confirming again that the missing proof must use the
  interaction of the two edges.
- A small SymPy identity search did not find a direct variable-only bridge
  from the strict odd parameters to the existing `no_odd_vieta_solution`
  equation; the bridge, if valid, must use quotient/divisibility data.
- Remaining Lean blocker is unchanged: close
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` without
  routing through the cyclic normalized/common-M wrappers or later wrappers.

Round 002 odd-parameter primitive obstruction iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python sanity
  check only; no web or literature source was used in this iteration.
- The run artifact directory is read-only in this sandbox, so this workspace
  proof-notes file is the durable record for the nontrivial tool check.
- Python bounded check over odd `h,u,p,q < 120` with `h < p`, `u < q`,
  halved AB coprimality, and the three exact factor-2 divisibility hypotheses
  found no witness to the requested primitive obstruction statement. This is
  route evidence only.
- Lean progress: added the requested declaration
  `odd_cross_halfShift_gap_exact_factor2_odd_parameter_primitive_obstruction`
  with the exact target signature, currently routed through the existing
  same-shaped `odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent`.
- Remaining Lean blocker: the workspace still fails earlier at
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`; its terminal
  `linarith` has no contradiction and still needs the order-safe primitive
  AB/Z descent certificate.

Round 002 odd-parameter primitive obstruction iteration 4 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python bounded
  search only; no web or literature source was used in this iteration.
- Python bounded search over odd `h,u < 80` and odd `p,q < 160` with
  `h < p`, `u < q`, halved AB coprimality, and the three exact factor-2
  divisibility hypotheses found no witness to the requested primitive
  obstruction statement. This is route evidence only.
- Lean progress: added verified support lemma
  `odd_cross_halfShift_gap_fourth_edge_of_Y_dvd_AB`, proving that the missing
  bridge `Y ∣ (Y + a*u) * (Y + h*b)` would imply the fourth half-shift edge
  `Y ∣ (Y + a*u + h*b + 2*a*b - 1)^2`.
- Current first Lean blocker remains the terminal contradiction in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`; after this
  helper, the next concrete primitive target is the divisor bridge
  `Y ∣ (Y + a*u) * (Y + h*b)` from the exact AB/Z hypotheses.

Round 002 odd-parameter primitive obstruction iteration 5 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-002-odd-cross-halfshift-gap-exact-factor2-odd-parameter-primitive-obstruction/math_tools_report.md`
- External/source material relied on: local proof-lab context, local proof
  notes, local Lean source, local verifier output, and local Python bounded
  check only; no web or literature source was used in this iteration.
- Python bounded check over odd `h,u < 80` and `1 <= a,b < 60` found 78
  assignments satisfying the two halved AB modular edges plus
  `Nat.Coprime A B`, but no assignment also satisfying the exact
  `Z ∣ (Y - 1)^2` edge. No counterexample to the bridge
  `Y ∣ (Y + a*u) * (Y + h*b)` appeared under the full checked AB/Z system.
  This is route evidence only.
- Lean progress: added verified support lemma
  `odd_cross_halfShift_gap_fourth_edge_of_modular_edges_and_Y_dvd_AB`,
  proving that the divisor bridge `Y ∣ (Y + a*u) * (Y + h*b)`, together
  with the two modular AB edges and halved coprimality, yields the fourth
  edge `Y ∣ (Y + a*u + h*b + 2*a*b - 1)^2`.
- Current first Lean blocker remains the primitive bridge
  `Y ∣ (Y + a*u) * (Y + h*b)` from the exact AB/Z hypotheses; this is the
  missing theorem-level certificate needed before the terminal core can close.

2026-06-26 round-003 Y-dvd-AB bridge formalizer iteration 2 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and local Python checks only; no web or literature source was used.
- Configured verifier initially reproduced the known endpoint:
  `07_crystals_odd_vieta_descent.lean:1518:2: error: linarith failed to find a contradiction`.
- Lean progress: added verified helper
  `odd_cross_halfShift_gap_Z_quotient_data`, exposing the quotient data from
  the exact Z edge:
  `(Y - 1)^2 = (Y + a*u + h*b + 2*a*b) * kZ`, `0 < kZ`, `kZ < Y`,
  `Nat.Coprime Y kZ`, and
  `(Y + a*u + h*b + 2*a*b) * kZ + 2*Y = Y^2 + 1`.
- Rewired the failing core to expose this quotient data before the terminal
  contradiction. The verifier now fails at the same logical gap with those
  hypotheses present in the proof state.
- Python bounded checks in this pass:
  full AB/coprime/Z search over `h,u < 80`, `a,b < 60` found no full bridge
  counterexample; AB/coprime-only search found examples where `Y ∤ a*b`,
  confirming that the Z edge is essential. A separate AB/coprime-only
  `gcd(A*B,Z)` scan found varied gcds, so a plain generic coprimality
  cancellation between `A*B` and `Z` is not a valid shortcut.
- Remaining theorem-level blocker: use the exposed Z quotient facts together
  with the AB modular/common-`M` divisibilities to prove the primitive bridge
  `Y ∣ (Y + a*u) * (Y + h*b)` or an equivalent smaller odd-parameter descent.

2026-06-26 round-003 Y-dvd-AB bridge formalizer iteration 3 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/prooflab_route_repair_20260626_2h/runs/crystals-abz-descent-certificate-prooflab/crystals-abz-descent-certificate-prooflab-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, local verifier output,
  and local Python checks only; no web or literature source was used.
- Python bounded check over `h,u < 80`, `1 <= a,b < 60` found no witnesses
  satisfying the full halved bridge hypotheses
  `h*u + 1 = 2*Y`, `3 <= h*u`, both AB modular edges, halved AB coprimality,
  and the exact `Z ∣ (Y - 1)^2` edge. This is route evidence only.
- Lean progress: added checked support lemma
  `odd_cross_halfShift_gap_Z_le_pred_sq_of_exact_Z`, extracting
  `Y + a*u + h*b + 2*a*b <= (Y - 1)^2` from the exact Z edge via the existing
  quotient package. This names a reusable inequality for the remaining
  primitive bridge/descent attempt.
- Configured verifier after this edit still fails at
  `07_crystals_odd_vieta_descent.lean:1602:2` in
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core`, where
  `linarith` cannot derive `False` from the exposed AB modular edges,
  common-`M` divisibilities, Y/Z coprimality, and Z quotient facts.

2026-06-27 round-003 ab-kZ quotient bridge formalizer iteration 1 notes:

- Proof-lab context bundle reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/context_bundle.md`
- AMRA math tools report reviewed:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/main_target_four_20260627_2h/runs/crystals-components-unique-main-descent/crystals-components-unique-main-descent-2h/lean_formalizer/round-003-odd-cross-halfshift-gap-y-dvd-ab-mul-z-quotient-of-exact-halved-abz/math_tools_report.md`
- External/source material relied on: local proof-lab context, local AMRA math
  tools report, local Lean source, local proof notes, and a local Python
  bounded check only; no web or literature source was used in this iteration.
- Python bounded check over `1 <= h,u < 40`, `1 <= a,b < 30` found no tuple
  satisfying the exact target hypotheses, and therefore no counterexample to
  `Y ∣ a*b*kZ`. This is route evidence only.
- Lean progress: added the exact requested declaration
  `odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ`.
  The current body is routed by contradiction through the existing halved
  odd-factor obstruction, so it removes the target-not-found issue but does
  not yet provide the primitive quotient proof requested by proof lab.
- Current verifier blocker remains the earlier
  `odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core` terminal
  `linarith`; the acyclic primitive proof of `Y ∣ a*b*kZ` from AB modular
  edges, common-`M` data, and Z quotient facts is still missing.
