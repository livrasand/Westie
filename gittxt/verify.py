"""Claim validation — "verified" is a validation status, not a synonym for plausible.

This module defines the single validation procedure that may stamp the
"verified" band: every emitted claim is re-checked against the repository
using git plumbing (git cat-file -e) rather than the extraction paths that
created it.

- Claims about file presence (Add file / Remove file) are verifiable.
- Structural, relational and interpretive claims are attributed to AST/diff
  evidence, which was already direct observation; re-running the same
  observer would not be independent, so they are reported as
  "not-verified" by this procedure and keep their evidence-based band.

An overall "verified" band is only produced when ALL emitted claims pass
this procedure; a single not-verifiable claim keeps the evidence band.
"""
import re
import subprocess
from pathlib import Path

from .inference import CONF, confidence_band

PROCEDURE = ("independent re-check of file-presence claims with git plumbing "
             "(git cat-file -e HEAD:<path> / :<path>) plus worktree checks")


def _blob_exists(path, ref):
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.returncode == 0


def _file_claim(claim):
    m = re.match(r"^(Add file |Remove file )(.+?)( \(.+\))?$", claim)
    if not m:
        return None
    is_add = m.group(1).strip() == "Add file"
    return is_add, m.group(2)


def run_verification(result, staged=False):
    """Re-check claims; set verification metadata and possibly the verified band."""
    ledger = result.get("claims", [])
    passed = failed = not_verifiable = 0
    for entry in ledger:
        parsed = _file_claim(entry["claim"])
        git_fact = CONF["git_fact"]
        if parsed is None or entry["confidence"] != git_fact:
            entry["verdict"] = "not-verified"
            not_verifiable += 1
            continue
        is_add, path = parsed
        exists_head = _blob_exists(path, "HEAD")
        if staged:
            exists_new = _blob_exists(path, ":")
            ok = (not exists_head and exists_new) if is_add else (exists_head and not exists_new)
        else:
            worktree = Path(path).is_file()
            ok = (not exists_head and worktree) if is_add else (exists_head and not worktree)
        entry["verdict"] = "verified" if ok else "failed"
        passed += ok
        failed += (not ok)

    result["verification"] = {
        "procedure": PROCEDURE,
        "passed": passed,
        "failed": failed,
        "not_verifiable": not_verifiable,
    }
    if failed == 0 and passed > 0 and not_verifiable == 0:
        result["band"] = "verified"
    return result
