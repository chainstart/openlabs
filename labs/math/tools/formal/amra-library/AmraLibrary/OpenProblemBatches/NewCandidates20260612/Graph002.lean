import Mathlib.Combinatorics.SimpleGraph.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Data.Fintype.Card
import Mathlib.Data.Nat.Find

/-!
Lean scratch target for the 2026-06-12 AMRA attack on GRAPH-002.
-/

namespace AmraNewCandidates20260612
namespace Graph002

variable {V : Type*}

/-- A finite guard set dominates when every vertex is either guarded or adjacent
to a guarded vertex. -/
def IsDominating (G : SimpleGraph V) (S : Finset V) : Prop :=
  ∀ v, v ∈ S ∨ ∃ w ∈ S, G.Adj v w

def HasDominatingSetCard (G : SimpleGraph V) (k : ℕ) : Prop :=
  ∃ S : Finset V, S.card = k ∧ IsDominating G S

lemma isDominating_univ [Fintype V] (G : SimpleGraph V) :
    IsDominating G (Finset.univ : Finset V) := by
  intro v
  exact Or.inl (Finset.mem_univ v)

lemma exists_hasDominatingSetCard [Fintype V] (G : SimpleGraph V) :
    ∃ k, HasDominatingSetCard G k :=
  ⟨Fintype.card V, Finset.univ, by simp, isDominating_univ G⟩

noncomputable def dominationNumber [Fintype V] (G : SimpleGraph V) : ℕ := by
  classical
  exact Nat.find (exists_hasDominatingSetCard G)

lemma dominationNumber_spec [Fintype V] (G : SimpleGraph V) :
    HasDominatingSetCard G (dominationNumber G) := by
  classical
  simpa [dominationNumber] using Nat.find_spec (exists_hasDominatingSetCard G)

lemma dominationNumber_le_of_hasDominatingSetCard [Fintype V] {G : SimpleGraph V}
    {k : ℕ} (h : HasDominatingSetCard G k) :
    dominationNumber G ≤ k := by
  classical
  simpa [dominationNumber] using Nat.find_min' (exists_hasDominatingSetCard G) h

/-- A finite West-style eternal domination interface with guard states of
uniform cardinality. -/
structure EternalFamily [DecidableEq V] (G : SimpleGraph V) (k : ℕ) where
  states : Finset (Finset V)
  nonempty : states.Nonempty
  card_eq : ∀ S, S ∈ states → S.card = k
  dominating : ∀ S, S ∈ states → IsDominating G S
  defend :
    ∀ S, S ∈ states → ∀ v, v ∉ S →
      ∃ u ∈ S, G.Adj u v ∧ insert v (S.erase u) ∈ states

def EternalFeasible [DecidableEq V] (G : SimpleGraph V) (k : ℕ) : Prop :=
  Nonempty (EternalFamily G k)

def trivialEternalFamily [Fintype V] [DecidableEq V] (G : SimpleGraph V) :
    EternalFamily G (Fintype.card V) where
  states := {Finset.univ}
  nonempty := by simp
  card_eq := by
    intro S hS
    rw [Finset.mem_singleton] at hS
    subst S
    simp
  dominating := by
    intro S hS
    rw [Finset.mem_singleton] at hS
    subst S
    exact isDominating_univ G
  defend := by
    intro S hS v hv
    rw [Finset.mem_singleton] at hS
    subst S
    exact (hv (Finset.mem_univ v)).elim

lemma exists_eternalFeasible [Fintype V] [DecidableEq V] (G : SimpleGraph V) :
    ∃ k, EternalFeasible G k :=
  ⟨Fintype.card V, ⟨trivialEternalFamily G⟩⟩

noncomputable def eternalDominationNumber [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) : ℕ := by
  classical
  exact Nat.find (exists_eternalFeasible G)

lemma eternalDominationNumber_spec [Fintype V] [DecidableEq V] (G : SimpleGraph V) :
    EternalFeasible G (eternalDominationNumber G) := by
  classical
  simpa [eternalDominationNumber] using Nat.find_spec (exists_eternalFeasible G)

lemma dominationNumber_le_of_eternalFeasible [Fintype V] [DecidableEq V]
    {G : SimpleGraph V} {k : ℕ} (h : EternalFeasible G k) :
    dominationNumber G ≤ k := by
  rcases h with ⟨family⟩
  obtain ⟨S, hS⟩ := family.nonempty
  exact dominationNumber_le_of_hasDominatingSetCard
    ⟨S, family.card_eq S hS, family.dominating S hS⟩

theorem dominationNumber_le_eternalDominationNumber
    [Fintype V] [DecidableEq V]
    (G : SimpleGraph V) :
    dominationNumber G ≤ eternalDominationNumber G := by
  exact dominationNumber_le_of_eternalFeasible
    (eternalDominationNumber_spec G)

end Graph002
end AmraNewCandidates20260612
