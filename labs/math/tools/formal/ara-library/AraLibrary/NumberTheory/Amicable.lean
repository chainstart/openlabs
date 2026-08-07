import Mathlib

/-!
Reusable elementary definitions and lemmas for amicable numbers.

This module is extracted from the ARA `amicable-prime-exclusion` campaign and
keeps only the project-independent Lean content.
-/

namespace AraLibrary
namespace Amicable

open BigOperators Finset

/-- The sum of proper divisors of `n`. -/
def properDivisorSum (n : ℕ) : ℕ :=
  ∑ d ∈ n.properDivisors, d

/-- Two positive integers are amicable if each is the proper-divisor sum of the other. -/
def IsAmicablePair (m n : ℕ) : Prop :=
  m ≠ 0 ∧ n ≠ 0 ∧ m ≠ n ∧ properDivisorSum m = n ∧ properDivisorSum n = m

/-- A natural number is amicable if it belongs to some amicable pair. -/
def IsAmicable (n : ℕ) : Prop :=
  ∃ m : ℕ, IsAmicablePair n m

instance (m n : ℕ) : Decidable (IsAmicablePair m n) := by
  unfold IsAmicablePair
  infer_instance

@[simp]
theorem properDivisorSum_zero : properDivisorSum 0 = 0 := by
  simp [properDivisorSum]

@[simp]
theorem properDivisorSum_one : properDivisorSum 1 = 0 := by
  simp [properDivisorSum]

theorem properDivisorSum_prime {p : ℕ} (hp : Nat.Prime p) : properDivisorSum p = 1 := by
  simp [properDivisorSum, hp.properDivisors]

theorem IsAmicablePair.symm {m n : ℕ} (h : IsAmicablePair m n) : IsAmicablePair n m := by
  rcases h with ⟨hm, hn, hne, hmn, hnm⟩
  exact ⟨hn, hm, hne.symm, hnm, hmn⟩

theorem IsAmicablePair.one_lt_left {m n : ℕ} (h : IsAmicablePair m n) : 1 < m := by
  rcases m with _ | _ | m
  · exact (h.1 rfl).elim
  · rcases h with ⟨_, hn, _, hmn, _⟩
    rw [properDivisorSum_one] at hmn
    exact (hn hmn.symm).elim
  · omega

theorem IsAmicablePair.one_lt_right {m n : ℕ} (h : IsAmicablePair m n) : 1 < n := by
  exact h.symm.one_lt_left

theorem not_isAmicable_one : ¬ IsAmicable 1 := by
  intro h
  rcases h with ⟨m, hm⟩
  exact Nat.lt_irrefl 1 hm.one_lt_left

theorem not_isAmicable_prime {p : ℕ} (hp : Nat.Prime p) : ¬ IsAmicable p := by
  intro h
  rcases h with ⟨m, hp0, hm0, hne, hpm, hmp⟩
  have hm : m = 1 := by
    rw [properDivisorSum_prime hp] at hpm
    exact hpm.symm
  have : p = 0 := by
    calc
      p = properDivisorSum 1 := by simpa [hm] using hmp.symm
      _ = 0 := properDivisorSum_one
  exact hp.ne_zero this

end Amicable
end AraLibrary
