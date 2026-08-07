import Mathlib

/-!
Reusable lightweight triangle-dissection shell.

This module is extracted from the ARA triangle-dissection campaigns, especially
the 634 campaign. It intentionally keeps only carrier structures and elementary
shape/placement lemmas. It is not a full Euclidean geometry formalization.
-/

namespace AraLibrary
namespace TriangleDissectionShell

/-- A lightweight triangle shell with integer-coordinate vertices. -/
structure EquilateralTriangle where
  vertices : Fin 3 → Int × Int

/-- A lightweight dissection shell used to stage later geometric constraints. -/
structure TriangleDissection (n : Nat) where
  original : EquilateralTriangle
  pieces : Fin n → EquilateralTriangle

/-- Whether an equilateral-triangle shell admits a dissection into `n` pieces. -/
def IsPossible (n : Nat) : Prop :=
  0 < n ∧ Nonempty (TriangleDissection n)

/-- The shell notion `IsPossible 0` is impossible. -/
theorem not_IsPossible_zero : ¬ IsPossible 0 := by
  intro h
  exact Nat.lt_irrefl 0 h.1

/-- A triangle shape represented by positive squared side lengths. -/
structure PaperTriangleShape where
  ab2 : Nat
  bc2 : Nat
  ca2 : Nat
  ab2_pos : 0 < ab2
  bc2_pos : 0 < bc2
  ca2_pos : 0 < ca2

/-- Project-local ambient plane for paper-style triangle placements. -/
abbrev PlanePoint := Int × Int

/-- Squared length of one integer coordinate difference. -/
def pointCoordSq (z : Int) : Nat :=
  Int.natAbs z ^ 2

/-- Squared Euclidean distance on the project-local ambient plane. -/
def squaredDistance (p q : PlanePoint) : Nat :=
  pointCoordSq (p.1 - q.1) + pointCoordSq (p.2 - q.2)

/-- Squared side-length data of a paper-facing triangle shell. -/
def PaperTriangleShape.edgeTriple (T : PaperTriangleShape) : Nat × Nat × Nat :=
  (T.ab2, T.bc2, T.ca2)

/-- The three squared side lengths, viewed as a relabeling-sensitive list. -/
def PaperTriangleShape.edgeList (T : PaperTriangleShape) : List Nat :=
  [T.ab2, T.bc2, T.ca2]

/-- The three squared side lengths after one common positive squared-scale factor. -/
def PaperTriangleShape.scaledEdgeList (T : PaperTriangleShape) (scale : Nat) : List Nat :=
  [scale * T.ab2, scale * T.bc2, scale * T.ca2]

/-- Same shape up to relabeling of the three side slots. -/
def PaperTriangleShape.sameShapeUpToRelabelling (T U : PaperTriangleShape) : Prop :=
  List.Perm T.edgeList U.edgeList

theorem PaperTriangleShape.sameShapeUpToRelabelling_refl (T : PaperTriangleShape) :
    T.sameShapeUpToRelabelling T := by
  exact List.Perm.refl _

theorem PaperTriangleShape.sameShapeUpToRelabelling_symm {T U : PaperTriangleShape} :
    T.sameShapeUpToRelabelling U → U.sameShapeUpToRelabelling T := by
  intro h
  exact h.symm

theorem PaperTriangleShape.sameShapeUpToRelabelling_trans
    {T U V : PaperTriangleShape} :
    T.sameShapeUpToRelabelling U →
      U.sameShapeUpToRelabelling V →
        T.sameShapeUpToRelabelling V := by
  intro hTU hUV
  exact hTU.trans hUV

/-- Shape-level similarity for squared side-length data, modulo relabeling. -/
def PaperTriangleShape.similarBySquaredScale (T U : PaperTriangleShape) : Prop :=
  ∃ a b : Nat, 0 < a ∧ 0 < b ∧
    List.Perm (T.scaledEdgeList a) (U.scaledEdgeList b)

/-- Right-angle predicate at one explicit vertex of the local triangle shell. -/
def PaperTriangleShape.IsRightAt (T : PaperTriangleShape) (i : Fin 3) : Prop :=
  match i.1 with
  | 0 => T.ab2 + T.ca2 = T.bc2
  | 1 => T.ab2 + T.bc2 = T.ca2
  | _ => T.bc2 + T.ca2 = T.ab2

/-- Relabeling-invariant and scale-invariant right-triangle predicate. -/
def PaperTriangleShape.IsRight (T : PaperTriangleShape) : Prop :=
  ∃ scale x y z : Nat, 0 < scale ∧
    List.Perm (T.scaledEdgeList scale) [x, y, z] ∧
      x + y = z

theorem PaperTriangleShape.isRight_of_isRightAt
    {T : PaperTriangleShape} {i : Fin 3} :
    T.IsRightAt i → T.IsRight := by
  intro hRight
  rcases i with ⟨i, hi⟩
  cases i with
  | zero =>
      refine ⟨1, T.ab2, T.ca2, T.bc2, by decide, ?_, ?_⟩
      · simpa [PaperTriangleShape.scaledEdgeList] using
          (List.Perm.cons T.ab2 (List.Perm.swap T.bc2 T.ca2 []).symm)
      · simpa [PaperTriangleShape.IsRightAt] using hRight
  | succ i =>
      cases i with
      | zero =>
          refine ⟨1, T.ab2, T.bc2, T.ca2, by decide, ?_, ?_⟩
          · simpa [PaperTriangleShape.scaledEdgeList] using
              (List.Perm.refl [T.ab2, T.bc2, T.ca2])
          · simpa [PaperTriangleShape.IsRightAt] using hRight
      | succ i =>
          cases i with
          | zero =>
              refine ⟨1, T.bc2, T.ca2, T.ab2, by decide, ?_, ?_⟩
              · have hSwapHead :
                    List.Perm (T.scaledEdgeList 1) [T.bc2, T.ab2, T.ca2] := by
                    simpa [PaperTriangleShape.scaledEdgeList] using
                      (List.Perm.swap T.ab2 T.bc2 [T.ca2]).symm
                have hSwapTail :
                    List.Perm [T.bc2, T.ab2, T.ca2] [T.bc2, T.ca2, T.ab2] := by
                    simpa using
                      (List.Perm.cons T.bc2 (List.Perm.swap T.ab2 T.ca2 []).symm)
                exact hSwapHead.trans hSwapTail
              · simpa [PaperTriangleShape.IsRightAt] using hRight
          | succ i =>
              exfalso
              omega

theorem PaperTriangleShape.similarBySquaredScale_refl (T : PaperTriangleShape) :
    T.similarBySquaredScale T := by
  refine ⟨1, 1, by decide, by decide, ?_⟩
  simpa [PaperTriangleShape.scaledEdgeList]

theorem PaperTriangleShape.similarBySquaredScale_of_sameShapeUpToRelabelling
    {T U : PaperTriangleShape} :
    T.sameShapeUpToRelabelling U →
      T.similarBySquaredScale U := by
  intro h
  refine ⟨1, 1, by decide, by decide, ?_⟩
  simpa [PaperTriangleShape.edgeList, PaperTriangleShape.scaledEdgeList,
    PaperTriangleShape.sameShapeUpToRelabelling] using h

theorem PaperTriangleShape.similarBySquaredScale_symm {T U : PaperTriangleShape} :
    T.similarBySquaredScale U → U.similarBySquaredScale T := by
  rintro ⟨a, b, ha, hb, hPerm⟩
  exact ⟨b, a, hb, ha, hPerm.symm⟩

theorem PaperTriangleShape.similarBySquaredScale_trans {T U V : PaperTriangleShape} :
    T.similarBySquaredScale U → U.similarBySquaredScale V → T.similarBySquaredScale V := by
  rintro ⟨a, b, ha, hb, hTU⟩ ⟨c, d, hc, hd, hUV⟩
  have hTU' :
      List.Perm (T.scaledEdgeList (c * a)) (U.scaledEdgeList (b * c)) := by
    simpa [PaperTriangleShape.scaledEdgeList, Nat.mul_assoc, Nat.mul_left_comm, Nat.mul_comm] using
      hTU.map (fun x => c * x)
  have hUV' :
      List.Perm (U.scaledEdgeList (b * c)) (V.scaledEdgeList (b * d)) := by
    simpa [PaperTriangleShape.scaledEdgeList, Nat.mul_assoc, Nat.mul_left_comm, Nat.mul_comm] using
      hUV.map (fun x => b * x)
  refine ⟨c * a, b * d, Nat.mul_pos hc ha, Nat.mul_pos hb hd, ?_⟩
  simpa [PaperTriangleShape.scaledEdgeList, Nat.mul_assoc] using hTU'.trans hUV'

theorem PaperTriangleShape.isRight_of_similarBySquaredScale
    {T U : PaperTriangleShape} :
    T.similarBySquaredScale U → T.IsRight → U.IsRight := by
  rintro ⟨a, b, ha, hb, hSim⟩ ⟨c, x, y, z, hc, hRight, hEq⟩
  have hRightScaled :
      List.Perm (T.scaledEdgeList (a * c)) [a * x, a * y, a * z] := by
    simpa [PaperTriangleShape.scaledEdgeList, Nat.mul_assoc, Nat.mul_left_comm, Nat.mul_comm] using
      hRight.map (fun t => a * t)
  have hSimScaled :
      List.Perm (T.scaledEdgeList (c * a)) (U.scaledEdgeList (c * b)) := by
    simpa [PaperTriangleShape.scaledEdgeList, Nat.mul_assoc, Nat.mul_left_comm, Nat.mul_comm] using
      hSim.map (fun t => c * t)
  refine ⟨c * b, a * x, a * y, a * z, Nat.mul_pos hc hb, ?_, ?_⟩
  · exact hSimScaled.symm.trans (by
      simpa [PaperTriangleShape.scaledEdgeList, Nat.mul_assoc, Nat.mul_left_comm, Nat.mul_comm] using
        hRightScaled)
  · rw [← Nat.mul_add, hEq]

/-- A paper-facing triangle together with one explicit placement in the ambient plane. -/
structure PlacedPaperTriangle where
  shape : PaperTriangleShape
  placement : Fin 3 → PlanePoint

def PlacedPaperTriangle.vertex (triangle : PlacedPaperTriangle) (i : Fin 3) : PlanePoint :=
  triangle.placement i

def PlacedPaperTriangle.similarBySquaredScale
    (triangle₁ triangle₂ : PlacedPaperTriangle) : Prop :=
  triangle₁.shape.similarBySquaredScale triangle₂.shape

def PlacedPaperTriangle.IsRightAt (triangle : PlacedPaperTriangle) (i : Fin 3) : Prop :=
  triangle.shape.IsRightAt i

def PlacedPaperTriangle.IsRight (triangle : PlacedPaperTriangle) : Prop :=
  triangle.shape.IsRight

theorem PlacedPaperTriangle.isRight_of_isRightAt
    {triangle : PlacedPaperTriangle} {i : Fin 3} :
    triangle.IsRightAt i → triangle.IsRight :=
  PaperTriangleShape.isRight_of_isRightAt

theorem PlacedPaperTriangle.similarBySquaredScale_of_sameShapeUpToRelabelling
    {triangle₁ triangle₂ : PlacedPaperTriangle} :
    triangle₁.shape.sameShapeUpToRelabelling triangle₂.shape →
      triangle₁.similarBySquaredScale triangle₂ :=
  PaperTriangleShape.similarBySquaredScale_of_sameShapeUpToRelabelling

theorem PlacedPaperTriangle.similarBySquaredScale_symm
    {triangle₁ triangle₂ : PlacedPaperTriangle} :
    triangle₁.similarBySquaredScale triangle₂ →
      triangle₂.similarBySquaredScale triangle₁ :=
  PaperTriangleShape.similarBySquaredScale_symm

theorem PlacedPaperTriangle.similarBySquaredScale_trans
    {triangle₁ triangle₂ triangle₃ : PlacedPaperTriangle} :
    triangle₁.similarBySquaredScale triangle₂ →
      triangle₂.similarBySquaredScale triangle₃ →
        triangle₁.similarBySquaredScale triangle₃ :=
  PaperTriangleShape.similarBySquaredScale_trans

theorem PlacedPaperTriangle.isRight_of_similarBySquaredScale
    {triangle₁ triangle₂ : PlacedPaperTriangle} :
    triangle₁.similarBySquaredScale triangle₂ →
      triangle₁.IsRight →
        triangle₂.IsRight :=
  PaperTriangleShape.isRight_of_similarBySquaredScale

def PlacedPaperTriangle.realizesShape (triangle : PlacedPaperTriangle) : Prop :=
  squaredDistance (triangle.vertex 0) (triangle.vertex 1) = triangle.shape.ab2 ∧
    squaredDistance (triangle.vertex 1) (triangle.vertex 2) = triangle.shape.bc2 ∧
    squaredDistance (triangle.vertex 2) (triangle.vertex 0) = triangle.shape.ca2

def PlacedPaperTriangle.HasVertex (triangle : PlacedPaperTriangle) (p : PlanePoint) : Prop :=
  ∃ i, triangle.vertex i = p

structure PlacedPaperTriangle.VertexWitness
    (triangle : PlacedPaperTriangle) (p : PlanePoint) where
  vertex_index : Fin 3
  vertex_eq : triangle.vertex vertex_index = p

def PlacedPaperTriangle.sideStart (triangle : PlacedPaperTriangle) (i : Fin 3) : PlanePoint :=
  match i.1 with
  | 0 => triangle.vertex 0
  | 1 => triangle.vertex 1
  | _ => triangle.vertex 2

def PlacedPaperTriangle.sideEnd (triangle : PlacedPaperTriangle) (i : Fin 3) : PlanePoint :=
  match i.1 with
  | 0 => triangle.vertex 1
  | 1 => triangle.vertex 2
  | _ => triangle.vertex 0

def PlacedPaperTriangle.precedingSideAtVertex (_triangle : PlacedPaperTriangle) (i : Fin 3) : Fin 3 :=
  match i.1 with
  | 0 => 2
  | 1 => 0
  | _ => 1

def PlacedPaperTriangle.followingSideAtVertex (_triangle : PlacedPaperTriangle) (i : Fin 3) : Fin 3 :=
  match i.1 with
  | 0 => 0
  | 1 => 1
  | _ => 2

def PlacedPaperTriangle.VerticesLieIn
    (triangle : PlacedPaperTriangle) (R : PlanePoint → Prop) : Prop :=
  ∀ i : Fin 3, R (triangle.vertex i)

def PlacedPaperTriangle.SharesTwoVertices
    (triangle₁ triangle₂ : PlacedPaperTriangle) : Prop :=
  ∃ p q : PlanePoint,
    p ≠ q ∧
      triangle₁.HasVertex p ∧
      triangle₁.HasVertex q ∧
      triangle₂.HasVertex p ∧
      triangle₂.HasVertex q

structure PlacedPaperTriangle.SharedVertexPair
    (triangle₁ triangle₂ : PlacedPaperTriangle) where
  firstPoint : PlanePoint
  secondPoint : PlanePoint
  points_distinct : firstPoint ≠ secondPoint
  leftFirst : PlacedPaperTriangle.VertexWitness triangle₁ firstPoint
  leftSecond : PlacedPaperTriangle.VertexWitness triangle₁ secondPoint
  rightFirst : PlacedPaperTriangle.VertexWitness triangle₂ firstPoint
  rightSecond : PlacedPaperTriangle.VertexWitness triangle₂ secondPoint

structure PlacedPaperTriangle.SharedSidePair
    (triangle₁ triangle₂ : PlacedPaperTriangle) where
  firstPoint : PlanePoint
  secondPoint : PlanePoint
  points_distinct : firstPoint ≠ secondPoint
  leftSide : Fin 3
  rightSide : Fin 3
  leftStart : triangle₁.sideStart leftSide = firstPoint
  leftEnd : triangle₁.sideEnd leftSide = secondPoint
  rightEndpoints :
    (triangle₂.sideStart rightSide = firstPoint ∧
        triangle₂.sideEnd rightSide = secondPoint) ∨
      (triangle₂.sideStart rightSide = secondPoint ∧
        triangle₂.sideEnd rightSide = firstPoint)

theorem PlacedPaperTriangle.hasVertex_vertex (triangle : PlacedPaperTriangle) (i : Fin 3) :
    triangle.HasVertex (triangle.vertex i) := by
  exact ⟨i, rfl⟩

theorem PlacedPaperTriangle.VertexWitness.toHasVertex
    {triangle : PlacedPaperTriangle} {p : PlanePoint}
    (witness : PlacedPaperTriangle.VertexWitness triangle p) :
    triangle.HasVertex p := by
  exact ⟨witness.vertex_index, witness.vertex_eq⟩

theorem PlacedPaperTriangle.hasVertex_sideStart
    (triangle : PlacedPaperTriangle) (i : Fin 3) :
    triangle.HasVertex (triangle.sideStart i) := by
  rcases i with ⟨i, hi⟩
  have hi' : i = 0 ∨ i = 1 ∨ i = 2 := by
    omega
  rcases hi' with rfl | h
  · simpa [PlacedPaperTriangle.sideStart] using triangle.hasVertex_vertex 0
  rcases h with rfl | rfl
  · simpa [PlacedPaperTriangle.sideStart] using triangle.hasVertex_vertex 1
  · simpa [PlacedPaperTriangle.sideStart] using triangle.hasVertex_vertex 2

theorem PlacedPaperTriangle.hasVertex_sideEnd
    (triangle : PlacedPaperTriangle) (i : Fin 3) :
    triangle.HasVertex (triangle.sideEnd i) := by
  rcases i with ⟨i, hi⟩
  have hi' : i = 0 ∨ i = 1 ∨ i = 2 := by
    omega
  rcases hi' with rfl | h
  · simpa [PlacedPaperTriangle.sideEnd] using triangle.hasVertex_vertex 1
  rcases h with rfl | rfl
  · simpa [PlacedPaperTriangle.sideEnd] using triangle.hasVertex_vertex 2
  · simpa [PlacedPaperTriangle.sideEnd] using triangle.hasVertex_vertex 0

theorem PlacedPaperTriangle.sideEnd_precedingSideAtVertex
    (triangle : PlacedPaperTriangle) (i : Fin 3) :
    triangle.sideEnd (triangle.precedingSideAtVertex i) = triangle.vertex i := by
  rcases i with ⟨i, hi⟩
  have hi' : i = 0 ∨ i = 1 ∨ i = 2 := by
    omega
  rcases hi' with rfl | h
  · simp [PlacedPaperTriangle.precedingSideAtVertex, PlacedPaperTriangle.sideEnd]
  rcases h with rfl | rfl
  · simp [PlacedPaperTriangle.precedingSideAtVertex, PlacedPaperTriangle.sideEnd]
  · simp [PlacedPaperTriangle.precedingSideAtVertex, PlacedPaperTriangle.sideEnd]

theorem PlacedPaperTriangle.sideStart_followingSideAtVertex
    (triangle : PlacedPaperTriangle) (i : Fin 3) :
    triangle.sideStart (triangle.followingSideAtVertex i) = triangle.vertex i := by
  rcases i with ⟨i, hi⟩
  have hi' : i = 0 ∨ i = 1 ∨ i = 2 := by
    omega
  rcases hi' with rfl | h
  · simp [PlacedPaperTriangle.followingSideAtVertex, PlacedPaperTriangle.sideStart]
  rcases h with rfl | rfl
  · simp [PlacedPaperTriangle.followingSideAtVertex, PlacedPaperTriangle.sideStart]
  · simp [PlacedPaperTriangle.followingSideAtVertex, PlacedPaperTriangle.sideStart]

theorem PlacedPaperTriangle.SharedVertexPair.toSharesTwoVertices
    {triangle₁ triangle₂ : PlacedPaperTriangle}
    (witness : PlacedPaperTriangle.SharedVertexPair triangle₁ triangle₂) :
    triangle₁.SharesTwoVertices triangle₂ := by
  refine ⟨witness.firstPoint, witness.secondPoint, witness.points_distinct, ?_, ?_, ?_, ?_⟩
  · exact witness.leftFirst.toHasVertex
  · exact witness.leftSecond.toHasVertex
  · exact witness.rightFirst.toHasVertex
  · exact witness.rightSecond.toHasVertex

noncomputable def PlacedPaperTriangle.vertexWitnessOfHasVertex
    {triangle : PlacedPaperTriangle} {p : PlanePoint}
    (hVertex : triangle.HasVertex p) :
    PlacedPaperTriangle.VertexWitness triangle p := by
  classical
  exact
    { vertex_index := Classical.choose hVertex
      vertex_eq := Classical.choose_spec hVertex }

noncomputable def PlacedPaperTriangle.SharedSidePair.toSharedVertexPair
    {triangle₁ triangle₂ : PlacedPaperTriangle}
    (witness : PlacedPaperTriangle.SharedSidePair triangle₁ triangle₂) :
    PlacedPaperTriangle.SharedVertexPair triangle₁ triangle₂ := by
  refine
    { firstPoint := witness.firstPoint
      secondPoint := witness.secondPoint
      points_distinct := witness.points_distinct
      leftFirst := ?_
      leftSecond := ?_
      rightFirst := ?_
      rightSecond := ?_ }
  · exact
      PlacedPaperTriangle.vertexWitnessOfHasVertex <| by
        rw [← witness.leftStart]
        exact triangle₁.hasVertex_sideStart witness.leftSide
  · exact
      PlacedPaperTriangle.vertexWitnessOfHasVertex <| by
        rw [← witness.leftEnd]
        exact triangle₁.hasVertex_sideEnd witness.leftSide
  · exact
      PlacedPaperTriangle.vertexWitnessOfHasVertex <| by
        rcases witness.rightEndpoints with hRight | hRight
        · rw [← hRight.1]
          exact triangle₂.hasVertex_sideStart witness.rightSide
        · rw [← hRight.2]
          exact triangle₂.hasVertex_sideEnd witness.rightSide
  · exact
      PlacedPaperTriangle.vertexWitnessOfHasVertex <| by
        rcases witness.rightEndpoints with hRight | hRight
        · rw [← hRight.2]
          exact triangle₂.hasVertex_sideEnd witness.rightSide
        · rw [← hRight.1]
          exact triangle₂.hasVertex_sideStart witness.rightSide

theorem PlacedPaperTriangle.SharedSidePair.toSharesTwoVertices
    {triangle₁ triangle₂ : PlacedPaperTriangle}
    (witness : PlacedPaperTriangle.SharedSidePair triangle₁ triangle₂) :
    triangle₁.SharesTwoVertices triangle₂ := by
  exact witness.toSharedVertexPair.toSharesTwoVertices

theorem PlacedPaperTriangle.sharesTwoVertices_symm
    {triangle₁ triangle₂ : PlacedPaperTriangle} :
    triangle₁.SharesTwoVertices triangle₂ → triangle₂.SharesTwoVertices triangle₁ := by
  rintro ⟨p, q, hpq, hp₁, hq₁, hp₂, hq₂⟩
  exact ⟨p, q, hpq, hp₂, hq₂, hp₁, hq₁⟩

def PlacedPaperTriangle.toLegacyTriangle (triangle : PlacedPaperTriangle) : EquilateralTriangle :=
  { vertices := triangle.placement }

/-- Abstract region semantics attached to one explicit placed paper triangle. -/
structure PlacedPaperTriangleRegion (triangle : PlacedPaperTriangle) where
  contains : PlanePoint → Prop
  interiorContains : PlanePoint → Prop
  contains_vertex : ∀ i, contains (triangle.vertex i)
  interior_subset_contains : ∀ ⦃p : PlanePoint⦄, interiorContains p → contains p

theorem PlacedPaperTriangle.verticesLieIn_of_region
    (triangle : PlacedPaperTriangle) (region : PlacedPaperTriangleRegion triangle) :
    triangle.VerticesLieIn region.contains := by
  intro i
  exact region.contains_vertex i

theorem PlacedPaperTriangleRegion.contains_of_hasVertex
    {triangle : PlacedPaperTriangle} (region : PlacedPaperTriangleRegion triangle)
    {p : PlanePoint} (hp : triangle.HasVertex p) :
    region.contains p := by
  rcases hp with ⟨i, rfl⟩
  exact region.contains_vertex i

theorem PlacedPaperTriangleRegion.contains_sideStart
    {triangle : PlacedPaperTriangle} (region : PlacedPaperTriangleRegion triangle) (i : Fin 3) :
    region.contains (triangle.sideStart i) := by
  exact region.contains_of_hasVertex (triangle.hasVertex_sideStart i)

theorem PlacedPaperTriangleRegion.contains_sideEnd
    {triangle : PlacedPaperTriangle} (region : PlacedPaperTriangleRegion triangle) (i : Fin 3) :
    region.contains (triangle.sideEnd i) := by
  exact region.contains_of_hasVertex (triangle.hasVertex_sideEnd i)

end TriangleDissectionShell
end AraLibrary
