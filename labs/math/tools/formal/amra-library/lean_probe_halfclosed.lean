import Mathlib.Data.Fin.Basic
import Mathlib.Data.Finset.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Data.Finset.Filter
import Mathlib.Data.Fintype.Defs
import Mathlib.Data.Fintype.Powerset
import Mathlib.Data.Nat.Choose.Bounds
import Mathlib.Data.Nat.Choose.Sum
import Mathlib.Tactic

private lemma card_univ_filter_card_le (n k : Nat) :
    ((Finset.univ : Finset (Finset (Fin n))).filter fun s => s.card <= k).card =
      ∑ i ∈ Finset.range (k + 1), Nat.choose n i := by
  classical
  have h := Finset.sum_card_fiberwise_eq_card_filter
    (s := (Finset.univ : Finset (Finset (Fin n))))
    (t := Finset.range (k + 1)) (g := fun s : Finset (Fin n) => s.card)
  calc
    ((Finset.univ : Finset (Finset (Fin n))).filter fun s => s.card <= k).card =
        ((Finset.univ : Finset (Finset (Fin n))).filter fun s => s.card ∈ Finset.range (k + 1)).card := by
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
      exact Finset.mem_erase.mpr ⟨by intro hxa; exact ha (by simpa [hxa] using hx), Finset.mem_univ x⟩
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
    simpa [Finset.erase_insert hau, Finset.erase_insert hav] using congrArg (fun s => s.erase a) huv

private lemma card_univ_filter_card_eq_succ_and_mem {n : Nat} (a : Fin n) (k : Nat) :
    ((Finset.univ : Finset (Finset (Fin n))).filter
      fun s => s.card = k + 1 ∧ a ∈ s).card =
      Nat.choose (n - 1) k := by
  classical
  let U : Finset (Fin n) := (Finset.univ : Finset (Fin n)).erase a
  have hUcard : U.card = n - 1 := by
    simp [U, Finset.card_erase_of_mem]
  have hset :
      ((Finset.univ : Finset (Finset (Fin n))).filter
        fun s => s.card = k + 1 ∧ a ∈ s) =
        (U.powersetCard k).image (fun u => insert a u) := by
    ext s
    simp only [Finset.mem_filter, Finset.mem_univ, true_and, Finset.mem_image,
      Finset.mem_powersetCard]
    constructor
    · rintro ⟨hcard, ha⟩
      refine ⟨s.erase a, ?_, ?_⟩
      · constructor
        · intro x hx
          simp [U] at hx ⊢
          exact hx.1
        · rw [Finset.card_erase_of_mem ha, hcard]
          omega
      · exact Finset.insert_erase ha
    · rintro ⟨u, ⟨huU, hucard⟩, rfl⟩
      have hau : a ∉ u := by
        intro hau
        have := huU hau
        simp [U] at this
      constructor
      · rw [Finset.card_insert_of_notMem hau, hucard]
      · exact Finset.mem_insert_self _ _
  rw [hset, Finset.card_image_of_injOn]
  · rw [Finset.card_powersetCard, hUcard]
  · intro u hu v hv huv
    have hu' : u ∈ U.powersetCard k := by simpa using hu
    have hv' : v ∈ U.powersetCard k := by simpa using hv
    have hau : a ∉ u := by
      intro hau
      have := (Finset.mem_powersetCard.mp hu').1 hau
      simp [U] at this
    have hav : a ∉ v := by
      intro hav
      have := (Finset.mem_powersetCard.mp hv').1 hav
      simp [U] at this
    simpa [Finset.erase_insert hau, Finset.erase_insert hav] using congrArg (fun s => s.erase a) huv

private def booleanVertexBoundary (n : Nat) (A : Finset (Finset (Fin n))) :
    Finset (Finset (Fin n)) :=
  Finset.univ.filter fun t : Finset (Fin n) =>
    t ∉ A ∧ ∃ s ∈ A,
      ((s ⊆ t ∧ t.card = s.card + 1) ∨
       (t ⊆ s ∧ s.card = t.card + 1))

private def booleanHalfInitialSegment (n : Nat) (hn : 0 < n) :
    Finset (Finset (Fin n)) :=
  Finset.univ.filter fun s =>
    if n % 2 = 1 then
      s.card <= n / 2
    else
      s.card < n / 2 ∨
        (s.card = n / 2 ∧ (⟨0, hn⟩ : Fin n) ∈ s)

example (m : Nat) (hn : 0 < 2 * m + 1) :
    booleanHalfInitialSegment (2 * m + 1) hn =
      Finset.univ.filter (fun s : Finset (Fin (2 * m + 1)) => s.card <= m) := by
  classical
  ext s
  simp [booleanHalfInitialSegment]
  omega

example (m : Nat) (hn : 0 < 2 * m) :
    booleanHalfInitialSegment (2 * m) hn =
      Finset.univ.filter (fun s : Finset (Fin (2 * m)) =>
        s.card < m ∨ (s.card = m ∧ (⟨0, hn⟩ : Fin (2 * m)) ∈ s)) := by
  classical
  ext s
  simp [booleanHalfInitialSegment]

example (m : Nat) (hn : 0 < 2 * m + 1) :
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
    · rcases h with ⟨htH, s, hsH, hsadj⟩
      rcases hsadj with ⟨hst, hcard⟩ | ⟨hts, hcard⟩
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

example (m : Nat) :
    ((Finset.univ : Finset (Finset (Fin (2 * m + 1)))).filter
      fun t => t.card <= m + 1).card =
      2 ^ (2 * m) + Nat.choose (2 * m + 1) m := by
  rw [card_univ_filter_card_le]
  rw [Finset.sum_range_succ]
  rw [Nat.sum_range_choose_halfway]
  rw [Nat.choose_symm_half]
  rw [show 4 ^ m = 2 ^ (2 * m) by rw [show (4 : Nat) = 2 ^ 2 by norm_num, pow_mul]]

example (m : Nat) (hn : 0 < 2 * m) :
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
    · rcases htH with hlt | ⟨heq, ha⟩
      · exact Or.inl (by omega)
      · exact Or.inl (by omega)
    · rcases hB with ⟨htH, s, hsH, hsadj⟩
      rcases hsH with hslt | ⟨hseq, hsa⟩
      · rcases hsadj with ⟨hst, hcard⟩ | ⟨hts, hcard⟩
        · exact Or.inl (by omega)
        · have htcard_le : t.card <= s.card := Finset.card_le_card hts
          exact Or.inl (by omega)
      · rcases hsadj with ⟨hst, hcard⟩ | ⟨hts, hcard⟩
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

example (m : Nat) (hn : 0 < 2 * m) :
    ((Finset.univ : Finset (Finset (Fin (2 * m)))).filter
      fun t => t.card <= m ∨ (t.card = m + 1 ∧ (⟨0, hn⟩ : Fin (2 * m)) ∈ t)).card =
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
    by_cases hta : a ∈ t <;> simp [hta] <;> omega
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
  rw [hsplit, Finset.card_union_of_disjoint hdisj]
  rw [card_univ_filter_card_le_and_not_mem, card_univ_filter_card_le_succ_and_mem]
  rw [hsum, hchoose, ← hpow]
  ring
