"""Reviewer-prediction test: does Lore's graph pick the people who actually review a PR
better than the official ownership chart?

  FALKORDB_HOST=localhost python scripts/eval_reviewers.py data/k8s_repo data/prs.jsonl 2026-08-01

Train = merged PRs before the cutoff (only those edges are used by Lore, via merged_ts < cutoff).
Test  = merged PRs on/after the cutoff that had at least one non-author reviewer/approver.
Truth = everyone (except the author and bots) who reviewed, /lgtm'd or /approve'd the PR.
Metric: hit@k = share of test PRs where at least one of the top-k suggestions is in the truth set.

Baselines (author always excluded):
  OWNERS-random: k people drawn at random from the OWNERS reviewers of the touched files
                 (what Prow's auto-assigner does); exact expected value, not a sample.
  SIG leads:     the official chairs / tech leads (sigs.yaml) of the PR's sig/* labels.
  Most active:   the k busiest reviewers in the whole repo before the cutoff (no graph structure).
"""
import datetime as dt
import json
import os
import sys
from math import comb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.graph_tools import get_graph, official_leads, suggest_reviewers  # noqa: E402
from app.ownership import load_owners, nearest_owner_dir, official_owners, sig_team  # noqa: E402

BOTS = {"k8s-ci-robot", "k8s-triage-robot", "k8s-infra-ci-robot"}


def p_hit_random(pool, truth, k):
    n, m = len(pool), len(pool & truth)
    if n == 0 or m == 0:
        return 0.0
    k = min(k, n)
    return 1 - comb(n - m, k) / comb(n, k)


def main(repo_dir, prs_path, cutoff_day, limit=None):
    cutoff = int(dt.datetime.fromisoformat(cutoff_day + "T00:00:00+00:00").timestamp())
    owners = load_owners(repo_dir)
    g = get_graph()
    test = []
    for line in open(prs_path):
        pr = json.loads(line)
        if pr["merged_at"] < cutoff_day:
            continue
        author = (pr["author"] or "").lower()
        truth = {x.lower() for x in pr["reviewers"] + pr["lgtm"] + pr["approvers"]} - BOTS - {author}
        truth = {t for t in truth if not t.endswith("[bot]")}
        if truth:
            test.append((pr, author, truth))
    if limit:
        test = test[:int(limit)]
    ks = (1, 3, 5)
    hits = {name: {k: 0.0 for k in ks} for name in ("lore", "owners_random", "sig_leads", "most_active")}
    busiest = [r[0] for r in g.query("""MATCH (p:Person)-[:REVIEWED_PR|LGTM|APPROVED_PR]->(pr:PR) WHERE pr.merged_ts < $c
                                        RETURN p.login, count(DISTINCT pr) AS n ORDER BY n DESC LIMIT 20""", {"c": cutoff}).result_set]
    covered = 0
    for pr, author, truth in test:
        dirs = sorted({nearest_owner_dir(owners, f) for f in pr["files"]})
        teams = sorted({t for t in (sig_team(lb) for lb in pr["labels"]) if t})
        lore = [e["login"] for e in suggest_reviewers(g, dirs, teams, cutoff_ts=cutoff, exclude=[author], k=max(ks))]
        pool = set()
        for f in pr["files"]:
            pool |= {x.lower() for x in official_owners(owners, f)["reviewers"]}
        pool.discard(author)
        leads = [x for x in official_leads(g, teams) if x != author]
        covered += bool(lore)
        for k in ks:
            hits["lore"][k] += bool(set(lore[:k]) & truth)
            hits["owners_random"][k] += p_hit_random(pool, truth, k)
            hits["sig_leads"][k] += bool(set(leads[:k]) & truth)
            hits["most_active"][k] += bool(set([b for b in busiest if b != author][:k]) & truth)
    n = len(test)
    result = {"cutoff": cutoff_day, "test_prs": n, "lore_had_suggestions": covered,
              "hit_at_k": {name: {f"@{k}": round(v[k] / n, 3) for k in ks} for name, v in hits.items()}}
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main(*sys.argv[1:5])
