"""Fetch merged kubernetes/kubernetes PRs (files, reviews, /lgtm and /approve comments) to JSONL.

Usage: GITHUB_TOKEN=... python scripts/fetch_k8s_prs.py data/prs.jsonl 2026-01-01 2026-10-17
Read-only, public data. Splits the date range into weekly windows (GitHub search caps at 1000 results).
"""
import datetime as dt
import json
import os
import sys
import time

import httpx

QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 25, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title mergedAt author { login }
      labels(first: 30) { nodes { name } }
      files(first: 100) { nodes { path } }
      reviews(first: 50) { nodes { author { login } state } }
      comments(first: 80) { nodes { author { login } body } }
    } }
  }
}"""


def run(out_path, start, end):
    token = os.environ["GITHUB_TOKEN"]
    client = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"})
    day = dt.date.fromisoformat(start)
    last = dt.date.fromisoformat(end)
    seen = set()
    with open(out_path, "a") as out:
        while day <= last:
            nxt = min(day + dt.timedelta(days=6), last)
            q = f"repo:kubernetes/kubernetes is:pr is:merged merged:{day}..{nxt}"
            after = None
            while True:
                for attempt in range(5):
                    r = client.post("https://api.github.com/graphql", json={"query": QUERY, "variables": {"q": q, "after": after}})
                    data = r.json() if r.status_code == 200 else {}
                    if "data" in data and data["data"] and data["data"]["search"]:
                        break
                    time.sleep(5 * (attempt + 1))
                else:
                    raise SystemExit(f"GitHub error {r.status_code}: {r.text[:300]}")
                s = data["data"]["search"]
                for n in s["nodes"]:
                    if not n or n["number"] in seen:
                        continue
                    seen.add(n["number"])
                    approvers, lgtm = set(), set()
                    for c in n["comments"]["nodes"]:
                        who = (c.get("author") or {}).get("login")
                        body = c.get("body") or ""
                        if not who or who.endswith("-bot") or who == "k8s-ci-robot":
                            continue
                        lines = [ln.strip() for ln in body.splitlines()]
                        if any(ln.startswith("/approve") and "cancel" not in ln for ln in lines):
                            approvers.add(who)
                        if any(ln.startswith("/lgtm") and "cancel" not in ln for ln in lines):
                            lgtm.add(who)
                    reviewers = {(rv.get("author") or {}).get("login") for rv in n["reviews"]["nodes"]} - {None}
                    out.write(json.dumps({
                        "number": n["number"], "title": n["title"], "merged_at": n["mergedAt"],
                        "author": (n.get("author") or {}).get("login"),
                        "labels": [x["name"] for x in n["labels"]["nodes"]],
                        "files": [x["path"] for x in n["files"]["nodes"]],
                        "reviewers": sorted(reviewers), "lgtm": sorted(lgtm), "approvers": sorted(approvers),
                    }) + "\n")
                if not s["pageInfo"]["hasNextPage"]:
                    break
                after = s["pageInfo"]["endCursor"]
            print(day, nxt, len(seen), flush=True)
            day = nxt + dt.timedelta(days=1)


if __name__ == "__main__":
    run(*sys.argv[1:4])
