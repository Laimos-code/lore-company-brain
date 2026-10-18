"""Can Lore predict who will review a PR? Everything is read from the k8s graph (main's schema).

    FALKORDB_HOST=localhost python scripts/eval_reviewers.py 2026-08-01

Test set: every merged PR in the graph with `merged >= cutoff` that has at least one reviewer
(REVIEWED, LGTM or APPROVED from someone other than its author).
No peeking: for each test PR, Lore and the busiest-reviewers baseline only see evidence dated
before the day that PR was opened (`as_of=<PR created day>`). The PR's own reviews all come
after that, so its answer can't leak into its prediction.
Metric: hit@k = share of test PRs where at least one of the top k suggestions really reviewed it.

Methods
  lore          app.tools._knowers (the ranking behind who_knows and route_issue's people) on each
                folder the PR TOUCHES, as of the day the PR was opened; totals summed over folders, author excluded;
                filled up from who_knows on the PR's FOR_TEAM team.
  most_active   the busiest reviewers in the whole graph before the day the PR was opened.
  owners_approvers   k random OWNERS approvers of the touched folders (exact expected value).
  owners_all         k random OWNERS approvers + reviewers of the touched folders (expected value).
  sig_leads          k random official leads (sigs.yaml) of the PR's teams (expected value).
Caveat: OWNERS files are today's (data/k8s-owners), not the ones in force at the cutoff.
"""
import json
import sys
from math import comb

from app import tools

KS = (1, 3, 5)


def p_hit_random(n_cand, n_true_in_cand, k):
    if n_cand == 0 or n_true_in_cand == 0:
        return 0.0
    k = min(k, n_cand)
    return 1.0 - comb(n_cand - n_true_in_cand, k) / comb(n_cand, k)


def main(cutoff):
    rows = tools._q("""MATCH (pr:PR) WHERE pr.merged >= $c
        OPTIONAL MATCH (a:Person)-[:AUTHORED]->(pr)
        WITH pr, collect(DISTINCT a.login) AS authors
        MATCH (r:Person)-[:REVIEWED|LGTM|APPROVED]->(pr)
        WITH pr, authors, collect(DISTINCT r.login) AS reviewers
        OPTIONAL MATCH (pr)-[:TOUCHES]->(f:Folder)
        WITH pr, authors, reviewers, collect(DISTINCT f.path) AS folders
        OPTIONAL MATCH (pr)-[:FOR_TEAM]->(t:Team)
        RETURN pr.num, pr.created, authors, reviewers, folders, collect(DISTINCT t.key)""", c=cutoff)
    busiest_by_day, folder_rank, team_rank, approvers, owners_all, leads = {}, {}, {}, {}, {}, {}

    def busiest(day):
        if day not in busiest_by_day:
            busiest_by_day[day] = [r[0] for r in tools._q("""MATCH (p:Person)-[e:REVIEWED|LGTM|APPROVED]->(pr:PR)
                WHERE e.at < $c RETURN p.login, count(DISTINCT pr) AS n ORDER BY n DESC LIMIT 20""", c=day)]
        return busiest_by_day[day]

    def ranked(cache, kind, key, day):
        if (key, day) not in cache:
            cache[(key, day)] = [(p["login"], p["total"]) for p in tools._knowers(kind, key, as_of=day)["ranked"]]
        return cache[(key, day)]

    def owners_of(path):
        if path not in approvers:
            res = tools._q("""MATCH (p:Person)-[e:APPROVER_OF|REVIEWER_OF]->(:Folder {path:$p})
                              RETURN p.login, type(e)""", p=path)
            approvers[path] = {l for l, t in res if t == "APPROVER_OF"}
            owners_all[path] = {l for l, _ in res}
        return approvers[path], owners_all[path]

    names = ("lore", "most_active", "owners_approvers", "owners_all", "sig_leads")
    hits = {n: dict.fromkeys(KS, 0.0) for n in names}
    n_test = 0
    for num, created, authors, reviewers, folders, teams in rows:
        truth = set(reviewers) - set(authors)
        if not truth:
            continue
        n_test += 1
        day = created[:10]  # everything Lore sees is dated before the day this PR was opened
        score = {}
        for path in folders:
            for login, total in ranked(folder_rank, "folder", path, day):
                score[login] = score.get(login, 0) + total
        lore = [l for l, _ in sorted(score.items(), key=lambda x: -x[1]) if l not in authors]
        for team in teams:
            lore += [l for l, _ in ranked(team_rank, "team", team, day) if l not in authors and l not in lore]
        active = [b for b in busiest(day) if b not in authors]
        appr = set().union(*(owners_of(p)[0] for p in folders)) - set(authors) if folders else set()
        alls = set().union(*(owners_of(p)[1] for p in folders)) - set(authors) if folders else set()
        for t in teams:
            if t not in leads:
                leads[t] = {x["login"] for x in tools._leads(t)}
        ld = set().union(*(leads[t] for t in teams)) - set(authors) if teams else set()
        for k in KS:
            hits["lore"][k] += bool(set(lore[:k]) & truth)
            hits["most_active"][k] += bool(set(active[:k]) & truth)
            hits["owners_approvers"][k] += p_hit_random(len(appr), len(appr & truth), k)
            hits["owners_all"][k] += p_hit_random(len(alls), len(alls & truth), k)
            hits["sig_leads"][k] += p_hit_random(len(ld), len(ld & truth), k)
    out = {"cutoff": cutoff, "test_prs": n_test,
           "no_peeking": "only evidence dated before the day each test PR was opened",
           "scope": "merged kubernetes/kubernetes PRs of the 5 slice teams in the graph, merged on/after cutoff",
           "hit_at_k": {n: {f"@{k}": round(v / max(n_test, 1), 3) for k, v in h.items()} for n, h in hits.items()}}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-08-01")
