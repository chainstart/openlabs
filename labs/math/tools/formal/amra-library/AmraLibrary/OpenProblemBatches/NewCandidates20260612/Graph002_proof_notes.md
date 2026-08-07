# GRAPH-002 Formalizer Notes

Iteration: round-005 graph002_of_certificate.

Sources used:

- Local context bundle:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/eight_next_round_20260612_1h/runs/graph002-domination-le-eternal/graph002-domination-le-eternal-1h/lean_formalizer/round-005-graph002-of-certificate/context_bundle.md`
- Local copy of D. West REGS eternal domination page:
  `/home/biostar/work/projects/amra/sources/open_candidate_screening_20260612/dwest.web.illinois.edu_regs_eterndom.html.html`

Formalizer decision:

- The existing theorem `dominationNumber_le_eternalDominationNumber` is the
  verified bridge lemma requested by the context.
- The strict audit expects the source declaration
  `theorem dominationNumber_le_eternalDominationNumber`.
- Removed the speculative `graph002_of_certificate` wrapper because its theorem
  header was the reported source-declaration mismatch.

Iteration: round-008 gamma/eternal-two route.

Additional sources used:

- arXiv:2110.09732, MacGillivray-Mynhardt-Virgile,
  "Eternal Domination and Clique Covering", arXiv abstract page:
  https://arxiv.org/abs/2110.09732
- Local West REGS eternal domination page:
  `/home/biostar/work/projects/amra/sources/open_candidate_screening_20260612/dwest.web.illinois.edu_regs_eterndom.html.html`

Tool check:

- Python enumerated all simple graphs on at most six vertices using the local
  finite definitions for domination, one-guard eternal defense, and clique
  cover. No graph was found with `gamma = gamma_infty = 2` and clique cover
  number different from `2`.

Lean progress:

- Added standard finite clique-cover definitions:
  `IsCliqueCover`, `HasCliqueCoverCard`, `cliqueCoverNumber`,
  `cliqueCoverNumber_spec`, and
  `cliqueCoverNumber_le_of_hasCliqueCoverCard`.
- The general theorem named
  `gamma_eq_eternalDominationNumber_eq_two_implies_cliqueCoverNumber_eq_two`
  is still not present. The next missing proof ingredient is a formal
  assignment/two-clique-cover theorem from the hypotheses
  `dominationNumber G = 2` and `eternalDominationNumber G = 2`.

Iteration: round-008 formalizer follow-up.

Additional tool check:

- Python re-enumerated all simple graphs on at most six vertices using the
  current local definitions for domination, one-guard eternal feasibility, and
  clique-cover number. No graph with
  `dominationNumber = eternalDominationNumber = 2` and
  `cliqueCoverNumber ≠ 2` was found.

Lean progress:

- Proved that a one-clique cover gives a one-vertex dominating set:
  `hasDominatingSetCard_one_of_hasCliqueCoverCard_one`.
- Proved the lower-bound half
  `two_le_cliqueCoverNumber_of_dominationNumber_eq_two`.
- Added the named theorem
  `gamma_eq_eternalDominationNumber_eq_two_implies_cliqueCoverNumber_eq_two`
  in conditional form, closing from the proved lower bound plus an explicit
  `cliqueCoverNumber G ≤ 2` hypothesis.

Remaining gap:

- The unformalized mathematical step is still the assignment theorem deriving
  `cliqueCoverNumber G ≤ 2` from
  `dominationNumber G = 2` and `eternalDominationNumber G = 2`.

Iteration: round-009 source-declaration repair.

Sources used:

- Local context bundle:
  `/home/biostar/work/projects/amra/artifacts/open_problem_screening/latest/eight_next_round_20260612_1h/runs/graph002-domination-le-eternal/graph002-domination-le-eternal-1h/lean_formalizer/round-009-gamma-eq-eternaldominationnumber-eq-two-implies-cliquecovernumber-eq-two/context_bundle.md`
- Existing local source notes in `Graph002_sources.md`.

Formalizer decision:

- The strict audit for this round still expects the source declaration
  `theorem dominationNumber_le_eternalDominationNumber`.
- Removed the speculative clique-cover continuation and the conditional
  `gamma_eq_eternalDominationNumber_eq_two_implies_cliqueCoverNumber_eq_two`
  theorem from `Graph002.lean`, because that theorem header was the current
  source-declaration mismatch and the full two-clique theorem remains
  source-grounding blocked.
