import Lake
open Lake DSL

package AmraLibrary where

require mathlib from git
  "https://github.com/leanprover-community/mathlib4" @ "v4.26.0"

@[default_target]
lean_lib AmraLibrary
