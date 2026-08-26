---
name: physics-research-loop
description: Run auditable analytical, computational, or public-data physics research from a current prior-art boundary through explicit conventions, falsifiable claims, reproducible calculations, independent checks, and evidence-gated handoff. Use for OpenLabs physics open-problem selection, derivations, simulations, public experimental or observational data analysis, and deciding whether a physics claim is mature enough for independent review.
---

# Physics Research Loop

Advance one precise claim or obstruction, not a broad field slogan.

1. Freeze the question, physical regime, observable, assumptions, units, sign/gauge/frame conventions,
   comparator and a result that would falsify or stop the route.
2. Establish a dated closest-work boundary. Separate published facts, standard assumptions, numerical
   evidence, conjectures and the exact unresolved increment. Recheck before claim promotion.
3. Select the smallest adequate tool route. Prefer analytic or exact checks before expensive numerics;
   reduce symmetry, dimensionality or truncation before increasing resources.
4. Register public data before analysis and preserve raw bytes immutably. Record source, terms,
   citation, acquisition time and SHA-256; never copy credentials or restricted data into OpenLabs.
5. Record each consequential computation with code/input/environment/output hashes, command, precision,
   randomness and numerical controls. Preserve null results, failed routes and counterexamples.
6. Check dimensions, limiting cases, symmetries, conservation laws and known benchmarks. A fit or a
   visually convincing plot is not a mechanism or proof.
7. Promote a claim to `verified` only after at least two genuinely independent evidence routes agree
   (for example analytic plus numeric, two formulations, or an isolated replication context).
8. Update the durable workstream and write the bounded OpenLabs result bundle. Use a fresh context for
   independent replication, adversarial review or route reselection.

Read [evidence-gates.md](references/evidence-gates.md) before supporting a claim,
[tool-routing.md](references/tool-routing.md) before adding dependencies, and
[public-data-governance.md](references/public-data-governance.md) before downloading data.

## OpenLabs boundary

Keep plans, small code, manifests and claim state under
`$OPENLABS_WORKSPACE/openlabs-data/workspaces/physics/<campaign-id>/`. Put raw datasets, large arrays,
checkpoints and heavy numerical outputs under
`$OPENLABS_WORKSPACE/openlabs-artifacts/experiments/<campaign-id>/`. Refer to artifacts by URI and
SHA-256. The lab analyzes existing public data but never operates real instruments or executes a
physical experiment. All heavy commands run through `bin/openlabs-resource-guard`.
