import Mathlib

#check Finsupp.degree_eq_sum
#check Finsupp.sum_fintype
#check MvPolynomial.monomial_add
#check MvPolynomial.monomial_single
#check MvPolynomial.C_mul_X_pow_eq_monomial
#check MvPolynomial.monomial_eq
#check MvPolynomial.totalDegree_eq_zero_iff_eq_C
#check MvPolynomial.irreducible_X_sub_C

open scoped BigOperators

private lemma finsupp_fin_two_degree_two_cases (m : Fin 2 →₀ ℕ)
    (hm : m.degree = 2) :
    m = Finsupp.single 0 2 ∨
      m = Finsupp.single 0 1 + Finsupp.single 1 1 ∨
      m = Finsupp.single 1 2 := by
  have hs : m 0 + m 1 = 2 := by
    simpa [Finsupp.degree, Fin.sum_univ_two] using hm
  rcases Nat.eq_zero_or_pos (m 0) with h0 | h0
  · right; right
    ext i
    fin_cases i
    · simp [h0]
    · simp [h0] at hs ⊢
      exact hs
  · rcases Nat.eq_one_or_lt_one h0 with h01 | h01
    · right; left
      ext i
      fin_cases i
      · simp [h01]
      · simp [h01] at hs ⊢
        omega
    · left
      ext i
      fin_cases i
      · simp
        omega
      · simp
        omega

private lemma homogeneous_quadratic_eq_three_terms
    (f : MvPolynomial (Fin 2) ℝ) (hf : f.IsHomogeneous 2) :
    f =
      MvPolynomial.C (MvPolynomial.coeff (Finsupp.single 0 2) f) *
          MvPolynomial.X 0 ^ 2 +
      MvPolynomial.C (MvPolynomial.coeff
          (Finsupp.single 0 1 + Finsupp.single 1 1) f) *
          MvPolynomial.X 0 * MvPolynomial.X 1 +
      MvPolynomial.C (MvPolynomial.coeff (Finsupp.single 1 2) f) *
          MvPolynomial.X 1 ^ 2 := by
  ext m
  by_cases hm : m.degree = 2
  · rcases finsupp_fin_two_degree_two_cases m hm with rfl | rfl | rfl <;>
      simp [MvPolynomial.coeff_C_mul, MvPolynomial.coeff_X_pow]
  · rw [hf.coeff_eq_zero hm]
    simp only [map_add, MvPolynomial.coeff_add, MvPolynomial.coeff_mul,
      MvPolynomial.coeff_C]
    simp [MvPolynomial.coeff_X_pow, hm]

private lemma not_isUnit_of_isHomogeneous_one_ne_zero
    {f : MvPolynomial (Fin 2) ℝ} (hh : f.IsHomogeneous 1) (hf : f ≠ 0) :
    ¬ IsUnit f := by
  intro hu
  have hd0 := (MvPolynomial.isUnit_iff_totalDegree_of_isReduced.mp hu).2
  have hd1 : f.totalDegree = 1 := hh.totalDegree hf
  omega

theorem test_target
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hEval : MvPolynomial.eval ![x, y] f = 0) :
    MvPolynomial.homogeneousComponent 1 f ≠ 0 := by
  classical
  intro hlinear
  have hdecomp := MvPolynomial.sum_homogeneousComponent f
  rw [hdeg] at hdecomp
  simp only [Finset.sum_range_succ, Finset.sum_range_zero, zero_add] at hdecomp
  have hf_eq : f = MvPolynomial.homogeneousComponent 2 f := by
    calc
      f = MvPolynomial.homogeneousComponent 0 f +
          MvPolynomial.homogeneousComponent 1 f +
          MvPolynomial.homogeneousComponent 2 f := hdecomp.symm
      _ = MvPolynomial.homogeneousComponent 2 f := by rw [hzero, hlinear]; simp
  let a := MvPolynomial.coeff (Finsupp.single 0 2) f
  let b := MvPolynomial.coeff
    (Finsupp.single 0 1 + Finsupp.single 1 1) f
  let c := MvPolynomial.coeff (Finsupp.single 1 2) f
  have hform : f =
      MvPolynomial.C a * MvPolynomial.X 0 ^ 2 +
      MvPolynomial.C b * MvPolynomial.X 0 * MvPolynomial.X 1 +
      MvPolynomial.C c * MvPolynomial.X 1 ^ 2 := by
    rw [hf_eq]
    simpa [a, b, c, hf_eq] using
      homogeneous_quadratic_eq_three_terms
        (MvPolynomial.homogeneousComponent 2 f)
        (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)
  simp [hform] at hEval
  rcases hxy with hx | hy
  · let g : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 1 - MvPolynomial.C (y / x) * MvPolynomial.X 0
    let k : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.C c * MvPolynomial.X 1 +
        MvPolynomial.C (b + c * (y / x)) * MvPolynomial.X 0
    have hfac : f = g * k := by
      rw [hform]
      dsimp [g, k]
      apply MvPolynomial.funext
      intro p
      simp only [map_add, map_mul, map_sub, MvPolynomial.eval_C,
        MvPolynomial.eval_X, map_pow]
      field_simp [hx] at hEval ⊢
      nlinarith
    have hg0 : g ≠ 0 := by
      intro hg
      have he := congrArg (MvPolynomial.eval ![0, 1]) hg
      simp [g] at he
    have hk0 : k ≠ 0 := by
      intro hk
      apply hf.ne_zero
      rw [hfac, hk, mul_zero]
    have hgh : g.IsHomogeneous 1 := by
      dsimp [g]
      exact (MvPolynomial.isHomogeneous_X 1).sub
        ((MvPolynomial.isHomogeneous_C _).mul (MvPolynomial.isHomogeneous_X 0))
    have hkh : k.IsHomogeneous 1 := by
      dsimp [k]
      exact ((MvPolynomial.isHomogeneous_C _).mul (MvPolynomial.isHomogeneous_X 1)).add
        ((MvPolynomial.isHomogeneous_C _).mul (MvPolynomial.isHomogeneous_X 0))
    rcases (irreducible_iff.mp hf).2 hfac with hgu | hku
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hgh hg0 hgu
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hkh hk0 hku
  · let g : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 0 - MvPolynomial.C (x / y) * MvPolynomial.X 1
    let k : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.C a * MvPolynomial.X 0 +
        MvPolynomial.C (b + a * (x / y)) * MvPolynomial.X 1
    have hfac : f = g * k := by
      rw [hform]
      dsimp [g, k]
      apply MvPolynomial.funext
      intro p
      simp only [map_add, map_mul, map_sub, MvPolynomial.eval_C,
        MvPolynomial.eval_X, map_pow]
      field_simp [hy] at hEval ⊢
      nlinarith
    have hg0 : g ≠ 0 := by
      intro hg
      have he := congrArg (MvPolynomial.eval ![1, 0]) hg
      simp [g] at he
    have hk0 : k ≠ 0 := by
      intro hk
      apply hf.ne_zero
      rw [hfac, hk, mul_zero]
    have hgh : g.IsHomogeneous 1 := by
      dsimp [g]
      exact (MvPolynomial.isHomogeneous_X 0).sub
        ((MvPolynomial.isHomogeneous_C _).mul (MvPolynomial.isHomogeneous_X 1))
    have hkh : k.IsHomogeneous 1 := by
      dsimp [k]
      exact ((MvPolynomial.isHomogeneous_C _).mul (MvPolynomial.isHomogeneous_X 0)).add
        ((MvPolynomial.isHomogeneous_C _).mul (MvPolynomial.isHomogeneous_X 1))
    rcases (irreducible_iff.mp hf).2 hfac with hgu | hku
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hgh hg0 hgu
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hkh hk0 hku
