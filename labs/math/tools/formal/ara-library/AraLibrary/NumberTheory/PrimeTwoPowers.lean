import Mathlib

/-!
Reusable shell for numbers representable as a prime plus two powers of two.

This module is extracted from the ARA Erdős #9 campaign. It contains only the
small verified obstruction that any representation `p + 2^k + 2^l` is at least
`4`, plus immediate consequences for the exceptional odd set.
-/

namespace AraLibrary
namespace PrimeTwoPowers

/-- Numbers representable as `p + 2^k + 2^l` with `p` prime. -/
def RepresentableByPrimeAndTwoPowers (n : ℕ) : Prop :=
  ∃ p k l : ℕ, Nat.Prime p ∧ n = p + 2 ^ k + 2 ^ l

/-- Odd numbers not representable as `p + 2^k + 2^l`. -/
def ExceptionalOddSet : Set ℕ :=
  {n | Odd n ∧ ¬ RepresentableByPrimeAndTwoPowers n}

/-- Any representation `p + 2^k + 2^l` is at least `4`. -/
theorem representable_lower_bound {n p k l : ℕ} (hp : Nat.Prime p)
    (h : n = p + 2 ^ k + 2 ^ l) : 4 ≤ n := by
  subst h
  have hp2 : 2 ≤ p := hp.two_le
  have hk : 1 ≤ 2 ^ k := by exact Nat.one_le_two_pow
  have hl : 1 ≤ 2 ^ l := by exact Nat.one_le_two_pow
  omega

theorem not_representable_one : ¬ RepresentableByPrimeAndTwoPowers 1 := by
  intro hrepr
  rcases hrepr with ⟨p, k, l, hp, hrepr⟩
  have h4 : 4 ≤ 1 := representable_lower_bound hp hrepr
  omega

theorem one_mem_exceptionalOddSet : 1 ∈ ExceptionalOddSet := by
  constructor
  · decide
  · exact not_representable_one

/-- Every odd natural number below `4` is exceptional for this representation shell. -/
theorem odd_lt_four_mem_exceptionalOddSet {n : ℕ} (hodd : Odd n) (hn_lt : n < 4) :
    n ∈ ExceptionalOddSet := by
  constructor
  · exact hodd
  · intro hrepr
    rcases hrepr with ⟨p, k, l, hp, hEq⟩
    have h4 : 4 ≤ n := representable_lower_bound hp hEq
    omega

end PrimeTwoPowers
end AraLibrary
