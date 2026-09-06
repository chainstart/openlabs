"""Fixtures exercise source semantics without importing or executing Lean code."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "problem_catalog_formal.py"
_SPEC = importlib.util.spec_from_file_location("problem_catalog_formal_under_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
parse_formal_tree = _MODULE.parse_formal_tree
REVISION = "a" * 40
RETRIEVED = "2026-09-05T00:00:00Z"


class FormalConjecturesAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "FormalConjectures").mkdir()

    def source(self, relative, text):
        path = self.root / "FormalConjectures" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def parse(self):
        return parse_formal_tree(self.root, REVISION, RETRIEVED)

    def test_exact_multiline_status_and_independent_erdos_variants(self):
        text = '''import FormalConjecturesUtil
namespace Erdos1084
variable {n : Nat}
/-! Status: open. https://www.erdosproblems.com/1084 -/
/-- A solved bound. -/
@[category research solved, AMS 52]
theorem erdos_1084.variants.bound (n : Nat) :
    n = n := by
  -- A proof hole is not mathematical openness.
  sorry

/-- An independent open variant. -/
@[
  category research (open),
  AMS 52
]
@[simp]
theorem erdos_1084.variants.question :
    answer(sorry) ↔ True := by
  sorry
end Erdos1084
'''
        self.source("ErdosProblems/1084.lean", text)
        first, second = self.parse()
        self.assertEqual(first["source_status"], "solved")
        self.assertTrue(first["contains_sorry"])
        self.assertEqual(second["source_status"], "open")
        self.assertEqual(first["canonical_erdos_id"], "1084")
        self.assertEqual(first["relation"], "variant_of")
        self.assertEqual(first["statement_text"], "theorem erdos_1084.variants.bound (n : Nat) :\n    n = n := by\n  -- A proof hole is not mathematical openness.\n  sorry")
        self.assertNotIn("independent open", first["statement_text"])
        self.assertEqual(second["declaration_full_name"], "Erdos1084.erdos_1084.variants.question")
        self.assertEqual(first["source_line"], 7)
        self.assertIn(f"/blob/{REVISION}/FormalConjectures/ErdosProblems/1084.lean#L7", first["source_url"])
        self.assertEqual(first["source_context_text"], text)
        self.assertEqual(first["file_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertFalse(first["verified"])
        self.assertEqual(first["statement_quality"], "lean_source_unverified")

    def test_not_test_api_or_textbook_and_not_cross_reference_identity(self):
        self.source("Wikipedia/Amicable.lean", '''import FormalConjecturesUtil
import FormalConjectures.ErdosProblems.«830»
/-! https://www.erdosproblems.com/830 -/
namespace AmicableNumbers
@[category test, AMS 11]
theorem witness : True := by trivial
@[category API, AMS 11]
theorem symmetry : True := by trivial
@[category textbook, AMS 11]
theorem textbook : True := by trivial
@[category research open, AMS 11]
theorem infinitely_many : type_of% Erdos830.erdos_830.parts.i := by
  sorry
end AmicableNumbers
''')
        entry, = self.parse()
        self.assertIsNone(entry["canonical_erdos_id"])
        self.assertEqual(entry["relation"], "unclassified")
        self.assertEqual(entry["source_imports"], ["FormalConjecturesUtil", "FormalConjectures.ErdosProblems.«830»"])
        self.assertIn("https://www.erdosproblems.com/830", entry["references"])

    def test_namespaces_sections_and_file_identity(self):
        self.source("Other/A.lean", '''namespace Outer
section context
namespace Inner
@[category research open]
theorem same : True := by trivial
end Inner
end context
@[category research solved]
theorem same : True := by trivial
end Outer
@[category research open]
theorem _root_.Global.name : True := by trivial
''')
        self.source("Other/B.lean", '''namespace Outer
@[category research open]
theorem same : True := by trivial
end Outer
''')
        entries = self.parse()
        self.assertEqual([entry["declaration_full_name"] for entry in entries], ["Outer.Inner.same", "Outer.same", "Global.name", "Outer.same"])
        self.assertEqual(len({entry["source_item_id"] for entry in entries}), 4)
        self.assertTrue(all(not entry["contains_sorry"] for entry in entries))

    def test_nested_comments_and_strings_do_not_create_research_or_sorry(self):
        self.source("Other/Comments.lean", '''/- outer /- nested -/
@[category research open]
theorem fake : True := by sorry
-/
def message := "@[category research open] theorem fake2 : True := by sorry"
@[category research solved]
def real : String := "sorry"
-- @[category research open]
-- theorem fake3 : True := by sorry
''')
        entry, = self.parse()
        self.assertEqual(entry["statement_text"], 'def real : String := "sorry"')
        self.assertFalse(entry["contains_sorry"])

    def test_inline_attribute_quoted_identifier_and_unknown_status(self):
        self.source("Other/Names.lean", '''namespace «Unusual namespace»
@[category research] theorem «odd name» : True := by
  trivial
end «Unusual namespace»
''')
        entry, = self.parse()
        self.assertEqual(entry["source_status"], "unknown")
        self.assertEqual(entry["declaration_full_name"], "«Unusual namespace».«odd name»")
        self.assertEqual(entry["statement_text"], "theorem «odd name» : True := by\n  trivial")

    def test_main_erdos_statement_is_formalization_not_all_file_equivalence(self):
        self.source("ErdosProblems/42.lean", '''namespace Erdos42
@[category research open]
theorem erdos_42 : True := by sorry
@[category research solved]
theorem erdos_42.parts.i : True := by trivial
end Erdos42
''')
        main, part = self.parse()
        self.assertEqual(main["relation"], "formalization_of")
        self.assertEqual(part["relation"], "variant_of")
        self.assertNotEqual(main["source_item_id"], part["source_item_id"])

    def test_tree_root_compatibility_and_reject_mutable_revision(self):
        self.source("Other/A.lean", "@[category research open]\ntheorem question : True := by sorry\n")
        self.assertEqual(self.parse(), parse_formal_tree(self.root / "FormalConjectures", REVISION, RETRIEVED))
        with self.assertRaisesRegex(ValueError, "immutable"):
            parse_formal_tree(self.root, "main", RETRIEVED)

    def test_missing_tree_and_unsupported_research_fail_visibly(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(ValueError, "Missing"):
                parse_formal_tree(Path(empty), REVISION, RETRIEVED)
        self.source("Other/A.lean", "@[category research open]\nunknown_new_command question : True\n")
        with self.assertRaisesRegex(ValueError, "Unsupported research declaration"):
            self.parse()

    def test_symlink_outside_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "foreign.lean"
            target.write_text("@[category research open]\ntheorem fake : True := by sorry\n")
            (self.root / "FormalConjectures" / "escape.lean").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "escapes"):
                self.parse()

    def test_anonymous_identity_survives_line_movement_without_merging_content(self):
        text = '''namespace Questions
@[category research solved]
example : True := by trivial
@[category research solved]
example : 1 = 1 := by rfl
end Questions
'''
        path = self.source("Other/Anonymous.lean", text)
        before = self.parse()
        path.write_text("/- New module documentation. -/\n\n" + text)
        after = self.parse()
        self.assertEqual([item["source_item_id"] for item in before], [item["source_item_id"] for item in after])
        self.assertNotEqual(before[0]["source_item_id"], before[1]["source_item_id"])
        self.assertEqual(after[0]["source_line"], before[0]["source_line"] + 2)
        self.assertTrue(all(item["anonymous_declaration"] for item in after))
        self.assertIn("@sha256-", after[0]["source_item_id"])


if __name__ == "__main__":
    unittest.main()
