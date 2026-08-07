import Mathlib.Algebra.MvPolynomial.Equiv
import Mathlib.RingTheory.Polynomial.Resultant.Basic
import Mathlib.RingTheory.Polynomial.GaussLemma
import Mathlib.RingTheory.PrincipalIdealDomain
import Mathlib.Algebra.Polynomial.Bivariate

open scoped Polynomial

#check MvPolynomial.finSuccEquiv
#check MvPolynomial.pUnitAlgEquiv
#check Polynomial.mapAlgEquiv
#check Polynomial.resultant_eq_zero_iff
#check Polynomial.resultant_ne_zero
#check Polynomial.exists_mul_add_mul_eq_C_resultant
#check IsRelPrime
#check IsCoprime.map
#check Polynomial.roots
#check Polynomial.finite_setOf_isRoot
#check Polynomial.IsPrimitive.dvd_of_fraction_map_dvd_fraction_map
#check Polynomial.IsPrimitive.dvd_iff_fraction_map_dvd_fraction_map
#check Polynomial.evalEval
#check MvPolynomial.ringHom_ext
#check Set.Finite.pi
#check Set.pi
#check Set.Finite.prod
#check Set.Finite.preimage
#check Polynomial.evalEval_add
#check MvPolynomial.ringHom_ext
#check Polynomial.evalEval_mul
#check MvPolynomial.ringHom_ext
#check Polynomial.eval_C
#check Polynomial.exists_mul_add_mul_eq_C_resultant

theorem isCoprime_fraction_map_of_irreducible_not_dvd
    {R F : Type*} [CommRing R] [IsDomain R]
    [NormalizedGCDMonoid R] [Field F] [Algebra R F]
    [IsFractionRing R F]
    (f g : Polynomial R) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    IsCoprime (f.map (algebraMap R F)) (g.map (algebraMap R F)) := by
  by_cases hdeg : f.natDegree = 0
  · have hcoeff : f.coeff 0 ≠ 0 := by
      intro hc
      apply hf.ne_zero
      rw [Polynomial.eq_C_of_natDegree_eq_zero hdeg]
      simp [hc]
    rw [Polynomial.eq_C_of_natDegree_eq_zero hdeg]
    rw [Polynomial.map_C]
    apply IsRelPrime.isCoprime
    apply IsUnit.isRelPrime_left
    apply Polynomial.isUnit_C.mpr
    exact (show algebraMap R F (f.coeff 0) ≠ 0 by
      simpa using (IsFractionRing.injective R F).ne hcoeff) |>.isUnit
  · have hfprim : f.IsPrimitive := hf.isPrimitive hdeg
    have hfmap : Irreducible (f.map (algebraMap R F)) :=
      hfprim.irreducible_iff_irreducible_map_fraction_map.mp hf
    rw [hfmap.coprime_iff_not_dvd]
    intro hdvd
    have hg0 : g ≠ 0 := by
      intro hg
      apply hndvd
      simp [hg]
    have hgcontent : g.content ≠ 0 := by
      intro hc
      apply hg0
      exact Polynomial.content_eq_zero_iff.mp hc
    have hcontent : IsUnit (algebraMap R F g.content) :=
      (show algebraMap R F g.content ≠ 0 by
        simpa using (IsFractionRing.injective R F).ne hgcontent) |>.isUnit
    have hdvdprim : f.map (algebraMap R F) ∣ g.primPart.map (algebraMap R F) := by
      rw [g.eq_C_content_mul_primPart, Polynomial.map_mul, Polynomial.map_C] at hdvd
      rwa [IsUnit.dvd_mul_left (Polynomial.isUnit_C.mpr hcontent)] at hdvd
    apply hndvd
    exact (hfprim.dvd_primPart_iff_dvd hg0).mp
      (hfprim.dvd_of_fraction_map_dvd_fraction_map g.isPrimitive_primPart hdvdprim)

noncomputable def bivarEquiv (K : Type*) [Field K] :
    MvPolynomial (Fin 2) K ≃ₐ[K] Polynomial (Polynomial K) :=
  (MvPolynomial.finSuccEquiv K 1).trans
    (Polynomial.mapAlgEquiv
      ((MvPolynomial.renameEquiv K (Equiv.equivPUnit.{1, 1} (Fin 1))).trans
        (MvPolynomial.pUnitAlgEquiv.{_, 0} K)))

theorem resultant_ne_zero_of_irreducible_not_dvd
    {K : Type*} [Field K]
    (f g : Polynomial (Polynomial K)) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    Polynomial.resultant f g ≠ 0 := by
  classical
  let F := FractionRing (Polynomial K)
  have hcop : IsCoprime
      (f.map (algebraMap (Polynomial K) F))
      (g.map (algebraMap (Polynomial K) F)) :=
    isCoprime_fraction_map_of_irreducible_not_dvd f g hf hndvd
  have hres : Polynomial.resultant
      (f.map (algebraMap (Polynomial K) F))
      (g.map (algebraMap (Polynomial K) F)) ≠ 0 :=
    Polynomial.resultant_ne_zero _ _ hcop
  intro hz
  apply hres
  rw [show (f.map (algebraMap (Polynomial K) F)).natDegree = f.natDegree by
        exact Polynomial.natDegree_map_eq_of_injective
          (IsFractionRing.injective (Polynomial K) F) f,
      show (g.map (algebraMap (Polynomial K) F)).natDegree = g.natDegree by
        exact Polynomial.natDegree_map_eq_of_injective
          (IsFractionRing.injective (Polynomial K) F) g,
      Polynomial.resultant_map_map, hz, map_zero]

theorem bivar_resultant_ne_zero_of_irreducible_not_dvd
    {K : Type*} [Field K]
    (f g : MvPolynomial (Fin 2) K) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    Polynomial.resultant (bivarEquiv K f) (bivarEquiv K g) ≠ 0 := by
  apply resultant_ne_zero_of_irreducible_not_dvd
  · exact hf.map (bivarEquiv K).toMulEquiv
  · intro hdvd
    apply hndvd
    rcases hdvd with ⟨q, hq⟩
    refine ⟨(bivarEquiv K).symm q, ?_⟩
    apply (bivarEquiv K).injective
    simp [hq]

theorem eval_resultant_eq_zero_of_common_zero
    {K : Type*} [Field K]
    (f g : Polynomial (Polynomial K)) (x y : K)
    (hf : f.evalEval x y = 0) (hg : g.evalEval x y = 0)
    (hdeg : f.natDegree ≠ 0 ∨ g.natDegree ≠ 0) :
    (Polynomial.resultant f g).eval x = 0 := by
  obtain ⟨p, q, _hp, _hq, hbez⟩ :=
    Polynomial.exists_mul_add_mul_eq_C_resultant f g le_rfl le_rfl hdeg
  have he := congrArg (Polynomial.evalEvalRingHom x y) hbez
  simpa [hf, hg] using he.symm

theorem bivarEquiv_evalEval
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) (p : Fin 2 → K) :
    (bivarEquiv K f).evalEval (p 1) (p 0) = MvPolynomial.eval p f := by
  change ((Polynomial.evalEvalRingHom (p 1) (p 0)).comp
      (bivarEquiv K).toRingEquiv.toRingHom) f =
    MvPolynomial.eval₂Hom (RingHom.id K) p f
  congr 1
  apply MvPolynomial.ringHom_ext
  · intro r
    simp [bivarEquiv, MvPolynomial.finSuccEquiv_apply,
      MvPolynomial.renameEquiv_apply, MvPolynomial.pUnitAlgEquiv_apply]
  · intro i
    fin_cases i
    · simp [bivarEquiv, MvPolynomial.finSuccEquiv_apply]
    · simp only [RingHom.comp_apply, MvPolynomial.eval₂Hom_X', RingHom.id_apply]
      unfold bivarEquiv
      change (Polynomial.evalEvalRingHom (p 1) (p 0))
        (Polynomial.map
          ((MvPolynomial.renameEquiv K (Equiv.equivPUnit (Fin 1))).trans
            (MvPolynomial.pUnitAlgEquiv K))
          (MvPolynomial.finSuccEquiv K 1 (MvPolynomial.X (Fin.succ 0)))) = p 1
      rw [MvPolynomial.finSuccEquiv_X_succ]
      simp [MvPolynomial.renameEquiv_apply, MvPolynomial.pUnitAlgEquiv_apply]

noncomputable def bivarSwapEquiv (K : Type*) [Field K] :
    MvPolynomial (Fin 2) K ≃ₐ[K] Polynomial (Polynomial K) :=
  (MvPolynomial.renameEquiv K (Equiv.swap (0 : Fin 2) 1)).trans
    (bivarEquiv K)

theorem bivarSwapEquiv_evalEval
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) (p : Fin 2 → K) :
    (bivarSwapEquiv K f).evalEval (p 0) (p 1) = MvPolynomial.eval p f := by
  let q : Fin 2 → K := fun i ↦ p (Equiv.swap (0 : Fin 2) 1 i)
  have h := bivarEquiv_evalEval
    (MvPolynomial.renameEquiv K (Equiv.swap (0 : Fin 2) 1) f) q
  simp only [MvPolynomial.renameEquiv_apply] at h
  rw [MvPolynomial.eval_rename] at h
  simpa [bivarSwapEquiv, q, Function.comp_def] using h

theorem exists_elimination_polynomial
    {K : Type*} [Field K]
    (f g : Polynomial (Polynomial K)) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    ∃ r : Polynomial K, r ≠ 0 ∧ ∀ x y : K,
      f.evalEval x y = 0 → g.evalEval x y = 0 → r.eval x = 0 := by
  by_cases hdeg : f.natDegree ≠ 0 ∨ g.natDegree ≠ 0
  · refine ⟨Polynomial.resultant f g,
      resultant_ne_zero_of_irreducible_not_dvd f g hf hndvd, ?_⟩
    intro x y hfx hgx
    exact eval_resultant_eq_zero_of_common_zero f g x y hfx hgx hdeg
  · have hfdeg : f.natDegree = 0 := not_ne_iff.mp (not_or.mp hdeg |>.1)
    have hgdeg : g.natDegree = 0 := not_ne_iff.mp (not_or.mp hdeg |>.2)
    have hf0 : f ≠ 0 := hf.ne_zero
    let g' := Polynomial.X * f + g
    have hndvd' : ¬f ∣ g' := by
      rintro ⟨q, hq⟩
      apply hndvd
      refine ⟨q - Polynomial.X, ?_⟩
      dsimp [g'] at hq
      calc
        g = (Polynomial.X * f + g) - Polynomial.X * f := by ring
        _ = f * q - Polynomial.X * f := by rw [hq]
        _ = f * (q - Polynomial.X) := by ring
    have hg'deg : g'.natDegree ≠ 0 := by
      have hlt : g.natDegree < (Polynomial.X * f).natDegree := by
        simp [hf0, hfdeg, hgdeg]
      rw [show g'.natDegree = (Polynomial.X * f).natDegree by
        exact Polynomial.natDegree_add_eq_left_of_natDegree_lt hlt]
      simp [hf0, hfdeg]
    refine ⟨Polynomial.resultant f g',
      resultant_ne_zero_of_irreducible_not_dvd f g' hf hndvd', ?_⟩
    intro x y hfx hgx
    apply eval_resultant_eq_zero_of_common_zero f g' x y hfx
    · simp [g', hfx, hgx]
    · exact Or.inr hg'deg

theorem finite_common_affine_zeros_of_irreducible_not_dvd
    {K : Type*} [Field K]
    (f g : MvPolynomial (Fin 2) K) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    Set.Finite {p : Fin 2 → K |
      MvPolynomial.eval p f = 0 ∧ MvPolynomial.eval p g = 0} := by
  classical
  have hf₀ : Irreducible (bivarEquiv K f) :=
    hf.map (bivarEquiv K).toMulEquiv
  have hndvd₀ : ¬bivarEquiv K f ∣ bivarEquiv K g := by
    intro hdvd
    apply hndvd
    rcases hdvd with ⟨q, hq⟩
    refine ⟨(bivarEquiv K).symm q, ?_⟩
    apply (bivarEquiv K).injective
    simp [hq]
  obtain ⟨r₁, hr₁0, hr₁⟩ :=
    exists_elimination_polynomial (bivarEquiv K f) (bivarEquiv K g) hf₀ hndvd₀
  have hf₁ : Irreducible (bivarSwapEquiv K f) :=
    hf.map (bivarSwapEquiv K).toMulEquiv
  have hndvd₁ : ¬bivarSwapEquiv K f ∣ bivarSwapEquiv K g := by
    intro hdvd
    apply hndvd
    rcases hdvd with ⟨q, hq⟩
    refine ⟨(bivarSwapEquiv K).symm q, ?_⟩
    apply (bivarSwapEquiv K).injective
    simp [hq]
  obtain ⟨r₀, hr₀0, hr₀⟩ :=
    exists_elimination_polynomial (bivarSwapEquiv K f)
      (bivarSwapEquiv K g) hf₁ hndvd₁
  let roots : Fin 2 → Set K := ![
    {x | r₀.eval x = 0}, {x | r₁.eval x = 0}]
  have hroots : ∀ i, (roots i).Finite := by
    intro i
    fin_cases i
    · simpa [roots, Polynomial.IsRoot] using Polynomial.finite_setOf_isRoot hr₀0
    · simpa [roots, Polynomial.IsRoot] using Polynomial.finite_setOf_isRoot hr₁0
  apply (Set.Finite.pi hroots).subset
  rintro p ⟨hfp, hgp⟩ i _hi
  fin_cases i
  · change r₀.eval (p 0) = 0
    apply hr₀ (p 0) (p 1)
    · simpa [bivarSwapEquiv_evalEval] using hfp
    · simpa [bivarSwapEquiv_evalEval] using hgp
  · change r₁.eval (p 1) = 0
    apply hr₁ (p 1) (p 0)
    · simpa [bivarEquiv_evalEval] using hfp
    · simpa [bivarEquiv_evalEval] using hgp
