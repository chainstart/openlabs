# Erdos 212 coefficient-descent Lean probe

Date: 2026-07-11

No new external web or literature source was used in this formalizer iteration.
The mathematical route was taken from the supplied durable `context_bundle.md`;
the API findings below come from the checked-in Mathlib source in `.lake/packages`.

## Compiling facts

`lean_probe_erdos212_descent.lean` compiles and checks the following route:

- `MvPolynomial.finSuccEquiv` and a one-variable rename followed by
  `MvPolynomial.pUnitAlgEquiv` give an explicit algebra equivalence
  `MvPolynomial (Fin 2) K ≃ₐ[K] Polynomial (Polynomial K)`.
- `Polynomial.resultant_eq_zero_iff` gives the resultant/coprimality criterion
  over a field.
- `Polynomial.finite_setOf_isRoot` gives the required finite-root conclusion
  once a nonzero eliminating polynomial is constructed.
- `Polynomial.IsPrimitive.dvd_of_fraction_map_dvd_fraction_map` reflects
  divisibility of primitive polynomials from a fraction field.

## Iteration 2 correction and verified bridge

The previous proposed general `IsRelPrime` bridge was stronger than needed.
The elimination application has an irreducible first polynomial.  The checked
lemma `isCoprime_fraction_map_of_irreducible_not_dvd` now handles exactly that
case: it splits on outer degree zero, and otherwise uses irreducibility to get
primitivity, Gauss's irreducibility equivalence, content/primitive-part
factorization of the second polynomial, and primitive divisibility reflection.
It compiles both in the probe and in the configured target file.

The superseded candidate was:

```lean
theorem isCoprime_fraction_map_of_isRelPrime
    {R F : Type*} [CommRing R] [IsDomain R]
    [NormalizedGCDMonoid R] [Field F] [Algebra R F]
    [IsFractionRing R F]
    (f g : Polynomial R) (hfg : IsRelPrime f g) :
    IsCoprime (f.map (algebraMap R F)) (g.map (algebraMap R F))
```

For the Erdos target, instantiate the new lemma with `R = Polynomial K` and
`F` its fraction field.  This produces a nonzero resultant after mapping.
The next exact blocker is proving that the original resultant in `Polynomial K`
is nonzero (using `map_resultant`) and assembling finite common affine zeros.
The fiber proof must handle the finitely many eliminated-coordinate roots and
show that at each such coordinate the two specializations cannot both be zero;
otherwise their common linear coordinate factor would contradict
nondivisibility by the irreducible polynomial.

Until this finite-common-zero lemma and coefficient decomposition are proved, the exact target
`irreducible_planePolynomial_descends_of_infinite_subfield_zeros` cannot be
introduced without a prohibited trusted assumption or placeholder.

## Iteration 3: nonzero resultant over the coefficient ring

The checked lemma `resultant_ne_zero_of_irreducible_not_dvd` has now been
promoted to `Erdos212.lean`.  It applies the preceding fraction-field
coprimality bridge, obtains a nonzero resultant in `FractionRing (K[X])`, and
uses `Polynomial.resultant_map_map`, injectivity of the fraction map, and
preservation of `natDegree` under an injective map to reflect nonvanishing back
to `K[X]`.

A useful refinement for the next step is to eliminate in both coordinate
directions.  A common affine zero must satisfy both coordinate resultants, so
outside degree-degenerate cases it lies in a product of two finite univariate
root sets.  This avoids building a separate finite-fiber argument for every
exceptional specialization.  The remaining formal work is the evaluation
compatibility for the two `MvPolynomial (Fin 2) K` to `K[X][X]`
equivalences, including the cases where one elimination direction has both
outer degrees zero.

The additional checked wrapper `planePolynomial_resultant_ne_zero_of_irreducible_not_dvd`
now supplies this nonzero resultant directly for `MvPolynomial (Fin 2) K`.
Its proof also certifies that the explicit two-variable algebra equivalence
preserves irreducibility and reflects divisibility.

No external source was used.  The API check was performed against the local
Mathlib sources and compiled with `lake env lean lean_probe_erdos212_descent.lean`.

## Iteration 4: evaluation and both elimination directions

The target file now contains two additional checked interfaces:

- `eval_resultant_eq_zero_of_common_zero` applies the Sylvester Bézout
  identity and the bivariate evaluation ring homomorphism to show that a
  common affine zero is a root of the coefficient-variable resultant whenever
  at least one outer degree is nonzero.
- `planePolynomialEquiv_evalEval` proves, by ring-homomorphism extensionality,
  that the explicit nested-univariate equivalence evaluates at `(p 1, p 0)`
  exactly as the original multivariate polynomial evaluates at `p`.

The swapped-coordinate equivalence `planePolynomialSwapEquiv`, its evaluation
lemma, and its nonzero-resultant theorem also compile.  Thus both coordinates
can be bounded by finite univariate root sets in the nondegenerate-degree
case.

The exact remaining elimination case is when both nested polynomials have
outer degree zero in one orientation.  Mathlib's resultant is then `1`, so the
Bézout-root lemma intentionally requires a nonzero outer degree.  The next
proof should either show that this degree-degenerate orientation has no common
zero using irreducibility/nondivisibility, or replace the second polynomial by
`X * f + g` in that branch (which preserves common zeros and nondivisibility
while forcing positive outer degree).  Once both coordinate roots are
obtained, `Set.Finite.pi` packages them into a finite subset of `Fin 2 → K`.

No external web or literature source was used in this iteration.  All API
checks were performed against local Mathlib and verified by Lean.

## Iteration 5: finite common affine zero set

The degree-degenerate elimination branch is now closed.  The checked lemma
`exists_elimination_polynomial` uses the ordinary resultant when either outer
degree is positive.  When both vanish, it replaces `g` by `X * f + g`; this
preserves every common zero with `f`, preserves `¬ f ∣ g`, and has outer degree
one because irreducibility implies `f ≠ 0`.

Applying this construction after both coordinate orientations yields the
verified theorem `finite_common_affine_zeros_of_irreducible_not_dvd`.  Each
coordinate of a common zero belongs to the root set of a nonzero univariate
elimination polynomial, and `Set.Finite.pi` makes their product finite.

The next blocker is coefficient descent itself: decompose the finite set of
real coefficients of `f` over the intermediate field `K`, obtain component
polynomials over `K`, and use the new finite-common-zero theorem plus the
infinite set `P` to show every nonzero mapped component is divisible by `f`.
One must then prove that a component supported inside `support f` and divisible
by `f` has constant quotient, allowing normalization by one nonzero real
coefficient.

No external source was used.  The Lean probe and configured target verifier
both passed.

## Iteration 6: verified coefficient descent

The coefficient-space step is now complete.  The checked helper
`planePolynomialCoeffComponent` takes one Hamel-basis coordinate of every
coefficient of the real polynomial.  Its evaluation lemma proves that, at a
point over the intermediate field, evaluation commutes with taking this
coordinate.  Hence every such component vanishes on `P`.

It suffices to select one component which is nonzero at a chosen support
monomial of `f`.  Injectivity of `K → ℝ` preserves infinitude of the image of
`P`; `finite_common_affine_zeros_of_irreducible_not_dvd` therefore forces `f`
to divide the mapped component.  The component has support contained in that
of `f`.  Total-degree additivity in the domain `MvPolynomial (Fin 2) ℝ` then
forces the quotient to have total degree zero, hence to be a constant.  Its
constant is nonzero because the selected component is nonzero, and inversion
gives the scalar in the requested theorem statement.

The small check in `lean_probe_erdos212_coeff.lean` and the configured verifier
both pass.  No external web or literature source was used in this iteration.
