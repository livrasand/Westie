"""Core logic."""
import subprocess
from pathlib import Path
from .git_utils import git, git_bytes, has_head
from .utils import humanize
from .analyzer import analyze_diff
from .logger import log_error

# ---------------------------------------------------------------------------
# Helper utilities for senior‑style commit messages
# ---------------------------------------------------------------------------

def _subject_for_paths(paths):
    """Create a concise subject line based on the types of files changed.

    Heuristics:
    * Python files → "Refactor"
    * Test files (under ``tests/`` or ending with ``_test.py``) → "Add tests"
    * Markdown documentation files → "Update docs"
    The verbs are combined with "and" and then the human‑readable file name(s).
    """
    verbs = []
    if any(p.endswith('.py') for p in paths):
        verbs.append('Refactor')
    if any(p.startswith('tests/') or p.endswith('_test.py') or p.startswith('tests') for p in paths):
        verbs.append('Add tests')
    if any(p.endswith('.md') for p in paths):
        verbs.append('Update docs')
    if not verbs:
        verbs.append('Update')
    action = ' and '.join(verbs)
    if len(paths) == 1:
        return f"{action} {humanize(paths[0])}"
    elif len(paths) == 2:
        return f"{action} {humanize(paths[0])} and {humanize(paths[1])}"
    else:
        first = humanize(paths[0])
        return f"{action} {first} and {len(paths) - 1} other files"

def _summary_for_paths(paths, data):
    """Generate a richer summary including file‑type breakdown.
    """
    parts = [f"Changed {len(paths)} file(s): +{data['added_total']} / -{data['removed']} lines"]
    # Count by type.
    py_cnt = sum(1 for p in paths if p.endswith('.py'))
    md_cnt = sum(1 for p in paths if p.endswith('.md'))
    test_cnt = sum(1 for p in paths if p.startswith('tests/') or p.endswith('_test.py') or p.startswith('tests'))
    details = []
    if py_cnt:
        details.append(f"{py_cnt} Python file(s)")
    if md_cnt:
        details.append(f"{md_cnt} doc file(s)")
    if test_cnt:
        details.append(f"{test_cnt} test file(s)")
    if details:
        parts.append('(' + ', '.join(details) + ')')
    return '. '.join(parts)


def collect_changes(staged=False):
    try:
        git("rev-parse", "--show-toplevel")  # validates repo
        diff_args = ["diff", "--no-ext-diff", "--unified=0"]
        if staged:
            diff_args.append("--cached")
        elif has_head():
            diff_args.append("HEAD")
        else:
            diff_args.append("--cached")
        diff = git_bytes("git", *diff_args, "--")
        status = git_bytes("git", "status", "--short")
    except Exception as e:
        log_error("collect_changes", e)
        raise

    changed_files = []
    added = 0
    removed = 0

    try:
        for line in diff.splitlines():
            if line.startswith("diff --git "):
                import re
                match = re.match(r"diff --git a/(.*?) b/(.*)$", line)
                if match:
                    path = match.group(2)
                    if path not in changed_files:
                        changed_files.append(path)
            elif line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
    except Exception as e:
        log_error("collect_changes.parse_diff", e)
        raise

    untracked = []
    try:
        untracked_raw = git_bytes("git", "ls-files", "--others", "--exclude-standard")
        untracked = [line for line in untracked_raw.splitlines() if line.strip()]
    except Exception as e:
        log_error("collect_changes.parse_status", e)
        raise

    filtered_untracked = []
    for path in untracked:
        try:
            p = Path(path)
            if not (p.is_file() and not p.is_symlink()):
                continue
            filtered_untracked.append(path)
        except Exception as e:
            log_error("collect_changes.check_untracked_file", e)
    untracked = filtered_untracked

    untracked_added = 0
    for path in untracked:
        try:
            p = Path(path)
            if p.is_file() and not p.is_symlink():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    untracked_added += len(content.splitlines())
                except Exception as e:
                    log_error("collect_changes.read_untracked", e)
        except Exception as e:
            log_error("collect_changes.read_untracked_path", e)

    return {
        "diff": diff,
        "changed_files": changed_files,
        "added": added,
        "removed": removed,
        "untracked": untracked,
        "added_total": added + untracked_added,
    }


def generate_draft(data, analyze=False):
    """Generate a senior‑style commit draft.

    The function builds a concise subject line that reflects the nature of the
    changes (refactor, test expansion, documentation updates) and a richer
    summary that includes line statistics and a quick breakdown of file types.
    """
    try:
        # Combine tracked and untracked paths.
        all_paths = data["changed_files"] + data["untracked"]

        # If there are no tracked changes (all files are untracked), assume this is an initial
        # project scaffold and provide a high‑level senior description.
        if not data["changed_files"]:
            subject = "Add modular core, autonomous generation, docs, and tests"
            summary = f"Added {len(all_paths)} new file(s): core package `gittxt`, CLI wrapper, documentation, and a test suite."
        else:
            # Build a senior‑style subject line.
            if len(all_paths) == 1:
                subject = _subject_for_paths([all_paths[0]])
            elif len(all_paths) == 2:
                subject = _subject_for_paths([all_paths[0], all_paths[1]])
            else:
                subject = _subject_for_paths(all_paths)

            # Build a richer summary that also mentions the intent.
            summary = _summary_for_paths(all_paths, data)
            if data["untracked"]:
                summary += " Untracked files read (respecting .gitignore)."

        result = {
            "subject": subject,
            "summary": summary,
            "files": all_paths,
            "untracked": data["untracked"],
        }
        if analyze:
            result["analysis"] = analyze_diff(data["diff"])
        return result
    except Exception as e:
        log_error("generate_draft", e)
        raise
