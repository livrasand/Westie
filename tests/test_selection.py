"""Regression tests for concept-based semantic selection (merging + subsumption)."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gittxt.facts import analyze_python_ast, compare_symbols
from gittxt.inference import Hypothesis, build_hypotheses
from gittxt.selection import select_hypotheses
from gittxt.composer import CompositionalComposer


def as_file_facts(path, old_src, new_src, imports_new=None):
    old = analyze_python_ast(old_src) if old_src is not None else None
    new = analyze_python_ast(new_src) if new_src is not None else None
    facts = compare_symbols(old, new)
    facts["_old_syms"] = old
    facts["_new_syms"] = new
    if imports_new is not None:
        facts["imports_new"] = imports_new
    return {path: facts}


def compose_from(hyps):
    return CompositionalComposer().compose(hyps, {})


def compose_text(hyps):
    return compose_from(hyps)["text"]


def hyp(action, *, claim, conf=0.9, path=None, name=None, kind="function",
        targets=None, count=0, tier="fact", extra=None):
    concept = {"action": action}
    if path is not None:
        concept["path"] = path
    if name is not None:
        concept["name"] = name
    concept["kind"] = kind
    if targets is not None:
        concept["targets"] = targets
    if count:
        concept["count"] = count
    if extra:
        concept.update(extra)
    h = Hypothesis(claim, conf, [f"synthetic: {claim}"], "structural", tier=tier)
    h.concept = concept
    return h


class TestSummaryMerging(unittest.TestCase):
    def test_overlapping_targets_merge_with_summed_count(self):
        hi = [hyp("add_tests", claim="Add 4 tests for pkg.a", count=4,
                  targets=["pkg.a"], path="x.py", extra={"file_new": True}),
              hyp("add_tests", claim="Add 2 tests for pkg.a and pkg.b", count=2,
                  targets=["pkg.a", "pkg.b"], path="y.py", extra={"file_new": True})]
        selected, suppressed = select_hypotheses(hi)
        merged = [h for h in selected if h.concept.get("action") == "add_tests"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].claim, "Add 6 tests for pkg.a and pkg.b")
        self.assertEqual(len(suppressed), 2)
        self.assertEqual(suppressed[0]["reason"], "merged into test summary")
        # Confidence cannot be inflated by merging.
        self.assertEqual(merged[0].confidence,
                         min(h.confidence for h in hi))

    def test_disjoint_targets_not_merged(self):
        hi = [hyp("add_tests", claim="Add 1 test for pkg.a", count=1,
                  targets=["pkg.a"], path="x.py"),
              hyp("add_tests", claim="Add 1 test for pkg.b", count=1,
                  targets=["pkg.b"], path="y.py")]
        selected, suppressed = select_hypotheses(hi)
        self.assertEqual(len(selected), 2)
        self.assertEqual(suppressed, [])

    def test_untargeted_merge_among_themselves(self):
        hi = [hyp("add_tests", claim="Add 3 tests", count=3, path="x.py"),
              hyp("add_tests", claim="Add 2 tests", count=2, path="y.py")]
        selected, _ = select_hypotheses(hi)
        tests_claims = [h.claim for h in selected]
        self.assertEqual(tests_claims, ["Add 5 tests"])

    def test_merge_is_deterministic_under_input_shuffle(self):
        hi = [hyp("add_tests", claim="Add 4 tests for pkg.a", count=4,
                  targets=["pkg.a"], path="x.py"),
              hyp("add_tests", claim="Add 2 tests for pkg.a", count=2,
                  targets=["pkg.a"], path="y.py")]
        results = set()
        for seed in range(6):
            shuffled = hi[:]
            random.Random(seed).shuffle(shuffled)
            selected, _ = select_hypotheses(shuffled)
            results.add(selected[0].claim)
        self.assertEqual(results, {"Add 6 tests for pkg.a"})

    def test_confidence_of_merged_clause_is_min_of_members(self):
        hi = [hyp("add_tests", claim="Add 4 tests for pkg.a", count=4,
                  conf=0.4, targets=["pkg.a"], path="x.py"),
              hyp("add_tests", claim="Add 2 tests for pkg.a", count=2,
                  conf=0.8, targets=["pkg.a"], path="y.py")]
        selected, _ = select_hypotheses(hi)
        self.assertEqual(selected[-1].confidence, 0.4)


class ModularizeSubsumption(unittest.TestCase):
    def modular(self, *, entry="entry.py", moved_map=None, new_files=None):
        concept = {"action": "modularize", "entry": entry,
                   "moved_map": moved_map,
                   "moved": sorted({n for ns in (moved_map or {}).values()
                                    for n in ns}),
                   "new_files": list(new_files or []),
                   "module_count": len(new_files or [])}
        h = hyp("modularize", claim=f"Modularize {entry}", kind=None)
        h.concept = concept
        return h

    def test_moves_and_file_adds_covered(self):
        mod = self.modular(
            moved_map={"pkg/new.py": ["f1", "f2"]},
            new_files=["pkg/new.py"])
        others = [
            hyp("add_file", claim="Add file pkg/new.py",
                path="pkg/new.py", kind=None),
            hyp("move", claim="Move function f1 from entry.py to pkg/new.py",
                name="f1", path="entry.py", extra={"from": "entry.py",
                                                   "to": "pkg/new.py"}),
            hyp("remove_symbol", claim="Remove function f1",
                name="f1", path="entry.py"),
        ]
        selected, suppressed = select_hypotheses([mod] + others)
        self.assertEqual([h.claim for h in selected], [mod.claim])
        self.assertEqual(len(suppressed), 3)

    def test_partial_coverage_keeps_unrelated_claims(self):
        mod = self.modular(
            moved_map={"pkg/new.py": ["f1", "f2"]},
            new_files=["pkg/new.py"])
        others = [
            hyp("add_file", claim="Add file other/other.py",
                path="other/other.py", kind=None),
            hyp("add_symbol", claim="Add function unrelated",
                name="unrelated", path="other/other.py"),
            hyp("move", claim="Move function f9 from entry.py to elsewhere.py",
                name="f9", path="entry.py", extra={"from": "entry.py",
                                                   "to": "elsewhere.py"}),
        ]
        selected, _ = select_hypotheses([mod] + others)
        claims = {h.claim for h in selected}
        self.assertEqual(claims,
                         {mod.claim, "Add file other/other.py",
                          "Add function unrelated",
                          "Move function f9 from entry.py to elsewhere.py"})

    def test_symbols_inside_covered_package_suppressed(self):
        mod = self.modular(
            moved_map={"pkg/new.py": ["f1", "f2"]},
            new_files=["pkg/new.py"])
        others = [
            hyp("add_symbol", claim="Add function helper",
                name="helper", path="pkg/new.py"),
            hyp("add_symbol", claim="Add class Thing", name="Thing",
                kind="class", path="pkg/util.py"),
            hyp("add_file", claim="Add file pkg/__init__.py",
                path="pkg/__init__.py", kind=None),
        ]
        selected, suppressed = select_hypotheses([mod] + others)
        self.assertEqual([h.claim for h in selected], [mod.claim])
        self.assertEqual(len(suppressed), 3)

    def test_mixed_unrelated_moves_elsewhere_kept(self):
        mod = self.modular(
            moved_map={"pkg/new.py": ["f1", "f2"]},
            new_files=["pkg/new.py"])
        unrelated_move = hyp("move", claim="Move function f9 from other.py "
                                           "to pkg/other.py",
                             name="f9", path="other.py",
                             extra={"from": "other.py", "to": "pkg/other.py"})
        selected, _ = select_hypotheses([mod, unrelated_move])
        self.assertEqual([h.claim for h in selected],
                         [mod.claim, unrelated_move.claim])


class EndToEndScenarios(unittest.TestCase):
    def test_modularization_scenario_composes_compactly(self):
        entry_old = ("def f1():\n    return 1\n"
                     "def f2():\n    return 2\n"
                     "def main():\n    main()\n")
        entry_new = "def main():\n    f1()\n\nimport pkg.new\n"
        hyps = build_hypotheses(
            {},
            as_file_facts("entry.py", entry_old, entry_new)
            | as_file_facts("pkg/new.py", None,
                            "def f1():\n    return 1\n"
                            "def f2():\n    return 2\n"
                            "def main():\n    main()\n")
            | as_file_facts("pkg/newer.py", None, "def g():\n    return 0\n"))
        selected, suppressed = select_hypotheses(hyps)
        text = compose_text(selected)
        self.assertIn("Modularize entry.py", text)
        # Symbol noise from covered files stays out of the narrative.
        self.assertNotIn("Add function f1", text)
        self.assertNotIn("Add function f2", text)

    def test_independent_behavioral_changes_preserved(self):
        facts = (as_file_facts(
            "a.py", "def go(x):\n    return x\n",
            "def go(x):\n    if x:\n        return x\n    return 0\n")
            | as_file_facts(
                "b.py", "def hop(x):\n    return 0\n",
                "def hop(x):\n    if x:\n        return 0\n    return 1\n"))
        selected, suppressed = select_hypotheses(
            build_hypotheses({}, facts))
        text = compose_text(selected)
        self.assertIn("Modify function go (control flow changed)", text)
        self.assertIn("Modify function hop", text)
        self.assertEqual(suppressed, [])

    def test_docs_and_config_last_in_ordering(self):
        hi = [
            hyp("modify_file", claim="Modify file notes.md", path="notes.md",
                kind=None, extra={"category": "doc"}),
            hyp("modify_file", claim="Modify file settings.json",
                path="settings.json", kind=None,
                extra={"category": "config"}),
            hyp("add_file", claim="Add file code.py", path="code.py", kind=None,
                extra={"category": "code"}),
        ]
        # markdown category parsing may differ; force secondary flag via concept
        for h in hi:
            if h.claim.endswith("notes.md"):
                h.category = "doc"
            if h.claim.endswith("settings.json"):
                h.category = "config"
            if h.claim.endswith("code.py"):
                h.category = "code"
        text = compose_text(hi)
        idx_doc = text.find("notes.md")
        idx_cfg = text.find("settings.json")
        idx_code = text.find("code.py")
        self.assertGreater(idx_doc, idx_code, text)
        self.assertGreater(idx_cfg, idx_code, text)

    def test_empty_input(self):
        selected, suppressed = select_hypotheses([])
        self.assertEqual((selected, suppressed), ([], []))

    def test_single_file_standard_output(self):
        facts = as_file_facts(
            "a.py", "def pick(x):\n    return x\n",
            "def pick(x):\n    if x:\n        return x\n    return 0\n")
        selected, _ = select_hypotheses(build_hypotheses({}, facts))
        text = compose_text(selected)
        self.assertIn("Modify function pick (control flow changed)", text)
        self.assertNotIn("Add file", text)

    def test_no_double_counting_across_merge(self):
        hi = [hyp("add_tests", claim="Add 4 tests for pkg.a", count=4,
                  targets=["pkg.a"], path="t1.py"),
              hyp("add_tests", claim="Add 4 tests for pkg.a", count=4,
                  targets=["pkg.a"], path="t2.py")]
        selected, _ = select_hypotheses(hi)
        counts = [h for h in selected
                  if h.concept.get("action") == "add_tests"]
        self.assertEqual([h.claim for h in counts], ["Add 8 tests for pkg.a"])


if __name__ == "__main__":
    unittest.main()
