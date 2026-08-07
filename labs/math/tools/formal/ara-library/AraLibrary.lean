import AraLibrary.Analysis.BMOBellmanContact

/-!
Reusable ARA Math library entry point for the active BMO formalization target.

The standalone geometry and number theory modules remain in the workspace, but
importing them through this aggregate module currently trips a Lean 4.26 native
codegen crash when rebuilding the root library.
-/
