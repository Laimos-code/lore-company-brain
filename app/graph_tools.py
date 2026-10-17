"""Lore graph tools: deterministic Cypher queries over the FalkorDB 'k8s' graph.

Used by the API (routing, who-knows, decision trails, stale decisions) and by
scripts/eval_reviewers.py, so the number we report is produced by the same code the demo runs.
"""
import os
import re
from typing import Any, Dict, List, Optional

HALF_LIFE_S = 90 * 24 * 3600  # recency decay: activity 90 days old counts ~37%
ROLE_WEIGHT = {"APPROVED_PR": 2.0, "LGTM": 1.5, "REVIEWED_PR": 1.0}
STOPWORDS = set("""a an the and or of to in on for with is are be by it this that from as at not after before when
into our we can still but if no yes how what why who does do has have only some get got after""".split())


def get_graph():
    from falkordb import FalkorDB
    db = FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379")))
    return db.select_graph("k8s")


def _rows(g, q, params=None):
    return g.query(q, params or {}).result_set


def suggest_reviewers(g, dirs: List[str], teams: Optional[List[str]] = None, cutoff_ts: Optional[int] = None,
                      exclude: Optional[List[str]] = None, k: int = 5) -> List[Dict[str, Any]]:
    """Rank people by recency-weighted review/approve activity on PRs touching the same code
    (exact OWNERS dir = 1.0, sibling dir under the same parent = 0.3) plus the owning team's PRs (0.2)."""
    cutoff = cutoff_ts if cutoff_ts is not None else 2 ** 40
    exclude = [e.lower() for e in (exclude or [])]
    params = {"dirs": dirs, "cutoff": cutoff, "exclude": exclude, "teams": teams or [], "hl": float(HALF_LIFE_S)}
    weight = """CASE type(r) WHEN 'APPROVED_PR' THEN 2.0 WHEN 'LGTM' THEN 1.5 ELSE 1.0 END
                * exp(-1.0 * ($cutoff - pr.merged_ts) / $hl)"""
    scores: Dict[str, Dict[str, Any]] = {}

    def add(q, w, kind):
        for login, s, n in _rows(g, q, params):
            e = scores.setdefault(login, {"login": login, "score": 0.0, "evidence": {}})
            e["score"] += w * s
            e["evidence"][kind] = e["evidence"].get(kind, 0) + n

    add(f"""MATCH (d:Dir) WHERE d.path IN $dirs
            MATCH (p:Person)-[r:REVIEWED_PR|LGTM|APPROVED_PR]->(pr:PR)-[:TOUCHES]->(d)
            WHERE pr.merged_ts < $cutoff AND NOT p.login IN $exclude
            RETURN p.login, sum({weight}), count(DISTINCT pr)""", 1.0, "prs_same_code")
    add(f"""MATCH (d:Dir)-[:IN]->(parent:Dir)<-[:IN]-(sib:Dir) WHERE d.path IN $dirs AND NOT sib.path IN $dirs
            MATCH (p:Person)-[r:REVIEWED_PR|LGTM|APPROVED_PR]->(pr:PR)-[:TOUCHES]->(sib)
            WHERE pr.merged_ts < $cutoff AND NOT p.login IN $exclude
            RETURN p.login, sum({weight}), count(DISTINCT pr)""", 0.3, "prs_nearby_code")
    if teams:
        add(f"""MATCH (t:Team) WHERE t.key IN $teams
                MATCH (p:Person)-[r:REVIEWED_PR|LGTM|APPROVED_PR]->(pr:PR)-[:TAGGED]->(t)
                WHERE pr.merged_ts < $cutoff AND NOT p.login IN $exclude
                RETURN p.login, sum({weight}), count(DISTINCT pr)""", 0.2, "prs_same_team")
    ranked = sorted(scores.values(), key=lambda e: -e["score"])[:k]
    for e in ranked:
        e["score"] = round(e["score"], 3)
    return ranked


def team_reviewers(g, team: str, k: int = 3) -> List[Dict[str, Any]]:
    """People who review this team's merged PRs, weighted by focus (share of their reviews on this team),
    so repo-wide reviewers (dependency bumps, API reviews) don't crowd out the real specialists."""
    rows = _rows(g, """MATCH (p:Person)-[:REVIEWED_PR|LGTM|APPROVED_PR]->(pr:PR)-[:TAGGED]->(:Team {key:$t})
        WITH p, count(DISTINCT pr) AS n WHERE n >= 3
        MATCH (p)-[:REVIEWED_PR|LGTM|APPROVED_PR]->(all:PR)
        WITH p, n, count(DISTINCT all) AS total
        RETURN p.login, n, total, n * (n * 1.0 / total) AS s ORDER BY s DESC LIMIT $k""", {"t": team, "k": k})
    return [{"login": lg, "score": round(sc, 2), "evidence": {"team_prs": n, "all_prs": tot, "focus": round(n / tot, 2)}}
            for lg, n, tot, sc in rows]


def official_leads(g, teams: List[str]) -> List[str]:
    return [r[0] for r in _rows(g, """MATCH (p:Person)-[:LEADS]->(t:Team) WHERE t.key IN $teams
                                      RETURN DISTINCT p.login ORDER BY p.login""", {"teams": teams})]


def who_knows(g, team: str, k: int = 8) -> Dict[str, Any]:
    """Official leaders (sigs.yaml) vs. people who actually decide (KEPs) and review (merged PRs)."""
    leads = {r[0]: r[1] for r in _rows(g, """MATCH (p:Person)-[l:LEADS]->(:Team {key:$t})
                                             RETURN p.display, collect(DISTINCT l.role)""", {"t": team})}
    rows = _rows(g, """MATCH (t:Team {key:$t})
        OPTIONAL MATCH (p0:Person)-[:AUTHORED|REVIEWED|APPROVED]->(k:KEP)-[:OWNED_BY]->(t)
        OPTIONAL MATCH (p0)-[:SAME_AS]->(c:Person)
        WITH t, coalesce(c, p0) AS p, count(DISTINCT k) AS decisions WHERE p IS NOT NULL
        OPTIONAL MATCH (p)-[:REVIEWED_PR|LGTM|APPROVED_PR]->(pr:PR)-[:TAGGED]->(t)
        RETURN p.display, decisions, count(DISTINCT pr) AS reviews
        ORDER BY decisions + reviews / 5.0 DESC LIMIT $k""", {"t": team, "k": k})
    official = {x.lower() for x in leads}
    knowers = [{"login": d, "decisions_count": n, "pr_reviews": r, "is_official": d.lower() in official}
               for d, n, r in rows]
    return {"team": team,
            "official_owners": [{"login": d, "role": ",".join(r)} for d, r in leads.items()],
            "actual_knowers": knowers,
            "hidden_experts": [x["login"] for x in knowers if not x["is_official"]]}


def decision_trail(g, text: str) -> Dict[str, Any]:
    """Find the decision (KEP) that best matches `text`, then walk REPLACES both ways."""
    hits = search_keps(g, text, k=1)
    if not hits:
        return {"trail": []}
    num = hits[0]["kep"]
    rows = _rows(g, """MATCH (k:KEP {num:$n})
        OPTIONAL MATCH p1 = (newer:KEP)-[:REPLACES*1..6]->(k)
        OPTIONAL MATCH p2 = (k)-[:REPLACES*1..6]->(older:KEP)
        WITH k, collect(DISTINCT newer) AS newer, collect(DISTINCT older) AS older
        UNWIND (older + [k] + newer) AS x
        OPTIONAL MATCH (x)-[:OWNED_BY]->(t:Team)
        OPTIONAL MATCH (a:Person)-[:APPROVED]->(x)
        RETURN DISTINCT x.num, x.title, x.status, x.stage, x.created, t.key, collect(DISTINCT a.display)""", {"n": num})
    trail = sorted(({"kep": f"KEP-{n}", "title": t, "status": s, "stage": st, "created": c, "team": tm,
                     "approvers": ap} for n, t, s, st, c, tm, ap in rows), key=lambda x: x["created"] or "")
    return {"matched": hits[0], "trail": trail}


def stale_decisions(g, releases_behind: int = 8, k: int = 10) -> Dict[str, Any]:
    latest = _rows(g, "MATCH (k:KEP) RETURN max(k.latest_minor)")[0][0]
    rows = _rows(g, """MATCH (k:KEP)-[:OWNED_BY]->(t:Team)
        WHERE k.status = 'implementable' AND k.stage = 'alpha' AND k.latest_minor >= 0 AND k.latest_minor <= $c
        OPTIONAL MATCH (a:Person)-[:AUTHORED]->(k)
        RETURN k.num, k.title, t.key, k.latest, collect(DISTINCT a.display), k.latest_minor AS lm ORDER BY lm""",
                 {"c": latest - releases_behind})
    return {"newest_release": f"v1.{latest}", "count": len(rows),
            "decisions": [{"kep": f"KEP-{n}", "title": t, "team": tm, "last_touched": lt, "authors": au}
                          for n, t, tm, lt, au, _ in rows[:k]]}


def _terms(text: str) -> List[str]:
    words = re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
    return [w for w in dict.fromkeys(words) if w not in STOPWORDS][:40]


def search_keps(g, text: str, k: int = 5) -> List[Dict[str, Any]]:
    """Score KEPs by how many issue words appear in their title (graph-side string matching)."""
    terms = _terms(text)
    if not terms:
        return []
    rows = _rows(g, """MATCH (k:KEP)-[:OWNED_BY]->(t:Team)
        WITH k, t, [w IN $terms WHERE toLower(k.title) CONTAINS w] AS hit
        WHERE size(hit) > 0
        RETURN k.num, k.title, t.key, hit, size(hit) * 1.0 / (1 + size(split(k.title, ' '))) AS s
        ORDER BY size(hit) DESC, s DESC LIMIT $k""", {"terms": terms, "k": k})
    return [{"kep": n, "title": t, "team": tm, "matched": h} for n, t, tm, h, _ in rows]


def route_issue(g, title: str, body: str, allowed_teams: Optional[List[str]] = None) -> Dict[str, Any]:
    """Suggest the owning team, reviewers and a draft comment for a new issue, with sources."""
    text = f"{title}\n{body}"
    keps = search_keps(g, text, k=8)
    votes: Dict[str, float] = {}
    for i, kp in enumerate(keps):
        votes[kp["team"]] = votes.get(kp["team"], 0) + len(kp["matched"]) / (1 + 0.15 * i)
    for team, w in _team_keyword_votes(text).items():
        votes[team] = votes.get(team, 0) + w
    if allowed_teams:
        votes = {t: v for t, v in votes.items() if t in allowed_teams}
    if not votes:
        return {"team": None, "reviewers": [], "related_decisions": [], "comment": ""}
    team = max(votes, key=votes.get)
    reviewers = team_reviewers(g, team, k=3)
    related = [kp for kp in keps if kp["team"] == team][:3]
    label = "sig/" + team[4:] if team.startswith("sig-") else None
    lines = [f"Thanks for the report. Lore suggests routing this to **{team.upper().replace('-', ' ')}**"
             + (f" (`{label}`)." if label else ".")]
    if related:
        lines.append("\nRelated design decisions:")
        lines += [f"- KEP-{r['kep']}: {r['title']}" for r in related]
    if reviewers:
        lines.append("\nPeople who recently reviewed this team's code:")
        lines += [f"- @{r['login']} (reviewed {r['evidence']['team_prs']} {team} merged PRs in the loaded window, "
                  f"{int(r['evidence']['focus'] * 100)}% of their reviews)" for r in reviewers]
    lines.append("\n_Suggested by Lore from the Kubernetes decision graph; approved by a human before posting._")
    return {"team": team, "label": label, "team_votes": {t: round(v, 2) for t, v in sorted(votes.items(), key=lambda x: -x[1])[:4]},
            "reviewers": reviewers, "related_decisions": related, "comment": "\n".join(lines)[:2000]}


_KEYWORDS = {
    "sig-node": "kubelet pod pods container runtime containerd cri sandbox eviction cgroup sidecar terminating probe oom",
    "sig-scheduling": "scheduler scheduling schedule preemption priority gang coscheduling topology spread affinity pending placement",
    "sig-auth": "rbac token tokens serviceaccount service-account authentication authorization secret secrets certificate oidc 401 403",
    "sig-storage": "volume volumes pvc pv csi storage attach detach mount snapshot capacity",
    "sig-network": "service services kube-proxy dns endpoint endpoints ingress networkpolicy loadbalancer externaltrafficpolicy traffic",
}


def _team_keyword_votes(text: str) -> Dict[str, float]:
    words = set(re.findall(r"[a-z0-9-]+", text.lower()))
    return {t: 1.5 * len(words & set(kw.split())) for t, kw in _KEYWORDS.items() if words & set(kw.split())}
