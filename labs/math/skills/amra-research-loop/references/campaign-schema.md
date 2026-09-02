# Campaign schema

## Canonical files

- `campaign_state.json`: Identity, immutable SHA-256 bindings for both statements, source locator,
  problem id, title, target relation, success type, source-authority bundle, and gate policy;
  current phase, artifact map, and append-only transition history.
- `closure_contract.json`: The exact source-original statement, the separately frozen local target,
  their typed relation (`exact`, `specialization`, `strengthening`, or `partial`), source,
  published comparator, admissible inputs, false-world controls, non-cosmetic consequence,
  success conditions, and outcomes that do not count. Only a whitespace-normalized exact match may
  use `original_problem_closed`; every non-exact target is a scoped theorem.
- `information_loss_map.json`: Inherited methods and their precise information losses.
- `representations.json`: Candidate representations with new information and first test.
- `mechanisms.json`: Decisive candidate claims, typed `would_close` outcomes, and their status. A
  proved survivor must include the contract's frozen success condition.
- `kill_tests.json`: Evidenced falsification records keyed by mechanism id.
- `survivors.json`: One to three selected mechanisms and rationale.
- `decisive_lemma.json`: Strongest deepened claim, exact scope, unconditional inputs,
  non-cosmetic consequence, status, typed closure effect, evidence, and gaps. A proved lemma must
  include the contract's frozen success condition in `closes`.
- `audit.json`: Independent reconstruction plus statement, hypothesis, dependency, counterexample,
  literature, novelty, formalization, and typed computation checks. Formalization may be marked
  infeasible only with a concrete reason. A computation marked `passed` must cite a replayable
  `openlabs.math_computation.v1` receipt.
- `decision.json`: Promotion or freeze decision tied to the closure contract.

Proof-authority evidence in `decisive_lemma.evidence`,
`audit.independent_reconstruction.evidence`, passed formalization/computation checks, and a promote
decision uses objects of the form
`{"path": "relative/path", "sha256": "<64 lowercase hex>"}`. The validator rejects missing
files, path escapes, and digest mismatches. Plain descriptive strings are not promotion evidence.
Every promote decision requires
`audit.independent_reconstruction.control_plane_receipt`, itself a hash-bound reference to an
`openlabs.result_receipt.v2` inside the canonical OpenLabs receipt archive. This is required for
every promotion, not only original-problem closure. Validation rechecks the canonical SQLite task,
fresh reviewer attempt, direct author-to-reviewer lineage, successful ingestion gate, Stop hook,
result path, and all hashes. A copied or self-authored campaign-local receipt is not authority.

The reviewer result is `openlabs.result_bundle.v1` with the
`openlabs.amra_review.v1` extension defined in
`../schemas/amra-review-result-extension.schema.json`. It must set
`amra_review_schema_version`, `amra_audit_outcome: passed`, `amra_campaign_id`,
`amra_statement_identity`, `amra_author_attempt_id`, `amra_resolution_type`, and
`amra_success_condition`, bind `amra_review_manifest_sha256`, and carry exactly one evidenced `verified` claim whose id is
`amra-<hyphenated-success-condition>`.

At `independent_audit`, first commit the final promote decision and its resolution type, then run:

```bash
python3 amra-research-loop/scripts/research_loop.py prepare-review \
  --campaign <path> \
  --author-attempt-id <canonical-author-attempt-id>
```

This writes `audit/review-manifest.json`, hashing the closure contract, information-loss map,
representations, mechanisms, kill tests, survivors, decisive lemma, decision, and all hash-bound
evidence referenced by those files. The fresh reviewer must audit those exact bytes and return the
manifest digest. Editing proof bytes after manifest preparation invalidates promotion.

## Core commands

Initialize:

```bash
python3 amra-research-loop/scripts/research_loop.py init \
  --root amra-research-loop/campaigns \
  --campaign-id erdos-809-potential \
  --problem-id erdos-809 \
  --title "Global reserve potential" \
  --source-statement "Exact public statement" \
  --target-statement "Exact public statement" \
  --target-relation exact \
  --source "Primary source URL or repository path" \
  --source-authority-receipt radar/cycle-NNN/selection.json
```

Do not silently copy a narrowed local target into `source_original_statement`. For a
specialization, strengthening, or partial result, preserve the full source statement, freeze the
different local statement in `frozen_target_statement`, and use `scoped_theorem_proved`. A stronger
local theorem may later serve as evidence in a separate exact-source closure campaign, but it is
not itself typed as `original_problem_closed`.

Initialization binds both normalized statements, source locator, problem id, title, relation,
success type, source authority, and gate policy into
`statement_identity` and the first history record. Changing a target or downgrading its success
criterion requires a new campaign or an explicit route branch; editing these fields in place makes
both validation paths fail.

For every non-exact contract, `mechanisms[*].would_close` and `decisive_lemma.closes` must not
contain `original_problem_closed`. Use the canonical `scoped_theorem_proved` token when the proof
artifact actually closes the frozen scoped target; descriptive labels may be included in addition.

Migrate a legacy v1 contract explicitly; `--target-statement` must match its old
`exact_statement`, so migration cannot be used to rewrite the local theorem:

```bash
python3 amra-research-loop/scripts/research_loop.py migrate-contract \
  --campaign <path> \
  --source-statement "Exact full statement from the primary source" \
  --target-statement "The unchanged legacy local target" \
  --target-relation partial \
  --reason "Separate the source problem from the prior scoped target"
```

The migration preserves a prior classification in `classification_history`, writes the corrected
success type, and appends a statement-identity binding event. It stages and validates the complete
replacement tree before a directory commit. If existing proof/audit tokens conflict with the new
scope, or a terminal campaign lacks current authority, migration refuses without changing live
files. Legacy exact campaigns must be reinitialized from a verified primary-source receipt.

Validate and advance:

```bash
python3 amra-research-loop/scripts/research_loop.py validate --campaign <path>
python3 amra-research-loop/scripts/research_loop.py advance --campaign <path> --to <next-phase>
```

Record mechanisms through `add-mechanism`; use `set-mechanism-status` after an evidenced test. When marking a mechanism `killed`, add a matching entry to `kill_tests.json` with `outcome: "killed"` and nonempty `evidence`.

Freeze through the CLI so transition history and `decision.json` remain synchronized.
