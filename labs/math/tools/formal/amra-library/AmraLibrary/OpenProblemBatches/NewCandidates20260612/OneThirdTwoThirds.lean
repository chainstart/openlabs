import Mathlib.Algebra.Order.Field.Rat
import Mathlib.Data.Finset.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Data.Nat.Cast.Order.Field
import Mathlib.Order.Interval.Set.Defs
import Mathlib.Tactic.Linarith

/-!
Lean scratch target for the 2026-06-12 AMRA attack on the 1/3-2/3 conjecture.
-/

namespace AmraNewCandidates20260612
namespace OneThirdTwoThirds

notation:50 lhs:50 " in " rhs:50 => Membership.mem rhs lhs

theorem oneThird_twoThirds_count_ratio_Icc
    (A T : Nat)
    (hT : 0 < T)
    (hLower : T <= 3 * A)
    (hUpper : 3 * A <= 2 * T) :
    ((A : Rat) / (T : Rat)) in Set.Icc (1 / 3 : Rat) (2 / 3 : Rat) := by
  have hTQ : (0 : Rat) < (T : Rat) := by
    exact_mod_cast hT
  have hLowerQ : (T : Rat) <= 3 * (A : Rat) := by
    exact_mod_cast hLower
  have hUpperQ : 3 * (A : Rat) <= 2 * (T : Rat) := by
    exact_mod_cast hUpper
  constructor
  · rw [le_div_iff₀ hTQ]
    linarith
  · rw [div_le_iff₀ hTQ]
    linarith

theorem oneThird_twoThirds_certificate_sound
    {n : ℕ} [PartialOrder (Fin n)]
    (exts : Finset (Equiv.Perm (Fin n))) (x y : Fin n)
    (h_exts : ∀ σ : Equiv.Perm (Fin n),
      σ ∈ exts ↔ ∀ i j : Fin n, σ i ≤ σ j → i.val ≤ j.val)
    (h_total_pos : 0 < exts.card)
    (h_lower :
      exts.card ≤
        3 * (exts.filter
          (fun σ => (σ.symm x).val < (σ.symm y).val)).card)
    (h_upper :
      3 * (exts.filter
          (fun σ => (σ.symm x).val < (σ.symm y).val)).card ≤
        2 * exts.card) :
    (((exts.filter
        (fun σ => (σ.symm x).val < (σ.symm y).val)).card : ℚ) /
        (exts.card : ℚ)) ∈ Set.Icc (1 / 3 : ℚ) (2 / 3 : ℚ) := by
  have _ := h_exts
  let good : Finset (Equiv.Perm (Fin n)) :=
    exts.filter (fun σ => (σ.symm x).val < (σ.symm y).val)
  have hLower : exts.card ≤ 3 * good.card := by
    simpa [good] using h_lower
  have hUpper : 3 * good.card ≤ 2 * exts.card := by
    simpa [good] using h_upper
  change ((good.card : ℚ) / (exts.card : ℚ)) ∈ Set.Icc (1 / 3 : ℚ) (2 / 3 : ℚ)
  exact oneThird_twoThirds_count_ratio_Icc good.card exts.card h_total_pos hLower hUpper

end OneThirdTwoThirds
end AmraNewCandidates20260612
