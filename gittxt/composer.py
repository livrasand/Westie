"""Compositional linguistic generation - no full-message templates."""
from .inference import confidence_band, CONF
from typing import List, Dict, Any, Tuple

GROUP_THRESHOLD = 3
GROUPABLE_KINDS = ("function", "class", "file")
SECONDARY_CATEGORIES = {"doc", "config"}


RANK = {
    ("Modularize", "other"): 0,
    ("Move", "function"): 1, ("Move", "class"): 1,
    ("Copy", "function"): 1, ("Copy", "class"): 1,
    ("Rename", "function"): 1, ("Rename", "class"): 1,
    ("Add", "file"): 2, ("Remove", "file"): 2,
    ("Add", "function"): 3, ("Add", "class"): 3,
    ("Remove", "function"): 3, ("Remove", "class"): 3,
    ("Add", "tests"): 4, ("Remove", "tests"): 4,
    ("Add", "test"): 4, ("Remove", "test"): 4,
    ("Modify", "function"): 5, ("Modify", "class"): 5,
    ("Modify", "file"): 6,
}


def parse_claim(claim: str) -> Tuple[str, str, str]:
    """Split a claim into (verb, kind, rest) deterministically."""
    words = claim.split(" ")
    verb = words[0]
    if len(words) >= 3 and words[1].isdigit() and words[2] in ("tests", "test"):
        return verb, "tests", " ".join(words[3:])
    if len(words) >= 2 and words[1] in GROUPABLE_KINDS:
        kind, rest = words[1], " ".join(words[2:])
        return verb, kind, rest
    return verb, "other", " ".join(words[1:])


class CompositionalComposer:
    def __init__(self):
        pass
    
    def compose(self, hypotheses: List, facts: Dict[str, Any]):
        """Compose description from facts and hypotheses without selecting pre-made sentences."""
        if not hypotheses:
            # Check for comment-only changes
            all_added = []
            all_removed = []
            for path, f in facts.get("files", {}).items():
                all_added.extend(f.get("added", []))
                all_removed.extend(f.get("removed", []))
            # Simple heuristic only for comments
            comment_changes = all(
                (a.strip().startswith('#') or not a.strip()) and 
                (r.strip().startswith('#') or not r.strip())
                for a,r in zip(all_added or [''], all_removed or [''])
            ) if (all_added or all_removed) else False
            if comment_changes and (all_added or all_removed):
                return {
                    "text": "Update comments only.",
                    "confidence": CONF["git_fact"],
                    "band": confidence_band(CONF["git_fact"]),
                    "claims": [{"claim": "Update comments only",
                                "confidence": CONF["git_fact"],
                                "evidence": "diff: only comment lines changed"}],
                    "facts_used": ["diff: only comment lines changed"],
                }
            return {
                "text": "Change not interpretable with sufficient confidence from available facts.",
                "confidence": 0.0,
                "band": confidence_band(0.0),
                "claims": [{"claim": "Change not interpretable with sufficient confidence "
                                      "from available facts",
                            "confidence": 0.0, "evidence": []}],
                "facts_used": [],
            }
        
        parts = []
        facts_used = []
        claims_ledger = []
        min_conf = 1.0

        # Collect claims in (verb, kind, secondary) groups, first-appearance order.
        groups = {}
        order = []
        for h in hypotheses:
            verb, kind, _rest = parse_claim(h.claim)
            sec = (getattr(h, "category", None) in SECONDARY_CATEGORIES)
            key = (verb, kind, sec)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(h)
            facts_used.extend(h.supporting_facts)
            min_conf = min(min_conf, h.confidence)

        def group_tier(hs):
            if any(h.tier == "interpretation" for h in hs):
                return 0
            if any(h.tier == "relation" for h in hs):
                return 1
            return 2

        # Relation 1: a new file whose content is N>=3 new symbols carries them;
        # fold those symbol claims into the file clause.
        newly_made = {h.claim[len("Add file "):]
                      for h in groups.get(("Add", "file", False), [])}
        folded = {}  # new-file path -> [n_functions, n_classes]
        skipped = set()  # id() of hypotheses folded away
        for h in groups.get(("Add", "function", False), []) + groups.get(("Add", "class", False), []):
            sf = h.supporting_facts[0] if h.supporting_facts else ""
            if sf.startswith("AST: ") and " defines " in sf:
                path = sf[len("AST: "):].split(" ", 1)[0]
                if path in newly_made:
                    folded.setdefault(path, [0, 0])[0 if h.claim.split(" ")[1] == "function" else 1] += 1
                    skipped.add(id(h))
        folded = {p: c for p, c in folded.items() if sum(c) >= GROUP_THRESHOLD}

        # Ordering: interpretations lead, then relations, then facts; doc/config
        # file claims come last. Deterministic ranks resolve ties.
        def sort_key(k):
            verb, kind, sec = k
            tier = group_tier(groups[k])
            # A merged test summary is evidence for the main narrative, not a
            # cross-file relation: it reads as a plain fact-level clause.
            if kind in ("tests", "test") and tier == 1:
                tier = 2
            rank = RANK.get((verb, kind), 6)
            if sec:
                rank = max(rank, 7)
            return (tier, rank, first_index[k])

        first_index = {k: i for i, k in enumerate(order)}
        order.sort(key=sort_key)

        for (verb, kind, sec) in order:
            bucket = [h for h in groups[(verb, kind, sec)] if id(h) not in skipped]
            if not bucket:
                continue
            if kind == "other" or len(bucket) < GROUP_THRESHOLD:
                for h in bucket:
                    claim = h.claim
                    if (verb, kind, sec) == ("Add", "file", False) and claim[len("Add file "):] in folded:
                        pth = claim[len("Add file "):]
                        nfun, ncls = folded[pth]
                        detail = []
                        if nfun:
                            detail.append(f"{nfun} functions")
                        if ncls:
                            detail.append(f"{ncls} classes")
                        claim += " (" + " and ".join(detail) + ")"
                    parts.append(claim)
                    claims_ledger.append({
                        "claim": claim,
                        "confidence": h.confidence,
                        "evidence": list(h.supporting_facts),
                    })
            else:
                n = len(bucket)
                plural = "classes" if kind == "class" else kind + "s"
                clause = f"{verb} {n} {plural}"
                if kind == "file" and folded:
                    doc_count = sum(
                        1 for h in bucket
                        if h.claim[len("Add file "):] in folded
                    )
                    if doc_count:
                        clause += f" ({doc_count} with new symbols)"
                parts.append(clause)
                for h in bucket:
                    claims_ledger.append({
                        "claim": clause,
                        "confidence": h.confidence,
                        "evidence": list(h.supporting_facts),
                    })

        if len(parts) == 1:
            text = parts[0] + "."
        elif len(parts) == 2:
            text = parts[0] + "; " + parts[1] + "."
        else:
            text = "; ".join(parts) + "."
        
        return {
            "text": text,
            "confidence": min_conf,
            "band": confidence_band(min_conf),
            "claims": claims_ledger,
            "facts_used": facts_used,
        }
