"""Parse Kubernetes OWNERS / OWNERS_ALIASES files (the official code-ownership chart)."""
import os
import re
from typing import Dict, List, Optional

import yaml


def sig_team(label: str) -> Optional[str]:
    """'sig/node' -> 'sig-node'; anything else -> None."""
    m = re.fullmatch(r"(sig|wg)/([a-z0-9-]+)", label.strip())
    if not m:
        return None
    return ("sig-" if m.group(1) == "sig" else "wg-") + m.group(2)


def _names(items, aliases) -> List[str]:
    out = []
    for x in items or []:
        x = str(x).strip()
        out.extend(aliases.get(x, [x]))
    return sorted({x for x in out if x})


def load_owners(repo_dir: str) -> Dict[str, dict]:
    """Map repo-relative dir ('' = root) -> {approvers, reviewers, teams, parent, no_parent}."""
    aliases_path = os.path.join(repo_dir, "OWNERS_ALIASES")
    aliases = {}
    if os.path.exists(aliases_path):
        aliases = {k: [str(v) for v in (vs or [])] for k, vs in
                   ((yaml.safe_load(open(aliases_path)) or {}).get("aliases") or {}).items()}
    owners = {}
    for root, _dirs, files in os.walk(repo_dir):
        if ".git" in root or "OWNERS" not in files:
            continue
        rel = os.path.relpath(root, repo_dir)
        rel = "" if rel == "." else rel
        try:
            data = yaml.safe_load(open(os.path.join(root, "OWNERS"))) or {}
        except Exception:
            continue
        approvers, reviewers, labels = list(data.get("approvers") or []), list(data.get("reviewers") or []), list(data.get("labels") or [])
        for f in (data.get("filters") or {}).values():
            approvers += f.get("approvers") or []
            reviewers += f.get("reviewers") or []
            labels += f.get("labels") or []
        owners[rel] = {
            "approvers": _names(approvers, aliases),
            "reviewers": _names(reviewers, aliases),
            "teams": sorted({t for t in (sig_team(lb) for lb in labels) if t}),
            "no_parent": bool((data.get("options") or {}).get("no_parent_owners")),
        }
    for d in owners:
        owners[d]["parent"] = None if d == "" else _parent_owner_dir(owners, d)
    return owners


def _parent_owner_dir(owners: Dict[str, dict], d: str) -> Optional[str]:
    while d:
        d = os.path.dirname(d)
        if d in owners:
            return d
    return "" if "" in owners else None


def nearest_owner_dir(owners: Dict[str, dict], file_path: str) -> str:
    d = os.path.dirname(file_path)
    while d and d not in owners:
        d = os.path.dirname(d)
    return d


def official_owners(owners: Dict[str, dict], file_path: str) -> Dict[str, List[str]]:
    """Approvers/reviewers that Prow would consider for this file (nearest OWNERS plus ancestors)."""
    d = nearest_owner_dir(owners, file_path)
    approvers, reviewers = set(), set()
    first = True
    while d is not None and d in owners:
        o = owners[d]
        approvers.update(o["approvers"])
        if first:
            reviewers.update(o["reviewers"])
            first = False
        if o["no_parent"] or d == "":
            break
        d = o["parent"]
    return {"approvers": sorted(approvers), "reviewers": sorted(reviewers)}
