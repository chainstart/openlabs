import AmraLibrary.Combinatorics.SimpleGraph.GraphConjectures.WowiiConjecture58

namespace SimpleGraph
namespace Wowii58Vertex

def isC : Wowii58Vertex -> Bool
  | c _ => true
  | _ => false

example (s : Finset Wowii58Vertex) :
    (s.filter fun v => isC v).card ≤ 55 := by
  native_decide +revert

end Wowii58Vertex
end SimpleGraph
