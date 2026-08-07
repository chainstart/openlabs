/-
Copyright 2026 AMRA contributors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-/

import Mathlib.Combinatorics.SimpleGraph.Finite

/-!
# Well totally dominated graphs

Reusable definitions from the Formal Conjectures WOWII total-domination files.
-/

namespace SimpleGraph

variable {α : Type*} [Fintype α] [DecidableEq α]

/-- A finite set `S` is a total dominating set of `G` if every vertex has a
neighbor in `S`. -/
def IsTotalDominatingSet (G : SimpleGraph α) [DecidableRel G.Adj] (S : Finset α) : Prop :=
  ∀ v : α, ∃ w ∈ S, G.Adj v w

/-- A total dominating set is minimal if no proper subset remains total
dominating. -/
def IsMinimalTotalDominatingSet (G : SimpleGraph α) [DecidableRel G.Adj]
    (S : Finset α) : Prop :=
  IsTotalDominatingSet G S ∧
    ∀ T : Finset α, T ⊂ S → ¬ IsTotalDominatingSet G T

/-- A graph is well totally dominated if all minimal total dominating sets have
the same cardinality. -/
def IsWellTotallyDominated (G : SimpleGraph α) [DecidableRel G.Adj] : Prop :=
  ∀ S T : Finset α,
    IsMinimalTotalDominatingSet G S →
    IsMinimalTotalDominatingSet G T →
    S.card = T.card

/-- Pendant vertices, i.e. vertices of degree one. -/
noncomputable def pendantVertices (G : SimpleGraph α) [DecidableRel G.Adj] : Finset α :=
  Finset.univ.filter (fun v => G.degree v = 1)

end SimpleGraph
