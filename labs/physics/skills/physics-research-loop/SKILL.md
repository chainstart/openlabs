---
name: physics-research-loop
description: Run auditable analytical, computational, or public-data physics research from a current prior-art boundary through explicit conventions, falsifiable claims, reproducible calculations, independent checks, and evidence-gated handoff. Use for OpenLabs physics open-problem selection, derivations, simulations, public experimental or observational data analysis, and deciding whether a physics claim is mature enough for independent review.
---

# Physics Research Loop

Own the configured physics objective and freely choose its decomposition, hypotheses, analytical
route, computation, public data, tools, milestones, and route changes. The items below are
claim-quality requirements, not a prescribed research process.

- State the exact question, regime, observable, assumptions, units, sign/gauge/frame conventions,
  comparator, and falsifier for every promoted claim. Load `resolution_decision.json` so changes in
  scope are explicit rather than silent.
- Maintain a dated closest-work boundary. Separate published facts, assumptions, numerical
  evidence, conjectures, and the unresolved increment; recheck novelty before promotion.
- Register public data and preserve raw bytes immutably. Record source, terms, citation,
  acquisition time, and SHA-256; never place credentials or restricted data in OpenLabs.
- Bind consequential computations to code/input/environment/output hashes, exact commands,
  precision, randomness, convergence controls, and applicable dimensional, limiting-case,
  symmetry, conservation-law, and benchmark checks.
- Preserve null results, failed routes, and counterexamples. A fit or visually convincing plot is
  not by itself a mechanism or proof.
- Mark a claim `verified` only when independent evidence appropriate to that claim agrees. Use a
  fresh context for an independent replication or adversarial review.

An intermediate audit, baseline, null result, obstruction, lemma, or literature update is a durable
advance but does not complete an active problem-solving task. Persist it and continue while the
task budget and role permit. Stop only on the task's scientific/quality target, a genuine
all-routes external blocker, an independent-review boundary, or a safe end-of-budget checkpoint.
Never declare the problem solved unless every criterion in a declared resolution route is `met`
with evidence. A `needs_replan` checkpoint must name an executable next attack.

Read [evidence-gates.md](references/evidence-gates.md) before supporting a claim,
[problem-resolution.md](references/problem-resolution.md) before closing a round or changing an
open-problem verdict,
[tool-routing.md](references/tool-routing.md) before adding dependencies, and
[public-data-governance.md](references/public-data-governance.md) before downloading data.

## OpenLabs boundary

Keep plans, small code, manifests and claim state under
the task's staged campaign path. Put raw datasets, large arrays, checkpoints and heavy numerical
outputs under `transaction.artifact_staging_root` (the prepared runtime exposes its
`experiments_root`). Refer to every staged payload by URI and SHA-256 in `result.artifacts`; never
write directly to the live `openlabs-artifacts/experiments/` tree. The control plane publishes the
bytes and promotes only a small reference manifest. The lab analyzes existing public data but never
operates real instruments or executes a physical experiment. All heavy commands run through
`bin/openlabs-resource-guard`.
