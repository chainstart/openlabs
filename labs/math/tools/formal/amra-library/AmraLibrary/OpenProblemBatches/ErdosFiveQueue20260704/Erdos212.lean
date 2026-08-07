import Lean
import Mathlib.Data.Complex.Basic
import Mathlib.Topology.Homeomorph.Defs
import Mathlib.Topology.MetricSpace.Basic
import Mathlib.Topology.MetricSpace.Pseudo.Constructions
import Mathlib.Data.Finset.Max
import Mathlib.Topology.MetricSpace.Pseudo.Lemmas
import Mathlib.Topology.Algebra.Ring.Real
import Mathlib.Topology.Separation.Basic
import Mathlib.Data.Real.Sqrt
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.FinCases
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.LinearCombination
import Mathlib.Tactic.Ring
import Mathlib.Algebra.Polynomial.Bivariate
import Mathlib.Algebra.MvPolynomial.Equiv
import Mathlib.Algebra.MvPolynomial.Monad
import Mathlib.Algebra.MvPolynomial.Funext
import Mathlib.RingTheory.Polynomial.Resultant.Basic
import Mathlib.RingTheory.Polynomial.GaussLemma
import Mathlib.RingTheory.PrincipalIdealDomain
import Mathlib.LinearAlgebra.Basis.VectorSpace
import Mathlib.RingTheory.MvPolynomial.MonomialOrder.DegLex
import Mathlib.RingTheory.MvPolynomial.Homogeneous
import Mathlib.RingTheory.Polynomial.UniqueFactorization
import Mathlib.LinearAlgebra.Complex.Module
import Mathlib.RingTheory.MvPolynomial.Homogeneous
import Mathlib.RingTheory.MvPolynomial.EulerIdentity
import Mathlib.RingTheory.GradedAlgebra.Homogeneous.Ideal
import Mathlib.Algebra.Polynomial.Degree.TrailingDegree
import Mathlib.Algebra.MvPolynomial.Nilpotent
import Mathlib.LinearAlgebra.Projectivization.Basic
import Mathlib.FieldTheory.RatFunc.AsPolynomial
import Mathlib.RingTheory.Localization.Ideal

namespace AmraErdosFiveQueue20260704
namespace Erdos212

/- 2026-07-04 continuation file.  This file is intentionally self-contained for
   the configured single-file verifier: importing the 2026-07-03 continuation
   requires a prebuilt project `.olean`. -/

private lemma complex_pair_injective :
    Function.Injective (fun z : ℂ => (z.re, z.im)) := by
  intro z w h
  exact Complex.ext (congrArg Prod.fst h) (congrArg Prod.snd h)

noncomputable instance : MetricSpace ℂ :=
  MetricSpace.induced (fun z : ℂ => (z.re, z.im)) complex_pair_injective inferInstance

def PairwiseRationalDistances (u : Set ℂ) : Prop :=
  ∀ ⦃z w : ℂ⦄, z ∈ u → w ∈ u → ∃ q : ℚ, dist z w = (q : ℝ)

/-- Bridge between the continuation-file total-pair formulation and the
original problem statement's `Set.Pairwise` formulation.  The diagonal case is
handled by the rational distance `0`. -/
theorem pairwise_rational_distances_iff_original_pairwise (u : Set ℂ) :
    PairwiseRationalDistances u ↔
      u.Pairwise fun z w => dist z w ∈ Set.range Rat.cast := by
  constructor
  · intro hu z hz w hw _hzw
    rcases hu hz hw with ⟨q, hq⟩
    exact ⟨q, hq.symm⟩
  · intro hu z w hz hw
    by_cases hzw : z = w
    · subst w
      exact ⟨0, by simp⟩
    · rcases hu hz hw hzw with ⟨q, hq⟩
      exact ⟨q, hq.symm⟩

/-- Existential version of `pairwise_rational_distances_iff_original_pairwise`,
matching the original Erdős #212 statement up to the repository's `answer`
wrapper. -/
theorem dense_pairwise_rational_distances_iff_original_pairwise :
    (∃ u : Set ℂ, Dense u ∧ PairwiseRationalDistances u) ↔
      ∃ u : Set ℂ, Dense u ∧
        u.Pairwise fun z w => dist z w ∈ Set.range Rat.cast := by
  constructor
  · rintro ⟨u, hu_dense, hu_rat⟩
    exact ⟨u, hu_dense,
      (pairwise_rational_distances_iff_original_pairwise u).1 hu_rat⟩
  · rintro ⟨u, hu_dense, hu_pairwise⟩
    exact ⟨u, hu_dense,
      (pairwise_rational_distances_iff_original_pairwise u).2 hu_pairwise⟩

/-- A set contained in a closed proper subset cannot be dense.  This is the
topological contradiction used after source theorems place a rational-distance
set inside a proper closed container. -/
theorem not_dense_of_subset_closed_proper
    {X : Type*} [TopologicalSpace X] {u Z : Set X}
    (hZclosed : IsClosed Z) (hZproper : Z ≠ Set.univ) (hu : u ⊆ Z) :
    ¬ Dense u := by
  intro hu_dense
  apply hZproper
  exact Set.eq_univ_of_forall fun x =>
    closure_minimal hu hZclosed (hu_dense x)

def ClosedProperContainer (u : Set ℂ) : Prop :=
  ∃ Z : Set ℂ, IsClosed Z ∧ Z ≠ Set.univ ∧ u ⊆ Z

/-- Closed proper containers are incompatible with density. -/
theorem not_dense_of_closedProperContainer {u : Set ℂ}
    (hu : ClosedProperContainer u) :
    ¬ Dense u := by
  rcases hu with ⟨Z, hZclosed, hZproper, hsubset⟩
  exact not_dense_of_subset_closed_proper hZclosed hZproper hsubset

def SubsetLineOrCircleUnionFinset (u : Set ℂ) : Prop :=
  (∃ F : Finset ℂ, ∃ a v : ℂ, v ≠ 0 ∧
    u ⊆ ({z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ))) ∨
  (∃ F : Finset ℂ, ∃ a : ℂ, ∃ r : ℝ,
    u ⊆ ({z : ℂ | dist z a = r} ∪ (F : Set ℂ)))

def LineOrCircleUnionFinsetClosedProperContainerSource : Prop :=
  ∀ {u : Set ℂ},
    SubsetLineOrCircleUnionFinset u →
    ClosedProperContainer u

private theorem exists_real_not_mem_finset (S : Finset ℝ) :
    ∃ x : ℝ, x ∉ S := by
  by_cases hS : S.Nonempty
  · refine ⟨S.max' hS + 1, ?_⟩
    intro hx
    have hle : S.max' hS + 1 ≤ S.max' hS :=
      S.le_max' (S.max' hS + 1) hx
    linarith
  · exact ⟨0, fun h0 => hS ⟨0, h0⟩⟩

private lemma complex_continuous_re : Continuous (fun z : ℂ => z.re) := by
  exact continuous_fst.comp
    (show Continuous (fun z : ℂ => (z.re, z.im)) from continuous_induced_dom)

private lemma complex_continuous_im : Continuous (fun z : ℂ => z.im) := by
  exact continuous_snd.comp
    (show Continuous (fun z : ℂ => (z.re, z.im)) from continuous_induced_dom)

private def lineCoord (a v z : ℂ) : ℝ :=
  (z.re - a.re) * v.im - (z.im - a.im) * v.re

private lemma continuous_lineCoord (a v : ℂ) :
    Continuous (fun z : ℂ => lineCoord a v z) := by
  unfold lineCoord
  exact (((complex_continuous_re.sub continuous_const).mul continuous_const).sub
    ((complex_continuous_im.sub continuous_const).mul continuous_const))

private lemma mem_real_line_iff_lineCoord_eq_zero (a v z : ℂ) (hv : v ≠ 0) :
    (∃ t : ℝ, z = a + (t : ℂ) * v) ↔ lineCoord a v z = 0 := by
  constructor
  · rintro ⟨t, rfl⟩
    simp [lineCoord, Complex.add_re, Complex.add_im, Complex.mul_re, Complex.mul_im]
    ring
  · intro h
    by_cases hvre : v.re = 0
    · have hvim : v.im ≠ 0 := by
        intro hvim
        apply hv
        exact Complex.ext hvre hvim
      refine ⟨(z.im - a.im) / v.im, ?_⟩
      apply Complex.ext
      · have hzre : z.re = a.re := by
          dsimp [lineCoord] at h
          rw [hvre, mul_zero, sub_zero] at h
          exact sub_eq_zero.mp ((mul_eq_zero.mp h).resolve_right hvim)
        simp [Complex.add_re, Complex.mul_re, hvre, hzre]
      · simp [Complex.add_im, Complex.mul_im, hvre, hvim]
    · refine ⟨(z.re - a.re) / v.re, ?_⟩
      apply Complex.ext
      · simp [Complex.add_re, Complex.mul_re, hvre]
      · have h1 : (z.im - a.im) * v.re = (z.re - a.re) * v.im := by
          dsimp [lineCoord] at h
          exact (sub_eq_zero.mp h).symm
        have hzim : z.im - a.im = ((z.re - a.re) / v.re) * v.im := by
          calc
            z.im - a.im = ((z.im - a.im) * v.re) / v.re := by
              field_simp [hvre]
            _ = ((z.re - a.re) * v.im) / v.re := by rw [h1]
            _ = ((z.re - a.re) / v.re) * v.im := by field_simp [hvre]
        simp [Complex.add_im, Complex.mul_im]
        exact sub_eq_iff_eq_add'.mp hzim

private lemma isClosed_real_line (a v : ℂ) (hv : v ≠ 0) :
    IsClosed {z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} := by
  have hpre :
      {z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} =
        (fun z : ℂ => lineCoord a v z) ⁻¹' ({0} : Set ℝ) := by
    ext z
    exact mem_real_line_iff_lineCoord_eq_zero a v z hv
  rw [hpre]
  exact isClosed_singleton.preimage (continuous_lineCoord a v)

private lemma finite_set_isClosed_complex (F : Finset ℂ) :
    IsClosed (F : Set ℂ) :=
  (Finset.finite_toSet F).isClosed

private lemma transverse_line_point_not_on_line
    (a v : ℂ) (hv : v ≠ 0) (x t : ℝ) :
    a + ((x : ℂ) + Complex.I) * v ≠ a + (t : ℂ) * v := by
  intro h
  have hsub : (((x : ℂ) + Complex.I) - (t : ℂ)) * v =
      (a + ((x : ℂ) + Complex.I) * v) - (a + (t : ℂ) * v) := by ring
  have hmul : (((x : ℂ) + Complex.I) - (t : ℂ)) * v = 0 := by
    rw [hsub, sub_eq_zero.mpr h]
  have hcoef : ((x : ℂ) + Complex.I) - (t : ℂ) = 0 := by
    exact (mul_eq_zero.mp hmul).resolve_right hv
  have him : (((x : ℂ) + Complex.I) - (t : ℂ)).im = 1 := by
    simp [Complex.add_im, Complex.sub_im]
  rw [hcoef, Complex.zero_im] at him
  norm_num at him

private lemma transverse_line_parameter_re
    (a v : ℂ) (hv : v ≠ 0) (x : ℝ) :
    (((a + ((x : ℂ) + Complex.I) * v - a) / v).re = x) := by
  rw [show a + ((x : ℂ) + Complex.I) * v - a =
      ((x : ℂ) + Complex.I) * v by ring]
  rw [mul_div_cancel_right₀ _ hv]
  simp [Complex.add_re]

private lemma horizontal_parameter_re (a : ℂ) (x : ℝ) :
    (a + (x : ℂ) - a).re = x := by simp

private lemma horizontal_dist (a : ℂ) (x : ℝ) :
    dist (a + (x : ℂ)) a = |x| := by
  change dist (((a + (x : ℂ)).re, (a + (x : ℂ)).im)) (a.re, a.im) = |x|
  rw [Prod.dist_eq]
  simp [Real.dist_eq, Complex.add_re, Complex.add_im]

private lemma exists_not_mem_real_line_union_finset
    (F : Finset ℂ) (a v : ℂ) (hv : v ≠ 0) :
    ∃ p : ℂ, p ∉ ({z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ)) := by
  let bad : Finset ℝ := F.image (fun z : ℂ => ((z - a) / v).re)
  rcases exists_real_not_mem_finset bad with ⟨x, hx⟩
  refine ⟨a + ((x : ℂ) + Complex.I) * v, ?_⟩
  rintro (hp | hp)
  · rcases hp with ⟨t, ht⟩
    exact transverse_line_point_not_on_line a v hv x t ht
  · apply hx
    refine Finset.mem_image.mpr ⟨_, hp, ?_⟩
    exact transverse_line_parameter_re a v hv x

private lemma exists_not_mem_circle_union_finset
    (F : Finset ℂ) (a : ℂ) (r : ℝ) :
    ∃ p : ℂ, p ∉ ({z : ℂ | dist z a = r} ∪ (F : Set ℂ)) := by
  let bad : Finset ℝ := insert r (insert (-r) (F.image (fun z : ℂ => (z - a).re)))
  rcases exists_real_not_mem_finset bad with ⟨x, hx⟩
  refine ⟨a + (x : ℂ), ?_⟩
  rintro (hp | hp)
  · have habs : |x| = r := (horizontal_dist a x).symm.trans hp
    have hr : 0 ≤ r := by rw [← habs]; exact abs_nonneg x
    rcases (abs_eq hr).mp habs with hxpos | hxneg
    · apply hx
      simp [bad, hxpos]
    · apply hx
      simp [bad, hxneg]
  · apply hx
    exact Finset.mem_insert.mpr <| Or.inr <| Finset.mem_insert.mpr <| Or.inr <|
      Finset.mem_image.mpr ⟨_, hp, horizontal_parameter_re a x⟩

theorem lineOrCircleUnionFinsetClosedProperContainer :
    LineOrCircleUnionFinsetClosedProperContainerSource := by
  intro u h
  rcases h with ⟨F, a, v, hv, hu⟩ | ⟨F, a, r, hu⟩
  · let Z : Set ℂ :=
      {z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ)
    refine ⟨Z, (isClosed_real_line a v hv).union (finite_set_isClosed_complex F), ?_, hu⟩
    rcases exists_not_mem_real_line_union_finset F a v hv with ⟨p, hp⟩
    change p ∉ Z at hp
    intro hZ
    apply hp
    rw [hZ]
    exact Set.mem_univ p
  · let Z : Set ℂ := {z : ℂ | dist z a = r} ∪ (F : Set ℂ)
    refine ⟨Z, Metric.isClosed_sphere.union (finite_set_isClosed_complex F), ?_, hu⟩
    rcases exists_not_mem_circle_union_finset F a r with ⟨p, hp⟩
    change p ∉ Z at hp
    intro hZ
    apply hp
    rw [hZ]
    exact Set.mem_univ p

def BombieriLangConsequenceForRationalDistanceSets : Prop :=
  ∀ {u : Set ℂ},
    ¬ u.Finite →
    PairwiseRationalDistances u →
    SubsetLineOrCircleUnionFinset u

theorem rational_distance_subset_line_or_circle_union_finset_of_finite
    {u : Set ℂ} (hu : u.Finite) :
    SubsetLineOrCircleUnionFinset u := by
  left
  refine ⟨hu.toFinset, 0, 1, one_ne_zero, ?_⟩
  intro z hz
  exact Or.inr (hu.mem_toFinset.mpr hz)

theorem ShaffafSolymosiDeZeeuwContainmentForRationalDistanceSetsAssumingBombieriLang
    (hBL : BombieriLangConsequenceForRationalDistanceSets)
    {u : Set ℂ} (hu : PairwiseRationalDistances u) :
    SubsetLineOrCircleUnionFinset u := by
  by_cases hfin : u.Finite
  · exact rational_distance_subset_line_or_circle_union_finset_of_finite hfin
  · exact hBL hfin hu

/-- The current conditional endgame for Erdős #212: Bombieri-Lang gives the
line/circle finite-exception containment, and the closed-proper-container
source turns that containment into a topological contradiction to density. -/
theorem no_dense_pairwise_rational_distances_assuming_sources
    (hBL : BombieriLangConsequenceForRationalDistanceSets)
    (hContainer : LineOrCircleUnionFinsetClosedProperContainerSource) :
    ¬ ∃ u : Set ℂ, Dense u ∧ PairwiseRationalDistances u := by
  rintro ⟨u, hu_dense, hu_rat⟩
  have hContainment :
      SubsetLineOrCircleUnionFinset u :=
    ShaffafSolymosiDeZeeuwContainmentForRationalDistanceSetsAssumingBombieriLang
      hBL hu_rat
  have hClosedProper : ClosedProperContainer u :=
    hContainer hContainment
  exact not_dense_of_closedProperContainer hClosedProper hu_dense

/-- Same conditional endgame, phrased in the original problem statement's
`Set.Pairwise` distance language. -/
theorem no_original_dense_rational_distance_set_assuming_sources
    (hBL : BombieriLangConsequenceForRationalDistanceSets)
    (hContainer : LineOrCircleUnionFinsetClosedProperContainerSource) :
    ¬ ∃ u : Set ℂ, Dense u ∧
      u.Pairwise fun z w => dist z w ∈ Set.range Rat.cast := by
  intro h
  have hTotal : ∃ u : Set ℂ, Dense u ∧ PairwiseRationalDistances u :=
    dense_pairwise_rational_distances_iff_original_pairwise.mpr h
  exact no_dense_pairwise_rational_distances_assuming_sources hBL hContainer hTotal

theorem no_original_dense_rational_distance_set_assuming_bombieriLang
    (hBL : BombieriLangConsequenceForRationalDistanceSets) :
    ¬ ∃ u : Set ℂ, Dense u ∧
      u.Pairwise fun z w => dist z w ∈ Set.range Rat.cast := by
  exact no_original_dense_rational_distance_set_assuming_sources hBL
    lineOrCircleUnionFinsetClosedProperContainer

theorem ProjectiveAutomorphismPullbackProperZariskiClosedContainer
    {P : Type*} [TopologicalSpace P] (Φ : P ≃ₜ P) {S Z' : Set P}
    (hZclosed : IsClosed Z') (hZproper : Z' ≠ Set.univ)
    (hS : Φ '' S ⊆ Z') :
    ∃ Z : Set P, IsClosed Z ∧ Z ≠ Set.univ ∧ S ⊆ Z := by
  refine ⟨Φ ⁻¹' Z', hZclosed.preimage Φ.continuous, ?_, ?_⟩
  · intro hpre
    apply hZproper
    ext y
    constructor
    · intro hy
      exact Set.mem_univ y
    · intro hy
      rcases Φ.toEquiv.surjective y with ⟨x, rfl⟩
      have hx : x ∈ Φ ⁻¹' Z' := by
        rw [hpre]
        exact Set.mem_univ x
      exact hx
  · intro x hx
    exact hS ⟨x, hx, rfl⟩

namespace Complex

noncomputable def abs (z : ℂ) : ℝ := Real.sqrt (_root_.Complex.normSq z)

lemma abs_nonneg (z : ℂ) : 0 ≤ abs z := Real.sqrt_nonneg _

lemma abs_sq (z : ℂ) : (abs z) ^ 2 = _root_.Complex.normSq z := by
  exact Real.sq_sqrt (_root_.Complex.normSq_nonneg z)

lemma abs_eq_zero_iff {z : ℂ} : abs z = 0 ↔ z = 0 := by
  rw [abs, Real.sqrt_eq_zero (_root_.Complex.normSq_nonneg z),
    _root_.Complex.normSq_eq_zero]

end Complex

def EuclideanPairwiseRationalDistances (u : Set ℂ) : Prop :=
  ∀ ⦃z w : ℂ⦄, z ∈ u → w ∈ u →
    ∃ q : ℚ, Complex.abs (z - w) = (q : ℝ)

noncomputable def similarityNormalize (a b z : ℂ) : ℂ :=
  (z - a) / (b - a)

noncomputable def quadraticPlane (k : ℚ) (p : ℚ × ℚ) : ℂ :=
  (p.1 : ℂ) +
    ((p.2 : ℂ) * (Real.sqrt (k : ℝ) : ℂ)) * Complex.I

private lemma euclidean_abs_eq_of_sq_eq {z : ℂ} {r : ℝ}
    (hr : 0 ≤ r) (h : r ^ 2 = Complex.normSq z) :
    Complex.abs z = r := by
  apply (sq_eq_sq₀ (Complex.abs_nonneg z) hr).mp
  rw [Complex.abs_sq, h]

private lemma similarityNormalize_sub (a b z w : ℂ) :
    similarityNormalize a b z - similarityNormalize a b w =
      (z - w) / (b - a) := by
  simp only [similarityNormalize]
  ring

private lemma euclidean_abs_similarityNormalize_sub
    (a b z w : ℂ) (hab : a ≠ b)
    {q s : ℚ}
    (hq : Complex.abs (z - w) = (q : ℝ))
    (hs : Complex.abs (a - b) = (s : ℝ)) :
    Complex.abs (similarityNormalize a b z - similarityNormalize a b w) =
      ((q / s : ℚ) : ℝ) := by
  have hsposR : 0 < (s : ℝ) := by
    rw [← hs]
    exact lt_of_le_of_ne (Complex.abs_nonneg _) (Ne.symm <|
      Complex.abs_eq_zero_iff.not.mpr (sub_ne_zero.mpr hab))
  have hspos : 0 < s := Rat.cast_pos.mp hsposR
  have hqnonnegR : 0 ≤ (q : ℝ) := by rw [← hq]; exact Complex.abs_nonneg _
  rw [Rat.cast_div]
  apply euclidean_abs_eq_of_sq_eq (div_nonneg hqnonnegR hsposR.le)
  rw [similarityNormalize_sub, Complex.normSq_div]
  have hden : Complex.normSq (b - a) = (s : ℝ) ^ 2 := by
    rw [← Complex.abs_sq]
    have hneg : Complex.abs (-(a - b)) = Complex.abs (a - b) := by
      apply (sq_eq_sq₀ (Complex.abs_nonneg _) (Complex.abs_nonneg _)).mp
      rw [Complex.abs_sq, Complex.abs_sq, Complex.normSq_neg]
    rw [show b - a = -(a - b) by ring, hneg, hs]
  have hnum : Complex.normSq (z - w) = (q : ℝ) ^ 2 := by
    rw [← Complex.abs_sq, hq]
  rw [hnum, hden]
  norm_cast
  field_simp

private lemma similarityNormalize_surjective (a b : ℂ) (hab : a ≠ b) :
    Function.Surjective (similarityNormalize a b) := by
  intro y
  refine ⟨a + y * (b - a), ?_⟩
  simp [similarityNormalize, sub_ne_zero.mpr hab.symm]

private lemma similarityNormalize_continuous (a b : ℂ) :
    Continuous (similarityNormalize a b) := by
  have hre : Continuous (fun z : ℂ => z.re) := by
    exact continuous_fst.comp
      (show Continuous (fun z : ℂ => (z.re, z.im)) from continuous_induced_dom)
  have him : Continuous (fun z : ℂ => z.im) := by
    exact continuous_snd.comp
      (show Continuous (fun z : ℂ => (z.re, z.im)) from continuous_induced_dom)
  apply continuous_induced_rng.mpr
  apply Continuous.prodMk
  · simp only [similarityNormalize, Complex.div_re, Complex.sub_re]
    exact ((((hre.sub continuous_const).mul continuous_const).div_const _).add
      (((him.sub continuous_const).mul continuous_const).div_const _))
  · simp only [similarityNormalize, Complex.div_im, Complex.sub_re, Complex.sub_im]
    exact ((((him.sub continuous_const).mul continuous_const).div_const _).sub
      (((hre.sub continuous_const).mul continuous_const).div_const _))

private lemma dense_similarityNormalize_image {u : Set ℂ}
    (hu : Dense u) (a b : ℂ) (hab : a ≠ b) :
    Dense (similarityNormalize a b '' u) := by
  exact (similarityNormalize_surjective a b hab).denseRange.dense_image
    (similarityNormalize_continuous a b) hu

private lemma normalized_pairwise_rational {u : Set ℂ}
    (hu : EuclideanPairwiseRationalDistances u)
    {a b : ℂ} (ha : a ∈ u) (hb : b ∈ u) (hab : a ≠ b) :
    EuclideanPairwiseRationalDistances (similarityNormalize a b '' u) := by
  rcases hu ha hb with ⟨s, hs⟩
  intro z w hz hw
  rcases hz with ⟨z, hz, rfl⟩
  rcases hw with ⟨w, hw, rfl⟩
  rcases hu hz hw with ⟨q, hq⟩
  exact ⟨q / s, euclidean_abs_similarityNormalize_sub a b z w hab hq hs⟩

private lemma rational_coordinates
    {V : Set ℂ} (hV : EuclideanPairwiseRationalDistances V)
    {z : ℂ} (hz : z ∈ V) (hzero : (0 : ℂ) ∈ V) (hone : (1 : ℂ) ∈ V) :
    ∃ rx ry : ℚ, z.re = (rx : ℝ) ∧ z.im ^ 2 = (ry : ℝ) := by
  rcases hV hz hzero with ⟨q₀, hq₀⟩
  rcases hV hz hone with ⟨q₁, hq₁⟩
  have hn₀ : _root_.Complex.normSq z = (q₀ : ℝ) ^ 2 := by
    have habs : Complex.abs z = (q₀ : ℝ) := by simpa using hq₀
    calc
      _root_.Complex.normSq z = Complex.abs z ^ 2 := (Complex.abs_sq z).symm
      _ = (q₀ : ℝ) ^ 2 := by rw [habs]
  have hn₁ : _root_.Complex.normSq (z - 1) = (q₁ : ℝ) ^ 2 := by
    rw [← Complex.abs_sq, hq₁]
  let rx : ℚ := (q₀ ^ 2 - q₁ ^ 2 + 1) / 2
  let ry : ℚ := q₀ ^ 2 - rx ^ 2
  have hzre : z.re = (rx : ℝ) := by
    rw [_root_.Complex.normSq_apply] at hn₀
    rw [_root_.Complex.normSq_apply] at hn₁
    simp only [_root_.Complex.sub_re, _root_.Complex.sub_im,
      _root_.Complex.one_re, _root_.Complex.one_im, sub_zero] at hn₁
    dsimp [rx]
    push_cast
    nlinarith
  refine ⟨rx, ry, hzre, ?_⟩
  · rw [_root_.Complex.normSq_apply] at hn₀
    dsimp [ry]
    push_cast
    rw [hzre] at hn₀
    ring_nf at hn₀ ⊢
    nlinarith

private lemma rational_imaginary_product
    {V : Set ℂ} (hV : EuclideanPairwiseRationalDistances V)
    (hzero : (0 : ℂ) ∈ V) (hone : (1 : ℂ) ∈ V)
    {z c : ℂ} (hz : z ∈ V) (hc : c ∈ V) :
    ∃ r : ℚ, z.im * c.im = (r : ℝ) := by
  rcases rational_coordinates hV hz hzero hone with ⟨rz, yz, hrz, hyz⟩
  rcases rational_coordinates hV hc hzero hone with ⟨rc, yc, hrc, hyc⟩
  rcases hV hz hc with ⟨q, hq⟩
  have hn : _root_.Complex.normSq (z - c) = (q : ℝ) ^ 2 := by
    rw [← Complex.abs_sq, hq]
  let r : ℚ := ((rz - rc) ^ 2 + yz + yc - q ^ 2) / 2
  refine ⟨r, ?_⟩
  rw [_root_.Complex.normSq_apply] at hn
  simp only [_root_.Complex.sub_re, _root_.Complex.sub_im] at hn
  dsimp [r]
  push_cast
  rw [hrz, hrc] at hn
  nlinarith

private lemma quadratic_representation
    {V : Set ℂ} (hV : EuclideanPairwiseRationalDistances V)
    (hzero : (0 : ℂ) ∈ V) (hone : (1 : ℂ) ∈ V)
    {c : ℂ} (hc : c ∈ V) (hcpos : 0 < c.im)
    {k : ℚ} (hck : c.im ^ 2 = (k : ℝ))
    {z : ℂ} (hz : z ∈ V) :
    ∃ p : ℚ × ℚ, quadraticPlane k p = z := by
  rcases rational_coordinates hV hz hzero hone with ⟨rz, yz, hrz, hyz⟩
  rcases rational_imaginary_product hV hzero hone hz hc with ⟨r, hr⟩
  have hkposR : 0 < (k : ℝ) := by rw [← hck]; positivity
  have hk : k ≠ 0 := ne_of_gt (Rat.cast_pos.mp hkposR)
  have hsqrt : Real.sqrt (k : ℝ) = c.im := by
    rw [← hck]
    exact Real.sqrt_sq hcpos.le
  refine ⟨(rz, r / k), ?_⟩
  apply _root_.Complex.ext
  · simp [quadraticPlane, hrz]
  · simp only [quadraticPlane, _root_.Complex.add_im, _root_.Complex.mul_im,
      _root_.Complex.ofReal_re, _root_.Complex.ofReal_im, add_zero,
      _root_.Complex.I_re, _root_.Complex.I_im, mul_zero, mul_one]
    norm_num
    rw [hsqrt, ← hck]
    rw [← hr]
    field_simp [hcpos.ne']

private lemma normalized_zero_mem {u : Set ℂ} {a b : ℂ}
    (ha : a ∈ u) :
    (0 : ℂ) ∈ similarityNormalize a b '' u := by
  refine ⟨a, ha, ?_⟩
  simp [similarityNormalize]

private lemma normalized_one_mem {u : Set ℂ} {a b : ℂ}
    (hb : b ∈ u) (hab : a ≠ b) :
    (1 : ℂ) ∈ similarityNormalize a b '' u := by
  refine ⟨b, hb, ?_⟩
  simp [similarityNormalize, sub_ne_zero.mpr hab.symm]

theorem euclidean_rational_distance_normalization_of_oriented_third_point
    {u : Set ℂ}
    (huRat : EuclideanPairwiseRationalDistances u)
    {a b c : ℂ}
    (ha : a ∈ u) (hb : b ∈ u) (hc : c ∈ u)
    (hab : a ≠ b)
    (hcUpper : 0 < (similarityNormalize a b c).im) :
    ∃ (k : ℚ) (P : Set (ℚ × ℚ)),
      0 < k ∧
      similarityNormalize a b '' u = quadraticPlane k '' P ∧
      EuclideanPairwiseRationalDistances (quadraticPlane k '' P) := by
  let V : Set ℂ := similarityNormalize a b '' u
  let c' : ℂ := similarityNormalize a b c
  have hVrat : EuclideanPairwiseRationalDistances V :=
    normalized_pairwise_rational huRat ha hb hab
  have hzero : (0 : ℂ) ∈ V := normalized_zero_mem ha
  have hone : (1 : ℂ) ∈ V := normalized_one_mem hb hab
  have hc' : c' ∈ V := ⟨c, hc, rfl⟩
  have hc'pos : 0 < c'.im := hcUpper
  rcases rational_coordinates hVrat hc' hzero hone with
    ⟨rc, k, hrc, hc'k⟩
  have hkposR : 0 < (k : ℝ) := by
    rw [← hc'k]
    exact sq_pos_of_pos hc'pos
  have hkpos : 0 < k := Rat.cast_pos.mp hkposR
  let P : Set (ℚ × ℚ) := {p | quadraticPlane k p ∈ V}
  have hEq : V = quadraticPlane k '' P := by
    apply Set.Subset.antisymm
    · intro z hz
      rcases quadratic_representation hVrat hzero hone hc' hc'pos hc'k hz with
        ⟨p, hp⟩
      refine ⟨p, ?_, hp⟩
      change quadraticPlane k p ∈ V
      rw [hp]
      exact hz
    · rintro z ⟨p, hp, rfl⟩
      exact hp
  refine ⟨k, P, hkpos, hEq, ?_⟩
  rw [← hEq]
  exact hVrat

theorem dense_euclidean_rational_distance_normalization
    {u : Set ℂ}
    (huDense : Dense u)
    (huRat : EuclideanPairwiseRationalDistances u) :
    ∃ (a b : ℂ) (k : ℚ) (P : Set (ℚ × ℚ)),
      a ∈ u ∧
      b ∈ u ∧
      a ≠ b ∧
      0 < k ∧
      similarityNormalize a b '' u = quadraticPlane k '' P ∧
      Dense (quadraticPlane k '' P) ∧
      EuclideanPairwiseRationalDistances (quadraticPlane k '' P) := by
  rcases huDense.nonempty with ⟨a, ha⟩
  have hopen : IsOpen ({a}ᶜ : Set ℂ) := isClosed_singleton.isOpen_compl
  have hnonempty : ({a}ᶜ : Set ℂ).Nonempty := by
    refine ⟨a + 1, ?_⟩
    simp
  rcases huDense.inter_open_nonempty {a}ᶜ hopen hnonempty with ⟨b, hbne, hb⟩
  have hab : a ≠ b := by simpa [ne_comm] using hbne
  let V : Set ℂ := similarityNormalize a b '' u
  have hVdense : Dense V := dense_similarityNormalize_image huDense a b hab
  have hVrat : EuclideanPairwiseRationalDistances V :=
    normalized_pairwise_rational huRat ha hb hab
  have hzero : (0 : ℂ) ∈ V := normalized_zero_mem ha
  have hone : (1 : ℂ) ∈ V := normalized_one_mem hb hab
  have himcont : Continuous (fun z : ℂ => z.im) := by
    exact continuous_snd.comp
      (show Continuous (fun z : ℂ => (z.re, z.im)) from continuous_induced_dom)
  have huppopen : IsOpen {z : ℂ | 0 < z.im} :=
    isOpen_lt continuous_const himcont
  have huppnonempty : Set.Nonempty {z : ℂ | 0 < z.im} := by
    exact ⟨_root_.Complex.I, by simp⟩
  rcases hVdense.inter_open_nonempty {z : ℂ | 0 < z.im} huppopen huppnonempty with
    ⟨c, hcpos, hc⟩
  rcases rational_coordinates hVrat hc hzero hone with ⟨rc, k, hrc, hck⟩
  have hkposR : 0 < (k : ℝ) := by
    rw [← hck]
    exact sq_pos_of_pos hcpos
  have hkpos : 0 < k := Rat.cast_pos.mp hkposR
  let P : Set (ℚ × ℚ) := {p | quadraticPlane k p ∈ V}
  have hEq : V = quadraticPlane k '' P := by
    apply Set.Subset.antisymm
    · intro z hz
      rcases quadratic_representation hVrat hzero hone hc hcpos hck hz with ⟨p, hp⟩
      refine ⟨p, ?_, hp⟩
      change quadraticPlane k p ∈ V
      rw [hp]
      exact hz
    · rintro z ⟨p, hp, rfl⟩
      exact hp
  refine ⟨a, b, k, P, ha, hb, hab, hkpos, ?_, ?_, ?_⟩
  · exact hEq
  · rw [← hEq]
    exact hVdense
  · rw [← hEq]
    exact hVrat

def FourQuadricAffine
    (k : ℚ) (A : Fin 4 → ℚ × ℚ) :
    Set (((ℚ × ℚ) × (Fin 4 → ℚ))) :=
  {Q | ∀ j,
    (Q.2 j) ^ 2 =
      (Q.1.1 - (A j).1) ^ 2 +
        k * (Q.1.2 - (A j).2) ^ 2}

private lemma quadraticPlane_normSq_sub
    {k : ℚ} (hk : 0 < k) (p a : ℚ × ℚ) :
    _root_.Complex.normSq (quadraticPlane k p - quadraticPlane k a) =
      (((p.1 - a.1) ^ 2 + k * (p.2 - a.2) ^ 2 : ℚ) : ℝ) := by
  rw [_root_.Complex.normSq_apply]
  simp only [quadraticPlane, _root_.Complex.sub_re, _root_.Complex.sub_im,
    _root_.Complex.add_re, _root_.Complex.add_im, _root_.Complex.mul_re,
    _root_.Complex.mul_im, _root_.Complex.ofReal_re, _root_.Complex.ofReal_im,
    _root_.Complex.I_re, _root_.Complex.I_im]
  norm_num
  have hsqrt : Real.sqrt (k : ℝ) ^ 2 = (k : ℝ) :=
    Real.sq_sqrt (Rat.cast_nonneg.mpr hk.le)
  nlinarith [hsqrt]

private lemma quadric_equation_of_euclidean_abs
    {k : ℚ} (hk : 0 < k) (p a : ℚ × ℚ) (r : ℚ)
    (h : Complex.abs (quadraticPlane k p - quadraticPlane k a) = (r : ℝ)) :
    r ^ 2 = (p.1 - a.1) ^ 2 + k * (p.2 - a.2) ^ 2 := by
  have hReal : (r : ℝ) ^ 2 =
      (((p.1 - a.1) ^ 2 + k * (p.2 - a.2) ^ 2 : ℚ) : ℝ) := by
    calc
    (r : ℝ) ^ 2 = Complex.abs (quadraticPlane k p - quadraticPlane k a) ^ 2 := by
      rw [h]
    _ = _root_.Complex.normSq (quadraticPlane k p - quadraticPlane k a) :=
      Complex.abs_sq _
    _ = (((p.1 - a.1) ^ 2 + k * (p.2 - a.2) ^ 2 : ℚ) : ℝ) :=
      quadraticPlane_normSq_sub hk p a
  exact_mod_cast hReal

theorem dense_quadraticPlane_fourQuadric_lift
    {k : ℚ} {P : Set (ℚ × ℚ)}
    (hk : 0 < k)
    (hDense : Dense (quadraticPlane k '' P))
    (hRat :
      EuclideanPairwiseRationalDistances (quadraticPlane k '' P)) :
    ∃ (A : Fin 4 → ℚ × ℚ)
      (R : Set ((ℚ × ℚ) × (Fin 4 → ℚ))),
      Function.Injective A ∧
      (∀ j, A j ∈ P) ∧
      R ⊆ FourQuadricAffine k A ∧
      Prod.fst '' R = P := by
  letI : Infinite ℂ := Infinite.of_injective
    (fun n : ℕ ↦ (((n : ℝ) : ℂ)))
    (fun _ _ h ↦ Nat.cast_injective (_root_.Complex.ofReal_injective h))
  have hPInfinite : P.Infinite := by
    intro hPFinite
    have hImageFinite : (quadraticPlane k '' P).Finite :=
      hPFinite.image (quadraticPlane k)
    have hImageUniv : quadraticPlane k '' P = Set.univ := by
      calc
        quadraticPlane k '' P = closure (quadraticPlane k '' P) :=
          hImageFinite.isClosed.closure_eq.symm
        _ = Set.univ := hDense.closure_eq
    exact Set.infinite_univ (hImageUniv ▸ hImageFinite)
  let e : Fin 4 ↪ {p // p ∈ P} :=
    Fin.valEmbedding.trans (hPInfinite.natEmbedding P)
  let A : Fin 4 → ℚ × ℚ := fun j ↦ (e j).1
  have hAInjective : Function.Injective A :=
    Subtype.val_injective.comp e.injective
  have hAMem : ∀ j, A j ∈ P := fun j ↦ (e j).2
  let R : Set (((ℚ × ℚ) × (Fin 4 → ℚ))) :=
    {Q | Q.1 ∈ P ∧ Q ∈ FourQuadricAffine k A}
  refine ⟨A, R, hAInjective, hAMem, ?_, ?_⟩
  · intro Q hQ
    exact hQ.2
  · apply Set.Subset.antisymm
    · rintro p ⟨Q, hQ, rfl⟩
      exact hQ.1
    · intro p hp
      have hpImage : quadraticPlane k p ∈ quadraticPlane k '' P := ⟨p, hp, rfl⟩
      have hDistances : ∀ j, ∃ r : ℚ,
          Complex.abs (quadraticPlane k p - quadraticPlane k (A j)) = (r : ℝ) := by
        intro j
        exact hRat hpImage ⟨A j, hAMem j, rfl⟩
      choose r hr using hDistances
      refine ⟨(p, r), ?_, rfl⟩
      refine ⟨hp, ?_⟩
      intro j
      exact quadric_equation_of_euclidean_abs hk p (A j) (r j) (hr j)

def FourPointsGeneralPosition
    (A : Fin 4 → ℚ × ℚ) : Prop :=
  Function.Injective A ∧
  ∀ ⦃i j l : Fin 4⦄,
    i ≠ j → i ≠ l → j ≠ l →
    ((A j).1 - (A i).1) * ((A l).2 - (A i).2) ≠
      ((A j).2 - (A i).2) * ((A l).1 - (A i).1)

private def rationalLineDet (a b c : ℚ × ℚ) : ℚ :=
  (b.1 - a.1) * (c.2 - a.2) -
    (b.2 - a.2) * (c.1 - a.1)

private lemma rationalLineDet_ne_permutations {a b c : ℚ × ℚ}
    (h : rationalLineDet a b c ≠ 0) :
    rationalLineDet a c b ≠ 0 ∧
    rationalLineDet b a c ≠ 0 ∧
    rationalLineDet b c a ≠ 0 ∧
    rationalLineDet c a b ≠ 0 ∧
    rationalLineDet c b a ≠ 0 := by
  constructor
  · intro hz
    apply h
    dsimp [rationalLineDet] at hz ⊢
    linear_combination -hz
  constructor
  · intro hz
    apply h
    dsimp [rationalLineDet] at hz ⊢
    linear_combination -hz
  constructor
  · intro hz
    apply h
    dsimp [rationalLineDet] at hz ⊢
    linear_combination hz
  constructor
  · intro hz
    apply h
    dsimp [rationalLineDet] at hz ⊢
    linear_combination hz
  · intro hz
    apply h
    dsimp [rationalLineDet] at hz ⊢
    linear_combination -hz

private def complexLineDet (a b z : ℂ) : ℝ :=
  (b.re - a.re) * (z.im - a.im) -
    (b.im - a.im) * (z.re - a.re)

private lemma continuous_complexLineDet (a b : ℂ) :
    Continuous (complexLineDet a b) := by
  unfold complexLineDet
  exact
    (continuous_const.mul (complex_continuous_im.sub continuous_const)).sub
      (continuous_const.mul (complex_continuous_re.sub continuous_const))

private lemma quadraticPlane_complexLineDet
    (k : ℚ) (a b p : ℚ × ℚ) :
    complexLineDet (quadraticPlane k a) (quadraticPlane k b)
        (quadraticPlane k p) =
      Real.sqrt (k : ℝ) *
        ((((b.1 - a.1) * (p.2 - a.2) -
          (b.2 - a.2) * (p.1 - a.1)) : ℚ) : ℝ) := by
  simp only [complexLineDet, quadraticPlane, _root_.Complex.add_re,
    _root_.Complex.add_im, _root_.Complex.mul_re, _root_.Complex.mul_im,
    _root_.Complex.ofReal_re, _root_.Complex.ofReal_im,
    _root_.Complex.I_re, _root_.Complex.I_im]
  norm_num
  ring

private lemma rational_det_ne_of_complexLineDet_ne
    {k : ℚ} {a b p : ℚ × ℚ}
    (hdet : complexLineDet (quadraticPlane k a) (quadraticPlane k b)
      (quadraticPlane k p) ≠ 0) :
    (b.1 - a.1) * (p.2 - a.2) ≠
      (b.2 - a.2) * (p.1 - a.1) := by
  intro h
  apply hdet
  rw [quadraticPlane_complexLineDet]
  rw [sub_eq_zero.mpr h]
  norm_num

private lemma exists_four_generalPosition_of_dense_quadraticPlane
    {k : ℚ} {P : Set (ℚ × ℚ)}
    (hDense : Dense (quadraticPlane k '' P)) :
    ∃ A : Fin 4 → ℚ × ℚ,
      FourPointsGeneralPosition A ∧ ∀ j, A j ∈ P := by
  rcases hDense.nonempty with ⟨z₀, hz₀⟩
  rcases hz₀ with ⟨p₀, hp₀, rfl⟩
  let U₁ : Set ℂ := {(quadraticPlane k p₀)}ᶜ
  have hU₁open : IsOpen U₁ := isClosed_singleton.isOpen_compl
  have hU₁nonempty : U₁.Nonempty := by
    refine ⟨quadraticPlane k p₀ + 1, ?_⟩
    simp [U₁]
  rcases hDense.inter_open_nonempty U₁ hU₁open hU₁nonempty with
    ⟨z₁, hz₁ne, hz₁⟩
  rcases hz₁ with ⟨p₁, hp₁, rfl⟩
  have hz₀₁ : quadraticPlane k p₀ ≠ quadraticPlane k p₁ := by
    simpa [U₁, ne_comm] using hz₁ne
  let U₂ : Set ℂ :=
    {z | complexLineDet (quadraticPlane k p₀) (quadraticPlane k p₁) z ≠ 0}
  have hU₂open : IsOpen U₂ :=
    isOpen_ne.preimage (continuous_complexLineDet _ _)
  have hU₂nonempty : U₂.Nonempty := by
    let dx := (quadraticPlane k p₁).re - (quadraticPlane k p₀).re
    let dy := (quadraticPlane k p₁).im - (quadraticPlane k p₀).im
    let z : ℂ :=
      ⟨(quadraticPlane k p₀).re - dy,
        (quadraticPlane k p₀).im + dx⟩
    refine ⟨z, ?_⟩
    intro hzero
    apply hz₀₁
    apply _root_.Complex.ext
    · dsimp [U₂, complexLineDet, z, dx, dy] at hzero
      nlinarith [sq_nonneg dx, sq_nonneg dy]
    · dsimp [U₂, complexLineDet, z, dx, dy] at hzero
      nlinarith [sq_nonneg dx, sq_nonneg dy]
  rcases hDense.inter_open_nonempty U₂ hU₂open hU₂nonempty with
    ⟨z₂, hz₂det, hz₂⟩
  rcases hz₂ with ⟨p₂, hp₂, rfl⟩
  have hdet₀₁₂ : complexLineDet (quadraticPlane k p₀)
      (quadraticPlane k p₁) (quadraticPlane k p₂) ≠ 0 := hz₂det
  let U₃ : Set ℂ :=
    {z | complexLineDet (quadraticPlane k p₀) (quadraticPlane k p₁) z ≠ 0} ∩
    {z | complexLineDet (quadraticPlane k p₀) (quadraticPlane k p₂) z ≠ 0} ∩
    {z | complexLineDet (quadraticPlane k p₁) (quadraticPlane k p₂) z ≠ 0}
  have hU₃open : IsOpen U₃ := by
    exact ((isOpen_ne.preimage (continuous_complexLineDet _ _)).inter
      (isOpen_ne.preimage (continuous_complexLineDet _ _))).inter
      (isOpen_ne.preimage (continuous_complexLineDet _ _))
  have hU₃nonempty : U₃.Nonempty := by
    let a := quadraticPlane k p₀
    let b := quadraticPlane k p₁
    let c := quadraticPlane k p₂
    let z : ℂ :=
      ⟨a.re + 2 * (b.re - a.re) + 4 * (c.re - a.re),
        a.im + 2 * (b.im - a.im) + 4 * (c.im - a.im)⟩
    have hz₀₁ : complexLineDet a b z = 4 * complexLineDet a b c := by
      simp only [complexLineDet, z]
      ring
    have hz₀₂ : complexLineDet a c z = -2 * complexLineDet a b c := by
      simp only [complexLineDet, z]
      ring
    have hz₁₂ : complexLineDet b c z = -5 * complexLineDet a b c := by
      simp only [complexLineDet, z]
      ring
    refine ⟨z, ⟨?_, ?_⟩, ?_⟩
    · change complexLineDet a b z ≠ 0
      rw [hz₀₁]
      exact mul_ne_zero (by norm_num) hdet₀₁₂
    · change complexLineDet a c z ≠ 0
      rw [hz₀₂]
      exact mul_ne_zero (by norm_num) hdet₀₁₂
    · change complexLineDet b c z ≠ 0
      rw [hz₁₂]
      exact mul_ne_zero (by norm_num) hdet₀₁₂
  rcases hDense.inter_open_nonempty U₃ hU₃open hU₃nonempty with
    ⟨z₃, hz₃det, hz₃⟩
  rcases hz₃ with ⟨p₃, hp₃, rfl⟩
  rcases hz₃det with ⟨⟨hdet₀₁₃, hdet₀₂₃⟩, hdet₁₂₃⟩
  have hq₀₁₂ := rational_det_ne_of_complexLineDet_ne hdet₀₁₂
  have hq₀₁₃ := rational_det_ne_of_complexLineDet_ne hdet₀₁₃
  have hq₀₂₃ := rational_det_ne_of_complexLineDet_ne hdet₀₂₃
  have hq₁₂₃ := rational_det_ne_of_complexLineDet_ne hdet₁₂₃
  have hd₀₁₂ : rationalLineDet p₀ p₁ p₂ ≠ 0 := sub_ne_zero.mpr hq₀₁₂
  have hd₀₁₃ : rationalLineDet p₀ p₁ p₃ ≠ 0 := sub_ne_zero.mpr hq₀₁₃
  have hd₀₂₃ : rationalLineDet p₀ p₂ p₃ ≠ 0 := sub_ne_zero.mpr hq₀₂₃
  have hd₁₂₃ : rationalLineDet p₁ p₂ p₃ ≠ 0 := sub_ne_zero.mpr hq₁₂₃
  rcases rationalLineDet_ne_permutations hd₀₁₂ with
    ⟨hd₀₂₁, hd₁₀₂, hd₁₂₀, hd₂₀₁, hd₂₁₀⟩
  rcases rationalLineDet_ne_permutations hd₀₁₃ with
    ⟨hd₀₃₁, hd₁₀₃, hd₁₃₀, hd₃₀₁, hd₃₁₀⟩
  rcases rationalLineDet_ne_permutations hd₀₂₃ with
    ⟨hd₀₃₂, hd₂₀₃, hd₂₃₀, hd₃₀₂, hd₃₂₀⟩
  rcases rationalLineDet_ne_permutations hd₁₂₃ with
    ⟨hd₁₃₂, hd₂₁₃, hd₂₃₁, hd₃₁₂, hd₃₂₁⟩
  let A : Fin 4 → ℚ × ℚ := ![p₀, p₁, p₂, p₃]
  have hp₀₁ : p₀ ≠ p₁ := by
    intro h
    subst p₁
    apply hq₀₁₂
    ring
  have hp₀₂ : p₀ ≠ p₂ := by
    intro h
    subst p₂
    apply hq₀₁₂
    ring
  have hp₁₂ : p₁ ≠ p₂ := by
    intro h
    subst p₂
    apply hq₀₁₂
    ring
  have hp₀₃ : p₀ ≠ p₃ := by
    intro h
    subst p₃
    apply hq₀₁₃
    ring
  have hp₁₃ : p₁ ≠ p₃ := by
    intro h
    subst p₃
    apply hq₀₁₃
    ring
  have hp₂₃ : p₂ ≠ p₃ := by
    intro h
    subst p₃
    apply hq₀₂₃
    ring
  have hAinj : Function.Injective A := by
    intro i j
    fin_cases i <;> fin_cases j <;>
      simp [A, hp₀₁, hp₀₂, hp₀₃, hp₁₂, hp₁₃, hp₂₃,
        ne_comm]
  refine ⟨A, ⟨hAinj, ?_⟩, ?_⟩
  · intro i j l hij hil hjl
    apply sub_ne_zero.mp
    change rationalLineDet (A i) (A j) (A l) ≠ 0
    fin_cases i <;> fin_cases j <;> fin_cases l
    all_goals try { exact (hij rfl).elim }
    all_goals try { exact (hil rfl).elim }
    all_goals try { exact (hjl rfl).elim }
    all_goals simp [A]
    all_goals first
      | exact hd₀₁₂ | exact hd₀₂₁ | exact hd₁₀₂
      | exact hd₁₂₀ | exact hd₂₀₁ | exact hd₂₁₀
      | exact hd₀₁₃ | exact hd₀₃₁ | exact hd₁₀₃
      | exact hd₁₃₀ | exact hd₃₀₁ | exact hd₃₁₀
      | exact hd₀₂₃ | exact hd₀₃₂ | exact hd₂₀₃
      | exact hd₂₃₀ | exact hd₃₀₂ | exact hd₃₂₀
      | exact hd₁₂₃ | exact hd₁₃₂ | exact hd₂₁₃
      | exact hd₂₃₁ | exact hd₃₁₂ | exact hd₃₂₁
  · intro j
    fin_cases j <;> simp [A, hp₀, hp₁, hp₂, hp₃]

theorem dense_quadraticPlane_fourQuadric_lift_generalPosition
    {k : ℚ} {P : Set (ℚ × ℚ)}
    (hk : 0 < k)
    (hDense : Dense (quadraticPlane k '' P))
    (hRat :
      EuclideanPairwiseRationalDistances (quadraticPlane k '' P)) :
    ∃ (A : Fin 4 → ℚ × ℚ)
      (R : Set ((ℚ × ℚ) × (Fin 4 → ℚ))),
      FourPointsGeneralPosition A ∧
      (∀ j, A j ∈ P) ∧
      R ⊆ FourQuadricAffine k A ∧
      Prod.fst '' R = P := by
  rcases exists_four_generalPosition_of_dense_quadraticPlane hDense with
    ⟨A, hAGeneral, hAMem⟩
  let R : Set (((ℚ × ℚ) × (Fin 4 → ℚ))) :=
    {Q | Q.1 ∈ P ∧ Q ∈ FourQuadricAffine k A}
  refine ⟨A, R, hAGeneral, hAMem, ?_, ?_⟩
  · intro Q hQ
    exact hQ.2
  · apply Set.Subset.antisymm
    · rintro p ⟨Q, hQ, rfl⟩
      exact hQ.1
    · intro p hp
      have hpImage : quadraticPlane k p ∈ quadraticPlane k '' P := ⟨p, hp, rfl⟩
      have hDistances : ∀ j, ∃ r : ℚ,
          Complex.abs (quadraticPlane k p - quadraticPlane k (A j)) = (r : ℝ) := by
        intro j
        exact hRat hpImage ⟨A j, hAMem j, rfl⟩
      choose r hr using hDistances
      refine ⟨(p, r), ?_, rfl⟩
      refine ⟨hp, ?_⟩
      intro j
      exact quadric_equation_of_euclidean_abs hk p (A j) (r j) (hr j)

theorem dense_euclidean_rational_distance_fourQuadric_firstObstruction
    {u : Set ℂ}
    (huDense : Dense u)
    (huRat : EuclideanPairwiseRationalDistances u) :
    ∃ (k : ℚ) (A : Fin 4 → ℚ × ℚ),
      0 < k ∧
      FourPointsGeneralPosition A ∧
      Dense
        (quadraticPlane k ''
          (Prod.fst '' FourQuadricAffine k A)) := by
  rcases dense_euclidean_rational_distance_normalization huDense huRat with
    ⟨a, b, k, P, ha, hb, hab, hk, hnorm, hPdense, hPrat⟩
  rcases dense_quadraticPlane_fourQuadric_lift_generalPosition
      hk hPdense hPrat with
    ⟨A, R, hAGeneral, hAMem, hRsub, hRproj⟩
  refine ⟨k, A, hk, hAGeneral, ?_⟩
  apply hPdense.mono
  apply Set.image_mono
  rw [← hRproj]
  exact Set.image_mono hRsub

/-- The Gauss-lemma bridge needed by bivariate resultant elimination.  When
the first polynomial is irreducible, nondivisibility over the coefficient
domain becomes coprimality after passage to its fraction field. -/
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
    have hdvdprim : f.map (algebraMap R F) ∣
        g.primPart.map (algebraMap R F) := by
      rw [g.eq_C_content_mul_primPart, Polynomial.map_mul,
        Polynomial.map_C] at hdvd
      rwa [IsUnit.dvd_mul_left (Polynomial.isUnit_C.mpr hcontent)] at hdvd
    apply hndvd
    exact (hfprim.dvd_primPart_iff_dvd hg0).mp
      (hfprim.dvd_of_fraction_map_dvd_fraction_map
        g.isPrimitive_primPart hdvdprim)

/-- A nonzero elimination polynomial for two nested univariate polynomials.
This is the resultant step in the finite-common-zero argument: irreducibility
and nondivisibility over `K[X]` give coprimality over its fraction field, and
injectivity of the fraction map reflects nonvanishing of the resultant. -/
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

/-- View a polynomial in two indexed variables as a polynomial whose
coefficients are univariate polynomials. -/
noncomputable def planePolynomialEquiv (K : Type*) [Field K] :
    MvPolynomial (Fin 2) K ≃ₐ[K] Polynomial (Polynomial K) :=
  (MvPolynomial.finSuccEquiv K 1).trans
    (Polynomial.mapAlgEquiv
      ((MvPolynomial.renameEquiv K (Equiv.equivPUnit.{1, 1} (Fin 1))).trans
        (MvPolynomial.pUnitAlgEquiv.{_, 0} K)))

/-- The bivariate form of `resultant_ne_zero_of_irreducible_not_dvd`. -/
theorem planePolynomial_resultant_ne_zero_of_irreducible_not_dvd
    {K : Type*} [Field K]
    (f g : MvPolynomial (Fin 2) K) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    Polynomial.resultant (planePolynomialEquiv K f)
      (planePolynomialEquiv K g) ≠ 0 := by
  apply resultant_ne_zero_of_irreducible_not_dvd
  · exact hf.map (planePolynomialEquiv K).toMulEquiv
  · intro hdvd
    apply hndvd
    rcases hdvd with ⟨q, hq⟩
    refine ⟨(planePolynomialEquiv K).symm q, ?_⟩
    apply (planePolynomialEquiv K).injective
    simp [hq]

/-- A common zero of two nested univariate polynomials is a zero of their
resultant in the coefficient variable, provided the eliminated variable
actually occurs in at least one polynomial. -/
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

/-- Evaluation compatibility for `planePolynomialEquiv`: the inner
polynomial variable is coordinate `1`, and the outer variable is coordinate
`0`. -/
theorem planePolynomialEquiv_evalEval
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) (p : Fin 2 → K) :
    (planePolynomialEquiv K f).evalEval (p 1) (p 0) =
      MvPolynomial.eval p f := by
  change ((Polynomial.evalEvalRingHom (p 1) (p 0)).comp
      (planePolynomialEquiv K).toRingEquiv.toRingHom) f =
    MvPolynomial.eval₂Hom (RingHom.id K) p f
  congr 1
  apply MvPolynomial.ringHom_ext
  · intro r
    simp [planePolynomialEquiv, MvPolynomial.finSuccEquiv_apply,
      MvPolynomial.renameEquiv_apply, MvPolynomial.pUnitAlgEquiv_apply]
  · intro i
    fin_cases i
    · simp [planePolynomialEquiv, MvPolynomial.finSuccEquiv_apply]
    · simp only [RingHom.comp_apply, MvPolynomial.eval₂Hom_X']
      unfold planePolynomialEquiv
      change (Polynomial.evalEvalRingHom (p 1) (p 0))
        (Polynomial.map
          ((MvPolynomial.renameEquiv K (Equiv.equivPUnit (Fin 1))).trans
            (MvPolynomial.pUnitAlgEquiv K))
          (MvPolynomial.finSuccEquiv K 1 (MvPolynomial.X (Fin.succ 0)))) = p 1
      rw [MvPolynomial.finSuccEquiv_X_succ]
      simp [MvPolynomial.renameEquiv_apply, MvPolynomial.pUnitAlgEquiv_apply]

/-- The same nested-univariate representation after interchanging the two
plane coordinates. -/
noncomputable def planePolynomialSwapEquiv (K : Type*) [Field K] :
    MvPolynomial (Fin 2) K ≃ₐ[K] Polynomial (Polynomial K) :=
  (MvPolynomial.renameEquiv K (Equiv.swap (0 : Fin 2) 1)).trans
    (planePolynomialEquiv K)

theorem planePolynomialSwapEquiv_evalEval
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) (p : Fin 2 → K) :
    (planePolynomialSwapEquiv K f).evalEval (p 0) (p 1) =
      MvPolynomial.eval p f := by
  let q : Fin 2 → K := fun i ↦ p (Equiv.swap (0 : Fin 2) 1 i)
  have h := planePolynomialEquiv_evalEval
    (MvPolynomial.renameEquiv K (Equiv.swap (0 : Fin 2) 1) f) q
  simp only [MvPolynomial.renameEquiv_apply] at h
  rw [MvPolynomial.eval_rename] at h
  simpa [planePolynomialSwapEquiv, q, Function.comp_def] using h

theorem planePolynomialSwap_resultant_ne_zero_of_irreducible_not_dvd
    {K : Type*} [Field K]
    (f g : MvPolynomial (Fin 2) K) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    Polynomial.resultant (planePolynomialSwapEquiv K f)
      (planePolynomialSwapEquiv K g) ≠ 0 := by
  apply resultant_ne_zero_of_irreducible_not_dvd
  · exact hf.map (planePolynomialSwapEquiv K).toMulEquiv
  · intro hdvd
    apply hndvd
    rcases hdvd with ⟨q, hq⟩
    refine ⟨(planePolynomialSwapEquiv K).symm q, ?_⟩
    apply (planePolynomialSwapEquiv K).injective
    simp [hq]

/-- Elimination remains available when both outer degrees vanish: replacing
the second polynomial by `X * f + g` preserves common zeros and forces degree. -/
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

/-- An irreducible plane polynomial and a polynomial it does not divide have
only finitely many common affine zeros. -/
theorem finite_common_affine_zeros_of_irreducible_not_dvd
    {K : Type*} [Field K]
    (f g : MvPolynomial (Fin 2) K) (hf : Irreducible f) (hndvd : ¬f ∣ g) :
    Set.Finite {p : Fin 2 → K |
      MvPolynomial.eval p f = 0 ∧ MvPolynomial.eval p g = 0} := by
  classical
  have hf₀ : Irreducible (planePolynomialEquiv K f) :=
    hf.map (planePolynomialEquiv K).toMulEquiv
  have hndvd₀ : ¬planePolynomialEquiv K f ∣ planePolynomialEquiv K g := by
    intro hdvd
    apply hndvd
    rcases hdvd with ⟨q, hq⟩
    refine ⟨(planePolynomialEquiv K).symm q, ?_⟩
    apply (planePolynomialEquiv K).injective
    simp [hq]
  obtain ⟨r₁, hr₁0, hr₁⟩ := exists_elimination_polynomial
    (planePolynomialEquiv K f) (planePolynomialEquiv K g) hf₀ hndvd₀
  have hf₁ : Irreducible (planePolynomialSwapEquiv K f) :=
    hf.map (planePolynomialSwapEquiv K).toMulEquiv
  have hndvd₁ : ¬planePolynomialSwapEquiv K f ∣ planePolynomialSwapEquiv K g := by
    intro hdvd
    apply hndvd
    rcases hdvd with ⟨q, hq⟩
    refine ⟨(planePolynomialSwapEquiv K).symm q, ?_⟩
    apply (planePolynomialSwapEquiv K).injective
    simp [hq]
  obtain ⟨r₀, hr₀0, hr₀⟩ := exists_elimination_polynomial
    (planePolynomialSwapEquiv K f) (planePolynomialSwapEquiv K g) hf₁ hndvd₁
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
    · simpa [planePolynomialSwapEquiv_evalEval] using hfp
    · simpa [planePolynomialSwapEquiv_evalEval] using hgp
  · change r₁.eval (p 1) = 0
    apply hr₁ (p 1) (p 0)
    · simpa [planePolynomialEquiv_evalEval] using hfp
    · simpa [planePolynomialEquiv_evalEval] using hgp

/-- The polynomial formed by taking one coordinate, in a fixed coefficient
basis, of every coefficient of `f`. -/
noncomputable def planePolynomialCoeffComponent
    {K R ι : Type*} [Field K] [Field R] [Algebra K R]
    (b : Module.Basis ι K R) (i : ι) (f : MvPolynomial (Fin 2) R) :
    MvPolynomial (Fin 2) K :=
  f.sum fun d c ↦ MvPolynomial.monomial d (b.repr c i)

theorem coeff_planePolynomialCoeffComponent
    {K R ι : Type*} [Field K] [Field R] [Algebra K R]
    (b : Module.Basis ι K R) (i : ι) (f : MvPolynomial (Fin 2) R)
    (d : Fin 2 →₀ ℕ) :
    MvPolynomial.coeff d (planePolynomialCoeffComponent b i f) =
      b.repr (MvPolynomial.coeff d f) i := by
  classical
  rw [planePolynomialCoeffComponent, MvPolynomial.sum_def,
    MvPolynomial.coeff_sum]
  by_cases hd : d ∈ f.support
  · simp [hd]
  · simp [hd, MvPolynomial.notMem_support_iff.mp hd]

/-- Evaluation at a point over the scalar field commutes with taking a
coefficient-basis coordinate. -/
theorem eval_planePolynomialCoeffComponent
    {K R ι : Type*} [Field K] [Field R] [Algebra K R]
    (b : Module.Basis ι K R) (i : ι) (f : MvPolynomial (Fin 2) R)
    (p : Fin 2 → K) :
    MvPolynomial.eval p (planePolynomialCoeffComponent b i f) =
      b.repr (MvPolynomial.eval (fun j ↦ algebraMap K R (p j)) f) i := by
  classical
  rw [planePolynomialCoeffComponent, MvPolynomial.sum_def,
    MvPolynomial.eval_sum, MvPolynomial.eval_eq]
  simp only [MvPolynomial.eval_monomial]
  change (∑ x ∈ f.support, (b.repr (MvPolynomial.coeff x f)) i *
      x.prod fun n e ↦ p n ^ e) =
    b.coord i (∑ x ∈ f.support, MvPolynomial.coeff x f *
      ∏ j ∈ x.support, algebraMap K R (p j) ^ x j)
  rw [map_sum]
  apply Finset.sum_congr rfl
  intro d _hd
  change (b.repr (MvPolynomial.coeff d f)) i *
      (d.prod fun j n ↦ p j ^ n) =
    (b.repr ((MvPolynomial.coeff d f) *
      d.prod fun j n ↦ algebraMap K R (p j) ^ n)) i
  have hprod : d.prod (fun j n ↦ algebraMap K R (p j) ^ n) =
      algebraMap K R (d.prod fun j n ↦ p j ^ n) := by
    classical
    simp only [Finsupp.prod]
    rw [map_prod]
    exact Finset.prod_congr rfl fun j _hj ↦
      (map_pow (algebraMap K R) (p j) (d j)).symm
  rw [hprod, mul_comm (MvPolynomial.coeff d f)]
  rw [← Algebra.smul_def]
  simp [mul_comm]

theorem irreducible_planePolynomial_descends_of_infinite_subfield_zeros
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
  have hcd : MvPolynomial.coeff d f ≠ 0 :=
    MvPolynomial.mem_support_iff.mp hd
  have hrepr : b.repr (MvPolynomial.coeff d f) ≠ 0 := by
    simpa using (b.repr.injective.ne hcd)
  obtain ⟨i, hi⟩ : (b.repr (MvPolynomial.coeff d f)).support.Nonempty :=
    Finsupp.support_nonempty_iff.mpr hrepr
  let g : MvPolynomial (Fin 2) K := planePolynomialCoeffComponent b i f
  have hgcoeff : MvPolynomial.coeff d g ≠ 0 := by
    rw [coeff_planePolynomialCoeffComponent]
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
    rw [eval_planePolynomialCoeffComponent]
    have hv := hvanish p hp
    change MvPolynomial.eval (fun j ↦ algebraMap K ℝ (p j)) f = 0 at hv
    rw [hv]
    simp
  have hcast_inj : Function.Injective
      (fun p : Fin 2 → K ↦ fun j ↦ (p j : ℝ)) := by
    intro p q hpq
    funext j
    exact Subtype.ext (congrFun hpq j)
  have himage :
      ((fun p : Fin 2 → K ↦ fun j ↦ (p j : ℝ)) '' P).Infinite :=
    hP.image hcast_inj.injOn
  have hdiv : f ∣ G := by
    by_contra hndvd
    have hfin := finite_common_affine_zeros_of_irreducible_not_dvd
      f G hf hndvd
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
    rw [coeff_planePolynomialCoeffComponent] at hm
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

/-- Coefficient descent over an arbitrary field extension.  In two variables,
an irreducible polynomial with infinitely many zeros rational over the base
field is a scalar multiple of a polynomial over that base field. -/
theorem irreducible_planePolynomial_descends_of_infinite_field_zeros
    (K R : Type*) [Field K] [Field R] [Algebra K R]
    (f : MvPolynomial (Fin 2) R)
    (hf : Irreducible f)
    (P : Set (Fin 2 → K))
    (hP : P.Infinite)
    (hvanish : ∀ p ∈ P,
      MvPolynomial.eval (fun i => algebraMap K R (p i)) f = 0) :
    ∃ (c : R) (g : MvPolynomial (Fin 2) K),
      c ≠ 0 ∧
      f = MvPolynomial.C c *
        MvPolynomial.map (algebraMap K R) g := by
  classical
  let b := Module.Free.chooseBasis K R
  obtain ⟨d, hd⟩ : f.support.Nonempty :=
    Finsupp.support_nonempty_iff.mpr hf.ne_zero
  have hcd : MvPolynomial.coeff d f ≠ 0 :=
    MvPolynomial.mem_support_iff.mp hd
  have hrepr : b.repr (MvPolynomial.coeff d f) ≠ 0 := by
    simpa using (b.repr.injective.ne hcd)
  obtain ⟨i, hi⟩ : (b.repr (MvPolynomial.coeff d f)).support.Nonempty :=
    Finsupp.support_nonempty_iff.mpr hrepr
  let g : MvPolynomial (Fin 2) K := planePolynomialCoeffComponent b i f
  have hgcoeff : MvPolynomial.coeff d g ≠ 0 := by
    rw [coeff_planePolynomialCoeffComponent]
    exact Finsupp.mem_support_iff.mp hi
  have hg0 : g ≠ 0 := by
    intro hg
    rw [hg, MvPolynomial.coeff_zero] at hgcoeff
    exact hgcoeff rfl
  let G : MvPolynomial (Fin 2) R := MvPolynomial.map (algebraMap K R) g
  have hG0 : G ≠ 0 := by
    exact (MvPolynomial.map_injective (algebraMap K R)
      (algebraMap K R).injective).ne hg0
  have hgvanish : ∀ p ∈ P, MvPolynomial.eval p g = 0 := by
    intro p hp
    rw [eval_planePolynomialCoeffComponent]
    rw [hvanish p hp]
    simp
  have hcast_inj : Function.Injective
      (fun p : Fin 2 → K ↦ fun j ↦ algebraMap K R (p j)) := by
    intro p q hpq
    funext j
    exact (algebraMap K R).injective (congrFun hpq j)
  have himage :
      ((fun p : Fin 2 → K ↦ fun j ↦ algebraMap K R (p j)) '' P).Infinite :=
    hP.image hcast_inj.injOn
  have hdiv : f ∣ G := by
    by_contra hndvd
    have hfin := finite_common_affine_zeros_of_irreducible_not_dvd
      f G hf hndvd
    apply himage
    apply hfin.subset
    rintro q ⟨p, hp, rfl⟩
    refine ⟨hvanish p hp, ?_⟩
    rw [MvPolynomial.eval_map]
    have heq : MvPolynomial.eval₂ (algebraMap K R)
        (fun j ↦ algebraMap K R (p j)) g =
        algebraMap K R (MvPolynomial.eval p g) := by
      symm
      exact MvPolynomial.map_eval₂Hom (RingHom.id K) p
        (algebraMap K R) g
    rw [heq, hgvanish p hp, map_zero]
  rcases hdiv with ⟨q, hq⟩
  have hgsupp : g.support ⊆ f.support := by
    intro m hm
    rw [MvPolynomial.mem_support_iff] at hm ⊢
    rw [coeff_planePolynomialCoeffComponent] at hm
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
  rw [← show G = MvPolynomial.map (algebraMap K R) g from rfl, hGa,
    ← mul_assoc, ← MvPolynomial.C_mul]
  simp [ha]

private noncomputable def inverseSimilarityVars (a b : ℂ) :
    Fin 2 → MvPolynomial (Fin 2) ℝ := ![
  MvPolynomial.C a.re + MvPolynomial.C (b - a).re * MvPolynomial.X 0 -
    MvPolynomial.C (b - a).im * MvPolynomial.X 1,
  MvPolynomial.C a.im + MvPolynomial.C (b - a).im * MvPolynomial.X 0 +
    MvPolynomial.C (b - a).re * MvPolynomial.X 1]

private noncomputable def normalizeSimilarityVars (a b : ℂ) :
    Fin 2 → MvPolynomial (Fin 2) ℝ :=
  let d := b - a
  let n := Complex.normSq d
  ![
    MvPolynomial.C ((-a.re * d.re - a.im * d.im) / n) +
      MvPolynomial.C (d.re / n) * MvPolynomial.X 0 +
      MvPolynomial.C (d.im / n) * MvPolynomial.X 1,
    MvPolynomial.C ((a.re * d.im - a.im * d.re) / n) -
      MvPolynomial.C (d.im / n) * MvPolynomial.X 0 +
      MvPolynomial.C (d.re / n) * MvPolynomial.X 1]

private lemma normSq_sub_ne_zero {a b : ℂ} (hab : a ≠ b) :
    Complex.normSq (b - a) ≠ 0 := by
  intro hn
  have hba : b - a = 0 := _root_.Complex.normSq_eq_zero.mp hn
  exact hab (sub_eq_zero.mp hba).symm

private lemma bind_inverse_normalize (a b : ℂ) (hab : a ≠ b) (i : Fin 2) :
    MvPolynomial.bind₁ (inverseSimilarityVars a b)
      (normalizeSimilarityVars a b i) = MvPolynomial.X i := by
  have hn := normSq_sub_ne_zero hab
  apply MvPolynomial.funext
  intro p
  fin_cases i <;>
    simp [MvPolynomial.eval,
      inverseSimilarityVars, normalizeSimilarityVars] <;>
    field_simp [hn] <;>
    simp only [_root_.Complex.normSq_apply, Complex.sub_re, Complex.sub_im] <;>
    ring

private lemma bind_normalize_inverse (a b : ℂ) (hab : a ≠ b) (i : Fin 2) :
    MvPolynomial.bind₁ (normalizeSimilarityVars a b)
      (inverseSimilarityVars a b i) = MvPolynomial.X i := by
  have hn := normSq_sub_ne_zero hab
  apply MvPolynomial.funext
  intro p
  fin_cases i <;>
    simp [MvPolynomial.eval,
      inverseSimilarityVars, normalizeSimilarityVars] <;>
    field_simp [hn] <;>
    simp only [_root_.Complex.normSq_apply, Complex.sub_re, Complex.sub_im] <;>
    ring

private noncomputable def similarityPolynomialEquiv (a b : ℂ) (hab : a ≠ b) :
    MvPolynomial (Fin 2) ℝ ≃ₐ[ℝ] MvPolynomial (Fin 2) ℝ := by
  apply AlgEquiv.ofAlgHom
    (MvPolynomial.bind₁ (inverseSimilarityVars a b))
    (MvPolynomial.bind₁ (normalizeSimilarityVars a b))
  · apply MvPolynomial.algHom_ext
    intro i
    rw [AlgHom.comp_apply, MvPolynomial.bind₁_bind₁,
      MvPolynomial.bind₁_X_right, bind_inverse_normalize a b hab]
    rfl
  · apply MvPolynomial.algHom_ext
    intro i
    rw [AlgHom.comp_apply, MvPolynomial.bind₁_bind₁,
      MvPolynomial.bind₁_X_right, bind_normalize_inverse a b hab]
    rfl

private lemma eval_inverseSimilarityVars_similarityNormalize
    (a b z : ℂ) (hab : a ≠ b) (i : Fin 2) :
    MvPolynomial.eval ![(similarityNormalize a b z).re,
      (similarityNormalize a b z).im] (inverseSimilarityVars a b i) =
      ![z.re, z.im] i := by
  have hn := normSq_sub_ne_zero hab
  fin_cases i <;>
    simp [inverseSimilarityVars, similarityNormalize, Complex.div_re,
      Complex.div_im] <;>
    field_simp [hn] <;>
    simp only [_root_.Complex.normSq_apply, Complex.sub_re, Complex.sub_im] <;>
    ring

theorem exists_irreducible_planePolynomial_vanishing_on_similarityNormalize_image
    {u : Set ℂ} {a b : ℂ}
    (hab : a ≠ b)
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hu : ∀ z ∈ u,
      MvPolynomial.eval ![z.re, z.im] f = 0) :
    ∃ g : MvPolynomial (Fin 2) ℝ,
      Irreducible g ∧
      ∀ w ∈ similarityNormalize a b '' u,
        MvPolynomial.eval ![w.re, w.im] g = 0 := by
  let e := similarityPolynomialEquiv a b hab
  refine ⟨e f, hf.map e.toMulEquiv, ?_⟩
  rintro w ⟨z, hz, rfl⟩
  change MvPolynomial.eval
      ![(similarityNormalize a b z).re, (similarityNormalize a b z).im]
      (MvPolynomial.bind₁ (inverseSimilarityVars a b) f) = 0
  change MvPolynomial.eval₂Hom (RingHom.id ℝ)
      ![(similarityNormalize a b z).re, (similarityNormalize a b z).im]
      (MvPolynomial.bind₁ (inverseSimilarityVars a b) f) = 0
  rw [MvPolynomial.eval₂Hom_bind₁]
  have hvars : (λ i ↦ MvPolynomial.eval₂Hom (RingHom.id ℝ)
      ![(similarityNormalize a b z).re, (similarityNormalize a b z).im]
      (inverseSimilarityVars a b i)) = ![z.re, z.im] := by
    funext i
    exact eval_inverseSimilarityVars_similarityNormalize a b z hab i
  rw [hvars]
  exact hu z hz

theorem irreducible_planePolynomial_descends_of_infinite_quadraticPlane_zeros
    (k : ℚ) (hk : 0 < k)
    (P : Set (ℚ × ℚ))
    (hInfinite : (quadraticPlane k '' P).Infinite)
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hvanish : ∀ z ∈ quadraticPlane k '' P,
      MvPolynomial.eval ![z.re, z.im] f = 0) :
    let K := IntermediateField.adjoin ℚ {Real.sqrt (k : ℝ)}
    ∃ (c : ℝ) (g : MvPolynomial (Fin 2) K),
      c ≠ 0 ∧
      f = MvPolynomial.C c *
        MvPolynomial.map (algebraMap K ℝ) g := by
  let K := IntermediateField.adjoin ℚ {Real.sqrt (k : ℝ)}
  let sqrtK : K :=
    ⟨Real.sqrt (k : ℝ), IntermediateField.subset_adjoin ℚ _ (by simp)⟩
  let liftPoint : ℚ × ℚ → Fin 2 → K := fun p ↦
    ![algebraMap ℚ K p.1, algebraMap ℚ K p.2 * sqrtK]
  let Q : Set (Fin 2 → K) := liftPoint '' P
  have hQ : Q.Infinite := by
    intro hQfin
    apply hInfinite
    apply (hQfin.image fun q : Fin 2 → K ↦
      ((q 0 : ℝ) : ℂ) + ((q 1 : ℝ) : ℂ) * Complex.I).subset
    rintro z ⟨p, hp, rfl⟩
    refine ⟨liftPoint p, ⟨p, hp, rfl⟩, ?_⟩
    simp [liftPoint, sqrtK, quadraticPlane]
  apply irreducible_planePolynomial_descends_of_infinite_subfield_zeros
    K f hf Q hQ
  rintro q ⟨p, hp, rfl⟩
  have hcoords : (fun i ↦ ((liftPoint p i : K) : ℝ)) =
      ![(quadraticPlane k p).re, (quadraticPlane k p).im] := by
    funext i
    fin_cases i <;> simp [liftPoint, sqrtK, quadraticPlane]
  rw [hcoords]
  exact hvanish (quadraticPlane k p) ⟨p, hp, rfl⟩

theorem irreducible_complexification_of_infinite_real_affine_zeros
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (P : Set (Fin 2 → ℝ))
    (hP : P.Infinite)
    (hvanish : ∀ p ∈ P, MvPolynomial.eval p f = 0) :
    Irreducible (MvPolynomial.map Complex.ofRealHom f) := by
  classical
  let F : MvPolynomial (Fin 2) ℂ := MvPolynomial.map Complex.ofRealHom f
  have hF0 : F ≠ 0 :=
    (MvPolynomial.map_injective Complex.ofRealHom Complex.ofReal_injective).ne hf.ne_zero
  let s := UniqueFactorizationMonoid.factors F
  have hsassoc : Associated s.prod F :=
    UniqueFactorizationMonoid.factors_prod hF0
  let Z : MvPolynomial (Fin 2) ℂ → Set (Fin 2 → ℝ) := fun q ↦
    {p | p ∈ P ∧ MvPolynomial.eval (fun i ↦ (p i : ℂ)) q = 0}
  have hfinite_union :
      (∀ q ∈ s, (Z q).Finite) →
      ({p | ∃ q ∈ s, p ∈ Z q} : Set (Fin 2 → ℝ)).Finite := by
    intro h
    have hu := Set.Finite.biUnion s.toFinset.finite_toSet
      (fun q hq ↦ h q (Multiset.mem_toFinset.mp hq))
    convert hu using 1
    ext p
    simp
  have hPsubset : P ⊆ {p | ∃ q ∈ s, p ∈ Z q} := by
    intro p hp
    have hvF : MvPolynomial.eval (fun i ↦ (p i : ℂ)) F = 0 := by
      dsimp [F]
      rw [MvPolynomial.eval_map]
      rw [show MvPolynomial.eval₂ Complex.ofRealHom (fun i ↦ (p i : ℂ)) f =
          Complex.ofRealHom (MvPolynomial.eval p f) by
        symm
        exact MvPolynomial.map_eval₂Hom (RingHom.id ℝ) p Complex.ofRealHom f]
      rw [hvanish p hp, map_zero]
    rcases hsassoc with ⟨u, hu⟩
    have hmul :
        MvPolynomial.eval (fun i ↦ (p i : ℂ)) s.prod *
          MvPolynomial.eval (fun i ↦ (p i : ℂ)) (u : MvPolynomial (Fin 2) ℂ) = 0 := by
      rw [← map_mul]
      rw [hu]
      exact hvF
    have hu_eval : IsUnit
        (MvPolynomial.eval (fun i ↦ (p i : ℂ))
          (u : MvPolynomial (Fin 2) ℂ)) :=
      IsUnit.map (MvPolynomial.eval₂Hom (RingHom.id ℂ)
        (fun i ↦ (p i : ℂ))) u.isUnit
    have hprod : MvPolynomial.eval (fun i ↦ (p i : ℂ)) s.prod = 0 :=
      (mul_eq_zero.mp hmul).resolve_right (isUnit_iff_ne_zero.mp hu_eval)
    change (MvPolynomial.eval₂Hom (RingHom.id ℂ)
      (fun i ↦ (p i : ℂ))) s.prod = 0 at hprod
    rw [map_multiset_prod] at hprod
    have hmem : 0 ∈ s.map
        (MvPolynomial.eval (fun i ↦ (p i : ℂ))) :=
      Multiset.prod_eq_zero_iff.mp hprod
    rcases Multiset.mem_map.mp hmem with ⟨q, hqs, hq0⟩
    exact ⟨q, hqs, hp, hq0⟩
  have hexists : ∃ q ∈ s, (Z q).Infinite := by
    by_contra h
    have hall : ∀ q ∈ s, (Z q).Finite := by
      intro q hqs
      exact Set.not_infinite.mp (fun hinf ↦ h ⟨q, hqs, hinf⟩)
    exact hP ((hfinite_union hall).subset hPsubset)
  obtain ⟨q, hqs, hZq⟩ := hexists
  have hqirr : Irreducible q :=
    UniqueFactorizationMonoid.irreducible_of_factor q hqs
  obtain ⟨c, g, hc, hq⟩ :=
    irreducible_planePolynomial_descends_of_infinite_field_zeros
      ℝ ℂ q hqirr (Z q) hZq (fun p hp ↦ hp.2)
  have hq_dvd_F : q ∣ F :=
    UniqueFactorizationMonoid.dvd_of_mem_factors hqs
  have hcommon : ∀ p ∈ Z q,
      MvPolynomial.eval p f = 0 ∧ MvPolynomial.eval p g = 0 := by
    intro p hp
    refine ⟨hvanish p hp.1, ?_⟩
    · have hpq := hp.2
      rw [hq, MvPolynomial.eval_mul, MvPolynomial.eval_C,
        MvPolynomial.eval_map] at hpq
      have heval : MvPolynomial.eval₂ Complex.ofRealHom
          (fun i ↦ (p i : ℂ)) g =
          Complex.ofRealHom (MvPolynomial.eval p g) := by
        symm
        exact MvPolynomial.map_eval₂Hom (RingHom.id ℝ) p Complex.ofRealHom g
      change c * MvPolynomial.eval₂ Complex.ofRealHom
        (fun i ↦ (p i : ℂ)) g = 0 at hpq
      rw [heval] at hpq
      exact Complex.ofReal_injective
        ((mul_eq_zero.mp hpq).resolve_left hc)
  have hfg : f ∣ g := by
    by_contra hndvd
    have hfin := finite_common_affine_zeros_of_irreducible_not_dvd
      f g hf hndvd
    exact hZq (hfin.subset hcommon)
  have hF_dvd_q : F ∣ q := by
    rcases hfg with ⟨a, ha⟩
    refine ⟨MvPolynomial.C c * MvPolynomial.map Complex.ofRealHom a, ?_⟩
    dsimp [F]
    rw [hq, ha, map_mul]
    rw [show algebraMap ℝ ℂ = Complex.ofRealHom by rfl]
    ring
  have hassoc : Associated q F :=
    dvd_dvd_iff_associated.mp ⟨hq_dvd_F, hF_dvd_q⟩
  exact hassoc.irreducible_iff.mp hqirr

/-- Total-degree homogenization of a polynomial in two variables.  The first
two variables are the affine coordinates and the last variable is the
homogenizing coordinate. -/
noncomputable def planePolynomialHomogenize {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) : MvPolynomial (Fin 3) K :=
  f.sum fun m c => MvPolynomial.monomial
    (Finsupp.equivFunOnFinite.symm
      ![m 0, m 1, f.totalDegree - m.degree]) c

/-- Restriction of a trivariate polynomial to the affine chart `Z = 1`. -/
noncomputable def planePolynomialDehomogenize {K : Type*} [Field K] :
    MvPolynomial (Fin 3) K →+* MvPolynomial (Fin 2) K :=
  MvPolynomial.eval₂Hom MvPolynomial.C
    ![MvPolynomial.X 0, MvPolynomial.X 1, 1]

/-- Homogenization followed by restriction to `Z = 1` is the identity. -/
lemma planePolynomialDehomogenize_homogenize
    {K : Type*} [Field K] (f : MvPolynomial (Fin 2) K) :
    planePolynomialDehomogenize (planePolynomialHomogenize f) = f := by
  classical
  conv_rhs => rw [← f.support_sum_monomial_coeff]
  unfold planePolynomialHomogenize planePolynomialDehomogenize
  simp only [Finsupp.sum, map_sum]
  apply Finset.sum_congr rfl
  intro m hm
  simp [Finsupp.prod_fintype, Fin.prod_univ_three, Fin.prod_univ_two,
    MvPolynomial.monomial_eq]
  rfl

lemma planePolynomialHomogenize_ne_zero
    {K : Type*} [Field K] {f : MvPolynomial (Fin 2) K} (hf : f ≠ 0) :
    planePolynomialHomogenize f ≠ 0 := by
  intro h
  have h' := congrArg planePolynomialDehomogenize h
  rw [planePolynomialDehomogenize_homogenize, map_zero] at h'
  exact hf h'

lemma planePolynomialHomogenize_not_isUnit
    {K : Type*} [Field K] {f : MvPolynomial (Fin 2) K} (hf : ¬ IsUnit f) :
    ¬ IsUnit (planePolynomialHomogenize f) := by
  intro h
  apply hf
  rw [← planePolynomialDehomogenize_homogenize f]
  exact h.map planePolynomialDehomogenize

lemma planePolynomialHomogenize_isHomogeneous
    {K : Type*} [Field K] (f : MvPolynomial (Fin 2) K) :
    (planePolynomialHomogenize f).IsHomogeneous f.totalDegree := by
  classical
  unfold planePolynomialHomogenize
  apply MvPolynomial.IsHomogeneous.sum
  intro m hm
  apply MvPolynomial.isHomogeneous_monomial
  let v : Fin 3 → ℕ := ![m 0, m 1, f.totalDegree - m.degree]
  have hv (i : Fin 3) :
      (Finsupp.equivFunOnFinite.symm v) i = v i := by
    exact congrFun (Finsupp.equivFunOnFinite.apply_symm_apply v) i
  rw [Finsupp.degree_eq_sum, Fin.sum_univ_three]
  rw [hv 0, hv 1, hv 2]
  change m 0 + m 1 + (f.totalDegree - m.degree) = f.totalDegree
  have hmdeg : m.degree = m 0 + m 1 := by
    rw [Finsupp.degree_eq_sum, Fin.sum_univ_two]
  have hle : m.degree ≤ f.totalDegree :=
    MvPolynomial.le_totalDegree hm
  omega

lemma eval_planePolynomialHomogenize_affine
    {K : Type*} [Field K] (f : MvPolynomial (Fin 2) K)
    (p : Fin 2 → K) :
    MvPolynomial.eval ![p 0, p 1, 1]
      (planePolynomialHomogenize f) = MvPolynomial.eval p f := by
  classical
  calc
    MvPolynomial.eval ![p 0, p 1, 1] (planePolynomialHomogenize f) =
        MvPolynomial.eval p
          (planePolynomialDehomogenize (planePolynomialHomogenize f)) := by
      unfold planePolynomialDehomogenize
      change MvPolynomial.eval ![p 0, p 1, 1]
          (planePolynomialHomogenize f) =
        MvPolynomial.eval p
          (MvPolynomial.eval₂ MvPolynomial.C
            ![MvPolynomial.X 0, MvPolynomial.X 1, 1]
            (planePolynomialHomogenize f))
      rw [MvPolynomial.eval_eval₂]
      rw [← MvPolynomial.eval₂_id]
      have hc : (MvPolynomial.eval p).comp MvPolynomial.C = RingHom.id K := by
        ext x
        simp
      rw [hc]
      apply MvPolynomial.eval₂_congr
      intro i c hi hcoeff
      fin_cases i <;> simp [MvPolynomial.eval]
    _ = MvPolynomial.eval p f := by
      rw [planePolynomialDehomogenize_homogenize]

noncomputable def scaleDegree {K σ : Type*} [Field K] :
    MvPolynomial σ K →+* Polynomial (MvPolynomial σ K) :=
  MvPolynomial.eval₂Hom
    ((Polynomial.C : MvPolynomial σ K →+* Polynomial (MvPolynomial σ K)).comp
      MvPolynomial.C)
    (fun i ↦ Polynomial.C (MvPolynomial.X i) * Polynomial.X)


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


noncomputable def dehom {K : Type*} [Field K] :
    MvPolynomial (Fin 3) K →+* MvPolynomial (Fin 2) K :=
  MvPolynomial.eval₂Hom MvPolynomial.C
    ![MvPolynomial.X 0, MvPolynomial.X 1, 1]

noncomputable def homAt {K : Type*} [Field K] (n : ℕ)
    (f : MvPolynomial (Fin 2) K) : MvPolynomial (Fin 3) K :=
  f.sum fun m c => MvPolynomial.monomial
    (Finsupp.equivFunOnFinite.symm ![m 0, m 1, n - m.degree]) c

lemma dehom_homAt_totalDegree {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) : dehom (homAt f.totalDegree f) = f := by
  classical
  conv_rhs => rw [← f.support_sum_monomial_coeff]
  unfold homAt dehom
  simp only [Finsupp.sum, map_sum]
  apply Finset.sum_congr rfl
  intro m hm
  simp [Finsupp.prod_fintype, Fin.prod_univ_three, Fin.prod_univ_two,
    MvPolynomial.monomial_eq]
  rfl

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

lemma X_two_not_dvd_homAt_totalDegree {K : Type*} [Field K]
    {f : MvPolynomial (Fin 2) K} (hf : f ≠ 0) :
    ¬ MvPolynomial.X 2 ∣ homAt f.totalDegree f := by
  classical
  have hsupp : f.support.Nonempty := MvPolynomial.support_nonempty.mpr hf
  obtain ⟨m, hm, hmtop⟩ :=
    Finset.exists_mem_eq_sup f.support hsupp (fun a ↦ a.degree)
  have hdeg : m.degree = f.totalDegree := by
    rw [MvPolynomial.totalDegree]
    exact hmtop.symm
  intro hdvd
  obtain ⟨q, hq⟩ := hdvd
  let v : Fin 3 →₀ ℕ :=
    Finsupp.equivFunOnFinite.symm ![m 0, m 1, 0]
  have hv2 : v 2 = 0 := by simp [v]
  have hcoeff_ne : MvPolynomial.coeff v (homAt f.totalDegree f) ≠ 0 := by
    rw [coeff_homAt_top f m hm hdeg]
    exact MvPolynomial.mem_support_iff.mp hm
  apply hcoeff_ne
  rw [hq, MvPolynomial.coeff_X_mul']
  simp [Finsupp.mem_support_iff, hv2]

theorem homAt_irreducible {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) (hf : Irreducible f) :
    Irreducible (homAt f.totalDegree f) := by
  rw [irreducible_iff]
  constructor
  · intro hu
    apply hf.not_isUnit
    rw [← dehom_homAt_totalDegree f]
    exact hu.map dehom
  · intro a b hab
    have hp0 : homAt f.totalDegree f ≠ 0 := by
      intro h
      have := congrArg dehom h
      rw [dehom_homAt_totalDegree, map_zero] at this
      exact hf.ne_zero this
    have ha : a ≠ 0 := fun ha ↦ hp0 (by rw [hab, ha, zero_mul])
    have hb : b ≠ 0 := fun hb ↦ hp0 (by rw [hab, hb, mul_zero])
    have hhom : (homAt f.totalDegree f).IsHomogeneous f.totalDegree := by
      classical
      unfold homAt
      apply MvPolynomial.IsHomogeneous.sum
      intro m hm
      apply MvPolynomial.isHomogeneous_monomial
      let v : Fin 3 → ℕ := ![m 0, m 1, f.totalDegree - m.degree]
      have hv (i : Fin 3) : (Finsupp.equivFunOnFinite.symm v) i = v i :=
        congrFun (Finsupp.equivFunOnFinite.apply_symm_apply v) i
      rw [Finsupp.degree_eq_sum, Fin.sum_univ_three, hv 0, hv 1, hv 2]
      change m 0 + m 1 + (f.totalDegree - m.degree) = f.totalDegree
      have hmdeg : m.degree = m 0 + m 1 := by
        rw [Finsupp.degree_eq_sum, Fin.sum_univ_two]
      have hle : m.degree ≤ f.totalDegree := MvPolynomial.le_totalDegree hm
      omega
    obtain ⟨haHom, hbHom⟩ := homogeneous_factors hhom ha hb hab
    have hdehom : f = dehom a * dehom b := by
      have := congrArg dehom hab
      rw [dehom_homAt_totalDegree, map_mul] at this
      exact this
    rcases (irreducible_iff.mp hf).2 hdehom with hua | hub
    · rcases isUnit_or_X_dvd_of_homogeneous_dehom_isUnit haHom hua with hua' | hXa
      · exact Or.inl hua'
      · exfalso
        apply X_two_not_dvd_homAt_totalDegree hf.ne_zero
        rw [hab]
        exact dvd_mul_of_dvd_left hXa b
    · rcases isUnit_or_X_dvd_of_homogeneous_dehom_isUnit hbHom hub with hub' | hXb
      · exact Or.inr hub'
      · exfalso
        apply X_two_not_dvd_homAt_totalDegree hf.ne_zero
        rw [hab]
        exact dvd_mul_of_dvd_right hXb a


theorem planePolynomialHomogenize_spec
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K)
    (hf : Irreducible f) :
    Irreducible (planePolynomialHomogenize f) ∧
    (planePolynomialHomogenize f).IsHomogeneous f.totalDegree ∧
    ∀ p : Fin 2 → K,
      MvPolynomial.eval ![p 0, p 1, 1]
        (planePolynomialHomogenize f) =
      MvPolynomial.eval p f := by
  refine ⟨?_, planePolynomialHomogenize_isHomogeneous f,
    eval_planePolynomialHomogenize_affine f⟩
  change Irreducible (homAt f.totalDegree f)
  exact homAt_irreducible f hf

lemma planePolynomialHomogenize_map
    {K L : Type*} [Field K] [Field L]
    (φ : K →+* L) (hφ : Function.Injective φ)
    (f : MvPolynomial (Fin 2) K) :
    MvPolynomial.map φ (planePolynomialHomogenize f) =
      planePolynomialHomogenize (MvPolynomial.map φ f) := by
  classical
  have hsupport : (MvPolynomial.map φ f).support = f.support :=
    MvPolynomial.support_map_of_injective f hφ
  have hdegree : (MvPolynomial.map φ f).totalDegree = f.totalDegree := by
    unfold MvPolynomial.totalDegree
    rw [hsupport]
  have hmapRange : MvPolynomial.map φ f =
      Finsupp.mapRange φ φ.map_zero f := by
    apply MvPolynomial.ext
    intro m
    exact MvPolynomial.coeff_map φ f m
  unfold planePolynomialHomogenize
  rw [hdegree, hmapRange]
  rw [Finsupp.sum_mapRange_index]
  · simp only [Finsupp.sum, map_sum, MvPolynomial.map_monomial]
  · intro m
    exact MvPolynomial.monomial_zero

theorem exists_geometrically_irreducible_projective_equation_of_infinite_quadraticPlane_zeros
    (k : ℚ) (hk : 0 < k)
    (P : Set (ℚ × ℚ))
    (hInfinite : (quadraticPlane k '' P).Infinite)
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hvanish : ∀ z ∈ quadraticPlane k '' P,
      MvPolynomial.eval ![z.re, z.im] f = 0) :
    let K := IntermediateField.adjoin ℚ {Real.sqrt (k : ℝ)}
    ∃ (c : ℝ) (g : MvPolynomial (Fin 2) K),
      c ≠ 0 ∧
      f = MvPolynomial.C c *
        MvPolynomial.map (algebraMap K ℝ) g ∧
      Irreducible
        (MvPolynomial.map (algebraMap K ℂ)
          (planePolynomialHomogenize g)) := by
  let K := IntermediateField.adjoin ℚ {Real.sqrt (k : ℝ)}
  let Q : Set (Fin 2 → ℝ) :=
    (fun z : ℂ ↦ ![z.re, z.im]) '' (quadraticPlane k '' P)
  have hcoords : Function.Injective (fun z : ℂ ↦ ![z.re, z.im]) := by
    intro z w h
    apply Complex.ext
    · simpa using congrFun h 0
    · simpa using congrFun h 1
  have hQ : Q.Infinite := hInfinite.image hcoords.injOn
  have hQvanish : ∀ p ∈ Q, MvPolynomial.eval p f = 0 := by
    rintro p ⟨z, hz, rfl⟩
    exact hvanish z hz
  have hfℂ : Irreducible (MvPolynomial.map Complex.ofRealHom f) :=
    irreducible_complexification_of_infinite_real_affine_zeros
      f hf Q hQ hQvanish
  obtain ⟨c, g, hc, hfg⟩ :=
    irreducible_planePolynomial_descends_of_infinite_quadraticPlane_zeros
      k hk P hInfinite f hf hvanish
  refine ⟨c, g, hc, hfg, ?_⟩
  have hcomp : Complex.ofRealHom.comp (algebraMap K ℝ) =
      algebraMap K ℂ := by
    rfl
  have hmap : MvPolynomial.map Complex.ofRealHom f =
      MvPolynomial.C (Complex.ofReal c) *
        MvPolynomial.map (algebraMap K ℂ) g := by
    rw [hfg, map_mul, MvPolynomial.map_C, MvPolynomial.map_map, hcomp]
    simp only [Complex.ofRealHom_eq_coe]
    rfl
  have hcℂ : IsUnit (Complex.ofReal c) :=
    isUnit_iff_ne_zero.mpr (Complex.ofReal_ne_zero.mpr hc)
  have hCunit : IsUnit
      (MvPolynomial.C (Complex.ofReal c) : MvPolynomial (Fin 2) ℂ) :=
    hcℂ.map (MvPolynomial.C : ℂ →+* MvPolynomial (Fin 2) ℂ)
  have hassoc : Associated (MvPolynomial.map Complex.ofRealHom f)
      (MvPolynomial.map (algebraMap K ℂ) g) := by
    rw [hmap]
    exact associated_unit_mul_left _ _ hCunit
  have hgℂ : Irreducible (MvPolynomial.map (algebraMap K ℂ) g) :=
    hassoc.irreducible_iff.mp hfℂ
  rw [planePolynomialHomogenize_map (algebraMap K ℂ)
    (algebraMap K ℂ).injective g]
  exact (planePolynomialHomogenize_spec
    (MvPolynomial.map (algebraMap K ℂ) g) hgℂ).1

theorem planePolynomialHomogenize_span_isPrime
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K)
    (hf : Irreducible f) :
    (Ideal.span
      ({planePolynomialHomogenize f} :
        Set (MvPolynomial (Fin 3) K))).IsPrime := by
  have hirr : Irreducible (planePolynomialHomogenize f) :=
    (planePolynomialHomogenize_spec f hf).1
  have hp : Prime (planePolynomialHomogenize f) := hirr.prime
  exact (Ideal.span_singleton_prime hp.ne_zero).2 hp

attribute [local instance] MvPolynomial.gradedAlgebra

theorem planePolynomialHomogenize_span_isHomogeneous
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) :
    (Ideal.span
      ({planePolynomialHomogenize f} :
        Set (MvPolynomial (Fin 3) K))).IsHomogeneous
      (MvPolynomial.homogeneousSubmodule (Fin 3) K) := by
  apply Ideal.homogeneous_span
  intro p hp
  rw [Set.mem_singleton_iff] at hp
  subst p
  exact ⟨f.totalDegree, planePolynomialHomogenize_isHomogeneous f⟩

noncomputable def rationalRadiusInversion (a : ℂ) (r : ℚ) (z : ℂ) : ℂ :=
  a + ((r : ℂ) ^ 2) / (starRingEnd ℂ) (z - a)

private lemma rationalRadiusInversion_sub (a : ℂ) (r : ℚ) (x y : ℂ)
    (hxa : x ≠ a) (hya : y ≠ a) :
    rationalRadiusInversion a r x - rationalRadiusInversion a r y =
      -((r : ℂ) ^ 2) * (starRingEnd ℂ) (x - y) /
        ((starRingEnd ℂ) (x - a) * (starRingEnd ℂ) (y - a)) := by
  have hxstar : (starRingEnd ℂ) (x - a) ≠ 0 := by
    intro h
    rw [map_sub, sub_eq_zero] at h
    exact hxa ((starRingEnd ℂ).injective h)
  have hystar : (starRingEnd ℂ) (y - a) ≠ 0 := by
    intro h
    rw [map_sub, sub_eq_zero] at h
    exact hya ((starRingEnd ℂ).injective h)
  unfold rationalRadiusInversion
  field_simp [hxstar, hystar]
  simp only [map_sub]
  ring

private lemma abs_rationalRadiusInversion_sub
    (a : ℂ) (r : ℚ) (x y : ℂ)
    (hxa : x ≠ a) (hya : y ≠ a)
    {q sx sy : ℚ}
    (hq : Complex.abs (x - y) = (q : ℝ))
    (hsx : Complex.abs (x - a) = (sx : ℝ))
    (hsy : Complex.abs (y - a) = (sy : ℝ)) :
    Complex.abs
        (rationalRadiusInversion a r x - rationalRadiusInversion a r y) =
      (((r ^ 2 * q) / (sx * sy) : ℚ) : ℝ) := by
  have hsxposR : 0 < (sx : ℝ) := by
    rw [← hsx]
    exact lt_of_le_of_ne (Complex.abs_nonneg _)
      (Ne.symm <| Complex.abs_eq_zero_iff.not.mpr (sub_ne_zero.mpr hxa))
  have hsyposR : 0 < (sy : ℝ) := by
    rw [← hsy]
    exact lt_of_le_of_ne (Complex.abs_nonneg _)
      (Ne.symm <| Complex.abs_eq_zero_iff.not.mpr (sub_ne_zero.mpr hya))
  have hqnonnegR : 0 ≤ (q : ℝ) := by
    rw [← hq]
    exact Complex.abs_nonneg _
  rw [Rat.cast_div, Rat.cast_mul, Rat.cast_mul, Rat.cast_pow]
  apply euclidean_abs_eq_of_sq_eq
    (div_nonneg (mul_nonneg (sq_nonneg _) hqnonnegR)
      (mul_nonneg hsxposR.le hsyposR.le))
  rw [rationalRadiusInversion_sub a r x y hxa hya,
    _root_.Complex.normSq_div, _root_.Complex.normSq_mul,
    _root_.Complex.normSq_mul, _root_.Complex.normSq_neg,
    _root_.Complex.normSq_conj, _root_.Complex.normSq_conj,
    _root_.Complex.normSq_conj]
  rw [map_pow, _root_.Complex.normSq_ratCast]
  have hnum : _root_.Complex.normSq (x - y) = (q : ℝ) ^ 2 := by
    rw [← Complex.abs_sq, hq]
  have hxden : _root_.Complex.normSq (x - a) = (sx : ℝ) ^ 2 := by
    rw [← Complex.abs_sq, hsx]
  have hyden : _root_.Complex.normSq (y - a) = (sy : ℝ) ^ 2 := by
    rw [← Complex.abs_sq, hsy]
  rw [hnum, hxden, hyden]
  field_simp

theorem euclideanPairwiseRationalDistances_rationalRadiusInversion
    {u : Set ℂ} (hu : EuclideanPairwiseRationalDistances u)
    {a : ℂ} (ha : a ∈ u)
    (r : ℚ) (hr : 0 < r) :
    EuclideanPairwiseRationalDistances
      (rationalRadiusInversion a r '' (u \ {a})) := by
  intro z w hz hw
  rcases hz with ⟨x, hx, rfl⟩
  rcases hw with ⟨y, hy, rfl⟩
  have hxu : x ∈ u := hx.1
  have hyu : y ∈ u := hy.1
  have hxa : x ≠ a := by simpa using hx.2
  have hya : y ≠ a := by simpa using hy.2
  rcases hu hxu hyu with ⟨q, hq⟩
  rcases hu hxu ha with ⟨sx, hsx⟩
  rcases hu hyu ha with ⟨sy, hsy⟩
  refine ⟨r ^ 2 * q / (sx * sy), ?_⟩
  exact abs_rationalRadiusInversion_sub a r x y hxa hya hq hsx hsy

/-- The affine equation obtained by pulling a plane polynomial back along
unit-circle inversion.  Homogenization clears the common denominator. -/
noncomputable def planePolynomialUnitCircleInversion
    {K : Type*} [Field K] (f : MvPolynomial (Fin 2) K) :
    MvPolynomial (Fin 2) K :=
  MvPolynomial.eval₂Hom MvPolynomial.C
    ![MvPolynomial.X 0, MvPolynomial.X 1,
      MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2]
    (planePolynomialHomogenize f)

theorem planePolynomialUnitCircleInversion_eval
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) (x y : K)
    (hQ : x ^ 2 + y ^ 2 ≠ 0) :
    MvPolynomial.eval ![x, y]
        (planePolynomialUnitCircleInversion f) =
      (x ^ 2 + y ^ 2) ^ f.totalDegree *
        MvPolynomial.eval
          ![x / (x ^ 2 + y ^ 2), y / (x ^ 2 + y ^ 2)] f := by
  classical
  let Q := x ^ 2 + y ^ 2
  have hQ' : Q ≠ 0 := hQ
  unfold planePolynomialUnitCircleInversion planePolynomialHomogenize
  change MvPolynomial.eval ![x, y]
      (MvPolynomial.eval₂ MvPolynomial.C
        ![MvPolynomial.X 0, MvPolynomial.X 1,
          MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2]
        (f.sum fun m c => MvPolynomial.monomial
          (Finsupp.equivFunOnFinite.symm
            ![m 0, m 1, f.totalDegree - m.degree]) c)) = _
  rw [MvPolynomial.eval_eval₂]
  have hc : (MvPolynomial.eval ![x, y]).comp MvPolynomial.C =
      RingHom.id K := by
    ext c
    simp
  rw [hc]
  have hg : (fun s => MvPolynomial.eval ![x, y]
      (![MvPolynomial.X 0, MvPolynomial.X 1,
        MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2] s)) =
      ![x, y, Q] := by
    funext i
    fin_cases i <;> simp [Q]
  rw [hg, MvPolynomial.eval₂_id]
  change (MvPolynomial.eval ![x, y, Q])
      (f.sum fun m c => MvPolynomial.monomial
        (Finsupp.equivFunOnFinite.symm
          ![m 0, m 1, f.totalDegree - m.degree]) c) =
      Q ^ f.totalDegree *
        MvPolynomial.eval ![x / Q, y / Q] f
  rw [Finsupp.sum, map_sum, MvPolynomial.eval_eq', Finset.mul_sum]
  apply Finset.sum_congr rfl
  intro m hm
  have hmdeg : m.degree = m 0 + m 1 := by
    rw [Finsupp.degree_eq_sum, Fin.sum_univ_two]
  have hle : m 0 + m 1 ≤ f.totalDegree := by
    rw [← hmdeg]
    exact MvPolynomial.le_totalDegree hm
  have hexp : f.totalDegree =
      (f.totalDegree - (m 0 + m 1)) + m 0 + m 1 := by
    omega
  simp [MvPolynomial.eval_monomial, Finsupp.prod_fintype,
    Fin.prod_univ_three, Fin.prod_univ_two]
  rw [hmdeg]
  rw [hexp, pow_add, pow_add]
  have hsub : f.totalDegree - (m 0 + m 1) + m 0 + m 1 -
      (m 0 + m 1) = f.totalDegree - (m 0 + m 1) := by
    omega
  rw [hsub, div_pow, div_pow]
  field_simp [pow_ne_zero _ hQ']
  change MvPolynomial.coeff m f * x ^ m 0 * y ^ m 1 =
    x ^ m 0 * y ^ m 1 * MvPolynomial.coeff m f
  ring

theorem planePolynomialUnitCircleInversion_eval_inverted_eq_zero_iff
       {K : Type*} [Field K]
       (f : MvPolynomial (Fin 2) K) (x y : K)
       (hQ : x ^ 2 + y ^ 2 ≠ 0) :
       MvPolynomial.eval
           ![x / (x ^ 2 + y ^ 2), y / (x ^ 2 + y ^ 2)]
           (planePolynomialUnitCircleInversion f) = 0 ↔
         MvPolynomial.eval ![x, y] f = 0 := by
  let Q : K := x ^ 2 + y ^ 2
  have hQ' : Q ≠ 0 := hQ
  have hden : (x / Q) ^ 2 + (y / Q) ^ 2 = Q⁻¹ := by
    dsimp [Q]
    field_simp
  have hden_ne : (x / Q) ^ 2 + (y / Q) ^ 2 ≠ 0 := by
    rw [hden]
    exact inv_ne_zero hQ'
  rw [planePolynomialUnitCircleInversion_eval f (x / Q) (y / Q) hden_ne]
  have hx : (x / Q) / ((x / Q) ^ 2 + (y / Q) ^ 2) = x := by
    rw [hden]
    field_simp
  have hy : (y / Q) / ((x / Q) ^ 2 + (y / Q) ^ 2) = y := by
    rw [hden]
    field_simp
  rw [show ![(x / Q) / ((x / Q) ^ 2 + (y / Q) ^ 2),
      (y / Q) / ((x / Q) ^ 2 + (y / Q) ^ 2)] = ![x, y] by
        ext i
        fin_cases i <;> simp [hx, hy]]
  exact mul_eq_zero.trans (or_iff_right (pow_ne_zero _ hden_ne))

theorem planePolynomialUnitCircleInversion_zeroLocus_inverted
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) :
    {p : Fin 2 → K |
      p 0 ^ 2 + p 1 ^ 2 ≠ 0 ∧
      MvPolynomial.eval
        ![p 0 / (p 0 ^ 2 + p 1 ^ 2),
          p 1 / (p 0 ^ 2 + p 1 ^ 2)]
        (planePolynomialUnitCircleInversion f) = 0} =
    {p : Fin 2 → K |
      p 0 ^ 2 + p 1 ^ 2 ≠ 0 ∧
      MvPolynomial.eval p f = 0} := by
  ext p
  simp only [Set.mem_setOf_eq]
  have hp : ![p 0, p 1] = p := by
    funext i
    fin_cases i <;> rfl
  constructor
  · rintro ⟨hQ, h⟩
    refine ⟨hQ, ?_⟩
    rw [← hp]
    exact (planePolynomialUnitCircleInversion_eval_inverted_eq_zero_iff
      f (p 0) (p 1) hQ).mp h
  · rintro ⟨hQ, h⟩
    refine ⟨hQ, ?_⟩
    apply (planePolynomialUnitCircleInversion_eval_inverted_eq_zero_iff
      f (p 0) (p 1) hQ).mpr
    rwa [hp]

private lemma rationalRadiusInversion_zero_one_involutive (z : ℂ) :
    rationalRadiusInversion 0 1 (rationalRadiusInversion 0 1 z) = z := by
  simp [rationalRadiusInversion]

private lemma rationalRadiusInversion_zero_one_re (z : ℂ) :
    (rationalRadiusInversion 0 1 z).re =
      z.re / (z.re ^ 2 + z.im ^ 2) := by
  simp [rationalRadiusInversion, _root_.Complex.normSq]
  ring

private lemma rationalRadiusInversion_zero_one_im (z : ℂ) :
    (rationalRadiusInversion 0 1 z).im =
      z.im / (z.re ^ 2 + z.im ^ 2) := by
  simp [rationalRadiusInversion, _root_.Complex.normSq]
  ring

theorem infinite_rationalDistance_zeroLocus_unitCircleInversion
    {u : Set ℂ}
    (huInf : u.Infinite)
    (huRat : EuclideanPairwiseRationalDistances u)
    (h0 : 0 ∈ u)
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : ∀ z ∈ u, MvPolynomial.eval ![z.re, z.im] f = 0) :
    let v := rationalRadiusInversion 0 1 '' (u \ {0})
    v.Infinite ∧
      EuclideanPairwiseRationalDistances v ∧
      ∀ w ∈ v,
        MvPolynomial.eval ![w.re, w.im]
          (planePolynomialUnitCircleInversion f) = 0 := by
  let v := rationalRadiusInversion 0 1 '' (u \ {0})
  have hInv : Function.LeftInverse
      (rationalRadiusInversion 0 1) (rationalRadiusInversion 0 1) :=
    rationalRadiusInversion_zero_one_involutive
  have hInjective : Function.Injective (rationalRadiusInversion 0 1) :=
    hInv.injective
  have huDiffInf : (u \ {0}).Infinite :=
    huInf.diff (Set.finite_singleton 0)
  have hvInf : v.Infinite := by
    exact huDiffInf.image hInjective.injOn
  have hvRat : EuclideanPairwiseRationalDistances v := by
    exact euclideanPairwiseRationalDistances_rationalRadiusInversion
      huRat h0 1 (by norm_num)
  refine ⟨hvInf, hvRat, ?_⟩
  intro w hw
  rcases hw with ⟨z, hz, rfl⟩
  have hzu : z ∈ u := hz.1
  have hz0 : z ≠ 0 := by simpa using hz.2
  have hQ : z.re ^ 2 + z.im ^ 2 ≠ 0 := by
    simpa [pow_two, _root_.Complex.normSq] using
      (_root_.Complex.normSq_eq_zero.not.mpr hz0)
  rw [rationalRadiusInversion_zero_one_re,
    rationalRadiusInversion_zero_one_im]
  exact (planePolynomialUnitCircleInversion_eval_inverted_eq_zero_iff
    f z.re z.im hQ).mpr (hf z hzu)

private lemma planePolynomialUnitCircleInversion_eq_sum
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) :
    planePolynomialUnitCircleInversion f =
      f.sum fun m c => MvPolynomial.monomial m c *
        (MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2) ^
          (f.totalDegree - m.degree) := by
  classical
  unfold planePolynomialUnitCircleInversion planePolynomialHomogenize
  rw [Finsupp.sum, map_sum]
  apply Finset.sum_congr rfl
  intro m hm
  simp [MvPolynomial.eval₂Hom_monomial, Finsupp.prod_fintype,
    Fin.prod_univ_three, MvPolynomial.monomial_eq]
  ring

theorem unitCirclePolynomial_dvd_planePolynomialUnitCircleInversion_iff
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K) :
    let Q : MvPolynomial (Fin 2) K :=
      MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
    Q ∣ planePolynomialUnitCircleInversion f ↔
      Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f := by
  classical
  let Q : MvPolynomial (Fin 2) K :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  change Q ∣ planePolynomialUnitCircleInversion f ↔
    Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f
  rw [planePolynomialUnitCircleInversion_eq_sum, Finsupp.sum]
  change Q ∣
      ∑ m ∈ f.support,
        MvPolynomial.monomial m (MvPolynomial.coeff m f) *
          Q ^ (f.totalDegree - m.degree) ↔
    Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f
  rw [← Finset.sum_filter_add_sum_filter_not f.support
    (fun m => m.degree = f.totalDegree)]
  have htop :
      ∑ m ∈ f.support with m.degree = f.totalDegree,
          MvPolynomial.monomial m (MvPolynomial.coeff m f) *
            Q ^ (f.totalDegree - m.degree) =
        MvPolynomial.homogeneousComponent f.totalDegree f := by
    rw [MvPolynomial.homogeneousComponent_apply]
    apply Finset.sum_congr rfl
    intro m hm
    have hdeg : m.degree = f.totalDegree := (Finset.mem_filter.mp hm).2
    simp [hdeg]
  rw [htop]
  have hlow : Q ∣
      ∑ m ∈ f.support with m.degree ≠ f.totalDegree,
        MvPolynomial.monomial m (MvPolynomial.coeff m f) *
          Q ^ (f.totalDegree - m.degree) := by
    apply Finset.dvd_sum
    intro m hm
    have hm' := (Finset.mem_filter.mp hm)
    have hle : m.degree ≤ f.totalDegree :=
      MvPolynomial.le_totalDegree hm'.1
    have hlt : m.degree < f.totalDegree := lt_of_le_of_ne hle hm'.2
    have hpos : 0 < f.totalDegree - m.degree := Nat.sub_pos_of_lt hlt
    exact dvd_mul_of_dvd_right (dvd_pow_self Q (Nat.ne_of_gt hpos)) _
  exact dvd_add_left hlow

theorem exists_planePolynomialUnitCircleInversion_strictTransform_of_dvd_top
    {K : Type*} [Field K]
    (f : MvPolynomial (Fin 2) K)
    (hTop :
      let Q : MvPolynomial (Fin 2) K :=
        MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
      Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f) :
    let Q : MvPolynomial (Fin 2) K :=
      MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
    ∃ g, planePolynomialUnitCircleInversion f = Q * g ∧
      ∀ x y : K, x ^ 2 + y ^ 2 ≠ 0 →
        (MvPolynomial.eval
            ![x / (x ^ 2 + y ^ 2),
              y / (x ^ 2 + y ^ 2)] g = 0 ↔
          MvPolynomial.eval ![x, y] f = 0) := by
  let Q : MvPolynomial (Fin 2) K :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  change Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f at hTop
  have hDiv : Q ∣ planePolynomialUnitCircleInversion f :=
    (unitCirclePolynomial_dvd_planePolynomialUnitCircleInversion_iff f).2 hTop
  obtain ⟨g, hg⟩ := hDiv
  refine ⟨g, hg, ?_⟩
  intro x y hxy
  let q : K := x ^ 2 + y ^ 2
  have hq : q ≠ 0 := hxy
  have hden : (x / q) ^ 2 + (y / q) ^ 2 = q⁻¹ := by
    dsimp [q]
    field_simp
  have hEvalQ :
      MvPolynomial.eval ![x / q, y / q] Q ≠ 0 := by
    have heq : MvPolynomial.eval ![x / q, y / q] Q = q⁻¹ := by
      simpa [Q] using hden
    rw [heq]
    exact inv_ne_zero hq
  have hQuotient :
      MvPolynomial.eval ![x / q, y / q] g = 0 ↔
        MvPolynomial.eval ![x / q, y / q]
          (planePolynomialUnitCircleInversion f) = 0 := by
    rw [hg, map_mul]
    simp [hEvalQ]
  exact hQuotient.trans
    (planePolynomialUnitCircleInversion_eval_inverted_eq_zero_iff
      f x y hxy)

def IsAffineCirclePolynomial
    (f : MvPolynomial (Fin 2) ℝ) : Prop :=
  let Q := MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  ∃ a b c d : ℝ, a ≠ 0 ∧
    f =
      MvPolynomial.C a * Q +
      MvPolynomial.C b * MvPolynomial.X 0 +
      MvPolynomial.C c * MvPolynomial.X 1 +
      MvPolynomial.C d

theorem isAffineCirclePolynomial_of_totalDegree_eq_two_of_dvd_top
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hTop :
      let Q := MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
      Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f) :
    IsAffineCirclePolynomial f := by
  classical
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  change Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f at hTop
  rw [hdeg] at hTop
  obtain ⟨g, hg⟩ := hTop
  have hQhom : Q.IsHomogeneous 2 := by
    dsimp [Q]
    exact (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 0 2).add
      (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 1 2)
  have hQ0 : Q ≠ 0 := by
    intro h
    have he := congrArg (MvPolynomial.eval ![1, 0]) h
    simpa [Q] using he
  have htop0 : MvPolynomial.homogeneousComponent 2 f ≠ 0 := by
    intro hzero
    have hf0 : f ≠ 0 := by
      intro hf
      rw [hf] at hdeg
      simp at hdeg
    obtain ⟨m, hm, hmdeg⟩ := f.support.exists_mem_eq_sup
      (Finsupp.support_nonempty_iff.mpr hf0)
      (fun m : Fin 2 →₀ ℕ => m.degree)
    have hmdeg' : m.degree = 2 := by
      calc
        m.degree = f.support.sup (fun m => m.degree) := hmdeg.symm
        _ = f.totalDegree := rfl
        _ = 2 := hdeg
    have hmcoeff : MvPolynomial.coeff m f ≠ 0 :=
      MvPolynomial.mem_support_iff.mp hm
    have hc := congrArg (MvPolynomial.coeff m) hzero
    simp [MvPolynomial.coeff_homogeneousComponent, hmdeg', hmcoeff] at hc
  have hgconst : ∃ a : ℝ, g = MvPolynomial.C a := by
    by_cases hg0 : g = 0
    · exact ⟨0, by simp [hg0]⟩
    · have hproddeg := MvPolynomial.totalDegree_mul_of_isDomain hQ0 hg0
      have hle : (Q * g).totalDegree ≤ 2 := by
        rw [← hg]
        exact (MvPolynomial.homogeneousComponent_isHomogeneous 2 f).totalDegree_le
      have hgdeg : g.totalDegree = 0 := by
        have hQdeg : Q.totalDegree = 2 := hQhom.totalDegree hQ0
        rw [hproddeg, hQdeg] at hle
        omega
      exact ⟨MvPolynomial.coeff 0 g,
        (MvPolynomial.totalDegree_eq_zero_iff_eq_C.mp hgdeg)⟩
  obtain ⟨a, rfl⟩ := hgconst
  have ha : a ≠ 0 := by
    intro ha0
    subst a
    simp at hg
    exact htop0 hg
  have hlin_mem : MvPolynomial.homogeneousComponent 1 f ∈
      Submodule.span ℝ
        (Set.range (MvPolynomial.X : Fin 2 → MvPolynomial (Fin 2) ℝ)) := by
    rw [← MvPolynomial.homogeneousSubmodule_one_eq_span_X]
    exact MvPolynomial.homogeneousComponent_mem 1 f
  obtain ⟨bc, hbc⟩ :=
    (Submodule.mem_span_range_iff_exists_fun ℝ).mp hlin_mem
  have hlin : MvPolynomial.homogeneousComponent 1 f =
      MvPolynomial.C (bc 0) * MvPolynomial.X 0 +
      MvPolynomial.C (bc 1) * MvPolynomial.X 1 := by
    rw [← hbc, Fin.sum_univ_two]
    simp [MvPolynomial.smul_eq_C_mul]
  have hconst := MvPolynomial.homogeneousComponent_zero f
  have hdecomp := MvPolynomial.sum_homogeneousComponent f
  rw [hdeg] at hdecomp
  simp only [Finset.sum_range_succ, Finset.sum_range_zero, zero_add] at hdecomp
  change IsAffineCirclePolynomial f
  refine ⟨a, bc 0, bc 1, MvPolynomial.coeff 0 f, ha, ?_⟩
  calc
    f = MvPolynomial.homogeneousComponent 0 f +
          MvPolynomial.homogeneousComponent 1 f +
          MvPolynomial.homogeneousComponent 2 f := hdecomp.symm
    _ = MvPolynomial.C a * Q +
          MvPolynomial.C (bc 0) * MvPolynomial.X 0 +
          MvPolynomial.C (bc 1) * MvPolynomial.X 1 +
          MvPolynomial.C (MvPolynomial.coeff 0 f) := by
      rw [hg, hlin, hconst]
      ring

theorem not_unitCirclePolynomial_dvd_planePolynomialUnitCircleInversion_of_totalDegree_eq_two_of_not_circle
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hNotCircle : ¬ IsAffineCirclePolynomial f) :
    let Q : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
    ¬ Q ∣ planePolynomialUnitCircleInversion f := by
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  change ¬ Q ∣ planePolynomialUnitCircleInversion f
  intro hDiv
  have hTop : Q ∣ MvPolynomial.homogeneousComponent f.totalDegree f :=
    (unitCirclePolynomial_dvd_planePolynomialUnitCircleInversion_iff f).1 hDiv
  exact hNotCircle
    (isAffineCirclePolynomial_of_totalDegree_eq_two_of_dvd_top f hdeg hTop)

private lemma planePolynomialHomogenize_mul
    {K : Type*} [Field K]
    {f g : MvPolynomial (Fin 2) K} (hf : f ≠ 0) (hg : g ≠ 0) :
    planePolynomialHomogenize (f * g) =
      planePolynomialHomogenize f * planePolynomialHomogenize g := by
  change homAt (f * g).totalDegree (f * g) =
    homAt f.totalDegree f * homAt g.totalDegree g
  rw [MvPolynomial.totalDegree_mul_of_isDomain hf hg]
  have h := homAt_dehom_of_homogeneous
    ((planePolynomialHomogenize_isHomogeneous f).mul
      (planePolynomialHomogenize_isHomogeneous g))
  change homAt (f.totalDegree + g.totalDegree)
      (dehom (homAt f.totalDegree f * homAt g.totalDegree g)) = _ at h
  rw [map_mul, dehom_homAt_totalDegree, dehom_homAt_totalDegree] at h
  exact h

private lemma planePolynomialUnitCircleInversion_mul
    {K : Type*} [Field K]
    {f g : MvPolynomial (Fin 2) K} (hf : f ≠ 0) (hg : g ≠ 0) :
    planePolynomialUnitCircleInversion (f * g) =
      planePolynomialUnitCircleInversion f *
        planePolynomialUnitCircleInversion g := by
  unfold planePolynomialUnitCircleInversion
  rw [planePolynomialHomogenize_mul hf hg, map_mul]

private lemma planePolynomialUnitCircleInversion_double_cross
    (f : MvPolynomial (Fin 2) ℝ) :
    let Q : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
    Q ^ f.totalDegree *
        planePolynomialUnitCircleInversion
          (planePolynomialUnitCircleInversion f) =
      Q ^ (planePolynomialUnitCircleInversion f).totalDegree * f := by
  classical
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  change Q ^ f.totalDegree *
        planePolynomialUnitCircleInversion
          (planePolynomialUnitCircleInversion f) =
      Q ^ (planePolynomialUnitCircleInversion f).totalDegree * f
  apply MvPolynomial.funext_set
      (fun _ : Fin 2 => ({0} : Set ℝ)ᶜ)
      (fun _ => (Set.finite_singleton 0).infinite_compl)
  intro p hp
  have hp0 (i : Fin 2) : p i ≠ 0 := hp i (Set.mem_univ i)
  let q : ℝ := p 0 ^ 2 + p 1 ^ 2
  have hq : q ≠ 0 := by
    dsimp [q]
    nlinarith [sq_pos_of_ne_zero (hp0 0)]
  have hden : (p 0 / q) ^ 2 + (p 1 / q) ^ 2 = q⁻¹ := by
    dsimp [q]
    field_simp
  have hden0 : (p 0 / q) ^ 2 + (p 1 / q) ^ 2 ≠ 0 := by
    rw [hden]
    exact inv_ne_zero hq
  have hpvec : ![p 0, p 1] = p := by
    ext i
    fin_cases i <;> rfl
  simp only [map_mul, map_pow]
  have hQeval : MvPolynomial.eval p Q = q := by
    simp [Q, q]
  rw [hQeval]
  rw [← hpvec, planePolynomialUnitCircleInversion_eval
    (planePolynomialUnitCircleInversion f) (p 0) (p 1) hq]
  rw [planePolynomialUnitCircleInversion_eval f (p 0 / q) (p 1 / q) hden0]
  have hinv :
      ![(p 0 / q) / ((p 0 / q) ^ 2 + (p 1 / q) ^ 2),
        (p 1 / q) / ((p 0 / q) ^ 2 + (p 1 / q) ^ 2)] = p := by
    rw [hden]
    ext i
    fin_cases i <;> simp [hq]
  rw [hinv, hden]
  rw [show p 0 ^ 2 + p 1 ^ 2 = q by rfl, hpvec]
  rw [inv_pow]
  have hpow : q ^ f.totalDegree ≠ 0 := pow_ne_zero _ hq
  calc
    q ^ f.totalDegree *
          (q ^ (planePolynomialUnitCircleInversion f).totalDegree *
            ((q ^ f.totalDegree)⁻¹ * MvPolynomial.eval p f)) =
        q ^ (planePolynomialUnitCircleInversion f).totalDegree *
          ((q ^ f.totalDegree) * (q ^ f.totalDegree)⁻¹) *
            MvPolynomial.eval p f := by ring
    _ = q ^ (planePolynomialUnitCircleInversion f).totalDegree *
          MvPolynomial.eval p f := by rw [mul_inv_cancel₀ hpow, mul_one]

private lemma exists_nonzero_eval_eq_zero_of_totalDegree_eq_one
    (f : MvPolynomial (Fin 2) ℝ) (hdeg : f.totalDegree = 1) :
    ∃ p : Fin 2 → ℝ, p ≠ 0 ∧ MvPolynomial.eval p f = 0 := by
  classical
  have hlin_mem : MvPolynomial.homogeneousComponent 1 f ∈
      Submodule.span ℝ
        (Set.range (MvPolynomial.X : Fin 2 → MvPolynomial (Fin 2) ℝ)) := by
    rw [← MvPolynomial.homogeneousSubmodule_one_eq_span_X]
    exact MvPolynomial.homogeneousComponent_mem 1 f
  obtain ⟨bc, hbc⟩ :=
    (Submodule.mem_span_range_iff_exists_fun ℝ).mp hlin_mem
  have hlin : MvPolynomial.homogeneousComponent 1 f =
      MvPolynomial.C (bc 0) * MvPolynomial.X 0 +
      MvPolynomial.C (bc 1) * MvPolynomial.X 1 := by
    rw [← hbc, Fin.sum_univ_two]
    simp [MvPolynomial.smul_eq_C_mul]
  have hdecomp := MvPolynomial.sum_homogeneousComponent f
  rw [hdeg] at hdecomp
  simp only [Finset.sum_range_succ, Finset.sum_range_zero, zero_add] at hdecomp
  have hf_eq : f =
      MvPolynomial.C (MvPolynomial.coeff 0 f) +
      (MvPolynomial.C (bc 0) * MvPolynomial.X 0 +
       MvPolynomial.C (bc 1) * MvPolynomial.X 1) := by
    rw [← hlin, ← MvPolynomial.homogeneousComponent_zero]
    exact hdecomp.symm
  have hbcne : bc 0 ≠ 0 ∨ bc 1 ≠ 0 := by
    by_contra h
    push_neg at h
    rcases h with ⟨h0, h1⟩
    have : f = MvPolynomial.C (MvPolynomial.coeff 0 f) := by
      calc
        f = MvPolynomial.C (MvPolynomial.coeff 0 f) +
            (MvPolynomial.C (bc 0) * MvPolynomial.X 0 +
             MvPolynomial.C (bc 1) * MvPolynomial.X 1) := hf_eq
        _ = MvPolynomial.C (MvPolynomial.coeff 0 f) := by
          rw [h0, h1]
          simp only [map_zero, zero_mul, add_zero]
    rw [this] at hdeg
    simp at hdeg
  rcases hbcne with h0 | h1
  · let p : Fin 2 → ℝ :=
      ![-(MvPolynomial.coeff 0 f + bc 1) / bc 0, 1]
    refine ⟨p, ?_, ?_⟩
    · intro hp
      have := congrFun hp 1
      simp [p] at this
    · rw [hf_eq]
      simp [p]
      field_simp
      ring
  · let p : Fin 2 → ℝ :=
      ![1, -(MvPolynomial.coeff 0 f + bc 0) / bc 1]
    refine ⟨p, ?_, ?_⟩
    · intro hp
      have := congrFun hp 0
      simp [p] at this
    · rw [hf_eq]
      simp [p]
      field_simp
      ring

private lemma unitCirclePolynomial_irreducible_real :
    Irreducible
      (MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2 :
        MvPolynomial (Fin 2) ℝ) := by
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  have hQhom : Q.IsHomogeneous 2 := by
    dsimp [Q]
    exact (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 0 2).add
      (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 1 2)
  have hQ0 : Q ≠ 0 := by
    intro h
    have he := congrArg (MvPolynomial.eval ![1, 0]) h
    simpa [Q] using he
  have hQdeg : Q.totalDegree = 2 := hQhom.totalDegree hQ0
  rw [irreducible_iff]
  constructor
  · intro hu
    have hzero := (MvPolynomial.isUnit_iff_totalDegree_of_isReduced.mp hu).2
    rw [hQdeg] at hzero
    norm_num at hzero
  · intro a b hab
    have ha0 : a ≠ 0 := by
      intro ha
      rw [ha, zero_mul] at hab
      exact hQ0 hab
    have hb0 : b ≠ 0 := by
      intro hb
      rw [hb, mul_zero] at hab
      exact hQ0 hab
    by_cases hua : IsUnit a
    · exact Or.inl hua
    by_cases hub : IsUnit b
    · exact Or.inr hub
    exfalso
    have hadeg0 : a.totalDegree ≠ 0 := by
      intro ha
      have haeq := MvPolynomial.totalDegree_eq_zero_iff_eq_C.mp ha
      have hc : MvPolynomial.coeff 0 a ≠ 0 := by
        intro hc
        apply ha0
        rw [haeq, hc, map_zero]
      apply hua
      rw [haeq]
      exact (isUnit_iff_ne_zero.mpr hc).map MvPolynomial.C
    have hbdeg0 : b.totalDegree ≠ 0 := by
      intro hb
      have hbeq := MvPolynomial.totalDegree_eq_zero_iff_eq_C.mp hb
      have hc : MvPolynomial.coeff 0 b ≠ 0 := by
        intro hc
        apply hb0
        rw [hbeq, hc, map_zero]
      apply hub
      rw [hbeq]
      exact (isUnit_iff_ne_zero.mpr hc).map MvPolynomial.C
    have hdegadd : a.totalDegree + b.totalDegree = 2 := by
      rw [← MvPolynomial.totalDegree_mul_of_isDomain ha0 hb0, ← hab, hQdeg]
    have hadeg : a.totalDegree = 1 := by omega
    obtain ⟨p, hp0, hpa⟩ :=
      exists_nonzero_eval_eq_zero_of_totalDegree_eq_one a hadeg
    have hQeval := congrArg (MvPolynomial.eval p) hab
    rw [map_mul, hpa, zero_mul] at hQeval
    have hpcoord : p 0 ≠ 0 ∨ p 1 ≠ 0 := by
      by_contra h
      push_neg at h
      apply hp0
      funext i
      fin_cases i <;> simp [h.1, h.2]
    simp only [map_add, map_pow, MvPolynomial.eval_X] at hQeval
    rcases hpcoord with hp | hp <;> nlinarith [sq_pos_of_ne_zero hp]

private lemma planePolynomialUnitCircleInversion_ne_zero_real
    {f : MvPolynomial (Fin 2) ℝ} (hf : f ≠ 0) :
    planePolynomialUnitCircleInversion f ≠ 0 := by
  intro h
  have hd := planePolynomialUnitCircleInversion_double_cross f
  have hTzero : planePolynomialUnitCircleInversion
      (0 : MvPolynomial (Fin 2) ℝ) = 0 := by
    rw [planePolynomialUnitCircleInversion_eq_sum]
    simp
  dsimp at hd
  rw [h, hTzero, MvPolynomial.totalDegree_zero, pow_zero, one_mul,
    mul_zero] at hd
  exact hf hd.symm

private lemma unitCirclePolynomial_not_dvd_of_not_dvd_mul_left
    {a b : MvPolynomial (Fin 2) ℝ}
    (h : ¬ (MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2) ∣ a * b) :
    ¬ (MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2) ∣ b := by
  intro hb
  exact h (dvd_mul_of_dvd_right hb a)

theorem irreducible_planePolynomialUnitCircleInversion_of_irreducible_of_not_dvd_real
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hQ :
      let Q : MvPolynomial (Fin 2) ℝ :=
        MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
      ¬ Q ∣ planePolynomialUnitCircleInversion f) :
    Irreducible (planePolynomialUnitCircleInversion f) := by
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  change ¬ Q ∣ planePolynomialUnitCircleInversion f at hQ
  have hQirr : Irreducible Q := unitCirclePolynomial_irreducible_real
  have hQprime : Prime Q := hQirr.prime
  have hQhom : Q.IsHomogeneous 2 := by
    dsimp [Q]
    exact (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 0 2).add
      (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 1 2)
  have hQdeg : Q.totalDegree = 2 := hQhom.totalDegree hQirr.ne_zero
  have hT0 : planePolynomialUnitCircleInversion f ≠ 0 :=
    planePolynomialUnitCircleInversion_ne_zero_real hf.ne_zero
  have hfdeg0 : f.totalDegree ≠ 0 := by
    intro hdeg
    have heq := MvPolynomial.totalDegree_eq_zero_iff_eq_C.mp hdeg
    have hc : MvPolynomial.coeff 0 f ≠ 0 := by
      intro hc
      apply hf.ne_zero
      rw [heq, hc, map_zero]
    apply hf.not_isUnit
    rw [heq]
    exact (isUnit_iff_ne_zero.mpr hc).map MvPolynomial.C
  have hf_not_dvd_Q : ¬ f ∣ Q := by
    intro hfd
    obtain ⟨c, hc⟩ := hfd
    have hc0 : c ≠ 0 := by
      intro hc0
      rw [hc0, mul_zero] at hc
      exact hQirr.ne_zero hc
    have hcu : IsUnit c := by
      rcases (irreducible_iff.mp hQirr).2 hc with hfu | hcu
      · exact (hf.not_isUnit hfu).elim
      · exact hcu
    have hQdf : Q ∣ f := by
      rw [hc]
      exact hcu.mul_right_dvd.mpr (dvd_refl f)
    obtain ⟨d, hd⟩ := hQdf
    have hd0 : d ≠ 0 := by
      intro hd0
      rw [hd0, mul_zero] at hd
      exact hf.ne_zero hd
    have hTmul := planePolynomialUnitCircleInversion_mul hQirr.ne_zero hd0
    rw [← hd] at hTmul
    apply hQ
    rw [hTmul]
    exact dvd_mul_of_dvd_left
      ((unitCirclePolynomial_dvd_planePolynomialUnitCircleInversion_iff Q).2
        (by rw [hQdeg, MvPolynomial.homogeneousComponent_of_mem hQhom]
            simp
            change Q ∣ Q
            exact dvd_refl Q)) _
  rw [irreducible_iff]
  constructor
  · intro hTu
    have hTdeg : (planePolynomialUnitCircleInversion f).totalDegree = 0 :=
      (MvPolynomial.isUnit_iff_totalDegree_of_isReduced.mp hTu).2
    have hd := planePolynomialUnitCircleInversion_double_cross f
    change Q ^ f.totalDegree *
        planePolynomialUnitCircleInversion
          (planePolynomialUnitCircleInversion f) =
      Q ^ (planePolynomialUnitCircleInversion f).totalDegree * f at hd
    rw [hTdeg, pow_zero, one_mul] at hd
    have hQdf : Q ∣ f := by
      rw [← hd]
      exact dvd_mul_of_dvd_left (dvd_pow_self Q hfdeg0) _
    obtain ⟨c, hc⟩ := hQdf
    have hc0 : c ≠ 0 := by
      intro hc0
      rw [hc0, mul_zero] at hc
      exact hf.ne_zero hc
    have hTmul := planePolynomialUnitCircleInversion_mul hQirr.ne_zero hc0
    rw [← hc] at hTmul
    apply hQ
    rw [hTmul]
    exact dvd_mul_of_dvd_left
      ((unitCirclePolynomial_dvd_planePolynomialUnitCircleInversion_iff Q).2
        (by rw [hQdeg, MvPolynomial.homogeneousComponent_of_mem hQhom]
            simp
            change Q ∣ Q
            exact dvd_refl Q)) _
  · intro a b hab
    have ha0 : a ≠ 0 := by
      intro ha
      rw [ha, zero_mul] at hab
      exact hT0 hab
    have hb0 : b ≠ 0 := by
      intro hb
      rw [hb, mul_zero] at hab
      exact hT0 hab
    have hTFdvd : f ∣ planePolynomialUnitCircleInversion
        (planePolynomialUnitCircleInversion f) := by
      have hd := planePolynomialUnitCircleInversion_double_cross f
      change Q ^ f.totalDegree *
          planePolynomialUnitCircleInversion
            (planePolynomialUnitCircleInversion f) =
        Q ^ (planePolynomialUnitCircleInversion f).totalDegree * f at hd
      have hdiv : f ∣ Q ^ f.totalDegree *
          planePolynomialUnitCircleInversion
            (planePolynomialUnitCircleInversion f) := by
        rw [hd]
        exact dvd_mul_left f _
      rcases hf.prime.dvd_mul.mp hdiv with hfpow | hfT
      · exact (hf_not_dvd_Q (hf.prime.dvd_of_dvd_pow hfpow)).elim
      · exact hfT
    have hTmul := planePolynomialUnitCircleInversion_mul ha0 hb0
    rw [hab, hTmul] at hTFdvd
    rcases hf.prime.dvd_mul.mp hTFdvd with hfa | hfb
    · right
      obtain ⟨c, hc⟩ := hfa
      have hTa0 := planePolynomialUnitCircleInversion_ne_zero_real ha0
      have hc0 : c ≠ 0 := by
        intro hc0
        rw [hc0, mul_zero] at hc
        exact hTa0 hc
      have hTc := planePolynomialUnitCircleInversion_mul hf.ne_zero hc0
      rw [← hc] at hTc
      have hab_dvd_TTa : a * b ∣
          planePolynomialUnitCircleInversion
            (planePolynomialUnitCircleInversion a) := by
        rw [hTc, ← hab]
        exact dvd_mul_right _ _
      have hcross := planePolynomialUnitCircleInversion_double_cross a
      change Q ^ a.totalDegree *
          planePolynomialUnitCircleInversion
            (planePolynomialUnitCircleInversion a) =
        Q ^ (planePolynomialUnitCircleInversion a).totalDegree * a at hcross
      have hab_dvd_pow_mul : a * b ∣
          Q ^ (planePolynomialUnitCircleInversion a).totalDegree * a := by
        rw [← hcross]
        exact dvd_mul_of_dvd_right hab_dvd_TTa _
      have hbpow : b ∣ Q ^ (planePolynomialUnitCircleInversion a).totalDegree := by
        apply (mul_dvd_mul_iff_left ha0).mp
        simpa [mul_comm, mul_left_comm] using hab_dvd_pow_mul
      obtain ⟨i, hi, hassoc⟩ :=
        (dvd_prime_pow hQprime _).mp hbpow
      have hQnb : ¬ Q ∣ b := by
        apply unitCirclePolynomial_not_dvd_of_not_dvd_mul_left
        simpa [Q, hab] using hQ
      have hi0 : i = 0 := by
        by_contra hi0
        apply hQnb
        exact (dvd_pow_self Q hi0).trans hassoc.symm.dvd
      subst i
      have hassoc_one : Associated b 1 := by simpa using hassoc
      exact associated_one_iff_isUnit.mp hassoc_one
    · left
      obtain ⟨c, hc⟩ := hfb
      have hTb0 := planePolynomialUnitCircleInversion_ne_zero_real hb0
      have hc0 : c ≠ 0 := by
        intro hc0
        rw [hc0, mul_zero] at hc
        exact hTb0 hc
      have hTc := planePolynomialUnitCircleInversion_mul hf.ne_zero hc0
      rw [← hc] at hTc
      have hab_dvd_TTb : a * b ∣
          planePolynomialUnitCircleInversion
            (planePolynomialUnitCircleInversion b) := by
        rw [hTc, ← hab]
        exact dvd_mul_right _ _
      have hcross := planePolynomialUnitCircleInversion_double_cross b
      change Q ^ b.totalDegree *
          planePolynomialUnitCircleInversion
            (planePolynomialUnitCircleInversion b) =
        Q ^ (planePolynomialUnitCircleInversion b).totalDegree * b at hcross
      have hab_dvd_pow_mul : a * b ∣
          Q ^ (planePolynomialUnitCircleInversion b).totalDegree * b := by
        rw [← hcross]
        exact dvd_mul_of_dvd_right hab_dvd_TTb _
      have hapow : a ∣ Q ^ (planePolynomialUnitCircleInversion b).totalDegree := by
        apply (mul_dvd_mul_iff_right hb0).mp
        simpa [mul_comm, mul_left_comm] using hab_dvd_pow_mul
      obtain ⟨i, hi, hassoc⟩ :=
        (dvd_prime_pow hQprime _).mp hapow
      have hQna : ¬ Q ∣ a := by
        intro hQa
        apply hQ
        rw [hab]
        exact dvd_mul_of_dvd_left hQa b
      have hi0 : i = 0 := by
        by_contra hi0
        apply hQna
        exact (dvd_pow_self Q hi0).trans hassoc.symm.dvd
      subst i
      have hassoc_one : Associated a 1 := by simpa using hassoc
      exact associated_one_iff_isUnit.mp hassoc_one

theorem planePolynomialUnitCircleInversion_totalDegree_eq_three
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (hlinear : MvPolynomial.homogeneousComponent 1 f ≠ 0) :
    (planePolynomialUnitCircleInversion f).totalDegree = 3 := by
  classical
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  have hQhom : Q.IsHomogeneous 2 := by
    dsimp [Q]
    exact (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 0 2).add
      (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 1 2)
  have hQ0 : Q ≠ 0 := by
    intro h
    have he := congrArg (MvPolynomial.eval ![1, 0]) h
    simpa [Q] using he
  have hsupport (m : Fin 2 →₀ ℕ) (hm : m ∈ f.support) :
      m.degree = 1 ∨ m.degree = 2 := by
    have hle : m.degree ≤ 2 := by
      simpa [hdeg] using MvPolynomial.le_totalDegree hm
    have hne : m.degree ≠ 0 := by
      intro hm0
      have hmzero : m = 0 := (Finsupp.degree_eq_zero_iff m).mp hm0
      subst m
      have hc0 : MvPolynomial.coeff 0 f = 0 := by
        simpa using congrArg (MvPolynomial.coeff 0) hzero
      exact (MvPolynomial.mem_support_iff.mp hm) hc0
    omega
  have hformula : planePolynomialUnitCircleInversion f =
      MvPolynomial.homogeneousComponent 1 f * Q +
        MvPolynomial.homogeneousComponent 2 f := by
    rw [planePolynomialUnitCircleInversion_eq_sum, Finsupp.sum, hdeg]
    change (∑ m ∈ f.support,
        MvPolynomial.monomial m (MvPolynomial.coeff m f) *
          Q ^ (2 - m.degree)) = _
    rw [← Finset.sum_filter_add_sum_filter_not f.support
      (fun m => m.degree = 1)]
    congr 1
    · rw [MvPolynomial.homogeneousComponent_apply, Finset.sum_mul]
      apply Finset.sum_congr rfl
      intro m hm
      have hmdeg : m.degree = 1 := (Finset.mem_filter.mp hm).2
      simp [hmdeg, Q]
    · rw [MvPolynomial.homogeneousComponent_apply]
      apply Finset.sum_congr
      · ext m
        simp only [Finset.mem_filter]
        constructor
        · rintro ⟨hm, hm1⟩
          exact ⟨hm, (hsupport m hm).resolve_left hm1⟩
        · rintro ⟨hm, hm2⟩
          exact ⟨hm, by omega⟩
      · intro m hm
        have hmdeg : m.degree = 2 := (Finset.mem_filter.mp hm).2
        simp [hmdeg]
  rw [hformula]
  have hlinhom := MvPolynomial.homogeneousComponent_isHomogeneous 1 f
  have hlinQhom :
      (MvPolynomial.homogeneousComponent 1 f * Q).IsHomogeneous 3 := by
    simpa using hlinhom.mul hQhom
  have hlinQ0 : MvPolynomial.homogeneousComponent 1 f * Q ≠ 0 :=
    mul_ne_zero hlinear hQ0
  have hlinQdeg :
      (MvPolynomial.homogeneousComponent 1 f * Q).totalDegree = 3 :=
    hlinQhom.totalDegree hlinQ0
  have hquaddeg : (MvPolynomial.homogeneousComponent 2 f).totalDegree ≤ 2 :=
    (MvPolynomial.homogeneousComponent_isHomogeneous 2 f).totalDegree_le
  have hlt : (MvPolynomial.homogeneousComponent 2 f).totalDegree <
      (MvPolynomial.homogeneousComponent 1 f * Q).totalDegree := by
    rw [hlinQdeg]
    omega
  calc
    (MvPolynomial.homogeneousComponent 1 f * Q +
        MvPolynomial.homogeneousComponent 2 f).totalDegree =
        (MvPolynomial.homogeneousComponent 1 f * Q).totalDegree :=
      MvPolynomial.totalDegree_add_eq_left_of_totalDegree_lt hlt
    _ = 3 := hlinQdeg

private lemma finsupp_fin_two_degree_two_cases (m : Fin 2 →₀ ℕ)
    (hm : m.degree = 2) :
    m = Finsupp.single 0 2 ∨
      m = Finsupp.single 0 1 + Finsupp.single 1 1 ∨
      m = Finsupp.single 1 2 := by
  have hs : m 0 + m 1 = 2 := by
    simpa [Finsupp.degree_eq_sum, Fin.sum_univ_two] using hm
  rcases Nat.eq_zero_or_pos (m 0) with h0 | h0
  · right; right
    ext i
    fin_cases i
    · simp [h0]
    · simp [h0] at hs ⊢
      exact hs
  · by_cases h01 : m 0 = 1
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
      MvPolynomial.monomial (Finsupp.single 0 2)
          (MvPolynomial.coeff (Finsupp.single 0 2) f) +
      MvPolynomial.monomial (Finsupp.single 0 1 + Finsupp.single 1 1)
          (MvPolynomial.coeff
            (Finsupp.single 0 1 + Finsupp.single 1 1) f) +
      MvPolynomial.monomial (Finsupp.single 1 2)
          (MvPolynomial.coeff (Finsupp.single 1 2) f) := by
  have h20_11 : (Finsupp.single 0 2 : Fin 2 →₀ ℕ) ≠
      Finsupp.single 0 1 + Finsupp.single 1 1 := by
    intro h
    have he := congrArg (fun m : Fin 2 →₀ ℕ => m 0) h
    norm_num at he
  have h20_02 : (Finsupp.single 0 2 : Fin 2 →₀ ℕ) ≠
      Finsupp.single 1 2 := by
    intro h
    have he := congrArg (fun m : Fin 2 →₀ ℕ => m 0) h
    norm_num at he
  have h11_02 : (Finsupp.single 0 1 + Finsupp.single 1 1 : Fin 2 →₀ ℕ) ≠
      Finsupp.single 1 2 := by
    intro h
    have he := congrArg (fun m : Fin 2 →₀ ℕ => m 0) h
    norm_num at he
  ext m
  by_cases hm : m.degree = 2
  · rcases finsupp_fin_two_degree_two_cases m hm with rfl | rfl | rfl <;>
      simp [MvPolynomial.coeff_monomial, h20_11, h20_02, h11_02,
        Ne.symm h20_11, Ne.symm h20_02, Ne.symm h11_02]
  · rw [hf.coeff_eq_zero hm]
    have h20 : Finsupp.single 0 2 ≠ m := by
      intro h
      subst m
      simp at hm
    have h11 : Finsupp.single 0 1 + Finsupp.single 1 1 ≠ m := by
      intro h
      subst m
      simp [Finsupp.degree_eq_sum, Fin.sum_univ_two] at hm
    have h02 : Finsupp.single 1 2 ≠ m := by
      intro h
      subst m
      simp at hm
    simp [MvPolynomial.coeff_monomial, h20, h11, h02]

private lemma not_isUnit_of_isHomogeneous_one_ne_zero
    {f : MvPolynomial (Fin 2) ℝ} (hh : f.IsHomogeneous 1) (hf : f ≠ 0) :
    ¬ IsUnit f := by
  intro hu
  have hd0 := (MvPolynomial.isUnit_iff_totalDegree_of_isReduced.mp hu).2
  have hd1 : f.totalDegree = 1 := hh.totalDegree hf
  omega

theorem homogeneousComponent_one_ne_zero_of_irreducible_quadratic_of_nonzero_zero
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
      MvPolynomial.C b * (MvPolynomial.X 0 * MvPolynomial.X 1) +
      MvPolynomial.C c * MvPolynomial.X 1 ^ 2 := by
    rw [hf_eq]
    simpa [a, b, c, MvPolynomial.monomial_eq,
      Finsupp.prod_fintype, Fin.prod_univ_two,
      MvPolynomial.coeff_homogeneousComponent,
      Finsupp.degree_eq_sum, Fin.sum_univ_two] using
      homogeneous_quadratic_eq_three_terms
        (MvPolynomial.homogeneousComponent 2 f)
        (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)
  rw [hform] at hEval
  simp at hEval
  rcases hxy with hx | hy
  · let g : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 1 - MvPolynomial.C (y / x) * MvPolynomial.X 0
    let k : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.C c * MvPolynomial.X 1 +
        MvPolynomial.C (b + c * (y / x)) * MvPolynomial.X 0
    have hrel : a * x ^ 2 + b * x * y + c * y ^ 2 = 0 := by
      nlinarith [hEval]
    have hfac : f = g * k := by
      rw [hform]
      dsimp [g, k]
      apply MvPolynomial.funext
      intro p
      simp only [map_add, map_mul, map_sub, MvPolynomial.eval_C,
        MvPolynomial.eval_X, map_pow]
      field_simp [hx]
      linear_combination (p 0) ^ 2 * hrel
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
      exact (MvPolynomial.isHomogeneous_X (R := ℝ) 1).sub
        ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
          (MvPolynomial.isHomogeneous_X (R := ℝ) 0))
    have hkh : k.IsHomogeneous 1 := by
      dsimp [k]
      exact ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
        (MvPolynomial.isHomogeneous_X (R := ℝ) 1)).add
        ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
          (MvPolynomial.isHomogeneous_X (R := ℝ) 0))
    rcases (irreducible_iff.mp hf).2 hfac with hgu | hku
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hgh hg0 hgu
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hkh hk0 hku
  · let g : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 0 - MvPolynomial.C (x / y) * MvPolynomial.X 1
    let k : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.C a * MvPolynomial.X 0 +
        MvPolynomial.C (b + a * (x / y)) * MvPolynomial.X 1
    have hrel : a * x ^ 2 + b * x * y + c * y ^ 2 = 0 := by
      nlinarith [hEval]
    have hfac : f = g * k := by
      rw [hform]
      dsimp [g, k]
      apply MvPolynomial.funext
      intro p
      simp only [map_add, map_mul, map_sub, MvPolynomial.eval_C,
        MvPolynomial.eval_X, map_pow]
      field_simp [hy]
      linear_combination (p 1) ^ 2 * hrel
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
      exact (MvPolynomial.isHomogeneous_X (R := ℝ) 0).sub
        ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
          (MvPolynomial.isHomogeneous_X (R := ℝ) 1))
    have hkh : k.IsHomogeneous 1 := by
      dsimp [k]
      exact ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
        (MvPolynomial.isHomogeneous_X (R := ℝ) 0)).add
        ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
          (MvPolynomial.isHomogeneous_X (R := ℝ) 1))
    rcases (irreducible_iff.mp hf).2 hfac with hgu | hku
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hgh hg0 hgu
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hkh hk0 hku

theorem irreducible_totalDegree_three_planePolynomialUnitCircleInversion
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hEval : MvPolynomial.eval ![x, y] f = 0)
    (hNotCircle : ¬ IsAffineCirclePolynomial f) :
    Irreducible (planePolynomialUnitCircleInversion f) ∧
      (planePolynomialUnitCircleInversion f).totalDegree = 3 := by
  have hQ :=
    not_unitCirclePolynomial_dvd_planePolynomialUnitCircleInversion_of_totalDegree_eq_two_of_not_circle
      f hdeg hNotCircle
  have hlinear :=
    homogeneousComponent_one_ne_zero_of_irreducible_quadratic_of_nonzero_zero
      f hf hdeg hzero x y hxy hEval
  exact ⟨
    irreducible_planePolynomialUnitCircleInversion_of_irreducible_of_not_dvd_real
      f hf hQ,
    planePolynomialUnitCircleInversion_totalDegree_eq_three
      f hdeg hzero hlinear⟩

theorem infinite_rationalDistance_zeroLocus_irreducible_cubic_unitCircleInversion
    {u : Set ℂ}
    (huInf : u.Infinite)
    (huRat : EuclideanPairwiseRationalDistances u)
    (h0 : 0 ∈ u)
    (f : MvPolynomial (Fin 2) ℝ)
    (hIrred : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hEval : MvPolynomial.eval ![x, y] f = 0)
    (hNotCircle : ¬ IsAffineCirclePolynomial f)
    (hfZero : ∀ z ∈ u, MvPolynomial.eval ![z.re, z.im] f = 0) :
    let g := planePolynomialUnitCircleInversion f
    let v := rationalRadiusInversion 0 1 '' (u \ {0})
    Irreducible g ∧
      g.totalDegree = 3 ∧
      v.Infinite ∧
      EuclideanPairwiseRationalDistances v ∧
      ∀ w ∈ v, MvPolynomial.eval ![w.re, w.im] g = 0 := by
  rcases irreducible_totalDegree_three_planePolynomialUnitCircleInversion
      f hIrred hdeg hzero x y hxy hEval hNotCircle with
    ⟨hgIrred, hgDegree⟩
  rcases infinite_rationalDistance_zeroLocus_unitCircleInversion
      huInf huRat h0 f hfZero with ⟨hvInf, hvRat, hvZero⟩
  exact ⟨hgIrred, hgDegree, hvInf, hvRat, hvZero⟩

theorem rationalRadiusInversion_zero_one_involutive_injective :
    Function.Involutive (rationalRadiusInversion 0 1) ∧
      Function.Injective (rationalRadiusInversion 0 1) := by
  have hInv : Function.Involutive (rationalRadiusInversion 0 1) :=
    rationalRadiusInversion_zero_one_involutive
  exact ⟨hInv, hInv.injective⟩

theorem planePolynomialUnitCircleInversion_singularAtOrigin
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0) :
    let g := planePolynomialUnitCircleInversion f
    MvPolynomial.eval ![0, 0] g = 0 ∧
      ∀ i : Fin 2,
        MvPolynomial.eval ![0, 0] (MvPolynomial.pderiv i g) = 0 := by
  classical
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  have hQhom : Q.IsHomogeneous 2 := by
    dsimp [Q]
    exact (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 0 2).add
      (MvPolynomial.isHomogeneous_X_pow (R := ℝ) 1 2)
  have hsupport (m : Fin 2 →₀ ℕ) (hm : m ∈ f.support) :
      m.degree = 1 ∨ m.degree = 2 := by
    have hle : m.degree ≤ 2 := by
      simpa [hdeg] using MvPolynomial.le_totalDegree hm
    have hne : m.degree ≠ 0 := by
      intro hm0
      have hmzero : m = 0 := (Finsupp.degree_eq_zero_iff m).mp hm0
      subst m
      have hc0 : MvPolynomial.coeff 0 f = 0 := by
        simpa using congrArg (MvPolynomial.coeff 0) hzero
      exact (MvPolynomial.mem_support_iff.mp hm) hc0
    omega
  have hformula : planePolynomialUnitCircleInversion f =
      MvPolynomial.homogeneousComponent 1 f * Q +
        MvPolynomial.homogeneousComponent 2 f := by
    rw [planePolynomialUnitCircleInversion_eq_sum, Finsupp.sum, hdeg]
    change (∑ m ∈ f.support,
        MvPolynomial.monomial m (MvPolynomial.coeff m f) *
          Q ^ (2 - m.degree)) = _
    rw [← Finset.sum_filter_add_sum_filter_not f.support
      (fun m => m.degree = 1)]
    congr 1
    · rw [MvPolynomial.homogeneousComponent_apply, Finset.sum_mul]
      apply Finset.sum_congr rfl
      intro m hm
      have hmdeg : m.degree = 1 := (Finset.mem_filter.mp hm).2
      simp [hmdeg, Q]
    · rw [MvPolynomial.homogeneousComponent_apply]
      apply Finset.sum_congr
      · ext m
        simp only [Finset.mem_filter]
        constructor
        · rintro ⟨hm, hm1⟩
          exact ⟨hm, (hsupport m hm).resolve_left hm1⟩
        · rintro ⟨hm, hm2⟩
          exact ⟨hm, by omega⟩
      · intro m hm
        have hmdeg : m.degree = 2 := (Finset.mem_filter.mp hm).2
        simp [hmdeg]
  have hcubic :
      (MvPolynomial.homogeneousComponent 1 f * Q).IsHomogeneous 3 := by
    simpa using
      (MvPolynomial.homogeneousComponent_isHomogeneous 1 f).mul hQhom
  have hquad : (MvPolynomial.homogeneousComponent 2 f).IsHomogeneous 2 :=
    MvPolynomial.homogeneousComponent_isHomogeneous 2 f
  have eval_origin_of_homogeneous {p : MvPolynomial (Fin 2) ℝ} {n : ℕ}
      (hp : p.IsHomogeneous n) (hn : n ≠ 0) :
      MvPolynomial.eval ![0, 0] p = 0 := by
    rw [show ![0, 0] = (0 : Fin 2 → ℝ) by
      funext i
      fin_cases i <;> rfl]
    rw [MvPolynomial.eval_zero]
    exact hp.coeff_eq_zero (by simpa using hn.symm)
  rw [hformula]
  constructor
  · rw [map_add]
    rw [eval_origin_of_homogeneous hcubic (by omega),
      eval_origin_of_homogeneous hquad (by omega), zero_add]
  · intro i
    rw [map_add, map_add]
    have hcubic' :
        (MvPolynomial.pderiv i
          (MvPolynomial.homogeneousComponent 1 f * Q)).IsHomogeneous 2 := by
      simpa using hcubic.pderiv
    have hquad' :
        (MvPolynomial.pderiv i
          (MvPolynomial.homogeneousComponent 2 f)).IsHomogeneous 1 := by
      simpa using hquad.pderiv
    rw [eval_origin_of_homogeneous hcubic' (by omega),
      eval_origin_of_homogeneous hquad' (by omega), add_zero]

private lemma eval_smul_of_isHomogeneous_fin_two
    {p : MvPolynomial (Fin 2) ℝ} {n : ℕ}
    (hp : p.IsHomogeneous n) (t : ℝ) (x : Fin 2 → ℝ) :
    MvPolynomial.eval (fun i => t * x i) p =
      t ^ n * MvPolynomial.eval x p := by
  classical
  rw [MvPolynomial.eval_eq', MvPolynomial.eval_eq']
  rw [Finset.mul_sum]
  apply Finset.sum_congr rfl
  intro m hm
  have hmdeg : m.degree = n := by
    have hraw := hp (MvPolynomial.mem_support_iff.mp hm)
    change Finsupp.weight (fun _ : Fin 2 => 1) m = n at hraw
    rw [← Finsupp.degree_eq_weight_one] at hraw
    exact hraw
  simp only [mul_pow, Finset.prod_mul_distrib]
  have htprod : (∏ i, t ^ m i) = t ^ m.degree := by
    simpa [Finsupp.degree_eq_sum] using
      (Finset.prod_pow_eq_pow_sum Finset.univ (fun i => m i) t)
  rw [htprod, hmdeg]
  ring

theorem planePolynomialUnitCircleInversion_parametrized_zero
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (a b : ℝ)
    (hnum :
      MvPolynomial.eval ![a, b]
        (MvPolynomial.homogeneousComponent 2 f) ≠ 0)
    (hden :
      MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 1 f) *
        (a ^ 2 + b ^ 2) ≠ 0) :
    let t :=
      -MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 2 f) /
        (MvPolynomial.eval ![a, b]
            (MvPolynomial.homogeneousComponent 1 f) *
          (a ^ 2 + b ^ 2))
    t ≠ 0 ∧
      MvPolynomial.eval ![t * a, t * b]
        (planePolynomialUnitCircleInversion f) = 0 := by
  classical
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  have hsupport (m : Fin 2 →₀ ℕ) (hm : m ∈ f.support) :
      m.degree = 1 ∨ m.degree = 2 := by
    have hle : m.degree ≤ 2 := by
      simpa [hdeg] using MvPolynomial.le_totalDegree hm
    have hne : m.degree ≠ 0 := by
      intro hm0
      have hmzero : m = 0 := (Finsupp.degree_eq_zero_iff m).mp hm0
      subst m
      have hc0 : MvPolynomial.coeff 0 f = 0 := by
        simpa using congrArg (MvPolynomial.coeff 0) hzero
      exact (MvPolynomial.mem_support_iff.mp hm) hc0
    omega
  have hformula : planePolynomialUnitCircleInversion f =
      MvPolynomial.homogeneousComponent 1 f * Q +
        MvPolynomial.homogeneousComponent 2 f := by
    rw [planePolynomialUnitCircleInversion_eq_sum, Finsupp.sum, hdeg]
    change (∑ m ∈ f.support,
        MvPolynomial.monomial m (MvPolynomial.coeff m f) *
          Q ^ (2 - m.degree)) = _
    rw [← Finset.sum_filter_add_sum_filter_not f.support
      (fun m => m.degree = 1)]
    congr 1
    · rw [MvPolynomial.homogeneousComponent_apply, Finset.sum_mul]
      apply Finset.sum_congr rfl
      intro m hm
      have hmdeg : m.degree = 1 := (Finset.mem_filter.mp hm).2
      simp [hmdeg, Q]
    · rw [MvPolynomial.homogeneousComponent_apply]
      apply Finset.sum_congr
      · ext m
        simp only [Finset.mem_filter]
        constructor
        · rintro ⟨hm, hm1⟩
          exact ⟨hm, (hsupport m hm).resolve_left hm1⟩
        · rintro ⟨hm, hm2⟩
          exact ⟨hm, by omega⟩
      · intro m hm
        have hmdeg : m.degree = 2 := (Finset.mem_filter.mp hm).2
        simp [hmdeg]
  dsimp only
  let t : ℝ :=
    -MvPolynomial.eval ![a, b]
        (MvPolynomial.homogeneousComponent 2 f) /
      (MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 1 f) *
        (a ^ 2 + b ^ 2))
  change t ≠ 0 ∧
    MvPolynomial.eval ![t * a, t * b]
      (planePolynomialUnitCircleInversion f) = 0
  constructor
  · dsimp [t]
    exact div_ne_zero (neg_ne_zero.mpr hnum) hden
  · rw [hformula, map_add, map_mul]
    have hlin := eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 1 f)
      t ![a, b]
    have hquad := eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)
      t ![a, b]
    have hvec : ![t * a, t * b] = fun i => t * ![a, b] i := by
      funext i
      fin_cases i <;> rfl
    simp only [pow_one] at hlin
    rw [hvec]
    simp only [Q, map_add, map_pow, MvPolynomial.eval_X]
    rw [hlin, hquad]
    dsimp [t]
    field_simp [hden]
    ring

theorem homogeneousComponent_one_eval_ne_zero_of_irreducible_quadratic_at_nonzero_inversion_zero
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hg :
      MvPolynomial.eval ![x, y]
        (planePolynomialUnitCircleInversion f) = 0) :
    MvPolynomial.eval ![x, y]
      (MvPolynomial.homogeneousComponent 1 f) ≠ 0 := by
  classical
  intro hlinxy
  let Q : ℝ := x ^ 2 + y ^ 2
  have hQ : Q ≠ 0 := by
    dsimp [Q]
    rcases hxy with hx | hy
    · have hxpos : 0 < x ^ 2 := sq_pos_of_ne_zero hx
      nlinarith [sq_nonneg y]
    · have hypos : 0 < y ^ 2 := sq_pos_of_ne_zero hy
      nlinarith [sq_nonneg x]
  have hfinv : MvPolynomial.eval ![x / Q, y / Q] f = 0 := by
    have he := planePolynomialUnitCircleInversion_eval f x y hQ
    rw [hg, hdeg] at he
    exact (mul_eq_zero.mp he.symm).resolve_left (pow_ne_zero 2 hQ)
  have hvec : ![x / Q, y / Q] = fun i => Q⁻¹ * ![x, y] i := by
    funext i
    fin_cases i <;> simp [div_eq_mul_inv, mul_comm]
  have hlininv : MvPolynomial.eval ![x / Q, y / Q]
      (MvPolynomial.homogeneousComponent 1 f) = 0 := by
    rw [hvec, eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 1 f)]
    simp [hlinxy]
  have hdecomp := MvPolynomial.sum_homogeneousComponent f
  rw [hdeg] at hdecomp
  simp only [Finset.sum_range_succ, Finset.sum_range_zero, zero_add] at hdecomp
  have hquadinv : MvPolynomial.eval ![x / Q, y / Q]
      (MvPolynomial.homogeneousComponent 2 f) = 0 := by
    have he := congrArg (MvPolynomial.eval ![x / Q, y / Q]) hdecomp
    simpa [hzero, hlininv, hfinv] using he
  have hquadxy : MvPolynomial.eval ![x, y]
      (MvPolynomial.homogeneousComponent 2 f) = 0 := by
    have hs := eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 2 f) Q⁻¹ ![x, y]
    rw [← hvec, hquadinv] at hs
    exact (mul_eq_zero.mp hs.symm).resolve_left
      (pow_ne_zero 2 (inv_ne_zero hQ))
  have hlin_mem : MvPolynomial.homogeneousComponent 1 f ∈
      Submodule.span ℝ
        (Set.range (MvPolynomial.X : Fin 2 → MvPolynomial (Fin 2) ℝ)) := by
    rw [← MvPolynomial.homogeneousSubmodule_one_eq_span_X]
    exact MvPolynomial.homogeneousComponent_mem 1 f
  obtain ⟨de, hde⟩ :=
    (Submodule.mem_span_range_iff_exists_fun ℝ).mp hlin_mem
  have hlinform : MvPolynomial.homogeneousComponent 1 f =
      MvPolynomial.C (de 0) * MvPolynomial.X 0 +
      MvPolynomial.C (de 1) * MvPolynomial.X 1 := by
    rw [← hde, Fin.sum_univ_two]
    simp [MvPolynomial.smul_eq_C_mul]
  let a := MvPolynomial.coeff (Finsupp.single 0 2) f
  let b := MvPolynomial.coeff
    (Finsupp.single 0 1 + Finsupp.single 1 1) f
  let c := MvPolynomial.coeff (Finsupp.single 1 2) f
  have hquadform : MvPolynomial.homogeneousComponent 2 f =
      MvPolynomial.C a * MvPolynomial.X 0 ^ 2 +
      MvPolynomial.C b * (MvPolynomial.X 0 * MvPolynomial.X 1) +
      MvPolynomial.C c * MvPolynomial.X 1 ^ 2 := by
    simpa [a, b, c, MvPolynomial.monomial_eq,
      Finsupp.prod_fintype, Fin.prod_univ_two,
      MvPolynomial.coeff_homogeneousComponent,
      Finsupp.degree_eq_sum, Fin.sum_univ_two] using
      homogeneous_quadratic_eq_three_terms
        (MvPolynomial.homogeneousComponent 2 f)
        (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)
  have hfform : f =
      (MvPolynomial.C (de 0) * MvPolynomial.X 0 +
        MvPolynomial.C (de 1) * MvPolynomial.X 1) +
      (MvPolynomial.C a * MvPolynomial.X 0 ^ 2 +
        MvPolynomial.C b * (MvPolynomial.X 0 * MvPolynomial.X 1) +
        MvPolynomial.C c * MvPolynomial.X 1 ^ 2) := by
    calc
      f = MvPolynomial.homogeneousComponent 0 f +
          MvPolynomial.homogeneousComponent 1 f +
          MvPolynomial.homogeneousComponent 2 f := hdecomp.symm
      _ = _ := by rw [hzero, hlinform, hquadform]; ring
  rw [hlinform] at hlinxy
  rw [hquadform] at hquadxy
  simp only [map_add, map_mul, MvPolynomial.eval_C, MvPolynomial.eval_X,
    map_pow] at hlinxy hquadxy
  simp at hlinxy hquadxy
  rcases hxy with hx | hy
  · let L : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 1 - MvPolynomial.C (y / x) * MvPolynomial.X 0
    let k : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.C (de 1) + MvPolynomial.C c * MvPolynomial.X 1 +
        MvPolynomial.C (b + c * (y / x)) * MvPolynomial.X 0
    have hfac : f = L * k := by
      rw [hfform]
      dsimp [L, k]
      apply MvPolynomial.funext
      intro p
      simp only [map_add, map_mul, map_sub, MvPolynomial.eval_C,
        MvPolynomial.eval_X, map_pow]
      field_simp [hx]
      linear_combination (p 0 * x) * hlinxy + (p 0) ^ 2 * hquadxy
    have hL0 : L ≠ 0 := by
      intro hL
      have he := congrArg (MvPolynomial.eval ![0, 1]) hL
      simp [L] at he
    have hk0 : k ≠ 0 := by
      intro hk
      apply hf.ne_zero
      rw [hfac, hk, mul_zero]
    have hLhom : L.IsHomogeneous 1 := by
      dsimp [L]
      exact (MvPolynomial.isHomogeneous_X (R := ℝ) 1).sub
        ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
          (MvPolynomial.isHomogeneous_X (R := ℝ) 0))
    rcases (irreducible_iff.mp hf).2 hfac with hLu | hku
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hLhom hL0 hLu
    · have hkdeg := (MvPolynomial.isUnit_iff_totalDegree_of_isReduced.mp hku).2
      have hLdeg : L.totalDegree = 1 := hLhom.totalDegree hL0
      have hmuldeg := MvPolynomial.totalDegree_mul_of_isDomain hL0 hk0
      rw [← hfac, hdeg, hLdeg, hkdeg] at hmuldeg
      omega
  · let L : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.X 0 - MvPolynomial.C (x / y) * MvPolynomial.X 1
    let k : MvPolynomial (Fin 2) ℝ :=
      MvPolynomial.C (de 0) + MvPolynomial.C a * MvPolynomial.X 0 +
        MvPolynomial.C (b + a * (x / y)) * MvPolynomial.X 1
    have hfac : f = L * k := by
      rw [hfform]
      dsimp [L, k]
      apply MvPolynomial.funext
      intro p
      simp only [map_add, map_mul, map_sub, MvPolynomial.eval_C,
        MvPolynomial.eval_X, map_pow]
      field_simp [hy]
      linear_combination (p 1 * y) * hlinxy + (p 1) ^ 2 * hquadxy
    have hL0 : L ≠ 0 := by
      intro hL
      have he := congrArg (MvPolynomial.eval ![1, 0]) hL
      simp [L] at he
    have hk0 : k ≠ 0 := by
      intro hk
      apply hf.ne_zero
      rw [hfac, hk, mul_zero]
    have hLhom : L.IsHomogeneous 1 := by
      dsimp [L]
      exact (MvPolynomial.isHomogeneous_X (R := ℝ) 0).sub
        ((MvPolynomial.isHomogeneous_C (σ := Fin 2) (R := ℝ) _).mul
          (MvPolynomial.isHomogeneous_X (R := ℝ) 1))
    rcases (irreducible_iff.mp hf).2 hfac with hLu | hku
    · exact not_isUnit_of_isHomogeneous_one_ne_zero hLhom hL0 hLu
    · have hkdeg := (MvPolynomial.isUnit_iff_totalDegree_of_isReduced.mp hku).2
      have hLdeg : L.totalDegree = 1 := hLhom.totalDegree hL0
      have hmuldeg := MvPolynomial.totalDegree_mul_of_isDomain hL0 hk0
      rw [← hfac, hdeg, hLdeg, hkdeg] at hmuldeg
      omega

theorem planePolynomialUnitCircleInversion_parametrization_complete
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hg :
      MvPolynomial.eval ![x, y]
        (planePolynomialUnitCircleInversion f) = 0) :
    let A :=
      MvPolynomial.eval ![x, y]
        (MvPolynomial.homogeneousComponent 1 f)
    let B :=
      MvPolynomial.eval ![x, y]
        (MvPolynomial.homogeneousComponent 2 f)
    let t := -B / (A * (x ^ 2 + y ^ 2))
    B ≠ 0 ∧
      A * (x ^ 2 + y ^ 2) ≠ 0 ∧
      t = 1 ∧
      MvPolynomial.eval ![t * x, t * y]
        (planePolynomialUnitCircleInversion f) = 0 := by
  classical
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  have hsupport (m : Fin 2 →₀ ℕ) (hm : m ∈ f.support) :
      m.degree = 1 ∨ m.degree = 2 := by
    have hle : m.degree ≤ 2 := by
      simpa [hdeg] using MvPolynomial.le_totalDegree hm
    have hne : m.degree ≠ 0 := by
      intro hm0
      have hmzero : m = 0 := (Finsupp.degree_eq_zero_iff m).mp hm0
      subst m
      have hc0 : MvPolynomial.coeff 0 f = 0 := by
        simpa using congrArg (MvPolynomial.coeff 0) hzero
      exact (MvPolynomial.mem_support_iff.mp hm) hc0
    omega
  have hformula : planePolynomialUnitCircleInversion f =
      MvPolynomial.homogeneousComponent 1 f * Q +
        MvPolynomial.homogeneousComponent 2 f := by
    rw [planePolynomialUnitCircleInversion_eq_sum, Finsupp.sum, hdeg]
    change (∑ m ∈ f.support,
        MvPolynomial.monomial m (MvPolynomial.coeff m f) *
          Q ^ (2 - m.degree)) = _
    rw [← Finset.sum_filter_add_sum_filter_not f.support
      (fun m => m.degree = 1)]
    congr 1
    · rw [MvPolynomial.homogeneousComponent_apply, Finset.sum_mul]
      apply Finset.sum_congr rfl
      intro m hm
      have hmdeg : m.degree = 1 := (Finset.mem_filter.mp hm).2
      simp [hmdeg, Q]
    · rw [MvPolynomial.homogeneousComponent_apply]
      apply Finset.sum_congr
      · ext m
        simp only [Finset.mem_filter]
        constructor
        · rintro ⟨hm, hm1⟩
          exact ⟨hm, (hsupport m hm).resolve_left hm1⟩
        · rintro ⟨hm, hm2⟩
          exact ⟨hm, by omega⟩
      · intro m hm
        have hmdeg : m.degree = 2 := (Finset.mem_filter.mp hm).2
        simp [hmdeg]
  dsimp only
  have hA : MvPolynomial.eval ![x, y]
      (MvPolynomial.homogeneousComponent 1 f) ≠ 0 :=
    homogeneousComponent_one_eval_ne_zero_of_irreducible_quadratic_at_nonzero_inversion_zero
      f hf hdeg hzero x y hxy hg
  have hnorm : x ^ 2 + y ^ 2 ≠ 0 := by
    rcases hxy with hx | hy
    · nlinarith [sq_pos_of_ne_zero hx, sq_nonneg y]
    · nlinarith [sq_nonneg x, sq_pos_of_ne_zero hy]
  have hden : MvPolynomial.eval ![x, y]
        (MvPolynomial.homogeneousComponent 1 f) *
      (x ^ 2 + y ^ 2) ≠ 0 :=
    mul_ne_zero hA hnorm
  have hsum :
      MvPolynomial.eval ![x, y]
          (MvPolynomial.homogeneousComponent 1 f) *
        (x ^ 2 + y ^ 2) +
      MvPolynomial.eval ![x, y]
          (MvPolynomial.homogeneousComponent 2 f) = 0 := by
    rw [hformula, map_add, map_mul] at hg
    simpa [Q] using hg
  have hB : MvPolynomial.eval ![x, y]
      (MvPolynomial.homogeneousComponent 2 f) ≠ 0 := by
    intro hB0
    rw [hB0, add_zero] at hsum
    exact hden hsum
  have hrel : MvPolynomial.eval ![x, y]
        (MvPolynomial.homogeneousComponent 2 f) =
      -(MvPolynomial.eval ![x, y]
          (MvPolynomial.homogeneousComponent 1 f) *
        (x ^ 2 + y ^ 2)) := by
    linarith
  refine ⟨hB, hden, ?_, ?_⟩
  · rw [hrel]
    field_simp
  · rw [hrel]
    simp [hden]
    exact hg

theorem planePolynomialUnitCircleInversion_parametrization_smul
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (a b c : ℝ)
    (hc : c ≠ 0)
    (hnum :
      MvPolynomial.eval ![a, b]
        (MvPolynomial.homogeneousComponent 2 f) ≠ 0)
    (hden :
      MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 1 f) *
        (a ^ 2 + b ^ 2) ≠ 0) :
    let t :=
      -MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 2 f) /
        (MvPolynomial.eval ![a, b]
            (MvPolynomial.homogeneousComponent 1 f) *
          (a ^ 2 + b ^ 2))
    let tc :=
      -MvPolynomial.eval ![c * a, c * b]
          (MvPolynomial.homogeneousComponent 2 f) /
        (MvPolynomial.eval ![c * a, c * b]
            (MvPolynomial.homogeneousComponent 1 f) *
          ((c * a) ^ 2 + (c * b) ^ 2))
    tc * (c * a) = t * a ∧
      tc * (c * b) = t * b ∧
      MvPolynomial.eval ![tc * (c * a), tc * (c * b)]
        (planePolynomialUnitCircleInversion f) = 0 := by
  classical
  dsimp only
  let A := MvPolynomial.eval ![a, b]
    (MvPolynomial.homogeneousComponent 1 f)
  let B := MvPolynomial.eval ![a, b]
    (MvPolynomial.homogeneousComponent 2 f)
  let Ac := MvPolynomial.eval ![c * a, c * b]
    (MvPolynomial.homogeneousComponent 1 f)
  let Bc := MvPolynomial.eval ![c * a, c * b]
    (MvPolynomial.homogeneousComponent 2 f)
  let N := a ^ 2 + b ^ 2
  let Nc := (c * a) ^ 2 + (c * b) ^ 2
  let t := -B / (A * N)
  let tc := -Bc / (Ac * Nc)
  change tc * (c * a) = t * a ∧
    tc * (c * b) = t * b ∧
    MvPolynomial.eval ![tc * (c * a), tc * (c * b)]
      (planePolynomialUnitCircleInversion f) = 0
  have hvec : ![c * a, c * b] = fun i => c * ![a, b] i := by
    funext i
    fin_cases i <;> rfl
  have hAc : Ac = c * A := by
    dsimp [Ac, A]
    rw [hvec, eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 1 f)]
    simp
  have hBc : Bc = c ^ 2 * B := by
    dsimp [Bc, B]
    rw [hvec, eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)]
  have hNc : Nc = c ^ 2 * N := by
    dsimp [Nc, N]
    ring
  have htc : tc * c = t := by
    dsimp [tc, t]
    rw [hAc, hBc, hNc]
    dsimp [A, B, N] at hden ⊢
    field_simp [hc, hden]
  have ha : tc * (c * a) = t * a := by
    calc
      tc * (c * a) = (tc * c) * a := by ring
      _ = t * a := by rw [htc]
  have hb : tc * (c * b) = t * b := by
    calc
      tc * (c * b) = (tc * c) * b := by ring
      _ = t * b := by rw [htc]
  refine ⟨ha, hb, ?_⟩
  rw [ha, hb]
  have hz := (planePolynomialUnitCircleInversion_parametrized_zero
    f hdeg hzero a b hnum hden).2
  simpa [t, A, B, N] using hz

theorem inversionCubicAdmissibleVector_smul_iff
    (f : MvPolynomial (Fin 2) ℝ)
    (a b c : ℝ)
    (hc : c ≠ 0) :
    (MvPolynomial.eval ![c * a, c * b]
          (MvPolynomial.homogeneousComponent 2 f) ≠ 0 ∧
      MvPolynomial.eval ![c * a, c * b]
          (MvPolynomial.homogeneousComponent 1 f) *
        ((c * a) ^ 2 + (c * b) ^ 2) ≠ 0) ↔
    (MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 2 f) ≠ 0 ∧
      MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 1 f) *
        (a ^ 2 + b ^ 2) ≠ 0) := by
  classical
  have hvec : ![c * a, c * b] = fun i => c * ![a, b] i := by
    funext i
    fin_cases i <;> rfl
  have hquad :
      MvPolynomial.eval ![c * a, c * b]
          (MvPolynomial.homogeneousComponent 2 f) =
        c ^ 2 * MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 2 f) := by
    rw [hvec, eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)]
  have hlin :
      MvPolynomial.eval ![c * a, c * b]
          (MvPolynomial.homogeneousComponent 1 f) =
        c * MvPolynomial.eval ![a, b]
          (MvPolynomial.homogeneousComponent 1 f) := by
    rw [hvec, eval_smul_of_isHomogeneous_fin_two
      (MvPolynomial.homogeneousComponent_isHomogeneous 1 f)]
    simp
  have hnorm : (c * a) ^ 2 + (c * b) ^ 2 =
      c ^ 2 * (a ^ 2 + b ^ 2) := by
    ring
  rw [hquad, hlin, hnorm]
  simp [hc]

/-- A nonzero direction on which the radial cubic parametrization is defined. -/
def inversionCubicAdmissibleVector (f : MvPolynomial (Fin 2) ℝ)
    (v : Fin 2 → ℝ) : Prop :=
  MvPolynomial.eval v (MvPolynomial.homogeneousComponent 2 f) ≠ 0 ∧
    MvPolynomial.eval v (MvPolynomial.homogeneousComponent 1 f) *
      (v 0 ^ 2 + v 1 ^ 2) ≠ 0

/-- Admissible real projective directions for the radial parametrization. -/
def inversionCubicAdmissibleDirections (f : MvPolynomial (Fin 2) ℝ) :=
  {p : Projectivization ℝ (Fin 2 → ℝ) //
    inversionCubicAdmissibleVector f p.rep}

/-- The non-origin real zero locus of the inverted polynomial. -/
def inversionCubicPuncturedZeroLocus (f : MvPolynomial (Fin 2) ℝ) :=
  {q : Fin 2 → ℝ //
    q ≠ 0 ∧
      MvPolynomial.eval q (planePolynomialUnitCircleInversion f) = 0}

/-- The radial point associated to an admissible direction vector. -/
noncomputable def planePolynomialUnitCircleInversionParametrizedVector
    (f : MvPolynomial (Fin 2) ℝ) (v : Fin 2 → ℝ) : Fin 2 → ℝ :=
  let t :=
    -MvPolynomial.eval v (MvPolynomial.homogeneousComponent 2 f) /
      (MvPolynomial.eval v (MvPolynomial.homogeneousComponent 1 f) *
        (v 0 ^ 2 + v 1 ^ 2))
  ![t * v 0, t * v 1]

/-- The representative-based radial parametrization on admissible projective
directions.  Scaling invariance makes its value independent of the chosen
representative of the projective point. -/
noncomputable def planePolynomialUnitCircleInversionProjectiveParametrization
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0) :
    inversionCubicAdmissibleDirections f →
      inversionCubicPuncturedZeroLocus f := fun p => by
  let v := p.1.rep
  let t :=
    -MvPolynomial.eval v (MvPolynomial.homogeneousComponent 2 f) /
      (MvPolynomial.eval v (MvPolynomial.homogeneousComponent 1 f) *
        (v 0 ^ 2 + v 1 ^ 2))
  have hv : v ≠ 0 := p.1.rep_nonzero
  have hadm : inversionCubicAdmissibleVector f v := p.2
  have hvcoords : ![v 0, v 1] = v := by
    funext i
    fin_cases i <;> rfl
  have ht : t ≠ 0 := div_ne_zero (neg_ne_zero.mpr hadm.1) hadm.2
  refine ⟨![t * v 0, t * v 1], ?_, ?_⟩
  · intro hz
    apply hv
    funext i
    fin_cases i
    · have hi := congrFun hz 0
      simpa [ht] using hi
    · have hi := congrFun hz 1
      simpa [ht] using hi
  · have hz := (planePolynomialUnitCircleInversion_parametrized_zero
      f hdeg hzero (v 0) (v 1) ?_ ?_).2
    · rw [hvcoords] at hz
      simpa [t] using hz
    · rw [hvcoords]
      exact hadm.1
    · rw [hvcoords]
      exact hadm.2

theorem planePolynomialUnitCircleInversion_projectiveParametrization_bijective
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0) :
    Function.Bijective
      (planePolynomialUnitCircleInversionProjectiveParametrization
        f hdeg hzero) := by
  classical
  constructor
  · intro p q hpq
    apply Subtype.ext
    rw [← Projectivization.mk_rep p.1, ← Projectivization.mk_rep q.1]
    apply (Projectivization.mk_eq_mk_iff' ℝ
      p.1.rep q.1.rep p.1.rep_nonzero q.1.rep_nonzero).2
    let v := p.1.rep
    let w := q.1.rep
    let t :=
      -MvPolynomial.eval v (MvPolynomial.homogeneousComponent 2 f) /
        (MvPolynomial.eval v (MvPolynomial.homogeneousComponent 1 f) *
          (v 0 ^ 2 + v 1 ^ 2))
    let u :=
      -MvPolynomial.eval w (MvPolynomial.homogeneousComponent 2 f) /
        (MvPolynomial.eval w (MvPolynomial.homogeneousComponent 1 f) *
          (w 0 ^ 2 + w 1 ^ 2))
    have ht : t ≠ 0 :=
      div_ne_zero (neg_ne_zero.mpr p.2.1) p.2.2
    have hu : u ≠ 0 :=
      div_ne_zero (neg_ne_zero.mpr q.2.1) q.2.2
    have he := congrArg Subtype.val hpq
    change ![t * v 0, t * v 1] = ![u * w 0, u * w 1] at he
    refine ⟨u / t, ?_⟩
    funext i
    simp only [Pi.smul_apply, smul_eq_mul]
    fin_cases i
    · have hi := congrFun he 0
      dsimp at hi ⊢
      field_simp [ht]
      nlinarith
    · have hi := congrFun he 1
      dsimp at hi ⊢
      field_simp [ht]
      nlinarith
  · intro q
    let x : Fin 2 → ℝ := q.1
    have hx : x ≠ 0 := q.2.1
    have hxy : x 0 ≠ 0 ∨ x 1 ≠ 0 := by
      by_contra h
      push_neg at h
      apply hx
      funext i
      fin_cases i
      · exact h.1
      · exact h.2
    have hxcoords : ![x 0, x 1] = x := by
      funext i
      fin_cases i <;> rfl
    have hqxzero :
        MvPolynomial.eval ![x 0, x 1]
          (planePolynomialUnitCircleInversion f) = 0 := by
      rw [hxcoords]
      exact q.2.2
    have hcomplete :=
      planePolynomialUnitCircleInversion_parametrization_complete
        f hf hdeg hzero (x 0) (x 1) hxy hqxzero
    dsimp only at hcomplete
    let p₀ := Projectivization.mk ℝ x hx
    obtain ⟨c, hc⟩ := Projectivization.exists_smul_eq_mk_rep ℝ x hx
    have hc0 : (c : ℝ) ≠ 0 := Units.ne_zero c
    have hrepcoords : ![(c : ℝ) * x 0, (c : ℝ) * x 1] = p₀.rep := by
      calc
        ![(c : ℝ) * x 0, (c : ℝ) * x 1] =
            fun i => (c : ℝ) * x i := by
              funext i
              fin_cases i <;> rfl
        _ = p₀.rep := by
          simpa [p₀, Pi.smul_apply, smul_eq_mul] using hc
    have hadmscaled :=
      (inversionCubicAdmissibleVector_smul_iff
        f (x 0) (x 1) (c : ℝ) hc0).2 ⟨hcomplete.1, hcomplete.2.1⟩
    have hadmrep : inversionCubicAdmissibleVector f p₀.rep := by
      rw [← hrepcoords]
      exact hadmscaled
    let p : inversionCubicAdmissibleDirections f := ⟨p₀, hadmrep⟩
    refine ⟨p, ?_⟩
    apply Subtype.ext
    have hsmul := planePolynomialUnitCircleInversion_parametrization_smul
      f hdeg hzero (x 0) (x 1) (c : ℝ) hc0 hcomplete.1 hcomplete.2.1
    dsimp only at hsmul
    rw [hcomplete.2.2.1] at hsmul
    funext i
    fin_cases i
    · change
        (-MvPolynomial.eval p₀.rep (MvPolynomial.homogeneousComponent 2 f) /
            (MvPolynomial.eval p₀.rep (MvPolynomial.homogeneousComponent 1 f) *
              (p₀.rep 0 ^ 2 + p₀.rep 1 ^ 2))) * p₀.rep 0 = x 0
      rw [← hrepcoords]
      simpa using hsmul.1
    · change
        (-MvPolynomial.eval p₀.rep (MvPolynomial.homogeneousComponent 2 f) /
            (MvPolynomial.eval p₀.rep (MvPolynomial.homogeneousComponent 1 f) *
              (p₀.rep 0 ^ 2 + p₀.rep 1 ^ 2))) * p₀.rep 1 = x 1
      rw [← hrepcoords]
      simpa using hsmul.2.1

/-- The generic radial parametrization of the inverted quadratic, with
projective direction `[1, X]`. -/
noncomputable def planePolynomialUnitCircleInversionRatFuncParametrization
    (f : MvPolynomial (Fin 2) ℝ)
    (_hdeg : f.totalDegree = 2)
    (_hzero : MvPolynomial.homogeneousComponent 0 f = 0) :
    MvPolynomial (Fin 2) ℝ →ₐ[ℝ] RatFunc ℝ :=
  let A := MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
    (MvPolynomial.homogeneousComponent 1 f)
  let B := MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
    (MvPolynomial.homogeneousComponent 2 f)
  let t := -B / (A * (1 + RatFunc.X ^ 2))
  MvPolynomial.aeval ![t, t * RatFunc.X]

private lemma eval₂_ratFunc_smul_of_isHomogeneous_fin_two
    {p : MvPolynomial (Fin 2) ℝ} {n : ℕ}
    (hp : p.IsHomogeneous n) (t : RatFunc ℝ) (x : Fin 2 → RatFunc ℝ) :
    MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) (fun i => t * x i) p =
      t ^ n * MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) x p := by
  classical
  rw [MvPolynomial.eval₂_eq', MvPolynomial.eval₂_eq']
  rw [Finset.mul_sum]
  apply Finset.sum_congr rfl
  intro m hm
  have hmdeg : m.degree = n := by
    have hraw := hp (MvPolynomial.mem_support_iff.mp hm)
    change Finsupp.weight (fun _ : Fin 2 => 1) m = n at hraw
    rw [← Finsupp.degree_eq_weight_one] at hraw
    exact hraw
  simp only [mul_pow, Finset.prod_mul_distrib]
  have htprod : (∏ i, t ^ m i) = t ^ m.degree := by
    simpa [Finsupp.degree_eq_sum] using
      (Finset.prod_pow_eq_pow_sum Finset.univ (fun i => m i) t)
  rw [htprod, hmdeg]
  ring

private theorem planePolynomialUnitCircleInversionRatFuncParametrization_vanishes
    (f : MvPolynomial (Fin 2) ℝ)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0) :
    planePolynomialUnitCircleInversionRatFuncParametrization f hdeg hzero
        (planePolynomialUnitCircleInversion f) = 0 := by
  classical
  let Q : MvPolynomial (Fin 2) ℝ :=
    MvPolynomial.X 0 ^ 2 + MvPolynomial.X 1 ^ 2
  have hsupport (m : Fin 2 →₀ ℕ) (hm : m ∈ f.support) :
      m.degree = 1 ∨ m.degree = 2 := by
    have hle : m.degree ≤ 2 := by
      simpa [hdeg] using MvPolynomial.le_totalDegree hm
    have hne : m.degree ≠ 0 := by
      intro hm0
      have hmzero : m = 0 := (Finsupp.degree_eq_zero_iff m).mp hm0
      subst m
      have hc0 : MvPolynomial.coeff 0 f = 0 := by
        simpa using congrArg (MvPolynomial.coeff 0) hzero
      exact (MvPolynomial.mem_support_iff.mp hm) hc0
    omega
  have hformula : planePolynomialUnitCircleInversion f =
      MvPolynomial.homogeneousComponent 1 f * Q +
        MvPolynomial.homogeneousComponent 2 f := by
    rw [planePolynomialUnitCircleInversion_eq_sum, Finsupp.sum, hdeg]
    change (∑ m ∈ f.support,
        MvPolynomial.monomial m (MvPolynomial.coeff m f) *
          Q ^ (2 - m.degree)) = _
    rw [← Finset.sum_filter_add_sum_filter_not f.support
      (fun m => m.degree = 1)]
    congr 1
    · rw [MvPolynomial.homogeneousComponent_apply, Finset.sum_mul]
      apply Finset.sum_congr rfl
      intro m hm
      have hmdeg : m.degree = 1 := (Finset.mem_filter.mp hm).2
      simp [hmdeg, Q]
    · rw [MvPolynomial.homogeneousComponent_apply]
      apply Finset.sum_congr
      · ext m
        simp only [Finset.mem_filter]
        constructor
        · rintro ⟨hm, hm1⟩
          exact ⟨hm, (hsupport m hm).resolve_left hm1⟩
        · rintro ⟨hm, hm2⟩
          exact ⟨hm, by omega⟩
      · intro m hm
        have hmdeg : m.degree = 2 := (Finset.mem_filter.mp hm).2
        simp [hmdeg]
  let A : RatFunc ℝ :=
    MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
      (MvPolynomial.homogeneousComponent 1 f)
  let B : RatFunc ℝ :=
    MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
      (MvPolynomial.homogeneousComponent 2 f)
  let t := -B / (A * (1 + RatFunc.X ^ 2))
  change MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![t, t * RatFunc.X]
      (planePolynomialUnitCircleInversion f) = 0
  rw [hformula, MvPolynomial.eval₂_add, MvPolynomial.eval₂_mul]
  have hlin := eval₂_ratFunc_smul_of_isHomogeneous_fin_two
    (MvPolynomial.homogeneousComponent_isHomogeneous 1 f)
    t ![1, RatFunc.X]
  have hquad := eval₂_ratFunc_smul_of_isHomogeneous_fin_two
    (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)
    t ![1, RatFunc.X]
  have hvec : ![t, t * RatFunc.X] = fun i => t * ![1, RatFunc.X] i := by
    funext i
    fin_cases i <;> simp
  rw [hvec]
  simp only [Q, MvPolynomial.eval₂_add, MvPolynomial.eval₂_pow,
    MvPolynomial.eval₂_X]
  rw [hlin, hquad]
  simp only [pow_one]
  dsimp [t, A, B]
  field_simp
  ring

theorem planePolynomialUnitCircleInversionRatFuncParametrization_apply_inversion
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hEval : MvPolynomial.eval ![x, y] f = 0)
    (hNotCircle : ¬ IsAffineCirclePolynomial f) :
    planePolynomialUnitCircleInversionRatFuncParametrization
        f hdeg hzero
        (planePolynomialUnitCircleInversion f) = 0 := by
  exact planePolynomialUnitCircleInversionRatFuncParametrization_vanishes
    f hdeg hzero

theorem planePolynomialUnitCircleInversionRatFuncParametrization_X_one_div_X_zero
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hEval : MvPolynomial.eval ![x, y] f = 0) :
    let φ :=
      planePolynomialUnitCircleInversionRatFuncParametrization f hdeg hzero
    φ (MvPolynomial.X 1) / φ (MvPolynomial.X 0) = RatFunc.X := by
  classical
  let A : RatFunc ℝ :=
    MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
      (MvPolynomial.homogeneousComponent 1 f)
  let B : RatFunc ℝ :=
    MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
      (MvPolynomial.homogeneousComponent 2 f)
  let t : RatFunc ℝ := -B / (A * (1 + RatFunc.X ^ 2))
  have hlin0 : MvPolynomial.homogeneousComponent 1 f ≠ 0 :=
    homogeneousComponent_one_ne_zero_of_irreducible_quadratic_of_nonzero_zero
      f hf hdeg hzero x y hxy hEval
  have hlin_mem : MvPolynomial.homogeneousComponent 1 f ∈
      Submodule.span ℝ
        (Set.range (MvPolynomial.X : Fin 2 → MvPolynomial (Fin 2) ℝ)) := by
    rw [← MvPolynomial.homogeneousSubmodule_one_eq_span_X]
    exact MvPolynomial.homogeneousComponent_mem 1 f
  obtain ⟨de, hde⟩ :=
    (Submodule.mem_span_range_iff_exists_fun ℝ).mp hlin_mem
  have hlinform : MvPolynomial.homogeneousComponent 1 f =
      MvPolynomial.C (de 0) * MvPolynomial.X 0 +
        MvPolynomial.C (de 1) * MvPolynomial.X 1 := by
    rw [← hde, Fin.sum_univ_two]
    simp [MvPolynomial.smul_eq_C_mul]
  have hA : A ≠ 0 := by
    intro hAzero
    have heval :
        MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
            (MvPolynomial.homogeneousComponent 1 f) = 0 := by
      exact hAzero
    rw [hlinform] at heval
    simp at heval
    have hpoly :
        (Polynomial.C (de 0) + Polynomial.C (de 1) * Polynomial.X :
          Polynomial ℝ) = 0 := by
      apply RatFunc.algebraMap_injective ℝ
      simpa using heval
    have hde0 := congrArg (fun p : Polynomial ℝ => p.coeff 0) hpoly
    have hde1 := congrArg (fun p : Polynomial ℝ => p.coeff 1) hpoly
    simp at hde0 hde1
    apply hlin0
    rw [hlinform, hde0, hde1]
    simp
  have hquad0 : MvPolynomial.homogeneousComponent 2 f ≠ 0 := by
    intro hquad
    have hf0 : f ≠ 0 := by
      intro hfzero
      rw [hfzero] at hdeg
      simp at hdeg
    obtain ⟨m, hm, hmdeg⟩ := f.support.exists_mem_eq_sup
      (Finsupp.support_nonempty_iff.mpr hf0)
      (fun m : Fin 2 →₀ ℕ => m.degree)
    have hmdeg' : m.degree = 2 := by
      calc
        m.degree = f.support.sup (fun m => m.degree) := hmdeg.symm
        _ = f.totalDegree := rfl
        _ = 2 := hdeg
    have hmcoeff : MvPolynomial.coeff m f ≠ 0 :=
      MvPolynomial.mem_support_iff.mp hm
    have hc := congrArg (MvPolynomial.coeff m) hquad
    simp [MvPolynomial.coeff_homogeneousComponent, hmdeg', hmcoeff] at hc
  let a := MvPolynomial.coeff (Finsupp.single 0 2)
    (MvPolynomial.homogeneousComponent 2 f)
  let b := MvPolynomial.coeff
    (Finsupp.single 0 1 + Finsupp.single 1 1)
    (MvPolynomial.homogeneousComponent 2 f)
  let c := MvPolynomial.coeff (Finsupp.single 1 2)
    (MvPolynomial.homogeneousComponent 2 f)
  have hquadform : MvPolynomial.homogeneousComponent 2 f =
      MvPolynomial.C a * MvPolynomial.X 0 ^ 2 +
      MvPolynomial.C b * (MvPolynomial.X 0 * MvPolynomial.X 1) +
      MvPolynomial.C c * MvPolynomial.X 1 ^ 2 := by
    simpa [a, b, c, MvPolynomial.monomial_eq,
      Finsupp.prod_fintype, Fin.prod_univ_two,
      Finsupp.degree_eq_sum, Fin.sum_univ_two] using
      homogeneous_quadratic_eq_three_terms
        (MvPolynomial.homogeneousComponent 2 f)
        (MvPolynomial.homogeneousComponent_isHomogeneous 2 f)
  have hB : B ≠ 0 := by
    intro hBzero
    have heval :
        MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) ![1, RatFunc.X]
            (MvPolynomial.homogeneousComponent 2 f) = 0 := by
      exact hBzero
    rw [hquadform] at heval
    simp at heval
    have hpoly :
        (Polynomial.C a + Polynomial.C b * Polynomial.X +
          Polynomial.C c * Polynomial.X ^ 2 : Polynomial ℝ) = 0 := by
      apply RatFunc.algebraMap_injective ℝ
      simpa using heval
    have ha := congrArg (fun p : Polynomial ℝ => p.coeff 0) hpoly
    have hb := congrArg (fun p : Polynomial ℝ => p.coeff 1) hpoly
    have hc := congrArg (fun p : Polynomial ℝ => p.coeff 2) hpoly
    simp at ha hb hc
    apply hquad0
    rw [hquadform, ha, hb, hc]
    simp
  have hnorm : (1 + RatFunc.X ^ 2 : RatFunc ℝ) ≠ 0 := by
    intro h
    have hpoly : (1 + (Polynomial.X : Polynomial ℝ) ^ 2) = 0 := by
      apply RatFunc.algebraMap_injective ℝ
      simpa using h
    have hc := congrArg (fun p : Polynomial ℝ => p.coeff 0) hpoly
    norm_num at hc
  have ht : t ≠ 0 :=
    div_ne_zero (neg_ne_zero.mpr hB) (mul_ne_zero hA hnorm)
  dsimp [planePolynomialUnitCircleInversionRatFuncParametrization]
  simp only [MvPolynomial.aeval_X]
  change
    ((-B / (A * (1 + RatFunc.X ^ 2))) * RatFunc.X) /
      (-B / (A * (1 + RatFunc.X ^ 2))) = RatFunc.X
  change (t * RatFunc.X) / t = RatFunc.X
  field_simp [ht]

private theorem eval₂_resultant_eq_zero_of_common_zero
    {K L : Type*} [Field K] [Field L] [Algebra K L]
    (f g : Polynomial (Polynomial K)) (x y : L)
    (hf : (f.map (Polynomial.mapRingHom (algebraMap K L))).evalEval x y = 0)
    (hg : (g.map (Polynomial.mapRingHom (algebraMap K L))).evalEval x y = 0)
    (hdeg : f.natDegree ≠ 0 ∨ g.natDegree ≠ 0) :
    Polynomial.eval₂ (algebraMap K L) x (Polynomial.resultant f g) = 0 := by
  have hinj : Function.Injective (algebraMap K L) := RingHom.injective _
  have hfdeg : (f.map (Polynomial.mapRingHom (algebraMap K L))).natDegree =
      f.natDegree :=
    Polynomial.natDegree_map_eq_of_injective
      (Polynomial.map_injective (algebraMap K L) hinj) f
  have hgdeg : (g.map (Polynomial.mapRingHom (algebraMap K L))).natDegree =
      g.natDegree :=
    Polynomial.natDegree_map_eq_of_injective
      (Polynomial.map_injective (algebraMap K L) hinj) g
  have h := eval_resultant_eq_zero_of_common_zero
    (f.map (Polynomial.mapRingHom (algebraMap K L)))
    (g.map (Polynomial.mapRingHom (algebraMap K L))) x y hf hg (by simpa [hfdeg, hgdeg] using hdeg)
  rw [hfdeg, hgdeg, Polynomial.resultant_map_map] at h
  simpa using h

private theorem exists_elimination_polynomial_aeval_zero
    {K L : Type*} [Field K] [Field L] [Algebra K L]
    (f g : Polynomial (Polynomial K)) (hf : Irreducible f) (hndvd : ¬f ∣ g)
    (x y : L)
    (hfx : (f.map (Polynomial.mapRingHom (algebraMap K L))).evalEval x y = 0)
    (hgx : (g.map (Polynomial.mapRingHom (algebraMap K L))).evalEval x y = 0) :
    ∃ r : Polynomial K, r ≠ 0 ∧ Polynomial.aeval x r = 0 := by
  by_cases hdeg : f.natDegree ≠ 0 ∨ g.natDegree ≠ 0
  · refine ⟨Polynomial.resultant f g,
      resultant_ne_zero_of_irreducible_not_dvd f g hf hndvd, ?_⟩
    simpa [Polynomial.aeval_def] using
      eval₂_resultant_eq_zero_of_common_zero f g x y hfx hgx hdeg
  · have hfdeg : f.natDegree = 0 := not_ne_iff.mp (not_or.mp hdeg).1
    have hgdeg : g.natDegree = 0 := not_ne_iff.mp (not_or.mp hdeg).2
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
    have hg'x :
        (g'.map (Polynomial.mapRingHom (algebraMap K L))).evalEval x y = 0 := by
      simp [g', hfx, hgx]
    refine ⟨Polynomial.resultant f g',
      resultant_ne_zero_of_irreducible_not_dvd f g' hf hndvd', ?_⟩
    simpa [Polynomial.aeval_def] using
      eval₂_resultant_eq_zero_of_common_zero f g' x y hfx hg'x (Or.inr hg'deg)

private theorem planePolynomialEquiv_X_zero
    (K : Type*) [Field K] :
    planePolynomialEquiv K (MvPolynomial.X 0) = Polynomial.X := by
  unfold planePolynomialEquiv
  change Polynomial.map _
    (MvPolynomial.finSuccEquiv K 1 (MvPolynomial.X 0)) = _
  rw [MvPolynomial.finSuccEquiv_apply]
  simp

private theorem planePolynomialEquiv_X_one
    (K : Type*) [Field K] :
    planePolynomialEquiv K (MvPolynomial.X 1) =
      Polynomial.C Polynomial.X := by
  unfold planePolynomialEquiv
  change Polynomial.map _
    (MvPolynomial.finSuccEquiv K 1
      (MvPolynomial.X (Fin.succ 0))) = _
  rw [MvPolynomial.finSuccEquiv_X_succ]
  simp [MvPolynomial.renameEquiv_apply, MvPolynomial.pUnitAlgEquiv_apply]

private theorem planePolynomialEquiv_map
    {K L : Type*} [Field K] [Field L] (F : K →+* L)
    (r : MvPolynomial (Fin 2) K) :
    planePolynomialEquiv L (MvPolynomial.map F r) =
      (planePolynomialEquiv K r).map (Polynomial.mapRingHom F) := by
  change (((planePolynomialEquiv L).toRingHom.comp (MvPolynomial.map F)) r) =
    (((Polynomial.mapRingHom (Polynomial.mapRingHom F)).comp
      (planePolynomialEquiv K).toRingHom) r)
  congr 1
  apply MvPolynomial.ringHom_ext
  · intro a
    simp [planePolynomialEquiv, MvPolynomial.finSuccEquiv_apply,
      MvPolynomial.renameEquiv_apply, MvPolynomial.pUnitAlgEquiv_apply]
  · intro i
    fin_cases i
    · simp only [RingHom.comp_apply, MvPolynomial.map_X]
      change planePolynomialEquiv L (MvPolynomial.X 0) =
        (planePolynomialEquiv K (MvPolynomial.X 0)).map
          (Polynomial.mapRingHom F)
      rw [planePolynomialEquiv_X_zero, planePolynomialEquiv_X_zero]
      simp
    · simp only [RingHom.comp_apply, MvPolynomial.map_X]
      change planePolynomialEquiv L (MvPolynomial.X 1) =
        (planePolynomialEquiv K (MvPolynomial.X 1)).map
          (Polynomial.mapRingHom F)
      rw [planePolynomialEquiv_X_one, planePolynomialEquiv_X_one]
      simp

private theorem planePolynomialSwapEquiv_X_zero
    (K : Type*) [Field K] :
    planePolynomialSwapEquiv K (MvPolynomial.X 0) =
      Polynomial.C Polynomial.X := by
  simp [planePolynomialSwapEquiv, MvPolynomial.renameEquiv_apply,
    planePolynomialEquiv_X_one]

private theorem planePolynomialSwapEquiv_X_one
    (K : Type*) [Field K] :
    planePolynomialSwapEquiv K (MvPolynomial.X 1) = Polynomial.X := by
  simp [planePolynomialSwapEquiv, MvPolynomial.renameEquiv_apply,
    planePolynomialEquiv_X_zero]

private theorem planePolynomialSwapEquiv_map
    (r : MvPolynomial (Fin 2) ℝ) :
    planePolynomialSwapEquiv (RatFunc ℝ)
        (MvPolynomial.map (algebraMap ℝ (RatFunc ℝ)) r) =
      (planePolynomialSwapEquiv ℝ r).map
        (Polynomial.mapRingHom (algebraMap ℝ (RatFunc ℝ))) := by
  change (((planePolynomialSwapEquiv (RatFunc ℝ)).toRingHom.comp
      (MvPolynomial.map (algebraMap ℝ (RatFunc ℝ)))) r) =
    (((Polynomial.mapRingHom
      (Polynomial.mapRingHom (algebraMap ℝ (RatFunc ℝ)))).comp
        (planePolynomialSwapEquiv ℝ).toRingHom) r)
  congr 1
  apply MvPolynomial.ringHom_ext
  · intro a
    simp [planePolynomialSwapEquiv, planePolynomialEquiv,
      MvPolynomial.finSuccEquiv_apply, MvPolynomial.renameEquiv_apply,
      MvPolynomial.pUnitAlgEquiv_apply]
  · intro i
    fin_cases i
    · simp only [RingHom.comp_apply, MvPolynomial.map_X]
      rw [planePolynomialSwapEquiv_X_zero,
        planePolynomialSwapEquiv_X_zero]
      simp
    · simp only [RingHom.comp_apply, MvPolynomial.map_X]
      rw [planePolynomialSwapEquiv_X_one,
        planePolynomialSwapEquiv_X_one]
      simp

theorem planePolynomialUnitCircleInversionRatFuncParametrization_kernel_saturates
    (f : MvPolynomial (Fin 2) ℝ)
    (hf : Irreducible f)
    (hdeg : f.totalDegree = 2)
    (hzero : MvPolynomial.homogeneousComponent 0 f = 0)
    (x y : ℝ)
    (hxy : x ≠ 0 ∨ y ≠ 0)
    (hEval : MvPolynomial.eval ![x, y] f = 0)
    (hNotCircle : ¬ IsAffineCirclePolynomial f)
    (q : MvPolynomial (Fin 2) ℝ)
    (hq :
      planePolynomialUnitCircleInversionRatFuncParametrization
        f hdeg hzero q = 0) :
    ∃ n : ℕ,
      MvPolynomial.X 0 ^ n * q ∈
        Ideal.span
          ({planePolynomialUnitCircleInversion f} : Set _) := by
  classical
  let P := planePolynomialUnitCircleInversion f
  let φ := planePolynomialUnitCircleInversionRatFuncParametrization f hdeg hzero
  let p : Fin 2 → RatFunc ℝ := ![φ (MvPolynomial.X 0), φ (MvPolynomial.X 1)]
  have hPirr : Irreducible P :=
    (irreducible_totalDegree_three_planePolynomialUnitCircleInversion
      f hf hdeg hzero x y hxy hEval hNotCircle).1
  by_contra hmem
  have hndvd : ¬ P ∣ q := by
    push_neg at hmem
    have hmem0 := hmem 0
    simpa [P, Ideal.mem_span_singleton] using hmem0
  have hφ : φ = MvPolynomial.aeval p := by
    apply MvPolynomial.algHom_ext
    intro i
    fin_cases i <;> simp [p]
  have hPzero : MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) p P = 0 := by
    rw [← MvPolynomial.aeval_def, ← hφ]
    simpa [P, φ] using
      planePolynomialUnitCircleInversionRatFuncParametrization_apply_inversion
        f hf hdeg hzero x y hxy hEval hNotCircle
  have hqzero : MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) p q = 0 := by
    rw [← MvPolynomial.aeval_def, ← hφ]
    exact hq
  have hmapzero (r : MvPolynomial (Fin 2) ℝ)
      (hr : MvPolynomial.eval₂ (algebraMap ℝ (RatFunc ℝ)) p r = 0) :
      MvPolynomial.eval p (MvPolynomial.map (algebraMap ℝ (RatFunc ℝ)) r) = 0 := by
    simpa [MvPolynomial.eval_map] using hr
  have hPmap := hmapzero P hPzero
  have hqmap := hmapzero q hqzero
  have hP₁ :
      ((planePolynomialEquiv ℝ P).map
        (Polynomial.mapRingHom (algebraMap ℝ (RatFunc ℝ)))).evalEval (p 1) (p 0) = 0 := by
    rw [← planePolynomialEquiv_map (algebraMap ℝ (RatFunc ℝ))]
    simpa [planePolynomialEquiv_evalEval] using hPmap
  have hq₁ :
      ((planePolynomialEquiv ℝ q).map
        (Polynomial.mapRingHom (algebraMap ℝ (RatFunc ℝ)))).evalEval (p 1) (p 0) = 0 := by
    rw [← planePolynomialEquiv_map (algebraMap ℝ (RatFunc ℝ))]
    simpa [planePolynomialEquiv_evalEval] using hqmap
  have hP₀ :
      ((planePolynomialSwapEquiv ℝ P).map
        (Polynomial.mapRingHom (algebraMap ℝ (RatFunc ℝ)))).evalEval (p 0) (p 1) = 0 := by
    rw [← planePolynomialSwapEquiv_map]
    simpa [planePolynomialSwapEquiv_evalEval] using hPmap
  have hq₀ :
      ((planePolynomialSwapEquiv ℝ q).map
        (Polynomial.mapRingHom (algebraMap ℝ (RatFunc ℝ)))).evalEval (p 0) (p 1) = 0 := by
    rw [← planePolynomialSwapEquiv_map]
    simpa [planePolynomialSwapEquiv_evalEval] using hqmap
  have hndvd₁ : ¬ planePolynomialEquiv ℝ P ∣ planePolynomialEquiv ℝ q := by
    intro hdvd
    apply hndvd
    rcases hdvd with ⟨r, hr⟩
    refine ⟨(planePolynomialEquiv ℝ).symm r, ?_⟩
    apply (planePolynomialEquiv ℝ).injective
    simp [hr]
  have hndvd₀ : ¬ planePolynomialSwapEquiv ℝ P ∣
      planePolynomialSwapEquiv ℝ q := by
    intro hdvd
    apply hndvd
    rcases hdvd with ⟨r, hr⟩
    refine ⟨(planePolynomialSwapEquiv ℝ).symm r, ?_⟩
    apply (planePolynomialSwapEquiv ℝ).injective
    simp [hr]
  obtain ⟨r₁, hr₁, hr₁eval⟩ := exists_elimination_polynomial_aeval_zero
    (planePolynomialEquiv ℝ P) (planePolynomialEquiv ℝ q)
    (hPirr.map (planePolynomialEquiv ℝ).toMulEquiv) hndvd₁
    (p 1) (p 0) hP₁ hq₁
  obtain ⟨r₀, hr₀, hr₀eval⟩ := exists_elimination_polynomial_aeval_zero
    (planePolynomialSwapEquiv ℝ P) (planePolynomialSwapEquiv ℝ q)
    (hPirr.map (planePolynomialSwapEquiv ℝ).toMulEquiv) hndvd₀
    (p 0) (p 1) hP₀ hq₀
  have halg₁ : IsAlgebraic ℝ (p 1) := ⟨r₁, hr₁, hr₁eval⟩
  have halg₀ : IsAlgebraic ℝ (p 0) := ⟨r₀, hr₀, hr₀eval⟩
  have hratio : p 1 / p 0 = RatFunc.X := by
    simpa [p, φ] using
      planePolynomialUnitCircleInversionRatFuncParametrization_X_one_div_X_zero
        f hf hdeg hzero x y hxy hEval
  apply RatFunc.transcendental_X (K := ℝ)
  rw [← hratio]
  simpa [div_eq_mul_inv] using halg₁.mul halg₀.inv

/-- Contracting membership from the principal open chart clears a power of
the chart coordinate.  This is the localization step used by the saturation
argument below. -/
private theorem exists_pow_mul_mem_of_algebraMap_mem_map_away
    {R : Type*} [CommRing R] (s q : R) (I : Ideal R)
    (h : algebraMap R (Localization.Away s) q ∈
      I.map (algebraMap R (Localization.Away s))) :
    ∃ n : ℕ, s ^ n * q ∈ I := by
  rw [IsLocalization.algebraMap_mem_map_algebraMap_iff
    (Submonoid.powers s)] at h
  obtain ⟨m, hm, hmq⟩ := h
  obtain ⟨n, rfl⟩ := hm
  exact ⟨n, hmq⟩

end Erdos212
end AmraErdosFiveQueue20260704
