import Mathlib.Data.Finset.Max
import Mathlib.Data.Real.Basic
import Mathlib.Data.Complex.Basic
import Mathlib.Topology.MetricSpace.Basic
import Mathlib.Topology.MetricSpace.Pseudo.Constructions
import Mathlib.Topology.MetricSpace.Pseudo.Lemmas
import Mathlib.Topology.Algebra.Ring.Real
import Mathlib.Topology.Separation.Basic
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Ring

/-!
Lean scratch target for the 2026-06-12 AMRA attack on Erdos Problem #212.
-/

namespace AmraNewCandidates20260612
namespace Erdos212

notation:50 x " notin " s => x ∉ s

theorem exists_real_not_mem_finset (S : Finset Real) :
    exists x : Real, x notin S := by
  by_cases hS : S.Nonempty
  · refine ⟨S.max' hS + 1, ?_⟩
    intro hx
    have hle : S.max' hS + 1 ≤ S.max' hS :=
      S.le_max' (S.max' hS + 1) hx
    linarith
  · refine ⟨0, ?_⟩
    intro h0
    exact hS ⟨0, h0⟩

private lemma complex_pair_injective :
    Function.Injective (fun z : ℂ => (z.re, z.im)) := by
  intro z w h
  exact Complex.ext (congrArg Prod.fst h) (congrArg Prod.snd h)

noncomputable instance : MetricSpace ℂ :=
  MetricSpace.induced (fun z : ℂ => (z.re, z.im)) complex_pair_injective inferInstance

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
            _ = ((z.re - a.re) * v.im) / v.re := by
              rw [h1]
            _ = ((z.re - a.re) / v.re) * v.im := by
              field_simp [hvre]
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

private lemma not_dense_of_isClosed_exists_not_mem
    {α : Type*} [TopologicalSpace α] {s : Set α}
    (hs : IsClosed s) (hne : ∃ x, x ∉ s) :
    ¬ Dense s := by
  rintro hd
  rcases hne with ⟨x, hx⟩
  have hxcl : x ∈ closure s := by
    rw [(dense_iff_closure_eq.mp hd)]
    trivial
  exact hx (by simpa [hs.closure_eq] using hxcl)

private lemma finite_set_isClosed_complex (F : Finset ℂ) :
    IsClosed (F : Set ℂ) :=
  (Finset.finite_toSet F).isClosed

private lemma transverse_line_point_not_on_line
    (a v : ℂ) (hv : v ≠ 0) (x t : ℝ) :
    a + ((x : ℂ) + Complex.I) * v ≠ a + (t : ℂ) * v := by
  intro h
  have hsub : (((x : ℂ) + Complex.I) - (t : ℂ)) * v =
      (a + ((x : ℂ) + Complex.I) * v) - (a + (t : ℂ) * v) := by
    ring
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
  rw [show a + ((x : ℂ) + Complex.I) * v - a = ((x : ℂ) + Complex.I) * v by ring]
  rw [mul_div_cancel_right₀ _ hv]
  simp [Complex.add_re]

private lemma horizontal_parameter_re (a : ℂ) (x : ℝ) :
    (a + (x : ℂ) - a).re = x := by
  simp

private lemma horizontal_dist (a : ℂ) (x : ℝ) :
    dist (a + (x : ℂ)) a = |x| := by
  change dist (((a + (x : ℂ)).re, (a + (x : ℂ)).im)) (a.re, a.im) = |x|
  rw [Prod.dist_eq]
  simp [Real.dist_eq, Complex.add_re, Complex.add_im]

private lemma not_dense_real_line_union_finset
    (F : Finset ℂ) (a v : ℂ) (hv : v ≠ 0) :
    ¬ Dense ({z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ)) := by
  let bad : Finset ℝ := F.image (fun z : ℂ => ((z - a) / v).re)
  rcases exists_real_not_mem_finset bad with ⟨x, hx⟩
  let p : ℂ := a + ((x : ℂ) + Complex.I) * v
  refine not_dense_of_isClosed_exists_not_mem
    ((isClosed_real_line a v hv).union (finite_set_isClosed_complex F)) ⟨p, ?_⟩
  rintro (hp | hp)
  · rcases hp with ⟨t, ht⟩
    exact transverse_line_point_not_on_line a v hv x t ht
  · apply hx
    refine Finset.mem_image.mpr ⟨p, hp, ?_⟩
    dsimp [p]
    exact transverse_line_parameter_re a v hv x

private lemma not_dense_circle_union_finset
    (F : Finset ℂ) (a : ℂ) (r : ℝ) :
    ¬ Dense ({z : ℂ | dist z a = r} ∪ (F : Set ℂ)) := by
  let bad : Finset ℝ := insert r (insert (-r) (F.image (fun z : ℂ => (z - a).re)))
  rcases exists_real_not_mem_finset bad with ⟨x, hx⟩
  let p : ℂ := a + (x : ℂ)
  refine not_dense_of_isClosed_exists_not_mem
    (Metric.isClosed_sphere.union (finite_set_isClosed_complex F)) ⟨p, ?_⟩
  rintro (hp | hp)
  · have habs : |x| = r := by
      have hd : dist p a = |x| := by
        dsimp [p]
        exact horizontal_dist a x
      exact hd.symm.trans hp
    have hr : 0 ≤ r := by
      rw [← habs]
      exact abs_nonneg x
    rcases (abs_eq hr).mp habs with hxpos | hxneg
    · apply hx
      simp [bad, hxpos]
    · apply hx
      simp [bad, hxneg]
  · apply hx
    exact Finset.mem_insert.mpr <| Or.inr <| Finset.mem_insert.mpr <| Or.inr <|
      Finset.mem_image.mpr ⟨p, hp, by dsimp [p]; exact horizontal_parameter_re a x⟩

lemma not_dense_line_or_circle_union_finset
    (F : Finset ℂ) :
    (∀ a v : ℂ,
      v ≠ 0 →
      ¬ Dense ({z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ))) ∧
    (∀ a : ℂ, ∀ r : ℝ,
      ¬ Dense ({z : ℂ | dist z a = r} ∪ (F : Set ℂ))) := by
  exact ⟨not_dense_real_line_union_finset F, not_dense_circle_union_finset F⟩

theorem no_dense_of_subset_line_or_circle_union_finset
    {u : Set ℂ}
    (h :
      (∃ F : Finset ℂ, ∃ a v : ℂ, v ≠ 0 ∧
        u ⊆ ({z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ))) ∨
      (∃ F : Finset ℂ, ∃ a : ℂ, ∃ r : ℝ,
        u ⊆ ({z : ℂ | dist z a = r} ∪ (F : Set ℂ)))) :
    ¬ Dense u := by
  intro hu
  rcases h with hline | hcircle
  · rcases hline with ⟨F, a, v, hv, hsub⟩
    exact (not_dense_line_or_circle_union_finset F).1 a v hv (hu.mono hsub)
  · rcases hcircle with ⟨F, a, r, hsub⟩
    exact (not_dense_line_or_circle_union_finset F).2 a r (hu.mono hsub)

theorem rational_distance_subset_line_or_circle_union_finset_of_finite
    {u : Set ℂ} (hu : u.Finite) :
    (∃ F : Finset ℂ, ∃ a v : ℂ, v ≠ 0 ∧
      u ⊆ ({z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ))) ∨
    (∃ F : Finset ℂ, ∃ a : ℂ, ∃ r : ℝ,
      u ⊆ ({z : ℂ | dist z a = r} ∪ (F : Set ℂ))) := by
  left
  refine ⟨hu.toFinset, 0, 1, one_ne_zero, ?_⟩
  intro z hz
  exact Or.inr (hu.mem_toFinset.mpr hz)

def PairwiseRationalDistances (u : Set ℂ) : Prop :=
  ∀ ⦃z w : ℂ⦄, z ∈ u → w ∈ u → ∃ q : ℚ, dist z w = (q : ℝ)

def SubsetLineOrCircleUnionFinset (u : Set ℂ) : Prop :=
  (∃ F : Finset ℂ, ∃ a v : ℂ, v ≠ 0 ∧
    u ⊆ ({z : ℂ | ∃ t : ℝ, z = a + (t : ℂ) * v} ∪ (F : Set ℂ))) ∨
  (∃ F : Finset ℂ, ∃ a : ℂ, ∃ r : ℝ,
    u ⊆ ({z : ℂ | dist z a = r} ∪ (F : Set ℂ)))

def BombieriLangConsequenceForRationalDistanceSets : Prop :=
  ∀ {u : Set ℂ},
    ¬ u.Finite →
    PairwiseRationalDistances u →
    SubsetLineOrCircleUnionFinset u

theorem rational_distance_subset_line_or_circle_union_finset_of_bombieri_lang
    (hBL : BombieriLangConsequenceForRationalDistanceSets)
    {u : Set ℂ} (hu : PairwiseRationalDistances u) :
    SubsetLineOrCircleUnionFinset u := by
  by_cases hfin : u.Finite
  · exact rational_distance_subset_line_or_circle_union_finset_of_finite hfin
  · exact hBL hfin hu

theorem no_dense_of_pairwise_rational_distances_of_bombieri_lang
    (hBL : BombieriLangConsequenceForRationalDistanceSets)
    {u : Set ℂ} (hu : PairwiseRationalDistances u) :
    ¬ Dense u := by
  have hcover : SubsetLineOrCircleUnionFinset u :=
    rational_distance_subset_line_or_circle_union_finset_of_bombieri_lang hBL hu
  exact no_dense_of_subset_line_or_circle_union_finset hcover

theorem no_erdos_212_formal_statement_of_bombieri_lang
    (hBL : BombieriLangConsequenceForRationalDistanceSets) :
    ¬ ∃ u : Set ℂ,
      Dense u ∧ u.Pairwise (fun z w => dist z w ∈ Set.range Rat.cast) := by
  rintro ⟨u, hdense, hpair⟩
  have hu : PairwiseRationalDistances u := by
    intro z w hz hw
    by_cases hzw : z = w
    · refine ⟨0, ?_⟩
      subst z
      simpa only [Rat.cast_zero] using dist_self w
    · rcases hpair hz hw hzw with ⟨q, hq⟩
      exact ⟨q, hq.symm⟩
  exact (no_dense_of_pairwise_rational_distances_of_bombieri_lang hBL hu) hdense

end Erdos212
end AmraNewCandidates20260612
