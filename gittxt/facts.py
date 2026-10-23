"""Fact extraction from git diffs and AST - no inference."""
import ast
import re
from pathlib import Path


def extract_diff_facts(diff_text):
    """Extract only observable facts from unified diff."""
    facts = {
        "files": {},  # path -> {added: [...], removed: [...]}
    }
    current_file = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line)
            if m:
                current_file = m.group(2)
                if current_file not in facts["files"]:
                    facts["files"][current_file] = {"added": [], "removed": []}
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            if current_file:
                facts["files"][current_file]["added"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            if current_file:
                facts["files"][current_file]["removed"].append(line[1:])
    return facts


def analyze_python_ast(source):
    """Analyze Python source into structured symbols. Returns None if unparseable."""
    if source is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    symbols = {
        "functions": {},
        "classes": {},
        "imports": [],
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            symbols["functions"][node.name] = {
                "args": [a.arg for a in node.args.args],
                "body": ast.unparse(node).strip(),
                "lineno": node.lineno,
                "has_raise": any(isinstance(n, ast.Raise) for n in ast.walk(node)),
                "has_return": any(isinstance(n, ast.Return) for n in ast.walk(node)),
                "has_if": any(isinstance(n, (ast.If,)) for n in ast.walk(node)),
            }
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols["functions"][node.name] = {
                "args": [a.arg for a in node.args.args],
                "body": ast.unparse(node).strip(),
                "lineno": node.lineno,
                "has_raise": any(isinstance(n, ast.Raise) for n in ast.walk(node)),
                "has_return": any(isinstance(n, ast.Return) for n in ast.walk(node)),
                "has_if": any(isinstance(n, (ast.If,)) for n in ast.walk(node)),
                "async": True,
            }
        elif isinstance(node, ast.ClassDef):
            symbols["classes"][node.name] = {"lineno": node.lineno, "body": ast.unparse(node).strip()}
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            symbols["imports"].append(ast.unparse(node) if hasattr(ast, 'unparse') else "")
    symbols["test_funcs"] = [
        n for n, f in symbols["functions"].items() if n.startswith("test_")
    ]
    symbols["test_classes"] = [
        n for n in symbols["classes"]
        if n.endswith("TestCase") or n.startswith("Test")
    ]
    symbols["is_tests"] = bool(symbols["test_funcs"] or symbols["test_classes"])
    return symbols


def compare_symbols(old_syms, new_syms):
    """Compare symbol sets - returns structural diff facts."""
    if old_syms is None and new_syms is None:
        return {"comparable": False}
    if old_syms is None:
        return {"comparable": True, "file_new": True,
                "added_funcs": sorted(new_syms["functions"]) if new_syms else [],
                "added_classes": sorted(new_syms["classes"]) if new_syms else [],
                "bodies_new": {n: new_syms["functions"].get(n, {}).get("body") for n in new_syms["functions"]} if new_syms else {},
                "class_bodies_new": {n: new_syms["classes"].get(n, {}).get("body") for n in new_syms["classes"]} if new_syms else {},
                "imports_new": list(new_syms["imports"]) if new_syms else [],
                "test_funcs": new_syms["test_funcs"] if new_syms else [],
                "is_tests": new_syms["is_tests"] if new_syms else False}
    if new_syms is None:
        return {"comparable": True, "file_removed": True,
                "removed_funcs": sorted(old_syms["functions"]) if old_syms else [],
                "bodies_old": {n: old_syms["functions"].get(n, {}).get("body") for n in old_syms["functions"]} if old_syms else {},
                "class_bodies_old": {n: old_syms["classes"].get(n, {}).get("body") for n in old_syms["classes"]} if old_syms else {},
                "imports_old": list(old_syms["imports"]) if old_syms else [],
                "is_tests": old_syms["is_tests"] if old_syms else False}
    
    old_funcs = set(old_syms["functions"].keys())
    new_funcs = set(new_syms["functions"].keys())
    old_classes = set(old_syms["classes"].keys())
    new_classes = set(new_syms["classes"].keys())
    
    facts = {
        "comparable": True,
        "added_funcs": sorted(list(new_funcs - old_funcs)),
        "removed_funcs": sorted(list(old_funcs - new_funcs)),
        "added_classes": sorted(list(new_classes - old_classes)),
        "removed_classes": sorted(list(old_classes - new_classes)),
        "modified_funcs": [],
        "bodies_old": {n: old_syms["functions"].get(n, {}).get("body")
                       for n in old_funcs},
        "bodies_new": {n: new_syms["functions"].get(n, {}).get("body")
                       for n in new_funcs},
        "class_bodies_old": {n: old_syms["classes"].get(n, {}).get("body")
                             for n in old_classes},
        "class_bodies_new": {n: new_syms["classes"].get(n, {}).get("body")
                             for n in new_classes},
        "imports_old": list(old_syms["imports"]),
        "imports_new": list(new_syms["imports"]),
        "added_imports": sorted(set(new_syms["imports"]) - set(old_syms["imports"])),
        "test_funcs": new_syms["test_funcs"],
        "is_tests": old_syms["is_tests"] or new_syms["is_tests"],
    }
    
    for name in old_funcs & new_funcs:
        old_f = old_syms["functions"][name]
        new_f = new_syms["functions"][name]
        changes = []
        if old_f.get("has_raise") != new_f.get("has_raise"):
            changes.append("raise_changed")
        if old_f.get("has_if") != new_f.get("has_if"):
            changes.append("conditional_changed")
        if old_f.get("args") != new_f.get("args"):
            changes.append("signature_changed")
        if changes:
            facts["modified_funcs"].append({"name": name, "changes": changes})
    
    return facts


BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
               ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".whl", ".so",
               ".dylib", ".dll", ".exe", ".bin", ".class", ".pyc", ".lock"}
CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
               ".env", ".xml", ".properties", ".plist", ".editorconfig"}
DOC_EXTS = {".md", ".txt", ".rst", ".adoc", ".html", ".css", ".csv"}
DATA_EXTS = {".sql", ".db", ".proto", ".graphql"}

BINARY_HINTS = (b"PK\x03\x04", b"GIF8", b"\x89PNG", b"%PDF", b"MZ", b"\x7fELF",
                b"\xca\xfe\xba\xbe")

COMMENT_PREFIXES = ("#", "//", "--", ";", "'", "REM")


def classify_path(path):
    ext = Path(path).suffix.lower()
    name = Path(path).name.lower()
    if ext in BINARY_EXTS or name.endswith(".lock"):
        return "binary"
    if ext in CONFIG_EXTS or name in (".gitignore", ".dockerignore", ".babelrc", ".npmrc"):
        return "config"
    if ext in DOC_EXTS:
        return "doc"
    if ext in DATA_EXTS:
        return "data"
    return "source"


def looks_binary(data):
    if data is None:
        return False
    return b"\x00" in data[:8192] or data.startswith(BINARY_HINTS)


def analyze_generic(path, old_data, new_data):
    """Observable facts for any file type. old_data/new_data are bytes or None."""
    category = classify_path(path)
    fact = {"comparable": True, "category": category,
            "old_lines": None, "new_lines": None}
    if category == "binary" or looks_binary(old_data) or looks_binary(new_data):
        fact["binary_content"] = True
        return fact
    if old_data is None:
        fact["file_new"] = True
    elif new_data is None:
        fact["file_removed"] = True
    old_text = old_data.decode("utf-8", "replace") if old_data is not None else None
    new_text = new_data.decode("utf-8", "replace") if new_data is not None else None
    fact["old_lines"] = len(old_text.splitlines()) if old_text is not None else None
    fact["new_lines"] = len(new_text.splitlines()) if new_text is not None else None
    # comment-only edit check (a conservative, observable fact)
    if not fact.get("file_new", False) and not fact.get("file_removed", False) \
            and old_text is not None and new_text is not None:
        old_body = [l for l in old_text.splitlines()
                    if l.strip() and not l.strip().startswith(COMMENT_PREFIXES)]
        new_body = [l for l in new_text.splitlines()
                    if l.strip() and not l.strip().startswith(COMMENT_PREFIXES)]
        fact["comment_only"] = old_body == new_body and old_text != new_text
    return fact


def strip_block_comments(text):
    if text is None:
        return None
    import re
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(
        l for l in text.splitlines()
        if l.strip() and not l.strip().startswith(COMMENT_PREFIXES)
    )
