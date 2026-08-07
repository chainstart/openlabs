import Mathlib.Data.Finset.Card
import Mathlib.Data.Fintype.Basic
import Mathlib.Data.Fintype.Powerset
import Mathlib.Tactic.NormNum

open Finset

theorem upperCone_separator_lowerClosure_card_gt_half_counterexample_n5_r3 :
  ∃ X M : Finset (Finset (Fin 5)),
    (∀ s ∈ X, s.card = 5 - 3) ∧
    (∀ m ∈ M, 5 - 3 < m.card) ∧
    (∀ t, (∃ s ∈ X, s ⊆ t) → t.card = 5 →
      ∃ m ∈ M, m ⊆ t) ∧
    M.card < X.card ∧
    ¬ 2 ^ (5 - 1) <
      (Finset.univ.filter fun u : Finset (Fin 5) =>
        ∃ p, (∃ s ∈ X, s ⊆ p) ∧
          (∀ m ∈ M, ¬ m ⊆ p) ∧ u ⊆ p).card := by
  let X : Finset (Finset (Fin 5)) :=
    {({0, 1} : Finset (Fin 5)), ({0, 2} : Finset (Fin 5)),
      ({0, 3} : Finset (Fin 5)), ({0, 4} : Finset (Fin 5))}
  let M : Finset (Finset (Fin 5)) :=
    {({0, 1, 2} : Finset (Fin 5)), ({0, 1, 3} : Finset (Fin 5)),
      ({0, 2, 3} : Finset (Fin 5))}
  exact ⟨X, M, by native_decide⟩
