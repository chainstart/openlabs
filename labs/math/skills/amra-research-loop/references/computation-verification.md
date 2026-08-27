# Replayable mathematics computation profiles

The mathematics lab prepares three trusted computation profiles before a production Codex starts:

- `sage-exact-v10.8` for exact symbolic, algebraic, combinatorial, and number-theoretic work;
- `arb-certified-v10.8` for rigorous real or complex ball enclosures through Sage/Arb;
- `smt-consensus-z3-cvc5-v1` for finitely encoded constraints checked by both Z3 and cvc5.

Prepared runtime records live under `.openlabs/tools/`. Experiment source and its
`openlabs.math_computation.v1` receipt must remain in the active attempt under the profile root:

```text
experiments/
├── sage/
├── arb/
└── smt/
```

These campaign directories are for small replayable source and typed receipts. Put captured solver
streams, bulk model dumps, large tables/JSONL, arrays, and archives under the task's
`transaction.artifact_staging_root`, then declare each payload in the OpenLabs result with its URI
and SHA-256. The typed receipt may refer to those payload artifacts but must not copy their bytes
back into campaign state.

Use the verifier path from the laboratory runtime context. Typical invocations are:

```bash
python3 /trusted/openlabs/labs/math/tools/computation/math_runtime.py run \
  --profile sage-exact-v10.8 --workspace . \
  --source research/cycle-001/target/experiments/sage/check.py \
  --receipt research/cycle-001/target/experiments/sage/verification.json

python3 /trusted/openlabs/labs/math/tools/computation/math_runtime.py run \
  --profile arb-certified-v10.8 --workspace . \
  --source research/cycle-001/target/experiments/arb/bound.py \
  --receipt research/cycle-001/target/experiments/arb/verification.json

python3 /trusted/openlabs/labs/math/tools/computation/math_runtime.py run \
  --profile smt-consensus-z3-cvc5-v1 --workspace . \
  --source research/cycle-001/target/experiments/smt/model.smt2 \
  --expect unsat \
  --receipt research/cycle-001/target/experiments/smt/verification.json
```

A Sage exact script must print exactly one `openlabs.sage_exact_output.v1` JSON object. Each claim
needs `claim_id`, `statement`, and `exact: true`. Do not use floating-point approximations in an
exact claim. The receipt proves reproducible execution under the pinned Sage environment; a
universal theorem still needs a proved completeness reduction or an independent proof.

An Arb script must print one `openlabs.arb_certificate_output.v1` object. Every certificate needs a
precision of at least 53 bits and finite decimal lower/upper bounds produced from Sage
`RealBallField` or `ComplexBallField` computations. State the analytic tail bound and domain
coverage in the source and claim; ball arithmetic does not invent those mathematical reductions.

The SMT profile runs the same SMT-LIB2 source through Z3 and cvc5 and passes only when their complete
decision sequences agree. `sat` proves existence only for the encoded constraints; `unsat` closes a
mathematical case only after a proved, scope-correct encoding and completeness reduction.

All profiles enforce the task reservation and a stricter profile ceiling with address-space, CPU,
wall-clock, file-size, open-file, thread, and captured-output limits. A timeout, signal, output
overflow, engine disagreement, changed input, changed runtime, or malformed typed result produces
no passed receipt.

When a computation is used in promotion audit, add an entry to `audit.computation_checks`:

```json
{
  "profile_id": "arb-certified-v10.8",
  "status": "passed",
  "reason": "The interval enclosure closes the named finite analytic remainder.",
  "evidence": ["experiments/arb/verification.json"]
}
```

The `amra-math` commit validator checks all source hashes and replays every passed computation before
the private attempt can be promoted.
