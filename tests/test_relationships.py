"""Regression tests for cross-file relations, tiers, verification and ordering."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gittxt.facts import analyze_python_ast, compare_symbols, extract_diff_facts
from gittxt.inference import (build_hypotheses, CONF, pair_copies, pair_moves,
                              pair_renames)
from gittxt.composer import CompositionalComposer
from gittxt.verify import run_verification


def as_file_facts(path, old_src, new_src):
    old = analyze_python_ast(old_src) if old_src is not None else None
    new = analyze_python_ast(new_src) if new_src is not None else None
    facts = compare_symbols(old, new)
    facts["_old_syms"] = old
    facts["_new_syms"] = new
    return {path: facts}


def compose_from(hyps):
    return CompositionalComposer().compose(hyps, {})


class RelationTests(unittest.TestCase):
    """pair_moves / pair_copies / pair_renames on synthetic facts."""

    def test_identical_move_is_relation_not_fact(self):
        src = "def pick(x):\n    return x\n"
        moves = pair_moves(as_file_facts("a.py", src, None) | as_file_facts("b.py", None, src))
        self.assertEqual(len(moves), 1)
        _k, _n, from_p, to_p, mtype, conf = moves[0]
        self.assertEqual((from_p, to_p, mtype), ("a.py", "b.py", "identical"))
        self.assertEqual(conf, CONF["relation"])
        hyps = build_hypotheses({}, as_file_facts("a.py", src, None) | as_file_facts("b.py", None, src))
        move = [h for h in hyps if h.claim.startswith("Move function pick")][0]
        self.assertEqual(move.tier, "relation")
        self.assertLess(move.confidence, CONF["ast_presence"])

    def test_copied_function_is_copy_not_move(self):
        src = "def twin():\n    return 7\n"
        facts = as_file_facts("a.py", src, src) | as_file_facts("b.py", None, src)
        copies = pair_copies(facts)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0][0], "function")
        self.assertEqual(copies[0][1], "twin")
        self.assertEqual(copies[0][2], "a.py")
        self.assertEqual(copies[0][3], "b.py")
        hyps = build_hypotheses({}, facts)
        self.assertTrue(any(h.claim.startswith("Copy function twin") for h in hyps))
        self.assertFalse(any(h.claim.startswith("Move function twin") for h in hyps))

    def test_removed_not_copy(self):
        src = "def twin():\n    return 7\n"
        facts = as_file_facts("a.py", None, src) | as_file_facts("b.py", src, None)
        self.assertEqual(pair_copies(facts), [])
        self.assertEqual(len(pair_moves(facts)), 1)

    def test_rename_within_file_suppresses_add_remove(self):
        old = "def fetch():\n    return DATA\n"
        new = "def retrieve():\n    return DATA\n"
        facts = as_file_facts("a.py", old, new)
        renames = pair_renames(facts)
        self.assertEqual(len(renames), 1)
        kind, new_name, old_name, path, _conf = renames[0]
        self.assertEqual((new_name, old_name, path), ("retrieve", "fetch", "a.py"))
        hyps = build_hypotheses({}, facts)
        self.assertTrue(any(h.claim.startswith("Rename function fetch to retrieve") for h in hyps))
        self.assertFalse(any(h.claim.startswith("Remove function fetch") for h in hyps))
        self.assertFalse(any(h.claim.startswith("Add function retrieve") for h in hyps))

    def test_ambiguous_rename_not_claimed(self):
        old = "def old_name():\n    return 1\n"
        new = ("def new_a():\n    return 1\n\n\ndef new_b():\n    return 1\n")
        facts = as_file_facts("a.py", old, new)
        self.assertEqual(pair_renames(facts), [])
        hyps = build_hypotheses({}, facts)
        self.assertFalse(any(h.claim.startswith("Rename") for h in hyps))

    def test_similar_names_not_mispaired(self):
        body = "def __impl__(self, request):\n    return request.path\n"
        body = body.replace("__impl__", "handler")
        src_old = "def handler(request):\n    return None\n"
        facts = as_file_facts("a.py", src_old, None)
        facts |= as_file_facts("b.py", None,
                               "def handler_variant(request):\n    return 1\n")
        hyps = build_hypotheses({}, facts)
        self.assertFalse(any(h.claim.startswith("Move") for h in hyps))
        self.assertFalse(any(h.claim.startswith("Copy") for h in hyps))

    def test_move_body_changed_flag(self):
        src_old = "def pick(x):\n    return x\n"
        src_new = "def pick(x):\n    return x + 1\n"
        facts = as_file_facts("a.py", src_old, None) | as_file_facts("b.py", None, src_new)
        hyps = build_hypotheses({}, facts)
        self.assertTrue(any(h.claim.startswith("Modify moved function pick") for h in hyps))


class ModularizationTests(unittest.TestCase):
    def _facts(self):
        entry_old = ("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n\n\n"
                     "def main():\n    alpha()\n    beta()\n")
        entry_new = "from alpha_mod import alpha\nfrom beta_mod import beta\n\ndef main():\n    alpha()\n    beta()\n"
        lib1 = "def alpha():\n    return 1\n"
        lib2 = "def beta():\n    return 2\n"
        facts = {}
        facts |= as_file_facts("entry.py", entry_old, entry_new)
        facts |= as_file_facts("alpha_mod.py", None, lib1)
        facts |= as_file_facts("beta_mod.py", None, lib2)
        return facts

    def test_split_module_triggers_modularization(self):
        hyps = build_hypotheses({}, self._facts())
        interps = [h for h in hyps if h.tier == "interpretation"]
        self.assertEqual(len(interps), 1)
        h = interps[0]
        self.assertEqual(h.claim, "Modularize entry.py into 2 local modules")
        self.assertEqual(h.confidence, CONF["interpretation"])
        self.assertTrue(any("imports" in f for f in h.supporting_facts))

    def test_no_imports_no_modularization(self):
        old = "def big():\n    return 1\n"
        new = "def other():\n    return 2\n"
        facts = as_file_facts("entry.py", old, new)
        hyps = build_hypotheses({}, facts)
        self.assertFalse([h for h in hyps if h.tier == "interpretation"])

    def test_two_moved_funcs_required(self):
        old = "def big():\n    return 1\n"
        new = "from delta_mod import delta\n\ndef big():\n    return 1\n"
        facts = as_file_facts("entry.py", old, new) | \
            as_file_facts("delta_mod.py", None, "def delta():\n    return 9\n")
        hyps = build_hypotheses({}, facts)
        self.assertFalse([h for h in hyps if h.tier == "interpretation"])


class TestRelationTests(unittest.TestCase):
    def test_new_test_file_claim(self):
        test_src = ("import unittest\nfrom gittxt.core import collect_changes\n\n"
                    "class SampleTests(unittest.TestCase):\n"
                    "    def test_ok(self):\n        self.assertTrue(True)\n")
        facts = {}
        facts |= as_file_facts("gittxt/core.py", "def old():\n    pass\n", "def x():\n    pass\n")
        facts |= as_file_facts("tests/t_generic.py", None, test_src)
        hyps = build_hypotheses({}, facts)
        self.assertIn("Add file tests/t_generic.py", [h.claim for h in hyps])
        tclaims = [h for h in hyps if re.match(r"^Add \d+ tests?\b", h.claim)]
        self.assertEqual(len(tclaims), 1)
        self.assertEqual(tclaims[0].claim, "Add 1 test for gittxt.core")
        self.assertEqual(tclaims[0].tier, "relation")
        self.assertFalse(any(h.claim.startswith("Add function test_") for h in hyps))

    def test_stdlib_only_tests_claim_has_no_target(self):
        test_src = ("import unittest\n\ndef test_one(self):\n    pass\n\n"
                    "def test_two(self):\n    pass\n")
        facts = as_file_facts("tests/t_only.py", None, test_src)
        hyps = build_hypotheses({}, facts)
        tclaims = [h for h in hyps if re.match(r"^Add \d+ tests?$", h.claim)]
        self.assertEqual(len(tclaims), 1)
        self.assertEqual(tclaims[0].confidence, CONF["ast_presence"])


class OrderingTests(unittest.TestCase):
    def test_docs_and_config_rank_last(self):
        class H:
            def __init__(self, claim, cat=None, tier="fact", conf=1.0):
                self.claim = claim
                self.confidence = conf
                self.supporting_facts = ["x: evidence"]
                self.tier = tier
                self.category = cat
        hyps = [
            H("Add function helper_a", tier="fact"),
            H("Modify README.md", cat="doc"),
            H("Modify .gitignore", cat="config"),
            H("Modify lib.py"),
        ]
        out = compose_from(hyps)
        text = out["text"]
        # helper/detail claims come before doc/config leftovers
        self.assertLess(text.index("helper_a"), text.index("README.md"))
        self.assertLess(text.index("helper_a"), text.index(".gitignore"))

    def test_interpretation_leads_and_relations_before_facts(self):
        class H:
            def __init__(self, claim, tier, conf=0.9):
                self.claim = claim
                self.confidence = conf
                self.supporting_facts = ["x: evidence"]
                self.tier = tier
                self.category = None
        hyps = [
            H("Add file main.py", "fact"),
            H("Move function go from a.py to b.py", "relation"),
            H("Modularize git.py into the gittxt package", "interpretation", 0.7),
        ]
        out = compose_from(hyps)
        i = out["text"].index
        self.assertLess(i("Modularize"), i("Move"))
        self.assertLess(i("Move"), i("Add file"))

    def test_deterministic_across_dict_order(self):
        old = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
        new = ("from alpha_mod import alpha\nfrom beta_mod import beta\n\n"
               "def main():\n    alpha()\n    beta()\n")
        facts_a = {}
        facts_a |= as_file_facts("entry.py", old, new)
        facts_a |= as_file_facts("alpha_mod.py", None, "def alpha():\n    return 1\n")
        facts_a |= as_file_facts("beta_mod.py", None, "def beta():\n    return 2\n")
        facts_b = {}
        facts_b |= as_file_facts("beta_mod.py", None, "def beta():\n    return 2\n")
        facts_b |= as_file_facts("alpha_mod.py", None, "def alpha():\n    return 1\n")
        facts_b |= as_file_facts("entry.py", old, new)
        out_a = compose_from(build_hypotheses({}, facts_a))
        out_b = compose_from(build_hypotheses({}, facts_b))
        self.assertEqual(out_a["text"], out_b["text"])


class VerificationTests(unittest.TestCase):
    def test_band_never_verified_without_validation(self):
        src = "def pick(x):\n    return x\n"
        out = compose_from(build_hypotheses({}, as_file_facts("a.py", src, None)
                                            | as_file_facts("b.py", None, src)))
        self.assertNotEqual(out["band"], "verified")

    def test_verified_only_when_all_claims_pass_procedure(self):
        class H:
            def __init__(self, claim, conf=1.0):
                self.claim = claim
                self.confidence = conf
                self.supporting_facts = ["git: presence claim"]
                self.tier = "fact"
                self.category = None

        def make_repo(files):
            tmp = Path(tempfile.mkdtemp(prefix="gt-verifytest-"))
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                subprocess.run(["git", "init", "-q"], check=True)
                subprocess.run(["git", "checkout", "-q", "-b", "main"], check=True,
                               capture_output=True)
                for name, content in files.items():
                    p = tmp / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(content)
                subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
                subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                "commit", "-qm", "base"], check=True, capture_output=True)
            finally:
                os.chdir(cwd)
            return tmp, cwd

        def in_repo(tmp, cwd, block):
            os.chdir(tmp)
            try:
                return block()
            finally:
                os.chdir(cwd)

        # Part 1: a mixed ledger -> verified is impossible
        base_tmp, cwd = make_repo({"gone.txt": "x", "keep.py": "y"})
        (base_tmp / "gone.txt").unlink()
        result = compose_from([
            H("Remove file gone.txt"),
            H("Move function go from a.py to b.py", 0.9),
        ])
        result = in_repo(base_tmp, cwd, lambda: run_verification(result))
        self.assertNotEqual(result["band"], "verified")
        self.assertEqual(result["verification"]["not_verifiable"], 1)
        self.assertEqual(result["verification"]["passed"], 1)

        # Part 2: every claim re-checked -> verified band
        add_tmp, cwd = make_repo({"base.py": "y"})
        (add_tmp / "new.txt").write_text("c")
        result = compose_from([H("Add file new.txt")])
        result = in_repo(add_tmp, cwd, lambda: run_verification(result))
        self.assertEqual(result["band"], "verified")
        self.assertEqual(result["verification"]["failed"], 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
