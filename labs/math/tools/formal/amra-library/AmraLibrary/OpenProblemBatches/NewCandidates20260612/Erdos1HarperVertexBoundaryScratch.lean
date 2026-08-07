import Mathlib.Data.Fin.Basic
import Mathlib.Data.Finset.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Data.Finset.Filter
import Mathlib.Data.Fintype.Defs
import Mathlib.Data.Fintype.Powerset
import Mathlib.Data.Nat.Choose.Bounds
import Mathlib.Data.Nat.EvenOddRec
import Mathlib.Data.Nat.Choose.Sum
import Mathlib.Tactic

/-!
Scratch target for the Erdos1 Harper/vertex-boundary route.

This file intentionally imports only Mathlib and does not import the local
`ErdosProblems/1.lean` file, whose current route still contains unrelated
open declarations. The campaign should prove or package the half-cube external
vertex-boundary specialization here first, then transfer it back to Erdos1.
-/

private lemma central_binomial_le_cube_card (n : Nat) :
    Nat.choose n (n / 2) <= 2 ^ n :=
  Nat.choose_le_two_pow n (n / 2)

private lemma card_univ_filter_card_le (n k : Nat) :
    ((Finset.univ : Finset (Finset (Fin n))).filter fun s => s.card <= k).card =
      ∑ i ∈ Finset.range (k + 1), Nat.choose n i := by
  classical
  have h := Finset.sum_card_fiberwise_eq_card_filter
    (s := (Finset.univ : Finset (Finset (Fin n))))
    (t := Finset.range (k + 1)) (g := fun s : Finset (Fin n) => s.card)
  calc
    ((Finset.univ : Finset (Finset (Fin n))).filter fun s => s.card <= k).card =
        ((Finset.univ : Finset (Finset (Fin n))).filter
          fun s => s.card ∈ Finset.range (k + 1)).card := by
      congr 1
      ext s
      simp [Nat.lt_succ_iff]
    _ = ∑ i ∈ Finset.range (k + 1), Nat.choose n i := by
      rw [← h]
      congr 1
      ext i
      simp [Finset.univ_filter_card_eq]

private lemma card_powerset_filter_card_le {α : Type*} [DecidableEq α]
    (U : Finset α) (k : Nat) :
    (U.powerset.filter fun s => s.card <= k).card =
      ∑ i ∈ Finset.range (k + 1), Nat.choose U.card i := by
  classical
  have h := Finset.sum_card_fiberwise_eq_card_filter
    (s := U.powerset) (t := Finset.range (k + 1))
    (g := fun s : Finset α => s.card)
  calc
    (U.powerset.filter fun s => s.card <= k).card =
        (U.powerset.filter fun s => s.card ∈ Finset.range (k + 1)).card := by
      congr 1
      ext s
      simp [Nat.lt_succ_iff]
    _ = ∑ i ∈ Finset.range (k + 1), Nat.choose U.card i := by
      rw [← h]
      congr 1
      ext i
      rw [← Finset.powersetCard_eq_filter]
      simp

private lemma card_univ_filter_card_le_and_not_mem {n : Nat} (a : Fin n) (k : Nat) :
    ((Finset.univ : Finset (Finset (Fin n))).filter
      fun s => s.card <= k ∧ a ∉ s).card =
      ∑ i ∈ Finset.range (k + 1), Nat.choose (n - 1) i := by
  classical
  let U : Finset (Fin n) := (Finset.univ : Finset (Fin n)).erase a
  have hUcard : U.card = n - 1 := by
    simp [U, Finset.card_erase_of_mem]
  have hset :
      ((Finset.univ : Finset (Finset (Fin n))).filter
        fun s => s.card <= k ∧ a ∉ s) =
        U.powerset.filter fun s => s.card <= k := by
    ext s
    simp [U, Finset.mem_powerset]
    constructor
    · rintro ⟨hcard, ha⟩
      refine ⟨?_, hcard⟩
      intro x hx
      exact Finset.mem_erase.mpr
        ⟨by intro hxa; exact ha (by simpa [hxa] using hx), Finset.mem_univ x⟩
    · intro h
      exact ⟨h.2, by
        intro ha
        exact (Finset.mem_erase.mp (h.1 ha)).1 rfl⟩
  rw [hset, card_powerset_filter_card_le, hUcard]

private lemma card_univ_filter_card_le_succ_and_mem {n : Nat} (a : Fin n) (k : Nat) :
    ((Finset.univ : Finset (Finset (Fin n))).filter
      fun s => s.card <= k + 1 ∧ a ∈ s).card =
      ∑ i ∈ Finset.range (k + 1), Nat.choose (n - 1) i := by
  classical
  let U : Finset (Fin n) := (Finset.univ : Finset (Fin n)).erase a
  have hUcard : U.card = n - 1 := by
    simp [U, Finset.card_erase_of_mem]
  have hset :
      ((Finset.univ : Finset (Finset (Fin n))).filter
        fun s => s.card <= k + 1 ∧ a ∈ s) =
        (U.powerset.filter fun u => u.card <= k).image (fun u => insert a u) := by
    ext s
    simp only [Finset.mem_filter, Finset.mem_univ, true_and, Finset.mem_image,
      Finset.mem_powerset]
    constructor
    · rintro ⟨hcard, ha⟩
      refine ⟨s.erase a, ?_, Finset.insert_erase ha⟩
      constructor
      · intro x hx
        exact Finset.mem_erase.mpr ⟨(Finset.mem_erase.mp hx).1, Finset.mem_univ x⟩
      · rw [Finset.card_erase_of_mem ha]
        omega
    · rintro ⟨u, ⟨huU, hucard⟩, rfl⟩
      have hau : a ∉ u := by
        intro hau
        have := huU hau
        simp [U] at this
      constructor
      · rw [Finset.card_insert_of_notMem hau]
        omega
      · exact Finset.mem_insert_self _ _
  rw [hset, Finset.card_image_of_injOn]
  · rw [card_powerset_filter_card_le, hUcard]
  · intro u hu v hv huv
    have hu' : u ∈ U.powerset.filter (fun u => u.card <= k) := by simpa using hu
    have hv' : v ∈ U.powerset.filter (fun u => u.card <= k) := by simpa using hv
    have hau : a ∉ u := by
      intro hau
      have hmemU := (Finset.mem_powerset.mp (Finset.mem_filter.mp hu').1) hau
      exact (Finset.mem_erase.mp hmemU).1 rfl
    have hav : a ∉ v := by
      intro hav
      have hmemU := (Finset.mem_powerset.mp (Finset.mem_filter.mp hv').1) hav
      exact (Finset.mem_erase.mp hmemU).1 rfl
    simpa [Finset.erase_insert hau, Finset.erase_insert hav] using
      congrArg (fun s => s.erase a) huv

private def booleanVertexBoundary (n : Nat) (A : Finset (Finset (Fin n))) :
    Finset (Finset (Fin n)) :=
  Finset.univ.filter fun t : Finset (Fin n) =>
    t ∉ A ∧ ∃ s ∈ A,
      ((s ⊆ t ∧ t.card = s.card + 1) ∨
       (t ⊆ s ∧ s.card = t.card + 1))

private lemma disjoint_booleanVertexBoundary
    (n : Nat) (A : Finset (Finset (Fin n))) :
    Disjoint A (booleanVertexBoundary n A) := by
  classical
  rw [Finset.disjoint_left]
  intro t htA htB
  exact (Finset.mem_filter.mp htB).2.1 htA

private lemma booleanClosedNeighborhood_card
    (n : Nat) (A : Finset (Finset (Fin n))) :
    (A ∪ booleanVertexBoundary n A).card =
      A.card + (booleanVertexBoundary n A).card := by
  classical
  exact Finset.card_union_of_disjoint (disjoint_booleanVertexBoundary n A)

private def booleanHalfInitialSegment (n : Nat) (hn : 0 < n) :
    Finset (Finset (Fin n)) :=
  Finset.univ.filter fun s =>
    if n % 2 = 1 then
      s.card <= n / 2
    else
      s.card < n / 2 ∨
        (s.card = n / 2 ∧ (⟨0, hn⟩ : Fin n) ∈ s)

private lemma booleanHalfInitialSegment_closedNeighborhood_odd
    (m : Nat) (hn : 0 < 2 * m + 1) :
    (booleanHalfInitialSegment (2 * m + 1) hn ∪
      booleanVertexBoundary (2 * m + 1) (booleanHalfInitialSegment (2 * m + 1) hn)) =
      Finset.univ.filter (fun t : Finset (Fin (2 * m + 1)) => t.card <= m + 1) := by
  classical
  ext t
  simp [booleanVertexBoundary, booleanHalfInitialSegment]
  constructor
  · intro h
    rcases h with ht | h
    · omega
    · rcases h with ⟨_htH, s, hsH, hsadj⟩
      rcases hsadj with ⟨_hst, hcard⟩ | ⟨hts, _hcard⟩
      · omega
      · have htcard_le : t.card <= s.card := Finset.card_le_card hts
        omega
  · intro ht
    by_cases htH : t.card <= m
    · exact Or.inl (by omega)
    · right
      have htc : t.card = m + 1 := by omega
      have hne : t.Nonempty := Finset.card_pos.mp (by omega)
      refine ⟨?_, t.erase (t.min' hne), ?_, ?_⟩
      · omega
      · have hminmem : t.min' hne ∈ t := Finset.min'_mem _ _
        have hcarderase : (t.erase (t.min' hne)).card = m := by
          rw [Finset.card_erase_of_mem hminmem, htc]
          omega
        omega
      · left
        constructor
        · exact Finset.erase_subset _ _
        · have hminmem : t.min' hne ∈ t := Finset.min'_mem _ _
          rw [Finset.card_erase_of_mem hminmem, htc]
          omega

private lemma booleanHalfInitialSegment_closedNeighborhood_odd_card
    (m : Nat) (hn : 0 < 2 * m + 1) :
    ((booleanHalfInitialSegment (2 * m + 1) hn) ∪
      booleanVertexBoundary (2 * m + 1)
        (booleanHalfInitialSegment (2 * m + 1) hn)).card =
      2 ^ (2 * m) + Nat.choose (2 * m + 1) m := by
  rw [booleanHalfInitialSegment_closedNeighborhood_odd m hn]
  rw [card_univ_filter_card_le]
  rw [Finset.sum_range_succ]
  rw [Nat.sum_range_choose_halfway]
  rw [Nat.choose_symm_half]
  rw [show 4 ^ m = 2 ^ (2 * m) by
    rw [show (4 : Nat) = 2 ^ 2 by norm_num, pow_mul]]

private lemma booleanHalfInitialSegment_closedNeighborhood_even
    (m : Nat) (hn : 0 < 2 * m) :
    (booleanHalfInitialSegment (2 * m) hn ∪
      booleanVertexBoundary (2 * m) (booleanHalfInitialSegment (2 * m) hn)) =
      Finset.univ.filter (fun t : Finset (Fin (2 * m)) =>
        t.card <= m ∨ (t.card = m + 1 ∧ (⟨0, hn⟩ : Fin (2 * m)) ∈ t)) := by
  classical
  let a : Fin (2 * m) := ⟨0, hn⟩
  have hmpos : 0 < m := by omega
  ext t
  simp [booleanVertexBoundary, booleanHalfInitialSegment]
  constructor
  · intro h
    rcases h with htH | hB
    · rcases htH with hlt | ⟨heq, _ha⟩
      · exact Or.inl (by omega)
      · exact Or.inl (by omega)
    · rcases hB with ⟨_htH, s, hsH, hsadj⟩
      rcases hsH with hslt | ⟨hseq, hsa⟩
      · rcases hsadj with ⟨_hst, hcard⟩ | ⟨hts, _hcard⟩
        · exact Or.inl (by omega)
        · have htcard_le : t.card <= s.card := Finset.card_le_card hts
          exact Or.inl (by omega)
      · rcases hsadj with ⟨hst, hcard⟩ | ⟨hts, _hcard⟩
        · exact Or.inr ⟨by omega, hst hsa⟩
        · have htcard_le : t.card <= s.card := Finset.card_le_card hts
          exact Or.inl (by omega)
  · intro ht
    rcases ht with ht_le | ⟨htc_succ, hta⟩
    · by_cases htlt : t.card < m
      · exact Or.inl (Or.inl htlt)
      · have htc : t.card = m := by omega
        by_cases hta : a ∈ t
        · exact Or.inl (Or.inr ⟨htc, hta⟩)
        · right
          have hne : t.Nonempty := Finset.card_pos.mp (by omega)
          refine ⟨?_, t.erase (t.min' hne), ?_, ?_⟩
          · constructor
            · omega
            · intro _h
              exact hta
          · left
            have hminmem : t.min' hne ∈ t := Finset.min'_mem _ _
            rw [Finset.card_erase_of_mem hminmem, htc]
            omega
          · left
            constructor
            · exact Finset.erase_subset _ _
            · have hminmem : t.min' hne ∈ t := Finset.min'_mem _ _
              rw [Finset.card_erase_of_mem hminmem, htc]
              omega
    · right
      have ht_not_H : m <= t.card ∧ (t.card = m → (⟨0, hn⟩ : Fin (2 * m)) ∉ t) := by
        constructor
        · omega
        · intro htc
          omega
      have h_erase_a_card : (t.erase a).card = m := by
        rw [Finset.card_erase_of_mem hta, htc_succ]
        omega
      have h_erase_a_ne : (t.erase a).Nonempty := Finset.card_pos.mp (by omega)
      let b : Fin (2 * m) := (t.erase a).min' h_erase_a_ne
      have hb_erase : b ∈ t.erase a := Finset.min'_mem _ _
      have hbt : b ∈ t := (Finset.mem_erase.mp hb_erase).2
      have hba : b ≠ a := by
        exact (Finset.mem_erase.mp hb_erase).1
      refine ⟨ht_not_H, t.erase b, ?_, ?_⟩
      · right
        constructor
        · rw [Finset.card_erase_of_mem hbt, htc_succ]
          omega
        · exact Finset.mem_erase.mpr ⟨by simpa [a] using hba.symm, hta⟩
      · left
        constructor
        · exact Finset.erase_subset _ _
        · rw [Finset.card_erase_of_mem hbt, htc_succ]
          omega

private lemma booleanHalfInitialSegment_closedNeighborhood_even_card
    (m : Nat) (hn : 0 < 2 * m) :
    ((booleanHalfInitialSegment (2 * m) hn) ∪
      booleanVertexBoundary (2 * m) (booleanHalfInitialSegment (2 * m) hn)).card =
      2 ^ (2 * m - 1) + Nat.choose (2 * m) m := by
  classical
  let a : Fin (2 * m) := ⟨0, hn⟩
  have hmpos : 0 < m := by omega
  have hsplit :
      ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
        fun t => t.card <= m ∨ (t.card = m + 1 ∧ a ∈ t)) =
      ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
        fun t => t.card <= m ∧ a ∉ t) ∪
      ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
        fun t => t.card <= m + 1 ∧ a ∈ t) := by
    ext t
    by_cases hta : a ∈ t
    · simp [hta]
      omega
    · simp [hta]
  have hdisj :
      Disjoint
        ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
          fun t => t.card <= m ∧ a ∉ t)
        ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
          fun t => t.card <= m + 1 ∧ a ∈ t) := by
    rw [Finset.disjoint_left]
    intro t ht1 ht2
    exact (Finset.mem_filter.mp ht1).2.2 (Finset.mem_filter.mp ht2).2.2
  have hsum :
      (∑ i ∈ Finset.range (m + 1), Nat.choose (2 * m - 1) i) =
        4 ^ (m - 1) + Nat.choose (2 * m - 1) m := by
    calc
      (∑ i ∈ Finset.range (m + 1), Nat.choose (2 * m - 1) i) =
          ∑ i ∈ Finset.range ((m - 1) + 1 + 1),
            Nat.choose (2 * (m - 1) + 1) i := by
        rw [show m + 1 = (m - 1) + 1 + 1 by omega,
          show 2 * m - 1 = 2 * (m - 1) + 1 by omega]
      _ = (∑ i ∈ Finset.range ((m - 1) + 1),
            Nat.choose (2 * (m - 1) + 1) i) +
            Nat.choose (2 * (m - 1) + 1) ((m - 1) + 1) := by
        rw [Finset.sum_range_succ]
      _ = 4 ^ (m - 1) + Nat.choose (2 * (m - 1) + 1) ((m - 1) + 1) := by
        rw [Nat.sum_range_choose_halfway]
      _ = 4 ^ (m - 1) + Nat.choose (2 * m - 1) m := by
        congr 2 <;> omega
  have hchoose :
      Nat.choose (2 * m) m = 2 * Nat.choose (2 * m - 1) m := by
    have hsym :
        Nat.choose (2 * m - 1) (m - 1) = Nat.choose (2 * m - 1) m := by
      apply Nat.choose_symm_of_eq_add
      omega
    calc
      Nat.choose (2 * m) m =
          Nat.choose ((2 * m - 1) + 1) ((m - 1) + 1) := by
        congr <;> omega
      _ = Nat.choose (2 * m - 1) (m - 1) +
          Nat.choose (2 * m - 1) ((m - 1) + 1) := by
        rw [Nat.choose_succ_succ']
      _ = 2 * Nat.choose (2 * m - 1) m := by
        rw [show (m - 1) + 1 = m by omega, hsym]
        ring
  have hpow : 2 * 4 ^ (m - 1) = 2 ^ (2 * m - 1) := by
    calc
      2 * 4 ^ (m - 1) = 2 * (2 ^ (2 * (m - 1))) := by
        rw [show (4 : Nat) = 2 ^ 2 by norm_num, pow_mul]
      _ = 2 ^ (2 * (m - 1) + 1) := by
        rw [pow_succ]
        ring
      _ = 2 ^ (2 * m - 1) := by
        congr 1
        omega
  rw [booleanHalfInitialSegment_closedNeighborhood_even m hn]
  rw [hsplit, Finset.card_union_of_disjoint hdisj]
  rw [card_univ_filter_card_le_and_not_mem, card_univ_filter_card_le_succ_and_mem]
  rw [hsum, hchoose, ← hpow]
  ring

private lemma booleanHalfInitialSegment_card_odd
    (m : Nat) (hn : 0 < 2 * m + 1) :
    (booleanHalfInitialSegment (2 * m + 1) hn).card = 2 ^ (2 * m) := by
  rw [booleanHalfInitialSegment]
  simp
  rw [card_univ_filter_card_le]
  rw [show (2 * m + 1) / 2 = m by omega]
  rw [Nat.sum_range_choose_halfway]
  rw [show 4 ^ m = 2 ^ (2 * m) by
    rw [show (4 : Nat) = 2 ^ 2 by norm_num, pow_mul]]

private lemma booleanHalfInitialSegment_card_even
    (m : Nat) (hn : 0 < 2 * m) :
    (booleanHalfInitialSegment (2 * m) hn).card = 2 ^ (2 * m - 1) := by
  classical
  let a : Fin (2 * m) := ⟨0, hn⟩
  have hmpos : 0 < m := by omega
  have hsplit :
      booleanHalfInitialSegment (2 * m) hn =
      ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
        fun t => t.card <= m - 1 ∧ a ∉ t) ∪
      ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
        fun t => t.card <= (m - 1) + 1 ∧ a ∈ t) := by
    ext t
    rw [booleanHalfInitialSegment]
    by_cases hta : a ∈ t
    · simp [a, hta]
      omega
    · simp [a, hta]
      omega
  have hdisj :
      Disjoint
        ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
          fun t => t.card <= m - 1 ∧ a ∉ t)
        ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
          fun t => t.card <= (m - 1) + 1 ∧ a ∈ t) := by
    rw [Finset.disjoint_left]
    intro t ht1 ht2
    exact (Finset.mem_filter.mp ht1).2.2 (Finset.mem_filter.mp ht2).2.2
  have hpow : 2 * 4 ^ (m - 1) = 2 ^ (2 * m - 1) := by
    calc
      2 * 4 ^ (m - 1) = 2 * (2 ^ (2 * (m - 1))) := by
        rw [show (4 : Nat) = 2 ^ 2 by norm_num, pow_mul]
      _ = 2 ^ (2 * (m - 1) + 1) := by
        rw [pow_succ]
        ring
      _ = 2 ^ (2 * m - 1) := by
        congr 1
        omega
  have hsum :
      (∑ i ∈ Finset.range (m - 1 + 1), Nat.choose (2 * m - 1) i) =
        4 ^ (m - 1) := by
    calc
      (∑ i ∈ Finset.range (m - 1 + 1), Nat.choose (2 * m - 1) i) =
          ∑ i ∈ Finset.range ((m - 1) + 1),
            Nat.choose (2 * (m - 1) + 1) i := by
        rw [show 2 * m - 1 = 2 * (m - 1) + 1 by omega]
      _ = 4 ^ (m - 1) := by
        rw [Nat.sum_range_choose_halfway]
  rw [hsplit, Finset.card_union_of_disjoint hdisj]
  rw [card_univ_filter_card_le_and_not_mem, card_univ_filter_card_le_succ_and_mem]
  rw [hsum, ← hpow]
  ring

theorem booleanHalfInitialSegment_card
    (n : Nat) (hn : 0 < n) :
    (booleanHalfInitialSegment n hn).card = 2 ^ (n - 1) := by
  revert hn
  induction n using Nat.evenOddRec with
  | h0 =>
      intro hn
      omega
  | h_even m _ih =>
      intro hn
      simpa using booleanHalfInitialSegment_card_even m hn
  | h_odd m _ih =>
      intro hn
      simpa using booleanHalfInitialSegment_card_odd m hn

theorem boolean_halfInitialSegment_closedNeighborhood_card
    (n : Nat) (hn : 0 < n) :
    ((booleanHalfInitialSegment n hn) ∪
      booleanVertexBoundary n (booleanHalfInitialSegment n hn)).card =
    2 ^ (n - 1) + Nat.choose n (n / 2) := by
  revert hn
  induction n using Nat.evenOddRec with
  | h0 =>
      intro hn
      omega
  | h_even m _ih =>
      intro hn
      simpa [show (2 * m) / 2 = m by omega] using
        booleanHalfInitialSegment_closedNeighborhood_even_card m hn
  | h_odd m _ih =>
      intro hn
      simpa [show (2 * m + 1) / 2 = m by omega] using
        booleanHalfInitialSegment_closedNeighborhood_odd_card m hn

private theorem boolean_boundary_card_ge_middle_of_closed_neighborhood
    (n : Nat) (A : Finset (Finset (Fin n)))
    (hcard : A.card = 2 ^ (n - 1))
    (hclosed :
      2 ^ (n - 1) + Nat.choose n (n / 2) <=
        (A ∪ booleanVertexBoundary n A).card) :
    Nat.choose n (n / 2) <= (booleanVertexBoundary n A).card := by
  have hsum :
      2 ^ (n - 1) + Nat.choose n (n / 2) <=
        A.card + (booleanVertexBoundary n A).card := by
    simpa [booleanClosedNeighborhood_card n A] using hclosed
  have hsum' :
      2 ^ (n - 1) + Nat.choose n (n / 2) <=
        2 ^ (n - 1) + (booleanVertexBoundary n A).card := by
    simpa [hcard] using hsum
  exact Nat.add_le_add_iff_left.mp hsum'

/-!
Constant-scale weighted source route:
the proof-lab audit identified the theorem below as the first missing
mathematical input for the original `erdos_1` target.  The local declaration
records the exact Lean proposition that would be needed, but it does not assert
the proposition; the only proved fact is the proof-neutral contract `P -> P`.
-/

private def erdos1WeightedDichotomySourceStatement : Prop :=
  ∃ c : ℚ, 0 < c ∧
    ∀ n : Nat, 0 < n → ∀ w : Fin n → Nat,
      (∀ i : Fin n, 0 < w i) →
      Function.Injective (fun s : Finset (Fin n) => ∑ i ∈ s, w i) →
      ∃ i : Fin n, c * (2 : ℚ) ^ n ≤ (w i : ℚ)

lemma erdos1_constant_scale_weighted_dichotomy_source :
    erdos1WeightedDichotomySourceStatement →
      erdos1WeightedDichotomySourceStatement := by
  intro hsource
  exact hsource

/-!
Subexponential modular-escape route:
the replacement route proposed by proof-lab would need a fixed `δ > 0` such
that every positive injective subset-sum weight system admits a modulus
`q = 2^n + t`, with `t < (2 - δ)^n`, for which subset sums remain injective
modulo `q`.  No admissible source for this package is present in the supplied
context, so the checked theorem below records the source-or-obstruction split
without asserting the missing source statement.
-/

private def erdos1SubexponentialModularEscapeSourceStatement : Prop :=
  ∃ δ : ℚ, 0 < δ ∧ δ < 1 ∧
    ∀ n : Nat, 0 < n → ∀ w : Fin n → Nat,
      (∀ i : Fin n, 0 < w i) →
      Function.Injective (fun s : Finset (Fin n) => ∑ i ∈ s, w i) →
      ∃ t : Nat,
        (t : ℚ) < ((2 : ℚ) - δ) ^ n ∧
          Function.Injective
            (fun s : Finset (Fin n) => (∑ i ∈ s, w i) % (2 ^ n + t))

lemma erdos1_subexponential_modular_escape_source_or_obstruction :
    erdos1SubexponentialModularEscapeSourceStatement ∨
      ¬ erdos1SubexponentialModularEscapeSourceStatement := by
  classical
  exact em erdos1SubexponentialModularEscapeSourceStatement

/-!
Remaining source route:
Raty, arXiv:1806.11061, restates Harper's closed-neighborhood minimization for
the Boolean cube in simplicial order. The intended Lean transfer also uses the
half-initial-segment count described in Przykucki--Roberts, arXiv:1808.02572.

The exact pending source declaration is
`harper_boolean_halfInitialSegment_minimizes_closedNeighborhood_source`.  Its
proof obligation is Harper's minimization theorem for the local
`booleanHalfInitialSegment`; the declarations below only compose that theorem
with the already checked half-segment cardinal calculation.
-/

private theorem boolean_half_family_closedNeighborhood_card_ge_middle_of_halfInitialSegment
    (n : Nat) (hn : 0 < n) (A : Finset (Finset (Fin n)))
    (_hcard : A.card = 2 ^ (n - 1))
    (hmin :
      ((booleanHalfInitialSegment n hn) ∪
          booleanVertexBoundary n (booleanHalfInitialSegment n hn)).card <=
        (A ∪ booleanVertexBoundary n A).card)
    (hsegment :
      2 ^ (n - 1) + Nat.choose n (n / 2) <=
        ((booleanHalfInitialSegment n hn) ∪
          booleanVertexBoundary n (booleanHalfInitialSegment n hn)).card) :
    2 ^ (n - 1) + Nat.choose n (n / 2) <=
      (A ∪ booleanVertexBoundary n A).card := by
  exact le_trans hsegment hmin
