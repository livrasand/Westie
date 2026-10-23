"""Thin wrapper to expose the git‑text CLI as a console‑script entry point.
It loads the original `git-text.py` (which lives alongside this file) and
executes its `main()` function.
"""
import importlib.util
from pathlib import Path
import sys

def _load_original():
    script_path = Path(__file__).with_name("git-text.py")
    spec = importlib.util.spec_from_file_location("git_text_cli", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module

def main() -> int:
    """Run the original CLI and return its exit status.
    The original script already handles argument parsing and printing.
    """
    mod = _load_original()
    # The original `main` returns an int and the `if __name__ == "__main__"`
    # block raises SystemExit(main()). We just call it and return the int.
    return mod.main()

if __name__ == "__main__":
    sys.exit(main())
