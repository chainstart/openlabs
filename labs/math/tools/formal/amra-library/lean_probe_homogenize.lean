import Mathlib.RingTheory.MvPolynomial.Homogeneous
import Mathlib.Algebra.Polynomial.Degree.TrailingDegree
import Mathlib.Algebra.MvPolynomial.Nilpotent

open scoped BigOperators

noncomputable section

open Polynomial

def scaleDegree {K σ : Type*} [Field K] :
    MvPolynomial σ K →+* Polynomial (MvPolynomial σ K) :=
  MvPolynomial.eval₂Hom
    ((Polynomial.C : MvPolynomial σ K →+* Polynomial (MvPolynomial σ K)).comp
      MvPolynomial.C)
    (fun i ↦ Polynomial.C (MvPolynomial.X i) * Polynomial.X)

#check Polynomial.natDegree_mul
#check Polynomial.natTrailingDegree_mul
#check Polynomial.C_mul_X_pow_eq_monomial
#check Polynomial.coeff
#check Polynomial.coeff_sum
#check Finset.prod_pow_eq_pow_sum
#check MvPolynomial.IsHomogeneous
#check MvPolynomial.homogeneousComponent

lemma scaleDegree_coeff {K σ : Type*} [Field K]
    (p : MvPolynomial σ K) (n : ℕ) :
    (scaleDegree p).coeff n = MvPolynomial.homogeneousComponent n p := by
  classical
  conv_lhs => rw [← p.support_sum_monomial_coeff]
  conv_rhs => rw [← p.support_sum_monomial_coeff]
  simp only [map_sum]
  have coeff_finset_sum (s : Finset (σ →₀ ℕ))
      (g : (σ →₀ ℕ) → Polynomial (MvPolynomial σ K)) :
      (∑ i ∈ s, g i).coeff n = ∑ i ∈ s, (g i).coeff n := by
    induction s using Finset.induction_on with
    | empty => simp
    | @insert a s ha ih => simp [ha, ih, Polynomial.coeff_add]
  rw [coeff_finset_sum]
  apply Finset.sum_congr rfl
  intro m hm
  rw [MvPolynomial.homogeneousComponent_apply]
  simp only [MvPolynomial.support_monomial, Finset.filter_singleton]
  unfold scaleDegree
  simp only [MvPolynomial.eval₂Hom_monomial, RingHom.coe_comp,
    Function.comp_apply, map_prod, map_pow]
  have hc : MvPolynomial.coeff m p ≠ 0 :=
    MvPolynomial.mem_support_iff.mp hm
  have hprod :
      (∏ x ∈ m.support,
        (Polynomial.C (MvPolynomial.X x : MvPolynomial σ K) *
          (Polynomial.X : Polynomial (MvPolynomial σ K))) ^ m x) =
        Polynomial.C (∏ x ∈ m.support,
          (MvPolynomial.X x : MvPolynomial σ K) ^ m x) *
          (Polynomial.X : Polynomial (MvPolynomial σ K)) ^ m.degree := by
    change _ = _ * Polynomial.X ^ (∑ x ∈ m.support, m x)
    simp_rw [mul_pow]
    rw [Finset.prod_mul_distrib, map_prod, Finset.prod_pow_eq_pow_sum]
    simp
  simp only [Finsupp.prod] at ⊢
  rw [hprod, ← mul_assoc, ← map_mul]
  rw [Polynomial.C_mul_X_pow_eq_monomial, Polynomial.coeff_monomial]
  rw [Finset.sum_filter]
  by_cases hmn : m.degree = n <;>
    simp [hc, hmn, MvPolynomial.C_mul_monomial]

lemma scaleDegree_ne_zero {K σ : Type*} [Field K]
    {p : MvPolynomial σ K} (hp : p ≠ 0) : scaleDegree p ≠ 0 := by
  intro hs
  apply hp
  rw [← MvPolynomial.sum_homogeneousComponent p]
  apply Finset.sum_eq_zero
  intro n hn
  rw [← scaleDegree_coeff p n, hs]
  simp

lemma scaleDegree_of_isHomogeneous {K σ : Type*} [Field K]
    {p : MvPolynomial σ K} {n : ℕ} (hp : p.IsHomogeneous n) :
    scaleDegree p = Polynomial.C p * Polynomial.X ^ n := by
  apply Polynomial.ext
  intro k
  rw [scaleDegree_coeff]
  rw [MvPolynomial.homogeneousComponent_of_mem hp]
  rw [Polynomial.C_mul_X_pow_eq_monomial, Polynomial.coeff_monomial]
  by_cases h : k = n
  · subst k
    simp
  · have h' : n ≠ k := fun hnk ↦ h hnk.symm
    simp [h, h']

lemma isHomogeneous_of_scaleDegree_single_degree {K σ : Type*} [Field K]
    {p : MvPolynomial σ K} (hp : p ≠ 0)
    (hdegree : (scaleDegree p).natDegree = (scaleDegree p).natTrailingDegree) :
    p.IsHomogeneous (scaleDegree p).natDegree := by
  intro m hm
  have hcoeff : (scaleDegree p).coeff m.degree ≠ 0 := by
    rw [scaleDegree_coeff]
    intro hzero
    have := congrArg (MvPolynomial.coeff m) hzero
    rw [MvPolynomial.coeff_homogeneousComponent] at this
    simp only [if_pos rfl] at this
    exact hm this
  have hle : m.degree ≤ (scaleDegree p).natDegree :=
    Polynomial.le_natDegree_of_ne_zero hcoeff
  have htrail : (scaleDegree p).natTrailingDegree ≤ m.degree := by
    by_contra h
    have hz := Polynomial.coeff_eq_zero_of_lt_natTrailingDegree
      (Nat.lt_of_not_ge h)
    exact hcoeff hz
  have hdn : m.degree = (scaleDegree p).natDegree := by omega
  simpa only [Finsupp.degree_eq_weight_one] using hdn

lemma homogeneous_factors {K σ : Type*} [Field K]
    {p a b : MvPolynomial σ K} {n : ℕ}
    (hp : p.IsHomogeneous n) (ha : a ≠ 0) (hb : b ≠ 0) (hab : p = a * b) :
    a.IsHomogeneous (scaleDegree a).natDegree ∧
      b.IsHomogeneous (scaleDegree b).natDegree := by
  have hp0 : p ≠ 0 := by rw [hab]; exact mul_ne_zero ha hb
  have hA0 := scaleDegree_ne_zero ha
  have hB0 := scaleDegree_ne_zero hb
  have hscale : scaleDegree a * scaleDegree b =
      Polynomial.C p * Polynomial.X ^ n := by
    rw [← map_mul, ← hab, scaleDegree_of_isHomogeneous hp]
  have hdeg : (scaleDegree a).natDegree + (scaleDegree b).natDegree = n := by
    rw [← Polynomial.natDegree_mul hA0 hB0, hscale,
      Polynomial.natDegree_C_mul_X_pow _ _ hp0]
  have htrail : (scaleDegree a).natTrailingDegree +
      (scaleDegree b).natTrailingDegree = n := by
    rw [← Polynomial.natTrailingDegree_mul hA0 hB0, hscale,
      Polynomial.natTrailingDegree_mul_X_pow (Polynomial.C_ne_zero.mpr hp0),
      Polynomial.natTrailingDegree_C, zero_add]
  have hAle := Polynomial.natTrailingDegree_le_natDegree (scaleDegree a)
  have hBle := Polynomial.natTrailingDegree_le_natDegree (scaleDegree b)
  constructor
  · apply isHomogeneous_of_scaleDegree_single_degree ha
    omega
  · apply isHomogeneous_of_scaleDegree_single_degree hb
    omega

#check irreducible_iff
#check Polynomial.natDegree_C_mul_X_pow
#check Finsupp.sum_add_index'
#check Finsupp.sum_single_index
#check Finsupp.sum_eq_single
#print MvPolynomial.monomial

noncomputable def dehom {K : Type*} [Field K] :
    MvPolynomial (Fin 3) K →+* MvPolynomial (Fin 2) K :=
  MvPolynomial.eval₂Hom MvPolynomial.C
    ![MvPolynomial.X 0, MvPolynomial.X 1, 1]

noncomputable def homAt {K : Type*} [Field K] (n : ℕ)
    (f : MvPolynomial (Fin 2) K) : MvPolynomial (Fin 3) K :=
  f.sum fun m c => MvPolynomial.monomial
    (Finsupp.equivFunOnFinite.symm ![m 0, m 1, n - m.degree]) c

lemma homAt_add {K : Type*} [Field K] (n : ℕ)
    (f g : MvPolynomial (Fin 2) K) :
    homAt n (f + g) = homAt n f + homAt n g := by
  classical
  unfold homAt
  apply Finsupp.sum_add_index'
  · intro i
    simp
  · intro i a b
    simp

lemma homAt_finsetSum {K ι : Type*} [Field K] (n : ℕ)
    (s : Finset ι) (f : ι → MvPolynomial (Fin 2) K) :
    homAt n (∑ i ∈ s, f i) = ∑ i ∈ s, homAt n (f i) := by
  classical
  induction s using Finset.induction_on with
  | empty => simp [homAt]
  | @insert a s ha ih => simp [ha, ih, homAt_add]

lemma homAt_dehom_of_homogeneous {K : Type*} [Field K]
    {q : MvPolynomial (Fin 3) K} {n : ℕ} (hq : q.IsHomogeneous n) :
    homAt n (dehom q) = q := by
  classical
  rw [← q.support_sum_monomial_coeff]
  unfold dehom
  rw [map_sum, homAt_finsetSum]
  -- both operations are additive, so it suffices to check one homogeneous monomial
  apply Finset.sum_congr rfl
  intro m hm
  have hdeg : m.degree = n := by
    rw [Finsupp.degree_eq_weight_one]
    exact hq (MvPolynomial.mem_support_iff.mp hm)
  let d : Fin 2 →₀ ℕ := Finsupp.equivFunOnFinite.symm ![m 0, m 1]
  have hd (i : Fin 2) : d i = ![m 0, m 1] i := by
    exact congrFun (Finsupp.equivFunOnFinite.apply_symm_apply
      (![m 0, m 1] : Fin 2 → ℕ)) i
  have hdehom :
      MvPolynomial.eval₂Hom MvPolynomial.C
        ![(MvPolynomial.X 0 : MvPolynomial (Fin 2) K),
          (MvPolynomial.X 1 : MvPolynomial (Fin 2) K),
          (1 : MvPolynomial (Fin 2) K)]
        (MvPolynomial.monomial m (MvPolynomial.coeff m q)) =
      MvPolynomial.monomial d (MvPolynomial.coeff m q) := by
    rw [MvPolynomial.eval₂Hom_monomial]
    simp [Finsupp.prod_fintype, Fin.prod_univ_three,
      MvPolynomial.monomial_eq, hd]
  rw [hdehom]
  have hc : MvPolynomial.coeff m q ≠ 0 :=
    MvPolynomial.mem_support_iff.mp hm
  unfold homAt
  change (Finsupp.single d (MvPolynomial.coeff m q)).sum _ = _
  rw [Finsupp.sum_single_index (by simp)]
  have hexp : Finsupp.equivFunOnFinite.symm
      ![d 0, d 1, n - d.degree] = m := by
    apply Finsupp.ext
    intro i
    fin_cases i
    · simp [hd]
    · simp [hd]
    · simp [hd]
      rw [show m.degree = m 0 + m 1 + m 2 by
        rw [Finsupp.degree_eq_sum, Fin.sum_univ_three]] at hdeg
      rw [show d.degree = m 0 + m 1 by
        rw [Finsupp.degree_eq_sum, Fin.sum_univ_two, hd, hd]
        simp]
      omega
  rw [hexp]

lemma homAt_C {K : Type*} [Field K] (n : ℕ) (c : K) :
    homAt n (MvPolynomial.C c) =
      MvPolynomial.C c * MvPolynomial.X 2 ^ n := by
  classical
  unfold homAt
  change (Finsupp.single 0 c).sum _ = _
  rw [Finsupp.sum_single_index (by simp)]
  rw [MvPolynomial.C_mul_X_pow_eq_monomial]
  have hexp : Finsupp.equivFunOnFinite.symm
      ![(0 : ℕ), 0, n - (0 : Fin 2 →₀ ℕ).degree] =
      Finsupp.single 2 n := by
    apply Finsupp.ext
    intro i
    fin_cases i <;> simp
  simpa using congrArg (fun e ↦ MvPolynomial.monomial e c) hexp

lemma isUnit_or_X_dvd_of_homogeneous_dehom_isUnit
    {K : Type*} [Field K] {q : MvPolynomial (Fin 3) K} {n : ℕ}
    (hq : q.IsHomogeneous n) (hu : IsUnit (dehom q)) :
    IsUnit q ∨ MvPolynomial.X 2 ∣ q := by
  rw [MvPolynomial.isUnit_iff_eq_C_of_isReduced] at hu
  obtain ⟨c, hc, heq⟩ := hu
  have hqeq : q = MvPolynomial.C c * MvPolynomial.X 2 ^ n := by
    rw [← homAt_dehom_of_homogeneous hq, heq, homAt_C]
  rcases n with _ | n
  · left
    rw [hqeq]
    simpa using hc.map
      (MvPolynomial.C : K →+* MvPolynomial (Fin 3) K)
  · right
    rw [hqeq, pow_succ]
    refine ⟨MvPolynomial.C c * MvPolynomial.X 2 ^ n, ?_⟩
    ring

lemma coeff_homAt_top {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) (m : Fin 2 →₀ ℕ)
    (hm : m ∈ f.support) (hdeg : m.degree = f.totalDegree) :
    MvPolynomial.coeff
      (Finsupp.equivFunOnFinite.symm ![m 0, m 1, 0])
      (homAt f.totalDegree f) = MvPolynomial.coeff m f := by
  classical
  unfold homAt
  rw [Finsupp.sum]
  let v : Fin 3 →₀ ℕ :=
    Finsupp.equivFunOnFinite.symm ![m 0, m 1, 0]
  let ch : MvPolynomial (Fin 3) K →+ K :=
    { toFun := fun q ↦ MvPolynomial.coeff v q
      map_zero' := MvPolynomial.coeff_zero v
      map_add' := by intro a b; simp }
  change ch (∑ a ∈ f.support, MvPolynomial.monomial
      (Finsupp.equivFunOnFinite.symm
        ![a 0, a 1, f.totalDegree - a.degree]) (MvPolynomial.coeff a f)) = _
  rw [map_sum]
  calc
    _ = ch (MvPolynomial.monomial
        (Finsupp.equivFunOnFinite.symm
          ![m 0, m 1, f.totalDegree - m.degree])
        (MvPolynomial.coeff m f)) := by
      apply Finset.sum_eq_single m
      · intro a ha ham
        change MvPolynomial.coeff v (MvPolynomial.monomial _ _) = 0
        rw [MvPolynomial.coeff_monomial]
        split_ifs with heq
        · exfalso
          apply ham
          apply Finsupp.ext
          intro i
          fin_cases i
          · have := congrFun (congrArg Finsupp.equivFunOnFinite heq) 0
            simpa using this
          · have := congrFun (congrArg Finsupp.equivFunOnFinite heq) 1
            simpa using this
        · rfl
      · intro hmnot
        exact (hmnot hm).elim
    _ = MvPolynomial.coeff m f := by
      change MvPolynomial.coeff v (MvPolynomial.monomial _ _) = _
      rw [MvPolynomial.coeff_monomial]
      rw [if_pos]
      apply Finsupp.ext
      intro i
      fin_cases i <;> simp [v, hdeg]
