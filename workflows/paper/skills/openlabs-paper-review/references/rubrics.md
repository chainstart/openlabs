# OpenLabs reviewer rubrics

The computer-science high standard preserves the validated ARA `RevisionAgent` semantics. The
mathematics standard uses the repository's four-leading-journal benchmark. The physics standard is
calibrated to the same exceptional selectivity, while applying discipline-appropriate tests of
physical correctness and importance. Materials science uses a selective leading-journal benchmark,
and quantitative finance uses a leading finance/econometrics journal benchmark. Every role also
receives the separate CAS Zone 1 journal view defined below. Apply only the high-standard section
selected from the paper registry domain.

## Common score calibration

Score all five dimensions from 1 to 10 using integers:

- `clarity`: organization, precision, readability, definitions, and presentation;
- `soundness`: correctness of methods, inference, experiments, proofs, and evidence;
- `significance`: importance and likely value of the validated contribution;
- `novelty`: originality relative to verified literature and established methods;
- `overall`: conservative holistic readiness under the selected domain standard.

Most submission-stage papers belong in the 5--7 range. Award 8 or above only to genuinely strong,
well-evidenced papers. An unsupported central claim, invalid inference, substantive proof gap, or
unverifiable critical artifact must prevent a positive accept decision regardless of the numeric
average. Do not use the repository floor as a scoring target.

Use the appropriate vocabulary for each view:

- Top conference: `strong_accept`, `accept`, `weak_accept`, `borderline`, `weak_reject`, `reject`,
  `strong_reject`.
- Four leading mathematics journals and CAS Zone 1 journals: `accept`, `minor_revision`,
  `major_revision`, `reject_and_resubmit`, `reject`.

Use `minor_revision` only when the contribution is already scientifically sound and the remaining
work needs no new central proof, experiment, dataset, analysis, formalization, or claim. Use
`major_revision` for substantial but same-cycle scientific repair, `reject_and_resubmit` when a
fundamentally new review cycle is needed, and `reject` when the present contribution or scope is not
viable.

## AI, computer science, and software engineering: `cs_top_tier`

Act as an expert reviewer for a top-tier computer-science conference such as NeurIPS, ICML, or
ACL. Be fair, detailed, constructive, specific, and actionable.

Judge soundness through method validity, experimental protocol, evidence strength, baselines,
statistics, and reproducibility. Distinguish text-only clarification from requests for new
experiments, analysis, figures, data/models, or missing baselines. Penalize benchmark breadth,
baseline coverage, or practical generality only to the extent required by the claims actually made.
Do not give top-conference novelty credit merely for extensive engineering, audit volume, or use of
an advanced model.

The numeric assessment always uses this top-conference standard for registry domains `ai`, `cs`,
and `se`. Produce two independent opinions:

- `top_conference`: apply the full top-conference standard and the seven-point vocabulary;
- `cas_zone_1_journal`: apply the CAS Zone 1 standard below and the five-point journal vocabulary.

## Mathematics: `math_four_journals`

Act as an expert referee applying the shared highest-tier standard represented by these four
general mathematics journals:

- *Annals of Mathematics*;
- *Inventiones Mathematicae*;
- *Journal of the American Mathematical Society* (JAMS);
- *Acta Mathematica*.

This is a benchmark for quality, depth, originality, breadth or field-level significance, and
lasting mathematical interest. It is not a claim that the manuscript fits the editorial scope of
all four journals. Evaluate theorem statements, proof correctness, novelty relative to prior
mathematics, exposition, definitions, notation, and claimed formalization artifacts. Be rigorous
but constructive.

Judge soundness through precise quantifiers and hypotheses, complete proof dependencies, hidden
assumptions, boundary cases, and valid computational claims. Treat a missing proof step, unverified
lemma, wrong quantifier, circular dependency, or unsupported formalization claim as a scientific
gap. A complete natural-language proof does not require proof-assistant formalization merely to be
scientifically ready. Judge the proof presented; do not require prior external peer review as a
precondition for the internal review.

A transparently bounded literature search may reduce novelty confidence, but it does not by itself
make a sound paper scientifically unready unless a concrete competing result is identified. Do not
request empirical baselines, seeds, datasets, or model comparisons unless the manuscript makes
empirical or computational claims. Symbolic or finite checks validate only their encoded contract
and never substitute for a general proof.

Calibrate the `overall` score specifically to the four-journal bar:

- `9--10`: an exceptionally deep or transformative result with complete support and a compelling
  case for the four-journal level; use very rarely;
- `8`: a credible four-journal candidate with major originality and significance, no central proof
  gap, and only bounded uncertainty about positioning or exposition;
- `7`: near the four-journal threshold but with material uncertainty about depth, reach, novelty,
  or required scientific revision; do not pair it with a positive journal decision unless the
  contribution is already scientifically at that level;
- `5--6`: potentially sound and publishable mathematics, but the present contribution is below the
  four-journal bar or its case has not been established;
- `3--4`: serious correctness, novelty, significance, or completeness problems;
- `1--2`: fundamentally invalid, unsupported, or non-viable in its present form.

Keep the dimensions distinct. A technically correct but incremental or narrowly scoped theorem may
score well on `soundness` while scoring substantially lower on `novelty`, `significance`, and
`overall`. Do not inflate those dimensions merely because the proof is long or formally verified.

Interpret `four_top_math_journals` at the same four-journal standard. `accept` and
`minor_revision` require an already four-journal-caliber scientific contribution;
`major_revision` means that level is plausible only after substantial same-cycle repair;
`reject_and_resubmit` means new mathematical work and a new review cycle are needed; and `reject`
also covers sound work whose contribution is clearly below this benchmark. Record ordinary target-
journal fit separately and never let an easier target raise the four-journal score.

Also produce `cas_zone_1_journal` under the standard below. Mathematics reviews must not contain a
conference opinion: the high-standard opinion is `four_top_math_journals`.

## Materials science: `materials_leading_journals`

Act as an expert referee for a leading, selective materials-science journal. Judge whether the
validated contribution is physically meaningful, genuinely new, reproducible, and supported at
the level required by its claims. Inspect composition/phase/structure provenance, model or
pseudopotential domain, numerical convergence, independent reference calculations, experimental
comparability, sampling units, uncertainty, finite-size/time/ensemble sensitivity, and exclusions.

Do not accept a learned potential as its own independent validator, trajectory frames as automatic
replicates, agreement with experiment as proof of mechanism, or a pilot as production evidence.
Differentiate association, mechanistic consistency, and causal elementary mechanism. A narrow but
sound result may be useful, but extensive computation alone does not establish novelty or
significance.

Use the five-point journal vocabulary for `leading_materials_journals`, then make a separate
`cas_zone_1_journal` assessment. Both views require sound central evidence; the leading-journal
view has the higher bar for novelty, breadth and field impact. Never emit a conference or
four-leading-mathematics-journal recommendation for this role.

## Physics: `physics_explicit_highest_tier_venues`

Read [physics-highest-tier-venues.md](physics-highest-tier-venues.md) before scoring. There is no
canonical “physics four”, so do not review against an unnamed prestige level. Independently
simulate the current official editorial standards of **Physical Review Letters**,
**Physical Review X**, and **Nature Physics**. These three journals are the fixed OpenLabs highest-tier
original-physics set. Their selectivity is used as the operational counterpart of the exceptional
four-leading-mathematics-journal bar; their scopes and criteria remain journal-specific.

Judge whether the manuscript contains a field-shaping, conceptually important physical result
rather than only a correct specialist calculation. Reconstruct the exact regime, assumptions,
normalizations, units, sign/gauge/frame conventions, boundary conditions, analytic continuation,
and the logical status of every central statement.

For analytical work, inspect identities, singularities, branches, factorization or limiting
behavior, imported theorems, and any claim that finite samples or finite-field reconstruction imply
a universal formula. For numerical or simulation work, inspect conditioning, precision,
convergence, discretization/truncation and finite-size/time effects, seeds, uncertainty, and known
benchmarks. For public-data work, inspect provenance, release/calibration, selection, uncertainty,
and reproducibility. Agreement with one check or known slice supports only that slice; it does not
establish a mechanism or full solution without a completeness argument.

Keep novelty, significance, and soundness separate. A rigorous scoped theorem, no-go result,
counterexample, or reproducible computational certificate can be important, but must not be
described as resolving the original open problem unless its declared resolution criteria are met.
A technically sound but narrow or mainly computational classification can score highly on
soundness while remaining below this highest-tier bar on significance, novelty, and overall.
Extensive exact computation, reproducibility, or difficulty alone does not establish field-level
importance.

For each named venue, fill its exact criterion-route and criterion-score fields before choosing a
decision. PRL requires a pivotal advance through at least one of its four official routes plus
novelty, importance, broad interest, presentation, and stand-alone Letter fit. PRX requires at
least one of its seven official routes and weighs innovation, quality, long-term impact, and broad
physics accessibility. Nature Physics requires a top-tier original result, strong expert
excitement, importance in fundamental physics or technological potential, reach beyond a narrow
specialty, and a credible long-term case. A technically correct specialist paper should normally
receive `criterion_route: none` at all three venues.

Calibrate each venue score and `overall` on this scale:

- `9--10`: an exceptionally deep or transformative physical result with complete support and a
  compelling case for field-level, lasting impact; use very rarely;
- `8`: a credible highest-tier physics candidate with major conceptual originality and
  significance, no central scientific gap, and only bounded uncertainty about positioning or
  exposition;
- `7`: near that threshold but with material uncertainty about depth, reach, conceptual novelty,
  or required scientific revision;
- `5--6`: potentially sound and publishable physics, but below the math-four-equivalent bar or
  without a demonstrated case for that level;
- `3--4`: serious correctness, novelty, significance, physical-interpretation, or completeness
  problems;
- `1--2`: fundamentally invalid, unsupported, or non-viable in its present form.

The `leading_physics_journals` summary must name the deterministic best fit while retaining all
three venue simulations. `accept` and `minor_revision` require an already highest-tier-caliber
contribution at that named journal; `major_revision` means that level is plausible only after
substantial same-cycle repair; `reject_and_resubmit` means new scientific work and a new review
cycle are needed; and `reject` also covers sound specialist work clearly below every venue in the
set. Then make an independent `cas_zone_1_journal` assessment. Never emit conference,
mathematics, materials, or quantitative-finance recommendations for this role.

## Quantitative finance: `quant_finance_leading_journals`

Act as an expert referee for a leading quantitative-finance, asset-pricing, financial econometrics,
or computational-finance journal. Judge whether the work contains a genuine financial or statistical
contribution rather than an adaptively selected profitable backtest. Require a dated closest-work
boundary, an intelligible mechanism or methodological advance, and evidence proportionate to the
markets and generality claimed.

Reconstruct the information timeline and inspect data vintages, revisions, universe entry/exit,
delistings, corporate actions, calendars, timestamp alignment, transformations and exclusions.
Recover the full hypothesis/parameter search family. Evaluate dependence-aware uncertainty,
selection and multiple-testing control, pre-specified confirmation, strong matched baselines,
subperiod and regime stability, and independent replication where central to the claim.

For strategy or factor results, separately assess gross and net performance, execution lag, fees,
spread/slippage, turnover, liquidity/capacity, funding/borrow, leverage, drawdown, known factor and
sector exposure, and benchmark-relative effects. Do not accept impossible same-bar fills, current
constituents projected backward, final revised data used as real-time information, nominal p-values
after adaptive search, or a repeatedly exposed holdout. A high Sharpe ratio or information
coefficient alone establishes neither novelty nor future profitability.

Use the five-point journal vocabulary for `leading_quant_finance_journals`, then make a separate
`cas_zone_1_journal` assessment. Both views require valid point-in-time evidence and honest search
provenance; the leading-journal view has the higher bar for mechanism, identification, novelty,
generalization, and likely field impact. Never emit conference, four-leading-mathematics-journal, or
materials-journal recommendations for this role.

## CAS major-category Zone 1 journal view

Apply this as a second, independent review view in every supported domain. It is deliberately less
selective than the top-computer-science-conference or four-leading-mathematics-journal standard.
The reduction is mainly in the required breadth, field-wide impact, and exceptional novelty; it is
not a relaxation of correctness, evidence integrity, claim support, or research ethics.

A CAS Zone 1 journal candidate should present a scientifically sound and non-trivial contribution,
adequate comparison with verified prior work, scope-appropriate evidence or complete proofs, and a
manuscript that can be made publishable within a normal journal revision cycle. A narrow result can
be viable when its importance within the stated scope is established. Extensive engineering,
length, or computation alone does not establish significance.

Use the five-point journal decisions as follows:

- `accept`: scientifically complete and publication-ready apart from production edits;
- `minor_revision`: the central contribution is already sound and meaningful, with only bounded
  corrections or clarifications that require no new central proof, experiment, dataset, analysis,
  or claim;
- `major_revision`: potentially viable at Zone 1, but substantial scientific work is still needed
  within the same review cycle;
- `reject_and_resubmit`: a new central result, redesigned evaluation/proof strategy, or fundamentally
  new review cycle is needed;
- `reject`: the present work is invalid, unsupported, insufficiently novel or significant even for
  this standard, or unsuitable in its current research form.

Do not translate the high-standard decision by a fixed number of levels. Reassess the contribution
against this standard. Use `major_category` as the repository's partition scope. If a particular
target journal is named, record `verified_target` only after verifying its current CAS partition,
scope, source, and check date; otherwise record `generic_standard` and do not claim the target is
actually Zone 1.
