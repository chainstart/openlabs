# Physics evidence gates

Use the weakest claim label justified by the complete record.

- `conjecture`: a precise statement with regime and falsifier, but no supporting route.
- `provisional`: debugging, exploratory algebra, pilot numerics or an unreviewed data pattern.
- `supported`: at least one hash-bound route survives basic dimensions, limits and benchmark checks.
- `verified`: at least two independent routes agree, numerical error and truncation are controlled,
  closest prior work has been rechecked, and an adversarial review has no unresolved fatal issue.
- `refuted`: a valid counterexample, contradiction or failed necessary check is preserved.

For every supported or verified claim record:

1. assumptions and conventions;
2. exact regime and observable;
3. evidence IDs and independence groups;
4. dimensional, symmetry, limiting-case and conservation checks that apply;
5. code, input, environment and output hashes for computations;
6. precision, seeds, tolerances, truncation/convergence study and uncertainty budget;
7. closest-work search date and unresolved novelty risk.

Do not promote a result solely because two agents repeated the same derivation or ran the same code.
Independence must come from different information paths or formulations. A negative or inconclusive
result remains a first-class artifact and may be the publishable outcome when it establishes a real
obstruction or excludes a method family.
