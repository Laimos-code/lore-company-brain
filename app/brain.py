"""Answer /api/ask from the graph when no LLM agent is configured.

Picks one of app/tools.py's Cypher tools for the question and returns its envelope
({tool, summary, data, evidence, sources, is_stub}) plus the fields the web page reads
(answer, official_owners, actual_knowers, decision_trail, graph).
"""
import re
from typing import Any, Dict

from app import tools

STALE = re.compile(r"\b(stuck|stale|abandon\w*|forgotten|dead)\b", re.I)
WHY = re.compile(r"^\s*(why|how come)\b|\b(decid\w*|decision|history|trail)\b", re.I)
GATE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")
WHY_PREFIX = re.compile(r"^\s*(why|how come)(\s+(did|do|does|was|were|is))?(\s+(they|we|kubernetes|k8s))?"
                        r"(\s+(choose|chose|pick|use|decide on|go with|add|remove))?\s*", re.I)
OWN = re.compile(r"\b(who owns|owner|owners|official)\b", re.I)
KEP = re.compile(r"\bKEP[-\s#]*(\d+)\b", re.I)
ROLE_TEXT = {"kep_approver": "KEP approver", "tech_lead": "tech lead"}


TEAM = re.compile(r"\b(sig|wg)[\s-]+([a-z]+)(?:[\s-]([a-z]+))?", re.I)


def _team_in(q: str):
    """The Team a question names ('SIG Node', 'sig-storage', 'wg batch'), else None."""
    for m in TEAM.finditer(q):
        kind, a, b = m.groups()
        for cand in ([f"{kind}-{a}-{b}"] if b else []) + [f"{kind}-{a}"]:
            key = tools._find_team(cand.lower())
            if key:
                return key
    return None


def _pick(question: str):
    q = question.strip()
    team = _team_in(q)
    m = KEP.search(q)
    kep = f"kep:{int(m.group(1))}" if m else None
    owns = bool(OWN.search(q)) and "know" not in q.lower()
    if STALE.search(q):
        return tools.whats_stale(team)
    gate = next((g for g in GATE.findall(q) if tools._resolve(f"gate:{g}")[0] == "gate"), None)
    if WHY.search(q):
        return tools.why(kep or gate or WHY_PREFIX.sub("", q).strip(" ?.") or q)
    if gate:
        return tools.who_knows(f"gate:{gate}")
    if kep:  # 'Who owns KEP-4671?' / 'Who knows KEP-4671?' / anything else about it: its trail
        if owns:
            return tools.who_owns(kep)
        return tools.who_knows(kep) if "know" in q.lower() else tools.why(kep)
    if team:
        return tools.who_owns(f"team:{team}") if owns else tools.who_knows(f"team:{team}")
    folder = re.search(r"\b[\w.-]+(?:/[\w.-]+)+\b", q)
    if folder and tools._resolve(f"folder:{folder.group(0)}")[0] == "folder":
        return tools.who_knows(f"folder:{folder.group(0)}")
    return tools.why(q)


def _official_owners(data: Dict[str, Any]):
    """Official owners in the page's shape ({login, role}) from any who_owns / who_knows result:
    team leaders, a KEP's team leaders and approvers, or a folder's OWNERS approvers."""
    roles: Dict[str, list] = {}

    def add(login, role):
        if login and role not in roles.setdefault(login, []):
            roles[login].append(role)
    for o in data.get("official_owners") or data.get("owners") or []:
        for r in o.get("roles") or ["official owner"]:
            add(o.get("login"), ROLE_TEXT.get(r, r))
    for o in data.get("team_leads") or []:
        add(o.get("login"), f"{data.get('team')} " + ", ".join(ROLE_TEXT.get(r, r) for r in o.get("roles") or ["lead"]))
    for o in data.get("approvers") or []:
        add(o.get("login"), f"approver ({o['source']})" if o.get("source") else "KEP approver")
    return [{"login": login, "role": ", ".join(rs)} for login, rs in roles.items()]


def answer(question: str) -> Dict[str, Any]:
    env = _pick(question)
    data = env.get("data") or {}
    out: Dict[str, Any] = dict(env)
    out["answer"] = env.get("summary", "")
    out["official_owners"] = _official_owners(data)
    out["actual_knowers"] = [{"login": p["login"], "is_official": p.get("is_official_owner", False),
                              "decisions_count": p.get("total", 0)} for p in data.get("people") or []][:8]
    out["decision_trail"] = [{"kep": k["ref"], "title": k["title"], "date": (k.get("created") or "")[:7],
                              "status": k.get("status") or ""} for k in data.get("trail") or []]
    ev = env.get("evidence") or {}
    out["graph"] = {"nodes": ev.get("nodes", []), "edges": ev.get("edges", [])}
    return out
