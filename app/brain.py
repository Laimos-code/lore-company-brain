"""Graph-backed answers for /api/ask when no LLM agent is configured.

Every answer is built from Cypher over FalkorDB (via app.graph_tools) and returns the
same shape as the tool contract, plus `tool` and `is_stub: false`.
"""
import re
from typing import Any, Dict, Optional

from app import graph_tools as gt


def _find_team(g, q: str) -> Optional[str]:
    ql = q.lower().replace("-", " ")
    rows = g.query("MATCH (t:Team) RETURN t.key, t.name").result_set
    best = None
    for key, name in rows:
        for cand in {key.replace("-", " "), f"sig {str(name or '').lower()}", f"wg {str(name or '').lower()}"}:
            if cand and re.search(r"\b" + re.escape(cand) + r"\b", ql) and (best is None or len(cand) > best[1]):
                best = (key, len(cand))
    return best[0] if best else None


def _gate(g, q: str) -> Optional[str]:
    for tok in re.findall(r"[A-Z][A-Za-z0-9]{5,}", q):
        if g.query("MATCH (f:FeatureGate {name:$n}) RETURN f.name", {"n": tok}).result_set:
            return tok
    return None


def answer(question: str, g=None) -> Dict[str, Any]:
    g = g or gt.get_graph()
    q = question.strip()
    ql = q.lower()
    out: Dict[str, Any] = {"question": q, "is_stub": False, "official_owners": [], "actual_knowers": [],
                           "decision_trail": [], "sources": [], "graph": {"nodes": [], "edges": []}}

    if re.search(r"\b(stuck|stale|abandon|forgotten)\b", ql):
        res = gt.stale_decisions(g)
        out.update(tool="stale_decisions", answer=(
            f"{res['count']} decisions are still 'implementable' at alpha and were last touched 8+ releases before "
            f"{res['newest_release']}. Oldest examples: " +
            "; ".join(f"{d['kep']} {d['title']} ({d['team']}, last {d['last_touched']})" for d in res["decisions"][:5]) + "."))
        out["sources"] = [{"type": "KEP", "ref": d["kep"], "title": d["title"]} for d in res["decisions"]]
        return out

    gate = _gate(g, q)
    if gate:
        rows = g.query("""MATCH (f:FeatureGate {name:$n})<-[:INTRODUCES]-(k:KEP)-[:OWNED_BY]->(t:Team)
            OPTIONAL MATCH (p:Person)-[:AUTHORED|APPROVED]->(k)
            OPTIONAL MATCH (p)-[:SAME_AS]->(c:Person)
            RETURN k.num, k.title, k.stage, t.key, collect(DISTINCT coalesce(c.display, p.display))""", {"n": gate}).result_set
        if rows:
            num, title, stage, team, people = rows[0]
            wk = gt.who_knows(g, team, k=5)
            out.update(tool="feature_gate_owner", official_owners=wk["official_owners"], actual_knowers=wk["actual_knowers"],
                       answer=f"Feature gate {gate} was introduced by KEP-{num} '{title}' (stage {stage}), owned by {team}. "
                              f"Ask the people who wrote or approved it: {', '.join('@' + p for p in people[:5])}.",
                       sources=[{"type": "KEP", "ref": f"KEP-{num}", "title": title},
                                {"type": "FeatureGate", "ref": gate, "title": team}])
            return out

    if ql.startswith("why") or "decid" in ql or "history" in ql:
        topic = re.sub(r"^(why|how come)( did| do| was| were)?( they| we| kubernetes| k8s)?( choose| pick| use| decide on)?", "", ql).strip(" ?")
        res = gt.decision_trail(g, topic)
        if res["trail"]:
            trail = res["trail"]
            out.update(tool="decision_trail", decision_trail=[
                {"kep": t["kep"], "title": t["title"], "date": (t["created"] or "")[:7], "status": t["status"]} for t in trail])
            chain = " -> ".join(f"{t['kep']} {t['title']} ({(t['created'] or '?')[:4]}, {t['status']})" for t in trail)
            approvers = sorted({a for t in trail for a in t["approvers"]})
            out["answer"] = (f"The decision trail for '{topic}' spans {len(trail)} design decision(s): {chain}. "
                             + (f"Approved by {', '.join('@' + a for a in approvers[:6])}." if approvers else ""))
            out["sources"] = [{"type": "KEP", "ref": t["kep"], "title": t["title"]} for t in trail]
            out["graph"] = {"nodes": [{"id": t["kep"], "label": f"{t['kep']}: {t['title']}", "type": "KEP"} for t in trail],
                            "edges": [{"source": b["kep"], "target": a["kep"], "relation": "REPLACES"}
                                      for a, b in zip(trail, trail[1:])]}
            return out

    team = _find_team(g, q)
    if team:
        wk = gt.who_knows(g, team)
        out.update(tool="who_knows", official_owners=wk["official_owners"], actual_knowers=wk["actual_knowers"])
        hidden = wk["hidden_experts"]
        out["answer"] = (f"{team} has {len(wk['official_owners'])} official leaders (sigs.yaml). Ranked by design decisions "
                         f"(KEPs authored/reviewed/approved) and merged-PR reviews, {len(hidden)} of the top "
                         f"{len(wk['actual_knowers'])} people are not on the official chart"
                         + (f": {', '.join('@' + h for h in hidden)}." if hidden else "."))
        out["sources"] = [{"type": "REGISTRY", "ref": "sigs.yaml", "title": f"{team} leadership"},
                          {"type": "GRAPH", "ref": "KEP + PR reviews", "title": f"{team} activity"}]
        out["graph"] = {"nodes": [{"id": team, "label": team, "type": "Team"}] +
                        [{"id": k["login"], "label": k["login"], "type": "Person",
                          "status": "owner_and_knower" if k["is_official"] else "knower"} for k in wk["actual_knowers"]],
                        "edges": [{"source": k["login"], "target": team, "relation": "KNOWS",
                                   "weight": k["decisions_count"]} for k in wk["actual_knowers"]]}
        return out

    keps = gt.search_keps(g, q, k=5)
    out.update(tool="search_decisions", sources=[{"type": "KEP", "ref": f"KEP-{k['kep']}", "title": k["title"]} for k in keps])
    out["answer"] = ("Closest design decisions in the graph: " + "; ".join(f"KEP-{k['kep']} {k['title']} ({k['team']})" for k in keps)
                     if keps else "No matching team, decision or feature gate found in the graph.")
    return out
