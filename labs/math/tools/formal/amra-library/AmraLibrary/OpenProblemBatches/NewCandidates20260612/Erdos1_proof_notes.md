# Erdos1 negative signed cut notes

## Empty-set obstruction

No external web or literature sources were used.

Lean probe run from `/home/biostar/work/projects/amra/amra_library/formal`:

```bash
lake env lean --stdin
```

The probe used standalone copies of the local shapes of `IsSumDistinctSet`,
`signedSum`, and `negativeSignedCut`, then checked the following facts:

- `IsSumDistinctSet (∅ : Finset ℕ) 0`
- `(negativeSignedCut (∅ : Finset ℕ) emptyEnum).card = 0`
- `¬ (2 * (negativeSignedCut (∅ : Finset ℕ) emptyEnum).card =
  2 ^ (∅ : Finset ℕ).card)`

Conclusion: `negativeSignedCut_card_eq_half_cube` is false as currently stated.
For `A = ∅`, the hypotheses are satisfiable and the claimed equation reduces
to `0 = 1`.

The configured run artifact directory was read-only during this check, so this
workspace note records the nontrivial tool result instead of
`lean_probe_log.md` in the run directory.

## Iteration 2 verifier result

No external web, literature, or source references were used.

The Lean file now contains a checked certificate:

- `empty_sum_distinct : IsSumDistinctSet (∅ : Finset ℕ) 0`
- `negativeSignedCut_card_eq_half_cube_empty_counterexample`, proving the
  requested equation fails for the empty set and the empty enumeration.

Required verifier command:

```bash
env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/NewCandidates20260612/Erdos1.lean
```

Result: passed with no emitted diagnostics.

## Iff classification verifier result

No external web or literature sources were used. The proof relies on local
proof-lab context, the verified theorem
`negativeSignedCut_card_eq_half_cube_of_card_pos`, and the empty-cardinality
calculation already present in `Erdos1.lean`.

Added theorem:

```lean
negativeSignedCut_card_eq_half_cube_iff_card_pos
```

Required verifier command:

```bash
env LEAN_NUM_THREADS=1 OMP_NUM_THREADS=1 lake env lean AmraLibrary/OpenProblemBatches/NewCandidates20260612/Erdos1.lean
```

Result: passed with no emitted diagnostics.
