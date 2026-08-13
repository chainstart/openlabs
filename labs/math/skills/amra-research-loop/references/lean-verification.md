# Lean verification profile

OpenLabs mathematics tasks receive the trusted `lean4-mathlib-v4.26.0` profile before Codex
starts. Runtime preparation is recorded at `.openlabs/tools/lean-runtime.json` in the private
attempt. The compiler and Mathlib cache are shared read-only; every project source and verification
receipt remains inside the writable campaign attempt.

Use Lean after the exact statement and dependencies stabilize, or earlier when a small formal probe
can decisively reject an interface. Do not use file volume or successful parsing as mathematical
evidence.

Place target-local files under the active AMRA campaign:

```text
formal/lean/
├── Main.lean
├── Helper.lean
└── verification.json
```

From the lane workspace, invoke the verifier path recorded in the prepared-runtime receipt. A
typical command is:

```bash
python3 /trusted/openlabs/labs/math/tools/formal/lean_runtime.py verify \
  --workspace . \
  --source research/cycle-001/target/formal/lean/Main.lean \
  --input research/cycle-001/target/formal/lean/Helper.lean \
  --declaration OpenLabs.Target.main_theorem \
  --receipt research/cycle-001/target/formal/lean/verification.json
```

The verifier runs the pinned Lean kernel with `lean.sorry` promoted to an error, records every input
hash, and audits the named declarations with `#print axioms`. Only `propext`, `Quot.sound`, and
`Classical.choice` are permitted by the default profile. Declare every theorem that supports the
scientific claim; helper compilation alone is not a proof receipt.

Every Lean subprocess runs inside a hard memory cgroup and also receives address-space, Lean heap,
CPU-time, wall-clock, file-size, open-file, process/thread, and captured-output limits. The default
verification ceiling is computed from the WSL kernel-visible resources: 75% of physical memory,
75% of available CPU threads, and 300 seconds of wall time. The normal task reservation is a
scheduler estimate, not Lean's hard ceiling. Lean checks are serialized, and all factory workers
together remain below the `openlabs-workers.slice` 80% physical-memory ceiling. Swap remains
disabled for these cgroups so a runaway elaboration fails instead of turning a large resident set
into an unbounded swap storm. Exceeding any limit fails the verification and writes no passed
receipt. Do not retry an out-of-memory proof by bypassing the verifier; split the source closure
while preserving the theorem boundary or change the trusted profile deliberately.

For `audit.formalization_check.status: passed`, list `formal/lean/verification.json` relative to the
AMRA campaign in `evidence`. Also bind the main `.lean` source, every imported project-local source,
and the receipt as SHA-256 artifacts in the task result. The `amra-math` commit validator rechecks
the hashes and reruns Lean from the private attempt before promotion.

Use `not_feasible` only with a concrete missing-library or unsuitable-statement explanation. It is
not an alias for “not attempted,” and formalization does not replace independent reconstruction,
novelty review, analytic dependency review, or counterexample search.
