# matfactory

`matfactory` is an auditable literature-to-simulation workflow for lithium solid
electrolytes. The current study targets exact-composition
Li6.5La3Zr1.5Ta0.5O12 (LLZTO) and keeps literature extraction, structure
realization, molecular dynamics, transport estimation, and experimental
validation traceable to immutable inputs.

## Current status

The completed restart handoff is recorded in [`CONTINUATION.md`](CONTINUATION.md),
with the current prior-art boundary, falsifiable paper claim, and publication
gates in [`docs/Q1_WORK_PLAN.md`](docs/Q1_WORK_PLAN.md). The isolated QE/SSSP
reference workflow is under [`dft/`](dft/README.md).

The repository is in supervised formal-production and independent-reference
validation, not yet at a publication-result stage. The current working tree
passes 335 tests. The earlier unattended runs are retained under
`runs/_superseded/` and must not be used in figures or fits. New runs use
protocol fingerprints and refuse to resume if code, configuration, structure,
package versions, or model weights change.

The first clean formal point, occupancy realization 0 at 700 K, has now
completed 500.1 ps and resolves both tracer and collective estimators under the
frozen convergence rules. It remains conditional on the full independent G2
model-domain gate and cannot by itself support an Arrhenius, population, or
experimental Haven-ratio claim; the same run had advanced to 750 K before the
long campaign was stopped.

The current campaign pins the default CHGNet state dictionary to SHA-256
`9484ac3e09d17e40e8df63f307c85fc0277981f9418f50d0bc7379c40b198b2c`;
loading different weights aborts before dynamics begins.

## Lightweight structure-discovery pilot

The long LLZTO production campaign is currently stopped. A separate, zero-GPU
pilot now audits experimental average structures for hidden occupational order
and routes small ordered structures toward later soft-mode checks. Its research
rationale, literature map, one-day budget, and publication gates are recorded
in
[`docs/ONE_DAY_MATERIALS_DISCOVERY_PROGRAM_2026-08-07.md`](docs/ONE_DAY_MATERIALS_DISCOVERY_PROGRAM_2026-08-07.md).

Inspect the frozen pilot without reading structures or writing results:

```bash
uv run matfactory-discover \
  protocols/hidden_order_soft_mode_pilot_v1.json --list
```

Run only the CPU structure audit (no model weights, GPU relaxation, phonons, or
DFT are started):

```bash
uv run matfactory-discover \
  protocols/hidden_order_soft_mode_pilot_v1.json
```

The calibration audit identifies the rounded LLZTO average occupancies as an
exact-composition hidden-order problem and keeps all downstream stages disabled.
It is workflow validation, not a new-material or paper-ready result.

Completed checks include:

- pinned experimental CIF (COD 1545083) and exact occupancy-constrained ordered
  cells with formal charge neutrality;
- force-and-cell relaxation before dynamics;
- modern ASE Nose-Hoover-chain NVT and optional MTK NPT equilibration;
- periodic unwrapping and host-framework drift correction that does not erase
  concerted Li motion;
- time-origin-averaged tracer and collective MSD, non-overlapping block
  uncertainty, diffusive-exponent checks, and explicit unresolved points;
- exact-composition experimental benchmarks with DOI and sample context;
- atomic outputs, source/data/model hashes, and strict run-directory manifests.
- complete-grid 1/2/4/8-rank QE equivalence auditing that verifies rank-specific
  queue provenance and treats timing only as a descriptive scaling diagnostic.

The initial 94-atom realization relaxed from 3.14 to 0.044 eV/A maximum force,
lowered its CHGNet energy by about 9.92 eV, and increased its volume by about
1.4%. A 2 ps, 1000 K smoke run was structurally stable but had a tracer MSD
exponent of about 0.50, correctly demonstrating that such a short trajectory is
not a resolved diffusion measurement.

## Reproduce the environment

Python 3.11 or newer and a CUDA-capable PyTorch installation are expected for
production MD.

```bash
uv sync --all-extras
uv run pytest -q
```

The project has no declared software license yet; do not assume redistribution
rights beyond the licenses of the cited inputs and dependencies.

## Data and provenance

- `data/structures/raw/cod_1545083.cif`: experimental LLZTO diffraction model,
  SHA-256 `cbcb4f83b3ee0be0ce7a4e05a9e02bf429f8bb5aee317690678af02939c92ba3`.
- `data/experimental/llzto_matched_v1.json`: hand-curated, exact-composition
  NMR and impedance benchmarks. Single crystals and ceramics remain distinct;
  a two-point activation energy derived from the reported NMR diffusivities is
  explicitly secondary and is excluded from primary inference.
- `facts/llzo_v9.jsonl`: deterministic re-extraction of the broader literature
  corpus. It is useful for contextual distributions, not as exchangeable
  exact-composition replicates.
- `protocols/llzto_q1_v1.json`: preregistered run matrix, numerical checks,
  stopping rules, sensitivity studies, and publication gates.

The structure comes from [COD 1545083](https://www.crystallography.net/cod/1545083.html).
Exact-composition measurements are taken from
[Inada et al.](https://doi.org/10.3389/fenrg.2016.00028),
[Hamao et al.](https://doi.org/10.2109/jcersj2.16019), and
[Kataoka et al.](https://doi.org/10.1002/celc.201800679); the CuO-assisted
ceramic of [Li et al.](https://doi.org/10.1007/s10853-020-05221-1) is marked as
a secondary processing benchmark.

## Run the staged campaign

Inspect every materialized configuration without starting GPU work:

```bash
uv run matfactory-campaign protocols/llzto_q1_v1.json --list
```

Run the entries currently enabled in the protocol (the matched 1 fs and 2 fs
NVE numerical pilots):

```bash
uv run matfactory-campaign protocols/llzto_q1_v1.json
```

Select a disabled stage explicitly after its preceding gate has been reviewed:

```bash
uv run matfactory-campaign protocols/llzto_q1_v1.json \
  --run pilot-occ00-20ps
```

Every campaign run has its own directory. A completed temperature point can be
resumed only under the identical fingerprint; changing a step count or any
source file requires a new run ID/directory. Partial JSON writes are atomic.

## Scientific design

The primary series uses 700, 750, 800, 850, and 900 K, with 0.5 ns production
per temperature. This matches a recent LLZO MD precedent that used the same
temperatures and 0.5 ns sampling. Five crystallographic occupancy realizations,
two additional velocity repeats, a 94-versus-188-atom size comparison, and
fixed/relaxed/thermal-volume checks are specified in the campaign.

Tracer diffusion and collective charge diffusion are accepted independently.
For each temperature, the relevant MSD must have a log-log exponent from 0.8
to 1.2, at least 20 A^2 displacement at the maximum analyzed lag, at least four
valid blocks, and relative block standard error no larger than 0.5. Any failed
temperature blocks the corresponding Arrhenius fit; no negative or unresolved
point is silently removed.

Population inference follows
`analysis/protocols/llzto_hierarchical_transport_v1.json`: each independently
prepared occupancy/velocity pair is one statistical unit, point uncertainty is
propagated on log diffusivity, activation energies use a REML random-effects
summary with a modified Hartung-Knapp interval, and a nested configuration
bootstrap propagates room-temperature extrapolation uncertainty. Trajectory
frames are never counted as independent replicates. Because the five primary
runs do not cross occupancy and velocity seeds, their between-run variance is
reported as configuration-plus-initialization variation—not mislabeled as a
pure occupancy effect. Fixed-occupancy velocity repeats are a sensitivity check.

Mechanism-to-transport inference is frozen separately in
`analysis/protocols/llzto_mechanism_transport_association_v1.json`. It uses the
five occupancy realizations as clusters, controls occupancy-specific intercepts
and Arrhenius temperature dependence, corrects the complete twelve-test family
with Holm's method, and requires leave-one-occupancy-out, cluster-bootstrap, and
mechanism-setting sensitivity agreement. Even a passing result is reported as
an association rather than a causal elementary mechanism. Once all formal
transport and mechanism reports exist, regenerate it with:

```bash
uv run python -m matfactory.mechanism_transport \
  --campaign-root runs/campaigns/llzto_q1_v1 \
  --mechanism-root runs/analysis/mechanisms-formal-v1 \
  --protocol analysis/protocols/llzto_mechanism_transport_association_v1.json \
  --out runs/analysis/mechanism-transport-association-v1.json
```

The 25 formal primary/sensitivity mechanism analyses are supervised by a
recoverable CPU queue. It remains dormant until the hash-bearing full G2 gate
passes, refuses to run alongside `pw.x`, and waits for each completed transport
artifact before reading its trajectory:

```bash
uv run python -m matfactory.mechanism_queue \
  --association-protocol analysis/protocols/llzto_mechanism_transport_association_v1.json \
  --release-gate runs/supervisor/g2-release-v1.json \
  --state runs/supervisor/mechanism-analysis-queue-v1.json
```

The primary association model uses the physically motivated Arrhenius
temperature term. A separately frozen robustness audit prevents shared
nonlinear temperature response from being mistaken for mechanism evidence by
refitting all twelve cells with categorical temperature fixed effects. It can
only retain or downgrade a primary association, never rescue one:

```bash
uv run python -m matfactory.mechanism_temperature_queue \
  --protocol analysis/protocols/llzto_mechanism_temperature_robustness_v1.json \
  --state runs/supervisor/mechanism-temperature-robustness-queue-v1.json
```

Its waiting state is covered by a narrow auxiliary watchdog so the existing
eleven-process watchdog remains immutable:

```bash
uv run python -m matfactory.master_watchdog \
  --protocol analysis/protocols/llzto_mechanism_temperature_watchdog_v1.json \
  --state runs/supervisor/mechanism-temperature-watchdog-v1.json
```

The exact-composition single-crystal literature defines its reported Haven
ratio as `D_tracer/D_sigma = 0.4`, whereas the trajectory estimator stores the
reciprocal `D_collective/D_tracer`. A frozen supplementary analysis fits the
paired-block ratio hierarchy, reports both conventions, and labels its 298 K
comparison as an extrapolation:

```bash
uv run python -m matfactory.haven_queue \
  --protocol analysis/protocols/llzto_haven_convention_validation_v1.json \
  --state runs/supervisor/haven-validation-queue-v1.json
```

Its waiting process is covered by
`analysis/protocols/llzto_haven_watchdog_v1.json` using the same conservative
waiting-only restart policy.

The 10 ps NVE timestep check does not establish that a 100 fs production
thermostat leaves 500 ps transport unchanged. A separately fingerprinted
control therefore reuses the exact occupancy-0 relaxed structure and velocity
seed at 800 K, performs the same 20 ps NVT equilibration, and then changes only
the 500 ps production dynamics from NVT to NVE:

```bash
uv run python -m matfactory.md_queue \
  protocols/llzto_ensemble_nve_matched_v1.json \
  --run ensemble-nve-matched-occ00-vel1701-800k \
  --release-gate runs/supervisor/g2-release-v1.json \
  --state runs/supervisor/md-ensemble-nve-matched-queue-v1.json
uv run python -m matfactory.ensemble_analysis_queue \
  --protocol analysis/protocols/llzto_ensemble_sensitivity_v1.json \
  --state runs/supervisor/ensemble-analysis-queue-v1.json
```

The analysis requires resolved tracer, collective, and ratio estimators, a
stable NVE energy/temperature record, and block-bootstrap equivalence within
the frozen factor-1.5 margin. Non-equivalence remains a reportable sensitivity
outcome; it cannot be converted into computational incompleteness or averaged
away. Both waiters are covered by
`analysis/protocols/llzto_ensemble_watchdog_v1.json`.

The universal CHGNet potential is useful for long trajectories, but agreement
with experiment alone is not a validation because error cancellation is
possible. Representative relaxed and finite-temperature configurations must be
compared with a consistently computed DFT reference set before publication-level
claims. The campaign therefore treats potential-domain validation as a hard
gate. The CHGNet model and training data are described by
[Deng et al.](https://doi.org/10.1038/s42256-023-00716-3).

The k-point queue is followed by a persistent, model-blind numerical state
machine. Gamma-to-2x2x2 passed the frozen relative-energy and stress limits but
failed the force limit, so the predeclared 3x3x3 comparison was activated. A
default-low-I/O input was stopped before its first SCF iteration after QE
reported an unsafe 42.29 GB total dynamic-memory estimate. The versioned v2/v3
resource-only amendment retains every structure, physical setting, mesh,
threshold, and decision rule while using the independently pre-probed
`disk_io=medium`, one k-point pool layout (29.45 GB estimate). The supervisor
then dispatches the frozen SCF branch and full MPI-rank grid only if the
model-blind numerical comparison passes:

```bash
uv run python -m matfactory.dft_numerical_queue \
  --protocol analysis/protocols/llzto_dft_numerical_supervisor_v2.json \
  --state runs/supervisor/dft-numerical-supervisor-v1.json
```

The following domain supervisor consumes that state and enforces the separate
12-snapshot development and 30-snapshot publication-heldout releases:

```bash
uv run python -m matfactory.dft_domain_queue \
  --protocol analysis/protocols/llzto_dft_domain_supervisor_v1.json \
  --state runs/supervisor/dft-domain-supervisor-v1.json
```

The end-to-end final supervisor waits for all DFT, MD, and mechanism queues,
runs the four independent formal analyses with up to four CPU workers, and then
serially builds the experimental comparison, publication package, manuscript,
attestations, evidence audit, and Q1-readiness dossier:

```bash
uv run python -m matfactory.final_queue \
  --protocol analysis/protocols/llzto_final_supervisor_v1.json \
  --state runs/supervisor/final-analysis-supervisor-v1.json
```

An operational watchdog observes all eleven heavy or waiting processes. It may
restart a missing Python supervisor only when its hash-verified state is still a
pure waiting state; interrupted calculations and scientific blockers are merely
reported for intervention. Formal-MD liveness follows the newest temperature
equilibration or production log, including transitions between those stages:

```bash
uv run python -m matfactory.master_watchdog \
  --protocol analysis/protocols/llzto_master_watchdog_v1.json \
  --state runs/supervisor/master-watchdog-v1.json
```

The publication route is selected only after the universal-potential domain
decision is complete. A passing universal branch is kept isolated; a failing
universal branch may trigger the frozen fine-tuning contingency and a full
rerun under a separately hashed model. The research-analysis waiter combines
only one selected branch, and the downstream publication waiter derives the
branch-specific 12-figure/12-table package, manuscript, test/environment
attestations, clean regeneration, eight-gate audit, and readiness dossier:

```bash
uv run python -m matfactory.research_analysis_queue \
  --protocol analysis/protocols/llzto_research_analysis_supervisor_v2.json \
  --state runs/supervisor/research-analysis-supervisor-v2.json
uv run python -m matfactory.research_final_queue \
  --protocol analysis/protocols/llzto_research_publication_supervisor_v4.json \
  --state runs/supervisor/research-publication-supervisor-v4.json
```

The v4 publication supervisor is a provenance-only successor to v3: in addition
to the 3x3x3 resource amendment, interruption, probes, assessment, and release
token, it adds a machine-verifiable source-equivalence certificate for the
already-running universal occupancy-0 series to the derived G0 hard gate. The
certificate freezes both Git source states and their exact diff, reproduces the
stored raw-CIF structure fingerprint, and obtains byte-identical legacy
transport values from all 5002 completed T700 frames. Branch selection and
scientific acceptance rules are unchanged. Both waiters have independent
hash-checking watchdogs.
Complete physical non-equivalence, null mechanism association, or experimental
incompatibility remains a reportable scientific result; unresolved or
provenance-invalid input still blocks the dossier.

The final completeness decision is declarative and hash-aware. The frozen
`analysis/protocols/llzto_q1_evidence_audit_v1.json` checks all eight hard gates,
including the machine-readable exclusion/negative-result ledger. It is expected
to report blockers until every formal artifact, figure, table, manuscript file,
and clean-regeneration attestation exists:

```bash
uv run python -m matfactory.evidence_audit \
  --protocol analysis/protocols/llzto_q1_evidence_audit_v1.json \
  --out runs/analysis/publication-v1/evidence-audit.json
```

Passing this audit authorizes the final qualitative Q1-level assessment; it does
not assert or guarantee a journal quartile.

The separately frozen readiness rubric refuses to run before that audit passes.
It summarizes the completed computational evidence while leaving the current
external novelty and journal-fit judgment explicit and unresolved:

```bash
uv run python -m matfactory.q1_readiness \
  --protocol analysis/protocols/llzto_q1_readiness_v1.json
```

After G0-G6 are complete, the original frozen template supplies the first nine
logical figures and tables. The active branch-aware research adapter adds the
matched production-ensemble, categorical-temperature mechanism, and explicit
Haven-convention outputs, for twelve logical figures (SVG/PDF/300-dpi PNG),
twelve machine-readable tables (JSON/CSV), and 60 hashed physical outputs. It
re-verifies every embedded source hash and refuses partial, unresolved, mixed-
model, or overwrite-prone builds. The persistent research publication
supervisor above is the canonical entry point; the base template can still be
inspected directly with:

```bash
uv run python -m matfactory.publication \
  --protocol analysis/protocols/llzto_publication_package_v1.json
```

The active research manuscript builder then turns those same twelve verified
tables into an outcome-aware English main article, complete supplementary
information, and a data/code-availability statement. It requires every figure
and table, preserves null/incompatible outcomes, labels room-temperature values
as extrapolations, forbids causal mechanism language, and hashes all three
documents in a manuscript manifest. The following command shows the underlying
nine-output template; the branch-specific twelve-output manuscript is generated
by `matfactory.research_final_queue` after routing:

```bash
uv run python -m matfactory.manuscript \
  --protocol analysis/protocols/llzto_manuscript_v1.json
```

Final attestations are deliberately separate from analysis. They rerun the full
test suite, verify the Python/QE locks plus QE binary and CHGNet weight hashes,
then rebuild every publication and manuscript artifact in a temporary clean
output tree and require byte-identical logical outputs:

```bash
uv run python -m matfactory.attestation tests \
  --out runs/analysis/publication-v1/test-attestation.json
uv run python -m matfactory.attestation environment \
  --audit-protocol analysis/protocols/llzto_q1_evidence_audit_v1.json \
  --qe-manifest dft/manifests/qe_7.5_conda_linux64.json \
  --formal-run-manifest runs/campaigns/llzto_q1_v1/formal-occ00-vel1701/run_manifest.json \
  --out runs/analysis/publication-v1/environment-attestation.json
uv run python -m matfactory.attestation regenerate \
  --publication-protocol analysis/protocols/llzto_publication_package_v1.json \
  --manifest runs/analysis/publication-v1/artifact-manifest.json \
  --manuscript-protocol analysis/protocols/llzto_manuscript_v1.json \
  --manuscript-manifest runs/analysis/publication-v1/manuscript-manifest.json \
  --out runs/analysis/publication-v1/clean-regeneration-attestation.json
```

## Interpretation limits

- Room-temperature values are extrapolations from high-temperature dynamics;
  non-Arrhenius behavior must be tested and reported.
- Occupancy-constrained structures are reproducible ordered realizations of a
  diffraction model, not a proven thermodynamic ensemble.
- Periodic bulk simulations predict intrinsic transport. They do not contain
  porosity, grain boundaries, secondary phases, electrode effects, or ceramic
  processing history.
- A journal-quartile target is not guaranteed by simulation volume. A defensible
  paper also requires a novel question, external potential validation,
  convergence, uncertainty propagation, and a complete negative-result record.

## Main commands

```bash
uv run matfactory-harvest --help
uv run matfactory-reextract --help
uv run matfactory-md --help
uv run matfactory-campaign --help
uv run matfactory-validate --help
uv run matfactory-compare --help
```
