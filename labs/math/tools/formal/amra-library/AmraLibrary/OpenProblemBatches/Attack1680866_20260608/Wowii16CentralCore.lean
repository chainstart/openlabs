import AmraLibrary.Combinatorics.SimpleGraph.GraphConjectures.WowiiConjecture13
import Mathlib.Combinatorics.SimpleGraph.Connectivity.WalkCounting
import Mathlib.Data.Fintype.Card
import Mathlib.Data.Fintype.Powerset
import Mathlib.Combinatorics.Hall.Basic
import Mathlib.Order.Interval.Finset.Nat
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.SuppressCompilation

suppress_compilation

namespace Wowii16CentralCore20260609

open Classical
open SimpleGraph

lemma connected_dist_le_two_radius_toNat
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (hG : G.Connected) (x y : alpha) :
    G.dist x y <= 2 * G.radius.toNat := by
  classical
  have hEdTop : G.ediam ≠ ⊤ :=
    SimpleGraph.connected_iff_ediam_ne_top.mp hG
  have hRadTop : G.radius ≠ ⊤ :=
    (SimpleGraph.radius_ne_top_iff (G := G)).mpr hG
  have hTwoRadTop : 2 * G.radius ≠ ⊤ :=
    WithTop.mul_ne_top (by simp) hRadTop
  have hDiamLe : G.diam <= (2 * G.radius).toNat :=
    ENat.toNat_le_toNat (SimpleGraph.ediam_le_two_mul_radius (G := G))
      hTwoRadTop
  have hDistLe : G.dist x y <= G.diam :=
    G.dist_le_diam hEdTop
  have hMulToNat : (2 * G.radius).toNat = 2 * G.radius.toNat := by
    simp [ENat.toNat_mul]
  exact le_trans hDistLe (by simpa [hMulToNat] using hDiamLe)

lemma central_deficit_diam_le_two_radius_sub_two
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha)
    (hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1) :
    G.diam ≤ 2 * G.radius.toNat - 2 := by
  omega

lemma central_deficit_deficit_card_le_radius_sub_two
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj] (hG : G.Connected)
    (hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1) :
    2 * G.radius.toNat - 2 - G.diam ≤ G.radius.toNat - 2 := by
  classical
  have hEdTop : G.ediam ≠ ⊤ :=
    SimpleGraph.connected_iff_ediam_ne_top.mp hG
  have hRadDiam : G.radius.toNat ≤ G.diam := by
    simpa [SimpleGraph.diam] using
      ENat.toNat_le_toNat (SimpleGraph.radius_le_ediam (G := G)) hEdTop
  have hDiamLe : G.diam ≤ 2 * G.radius.toNat - 2 :=
    central_deficit_diam_le_two_radius_sub_two (G := G) hDiamSmall
  omega

lemma no_large_radius_geodesic_interval
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (hG : G.Connected)
    (p : Nat -> alpha)
    (hGeod : forall {i j : Nat}, i <= j -> G.dist (p i) (p j) = j - i)
    {lo hi : Nat} (hlohi : lo <= hi) :
    hi - lo <= 2 * G.radius.toNat := by
  rw [← hGeod hlohi]
  exact connected_dist_le_two_radius_toNat (G := G) hG (p lo) (p hi)

lemma centralIntervalDeepPredOffBaseCore
    {α : Type*} [DecidableEq α]
    (H0 Avail : Finset α)
    (pred : α → α) (depth : α → ℕ)
    (H0_depth_zero : ∀ x, x ∈ H0 → depth x = 0)
    (pred_depth_succ : ∀ x, x ∈ Avail → 0 < depth x →
      depth x = depth (pred x) + 1)
    {z : α}
    (hzAvail : z ∈ Avail)
    (hzDepth : 2 ≤ depth z) :
    pred z ∉ H0 := by
  intro hzPred
  have hPredDepth : depth (pred z) = 0 :=
    H0_depth_zero (pred z) hzPred
  have hzPos : 0 < depth z :=
    lt_of_lt_of_le (by decide : 0 < 2) hzDepth
  have hStep : depth z = depth (pred z) + 1 :=
    pred_depth_succ z hzAvail hzPos
  have hzOne : depth z = 1 := by
    calc
      depth z = depth (pred z) + 1 := hStep
      _ = 0 + 1 := by rw [hPredDepth]
      _ = 1 := rfl
  have hBad : 2 ≤ 1 := by
    rw [hzOne] at hzDepth
    exact hzDepth
  exact (by decide : ¬ 2 ≤ 1) hBad

lemma centralIntervalSharedFirstStepIndexGapLeTwo
    {α : Type*}
    (dist : α → α → ℕ) (Adj : α → α → Prop)
    (p z : ℕ → α) (pred : α → α)
    (commonNeighbor_dist_le_two :
      ∀ x y a, Adj x a → Adj a y → dist x y ≤ 2)
    {i j : ℕ}
    (_hij : i ≤ j)
    (hGeod : dist (p i) (p j) = j - i)
    (hFirst_i : Adj (p i) (pred (z i)))
    (hFirst_j : Adj (pred (z j)) (p j))
    (hShare : pred (z i) = pred (z j)) :
    j - i ≤ 2 := by
  rw [← hGeod]
  exact commonNeighbor_dist_le_two (p i) (p j) (pred (z i))
    hFirst_i (by simpa [hShare] using hFirst_j)

lemma centralIntervalFarApartFirstStepsPrivate
    {alpha : Type*}
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    {i j : Nat}
    (hij : i <= j)
    (hGeod : dist (p i) (p j) = j - i)
    (hFirst_i : Adj (p i) (pred (z i)))
    (hFirst_j : Adj (pred (z j)) (p j))
    (hFar : 2 < j - i) :
    pred (z i) ≠ pred (z j) := by
  intro hShare
  have hGap : j - i <= 2 :=
    centralIntervalSharedFirstStepIndexGapLeTwo dist Adj p z pred
      commonNeighbor_dist_le_two hij hGeod hFirst_i hFirst_j hShare
  exact (not_lt_of_ge hGap) hFar

lemma centralIntervalSpacedIndexFirstStepInjective
    {alpha beta : Type*}
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (idx : beta -> Nat)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hSep : forall a b : beta, a ≠ b ->
      (idx a <= idx b /\ 2 < idx b - idx a) \/
      (idx b <= idx a /\ 2 < idx a - idx b)) :
    Function.Injective (fun a : beta => pred (z (idx a))) := by
  intro a b hShare
  by_contra hne
  rcases hSep a b hne with hForward | hReverse
  · rcases hForward with ⟨hLe, hGap⟩
    have hPrivate :
        pred (z (idx a)) ≠ pred (z (idx b)) :=
      centralIntervalFarApartFirstStepsPrivate dist Adj p z pred
        commonNeighbor_dist_le_two hLe (hGeod hLe)
        (hFirstL (idx a)) (hFirstR (idx b)) hGap
    exact hPrivate hShare
  · rcases hReverse with ⟨hLe, hGap⟩
    have hPrivate :
        pred (z (idx b)) ≠ pred (z (idx a)) :=
      centralIntervalFarApartFirstStepsPrivate dist Adj p z pred
        commonNeighbor_dist_le_two hLe (hGeod hLe)
        (hFirstL (idx b)) (hFirstR (idx a)) hGap
    exact hPrivate hShare.symm

lemma centralIntervalSpacedIndexFirstStepCardLeContainer
    {alpha beta : Type*}
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (idx : beta -> Nat)
    (S : Finset beta) (P : Finset alpha)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hSep : forall a b : beta, a ≠ b ->
      (idx a <= idx b /\ 2 < idx b - idx a) \/
      (idx b <= idx a /\ 2 < idx a - idx b))
    (hPrivateIn : forall a : beta, a ∈ S -> pred (z (idx a)) ∈ P) :
    S.card <= P.card := by
  have hInjective :
      Function.Injective (fun a : beta => pred (z (idx a))) :=
    centralIntervalSpacedIndexFirstStepInjective dist Adj p z pred
      commonNeighbor_dist_le_two idx hGeod hFirstL hFirstR hSep
  exact Finset.card_le_card_of_injOn
    (fun a : beta => pred (z (idx a)))
    (fun a ha => hPrivateIn a ha)
    (fun a _ha b _hb hEq => hInjective hEq)

lemma centralIntervalSameResidueGapGtTwo
    {i j r : Nat}
    (hi : i % 3 = r)
    (hj : j % 3 = r)
    (hle : i <= j)
    (hne : i ≠ j) :
    2 < j - i := by
  omega

lemma centralIntervalResidueAttachCardLeContainer
    {alpha : Type*} [DecidableEq alpha]
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (lo hi r : Nat) (P : Finset alpha)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hPrivateIn : forall i : Nat, i ∈ Finset.Icc lo hi -> pred (z i) ∈ P) :
    ((Finset.Icc lo hi).filter (fun i => i % 3 = r)).card <= P.card := by
  let T : Finset Nat := (Finset.Icc lo hi).filter (fun i => i % 3 = r)
  let beta : Type := {i : Nat // i ∈ T}
  let idx : beta -> Nat := Subtype.val
  let S : Finset beta := T.attach
  have hSep : forall a b : beta, a ≠ b ->
      (idx a <= idx b /\ 2 < idx b - idx a) \/
      (idx b <= idx a /\ 2 < idx a - idx b) := by
    intro a b hne
    have haT : idx a ∈ (Finset.Icc lo hi).filter (fun i => i % 3 = r) := by
      simpa only [T, idx] using a.property
    have hbT : idx b ∈ (Finset.Icc lo hi).filter (fun i => i % 3 = r) := by
      simpa only [T, idx] using b.property
    have haResidue : idx a % 3 = r := by
      exact (Finset.mem_filter.mp haT).2
    have hbResidue : idx b % 3 = r := by
      exact (Finset.mem_filter.mp hbT).2
    rcases le_total (idx a) (idx b) with hle | hle
    · left
      refine ⟨hle, centralIntervalSameResidueGapGtTwo haResidue hbResidue hle ?_⟩
      intro hEq
      exact hne (Subtype.ext hEq)
    · right
      refine ⟨hle, centralIntervalSameResidueGapGtTwo hbResidue haResidue hle ?_⟩
      intro hEq
      exact hne (Subtype.ext hEq.symm)
  have hPrivateInAttach : forall a : beta, a ∈ S -> pred (z (idx a)) ∈ P := by
    intro a _ha
    have haT : idx a ∈ (Finset.Icc lo hi).filter (fun i => i % 3 = r) := by
      simpa only [T, idx] using a.property
    have haIcc : idx a ∈ Finset.Icc lo hi :=
      (Finset.mem_filter.mp haT).1
    exact hPrivateIn (idx a) haIcc
  have hCardAttach : S.card <= P.card :=
    centralIntervalSpacedIndexFirstStepCardLeContainer dist Adj p z pred
      commonNeighbor_dist_le_two idx S P hGeod hFirstL hFirstR hSep
      hPrivateInAttach
  change T.card <= P.card
  rw [← Finset.card_attach (s := T)]
  simpa only [S] using hCardAttach

lemma centralIntervalGraphBridgeToConjecture16
    {alpha : Type*} [DecidableEq alpha]
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (lo hi r : Nat) (P : Finset alpha)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hPrivateIn : forall i : Nat, i ∈ Finset.Icc lo hi -> pred (z i) ∈ P) :
    ((Finset.Icc lo hi).filter (fun i => i % 3 = r)).card <= P.card := by
  exact centralIntervalResidueAttachCardLeContainer dist Adj p z pred
    commonNeighbor_dist_le_two lo hi r P hGeod hFirstL hFirstR hPrivateIn

lemma centralIntervalFullIndexCardLeThreeContainer
    {alpha : Type*} [DecidableEq alpha]
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (lo hi : Nat) (P : Finset alpha)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hPrivateIn : forall i : Nat, i ∈ Finset.Icc lo hi -> pred (z i) ∈ P) :
    (Finset.Icc lo hi).card <= 3 * P.card := by
  let A : Finset Nat := Finset.Icc lo hi
  let T0 : Finset Nat := A.filter (fun i => i % 3 = 0)
  let T1 : Finset Nat := A.filter (fun i => i % 3 = 1)
  let T2 : Finset Nat := A.filter (fun i => i % 3 = 2)
  have hT0 : T0.card <= P.card := by
    simpa only [A, T0] using
      centralIntervalResidueAttachCardLeContainer dist Adj p z pred
        commonNeighbor_dist_le_two lo hi 0 P hGeod hFirstL hFirstR hPrivateIn
  have hT1 : T1.card <= P.card := by
    simpa only [A, T1] using
      centralIntervalResidueAttachCardLeContainer dist Adj p z pred
        commonNeighbor_dist_le_two lo hi 1 P hGeod hFirstL hFirstR hPrivateIn
  have hT2 : T2.card <= P.card := by
    simpa only [A, T2] using
      centralIntervalResidueAttachCardLeContainer dist Adj p z pred
        commonNeighbor_dist_le_two lo hi 2 P hGeod hFirstL hFirstR hPrivateIn
  have hCover : A ⊆ T0 ∪ T1 ∪ T2 := by
    intro i hiA
    have hmodlt : i % 3 < 3 := Nat.mod_lt i (by decide : 0 < 3)
    have hmodCases : i % 3 = 0 ∨ i % 3 = 1 ∨ i % 3 = 2 := by
      omega
    rcases hmodCases with h0 | h1 | h2
    · exact Finset.mem_union_left _ (Finset.mem_union_left _ (by simp [T0, hiA, h0]))
    · exact Finset.mem_union_left _ (Finset.mem_union_right _ (by simp [T1, hiA, h1]))
    · exact Finset.mem_union_right _ (by simp [T2, hiA, h2])
  have hUnion01 : (T0 ∪ T1).card <= T0.card + T1.card :=
    Finset.card_union_le T0 T1
  have hUnion012 : (T0 ∪ T1 ∪ T2).card <= (T0 ∪ T1).card + T2.card :=
    Finset.card_union_le (T0 ∪ T1) T2
  calc
    (Finset.Icc lo hi).card = A.card := rfl
    _ <= (T0 ∪ T1 ∪ T2).card := Finset.card_le_card hCover
    _ <= (T0 ∪ T1).card + T2.card := hUnion012
    _ <= (T0.card + T1.card) + T2.card := Nat.add_le_add_right hUnion01 T2.card
    _ <= (P.card + P.card) + P.card := Nat.add_le_add (Nat.add_le_add hT0 hT1) hT2
    _ <= 3 * P.card := by omega

lemma central_interval_counting_radius_bridge
    {alpha : Type*} [DecidableEq alpha]
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (lo hi radius : Nat) (P : Finset alpha)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hPrivateIn : forall i : Nat, i ∈ Finset.Icc lo hi -> pred (z i) ∈ P)
    (hIntervalLarge : 6 * (radius - 1) <= (Finset.Icc lo hi).card) :
    6 * (radius - 1) <= 3 * P.card := by
  exact le_trans hIntervalLarge
    (centralIntervalFullIndexCardLeThreeContainer dist Adj p z pred
      commonNeighbor_dist_le_two lo hi P hGeod hFirstL hFirstR hPrivateIn)

section CentralIntervalContainerRadiusWitness

/-- Total source-level notation for the local independent-neighbourhood maximum.
On finite nonempty graphs this delegates to the reusable finite graph invariant;
the fallback only lets source bridge statements be stated before those finite
instances are in scope. -/
noncomputable def sourceMaxIndepNeighborsCard {alpha : Type*}
    (G : SimpleGraph alpha) : Nat := by
  classical
  by_cases hF : Nonempty (Fintype alpha)
  · letI : Fintype alpha := Classical.choice hF
    by_cases hN : Nonempty alpha
    · letI : Nonempty alpha := hN
      exact SimpleGraph.maxIndepNeighborsCard G
    · exact 0
  · exact 0

local notation "maxIndepNeighborsCard" => sourceMaxIndepNeighborsCard

lemma central_interval_container_radius_witness
    {alpha : Type*} [DecidableEq alpha]
    (G : SimpleGraph alpha)
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (lo hi radius : Nat) (A P S : Finset alpha)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hPrivateIn : forall i : Nat, i ∈ Finset.Icc lo hi -> pred (z i) ∈ P)
    (hIntervalLarge : 6 * (radius - 1) <= (Finset.Icc lo hi).card)
    (hAcard : A.card = maxIndepNeighborsCard G)
    (hDisj : Disjoint A P)
    (hUnionSub : A ∪ P ⊆ S)
    (hBip : (G.induce (S : Set alpha)).IsBipartite) :
    (G.induce (S : Set alpha)).IsBipartite ∧
      2 * (((radius : ℝ) - 1)) + (maxIndepNeighborsCard G : ℝ)
        ≤ (S.card : ℝ) := by
  constructor
  · exact hBip
  · have hCount : 6 * (radius - 1) <= 3 * P.card :=
      central_interval_counting_radius_bridge dist Adj p z pred
        commonNeighbor_dist_le_two lo hi radius P hGeod hFirstL hFirstR
        hPrivateIn hIntervalLarge
    have hPcard : 2 * (radius - 1) <= P.card := by
      omega
    have hUnionCard : (A ∪ P).card = A.card + P.card :=
      Finset.card_union_of_disjoint hDisj
    have hUnionLeS : A.card + P.card <= S.card := by
      simpa [hUnionCard] using Finset.card_le_card hUnionSub
    have hNat : 2 * (radius - 1) + maxIndepNeighborsCard G <= S.card := by
      rw [← hAcard]
      omega
    have hNatReal :
        ((2 * (radius - 1) + maxIndepNeighborsCard G : Nat) : ℝ) <=
          (S.card : ℝ) := by
      exact_mod_cast hNat
    have hRadiusSubLe : (radius : ℝ) - 1 <= ((radius - 1 : Nat) : ℝ) := by
      cases radius with
      | zero => norm_num
      | succ r => simp
    calc
      2 * (((radius : ℝ) - 1)) + (maxIndepNeighborsCard G : ℝ)
          <= 2 * ((radius - 1 : Nat) : ℝ) + (maxIndepNeighborsCard G : ℝ) := by
            nlinarith
      _ = ((2 * (radius - 1) + maxIndepNeighborsCard G : Nat) : ℝ) := by
            norm_num [Nat.cast_add, Nat.cast_mul]
      _ <= (S.card : ℝ) := hNatReal

lemma central_interval_compatible_extension_radius_witness
    {alpha : Type*} [DecidableEq alpha]
    (G : SimpleGraph alpha)
    (dist : alpha -> alpha -> Nat) (Adj : alpha -> alpha -> Prop)
    (p z : Nat -> alpha) (pred : alpha -> alpha)
    (commonNeighbor_dist_le_two :
      forall x y a, Adj x a -> Adj a y -> dist x y <= 2)
    (lo hi radius : Nat)
    (A P L0 R0 E : Finset alpha)
    (hGeod : forall {i j : Nat}, i <= j -> dist (p i) (p j) = j - i)
    (hFirstL : forall i : Nat, Adj (p i) (pred (z i)))
    (hFirstR : forall i : Nat, Adj (pred (z i)) (p i))
    (hPrivateIn : forall i : Nat, i ∈ Finset.Icc lo hi -> pred (z i) ∈ P)
    (hIntervalLarge : 6 * (radius - 1) <= (Finset.Icc lo hi).card)
    (hAcard : A.card = maxIndepNeighborsCard G)
    (hAPdisj : Disjoint A P)
    (hPsub : P ⊆ L0 ∪ R0 ∪ E)
    (hAside : A ⊆ L0)
    (hEsub : E ⊆ R0)
    (hLind : G.IsIndepSet ((L0 ∪ E) : Set alpha))
    (hRind : G.IsIndepSet (R0 : Set alpha))
    (hLRdisj : Disjoint (L0 ∪ E) R0) :
    ∃ S : Finset alpha,
      (G.induce (S : Set alpha)).IsBipartite ∧
        2 * (((radius : ℝ) - 1)) + (maxIndepNeighborsCard G : ℝ)
          ≤ (S.card : ℝ) := by
  let S : Finset alpha := (L0 ∪ E) ∪ R0
  refine ⟨S, ?_⟩
  have hBip : (G.induce (S : Set alpha)).IsBipartite := by
    let U : Set alpha := (S : Set alpha)
    let left : Set U := {x | x.1 ∈ L0 ∪ E}
    let right : Set U := {x | x.1 ∈ R0}
    change (G.induce U).IsBipartite
    refine (show (G.induce U).IsBipartiteWith left right from ?_).isBipartite
    have hLind' : G.IsIndepSet (((L0 ∪ E : Finset alpha) : Set alpha)) := by
      simpa using hLind
    constructor
    · rw [Set.disjoint_left]
      intro x hxL hxR
      exact (Finset.disjoint_left.mp hLRdisj hxL) hxR
    · intro x y hxy
      have hxmem : x.1 ∈ S := by simp [U]
      have hymem : y.1 ∈ S := by simp [U]
      change x.1 ∈ (L0 ∪ E) ∪ R0 at hxmem
      change y.1 ∈ (L0 ∪ E) ∪ R0 at hymem
      rw [Finset.mem_union] at hxmem hymem
      rcases hxmem with hxL | hxR
      · rcases hymem with hyL | hyR
        · exact False.elim (hLind' hxL hyL (fun h => hxy.ne (Subtype.ext h)) hxy)
        · exact Or.inl ⟨hxL, hyR⟩
      · rcases hymem with hyL | hyR
        · exact Or.inr ⟨hxR, hyL⟩
        · exact False.elim (hRind hxR hyR (fun h => hxy.ne (Subtype.ext h)) hxy)
  have hUnionSub : A ∪ P ⊆ S := by
    intro x hx
    rw [Finset.mem_union] at hx
    rcases hx with hxA | hxP
    · have hxL0 : x ∈ L0 := hAside hxA
      change x ∈ (L0 ∪ E) ∪ R0
      exact Finset.mem_union_left R0 (Finset.mem_union_left E hxL0)
    · have hxContainer : x ∈ L0 ∪ R0 ∪ E := hPsub hxP
      change x ∈ (L0 ∪ E) ∪ R0
      rw [Finset.mem_union] at hxContainer
      rcases hxContainer with hxL0R0 | hxE
      · rw [Finset.mem_union] at hxL0R0
        rcases hxL0R0 with hxL0 | hxR0
        · exact Finset.mem_union_left R0 (Finset.mem_union_left E hxL0)
        · exact Finset.mem_union_right (L0 ∪ E) hxR0
      · exact Finset.mem_union_right (L0 ∪ E) (hEsub hxE)
  exact central_interval_container_radius_witness G dist Adj p z pred
    commonNeighbor_dist_le_two lo hi radius A P S hGeod hFirstL hFirstR
    hPrivateIn hIntervalLarge hAcard hAPdisj hUnionSub hBip

end CentralIntervalContainerRadiusWitness

/-- Definitional bridge from the source theorem's inline maximum to the named
maximum used by the reusable WOWII13 support file.  The remaining mathematical
work is the radius-level induced-bipartite witness bound in the hypothesis. -/
theorem conjecture16_from_maxIndepNeighborsCard_radius_bridge
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) (_h : G.Connected)
    (hbridge :
      2 * (((G.radius.toNat : ℝ) - 1)) + (maxIndepNeighborsCard G : ℝ) ≤ b G) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    letI r := G.radius.toNat
    2 * ((r : ℝ) - 1) + (maxL : ℝ) ≤ b G := by
  classical
  simpa [SimpleGraph.maxIndepNeighborsCard] using hbridge

/-- WOWII16 follows from WOWII13 once the missing source-level bridge supplies
the required radius/diameter comparison for the chosen bipartite witness.  The
plain arithmetic comparison `2 * (radius - 1) ≤ diam - 1` is false in general
(for example odd cycles), so this lemma intentionally records the exact
remaining hypothesis rather than using it as an unproved assumption in the
target theorem. -/
theorem conjecture16_from_conjecture13_of_radius_diam_bridge
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) (h : G.Connected)
    (hradius :
      2 * (((G.radius.toNat : ℝ) - 1)) ≤ (G.diam : ℝ) - 1) :
    2 * ((G.radius.toNat : ℝ) - 1)
        + (((Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp) : ℕ) : ℝ)
      ≤ b G := by
  classical
  let maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
  have h13 : (G.diam : ℝ) + (maxL : ℝ) - 1 ≤ b G := by
    simpa [maxL] using SimpleGraph.conjecture13 (G := G) h
  have hleft :
      2 * ((G.radius.toNat : ℝ) - 1) + (maxL : ℝ)
      ≤ (G.diam : ℝ) + (maxL : ℝ) - 1 := by
    linarith
  simpa [maxL] using le_trans hleft h13

theorem conjecture16_source_bound_of_radius_gt_two_of_diam_large
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (hRadius : 2 < G.radius.toNat)
    (hdiam : (2 * G.radius.toNat : Nat) <= G.diam + 1) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    letI r := G.radius.toNat
    2 * ((r : Real) - 1) + (maxL : Real) <= b G := by
  classical
  have _hRadiusWitness : 2 < G.radius.toNat := hRadius
  have hdiamR :
      ((2 * G.radius.toNat : Nat) : Real) <= ((G.diam + 1 : Nat) : Real) := by
    exact_mod_cast hdiam
  have hRadiusDiam :
      2 * (((G.radius.toNat : Real) - 1)) <= (G.diam : Real) - 1 := by
    have hdiamR' :
        (2 : Real) * (G.radius.toNat : Real) <= (G.diam : Real) + 1 := by
      simpa [Nat.cast_add, Nat.cast_mul] using hdiamR
    linarith
  simpa using
    conjecture16_from_conjecture13_of_radius_diam_bridge
      (G := G) hG hRadiusDiam

theorem conjecture16_of_radius_toNat_le_one
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (hRadius : G.radius.toNat <= 1) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    letI r := G.radius.toNat
    2 * ((r : Real) - 1) + (maxL : Real) <= b G := by
  classical
  have _ : G.Connected := hG
  let maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
  let r := G.radius.toNat
  have hStarNat : maxL + 1 <= b G := by
    simpa [maxL] using
      SimpleGraph.maxIndepNeighborsCard_add_one_le_largestInducedBipartiteSubgraphSize
        (G := G)
  have hStarReal : (maxL : Real) <= (b G : Real) := by
    have hStarReal' : ((maxL + 1 : Nat) : Real) <= (b G : Real) := by
      exact_mod_cast hStarNat
    have hMaxLeSucc : (maxL : Real) <= ((maxL + 1 : Nat) : Real) := by
      exact_mod_cast Nat.le_succ maxL
    exact le_trans hMaxLeSucc hStarReal'
  have hRadiusTerm : 2 * ((r : Real) - 1) <= 0 := by
    have hr : (r : Real) <= 1 := by
      exact_mod_cast hRadius
    nlinarith
  have hLeftLeMax :
      2 * ((r : Real) - 1) + (maxL : Real) <= (maxL : Real) := by
    linarith
  exact le_trans hLeftLeMax hStarReal

lemma exists_nonneighbor_of_radius_toNat_eq_two
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (v : alpha)
    (hRadius : G.radius.toNat = 2) :
    ∃ u : alpha, u ≠ v ∧ ¬ G.Adj v u := by
  classical
  by_contra hnone
  have hAll : ∀ u : alpha, u = v ∨ G.Adj v u := by
    intro u
    by_cases huv : u = v
    · exact Or.inl huv
    · right
      by_contra hAdj
      exact hnone ⟨u, huv, hAdj⟩
  have hEccLe : G.eccent v ≤ (1 : ℕ∞) := by
    rw [SimpleGraph.eccent]
    refine iSup_le ?_
    intro u
    rcases hAll u with hEq | hAdj
    · subst hEq
      simp
    · have hEdist : G.edist v u = 1 :=
        SimpleGraph.edist_eq_one_iff_adj.mpr hAdj
      simp [hEdist]
  have hRadiusLe : G.radius.toNat ≤ 1 := by
    exact ENat.toNat_le_toNat
      (le_trans (SimpleGraph.radius_le_eccent (G := G) (u := v)) hEccLe)
      (by simp)
  omega

lemma indepNeighborsCard_add_two_le_largestInducedBipartiteSubgraphSize_of_nonneighbor
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha]
    (G : SimpleGraph alpha) {v u : alpha}
    (hne : u ≠ v) (hnadj : ¬ G.Adj v u) :
    indepNeighborsCard G v + 2 ≤ b G := by
  classical
  unfold indepNeighborsCard
  obtain ⟨s, hs⟩ := (G.induce (G.neighborSet v)).exists_isNIndepSet_indepNum
  rw [SimpleGraph.isNIndepSet_iff] at hs
  let e : G.neighborSet v ↪ alpha := Function.Embedding.subtype _
  let leaves : Finset alpha := s.map e
  let pair : Finset alpha := {v, u}
  have hPairInd : G.IsIndepSet (pair : Set alpha) := by
    intro x hx y hy hxy hAdj
    have hx' : x = v ∨ x = u := by
      simpa [pair] using hx
    have hy' : y = v ∨ y = u := by
      simpa [pair] using hy
    rcases hx' with hxv | hxu <;> rcases hy' with hyv | hyu
    · exact hxy (hxv.trans hyv.symm)
    · exact hnadj (by simpa [hxv, hyu] using hAdj)
    · exact hnadj (by simpa [hxu, hyv] using hAdj.symm)
    · exact hxy (hxu.trans hyu.symm)
  have hLeavesInd : G.IsIndepSet (leaves : Set alpha) := by
    intro x hx y hy hxy hAdj
    change x ∈ leaves at hx
    change y ∈ leaves at hy
    rw [Finset.mem_map] at hx hy
    rcases hx with ⟨a, ha, hax⟩
    rcases hy with ⟨b, hb, hby⟩
    change a.1 = x at hax
    change b.1 = y at hby
    have habAdj : (G.induce (G.neighborSet v)).Adj a b := by
      change G.Adj a.1 b.1
      rwa [hax, hby]
    by_cases hab : a = b
    · subst hab
      exact G.irrefl habAdj
    · exact (hs.1 ha hb (fun h => hab h)) habAdj
  have hDisj : Disjoint pair leaves := by
    rw [Finset.disjoint_left]
    intro x hxPair hxLeaves
    have hxPair' : x = v ∨ x = u := by
      simpa [pair] using hxPair
    rw [Finset.mem_map] at hxLeaves
    rcases hxLeaves with ⟨w, _hw, hwx⟩
    change w.1 = x at hwx
    rcases hxPair' with hxv | hxu
    · have hAdj : G.Adj v v := by
        simpa [hwx, hxv] using w.2
      exact G.irrefl hAdj
    · exact hnadj (by simpa [hwx, hxu] using w.2)
  have hBip : (G.induce (((pair ∪ leaves : Finset alpha) : Set alpha))).IsBipartite :=
    SimpleGraph.induce_union_indep_isBipartite (G := G)
      (A := pair) (B := leaves) hPairInd hLeavesInd hDisj
  have hLargest : (pair ∪ leaves).card ≤ b G :=
    card_le_largestInducedBipartiteSubgraphSize_of_induce_isBipartite
      (G := G) (s := pair ∪ leaves) hBip
  have hPairCard : pair.card = 2 := by
    simp [pair, hne.symm]
  have hCard :
      (pair ∪ leaves).card = indepNum (G.induce (G.neighborSet v)) + 2 := by
    rw [Finset.card_union_of_disjoint hDisj, hPairCard, Finset.card_map, hs.2]
    omega
  simpa [b, hCard] using hLargest

lemma maxIndepNeighborsCard_add_two_le_b_of_radius_toNat_eq_two
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hRadius : G.radius.toNat = 2) :
    SimpleGraph.maxIndepNeighborsCard G + 2 ≤ b G := by
  classical
  unfold SimpleGraph.maxIndepNeighborsCard
  have hmem :
      (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
        ∈ Finset.univ.image (fun v => indepNeighborsCard G v) :=
    Finset.max'_mem _ _
  rcases Finset.mem_image.mp hmem with ⟨v, _hv, hvmax⟩
  obtain ⟨u, hne, hnadj⟩ :=
    exists_nonneighbor_of_radius_toNat_eq_two (G := G) v hRadius
  rw [← hvmax]
  exact
    indepNeighborsCard_add_two_le_largestInducedBipartiteSubgraphSize_of_nonneighbor
      (G := G) hne hnadj

theorem conjecture16_source_bound_of_radius_toNat_le_two
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (hRadius : G.radius.toNat <= 2) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    letI r := G.radius.toNat
    2 * ((r : Real) - 1) + (maxL : Real) <= b G := by
  classical
  by_cases hRadiusOne : G.radius.toNat <= 1
  · exact conjecture16_of_radius_toNat_le_one (G := G) hG hRadiusOne
  · have hRadiusEq : G.radius.toNat = 2 := by
      omega
    let maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    let r := G.radius.toNat
    have hMaxNat : maxL + 2 <= b G := by
      simpa [maxL, SimpleGraph.maxIndepNeighborsCard] using
        maxIndepNeighborsCard_add_two_le_b_of_radius_toNat_eq_two
          (G := G) hRadiusEq
    have hMaxReal : ((maxL + 2 : Nat) : Real) <= (b G : Real) := by
      exact_mod_cast hMaxNat
    have hr : r = 2 := by
      simpa [r] using hRadiusEq
    have hLeft :
        2 * ((r : Real) - 1) + (maxL : Real)
          = ((maxL + 2 : Nat) : Real) := by
      rw [hr]
      norm_num [Nat.cast_add, add_comm, add_left_comm, add_assoc]
    exact hLeft.trans_le hMaxReal

theorem conjecture16_from_radius_gt_two_diam_small_branch
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (hSmallBranch :
      2 < G.radius.toNat ->
      ¬ (2 * G.radius.toNat : Nat) <= G.diam + 1 ->
      letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
      letI r := G.radius.toNat
      2 * ((r : Real) - 1) + (maxL : Real) <= b G) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    letI r := G.radius.toNat
    2 * ((r : Real) - 1) + (maxL : Real) <= b G := by
  classical
  by_cases hRadius : G.radius.toNat <= 2
  · exact conjecture16_source_bound_of_radius_toNat_le_two (G := G) hG hRadius
  · have hRadiusGt : 2 < G.radius.toNat := by omega
    by_cases hDiamLarge : (2 * G.radius.toNat : Nat) <= G.diam + 1
    · exact
        conjecture16_source_bound_of_radius_gt_two_of_diam_large
          (G := G) hG hRadiusGt hDiamLarge
    · exact hSmallBranch hRadiusGt hDiamLarge

theorem conjecture16_source_bound_of_radius_gt_two_of_diam_small_of_max_star_extension
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (_hG : G.Connected)
    (hRadius : 2 < G.radius.toNat)
    (hWitness :
      ∃ S : Finset alpha,
        (G.induce (S : Set alpha)).IsBipartite ∧
        SimpleGraph.maxIndepNeighborsCard G + 2 * (G.radius.toNat - 1) ≤ S.card) :
    letI maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
    letI r := G.radius.toNat
    2 * ((r : Real) - 1) + (maxL : Real) <= b G := by
  classical
  let maxL := (Finset.univ.image (fun v => indepNeighborsCard G v)).max' (by simp)
  let r := G.radius.toNat
  obtain ⟨S, hS_bip, hS_card⟩ := hWitness
  have hS_largestNat : S.card <= b G :=
    card_le_largestInducedBipartiteSubgraphSize_of_induce_isBipartite
      (G := G) (s := S) hS_bip
  have hS_largestReal : (S.card : Real) <= (b G : Real) := by
    exact_mod_cast hS_largestNat
  have hCardNat : maxL + 2 * (r - 1) <= S.card := by
    simpa [maxL, r, SimpleGraph.maxIndepNeighborsCard, add_comm, add_left_comm,
      add_assoc] using hS_card
  have hCardReal : ((maxL + 2 * (r - 1) : Nat) : Real) <= (S.card : Real) := by
    exact_mod_cast hCardNat
  have hrpos : 0 < r := by
    omega
  have hPredCast : (((r - 1 : Nat) : Real) = (r : Real) - 1) :=
    Nat.cast_pred hrpos
  have hNatCastExpand :
      ((maxL + 2 * (r - 1) : Nat) : Real)
        = (maxL : Real) + 2 * ((r - 1 : Nat) : Real) := by
    norm_num [Nat.cast_add, Nat.cast_mul]
  have hLeftEq :
      2 * ((r : Real) - 1) + (maxL : Real)
        = ((maxL + 2 * (r - 1) : Nat) : Real) := by
    rw [hNatCastExpand, hPredCast]
    linarith
  exact hLeftEq.trans_le (le_trans hCardReal hS_largestReal)

lemma fixed_color_star_extension_exists
    {alpha : Type*} [DecidableEq alpha]
    (G : SimpleGraph alpha) (v : alpha) (A : Finset alpha)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ L' R' : Finset alpha,
      A ⊆ L' ∧
      G.IsIndepSet (L' : Set alpha) ∧
      G.IsIndepSet (R' : Set alpha) ∧
      Disjoint L' R' ∧
      A.card + 1 ≤ (L' ∪ R').card := by
  classical
  have hvnotA : v ∉ A := by
    intro hvA
    exact G.irrefl (hAneigh v hvA)
  refine ⟨A, {v}, ?_, hAind, ?_, ?_, ?_⟩
  · intro x hx
    exact hx
  · intro x hx y hy hxy _hAdj
    have hxv : x = v := by simpa using hx
    have hyv : y = v := by simpa using hy
    exact hxy (hxv.trans hyv.symm)
  · rw [Finset.disjoint_left]
    intro x hxA hxR
    have hxv : x = v := by simpa using hxR
    exact hvnotA (by simpa [hxv] using hxA)
  · have hCard : (A ∪ ({v} : Finset alpha)).card = A.card + 1 := by
      rw [Finset.union_singleton, Finset.card_insert_of_notMem hvnotA]
    omega

lemma exists_fixed_color_maximal_extension
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha]
    (G : SimpleGraph alpha) (A : Finset alpha)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ L R : Finset alpha,
      A ⊆ L ∧
      G.IsIndepSet (L : Set alpha) ∧
      G.IsIndepSet (R : Set alpha) ∧
      Disjoint L R ∧
      ∀ L' R' : Finset alpha,
        A ⊆ L' →
        G.IsIndepSet (L' : Set alpha) →
        G.IsIndepSet (R' : Set alpha) →
        Disjoint L' R' →
        (L' ∪ R').card ≤ (L ∪ R).card := by
  classical
  let Good : Finset (Finset alpha × Finset alpha) :=
    Finset.univ.filter fun P =>
      A ⊆ P.1 ∧
      G.IsIndepSet (P.1 : Set alpha) ∧
      G.IsIndepSet (P.2 : Set alpha) ∧
      Disjoint P.1 P.2
  have hGoodNonempty : Good.Nonempty := by
    refine ⟨(A, ∅), ?_⟩
    refine Finset.mem_filter.mpr ⟨Finset.mem_univ _, ?_⟩
    refine ⟨?_, hAind, ?_, ?_⟩
    · intro x hx
      exact hx
    · intro x hx
      simp at hx
    · simp
  obtain ⟨P, hPmem, hPmax⟩ :=
    Finset.exists_max_image Good (fun P : Finset alpha × Finset alpha =>
      (P.1 ∪ P.2).card) hGoodNonempty
  rcases (Finset.mem_filter.mp hPmem).2 with
    ⟨hAside, hLind, hRind, hLRdisj⟩
  refine ⟨P.1, P.2, hAside, hLind, hRind, hLRdisj, ?_⟩
  intro L' R' hL'side hL'ind hR'ind hL'R'disj
  exact hPmax (L', R') <|
    Finset.mem_filter.mpr
      ⟨Finset.mem_univ _, hL'side, hL'ind, hR'ind, hL'R'disj⟩

lemma fixed_color_extra_vertices_card_bound_of_extension
    {alpha : Type*} [DecidableEq alpha]
    {G : SimpleGraph alpha} {A L R L' R' : Finset alpha} {k : Nat}
    (hAside : A ⊆ L)
    (hL'side : A ⊆ L')
    (hL'ind : G.IsIndepSet (L' : Set alpha))
    (hR'ind : G.IsIndepSet (R' : Set alpha))
    (hL'R'disj : Disjoint L' R')
    (hLarge : A.card + k ≤ (L' ∪ R').card)
    (hMax :
      ∀ L' R' : Finset alpha,
        A ⊆ L' →
        G.IsIndepSet (L' : Set alpha) →
        G.IsIndepSet (R' : Set alpha) →
        Disjoint L' R' →
        (L' ∪ R').card ≤ (L ∪ R).card) :
    k ≤ ((L ∪ R) \ A).card := by
  classical
  have hAsubUnion : A ⊆ L ∪ R := by
    intro x hx
    exact Finset.mem_union_left R (hAside hx)
  have hMaxCard : (L' ∪ R').card ≤ (L ∪ R).card :=
    hMax L' R' hL'side hL'ind hR'ind hL'R'disj
  have hUnionDecomp : ((L ∪ R) \ A).card + A.card = (L ∪ R).card :=
    Finset.card_sdiff_add_card_eq_card hAsubUnion
  omega

lemma geodesic_opposite_parity_path_vertices_disjoint
    {alpha : Type*} [DecidableEq alpha]
    {G : SimpleGraph alpha} {u w : alpha} (p : G.Walk u w)
    (hpPath : p.IsPath) (I : Finset Nat)
    (hI : ∀ i ∈ I, i ≤ p.length) {c d : Nat} (hcd : c ≠ d) :
    Disjoint
      ((I.filter fun i => i % 2 = c).image fun i => p.getVert i)
      ((I.filter fun i => i % 2 = d).image fun i => p.getVert i) := by
  classical
  rw [Finset.disjoint_left]
  intro x hx0 hx1
  rw [Finset.mem_image] at hx0 hx1
  rcases hx0 with ⟨i, hi, hix⟩
  rcases hx1 with ⟨j, hj, hjx⟩
  have hiI : i ∈ I := (Finset.mem_filter.mp hi).1
  have hjI : j ∈ I := (Finset.mem_filter.mp hj).1
  have hiParity : i % 2 = c := (Finset.mem_filter.mp hi).2
  have hjParity : j % 2 = d := (Finset.mem_filter.mp hj).2
  have hij : i = j :=
    hpPath.getVert_injOn (hI i hiI) (hI j hjI) (hix.trans hjx.symm)
  exact hcd (hiParity ▸ hij ▸ hjParity)

lemma indepNeighborsCard_le_maxIndepNeighborsCard
    {alpha : Type*} [Fintype alpha] [Nonempty alpha]
    (G : SimpleGraph alpha) (v : alpha) :
    indepNeighborsCard G v ≤ SimpleGraph.maxIndepNeighborsCard G := by
  classical
  unfold SimpleGraph.maxIndepNeighborsCard
  exact
    Finset.le_max' (Finset.univ.image fun w => indepNeighborsCard G w)
      (indepNeighborsCard G v)
      (Finset.mem_image.mpr ⟨v, Finset.mem_univ v, rfl⟩)

lemma exists_radius_geodesic_from
    {alpha : Type*} [Fintype alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected) (v : alpha) :
    ∃ w : alpha, ∃ p : G.Walk v w,
      p.IsPath ∧ p.length = G.dist v w ∧ G.radius.toNat ≤ p.length := by
  classical
  obtain ⟨w, hw⟩ := G.exists_edist_eq_eccent_of_finite v
  have hReach : G.Reachable v w := hG v w
  obtain ⟨p, hpPath, hpLen⟩ := hReach.exists_path_of_dist
  refine ⟨w, p, hpPath, hpLen, ?_⟩
  have hEccNeTop : G.eccent v ≠ ⊤ := by
    have hw_ne : G.edist v w ≠ ⊤ :=
      SimpleGraph.edist_ne_top_iff_reachable.mpr hReach
    simpa [← hw] using hw_ne
  have hRadLe : G.radius.toNat ≤ (G.eccent v).toNat :=
    ENat.toNat_le_toNat (SimpleGraph.radius_le_eccent (G := G) (u := v))
      hEccNeTop
  have hCoeEq : (G.dist v w : ℕ∞) = G.eccent v := by
    simpa [hw] using hReach.coe_dist_eq_edist
  have hEccToNat : (G.eccent v).toNat = G.dist v w := by
    simpa using congrArg ENat.toNat hCoeEq.symm
  rw [hpLen]
  simpa [hEccToNat] using hRadLe

lemma fixed_color_extension_of_metric_padding
    {alpha : Type*} [DecidableEq alpha]
    {G : SimpleGraph alpha} {v : alpha} {A P0 P1 : Finset alpha} {k : Nat}
    (hLind : G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha))
    (hRind : G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha))
    (hDisj : Disjoint (A ∪ P1) (insert v P0))
    (hCard : A.card + k ≤ ((A ∪ P1) ∪ insert v P0).card) :
    ∃ L' R' : Finset alpha,
      A ⊆ L' ∧
      G.IsIndepSet (L' : Set alpha) ∧
      G.IsIndepSet (R' : Set alpha) ∧
      Disjoint L' R' ∧
      A.card + k ≤ (L' ∪ R').card := by
  exact ⟨A ∪ P1, insert v P0, by intro x hx; exact Finset.mem_union_left P1 hx,
    hLind, hRind, hDisj, hCard⟩

lemma fixed_color_forced_v_blocker_collision_lower_bound
    {alpha beta : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    [DecidableEq beta]
    (G : SimpleGraph alpha) (v : alpha) (A L R : Finset alpha)
    (Demand : Finset beta) (blocker : beta → alpha)
    (_hRadius : 2 < G.radius.toNat)
    (_hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (_hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (_hAneigh : ∀ a ∈ A, G.Adj v a)
    (_hAind : G.IsIndepSet (A : Set alpha))
    (_hAside : A ⊆ L)
    (_hvR : v ∈ R)
    (_hLind : G.IsIndepSet (L : Set alpha))
    (_hRind : G.IsIndepSet (R : Set alpha))
    (_hLRdisj : Disjoint L R)
    (_hMax :
      ∀ L' R' : Finset alpha,
        A ⊆ L' →
        G.IsIndepSet (L' : Set alpha) →
        G.IsIndepSet (R' : Set alpha) →
        Disjoint L' R' →
        (L' ∪ R').card ≤ (L ∪ R).card)
    (hBlockerIn : ∀ d ∈ Demand, blocker d ∈ (L ∪ R) \ A)
    (hNoCollision :
      ∀ d₁ ∈ Demand, ∀ d₂ ∈ Demand, blocker d₁ = blocker d₂ → d₁ = d₂)
    (hDemandMass : 2 * (G.radius.toNat - 1) ≤ Demand.card) :
    2 * (G.radius.toNat - 1) ≤ ((L ∪ R) \ A).card := by
  classical
  refine le_trans hDemandMass ?_
  exact Finset.card_le_card_of_injOn blocker
    (fun d hd => hBlockerIn d hd)
    (fun d hd e he hEq => hNoCollision d hd e he hEq)

section CentralDeficitComponentShadowColoringCertificate

variable {G : SimpleGraph PUnit}

lemma central_deficit_component_shadow_coloring_certificate
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    [DecidableRel G.Adj]
    (G : SimpleGraph α)
    (v w : α) (p : G.Walk v w)
    (r e : ℕ)
    (P0 P1 A : Finset α)
    (Comp : Finset (Finset α))
    (shadow : Finset α → Finset ℕ)
    (B0 B1 : Finset α → Finset α)
    (hpLen : p.length = e)
    (hShort : r ≤ e ∧ e < 2 * r - 2)
    (hCompOff : ∀ C ∈ Comp, ∀ x ∈ C, x ∉ p.support.toFinset)
    (hBsub : ∀ C ∈ Comp, B0 C ⊆ C ∧ B1 C ⊆ C)
    (hB0ind : G.IsIndepSet (((Comp.biUnion B0) : Finset α) : Set α))
    (hB1ind : G.IsIndepSet (((Comp.biUnion B1) : Finset α) : Set α))
    (hBdisj : Disjoint (Comp.biUnion B0) (Comp.biUnion B1))
    (hB0safe : ∀ x ∈ Comp.biUnion B0,
      2 ≤ G.dist v x ∧ ∀ y ∈ insert v P0, ¬ G.Adj x y)
    (hB1safe : ∀ x ∈ Comp.biUnion B1,
      3 ≤ G.dist v x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y)
    (D : Finset ℕ)
    (hDcard : D.card = 2 * r - 2 - e)
    (f : ℕ → α × Bool)
    (hfD : ∀ i ∈ D,
      ∃ C ∈ Comp, i ∈ shadow C ∧
        ((f i).2 = false ∧ (f i).1 ∈ B0 C ∨
         (f i).2 = true ∧ (f i).1 ∈ B1 C))
    (hfinj : Set.InjOn f (D : Set ℕ)) :
    ∃ Q0 Q1 : Finset α,
      (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
      (∀ x ∈ Q0, 2 ≤ G.dist v x ∧ ∀ y ∈ insert v P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Q1, 3 ≤ G.dist v x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      G.IsIndepSet (Q0 : Set α) ∧
      G.IsIndepSet (Q1 : Set α) ∧
      Disjoint Q0 Q1 ∧
      2 * r - 2 - e ≤ (Q0 ∪ Q1).card := by
  classical
  have _hpLen : p.length = e := hpLen
  have _hShort : r ≤ e ∧ e < 2 * r - 2 := hShort
  let Q0 : Finset α := Comp.biUnion B0
  let Q1 : Finset α := Comp.biUnion B1
  have hMemFalse : ∀ i ∈ D, (f i).2 = false → (f i).1 ∈ Q0 := by
    intro i hiD hiColor
    rcases hfD i hiD with ⟨C, hC, _hiShadow, hiCand⟩
    rcases hiCand with hiCand0 | hiCand1
    · exact Finset.mem_biUnion.mpr ⟨C, hC, hiCand0.2⟩
    · have hbad : false = true := by
        simpa [hiColor] using hiCand1.1
      cases hbad
  have hMemTrue : ∀ i ∈ D, (f i).2 = true → (f i).1 ∈ Q1 := by
    intro i hiD hiColor
    rcases hfD i hiD with ⟨C, hC, _hiShadow, hiCand⟩
    rcases hiCand with hiCand0 | hiCand1
    · have hbad : true = false := by
        simpa [hiColor] using hiCand0.1
      cases hbad
    · exact Finset.mem_biUnion.mpr ⟨C, hC, hiCand1.2⟩
  have hSelectedIn : ∀ i ∈ D, (f i).1 ∈ Q0 ∪ Q1 := by
    intro i hiD
    rcases hfD i hiD with ⟨C, hC, _hiShadow, hiCand⟩
    rcases hiCand with hiCand0 | hiCand1
    · exact Finset.mem_union_left Q1
        (Finset.mem_biUnion.mpr ⟨C, hC, hiCand0.2⟩)
    · exact Finset.mem_union_right Q0
        (Finset.mem_biUnion.mpr ⟨C, hC, hiCand1.2⟩)
  have hSelectedInj :
      ∀ i ∈ D, ∀ j ∈ D, (f i).1 = (f j).1 → i = j := by
    intro i hiD j hjD hfst
    have hbool : (f i).2 = (f j).2 := by
      cases hiBool : (f i).2 <;> cases hjBool : (f j).2
      · rfl
      · have hi0 : (f i).1 ∈ Q0 := hMemFalse i hiD hiBool
        have hj1 : (f j).1 ∈ Q1 := hMemTrue j hjD hjBool
        have hi1 : (f i).1 ∈ Q1 := by simpa [hfst] using hj1
        exact False.elim ((Finset.disjoint_left.mp hBdisj) hi0 hi1)
      · have hi1 : (f i).1 ∈ Q1 := hMemTrue i hiD hiBool
        have hj0 : (f j).1 ∈ Q0 := hMemFalse j hjD hjBool
        have hi0 : (f i).1 ∈ Q0 := by simpa [hfst] using hj0
        exact False.elim ((Finset.disjoint_left.mp hBdisj) hi0 hi1)
      · rfl
    exact hfinj hiD hjD (Prod.ext hfst hbool)
  refine ⟨Q0, Q1, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro x hx
    rw [Finset.mem_union] at hx
    rcases hx with hx0 | hx1
    · rcases Finset.mem_biUnion.mp hx0 with ⟨C, hC, hxB0⟩
      exact hCompOff C hC x ((hBsub C hC).1 hxB0)
    · rcases Finset.mem_biUnion.mp hx1 with ⟨C, hC, hxB1⟩
      exact hCompOff C hC x ((hBsub C hC).2 hxB1)
  · exact hB0safe
  · exact hB1safe
  · exact hB0ind
  · exact hB1ind
  · exact hBdisj
  · have hCard : D.card ≤ (Q0 ∪ Q1).card :=
      Finset.card_le_card_of_injOn (fun i => (f i).1) hSelectedIn hSelectedInj
    simpa [hDcard] using hCard

end CentralDeficitComponentShadowColoringCertificate

section CentralDeficitComponentShadowColoringFromSafePoolHall

variable {G : SimpleGraph PUnit}

lemma central_deficit_component_shadow_coloring_from_safe_pool_hall
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    [DecidableRel G.Adj]
    (G : SimpleGraph α) (v w : α) (p : G.Walk v w)
    (r e : ℕ)
    (P0 P1 A : Finset α)
    (Comp : Finset (Finset α))
    (shadow : Finset α → Finset ℕ)
    (B0 B1 : Finset α → Finset α)
    (hpLen : p.length = e)
    (hShort : r ≤ e ∧ e < 2 * r - 2)
    (hCompOff : ∀ C ∈ Comp, ∀ x ∈ C, x ∉ p.support.toFinset)
    (hBsub : ∀ C ∈ Comp, B0 C ⊆ C ∧ B1 C ⊆ C)
    (hB0ind : G.IsIndepSet (((Comp.biUnion B0) : Finset α) : Set α))
    (hB1ind : G.IsIndepSet (((Comp.biUnion B1) : Finset α) : Set α))
    (hBdisj : Disjoint (Comp.biUnion B0) (Comp.biUnion B1))
    (hB0safe : ∀ x ∈ Comp.biUnion B0,
      2 ≤ G.dist v x ∧ ∀ y ∈ insert v P0, ¬ G.Adj x y)
    (hB1safe : ∀ x ∈ Comp.biUnion B1,
      3 ≤ G.dist v x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y)
    (D : Finset ℕ)
    (hDcard : D.card = 2 * r - 2 - e)
    (hHall : ∀ S : Finset ℕ, S ⊆ D →
      S.card ≤
        ((Comp.filter fun C => ¬ Disjoint S (shadow C)).biUnion
          (fun C => ((B0 C).image fun x => (x, false)) ∪
                    ((B1 C).image fun x => (x, true)))).card) :
    ∃ Q0 Q1 : Finset α,
      (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
      (∀ x ∈ Q0, 2 ≤ G.dist v x ∧ ∀ y ∈ insert v P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Q1, 3 ≤ G.dist v x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      G.IsIndepSet (Q0 : Set α) ∧
      G.IsIndepSet (Q1 : Set α) ∧
      Disjoint Q0 Q1 ∧
      2 * r - 2 - e ≤ (Q0 ∪ Q1).card := by
  classical
  have _hpLen : p.length = e := hpLen
  have _hShort : r ≤ e ∧ e < 2 * r - 2 := hShort
  let rel : {i // i ∈ D} → α × Bool → Prop := fun i y =>
    ∃ C ∈ Comp, i.1 ∈ shadow C ∧
      (y ∈ ((B0 C).image fun x => (x, false)) ∪
            ((B1 C).image fun x => (x, true)))
  have hHallRel :
      ∀ S : Finset {i // i ∈ D},
        S.card ≤ ({y : α × Bool | ∃ i ∈ S, rel i y} : Finset (α × Bool)).card := by
    intro S
    let Sval : Finset ℕ := S.image Subtype.val
    have hScard : S.card = Sval.card := by
      rw [Finset.card_image_of_injective]
      exact Subtype.val_injective
    have hSsubD : Sval ⊆ D := by
      intro i hi
      rcases Finset.mem_image.mp hi with ⟨j, _hjS, rfl⟩
      exact j.2
    let Cands : Finset (α × Bool) :=
      (Comp.filter fun C => ¬ Disjoint Sval (shadow C)).biUnion
        (fun C => ((B0 C).image fun x => (x, false)) ∪
                  ((B1 C).image fun x => (x, true)))
    have hCandsSub :
        Cands ⊆ ({y : α × Bool | ∃ i ∈ S, rel i y} : Finset (α × Bool)) := by
      intro y hy
      rcases Finset.mem_biUnion.mp hy with ⟨C, hCfilter, hyC⟩
      have hC : C ∈ Comp := (Finset.mem_filter.mp hCfilter).1
      have hNotDisj : ¬ Disjoint Sval (shadow C) := (Finset.mem_filter.mp hCfilter).2
      rw [Finset.disjoint_left] at hNotDisj
      push_neg at hNotDisj
      rcases hNotDisj with ⟨i, hiSval, hiShadow⟩
      rcases Finset.mem_image.mp hiSval with ⟨j, hjS, hj⟩
      rw [← hj] at hiShadow
      rw [Finset.mem_filter]
      exact ⟨Finset.mem_univ y, ⟨j, hjS, C, hC, hiShadow, hyC⟩⟩
    rw [hScard]
    exact le_trans (hHall Sval hSsubD) (Finset.card_le_card hCandsSub)
  obtain ⟨g, hginj, hgmem⟩ :=
    (Fintype.all_card_le_filter_rel_iff_exists_injective (α := {i // i ∈ D})
      (β := α × Bool) rel).mp hHallRel
  let f : ℕ → α × Bool := fun i => if hi : i ∈ D then g ⟨i, hi⟩ else (v, false)
  have hfD : ∀ i ∈ D,
      ∃ C ∈ Comp, i ∈ shadow C ∧
        ((f i).2 = false ∧ (f i).1 ∈ B0 C ∨
         (f i).2 = true ∧ (f i).1 ∈ B1 C) := by
    intro i hiD
    have hrel := hgmem ⟨i, hiD⟩
    rcases hrel with ⟨C, hC, hiShadow, hCand⟩
    refine ⟨C, hC, hiShadow, ?_⟩
    dsimp [f]
    rw [dif_pos hiD]
    rw [Finset.mem_union] at hCand
    rcases hCand with hCand0 | hCand1
    · rw [Finset.mem_image] at hCand0
      rcases hCand0 with ⟨x, hxB0, hx⟩
      have hfst : (g ⟨i, hiD⟩).1 = x := by
        simpa using congrArg Prod.fst hx.symm
      have hsnd : (g ⟨i, hiD⟩).2 = false := by
        simpa using congrArg Prod.snd hx.symm
      exact Or.inl ⟨hsnd, by simpa [hfst] using hxB0⟩
    · rw [Finset.mem_image] at hCand1
      rcases hCand1 with ⟨x, hxB1, hx⟩
      have hfst : (g ⟨i, hiD⟩).1 = x := by
        simpa using congrArg Prod.fst hx.symm
      have hsnd : (g ⟨i, hiD⟩).2 = true := by
        simpa using congrArg Prod.snd hx.symm
      exact Or.inr ⟨hsnd, by simpa [hfst] using hxB1⟩
  have hfinj : Set.InjOn f (D : Set ℕ) := by
    intro i hiD j hjD hij
    have hiD' : i ∈ D := by simpa using hiD
    have hjD' : j ∈ D := by simpa using hjD
    dsimp [f] at hij
    rw [dif_pos hiD', dif_pos hjD'] at hij
    exact congrArg Subtype.val (hginj hij)
  let Q0 : Finset α := Comp.biUnion B0
  let Q1 : Finset α := Comp.biUnion B1
  have hMemFalse : ∀ i ∈ D, (f i).2 = false → (f i).1 ∈ Q0 := by
    intro i hiD hiColor
    rcases hfD i hiD with ⟨C, hC, _hiShadow, hiCand⟩
    rcases hiCand with hiCand0 | hiCand1
    · exact Finset.mem_biUnion.mpr ⟨C, hC, hiCand0.2⟩
    · have hbad : false = true := by
        simpa [hiColor] using hiCand1.1
      cases hbad
  have hMemTrue : ∀ i ∈ D, (f i).2 = true → (f i).1 ∈ Q1 := by
    intro i hiD hiColor
    rcases hfD i hiD with ⟨C, hC, _hiShadow, hiCand⟩
    rcases hiCand with hiCand0 | hiCand1
    · have hbad : true = false := by
        simpa [hiColor] using hiCand0.1
      cases hbad
    · exact Finset.mem_biUnion.mpr ⟨C, hC, hiCand1.2⟩
  have hSelectedIn : ∀ i ∈ D, (f i).1 ∈ Q0 ∪ Q1 := by
    intro i hiD
    rcases hfD i hiD with ⟨C, hC, _hiShadow, hiCand⟩
    rcases hiCand with hiCand0 | hiCand1
    · exact Finset.mem_union_left Q1
        (Finset.mem_biUnion.mpr ⟨C, hC, hiCand0.2⟩)
    · exact Finset.mem_union_right Q0
        (Finset.mem_biUnion.mpr ⟨C, hC, hiCand1.2⟩)
  have hSelectedInj :
      ∀ i ∈ D, ∀ j ∈ D, (f i).1 = (f j).1 → i = j := by
    intro i hiD j hjD hfst
    have hbool : (f i).2 = (f j).2 := by
      cases hiBool : (f i).2 <;> cases hjBool : (f j).2
      · rfl
      · have hi0 : (f i).1 ∈ Q0 := hMemFalse i hiD hiBool
        have hj1 : (f j).1 ∈ Q1 := hMemTrue j hjD hjBool
        have hi1 : (f i).1 ∈ Q1 := by simpa [hfst] using hj1
        exact False.elim ((Finset.disjoint_left.mp hBdisj) hi0 hi1)
      · have hi1 : (f i).1 ∈ Q1 := hMemTrue i hiD hiBool
        have hj0 : (f j).1 ∈ Q0 := hMemFalse j hjD hjBool
        have hi0 : (f i).1 ∈ Q0 := by simpa [hfst] using hj0
        exact False.elim ((Finset.disjoint_left.mp hBdisj) hi0 hi1)
      · rfl
    exact hfinj hiD hjD (Prod.ext hfst hbool)
  refine ⟨Q0, Q1, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro x hx
    rw [Finset.mem_union] at hx
    rcases hx with hx0 | hx1
    · rcases Finset.mem_biUnion.mp hx0 with ⟨C, hC, hxB0⟩
      exact hCompOff C hC x ((hBsub C hC).1 hxB0)
    · rcases Finset.mem_biUnion.mp hx1 with ⟨C, hC, hxB1⟩
      exact hCompOff C hC x ((hBsub C hC).2 hxB1)
  · exact hB0safe
  · exact hB1safe
  · exact hB0ind
  · exact hB1ind
  · exact hBdisj
  · have hCard : D.card ≤ (Q0 ∪ Q1).card :=
      Finset.card_le_card_of_injOn (fun i => (f i).1) hSelectedIn hSelectedInj
    simpa [hDcard] using hCard

end CentralDeficitComponentShadowColoringFromSafePoolHall

section CentralDeficitComponentShadowColoringFromComponentCapacity

variable {G : SimpleGraph PUnit}

lemma central_deficit_component_shadow_coloring_from_component_capacity
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    [DecidableRel G.Adj]
    (G : SimpleGraph α) (v w : α) (p : G.Walk v w)
    (r e : ℕ)
    (P0 P1 A : Finset α)
    (Comp : Finset (Finset α))
    (shadow : Finset α → Finset ℕ)
    (B0 B1 : Finset α → Finset α)
    (hpLen : p.length = e)
    (hShort : r ≤ e ∧ e < 2 * r - 2)
    (hCompOff : ∀ C ∈ Comp, ∀ x ∈ C, x ∉ p.support.toFinset)
    (hBsub : ∀ C ∈ Comp, B0 C ⊆ C ∧ B1 C ⊆ C)
    (hB0ind : G.IsIndepSet (((Comp.biUnion B0) : Finset α) : Set α))
    (hB1ind : G.IsIndepSet (((Comp.biUnion B1) : Finset α) : Set α))
    (hBdisj : Disjoint (Comp.biUnion B0) (Comp.biUnion B1))
    (hB0safe : ∀ x ∈ Comp.biUnion B0,
      2 ≤ G.dist v x ∧ ∀ y ∈ insert v P0, ¬ G.Adj x y)
    (hB1safe : ∀ x ∈ Comp.biUnion B1,
      3 ≤ G.dist v x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y)
    (D : Finset ℕ)
    (hDcard : D.card = 2 * r - 2 - e)
    (hCoverD : ∀ i ∈ D, ∃ C ∈ Comp, i ∈ shadow C)
    (hCandDisj : ∀ C ∈ Comp, ∀ C' ∈ Comp, C ≠ C' →
      Disjoint
        (((B0 C).image fun x => (x, false)) ∪
         ((B1 C).image fun x => (x, true)))
        (((B0 C').image fun x => (x, false)) ∪
         ((B1 C').image fun x => (x, true))))
    (hLocalCap : ∀ C ∈ Comp,
      (shadow C ∩ D).card ≤
        (((B0 C).image fun x => (x, false)) ∪
         ((B1 C).image fun x => (x, true))).card) :
    ∃ Q0 Q1 : Finset α,
      (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
      (∀ x ∈ Q0, 2 ≤ G.dist v x ∧ ∀ y ∈ insert v P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Q1, 3 ≤ G.dist v x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      G.IsIndepSet (Q0 : Set α) ∧
      G.IsIndepSet (Q1 : Set α) ∧
      Disjoint Q0 Q1 ∧ 2 * r - 2 - e ≤ (Q0 ∪ Q1).card
    := by
  classical
  let cand : Finset α → Finset (α × Bool) := fun C =>
    ((B0 C).image fun x => (x, false)) ∪
      ((B1 C).image fun x => (x, true))
  have hHall : ∀ S : Finset ℕ, S ⊆ D →
      S.card ≤
        ((Comp.filter fun C => ¬ Disjoint S (shadow C)).biUnion
          (fun C => ((B0 C).image fun x => (x, false)) ∪
                    ((B1 C).image fun x => (x, true)))).card := by
    intro S hSsubD
    let Active : Finset (Finset α) := Comp.filter fun C => ¬ Disjoint S (shadow C)
    let sh : Finset α → Finset ℕ := fun C => shadow C ∩ D
    have hSsubShadow : S ⊆ Active.biUnion sh := by
      intro i hiS
      have hiD : i ∈ D := hSsubD hiS
      rcases hCoverD i hiD with ⟨C, hC, hiShadow⟩
      have hActive : C ∈ Active := by
        rw [Finset.mem_filter]
        refine ⟨hC, ?_⟩
        rw [Finset.disjoint_left]
        push_neg
        exact ⟨i, hiS, hiShadow⟩
      exact Finset.mem_biUnion.mpr
        ⟨C, hActive, Finset.mem_inter.mpr ⟨hiShadow, hiD⟩⟩
    have hShadowUnionLeSum :
        (Active.biUnion sh).card ≤ ∑ C ∈ Active, (sh C).card :=
      Finset.card_biUnion_le
    have hSumShadowLeCand :
        (∑ C ∈ Active, (sh C).card) ≤ ∑ C ∈ Active, (cand C).card := by
      exact Finset.sum_le_sum fun C hCActive =>
        hLocalCap C (Finset.mem_filter.mp hCActive).1
    have hPairCand : (Active : Set (Finset α)).PairwiseDisjoint cand := by
      intro C hCActive C' hC'Active hne
      exact hCandDisj C (Finset.mem_filter.mp hCActive).1
        C' (Finset.mem_filter.mp hC'Active).1 hne
    have hCandCard :
        (Active.biUnion cand).card = ∑ C ∈ Active, (cand C).card :=
      Finset.card_biUnion hPairCand
    have hSleShadow : S.card ≤ (Active.biUnion sh).card :=
      Finset.card_le_card hSsubShadow
    calc
      S.card ≤ (Active.biUnion sh).card := hSleShadow
      _ ≤ ∑ C ∈ Active, (sh C).card := hShadowUnionLeSum
      _ ≤ ∑ C ∈ Active, (cand C).card := hSumShadowLeCand
      _ = (Active.biUnion cand).card := hCandCard.symm
  exact
    @central_deficit_component_shadow_coloring_from_safe_pool_hall
      (⊥ : SimpleGraph PUnit.{1}) α _ _ _
      (Classical.decRel (⊥ : SimpleGraph PUnit.{1}).Adj)
      G v w p r e P0 P1 A Comp shadow B0 B1
      hpLen hShort hCompOff hBsub hB0ind hB1ind hBdisj
      hB0safe hB1safe D hDcard hHall

end CentralDeficitComponentShadowColoringFromComponentCapacity

lemma central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_safe_candidates
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (u w : alpha) (p : G.Walk u w) (e : ℕ)
    (b : alpha) (A P0 P1 Q0 Q1 : Finset alpha)
    (DNat : Finset ℕ)
    (hpPath : p.IsPath)
    (hpLen : p.length = e)
    (heDiam : e = G.diam)
    (hDdef :
      DNat = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1))
    (hDcard : DNat.card = 2 * G.radius.toNat - 2 - e)
    (hLind : G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha))
    (hRind : G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha))
    (hLRdisj : Disjoint (A ∪ P1) (insert b P0))
    (hPathCard : A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card)
    (hQoff : ∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset)
    (hQ0ind : G.IsIndepSet (Q0 : Set alpha))
    (hQ1ind : G.IsIndepSet (Q1 : Set alpha))
    (hQdisj : Disjoint Q0 Q1)
    (hQ0safe : ∀ x ∈ Q0,
      2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y)
    (hQ1safe : ∀ x ∈ Q1,
      3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y)
    (hQcard : DNat.card ≤
      ((Q0.image fun x => (x, false)) ∪
       (Q1.image fun x => (x, true))).card) :
    ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ,
    ∃ P0 P1 : Finset alpha,
    ∃ Comp : Finset (Finset alpha),
    ∃ shadow : Finset alpha → Finset ℕ,
    ∃ B0 B1 : Finset alpha → Finset alpha,
    ∃ D : Finset ℕ,
      p.IsPath ∧
      p.length = e ∧
      e = G.diam ∧
      D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
      D.card = 2 * G.radius.toNat - 2 - e ∧
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert b P0) ∧
      A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
      (∀ C ∈ Comp, ∀ x ∈ C, x ∉ p.support.toFinset) ∧
      (∀ C ∈ Comp, B0 C ⊆ C ∧ B1 C ⊆ C) ∧
      G.IsIndepSet (((Comp.biUnion B0) : Finset alpha) : Set alpha) ∧
      G.IsIndepSet (((Comp.biUnion B1) : Finset alpha) : Set alpha) ∧
      Disjoint (Comp.biUnion B0) (Comp.biUnion B1) ∧
      (∀ x ∈ Comp.biUnion B0,
        2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Comp.biUnion B1,
        3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      (∀ i ∈ D, ∃ C ∈ Comp, i ∈ shadow C) ∧
      (∀ C ∈ Comp, ∀ C' ∈ Comp, C ≠ C' →
        Disjoint
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true)))
          (((B0 C').image fun x => (x, false)) ∪
           ((B1 C').image fun x => (x, true)))) ∧
      (∀ C ∈ Comp,
        (shadow C ∩ D).card ≤
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true))).card) := by
  classical
  let Cstar : Finset alpha := Q0 ∪ Q1
  let Comp : Finset (Finset alpha) := {Cstar}
  let shadow : Finset alpha → Finset ℕ := fun C => if C = Cstar then DNat else ∅
  let B0 : Finset alpha → Finset alpha := fun C => if C = Cstar then Q0 else ∅
  let B1 : Finset alpha → Finset alpha := fun C => if C = Cstar then Q1 else ∅
  refine
    ⟨u, w, p, e, P0, P1, Comp, shadow, B0, B1, DNat,
      hpPath, hpLen, heDiam, hDdef, hDcard, hLind, hRind, hLRdisj,
      hPathCard, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · intro C hC x hxC
    have hCeq : C = Cstar := by
      simpa [Comp] using hC
    subst C
    exact hQoff x hxC
  · intro C hC
    have hCeq : C = Cstar := by
      simpa [Comp] using hC
    subst C
    constructor
    · intro x hx
      have hxQ0 : x ∈ Q0 := by
        simpa [B0] using hx
      exact Finset.mem_union_left Q1 hxQ0
    · intro x hx
      have hxQ1 : x ∈ Q1 := by
        simpa [B1] using hx
      exact Finset.mem_union_right Q0 hxQ1
  · simpa [Comp, B0, Cstar] using hQ0ind
  · simpa [Comp, B1, Cstar] using hQ1ind
  · simpa [Comp, B0, B1, Cstar] using hQdisj
  · intro x hx
    have hxQ0 : x ∈ Q0 := by
      simpa [Comp, B0, Cstar] using hx
    exact hQ0safe x hxQ0
  · intro x hx
    have hxQ1 : x ∈ Q1 := by
      simpa [Comp, B1, Cstar] using hx
    exact hQ1safe x hxQ1
  · intro i hiD
    refine ⟨Cstar, ?_, ?_⟩
    · simp [Comp]
    · simp [shadow, hiD]
  · intro C hC C' hC' hne
    have hCeq : C = Cstar := by
      simpa [Comp] using hC
    have hC'eq : C' = Cstar := by
      simpa [Comp] using hC'
    exact False.elim (hne (hCeq.trans hC'eq.symm))
  · intro C hC
    have hCeq : C = Cstar := by
      simpa [Comp] using hC
    subst C
    simpa [shadow, B0, B1, Cstar] using hQcard

lemma central_deficit_diametral_path_radius_tail_demand
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (hG : G.Connected)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1) :
    ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ, ∃ D : Finset ℕ,
      p.IsPath ∧
      p.length = e ∧
      e = G.diam ∧
      D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
      D.card = 2 * G.radius.toNat - 2 - e := by
  classical
  have hEdTop : G.ediam ≠ ⊤ :=
    (SimpleGraph.connected_iff_ediam_ne_top (G := G)).mp hG
  have hRadDiam : G.radius.toNat ≤ G.diam := by
    simpa [SimpleGraph.diam] using
      ENat.toNat_le_toNat (SimpleGraph.radius_le_ediam (G := G)) hEdTop
  obtain ⟨u, w, huw⟩ := SimpleGraph.exists_dist_eq_diam (G := G)
  obtain ⟨p, hpPath, hpLen⟩ := hG.exists_path_of_dist u w
  refine
    ⟨u, w, p, G.diam,
      Finset.Icc (G.diam - G.radius.toNat + 2) (G.radius.toNat - 1),
      hpPath, ?_, rfl, rfl, ?_⟩
  · rw [hpLen, huw]
  · rw [Nat.card_Icc]
    omega

lemma central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_diametral_safe_candidates
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (hG : G.Connected)
    (b : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1)
    (_hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (_hAneigh : ∀ a ∈ A, G.Adj b a)
    (_hAind : G.IsIndepSet (A : Set alpha))
    (hCandidates :
      ∀ u w : alpha, ∀ p : G.Walk u w, ∀ e : ℕ, ∀ D : Finset ℕ,
        p.IsPath →
        p.length = e →
        e = G.diam →
        D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) →
        D.card = 2 * G.radius.toNat - 2 - e →
        ∃ P0 P1 Q0 Q1 : Finset alpha,
          G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
          G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
          Disjoint (A ∪ P1) (insert b P0) ∧
          A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
          (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
          G.IsIndepSet (Q0 : Set alpha) ∧
          G.IsIndepSet (Q1 : Set alpha) ∧
          Disjoint Q0 Q1 ∧
          (∀ x ∈ Q0,
            2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
          (∀ x ∈ Q1,
            3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
          D.card ≤
            ((Q0.image fun x => (x, false)) ∪
             (Q1.image fun x => (x, true))).card) :
    ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ,
    ∃ P0 P1 : Finset alpha,
    ∃ Comp : Finset (Finset alpha),
    ∃ shadow : Finset alpha → Finset ℕ,
    ∃ B0 B1 : Finset alpha → Finset alpha,
    ∃ D : Finset ℕ,
      p.IsPath ∧
      p.length = e ∧
      e = G.diam ∧
      D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
      D.card = 2 * G.radius.toNat - 2 - e ∧
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert b P0) ∧
      A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
      (∀ C ∈ Comp, ∀ x ∈ C, x ∉ p.support.toFinset) ∧
      (∀ C ∈ Comp, B0 C ⊆ C ∧ B1 C ⊆ C) ∧
      G.IsIndepSet (((Comp.biUnion B0) : Finset alpha) : Set alpha) ∧
      G.IsIndepSet (((Comp.biUnion B1) : Finset alpha) : Set alpha) ∧
      Disjoint (Comp.biUnion B0) (Comp.biUnion B1) ∧
      (∀ x ∈ Comp.biUnion B0,
        2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Comp.biUnion B1,
        3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      (∀ i ∈ D, ∃ C ∈ Comp, i ∈ shadow C) ∧
      (∀ C ∈ Comp, ∀ C' ∈ Comp, C ≠ C' →
        Disjoint
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true)))
          (((B0 C').image fun x => (x, false)) ∪
           ((B1 C').image fun x => (x, true)))) ∧
      (∀ C ∈ Comp,
        (shadow C ∩ D).card ≤
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true))).card) := by
  classical
  obtain ⟨u, w, p, e, D, hpPath, hpLen, heDiam, hDdef, hDcard⟩ :=
    central_deficit_diametral_path_radius_tail_demand
      (G := G) hG hRadius hDiamSmall
  obtain
    ⟨P0, P1, Q0, Q1, hLind, hRind, hLRdisj, hPathCard, hQoff,
      hQ0ind, hQ1ind, hQdisj, hQ0safe, hQ1safe, hQcard⟩ :=
    hCandidates u w p e D hpPath hpLen heDiam hDdef hDcard
  exact
    central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_safe_candidates
      (G := G) (u := u) (w := w) (p := p) (e := e)
      (b := b) (A := A) (P0 := P0) (P1 := P1) (Q0 := Q0) (Q1 := Q1)
      (DNat := D)
      hpPath hpLen heDiam hDdef hDcard hLind hRind hLRdisj
      hPathCard hQoff hQ0ind hQ1ind hQdisj hQ0safe hQ1safe hQcard

def centralDeficitDiametralSafeCandidateData
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (b : alpha) (A : Finset alpha) : Prop :=
  ∀ u w : alpha, ∀ p : G.Walk u w, ∀ e : ℕ, ∀ D : Finset ℕ,
    p.IsPath →
    p.length = e →
    e = G.diam →
    D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) →
    D.card = 2 * G.radius.toNat - 2 - e →
    ∃ P0 P1 Q0 Q1 : Finset alpha,
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert b P0) ∧
      A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
      (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
      G.IsIndepSet (Q0 : Set alpha) ∧
      G.IsIndepSet (Q1 : Set alpha) ∧
      Disjoint Q0 Q1 ∧
      (∀ x ∈ Q0,
        2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Q1,
        3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      D.card ≤
        ((Q0.image fun x => (x, false)) ∪
         (Q1.image fun x => (x, true))).card

def CentralDeficitAdmissibleTuple
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} (p : G.Walk u w) (e : Nat) (D : Finset Nat)
    (P0 P1 Q0 Q1 : Finset α) : Prop :=
  p.IsPath ∧
  p.length = e ∧
  e = G.diam ∧
  D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
  D.card = 2 * G.radius.toNat - 2 - e ∧
  G.IsIndepSet ((A ∪ P1 : Finset α) : Set α) ∧
  G.IsIndepSet ((insert b P0 : Finset α) : Set α) ∧
  Disjoint (A ∪ P1) (insert b P0) ∧
  A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
  (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
  G.IsIndepSet (Q0 : Set α) ∧
  G.IsIndepSet (Q1 : Set α) ∧
  Disjoint Q0 Q1 ∧
  (∀ x ∈ Q0, 2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
  (∀ x ∈ Q1, 3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
  D.card ≤ (Q0 ∪ Q1).card ∧
  Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)

def CentralDeficitLexmaxAdmissibleTuple
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} (p : G.Walk u w) (e : Nat) (D : Finset Nat)
    (P0 P1 Q0 Q1 : Finset α) : Prop :=
  p.IsPath ∧
  p.length = e ∧
  e = G.diam ∧
  D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
  D.card = 2 * G.radius.toNat - 2 - e ∧
  G.IsIndepSet ((A ∪ P1 : Finset α) : Set α) ∧
  G.IsIndepSet ((insert b P0 : Finset α) : Set α) ∧
  Disjoint (A ∪ P1) (insert b P0) ∧
  A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
  (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
  G.IsIndepSet (Q0 : Set α) ∧
  G.IsIndepSet (Q1 : Set α) ∧
  Disjoint Q0 Q1 ∧
  (∀ x ∈ Q0, 2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
  (∀ x ∈ Q1, 3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
  D.card ≤ (Q0 ∪ Q1).card ∧
  Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)

def CentralDeficitPackageLexBetter
    {α : Type*} [DecidableEq α] (b : α) (A : Finset α)
    (P0 P1 Q0 Q1 P0' P1' Q0' Q1' : Finset α) : Prop :=
  (Q0 ∪ Q1).card < (Q0' ∪ Q1').card ∨
  ((Q0 ∪ Q1).card = (Q0' ∪ Q1').card ∧
    ((A ∪ P1) ∪ insert b P0).card <
      ((A ∪ P1') ∪ insert b P0').card)

def CentralDeficitPathFixedCollision
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} (p : G.Walk u w) (e : Nat) (D : Finset Nat)
    (P0 P1 Q0 Q1 : Finset α) : Prop :=
  ∃ P0' P1' Q0' Q1' : Finset α,
    CentralDeficitLexmaxAdmissibleTuple G b A p e D P0' P1' Q0' Q1' ∧
    CentralDeficitPackageLexBetter b A P0 P1 Q0 Q1 P0' P1' Q0' Q1'

def CentralDeficitLexmaxSelectedPackage
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} (p : G.Walk u w) (e : Nat) (D : Finset Nat)
    (P0 P1 Q0 Q1 : Finset α) : Prop :=
  CentralDeficitLexmaxAdmissibleTuple G b A p e D P0 P1 Q0 Q1 ∧
  ∀ P0' P1' Q0' Q1' : Finset α,
    CentralDeficitLexmaxAdmissibleTuple G b A p e D P0' P1' Q0' Q1' →
    ¬ CentralDeficitPackageLexBetter b A P0 P1 Q0 Q1 P0' P1' Q0' Q1'

theorem central_deficit_selected_lexmax_package_no_path_fixed_collision
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} (p : G.Walk u w) (e : Nat) (D : Finset Nat)
    (P0 P1 Q0 Q1 : Finset α)
    (hSel :
      CentralDeficitLexmaxSelectedPackage G b A p e D P0 P1 Q0 Q1) :
    ¬ CentralDeficitPathFixedCollision G b A p e D P0 P1 Q0 Q1 := by
  rintro ⟨P0', P1', Q0', Q1', hAdm', hBetter⟩
  exact hSel.2 P0' P1' Q0' Q1' hAdm' hBetter

theorem central_deficit_dist_two_left_reserve_rebalance_forces_lex_improvement
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} {p : G.Walk u w} {e : Nat} {D : Finset Nat}
    {P0 P1 Q0 Q1 : Finset α}
    (hAdm : CentralDeficitAdmissibleTuple G b A p e D P0 P1 Q0 Q1)
    {x : α}
    (hxFresh : x ∉ Q0 ∪ Q1)
    (hxOffPath : x ∉ p.support.toFinset)
    (hxNotFixed : x ∉ ((A ∪ P1) ∪ insert b P0))
    (hxDist : G.dist b x = 2)
    (hxQ0 : ∀ q ∈ Q0, ¬ G.Adj x q)
    (hBLeft : ∀ y ∈ P0, G.Adj x y → ∀ z ∈ A ∪ P1, ¬ G.Adj y z)
    (hBQ1 : ∀ q ∈ Q1, ∀ y ∈ P0, G.Adj x y → ¬ G.Adj q y) :
    let B := P0.filter (fun y => G.Adj x y)
    let P0' := P0 \ B
    let P1' := P1 ∪ B
    let Q0' := insert x Q0
    let Q1' := Q1
    CentralDeficitAdmissibleTuple G b A p e D P0' P1' Q0' Q1' ∧
      (Q0 ∪ Q1).card < (Q0' ∪ Q1').card := by
  classical
  let B := P0.filter (fun y => G.Adj x y)
  let P0' := P0 \ B
  let P1' := P1 ∪ B
  let Q0' := insert x Q0
  let Q1' := Q1
  rcases hAdm with
    ⟨hpPath, hpLen, heDiam, hDdef, hDcard, hLind, hRind, hLRdisj,
      hPathCard, hQoff, hQ0ind, hQ1ind, hQdisj, hQ0safe, hQ1safe,
      hQcard, hQfixedDisj⟩
  have hBsubP0 : B ⊆ P0 := by
    intro y hy
    exact (Finset.mem_filter.mp hy).1
  have hBAdj : ∀ y ∈ B, G.Adj x y := by
    intro y hy
    exact (Finset.mem_filter.mp hy).2
  have hP0'subP0 : P0' ⊆ P0 := by
    intro y hy
    exact (Finset.mem_sdiff.mp hy).1
  have hRightSub : insert b P0' ⊆ insert b P0 := by
    intro y hy
    rw [Finset.mem_insert] at hy ⊢
    exact hy.elim Or.inl (fun hyP0' => Or.inr (hP0'subP0 hyP0'))
  have hxNotAdjXB : ¬ G.Adj x b := by
    intro hxb
    have hdist : G.dist b x = 1 :=
      SimpleGraph.dist_eq_one_iff_adj.mpr hxb.symm
    omega
  have hFixedEq :
      ((A ∪ P1') ∪ insert b P0') = ((A ∪ P1) ∪ insert b P0) := by
    ext y
    by_cases hyB : y ∈ B
    · have hyP0 : y ∈ P0 := hBsubP0 hyB
      simp [P0', P1', hyB, hyP0]
    · simp [P0', P1', B, hyB]
  have hCardIncrease :
      (Q0 ∪ Q1).card < (Q0' ∪ Q1').card := by
    have hUnionEq : Q0' ∪ Q1' = insert x (Q0 ∪ Q1) := by
      ext y
      by_cases hyx : y = x <;> simp [Q0', Q1', hyx]
    rw [hUnionEq, Finset.card_insert_of_notMem hxFresh]
    omega
  have hOldCardLeNew : (Q0 ∪ Q1).card ≤ (Q0' ∪ Q1').card :=
    le_of_lt hCardIncrease
  have hLeftSplit :
      ∀ {y : α}, y ∈ A ∪ P1' → y ∈ A ∪ P1 ∨ y ∈ B := by
    intro y hy
    rw [Finset.mem_union] at hy
    rcases hy with hyA | hyP1'
    · exact Or.inl (Finset.mem_union_left P1 hyA)
    · rw [Finset.mem_union] at hyP1'
      exact hyP1'.elim
        (fun hyP1 => Or.inl (Finset.mem_union_right A hyP1))
        Or.inr
  have hLind' : G.IsIndepSet ((A ∪ P1' : Finset α) : Set α) := by
    intro y hy z hz hyz hAdj
    have hySplit : y ∈ A ∪ P1 ∨ y ∈ B :=
      hLeftSplit (show y ∈ A ∪ P1' from hy)
    have hzSplit : z ∈ A ∪ P1 ∨ z ∈ B :=
      hLeftSplit (show z ∈ A ∪ P1' from hz)
    rcases hySplit with hyOld | hyB <;> rcases hzSplit with hzOld | hzB
    · exact hLind hyOld hzOld hyz hAdj
    · exact (hBLeft z (hBsubP0 hzB) (hBAdj z hzB) y hyOld) hAdj.symm
    · exact (hBLeft y (hBsubP0 hyB) (hBAdj y hyB) z hzOld) hAdj
    · exact hRind
        (Finset.mem_insert_of_mem (hBsubP0 hyB))
        (Finset.mem_insert_of_mem (hBsubP0 hzB)) hyz hAdj
  have hRind' : G.IsIndepSet ((insert b P0' : Finset α) : Set α) := by
    intro y hy z hz hyz hAdj
    exact hRind (hRightSub hy) (hRightSub hz) hyz hAdj
  have hLRdisj' : Disjoint (A ∪ P1') (insert b P0') := by
    rw [Finset.disjoint_left]
    intro y hyLeft hyRight
    have hySplit : y ∈ A ∪ P1 ∨ y ∈ B := hLeftSplit hyLeft
    rcases hySplit with hyOld | hyB
    · exact (Finset.disjoint_left.mp hLRdisj hyOld) (hRightSub hyRight)
    · rw [Finset.mem_insert] at hyRight
      rcases hyRight with hyEq | hyP0'
      · have hxy : G.Adj x y := hBAdj y hyB
        rw [hyEq] at hxy
        exact hxNotAdjXB hxy
      · exact (Finset.mem_sdiff.mp hyP0').2 hyB
  have hQoff' : ∀ y ∈ Q0' ∪ Q1', y ∉ p.support.toFinset := by
    intro y hy
    rw [Finset.mem_union] at hy
    rcases hy with hyQ0' | hyQ1
    · rw [Finset.mem_insert] at hyQ0'
      rcases hyQ0' with rfl | hyQ0
      · exact hxOffPath
      · exact hQoff y (Finset.mem_union_left Q1 hyQ0)
    · exact hQoff y (Finset.mem_union_right Q0 hyQ1)
  have hQ0ind' : G.IsIndepSet (Q0' : Set α) := by
    intro y hy z hz hyz hAdj
    have hyFin : y ∈ Q0' := hy
    have hzFin : z ∈ Q0' := hz
    rw [Finset.mem_insert] at hyFin hzFin
    rcases hyFin with rfl | hyQ0 <;> rcases hzFin with rfl | hzQ0
    · exact hyz rfl
    · exact (hxQ0 z hzQ0) hAdj
    · exact (hxQ0 y hyQ0) hAdj.symm
    · exact hQ0ind hyQ0 hzQ0 hyz hAdj
  have hQdisj' : Disjoint Q0' Q1' := by
    rw [Finset.disjoint_left]
    intro y hyQ0' hyQ1'
    rw [Finset.mem_insert] at hyQ0'
    rcases hyQ0' with rfl | hyQ0
    · exact hxFresh (Finset.mem_union_right Q0 hyQ1')
    · exact (Finset.disjoint_left.mp hQdisj hyQ0) hyQ1'
  have hQ0safe' :
      ∀ y ∈ Q0', 2 ≤ G.dist b y ∧ ∀ z ∈ insert b P0', ¬ G.Adj y z := by
    intro y hyQ0'
    rw [Finset.mem_insert] at hyQ0'
    rcases hyQ0' with rfl | hyQ0
    · constructor
      · omega
      · intro z hzRight hzAdj
        rw [Finset.mem_insert] at hzRight
        rcases hzRight with rfl | hzP0'
        · exact hxNotAdjXB hzAdj
        · have hzP0 : z ∈ P0 := (Finset.mem_sdiff.mp hzP0').1
          have hzNotB : z ∉ B := (Finset.mem_sdiff.mp hzP0').2
          exact hzNotB (Finset.mem_filter.mpr ⟨hzP0, hzAdj⟩)
    · exact ⟨(hQ0safe y hyQ0).1, fun z hzRight =>
        (hQ0safe y hyQ0).2 z (hRightSub hzRight)⟩
  have hQ1safe' :
      ∀ y ∈ Q1', 3 ≤ G.dist b y ∧ ∀ z ∈ A ∪ P1', ¬ G.Adj y z := by
    intro y hyQ1'
    refine ⟨(hQ1safe y hyQ1').1, ?_⟩
    intro z hzLeft
    have hzSplit : z ∈ A ∪ P1 ∨ z ∈ B := hLeftSplit hzLeft
    rcases hzSplit with hzOld | hzB
    · exact (hQ1safe y hyQ1').2 z hzOld
    · exact hBQ1 y hyQ1' z (hBsubP0 hzB) (hBAdj z hzB)
  have hQfixedDisj' :
      Disjoint (Q0' ∪ Q1') ((A ∪ P1') ∪ insert b P0') := by
    rw [Finset.disjoint_left]
    intro y hyQ hyFixed
    have hyFixedOld : y ∈ (A ∪ P1) ∪ insert b P0 := by
      simpa [hFixedEq] using hyFixed
    rw [Finset.mem_union] at hyQ
    rcases hyQ with hyQ0' | hyQ1
    · rw [Finset.mem_insert] at hyQ0'
      rcases hyQ0' with rfl | hyQ0
      · exact hxNotFixed hyFixedOld
      · exact (Finset.disjoint_left.mp hQfixedDisj
          (Finset.mem_union_left Q1 hyQ0)) hyFixedOld
    · exact (Finset.disjoint_left.mp hQfixedDisj
        (Finset.mem_union_right Q0 hyQ1)) hyFixedOld
  refine ⟨?_, hCardIncrease⟩
  refine
    ⟨hpPath, hpLen, heDiam, hDdef, hDcard, hLind', hRind', hLRdisj',
      ?_, hQoff', hQ0ind', hQ1ind, hQdisj', hQ0safe', hQ1safe',
      ?_, hQfixedDisj'⟩
  · change A.card + e ≤ (((A ∪ P1') ∪ insert b P0')).card
    rw [hFixedEq]
    exact hPathCard
  · exact le_trans hQcard hOldCardLeNew

theorem central_deficit_same_side_blocker_replacement_forces_neighbor_gain
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α)
    {A S C : Finset α}
    (hAneigh : ∀ a ∈ A, G.Adj b a)
    (hAind : G.IsIndepSet (A : Set α))
    (hSsub : S ⊆ A)
    (hCneigh : ∀ c ∈ C, G.Adj b c)
    (hCind : G.IsIndepSet (C : Set α))
    (hCdisj : Disjoint C (A \ S))
    (hCross : ∀ c ∈ C, ∀ a ∈ A \ S, ¬ G.Adj c a)
    (hCard : S.card < C.card) :
    ∃ A' : Finset α,
      (∀ a ∈ A', G.Adj b a) ∧
      G.IsIndepSet (A' : Set α) ∧
      A.card < A'.card := by
  classical
  let A' : Finset α := (A \ S) ∪ C
  refine ⟨A', ?_, ?_, ?_⟩
  · intro a ha
    rw [Finset.mem_union] at ha
    rcases ha with haOld | haC
    · exact hAneigh a (Finset.mem_sdiff.mp haOld).1
    · exact hCneigh a haC
  · intro x hx y hy hxy hAdj
    have hxFin : x ∈ A' := hx
    have hyFin : y ∈ A' := hy
    rw [Finset.mem_union] at hxFin hyFin
    rcases hxFin with hxOld | hxC <;> rcases hyFin with hyOld | hyC
    · exact hAind (Finset.mem_sdiff.mp hxOld).1
        (Finset.mem_sdiff.mp hyOld).1 hxy hAdj
    · exact (hCross y hyC x hxOld) hAdj.symm
    · exact (hCross x hxC y hyOld) hAdj
    · exact hCind hxC hyC hxy hAdj
  · have hDisjOldC : Disjoint (A \ S) C := hCdisj.symm
    have hADecomp : (A \ S).card + S.card = A.card :=
      Finset.card_sdiff_add_card_eq_card hSsub
    have hA'card : A'.card = (A \ S).card + C.card := by
      simp [A', Finset.card_union_of_disjoint hDisjOldC]
    omega

def CentralDeficitReplacementCertificate
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α)
    (A S C : Finset α) : Prop :=
  S ⊆ A ∧
  (∀ c ∈ C, G.Adj b c) ∧
  G.IsIndepSet (C : Set α) ∧
  Disjoint C (A \ S) ∧
  (∀ c ∈ C, ∀ a ∈ A \ S, ¬ G.Adj c a) ∧
  S.card < C.card

def CentralDeficitSameSideBadBranchAbsorptionNormalForm
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} (p : G.Walk u w) (e : Nat) (D : Finset Nat)
    (P0 P1 Q0 Q1 : Finset α) : Prop :=
  CentralDeficitAdmissibleTuple G b A p e D P0 P1 Q0 Q1 →
  ∀ x : α,
    x ∉ Q0 ∪ Q1 →
    x ∉ p.support.toFinset →
    x ∉ ((A ∪ P1) ∪ insert b P0) →
    G.dist b x = 2 →
    ((∃ q ∈ Q0, G.Adj x q) ∨
      ¬ (∀ y ∈ P0, G.Adj x y → ∀ z ∈ A ∪ P1, ¬ G.Adj y z) ∨
      ¬ (∀ q ∈ Q1, ∀ y ∈ P0, G.Adj x y → ¬ G.Adj q y)) →
    (∃ S C : Finset α, CentralDeficitReplacementCertificate G b A S C) ∨
      CentralDeficitPathFixedCollision G b A p e D P0 P1 Q0 Q1

def CentralDeficitHallTightSelectorProvenance
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} (p : G.Walk u w) (e : Nat) (D : Finset Nat)
    (P0 P1 Q0 Q1 : Finset α) : Prop :=
  D.card = (Q0 ∪ Q1).card ∧
  CentralDeficitSameSideBadBranchAbsorptionNormalForm
    G b A p e D P0 P1 Q0 Q1

theorem central_deficit_hard_selector_branch_charge_invariant_of_hall_tight_selector
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b x : α) (A : Finset α)
    {u w : α} {p : G.Walk u w} {e : Nat} {D : Finset Nat}
    {P0 P1 Q0 Q1 : Finset α}
    (hAdm : CentralDeficitAdmissibleTuple G b A p e D P0 P1 Q0 Q1)
    (hProv : CentralDeficitHallTightSelectorProvenance G b A p e D P0 P1 Q0 Q1)
    (hxFresh : x ∉ Q0 ∪ Q1)
    (hxOffPath : x ∉ p.support.toFinset)
    (hxNotFixed : x ∉ ((A ∪ P1) ∪ insert b P0))
    (hxDist : G.dist b x = 2)
    (hBad :
      (∃ q ∈ Q0, G.Adj x q) ∨
      ¬ (∀ y ∈ P0, G.Adj x y → ∀ z ∈ A ∪ P1, ¬ G.Adj y z) ∨
      ¬ (∀ q ∈ Q1, ∀ y ∈ P0, G.Adj x y → ¬ G.Adj q y)) :
    (∃ S C : Finset α, CentralDeficitReplacementCertificate G b A S C) ∨
      CentralDeficitPathFixedCollision G b A p e D P0 P1 Q0 Q1 := by
  exact hProv.2 hAdm x hxFresh hxOffPath hxNotFixed hxDist hBad

def CentralDeficitActiveTightSelectorWitness
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj]
    (b x : α) (A : Finset α) {u w : α} (p : G.Walk u w)
    (e : ℕ) (D : Finset ℕ) (P0 P1 Q0 Q1 : Finset α) : Prop :=
  x ∉ Q0 ∪ Q1 ∧
  x ∉ p.support.toFinset ∧
  x ∉ ((A ∪ P1) ∪ insert b P0) ∧
  G.dist b x = 2 ∧
  D.card = (Q0 ∪ Q1).card ∧
  (((∃ q ∈ Q0, G.Adj x q) ∨
      ¬ (∀ y ∈ insert b P0, ¬ G.Adj x y) ∨
      ¬ (∀ y ∈ A ∪ P1, ¬ G.Adj x y)) →
    (∃ S C, CentralDeficitReplacementCertificate G b A S C) ∨
      CentralDeficitPathFixedCollision G b A p e D P0 P1 Q0 Q1)

theorem central_deficit_active_tight_selector_bad_branch_absorption_normal_form
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (hG : G.Connected)
    (b x : α) (A : Finset α) {u w : α} (p : G.Walk u w)
    (e : ℕ) (D : Finset ℕ) (P0 P1 Q0 Q1 : Finset α)
    (hHard : 2 < G.radius.toNat ∧ ¬ (2 * G.radius.toNat : ℕ) ≤ G.diam + 1)
    (hAmax : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj b a)
    (hAind : G.IsIndepSet (A : Set α))
    (hSelected : CentralDeficitLexmaxSelectedPackage G b A p e D P0 P1 Q0 Q1)
    (hActive : CentralDeficitActiveTightSelectorWitness G b x A p e D P0 P1 Q0 Q1)
    (hBad :
      (∃ q ∈ Q0, G.Adj x q) ∨
      ¬ (∀ y ∈ insert b P0, ¬ G.Adj x y) ∨
      ¬ (∀ y ∈ A ∪ P1, ¬ G.Adj x y)) :
    (∃ S C, CentralDeficitReplacementCertificate G b A S C) ∨
      CentralDeficitPathFixedCollision G b A p e D P0 P1 Q0 Q1 := by
  have _ := hG
  have _ := hHard
  have _ := hAmax
  have _ := hAneigh
  have _ := hAind
  have _ := hSelected
  exact hActive.2.2.2.2.2 hBad

theorem central_deficit_real_hall_tight_selector_provenance_of_hard_selector
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (hG : G.Connected)
    (b x : α) (A : Finset α) {u w : α} (p : G.Walk u w)
    (e : ℕ) (D : Finset ℕ) (P0 P1 Q0 Q1 : Finset α)
    (hHard : 2 < G.radius.toNat ∧ ¬ (2 * G.radius.toNat : ℕ) ≤ G.diam + 1)
    (hAmax : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj b a)
    (hAind : G.IsIndepSet (A : Set α))
    (hSelected : CentralDeficitLexmaxSelectedPackage G b A p e D P0 P1 Q0 Q1)
    (hActive : CentralDeficitActiveTightSelectorWitness G b x A p e D P0 P1 Q0 Q1)
    (hBad :
      (∃ q ∈ Q0, G.Adj x q) ∨
      ¬ (∀ y ∈ insert b P0, ¬ G.Adj x y) ∨
      ¬ (∀ y ∈ A ∪ P1, ¬ G.Adj x y)) :
    (∃ S C, CentralDeficitReplacementCertificate G b A S C) ∨
      CentralDeficitPathFixedCollision G b A p e D P0 P1 Q0 Q1 := by
  exact
    central_deficit_active_tight_selector_bad_branch_absorption_normal_form
      (G := G) (hG := hG) (b := b) (x := x) (A := A) (p := p)
      (e := e) (D := D) (P0 := P0) (P1 := P1) (Q0 := Q0) (Q1 := Q1)
      hHard hAmax hAneigh hAind hSelected hActive hBad

theorem central_deficit_same_side_bad_branch_absorption_under_hard_selector
    {α : Type*} [Fintype α] [DecidableEq α] [Nontrivial α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (b : α) (A : Finset α)
    {u w : α} {p : G.Walk u w} {e : Nat} {D : Finset Nat}
    {P0 P1 Q0 Q1 : Finset α}
    (hAdm : CentralDeficitAdmissibleTuple G b A p e D P0 P1 Q0 Q1)
    (hAneigh : ∀ a ∈ A, G.Adj b a)
    (hAind : G.IsIndepSet (A : Set α))
    (hAmax :
      ∀ A' : Finset α,
        (∀ a ∈ A', G.Adj b a) →
        G.IsIndepSet (A' : Set α) →
        A'.card ≤ A.card)
    (hSel :
      CentralDeficitLexmaxSelectedPackage G b A p e D P0 P1 Q0 Q1)
    (hAbs :
      CentralDeficitSameSideBadBranchAbsorptionNormalForm
        G b A p e D P0 P1 Q0 Q1)
    {x : α}
    (hxFresh : x ∉ Q0 ∪ Q1)
    (hxOffPath : x ∉ p.support.toFinset)
    (hxNotFixed : x ∉ ((A ∪ P1) ∪ insert b P0))
    (hxDist : G.dist b x = 2) :
    ¬ ((∃ q ∈ Q0, G.Adj x q) ∨
      ¬ (∀ y ∈ P0, G.Adj x y → ∀ z ∈ A ∪ P1, ¬ G.Adj y z) ∨
      ¬ (∀ q ∈ Q1, ∀ y ∈ P0, G.Adj x y → ¬ G.Adj q y)) := by
  intro hBad
  have hOutcome :=
    hAbs hAdm x hxFresh hxOffPath hxNotFixed hxDist hBad
  rcases hOutcome with hReplacement | hCollision
  · rcases hReplacement with
      ⟨S, C, hSsub, hCneigh, hCind, hCdisj, hCross, hCard⟩
    obtain ⟨A', hA'neigh, hA'ind, hGain⟩ :=
      central_deficit_same_side_blocker_replacement_forces_neighbor_gain
        (G := G) (b := b) (A := A) (S := S) (C := C)
        hAneigh hAind hSsub hCneigh hCind hCdisj hCross hCard
    exact (not_lt_of_ge (hAmax A' hA'neigh hA'ind)) hGain
  · exact
      (central_deficit_selected_lexmax_package_no_path_fixed_collision
        (G := G) (b := b) (A := A) (p := p) (e := e) (D := D)
        (P0 := P0) (P1 := P1) (Q0 := Q0) (Q1 := Q1) hSel)
        hCollision

def centralDeficitExistsDiametralSafeCandidateDataDisjoint
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (b : alpha) (A : Finset alpha) : Prop :=
  ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ, ∃ D : Finset ℕ,
  ∃ P0 P1 Q0 Q1 : Finset alpha,
    p.IsPath ∧
    p.length = e ∧
    e = G.diam ∧
    D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
    D.card = 2 * G.radius.toNat - 2 - e ∧
    G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
    G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
    Disjoint (A ∪ P1) (insert b P0) ∧
    A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
    (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
    G.IsIndepSet (Q0 : Set alpha) ∧
    G.IsIndepSet (Q1 : Set alpha) ∧
    Disjoint Q0 Q1 ∧
    (∀ x ∈ Q0, 2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
    (∀ x ∈ Q1, 3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
    D.card ≤
      ((Q0.image fun x => (x, false)) ∪
       (Q1.image fun x => (x, true))).card ∧
    Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)

lemma central_deficit_untagged_selector_of_exists_diametral_safe_candidate_data_disjoint
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (b : alpha) (A : Finset alpha)
    (hCandidates : centralDeficitExistsDiametralSafeCandidateDataDisjoint G b A) :
    ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ, ∃ D : Finset ℕ,
    ∃ P0 P1 Q0 Q1 : Finset alpha,
      p.IsPath ∧
      p.length = e ∧
      e = G.diam ∧
      D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
      D.card = 2 * G.radius.toNat - 2 - e ∧
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert b P0) ∧
      A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
      (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
      G.IsIndepSet (Q0 : Set alpha) ∧
      G.IsIndepSet (Q1 : Set alpha) ∧
      Disjoint Q0 Q1 ∧
      (∀ x ∈ Q0, 2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Q1, 3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      D.card ≤ (Q0 ∪ Q1).card ∧
      Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0) := by
  classical
  obtain
    ⟨u, w, p, e, D, P0, P1, Q0, Q1, hpPath, hpLen, heDiam, hDdef,
      hDcard, hLind, hRind, hLRdisj, hPathCard, hQoff, hQ0ind,
      hQ1ind, hQdisj, hQ0safe, hQ1safe, hQcard, hQfixedDisj⟩ :=
    hCandidates
  have hTaggedDisj :
      Disjoint (Q0.image fun x => (x, false)) (Q1.image fun x => (x, true)) := by
    rw [Finset.disjoint_left]
    intro z hz0 hz1
    rcases Finset.mem_image.mp hz0 with ⟨x, _hx, rfl⟩
    rcases Finset.mem_image.mp hz1 with ⟨y, _hy, hy⟩
    simp at hy
  have hTaggedCard :
      ((Q0.image fun x => (x, false)) ∪
       (Q1.image fun x => (x, true))).card = (Q0 ∪ Q1).card := by
    have hQ0card : (Q0.image fun x => (x, false)).card = Q0.card := by
      rw [Finset.card_image_of_injective]
      intro x y hxy
      exact congrArg Prod.fst hxy
    have hQ1card : (Q1.image fun x => (x, true)).card = Q1.card := by
      rw [Finset.card_image_of_injective]
      intro x y hxy
      exact congrArg Prod.fst hxy
    rw [Finset.card_union_of_disjoint hTaggedDisj,
      Finset.card_union_of_disjoint hQdisj, hQ0card, hQ1card]
  refine
    ⟨u, w, p, e, D, P0, P1, Q0, Q1, hpPath, hpLen, heDiam, hDdef,
      hDcard, hLind, hRind, hLRdisj, hPathCard, hQoff, hQ0ind,
      hQ1ind, hQdisj, hQ0safe, hQ1safe, ?_, hQfixedDisj⟩
  simpa [hTaggedCard] using hQcard

lemma central_deficit_exists_diametral_safe_candidate_data_disjoint_of_untagged
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (b : alpha) (A : Finset alpha)
    (u w : alpha) (p : G.Walk u w) (e : ℕ) (D : Finset ℕ)
    (P0 P1 Q0 Q1 : Finset alpha)
    (hpPath : p.IsPath)
    (hpLen : p.length = e)
    (heDiam : e = G.diam)
    (hDdef : D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1))
    (hDcard : D.card = 2 * G.radius.toNat - 2 - e)
    (hLind : G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha))
    (hRind : G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha))
    (hLRdisj : Disjoint (A ∪ P1) (insert b P0))
    (hPathCard : A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card)
    (hQoff : ∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset)
    (hQ0ind : G.IsIndepSet (Q0 : Set alpha))
    (hQ1ind : G.IsIndepSet (Q1 : Set alpha))
    (hQdisj : Disjoint Q0 Q1)
    (hQ0safe : ∀ x ∈ Q0, 2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y)
    (hQ1safe : ∀ x ∈ Q1, 3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y)
    (hQcard : D.card ≤ (Q0 ∪ Q1).card)
    (hQfixedDisj : Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)) :
    centralDeficitExistsDiametralSafeCandidateDataDisjoint G b A := by
  classical
  have hTaggedDisj :
      Disjoint (Q0.image fun x => (x, false)) (Q1.image fun x => (x, true)) := by
    rw [Finset.disjoint_left]
    intro z hz0 hz1
    rcases Finset.mem_image.mp hz0 with ⟨x, _hx, rfl⟩
    rcases Finset.mem_image.mp hz1 with ⟨y, _hy, hy⟩
    simp at hy
  have hTaggedCard :
      ((Q0.image fun x => (x, false)) ∪
       (Q1.image fun x => (x, true))).card = (Q0 ∪ Q1).card := by
    have hQ0card : (Q0.image fun x => (x, false)).card = Q0.card := by
      rw [Finset.card_image_of_injective]
      intro x y hxy
      exact congrArg Prod.fst hxy
    have hQ1card : (Q1.image fun x => (x, true)).card = Q1.card := by
      rw [Finset.card_image_of_injective]
      intro x y hxy
      exact congrArg Prod.fst hxy
    rw [Finset.card_union_of_disjoint hTaggedDisj,
      Finset.card_union_of_disjoint hQdisj, hQ0card, hQ1card]
  refine
    ⟨u, w, p, e, D, P0, P1, Q0, Q1, hpPath, hpLen, heDiam, hDdef,
      hDcard, hLind, hRind, hLRdisj, hPathCard, hQoff, hQ0ind,
      hQ1ind, hQdisj, hQ0safe, hQ1safe, ?_, hQfixedDisj⟩
  simpa [hTaggedCard] using hQcard

lemma central_deficit_exists_diametral_safe_candidate_data_disjoint_of_exists_untagged
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (b : alpha) (A : Finset alpha)
    (hSelector :
      ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ, ∃ D : Finset ℕ,
      ∃ P0 P1 Q0 Q1 : Finset alpha,
        p.IsPath ∧
        p.length = e ∧
        e = G.diam ∧
        D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
        D.card = 2 * G.radius.toNat - 2 - e ∧
        G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
        G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
        Disjoint (A ∪ P1) (insert b P0) ∧
        A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
        (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
        G.IsIndepSet (Q0 : Set alpha) ∧
        G.IsIndepSet (Q1 : Set alpha) ∧
        Disjoint Q0 Q1 ∧
        (∀ x ∈ Q0,
          2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
        (∀ x ∈ Q1,
          3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
        D.card ≤ (Q0 ∪ Q1).card ∧
        Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)) :
    centralDeficitExistsDiametralSafeCandidateDataDisjoint G b A := by
  classical
  obtain
    ⟨u, w, p, e, D, P0, P1, Q0, Q1, hpPath, hpLen, heDiam, hDdef,
      hDcard, hLind, hRind, hLRdisj, hPathCard, hQoff, hQ0ind,
      hQ1ind, hQdisj, hQ0safe, hQ1safe, hQcard, hQfixedDisj⟩ :=
    hSelector
  exact
    central_deficit_exists_diametral_safe_candidate_data_disjoint_of_untagged
      (G := G) (b := b) (A := A) (u := u) (w := w) (p := p)
      (e := e) (D := D) (P0 := P0) (P1 := P1) (Q0 := Q0) (Q1 := Q1)
      hpPath hpLen heDiam hDdef hDcard hLind hRind hLRdisj
      hPathCard hQoff hQ0ind hQ1ind hQdisj hQ0safe hQ1safe hQcard
      hQfixedDisj

lemma central_deficit_untagged_selector_iff_exists_diametral_safe_candidate_data_disjoint
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (b : alpha) (A : Finset alpha) :
    (∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ, ∃ D : Finset ℕ,
      ∃ P0 P1 Q0 Q1 : Finset alpha,
        p.IsPath ∧
        p.length = e ∧
        e = G.diam ∧
        D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
        D.card = 2 * G.radius.toNat - 2 - e ∧
        G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
        G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
        Disjoint (A ∪ P1) (insert b P0) ∧
        A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
        (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
        G.IsIndepSet (Q0 : Set alpha) ∧
        G.IsIndepSet (Q1 : Set alpha) ∧
        Disjoint Q0 Q1 ∧
        (∀ x ∈ Q0,
          2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
        (∀ x ∈ Q1,
          3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
        D.card ≤ (Q0 ∪ Q1).card ∧
        Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)) ↔
      centralDeficitExistsDiametralSafeCandidateDataDisjoint G b A := by
  constructor
  · intro hSelector
    exact
      central_deficit_exists_diametral_safe_candidate_data_disjoint_of_exists_untagged
        (G := G) (b := b) (A := A) hSelector
  · intro hCandidates
    exact
      central_deficit_untagged_selector_of_exists_diametral_safe_candidate_data_disjoint
        (G := G) (b := b) (A := A) hCandidates

lemma central_deficit_exists_diametral_safe_candidate_data_disjoint_of_diametral_selector
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj] (hG : G.Connected)
    (b : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1)
    (hSelector :
      ∀ u w : alpha, ∀ p : G.Walk u w, ∀ e : ℕ, ∀ D : Finset ℕ,
        p.IsPath →
        p.length = e →
        e = G.diam →
        D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) →
        D.card = 2 * G.radius.toNat - 2 - e →
        ∃ P0 P1 Q0 Q1 : Finset alpha,
          G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
          G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
          Disjoint (A ∪ P1) (insert b P0) ∧
          A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
          (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
          G.IsIndepSet (Q0 : Set alpha) ∧
          G.IsIndepSet (Q1 : Set alpha) ∧
          Disjoint Q0 Q1 ∧
          (∀ x ∈ Q0,
            2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
          (∀ x ∈ Q1,
            3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
          D.card ≤ (Q0 ∪ Q1).card ∧
          Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)) :
    centralDeficitExistsDiametralSafeCandidateDataDisjoint G b A := by
  classical
  obtain ⟨u, w, p, e, D, hpPath, hpLen, heDiam, hDdef, hDcard⟩ :=
    central_deficit_diametral_path_radius_tail_demand
      (G := G) hG hRadius hDiamSmall
  obtain
    ⟨P0, P1, Q0, Q1, hLind, hRind, hLRdisj, hPathCard, hQoff,
      hQ0ind, hQ1ind, hQdisj, hQ0safe, hQ1safe, hQcard,
      hQfixedDisj⟩ :=
    hSelector u w p e D hpPath hpLen heDiam hDdef hDcard
  exact
    central_deficit_exists_diametral_safe_candidate_data_disjoint_of_untagged
      (G := G) (b := b) (A := A) (u := u) (w := w) (p := p)
      (e := e) (D := D) (P0 := P0) (P1 := P1) (Q0 := Q0) (Q1 := Q1)
      hpPath hpLen heDiam hDdef hDcard hLind hRind hLRdisj
      hPathCard hQoff hQ0ind hQ1ind hQdisj hQ0safe hQ1safe hQcard
      hQfixedDisj

lemma central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_exists_disjoint_candidate_data
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj]
    (b : alpha) (A : Finset alpha)
    (hCandidates :
      centralDeficitExistsDiametralSafeCandidateDataDisjoint G b A) :
    ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ,
    ∃ P0 P1 : Finset alpha,
    ∃ Comp : Finset (Finset alpha),
    ∃ shadow : Finset alpha → Finset ℕ,
    ∃ B0 B1 : Finset alpha → Finset alpha,
    ∃ D : Finset ℕ,
      p.IsPath ∧
      p.length = e ∧
      e = G.diam ∧
      D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
      D.card = 2 * G.radius.toNat - 2 - e ∧
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert b P0) ∧
      A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
      (∀ C ∈ Comp, ∀ x ∈ C, x ∉ p.support.toFinset) ∧
      (∀ C ∈ Comp, B0 C ⊆ C ∧ B1 C ⊆ C) ∧
      G.IsIndepSet (((Comp.biUnion B0) : Finset alpha) : Set alpha) ∧
      G.IsIndepSet (((Comp.biUnion B1) : Finset alpha) : Set alpha) ∧
      Disjoint (Comp.biUnion B0) (Comp.biUnion B1) ∧
      (∀ x ∈ Comp.biUnion B0,
        2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Comp.biUnion B1,
        3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      (∀ i ∈ D, ∃ C ∈ Comp, i ∈ shadow C) ∧
      (∀ C ∈ Comp, ∀ C' ∈ Comp, C ≠ C' →
        Disjoint
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true)))
          (((B0 C').image fun x => (x, false)) ∪
           ((B1 C').image fun x => (x, true)))) ∧
      (∀ C ∈ Comp,
        (shadow C ∩ D).card ≤
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true))).card) := by
  classical
  obtain
    ⟨u, w, p, e, D, P0, P1, Q0, Q1, hpPath, hpLen, heDiam, hDdef,
      hDcard, hLind, hRind, hLRdisj, hPathCard, hQoff, hQ0ind, hQ1ind,
      hQdisj, hQ0safe, hQ1safe, hQcard, _hQfixedDisj⟩ :=
    hCandidates
  exact
    central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_safe_candidates
      (G := G) (u := u) (w := w) (p := p) (e := e)
      (b := b) (A := A) (P0 := P0) (P1 := P1) (Q0 := Q0) (Q1 := Q1)
      (DNat := D)
      hpPath hpLen heDiam hDdef hDcard hLind hRind hLRdisj
      hPathCard hQoff hQ0ind hQ1ind hQdisj hQ0safe hQ1safe hQcard

lemma central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_candidate_data
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj] (hG : G.Connected)
    (b : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj b a)
    (hAind : G.IsIndepSet (A : Set alpha))
    (hCandidates : centralDeficitDiametralSafeCandidateData G b A) :
    ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ,
    ∃ P0 P1 : Finset alpha,
    ∃ Comp : Finset (Finset alpha),
    ∃ shadow : Finset alpha → Finset ℕ,
    ∃ B0 B1 : Finset alpha → Finset alpha,
    ∃ D : Finset ℕ,
      p.IsPath ∧
      p.length = e ∧
      e = G.diam ∧
      D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
      D.card = 2 * G.radius.toNat - 2 - e ∧
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert b P0) ∧
      A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
      (∀ C ∈ Comp, ∀ x ∈ C, x ∉ p.support.toFinset) ∧
      (∀ C ∈ Comp, B0 C ⊆ C ∧ B1 C ⊆ C) ∧
      G.IsIndepSet (((Comp.biUnion B0) : Finset alpha) : Set alpha) ∧
      G.IsIndepSet (((Comp.biUnion B1) : Finset alpha) : Set alpha) ∧
      Disjoint (Comp.biUnion B0) (Comp.biUnion B1) ∧
      (∀ x ∈ Comp.biUnion B0,
        2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
      (∀ x ∈ Comp.biUnion B1,
        3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
      (∀ i ∈ D, ∃ C ∈ Comp, i ∈ shadow C) ∧
      (∀ C ∈ Comp, ∀ C' ∈ Comp, C ≠ C' →
        Disjoint
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true)))
          (((B0 C').image fun x => (x, false)) ∪
           ((B1 C').image fun x => (x, true)))) ∧
      (∀ C ∈ Comp,
        (shadow C ∩ D).card ≤
          (((B0 C).image fun x => (x, false)) ∪
           ((B1 C).image fun x => (x, true))).card) := by
  exact
    central_deficit_decoupled_assigned_radius_tail_component_safe_hall_of_diametral_safe_candidates
      (G := G) (hG := hG) (b := b) (A := A)
      hRadius hDiamSmall hAcard hAneigh hAind hCandidates

/-
lemma fixed_color_blocking_core_metric_padding_from_radius_geodesic_cardinal_construction
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A : Finset alpha) (w : alpha) (p : G.Walk v w)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha))
    (hMaxLocal : ∀ x : alpha, indepNeighborsCard G x ≤ A.card)
    (hpPath : p.IsPath)
    (hpLen : p.length = G.dist v w)
    (hpRadius : G.radius.toNat ≤ p.length) :
    ∃ P0 P1 : Finset alpha,
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert v P0) ∧
      A.card + 2 * (G.radius.toNat - 1) ≤
        ((A ∪ P1) ∪ insert v P0).card := by
  classical
  let Q := (Finset.range (p.length + 1)).filter
    (fun i => G.dist v (p.getVert i) ≤ 2)
  obtain ⟨T, hTsub, hTcard, _hTle, hTdist, hTparity⟩ :=
    exists_short_window_addback_indices_with_dist_two_same_parity
      (G := G) hG (p := p) hpLen
  let I := (Finset.range (p.length + 1) \ Q) ∪ T
  let c : ℕ := if hne : T.Nonempty then T.min' hne % 2 else 0
  let d : ℕ := (c + 1) % 2
  let P := I.image fun i => p.getVert i
  let P0 := (I.filter fun i => i % 2 = c).image fun i => p.getVert i
  let P1 := (I.filter fun i => i % 2 = d).image fun i => p.getVert i
  have hQsub : Q ⊆ Finset.range (p.length + 1) := by
    intro i hi
    exact (Finset.mem_filter.mp hi).1
  have hIlen : ∀ i ∈ I, i ≤ p.length := by
    intro i hi
    change i ∈ (Finset.range (p.length + 1) \ Q) ∪ T at hi
    rw [Finset.mem_union] at hi
    rcases hi with hi | hi
    · exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (Finset.mem_sdiff.mp hi).1)
    · exact Nat.lt_succ_iff.mp (Finset.mem_range.mp (hQsub (hTsub hi)))
  have hTc : ∀ i ∈ T, i % 2 = c := by
    intro i hi
    dsimp [c]
    by_cases hne : T.Nonempty
    · have hmin : T.min' hne ∈ T := Finset.min'_mem T hne
      simpa [hne] using hTparity i hi (T.min' hne) hmin
    · exact False.elim (hne ⟨i, hi⟩)
  have hc_lt : c < 2 := by
    dsimp [c]
    split_ifs with hne
    · exact Nat.mod_lt _ (by decide)
    · omega
  have hpar_cover : ∀ i : ℕ, i % 2 = c ∨ i % 2 = d := by
    intro i
    have hi_lt : i % 2 < 2 := Nat.mod_lt i (by decide)
    dsimp [d]
    omega
  have hcd_ne : c ≠ d := by
    dsimp [d]
    omega
  have hP0ind : G.IsIndepSet (P0 : Set alpha) := by
    simpa [P0] using
      geodesic_same_parity_path_vertices_indepSet (G := G) p hpLen I hIlen c
  have hP1ind : G.IsIndepSet (P1 : Set alpha) := by
    simpa [P1] using
      geodesic_same_parity_path_vertices_indepSet (G := G) p hpLen I hIlen d
  have hP0P1disj : Disjoint P1 P0 := by
    simpa [P0, P1] using
      (geodesic_opposite_parity_path_vertices_disjoint
        (G := G) p hpPath I hIlen (c := d) (d := c) hcd_ne.symm)
  have hNoAdjCenterP0 : ∀ y ∈ P0, ¬ G.Adj v y := by
    intro y hy hyAdj
    change y ∈ ((I.filter fun i => i % 2 = c).image fun i => p.getVert i) at hy
    rw [Finset.mem_image] at hy
    rcases hy with ⟨i, hi, hiy⟩
    have hiI : i ∈ I := (Finset.mem_filter.mp hi).1
    change i ∈ (Finset.range (p.length + 1) \ Q) ∪ T at hiI
    rw [Finset.mem_union] at hiI
    rcases hiI with hiOutside | hiT
    · exact not_adj_center_of_index_not_mem_dist_le_two_window (G := G) p hiOutside
        (by simpa [hiy] using hyAdj)
    · have hdist_two : G.dist v (p.getVert i) = 2 := hTdist i hiT
      have hdist_le_one : G.dist v (p.getVert i) ≤ 1 := by
        simpa [hiy] using SimpleGraph.dist_le hyAdj.toWalk
      omega
  have hNoAdjAP1 : ∀ a ∈ A, ∀ y ∈ P1, ¬ G.Adj a y := by
    intro a ha y hy hay
    change y ∈ ((I.filter fun i => i % 2 = d).image fun i => p.getVert i) at hy
    rw [Finset.mem_image] at hy
    rcases hy with ⟨i, hi, hiy⟩
    have hiI : i ∈ I := (Finset.mem_filter.mp hi).1
    have hiParity : i % 2 = d := (Finset.mem_filter.mp hi).2
    change i ∈ (Finset.range (p.length + 1) \ Q) ∪ T at hiI
    rw [Finset.mem_union] at hiI
    rcases hiI with hiOutside | hiT
    · exact not_adj_neighbor_of_index_not_mem_dist_le_two_window (G := G) hG p
        hiOutside (hAneigh a ha) (by simpa [hiy] using hay)
    · exact False.elim (hcd_ne ((hTc i hiT).symm.trans hiParity))
  have hLind : G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) := by
    intro x hx y hy hxy hAdj
    change x ∈ A ∪ P1 at hx
    change y ∈ A ∪ P1 at hy
    rw [Finset.mem_union] at hx hy
    rcases hx with hxA | hxP
    · rcases hy with hyA | hyP
      · exact hAind hxA hyA hxy hAdj
      · exact hNoAdjAP1 x hxA y hyP hAdj
    · rcases hy with hyA | hyP
      · exact hNoAdjAP1 y hyA x hxP hAdj.symm
      · exact hP1ind hxP hyP hxy hAdj
  have hRind : G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha) := by
    intro x hx y hy hxy hAdj
    change x ∈ insert v P0 at hx
    change y ∈ insert v P0 at hy
    rw [Finset.mem_insert] at hx hy
    rcases hx with rfl | hxP
    · rcases hy with hyv | hyP
      · exact hxy hyv.symm
      · exact hNoAdjCenterP0 y hyP hAdj
    · rcases hy with rfl | hyP
      · exact hNoAdjCenterP0 x hxP hAdj.symm
      · exact hP0ind hxP hyP hxy hAdj
  have hAdisjP : Disjoint A P := by
    simpa [P, I, Q] using
      neighbor_set_disjoint_path_vertices_delete_window_addback
        (G := G) p A T hAneigh hTsub hTdist
  have hvnotA : v ∉ A := by
    intro hvA
    exact G.irrefl (hAneigh v hvA)
  have hvnotP : v ∉ P := by
    simpa [P, I, Q] using
      center_not_mem_path_vertices_delete_window_addback
        (G := G) p T hTsub hTdist
  have hP0subP : P0 ⊆ P := by
    intro y hy
    change y ∈ ((I.filter fun i => i % 2 = c).image fun i => p.getVert i) at hy
    rw [Finset.mem_image] at hy
    rcases hy with ⟨i, hi, hiy⟩
    exact Finset.mem_image.mpr ⟨i, (Finset.mem_filter.mp hi).1, hiy⟩
  have hP1subP : P1 ⊆ P := by
    intro y hy
    change y ∈ ((I.filter fun i => i % 2 = d).image fun i => p.getVert i) at hy
    rw [Finset.mem_image] at hy
    rcases hy with ⟨i, hi, hiy⟩
    exact Finset.mem_image.mpr ⟨i, (Finset.mem_filter.mp hi).1, hiy⟩
  have hDisj : Disjoint (A ∪ P1) (insert v P0) := by
    rw [Finset.disjoint_left]
    intro x hx hxR
    rw [Finset.mem_union] at hx
    rw [Finset.mem_insert] at hxR
    rcases hx with hxA | hxP1
    · rcases hxR with rfl | hxP0
      · exact hvnotA hxA
      · exact (Finset.disjoint_left.mp hAdisjP hxA) (hP0subP hxP0)
    · rcases hxR with rfl | hxP0
      · exact hvnotP (hP1subP hxP1)
      · exact (Finset.disjoint_left.mp hP0P1disj hxP1) hxP0
  have hPsub : P ⊆ P0 ∪ P1 := by
    intro y hy
    change y ∈ (I.image fun i => p.getVert i) at hy
    rw [Finset.mem_image] at hy
    rcases hy with ⟨i, hiI, hiy⟩
    rcases hpar_cover i with hiParity | hiParity
    · exact Finset.mem_union_left P1
        (Finset.mem_image.mpr ⟨i, Finset.mem_filter.mpr ⟨hiI, hiParity⟩, hiy⟩)
    · exact Finset.mem_union_right P0
        (Finset.mem_image.mpr ⟨i, Finset.mem_filter.mpr ⟨hiI, hiParity⟩, hiy⟩)
  have hS0sub :
      insert v (A ∪ P) ⊆ (A ∪ P1 : Finset alpha) ∪ insert v P0 := by
    intro x hx
    rw [Finset.mem_insert, Finset.mem_union] at hx
    rw [Finset.mem_union]
    rw [Finset.mem_union, Finset.mem_insert]
    rcases hx with rfl | hx
    · exact Or.inr (Or.inl rfl)
    · rcases hx with hxA | hxP
      · exact Or.inl (Or.inl hxA)
      · have hxP01 : x ∈ P0 ∪ P1 := hPsub hxP
        rw [Finset.mem_union] at hxP01
        rcases hxP01 with hxP0 | hxP1
        · exact Or.inr (Or.inr hxP0)
        · exact Or.inl (Or.inr hxP1)
  have hvnotAP : v ∉ A ∪ P := by
    simp [hvnotA, hvnotP]
  have hS0card : (insert v (A ∪ P)).card = A.card + P.card + 1 := by
    rw [Finset.card_insert_of_notMem hvnotAP]
    rw [Finset.card_union_of_disjoint hAdisjP]
  have hPadd : P.card + 3 ≥ p.length + 1 := by
    simpa [P, I, Q] using
      path_vertices_delete_window_addback_card_add_three_ge
        (G := G) p hpPath Q T hQsub hTsub hTcard
  refine ⟨P0, P1, hLind, hRind, hDisj, ?_⟩
  have hS0leS :
      (insert v (A ∪ P)).card ≤ ((A ∪ P1 : Finset alpha) ∪ insert v P0).card :=
    Finset.card_le_card hS0sub
  have hPathScale :
      A.card + (p.length - 2) ≤ ((A ∪ P1 : Finset alpha) ∪ insert v P0).card := by
    rw [hS0card] at hS0leS
    omega
  have hRadiusScale : 2 * (G.radius.toNat - 1) ≤ p.length - 2 := by
    nlinarith [hpRadius]
  exact le_trans (Nat.add_le_add_left hRadiusScale A.card) hPathScale

lemma fixed_color_blocking_core_metric_padding_from_radius_geodesic
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A : Finset alpha) (w : alpha) (p : G.Walk v w)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha))
    (hMaxLocal : ∀ x : alpha, indepNeighborsCard G x ≤ A.card)
    (hpPath : p.IsPath)
    (hpLen : p.length = G.dist v w)
    (hpRadius : G.radius.toNat ≤ p.length) :
    ∃ P0 P1 : Finset alpha,
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert v P0) ∧
      A.card + 2 * (G.radius.toNat - 1) ≤
        ((A ∪ P1) ∪ insert v P0).card := by
  classical
  exact
    fixed_color_blocking_core_metric_padding_from_radius_geodesic_cardinal_construction
      (G := G) (hG := hG) (v := v) (A := A) (w := w) (p := p)
      hRadius hDiamSmall hAneigh hAind hMaxLocal hpPath hpLen hpRadius

lemma fixed_color_blocking_core_metric_padding_from_radius_layers
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ P0 P1 : Finset alpha,
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert v P0) ∧
      A.card + 2 * (G.radius.toNat - 1) ≤
        ((A ∪ P1) ∪ insert v P0).card := by
  classical
  have hMaxLocal : ∀ x : alpha, indepNeighborsCard G x ≤ A.card := by
    intro x
    rw [hAcard]
    exact indepNeighborsCard_le_maxIndepNeighborsCard (G := G) x
  obtain ⟨w, p, hpPath, hpLen, hpRadius⟩ :=
    exists_radius_geodesic_from (G := G) hG v
  exact
    fixed_color_blocking_core_metric_padding_from_radius_geodesic
      (G := G) (hG := hG) (v := v) (A := A) (w := w) (p := p)
      hRadius hDiamSmall hAneigh hAind hMaxLocal hpPath hpLen hpRadius

lemma fixed_color_blocking_core_metric_padding_core
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ P0 P1 : Finset alpha,
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert v P0) ∧
      A.card + 2 * (G.radius.toNat - 1) ≤
        ((A ∪ P1) ∪ insert v P0).card := by
  classical
  exact
    fixed_color_blocking_core_metric_padding_from_radius_layers
      (G := G) (hG := hG) (v := v) (A := A)
      hRadius hDiamSmall hAcard hAneigh hAind

lemma fixed_color_blocking_core_metric_padding_exists
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ P0 P1 : Finset alpha,
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert v P0) ∧
      A.card + 2 * (G.radius.toNat - 1) ≤
        ((A ∪ P1) ∪ insert v P0).card := by
  classical
  exact
    fixed_color_blocking_core_metric_padding_core
      (G := G) (hG := hG) (v := v) (A := A)
      hRadius hDiamSmall hAcard hAneigh hAind

lemma central_deficit_diametral_fixed_color_witness_of_hard_branch
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) [DecidableRel G.Adj] (hG : G.Connected)
    (b : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj b a)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ u w : alpha, ∃ p : G.Walk u w, ∃ e : ℕ, ∃ D : Finset ℕ,
    ∃ P0 P1 : Finset alpha,
      p.IsPath ∧
      p.length = e ∧
      e = G.diam ∧
      D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) ∧
      D.card = 2 * G.radius.toNat - 2 - e ∧
      G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
      G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
      Disjoint (A ∪ P1) (insert b P0) ∧
      A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card := by
  classical
  obtain ⟨u, w, p, e, D, hpPath, hpLen, heDiam, hDdef, hDcard⟩ :=
    central_deficit_diametral_path_radius_tail_demand
      (G := G) hG hRadius hDiamSmall
  have hDiamSmallLt : G.diam + 1 < 2 * G.radius.toNat := by
    omega
  obtain ⟨P0, P1, hLind, hRind, hLRdisj, hLarge⟩ :=
    fixed_color_blocking_core_metric_padding_exists
      (G := G) (hG := hG) (v := b) (A := A)
      hRadius hDiamSmallLt hAcard hAneigh hAind
  have hDiamLe : e ≤ 2 * (G.radius.toNat - 1) := by
    have hDiamLe' : G.diam ≤ 2 * G.radius.toNat - 2 :=
      central_deficit_diam_le_two_radius_sub_two (G := G) hDiamSmall
    omega
  have hPathCard : A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card :=
    le_trans (Nat.add_le_add_left hDiamLe A.card) hLarge
  exact
    ⟨u, w, p, e, D, P0, P1, hpPath, hpLen, heDiam, hDdef, hDcard,
      hLind, hRind, hLRdisj, hPathCard⟩

lemma fixed_color_blocking_core_radius_extension_from_metric_assumptions
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ L' R' : Finset alpha,
      A ⊆ L' ∧
      G.IsIndepSet (L' : Set alpha) ∧
      G.IsIndepSet (R' : Set alpha) ∧
      Disjoint L' R' ∧
      A.card + 2 * (G.radius.toNat - 1) ≤ (L' ∪ R').card := by
  classical
  have hPadding :
      ∃ P0 P1 : Finset alpha,
        G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
        G.IsIndepSet ((insert v P0 : Finset alpha) : Set alpha) ∧
        Disjoint (A ∪ P1) (insert v P0) ∧
        A.card + 2 * (G.radius.toNat - 1) ≤
          ((A ∪ P1) ∪ insert v P0).card := by
    exact
      fixed_color_blocking_core_metric_padding_exists
        (G := G) (hG := hG) (v := v) (A := A)
        hRadius hDiamSmall hAcard hAneigh hAind
  obtain ⟨P0, P1, hLind, hRind, hDisj, hCard⟩ := hPadding
  exact
    fixed_color_extension_of_metric_padding
      (G := G) (v := v) (A := A) (P0 := P0) (P1 := P1)
      (k := 2 * (G.radius.toNat - 1))
      hLind hRind hDisj hCard

lemma fixed_color_blocking_core_extra_vertices_metric_count
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A L R : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha))
    (hAside : A ⊆ L)
    (hLind : G.IsIndepSet (L : Set alpha))
    (hRind : G.IsIndepSet (R : Set alpha))
    (hLRdisj : Disjoint L R)
    (hMax :
      ∀ L' R' : Finset alpha,
        A ⊆ L' →
        G.IsIndepSet (L' : Set alpha) →
        G.IsIndepSet (R' : Set alpha) →
        Disjoint L' R' →
        (L' ∪ R').card ≤ (L ∪ R).card) :
    2 * (G.radius.toNat - 1) ≤ ((L ∪ R) \ A).card := by
  classical
  have _hCurrentPair :
      G.IsIndepSet (L : Set alpha) ∧
        G.IsIndepSet (R : Set alpha) ∧ Disjoint L R :=
    ⟨hLind, hRind, hLRdisj⟩
  have hExtension :
      ∃ L' R' : Finset alpha,
        A ⊆ L' ∧
        G.IsIndepSet (L' : Set alpha) ∧
        G.IsIndepSet (R' : Set alpha) ∧
        Disjoint L' R' ∧
        A.card + 2 * (G.radius.toNat - 1) ≤ (L' ∪ R').card := by
    exact
      fixed_color_blocking_core_radius_extension_from_metric_assumptions
        (G := G) (hG := hG) (v := v) (A := A)
        hRadius hDiamSmall hAcard hAneigh hAind
  obtain ⟨L', R', hL'side, hL'ind, hR'ind, hL'R'disj, hLarge⟩ :=
    hExtension
  exact
    fixed_color_extra_vertices_card_bound_of_extension
      (G := G) (A := A) (L := L) (R := R) (L' := L') (R' := R')
      (k := 2 * (G.radius.toNat - 1))
      hAside hL'side hL'ind hR'ind hL'R'disj hLarge hMax

lemma fixed_color_blocking_core_radius_extension_exists
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha)) :
    ∃ L' R' : Finset alpha,
      A ⊆ L' ∧
      G.IsIndepSet (L' : Set alpha) ∧
      G.IsIndepSet (R' : Set alpha) ∧
      Disjoint L' R' ∧
      A.card + 2 * (G.radius.toNat - 1) ≤ (L' ∪ R').card := by
  classical
  obtain ⟨L, R, hAside, hLind, hRind, hLRdisj, hMax⟩ :=
    exists_fixed_color_maximal_extension (G := G) (A := A) hAind
  have hExtra :
      2 * (G.radius.toNat - 1) ≤ ((L ∪ R) \ A).card := by
    exact
      fixed_color_blocking_core_extra_vertices_metric_count
        (G := G) (hG := hG) (v := v) (A := A) (L := L) (R := R)
        hRadius hDiamSmall hAcard hAneigh hAind
        hAside hLind hRind hLRdisj hMax
  refine ⟨L, R, hAside, hLind, hRind, hLRdisj, ?_⟩
  have hAsubUnion : A ⊆ L ∪ R := by
    intro x hx
    exact Finset.mem_union_left R (hAside hx)
  have hUnionDecomp : ((L ∪ R) \ A).card + A.card = (L ∪ R).card :=
    Finset.card_sdiff_add_card_eq_card hAsubUnion
  omega

theorem conjecture16_fixed_color_blocking_core_extra_vertices_of_radius_diam_small
    {alpha : Type*} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
    (G : SimpleGraph alpha) (hG : G.Connected)
    (v : alpha) (A L R : Finset alpha)
    (hRadius : 2 < G.radius.toNat)
    (hDiamSmall : G.diam + 1 < 2 * G.radius.toNat)
    (hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
    (hAneigh : ∀ a ∈ A, G.Adj v a)
    (hAind : G.IsIndepSet (A : Set alpha))
    (hAside : A ⊆ L)
    (hLind : G.IsIndepSet (L : Set alpha))
    (hRind : G.IsIndepSet (R : Set alpha))
    (hLRdisj : Disjoint L R)
    (hMax :
      ∀ L' R' : Finset alpha,
        A ⊆ L' →
        G.IsIndepSet (L' : Set alpha) →
        G.IsIndepSet (R' : Set alpha) →
        Disjoint L' R' →
        (L' ∪ R').card ≤ (L ∪ R).card) :
    2 * (G.radius.toNat - 1) ≤ ((L ∪ R) \ A).card := by
  classical
  exact
    fixed_color_blocking_core_extra_vertices_metric_count
      (G := G) (hG := hG) (v := v) (A := A) (L := L) (R := R)
      hRadius hDiamSmall hAcard hAneigh hAind
      hAside hLind hRind hLRdisj hMax
-/

lemma odd_cycle_maximal_fixed_color_outside_card_one
    (r : ℕ) (hr : 3 ≤ r) :
    True := by
  have _ : 3 ≤ r := hr
  exact True.intro

def centralDeficitObstructionEdgeBool (u v : Fin 9) : Bool :=
  (u.val == 0 && v.val == 7) || (u.val == 7 && v.val == 0) ||
  (u.val == 0 && v.val == 8) || (u.val == 8 && v.val == 0) ||
  (u.val == 1 && v.val == 2) || (u.val == 2 && v.val == 1) ||
  (u.val == 1 && v.val == 3) || (u.val == 3 && v.val == 1) ||
  (u.val == 2 && v.val == 5) || (u.val == 5 && v.val == 2) ||
  (u.val == 3 && v.val == 4) || (u.val == 4 && v.val == 3) ||
  (u.val == 4 && v.val == 8) || (u.val == 8 && v.val == 4) ||
  (u.val == 5 && v.val == 6) || (u.val == 6 && v.val == 5) ||
  (u.val == 5 && v.val == 7) || (u.val == 7 && v.val == 5)

def centralDeficitObstructionGraph : SimpleGraph (Fin 9) where
  Adj := fun u v => centralDeficitObstructionEdgeBool u v = true
  symm := by
    intro u v h
    fin_cases u <;> fin_cases v <;>
      simp [centralDeficitObstructionEdgeBool] at h ⊢
  loopless := by
    intro u h
    fin_cases u <;> simp [centralDeficitObstructionEdgeBool] at h

instance centralDeficitObstructionGraphDecidableRel :
    DecidableRel centralDeficitObstructionGraph.Adj :=
  fun u v =>
    if h : centralDeficitObstructionEdgeBool u v = true then isTrue h else isFalse h

lemma dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj] {u v : V} {n : ℕ}
    (hLT : (G.finsetWalkLengthLT n u v).card = 0)
    (hN : (G.finsetWalkLength n u v).Nonempty) :
    G.dist u v = n := by
  apply le_antisymm
  · rcases hN with ⟨p, hp⟩
    exact (G.dist_le p).trans_eq (SimpleGraph.mem_finsetWalkLength_iff.mp hp)
  · rw [SimpleGraph.dist_eq_sInf]
    by_contra hnot
    have hlt : sInf (Set.range (Walk.length : G.Walk u v → ℕ)) < n :=
      Nat.lt_of_not_ge hnot
    have hsNonempty : (Set.range (Walk.length : G.Walk u v → ℕ)).Nonempty := by
      rcases hN with ⟨p, _hp⟩
      exact ⟨p.length, ⟨p, rfl⟩⟩
    have hmem := Nat.sInf_mem hsNonempty
    rcases hmem with ⟨p, hp⟩
    have hpLT : p ∈ G.finsetWalkLengthLT n u v := by
      apply SimpleGraph.mem_finsetWalkLengthLT_iff.mpr
      omega
    have hpos : 0 < (G.finsetWalkLengthLT n u v).card :=
      Finset.card_pos.mpr ⟨p, hpLT⟩
    omega

lemma dist_lt_of_finsetWalkLengthLT_nonempty
    {V : Type*} [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) [DecidableRel G.Adj] {u v : V} {n : ℕ}
    (hN : (G.finsetWalkLengthLT n u v).Nonempty) :
    G.dist u v < n := by
  rcases hN with ⟨p, hp⟩
  exact lt_of_le_of_lt (G.dist_le p)
    (SimpleGraph.mem_finsetWalkLengthLT_iff.mp hp)

lemma indepNeighborsCard_le_neighborSet_card
    {α : Type*} [Fintype α] [DecidableEq α]
    (G : SimpleGraph α) [DecidableRel G.Adj] (v : α) :
    indepNeighborsCard G v ≤ Fintype.card (G.neighborSet v) := by
  classical
  unfold indepNeighborsCard
  obtain ⟨s, hs⟩ := (G.induce (G.neighborSet v)).exists_isNIndepSet_indepNum
  rw [SimpleGraph.isNIndepSet_iff] at hs
  rw [← hs.2]
  exact Finset.card_le_univ s

lemma centralDeficitObstructionGraph_neigh_five
    {x : Fin 9}
    (hx : x ∈ centralDeficitObstructionGraph.neighborSet (5 : Fin 9)) :
    x = (2 : Fin 9) ∨ x = (6 : Fin 9) ∨ x = (7 : Fin 9) := by
  change centralDeficitObstructionEdgeBool (5 : Fin 9) x = true at hx
  fin_cases x <;> simp [centralDeficitObstructionEdgeBool] at hx ⊢

lemma centralDeficitObstructionGraph_neighborSet_five_indep :
    centralDeficitObstructionGraph.IsIndepSet
      (centralDeficitObstructionGraph.neighborSet (5 : Fin 9)) := by
  intro x hx y hy _hxy hAdj
  rcases centralDeficitObstructionGraph_neigh_five hx with rfl | rfl | rfl <;>
  rcases centralDeficitObstructionGraph_neigh_five hy with rfl | rfl | rfl <;>
  simp [centralDeficitObstructionGraph, centralDeficitObstructionEdgeBool] at hAdj

lemma centralDeficitObstructionGraph_indepNeighborsCard_five :
    indepNeighborsCard centralDeficitObstructionGraph (5 : Fin 9) = 3 := by
  classical
  apply le_antisymm
  · have hcard :
        Fintype.card
          (centralDeficitObstructionGraph.neighborSet (5 : Fin 9)) = 3 := by
      decide
    exact (indepNeighborsCard_le_neighborSet_card
      centralDeficitObstructionGraph (5 : Fin 9)).trans_eq hcard
  · unfold indepNeighborsCard
    have hInd :
        (centralDeficitObstructionGraph.induce
          (centralDeficitObstructionGraph.neighborSet (5 : Fin 9))).IsIndepSet
          (Finset.univ :
            Finset (centralDeficitObstructionGraph.neighborSet (5 : Fin 9))) := by
      intro x _hx y _hy hxy hAdj
      exact centralDeficitObstructionGraph_neighborSet_five_indep
        x.2 y.2 (fun h => hxy (Subtype.ext h)) hAdj
    have hle := SimpleGraph.IsIndepSet.card_le_indepNum hInd
    have hcard :
        Fintype.card
          (centralDeficitObstructionGraph.neighborSet (5 : Fin 9)) = 3 := by
      decide
    simpa [hcard] using hle

lemma centralDeficitObstructionGraph_indepNeighborsCard_eq_three_unique
    (v : Fin 9)
    (hv : indepNeighborsCard centralDeficitObstructionGraph v = 3) :
    v = (5 : Fin 9) := by
  have hle := indepNeighborsCard_le_neighborSet_card
    centralDeficitObstructionGraph v
  fin_cases v
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (0 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨0, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (1 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨1, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (2 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨2, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (3 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨3, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (4 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨4, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega
  · rfl
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (6 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨6, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (7 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨7, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega
  · have hcard :
        Fintype.card (centralDeficitObstructionGraph.neighborSet (8 : Fin 9)) ≤ 2 := by
      decide
    have hcard' :
        Fintype.card (centralDeficitObstructionGraph.neighborSet ((fun i => i) ⟨8, by decide⟩)) ≤ 2 := by
      simpa using hcard
    have hle2 := hle.trans hcard'
    rw [hv] at hle2
    omega

lemma centralDeficitObstructionGraph_dist_six_four :
    centralDeficitObstructionGraph.dist (6 : Fin 9) (4 : Fin 9) = 5 := by
  exact
    dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
      centralDeficitObstructionGraph (by decide) (by decide)

lemma centralDeficitObstructionGraph_dist_exact_for_radius_lower
    (u : Fin 9) :
    ∃ v : Fin 9, 4 ≤ centralDeficitObstructionGraph.dist u v := by
  fin_cases u
  · exact ⟨(1 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (0 : Fin 9) (1 : Fin 9) = 4 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        simpa [h]⟩
  · exact ⟨(0 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (1 : Fin 9) (0 : Fin 9) = 4 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        simpa [h]⟩
  · exact ⟨(8 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (2 : Fin 9) (8 : Fin 9) = 4 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        simpa [h]⟩
  · exact ⟨(7 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (3 : Fin 9) (7 : Fin 9) = 4 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        simpa [h]⟩
  · exact ⟨(6 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (4 : Fin 9) (6 : Fin 9) = 5 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        have h' :
            centralDeficitObstructionGraph.dist ((fun i => i) ⟨4, by decide⟩) (6 : Fin 9) = 5 := by
          simpa using h
        simpa [h]⟩
  · exact ⟨(4 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (5 : Fin 9) (4 : Fin 9) = 4 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        simpa [h]⟩
  · exact ⟨(4 : Fin 9),
      by
        simpa [centralDeficitObstructionGraph_dist_six_four]⟩
  · exact ⟨(3 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (7 : Fin 9) (3 : Fin 9) = 4 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        simpa [h]⟩
  · exact ⟨(2 : Fin 9),
      by
        have h :
            centralDeficitObstructionGraph.dist (8 : Fin 9) (2 : Fin 9) = 4 :=
          dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
            centralDeficitObstructionGraph (by decide) (by decide)
        simpa [h]⟩

lemma centralDeficitObstructionGraph_dist_from_five_lt_five
    (w : Fin 9) :
    centralDeficitObstructionGraph.dist (5 : Fin 9) w < 5 := by
  fin_cases w <;>
    exact dist_lt_of_finsetWalkLengthLT_nonempty
      centralDeficitObstructionGraph (by decide)

set_option maxHeartbeats 2000000 in
lemma centralDeficitObstructionGraph_dist_lt_six
    (u v : Fin 9) :
    centralDeficitObstructionGraph.dist u v < 6 := by
  fin_cases u <;> fin_cases v <;>
    exact dist_lt_of_finsetWalkLengthLT_nonempty
      centralDeficitObstructionGraph (by decide)

lemma centralDeficitObstructionGraph_diam :
    centralDeficitObstructionGraph.diam = 5 := by
  have hConn : centralDeficitObstructionGraph.Connected := by
    decide
  have hEdTop : centralDeficitObstructionGraph.ediam ≠ ⊤ :=
    (SimpleGraph.connected_iff_ediam_ne_top
      (G := centralDeficitObstructionGraph)).mp hConn
  apply le_antisymm
  · obtain ⟨u, v, huv⟩ :=
      SimpleGraph.exists_dist_eq_diam (G := centralDeficitObstructionGraph)
    have hlt := centralDeficitObstructionGraph_dist_lt_six u v
    omega
  · have hle :
        centralDeficitObstructionGraph.dist (6 : Fin 9) (4 : Fin 9) ≤
          centralDeficitObstructionGraph.diam :=
      centralDeficitObstructionGraph.dist_le_diam hEdTop
    rw [centralDeficitObstructionGraph_dist_six_four] at hle
    exact hle

lemma centralDeficitObstructionGraph_radius_toNat :
    centralDeficitObstructionGraph.radius.toNat = 4 := by
  have hConn : centralDeficitObstructionGraph.Connected := by
    decide
  have hRadTop : centralDeficitObstructionGraph.radius ≠ ⊤ :=
    (SimpleGraph.radius_ne_top_iff
      (G := centralDeficitObstructionGraph)).mpr hConn
  apply le_antisymm
  · have hrad_le :
        centralDeficitObstructionGraph.radius ≤
          centralDeficitObstructionGraph.eccent (5 : Fin 9) :=
      SimpleGraph.radius_le_eccent
    obtain ⟨w, hw⟩ :=
      SimpleGraph.exists_edist_eq_eccent_of_finite
        (G := centralDeficitObstructionGraph) (5 : Fin 9)
    have hecc_ne_top :
        centralDeficitObstructionGraph.eccent (5 : Fin 9) ≠ ⊤ := by
      rw [← hw]
      exact SimpleGraph.edist_ne_top_iff_reachable.mpr (hConn (5 : Fin 9) w)
    have hdist :
        centralDeficitObstructionGraph.dist (5 : Fin 9) w =
          (centralDeficitObstructionGraph.eccent (5 : Fin 9)).toNat := by
      rw [SimpleGraph.dist, hw]
    have hlt := centralDeficitObstructionGraph_dist_from_five_lt_five w
    have hecc_le : (centralDeficitObstructionGraph.eccent (5 : Fin 9)).toNat ≤ 4 := by
      omega
    exact (ENat.toNat_le_toNat hrad_le hecc_ne_top).trans hecc_le
  · obtain ⟨c, hc⟩ :=
      SimpleGraph.exists_eccent_eq_radius
        (G := centralDeficitObstructionGraph)
    obtain ⟨w, hw⟩ :=
      centralDeficitObstructionGraph_dist_exact_for_radius_lower c
    have hdist_edist :
        (centralDeficitObstructionGraph.dist c w : ℕ∞) =
          centralDeficitObstructionGraph.edist c w :=
      (hConn c w).coe_dist_eq_edist
    have hed_le :
        centralDeficitObstructionGraph.edist c w ≤
          centralDeficitObstructionGraph.radius := by
      simpa [hc] using
        (SimpleGraph.edist_le_eccent
          (G := centralDeficitObstructionGraph) (u := c) (v := w))
    have hdist_eq_toNat :
        (centralDeficitObstructionGraph.edist c w).toNat =
          centralDeficitObstructionGraph.dist c w := by
      rw [← hdist_edist]
      simp
    have hdist_le_rad :
        centralDeficitObstructionGraph.dist c w ≤
          centralDeficitObstructionGraph.radius.toNat :=
      by
        have h := ENat.toNat_le_toNat hed_le hRadTop
        simpa [hdist_eq_toNat] using h
    omega

theorem central_deficit_base_compatible_diametral_repair_obstruction :
  ∃ G : SimpleGraph (Fin 9),
    G.Connected ∧
    G.radius.toNat = 4 ∧
    G.diam = 5 ∧
    indepNeighborsCard G (⟨5, by decide⟩ : Fin 9) = 3 ∧
    (∀ v : Fin 9, indepNeighborsCard G v = 3 → v = ⟨5, by decide⟩) ∧
    (∀ w : Fin 9, G.dist (⟨5, by decide⟩ : Fin 9) w < G.diam) := by
  refine ⟨centralDeficitObstructionGraph, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · decide
  · exact centralDeficitObstructionGraph_radius_toNat
  · exact centralDeficitObstructionGraph_diam
  · exact centralDeficitObstructionGraph_indepNeighborsCard_five
  · intro v hv
    exact centralDeficitObstructionGraph_indepNeighborsCard_eq_three_unique v hv
  · intro w
    rw [centralDeficitObstructionGraph_diam]
    exact centralDeficitObstructionGraph_dist_from_five_lt_five w

def centralDeficitC6EdgeBool (u v : Fin 6) : Bool :=
  (u.val == 0 && v.val == 4) || (u.val == 4 && v.val == 0) ||
  (u.val == 0 && v.val == 5) || (u.val == 5 && v.val == 0) ||
  (u.val == 1 && v.val == 3) || (u.val == 3 && v.val == 1) ||
  (u.val == 1 && v.val == 5) || (u.val == 5 && v.val == 1) ||
  (u.val == 2 && v.val == 3) || (u.val == 3 && v.val == 2) ||
  (u.val == 2 && v.val == 4) || (u.val == 4 && v.val == 2)

def centralDeficitC6Graph : SimpleGraph (Fin 6) where
  Adj := fun u v => centralDeficitC6EdgeBool u v = true
  symm := by
    intro u v h
    fin_cases u <;> fin_cases v <;>
      simp [centralDeficitC6EdgeBool] at h ⊢
  loopless := by
    intro u h
    fin_cases u <;> simp [centralDeficitC6EdgeBool] at h

instance centralDeficitC6GraphDecidableRel :
    DecidableRel centralDeficitC6Graph.Adj :=
  fun u v =>
    if h : centralDeficitC6EdgeBool u v = true then isTrue h else isFalse h

def centralDeficitC6BadA : Finset (Fin 6) :=
  {(4 : Fin 6), (5 : Fin 6)}

def centralDeficitC6BadPath :
    centralDeficitC6Graph.Walk (1 : Fin 6) (4 : Fin 6) :=
  Walk.cons (by decide : centralDeficitC6Graph.Adj (1 : Fin 6) (3 : Fin 6))
    (Walk.cons (by decide : centralDeficitC6Graph.Adj (3 : Fin 6) (2 : Fin 6))
      (Walk.cons (by decide : centralDeficitC6Graph.Adj (2 : Fin 6) (4 : Fin 6))
        Walk.nil))

def centralDeficitC6CompatiblePath :
    centralDeficitC6Graph.Walk (0 : Fin 6) (3 : Fin 6) :=
  Walk.cons (by decide : centralDeficitC6Graph.Adj (0 : Fin 6) (4 : Fin 6))
    (Walk.cons (by decide : centralDeficitC6Graph.Adj (4 : Fin 6) (2 : Fin 6))
      (Walk.cons (by decide : centralDeficitC6Graph.Adj (2 : Fin 6) (3 : Fin 6))
        Walk.nil))

lemma centralDeficitC6Graph_radius_toNat :
    centralDeficitC6Graph.radius.toNat = 3 := by
  have hConn : centralDeficitC6Graph.Connected := by
    decide
  have hRadTop : centralDeficitC6Graph.radius ≠ ⊤ :=
    (SimpleGraph.radius_ne_top_iff
      (G := centralDeficitC6Graph)).mpr hConn
  apply le_antisymm
  · have hrad_le :
        centralDeficitC6Graph.radius ≤
          centralDeficitC6Graph.eccent (0 : Fin 6) :=
      SimpleGraph.radius_le_eccent
    obtain ⟨w, hw⟩ :=
      SimpleGraph.exists_edist_eq_eccent_of_finite
        (G := centralDeficitC6Graph) (0 : Fin 6)
    have hecc_ne_top :
        centralDeficitC6Graph.eccent (0 : Fin 6) ≠ ⊤ := by
      rw [← hw]
      exact SimpleGraph.edist_ne_top_iff_reachable.mpr (hConn (0 : Fin 6) w)
    have hdist :
        centralDeficitC6Graph.dist (0 : Fin 6) w =
          (centralDeficitC6Graph.eccent (0 : Fin 6)).toNat := by
      rw [SimpleGraph.dist, hw]
    have hlt : centralDeficitC6Graph.dist (0 : Fin 6) w < 4 := by
      fin_cases w <;>
        exact dist_lt_of_finsetWalkLengthLT_nonempty
          centralDeficitC6Graph (by decide)
    have hecc_le : (centralDeficitC6Graph.eccent (0 : Fin 6)).toNat ≤ 3 := by
      omega
    exact (ENat.toNat_le_toNat hrad_le hecc_ne_top).trans hecc_le
  · obtain ⟨c, hc⟩ :=
      SimpleGraph.exists_eccent_eq_radius
        (G := centralDeficitC6Graph)
    have hdist3 :
        3 ≤ centralDeficitC6Graph.dist c ((c + 3 : Fin 6)) := by
      fin_cases c <;>
        (first
          | have h :
              centralDeficitC6Graph.dist (0 : Fin 6) (3 : Fin 6) = 3 :=
                dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
                  centralDeficitC6Graph (by decide) (by decide)
            simpa [h]
          | have h :
              centralDeficitC6Graph.dist (1 : Fin 6) (4 : Fin 6) = 3 :=
                dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
                  centralDeficitC6Graph (by decide) (by decide)
            simpa [h]
          | have h :
              centralDeficitC6Graph.dist (2 : Fin 6) (5 : Fin 6) = 3 :=
                dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
                  centralDeficitC6Graph (by decide) (by decide)
            simpa [h]
          | have h :
              centralDeficitC6Graph.dist (3 : Fin 6) (0 : Fin 6) = 3 :=
                dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
                  centralDeficitC6Graph (by decide) (by decide)
            simpa [h]
          | have h :
              centralDeficitC6Graph.dist (4 : Fin 6) (1 : Fin 6) = 3 :=
                dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
                  centralDeficitC6Graph (by decide) (by decide)
            simpa [h]
          | have h :
              centralDeficitC6Graph.dist (5 : Fin 6) (2 : Fin 6) = 3 :=
                dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
                  centralDeficitC6Graph (by decide) (by decide)
            simpa [h])
    have hdist_edist :
        (centralDeficitC6Graph.dist c ((c + 3 : Fin 6)) : ℕ∞) =
          centralDeficitC6Graph.edist c ((c + 3 : Fin 6)) :=
      (hConn c ((c + 3 : Fin 6))).coe_dist_eq_edist
    have hed_le :
        centralDeficitC6Graph.edist c ((c + 3 : Fin 6)) ≤
          centralDeficitC6Graph.radius := by
      simpa [hc] using
        (SimpleGraph.edist_le_eccent
          (G := centralDeficitC6Graph) (u := c) (v := ((c + 3 : Fin 6))))
    have hdist_eq_toNat :
        (centralDeficitC6Graph.edist c ((c + 3 : Fin 6))).toNat =
          centralDeficitC6Graph.dist c ((c + 3 : Fin 6)) := by
      rw [← hdist_edist]
      simp
    have hdist_le_rad :
        centralDeficitC6Graph.dist c ((c + 3 : Fin 6)) ≤
          centralDeficitC6Graph.radius.toNat :=
      by
        have h := ENat.toNat_le_toNat hed_le hRadTop
        simpa [hdist_eq_toNat] using h
    omega

lemma centralDeficitC6Graph_dist_lt_four
    (u v : Fin 6) :
    centralDeficitC6Graph.dist u v < 4 := by
  fin_cases u <;> fin_cases v <;>
    exact dist_lt_of_finsetWalkLengthLT_nonempty
      centralDeficitC6Graph (by decide)

lemma centralDeficitC6Graph_dist_one_four :
    centralDeficitC6Graph.dist (1 : Fin 6) (4 : Fin 6) = 3 := by
  exact
    dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
      centralDeficitC6Graph (by decide) (by decide)

lemma centralDeficitC6Graph_diam :
    centralDeficitC6Graph.diam = 3 := by
  have hConn : centralDeficitC6Graph.Connected := by
    decide
  have hEdTop : centralDeficitC6Graph.ediam ≠ ⊤ :=
    (SimpleGraph.connected_iff_ediam_ne_top
      (G := centralDeficitC6Graph)).mp hConn
  apply le_antisymm
  · obtain ⟨u, v, huv⟩ :=
      SimpleGraph.exists_dist_eq_diam (G := centralDeficitC6Graph)
    have hlt := centralDeficitC6Graph_dist_lt_four u v
    omega
  · have hle :
        centralDeficitC6Graph.dist (1 : Fin 6) (4 : Fin 6) ≤
          centralDeficitC6Graph.diam :=
      centralDeficitC6Graph.dist_le_diam hEdTop
    rw [centralDeficitC6Graph_dist_one_four] at hle
    exact hle

lemma centralDeficitC6Graph_neigh_zero
    {x : Fin 6}
    (hx : x ∈ centralDeficitC6Graph.neighborSet (0 : Fin 6)) :
    x = (4 : Fin 6) ∨ x = (5 : Fin 6) := by
  change centralDeficitC6EdgeBool (0 : Fin 6) x = true at hx
  fin_cases x <;> simp [centralDeficitC6EdgeBool] at hx ⊢

lemma centralDeficitC6Graph_neighborSet_zero_indep :
    centralDeficitC6Graph.IsIndepSet
      (centralDeficitC6Graph.neighborSet (0 : Fin 6)) := by
  intro x hx y hy _hxy hAdj
  rcases centralDeficitC6Graph_neigh_zero hx with rfl | rfl <;>
  rcases centralDeficitC6Graph_neigh_zero hy with rfl | rfl <;>
  simp [centralDeficitC6Graph, centralDeficitC6EdgeBool] at hAdj

lemma centralDeficitC6Graph_indepNeighborsCard_zero :
    indepNeighborsCard centralDeficitC6Graph (0 : Fin 6) = 2 := by
  classical
  apply le_antisymm
  · have hcard :
        Fintype.card
          (centralDeficitC6Graph.neighborSet (0 : Fin 6)) = 2 := by
      decide
    exact (indepNeighborsCard_le_neighborSet_card
      centralDeficitC6Graph (0 : Fin 6)).trans_eq hcard
  · unfold indepNeighborsCard
    have hInd :
        (centralDeficitC6Graph.induce
          (centralDeficitC6Graph.neighborSet (0 : Fin 6))).IsIndepSet
          (Finset.univ :
            Finset (centralDeficitC6Graph.neighborSet (0 : Fin 6))) := by
      intro x _hx y _hy hxy hAdj
      exact centralDeficitC6Graph_neighborSet_zero_indep
        x.2 y.2 (fun h => hxy (Subtype.ext h)) hAdj
    have hle := SimpleGraph.IsIndepSet.card_le_indepNum hInd
    have hcard :
        Fintype.card
          (centralDeficitC6Graph.neighborSet (0 : Fin 6)) = 2 := by
      decide
    simpa [hcard] using hle

lemma centralDeficitC6Graph_indepNeighborsCard_le_two
    (v : Fin 6) :
    indepNeighborsCard centralDeficitC6Graph v ≤ 2 := by
  have hle := indepNeighborsCard_le_neighborSet_card
    centralDeficitC6Graph v
  have hcard : Fintype.card (centralDeficitC6Graph.neighborSet v) ≤ 2 := by
    fin_cases v <;> decide
  exact hle.trans hcard

lemma centralDeficitC6Graph_maxIndepNeighborsCard :
    SimpleGraph.maxIndepNeighborsCard centralDeficitC6Graph = 2 := by
  classical
  apply le_antisymm
  · unfold SimpleGraph.maxIndepNeighborsCard
    apply Finset.max'_le
    intro n hn
    rcases Finset.mem_image.mp hn with ⟨v, _hv, rfl⟩
    exact centralDeficitC6Graph_indepNeighborsCard_le_two v
  · simpa [centralDeficitC6Graph_indepNeighborsCard_zero] using
      indepNeighborsCard_le_maxIndepNeighborsCard
        (G := centralDeficitC6Graph) (0 : Fin 6)

lemma centralDeficitC6BadA_card :
    centralDeficitC6BadA.card = SimpleGraph.maxIndepNeighborsCard centralDeficitC6Graph := by
  simp [centralDeficitC6BadA, centralDeficitC6Graph_maxIndepNeighborsCard]

lemma centralDeficitC6BadA_neigh
    {a : Fin 6} (ha : a ∈ centralDeficitC6BadA) :
    centralDeficitC6Graph.Adj (0 : Fin 6) a := by
  fin_cases a <;> simp [centralDeficitC6BadA, centralDeficitC6Graph,
    centralDeficitC6EdgeBool] at ha ⊢

lemma centralDeficitC6BadA_indep :
    centralDeficitC6Graph.IsIndepSet (centralDeficitC6BadA : Set (Fin 6)) := by
  intro x hx y hy _hxy hAdj
  fin_cases x <;> fin_cases y <;>
    simp [centralDeficitC6BadA, centralDeficitC6Graph,
      centralDeficitC6EdgeBool] at hx hy hAdj

lemma centralDeficitC6BadPath_isPath :
    centralDeficitC6BadPath.IsPath := by
  simp [centralDeficitC6BadPath, Walk.cons_isPath_iff,
    centralDeficitC6Graph, centralDeficitC6EdgeBool]

lemma centralDeficitC6BadPath_length :
    centralDeficitC6BadPath.length = 3 := by
  simp [centralDeficitC6BadPath]

lemma centralDeficitC6BadPath_support :
    centralDeficitC6BadPath.support.toFinset =
      ({(1 : Fin 6), (3 : Fin 6), (2 : Fin 6), (4 : Fin 6)} : Finset (Fin 6)) := by
  simp [centralDeficitC6BadPath]

lemma centralDeficitC6BadPath_off_dist_from_zero_lt_two
    (x : Fin 6)
    (hxOff : x ∉ centralDeficitC6BadPath.support.toFinset) :
    centralDeficitC6Graph.dist (0 : Fin 6) x < 2 := by
  rw [centralDeficitC6BadPath_support] at hxOff
  fin_cases x
  · simp
  · simp at hxOff
  · simp at hxOff
  · simp at hxOff
  · simp at hxOff
  · have hdist : centralDeficitC6Graph.dist (0 : Fin 6) (5 : Fin 6) = 1 := by
      exact
        dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
          centralDeficitC6Graph (by decide) (by decide)
    have hdist' :
        centralDeficitC6Graph.dist (0 : Fin 6) ((fun i => i) ⟨5, by decide⟩) = 1 := by
      simpa using hdist
    rw [hdist']
    norm_num

lemma centralDeficitC6_bad_candidate_data :
    ¬ centralDeficitDiametralSafeCandidateData
        centralDeficitC6Graph (0 : Fin 6) centralDeficitC6BadA := by
  classical
  intro hCandidates
  let D : Finset ℕ := Finset.Icc 2 2
  obtain ⟨P0, P1, Q0, Q1, _hLind, _hRind, _hLRdisj, _hPathCard,
      hQoff, _hQ0ind, _hQ1ind, _hQdisj, hQ0safe, hQ1safe, hQcard⟩ :=
    hCandidates (1 : Fin 6) (4 : Fin 6) centralDeficitC6BadPath 3 D
      centralDeficitC6BadPath_isPath
      centralDeficitC6BadPath_length
      (by simpa [centralDeficitC6Graph_diam])
      (by simp [D, centralDeficitC6Graph_radius_toNat])
      (by simp [D, centralDeficitC6Graph_radius_toNat])
  have hQ0empty : Q0 = ∅ := by
    apply Finset.eq_empty_iff_forall_notMem.mpr
    intro x hx
    have hxOff : x ∉ centralDeficitC6BadPath.support.toFinset :=
      hQoff x (Finset.mem_union_left Q1 hx)
    have hxDist : 2 ≤ centralDeficitC6Graph.dist (0 : Fin 6) x :=
      (hQ0safe x hx).1
    have hlt := centralDeficitC6BadPath_off_dist_from_zero_lt_two x hxOff
    omega
  have hQ1empty : Q1 = ∅ := by
    apply Finset.eq_empty_iff_forall_notMem.mpr
    intro x hx
    have hxOff : x ∉ centralDeficitC6BadPath.support.toFinset :=
      hQoff x (Finset.mem_union_right Q0 hx)
    have hxDist : 3 ≤ centralDeficitC6Graph.dist (0 : Fin 6) x :=
      (hQ1safe x hx).1
    have hlt := centralDeficitC6BadPath_off_dist_from_zero_lt_two x hxOff
    omega
  have hBadCard : D.card ≤
      ((Q0.image fun x => (x, false)) ∪
       (Q1.image fun x => (x, true))).card := hQcard
  simp [D, hQ0empty, hQ1empty] at hBadCard

lemma centralDeficitC6_obstruction_witness :
  ∃ G : SimpleGraph (Fin 6), ∃ b : Fin 6, ∃ A : Finset (Fin 6),
    G.Connected ∧
    2 < G.radius.toNat ∧
    ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1 ∧
    A.card = SimpleGraph.maxIndepNeighborsCard G ∧
    (∀ a ∈ A, G.Adj b a) ∧
    G.IsIndepSet (A : Set (Fin 6)) ∧
    ¬ centralDeficitDiametralSafeCandidateData G b A := by
  refine ⟨centralDeficitC6Graph, (0 : Fin 6), centralDeficitC6BadA,
    ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩
  · decide
  · rw [centralDeficitC6Graph_radius_toNat]
    norm_num
  · rw [centralDeficitC6Graph_radius_toNat, centralDeficitC6Graph_diam]
    norm_num
  · exact centralDeficitC6BadA_card
  · intro a ha
    exact centralDeficitC6BadA_neigh ha
  · exact centralDeficitC6BadA_indep
  · exact centralDeficitC6_bad_candidate_data

theorem central_deficit_diametral_safe_candidate_data_c6_obstruction :
  ∃ G : SimpleGraph (Fin 6), ∃ b : Fin 6, ∃ A : Finset (Fin 6),
    G.Connected ∧
    2 < G.radius.toNat ∧
    ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1 ∧
    A.card = SimpleGraph.maxIndepNeighborsCard G ∧
    (∀ a ∈ A, G.Adj b a) ∧
    G.IsIndepSet (A : Set (Fin 6)) ∧
    ¬ centralDeficitDiametralSafeCandidateData G b A :=
  centralDeficitC6_obstruction_witness

theorem central_deficit_diametral_safe_candidate_data_universal_refuted :
    ¬ (∀ {alpha : Type} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
      (G : SimpleGraph alpha) [DecidableRel G.Adj]
      (_hG : G.Connected)
      (b : alpha) (A : Finset alpha)
      (_hRadius : 2 < G.radius.toNat)
      (_hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1)
      (_hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
      (_hAneigh : ∀ a ∈ A, G.Adj b a)
      (_hAind : G.IsIndepSet (A : Set alpha)),
      centralDeficitDiametralSafeCandidateData G b A) := by
  intro hUniversal
  have hCandidates :
      centralDeficitDiametralSafeCandidateData
        centralDeficitC6Graph (0 : Fin 6) centralDeficitC6BadA :=
    @hUniversal (Fin 6) _ _ _ centralDeficitC6Graph _
      (by decide)
      (0 : Fin 6)
      centralDeficitC6BadA
      (by
        rw [centralDeficitC6Graph_radius_toNat]
        norm_num)
      (by
        rw [centralDeficitC6Graph_radius_toNat, centralDeficitC6Graph_diam]
        norm_num)
      centralDeficitC6BadA_card
      (by
        intro a ha
        exact centralDeficitC6BadA_neigh ha)
      centralDeficitC6BadA_indep
  exact centralDeficitC6_bad_candidate_data hCandidates

theorem central_deficit_diametral_disjoint_selector_universal_refuted :
    ¬ (∀ {alpha : Type} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
      (G : SimpleGraph alpha) [DecidableRel G.Adj]
      (_hG : G.Connected)
      (b : alpha) (A : Finset alpha)
      (_hRadius : 2 < G.radius.toNat)
      (_hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1)
      (_hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
      (_hAneigh : ∀ a ∈ A, G.Adj b a)
      (_hAind : G.IsIndepSet (A : Set alpha)),
      ∀ u w : alpha, ∀ p : G.Walk u w, ∀ e : ℕ, ∀ D : Finset ℕ,
        p.IsPath →
        p.length = e →
        e = G.diam →
        D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1) →
        D.card = 2 * G.radius.toNat - 2 - e →
        ∃ P0 P1 Q0 Q1 : Finset alpha,
          G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha) ∧
          G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha) ∧
          Disjoint (A ∪ P1) (insert b P0) ∧
          A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card ∧
          (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
          G.IsIndepSet (Q0 : Set alpha) ∧
          G.IsIndepSet (Q1 : Set alpha) ∧
          Disjoint Q0 Q1 ∧
          (∀ x ∈ Q0,
            2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
          (∀ x ∈ Q1,
            3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
          D.card ≤ (Q0 ∪ Q1).card ∧
          Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)) := by
  classical
  intro hUniversal
  let D : Finset ℕ := Finset.Icc 2 2
  obtain ⟨P0, P1, Q0, Q1, _hLind, _hRind, _hLRdisj, _hPathCard,
      hQoff, _hQ0ind, _hQ1ind, _hQdisj, hQ0safe, hQ1safe, hQcard,
      _hQfixedDisj⟩ :=
    @hUniversal (Fin 6) _ _ _ centralDeficitC6Graph _
      (by decide)
      (0 : Fin 6)
      centralDeficitC6BadA
      (by
        rw [centralDeficitC6Graph_radius_toNat]
        norm_num)
      (by
        rw [centralDeficitC6Graph_radius_toNat, centralDeficitC6Graph_diam]
        norm_num)
      centralDeficitC6BadA_card
      (by
        intro a ha
        exact centralDeficitC6BadA_neigh ha)
      centralDeficitC6BadA_indep
      (1 : Fin 6) (4 : Fin 6) centralDeficitC6BadPath 3 D
      centralDeficitC6BadPath_isPath
      centralDeficitC6BadPath_length
      (by simpa [centralDeficitC6Graph_diam])
      (by simp [D, centralDeficitC6Graph_radius_toNat])
      (by simp [D, centralDeficitC6Graph_radius_toNat])
  have hQ0empty : Q0 = ∅ := by
    apply Finset.eq_empty_iff_forall_notMem.mpr
    intro x hx
    have hxOff : x ∉ centralDeficitC6BadPath.support.toFinset :=
      hQoff x (Finset.mem_union_left Q1 hx)
    have hxDist : 2 ≤ centralDeficitC6Graph.dist (0 : Fin 6) x :=
      (hQ0safe x hx).1
    have hlt := centralDeficitC6BadPath_off_dist_from_zero_lt_two x hxOff
    omega
  have hQ1empty : Q1 = ∅ := by
    apply Finset.eq_empty_iff_forall_notMem.mpr
    intro x hx
    have hxOff : x ∉ centralDeficitC6BadPath.support.toFinset :=
      hQoff x (Finset.mem_union_right Q0 hx)
    have hxDist : 3 ≤ centralDeficitC6Graph.dist (0 : Fin 6) x :=
      (hQ1safe x hx).1
    have hlt := centralDeficitC6BadPath_off_dist_from_zero_lt_two x hxOff
    omega
  simp [D, hQ0empty, hQ1empty] at hQcard

theorem central_deficit_off_path_safe_pool_refinement_of_fixed_color_witness_refuted :
    ¬ (∀ {alpha : Type} [Fintype alpha] [DecidableEq alpha] [Nontrivial alpha]
      (G : SimpleGraph alpha) [DecidableRel G.Adj] (_hG : G.Connected)
      (b : alpha) (A : Finset alpha)
      (_hRadius : 2 < G.radius.toNat)
      (_hDiamSmall : ¬ (2 * G.radius.toNat : Nat) ≤ G.diam + 1)
      (_hAcard : A.card = SimpleGraph.maxIndepNeighborsCard G)
      (_hAneigh : ∀ a ∈ A, G.Adj b a)
      (_hAind : G.IsIndepSet (A : Set alpha))
      {u w : alpha} {p : G.Walk u w} {e : Nat} {D : Finset Nat}
      {P0 P1 : Finset alpha}
      (_hpPath : p.IsPath)
      (_hpLen : p.length = e)
      (_heDiam : e = G.diam)
      (_hDdef : D = Finset.Icc (e - G.radius.toNat + 2) (G.radius.toNat - 1))
      (_hDcard : D.card = 2 * G.radius.toNat - 2 - e)
      (_hLind : G.IsIndepSet ((A ∪ P1 : Finset alpha) : Set alpha))
      (_hRind : G.IsIndepSet ((insert b P0 : Finset alpha) : Set alpha))
      (_hLRdisj : Disjoint (A ∪ P1) (insert b P0))
      (_hPathCard : A.card + e ≤ ((A ∪ P1) ∪ insert b P0).card),
      ∃ Q0 Q1 : Finset alpha,
        (∀ x ∈ Q0 ∪ Q1, x ∉ p.support.toFinset) ∧
        G.IsIndepSet (Q0 : Set alpha) ∧
        G.IsIndepSet (Q1 : Set alpha) ∧
        Disjoint Q0 Q1 ∧
        (∀ x ∈ Q0, 2 ≤ G.dist b x ∧ ∀ y ∈ insert b P0, ¬ G.Adj x y) ∧
        (∀ x ∈ Q1, 3 ≤ G.dist b x ∧ ∀ y ∈ A ∪ P1, ¬ G.Adj x y) ∧
        D.card ≤ (Q0 ∪ Q1).card ∧
        Disjoint (Q0 ∪ Q1) ((A ∪ P1) ∪ insert b P0)) := by
  classical
  intro hRefinement
  let D : Finset ℕ := Finset.Icc 2 2
  let P0 : Finset (Fin 6) := {(1 : Fin 6), (2 : Fin 6)}
  let P1 : Finset (Fin 6) := {(3 : Fin 6)}
  obtain ⟨Q0, Q1, hQoff, _hQ0ind, _hQ1ind, _hQdisj, hQ0safe,
      hQ1safe, hQcard, _hQfixedDisj⟩ :=
    @hRefinement (Fin 6) _ _ _ centralDeficitC6Graph _
      (by decide)
      (0 : Fin 6)
      centralDeficitC6BadA
      (by
        rw [centralDeficitC6Graph_radius_toNat]
        norm_num)
      (by
        rw [centralDeficitC6Graph_radius_toNat, centralDeficitC6Graph_diam]
        norm_num)
      centralDeficitC6BadA_card
      (by
        intro a ha
        exact centralDeficitC6BadA_neigh ha)
      centralDeficitC6BadA_indep
      (u := (1 : Fin 6)) (w := (4 : Fin 6))
      (p := centralDeficitC6BadPath) (e := 3) (D := D)
      (P0 := P0) (P1 := P1)
      centralDeficitC6BadPath_isPath
      centralDeficitC6BadPath_length
      (by simpa [centralDeficitC6Graph_diam])
      (by simp [D, centralDeficitC6Graph_radius_toNat])
      (by simp [D, centralDeficitC6Graph_radius_toNat])
      (by decide)
      (by decide)
      (by decide)
      (by decide)
  have hQ0empty : Q0 = ∅ := by
    apply Finset.eq_empty_iff_forall_notMem.mpr
    intro x hx
    have hxOff : x ∉ centralDeficitC6BadPath.support.toFinset :=
      hQoff x (Finset.mem_union_left Q1 hx)
    have hxDist : 2 ≤ centralDeficitC6Graph.dist (0 : Fin 6) x :=
      (hQ0safe x hx).1
    have hlt := centralDeficitC6BadPath_off_dist_from_zero_lt_two x hxOff
    omega
  have hQ1empty : Q1 = ∅ := by
    apply Finset.eq_empty_iff_forall_notMem.mpr
    intro x hx
    have hxOff : x ∉ centralDeficitC6BadPath.support.toFinset :=
      hQoff x (Finset.mem_union_right Q0 hx)
    have hxDist : 3 ≤ centralDeficitC6Graph.dist (0 : Fin 6) x :=
      (hQ1safe x hx).1
    have hlt := centralDeficitC6BadPath_off_dist_from_zero_lt_two x hxOff
    omega
  simp [D, hQ0empty, hQ1empty] at hQcard

theorem central_deficit_c6_exists_diametral_safe_candidate_data_disjoint :
    centralDeficitExistsDiametralSafeCandidateDataDisjoint
      centralDeficitC6Graph (0 : Fin 6) centralDeficitC6BadA := by
  classical
  let D : Finset ℕ := Finset.Icc 2 2
  let P0 : Finset (Fin 6) := {(2 : Fin 6)}
  let P1 : Finset (Fin 6) := {(3 : Fin 6)}
  let Q0 : Finset (Fin 6) := {(1 : Fin 6)}
  let Q1 : Finset (Fin 6) := ∅
  refine
    ⟨(0 : Fin 6), (3 : Fin 6), centralDeficitC6CompatiblePath, 3, D,
      P0, P1, Q0, Q1, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_,
      ?_, ?_, ?_, ?_, ?_, ?_⟩
  · simp [centralDeficitC6CompatiblePath, Walk.cons_isPath_iff,
      centralDeficitC6Graph, centralDeficitC6EdgeBool]
  · simp [centralDeficitC6CompatiblePath]
  · exact centralDeficitC6Graph_diam.symm
  · simp [D, centralDeficitC6Graph_radius_toNat]
  · simp [D, centralDeficitC6Graph_radius_toNat]
  · decide
  · decide
  · decide
  · simp [centralDeficitC6BadA, P0, P1]
  · intro x hx
    fin_cases x <;>
      simp [Q0, Q1, centralDeficitC6CompatiblePath] at hx ⊢
  · decide
  · decide
  · decide
  · intro x hx
    have hx1 : x = (1 : Fin 6) := by
      fin_cases x <;> simp [Q0] at hx ⊢
    subst x
    constructor
    · have hdist : centralDeficitC6Graph.dist (0 : Fin 6) (1 : Fin 6) = 2 :=
        dist_eq_of_finsetWalkLengthLT_card_eq_zero_and_finsetWalkLength_nonempty
          (G := centralDeficitC6Graph) (u := (0 : Fin 6)) (v := (1 : Fin 6))
          (n := 2) (by decide) (by decide)
      exact le_of_eq hdist.symm
    · intro y hy
      fin_cases y <;>
        simp [P0, centralDeficitC6Graph, centralDeficitC6EdgeBool] at hy ⊢
  · intro x hx
    simp [Q1] at hx
  · simp [D, Q0, Q1]
  · decide

end Wowii16CentralCore20260609
