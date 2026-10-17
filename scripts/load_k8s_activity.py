"""Add real code ownership (OWNERS files) and review activity (merged PRs) to the Lore graph.

Run after load_k8s_brain.py (it adds to the existing 'k8s' graph):
  FALKORDB_HOST=localhost python scripts/load_k8s_activity.py data/k8s_repo data/prs.jsonl

Adds:
  (:Dir {path})-[:IN]->(:Dir)                 directory tree of OWNERS files
  (:Person)-[:OWNS_CODE {role}]->(:Dir)       official code owners (approvers/reviewers)
  (:Dir)-[:LABELED]->(:Team)                  sig/* labels declared in OWNERS
  (:PR {number,title,merged_ts})-[:TOUCHES]->(:Dir)
  (:Person)-[:OPENED|REVIEWED_PR|LGTM|APPROVED_PR]->(:PR)
  (:PR)-[:TAGGED]->(:Team)                    from sig/* labels
  (:Person)-[:SAME_AS]->(:Person)             entity resolution (typo / case variants)
"""
import datetime as dt
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from ownership import load_owners, nearest_owner_dir, sig_team  # noqa: E402

BOTS = {"k8s-ci-robot", "k8s-triage-robot", "dependabot", "k8s-infra-ci-robot"}


def connect():
    from falkordb import FalkorDB
    return FalkorDB(host=os.environ.get("FALKORDB_HOST", "localhost"), port=int(os.environ.get("FALKORDB_PORT", "6379")))


def edit1(a, b):
    """True if a and b differ by exactly one insert/delete/substitute."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = diff = 0
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            diff += 1
            if diff > 1:
                return False
            if len(a) == len(b):
                i += 1
            j += 1
        else:
            i += 1
            j += 1
    return diff + (len(b) - j) <= 1


def main(repo_dir, prs_path):
    owners = load_owners(repo_dir)
    g = connect().select_graph("k8s")
    for q in ("CREATE INDEX FOR (d:Dir) ON (d.path)", "CREATE INDEX FOR (pr:PR) ON (pr.number)"):
        try:
            g.query(q)
        except Exception:
            pass

    def load(query, rows, size=500):
        for i in range(0, len(rows), size):
            g.query(query, {"rows": rows[i:i + size]})

    dirs = [{"path": d, "parent": o["parent"]} for d, o in owners.items()]
    load("UNWIND $rows AS r MERGE (:Dir {path:r.path})", dirs)
    load("""UNWIND $rows AS r MATCH (d:Dir {path:r.path}), (p:Dir {path:r.parent})
            MERGE (d)-[:IN]->(p)""", [d for d in dirs if d["parent"] is not None])
    own_rows, label_rows = [], []
    for d, o in owners.items():
        for role in ("approvers", "reviewers"):
            for login in o[role]:
                own_rows.append({"login": login.lower(), "display": login, "path": d, "role": role[:-1]})
        for team in o["teams"]:
            label_rows.append({"path": d, "team": team})
    load("""UNWIND $rows AS r MATCH (d:Dir {path:r.path})
            MERGE (p:Person {login:r.login}) ON CREATE SET p.display=r.display
            MERGE (p)-[:OWNS_CODE {role:r.role}]->(d)""", own_rows)
    load("""UNWIND $rows AS r MATCH (d:Dir {path:r.path}) MERGE (t:Team {key:r.team})
            MERGE (d)-[:LABELED]->(t)""", label_rows)

    prs, touches, acts, tags = [], [], [], []
    with open(prs_path) as f:
        for line in f:
            pr = json.loads(line)
            ts = int(dt.datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00")).timestamp())
            prs.append({"number": pr["number"], "title": pr["title"], "merged_ts": ts, "merged_at": pr["merged_at"]})
            for d in sorted({nearest_owner_dir(owners, p) for p in pr["files"]}):
                touches.append({"number": pr["number"], "path": d})
            author = (pr["author"] or "").lower()
            if author and author not in BOTS:
                acts.append({"number": pr["number"], "login": author, "display": pr["author"], "rel": "OPENED"})
            for rel, key in (("REVIEWED_PR", "reviewers"), ("LGTM", "lgtm"), ("APPROVED_PR", "approvers")):
                for who in pr[key]:
                    if who.lower() not in BOTS and who.lower() != author and not who.endswith("[bot]"):
                        acts.append({"number": pr["number"], "login": who.lower(), "display": who, "rel": rel})
            for lab in pr["labels"]:
                team = sig_team(lab)
                if team:
                    tags.append({"number": pr["number"], "team": team})
    load("""UNWIND $rows AS r MERGE (pr:PR {number:r.number})
            SET pr.title=r.title, pr.merged_ts=r.merged_ts, pr.merged_at=r.merged_at""", prs)
    load("""UNWIND $rows AS r MATCH (pr:PR {number:r.number}), (d:Dir {path:r.path})
            MERGE (pr)-[:TOUCHES]->(d)""", touches)
    for rel in ("OPENED", "REVIEWED_PR", "LGTM", "APPROVED_PR"):
        load(f"""UNWIND $rows AS r MATCH (pr:PR {{number:r.number}})
                 MERGE (p:Person {{login:r.login}}) ON CREATE SET p.display=r.display
                 MERGE (p)-[:{rel}]->(pr)""", [a for a in acts if a["rel"] == rel])
    load("""UNWIND $rows AS r MATCH (pr:PR {number:r.number}) MERGE (t:Team {key:r.team})
            MERGE (pr)-[:TAGGED]->(t)""", tags)

    # Entity resolution: a login one edit away from a much more active login (3x the edges) is the same person.
    rows = g.query("""MATCH (p:Person) OPTIONAL MATCH (p)-[r]-()
                      RETURN p.login, count(r) AS deg""").result_set
    deg = {login: d for login, d in rows}
    logins = [lg for lg in deg if len(lg) >= 5]
    same = []
    for lg in logins:
        match = [k for k in logins if deg[k] >= max(5, 3 * deg[lg]) and edit1(lg, k)]
        if len(match) == 1:
            same.append({"alias": lg, "canonical": match[0]})
    load("""UNWIND $rows AS r MATCH (a:Person {login:r.alias}), (c:Person {login:r.canonical})
            MERGE (a)-[:SAME_AS]->(c)""", same)

    print(f"dirs={len(dirs)} code_owner_edges={len(own_rows)} prs={len(prs)} "
          f"pr_activity_edges={len(acts)} touches={len(touches)} same_as={len(same)}")
    for s in same[:15]:
        print(f"   SAME_AS {s['alias']} -> {s['canonical']}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
