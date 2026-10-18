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


def _pick(question: str):
    q = question.strip()
    team = tools._find_team(q)
    if STALE.search(q):
        return tools.whats_stale(team)
    gate = next((g for g in GATE.findall(q) if tools._resolve(f"gate:{g}")[0] == "gate"), None)
    if WHY.search(q):
        return tools.why(gate or WHY_PREFIX.sub("", q).strip(" ?.") or q)
    if gate:
        return tools.who_knows(f"gate:{gate}")
    if team:
        return tools.who_owns(f"team:{team}") if OWN.search(q) and "know" not in q.lower() else tools.who_knows(f"team:{team}")
    folder = re.search(r"\b[\w.-]+(?:/[\w.-]+)+\b", q)
    if folder and tools._resolve(f"folder:{folder.group(0)}")[0] == "folder":
        return tools.who_knows(f"folder:{folder.group(0)}")
    return tools.why(q)


def answer(question: str) -> Dict[str, Any]:
    env = _pick(question)
    data = env.get("data") or {}
    out: Dict[str, Any] = dict(env)
    out["answer"] = env.get("summary", "")
    owners = data.get("official_owners") or data.get("owners") or []
    out["official_owners"] = [{"login": o["login"], "role": ", ".join(o.get("roles") or []) or "official owner"}
                              for o in owners if isinstance(o, dict) and o.get("login")]
    out["actual_knowers"] = [{"login": p["login"], "is_official": p.get("is_official_owner", False),
                              "decisions_count": p.get("total", 0)} for p in data.get("people") or []][:8]
    out["decision_trail"] = [{"kep": k["ref"], "title": k["title"], "date": (k.get("created") or "")[:7],
                              "status": k.get("status") or ""} for k in data.get("trail") or []]
    ev = env.get("evidence") or {}
    out["graph"] = {"nodes": ev.get("nodes", []), "edges": ev.get("edges", [])}
    return out
