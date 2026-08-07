import Mathlib.Algebra.Order.Floor.Defs
import Mathlib.Data.Finset.Card
import Mathlib.Data.Finset.Range
import Mathlib.Data.Nat.Prime.Defs
import Mathlib.Data.Real.Archimedean
import Mathlib.Data.Set.Finite.Basic
import Mathlib.Order.Filter.AtTopBot.Basic

infixr:35 " and " => And
notation3 "forallᶠ "(...)" in "f", "r:(scoped p => Filter.Eventually p f) => r

/-!
Lean scratch target for the 2026-06-12 AMRA attack on Erdos Problem #972.
-/

namespace AmraNewCandidates20260612
namespace Erdos972

open Classical

theorem beatty_prime_pair_count_unbounded_of_eventual_lower_bound
    (C actualCount : Nat -> Nat)
    (hC_unbounded_atTop : forall N X0 : Nat, exists X : Nat, X0 <= X and N <= C X)
    (hLower : forallᶠ X in Filter.atTop, C X <= actualCount X) :
    forall N : Nat, exists X : Nat, N <= actualCount X := by
  intro N
  rw [Filter.eventually_atTop] at hLower
  rcases hLower with ⟨X0, hX0⟩
  rcases hC_unbounded_atTop N X0 with ⟨X, hX_ge, hN_le_C⟩
  exact ⟨X, le_trans hN_le_C (hX0 X hX_ge)⟩

theorem set_infinite_of_unbounded_initial_segment_count
    (S : Set Nat)
    (hCount_unbounded :
      forall N : Nat, exists X : Nat,
        N <= ((Finset.range X).filter (fun p : Nat => p ∈ S)).card) :
    S.Infinite := by
  intro hSfinite
  let T : Finset Nat := hSfinite.toFinset
  rcases hCount_unbounded (T.card + 1) with ⟨X, hcount⟩
  have hsubset : (Finset.range X).filter (fun p : Nat => p ∈ S) ⊆ T := by
    intro p hp
    exact hSfinite.mem_toFinset.mpr ((Finset.mem_filter.mp hp).2)
  exact Nat.not_succ_le_self T.card (le_trans hcount (Finset.card_le_card hsubset))

theorem set_infinite_of_eventual_lower_bound_initial_segment_count
    (S : Set Nat)
    (C : Nat -> Nat)
    (hC_unbounded_atTop :
      forall N X0 : Nat, exists X : Nat, X0 <= X and N <= C X)
    (hLower :
      forallᶠ X in Filter.atTop,
        C X <= ((Finset.range X).filter (fun p : Nat => p ∈ S)).card) :
    S.Infinite := by
  exact set_infinite_of_unbounded_initial_segment_count S
    (beatty_prime_pair_count_unbounded_of_eventual_lower_bound C
      (fun X : Nat => ((Finset.range X).filter (fun p : Nat => p ∈ S)).card)
      hC_unbounded_atTop hLower)

theorem beatty_prime_pair_set_infinite_of_eventual_lower_bound
    (α : ℝ)
    (C : Nat -> Nat)
    (hC_unbounded_atTop :
      forall N X0 : Nat, exists X : Nat, X0 <= X and N <= C X)
    (hLower :
      forallᶠ X in Filter.atTop,
        C X <= ((Finset.range X).filter
          (fun p : Nat => Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊)).card) :
    ({p : Nat | Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊} : Set Nat).Infinite := by
  have hCount_unbounded :
      forall N : Nat, exists X : Nat,
        N <= ((Finset.range X).filter
          (fun p : Nat => Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊)).card :=
    beatty_prime_pair_count_unbounded_of_eventual_lower_bound C
      (fun X : Nat => ((Finset.range X).filter
        (fun p : Nat => Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊)).card)
      hC_unbounded_atTop hLower
  intro hfinite
  let T : Finset Nat := hfinite.toFinset
  rcases hCount_unbounded (T.card + 1) with ⟨X, hcount⟩
  have hsubset :
      (Finset.range X).filter
          (fun p : Nat => Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊) ⊆ T := by
    intro p hp
    exact hfinite.mem_toFinset.mpr ((Finset.mem_filter.mp hp).2)
  exact Nat.not_succ_le_self T.card (le_trans hcount (Finset.card_le_card hsubset))

end Erdos972
end AmraNewCandidates20260612
