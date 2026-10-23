"""Autonomous generator - separates extraction, inference, generation."""
from .ast_engine import build_facts, import_symbols_from_bytes, worktree_state
from .facts import analyze_generic, compare_symbols
from .inference import build_hypotheses
from .selection import select_hypotheses
from .composer import CompositionalComposer
from .logger import log_error
from .verify import run_verification


def add_untracked(facts_by_file, untracked):
    for path in untracked or []:
        if path in facts_by_file:
            continue
        new_bytes, new_state = worktree_state(path)
        if new_state == "error":
            facts_by_file[path] = {"comparable": False, "read_error": True,
                                   "category": new_state or "source"}
            continue
        if path.endswith(".py") and import_symbols_from_bytes(new_bytes):
            syms = import_symbols_from_bytes(new_bytes)
            facts_by_file[path] = compare_symbols(None, syms)
            facts_by_file[path]["_new_syms"] = syms
        else:
            facts_by_file[path] = analyze_generic(path, None, new_bytes)


def generate_autonomous(diff_text, staged=False, untracked=None):
    try:
        diff_facts, facts_by_file = build_facts(diff_text, staged=staged)
        add_untracked(facts_by_file, untracked)
        hypotheses = build_hypotheses(diff_facts, facts_by_file)
        selected, suppressed = select_hypotheses(hypotheses)
        composer = CompositionalComposer()
        result = composer.compose(selected, diff_facts)
        result = run_verification(result, staged=staged)
        result["suppressed_claims"] = suppressed
        result["hypotheses"] = [
            {"claim": h.claim, "confidence": h.confidence,
             "supporting_facts": h.supporting_facts, "type": h.type}
            for h in hypotheses
        ]
        result["facts_by_file"] = facts_by_file
        return result
    except Exception as e:
        log_error("generate_autonomous", e)
        raise
