import Mathlib.Data.Complex.Basic
import Mathlib.Topology.MetricSpace.Basic
import Mathlib.Topology.MetricSpace.Pseudo.Constructions

namespace AmraErdosFiveQueue20260703
namespace Erdos212

/- Queued promotion file for Erdos #212.  This file is intentionally
   self-contained for the configured single-file verifier: importing the older
   NewCandidates module requires a prebuilt `.olean`, which this job is not
   allowed to create with an aggregate build. -/

private lemma complex_pair_injective :
    Function.Injective (fun z : ℂ => (z.re, z.im)) := by
  intro z w h
  exact Complex.ext (congrArg Prod.fst h) (congrArg Prod.snd h)

noncomputable instance : MetricSpace ℂ :=
  MetricSpace.induced (fun z : ℂ => (z.re, z.im)) complex_pair_injective inferInstance

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

end Erdos212
end AmraErdosFiveQueue20260703
