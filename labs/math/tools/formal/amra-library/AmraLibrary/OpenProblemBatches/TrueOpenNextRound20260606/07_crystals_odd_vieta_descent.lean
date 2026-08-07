import Mathlib.Data.Finset.Insert
import Mathlib.Data.Nat.GCD.Basic
import Mathlib.Data.Nat.ModEq
import Mathlib.Data.Nat.Prime.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring
import Mathlib.Tactic.SuppressCompilation

suppress_compilation

/-!
Staging file for the arithmetic core of the crystal-components Vieta descent
route.  The next target is the local inequality
`odd_vieta_d_lt_two_mul_se`; this file intentionally contains no open theorem
stub.
-/

namespace CrystalsOddVietaDescent20260610

/--
Source-faithful local copy of the crystal-with-components predicate used by
the upstream Formal Conjectures statement.
-/
def IsCrystalWithComponents (n a b : Nat) : Prop :=
  Odd n ∧ 1 < a ∧ 1 < b ∧ n = a * b ∧
    2 * (a + 1) * (b + 1) ∣ (a + b) ^ 2 + (a * b + 1) ^ 2

lemma halfShift_crystal_den_eq (r s : Nat) (hr : 1 <= r) (hs : 1 <= s) :
    2 * ((2 * r - 1) + 1) * ((2 * s - 1) + 1) = 8 * (r * s) := by
  rcases Nat.exists_eq_add_of_le hr with ⟨r0, rfl⟩
  rcases Nat.exists_eq_add_of_le hs with ⟨s0, rfl⟩
  have hrA : 2 * (1 + r0) - 1 = 2 * r0 + 1 := by omega
  have hsA : 2 * (1 + s0) - 1 = 2 * s0 + 1 := by omega
  rw [hrA, hsA]
  ring

lemma halfShift_crystal_num_eq (r s : Nat) (hr : 1 <= r) (hs : 1 <= s) :
    ((2 * r - 1) + (2 * s - 1)) ^ 2 +
        (((2 * r - 1) * (2 * s - 1) + 1) ^ 2) =
      8 * ((r + s - 1) ^ 2 + 2 * r * s * ((r - 1) * (s - 1))) := by
  rcases Nat.exists_eq_add_of_le hr with ⟨r0, rfl⟩
  rcases Nat.exists_eq_add_of_le hs with ⟨s0, rfl⟩
  have hrA : 2 * (1 + r0) - 1 = 2 * r0 + 1 := by omega
  have hsA : 2 * (1 + s0) - 1 = 2 * s0 + 1 := by omega
  have hrB : 1 + r0 - 1 = r0 := by omega
  have hsB : 1 + s0 - 1 = s0 := by omega
  have hrsum : 1 + r0 + (1 + s0) - 1 = r0 + s0 + 1 := by omega
  rw [hrA, hsA, hrB, hsB, hrsum]
  ring

lemma halfShift_crystal_dvd_implies_rs_dvd_sq
    (r s : Nat) (hr : 1 <= r) (hs : 1 <= s)
    (h : 2 * ((2 * r - 1) + 1) * ((2 * s - 1) + 1) ∣
      ((2 * r - 1) + (2 * s - 1)) ^ 2 +
        (((2 * r - 1) * (2 * s - 1) + 1) ^ 2)) :
    r * s ∣ (r + s - 1) ^ 2 := by
  have hden := halfShift_crystal_den_eq r s hr hs
  have hnum := halfShift_crystal_num_eq r s hr hs
  have hsimpl :
      8 * (r * s) ∣
        8 * ((r + s - 1) ^ 2 + 2 * r * s * ((r - 1) * (s - 1))) := by
    simpa [hden, hnum] using h
  rcases hsimpl with ⟨k, hk⟩
  have hcancel :
      (r + s - 1) ^ 2 + 2 * r * s * ((r - 1) * (s - 1)) = r * s * k := by
    have h8 :
        8 * ((r + s - 1) ^ 2 + 2 * r * s * ((r - 1) * (s - 1))) =
          8 * (r * s * k) := by
      calc
        8 * ((r + s - 1) ^ 2 + 2 * r * s * ((r - 1) * (s - 1)))
        _ = 8 * (r * s) * k := hk
        _ = 8 * (r * s * k) := by ring
    exact Nat.mul_left_cancel (by decide : 0 < 8) h8
  have hmain :
      r * s ∣ (r + s - 1) ^ 2 + 2 * r * s * ((r - 1) * (s - 1)) := by
    exact ⟨k, hcancel⟩
  have htail : r * s ∣ 2 * r * s * ((r - 1) * (s - 1)) := by
    exact ⟨2 * ((r - 1) * (s - 1)), by ring⟩
  exact ((Nat.dvd_add_iff_left htail :
    r * s ∣ (r + s - 1) ^ 2 ↔
      r * s ∣ (r + s - 1) ^ 2 + 2 * r * s * ((r - 1) * (s - 1))).mpr hmain)

theorem isCrystalWithComponents_halfShift_admissible
    {n a b : Nat} (h : IsCrystalWithComponents n a b) :
    ∃ r s : Nat, 2 <= r ∧ 2 <= s ∧ a = 2 * r - 1 ∧ b = 2 * s - 1 ∧
      r * s ∣ (r + s - 1) ^ 2 := by
  rcases h with ⟨hnodd, ha_gt, hb_gt, hnab, hdvd⟩
  have hab_odd : Odd (a * b) := by
    simpa [hnab] using hnodd
  have ha_odd : Odd a := Nat.Odd.of_mul_left hab_odd
  have hb_odd : Odd b := Nat.Odd.of_mul_right hab_odd
  rcases ha_odd with ⟨ra, hra⟩
  rcases hb_odd with ⟨sb, hsb⟩
  let r := ra + 1
  let s := sb + 1
  have hr_ge : 2 <= r := by
    dsimp [r]
    omega
  have hs_ge : 2 <= s := by
    dsimp [s]
    omega
  have ha_eq : a = 2 * r - 1 := by
    dsimp [r]
    omega
  have hb_eq : b = 2 * s - 1 := by
    dsimp [s]
    omega
  have hr1 : 1 <= r := le_trans (by decide : 1 <= 2) hr_ge
  have hs1 : 1 <= s := le_trans (by decide : 1 <= 2) hs_ge
  have hdvd_shift :
      2 * ((2 * r - 1) + 1) * ((2 * s - 1) + 1) ∣
        ((2 * r - 1) + (2 * s - 1)) ^ 2 +
          (((2 * r - 1) * (2 * s - 1) + 1) ^ 2) := by
    simpa [ha_eq, hb_eq] using hdvd
  exact ⟨r, s, hr_ge, hs_ge, ha_eq, hb_eq,
    halfShift_crystal_dvd_implies_rs_dvd_sq r s hr1 hs1 hdvd_shift⟩

lemma odd_vieta_d_lt_two_mul_se
    (r s d e : Nat)
    (hr : 1 <= r) (hs : 1 <= s)
    (hd : Odd d) (he : Odd e)
    (h : r * d ^ 2 + s * e ^ 2 = 2 * r * s * d * e + 1) :
    d < 2 * s * e := by
  by_contra hnot
  have hle : 2 * s * e <= d := Nat.le_of_not_gt hnot
  rcases lt_or_eq_of_le hle with hlt | heq
  · have hdpos : 0 < d := by
      rcases hd with ⟨k, hk⟩
      omega
    have hpos_rd : 0 < r * d := Nat.mul_pos hr hdpos
    have hmul : (2 * s * e) * (r * d) < d * (r * d) :=
      Nat.mul_lt_mul_of_pos_right hlt hpos_rd
    have hmain : 2 * r * s * d * e < r * d ^ 2 := by
      calc
        2 * r * s * d * e = (2 * s * e) * (r * d) := by ring
        _ < d * (r * d) := hmul
        _ = r * d ^ 2 := by ring
    have hle_main : 2 * r * s * d * e + 1 <= r * d ^ 2 :=
      Nat.succ_le_of_lt hmain
    have hepos : 0 < e := by
      rcases he with ⟨k, hk⟩
      omega
    have hsepos_lt : 0 < s * e ^ 2 := Nat.mul_pos hs (pow_pos hepos 2)
    have hle_left : r * d ^ 2 + s * e ^ 2 <= r * d ^ 2 := by
      calc
        r * d ^ 2 + s * e ^ 2 = 2 * r * s * d * e + 1 := h
        _ <= r * d ^ 2 := hle_main
    have hlt_left : r * d ^ 2 < r * d ^ 2 + s * e ^ 2 :=
      Nat.lt_add_of_pos_right hsepos_lt
    exact (Nat.not_lt_of_ge hle_left) hlt_left
  · exact hd.not_two_dvd_nat ⟨s * e, by
      rw [← heq]
      ring⟩

lemma odd_vieta_outer_d_step
    (r s d e : Nat)
    (hr : 1 <= r) (hs : 1 <= s)
    (hd : Odd d) (he : Odd e)
    (h : r * d ^ 2 + s * e ^ 2 = 2 * r * s * d * e + 1)
    (hout : s * e < d) :
    let d' := 2 * s * e - d
    0 < d' ∧ Odd d' ∧ d' + e < d + e ∧
      r * d' ^ 2 + s * e ^ 2 = 2 * r * s * d' * e + 1 := by
  intro d'
  have hd' : d' = 2 * s * e - d := rfl
  have hlt_two : d < 2 * s * e :=
    odd_vieta_d_lt_two_mul_se r s d e hr hs hd he h
  have hle_two : d <= 2 * s * e := hlt_two.le
  have hd'_pos : 0 < d' := by
    rw [hd']
    exact Nat.sub_pos_of_lt hlt_two
  have htwo_even : Even (2 * s * e) := by
    rw [show 2 * s * e = 2 * (s * e) by ring]
    exact even_two_mul (s * e)
  have hd'_odd : Odd d' := by
    rw [hd']
    exact Nat.Even.sub_odd hle_two htwo_even hd
  have hepos : 0 < e := by
    rcases he with ⟨k, hk⟩
    omega
  have hsepos : 0 < s * e := Nat.mul_pos hs hepos
  have hd'_lt_d : d' < d := by
    rw [hd']
    have hd'_lt_se : 2 * s * e - d < s * e := by
      rw [show 2 * s * e = s * e + s * e by ring]
      omega
    omega
  have hmeasure : d' + e < d + e := Nat.add_lt_add_right hd'_lt_d e
  have hd'cast : (d' : Int) = (2 * s * e : Nat) - d := by
    rw [hd']
    exact Nat.cast_sub hle_two
  have htwose_cast : ((2 * s * e : Nat) : Int) = 2 * (s : Int) * (e : Int) := by
    norm_num
  have hint : (r : Int) * (d : Int) ^ 2 + (s : Int) * (e : Int) ^ 2 =
      2 * (r : Int) * (s : Int) * (d : Int) * (e : Int) + 1 := by
    exact_mod_cast h
  have hpoly : (r : Int) * (d : Int) ^ 2 -
      2 * (r : Int) * (s : Int) * (d : Int) * (e : Int) +
      (s : Int) * (e : Int) ^ 2 - 1 = 0 := by
    linarith
  have heq_int : (r : Int) * (d' : Int) ^ 2 + (s : Int) * (e : Int) ^ 2 =
      2 * (r : Int) * (s : Int) * (d' : Int) * (e : Int) + 1 := by
    rw [hd'cast, htwose_cast]
    ring_nf at hpoly ⊢
    linarith
  have heq_nat : r * d' ^ 2 + s * e ^ 2 = 2 * r * s * d' * e + 1 := by
    exact_mod_cast heq_int
  exact ⟨hd'_pos, hd'_odd, hmeasure, heq_nat⟩

theorem no_odd_vieta_solution
    (r s d e : Nat)
    (hr : 1 <= r) (hs : 1 <= s)
    (hd : Odd d) (he : Odd e) :
    ¬ r * d ^ 2 + s * e ^ 2 = 2 * r * s * d * e + 1 := by
  have hmain :
      ∀ n r s d e,
        d + e = n →
        1 <= r → 1 <= s → Odd d → Odd e →
        ¬ r * d ^ 2 + s * e ^ 2 = 2 * r * s * d * e + 1 := by
    intro n
    induction n using Nat.strong_induction_on with
    | h n ih =>
      intro r s d e hsum hr hs hd he hEq
      by_cases hsd : s * e < d
      · let d' := 2 * s * e - d
        have hstep := odd_vieta_outer_d_step r s d e hr hs hd he hEq hsd
        dsimp only at hstep
        rcases hstep with ⟨hd'_pos, hd'_odd, hmeasure, hEq'⟩
        exact ih (d' + e) (by omega) r s d' e rfl hr hs hd'_odd he hEq'
      · by_cases hrd : r * d < e
        · have hEq_swap :
              s * e ^ 2 + r * d ^ 2 = 2 * s * r * e * d + 1 := by
            calc
              s * e ^ 2 + r * d ^ 2 = r * d ^ 2 + s * e ^ 2 := by ring
              _ = 2 * r * s * d * e + 1 := hEq
              _ = 2 * s * r * e * d + 1 := by ring
          let e' := 2 * r * d - e
          have hstep := odd_vieta_outer_d_step s r e d hs hr he hd hEq_swap hrd
          dsimp only at hstep
          rcases hstep with ⟨he'_pos, he'_odd, hmeasure, hEq'⟩
          exact ih (e' + d) (by omega) s r e' d rfl hs hr he'_odd hd hEq'
        · have hle_d : d <= s * e := Nat.le_of_not_gt hsd
          have hle_e : e <= r * d := Nat.le_of_not_gt hrd
          have hle_left :
              r * d ^ 2 <= r * s * d * e := by
            calc
              r * d ^ 2 = d * (r * d) := by ring
              _ <= (s * e) * (r * d) := Nat.mul_le_mul_right (r * d) hle_d
              _ = r * s * d * e := by ring
          have hle_right :
              s * e ^ 2 <= r * s * d * e := by
            calc
              s * e ^ 2 = e * (s * e) := by ring
              _ <= (r * d) * (s * e) := Nat.mul_le_mul_right (s * e) hle_e
              _ = r * s * d * e := by ring
          have hle_sum :
              r * d ^ 2 + s * e ^ 2 <= 2 * r * s * d * e := by
            calc
              r * d ^ 2 + s * e ^ 2
                  <= r * s * d * e + r * s * d * e :=
                    Nat.add_le_add hle_left hle_right
              _ = 2 * r * s * d * e := by ring
          omega
  exact hmain (d + e) r s d e rfl hr hs hd he

theorem no_odd_vieta_solution_exists :
    ¬ ∃ R S X Y : Nat,
      1 <= R ∧ 1 <= S ∧ Odd X ∧ Odd Y ∧
      R * X ^ 2 + S * Y ^ 2 = 2 * R * S * X * Y + 1 := by
  rintro ⟨R, S, X, Y, hR, hS, hX, hY, hEq⟩
  exact no_odd_vieta_solution R S X Y hR hS hX hY hEq

lemma cross_halfShift_product_int_relation
    (r s x y : Nat)
    (hr : 2 <= r) (hs : 2 <= s) (hx : 2 <= x) (hy : 2 <= y)
    (hprod : (2 * r - 1) * (2 * s - 1) = (2 * x - 1) * (2 * y - 1)) :
    2 * (r : Int) * (s : Int) - (r : Int) - (s : Int) =
      2 * (x : Int) * (y : Int) - (x : Int) - (y : Int) := by
  have hprodInt :
      (((2 * r - 1) * (2 * s - 1) : Nat) : Int) =
        (((2 * x - 1) * (2 * y - 1) : Nat) : Int) := by
    exact_mod_cast hprod
  have hrCast : ((2 * r - 1 : Nat) : Int) = 2 * (r : Int) - 1 := by omega
  have hsCast : ((2 * s - 1 : Nat) : Int) = 2 * (s : Int) - 1 := by omega
  have hxCast : ((2 * x - 1 : Nat) : Int) = 2 * (x : Int) - 1 := by omega
  have hyCast : ((2 * y - 1 : Nat) : Int) = 2 * (y : Int) - 1 := by omega
  rw [Nat.cast_mul, Nat.cast_mul, hrCast, hsCast, hxCast, hyCast] at hprodInt
  ring_nf at hprodInt ⊢
  linarith

lemma cross_halfShift_divisibility_quotients
    (r s x y : Nat)
    (hr : 2 <= r) (hs : 2 <= s) (hx : 2 <= x) (hy : 2 <= y)
    (hprod : (2 * r - 1) * (2 * s - 1) = (2 * x - 1) * (2 * y - 1))
    (hrs : r * s ∣ (r + s - 1) ^ 2)
    (hxy : x * y ∣ (x + y - 1) ^ 2) :
    ∃ K L : Nat,
      (r + s - 1) ^ 2 = r * s * K ∧
      (x + y - 1) ^ 2 = x * y * L ∧
      2 * (r : Int) * (s : Int) - (r : Int) - (s : Int) =
        2 * (x : Int) * (y : Int) - (x : Int) - (y : Int) := by
  rcases hrs with ⟨K, hK⟩
  rcases hxy with ⟨L, hL⟩
  exact ⟨K, L, hK, hL,
    cross_halfShift_product_int_relation r s x y hr hs hx hy hprod⟩

lemma halfShift_divisibility_modular
    (r s : Nat) (hr : 2 <= r) (hs : 2 <= s)
    (h : r * s ∣ (r + s - 1) ^ 2) :
    r ∣ (s - 1) ^ 2 ∧ s ∣ (r - 1) ^ 2 := by
  constructor
  · have hr_dvd_prod : r ∣ r * s := ⟨s, by ring⟩
    have hr_dvd_sq : r ∣ (r + s - 1) ^ 2 := dvd_trans hr_dvd_prod h
    have hsum : r + s - 1 = r + (s - 1) := by omega
    have htail : r ∣ r ^ 2 + 2 * r * (s - 1) := by
      exact ⟨r + 2 * (s - 1), by ring⟩
    have hmain : r ∣ (s - 1) ^ 2 + (r ^ 2 + 2 * r * (s - 1)) := by
      have hrewrite :
          (r + s - 1) ^ 2 = (s - 1) ^ 2 + (r ^ 2 + 2 * r * (s - 1)) := by
        rw [hsum]
        ring
      simpa [hrewrite] using hr_dvd_sq
    exact (Nat.dvd_add_iff_left htail).mpr hmain
  · have hs_dvd_prod : s ∣ r * s := ⟨r, by ring⟩
    have hs_dvd_sq : s ∣ (r + s - 1) ^ 2 := dvd_trans hs_dvd_prod h
    have hsum : r + s - 1 = s + (r - 1) := by omega
    have htail : s ∣ s ^ 2 + 2 * s * (r - 1) := by
      exact ⟨s + 2 * (r - 1), by ring⟩
    have hmain : s ∣ (r - 1) ^ 2 + (s ^ 2 + 2 * s * (r - 1)) := by
      have hrewrite :
          (r + s - 1) ^ 2 = (r - 1) ^ 2 + (s ^ 2 + 2 * s * (r - 1)) := by
        rw [hsum]
        ring
      simpa [hrewrite] using hs_dvd_sq
    exact (Nat.dvd_add_iff_left htail).mpr hmain

lemma halfShift_divisibility_coprime
    (r s : Nat) (hr : 2 <= r) (hs : 2 <= s)
    (h : r * s ∣ (r + s - 1) ^ 2) :
    Nat.Coprime r s := by
  by_contra hcop
  rw [Nat.Prime.not_coprime_iff_dvd] at hcop
  rcases hcop with ⟨p, hp, hpr, hps⟩
  let A := r + s - 1
  have hp_dvd_prod : p ∣ r * s := dvd_mul_of_dvd_left hpr s
  have hp_dvd_A2 : p ∣ A ^ 2 := dvd_trans hp_dvd_prod h
  have hp_dvd_A : p ∣ A := hp.dvd_of_dvd_pow hp_dvd_A2
  have hp_dvd_sum : p ∣ r + s := Nat.dvd_add hpr hps
  have hp_dvd_one' : p ∣ (r + s) - A := Nat.dvd_sub hp_dvd_sum hp_dvd_A
  have hsub : (r + s) - A = 1 := by
    dsimp [A]
    omega
  have hp_dvd_one : p ∣ 1 := by
    simpa [hsub] using hp_dvd_one'
  exact hp.not_dvd_one hp_dvd_one

lemma halfShift_modular_coprime_dvd_sumSubOne_sq
    (r s : Nat) (hr : 1 <= r) (hs : 1 <= s)
    (hrmod : r ∣ (s - 1) ^ 2)
    (hsmod : s ∣ (r - 1) ^ 2)
    (hcop : Nat.Coprime r s) :
    r * s ∣ (r + s - 1) ^ 2 := by
  have hr_dvd_sq : r ∣ (r + s - 1) ^ 2 := by
    have hsum : r + s - 1 = r + (s - 1) := by omega
    have htail : r ∣ r ^ 2 + 2 * r * (s - 1) := by
      exact ⟨r + 2 * (s - 1), by ring⟩
    have hrewrite :
        (r + s - 1) ^ 2 = (s - 1) ^ 2 + (r ^ 2 + 2 * r * (s - 1)) := by
      rw [hsum]
      ring
    have hmain : r ∣ (s - 1) ^ 2 + (r ^ 2 + 2 * r * (s - 1)) :=
      (Nat.dvd_add_iff_left htail).mp hrmod
    simpa [hrewrite] using hmain
  have hs_dvd_sq : s ∣ (r + s - 1) ^ 2 := by
    have hsum : r + s - 1 = s + (r - 1) := by omega
    have htail : s ∣ s ^ 2 + 2 * s * (r - 1) := by
      exact ⟨s + 2 * (r - 1), by ring⟩
    have hrewrite :
        (r + s - 1) ^ 2 = (r - 1) ^ 2 + (s ^ 2 + 2 * s * (r - 1)) := by
      rw [hsum]
      ring
    have hmain : s ∣ (r - 1) ^ 2 + (s ^ 2 + 2 * s * (r - 1)) :=
      (Nat.dvd_add_iff_left htail).mp hsmod
    simpa [hrewrite] using hmain
  exact hcop.mul_dvd_of_dvd_of_dvd hr_dvd_sq hs_dvd_sq

lemma halfShift_scaled_common_factor_cancel_dvd
    (g a b : Nat)
    (h : (g * a + 1) * (g * b + 1) ∣ g ^ 2 * (a + b) ^ 2) :
    (g * a + 1) * (g * b + 1) ∣ (a + b) ^ 2 := by
  have hcop : Nat.Coprime ((g * a + 1) * (g * b + 1)) (g ^ 2) := by
    have hcop' : Nat.Coprime g ((g * a + 1) * (g * b + 1)) := by
      apply Nat.Coprime.mul_right
      · rw [Nat.coprime_mul_left_add_right]
        simp
      · rw [Nat.coprime_mul_left_add_right]
        simp
    exact (hcop'.pow_left 2).symm
  exact hcop.dvd_of_dvd_mul_left (by simpa [mul_assoc] using h)

lemma halfShift_oddFactor_den_eq (r s : Nat) (hr : 1 <= r) (hs : 1 <= s) :
    ((2 * r - 1) + 1) * ((2 * s - 1) + 1) = 4 * (r * s) := by
  have hrw : (2 * r - 1) + 1 = 2 * r := by omega
  have hsw : (2 * s - 1) + 1 = 2 * s := by omega
  rw [hrw, hsw]
  ring

lemma halfShift_oddFactor_sum_eq (r s : Nat) (hr : 1 <= r) (hs : 1 <= s) :
    (2 * r - 1) + (2 * s - 1) = 2 * (r + s - 1) := by
  rcases Nat.exists_eq_add_of_le hr with ⟨r0, rfl⟩
  rcases Nat.exists_eq_add_of_le hs with ⟨s0, rfl⟩
  omega

lemma halfShift_divisibility_oddFactors
    (r s : Nat) (hr : 1 <= r) (hs : 1 <= s)
    (h : r * s ∣ (r + s - 1) ^ 2) :
    ((2 * r - 1) + 1) * ((2 * s - 1) + 1) ∣
      ((2 * r - 1) + (2 * s - 1)) ^ 2 := by
  rcases h with ⟨k, hk⟩
  refine ⟨k, ?_⟩
  rw [halfShift_oddFactor_den_eq r s hr hs,
    halfShift_oddFactor_sum_eq r s hr hs]
  calc
    (2 * (r + s - 1)) ^ 2 = 4 * ((r + s - 1) ^ 2) := by ring
    _ = 4 * (r * s * k) := by rw [hk]
    _ = 4 * (r * s) * k := by ring

lemma oddFactor_den_mul_sq_identity
    (A B : Nat) (hA : 1 <= A) (hB : 1 <= B) :
    (A * B + 1) ^ 2 =
      (A + B) ^ 2 + (A + 1) * (B + 1) * ((A - 1) * (B - 1)) := by
  rcases Nat.exists_eq_add_of_le hA with ⟨A0, rfl⟩
  rcases Nat.exists_eq_add_of_le hB with ⟨B0, rfl⟩
  have hA0 : 1 + A0 - 1 = A0 := by omega
  have hB0 : 1 + B0 - 1 = B0 := by omega
  rw [hA0, hB0]
  ring_nf

lemma oddFactor_den_dvd_product_succ_sq
    (A B : Nat) (hA : 1 <= A) (hB : 1 <= B)
    (h : (A + 1) * (B + 1) ∣ (A + B) ^ 2) :
    (A + 1) * (B + 1) ∣ (A * B + 1) ^ 2 := by
  rw [oddFactor_den_mul_sq_identity A B hA hB]
  exact Nat.dvd_add h ⟨(A - 1) * (B - 1), by ring⟩

lemma halfShift_den_dvd_product_succ_sq
    (r s : Nat) (hr : 1 <= r) (hs : 1 <= s)
    (h : r * s ∣ (r + s - 1) ^ 2) :
    ((2 * r - 1) + 1) * ((2 * s - 1) + 1) ∣
      ((2 * r - 1) * (2 * s - 1) + 1) ^ 2 := by
  have hA : 1 <= 2 * r - 1 := by omega
  have hB : 1 <= 2 * s - 1 := by omega
  exact oddFactor_den_dvd_product_succ_sq (2 * r - 1) (2 * s - 1) hA hB
    (halfShift_divisibility_oddFactors r s hr hs h)

lemma cross_halfShift_den_dvd_common_product_succ_sq
    (r s x y : Nat)
    (hr : 2 <= r) (hs : 2 <= s) (hx : 2 <= x) (hy : 2 <= y)
    (hprod : (2 * r - 1) * (2 * s - 1) = (2 * x - 1) * (2 * y - 1))
    (hrs : r * s ∣ (r + s - 1) ^ 2)
    (hxy : x * y ∣ (x + y - 1) ^ 2) :
    ((2 * r - 1) + 1) * ((2 * s - 1) + 1) ∣
        ((2 * x - 1) * (2 * y - 1) + 1) ^ 2 ∧
      ((2 * x - 1) + 1) * ((2 * y - 1) + 1) ∣
        ((2 * r - 1) * (2 * s - 1) + 1) ^ 2 := by
  constructor
  · simpa [hprod] using
      halfShift_den_dvd_product_succ_sq r s
        (le_trans (by decide : 1 <= 2) hr)
        (le_trans (by decide : 1 <= 2) hs) hrs
  · simpa [hprod] using
      halfShift_den_dvd_product_succ_sq x y
        (le_trans (by decide : 1 <= 2) hx)
        (le_trans (by decide : 1 <= 2) hy) hxy

lemma halfShift_sumSubOne_le_prod
    (r s : Nat) (hr : 2 <= r) (hs : 2 <= s) :
    r + s - 1 <= r * s := by
  rcases le_total r s with hrs | hsr
  · have h2s : 2 * s <= r * s := Nat.mul_le_mul_right s hr
    omega
  · have h2r : 2 * r <= r * s := by
      simpa [mul_comm] using Nat.mul_le_mul_right r hs
    omega

lemma halfShift_prod_dvd_common_M_sq
    (r s : Nat) (hr : 2 <= r) (hs : 2 <= s)
    (h : r * s ∣ (r + s - 1) ^ 2) :
    r * s ∣ (2 * r * s - (r + s - 1)) ^ 2 := by
  rcases h with ⟨k, hk⟩
  refine ⟨k + 4 * (r * s - (r + s - 1)), ?_⟩
  have hle : r + s - 1 <= r * s := halfShift_sumSubOne_le_prod r s hr hs
  have hle_two : r + s - 1 <= 2 * r * s := by nlinarith
  have hsub : r * s - (r + s - 1) + (r + s - 1) = r * s := by omega
  have hmain :
      (2 * r * s - (r + s - 1)) ^ 2 =
        (r + s - 1) ^ 2 + 4 * (r * s) * (r * s - (r + s - 1)) := by
    apply Int.ofNat.inj
    change (((2 * r * s - (r + s - 1)) ^ 2 : Nat) : Int) =
      (((r + s - 1) ^ 2 + 4 * (r * s) * (r * s - (r + s - 1)) : Nat) : Int)
    norm_num [Nat.cast_pow, Nat.cast_add, Nat.cast_mul]
    rw [Nat.cast_sub hle_two, Nat.cast_sub hle]
    norm_num [Nat.cast_mul]
    ring
  rw [hmain, hk]
  ring

lemma halfShift_prod_dvd_sumSubOne_sq_of_common_M_sq
    (r s : Nat) (hr : 2 <= r) (hs : 2 <= s)
    (h : r * s ∣ (2 * r * s - (r + s - 1)) ^ 2) :
    r * s ∣ (r + s - 1) ^ 2 := by
  have hle : r + s - 1 <= r * s := halfShift_sumSubOne_le_prod r s hr hs
  have hle_two : r + s - 1 <= 2 * r * s := by nlinarith
  have hmain :
      (2 * r * s - (r + s - 1)) ^ 2 =
        (r + s - 1) ^ 2 + 4 * (r * s) * (r * s - (r + s - 1)) := by
    apply Int.ofNat.inj
    change (((2 * r * s - (r + s - 1)) ^ 2 : Nat) : Int) =
      (((r + s - 1) ^ 2 + 4 * (r * s) * (r * s - (r + s - 1)) : Nat) : Int)
    norm_num [Nat.cast_pow, Nat.cast_add, Nat.cast_mul]
    rw [Nat.cast_sub hle_two, Nat.cast_sub hle]
    norm_num [Nat.cast_mul]
    ring
  have htail :
      r * s ∣ 4 * (r * s) * (r * s - (r + s - 1)) := by
    refine ⟨4 * (r * s - (r + s - 1)), ?_⟩
    ring
  have hsub :
      (2 * r * s - (r + s - 1)) ^ 2 -
          4 * (r * s) * (r * s - (r + s - 1)) =
        (r + s - 1) ^ 2 := by
    rw [hmain]
    omega
  have hdiff :
      r * s ∣
        (2 * r * s - (r + s - 1)) ^ 2 -
          4 * (r * s) * (r * s - (r + s - 1)) :=
    Nat.dvd_sub h htail
  simpa [hsub] using hdiff

lemma halfShift_prod_common_M_sq_quotient_eq
    (r s k : Nat) (hr : 2 <= r) (hs : 2 <= s)
    (hk : (r + s - 1) ^ 2 = r * s * k) :
    (2 * r * s - (r + s - 1)) ^ 2 =
      r * s * (k + 4 * (r * s - (r + s - 1))) := by
  have hle : r + s - 1 <= r * s := halfShift_sumSubOne_le_prod r s hr hs
  have hle_two : r + s - 1 <= 2 * r * s := by nlinarith
  have hmain :
      (2 * r * s - (r + s - 1)) ^ 2 =
        (r + s - 1) ^ 2 + 4 * (r * s) * (r * s - (r + s - 1)) := by
    apply Int.ofNat.inj
    change (((2 * r * s - (r + s - 1)) ^ 2 : Nat) : Int) =
      (((r + s - 1) ^ 2 + 4 * (r * s) * (r * s - (r + s - 1)) : Nat) : Int)
    norm_num [Nat.cast_pow, Nat.cast_add, Nat.cast_mul]
    rw [Nat.cast_sub hle_two, Nat.cast_sub hle]
    norm_num [Nat.cast_mul]
    ring
  rw [hmain, hk]
  ring

lemma cross_halfShift_common_M_eq
    (r s x y : Nat)
    (hr : 2 <= r) (hs : 2 <= s) (hx : 2 <= x) (hy : 2 <= y)
    (hprod : (2 * r - 1) * (2 * s - 1) = (2 * x - 1) * (2 * y - 1)) :
    2 * r * s - (r + s - 1) =
      2 * x * y - (x + y - 1) := by
  have hInt := cross_halfShift_product_int_relation r s x y hr hs hx hy hprod
  have hle_rs : r + s - 1 <= 2 * r * s := by
    have hle := halfShift_sumSubOne_le_prod r s hr hs
    nlinarith
  have hle_xy : x + y - 1 <= 2 * x * y := by
    have hle := halfShift_sumSubOne_le_prod x y hx hy
    nlinarith
  apply Int.ofNat.inj
  change ((2 * r * s - (r + s - 1) : Nat) : Int) =
    ((2 * x * y - (x + y - 1) : Nat) : Int)
  have hrsCast : ((r + s - 1 : Nat) : Int) = (r : Int) + (s : Int) - 1 := by
    omega
  have hxyCast : ((x + y - 1 : Nat) : Int) = (x : Int) + (y : Int) - 1 := by
    omega
  rw [Nat.cast_sub hle_rs, Nat.cast_sub hle_xy]
  rw [hrsCast, hxyCast]
  norm_num [Nat.cast_mul]
  ring_nf at hInt ⊢
  linarith

lemma cross_halfShift_products_dvd_common_M_sq
    (r s x y : Nat)
    (hr : 2 <= r) (hs : 2 <= s) (hx : 2 <= x) (hy : 2 <= y)
    (hprod : (2 * r - 1) * (2 * s - 1) = (2 * x - 1) * (2 * y - 1))
    (hrs : r * s ∣ (r + s - 1) ^ 2)
    (hxy : x * y ∣ (x + y - 1) ^ 2) :
    r * s ∣ (2 * r * s - (r + s - 1)) ^ 2 ∧
      x * y ∣ (2 * r * s - (r + s - 1)) ^ 2 := by
  constructor
  · exact halfShift_prod_dvd_common_M_sq r s hr hs hrs
  · have hM := cross_halfShift_common_M_eq r s x y hr hs hx hy hprod
    simpa [hM] using halfShift_prod_dvd_common_M_sq x y hx hy hxy

lemma finset_pair_eq_of_eq_or_swap {a b c d : Nat}
    (h : (a = c ∧ b = d) ∨ (a = d ∧ b = c)) :
    ({a, b} : Finset Nat) = {c, d} := by
  ext z
  rcases h with ⟨rfl, rfl⟩ | ⟨rfl, rfl⟩ <;> simp [Finset.pair_comm]

lemma nat_pair_eq_or_swap_of_mul_eq_add_eq
    (a b c d : Nat)
    (hmul : a * b = c * d)
    (hadd : a + b = c + d) :
    (a = c ∧ b = d) ∨ (a = d ∧ b = c) := by
  rcases le_total a c with hac | hca
  · rcases Nat.exists_eq_add_of_le hac with ⟨k, rfl⟩
    have hb : b = d + k := by omega
    subst b
    have hmul' : a * (d + k) = (a + k) * d := hmul
    have hmulInt :
        (a : Int) * ((d : Int) + (k : Int)) =
          ((a : Int) + (k : Int)) * (d : Int) := by
      exact_mod_cast hmul'
    have hkaInt : (k : Int) * (a : Int) = (k : Int) * (d : Int) := by
      ring_nf at hmulInt ⊢
      linarith
    have hka : k * a = k * d := by
      exact_mod_cast hkaInt
    by_cases hk : k = 0
    · subst k
      left
      constructor <;> omega
    · have hkpos : 0 < k := Nat.pos_of_ne_zero hk
      have had : a = d := Nat.mul_left_cancel hkpos hka
      right
      constructor
      · exact had
      · omega
  · rcases Nat.exists_eq_add_of_le hca with ⟨k, rfl⟩
    have hd : d = b + k := by omega
    subst d
    have hmul' : (c + k) * b = c * (b + k) := hmul
    have hmulInt :
        ((c : Int) + (k : Int)) * (b : Int) =
          (c : Int) * ((b : Int) + (k : Int)) := by
      exact_mod_cast hmul'
    have hkcInt : (k : Int) * (b : Int) = (k : Int) * (c : Int) := by
      ring_nf at hmulInt ⊢
      linarith
    have hkc : k * b = k * c := by
      exact_mod_cast hkcInt
    by_cases hk : k = 0
    · subst k
      left
      constructor <;> omega
    · have hkpos : 0 < k := Nat.pos_of_ne_zero hk
      have hbc : b = c := Nat.mul_left_cancel hkpos hkc
      right
      constructor <;> omega

lemma cross_halfShift_eq_or_swap_of_product_and_sum
    (r s x y : Nat)
    (hprod : (2 * r - 1) * (2 * s - 1) = (2 * x - 1) * (2 * y - 1))
    (hsum : (2 * r - 1) + (2 * s - 1) = (2 * x - 1) + (2 * y - 1)) :
    (2 * r - 1 = 2 * x - 1 ∧ 2 * s - 1 = 2 * y - 1) ∨
      (2 * r - 1 = 2 * y - 1 ∧ 2 * s - 1 = 2 * x - 1) := by
  exact nat_pair_eq_or_swap_of_mul_eq_add_eq
    (2 * r - 1) (2 * s - 1) (2 * x - 1) (2 * y - 1) hprod hsum

lemma odd_cross_halfShift_gap_double_identities
    (a b h u Y : Nat)
    (hY : h * u + 1 = 2 * Y) :
    2 * (Y + a * u) = (h + 2 * a) * u + 1 ∧
      2 * (Y + h * b) = h * (u + 2 * b) + 1 ∧
      2 * (2 * Y + a * u + h * b - 1) =
        (h + 2 * a) * u + h * (u + 2 * b) ∧
      2 * (Y + a * u + h * b + 2 * a * b) =
        (h + 2 * a) * (u + 2 * b) + 1 := by
  have hY' : 2 * Y = h * u + 1 := by omega
  constructor
  · nlinarith
  constructor
  · nlinarith
  constructor
  · have hinner :
        2 * Y + a * u + h * b - 1 = h * u + a * u + h * b := by
      omega
    rw [hinner]
    ring
  · nlinarith

lemma odd_cross_halfShift_gap_same_odd_product
    (a b h u Y : Nat)
    (hY : h * u + 1 = 2 * Y) :
    (2 * (Y + a * u) - 1) * (2 * (Y + h * b) - 1) =
      (2 * Y - 1) *
        (2 * (Y + a * u + h * b + 2 * a * b) - 1) := by
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hA, hB, _hn, hZ⟩
  have hYodd : 2 * Y - 1 = h * u := by omega
  have hAodd : 2 * (Y + a * u) - 1 = (h + 2 * a) * u := by omega
  have hBodd : 2 * (Y + h * b) - 1 = h * (u + 2 * b) := by omega
  have hZodd :
      2 * (Y + a * u + h * b + 2 * a * b) - 1 =
        (h + 2 * a) * (u + 2 * b) := by
    omega
  rw [hAodd, hBodd, hYodd, hZodd]
  ring

lemma odd_cross_halfShift_gap_first_modular
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hdiv1 :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2) :
    (Y + a * u) ∣ (Y + h * b - 1) ^ 2 ∧
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2 := by
  have hYge : 2 <= Y := by omega
  have hA : 2 <= Y + a * u := by omega
  have hB : 2 <= Y + h * b := by omega
  have hsum :
      2 * Y + a * u + h * b - 1 =
        (Y + a * u) + (Y + h * b) - 1 := by
    omega
  have hdivAB :
      (Y + a * u) * (Y + h * b) ∣
        ((Y + a * u) + (Y + h * b) - 1) ^ 2 := by
    simpa [hsum] using hdiv1
  exact halfShift_divisibility_modular (Y + a * u) (Y + h * b) hA hB hdivAB

lemma odd_cross_halfShift_gap_modular_product
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b)) :
    (Y + a * u) * (Y + h * b) ∣
      (2 * Y + a * u + h * b - 1) ^ 2 := by
  have hYge : 2 <= Y := by omega
  have hApos : 1 <= Y + a * u := by omega
  have hBpos : 1 <= Y + h * b := by omega
  have hsum :
      2 * Y + a * u + h * b - 1 =
        (Y + a * u) + (Y + h * b) - 1 := by
    omega
  simpa [hsum] using
    halfShift_modular_coprime_dvd_sumSubOne_sq
      (Y + a * u) (Y + h * b) hApos hBpos hAmod hBmod hABcop

lemma odd_cross_halfShift_gap_AB_from_edges
    (r s h u Y : Nat)
    (hr : 1 ≤ r) (hs : 1 ≤ s)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 ≤ h * u)
    (hAmod : (Y + r * u) ∣ (Y + h * s - 1) ^ 2)
    (hBmod : (Y + h * s) ∣ (Y + r * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + r * u) (Y + h * s)) :
    (Y + r * u) * (Y + h * s) ∣
      (2 * Y + r * u + h * s - 1) ^ 2 := by
  exact odd_cross_halfShift_gap_modular_product
    r s h u Y hr hs hY hYu hAmod hBmod hABcop

lemma halfShift_right_factor_dvd_common_M_sq
    (y z : Nat) (hy : 1 <= y) (hz : 1 <= z)
    (h : z ∣ (y - 1) ^ 2) :
    z ∣ (2 * y * z - (y + z - 1)) ^ 2 := by
  let M := 2 * y * z - (y + z - 1)
  have hyz : y + z - 1 <= y * z := by
    rcases Nat.exists_eq_add_of_le hy with ⟨y0, rfl⟩
    rcases Nat.exists_eq_add_of_le hz with ⟨z0, rfl⟩
    ring_nf
    omega
  have hle : y + z - 1 <= 2 * y * z := by nlinarith
  have hsum :
      (M : Int) + ((y - 1 : Nat) : Int) =
        (z : Int) * (2 * (y : Int) - 1) := by
    dsimp [M]
    rw [Nat.cast_sub hle]
    have hyCast : ((y + z - 1 : Nat) : Int) = (y : Int) + (z : Int) - 1 := by
      omega
    have hySubCast : ((y - 1 : Nat) : Int) = (y : Int) - 1 := by
      omega
    rw [hyCast, hySubCast]
    norm_num [Nat.cast_mul]
    ring
  have hmod : M ^ 2 ≡ (y - 1) ^ 2 [MOD z] := by
    rw [Nat.modEq_iff_dvd]
    refine ⟨-(((M : Int) - ((y - 1 : Nat) : Int)) *
      (2 * (y : Int) - 1)), ?_⟩
    calc
      (((y - 1) ^ 2 : Nat) : Int) - ((M ^ 2 : Nat) : Int)
          = ((y - 1 : Nat) : Int) ^ 2 - (M : Int) ^ 2 := by
            norm_num [Nat.cast_pow]
      _ = (((y - 1 : Nat) : Int) - (M : Int)) *
            (((y - 1 : Nat) : Int) + (M : Int)) := by ring
      _ = -(((M : Int) - ((y - 1 : Nat) : Int)) *
            ((M : Int) + ((y - 1 : Nat) : Int))) := by ring
      _ = (z : Int) * -(((M : Int) - ((y - 1 : Nat) : Int)) *
            (2 * (y : Int) - 1)) := by
            rw [hsum]
            ring
  have hzero : (y - 1) ^ 2 ≡ 0 [MOD z] :=
    Nat.modEq_zero_iff_dvd.mpr h
  exact Nat.modEq_zero_iff_dvd.mp (hmod.trans hzero)

lemma halfShift_right_common_M_sq_quotient_eq
    (y z k : Nat) (hy : 1 <= y) (hz : 1 <= z)
    (hk : (y - 1) ^ 2 = z * k) :
    (2 * y * z - (y + z - 1)) ^ 2 =
      z * (k +
        (2 * y * z - (y + z - 1) - (y - 1)) * (2 * y - 1)) := by
  let M := 2 * y * z - (y + z - 1)
  have hle : y + z - 1 <= 2 * y * z := by
    rcases Nat.exists_eq_add_of_le hy with ⟨y0, rfl⟩
    rcases Nat.exists_eq_add_of_le hz with ⟨z0, rfl⟩
    ring_nf
    omega
  have hpred_le_M : y - 1 <= M := by
    have hpred_add : (y - 1) + (y + z - 1) <= 2 * y * z := by
      rcases Nat.exists_eq_add_of_le hy with ⟨y0, rfl⟩
      rcases Nat.exists_eq_add_of_le hz with ⟨z0, rfl⟩
      ring_nf
      omega
    dsimp [M]
    exact Nat.le_sub_of_add_le hpred_add
  have hmain :
      M ^ 2 =
        (y - 1) ^ 2 +
          z * ((M - (y - 1)) * (2 * y - 1)) := by
    apply Int.ofNat.inj
    change ((M ^ 2 : Nat) : Int) =
      (((y - 1) ^ 2 + z * ((M - (y - 1)) * (2 * y - 1)) : Nat) : Int)
    norm_num [Nat.cast_pow, Nat.cast_add, Nat.cast_mul]
    rw [Nat.cast_sub hle, Nat.cast_sub hpred_le_M]
    have hySubCast : ((y - 1 : Nat) : Int) = (y : Int) - 1 := by
      omega
    have hsumCast : ((y + z - 1 : Nat) : Int) =
        (y : Int) + (z : Int) - 1 := by
      omega
    have htwoYSubCast : ((2 * y - 1 : Nat) : Int) = 2 * (y : Int) - 1 := by
      omega
    have hMCast : (M : Int) = 2 * (y : Int) * (z : Int) -
        ((y : Int) + (z : Int) - 1) := by
      dsimp [M]
      rw [Nat.cast_sub hle, hsumCast]
      norm_num [Nat.cast_mul]
    rw [hySubCast, hsumCast, htwoYSubCast, hMCast]
    norm_num [Nat.cast_mul]
    ring
  dsimp [M] at hmain
  rw [hmain, hk]
  ring

lemma halfShift_left_factor_dvd_pred_sq_of_common_M_sq
    (y z : Nat) (hy : 1 <= y) (hz : 1 <= z)
    (h : y ∣ (2 * y * z - (y + z - 1)) ^ 2) :
    y ∣ (z - 1) ^ 2 := by
  let M := 2 * y * z - (y + z - 1)
  have hle : y + z - 1 <= 2 * y * z := by
    rcases Nat.exists_eq_add_of_le hy with ⟨y0, rfl⟩
    rcases Nat.exists_eq_add_of_le hz with ⟨z0, rfl⟩
    ring_nf
    omega
  have hsum :
      (M : Int) + ((z - 1 : Nat) : Int) =
        (y : Int) * (2 * (z : Int) - 1) := by
    dsimp [M]
    rw [Nat.cast_sub hle]
    have hsumCast : ((y + z - 1 : Nat) : Int) =
        (y : Int) + (z : Int) - 1 := by
      omega
    have hzSubCast : ((z - 1 : Nat) : Int) = (z : Int) - 1 := by
      omega
    rw [hsumCast, hzSubCast]
    norm_num [Nat.cast_mul]
    ring
  have hmod : M ^ 2 ≡ (z - 1) ^ 2 [MOD y] := by
    rw [Nat.modEq_iff_dvd]
    refine ⟨-(((M : Int) - ((z - 1 : Nat) : Int)) *
      (2 * (z : Int) - 1)), ?_⟩
    calc
      (((z - 1) ^ 2 : Nat) : Int) - ((M ^ 2 : Nat) : Int)
          = ((z - 1 : Nat) : Int) ^ 2 - (M : Int) ^ 2 := by
            norm_num [Nat.cast_pow]
      _ = (((z - 1 : Nat) : Int) - (M : Int)) *
            (((z - 1 : Nat) : Int) + (M : Int)) := by ring
      _ = -(((M : Int) - ((z - 1 : Nat) : Int)) *
            ((M : Int) + ((z - 1 : Nat) : Int))) := by ring
      _ = (y : Int) * -(((M : Int) - ((z - 1 : Nat) : Int)) *
            (2 * (z : Int) - 1)) := by
            rw [hsum]
            ring
  have hzero : M ^ 2 ≡ 0 [MOD y] :=
    Nat.modEq_zero_iff_dvd.mpr h
  exact Nat.modEq_zero_iff_dvd.mp (hmod.symm.trans hzero)

lemma dvd_pred_sq_coprime
    (y z : Nat) (hy : 1 <= y)
    (h : z ∣ (y - 1) ^ 2) : Nat.Coprime y z := by
  by_contra hcop
  rw [Nat.Prime.not_coprime_iff_dvd] at hcop
  rcases hcop with ⟨p, hp, hpy, hpz⟩
  have hp_dvd_sq : p ∣ (y - 1) ^ 2 := dvd_trans hpz h
  have hp_dvd_pred : p ∣ y - 1 := hp.dvd_of_dvd_pow hp_dvd_sq
  have hp_dvd_one' : p ∣ y - (y - 1) := Nat.dvd_sub hpy hp_dvd_pred
  have hp_dvd_one : p ∣ 1 := by
    simpa [show y - (y - 1) = 1 by omega] using hp_dvd_one'
  exact hp.not_dvd_one hp_dvd_one

lemma pred_sq_quotient_coprime
    (y z k : Nat) (hy : 1 <= y)
    (hk : (y - 1) ^ 2 = z * k) : Nat.Coprime y k := by
  by_contra hcop
  rw [Nat.Prime.not_coprime_iff_dvd] at hcop
  rcases hcop with ⟨p, hp, hpy, hpk⟩
  have hp_dvd_prod : p ∣ z * k := dvd_mul_of_dvd_right hpk z
  have hp_dvd_sq : p ∣ (y - 1) ^ 2 := by
    simpa [hk] using hp_dvd_prod
  have hp_dvd_pred : p ∣ y - 1 := hp.dvd_of_dvd_pow hp_dvd_sq
  have hp_dvd_one' : p ∣ y - (y - 1) := Nat.dvd_sub hpy hp_dvd_pred
  have hp_dvd_one : p ∣ 1 := by
    simpa [show y - (y - 1) = 1 by omega] using hp_dvd_one'
  exact hp.not_dvd_one hp_dvd_one

lemma dvd_sq_complement_of_dvd_sq
    (d n : Nat) (hn : n <= d)
    (h : d ∣ n ^ 2) :
    d ∣ (d - n) ^ 2 := by
  have hmod : (d - n) ^ 2 ≡ n ^ 2 [MOD d] := by
    rw [Nat.modEq_iff_dvd]
    refine ⟨(2 * (n : Int) - (d : Int)), ?_⟩
    calc
      ((n ^ 2 : Nat) : Int) - (((d - n) ^ 2 : Nat) : Int)
          = (n : Int) ^ 2 - ((d : Int) - (n : Int)) ^ 2 := by
            rw [Nat.cast_pow, Nat.cast_pow, Nat.cast_sub hn]
      _ = (d : Int) * (2 * (n : Int) - (d : Int)) := by ring
  have hzero : n ^ 2 ≡ 0 [MOD d] :=
    Nat.modEq_zero_iff_dvd.mpr h
  exact Nat.modEq_zero_iff_dvd.mp (hmod.trans hzero)

lemma odd_cross_halfShift_gap_odd_factor_Z_complement_divisibility
    (h u p q : Nat)
    (hhu_pos : 1 <= h * u)
    (hhp : h < p) (huq : u < q)
    (hZ :
      (p * q + 1) ∣ (h * u - 1) ^ 2) :
    (p * q + 1) ∣ (p * q - h * u + 2) ^ 2 := by
  have hmul_le : h * u <= p * q := Nat.mul_le_mul hhp.le huq.le
  have hn : h * u - 1 <= p * q + 1 := by omega
  have hcomp :
      p * q + 1 - (h * u - 1) = p * q - h * u + 2 := by
    omega
  simpa [hcomp] using
    dvd_sq_complement_of_dvd_sq (p * q + 1) (h * u - 1) hn hZ

lemma odd_cross_halfShift_gap_odd_factor_Z_original_divisibility
    (h u p q : Nat)
    (hhu_pos : 1 <= h * u)
    (hhp : h < p) (huq : u < q)
    (hZcomp :
      (p * q + 1) ∣ (p * q - h * u + 2) ^ 2) :
    (p * q + 1) ∣ (h * u - 1) ^ 2 := by
  have hmul_le : h * u <= p * q := Nat.mul_le_mul hhp.le huq.le
  have hn : p * q - h * u + 2 <= p * q + 1 := by omega
  have hcomp :
      p * q + 1 - (p * q - h * u + 2) = h * u - 1 := by
    omega
  simpa [hcomp] using
    dvd_sq_complement_of_dvd_sq (p * q + 1) (p * q - h * u + 2) hn hZcomp

lemma odd_cross_halfShift_gap_odd_factor_Z_complement_iff
    (h u p q : Nat)
    (hhu_pos : 1 <= h * u)
    (hhp : h < p) (huq : u < q) :
    (p * q + 1) ∣ (p * q - h * u + 2) ^ 2 ↔
      (p * q + 1) ∣ (h * u - 1) ^ 2 := by
  constructor
  · exact odd_cross_halfShift_gap_odd_factor_Z_original_divisibility
      h u p q hhu_pos hhp huq
  · exact odd_cross_halfShift_gap_odd_factor_Z_complement_divisibility
      h u p q hhu_pos hhp huq

lemma odd_cross_halfShift_gap_odd_factor_edges_Z_complement_counterexample :
    ∃ h u p q : Nat,
      Odd h ∧ Odd u ∧ Odd p ∧ Odd q ∧
      3 <= h * u ∧ h < p ∧ u < q ∧
      (p * u + 1) ∣ (h * q - 1) ^ 2 ∧
      (h * q + 1) ∣ (p * u - 1) ^ 2 ∧
      (p * q + 1) ∣ (p * q - h * u + 2) ^ 2 := by
  refine ⟨3, 31, 217, 39, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · exact ⟨1, by norm_num⟩
  · exact ⟨15, by norm_num⟩
  · exact ⟨108, by norm_num⟩
  · exact ⟨19, by norm_num⟩
  all_goals norm_num

lemma odd_cross_halfShift_gap_core_YZ_coprime
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    Nat.Coprime Y (Y + a * u + h * b + 2 * a * b) := by
  have hYge : 2 <= Y := by omega
  exact dvd_pred_sq_coprime Y (Y + a * u + h * b + 2 * a * b)
    (le_trans (by decide : 1 <= 2) hYge) hZmod

lemma dvd_sq_double_of_dvd_sq
    (A t n m : Nat)
    (hn : n = 2 * A) (hm : m = 2 * t)
    (h : A ∣ t ^ 2) : n ∣ m ^ 2 := by
  rcases h with ⟨k, hk⟩
  refine ⟨2 * k, ?_⟩
  rw [hn, hm]
  rw [show (2 * t) ^ 2 = 4 * t ^ 2 by ring, hk]
  ring

lemma dvd_sq_double_two_of_dvd_sq
    (A t n m : Nat)
    (hn : n = 2 * A) (hm : m = 2 * t)
    (h : A ∣ t ^ 2) : 2 * n ∣ m ^ 2 := by
  rcases h with ⟨k, hk⟩
  refine ⟨k, ?_⟩
  rw [hn, hm]
  rw [show (2 * t) ^ 2 = 4 * t ^ 2 by ring, hk]
  ring

lemma odd_cross_halfShift_gap_core_odd_factor_edge_divisibilities
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    ((h + 2 * a) * u + 1) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
      (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
      ((h + 2 * a) * (u + 2 * b) + 1) ∣ (h * u - 1) ^ 2 := by
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hA2, hB2, _hN2, hZ2⟩
  have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := by
    omega
  have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := by
    omega
  have hZden :
      (h + 2 * a) * (u + 2 * b) + 1 =
        2 * (Y + a * u + h * b + 2 * a * b) := by
    omega
  have hBnum : h * (u + 2 * b) - 1 = 2 * (Y + h * b - 1) := by
    have hBpos : 1 <= Y + h * b := by omega
    omega
  have hAnum : (h + 2 * a) * u - 1 = 2 * (Y + a * u - 1) := by
    have hApos : 1 <= Y + a * u := by omega
    omega
  have hYnum : h * u - 1 = 2 * (Y - 1) := by
    have hYpos : 1 <= Y := by omega
    omega
  constructor
  · exact dvd_sq_double_of_dvd_sq
      (Y + a * u) (Y + h * b - 1)
      ((h + 2 * a) * u + 1) (h * (u + 2 * b) - 1)
      hAden hBnum hAmod
  constructor
  · exact dvd_sq_double_of_dvd_sq
      (Y + h * b) (Y + a * u - 1)
      (h * (u + 2 * b) + 1) ((h + 2 * a) * u - 1)
      hBden hAnum hBmod
  · exact dvd_sq_double_of_dvd_sq
      (Y + a * u + h * b + 2 * a * b) (Y - 1)
      ((h + 2 * a) * (u + 2 * b) + 1) (h * u - 1)
      hZden hYnum hZmod

lemma odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
      2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
      2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2 := by
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hA2, hB2, _hN2, hZ2⟩
  have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := by
    omega
  have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := by
    omega
  have hZden :
      (h + 2 * a) * (u + 2 * b) + 1 =
        2 * (Y + a * u + h * b + 2 * a * b) := by
    omega
  have hBnum : h * (u + 2 * b) - 1 = 2 * (Y + h * b - 1) := by
    have hBpos : 1 <= Y + h * b := by omega
    omega
  have hAnum : (h + 2 * a) * u - 1 = 2 * (Y + a * u - 1) := by
    have hApos : 1 <= Y + a * u := by omega
    omega
  have hYnum : h * u - 1 = 2 * (Y - 1) := by
    have hYpos : 1 <= Y := by omega
    omega
  constructor
  · exact dvd_sq_double_two_of_dvd_sq
      (Y + a * u) (Y + h * b - 1)
      ((h + 2 * a) * u + 1) (h * (u + 2 * b) - 1)
      hAden hBnum hAmod
  constructor
  · exact dvd_sq_double_two_of_dvd_sq
      (Y + h * b) (Y + a * u - 1)
      (h * (u + 2 * b) + 1) ((h + 2 * a) * u - 1)
      hBden hAnum hBmod
  · exact dvd_sq_double_two_of_dvd_sq
      (Y + a * u + h * b + 2 * a * b) (Y - 1)
      ((h + 2 * a) * (u + 2 * b) + 1) (h * u - 1)
      hZden hYnum hZmod

lemma odd_lt_odd_eq_add_two_mul
    (a b : Nat) (ha : Odd a) (hb : Odd b) (hab : a < b) :
    ∃ k : Nat, 1 <= k ∧ b = a + 2 * k := by
  rcases ha with ⟨ka, hka⟩
  rcases hb with ⟨kb, hkb⟩
  refine ⟨kb - ka, ?_, ?_⟩ <;> omega

lemma odd_cross_halfShift_gap_strict_refactor_parameters
    (h u p q : Nat)
    (hhodd : Odd h) (huodd : Odd u)
    (hpodd : Odd p) (hqodd : Odd q)
    (hhp : h < p) (huq : u < q) :
    ∃ a b : Nat, 1 <= a ∧ 1 <= b ∧
      p = h + 2 * a ∧ q = u + 2 * b := by
  rcases odd_lt_odd_eq_add_two_mul h p hhodd hpodd hhp with
    ⟨a, ha, hp⟩
  rcases odd_lt_odd_eq_add_two_mul u q huodd hqodd huq with
    ⟨b, hb, hq⟩
  exact ⟨a, b, ha, hb, hp, hq⟩

lemma odd_cross_halfShift_gap_strict_refactor_double_identities
    (a b h u p q Y : Nat)
    (hp : p = h + 2 * a) (hq : q = u + 2 * b)
    (hY : h * u + 1 = 2 * Y) :
    2 * (Y + a * u) = p * u + 1 ∧
      2 * (Y + h * b) = h * q + 1 ∧
      2 * (2 * Y + a * u + h * b - 1) =
        p * u + h * q ∧
      2 * (Y + a * u + h * b + 2 * a * b) =
        p * q + 1 := by
  subst p
  subst q
  exact odd_cross_halfShift_gap_double_identities a b h u Y hY

lemma odd_cross_halfShift_gap_hu_odd_of_halfshift
    (h u Y : Nat)
    (hY : h * u + 1 = 2 * Y) :
    Odd h ∧ Odd u := by
  have hhuOdd : Odd (h * u) := by
    refine ⟨Y - 1, ?_⟩
    omega
  exact ⟨Nat.Odd.of_mul_left hhuOdd, Nat.Odd.of_mul_right hhuOdd⟩

lemma odd_cross_halfShift_gap_core_odd_factor_parities
    (a b h u : Nat) (hhodd : Odd h) (huodd : Odd u) :
    Odd (h + 2 * a) ∧ Odd (u + 2 * b) := by
  constructor
  · rcases hhodd with ⟨kh, hkh⟩
    refine ⟨kh + a, ?_⟩
    omega
  · rcases huodd with ⟨ku, hku⟩
    refine ⟨ku + b, ?_⟩
    omega

lemma odd_cross_halfShift_gap_core_common_M_divisibilities
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    (Y + a * u) * (Y + h * b) ∣
        (2 * (Y + a * u) * (Y + h * b) -
          ((Y + a * u) + (Y + h * b) - 1)) ^ 2 ∧
      (Y + a * u + h * b + 2 * a * b) ∣
        (2 * (Y + a * u) * (Y + h * b) -
          ((Y + a * u) + (Y + h * b) - 1)) ^ 2 := by
  have hYge : 2 <= Y := by omega
  have hA : 2 <= Y + a * u := by omega
  have hB : 2 <= Y + h * b := by omega
  have hZge : 2 <= Y + a * u + h * b + 2 * a * b := by omega
  have hprodAB :
      (Y + a * u) * (Y + h * b) ∣
        ((Y + a * u) + (Y + h * b) - 1) ^ 2 := by
    simpa [show 2 * Y + a * u + h * b - 1 =
        (Y + a * u) + (Y + h * b) - 1 by omega] using
      odd_cross_halfShift_gap_modular_product
        a b h u Y ha hb hY hYu hAmod hBmod hABcop
  constructor
  · exact halfShift_prod_dvd_common_M_sq
      (Y + a * u) (Y + h * b) hA hB hprodAB
  · have hM :
      2 * (Y + a * u) * (Y + h * b) -
          ((Y + a * u) + (Y + h * b) - 1) =
        2 * Y * (Y + a * u + h * b + 2 * a * b) -
          (Y + (Y + a * u + h * b + 2 * a * b) - 1) := by
      exact cross_halfShift_common_M_eq
        (Y + a * u) (Y + h * b)
        Y (Y + a * u + h * b + 2 * a * b)
        hA hB hYge hZge
        (odd_cross_halfShift_gap_same_odd_product a b h u Y hY)
    rw [hM]
    exact halfShift_right_factor_dvd_common_M_sq
      Y (Y + a * u + h * b + 2 * a * b)
      (le_trans (by decide : 1 <= 2) hYge)
      (le_trans (by decide : 1 <= 2) hZge)
      hZmod

lemma odd_cross_halfShift_gap_AB_add_ab_eq_YZ
    (a b h u Y : Nat)
    (hY : h * u + 1 = 2 * Y) :
    (Y + a * u) * (Y + h * b) + a * b =
      Y * (Y + a * u + h * b + 2 * a * b) := by
  apply Int.ofNat.inj
  have hYint : (h : Int) * (u : Int) + 1 = 2 * (Y : Int) := by
    exact_mod_cast hY
  have hYmul :
      (h : Int) * (u : Int) * (a : Int) * (b : Int) +
          (a : Int) * (b : Int) =
        2 * (Y : Int) * (a : Int) * (b : Int) := by
    calc
      (h : Int) * (u : Int) * (a : Int) * (b : Int) +
          (a : Int) * (b : Int)
          = ((h : Int) * (u : Int) + 1) * ((a : Int) * (b : Int)) := by
            ring
      _ = (2 * (Y : Int)) * ((a : Int) * (b : Int)) := by rw [hYint]
      _ = 2 * (Y : Int) * (a : Int) * (b : Int) := by ring
  norm_num [Nat.cast_add, Nat.cast_mul]
  ring_nf at hYmul ⊢
  linarith

lemma odd_cross_halfShift_gap_Y_dvd_AB_iff_Y_dvd_ab
    (a b h u Y : Nat)
    (hY : h * u + 1 = 2 * Y) :
    Y ∣ (Y + a * u) * (Y + h * b) ↔ Y ∣ a * b := by
  have hsum := odd_cross_halfShift_gap_AB_add_ab_eq_YZ a b h u Y hY
  have hYsum :
      Y ∣ (Y + a * u) * (Y + h * b) + a * b := by
    exact ⟨Y + a * u + h * b + 2 * a * b, hsum⟩
  constructor
  · intro hAB
    exact (Nat.dvd_add_iff_right hAB).mpr hYsum
  · intro hab
    exact (Nat.dvd_add_iff_left hab).mpr hYsum

lemma dvd_sq_of_dvd_double_sq
    (A t n m : Nat)
    (hn : n = 2 * A) (hm : m = 2 * t)
    (h : 2 * n ∣ m ^ 2) : A ∣ t ^ 2 := by
  rcases h with ⟨k, hk⟩
  refine ⟨k, ?_⟩
  have h4 : 4 * (A * k) = 4 * t ^ 2 := by
    calc
      4 * (A * k) = (2 * (2 * A)) * k := by ring
      _ = (2 * n) * k := by rw [hn]
      _ = m ^ 2 := by rw [← hk]
      _ = (2 * t) ^ 2 := by rw [hm]
      _ = 4 * t ^ 2 := by ring
  exact (Nat.mul_left_cancel (by decide : 0 < 4) h4).symm

lemma odd_cross_halfShift_gap_normalized_common_M_quotients
    (a b h u Y kAB kZ : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hkAB :
      (2 * Y + a * u + h * b - 1) ^ 2 =
        (Y + a * u) * (Y + h * b) * kAB)
    (hkZ :
      (Y - 1) ^ 2 =
        (Y + a * u + h * b + 2 * a * b) * kZ) :
    (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 =
      (Y + a * u) * (Y + h * b) *
        (kAB +
          4 * ((Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1))) ∧
    (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 =
      (Y + a * u + h * b + 2 * a * b) *
        (kZ +
          (2 * (Y + a * u) * (Y + h * b) -
              ((Y + a * u) + (Y + h * b) - 1) -
            (Y - 1)) *
          (2 * Y - 1)) := by
  have hYge : 2 <= Y := by omega
  have hA : 2 <= Y + a * u := by omega
  have hB : 2 <= Y + h * b := by omega
  have hZge : 2 <= Y + a * u + h * b + 2 * a * b := by omega
  constructor
  · have hsum :
        2 * Y + a * u + h * b - 1 =
          (Y + a * u) + (Y + h * b) - 1 := by
      omega
    exact halfShift_prod_common_M_sq_quotient_eq
      (Y + a * u) (Y + h * b) kAB hA hB
      (by simpa [hsum] using hkAB)
  · have hM :
      2 * (Y + a * u) * (Y + h * b) -
          ((Y + a * u) + (Y + h * b) - 1) =
        2 * Y * (Y + a * u + h * b + 2 * a * b) -
          (Y + (Y + a * u + h * b + 2 * a * b) - 1) := by
      exact cross_halfShift_common_M_eq
        (Y + a * u) (Y + h * b)
        Y (Y + a * u + h * b + 2 * a * b)
        hA hB hYge hZge
        (odd_cross_halfShift_gap_same_odd_product a b h u Y hY)
    simpa [hM] using
      halfShift_right_common_M_sq_quotient_eq
        Y (Y + a * u + h * b + 2 * a * b) kZ
        (le_trans (by decide : 1 <= 2) hYge)
        (le_trans (by decide : 1 <= 2) hZge)
        hkZ

lemma odd_cross_halfShift_gap_exact_factor2_halved_edges_core
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (_hYu : 3 <= h * u)
    (hExact :
      2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
        2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
        2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2) :
    (Y + a * u) ∣ (Y + h * b - 1) ^ 2 ∧
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2 ∧
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 := by
  rcases hExact with ⟨hAexact, hBexact, hZexact⟩
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hAden_rev, hBden_rev, _hNden_rev, hZden_rev⟩
  have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := hAden_rev.symm
  have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := hBden_rev.symm
  have hZden :
      (h + 2 * a) * (u + 2 * b) + 1 =
        2 * (Y + a * u + h * b + 2 * a * b) := hZden_rev.symm
  have hBnum : h * (u + 2 * b) - 1 = 2 * (Y + h * b - 1) := by
    have hBpos : 1 <= Y + h * b := by omega
    omega
  have hAnum : (h + 2 * a) * u - 1 = 2 * (Y + a * u - 1) := by
    have hApos : 1 <= Y + a * u := by omega
    omega
  have hYnum : h * u - 1 = 2 * (Y - 1) := by
    have hYpos : 1 <= Y := by omega
    omega
  constructor
  · exact dvd_sq_of_dvd_double_sq
      (Y + a * u) (Y + h * b - 1)
      ((h + 2 * a) * u + 1) (h * (u + 2 * b) - 1)
      hAden hBnum hAexact
  constructor
  · exact dvd_sq_of_dvd_double_sq
      (Y + h * b) (Y + a * u - 1)
      (h * (u + 2 * b) + 1) ((h + 2 * a) * u - 1)
      hBden hAnum hBexact
  · exact dvd_sq_of_dvd_double_sq
      (Y + a * u + h * b + 2 * a * b) (Y - 1)
      ((h + 2 * a) * (u + 2 * b) + 1) (h * u - 1)
      hZden hYnum hZexact

lemma odd_cross_halfShift_gap_fourth_edge_of_Y_dvd_AB
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAB :
      (Y + a * u) * (Y + h * b) ∣
        ((Y + a * u) + (Y + h * b) - 1) ^ 2)
    (hYAB : Y ∣ (Y + a * u) * (Y + h * b)) :
    Y ∣ (Y + a * u + h * b + 2 * a * b - 1) ^ 2 := by
  have hY_S :
      Y ∣ ((Y + a * u) + (Y + h * b) - 1) ^ 2 :=
    dvd_trans hYAB hAB
  have hYab : Y ∣ a * b :=
    (odd_cross_halfShift_gap_Y_dvd_AB_iff_Y_dvd_ab a b h u Y hY).mp hYAB
  rcases hYab with ⟨k, hk⟩
  have hmod :
      (Y + a * u + h * b + 2 * a * b - 1) ≡
        ((Y + a * u) + (Y + h * b) - 1) [MOD Y] := by
    rw [Nat.modEq_iff_dvd]
    refine ⟨(1 - 2 * (k : Int)), ?_⟩
    have hleft :
        ((Y + a * u + h * b + 2 * a * b - 1 : Nat) : Int) =
          (Y : Int) + (a : Int) * (u : Int) + (h : Int) * (b : Int) +
            2 * (a : Int) * (b : Int) - 1 := by
      rw [Nat.cast_sub (by omega :
        1 <= Y + a * u + h * b + 2 * a * b)]
      norm_num [Nat.cast_add, Nat.cast_mul]
    have hright :
        ((((Y + a * u) + (Y + h * b) - 1) : Nat) : Int) =
          2 * (Y : Int) + (a : Int) * (u : Int) + (h : Int) * (b : Int) -
            1 := by
      rw [Nat.cast_sub (by omega :
        1 <= (Y + a * u) + (Y + h * b))]
      norm_num [Nat.cast_add, Nat.cast_mul]
      ring
    have hkInt : (a : Int) * (b : Int) = (Y : Int) * (k : Int) := by
      exact_mod_cast hk
    rw [hleft, hright]
    nlinarith [hkInt]
  have hsqmod :
      (Y + a * u + h * b + 2 * a * b - 1) ^ 2 ≡
        ((Y + a * u) + (Y + h * b) - 1) ^ 2 [MOD Y] :=
    hmod.pow 2
  have hzero :
      ((Y + a * u) + (Y + h * b) - 1) ^ 2 ≡ 0 [MOD Y] :=
    Nat.modEq_zero_iff_dvd.mpr hY_S
  exact Nat.modEq_zero_iff_dvd.mp (hsqmod.trans hzero)

lemma odd_cross_halfShift_gap_fourth_edge_of_modular_edges_and_Y_dvd_AB
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hYAB : Y ∣ (Y + a * u) * (Y + h * b)) :
    Y ∣ (Y + a * u + h * b + 2 * a * b - 1) ^ 2 := by
  have hAB_core :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2 :=
    odd_cross_halfShift_gap_modular_product
      a b h u Y ha hb hY hYu hAmod hBmod hABcop
  have hAB_sum :
      (Y + a * u) * (Y + h * b) ∣
        ((Y + a * u) + (Y + h * b) - 1) ^ 2 := by
    have hsum :
        2 * Y + a * u + h * b - 1 =
          (Y + a * u) + (Y + h * b) - 1 := by
      omega
    simpa [hsum] using hAB_core
  exact odd_cross_halfShift_gap_fourth_edge_of_Y_dvd_AB
    a b h u Y ha hb hY hYu hAB_sum hYAB

lemma odd_cross_halfShift_gap_core_ordered_ABZ_product_data
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u) :
    2 <= Y ∧
      Y < Y + a * u ∧
      Y < Y + h * b ∧
      Y + a * u < Y + a * u + h * b + 2 * a * b ∧
      Y + h * b < Y + a * u + h * b + 2 * a * b ∧
      (2 * (Y + a * u) - 1) * (2 * (Y + h * b) - 1) =
        (2 * Y - 1) *
          (2 * (Y + a * u + h * b + 2 * a * b) - 1) := by
  have hhu_pos : 0 < h * u := by omega
  have hupos : 0 < u := pos_of_mul_pos_right hhu_pos (Nat.zero_le h)
  have hhpos : 0 < h := pos_of_mul_pos_left hhu_pos (Nat.zero_le u)
  have haupos : 0 < a * u := Nat.mul_pos (by omega) hupos
  have hhbpos : 0 < h * b := Nat.mul_pos hhpos (by omega)
  have habpos : 0 < a * b := Nat.mul_pos (by omega) (by omega)
  refine ⟨by omega, by omega, by omega, by omega, by omega, ?_⟩
  exact odd_cross_halfShift_gap_same_odd_product a b h u Y hY

lemma odd_cross_halfShift_gap_Z_quotient_data
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    ∃ kZ : Nat,
      (Y - 1) ^ 2 =
          (Y + a * u + h * b + 2 * a * b) * kZ ∧
        0 < kZ ∧ kZ < Y ∧ Nat.Coprime Y kZ ∧
        (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
        Y ^ 2 + 1 := by
  rcases hZmod with ⟨kZ, hkZ⟩
  have hYge : 2 <= Y := by omega
  have hZgtY : Y < Y + a * u + h * b + 2 * a * b := by
    have htwoab_pos : 0 < 2 * a * b := by
      exact Nat.mul_pos (Nat.mul_pos (by decide : 0 < 2) (by omega)) (by omega)
    omega
  have hkZpos : 0 < kZ := by
    by_contra hkZzero
    have hkZ_eq : kZ = 0 := Nat.eq_zero_of_not_pos hkZzero
    have hpred_sq_pos : 0 < (Y - 1) ^ 2 := by
      exact pow_pos (by omega : 0 < Y - 1) 2
    rw [hkZ_eq, mul_zero] at hkZ
    omega
  have hkZltY : kZ < Y := by
    by_contra hnot
    have hYle : Y <= kZ := Nat.le_of_not_gt hnot
    have hmul_le :
        (Y + a * u + h * b + 2 * a * b) * Y <=
          (Y + a * u + h * b + 2 * a * b) * kZ :=
      Nat.mul_le_mul_left (Y + a * u + h * b + 2 * a * b) hYle
    have hsq_lt :
        (Y - 1) ^ 2 <
          (Y + a * u + h * b + 2 * a * b) * Y := by
      have hYpos : 0 < Y := by omega
      have hpred_lt_Y : Y - 1 < Y := by omega
      have hpred_sq_lt : (Y - 1) ^ 2 < Y ^ 2 := by
        exact Nat.pow_lt_pow_left hpred_lt_Y (by decide : 2 ≠ 0)
      have hY_sq_lt :
          Y ^ 2 < (Y + a * u + h * b + 2 * a * b) * Y := by
        rw [pow_two]
        simpa [Nat.mul_comm] using Nat.mul_lt_mul_of_pos_right hZgtY hYpos
      exact lt_trans hpred_sq_lt hY_sq_lt
    rw [← hkZ] at hmul_le
    exact (not_lt_of_ge hmul_le) hsq_lt
  have hYkZcop : Nat.Coprime Y kZ :=
    pred_sq_quotient_coprime
      Y (Y + a * u + h * b + 2 * a * b) kZ
      (le_trans (by decide : 1 <= 2) hYge) hkZ
  have hkZ_expanded :
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
        Y ^ 2 + 1 := by
    have hYpred_sq_add : (Y - 1) ^ 2 + 2 * Y = Y ^ 2 + 1 := by
      rcases Nat.exists_eq_add_of_le hYge with ⟨Y0, rfl⟩
      have hsub : 2 + Y0 - 1 = Y0 + 1 := by omega
      rw [hsub]
      ring
    calc
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
          (Y - 1) ^ 2 + 2 * Y := by rw [← hkZ]
      _ = Y ^ 2 + 1 := hYpred_sq_add
  exact ⟨kZ, hkZ, hkZpos, hkZltY, hYkZcop, hkZ_expanded⟩

lemma odd_cross_halfShift_gap_Y_dvd_AB_of_Y_dvd_AB_mul_Z_quotient
    (a b h u Y kZ : Nat)
    (hYkZcop : Nat.Coprime Y kZ)
    (hYABkZ : Y ∣ (Y + a * u) * (Y + h * b) * kZ) :
    Y ∣ (Y + a * u) * (Y + h * b) := by
  exact hYkZcop.dvd_of_dvd_mul_right hYABkZ

lemma odd_cross_halfShift_gap_Y_dvd_ab_of_Y_dvd_ab_mul_Z_quotient
    (a b Y kZ : Nat)
    (hYkZcop : Nat.Coprime Y kZ)
    (hYabkZ : Y ∣ a * b * kZ) :
    Y ∣ a * b := by
  exact hYkZcop.dvd_of_dvd_mul_right hYabkZ

lemma odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_Y_dvd_ab
    (a b Y kZ : Nat)
    (hYab : Y ∣ a * b) :
    Y ∣ a * b * kZ := by
  exact dvd_mul_of_dvd_left hYab kZ

lemma odd_cross_halfShift_gap_Y_dvd_AB_mul_Z_quotient_iff_Y_dvd_ab_mul_Z_quotient
    (a b h u Y kZ : Nat)
    (hY : h * u + 1 = 2 * Y) :
    Y ∣ (Y + a * u) * (Y + h * b) * kZ ↔
      Y ∣ a * b * kZ := by
  have hAB_add :
      (Y + a * u) * (Y + h * b) + a * b =
        Y * (Y + a * u + h * b + 2 * a * b) :=
    odd_cross_halfShift_gap_AB_add_ab_eq_YZ a b h u Y hY
  have hYsum :
      Y ∣ (Y + a * u) * (Y + h * b) * kZ + a * b * kZ := by
    refine ⟨(Y + a * u + h * b + 2 * a * b) * kZ, ?_⟩
    calc
      (Y + a * u) * (Y + h * b) * kZ + a * b * kZ =
          ((Y + a * u) * (Y + h * b) + a * b) * kZ := by ring
      _ = (Y * (Y + a * u + h * b + 2 * a * b)) * kZ := by rw [hAB_add]
      _ = Y * ((Y + a * u + h * b + 2 * a * b) * kZ) := by ring
  constructor
  · intro hYABkZ
    exact (Nat.dvd_add_iff_right hYABkZ).mpr hYsum
  · intro hYabkZ
    exact (Nat.dvd_add_iff_left hYabkZ).mpr hYsum

lemma odd_cross_halfShift_gap_Y_dvd_AB_mul_Z_quotient_of_exact_halved_ABZ
    (a b h u Y kZ : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (_hYu : 3 <= h * u)
    (_hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (_hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (_hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (_hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (_hkZ :
      (Y - 1) ^ 2 =
        (Y + a * u + h * b + 2 * a * b) * kZ)
    (_hkZ_expanded :
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
        Y ^ 2 + 1)
    (hYabkZ : Y ∣ a * b * kZ) :
    Y ∣ (Y + a * u) * (Y + h * b) * kZ := by
  have hAB_add :
      (Y + a * u) * (Y + h * b) + a * b =
        Y * (Y + a * u + h * b + 2 * a * b) :=
    odd_cross_halfShift_gap_AB_add_ab_eq_YZ a b h u Y hY
  have hYsum :
      Y ∣ (Y + a * u) * (Y + h * b) * kZ + a * b * kZ := by
    refine ⟨(Y + a * u + h * b + 2 * a * b) * kZ, ?_⟩
    calc
      (Y + a * u) * (Y + h * b) * kZ + a * b * kZ =
          ((Y + a * u) * (Y + h * b) + a * b) * kZ := by ring
      _ = (Y * (Y + a * u + h * b + 2 * a * b)) * kZ := by rw [hAB_add]
      _ = Y * ((Y + a * u + h * b + 2 * a * b) * kZ) := by ring
  exact (Nat.dvd_add_iff_left hYabkZ).mpr hYsum

lemma odd_cross_halfShift_gap_Z_le_pred_sq_of_exact_Z
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    Y + a * u + h * b + 2 * a * b <= (Y - 1) ^ 2 := by
  rcases odd_cross_halfShift_gap_Z_quotient_data
      a b h u Y ha hb hY hYu hZmod with
    ⟨kZ, hkZ, hkZpos, _hkZltY, _hYkZcop, _hkZ_expanded⟩
  rw [hkZ]
  nth_rewrite 1 [← Nat.mul_one (Y + a * u + h * b + 2 * a * b)]
  exact Nat.mul_le_mul_left
    (Y + a * u + h * b + 2 * a * b) (by omega : 1 <= kZ)

lemma odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAB :
      (Y + a * u) * (Y + h * b) ∣
        ((Y + a * u) + (Y + h * b) - 1) ^ 2)
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hExact :
      2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
        2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
        2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2) :
    False := by
  have hAB_core :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2 := by
    have hsum :
        2 * Y + a * u + h * b - 1 =
          (Y + a * u) + (Y + h * b) - 1 := by
      omega
    simpa [hsum] using hAB
  rcases odd_cross_halfShift_gap_first_modular
      a b h u Y ha hb hY hYu hAB_core with
    ⟨hAmod, hBmod⟩
  have hHalved :=
    odd_cross_halfShift_gap_exact_factor2_halved_edges_core
      a b h u Y ha hb hY hYu hExact
  have hZmod_from_exact :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 := hHalved.2.2
  have hcommon := odd_cross_halfShift_gap_core_common_M_divisibilities
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod
  have hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b) :=
    odd_cross_halfShift_gap_core_YZ_coprime
      a b h u Y ha hb hY hYu hZmod
  have hYge : 2 <= Y := by omega
  rcases odd_cross_halfShift_gap_Z_quotient_data
      a b h u Y ha hb hY hYu hZmod with
    ⟨kZ, hkZ, hkZpos, hkZltY, hYkZcop, hkZ_expanded⟩
  linarith

lemma odd_cross_halfShift_gap_normalized_common_M_descent
    (a b h u Y kZ kMAB kMZ : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b))
    (hYkZcop : Nat.Coprime Y kZ)
    (hAB_add :
      (Y + a * u) * (Y + h * b) + a * b =
        Y * (Y + a * u + h * b + 2 * a * b))
    (hkZ_expanded :
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
        Y ^ 2 + 1)
    (hkMAB :
      (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 =
          (Y + a * u) * (Y + h * b) * kMAB)
    (hkMZ :
      (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 =
          (Y + a * u + h * b + 2 * a * b) * kMZ) :
    False := by
  have hYge : 2 <= Y := by omega
  have hA2 : 2 <= Y + a * u := by omega
  have hB2 : 2 <= Y + h * b := by omega
  have hAB_common :
      (Y + a * u) * (Y + h * b) ∣
        (2 * (Y + a * u) * (Y + h * b) -
          ((Y + a * u) + (Y + h * b) - 1)) ^ 2 := by
    exact ⟨kMAB, hkMAB⟩
  have hAB_sum :
      (Y + a * u) * (Y + h * b) ∣
        ((Y + a * u) + (Y + h * b) - 1) ^ 2 := by
    exact halfShift_prod_dvd_sumSubOne_sq_of_common_M_sq
      (Y + a * u) (Y + h * b) hA2 hB2 hAB_common
  have hAB :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2 := by
    have hsum :
        2 * Y + a * u + h * b - 1 =
          (Y + a * u) + (Y + h * b) - 1 := by
      omega
    simpa [hsum] using hAB_sum
  have hEdges := odd_cross_halfShift_gap_first_modular
    a b h u Y ha hb hY hYu hAB
  have hABcop : Nat.Coprime (Y + a * u) (Y + h * b) := by
    exact halfShift_divisibility_coprime
      (Y + a * u) (Y + h * b) hA2 hB2 hAB_sum
  have hYpred_sq_add : (Y - 1) ^ 2 + 2 * Y = Y ^ 2 + 1 := by
    rcases Nat.exists_eq_add_of_le hYge with ⟨Y0, rfl⟩
    have hsub : 2 + Y0 - 1 = Y0 + 1 := by omega
    rw [hsub]
    ring
  have hkZsq :
      (Y - 1) ^ 2 = (Y + a * u + h * b + 2 * a * b) * kZ := by
    nlinarith [hYpred_sq_add, hkZ_expanded]
  have hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 := by
    exact ⟨kZ, hkZsq⟩
  have hExact :=
    odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities
      a b h u Y ha hb hY hYu hEdges.1 hEdges.2 hZmod
  exact odd_cross_halfShift_gap_exact_factor2_edges_obstruction_core
    a b h u Y ha hb hY hYu hAB_sum hZmod hABcop hExact

lemma odd_cross_halfShift_gap_normalized_quotient_descent
    (a b h u Y kAB kZ kMAB kMZ : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b))
    (hYkZcop : Nat.Coprime Y kZ)
    (hAB_add :
      (Y + a * u) * (Y + h * b) + a * b =
        Y * (Y + a * u + h * b + 2 * a * b))
    (hkAB :
      (2 * Y + a * u + h * b - 1) ^ 2 =
        (Y + a * u) * (Y + h * b) * kAB)
    (hkZ :
      (Y - 1) ^ 2 =
        (Y + a * u + h * b + 2 * a * b) * kZ)
    (hkZpos : 0 < kZ)
    (hkZltY : kZ < Y)
    (hkZ_expanded :
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
        Y ^ 2 + 1)
    (hkMAB :
      (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 =
          (Y + a * u) * (Y + h * b) * kMAB)
    (hkMZ :
      (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 =
          (Y + a * u + h * b + 2 * a * b) * kMZ) :
    False := by
  have hYge : 2 <= Y := by omega
  have hA2 : 2 <= Y + a * u := by omega
  have hB2 : 2 <= Y + h * b := by omega
  have hABdiv :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2 := by
    exact ⟨kAB, hkAB⟩
  have hABcop : Nat.Coprime (Y + a * u) (Y + h * b) := by
    have hsum :
        2 * Y + a * u + h * b - 1 =
          (Y + a * u) + (Y + h * b) - 1 := by
      omega
    exact halfShift_divisibility_coprime
      (Y + a * u) (Y + h * b) hA2 hB2
      (by simpa [hsum] using hABdiv)
  have hEdges := odd_cross_halfShift_gap_first_modular
    a b h u Y ha hb hY hYu hABdiv
  have hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 := by
    exact ⟨kZ, hkZ⟩
  exact odd_cross_halfShift_gap_normalized_common_M_descent
    a b h u Y kZ kMAB kMZ
    ha hb hY hYu hYZcop hYkZcop hAB_add hkZ_expanded hkMAB hkMZ

lemma odd_cross_halfShift_gap_halved_edges_valuation_obstruction_direct
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    False := by
  have hAB :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2 :=
    odd_cross_halfShift_gap_modular_product
      a b h u Y ha hb hY hYu hAmod hBmod hABcop
  have hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b) :=
    odd_cross_halfShift_gap_core_YZ_coprime
      a b h u Y ha hb hY hYu hZmod
  have hcommon := odd_cross_halfShift_gap_core_common_M_divisibilities
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod
  have hAB_add :
      (Y + a * u) * (Y + h * b) + a * b =
        Y * (Y + a * u + h * b + 2 * a * b) :=
    odd_cross_halfShift_gap_AB_add_ab_eq_YZ a b h u Y hY
  rcases hAB with ⟨kAB, hkAB⟩
  rcases hZmod with ⟨kZ, hkZ⟩
  have hYge : 2 <= Y := by omega
  have hYkZcop : Nat.Coprime Y kZ :=
    pred_sq_quotient_coprime
      Y (Y + a * u + h * b + 2 * a * b) kZ
      (le_trans (by decide : 1 <= 2) hYge) hkZ
  have hZgtY : Y < Y + a * u + h * b + 2 * a * b := by
    have hapos : 0 < a := by omega
    have hbpos : 0 < b := by omega
    have htwoab_pos : 0 < 2 * a * b := by
      exact Nat.mul_pos (Nat.mul_pos (by decide : 0 < 2) hapos) hbpos
    have htail_pos : 0 < a * u + h * b + 2 * a * b := by
      omega
    omega
  have hkZpos : 0 < kZ := by
    by_contra hkZzero
    have hkZ_eq : kZ = 0 := Nat.eq_zero_of_not_pos hkZzero
    have hpred_sq_pos : 0 < (Y - 1) ^ 2 := by
      exact pow_pos (by omega : 0 < Y - 1) 2
    rw [hkZ_eq, mul_zero] at hkZ
    omega
  have hkZltY : kZ < Y := by
    by_contra hnot
    have hYle : Y <= kZ := Nat.le_of_not_gt hnot
    have hmul_le :
        (Y + a * u + h * b + 2 * a * b) * Y <=
          (Y + a * u + h * b + 2 * a * b) * kZ :=
      Nat.mul_le_mul_left (Y + a * u + h * b + 2 * a * b) hYle
    have hsq_lt :
        (Y - 1) ^ 2 <
          (Y + a * u + h * b + 2 * a * b) * Y := by
      have hYpos : 0 < Y := by omega
      have hpred_lt_Y : Y - 1 < Y := by omega
      have hpred_sq_lt : (Y - 1) ^ 2 < Y ^ 2 := by
        exact Nat.pow_lt_pow_left hpred_lt_Y (by decide : 2 ≠ 0)
      have hY_sq_lt :
          Y ^ 2 < (Y + a * u + h * b + 2 * a * b) * Y := by
        rw [pow_two]
        simpa [Nat.mul_comm] using Nat.mul_lt_mul_of_pos_right hZgtY hYpos
      exact lt_trans hpred_sq_lt hY_sq_lt
    rw [← hkZ] at hmul_le
    exact (not_lt_of_ge hmul_le) hsq_lt
  have hkZ_expanded :
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
        Y ^ 2 + 1 := by
    have hYpred_sq_add : (Y - 1) ^ 2 + 2 * Y = Y ^ 2 + 1 := by
      rcases Nat.exists_eq_add_of_le hYge with ⟨Y0, rfl⟩
      have hsub : 2 + Y0 - 1 = Y0 + 1 := by omega
      rw [hsub]
      ring
    calc
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
          (Y - 1) ^ 2 + 2 * Y := by rw [← hkZ]
      _ = Y ^ 2 + 1 := hYpred_sq_add
  rcases hcommon.1 with ⟨kMAB, hkMAB⟩
  rcases hcommon.2 with ⟨kMZ, hkMZ⟩
  exact odd_cross_halfShift_gap_normalized_quotient_descent
    a b h u Y kAB kZ kMAB kMZ
    ha hb hY hYu hYZcop hYkZcop hAB_add hkAB hkZ
    hkZpos hkZltY hkZ_expanded hkMAB hkMZ

lemma odd_cross_halfShift_gap_exact_factor2_split_divisibility_descent
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hAexact :
      2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2)
    (hBexact :
      2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2)
    (hZexact :
      2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2) :
    False := by
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hAden_rev, hBden_rev, _hNden_rev, hZden_rev⟩
  have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := hAden_rev.symm
  have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := hBden_rev.symm
  have hZden :
      (h + 2 * a) * (u + 2 * b) + 1 =
        2 * (Y + a * u + h * b + 2 * a * b) := hZden_rev.symm
  have hBnum : h * (u + 2 * b) - 1 = 2 * (Y + h * b - 1) := by
    have hBpos : 1 <= Y + h * b := by omega
    omega
  have hAnum : (h + 2 * a) * u - 1 = 2 * (Y + a * u - 1) := by
    have hApos : 1 <= Y + a * u := by omega
    omega
  have hYnum : h * u - 1 = 2 * (Y - 1) := by
    have hYpos : 1 <= Y := by omega
    omega
  have hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2 :=
    dvd_sq_of_dvd_double_sq
      (Y + a * u) (Y + h * b - 1)
      ((h + 2 * a) * u + 1) (h * (u + 2 * b) - 1)
      hAden hBnum hAexact
  have hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2 :=
    dvd_sq_of_dvd_double_sq
      (Y + h * b) (Y + a * u - 1)
      (h * (u + 2 * b) + 1) ((h + 2 * a) * u - 1)
      hBden hAnum hBexact
  have hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 :=
    dvd_sq_of_dvd_double_sq
      (Y + a * u + h * b + 2 * a * b) (Y - 1)
      ((h + 2 * a) * (u + 2 * b) + 1) (h * u - 1)
      hZden hYnum hZexact
  exact odd_cross_halfShift_gap_halved_edges_valuation_obstruction_direct
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod

lemma odd_cross_halfShift_gap_halved_product_Z_descent_core
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAB :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2)
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    False := by
  have hYge : 2 <= Y := by omega
  have hA2 : 2 <= Y + a * u := by omega
  have hB2 : 2 <= Y + h * b := by omega
  have hABmod := odd_cross_halfShift_gap_first_modular
    a b h u Y ha hb hY hYu hAB
  rcases hABmod with ⟨hAmod, hBmod⟩
  have hABcop : Nat.Coprime (Y + a * u) (Y + h * b) := by
    have hsum :
        2 * Y + a * u + h * b - 1 =
          (Y + a * u) + (Y + h * b) - 1 := by
      omega
    exact halfShift_divisibility_coprime
      (Y + a * u) (Y + h * b) hA2 hB2
      (by simpa [hsum] using hAB)
  have hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b) :=
    odd_cross_halfShift_gap_core_YZ_coprime
      a b h u Y ha hb hY hYu hZmod
  have hcommon := odd_cross_halfShift_gap_core_common_M_divisibilities
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod
  have hExact :=
    odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities
      a b h u Y ha hb hY hYu hAmod hBmod hZmod
  rcases hExact with ⟨hAexact, hBexact, hZexact⟩
  exact odd_cross_halfShift_gap_exact_factor2_split_divisibility_descent
    a b h u Y ha hb hY hYu hABcop hAexact hBexact hZexact

lemma odd_cross_halfShift_gap_halved_edges_valuation_obstruction_core
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    False := by
  have hAB :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2 :=
    odd_cross_halfShift_gap_modular_product
      a b h u Y ha hb hY hYu hAmod hBmod hABcop
  exact odd_cross_halfShift_gap_halved_product_Z_descent_core
    a b h u Y ha hb hY hYu hAB hZmod

lemma odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent
    (h u p q : Nat)
    (hhodd : Odd h) (huodd : Odd u)
    (hpodd : Odd p) (hqodd : Odd q)
    (hhu : 3 <= h * u)
    (hhp : h < p) (huq : u < q)
    (hABcop : Nat.Coprime ((p * u + 1) / 2) ((h * q + 1) / 2))
    (hA : 2 * (p * u + 1) ∣ (h * q - 1) ^ 2)
    (hB : 2 * (h * q + 1) ∣ (p * u - 1) ^ 2)
    (hZ : 2 * (p * q + 1) ∣ (h * u - 1) ^ 2) :
    False := by
  rcases odd_cross_halfShift_gap_strict_refactor_parameters
      h u p q hhodd huodd hpodd hqodd hhp huq with
    ⟨a, b, ha, hb, hp, hq⟩
  subst p
  subst q
  let Y := (h * u + 1) / 2
  have hY : h * u + 1 = 2 * Y := by
    rcases hhodd with ⟨kh, hkh⟩
    rcases huodd with ⟨ku, hku⟩
    have hprod_even : h * u + 1 = 2 * (2 * kh * ku + kh + ku + 1) := by
      rw [hkh, hku]
      ring
    dsimp [Y]
    omega
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hAden_rev, hBden_rev, _hNden_rev, hZden_rev⟩
  have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := hAden_rev.symm
  have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := hBden_rev.symm
  have hZden :
      (h + 2 * a) * (u + 2 * b) + 1 =
        2 * (Y + a * u + h * b + 2 * a * b) := hZden_rev.symm
  have hAhalf : (((h + 2 * a) * u + 1) / 2) = Y + a * u := by
    omega
  have hBhalf : ((h * (u + 2 * b) + 1) / 2) = Y + h * b := by
    omega
  have hABcop_halves : Nat.Coprime (Y + a * u) (Y + h * b) := by
    simpa [hAhalf, hBhalf] using hABcop
  have hBnum : h * (u + 2 * b) - 1 = 2 * (Y + h * b - 1) := by
    have hBpos : 1 <= Y + h * b := by omega
    omega
  have hAnum : (h + 2 * a) * u - 1 = 2 * (Y + a * u - 1) := by
    have hApos : 1 <= Y + a * u := by omega
    omega
  have hYnum : h * u - 1 = 2 * (Y - 1) := by
    have hYpos : 1 <= Y := by omega
    omega
  have hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2 :=
    dvd_sq_of_dvd_double_sq
      (Y + a * u) (Y + h * b - 1)
      ((h + 2 * a) * u + 1) (h * (u + 2 * b) - 1)
      hAden hBnum hA
  have hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2 :=
    dvd_sq_of_dvd_double_sq
      (Y + h * b) (Y + a * u - 1)
      (h * (u + 2 * b) + 1) ((h + 2 * a) * u - 1)
      hBden hAnum hB
  have hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 :=
    dvd_sq_of_dvd_double_sq
      (Y + a * u + h * b + 2 * a * b) (Y - 1)
      ((h + 2 * a) * (u + 2 * b) + 1) (h * u - 1)
      hZden hYnum hZ
  exact odd_cross_halfShift_gap_halved_edges_valuation_obstruction_core
    a b h u Y ha hb hY hhu hAmod hBmod hABcop_halves hZmod

lemma odd_cross_halfShift_gap_exact_factor2_odd_parameter_primitive_obstruction
    (h u p q : Nat)
    (hhodd : Odd h) (huodd : Odd u)
    (hpodd : Odd p) (hqodd : Odd q)
    (hhu : 3 <= h * u)
    (hhp : h < p) (huq : u < q)
    (hABcop : Nat.Coprime ((p * u + 1) / 2) ((h * q + 1) / 2))
    (hA : 2 * (p * u + 1) ∣ (h * q - 1) ^ 2)
    (hB : 2 * (h * q + 1) ∣ (p * u - 1) ^ 2)
    (hZ : 2 * (p * q + 1) ∣ (h * u - 1) ^ 2) :
    False := by
  exact odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent
    h u p q hhodd huodd hpodd hqodd hhu hhp huq hABcop hA hB hZ

lemma odd_cross_halfShift_gap_exact_factor2_valuation_obstruction_core
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hExact :
      2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
        2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
        2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2) :
    False := by
  rcases hExact with ⟨hA, hB, hZ⟩
  rcases odd_cross_halfShift_gap_hu_odd_of_halfshift h u Y hY with
    ⟨hhodd, huodd⟩
  rcases odd_cross_halfShift_gap_core_odd_factor_parities a b h u hhodd huodd with
    ⟨hpodd, hqodd⟩
  have hhp : h < h + 2 * a := by omega
  have huq : u < u + 2 * b := by omega
  have hAhalf : (((h + 2 * a) * u + 1) / 2) = Y + a * u := by
    have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := by
      rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
        ⟨hAden_rev, _hBden_rev, _hNden_rev, _hZden_rev⟩
      exact hAden_rev.symm
    omega
  have hBhalf : ((h * (u + 2 * b) + 1) / 2) = Y + h * b := by
    have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := by
      rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
        ⟨_hAden_rev, hBden_rev, _hNden_rev, _hZden_rev⟩
      exact hBden_rev.symm
    omega
  have hABcop_halves :
      Nat.Coprime (((h + 2 * a) * u + 1) / 2)
        ((h * (u + 2 * b) + 1) / 2) := by
    simpa [hAhalf, hBhalf] using hABcop
  exact odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent
    h u (h + 2 * a) (u + 2 * b)
    hhodd huodd hpodd hqodd hYu hhp huq hABcop_halves
    hA hB hZ

lemma odd_cross_halfShift_gap_exact_factor2_pre_common_M_obstruction
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hExact :
      2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
        2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
        2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2) :
    False := by
  exact odd_cross_halfShift_gap_exact_factor2_valuation_obstruction_core
    a b h u Y ha hb hY hYu hABcop hExact

lemma odd_cross_halfShift_gap_exact_factor2_halved_edges
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (_hYu : 3 <= h * u)
    (hExact :
      2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
        2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
        2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2) :
    (Y + a * u) ∣ (Y + h * b - 1) ^ 2 ∧
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2 ∧
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 := by
  rcases hExact with ⟨hA2, hB2, hZ2⟩
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hAden2, hBden2, _hNden2, hZden2⟩
  have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := by
    omega
  have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := by
    omega
  have hZden :
      (h + 2 * a) * (u + 2 * b) + 1 =
        2 * (Y + a * u + h * b + 2 * a * b) := by
    omega
  have hBnum : h * (u + 2 * b) - 1 = 2 * (Y + h * b - 1) := by
    have hBpos : 1 <= Y + h * b := by omega
    omega
  have hAnum : (h + 2 * a) * u - 1 = 2 * (Y + a * u - 1) := by
    have hApos : 1 <= Y + a * u := by omega
    omega
  have hYnum : h * u - 1 = 2 * (Y - 1) := by
    have hYpos : 1 <= Y := by omega
    omega
  constructor
  · exact dvd_sq_of_dvd_double_sq
      (Y + a * u) (Y + h * b - 1)
      ((h + 2 * a) * u + 1) (h * (u + 2 * b) - 1)
      hAden hBnum hA2
  constructor
  · exact dvd_sq_of_dvd_double_sq
      (Y + h * b) (Y + a * u - 1)
      (h * (u + 2 * b) + 1) ((h + 2 * a) * u - 1)
      hBden hAnum hB2
  · exact dvd_sq_of_dvd_double_sq
      (Y + a * u + h * b + 2 * a * b) (Y - 1)
      ((h + 2 * a) * (u + 2 * b) + 1) (h * u - 1)
      hZden hYnum hZ2

lemma odd_cross_halfShift_gap_halved_edges_valuation_obstruction
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    False := by
  rcases odd_cross_halfShift_gap_hu_odd_of_halfshift h u Y hY with
    ⟨hhodd, huodd⟩
  rcases odd_cross_halfShift_gap_core_odd_factor_parities a b h u hhodd huodd with
    ⟨hpodd, hqodd⟩
  have hhp : h < h + 2 * a := by omega
  have huq : u < u + 2 * b := by omega
  have hExact :=
    odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities
      a b h u Y ha hb hY hYu hAmod hBmod hZmod
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hAden2, hBden2, _hNden2, _hZden2⟩
  have hAhalf : (((h + 2 * a) * u + 1) / 2) = Y + a * u := by
    have hAden : (h + 2 * a) * u + 1 = 2 * (Y + a * u) := by omega
    omega
  have hBhalf : ((h * (u + 2 * b) + 1) / 2) = Y + h * b := by
    have hBden : h * (u + 2 * b) + 1 = 2 * (Y + h * b) := by omega
    omega
  have hABcop_halves :
      Nat.Coprime (((h + 2 * a) * u + 1) / 2)
        ((h * (u + 2 * b) + 1) / 2) := by
    simpa [hAhalf, hBhalf] using hABcop
  exact odd_cross_halfShift_gap_exact_factor2_odd_parameter_valuation_descent
    h u (h + 2 * a) (u + 2 * b)
    hhodd huodd hpodd hqodd hYu hhp huq hABcop_halves
    hExact.1 hExact.2.1 hExact.2.2

lemma odd_cross_halfShift_gap_exact_factor2_odd_factor_divisibility_obstruction
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hExact :
      2 * (((h + 2 * a) * u + 1)) ∣ (h * (u + 2 * b) - 1) ^ 2 ∧
        2 * (h * (u + 2 * b) + 1) ∣ ((h + 2 * a) * u - 1) ^ 2 ∧
        2 * (((h + 2 * a) * (u + 2 * b) + 1)) ∣ (h * u - 1) ^ 2) :
    False := by
  exact odd_cross_halfShift_gap_exact_factor2_pre_common_M_obstruction
    a b h u Y ha hb hY hYu hABcop hExact

lemma odd_cross_halfShift_gap_exact_halved_odd_factor_obstruction_of_edges
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    False := by
  have hExact :=
    odd_cross_halfShift_gap_core_exact_halved_odd_factor_divisibilities
      a b h u Y ha hb hY hYu hAmod hBmod hZmod
  exact odd_cross_halfShift_gap_exact_factor2_odd_factor_divisibility_obstruction
    a b h u Y ha hb hY hYu hABcop hExact

lemma odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ
    (a b h u Y kZ : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod : (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod : (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod : (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (hkZ :
      (Y - 1) ^ 2 =
        (Y + a * u + h * b + 2 * a * b) * kZ)
    (hkZpos : 0 < kZ)
    (hkZltY : kZ < Y)
    (hYkZcop : Nat.Coprime Y kZ)
    (hkZ_expanded :
      (Y + a * u + h * b + 2 * a * b) * kZ + 2 * Y =
        Y ^ 2 + 1) :
    Y ∣ a * b * kZ := by
  exact False.elim
    (odd_cross_halfShift_gap_exact_halved_odd_factor_obstruction_of_edges
      a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod)

lemma odd_cross_halfShift_gap_halved_Y_dvd_AB_of_edges
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    Y ∣ (Y + a * u) * (Y + h * b) := by
  rcases odd_cross_halfShift_gap_Z_quotient_data
      a b h u Y ha hb hY hYu hZmod with
    ⟨kZ, hkZ, hkZpos, hkZltY, hYkZcop, hkZ_expanded⟩
  have hYabkZ :
      Y ∣ a * b * kZ :=
    odd_cross_halfShift_gap_Y_dvd_ab_mul_Z_quotient_of_exact_halved_ABZ
      a b h u Y kZ ha hb hY hYu hAmod hBmod hABcop hZmod
      hkZ hkZpos hkZltY hYkZcop hkZ_expanded
  have hYABkZ :
      Y ∣ (Y + a * u) * (Y + h * b) * kZ :=
    odd_cross_halfShift_gap_Y_dvd_AB_mul_Z_quotient_of_exact_halved_ABZ
      a b h u Y kZ ha hb hY hYu hAmod hBmod hABcop hZmod
      hkZ hkZ_expanded hYabkZ
  exact odd_cross_halfShift_gap_Y_dvd_AB_of_Y_dvd_AB_mul_Z_quotient
    a b h u Y kZ hYkZcop hYABkZ

lemma odd_cross_halfShift_gap_Y_dvd_AB_of_exact_halved_ABZ
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    Y ∣ (Y + a * u) * (Y + h * b) := by
  exact odd_cross_halfShift_gap_halved_Y_dvd_AB_of_edges
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod

lemma odd_cross_halfShift_gap_halved_common_M_left_of_Y_dvd_AB
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (_hY : h * u + 1 = 2 * Y)
    (_hYu : 3 <= h * u)
    (_hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (_hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (_hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (_hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (_hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b))
    (hcommon :
      (Y + a * u) * (Y + h * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2 ∧
        (Y + a * u + h * b + 2 * a * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2)
    (hYAB : Y ∣ (Y + a * u) * (Y + h * b)) :
    Y ∣
      (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 := by
  exact dvd_trans hYAB hcommon.1

lemma odd_cross_halfShift_gap_halved_Y_dvd_AB_of_common
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (_hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b))
    (_hcommon :
      (Y + a * u) * (Y + h * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2 ∧
        (Y + a * u + h * b + 2 * a * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2) :
    Y ∣ (Y + a * u) * (Y + h * b) := by
  exact odd_cross_halfShift_gap_halved_Y_dvd_AB_of_edges
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod

lemma odd_cross_halfShift_gap_halved_common_M_left
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b))
    (hcommon :
      (Y + a * u) * (Y + h * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2 ∧
        (Y + a * u + h * b + 2 * a * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2) :
    Y ∣
      (2 * (Y + a * u) * (Y + h * b) -
        ((Y + a * u) + (Y + h * b) - 1)) ^ 2 := by
  exact odd_cross_halfShift_gap_halved_common_M_left_of_Y_dvd_AB
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod hYZcop hcommon
    (odd_cross_halfShift_gap_halved_Y_dvd_AB_of_common
      a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod hYZcop hcommon)

lemma odd_cross_halfShift_gap_halved_fourth_edge_of_common_M_left
    (a b h u Y : Nat)
    (_ha : 1 <= a) (_hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (_hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (_hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (_hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (_hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (_hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b))
    (_hcommon :
      (Y + a * u) * (Y + h * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2 ∧
        (Y + a * u + h * b + 2 * a * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2)
    (hYcommon :
      Y ∣
        (2 * (Y + a * u) * (Y + h * b) -
          ((Y + a * u) + (Y + h * b) - 1)) ^ 2) :
    Y ∣ (Y + a * u + h * b + 2 * a * b - 1) ^ 2 := by
  have hYge : 2 <= Y := by omega
  have hA : 2 <= Y + a * u := by omega
  have hB : 2 <= Y + h * b := by omega
  have hZge : 2 <= Y + a * u + h * b + 2 * a * b := by omega
  have hM :
      2 * (Y + a * u) * (Y + h * b) -
          ((Y + a * u) + (Y + h * b) - 1) =
        2 * Y * (Y + a * u + h * b + 2 * a * b) -
          (Y + (Y + a * u + h * b + 2 * a * b) - 1) := by
    exact cross_halfShift_common_M_eq
      (Y + a * u) (Y + h * b)
      Y (Y + a * u + h * b + 2 * a * b)
      hA hB hYge hZge
      (odd_cross_halfShift_gap_same_odd_product a b h u Y hY)
  have hYcommonYZ :
      Y ∣
        (2 * Y * (Y + a * u + h * b + 2 * a * b) -
          (Y + (Y + a * u + h * b + 2 * a * b) - 1)) ^ 2 := by
    simpa [hM] using hYcommon
  exact halfShift_left_factor_dvd_pred_sq_of_common_M_sq
    Y (Y + a * u + h * b + 2 * a * b)
    (le_trans (by decide : 1 <= 2) hYge)
    (le_trans (by decide : 1 <= 2) hZge)
    hYcommonYZ

lemma odd_cross_halfShift_gap_old_unhalved_witness_halved_AB_not_Z :
    ((((217 * 31 + 1) / 2) * ((3 * 39 + 1) / 2)) ∣
        (((217 * 31 + 3 * 39) / 2) ^ 2)) ∧
      ¬ (((217 * 39 + 1) / 2) ∣ (((3 * 31 - 1) / 2) ^ 2)) := by
  constructor <;> norm_num

lemma odd_cross_halfShift_gap_halved_scalar_obstruction
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAmod :
      (Y + a * u) ∣ (Y + h * b - 1) ^ 2)
    (hBmod :
      (Y + h * b) ∣ (Y + a * u - 1) ^ 2)
    (hABcop : Nat.Coprime (Y + a * u) (Y + h * b))
    (hZmod :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2)
    (_hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b))
    (_hcommon :
      (Y + a * u) * (Y + h * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2 ∧
        (Y + a * u + h * b + 2 * a * b) ∣
          (2 * (Y + a * u) * (Y + h * b) -
            ((Y + a * u) + (Y + h * b) - 1)) ^ 2) :
    False := by
  exact odd_cross_halfShift_gap_exact_halved_odd_factor_obstruction_of_edges
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZmod

lemma odd_cross_halfShift_gap_halved_core_obstruction
    (a b h u Y : Nat)
    (ha : 1 <= a) (hb : 1 <= b)
    (hY : h * u + 1 = 2 * Y)
    (hYu : 3 <= h * u)
    (hAB :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2)
    (hZ :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2) :
    False := by
  have hYge : 2 <= Y := by omega
  have hA2 : 2 <= Y + a * u := by omega
  have hB2 : 2 <= Y + h * b := by omega
  have hABmod := odd_cross_halfShift_gap_first_modular
    a b h u Y ha hb hY hYu hAB
  rcases hABmod with ⟨hAmod, hBmod⟩
  have hABcop : Nat.Coprime (Y + a * u) (Y + h * b) := by
    have hsum :
        2 * Y + a * u + h * b - 1 =
          (Y + a * u) + (Y + h * b) - 1 := by
      omega
    exact halfShift_divisibility_coprime
      (Y + a * u) (Y + h * b) hA2 hB2
      (by simpa [hsum] using hAB)
  have hYZcop :
      Nat.Coprime Y (Y + a * u + h * b + 2 * a * b) :=
    odd_cross_halfShift_gap_core_YZ_coprime
      a b h u Y ha hb hY hYu hZ
  have hcommon := odd_cross_halfShift_gap_core_common_M_divisibilities
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZ
  exact odd_cross_halfShift_gap_halved_scalar_obstruction
    a b h u Y ha hb hY hYu hAmod hBmod hABcop hZ hYZcop hcommon

lemma odd_cross_halfShift_gap_ABZ_halved_factor_obstruction
    (h u H U : Nat)
    (hhodd : Odd h) (huodd : Odd u)
    (hHodd : Odd H) (hUodd : Odd U)
    (hhu : 3 ≤ h * u)
    (hH : h < H) (hU : u < U)
    (hAB :
      ((H * u + 1) / 2) * ((h * U + 1) / 2) ∣
        ((H * u + h * U) / 2) ^ 2)
    (hZ :
      ((H * U + 1) / 2) ∣ ((h * u - 1) / 2) ^ 2) :
    False := by
  rcases odd_cross_halfShift_gap_strict_refactor_parameters
      h u H U hhodd huodd hHodd hUodd hH hU with
    ⟨a, b, ha, hb, hH_eq, hU_eq⟩
  subst H
  subst U
  let Y := (h * u + 1) / 2
  have hY : h * u + 1 = 2 * Y := by
    rcases hhodd with ⟨kh, hkh⟩
    rcases huodd with ⟨ku, hku⟩
    have hprod_even : h * u + 1 = 2 * (2 * kh * ku + kh + ku + 1) := by
      rw [hkh, hku]
      ring
    dsimp [Y]
    omega
  rcases odd_cross_halfShift_gap_double_identities a b h u Y hY with
    ⟨hA2, hB2, hN2, hZ2⟩
  have hAdiv : (((h + 2 * a) * u + 1) / 2) = Y + a * u := by
    omega
  have hBdiv : ((h * (u + 2 * b) + 1) / 2) = Y + h * b := by
    omega
  have hNdiv :
      (((h + 2 * a) * u + h * (u + 2 * b)) / 2) =
        2 * Y + a * u + h * b - 1 := by
    omega
  have hZdiv :
      (((h + 2 * a) * (u + 2 * b) + 1) / 2) =
        Y + a * u + h * b + 2 * a * b := by
    omega
  have hYpred_div : ((h * u - 1) / 2) = Y - 1 := by
    omega
  have hABcore :
      (Y + a * u) * (Y + h * b) ∣
        (2 * Y + a * u + h * b - 1) ^ 2 := by
    simpa [hAdiv, hBdiv, hNdiv] using hAB
  have hZcore :
      (Y + a * u + h * b + 2 * a * b) ∣ (Y - 1) ^ 2 := by
    simpa [hZdiv, hYpred_div] using hZ
  exact odd_cross_halfShift_gap_halved_core_obstruction
    a b h u Y ha hb hY hhu hABcore hZcore

lemma odd_cross_halfShift_gap_ordered_odd_product_refactor
    (Y A B Z : Nat)
    (hY : 2 <= Y)
    (hYA : Y < A) (hYB : Y < B)
    (hAZ : A < Z) (_hBZ : B < Z)
    (hprod : (2 * A - 1) * (2 * B - 1) = (2 * Y - 1) * (2 * Z - 1)) :
    ∃ h u H U : Nat,
      Odd h ∧ Odd u ∧ Odd H ∧ Odd U ∧
        3 <= h * u ∧ h < H ∧ u < U ∧
        2 * Y - 1 = h * u ∧
        2 * A - 1 = H * u ∧
        2 * B - 1 = h * U ∧
        2 * Z - 1 = H * U := by
  let x := 2 * Y - 1
  let p := 2 * A - 1
  let q := 2 * B - 1
  let z := 2 * Z - 1
  have hxpos : 0 < x := by dsimp [x]; omega
  have hppos : 0 < p := by dsimp [p]; omega
  have hqpos : 0 < q := by dsimp [q]; omega
  have hzpos : 0 < z := by dsimp [z]; omega
  have hxp : x < p := by dsimp [x, p]; omega
  have hxq : x < q := by dsimp [x, q]; omega
  have hpz : p < z := by dsimp [p, z]; omega
  let u := Nat.gcd x p
  let h := x / u
  let H := p / u
  have hupos : 0 < u := by
    dsimp [u]
    exact Nat.gcd_pos_of_pos_left p hxpos
  have hxu : x = h * u := by
    dsimp [h]
    exact (Nat.div_mul_cancel (Nat.gcd_dvd_left x p)).symm
  have hpu : p = H * u := by
    dsimp [H]
    exact (Nat.div_mul_cancel (Nat.gcd_dvd_right x p)).symm
  have hhpos : 0 < h := by
    dsimp [h]
    exact Nat.div_pos (Nat.le_of_dvd hxpos (by
      dsimp [u]
      exact Nat.gcd_dvd_left x p)) hupos
  have hHpos : 0 < H := by
    dsimp [H]
    exact Nat.div_pos (Nat.le_of_dvd hppos (by
      dsimp [u]
      exact Nat.gcd_dvd_right x p)) hupos
  have hhHcop : Nat.Coprime h H := by
    dsimp [h, H, u]
    exact Nat.coprime_div_gcd_div_gcd hupos
  have hprod_xpqz : p * q = x * z := by
    dsimp [x, p, q, z]
    exact hprod
  have hcancel_u : H * q = h * z := by
    have hmul : (H * u) * q = (h * u) * z := by
      simpa [hpu, hxu] using hprod_xpqz
    have hmul' : u * (H * q) = u * (h * z) := by
      calc
        u * (H * q) = (H * u) * q := by ring
        _ = (h * u) * z := hmul
        _ = u * (h * z) := by ring
    exact Nat.mul_left_cancel hupos hmul'
  have hH_dvd_z : H ∣ z := by
    exact (Nat.Coprime.dvd_of_dvd_mul_left hhHcop.symm
      ⟨q, hcancel_u.symm⟩)
  let U := z / H
  have hzHU : z = H * U := by
    dsimp [U]
    calc
      z = z / H * H := (Nat.div_mul_cancel hH_dvd_z).symm
      _ = H * (z / H) := by ring
  have hqHU : q = h * U := by
    have hmain : H * q = H * (h * U) := by
      calc
        H * q = h * z := hcancel_u
        _ = h * (H * U) := by rw [hzHU]
        _ = H * (h * U) := by ring
    exact Nat.mul_left_cancel hHpos hmain
  have hh_lt_H : h < H := by
    have hmul_lt : h * u < H * u := by
      simpa [hxu, hpu] using hxp
    exact (Nat.mul_lt_mul_right hupos).mp hmul_lt
  have hu_lt_U : u < U := by
    have hmul_lt : h * u < h * U := by
      simpa [hxu, hqHU] using hxq
    exact (Nat.mul_lt_mul_left hhpos).mp hmul_lt
  have hxodd : Odd x := by
    dsimp [x]
    refine ⟨Y - 1, ?_⟩
    omega
  have hpodd : Odd p := by
    dsimp [p]
    refine ⟨A - 1, ?_⟩
    omega
  have hqodd : Odd q := by
    dsimp [q]
    refine ⟨B - 1, ?_⟩
    omega
  have hzodd : Odd z := by
    dsimp [z]
    refine ⟨Z - 1, ?_⟩
    omega
  have hhodd : Odd h := by
    rw [hxu] at hxodd
    exact Nat.Odd.of_mul_left hxodd
  have huodd : Odd u := by
    rw [hxu] at hxodd
    exact Nat.Odd.of_mul_right hxodd
  have hHodd : Odd H := by
    rw [hpu] at hpodd
    exact Nat.Odd.of_mul_left hpodd
  have hUodd : Odd U := by
    rw [hqHU] at hqodd
    exact Nat.Odd.of_mul_right hqodd
  refine ⟨h, u, H, U, hhodd, huodd, hHodd, hUodd, ?_, hh_lt_H, hu_lt_U,
    ?_, ?_, ?_, ?_⟩
  · dsimp [x] at hxu
    omega
  · exact hxu
  · exact hpu
  · exact hqHU
  · exact hzHU

lemma odd_cross_halfShift_gap_ABZ_product_Z_coprime_obstruction
    (Y A B Z : Nat)
    (hY : 2 <= Y)
    (hYA : Y < A) (hYB : Y < B)
    (hAZ : A < Z) (hBZ : B < Z)
    (hprod : (2 * A - 1) * (2 * B - 1) = (2 * Y - 1) * (2 * Z - 1))
    (hAB : A * B ∣ (A + B - 1) ^ 2)
    (hZ : Z ∣ (Y - 1) ^ 2)
    (hABcop : Nat.Coprime A B) :
    False := by
  rcases odd_cross_halfShift_gap_ordered_odd_product_refactor
      Y A B Z hY hYA hYB hAZ hBZ hprod with
    ⟨h, u, H, U, hhodd, huodd, hHodd, hUodd, hhu, hhH, huU,
      hYodd, hAodd, hBodd, hZodd⟩
  have hAhalf : ((H * u + 1) / 2) = A := by omega
  have hBhalf : ((h * U + 1) / 2) = B := by omega
  have hZhalf : ((H * U + 1) / 2) = Z := by omega
  have hYpred_half : ((h * u - 1) / 2) = Y - 1 := by omega
  have hABnum :
      ((H * u + h * U) / 2) = A + B - 1 := by omega
  have hABcore :
      ((H * u + 1) / 2) * ((h * U + 1) / 2) ∣
        ((H * u + h * U) / 2) ^ 2 := by
    simpa [hAhalf, hBhalf, hABnum] using hAB
  have hZcore :
      ((H * U + 1) / 2) ∣ ((h * u - 1) / 2) ^ 2 := by
    simpa [hZhalf, hYpred_half] using hZ
  exact odd_cross_halfShift_gap_ABZ_halved_factor_obstruction
    h u H U hhodd huodd hHodd hUodd hhu hhH huU hABcore hZcore

lemma halfShift_cross_AB_Z_obstruction
    (Y A B Z : Nat)
    (hY : 2 <= Y)
    (hYA : Y < A) (hYB : Y < B)
    (hAZ : A < Z) (hBZ : B < Z)
    (hprod :
      (2 * A - 1) * (2 * B - 1) =
        (2 * Y - 1) * (2 * Z - 1))
    (hAB : A * B ∣ (A + B - 1) ^ 2)
    (hZ : Z ∣ (Y - 1) ^ 2)
    (hABcop : Nat.Coprime A B) :
    False := by
  exact odd_cross_halfShift_gap_ABZ_product_Z_coprime_obstruction
    Y A B Z hY hYA hYB hAZ hBZ hprod hAB hZ hABcop

end CrystalsOddVietaDescent20260610
