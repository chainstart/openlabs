import Mathlib.Algebra.Order.Floor.Defs
import Mathlib.Data.Finset.Card
import Mathlib.Data.Finset.Range
import Mathlib.Data.Nat.Prime.Defs
import Mathlib.Data.Real.Archimedean
import Mathlib.NumberTheory.Real.Irrational
import Mathlib.Data.Set.Finite.Basic
import Mathlib.Order.Filter.AtTopBot.Basic

namespace AmraErdosFiveQueue20260703
namespace Erdos972

/- Queued promotion file for Erdos #972.  Local work should package conditional
   counting-to-infinitude bridges; the analytic lower bound itself must remain
   a named source theorem/contract. -/

open Classical

theorem beatty_prime_pair_count_unbounded_of_eventual_lower_bound
    (C actualCount : Nat -> Nat)
    (hC_unbounded_atTop :
      forall N X0 : Nat, exists X : Nat, X0 <= X /\ N <= C X)
    (hLower : Filter.Eventually (fun X : Nat => C X <= actualCount X) Filter.atTop) :
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

theorem beatty_prime_pair_set_infinite_of_eventual_lower_bound
    (α : ℝ)
    (C : Nat -> Nat)
    (hC_unbounded_atTop :
      forall N X0 : Nat, exists X : Nat, X0 <= X /\ N <= C X)
    (hLower :
      Filter.Eventually
        (fun X : Nat =>
          C X <= ((Finset.range X).filter
            (fun p : Nat => Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊)).card)
        Filter.atTop) :
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

theorem beatty_prime_pair_vonMangoldt_hypothesis_source_contract
    (hSource :
      forall α : ℝ, α > 1 -> Irrational α ->
        exists C : Nat -> Nat,
          (forall N X0 : Nat, exists X : Nat, X0 <= X /\ N <= C X) /\
          Filter.Eventually
            (fun X : Nat =>
              C X <= ((Finset.range X).filter
                (fun p : Nat => Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊)).card)
            Filter.atTop) :
    forall α : ℝ, α > 1 -> Irrational α ->
      ({p : Nat | Nat.Prime p ∧ Nat.Prime ⌊(α * p)⌋₊} : Set Nat).Infinite := by
  intro α hα hα_irr
  rcases hSource α hα hα_irr with ⟨C, hC_unbounded_atTop, hLower⟩
  exact beatty_prime_pair_set_infinite_of_eventual_lower_bound α C
    hC_unbounded_atTop hLower

end Erdos972
end AmraErdosFiveQueue20260703
