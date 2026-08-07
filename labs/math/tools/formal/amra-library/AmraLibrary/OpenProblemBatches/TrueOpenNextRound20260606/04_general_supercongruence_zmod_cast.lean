import Mathlib.Data.ZMod.Basic
import Mathlib.Algebra.Field.ZMod
import Mathlib.Data.Rat.Lemmas
import Mathlib.Data.Nat.Choose.Basic
import Mathlib.Data.Nat.Choose.Sum
import Mathlib.Data.Nat.Prime.Basic
import Mathlib.Data.Nat.GCD.BigOperators
import Mathlib.Data.Nat.Totient
import Mathlib.Algebra.BigOperators.Intervals
import Mathlib.Algebra.BigOperators.GroupWithZero.Finset
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Tactic.Ring

namespace OeisA357513

noncomputable def u (m : ℕ) (n : ℕ) : ℕ :=
  ∑ k ∈ (Finset.Icc 1 n),
    ((n.choose k : ℚ) ^ 2 * ((n + k).choose k : ℚ) ^ 2) / k ^ (2 * m + 1) |>.num.natAbs

end OeisA357513

namespace OeisA357513NextRound20260606

open scoped BigOperators

syntax (name := finsetProdInCompat) "∏ " ident " in " term ", " term : term
macro_rules
  | `(∏ $x:ident in $s:term, $body:term) => `(Finset.prod $s (fun $x => $body))

syntax (name := finsetSumInCompat) "∑ " ident " in " term ", " term : term
macro_rules
  | `(∑ $x:ident in $s:term, $body:term) => `(Finset.sum $s (fun $x => $body))

lemma zmod_nat_cast_mul_self_eq_zero_mod_square (p : ℕ) :
    ((p * p : ℕ) : ZMod (p ^ 2)) = 0 := by
  rw [ZMod.natCast_eq_zero_iff]
  simp [pow_two]

lemma zmod_nat_cast_self_sq_eq_zero_mod_square (p : ℕ) :
    ((p : ZMod (p ^ 2)) ^ 2) = 0 := by
  simpa [pow_two, Nat.cast_mul] using zmod_nat_cast_mul_self_eq_zero_mod_square p

lemma zmod_range_coprime_mod_square (p k : ℕ)
    (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    Nat.Coprime k (p ^ 2) := by
  have hklt : k < p := by
    exact lt_of_le_of_lt hkp (Nat.sub_one_lt (Nat.ne_of_gt hp.pos))
  have hnot : ¬ p ∣ k := Nat.not_dvd_of_pos_of_lt hk1 hklt
  simpa using hp.coprime_pow_of_not_dvd (m := 2) hnot

lemma zmod_range_coprime_mod_fourth_power (p k : ℕ)
    (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    Nat.Coprime k (p ^ 4) := by
  have hklt : k < p := by
    exact lt_of_le_of_lt hkp (Nat.sub_one_lt (Nat.ne_of_gt hp.pos))
  have hnot : ¬ p ∣ k := Nat.not_dvd_of_pos_of_lt hk1 hklt
  simpa using hp.coprime_pow_of_not_dvd (m := 4) hnot

lemma zmod_unit_denominator_for_range
    (p k : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    IsUnit (k : ZMod (p ^ 4)) := by
  rw [ZMod.isUnit_iff_coprime]
  exact zmod_range_coprime_mod_fourth_power p k hp hk1 hkp

set_option maxHeartbeats 20000
lemma zmod_p_minus_one_choose_factor_expansion_mod_p4_aux
    (p k : ℕ) (hp : p.Prime) (hkp : k ≤ p - 1) :
    (((p - 1).choose k : ZMod (p ^ 4))) =
      (-1 : ZMod (p ^ 4)) ^ k *
        Finset.prod (Finset.Icc 1 k)
          (fun j => 1 - (p : ZMod (p ^ 4)) * (j : ZMod (p ^ 4))⁻¹) := by
  induction k with
  | zero =>
      rw [Nat.choose_zero_right, pow_zero,
        Finset.Icc_eq_empty_of_lt (by norm_num : (0 : ℕ) < 1), Finset.prod_empty,
        mul_one]
      exact Nat.cast_one
  | succ k ih =>
      let R := ZMod (p ^ 4)
      have hk_le : k ≤ p - 1 := le_trans (Nat.le_succ k) hkp
      have ih' :
          (((p - 1).choose k : R)) =
        (-1 : R) ^ k *
          Finset.prod (Finset.Icc 1 k)
            (fun j => 1 - (p : R) * (j : R)⁻¹) := by
        exact ih hk_le
      have hunit : IsUnit (((k + 1 : ℕ) : R)) :=
        zmod_unit_denominator_for_range p (k + 1) hp (Nat.succ_pos k) hkp
      have hrec :
          (((p - 1).choose (k + 1) : R) * ((k + 1 : ℕ) : R)) =
            ((p - 1).choose k : R) * ((p - 1 - k : ℕ) : R) := by
        have hrec_nat := Nat.choose_succ_right_eq (p - 1) k
        have hrec_cast := congrArg (fun n : ℕ => (n : R)) hrec_nat
        simpa only [Nat.cast_mul] using hrec_cast
      have hcancel :
          (((p - 1).choose (k + 1) : R)) =
            (((p - 1).choose k : R)) *
              (((p - 1 - k : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹)) := by
        calc
          (((p - 1).choose (k + 1) : R))
              = (((p - 1).choose (k + 1) : R)) *
                  (((k + 1 : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹)) := by
                rw [ZMod.mul_inv_of_unit _ hunit, mul_one]
          _ = (((p - 1).choose (k + 1) : R) * ((k + 1 : ℕ) : R)) *
                  (((k + 1 : ℕ) : R)⁻¹) := by
                rw [mul_assoc]
          _ = (((p - 1).choose k : R) * ((p - 1 - k : ℕ) : R)) *
                  (((k + 1 : ℕ) : R)⁻¹) := by
                exact congrArg (fun x : R => x * (((k + 1 : ℕ) : R)⁻¹)) hrec
          _ = (((p - 1).choose k : R)) *
              (((p - 1 - k : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹)) := by
                exact mul_assoc ((p - 1).choose k : R) ((p - 1 - k : ℕ) : R)
                  (((k + 1 : ℕ) : R)⁻¹)
      have hkp' : k + 1 ≤ p := by
        exact le_trans hkp (Nat.sub_le p 1)
      have hfactor :
          ((p - 1 - k : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹) =
            (-1 : R) *
              (1 - (p : R) * (((k + 1 : ℕ) : R)⁻¹)) := by
        have hsub_nat : p - 1 - k = p - (k + 1) := by
          rw [Nat.sub_sub, Nat.add_comm]
        have hcast : ((p - 1 - k : ℕ) : R) = (p : R) - ((k + 1 : ℕ) : R) := by
          rw [hsub_nat]
          exact Nat.cast_sub hkp'
        have hmul : ((k + 1 : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹) = 1 :=
          ZMod.mul_inv_of_unit _ hunit
        calc
          ((p - 1 - k : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹)
              = ((p : R) - ((k + 1 : ℕ) : R)) *
                  (((k + 1 : ℕ) : R)⁻¹) := by
                rw [hcast]
          _ = (p : R) * (((k + 1 : ℕ) : R)⁻¹) -
                  ((k + 1 : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹) := by
                rw [sub_mul]
          _ = (p : R) * (((k + 1 : ℕ) : R)⁻¹) - 1 := by
                exact congrArg
                  (fun x : R => (p : R) * (((k + 1 : ℕ) : R)⁻¹) - x) hmul
          _ = (-1 : R) *
                (1 - (p : R) * (((k + 1 : ℕ) : R)⁻¹)) := by
                rw [neg_one_mul, neg_sub]
      calc
        (((p - 1).choose (k + 1) : R))
            = (((p - 1).choose k : R)) *
              (((p - 1 - k : ℕ) : R) * (((k + 1 : ℕ) : R)⁻¹)) := hcancel
        _ = ((-1 : R) ^ k *
              Finset.prod (Finset.Icc 1 k)
                (fun j => 1 - (p : R) * (j : R)⁻¹)) *
              ((-1 : R) *
                (1 - (p : R) * (((k + 1 : ℕ) : R)⁻¹))) := by
              rw [ih', hfactor]
        _ = (-1 : R) ^ (k + 1) *
              Finset.prod (Finset.Icc 1 (k + 1))
                (fun j => 1 - (p : R) * (j : R)⁻¹) := by
              let P : R :=
                Finset.prod (Finset.Icc 1 k)
                  (fun j => 1 - (p : R) * (j : R)⁻¹)
              let F : R := 1 - (p : R) * (((k + 1 : ℕ) : R)⁻¹)
              have hpow : (-1 : R) ^ (k + 1) = (-1 : R) ^ k * (-1 : R) := by
                rw [pow_succ]
              rw [Finset.prod_Icc_succ_top (Nat.succ_pos k), hpow]
              change (((-1 : R) ^ k * P) * ((-1 : R) * F)) =
                (((-1 : R) ^ k * (-1 : R)) * (P * F))
              rw [mul_assoc]
              rw [← mul_assoc P (-1 : R) F]
              rw [mul_comm P (-1 : R)]
              rw [mul_assoc (-1 : R) P F]
              rw [← mul_assoc ((-1 : R) ^ k) (-1 : R) (P * F)]

lemma zmod_p_minus_one_choose_factor_expansion_mod_p4
    (p k : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    (((p - 1).choose k : ZMod (p ^ 4))) =
      (-1 : ZMod (p ^ 4)) ^ k *
        Finset.prod (Finset.Icc 1 k)
          (fun j => 1 - (p : ZMod (p ^ 4)) * (j : ZMod (p ^ 4))⁻¹) := by
  have _ := hk1
  exact zmod_p_minus_one_choose_factor_expansion_mod_p4_aux p k hp hkp

lemma zmod_p_add_choose_factor_expansion_mod_p4_aux
    (p t : ℕ) (hp : p.Prime) (ht : t + 1 ≤ p - 1) :
    let R := ZMod (p ^ 4)
    (((p + t).choose (t + 1) : R)) =
      (p : R) * (((t + 1 : ℕ) : R)⁻¹) *
        Finset.prod (Finset.Icc 1 t)
          (fun j => 1 + (p : R) * (j : R)⁻¹) := by
  induction t with
  | zero =>
      let R := ZMod (p ^ 4)
      change (((p + 0).choose (0 + 1) : R)) =
        (p : R) * (((0 + 1 : ℕ) : R)⁻¹) *
          Finset.prod (Finset.Icc 1 0)
            (fun j : ℕ => 1 + (p : R) * (j : R)⁻¹)
      rw [Nat.choose_one_right, Finset.Icc_eq_empty_of_lt
        (by norm_num : (0 : ℕ) < 1), Finset.prod_empty]
      rw [mul_one]
      have hone : (((0 + 1 : ℕ) : R)) = 1 := by norm_num
      rw [hone]
      have hinvone : ((1 : R)⁻¹) = 1 := by
        calc
          ((1 : R)⁻¹) = (1 : R) * ((1 : R)⁻¹) := by rw [one_mul]
          _ = 1 := ZMod.mul_inv_of_unit (1 : R) isUnit_one
      rw [hinvone, mul_one, Nat.add_zero]
  | succ t ih =>
      let R := ZMod (p ^ 4)
      have ht_prev : t + 1 ≤ p - 1 := le_trans (Nat.le_succ (t + 1)) ht
      have ih' :
          (((p + t).choose (t + 1) : R)) =
        (p : R) * (((t + 1 : ℕ) : R)⁻¹) *
          Finset.prod (Finset.Icc 1 t)
            (fun j => 1 + (p : R) * (j : R)⁻¹) := by
        exact ih ht_prev
      have hunit_prev : IsUnit (((t + 1 : ℕ) : R)) :=
        zmod_unit_denominator_for_range p (t + 1) hp (Nat.succ_pos t) ht_prev
      have hunit_next : IsUnit ((((t + 1) + 1 : ℕ) : R)) :=
        zmod_unit_denominator_for_range p ((t + 1) + 1) hp (Nat.succ_pos (t + 1)) ht
      have hrec :
          (((p + (t + 1)).choose ((t + 1) + 1) : R) *
              (((t + 1) + 1 : ℕ) : R)) =
            ((p + t).choose (t + 1) : R) * (((p + t) + 1 : ℕ) : R) := by
        have hrec_nat := (Nat.add_one_mul_choose_eq (p + t) (t + 1)).symm
        have hrec_cast := congrArg (fun n : ℕ => (n : R)) hrec_nat
        have hrec_cast' :
            (((p + (t + 1)).choose ((t + 1) + 1) : R) *
                (((t + 1) + 1 : ℕ) : R)) =
              (((p + t) + 1 : ℕ) : R) * ((p + t).choose (t + 1) : R) := by
          simpa only [Nat.cast_mul, Nat.add_assoc] using hrec_cast
        exact hrec_cast'.trans
          (mul_comm (((p + t) + 1 : ℕ) : R) ((p + t).choose (t + 1) : R))
      have hcancel :
          (((p + (t + 1)).choose ((t + 1) + 1) : R)) =
            ((p + t).choose (t + 1) : R) *
              ((((p + t) + 1 : ℕ) : R) * ((((t + 1) + 1 : ℕ) : R)⁻¹)) := by
        calc
          (((p + (t + 1)).choose ((t + 1) + 1) : R))
              = (((p + (t + 1)).choose ((t + 1) + 1) : R)) *
                  ((((t + 1) + 1 : ℕ) : R) *
                    ((((t + 1) + 1 : ℕ) : R)⁻¹)) := by
                rw [ZMod.mul_inv_of_unit _ hunit_next, mul_one]
          _ = (((p + (t + 1)).choose ((t + 1) + 1) : R) *
                  (((t + 1) + 1 : ℕ) : R)) *
                  ((((t + 1) + 1 : ℕ) : R)⁻¹) := by
                exact (mul_assoc ((p + (t + 1)).choose ((t + 1) + 1) : R)
                  (((t + 1) + 1 : ℕ) : R) (((((t + 1) + 1 : ℕ) : R)⁻¹))).symm
          _ = (((p + t).choose (t + 1) : R) * (((p + t) + 1 : ℕ) : R)) *
                  ((((t + 1) + 1 : ℕ) : R)⁻¹) := by
                exact congrArg
                  (fun x : R => x * (((((t + 1) + 1 : ℕ) : R)⁻¹))) hrec
          _ = ((p + t).choose (t + 1) : R) *
              ((((p + t) + 1 : ℕ) : R) * ((((t + 1) + 1 : ℕ) : R)⁻¹)) := by
                exact mul_assoc ((p + t).choose (t + 1) : R)
                  (((p + t) + 1 : ℕ) : R) (((((t + 1) + 1 : ℕ) : R)⁻¹))
      have hfactor :
          (((t + 1 : ℕ) : R)⁻¹) * (((p + t) + 1 : ℕ) : R) =
            1 + (p : R) * (((t + 1 : ℕ) : R)⁻¹) := by
        have hcast : (((p + t) + 1 : ℕ) : R) = (p : R) + ((t + 1 : ℕ) : R) := by
          have hadd : (p + t) + 1 = p + (t + 1) := by omega
          rw [hadd, Nat.cast_add]
        have hmul : (((t + 1 : ℕ) : R)⁻¹) * ((t + 1 : ℕ) : R) = 1 := by
          simpa [mul_comm] using ZMod.mul_inv_of_unit (((t + 1 : ℕ) : R)) hunit_prev
        calc
          (((t + 1 : ℕ) : R)⁻¹) * (((p + t) + 1 : ℕ) : R)
              = (((t + 1 : ℕ) : R)⁻¹) *
                  ((p : R) + ((t + 1 : ℕ) : R)) := by
                rw [hcast]
          _ = (((t + 1 : ℕ) : R)⁻¹) * (p : R) +
                  (((t + 1 : ℕ) : R)⁻¹) * ((t + 1 : ℕ) : R) := by
                rw [mul_add]
          _ = (((t + 1 : ℕ) : R)⁻¹) * (p : R) + 1 := by
                rw [hmul]
          _ = 1 + (p : R) * (((t + 1 : ℕ) : R)⁻¹) := by
                ac_rfl
      calc
        (((p + (t + 1)).choose ((t + 1) + 1) : R))
            = ((p + t).choose (t + 1) : R) *
              ((((p + t) + 1 : ℕ) : R) * ((((t + 1) + 1 : ℕ) : R)⁻¹)) := hcancel
        _ = ((p : R) * (((t + 1 : ℕ) : R)⁻¹) *
              Finset.prod (Finset.Icc 1 t)
                (fun j => 1 + (p : R) * (j : R)⁻¹)) *
              ((((p + t) + 1 : ℕ) : R) * ((((t + 1) + 1 : ℕ) : R)⁻¹)) := by
              rw [ih']
        _ = ((p : R) *
              (Finset.prod (Finset.Icc 1 t)
                (fun j => 1 + (p : R) * (j : R)⁻¹) *
                ((((t + 1 : ℕ) : R)⁻¹) * (((p + t) + 1 : ℕ) : R)))) *
                ((((t + 1) + 1 : ℕ) : R)⁻¹) := by
              ac_rfl
        _ = ((p : R) *
              (Finset.prod (Finset.Icc 1 t)
                (fun j => 1 + (p : R) * (j : R)⁻¹) *
                (1 + (p : R) * (((t + 1 : ℕ) : R)⁻¹)))) *
                ((((t + 1) + 1 : ℕ) : R)⁻¹) := by
              rw [hfactor]
        _ = (p : R) * ((((t + 1) + 1 : ℕ) : R)⁻¹) *
              Finset.prod (Finset.Icc 1 (t + 1))
                (fun j => 1 + (p : R) * (j : R)⁻¹) := by
              rw [Finset.prod_Icc_succ_top (Nat.succ_pos t)]
              let P : R := Finset.prod (Finset.Icc 1 t)
                (fun j => 1 + (p : R) * (j : R)⁻¹)
              let F : R := 1 + (p : R) * (((t + 1 : ℕ) : R)⁻¹)
              let V : R := ((((t + 1) + 1 : ℕ) : R)⁻¹)
              change ((p : R) * (P * F)) * V = (p : R) * V * (P * F)
              ac_rfl

lemma zmod_p_minus_one_add_choose_factor_expansion_mod_p4
    (p k : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    let R := ZMod (p ^ 4)
    (((p - 1 + k).choose k : R)) =
      (p : R) * ((k : R)⁻¹) *
        Finset.prod (Finset.Icc 1 (k - 1))
          (fun j => 1 + (p : R) * (j : R)⁻¹) := by
  let R := ZMod (p ^ 4)
  have ht : (k - 1) + 1 ≤ p - 1 := by
    simpa [Nat.sub_add_cancel hk1] using hkp
  have htop : p + (k - 1) = p - 1 + k := by
    have hp1 : 1 ≤ p := Nat.succ_le_of_lt hp.pos
    calc
      p + (k - 1) = p + k - 1 := by
        rw [Nat.add_sub_assoc hk1 p]
      _ = p - 1 + k := by
        rw [Nat.sub_add_comm hp1]
  have haux := zmod_p_add_choose_factor_expansion_mod_p4_aux p (k - 1) hp ht
  change (((p - 1 + k).choose k : R)) =
    (p : R) * ((k : R)⁻¹) *
      Finset.prod (Finset.Icc 1 (k - 1))
        (fun j => 1 + (p : R) * (j : R)⁻¹)
  change (((p + (k - 1)).choose ((k - 1) + 1) : R)) =
    (p : R) * ((((k - 1) + 1 : ℕ) : R)⁻¹) *
      Finset.prod (Finset.Icc 1 (k - 1))
        (fun j => 1 + (p : R) * (j : R)⁻¹) at haux
  rw [Nat.sub_add_cancel hk1] at haux
  rw [htop] at haux
  exact haux

lemma square_zero_mul_prod_one_add
    {R : Type*} [CommSemiring R]
    (s : Finset ℕ) (q : R) (b : ℕ → R) (hq : q ^ 2 = 0) :
    q * Finset.prod s (fun x => 1 + q * b x) = q := by
  refine Finset.induction_on s ?base ?step
  · rw [Finset.prod_empty, mul_one]
  · intro a s has ih
    rw [Finset.prod_insert has]
    let P := Finset.prod s (fun x => 1 + q * b x)
    change q * ((1 + q * b a) * P) = q
    calc
      q * ((1 + q * b a) * P)
          = (q * (1 + q * b a)) * P := by
            rw [mul_assoc]
      _ = q * P := by
            have hqa : q * (1 + q * b a) = q := by
              calc
                q * (1 + q * b a) = q + q ^ 2 * b a := by
                  rw [mul_add, mul_one]
                  rw [show q * (q * b a) = q ^ 2 * b a by rw [pow_two, mul_assoc]]
                _ = q := by rw [hq, zero_mul, add_zero]
            rw [hqa]
      _ = q := ih

lemma square_zero_mul_prod_one_add_sq
    {R : Type*} [CommSemiring R]
    (s : Finset ℕ) (q : R) (b : ℕ → R) (hq : q ^ 2 = 0) :
    q * (Finset.prod s (fun x => 1 + q * b x)) ^ 2 = q := by
  let P := Finset.prod s (fun x => 1 + q * b x)
  have hP : q * P = q := square_zero_mul_prod_one_add s q b hq
  calc
    q * P ^ 2 = (q * P) * P := by
      rw [pow_two, mul_assoc]
    _ = q * P := by
      rw [hP]
      exact hP
    _ = q := hP

lemma zmod_pair_factor_collapse_mod_square (p k : ℕ)
    (_hk : Nat.Coprime k (p ^ 2)) :
    (1 - (p : ZMod (p ^ 2)) * (k : ZMod (p ^ 2))⁻¹) *
      (1 + (p : ZMod (p ^ 2)) * (k : ZMod (p ^ 2))⁻¹) = 1 := by
  let R := ZMod (p ^ 2)
  change (1 - (p : R) * (k : R)⁻¹) *
      (1 + (p : R) * (k : R)⁻¹) = 1
  have hp2 : ((p : R) ^ 2) = 0 := by
    simpa [R] using zmod_nat_cast_self_sq_eq_zero_mod_square p
  calc
    (1 - (p : R) * (k : R)⁻¹) * (1 + (p : R) * (k : R)⁻¹)
        = 1 - ((p : R) * (k : R)⁻¹) ^ 2 := by ring
    _ = 1 := by
      rw [mul_pow, hp2, zero_mul, sub_zero]

lemma zmod_pair_factor_product_collapse_mod_square (p : ℕ) (hp : p.Prime) :
    Finset.prod (Finset.Icc 1 (p - 1))
        (fun k => (1 - (p : ZMod (p ^ 2)) * (k : ZMod (p ^ 2))⁻¹)) *
      Finset.prod (Finset.Icc 1 (p - 1))
        (fun k => (1 + (p : ZMod (p ^ 2)) * (k : ZMod (p ^ 2))⁻¹)) = 1 := by
  rw [← Finset.prod_mul_distrib]
  apply Finset.prod_eq_one
  intro k hk
  exact zmod_pair_factor_collapse_mod_square p k
    (zmod_range_coprime_mod_square p k hp (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2)

lemma zmod_inv_pow_of_unit {n : ℕ} (x : ZMod n) (hx : IsUnit x) (r : ℕ) :
    (x ^ r)⁻¹ = x⁻¹ ^ r := by
  apply ZMod.inv_eq_of_mul_eq_one
  rw [← mul_pow, ZMod.mul_inv_of_unit x hx]
  simp

lemma zmod_nat_cast_self_pow_four_eq_zero_mod_p4 (p : ℕ) :
    ((p : ZMod (p ^ 4)) ^ 4) = 0 := by
  simpa [Nat.cast_pow] using
    (ZMod.natCast_pow_eq_zero_of_le p (m := 4) (n := 4) le_rfl)

lemma zmod_nat_cast_self_sq_sq_eq_zero_mod_p4 (p : ℕ) :
    (((p : ZMod (p ^ 4)) ^ 2) ^ 2) = 0 := by
  rw [← pow_mul]
  exact zmod_nat_cast_self_pow_four_eq_zero_mod_p4 p

lemma zmod_paired_factor_product_sq_kill_by_p2_mod_p4 (p k : ℕ) :
    let R := ZMod (p ^ 4)
    (p : R) ^ 2 *
      (Finset.prod (Finset.Icc 1 (k - 1))
          (fun j => 1 - (p : R) * (j : R)⁻¹) *
        Finset.prod (Finset.Icc 1 (k - 1))
          (fun j => 1 + (p : R) * (j : R)⁻¹)) ^ 2 =
      (p : R) ^ 2 := by
  let R := ZMod (p ^ 4)
  let q : R := (p : R) ^ 2
  change q *
      (Finset.prod (Finset.Icc 1 (k - 1))
          (fun j => 1 - (p : R) * (j : R)⁻¹) *
        Finset.prod (Finset.Icc 1 (k - 1))
          (fun j => 1 + (p : R) * (j : R)⁻¹)) ^ 2 =
      q
  have hq : q ^ 2 = 0 := by
    simpa [q] using zmod_nat_cast_self_sq_sq_eq_zero_mod_p4 p
  calc
    q *
        (Finset.prod (Finset.Icc 1 (k - 1))
            (fun j => 1 - (p : R) * (j : R)⁻¹) *
          Finset.prod (Finset.Icc 1 (k - 1))
            (fun j => 1 + (p : R) * (j : R)⁻¹)) ^ 2
        =
        q *
          (Finset.prod (Finset.Icc 1 (k - 1))
            (fun j =>
              (1 - (p : R) * (j : R)⁻¹) *
                (1 + (p : R) * (j : R)⁻¹))) ^ 2 := by
          rw [Finset.prod_mul_distrib]
    _ =
        q *
          (Finset.prod (Finset.Icc 1 (k - 1))
            (fun j => 1 + q * (-(((j : R)⁻¹) ^ 2)))) ^ 2 := by
          congr 2
          apply Finset.prod_congr rfl
          intro j _hj
          simp [q]
          ring
    _ = q :=
        square_zero_mul_prod_one_add_sq (Finset.Icc 1 (k - 1)) q
          (fun j => -(((j : R)⁻¹) ^ 2)) hq

set_option maxHeartbeats 50000 in
lemma zmod_hypergeometric_summand_expansion_mod_p4
    (p k m : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    let R := ZMod (p ^ 4)
    ((((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹)) =
      (p : R) ^ 2 * (((k : R) ^ (2 * m + 3))⁻¹) -
        (2 : R) * (p : R) ^ 3 * (((k : R) ^ (2 * m + 4))⁻¹) := by
  let R := ZMod (p ^ 4)
  change ((((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹)) =
      (p : R) ^ 2 * (((k : R) ^ (2 * m + 3))⁻¹) -
        (2 : R) * (p : R) ^ 3 * (((k : R) ^ (2 * m + 4))⁻¹)
  let Pm : R :=
    Finset.prod (Finset.Icc 1 (k - 1))
      (fun j => 1 - (p : R) * (j : R)⁻¹)
  let Pp : R :=
    Finset.prod (Finset.Icc 1 (k - 1))
      (fun j => 1 + (p : R) * (j : R)⁻¹)
  let u : R := (k : R)⁻¹
  have hunit : IsUnit (k : R) :=
    zmod_unit_denominator_for_range p k hp hk1 hkp
  have hlower := zmod_p_minus_one_choose_factor_expansion_mod_p4 p k hp hk1 hkp
  have hupper := zmod_p_minus_one_add_choose_factor_expansion_mod_p4 p k hp hk1 hkp
  change (((p - 1).choose k : R)) =
      (-1 : R) ^ k *
        Finset.prod (Finset.Icc 1 k)
          (fun j => 1 - (p : R) * (j : R)⁻¹) at hlower
  change (((p - 1 + k).choose k : R)) =
      (p : R) * ((k : R)⁻¹) *
        Finset.prod (Finset.Icc 1 (k - 1))
          (fun j => 1 + (p : R) * (j : R)⁻¹) at hupper
  have hsplit :
      Finset.prod (Finset.Icc 1 k)
          (fun j => 1 - (p : R) * (j : R)⁻¹) =
        Pm * (1 - (p : R) * u) := by
    have hkpred : k - 1 + 1 = k := Nat.sub_add_cancel hk1
    rw [← hkpred]
    change Finset.prod (Finset.Icc 1 (k - 1 + 1))
          (fun j => 1 - (p : R) * (j : R)⁻¹) =
        Pm * (1 - (p : R) * u)
    rw [Finset.prod_Icc_succ_top (by simpa [hkpred] using hk1)]
    simp [Pm, u, hkpred]
  have hcollapse : (p : R) ^ 2 * (Pm * Pp) ^ 2 = (p : R) ^ 2 := by
    simpa [R, Pm, Pp] using zmod_paired_factor_product_sq_kill_by_p2_mod_p4 p k
  have hp4 : (p : R) ^ 4 = 0 := by
    simpa [R] using zmod_nat_cast_self_pow_four_eq_zero_mod_p4 p
  have hinv1 :
      (((k : R) ^ (2 * m + 1))⁻¹) = u ^ (2 * m + 1) := by
    simpa [u] using zmod_inv_pow_of_unit (k : R) hunit (2 * m + 1)
  have hinv3 :
      (((k : R) ^ (2 * m + 3))⁻¹) = u ^ (2 * m + 3) := by
    simpa [u] using zmod_inv_pow_of_unit (k : R) hunit (2 * m + 3)
  have hinv4 :
      (((k : R) ^ (2 * m + 4))⁻¹) = u ^ (2 * m + 4) := by
    simpa [u] using zmod_inv_pow_of_unit (k : R) hunit (2 * m + 4)
  rw [hlower, hupper, hsplit, hinv1, hinv3, hinv4]
  have hsign : ((-1 : R) ^ k * (Pm * (1 - (p : R) * u))) ^ 2 =
      (Pm * (1 - (p : R) * u)) ^ 2 := by
    calc
      ((-1 : R) ^ k * (Pm * (1 - (p : R) * u))) ^ 2
          = ((-1 : R) ^ k) ^ 2 * (Pm * (1 - (p : R) * u)) ^ 2 := by
            rw [mul_pow]
      _ = (Pm * (1 - (p : R) * u)) ^ 2 := by
            have hneg : ((-1 : R) ^ k) ^ 2 = 1 := by
              rw [← pow_mul]
              have hEven : Even (k * 2) := ⟨k, by omega⟩
              exact hEven.neg_one_pow
            rw [hneg, one_mul]
  rw [hsign]
  calc
    (Pm * (1 - (p : R) * u)) ^ 2 *
          ((p : R) * u * Pp) ^ 2 * u ^ (2 * m + 1)
        =
        ((p : R) ^ 2 * (Pm * Pp) ^ 2) *
          (u ^ 2 * u ^ (2 * m + 1)) *
          (1 - (p : R) * u) ^ 2 := by
          ring
    _ =
        (p : R) ^ 2 * u ^ (2 * m + 3) -
          (2 : R) * (p : R) ^ 3 * u ^ (2 * m + 4) := by
          rw [hcollapse]
          have hpow1 : 2 + (2 * m + 1) = 2 * m + 3 := by omega
          rw [← pow_add, hpow1]
          have hsucc : 2 * m + 3 + 1 = 2 * m + 4 := by omega
          have hpowu : u ^ (2 * m + 4) = u ^ (2 * m + 3) * u := by
            rw [← hsucc, pow_succ]
          rw [hpowu]
          calc
            (p : R) ^ 2 * u ^ (2 * m + 3) * (1 - (p : R) * u) ^ 2
                =
                (p : R) ^ 2 * u ^ (2 * m + 3) -
                  (2 : R) * (p : R) ^ 3 * (u ^ (2 * m + 3) * u) +
                    (p : R) ^ 4 * (u ^ (2 * m + 3) * u ^ 2) := by
                  ring
            _ =
                (p : R) ^ 2 * u ^ (2 * m + 3) -
                  (2 : R) * (p : R) ^ 3 * (u ^ (2 * m + 3) * u) := by
                  rw [hp4, zero_mul, add_zero]

lemma finset_mul_sum_left
    {R : Type*} [Semiring R] {ι : Type*}
    (s : Finset ι) (a : R) (f : ι → R) :
    a * Finset.sum s f = Finset.sum s (fun x => a * f x) := by
  classical
  refine Finset.induction_on s ?base ?step
  · simp
  · intro x s hx ih
    rw [Finset.sum_insert hx, Finset.sum_insert hx, mul_add, ih]

set_option maxHeartbeats 50000 in
lemma zmod_hypergeometric_sum_expansion_mod_p4
    (p m : ℕ) (hp : p.Prime) :
    let R := ZMod (p ^ 4)
    (∑ k in Finset.Icc 1 (p - 1),
      (((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹)) =
      (p : R) ^ 2 *
        (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 3))⁻¹)) -
      (2 : R) * (p : R) ^ 3 *
        (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 4))⁻¹)) := by
  let R := ZMod (p ^ 4)
  change
    (∑ k in Finset.Icc 1 (p - 1),
      (((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹)) =
      (p : R) ^ 2 *
        (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 3))⁻¹)) -
      (2 : R) * (p : R) ^ 3 *
        (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 4))⁻¹))
  calc
    (∑ k in Finset.Icc 1 (p - 1),
      (((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹))
        =
        ∑ k in Finset.Icc 1 (p - 1),
          ((p : R) ^ 2 * (((k : R) ^ (2 * m + 3))⁻¹) -
            (2 : R) * (p : R) ^ 3 * (((k : R) ^ (2 * m + 4))⁻¹)) := by
          apply Finset.sum_congr rfl
          intro k hk
          exact zmod_hypergeometric_summand_expansion_mod_p4 p k m hp
            (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2
    _ =
      (p : R) ^ 2 *
        (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 3))⁻¹)) -
      (2 : R) * (p : R) ^ 3 *
        (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 4))⁻¹)) := by
      rw [Finset.sum_sub_distrib]
      rw [← finset_mul_sum_left, ← finset_mul_sum_left]

lemma zmod_prime_isUnit_of_ne_zero
    (p : ℕ) [NeZero p] (hp : p.Prime) {x : ZMod p} (hx : x ≠ 0) :
    IsUnit x := by
  rw [← ZMod.natCast_zmod_val x]
  rw [ZMod.isUnit_iff_coprime]
  have hvalne : x.val ≠ 0 := by
    intro h
    exact hx ((ZMod.val_eq_zero x).mp h)
  have hnot : ¬ p ∣ x.val :=
    Nat.not_dvd_of_pos_of_lt (Nat.pos_of_ne_zero hvalne) (ZMod.val_lt x)
  exact (hp.coprime_iff_not_dvd.mpr hnot).symm

lemma zmod_p_dvd_p_fourth_power (p : ℕ) : p ∣ p ^ 4 := by
  rw [show p ^ 4 = p * p ^ 3 by ring]
  exact dvd_mul_right p (p ^ 3)

lemma zmod_p_dvd_p_square_power (p : ℕ) : p ∣ p ^ 2 := by
  rw [pow_two]
  exact dvd_mul_right p p

lemma zmod_p_square_dvd_p_fourth_power (p : ℕ) : p ^ 2 ∣ p ^ 4 := by
  rw [show p ^ 4 = p ^ 2 * p ^ 2 by
    rw [← pow_add]]
  exact dvd_mul_right (p ^ 2) (p ^ 2)

lemma zmod_p3_mul_eq_zero_of_cast_mod_p_eq_zero
    (p : ℕ) (hp : p.Prime) (x : ZMod (p ^ 4))
    (hx : ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p) x = 0) :
    (p : ZMod (p ^ 4)) ^ 3 * x = 0 := by
  haveI : NeZero p := ⟨Nat.ne_of_gt hp.pos⟩
  haveI : NeZero (p ^ 4) := ⟨pow_ne_zero 4 (Nat.ne_of_gt hp.pos)⟩
  have hdiv : p ∣ x.val := by
    have hvalzero : (x.val : ZMod p) = 0 := by
      change ZMod.cast x = 0 at hx
      rw [ZMod.cast_eq_val] at hx
      exact hx
    exact (ZMod.natCast_eq_zero_iff x.val p).mp hvalzero
  rw [← ZMod.natCast_zmod_val x]
  rw [← Nat.cast_pow, ← Nat.cast_mul]
  rw [ZMod.natCast_eq_zero_iff]
  rcases hdiv with ⟨a, ha⟩
  refine ⟨a, ?_⟩
  rw [ha]
  rw [show p ^ 3 * (p * a) = p ^ 4 * a by
    rw [show p ^ 4 = p ^ 3 * p by ring]
    rw [Nat.mul_assoc]]

lemma zmod_p_mul_eq_zero_of_cast_mod_p_eq_zero
    (p : ℕ) (hp : p.Prime) (x : ZMod (p ^ 2))
    (hx : ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p) x = 0) :
    (p : ZMod (p ^ 2)) * x = 0 := by
  haveI : NeZero p := ⟨Nat.ne_of_gt hp.pos⟩
  haveI : NeZero (p ^ 2) := ⟨pow_ne_zero 2 (Nat.ne_of_gt hp.pos)⟩
  have hdiv : p ∣ x.val := by
    have hvalzero : (x.val : ZMod p) = 0 := by
      change ZMod.cast x = 0 at hx
      rw [ZMod.cast_eq_val] at hx
      exact hx
    exact (ZMod.natCast_eq_zero_iff x.val p).mp hvalzero
  have hxval : (x.val : ZMod (p ^ 2)) = x := ZMod.natCast_zmod_val x
  calc
    (p : ZMod (p ^ 2)) * x =
        (p : ZMod (p ^ 2)) * (x.val : ZMod (p ^ 2)) := by rw [hxval]
    _ = ((p * x.val : ℕ) : ZMod (p ^ 2)) := by rw [Nat.cast_mul]
    _ = 0 := by
      rw [ZMod.natCast_eq_zero_iff]
      rcases hdiv with ⟨a, ha⟩
      refine ⟨a, ?_⟩
      rw [ha]
      rw [show p * (p * a) = p ^ 2 * a by
        rw [pow_two]
        rw [Nat.mul_assoc]]

lemma zmod_p2_mul_eq_zero_of_cast_mod_p2_eq_zero
    (p : ℕ) (hp : p.Prime) (x : ZMod (p ^ 4))
    (hx : ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2)) x = 0) :
    (p : ZMod (p ^ 4)) ^ 2 * x = 0 := by
  haveI : NeZero (p ^ 2) := ⟨pow_ne_zero 2 (Nat.ne_of_gt hp.pos)⟩
  haveI : NeZero (p ^ 4) := ⟨pow_ne_zero 4 (Nat.ne_of_gt hp.pos)⟩
  have hdiv : p ^ 2 ∣ x.val := by
    have hvalzero : (x.val : ZMod (p ^ 2)) = 0 := by
      change ZMod.cast x = 0 at hx
      rw [ZMod.cast_eq_val] at hx
      exact hx
    exact (ZMod.natCast_eq_zero_iff x.val (p ^ 2)).mp hvalzero
  rw [← ZMod.natCast_zmod_val x]
  rw [← Nat.cast_pow, ← Nat.cast_mul]
  rw [ZMod.natCast_eq_zero_iff]
  rcases hdiv with ⟨a, ha⟩
  refine ⟨a, ?_⟩
  rw [ha]
  rw [show p ^ 2 * (p ^ 2 * a) = p ^ 4 * a by
    rw [show p ^ 4 = p ^ 2 * p ^ 2 by
      rw [← pow_add]]
    rw [Nat.mul_assoc]]

lemma zmod_unit_denominator_for_range_mod_square
    (p k : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    IsUnit (k : ZMod (p ^ 2)) := by
  rw [ZMod.isUnit_iff_coprime]
  exact zmod_range_coprime_mod_square p k hp hk1 hkp

lemma zmod_sum_Icc_cast_eq_sum_univ_erase
    {A : Type*} [AddCommMonoid A] (p : ℕ) [NeZero p] (hp : p.Prime)
    (f : ZMod p → A) :
    (∑ k in Finset.Icc 1 (p - 1), f (k : ZMod p)) =
      ∑ x in (Finset.univ.erase (0 : ZMod p)), f x := by
  refine Finset.sum_bij (s := Finset.Icc 1 (p - 1))
    (t := Finset.univ.erase (0 : ZMod p))
    (f := fun k => f (k : ZMod p)) (g := f)
    (fun k _ => (k : ZMod p)) ?_ ?_ ?_ ?_
  · intro k hk
    rw [Finset.mem_erase]
    constructor
    · intro hzero
      have hk' := Finset.mem_Icc.mp hk
      have hklt : k < p :=
        lt_of_le_of_lt hk'.2 (Nat.sub_one_lt (Nat.ne_of_gt hp.pos))
      have hval := congrArg ZMod.val hzero
      rw [ZMod.val_natCast_of_lt hklt, ZMod.val_zero] at hval
      have hkpos : 0 < k := lt_of_lt_of_le zero_lt_one hk'.1
      exact (Nat.ne_of_gt hkpos) hval
    · simp
  · intro a ha b hb hEq
    have ha' := Finset.mem_Icc.mp ha
    have hb' := Finset.mem_Icc.mp hb
    have halt : a < p :=
      lt_of_le_of_lt ha'.2 (Nat.sub_one_lt (Nat.ne_of_gt hp.pos))
    have hblt : b < p :=
      lt_of_le_of_lt hb'.2 (Nat.sub_one_lt (Nat.ne_of_gt hp.pos))
    have hval := congrArg ZMod.val hEq
    rw [ZMod.val_natCast_of_lt halt, ZMod.val_natCast_of_lt hblt] at hval
    exact hval
  · intro x hx
    refine ⟨x.val, ?_, ?_⟩
    · rw [Finset.mem_Icc]
      have hxne : x ≠ 0 := (Finset.mem_erase.mp hx).1
      have hvalne : x.val ≠ 0 := by
        intro h
        exact hxne ((ZMod.val_eq_zero x).mp h)
      constructor
      · exact Nat.succ_le_of_lt (Nat.pos_of_ne_zero hvalne)
      · have hvlt : x.val < p := ZMod.val_lt x
        exact Nat.le_pred_of_lt hvlt
    · exact ZMod.natCast_zmod_val x
  · intro k hk
    rfl

lemma zmod_sum_units_eq_sum_univ_erase_pow
    (p e : ℕ) [Fintype (ZMod p)ˣ] [NeZero p] (hp : p.Prime) :
    Finset.sum (Finset.univ : Finset (ZMod p)ˣ)
        (fun u => ((u : ZMod p) ^ e)) =
      Finset.sum (Finset.univ.erase (0 : ZMod p)) (fun x => x ^ e) := by
  haveI : Fact p.Prime := ⟨hp⟩
  refine Finset.sum_bij (s := (Finset.univ : Finset (ZMod p)ˣ))
    (t := Finset.univ.erase (0 : ZMod p))
    (f := fun u => ((u : ZMod p) ^ e)) (g := fun x => x ^ e)
    (fun u _ => (u : ZMod p)) ?_ ?_ ?_ ?_
  · intro u _hu
    rw [Finset.mem_erase]
    exact ⟨Units.ne_zero u, by simp⟩
  · intro a _ha b _hb h
    exact Units.ext h
  · intro y hy
    have hyne : y ≠ 0 := (Finset.mem_erase.mp hy).1
    have hyunit := zmod_prime_isUnit_of_ne_zero p hp hyne
    rcases hyunit with ⟨u, hu⟩
    refine ⟨u, by simp, ?_⟩
    simpa using hu
  · intro u _hu
    rfl

lemma zmod_sum_univ_erase_inv_pow_eq_sum_univ_erase_pow
    (p e : ℕ) [NeZero p] (hp : p.Prime) :
    Finset.sum (Finset.univ.erase (0 : ZMod p)) (fun x => ((x ^ e)⁻¹)) =
      Finset.sum (Finset.univ.erase (0 : ZMod p)) (fun x => x ^ e) := by
  refine Finset.sum_bij (s := Finset.univ.erase (0 : ZMod p))
    (t := Finset.univ.erase (0 : ZMod p))
    (f := fun x => ((x ^ e)⁻¹)) (g := fun x => x ^ e)
    (fun x _ => x⁻¹) ?_ ?_ ?_ ?_
  · intro x hx
    rw [Finset.mem_erase]
    have hxne : x ≠ 0 := (Finset.mem_erase.mp hx).1
    have hxunit := zmod_prime_isUnit_of_ne_zero p hp hxne
    constructor
    · intro hinvzero
      change x⁻¹ = 0 at hinvzero
      have hxzero : x = 0 := by
        calc
          x = x * (1 : ZMod p) := by rw [mul_one]
          _ = x * (x * x⁻¹) := by rw [ZMod.mul_inv_of_unit x hxunit]
          _ = x * (x * 0) := by rw [hinvzero]
          _ = 0 := by ring
      exact hxne hxzero
    · simp
  · intro a ha b hb hEq
    change a⁻¹ = b⁻¹ at hEq
    have hane : a ≠ 0 := (Finset.mem_erase.mp ha).1
    have hbne : b ≠ 0 := (Finset.mem_erase.mp hb).1
    have haunit := zmod_prime_isUnit_of_ne_zero p hp hane
    have hbunit := zmod_prime_isUnit_of_ne_zero p hp hbne
    calc
      a = (a⁻¹)⁻¹ := by
        exact (ZMod.inv_eq_of_mul_eq_one p (a⁻¹) a
          (ZMod.inv_mul_of_unit a haunit)).symm
      _ = (b⁻¹)⁻¹ := by rw [hEq]
      _ = b := by
        exact ZMod.inv_eq_of_mul_eq_one p (b⁻¹) b
          (ZMod.inv_mul_of_unit b hbunit)
  · intro y hy
    refine ⟨y⁻¹, ?_, ?_⟩
    · rw [Finset.mem_erase]
      have hyne : y ≠ 0 := (Finset.mem_erase.mp hy).1
      have hyunit := zmod_prime_isUnit_of_ne_zero p hp hyne
      constructor
      · intro hinvzero
        have hyzero : y = 0 := by
          calc
            y = y * (1 : ZMod p) := by rw [mul_one]
            _ = y * (y * y⁻¹) := by rw [ZMod.mul_inv_of_unit y hyunit]
            _ = y * (y * 0) := by rw [hinvzero]
            _ = 0 := by ring
        exact hyne hyzero
      · simp
    · have hyne : y ≠ 0 := (Finset.mem_erase.mp hy).1
      have hyunit := zmod_prime_isUnit_of_ne_zero p hp hyne
      exact ZMod.inv_eq_of_mul_eq_one p (y⁻¹) y
        (ZMod.inv_mul_of_unit y hyunit)
  · intro x hx
    have hxne : x ≠ 0 := (Finset.mem_erase.mp hx).1
    have hxunit := zmod_prime_isUnit_of_ne_zero p hp hxne
    simpa using
      (ZMod.inv_eq_of_mul_eq_one p (x ^ e) ((x⁻¹) ^ e)
        (by rw [← mul_pow, ZMod.mul_inv_of_unit x hxunit, one_pow]))

lemma zmod_binom_shift_sub (R : Type*) [CommRing R] (x : R) (e : ℕ) :
    (x + 1) ^ (e + 1) - x ^ (e + 1) =
      Finset.sum (Finset.range (e + 1))
        (fun i => ((e + 1).choose i : R) * x ^ i) := by
  rw [add_pow]
  rw [Finset.sum_range_succ]
  simp [mul_comm]

lemma zmod_sum_univ_pow_eq_zero_of_pos_lt
    (p e : ℕ) [NeZero p] (hp : p.Prime) (hepos : 0 < e) (helt : e < p - 1) :
    (∑ x : ZMod p, x ^ e) = 0 := by
  revert hepos helt
  induction e using Nat.strong_induction_on with
  | h e ih =>
      intro hepos helt
      cases e with
      | zero => omega
      | succ d =>
          let R := ZMod p
          have hshift :
              (∑ x : R, (x + 1) ^ (d + 2)) = ∑ x : R, x ^ (d + 2) := by
            simpa [R] using
              (Equiv.sum_comp (Equiv.addRight (1 : R)) (fun x : R => x ^ (d + 2)))
          have hzero :
              (∑ x : R, ((x + 1) ^ (d + 2) - x ^ (d + 2))) = 0 := by
            rw [Finset.sum_sub_distrib, hshift, sub_self]
          have hsum_expand :
              (∑ x : R, ((x + 1) ^ (d + 2) - x ^ (d + 2))) =
                Finset.sum (Finset.range (d + 2))
                  (fun i => (((d + 2).choose i : R) * (∑ x : R, x ^ i))) := by
            calc
              (∑ x : R, ((x + 1) ^ (d + 2) - x ^ (d + 2))) =
                  ∑ x : R, Finset.sum (Finset.range (d + 2))
                    (fun i => ((d + 2).choose i : R) * x ^ i) := by
                    apply Finset.sum_congr rfl
                    intro x _
                    simpa [Nat.succ_eq_add_one, add_assoc] using
                      zmod_binom_shift_sub R x (d + 1)
              _ =
                  Finset.sum (Finset.range (d + 2))
                    (fun i => ∑ x : R, ((d + 2).choose i : R) * x ^ i) := by
                    rw [Finset.sum_comm]
              _ =
                  Finset.sum (Finset.range (d + 2))
                    (fun i => (((d + 2).choose i : R) * (∑ x : R, x ^ i))) := by
                    apply Finset.sum_congr rfl
                    intro i hi
                    rw [Finset.mul_sum]
          have hlower :
              ∀ i ∈ Finset.range (d + 1),
                (((d + 2).choose i : R) * (∑ x : R, x ^ i)) = 0 := by
            intro i hi
            have hi_lt : i < d + 1 := Finset.mem_range.mp hi
            by_cases hi0 : i = 0
            · subst hi0
              simp [R]
            · have hio : 0 < i := Nat.pos_of_ne_zero hi0
              have hip : i < p - 1 := lt_trans hi_lt (by omega)
              have hih := ih i (by omega) hio hip
              rw [hih, mul_zero]
          rw [hsum_expand] at hzero
          rw [show Finset.range (d + 2) = insert (d + 1) (Finset.range (d + 1)) by
            rw [Finset.range_add_one]] at hzero
          rw [Finset.sum_insert] at hzero
          · rw [Finset.sum_eq_zero hlower, add_zero] at hzero
            have hchoose : (d + 2).choose (d + 1) = d + 2 := by
              simp
            rw [hchoose] at hzero
            have hcoeff : IsUnit (((d + 2 : ℕ) : R)) := by
              rw [ZMod.isUnit_iff_coprime]
              have hd2lt : d + 2 < p := by omega
              have hnot : ¬ p ∣ d + 2 := Nat.not_dvd_of_pos_of_lt (by omega) hd2lt
              exact (hp.coprime_iff_not_dvd.mpr hnot).symm
            exact (IsUnit.mul_right_eq_zero hcoeff).mp hzero
          · simp

lemma zmod_inverse_power_sum_eq_zero_mod_p_of_pos_lt
    (p e : ℕ) (hp : p.Prime) (hepos : 0 < e) (helt : e < p - 1) :
    (∑ k in Finset.Icc 1 (p - 1), (((k : ZMod p) ^ e)⁻¹)) = 0 := by
  classical
  haveI : Fact p.Prime := ⟨hp⟩
  haveI : NeZero p := ⟨Nat.ne_of_gt hp.pos⟩
  haveI : Fintype (ZMod p)ˣ := Fintype.ofFinite (ZMod p)ˣ
  calc
    (∑ k in Finset.Icc 1 (p - 1), (((k : ZMod p) ^ e)⁻¹))
        =
        Finset.sum (Finset.univ.erase (0 : ZMod p)) (fun x => ((x ^ e)⁻¹)) := by
          exact zmod_sum_Icc_cast_eq_sum_univ_erase p hp (fun x => ((x ^ e)⁻¹))
    _ =
        Finset.sum (Finset.univ.erase (0 : ZMod p)) (fun x => x ^ e) := by
          exact zmod_sum_univ_erase_inv_pow_eq_sum_univ_erase_pow p e hp
    _ =
        Finset.sum (Finset.univ : Finset (ZMod p)ˣ)
          (fun u => ((u : ZMod p) ^ e)) := by
          exact (zmod_sum_units_eq_sum_univ_erase_pow p e hp).symm
    _ =
        Finset.sum (Finset.univ.erase (0 : ZMod p)) (fun x => x ^ e) := by
          exact zmod_sum_units_eq_sum_univ_erase_pow p e hp
    _ = ∑ x : ZMod p, x ^ e := by
          rw [Finset.sum_erase]
          simp [Nat.ne_of_gt hepos]
    _ = 0 := zmod_sum_univ_pow_eq_zero_of_pos_lt p e hp hepos helt

lemma zmod_cast_inverse_power_term_mod_p
    (p k e : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p)
        ((((k : ZMod (p ^ 4)) ^ e)⁻¹)) =
      (((k : ZMod p) ^ e)⁻¹) := by
  haveI : Fact p.Prime := ⟨hp⟩
  haveI : NeZero p := ⟨Nat.ne_of_gt hp.pos⟩
  have hunit4 : IsUnit (k : ZMod (p ^ 4)) :=
    zmod_unit_denominator_for_range p k hp hk1 hkp
  have hunitp : IsUnit (k : ZMod p) := by
    rw [← ZMod.natCast_zmod_val (k : ZMod p)]
    rw [ZMod.isUnit_iff_coprime]
    have hklt : k < p :=
      lt_of_le_of_lt hkp (Nat.sub_one_lt (Nat.ne_of_gt hp.pos))
    have hval : (k : ZMod p).val = k := ZMod.val_natCast_of_lt hklt
    rw [hval]
    have hnot : ¬ p ∣ k := Nat.not_dvd_of_pos_of_lt hk1 hklt
    exact (hp.coprime_iff_not_dvd.mpr hnot).symm
  have hmap_inv_k :
      ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p)
          ((k : ZMod (p ^ 4))⁻¹) = ((k : ZMod p)⁻¹) := by
    symm
    apply ZMod.inv_eq_of_mul_eq_one
    calc
      (k : ZMod p) *
          ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p)
            ((k : ZMod (p ^ 4))⁻¹)
          =
          ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p)
            ((k : ZMod (p ^ 4)) * ((k : ZMod (p ^ 4))⁻¹)) := by
            rw [map_mul]
            simp
      _ = 1 := by rw [ZMod.mul_inv_of_unit _ hunit4, map_one]
  rw [zmod_inv_pow_of_unit (k : ZMod (p ^ 4)) hunit4 e]
  rw [map_pow]
  rw [hmap_inv_k]
  exact (zmod_inv_pow_of_unit (k : ZMod p) hunitp e).symm

lemma zmod_cast_inverse_power_term_mod_p_from_p2
    (p k e : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p)
        ((((k : ZMod (p ^ 2)) ^ e)⁻¹)) =
      (((k : ZMod p) ^ e)⁻¹) := by
  haveI : Fact p.Prime := ⟨hp⟩
  haveI : NeZero p := ⟨Nat.ne_of_gt hp.pos⟩
  have hunit2 : IsUnit (k : ZMod (p ^ 2)) :=
    zmod_unit_denominator_for_range_mod_square p k hp hk1 hkp
  have hunitp : IsUnit (k : ZMod p) := by
    rw [← ZMod.natCast_zmod_val (k : ZMod p)]
    rw [ZMod.isUnit_iff_coprime]
    have hklt : k < p :=
      lt_of_le_of_lt hkp (Nat.sub_one_lt (Nat.ne_of_gt hp.pos))
    have hval : (k : ZMod p).val = k := ZMod.val_natCast_of_lt hklt
    rw [hval]
    have hnot : ¬ p ∣ k := Nat.not_dvd_of_pos_of_lt hk1 hklt
    exact (hp.coprime_iff_not_dvd.mpr hnot).symm
  have hmap_inv_k :
      ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p)
          ((k : ZMod (p ^ 2))⁻¹) = ((k : ZMod p)⁻¹) := by
    symm
    apply ZMod.inv_eq_of_mul_eq_one
    calc
      (k : ZMod p) *
          ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p)
            ((k : ZMod (p ^ 2))⁻¹)
          =
          ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p)
            ((k : ZMod (p ^ 2)) * ((k : ZMod (p ^ 2))⁻¹)) := by
            rw [map_mul]
            simp
      _ = 1 := by rw [ZMod.mul_inv_of_unit _ hunit2, map_one]
  rw [zmod_inv_pow_of_unit (k : ZMod (p ^ 2)) hunit2 e]
  rw [map_pow]
  rw [hmap_inv_k]
  exact (zmod_inv_pow_of_unit (k : ZMod p) hunitp e).symm

lemma zmod_cast_inverse_power_term_mod_p2
    (p k e : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1) :
    ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2))
        ((((k : ZMod (p ^ 4)) ^ e)⁻¹)) =
      (((k : ZMod (p ^ 2)) ^ e)⁻¹) := by
  have hunit4 : IsUnit (k : ZMod (p ^ 4)) :=
    zmod_unit_denominator_for_range p k hp hk1 hkp
  have hunit2 : IsUnit (k : ZMod (p ^ 2)) :=
    zmod_unit_denominator_for_range_mod_square p k hp hk1 hkp
  have hmap_inv_k :
      ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2))
          ((k : ZMod (p ^ 4))⁻¹) = ((k : ZMod (p ^ 2))⁻¹) := by
    symm
    apply ZMod.inv_eq_of_mul_eq_one
    calc
      (k : ZMod (p ^ 2)) *
          ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2))
            ((k : ZMod (p ^ 4))⁻¹)
          =
          ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2))
            ((k : ZMod (p ^ 4)) * ((k : ZMod (p ^ 4))⁻¹)) := by
            rw [map_mul]
            simp
      _ = 1 := by rw [ZMod.mul_inv_of_unit _ hunit4, map_one]
  rw [zmod_inv_pow_of_unit (k : ZMod (p ^ 4)) hunit4 e]
  rw [map_pow]
  rw [hmap_inv_k]
  exact (zmod_inv_pow_of_unit (k : ZMod (p ^ 2)) hunit2 e).symm

lemma finset_sum_Icc_reflect_sub
    {A : Type*} [AddCommMonoid A] (p : ℕ) (hp : p.Prime) (f : ℕ → A) :
    (∑ k in Finset.Icc 1 (p - 1), f (p - k)) =
      ∑ k in Finset.Icc 1 (p - 1), f k := by
  have hp0 : 0 < p := hp.pos
  have hIcc : Finset.Icc 1 (p - 1) = Finset.Ico 1 p := by
    ext x
    simp only [Finset.mem_Icc, Finset.mem_Ico]
    omega
  rw [hIcc]
  have h := Finset.sum_Ico_reflect f 1 (m := p) (n := p) (by omega : p ≤ p + 1)
  rw [show p + 1 - p = 1 by omega, show p + 1 - 1 = p by omega] at h
  exact h

lemma pow_one_add_nilpotent_linear
    {R : Type*} [CommRing R] (a : R) (ha2 : a ^ 2 = 0) (n : ℕ) :
    (1 + a) ^ n = 1 + (n : R) * a := by
  induction n with
  | zero => simp
  | succ n ih =>
      rw [pow_succ, ih]
      rw [Nat.cast_succ]
      calc
        (1 + (n : R) * a) * (1 + a) =
            1 + ((n : R) + 1) * a + (n : R) * a ^ 2 := by ring
        _ = 1 + ((n : R) + 1) * a := by rw [ha2, mul_zero, add_zero]

lemma zmod_reflect_inv_power_linear_mod_p2
    (p e : ℕ) (u : ZMod (p ^ 2)) (hodd : Odd e) :
    ((-u) * (1 + (p : ZMod (p ^ 2)) * u)) ^ e =
      - u ^ e - (e : ZMod (p ^ 2)) * (p : ZMod (p ^ 2)) * u ^ (e + 1) := by
  have hp2 : ((p : ZMod (p ^ 2)) * (p : ZMod (p ^ 2))) = 0 := by
    rw [← Nat.cast_mul, ZMod.natCast_eq_zero_iff]
    exact ⟨1, by rw [pow_two, mul_one]⟩
  have ha2 : ((p : ZMod (p ^ 2)) * u) ^ 2 = 0 := by
    rw [show ((p : ZMod (p ^ 2)) * u) ^ 2 =
        ((p : ZMod (p ^ 2)) * (p : ZMod (p ^ 2))) * (u * u) by ring]
    rw [hp2, zero_mul]
  rw [mul_pow]
  rw [pow_one_add_nilpotent_linear ((p : ZMod (p ^ 2)) * u) ha2 e]
  have hneg : (-u) ^ e = - u ^ e := by
    rw [neg_pow]
    rw [hodd.neg_one_pow]
    rw [neg_one_mul]
  rw [hneg]
  have hpow : u ^ e * ((p : ZMod (p ^ 2)) * u) =
      (p : ZMod (p ^ 2)) * u ^ (e + 1) := by
    rw [show u ^ (e + 1) = u ^ e * u by exact pow_succ u e]
    ring
  calc
    -u ^ e * (1 + (e : ZMod (p ^ 2)) * ((p : ZMod (p ^ 2)) * u)) =
        -u ^ e - (e : ZMod (p ^ 2)) * (p : ZMod (p ^ 2)) * u ^ (e + 1) := by
      rw [mul_add, mul_one]
      rw [show -u ^ e * ((e : ZMod (p ^ 2)) * ((p : ZMod (p ^ 2)) * u)) =
          - (e : ZMod (p ^ 2)) * (p : ZMod (p ^ 2)) * u ^ (e + 1) by
        calc
          -u ^ e * ((e : ZMod (p ^ 2)) * ((p : ZMod (p ^ 2)) * u)) =
              - (e : ZMod (p ^ 2)) * (u ^ e * ((p : ZMod (p ^ 2)) * u)) := by ring
          _ = - (e : ZMod (p ^ 2)) * ((p : ZMod (p ^ 2)) * u ^ (e + 1)) := by rw [hpow]
          _ = - (e : ZMod (p ^ 2)) * (p : ZMod (p ^ 2)) * u ^ (e + 1) := by ring]
      ring

lemma zmod_inverse_power_reflect_pair_mod_p2
    (p k e : ℕ) (hp : p.Prime) (hk1 : 1 ≤ k) (hkp : k ≤ p - 1)
    (hodd : Odd e) :
    let R := ZMod (p ^ 2)
    (((k : R) ^ e)⁻¹) + ((((p - k : ℕ) : R) ^ e)⁻¹) =
      - (e : R) * (p : R) * (((k : R) ^ (e + 1))⁻¹) := by
  let R := ZMod (p ^ 2)
  change (((k : R) ^ e)⁻¹) + ((((p - k : ℕ) : R) ^ e)⁻¹) =
      - (e : R) * (p : R) * (((k : R) ^ (e + 1))⁻¹)
  let u : R := (k : R)⁻¹
  have hunitk : IsUnit (k : R) :=
    zmod_unit_denominator_for_range_mod_square p k hp hk1 hkp
  have hk_le_p : k ≤ p := le_trans hkp (Nat.sub_le p 1)
  have hpk1 : 1 ≤ p - k := by omega
  have hpkp : p - k ≤ p - 1 := by omega
  have hunitpk : IsUnit ((p - k : ℕ) : R) :=
    zmod_unit_denominator_for_range_mod_square p (p - k) hp hpk1 hpkp
  have hp2 : ((p : R) * (p : R)) = 0 := by
    rw [← Nat.cast_mul, ZMod.natCast_eq_zero_iff]
    exact ⟨1, by rw [pow_two, mul_one]⟩
  have hcast_sub : (((p - k : ℕ) : R)) = (p : R) - (k : R) := by
    exact Nat.cast_sub hk_le_p
  have hmulku : (k : R) * u = 1 := by
    exact ZMod.mul_inv_of_unit _ hunitk
  have hpk_inv : (((p - k : ℕ) : R)⁻¹) =
      (-u) * (1 + (p : R) * u) := by
    apply ZMod.inv_eq_of_mul_eq_one
    rw [hcast_sub]
    calc
      ((p : R) - (k : R)) * ((-u) * (1 + (p : R) * u))
          =
          -((p : R) * u) * (1 + (p : R) * u) +
            ((k : R) * u) * (1 + (p : R) * u) := by ring
      _ =
          -((p : R) * u) * (1 + (p : R) * u) +
            1 * (1 + (p : R) * u) := by rw [hmulku]
      _ = 1 := by
        have hp2u : ((p : R) * u) * ((p : R) * u) = 0 := by
          calc
            ((p : R) * u) * ((p : R) * u) =
                ((p : R) * (p : R)) * (u * u) := by ring
            _ = 0 := by rw [hp2, zero_mul]
        calc
          -((p : R) * u) * (1 + (p : R) * u) +
              1 * (1 + (p : R) * u) =
              1 - ((p : R) * u) * ((p : R) * u) := by ring
          _ = 1 := by rw [hp2u]; ring
  rw [zmod_inv_pow_of_unit (k : R) hunitk e]
  rw [zmod_inv_pow_of_unit (((p - k : ℕ) : R)) hunitpk e]
  rw [zmod_inv_pow_of_unit (k : R) hunitk (e + 1)]
  change u ^ e + (((p - k : ℕ) : R)⁻¹) ^ e =
      - (e : R) * (p : R) * u ^ (e + 1)
  rw [hpk_inv]
  rw [zmod_reflect_inv_power_linear_mod_p2 p e u hodd]
  ring

lemma zmod_inverse_power_sum_odd_eq_zero_mod_p2_of_pos_lt
    (p e : ℕ) (hp : p.Prime) (hodd : Odd e)
    (h2p : 2 < p) (hepos : 0 < e + 1) (helt : e + 1 < p - 1) :
    (∑ k in Finset.Icc 1 (p - 1), (((k : ZMod (p ^ 2)) ^ e)⁻¹)) = 0 := by
  classical
  let R := ZMod (p ^ 2)
  let S : R := ∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ e)⁻¹)
  let E : R := ∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (e + 1))⁻¹)
  have hcastE : ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p) E = 0 := by
    calc
      ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p) E
          =
          ∑ k in Finset.Icc 1 (p - 1),
            (((k : ZMod p) ^ (e + 1))⁻¹) := by
            change
              ZMod.castHom (zmod_p_dvd_p_square_power p) (ZMod p)
                  (∑ k in Finset.Icc 1 (p - 1),
                    (((k : R) ^ (e + 1))⁻¹)) =
                ∑ k in Finset.Icc 1 (p - 1),
                  (((k : ZMod p) ^ (e + 1))⁻¹)
            rw [map_sum]
            apply Finset.sum_congr rfl
            intro k hk
            exact zmod_cast_inverse_power_term_mod_p_from_p2 p k (e + 1) hp
              (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2
      _ = 0 :=
          zmod_inverse_power_sum_eq_zero_mod_p_of_pos_lt p (e + 1) hp hepos helt
  have hkillE : (p : R) * E = 0 :=
    zmod_p_mul_eq_zero_of_cast_mod_p_eq_zero p hp E hcastE
  have hreflect :
      (∑ k in Finset.Icc 1 (p - 1), ((((p - k : ℕ) : R) ^ e)⁻¹)) = S := by
    exact finset_sum_Icc_reflect_sub p hp (fun k => (((k : R) ^ e)⁻¹))
  have htwoS : (2 : R) * S = 0 := by
    calc
      (2 : R) * S = S + S := by ring
      _ =
          (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ e)⁻¹)) +
            (∑ k in Finset.Icc 1 (p - 1), ((((p - k : ℕ) : R) ^ e)⁻¹)) := by
            rw [hreflect]
      _ =
          ∑ k in Finset.Icc 1 (p - 1),
            ((((k : R) ^ e)⁻¹) + ((((p - k : ℕ) : R) ^ e)⁻¹)) := by
            rw [Finset.sum_add_distrib]
      _ =
          ∑ k in Finset.Icc 1 (p - 1),
            (- (e : R) * (p : R) * (((k : R) ^ (e + 1))⁻¹)) := by
            apply Finset.sum_congr rfl
            intro k hk
            exact zmod_inverse_power_reflect_pair_mod_p2 p k e hp
              (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2 hodd
      _ =
          - (e : R) * ((p : R) * E) := by
            rw [← finset_mul_sum_left]
            simp [E]
            ring
      _ = 0 := by rw [hkillE, mul_zero]
  have hunit2 : IsUnit (2 : R) := by
    change IsUnit (2 : ZMod (p ^ 2))
    exact (ZMod.isUnit_iff_coprime 2 (p ^ 2)).mpr
      (Nat.Coprime.pow_right 2 (Nat.coprime_two_left.mpr (hp.odd_of_ne_two (by omega))))
  exact (IsUnit.mul_right_eq_zero hunit2).mp htwoS

lemma zmod_p3_mul_inverse_power_sum_even_eq_zero_mod_p4_of_large
    (p m : ℕ) (hp : p.Prime) (hlarge : 2 * m + 6 < p) :
    let R := ZMod (p ^ 4)
    (2 : R) * (p : R) ^ 3 *
      (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 4))⁻¹)) = 0 := by
  let R := ZMod (p ^ 4)
  change (2 : R) * (p : R) ^ 3 *
      (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 4))⁻¹)) = 0
  have hepos : 0 < 2 * m + 4 := by omega
  have helt : 2 * m + 4 < p - 1 := by omega
  let S : R := ∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 4))⁻¹)
  have hcastS : ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p) S = 0 := by
    calc
      ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p) S
          =
          ∑ k in Finset.Icc 1 (p - 1),
            (((k : ZMod p) ^ (2 * m + 4))⁻¹) := by
            change
              ZMod.castHom (zmod_p_dvd_p_fourth_power p) (ZMod p)
                  (∑ k in Finset.Icc 1 (p - 1),
                    (((k : R) ^ (2 * m + 4))⁻¹)) =
                ∑ k in Finset.Icc 1 (p - 1),
                  (((k : ZMod p) ^ (2 * m + 4))⁻¹)
            rw [map_sum]
            apply Finset.sum_congr rfl
            intro k hk
            exact zmod_cast_inverse_power_term_mod_p p k (2 * m + 4) hp
              (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2
      _ = 0 :=
          zmod_inverse_power_sum_eq_zero_mod_p_of_pos_lt p (2 * m + 4) hp hepos helt
  have hkill : (p : R) ^ 3 * S = 0 :=
    zmod_p3_mul_eq_zero_of_cast_mod_p_eq_zero p hp S hcastS
  rw [mul_assoc, hkill, mul_zero]

lemma zmod_p2_mul_inverse_power_sum_odd_eq_zero_mod_p4_of_large
    (p m : ℕ) (hp : p.Prime) (hlarge : 2 * m + 6 < p) :
    let R := ZMod (p ^ 4)
    (p : R) ^ 2 *
      (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 3))⁻¹)) = 0 := by
  let R := ZMod (p ^ 4)
  change (p : R) ^ 2 *
      (∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 3))⁻¹)) = 0
  let S : R := ∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 3))⁻¹)
  have hodd : Odd (2 * m + 3) := by
    refine ⟨m + 1, ?_⟩
    omega
  have h2p : 2 < p := by omega
  have hepos : 0 < (2 * m + 3) + 1 := by omega
  have helt : (2 * m + 3) + 1 < p - 1 := by omega
  have hcastS :
      ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2)) S = 0 := by
    calc
      ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2)) S
          =
          ∑ k in Finset.Icc 1 (p - 1),
            (((k : ZMod (p ^ 2)) ^ (2 * m + 3))⁻¹) := by
            change
              ZMod.castHom (zmod_p_square_dvd_p_fourth_power p) (ZMod (p ^ 2))
                  (∑ k in Finset.Icc 1 (p - 1),
                    (((k : R) ^ (2 * m + 3))⁻¹)) =
                ∑ k in Finset.Icc 1 (p - 1),
                  (((k : ZMod (p ^ 2)) ^ (2 * m + 3))⁻¹)
            rw [map_sum]
            apply Finset.sum_congr rfl
            intro k hk
            exact zmod_cast_inverse_power_term_mod_p2 p k (2 * m + 3) hp
              (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2
      _ = 0 :=
          zmod_inverse_power_sum_odd_eq_zero_mod_p2_of_pos_lt p (2 * m + 3) hp
            hodd h2p hepos helt
  exact zmod_p2_mul_eq_zero_of_cast_mod_p2_eq_zero p hp S hcastS

lemma zmod_hypergeometric_sum_vanish_mod_p4_of_large
    (p m : ℕ) (hp : p.Prime) (hlarge : 2 * m + 6 < p) :
    let R := ZMod (p ^ 4)
    (∑ k in Finset.Icc 1 (p - 1),
      (((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹)) = 0 := by
  let R := ZMod (p ^ 4)
  change
    (∑ k in Finset.Icc 1 (p - 1),
      (((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹)) = 0
  let Sodd : R :=
    ∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 3))⁻¹)
  let Seven : R :=
    ∑ k in Finset.Icc 1 (p - 1), (((k : R) ^ (2 * m + 4))⁻¹)
  have hsum :
      (∑ k in Finset.Icc 1 (p - 1),
        (((p - 1).choose k : R) ^ 2) *
        (((p - 1 + k).choose k : R) ^ 2) *
        (((k : R) ^ (2 * m + 1))⁻¹)) =
        (p : R) ^ 2 * Sodd - (2 : R) * (p : R) ^ 3 * Seven := by
    simpa [Sodd, Seven] using zmod_hypergeometric_sum_expansion_mod_p4 p m hp
  have hodd :
      (p : R) ^ 2 * Sodd = 0 := by
    simpa [Sodd] using
      zmod_p2_mul_inverse_power_sum_odd_eq_zero_mod_p4_of_large p m hp hlarge
  have heven :
      (2 : R) * (p : R) ^ 3 * Seven = 0 := by
    simpa [Seven] using
      zmod_p3_mul_inverse_power_sum_even_eq_zero_mod_p4_of_large p m hp hlarge
  calc
    (∑ k in Finset.Icc 1 (p - 1),
      (((p - 1).choose k : R) ^ 2) *
      (((p - 1 + k).choose k : R) ^ 2) *
      (((k : R) ^ (2 * m + 1))⁻¹))
        = (p : R) ^ 2 * Sodd - (2 : R) * (p : R) ^ 3 * Seven := hsum
    _ = 0 - (2 : R) * (p : R) ^ 3 * Seven := by rw [hodd]
    _ = 0 - 0 := by rw [heven]
    _ = 0 := by ring

lemma rat_term_common_den (A D k e : ℕ)
    (hdiv : k ^ e ∣ D) (hk0 : k ≠ 0) (hD : D ≠ 0) :
    (A : ℚ) / (k : ℚ) ^ e =
      ((A * (D / (k ^ e) : ℕ) : ℕ) : ℚ) / (D : ℚ) := by
  have hkpow_ne : k ^ e ≠ 0 := pow_ne_zero e hk0
  have hD_eq : D = k ^ e * (D / k ^ e) := (Nat.mul_div_cancel' hdiv).symm
  have hcastD : (D : ℚ) = (k : ℚ) ^ e * ((D / k ^ e : ℕ) : ℚ) := by
    exact_mod_cast hD_eq
  have hkpow_cast_ne : ((k : ℚ) ^ e) ≠ 0 := by exact_mod_cast hkpow_ne
  have hquot_ne_nat : D / k ^ e ≠ 0 := by
    intro hq
    have hzero : D = 0 := by simpa [hq] using hD_eq
    exact hD hzero
  have hquot_cast_ne : (((D / k ^ e : ℕ) : ℚ)) ≠ 0 := by
    exact_mod_cast hquot_ne_nat
  have hquot_div_D :
      (((D / k ^ e : ℕ) : ℚ) / (D : ℚ)) = (((k : ℚ) ^ e)⁻¹) := by
    calc
      (((D / k ^ e : ℕ) : ℚ) / (D : ℚ))
          = (((D / k ^ e : ℕ) : ℚ) /
              ((k : ℚ) ^ e * ((D / k ^ e : ℕ) : ℚ))) := by
              rw [hcastD]
      _ = (((D / k ^ e : ℕ) : ℚ) *
              (((k : ℚ) ^ e * ((D / k ^ e : ℕ) : ℚ))⁻¹)) := by
              rw [div_eq_mul_inv]
      _ = (((D / k ^ e : ℕ) : ℚ) *
              (((D / k ^ e : ℕ) : ℚ)⁻¹ * (((k : ℚ) ^ e)⁻¹))) := by
              rw [mul_inv_rev]
      _ = ((((D / k ^ e : ℕ) : ℚ) *
              (((D / k ^ e : ℕ) : ℚ)⁻¹)) * (((k : ℚ) ^ e)⁻¹)) := by
              ring
      _ = (((k : ℚ) ^ e)⁻¹) := by
              rw [mul_inv_cancel₀ hquot_cast_ne, one_mul]
  calc
    (A : ℚ) / (k : ℚ) ^ e =
    (A : ℚ) * (((k : ℚ) ^ e)⁻¹) := by rw [div_eq_mul_inv]
    _ = (A : ℚ) * (((D / k ^ e : ℕ) : ℚ) / (D : ℚ)) := by
          rw [hquot_div_D]
    _ = ((A * (D / (k ^ e) : ℕ) : ℕ) : ℚ) / (D : ℚ) := by
          rw [div_eq_mul_inv]
          simp [Nat.cast_mul]
          ring

lemma rat_common_den_sum_eq
    (s : Finset ℕ) (A : ℕ → ℕ) (D e : ℕ)
    (hdiv : ∀ k ∈ s, k ^ e ∣ D)
    (hk0 : ∀ k ∈ s, k ≠ 0)
    (hD : D ≠ 0) :
    (∑ k ∈ s, (A k : ℚ) / (k : ℚ) ^ e) =
      ((∑ k ∈ s, A k * (D / (k ^ e) : ℕ) : ℕ) : ℚ) / (D : ℚ) := by
  calc
    (∑ k ∈ s, (A k : ℚ) / (k : ℚ) ^ e)
        = ∑ k ∈ s, ((A k * (D / (k ^ e) : ℕ) : ℕ) : ℚ) / (D : ℚ) := by
          apply Finset.sum_congr rfl
          intro k hk
          exact rat_term_common_den (A k) D k e (hdiv k hk) (hk0 k hk) hD
    _ = ((∑ k ∈ s, A k * (D / (k ^ e) : ℕ) : ℕ) : ℚ) / (D : ℚ) := by
          simp_rw [div_eq_mul_inv]
          rw [← Finset.sum_mul]
          congr 1
          exact (map_sum (Nat.castRingHom ℚ)
            (fun k => A k * (D / (k ^ e) : ℕ)) s).symm

lemma zmod_common_den_sum_eq
    (M : ℕ) (s : Finset ℕ) (A : ℕ → ℕ) (D e : ℕ)
    (hdiv : ∀ k ∈ s, k ^ e ∣ D)
    (hunit : ∀ k ∈ s, IsUnit (k : ZMod M)) :
    (((∑ k ∈ s, A k * (D / (k ^ e) : ℕ)) : ℕ) : ZMod M) =
      (D : ZMod M) *
        (∑ k ∈ s, (A k : ZMod M) * ((((k : ZMod M) ^ e)⁻¹))) := by
  rw [Finset.mul_sum]
  rw [show (((∑ k ∈ s, A k * (D / (k ^ e) : ℕ)) : ℕ) : ZMod M) =
      ∑ k ∈ s, (((A k * (D / (k ^ e) : ℕ) : ℕ) : ZMod M)) by
    exact map_sum (Nat.castRingHom (ZMod M))
      (fun k => A k * (D / (k ^ e) : ℕ)) s]
  apply Finset.sum_congr rfl
  intro k hk
  have hpowunit : IsUnit ((k : ZMod M) ^ e) := IsUnit.pow e (hunit k hk)
  have hmul_inv : ((k : ZMod M) ^ e) * ((((k : ZMod M) ^ e)⁻¹)) = 1 :=
    ZMod.mul_inv_of_unit _ hpowunit
  have hD_eq_nat : k ^ e * (D / (k ^ e) : ℕ) = D :=
    Nat.mul_div_cancel' (hdiv k hk)
  have hDcast : (D : ZMod M) =
      (k : ZMod M) ^ e * (((D / (k ^ e) : ℕ) : ZMod M)) := by
    have hcast : ((D : ℕ) : ZMod M) =
        ((k ^ e * (D / (k ^ e) : ℕ) : ℕ) : ZMod M) := by
      exact congrArg (fun n : ℕ => ((n : ℕ) : ZMod M)) hD_eq_nat.symm
    simpa [Nat.cast_mul, Nat.cast_pow] using hcast
  calc
    (((A k * (D / (k ^ e) : ℕ) : ℕ) : ZMod M)) =
        (A k : ZMod M) * (((D / (k ^ e) : ℕ) : ZMod M)) := by
          simp [Nat.cast_mul]
    _ = (D : ZMod M) * ((A k : ZMod M) * ((((k : ZMod M) ^ e)⁻¹))) := by
          rw [hDcast]
          rw [show ((k : ZMod M) ^ e * (((D / (k ^ e) : ℕ) : ZMod M))) *
                ((A k : ZMod M) * ((((k : ZMod M) ^ e)⁻¹))) =
              (A k : ZMod M) * (((D / (k ^ e) : ℕ) : ZMod M)) *
                (((k : ZMod M) ^ e) * ((((k : ZMod M) ^ e)⁻¹)) : ZMod M) by ring]
          rw [hmul_inv]
          ring

lemma zmod_natAbs_cast_zero_of_int_cast_zero (M : ℕ) (z : ℤ)
    (hz : (z : ZMod M) = 0) : ((z.natAbs : ℕ) : ZMod M) = 0 := by
  rw [ZMod.natCast_eq_zero_iff]
  rw [ZMod.intCast_zmod_eq_zero_iff_dvd] at hz
  exact Int.natCast_dvd_natCast.mp (Int.dvd_natAbs.mpr hz)

lemma zmod_int_cast_zero_of_unit_mul_eq_zero (M : ℕ) (c z : ℤ)
    (hc : IsUnit (c : ZMod M)) (hcz : ((c * z : ℤ) : ZMod M) = 0) :
    (z : ZMod M) = 0 := by
  rw [Int.cast_mul] at hcz
  rw [mul_comm] at hcz
  exact (IsUnit.mul_left_eq_zero hc).mp hcz

set_option maxHeartbeats 50000 in
lemma zmod_u_eq_hypergeometric_sum_mod_p4_of_large
    (p m : ℕ) (hp : p.Prime) (hlarge : 2 * m + 6 < p) :
    let R := ZMod (p ^ 4)
    ((OeisA357513.u m (p - 1) : ℕ) : R) =
      (∑ k in Finset.Icc 1 (p - 1),
        (((p - 1).choose k : R) ^ 2) *
        (((p - 1 + k).choose k : R) ^ 2) *
        (((k : R) ^ (2 * m + 1))⁻¹)) := by
  let R := ZMod (p ^ 4)
  change ((OeisA357513.u m (p - 1) : ℕ) : R) =
      (∑ k in Finset.Icc 1 (p - 1),
        (((p - 1).choose k : R) ^ 2) *
        (((p - 1 + k).choose k : R) ^ 2) *
        (((k : R) ^ (2 * m + 1))⁻¹))
  let s : Finset ℕ := Finset.Icc 1 (p - 1)
  let e : ℕ := 2 * m + 1
  let A : ℕ → ℕ := fun k => ((p - 1).choose k) ^ 2 * ((p - 1 + k).choose k) ^ 2
  let D : ℕ := ∏ k in s, k ^ e
  let N : ℕ := ∑ k ∈ s, A k * (D / (k ^ e) : ℕ)
  let q : ℚ := ∑ k ∈ Finset.Icc 1 (p - 1),
    ((p - 1).choose k : ℚ) ^ 2 *
      ((p - 1 + k).choose k : ℚ) ^ 2 / (k : ℚ) ^ e
  have hright :
      (∑ k in Finset.Icc 1 (p - 1),
        (((p - 1).choose k : R) ^ 2) *
        (((p - 1 + k).choose k : R) ^ 2) *
        (((k : R) ^ (2 * m + 1))⁻¹)) = 0 :=
    zmod_hypergeometric_sum_vanish_mod_p4_of_large p m hp hlarge
  have hdiv : ∀ k ∈ s, k ^ e ∣ D := by
    intro k hk
    exact Finset.dvd_prod_of_mem (fun j => j ^ e) hk
  have hk0 : ∀ k ∈ s, k ≠ 0 := by
    intro k hk hzero
    have hk1 : 1 ≤ k := (Finset.mem_Icc.mp hk).1
    omega
  have hD : D ≠ 0 := by
    rw [Finset.prod_ne_zero_iff]
    intro k hk
    exact pow_ne_zero e (hk0 k hk)
  have hDcop : D.Coprime (p ^ 4) := by
    apply Nat.Coprime.prod_left
    intro k hk
    exact (zmod_range_coprime_mod_fourth_power p k hp
      (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2).pow_left e
  have hunitD : IsUnit (D : R) := by
    rw [ZMod.isUnit_iff_coprime]
    exact hDcop
  have hunit_terms : ∀ k ∈ s, IsUnit (k : R) := by
    intro k hk
    exact zmod_unit_denominator_for_range p k hp
      (Finset.mem_Icc.mp hk).1 (Finset.mem_Icc.mp hk).2
  have hcommon_zmod :
      ((N : ℕ) : R) =
        (D : R) *
          (∑ k ∈ s, (A k : R) * ((((k : R) ^ e)⁻¹))) := by
    simpa [N, D, R] using zmod_common_den_sum_eq (p ^ 4) s A D e hdiv hunit_terms
  have hNzero : ((N : ℕ) : R) = 0 := by
    rw [hcommon_zmod]
    have hsum_eq :
        (∑ k ∈ s, (A k : R) * ((((k : R) ^ e)⁻¹))) =
          (∑ k in Finset.Icc 1 (p - 1),
            (((p - 1).choose k : R) ^ 2) *
            (((p - 1 + k).choose k : R) ^ 2) *
            (((k : R) ^ (2 * m + 1))⁻¹)) := by
      simp [s, A, e, pow_two, Nat.cast_mul, mul_assoc]
    rw [hsum_eq, hright, mul_zero]
  have hq_common : q = ((N : ℕ) : ℚ) / (D : ℚ) := by
    simpa [q, N, A, s, e, pow_two, mul_assoc] using
      rat_common_den_sum_eq s A D e hdiv hk0 hD
  have hq_common_int : q = ((N : ℤ) : ℚ) / (D : ℤ) := by
    simpa using hq_common
  have hD_int : (D : ℤ) ≠ 0 := by exact_mod_cast hD
  obtain ⟨c, hcN, hcD⟩ :=
    Rat.exists_eq_mul_div_num_and_eq_mul_div_den ((N : ℤ)) (d := (D : ℤ)) hD_int
  rw [← hq_common_int] at hcN hcD
  have hNzero_int : ((N : ℤ) : R) = 0 := by
    simpa using hNzero
  have hcqzero : ((c * q.num : ℤ) : R) = 0 := by
    rw [← hcN]
    exact hNzero_int
  have hcdvdD_int : c ∣ (D : ℤ) := ⟨(q.den : ℤ), by simpa [mul_comm] using hcD⟩
  have hcdvdD_nat : c.natAbs ∣ D := Int.dvd_natCast.mp hcdvdD_int
  have hc_coprime : c.natAbs.Coprime (p ^ 4) :=
    Nat.Coprime.of_dvd_left hcdvdD_nat hDcop
  have hcunit_abs : IsUnit ((c.natAbs : ℕ) : R) := by
    rw [ZMod.isUnit_iff_coprime]
    exact hc_coprime
  have hcunit : IsUnit (c : R) := by
    rcases Int.natAbs_eq c with hc | hc
    · rw [hc, Int.cast_natCast]
      exact hcunit_abs
    · rw [hc, Int.cast_neg, Int.cast_natCast]
      exact IsUnit.neg hcunit_abs
  have hqnum_zero : (q.num : R) = 0 :=
    zmod_int_cast_zero_of_unit_mul_eq_zero (p ^ 4) c q.num hcunit hcqzero
  have hleft : ((OeisA357513.u m (p - 1) : ℕ) : R) = 0 := by
    unfold OeisA357513.u
    change ((q.num.natAbs : ℕ) : R) = 0
    exact zmod_natAbs_cast_zero_of_int_cast_zero (p ^ 4) q.num hqnum_zero
  rw [hleft, hright]

lemma zmod_u_vanish_mod_p4_of_large
    (p m : ℕ) (hp : p.Prime) (hlarge : 2 * m + 6 < p) :
    ((OeisA357513.u m (p - 1) : ℕ) : ZMod (p ^ 4)) = 0 := by
  let R := ZMod (p ^ 4)
  change ((OeisA357513.u m (p - 1) : ℕ) : R) = 0
  rw [zmod_u_eq_hypergeometric_sum_mod_p4_of_large p m hp hlarge]
  exact zmod_hypergeometric_sum_vanish_mod_p4_of_large p m hp hlarge

theorem general_supercongruence_eventual
    (m : ℕ) :
    ∃ exceptions : Finset ℕ, ∀ p, p.Prime →
      p ∉ exceptions →
      ((OeisA357513.u m (p - 1) : ℕ) : ZMod (p ^ 4)) = 0 := by
  refine ⟨Finset.Icc 0 (2 * m + 6), ?_⟩
  intro p hp hp_not
  have hlarge : 2 * m + 6 < p := by
    by_contra hnot
    have hp_le : p ≤ 2 * m + 6 := by omega
    exact hp_not (by simp [hp_le])
  exact zmod_u_vanish_mod_p4_of_large p m hp hlarge

theorem general_supercongruence_source_statement
    (m : ℕ) : ∃ exceptions : Finset ℕ, ∀ p, p.Prime →
      p ∉ exceptions → OeisA357513.u m (p - 1) = (0 : ZMod (p ^ 4)) := by
  exact general_supercongruence_eventual m
end OeisA357513NextRound20260606
