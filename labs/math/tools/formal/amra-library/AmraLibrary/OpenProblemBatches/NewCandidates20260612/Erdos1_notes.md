# Erdos1 Formalizer Notes

- 2026-06-14: No external web or literature source was used in this Lean iteration.
- Python finite sanity check over all down-closed half-sized families for `n = 1,2,3,4`
  found minimum outer-boundary sizes `1,2,3,6`, matching
  `Nat.choose n (n / 2)` and disproving the stronger shortcut
  `2 ^ (n - 1) ≤ (setFamilyOuterBoundary D).card` at `n = 3,4`.
- 2026-06-14 iteration 2: no external web or literature source was used.
  The exact required verifier command aborted in this sandbox with Lean runtime
  exit 134 and no Lean diagnostic output after the current file was restored to
  the prior Lean footprint. The same file checked successfully with explicit
  `lake env lean -j1 AmraLibrary/OpenProblemBatches/NewCandidates20260612/Erdos1.lean`,
  so the observed failure is a Lean worker/thread runtime issue, not a proof
  error from the file. The target declaration remains absent.
- 2026-06-14 round 8 iteration 1: no external web or literature source was used.
  Exhaustive Python search over all down-closed half-sized families for
  `n = 1,2,3,4,5` found minimum outer-boundary sizes `1,2,3,6,10`,
  matching `Nat.choose n (n / 2)`. The configured run artifact directory was
  read-only in this sandbox, so this workspace note records the tool result.
  Lean now has a checked bridge from the central-layer cardinal form to the
  `Nat.choose` form, but the central-layer boundary theorem itself remains the
  missing combinatorial step.
