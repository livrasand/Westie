"""Tests for autonomous generation: facts -> hypotheses -> compositional text."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gittxt.facts import extract_diff_facts, analyze_python_ast, compare_symbols
from gittxt.inference import build_hypotheses
from gittxt.composer import CompositionalComposer



BASE = """def greet():
    print("hi")

def bye():
    print("bye")
"""

OUTPUT = """just a placeholder needed to keep diff valid"""


def make_diff(path, old_src, new_src, a_name=path if False else None):
    """Build a unified diff string for one .py file."""
    import difflib
    old_lines = old_src.splitlines(keepends=True) if old_src is not None else []
    new_lines = new_src.splitlines(keepends=True) if new_src is not None else []
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}", n=0, lineterm="\n"
    )
    header = f"diff --git a/{path} b/{path}\n"
    return header + "".join(diff)


class FactExtractionTests(unittest.TestCase):
    def test_extract_diff_facts_counts_lines(self):
        diff = make_diff("m.py", BASE, OUTPUT)
        facts = extract_diff_facts(diff)
        f = facts["files"]["m.py"]
        self.assertGreater(len(f["added"]), 0)
        self.assertGreater(len(f["removed"]), 0)

    def test_ast_symbols(self):
        syms = analyze_python_ast(BASE)
        self.assertEqual(sorted(syms["functions"].keys()), ["bye", "greet"])


class ScenarioTests(unittest.TestCase):
    """Each scenario: patch the engine's file access so tests don't touch a real repo."""

    def run_scenario(self, old_src, new_src, path="mod.py"):
        """Build ast facts via compare_symbols directly with a small harness that
        emulates build_ast_facts for one file."""
        old_syms = analyze_python_ast(old_src)
        new_syms = analyze_python_ast(new_src)
        per_file = {path: compare_symbols(old_syms, new_syms)}
        diff_facts = extract_diff_facts(make_diff(path, old_src, new_src))
        hyps = build_hypotheses(diff_facts, per_file)
        composer = CompositionalComposer()
        return composer.compose(hyps, diff_facts)

    def test_add_function(self):
        new = BASE + "\ndef extra():\n    pass\n"
        out = self.run_scenario(BASE, new)
        self.assertIn("Add function extra", out["text"])

    def test_modify_function(self):
        new = BASE.replace('print("hi")', 'print("hello")')
        new = new.replace("greet", "greet")  # keep same name
        out = self.run_scenario(BASE, new)
        self.assertIsNotNone(out["text"])
        # body-only change: no structural modification is expected beyond neutral
        self.assertTrue(out["text"])
        self.assertNotIn("Add function", out["text"])
        self.assertNotIn("Remove function", out["text"])

    def test_delete_function(self):
        old = BASE
        new = BASE.replace("def greet():\n    print(\"hi\")\n\n", "")
        out = self.run_scenario(old, new)
        self.assertIn("Remove function greet", out["text"])

    def test_condition_with_raise_added(self):
        new = BASE.replace(
            'def greet():\n    print("hi")',
            'def greet():\n    if not True:\n        raise ValueError("bad")'
        )
        out = self.run_scenario(BASE, new)
        self.assertIn("greet", out["text"])
        self.assertIn("Modify", out["text"])
        self.assertTrue("exception" in out["text"].lower() or "raise" in out["text"].lower())

    def test_read_error_low_confidence(self):
        old = "def a():\n    x = 1\n"
        facts = {"x.py": {"comparable": False, "read_error": True, "category": "source"}}
        hyps = build_hypotheses({}, facts)
        composer = CompositionalComposer()
        out = composer.compose(hyps, {})
        self.assertTrue("Modify file x.py" in out["text"])
        self.assertEqual(out["confidence"], 0.3)
        self.assertEqual(out["band"], "weak")
        self.assertTrue(out["claims"], "article ledger missing")

    def test_renamed_variable(self):
        old = "def a():\n    x = 1\n    return x\n"
        new = "def a():\n    y = 1\n    return y\n"
        out = self.run_scenario(old, new)
        # Rename is not structural in this MVP: expect neutral/unknown, not an invention
        self.assertFalse(out["text"].startswith("Add ") or out["text"].startswith("Remove "))

    def test_group_many_symbol_claims(self):
        class H:
            def __init__(self, claim):
                self.claim = claim
                self.confidence = 1.0
                self.supporting_facts = ["AST: evidence"]
                self.tier = "fact"
        hyps = [
            H("Add file gittxt/pkg.py"),
            H("Add function f1"), H("Add function f2"), H("Add function f3"),
            H("Add class C1"), H("Add class C2"),
            H("Remove function g1"), H("Remove function g2"), H("Remove function g3"),
        ]
        out = CompositionalComposer().compose(hyps, {})
        self.assertIn("Add file gittxt/pkg.py", out["text"])
        self.assertIn("Add 3 functions", out["text"])
        self.assertIn("Add class C1", out["text"])
        self.assertIn("Add class C2", out["text"])
        self.assertIn("Remove 3 functions", out["text"])
        self.assertNotIn("Add function f1", out["text"])
        self.assertIn("AST: evidence", out["facts_used"])
        self.assertIn("band", out)
        for claim in out["claims"]:
            self.assertIn(claim["claim"], out["text"])
            self.assertTrue(claim["evidence"])

    def test_new_file_folds_symbol_claims(self):
        class H:
            def __init__(self, claim, facts):
                self.claim = claim
                self.confidence = 1.0
                self.supporting_facts = facts
                self.tier = "fact"
        hyps = [
            H("Add file nf.py", ["git: nf.py is absent from HEAD",
                                 "AST: nf.py defines 4 functions and 0 classes"]),
        ] + [
            H(f"Add function f{i}", [f"AST: nf.py defines function f{i} not present before"])
            for i in range(1, 5)
        ]
        out = CompositionalComposer().compose(hyps, {})
        self.assertIn("Add file nf.py (4 functions)", out["text"])
        self.assertNotIn("Add function f1", out["text"])

    def test_move_function_between_files(self):
        src = "def mover():\n    return 42\n"
        facts = {
            "a.py": compare_symbols(analyze_python_ast(src), None),
            "b.py": compare_symbols(None, analyze_python_ast(src)),
        }
        hyps = build_hypotheses({}, facts)
        composer = CompositionalComposer()
        out = composer.compose(hyps, {})
        self.assertIn("Move function mover from a.py to b.py", out["text"])
        hyps = build_hypotheses({}, facts)
        self.assertFalse(any(h.claim.startswith("Remove function mover") for h in hyps))
        self.assertFalse(any(h.claim.startswith("Add function mover") for h in hyps))

    def test_comments_only(self):
        old = "def a():\n    # old note\n    pass\n"
        new = "def a():\n    # new note\n    pass\n"
        out = self.run_scenario(old, new)
        self.assertIn("comment", out["text"].lower())

    def test_ambiguous_change_neutral(self):
        old = "def a():\n    x = compute(h)\n    return x\n"
        new = "def a():\n    x = compute(g)\n    return x\n"
        out = self.run_scenario(old, new)
        self.assertLessEqual(out["confidence"], 0.5)
        self.assertEqual(out["confidence"], 0.0)
        self.assertEqual(out["band"], "weak")

    def test_mixed_add_and_remove(self):
        old = "def gone():\n    pass\n\n\ndef stay():\n    pass\n"
        new = "def new_func():\n    pass\n\n\ndef stay():\n    pass\n"
        out = self.run_scenario(old, new)
        self.assertIn("gone", out["text"])
        self.assertIn("new_func", out["text"])
        # identical bodies + name change -> rename claim (renames turned out as such)
        self.assertIn("rename", out["text"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
