import Mathlib.Algebra.MvPolynomial.Equiv
import Mathlib.Algebra.MvPolynomial.Eval
import Mathlib.Data.Complex.Basic
import Mathlib.Data.Real.Sqrt
import Mathlib.FieldTheory.IntermediateField.Basic
import Mathlib.LinearAlgebra.Basis.VectorSpace
import Mathlib.RingTheory.MvPolynomial.MonomialOrder.DegLex

open scoped Polynomial

#check Module.Basis
#check Module.Free.chooseBasis

noncomputable def coeffComponent
    {K R σ ι : Type*} [Field K] [Field R] [Algebra K R]
    (b : Module.Basis ι K R) (i : ι) (f : MvPolynomial σ R) : MvPolynomial σ K :=
  f.sum fun d c ↦ MvPolynomial.monomial d (b.repr c i)

theorem coeff_coeffComponent
    {K R σ ι : Type*} [Field K] [Field R] [Algebra K R]
    (b : Module.Basis ι K R) (i : ι) (f : MvPolynomial σ R) (d : σ →₀ ℕ) :
    MvPolynomial.coeff d (coeffComponent b i f) = b.repr (MvPolynomial.coeff d f) i := by
  classical
  rw [coeffComponent, MvPolynomial.sum_def, MvPolynomial.coeff_sum]
  by_cases hd : d ∈ f.support
  · simp [hd]
  · simp [hd, MvPolynomial.notMem_support_iff.mp hd]

theorem eval_coeffComponent
    {K R σ ι : Type*} [Field K] [Field R] [Algebra K R]
    (b : Module.Basis ι K R) (i : ι) (f : MvPolynomial σ R) (p : σ → K) :
    MvPolynomial.eval p (coeffComponent b i f) =
      b.repr (MvPolynomial.eval (fun j ↦ algebraMap K R (p j)) f) i := by
  classical
  rw [coeffComponent, MvPolynomial.sum_def, MvPolynomial.eval_sum,
    MvPolynomial.eval_eq]
  simp only [MvPolynomial.eval_monomial]
  change (∑ x ∈ f.support, (b.repr (MvPolynomial.coeff x f)) i *
      x.prod fun n e ↦ p n ^ e) =
    b.coord i (∑ x ∈ f.support, MvPolynomial.coeff x f *
      ∏ j ∈ x.support, algebraMap K R (p j) ^ x j)
  rw [map_sum]
  apply Finset.sum_congr rfl
  intro d hd
  change (b.repr (MvPolynomial.coeff d f)) i *
      (d.prod fun j n ↦ p j ^ n) =
    (b.repr ((MvPolynomial.coeff d f) *
      d.prod fun j n ↦ algebraMap K R (p j) ^ n)) i
  have hprod : d.prod (fun j n ↦ algebraMap K R (p j) ^ n) =
      algebraMap K R (d.prod fun j n ↦ p j ^ n) := by
    classical
    simp only [Finsupp.prod]
    rw [map_prod]
    exact Finset.prod_congr rfl fun j hj ↦
      (map_pow (algebraMap K R) (p j) (d j)).symm
  rw [hprod, mul_comm (MvPolynomial.coeff d f)]
  rw [← Algebra.smul_def]
  simp [mul_comm]

#check MvPolynomial.totalDegree_mul_of_isDomain
#check MvPolynomial.totalDegree_le_of_support_subset
#check MvPolynomial.totalDegree_eq_zero_iff_eq_C
#check Module.Basis.sum_repr

theorem descent_from_finite_common_zeros
    (finite_common : ∀ {F G : MvPolynomial (Fin 2) ℝ},
      Irreducible F → ¬ F ∣ G →
      Set.Finite {p : Fin 2 → ℝ |
        MvPolynomial.eval p F = 0 ∧ MvPolynomial.eval p G = 0})
    (K : IntermediateField ℚ ℝ)
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (P : Set (Fin 2 → K))
    (hP : P.Infinite)
    (hvanish : ∀ p ∈ P,
      MvPolynomial.eval (fun i => (p i : ℝ)) f = 0) :
    ∃ (c : ℝ) (g : MvPolynomial (Fin 2) K),
      c ≠ 0 ∧
      f = MvPolynomial.C c *
        MvPolynomial.map (algebraMap K ℝ) g := by
  classical
  let b := Module.Free.chooseBasis K ℝ
  obtain ⟨d, hd⟩ : f.support.Nonempty :=
    Finsupp.support_nonempty_iff.mpr hf.ne_zero
  have hcd : MvPolynomial.coeff d f ≠ 0 := MvPolynomial.mem_support_iff.mp hd
  have hrepr : b.repr (MvPolynomial.coeff d f) ≠ 0 := by
    simpa using (b.repr.injective.ne hcd)
  obtain ⟨i, hi⟩ : (b.repr (MvPolynomial.coeff d f)).support.Nonempty :=
    Finsupp.support_nonempty_iff.mpr hrepr
  let g : MvPolynomial (Fin 2) K := coeffComponent b i f
  have hgcoeff : MvPolynomial.coeff d g ≠ 0 := by
    rw [coeff_coeffComponent]
    exact Finsupp.mem_support_iff.mp hi
  have hg0 : g ≠ 0 := by
    intro hg
    rw [hg, MvPolynomial.coeff_zero] at hgcoeff
    exact hgcoeff rfl
  let G : MvPolynomial (Fin 2) ℝ := MvPolynomial.map (algebraMap K ℝ) g
  have hG0 : G ≠ 0 := by
    exact (MvPolynomial.map_injective (algebraMap K ℝ)
      (algebraMap K ℝ).injective).ne hg0
  have hgvanish : ∀ p ∈ P, MvPolynomial.eval p g = 0 := by
    intro p hp
    rw [eval_coeffComponent]
    have hv := hvanish p hp
    change MvPolynomial.eval (fun j ↦ algebraMap K ℝ (p j)) f = 0 at hv
    rw [hv]
    simp
  have hcast_inj : Function.Injective
      (fun p : Fin 2 → K ↦ fun j ↦ (p j : ℝ)) := by
    intro p q hpq
    funext j
    exact Subtype.ext (congrFun hpq j)
  have himage : ((fun p : Fin 2 → K ↦ fun j ↦ (p j : ℝ)) '' P).Infinite :=
    hP.image hcast_inj.injOn
  have hdiv : f ∣ G := by
    by_contra hndvd
    have hfin := finite_common hf hndvd
    apply himage
    apply hfin.subset
    rintro q ⟨p, hp, rfl⟩
    refine ⟨hvanish p hp, ?_⟩
    rw [MvPolynomial.eval_map]
    have heq : MvPolynomial.eval₂ (algebraMap K ℝ)
        (fun j ↦ (p j : ℝ)) g =
        algebraMap K ℝ (MvPolynomial.eval p g) := by
      symm
      exact MvPolynomial.map_eval₂Hom (RingHom.id K) p
        (algebraMap K ℝ) g
    rw [heq, hgvanish p hp, map_zero]
  rcases hdiv with ⟨q, hq⟩
  have hgsupp : g.support ⊆ f.support := by
    intro m hm
    rw [MvPolynomial.mem_support_iff] at hm ⊢
    rw [coeff_coeffComponent] at hm
    intro hf0
    rw [hf0, map_zero] at hm
    exact hm rfl
  have hGsupp : G.support ⊆ f.support :=
    (MvPolynomial.support_map_subset _ _).trans hgsupp
  have hq0 : q ≠ 0 := by
    intro hq0
    subst q
    simp at hq
    exact hG0 hq
  have htdle : G.totalDegree ≤ f.totalDegree :=
    MvPolynomial.totalDegree_le_of_support_subset hGsupp
  have htdmul : (f * q).totalDegree = f.totalDegree + q.totalDegree :=
    MvPolynomial.totalDegree_mul_of_isDomain hf.ne_zero hq0
  have hqtd : q.totalDegree = 0 := by
    rw [hq] at htdle
    rw [htdmul] at htdle
    omega
  let a := MvPolynomial.coeff 0 q
  have hqC : q = MvPolynomial.C a :=
    MvPolynomial.totalDegree_eq_zero_iff_eq_C.mp hqtd
  have hGa : G = MvPolynomial.C a * f := by
    rw [hq, hqC, mul_comm]
  have ha : a ≠ 0 := by
    intro ha
    apply hG0
    rw [hGa, ha]
    simp
  refine ⟨a⁻¹, g, inv_ne_zero ha, ?_⟩
  rw [← show G = MvPolynomial.map (algebraMap K ℝ) g from rfl, hGa,
    ← mul_assoc, ← MvPolynomial.C_mul]
  simp [ha]
