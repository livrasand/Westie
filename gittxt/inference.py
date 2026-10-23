"""Separate inference from facts. Each hypothesis must cite supporting facts.

Confidence scale (calibrated: value == strength of evidence, not of polish):
  1.00  git-fact        - direct fact from git/diff (presence, absence, line counts,
                        non-comment-line equality); cannot be otherwise
  0.95  ast-presence    - symbol present/absent in both parsed AST versions
  0.90  ast-detail      - AST-level difference located (signature/body/flow); the
                        exact wording of the change is a further reading
  0.90  relation        - cross-file relationship inferred from >=2 concrete facts
                        (e.g. a move with an identical body)
  0.70  weak_relation   - relationship inferred, but identity of intent is not
                        provable (e.g. rename candidates with identical bodies)
  0.70  interpretation  - architectural reading composed from facts
  0.60  presence-only   - existence fact whose content could not be verified
                        (binary/unreadable content)
  0.50  heuristic       - inference beyond the observed fact (e.g. same-name move
                        without comparable bodies; line-count similarity)
  0.40  binary          - binary diff; content unknown
  0.30  unavailable     - evidence needed exists but could not be read
"""
import re
from dataclasses import dataclass
from typing import List, Optional

CONF = {
    "git_fact": 1.0,
    "ast_presence": 0.95,
    "ast_detail": 0.9,
    "relation": 0.9,
    "weak_relation": 0.7,
    "interpretation": 0.7,
    "presence_only": 0.6,
    "heuristic": 0.5,
    "binary": 0.4,
    "unavailable": 0.3,
}

# Tiers of knowledge, distinct from confidence:
#   fact           - directly observed (git/diff/AST of one version)
#   relation       - cross-file relationship inferred from >=2 facts
#   interpretation - high-level reading composed from facts (never stated as fact)


def confidence_band(value):
    # Bands only reflect evidence quality. "verified" is reserved for claims
    # re-checked by gittxt.verify; it is never derived from confidence alone.
    if value >= 0.9:
        return "well-evidenced"
    if value >= 0.5:
        return "heuristic"
    return "weak"


@dataclass
class Hypothesis:
    claim: str
    confidence: float
    supporting_facts: List[str]
    type: str  # "structural" | "file" | "neutral"
    tier: str = "fact"  # "fact" | "relation" | "interpretation"
    category: Optional[str] = None  # doc/config secondary grouping hint
    # Machine-readable claim content (concept), independent of wording:
    # {"action": ..., "kind": ..., "name": ..., "path"-/"paths": ...}.
    # Used by gittxt.selection for semantic merging and subsumption.
    concept: Optional[dict] = None


def _identifiers(body):
    if not body:
        return None
    return frozenset(re.findall(r"[A-Za-z_]\w*", body))


def _body_match(old_body, new_body):
    """Deterministic comparison of two function bodies. Returns (kind, confidence)."""
    if old_body is None or new_body is None:
        return "name-only", CONF["heuristic"]
    if old_body.strip() == new_body.strip():
        return "identical", CONF["relation"]  # same AST text: strong move evidence
    oi, ni = _identifiers(old_body), _identifiers(new_body)
    if oi is not None and oi == ni:
        return "same-identifiers", CONF["weak_relation"]
    return "changed", CONF["heuristic"]


def pair_moves(facts_by_file):
    """Pair removed symbols in one file with same-named added symbols in another.

    Returns list of moves:
    (symbol_kind, name, from_path, to_path, kind, confidence).
    A move is only claimed when the same symbol name leaves one file and appears
    in a different one; body comparison further grades the evidence."""
    removed = {}   # name -> [(path, body)]
    added = {}
    for path, facts in sorted(facts_by_file.items()):
        if not facts.get("comparable", True) or ("added_funcs" not in facts and "removed_funcs" not in facts):
            continue
        bodies_old = facts.get("bodies_old", {})
        bodies_new = facts.get("bodies_new", {})
        for name in facts.get("removed_funcs", []):
            removed.setdefault(name, []).append((path, bodies_old.get(name)))
        for name in facts.get("added_funcs", []):
            added.setdefault(name, []).append((path, bodies_new.get(name)))
    cls_removed = {}
    cls_added = {}
    for path, facts in sorted(facts_by_file.items()):
        if not facts.get("comparable", True) or ("added_classes" not in facts and "removed_classes" not in facts):
            continue
        for name in facts.get("removed_classes", []):
            cls_removed.setdefault(name, []).append((path, facts.get("class_bodies_old", {}).get(name)))
        for name in facts.get("added_classes", []):
            cls_added.setdefault(name, []).append((path, facts.get("class_bodies_new", {}).get(name)))

    moves = []
    for kind, rem, add in (("function", removed, added), ("class", cls_removed, cls_added)):
        for name, rlist in rem.items():
            if name not in add:
                continue
            for (from_path, from_body) in rlist:
                for (to_path, to_body) in add[name]:
                    if from_path == to_path:
                        continue
                    mtype, conf = _body_match(from_body, to_body)
                    moves.append((kind, name, from_path, to_path, mtype, conf))
    return sorted(moves)


def pair_copies(facts_by_file):
    """Detect symbol copies: same name AND identical body added in one file while
    still defined in another. Verified only against observable facts.

    Returns list of (kind, name, source_path, into_path)."""
    copies = []
    for to_path, tfacts in sorted(facts_by_file.items()):
        if "added_funcs" not in tfacts and "added_classes" not in tfacts:
            continue
        if not tfacts.get("comparable", True):
            continue
        added_f = tfacts.get("added_funcs", [])
        added_c = tfacts.get("added_classes", [])
        for kind, added_names, bodies_new in (
            ("function", added_f, tfacts.get("bodies_new", {})),
            ("class", added_c, tfacts.get("class_bodies_new", {})),
        ):
            for name in added_names:
                target_body = bodies_new.get(name)
                if target_body is None:
                    continue
                for src_path, sfacts in sorted(facts_by_file.items()):
                    if src_path == to_path or not sfacts.get("comparable", True):
                        continue
                    # name must already exist in source AND survive there
                    if name in sfacts.get("removed_funcs", []) if kind == "function" else name in sfacts.get("removed_classes", []):
                        continue
                    src_bodies = (sfacts.get("bodies_old", {}), sfacts.get("bodies_new", {}))
                    if kind == "class":
                        src_bodies = (sfacts.get("class_bodies_old", {}), sfacts.get("class_bodies_new", {}))
                    old_b = src_bodies[0].get(name)
                    new_b = src_bodies[1].get(name)
                    if old_b is None and kind == "function":
                        continue
                    if old_b is not None and old_b.strip() != target_body.strip():
                        continue
                    if new_b is None or new_b.strip() != target_body.strip():
                        continue
                    copies.append((kind, name, src_path, to_path))
    return sorted(copies)


def pair_renames(facts_by_file):
    """Detect plausible renames inside a single file: a removed symbol whose body
    appears again under a different name among the added symbols of the same file.

    Returns list of (kind, name, old_name, path, confidence)."""
    renames = []
    for path, facts in sorted(facts_by_file.items()):
        if not facts.get("comparable", True):
            continue
        for kind, removed_k, added_k, bodies_old, bodies_new in (
            ("function", facts.get("removed_funcs", []), facts.get("added_funcs", []),
             facts.get("bodies_old", {}), facts.get("bodies_new", {})),
            ("class", facts.get("removed_classes", []), facts.get("added_classes", []),
             facts.get("class_bodies_old", {}), facts.get("class_bodies_new", {})),
        ):
            for old_name in removed_k:
                old_body = bodies_old.get(old_name)
                if not old_body:
                    continue
                matches = [n for n in added_k
                           if bodies_new.get(n) and _name_free(bodies_new[n]) == _name_free(old_body)]
                if len(matches) != 1:
                    continue  # ambiguous: leave general claims alone
                renames.append((kind, matches[0], old_name, path, CONF["weak_relation"]))
    return sorted(renames)


def _name_free(body):
    """Body text with the definition line removed (function/class name stripped)."""
    lines = body.splitlines()
    return "\n".join(lines[1:]).strip() if len(lines) > 1 else ""


def emit_py_hypotheses(hypotheses, path, facts):
    def h(claim, conf, facttxt, tier="fact", kind=None, name=None, action=None):
        concept = None
        if action and kind:
            concept = {"action": action, "kind": kind, "name": name, "path": path}
        hypotheses.append(Hypothesis(claim, conf, [facttxt], "structural", tier=tier,
                                     concept=concept))

    for name in facts.get("removed_funcs", []):
        h(f"Remove function {name}", CONF["ast_presence"],
          f"AST: {path} no longer defines function {name}",
          kind="function", name=name, action="remove_symbol")
    for name in facts.get("added_funcs", []):
        h(f"Add function {name}", CONF["ast_presence"],
          f"AST: {path} defines function {name} not present before",
          kind="function", name=name, action="add_symbol")
    for cname in facts.get("added_classes", []):
        h(f"Add class {cname}", CONF["ast_presence"],
          f"AST: {path} defines class {cname} not present before",
          kind="class", name=cname, action="add_symbol")
    for cname in facts.get("removed_classes", []):
        h(f"Remove class {cname}", CONF["ast_presence"],
          f"AST: {path} no longer defines class {cname}",
          kind="class", name=cname, action="remove_symbol")
    for mod in facts.get("modified_funcs", []):
        reasons = mod["changes"]
        label = None
        if "raise_changed" in reasons:
            label = "(exception handling changed)"
        elif "conditional_changed" in reasons:
            label = "(control flow changed)"
        elif "signature_changed" in reasons:
            label = "(signature changed)"
        suffix = f" {label}" if label else ""
        h(f"Modify function {mod['name']}{suffix}", CONF["ast_detail"],
          f"AST: {path}::{mod['name']} differs between versions ({', '.join(reasons)})",
          kind="function", name=mod["name"], action="modify_symbol")


def _test_summary(old_syms, new_syms):
    """Count test symbols (functions + test classes) before/after."""
    def tests(syms):
        if syms is None:
            return set()
        return set(syms.get("test_funcs", [])) | set(syms.get("test_classes", []))
    return tests(old_syms), tests(new_syms)


def build_hypotheses(diff_facts, facts_by_file):
    hypotheses = []

    for path in sorted(facts_by_file):
        facts = facts_by_file[path]
        if not facts.get("comparable", True):
            if facts.get("read_error"):
                hypotheses.append(Hypothesis(
                    claim=f"Modify file {path}",
                    confidence=CONF["unavailable"],
                    supporting_facts=[
                        f"git: a version of {path} exists but could not be read; "
                        "comparison impossible",
                    ],
                    type="neutral",
                    concept={"action": "modify_file", "path": path,
                             "category": None, "read_error": True},
                ))
            continue
        is_ast = "added_funcs" in facts
        is_tests = bool(facts.get("is_tests"))
        if not is_ast and facts.get("file_new"):
            lines = facts.get("new_lines")
            detail = f"{lines} lines" if lines is not None else "content not analyzed"
            hypotheses.append(Hypothesis(
                claim=f"Add file {path}",
                confidence=(CONF["git_fact"] if not facts.get("binary_content")
                            else CONF["presence_only"]),
                supporting_facts=[
                    f"git: {path} is absent from HEAD",
                    f"git: {path} is a {facts['category']} file ({detail})",
                ],
                type="file",
                category=facts.get("category"),
                concept={"action": "add_file", "path": path,
                         "category": facts.get("category"),
                         "binary": bool(facts.get("binary_content")),
                         "tests": 0, "functions": None, "classes": None},
            ))
        elif facts.get("file_removed"):
            hypotheses.append(Hypothesis(
                claim=f"Remove file {path}",
                confidence=CONF["git_fact"],
                supporting_facts=[f"git: {path} exists in HEAD but not in the worktree/index"],
                type="file",
                category=facts.get("category"),
                concept={"action": "remove_file", "path": path,
                         "category": facts.get("category")},
            ))
        elif is_ast:
            if is_tests:
                # Test files: prefer one high-level claim over a list of symbols.
                old_syms = facts.get("_old_syms")
                new_syms = facts.get("_new_syms")
                old_tests, new_tests = _test_summary(old_syms, new_syms)
                if facts.get("file_new"):
                    hypotheses.append(Hypothesis(
                        claim=f"Add file {path}",
                        confidence=CONF["git_fact"],
                        supporting_facts=[
                            f"git: {path} is absent from HEAD",
                            f"AST: {path} defines {len(new_tests)} test symbols (unittest)",
                        ],
                        type="file",
                        category=facts.get("category"),
                        concept={"action": "add_file", "path": path,
                                 "category": facts.get("category"),
                                 "binary": False,
                                 "tests": len(new_tests),
                                 "functions": None, "classes": None},
                    ))
                added_tests = sorted(new_tests - old_tests) if not facts.get("file_new") else sorted(new_tests)
                n = len(new_tests if facts.get("file_new") else new_tests - old_tests)
                targets = _test_targets(path, facts, facts_by_file)
                if n > 0:
                    if targets:
                        unit = "test" if n == 1 else "tests"
                        claim = f"Add {n} {unit} for {' and '.join(targets)}"
                        conf = CONF["weak_relation"]
                        tier = "relation"
                        fcount = f"AST: {path} defines {n} test symbols (unittest)"
                        fimports = f"AST: {path} imports {', '.join(targets)}"
                        supporting = [fcount, fimports]
                    else:
                        unit = "test" if n == 1 else "tests"
                        claim = f"Add {n} {unit}"
                        conf = CONF["ast_presence"]
                        tier = "fact"
                        supporting = [f"AST: {path} defines {n} test symbols (unittest)"]
                    hypotheses.append(Hypothesis(
                        claim, conf, supporting, "structural", tier=tier,
                        concept={"action": "add_tests", "path": path, "count": n,
                                 "targets": list(targets), "file_new":
                                 bool(facts.get("file_new"))},
                    ))
                removed_tests = sorted(old_tests - new_tests)
                if removed_tests and not facts.get("file_new"):
                    hypotheses.append(Hypothesis(
                        claim=f"Remove {len(removed_tests)} "
                              f"{'test' if len(removed_tests) == 1 else 'tests'}",
                        confidence=CONF["ast_presence"],
                        supporting_facts=[f"AST: {path} no longer defines {len(removed_tests)} test symbols"],
                        type="structural",
                        tier="fact",
                        concept={"action": "remove_tests", "path": path,
                                 "count": len(removed_tests), "targets": []},
                    ))
                if not facts.get("file_new"):
                    a = facts.get("old_lines", "?")
                    b = facts.get("new_lines", "?")
                    hypotheses.append(Hypothesis(
                        claim=f"Modify file {path}",
                        confidence=CONF["git_fact"],
                        supporting_facts=[
                            f"diff: {a if a is None or a == '?' else a} -> {b if b is None or b == '?' else b} lines",
                            f"diff: {facts['category']} file",
                        ],
                        type="file",
                        category=facts.get("category"),
                        concept={"action": "modify_file", "path": path,
                                 "category": facts.get("category"),
                                 "comment_only": False, "read_error": False},
                    ))
                continue
            if facts.get("file_new"):
                n_fun = len(facts.get("added_funcs", []))
                n_cls = len(facts.get("added_classes", []))
                hypotheses.append(Hypothesis(
                    claim=f"Add file {path}",
                    confidence=CONF["git_fact"],
                    supporting_facts=[
                        f"git: {path} is absent from HEAD",
                        f"AST: {path} defines {n_fun} functions and {n_cls} classes",
                    ],
                    type="file",
                    category=facts.get("category"),
                    concept={"action": "add_file", "path": path,
                             "category": facts.get("category"),
                             "binary": False,
                             "tests": 0, "functions": n_fun, "classes": n_cls},
                ))
            emit_py_hypotheses(hypotheses, path, facts)
            continue
        elif facts.get("comment_only"):
            hypotheses.append(Hypothesis(
                claim=f"Modify file {path}",
                confidence=CONF["git_fact"],
                supporting_facts=["git: non-comment lines are identical; only comments changed"],
                type="neutral",
                category=facts.get("category"),
                concept={"action": "modify_file", "path": path,
                         "category": facts.get("category"),
                         "comment_only": True, "read_error": False},
            ))
        else:
            a = facts.get("old_lines", "?")
            b = facts.get("new_lines", "?")
            hypotheses.append(Hypothesis(
                claim=f"Modify file {path}",
                confidence=(CONF["git_fact"] if not facts.get("binary_content")
                            else CONF["binary"]),
                supporting_facts=[
                    f"diff: {a if a is None or a == '?' else a} -> {b if b is None or b == '?' else b} lines",
                    f"diff: {facts['category']} file",
                ],
                type="file",
                category=facts.get("category"),
                concept={"action": "modify_file", "path": path,
                         "category": facts.get("category"),
                         "binary": bool(facts.get("binary_content")),
                         "comment_only": False, "read_error": False},
            ))

    # Cross-file moves: replace independent Add/Remove claims with one Move claim
    moves = pair_moves(facts_by_file)
    for kind, name, from_path, to_path, mtype, conf in moves:
        detail = {
            "identical": "same body",
            "same-identifiers": "same identifiers, formatting changed",
            "changed": "content differs",
            "name-only": "body comparison unavailable",
        }[mtype]
        fact = (f"AST: {kind} {name} was defined in {from_path} (old version) and "
                f"is defined in {to_path} (new version); {detail}")
        hypotheses.append(Hypothesis(
            claim=f"Move {kind} {name} from {from_path} to {to_path}",
            confidence=conf,
            supporting_facts=[fact],
            type="structural",
            tier="relation",
            concept={"action": "move", "kind": kind, "name": name,
                     "from": from_path, "to": to_path, "body": mtype},
        ))
        if mtype in ("changed", "same-identifiers"):
            hypotheses.append(Hypothesis(
                claim=f"Modify moved {kind} {name}",
                confidence=CONF["heuristic"],
                supporting_facts=[fact],
                type="structural",
                tier="relation",
                concept={"action": "modify_moved", "kind": kind, "name": name,
                         "paths": [from_path, to_path]},
            ))

    # Copies and renames: distinguish them from moves
    copies = pair_copies(facts_by_file)
    for kind, name, src_path, to_path in copies:
        hypotheses.append(Hypothesis(
            claim=f"Copy {kind} {name} from {src_path} to {to_path}",
            confidence=CONF["relation"],
            supporting_facts=[
                f"AST: {name} is still defined in {src_path} (new version), "
                f"with an identical body now added in {to_path}; same name, same content",
            ],
            type="structural",
            tier="relation",
            concept={"action": "copy", "kind": kind, "name": name,
                     "from": src_path, "to": to_path},
        ))

    renames = pair_renames(facts_by_file)
    for kind, new_name, old_name, path, conf in renames:
        hypotheses.append(Hypothesis(
            claim=f"Rename {kind} {old_name} to {new_name} in {path}",
            confidence=conf,
            supporting_facts=[
                f"AST: {path} no longer defines {kind} {old_name}; a {kind} {new_name} "
                "with an identical body has been added; same name content and identical body",
            ],
            type="structural",
            tier="relation",
            concept={"action": "rename", "kind": kind, "name": new_name,
                     "old": old_name, "path": path},
        ))

    # Modularization: an entry file whose functions moved into new, locally imported modules
    modular = _modularization(facts_by_file, moves)
    if modular:
        hypotheses.append(modular)

    # Suppress claims that are superseded by a richer relational claim.
    move_keys = {(kind, name, from_path, to_path) for kind, name, from_path, to_path, *_ in moves}
    copy_keys = {(kind, name, to_path) for kind, name, _s, to_path in copies}
    rename_keys = {(kind, old_name, path) for kind, _n, old_name, path, _c in renames}
    rename_added = {(kind, new_name, path) for kind, new_name, _o, path, _c in renames}

    def sup_txt(h):
        return h.supporting_facts[0] if h.supporting_facts else ""

    def drop(h):
        txt = sup_txt(h)
        for kind, name, from_path, to_path in move_keys:
            for p in (from_path, to_path):
                if txt in (f"AST: {p} no longer defines {kind} {name}",
                           f"AST: {p} defines {'function' if kind == 'function' else 'class'} {name} not present before"):
                    return True
        for kind, name, to_path in copy_keys:
            if txt == f"AST: {to_path} defines {'function' if kind == 'function' else 'class'} {name} not present before":
                return True
        for kind, old_name, path in rename_keys:
            if txt == f"AST: {path} no longer defines {kind} {old_name}":
                return True
        for kind, new_name, path in rename_added:
            if txt == f"AST: {path} defines {kind} {new_name} not present before":
                return True
        return False

    hypotheses = [h for h in hypotheses if not drop(h)]
    return hypotheses


def _test_targets(path, facts, facts_by_file):
    """Determine plausible test targets from imports (evidence, not filename)."""
    imports = facts.get("imports_new", [])
    targets = []
    known = _local_module_names(facts_by_file, exclude=path)
    if not known:
        return targets
    for imp in imports:
        m = re.match(r"(?:import|from)\s+([\w.]+)", imp)
        if not m:
            continue
        mod = m.group(1)
        parts = mod.split(".")
        last = parts[-1]
        if mod in known or last in known:
            txt = mod
            if txt not in targets:
                targets.append(txt)
    return targets


def _local_module_names(facts_by_file, exclude=None):
    """Basenames of python files observed in this change set (module-name evidence)."""
    names = set()
    for p, f in facts_by_file.items():
        if exclude and p == exclude:
            continue
        if p.endswith(".py"):
            names.add(p[:-3].replace("/", "."))
            parent = p.rsplit("/", 1)[0].replace("/", ".") if "/" in p else None
            if parent:
                names.add(parent)
    return names


def _modularization(facts_by_file, moves):
    """Evidence-based architectural claim: an entry point that lost functions now
    provided by new modules it imports returns an interpretation hypothesis."""
    moved_by_source = {}
    for kind, name, from_path, to_path, *_ in moves:
        moved_by_source.setdefault(from_path, []).append(name)
    new_py = [p for p, f in facts_by_file.items()
              if f.get("file_new") and p.endswith(".py") and not f.get("is_tests")]
    new_stems = {p[:-3].rsplit("/", 1)[-1] for p in new_py}
    for entry, moved in moved_by_source.items():
        if len(moved) < 2:
            continue
        facts = facts_by_file.get(entry, {})
        added_imports = facts.get("added_imports", [])
        matched = []
        for imp in added_imports:
            m = re.match(r"(?:import|from)\s+([\w.]+)", imp)
            if not m:
                continue
            mod = m.group(1)
            if mod.split(".")[-1] in new_stems:
                matched.append(mod)
        if not matched:
            continue
        def mod_path(mod):
            segs = [s for s in mod.split(".") if s]
            return "/".join(segs) + ".py"

        def rel_path(source_py, mod):
            """Resolve an import target (possibly relative) to a file path."""
            if not mod.startswith("."):
                return mod_path(mod)
            dots = len(mod) - len(mod.lstrip("."))
            rest = [s for s in mod.lstrip(".").split(".") if s]
            dirparts = source_py[:-len(".py")].split("/")[:-1]
            keep = len(dirparts) - (dots - 1) if dots > 1 else len(dirparts)
            return "/".join(dirparts[:keep] + rest) + ".py"

        def path_mod(p):
            """Canonical dotted module name derived from a file path."""
            return p[:-len(".py")].replace("/", ".")

        # Resolve the import closure over new files: a module is part of the
        # restructuring only if it (or its importer chain) is itself a new file
        # observed in this change set. Evidence-based, no path guesses.
        new_py_set = set(new_py)
        seen_mods = list(matched)
        seen_paths = {path_mod(mod_path(m)) for m in matched}
        frontier = [(path_mod(mod_path(m)), mod_path(m)) for m in matched]
        while frontier:
            _mod_str, p = frontier.pop(0)
            fp = facts_by_file.get(p, {})
            for imp in fp.get("imports_new", []):
                m2 = re.match(r"(?:import|from)\s+([\w.]+)", imp)
                if not m2:
                    continue
                mod2 = m2.group(1)
                p2 = rel_path(p, mod2)
                if p2 in seen_paths or p2 not in new_py_set:
                    continue
                seen_paths.add(p2)
                mod_str = path_mod(p2)
                seen_mods.append(mod_str)
                frontier.append((mod_str, p2))
        matched = sorted(set(seen_mods))

        per_file_paths = set(facts_by_file)
        segs = [m.split(".") for m in matched]
        single = all(len(s) == 1 for s in segs)
        if len(matched) >= 2 and single and all(
                segs[i][0] + ".py" in per_file_paths for i in range(len(segs))):
            claim = f"Modularize {entry} into {len(set(matched))} local modules"
        elif (len(matched) >= 2 and not single
              and len({tuple(s[:-1]) for s in segs if len(s) >= 2}) == 1
              and all(len(s) >= 2 and mod_path(m) in per_file_paths
                      for s, m in zip(segs, matched))):
            claim = f"Modularize {entry} into the {segs[0][-2]} package"
        else:
            claim = f"Modularize {entry} into {len(set(matched))} new modules"
        moved_map = {}
        for kind, name, from_path, to_path, *_ in moves:
            if from_path == entry:
                moved_map.setdefault(to_path, []).append(name)
        moved_map = {p: sorted(set(names)) for p, names in sorted(moved_map.items())}
        moved_all = sorted({n for names in moved_map.values() for n in names})

        module_facts = []
        for mod in sorted(set(matched)):
            mpath = mod_path(mod)
            mfacts = facts_by_file.get(mpath, {})
            nf = len(mfacts.get("added_funcs", []))
            nc = len(mfacts.get("added_classes", []))
            nmoved = len(moved_map.get(mpath, []))
            module_facts.append(
                f"AST: {mpath} now defines {nf} functions and {nc} classes "
                f"({nmoved} moved from {entry})")
        new_files = sorted({mod_path(m) for m in set(matched)})
        hyp = Hypothesis(
            claim=claim,
            confidence=CONF["interpretation"],
            supporting_facts=[
                f"AST: {entry} now imports {', '.join(sorted(set(matched)))}",
            ] + module_facts + [
                f"AST: {len(moved_all)} functions were moved from {entry}: "
                + ", ".join(moved_all),
                f"git: {' and '.join(new_files)} are new files",
            ],
            type="structural",
            tier="interpretation",
            concept={"action": "modularize", "entry": entry,
                     "moved": moved_all, "moved_map": moved_map,
                     "new_files": new_files,
                     "module_count": len(set(matched))},
        )
        return hyp
    return None
