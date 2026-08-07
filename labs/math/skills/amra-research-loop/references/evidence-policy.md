# Evidence policy

Classify mathematical and publication maturity separately.

## Required dimensions

- `statement_match`: Check all quantifiers, parameter ranges, variants, and compound subquestions.
- `mathematical_status`: Use `proved`, `refuted`, `conditional`, `finite`, or `open`.
- `machine_reproduced`: Record the exact command, environment, and artifact hash when applicable.
- `independent_reconstruction`: Require a reviewer who did not author the candidate proof.
- `novelty_check`: Compare against primary literature; use `priority_uncertain` when unresolved.
- `publication_state`: Keep private note, public manuscript, preprint, accepted, and published distinct.

## Evidence strength

1. Exact kernel-checked or independently replayed formal proof.
2. Independently reconstructed natural proof with all dependencies checked.
3. Exact symbolic, SAT, or finite certificate plus a proved completeness reduction.
4. Author-verified natural proof or computation.
5. Conditional derivation with named open inputs.
6. Finite experiment, heuristic, analogy, or candidate.

Never convert levels 4–6 into a universal theorem through summary language.

## Negative evidence

Retain counterexamples to bridges, failed invariants, and no-go theorems. Record precisely what they refute and what they leave open. Negative route evidence is valuable but does not close the public problem unless it directly contradicts the public statement.
