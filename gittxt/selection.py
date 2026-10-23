"""Semantic selection: merge and suppress hypotheses by concept, before composing.

Works on the structured `concept` attached to each hypothesis (never on claim
wording, never on hardcoded project names). A claim is suppressed only when a
selected hypothesis with at least as strong evidence covers exactly what it
states. Returns (selected, suppressed) and never inflates confidence: merged
claims carry the minimum confidence of their members.

Merging rules:
- Targeted test claims ("Add N tests for <modules>") whose target sets overlap
  are merged into one clause with a summed count and a union of targets. Counts
  are never double-counted: each member counts tests defined in its own file.
- Untargeted test claims are merged with each other (they cover disjoint files).
Subsumption rules:
- A modularization claim covers the removal of moved functions from the entry
  file, their reappearance in the new modules, the creation of those module
  files, and the cross-file moves between them.
- Test-file addition claims are covered by the merged test summary that includes
  them as source files.
"""
from .inference import Hypothesis


def _concept(h):
    c = getattr(h, "concept", None)
    return c if isinstance(c, dict) else {}


def _action(h):
    return _concept(h).get("action")


def _join_targets(targets):
    if not targets:
        return ""
    if len(targets) == 1:
        return targets[0]
    if len(targets) == 2:
        return " and ".join(targets)
    return ", ".join(targets[:-1]) + ", and " + targets[-1]


def select_hypotheses(hypotheses):
    selected = list(hypotheses)
    suppressed = []

    def remove(h, reason):
        if h in selected:
            selected.remove(h)
            suppressed.append({"claim": h.claim, "reason": reason})

    # 1. Modularization subsumption (concept-based, not wording-based).
    for m in [h for h in hypotheses if _action(h) == "modularize"]:
        c = m.concept
        entry = c.get("entry")
        moved_map = c.get("moved_map", {})
        moved_names = {n for names in moved_map.values() for n in names}
        scope = set(c.get("new_files", [])) | set(moved_map)
        # Files of the created package(s) are part of the restructuring: any
        # module-level claim inside those directories is covered by the claim.
        package_dirs = {p.rsplit("/", 1)[0] for p in scope if "/" in p}

        def in_scope(path):
            if not path:
                return False
            return path in scope or path.rsplit("/", 1)[0] in package_dirs

        for h in list(selected):
            if h is m:
                continue
            hc = _concept(h)
            a = hc.get("action")
            if a == "remove_symbol" and hc.get("path") == entry \
                    and hc.get("name") in moved_names:
                remove(h, "covered by modularization")
            elif a in ("add_symbol", "remove_symbol", "modify_symbol") \
                    and in_scope(hc.get("path")):
                remove(h, "covered by modularization")
            elif a == "add_file" and in_scope(hc.get("path")) \
                    and hc.get("path") != entry:
                remove(h, "covered by modularization")
            elif a == "move" and hc.get("from") == entry \
                    and in_scope(hc.get("to")) \
                    and hc.get("name") in moved_names:
                remove(h, "covered by modularization")

    # 2. Merge overlapping test summaries.
    targeted = sorted(
        [h for h in selected
         if _action(h) == "add_tests" and _concept(h).get("targets")],
        key=lambda h: (tuple(_concept(h).get("targets", [])),
                       _concept(h).get("path") or ""))
    untargeted = sorted(
        [h for h in selected
         if _action(h) == "add_tests" and not _concept(h).get("targets")],
        key=lambda h: (_concept(h).get("count") or 0,
                       _concept(h).get("path") or ""))

    def merge_groups(raw_sorted, grouped):
        """Group members with intersecting target sets, then merge each group."""
        groups = []
        for h in raw_sorted:
            tset = set(_concept(h).get("targets", []))
            placed = False
            for g in groups:
                # Untargeted claims merge among themselves: every member covers
                # a disjoint file, so an empty target set is compatible with
                # other empty target sets.
                if (not grouped and not tset and not g["targets"]) \
                        or (tset & set(g["targets"])):
                    g["members"].append(h)
                    g["targets"] = sorted(set(g["targets"]) | tset)
                    placed = True
                    break
            if not placed:
                groups.append({"targets": sorted(tset), "members": [h]})
        for g in groups:
            members = g["members"]
            if len(members) < 2:
                continue
            targets = g["targets"] if grouped else []
            count = sum(_concept(m).get("count", 0) for m in members)
            supporting = []
            for m in members:
                for f in m.supporting_facts:
                    if f not in supporting:
                        supporting.append(f)
            if targets:
                claim = (f"Add {count} "
                         f"{'test' if count == 1 else 'tests'} "
                         f"for {_join_targets(targets)}")
                tier = "relation"
            else:
                claim = f"Add {count} {'test' if count == 1 else 'tests'}"
                tier = "fact"
            conf = min(m.confidence for m in members)
            merged = Hypothesis(claim, conf, supporting, "structural",
                                tier=tier)
            merged.concept = {
                "action": "add_tests", "count": count, "targets": targets,
                "paths": sorted({p for m in members
                                 for p in [_concept(m).get("path")]
                                 if p}),
                "file_new": all(_concept(m).get("file_new", False)
                                for m in members),
            }
            paths = set(merged.concept["paths"])
            idx = min(selected.index(m) for m in members)
            for m in members:
                selected.remove(m)
                suppressed.append({"claim": m.claim,
                                   "reason": "merged into test summary"})
            selected.insert(idx, merged)
            # The merged summary mentions each source file; the file-addition
            # claim for a source file is covered by it.
            for h in list(selected):
                if _action(h) == "add_file" \
                        and _concept(h).get("path") in paths:
                    remove(h, "covered by test summary")

    merge_groups(targeted, grouped=True)
    merge_groups(untargeted, grouped=False)

    return selected, suppressed


def render_concept_targets(concept):
    """Render the target list of a concept deterministically (shared wording)."""
    return _join_targets(concept.get("targets", []))
