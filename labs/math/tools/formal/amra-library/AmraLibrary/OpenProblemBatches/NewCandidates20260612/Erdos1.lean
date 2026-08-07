import Mathlib.Algebra.BigOperators.Group.Finset.Basic
import Mathlib.Algebra.BigOperators.Ring.Finset
import Mathlib.Data.Bool.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Data.Finset.Powerset
import Mathlib.Data.Fintype.Powerset
import Mathlib.Data.Fintype.Pi
import Mathlib.Data.Int.Interval
import Mathlib.Data.ZMod.Basic
import Mathlib.Combinatorics.SetFamily.LYM
import Mathlib.Order.Interval.Finset.Nat
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Ring

/-!
Lean scratch target for the 2026-06-12 AMRA attack on Erdos Problem #1.

This file is intentionally empty except for imports and namespace scaffolding.
The campaign formalizer should add only theorem-level support for the current
small target, not a weakened version of the original conjecture.
-/

namespace AmraNewCandidates20260612
namespace Erdos1

open scoped BigOperators
open scoped FinsetFamily

/--
`A` is sum-distinct in `[1, N]`: it is contained in the interval and all
subset sums over `A` are different.
-/
abbrev IsSumDistinctSet (A : Finset ℕ) (N : ℕ) : Prop :=
  A ⊆ Finset.Icc 1 N ∧
    (fun (S : A.powerset) => S.1.sum id).Injective

/-- The signed sum attached to a Boolean vector through an enumeration of `A`. -/
def signedSum (A : Finset ℕ) (e : Fin A.card ≃ {a // a ∈ A})
    (u : Fin A.card → Bool) : ℤ :=
  ∑ i : Fin A.card, if u i = true then ((e i).1 : ℤ) else -((e i).1 : ℤ)

/-- The negative signed-sum cut in the Boolean cube. -/
def negativeSignedCut (A : Finset ℕ) (e : Fin A.card ≃ {a // a ∈ A}) :
    Finset (Fin A.card → Bool) :=
  Finset.univ.filter fun u => signedSum A e u < 0

/-- Outer vertex boundary in the Boolean cube, using one-coordinate flips. -/
def cubeOuterBoundary {n : ℕ} (F : Finset (Fin n → Bool)) :
    Finset (Fin n → Bool) :=
  Finset.univ.filter fun v =>
    v ∉ F ∧ ∃ u ∈ F, ∃ i : Fin n, Function.update u i (!(u i)) = v

/-- The subset of coordinates where a Boolean cube point is `true`. -/
def boolSupport {n : ℕ} (u : Fin n → Bool) : Finset (Fin n) :=
  Finset.univ.filter fun i => u i = true

lemma mem_boolSupport_iff {n : ℕ} (u : Fin n → Bool) (i : Fin n) :
    i ∈ boolSupport u ↔ u i = true := by
  simp [boolSupport]

lemma boolSupport_injective {n : ℕ} :
    Function.Injective (boolSupport : (Fin n → Bool) → Finset (Fin n)) := by
  intro u v huv
  funext i
  have hi : u i = true ↔ v i = true := by
    rw [← mem_boolSupport_iff u i, huv, mem_boolSupport_iff v i]
  cases hu : u i <;> cases hv : v i <;> simp [hu, hv] at hi ⊢

/-- Transport a Boolean cube family to the corresponding family of coordinate supports. -/
def supportFamily {n : ℕ} (F : Finset (Fin n → Bool)) : Finset (Finset (Fin n)) :=
  F.image boolSupport

lemma supportFamily_card {n : ℕ} (F : Finset (Fin n → Bool)) :
    (supportFamily F).card = F.card := by
  rw [supportFamily]
  exact Finset.card_image_of_injective F boolSupport_injective

lemma boolSupport_update_false {n : ℕ} (u : Fin n → Bool) (i : Fin n)
    (hi : u i = false) :
    boolSupport (Function.update u i (!(u i))) = insert i (boolSupport u) := by
  ext j
  by_cases hji : j = i
  · subst j
    simp [mem_boolSupport_iff, hi]
  · have hupdate : Function.update u i (!(u i)) j = u j :=
      Function.update_of_ne hji (!(u i)) u
    rw [mem_boolSupport_iff, hupdate]
    simp [mem_boolSupport_iff, hji]

lemma boolSupport_update_true {n : ℕ} (u : Fin n → Bool) (i : Fin n)
    (hi : u i = true) :
    boolSupport (Function.update u i (!(u i))) = (boolSupport u).erase i := by
  ext j
  by_cases hji : j = i
  · subst j
    simp [mem_boolSupport_iff, hi]
  · have hupdate : Function.update u i (!(u i)) j = u j :=
      Function.update_of_ne hji (!(u i)) u
    rw [mem_boolSupport_iff, hupdate]
    simp [mem_boolSupport_iff, hji]

lemma boolSupport_mem_supportFamily_iff {n : ℕ}
    (F : Finset (Fin n → Bool)) (u : Fin n → Bool) :
    boolSupport u ∈ supportFamily F ↔ u ∈ F := by
  constructor
  · intro hu
    rw [supportFamily] at hu
    rcases Finset.mem_image.mp hu with ⟨v, hv, hvu⟩
    have hvu' : v = u := boolSupport_injective hvu
    simpa [hvu'] using hv
  · intro hu
    rw [supportFamily]
    exact Finset.mem_image.mpr ⟨u, hu, rfl⟩

lemma boolSupport_update_eq_erase_or_insert {n : ℕ}
    (F : Finset (Fin n → Bool)) {u : Fin n → Bool} (hu : u ∈ F)
    (i : Fin n) :
    ∃ s ∈ supportFamily F, ∃ j : Fin n,
      boolSupport (Function.update u i (!(u i))) = s.erase j ∨
        boolSupport (Function.update u i (!(u i))) = insert j s := by
  classical
  by_cases hui : u i = true
  · exact ⟨boolSupport u, (boolSupport_mem_supportFamily_iff F u).mpr hu, i,
      Or.inl (boolSupport_update_true u i hui)⟩
  · have hifalse : u i = false := by
      cases h : u i <;> simp [h] at hui ⊢
    exact ⟨boolSupport u, (boolSupport_mem_supportFamily_iff F u).mpr hu, i,
      Or.inr (boolSupport_update_false u i hifalse)⟩

lemma boolSupport_not_mem_and_neighbor_of_mem_cubeOuterBoundary {n : ℕ}
    {F : Finset (Fin n → Bool)} {v : Fin n → Bool}
    (hv : v ∈ cubeOuterBoundary F) :
    boolSupport v ∉ supportFamily F ∧
      ∃ s ∈ supportFamily F, ∃ i : Fin n,
        boolSupport v = s.erase i ∨ boolSupport v = insert i s := by
  classical
  rw [cubeOuterBoundary] at hv
  rcases Finset.mem_filter.mp hv with ⟨_hv_univ, hvnot, u, hu, i, huv⟩
  constructor
  · simpa [boolSupport_mem_supportFamily_iff F v] using hvnot
  · simpa [huv] using boolSupport_update_eq_erase_or_insert F hu i

/-- Every coordinate subset is the support of its characteristic Boolean vector. -/
lemma boolSupport_indicator {n : ℕ} (s : Finset (Fin n)) :
    boolSupport (fun i : Fin n => decide (i ∈ s)) = s := by
  ext i
  rw [mem_boolSupport_iff]
  by_cases hi : i ∈ s <;> simp [hi]

/--
Outer vertex boundary for set families in the Boolean lattice, stated with the
same one-coordinate adjacency convention as `cubeOuterBoundary`.
-/
def setFamilyOuterBoundary {n : ℕ} (𝒜 : Finset (Finset (Fin n))) :
    Finset (Finset (Fin n)) :=
  Finset.univ.filter fun t =>
    t ∉ 𝒜 ∧ ∃ s ∈ 𝒜, ∃ i : Fin n, t = s.erase i ∨ t = insert i s

private def setFamilyUpShadow {n : ℕ} (𝒜 : Finset (Finset (Fin n))) :
    Finset (Finset (Fin n)) :=
  Finset.univ.filter fun t =>
    ∃ s ∈ 𝒜, ∃ i : Fin n, i ∉ s ∧ t = insert i s

private lemma setFamilyUpShadow_eq_upShadow {n : ℕ}
    (𝒜 : Finset (Finset (Fin n))) :
    setFamilyUpShadow 𝒜 = Finset.upShadow 𝒜 := by
  classical
  ext t
  rw [setFamilyUpShadow, Finset.mem_filter, Finset.mem_upShadow_iff]
  constructor
  · rintro ⟨_ht, s, hs, i, hi, rfl⟩
    exact ⟨s, hs, i, hi, rfl⟩
  · rintro ⟨s, hs, i, hi, hit⟩
    exact ⟨by simp, s, hs, i, hi, hit.symm⟩

private theorem upShadow_local_lym_mul {n r : ℕ}
    {𝒜 : Finset (Finset (Fin n))}
    (h𝒜 : (𝒜 : Set (Finset (Fin n))).Sized r) :
    𝒜.card * (n - r) ≤ (Finset.upShadow 𝒜).card * (r + 1) := by
  classical
  by_cases hne : 𝒜.Nonempty
  · rcases hne with ⟨s, hs⟩
    have hrn : r ≤ n := by
      rw [← h𝒜 hs]
      exact s.card_le_univ
    have hcompl :
        (𝒜ᶜˢ : Set (Finset (Fin n))).Sized (n - r) := by
      simpa [Fintype.card_fin] using h𝒜.compls
    have h :=
      Finset.local_lubell_yamamoto_meshalkin_inequality_mul
        (α := Fin n) (𝒜 := 𝒜ᶜˢ) (r := n - r) hcompl
    simpa [Fintype.card_fin, Nat.sub_sub_self hrn] using h
  · have hcard : 𝒜.card = 0 := by
      exact Finset.card_eq_zero.mpr (by
        rw [eq_empty_iff_forall_not_mem]
        intro s hs
        exact hne ⟨s, hs⟩)
    simp [hcard]

private lemma centralLayer_card_eq_choose (n : ℕ) :
    (Finset.univ.filter fun s : Finset (Fin n) => s.card = n / 2).card =
      Nat.choose n (n / 2) := by
  rw [Finset.univ_filter_card_eq (Fin n) (n / 2)]
  rw [Finset.card_powersetCard]
  simp

lemma not_mem_of_mem_setFamilyOuterBoundary {n : ℕ}
    {𝒜 : Finset (Finset (Fin n))} {t : Finset (Fin n)}
    (ht : t ∈ setFamilyOuterBoundary 𝒜) :
    t ∉ 𝒜 := by
  rw [setFamilyOuterBoundary] at ht
  exact (Finset.mem_filter.mp ht).2.1

lemma disjoint_setFamilyOuterBoundary {n : ℕ}
    (𝒜 : Finset (Finset (Fin n))) :
    Disjoint 𝒜 (setFamilyOuterBoundary 𝒜) := by
  classical
  rw [Finset.disjoint_left]
  intro t htA htbd
  rw [setFamilyOuterBoundary] at htbd
  exact (Finset.mem_filter.mp htbd).2.1 htA

private lemma empty_mem_of_downClosed_of_nonempty {n : ℕ}
    {𝒟 : Finset (Finset (Fin n))}
    (hdown : ∀ ⦃s t : Finset (Fin n)⦄, t ⊆ s → s ∈ 𝒟 → t ∈ 𝒟)
    (hne : 𝒟.Nonempty) :
    ∅ ∈ 𝒟 := by
  rcases hne with ⟨s, hs⟩
  exact hdown (Finset.empty_subset s) hs

private lemma empty_mem_of_downClosed_card_half {n : ℕ}
    {𝒟 : Finset (Finset (Fin n))}
    (hdown : ∀ ⦃s t : Finset (Fin n)⦄, t ⊆ s → s ∈ 𝒟 → t ∈ 𝒟)
    (h𝒟 : 𝒟.card = 2 ^ (n - 1)) :
    ∅ ∈ 𝒟 := by
  apply empty_mem_of_downClosed_of_nonempty hdown
  exact Finset.card_pos.mp (by
    rw [h𝒟]
    exact Nat.pow_pos (by norm_num : 0 < 2))

private lemma setFamilyOuterBoundary_eq_upShadow_sdiff_of_downClosed {n : ℕ}
    (𝒟 : Finset (Finset (Fin n)))
    (hdown : ∀ ⦃s t : Finset (Fin n)⦄, t ⊆ s → s ∈ 𝒟 → t ∈ 𝒟) :
    setFamilyOuterBoundary 𝒟 = setFamilyUpShadow 𝒟 \ 𝒟 := by
  classical
  ext t
  constructor
  · intro ht
    rw [setFamilyOuterBoundary] at ht
    rcases Finset.mem_filter.mp ht with ⟨_htuniv, htD, s, hsD, i, hneighbor⟩
    rw [Finset.mem_sdiff]
    refine ⟨?_, htD⟩
    rw [setFamilyUpShadow]
    rcases hneighbor with hdel | hins
    · exfalso
      exact htD (by
        rw [hdel]
        exact hdown (Finset.erase_subset i s) hsD)
    · have his : i ∉ s := by
        intro his
        have ht_eq_s : t = s := by simpa [Finset.insert_eq_of_mem his] using hins
        exact htD (by rw [ht_eq_s]; exact hsD)
      exact Finset.mem_filter.mpr ⟨by simp, s, hsD, i, his, hins⟩
  · intro ht
    rw [Finset.mem_sdiff] at ht
    rcases ht with ⟨htup, htD⟩
    rw [setFamilyUpShadow] at htup
    rcases Finset.mem_filter.mp htup with ⟨_htuniv, s, hsD, i, _his, hit⟩
    rw [setFamilyOuterBoundary]
    exact Finset.mem_filter.mpr ⟨by simp, htD, s, hsD, i, Or.inr hit⟩

lemma setFamilyClosedNeighborhood_card {n : ℕ}
    (𝒜 : Finset (Finset (Fin n))) :
    (𝒜 ∪ setFamilyOuterBoundary 𝒜).card =
      𝒜.card + (setFamilyOuterBoundary 𝒜).card := by
  classical
  exact Finset.card_union_of_disjoint (disjoint_setFamilyOuterBoundary 𝒜)

theorem setFamilyClosedNeighborhood_half_cube_ge_central_of_outer
    (n : ℕ) (𝒜 : Finset (Finset (Fin n)))
    (h𝒜 : 𝒜.card = 2 ^ (n - 1))
    (houter : Nat.choose n (n / 2) ≤ (setFamilyOuterBoundary 𝒜).card) :
    2 ^ (n - 1) + Nat.choose n (n / 2) ≤
      (𝒜 ∪ setFamilyOuterBoundary 𝒜).card := by
  calc
    2 ^ (n - 1) + Nat.choose n (n / 2)
        ≤ 2 ^ (n - 1) + (setFamilyOuterBoundary 𝒜).card :=
      Nat.add_le_add_left houter (2 ^ (n - 1))
    _ = 𝒜.card + (setFamilyOuterBoundary 𝒜).card := by
      rw [h𝒜]
    _ = (𝒜 ∪ setFamilyOuterBoundary 𝒜).card := by
      rw [setFamilyClosedNeighborhood_card]

theorem downClosed_setFamilyOuterBoundary_card_ge_central_of_card_half_of_centralLayer
    (n : ℕ) (𝒟 : Finset (Finset (Fin n)))
    (hcentral :
      (Finset.univ.filter fun s : Finset (Fin n) => s.card = n / 2).card ≤
        (setFamilyOuterBoundary 𝒟).card) :
    Nat.choose n (n / 2) ≤ (setFamilyOuterBoundary 𝒟).card := by
  simpa [centralLayer_card_eq_choose n] using hcentral

private def permFinsetImage {n : ℕ} (e : Equiv.Perm (Fin n))
    (s : Finset (Fin n)) : Finset (Fin n) :=
  s.map e.toEmbedding

private def permFinsetPreimage {n : ℕ} (e : Equiv.Perm (Fin n))
    (s : Finset (Fin n)) : Finset (Fin n) :=
  s.map e.symm.toEmbedding

private lemma permFinsetImage_injective {n : ℕ} (e : Equiv.Perm (Fin n)) :
    Function.Injective (permFinsetImage e) := by
  intro s t hst
  exact Finset.map_injective e.toEmbedding hst

private lemma permFinsetImage_preimage {n : ℕ} (e : Equiv.Perm (Fin n))
    (t : Finset (Fin n)) :
    permFinsetImage e (permFinsetPreimage e t) = t := by
  ext i
  simp [permFinsetImage, permFinsetPreimage, Finset.mem_map_equiv]

private lemma permFinsetPreimage_image {n : ℕ} (e : Equiv.Perm (Fin n))
    (s : Finset (Fin n)) :
    permFinsetPreimage e (permFinsetImage e s) = s := by
  ext i
  simp [permFinsetImage, permFinsetPreimage, Finset.mem_map_equiv]

private lemma permFinsetImage_erase {n : ℕ} (e : Equiv.Perm (Fin n))
    (s : Finset (Fin n)) (i : Fin n) :
    permFinsetImage e (s.erase i) = (permFinsetImage e s).erase (e i) := by
  simp [permFinsetImage]

private lemma permFinsetImage_insert {n : ℕ} (e : Equiv.Perm (Fin n))
    (s : Finset (Fin n)) (i : Fin n) :
    permFinsetImage e (insert i s) = insert (e i) (permFinsetImage e s) := by
  simp [permFinsetImage]

private lemma permFinsetPreimage_erase {n : ℕ} (e : Equiv.Perm (Fin n))
    (s : Finset (Fin n)) (i : Fin n) :
    permFinsetPreimage e (s.erase i) =
      (permFinsetPreimage e s).erase (e.symm i) := by
  simp [permFinsetPreimage]

private lemma permFinsetPreimage_insert {n : ℕ} (e : Equiv.Perm (Fin n))
    (s : Finset (Fin n)) (i : Fin n) :
    permFinsetPreimage e (insert i s) =
      insert (e.symm i) (permFinsetPreimage e s) := by
  simp [permFinsetPreimage]

private lemma setFamilyOuterBoundary_permImage {n : ℕ}
    (𝒜 : Finset (Finset (Fin n))) (e : Equiv.Perm (Fin n)) :
    setFamilyOuterBoundary (𝒜.image (permFinsetImage e)) =
      (setFamilyOuterBoundary 𝒜).image (permFinsetImage e) := by
  classical
  ext t
  constructor
  · intro ht
    rw [setFamilyOuterBoundary] at ht
    rcases Finset.mem_filter.mp ht with ⟨_htuniv, htnot, s', hs', i, hneighbor⟩
    rcases Finset.mem_image.mp hs' with ⟨s, hs, rfl⟩
    rw [setFamilyOuterBoundary]
    refine Finset.mem_image.mpr
      ⟨permFinsetPreimage e t, ?_, permFinsetImage_preimage e t⟩
    refine Finset.mem_filter.mpr ⟨by simp, ?_, s, hs, e.symm i, ?_⟩
    · intro hpre
      exact htnot
        (Finset.mem_image.mpr
          ⟨permFinsetPreimage e t, hpre, permFinsetImage_preimage e t⟩)
    · rcases hneighbor with hdel | hins
      · left
        calc
          permFinsetPreimage e t =
              permFinsetPreimage e ((permFinsetImage e s).erase i) := by rw [hdel]
          _ = (permFinsetPreimage e (permFinsetImage e s)).erase (e.symm i) := by
            rw [permFinsetPreimage_erase]
          _ = s.erase (e.symm i) := by rw [permFinsetPreimage_image]
      · right
        calc
          permFinsetPreimage e t =
              permFinsetPreimage e (insert i (permFinsetImage e s)) := by rw [hins]
          _ = insert (e.symm i) (permFinsetPreimage e (permFinsetImage e s)) := by
            rw [permFinsetPreimage_insert]
          _ = insert (e.symm i) s := by rw [permFinsetPreimage_image]
  · intro ht
    rcases Finset.mem_image.mp ht with ⟨t0, ht0, rfl⟩
    rw [setFamilyOuterBoundary] at ht0 ⊢
    rcases Finset.mem_filter.mp ht0 with ⟨_ht0univ, ht0not, s, hs, i, hneighbor⟩
    refine Finset.mem_filter.mpr
      ⟨by simp, ?_, permFinsetImage e s,
        Finset.mem_image.mpr ⟨s, hs, rfl⟩, e i, ?_⟩
    · intro himg
      rcases Finset.mem_image.mp himg with ⟨u, hu, hu_eq⟩
      exact ht0not (by
        have htu : t0 = u := permFinsetImage_injective e hu_eq.symm
        simpa [htu] using hu)
    · rcases hneighbor with hdel | hins
      · left
        calc
          permFinsetImage e t0 = permFinsetImage e (s.erase i) := by rw [hdel]
          _ = (permFinsetImage e s).erase (e i) := permFinsetImage_erase e s i
      · right
        calc
          permFinsetImage e t0 = permFinsetImage e (insert i s) := by rw [hins]
          _ = insert (e i) (permFinsetImage e s) := permFinsetImage_insert e s i

theorem setFamilyClosedNeighborhood_card_permImage
    {n : ℕ} (𝒜 : Finset (Finset (Fin n))) (e : Equiv.Perm (Fin n)) :
    ((𝒜.image (fun s => s.image e.toEmbedding)) ∪
      setFamilyOuterBoundary (𝒜.image (fun s => s.image e.toEmbedding))).card =
    (𝒜 ∪ setFamilyOuterBoundary 𝒜).card := by
  classical
  have hfun :
      (fun s : Finset (Fin n) => s.image e.toEmbedding) = permFinsetImage e := by
    funext s
    exact (Finset.map_eq_image e.toEmbedding s).symm
  rw [hfun]
  rw [setFamilyOuterBoundary_permImage]
  have hunion :
      𝒜.image (permFinsetImage e) ∪
          (setFamilyOuterBoundary 𝒜).image (permFinsetImage e) =
        (𝒜 ∪ setFamilyOuterBoundary 𝒜).image (permFinsetImage e) := by
    ext t
    simp [or_and_right, exists_or]
  rw [hunion]
  exact Finset.card_image_of_injective _ (permFinsetImage_injective e)

lemma supportFamily_cubeOuterBoundary {n : ℕ}
    (F : Finset (Fin n → Bool)) :
    supportFamily (cubeOuterBoundary F) =
      setFamilyOuterBoundary (supportFamily F) := by
  classical
  ext t
  constructor
  · intro ht
    rw [supportFamily] at ht
    rcases Finset.mem_image.mp ht with ⟨v, hv, rfl⟩
    rcases boolSupport_not_mem_and_neighbor_of_mem_cubeOuterBoundary hv with
      ⟨hvnot, s, hs, i, hneighbor⟩
    rw [setFamilyOuterBoundary]
    exact Finset.mem_filter.mpr ⟨by simp, hvnot, s, hs, i, hneighbor⟩
  · intro ht
    rw [setFamilyOuterBoundary] at ht
    rcases Finset.mem_filter.mp ht with ⟨_ht_univ, htnot, s, hs, i, hneighbor⟩
    have hs_mem : s ∈ supportFamily F := hs
    rw [supportFamily] at hs
    rcases Finset.mem_image.mp hs with ⟨u, hu, hus⟩
    let v : Fin n → Bool := fun j => decide (j ∈ t)
    have hvt : boolSupport v = t := boolSupport_indicator t
    have hvnot : v ∉ F := by
      intro hvF
      exact htnot (by
        rw [← hvt]
        exact (boolSupport_mem_supportFamily_iff F v).mpr hvF)
    have hupdate : Function.update u i (!(u i)) = v := by
      apply boolSupport_injective
      rcases hneighbor with hdel | hins
      · have his : i ∈ s := by
          by_contra hi
          have hsame : s.erase i = s := Finset.erase_eq_of_notMem hi
          exact htnot (by simpa [hdel, hsame] using hs_mem)
        have hui : u i = true := by
          rw [← mem_boolSupport_iff u i, hus]
          exact his
        calc
          boolSupport (Function.update u i (!(u i))) = s.erase i := by
            rw [boolSupport_update_true u i hui, hus]
          _ = t := hdel.symm
          _ = boolSupport v := hvt.symm
      · have his : i ∉ s := by
          intro hi
          have hsame : insert i s = s := Finset.insert_eq_of_mem hi
          exact htnot (by simpa [hins, hsame] using hs_mem)
        have hui : u i = false := by
          cases hui : u i
          · rfl
          · exfalso
            exact his (by
              rw [← hus, mem_boolSupport_iff u i]
              simp [hui])
        calc
          boolSupport (Function.update u i (!(u i))) = insert i s := by
            rw [boolSupport_update_false u i hui, hus]
          _ = t := hins.symm
          _ = boolSupport v := hvt.symm
    have hvboundary : v ∈ cubeOuterBoundary F := by
      rw [cubeOuterBoundary]
      exact Finset.mem_filter.mpr ⟨by simp, hvnot, u, hu, i, hupdate⟩
    rw [supportFamily]
    exact Finset.mem_image.mpr ⟨v, hvboundary, hvt⟩

private def positiveSubset (A : Finset ℕ) (e : Fin A.card ≃ {a // a ∈ A})
    (u : Fin A.card → Bool) : Finset ℕ :=
  (Finset.univ.filter fun i : Fin A.card => u i = true).image fun i => (e i).1

private lemma enum_value_injective (A : Finset ℕ)
    (e : Fin A.card ≃ {a // a ∈ A}) :
    Function.Injective fun i : Fin A.card => (e i).1 := by
  intro i j hij
  apply e.injective
  exact Subtype.ext hij

private lemma positiveSubset_mem_powerset (A : Finset ℕ)
    (e : Fin A.card ≃ {a // a ∈ A}) (u : Fin A.card → Bool) :
    positiveSubset A e u ∈ A.powerset := by
  rw [Finset.mem_powerset]
  intro a ha
  rcases Finset.mem_image.mp ha with ⟨i, _hi, rfl⟩
  exact (e i).2

private lemma mem_positiveSubset_iff (A : Finset ℕ)
    (e : Fin A.card ≃ {a // a ∈ A}) (u : Fin A.card → Bool)
    (i : Fin A.card) :
    (e i).1 ∈ positiveSubset A e u ↔ u i = true := by
  constructor
  · intro hi
    rcases Finset.mem_image.mp hi with ⟨j, hj, hji⟩
    have hji' : j = i := enum_value_injective A e hji
    simpa [positiveSubset, hji'] using (Finset.mem_filter.mp hj).2
  · intro hi
    rw [positiveSubset]
    exact Finset.mem_image.mpr ⟨i, by simp [hi], rfl⟩

private lemma positiveSubset_sum_eq (A : Finset ℕ)
    (e : Fin A.card ≃ {a // a ∈ A}) (u : Fin A.card → Bool) :
    (positiveSubset A e u).sum id =
      ∑ i : Fin A.card, if u i = true then (e i).1 else 0 := by
  classical
  rw [positiveSubset]
  rw [Finset.sum_image]
  · simp [Finset.sum_filter]
  · intro i hi j hj hij
    exact enum_value_injective A e hij

private lemma signedSum_eq_two_positiveSubset_sub_total (A : Finset ℕ)
    (e : Fin A.card ≃ {a // a ∈ A}) (u : Fin A.card → Bool) :
    signedSum A e u =
      2 * ((positiveSubset A e u).sum (fun x => x) : ℤ) -
        (∑ i : Fin A.card, ((e i).1 : ℤ)) := by
  classical
  unfold signedSum
  have hpos :
      ((positiveSubset A e u).sum (fun x => x) : ℤ) =
        ∑ i : Fin A.card, if u i = true then ((e i).1 : ℤ) else 0 := by
    simpa using congrArg (fun n : ℕ => (n : ℤ)) (positiveSubset_sum_eq A e u)
  calc
    (∑ i : Fin A.card,
        if u i = true then ((e i).1 : ℤ) else -((e i).1 : ℤ))
        = ∑ i : Fin A.card,
            (2 * (if u i = true then ((e i).1 : ℤ) else 0) -
              ((e i).1 : ℤ)) := by
          refine Finset.sum_congr rfl ?_
          intro i _hi
          by_cases hui : u i = true
          · simp [hui]
            ring
          · simp [hui]
    _ = 2 * (∑ i : Fin A.card, if u i = true then ((e i).1 : ℤ) else 0) -
          ∑ i : Fin A.card, ((e i).1 : ℤ) := by
          rw [Finset.sum_sub_distrib, ← Finset.mul_sum]
    _ = 2 * ((positiveSubset A e u).sum (fun x => x) : ℤ) -
          ∑ i : Fin A.card, ((e i).1 : ℤ) := by
          rw [hpos]

private lemma signedSum_injective (N : ℕ) (A : Finset ℕ)
    (e : Fin A.card ≃ {a // a ∈ A}) (hA : IsSumDistinctSet A N) :
    Function.Injective (signedSum A e) := by
  classical
  intro u v huv
  have hpos_int :
      ((positiveSubset A e u).sum (fun x => x) : ℤ) =
        ((positiveSubset A e v).sum (fun x => x) : ℤ) := by
    have hu := signedSum_eq_two_positiveSubset_sub_total A e u
    have hv := signedSum_eq_two_positiveSubset_sub_total A e v
    linarith
  have hpos_nat :
      (positiveSubset A e u).sum (fun x => x) =
        (positiveSubset A e v).sum (fun x => x) := by
    exact Nat.cast_injective (R := ℤ) (by simpa using hpos_int)
  have hsets :
      positiveSubset A e u = positiveSubset A e v := by
    have hsum :
        (fun (S : A.powerset) => S.1.sum id)
            ⟨positiveSubset A e u, positiveSubset_mem_powerset A e u⟩ =
          (fun (S : A.powerset) => S.1.sum id)
            ⟨positiveSubset A e v, positiveSubset_mem_powerset A e v⟩ := by
      simpa using hpos_nat
    have hsub :
        (⟨positiveSubset A e u, positiveSubset_mem_powerset A e u⟩ : A.powerset) =
          ⟨positiveSubset A e v, positiveSubset_mem_powerset A e v⟩ :=
      hA.2 hsum
    exact congrArg Subtype.val hsub
  funext i
  have hi : u i = true ↔ v i = true := by
    rw [← mem_positiveSubset_iff A e u i, hsets,
      mem_positiveSubset_iff A e v i]
  cases hui : u i <;> cases hvi : v i <;> simp [hui, hvi] at hi ⊢

private lemma signedSum_update_not (A : Finset ℕ)
    (e : Fin A.card ≃ {a // a ∈ A}) (u : Fin A.card → Bool)
    (i : Fin A.card) :
    signedSum A e (Function.update u i (!(u i))) =
      signedSum A e u +
        (if u i = true then -2 * ((e i).1 : ℤ) else 2 * ((e i).1 : ℤ)) := by
  classical
  unfold signedSum
  let f : (Fin A.card → Bool) → Fin A.card → ℤ := fun w j =>
    if w j = true then ((e j).1 : ℤ) else -((e j).1 : ℤ)
  change
    (∑ x : Fin A.card, f (Function.update u i (!(u i))) x) =
      (∑ x : Fin A.card, f u x) +
        (if u i = true then -2 * ((e i).1 : ℤ) else 2 * ((e i).1 : ℤ))
  have hrest :
      (∑ x ∈ Finset.univ.erase i, f (Function.update u i (!(u i))) x) =
        ∑ x ∈ Finset.univ.erase i, f u x := by
    refine Finset.sum_congr rfl ?_
    intro j hj
    have hji : j ≠ i := (Finset.mem_erase.mp hj).1
    simp [f, Function.update_of_ne hji]
  rw [← Finset.add_sum_erase (s := Finset.univ)
      (f := f (Function.update u i (!(u i)))) (a := i) (by simp),
    ← Finset.add_sum_erase (s := Finset.univ) (f := f u) (a := i) (by simp),
    hrest]
  cases hui : u i <;> simp [f, hui, Function.update_self] <;> linarith

end Erdos1
end AmraNewCandidates20260612
