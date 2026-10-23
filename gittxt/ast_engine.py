"""Engine: builds per-file facts for any file type (AST for Python, generic otherwise)."""
import ast
import subprocess
from pathlib import Path

from .facts import (
    extract_diff_facts, analyze_python_ast, compare_symbols, analyze_generic,
    classify_path, looks_binary,
)
from .git_utils import git


def blob_state(ref, path):
    """Read a blob. Returns (bytes | None, state) where state in
    "absent" | "ok" | "error" — absence of the file and read failure are distinct."""
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if probe.returncode != 0:
        return None, "absent"   # path does not exist in ref/index
    result = subprocess.run(
        ["git", "cat-file", "-p", f"{ref}:{path}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None, "error"    # exists but unreadable (e.g. submodule, corrupt, perms)
    return result.stdout, "ok"


def worktree_state(path):
    p = Path(path)
    if not p.is_file():
        return None, "absent"   # deleted from worktree (or never existed)
    try:
        return p.read_bytes(), "ok"
    except OSError:
        return None, "error"    # exists but unreadable (perms, special file)


def get_old_new(path, staged):
    if staged:
        old, old_state = blob_state("HEAD", path)
        new, new_state = blob_state("", path)
    else:
        old, old_state = blob_state("HEAD", path)
        new, new_state = worktree_state(path)
    return (old, new), (old_state, new_state)


def import_symbols_from_bytes(data):
    if data is None:
        return None
    try:
        return analyze_python_ast(data.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def build_facts(diff_text, staged=False):
    """Returns (diff_facts, facts_by_file). facts_by_file includes every diff'd file."""
    diff_facts = extract_diff_facts(diff_text)
    facts_by_file = {}

    for path in diff_facts["files"]:
        (old_bytes, new_bytes), (old_state, new_state) = get_old_new(path, staged)

        # If either version exists but couldn't be read, we cannot compare safely.
        if "error" in (old_state, new_state):
            facts_by_file[path] = {
                "comparable": False,
                "read_error": True,
                "category": classify_path(path),
            }
            continue

        if path.endswith(".py"):
            old_syms = import_symbols_from_bytes(old_bytes)
            new_syms = import_symbols_from_bytes(new_bytes)
            if old_syms is not None or new_syms is not None:
                facts_by_file[path] = compare_symbols(old_syms, new_syms)
                facts_by_file[path]["_old_syms"] = old_syms
                facts_by_file[path]["_new_syms"] = new_syms
                continue

        facts_by_file[path] = analyze_generic(path, old_bytes, new_bytes)

    return diff_facts, facts_by_file
