# Lore — a company brain that knows who really knows

> Built for **WeMakeDevs × FalkorDB Graph Hacks** (Track 03: Company Brain · Track 01: Agents That Act on Connected Data).

Lore models how an organisation actually works as a FalkorDB property graph. It answers:
- **Who owns this?** — formal owners with the evidence path.
- **Who really knows this?** — people ranked by decisions authored, PRs reviewed, issues fixed.
- **Why was this decided?** — full decision trail: authors, approvers, replaces chain, release milestones.
- **Where should this issue go?** — team, related design decision, likely duplicates, top 2–3 experts.
- **What's stale?** — stuck decisions and docs that disagree with the latest choice.

Proven on **Kubernetes** — the largest open-source organisation whose inner workings (org chart, design decisions, tickets, reviews) are all public.

---

## Setup

### Prerequisites
- Python 3.11+
- Docker (to run FalkorDB)

### 1. Start FalkorDB

```bash
docker run -p 6379:6379 -p 3000:3000 -it --rm falkordb/falkordb:latest
```

Browse the graph visually at <http://localhost:3000>.

Or use Docker Compose (starts but does not keep data after `docker compose down`):

```bash
docker compose up falkordb
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Fetch the source data (one-time, ~5 MB)

```bash
mkdir -p data
git clone --depth 1 --filter=blob:none --sparse https://github.com/kubernetes/community.git data/community
git -C data/community sparse-checkout set --no-cone 'sigs.yaml'
git clone --depth 1 --filter=blob:none --sparse https://github.com/kubernetes/enhancements.git data/enhancements
git -C data/enhancements sparse-checkout set --no-cone 'keps/**/kep.yaml'
```

### 4. Load the graph

```bash
FALKORDB_HOST=localhost python scripts/load_k8s_brain.py data/
```

Expected output — first-load sanity check:

| Node | Count | | Edge | Count |
|------|-------|-|------|-------|
| Person | 760 | | REVIEWED | 1952 |
| KEP | 679 | | APPROVED | 1286 |
| FeatureGate | 450 | | REACHED | 1273 |
| Subproject | 240 | | AUTHORED | 1149 |
| Release | 59 | | (others) | 3111 |
| Team | 52 | | **Total** | **8771** |
| Component | 27 | | | |

---

## Graph data model

```
(Person)-[:LEADS {role}]->(Team)-[:HAS_SUBPROJECT]->(Subproject)
(Person)-[:AUTHORED|REVIEWED|APPROVED]->(KEP)
(KEP)-[:OWNED_BY|INVOLVES]->(Team)
(KEP)-[:REPLACES|SEE_ALSO]->(KEP)
(KEP)-[:INTRODUCES]->(FeatureGate)-[:USED_IN]->(Component)
(KEP)-[:REACHED {stage}]->(Release)
```

Planned additions (GitHub API data for sig-node, sig-scheduling, sig-auth, sig-storage, sig-network):

```
(Issue)-[:LABELED {at}]->(Team)
(Person)-[:AUTHORED|REVIEWED {at}]->(PR)-[:TOUCHES]->(Folder)
(PR)-[:FIXES]->(Issue)
(PR)-[:IMPLEMENTS]->(KEP)
(Person)-[:APPROVER_OF]->(Folder)      # from OWNERS files
(Person)-[:WROTE {at}]->(Comment)-[:ON]->(Issue|PR)
```

---

## Key Cypher queries

### Who are the official owners of a team?
```cypher
MATCH (p:Person)-[l:LEADS]->(:Team {key:'sig-node'})
RETURN p.display, collect(l.role)
ORDER BY p.display
```

### Who really knows a topic (by decision involvement)?
```cypher
MATCH (p:Person)-[:AUTHORED|REVIEWED|APPROVED]->(k:KEP)-[:OWNED_BY]->(:Team {key:'sig-node'})
RETURN p.display, count(DISTINCT k) AS decisions
ORDER BY decisions DESC LIMIT 10
```

### Why was this decision made? (replaces chain)
```cypher
MATCH path = (a:KEP)-[:REPLACES*1..6]->(b:KEP)
WHERE NOT ()-[:REPLACES]->(a)
RETURN [n IN nodes(path) | 'KEP-' + n.num + ' (' + n.status + ')'] AS chain
ORDER BY length(path) DESC LIMIT 5
```

### Which teams collaborate most?
```cypher
MATCH (a:Team)<-[:OWNED_BY|INVOLVES]-(k:KEP)-[:OWNED_BY|INVOLVES]->(b:Team)
WHERE a.key < b.key
RETURN a.key, b.key, count(DISTINCT k) AS shared
ORDER BY shared DESC LIMIT 10
```

### Who do I ask about a feature gate?
```cypher
MATCH (f:FeatureGate {name:$gate})<-[:INTRODUCES]-(k:KEP)-[:OWNED_BY]->(t:Team)
OPTIONAL MATCH (ap:Person)-[:APPROVED]->(k)
RETURN 'KEP-' + k.num, k.title, t.key, collect(DISTINCT ap.display) AS approvers
```

### Stale decisions (implementable at alpha, 8+ releases untouched)
```cypher
MATCH (k:KEP)-[:OWNED_BY]->(t:Team)
WHERE k.status = 'implementable' AND k.stage = 'alpha'
  AND k.latest_minor >= 0 AND k.latest_minor <= 30
RETURN count(k) AS stale, collect(t.key)[0..5] AS sample_teams
```

---

## Known data quirks

| Quirk | Handling |
|-------|----------|
| `replaces`/`superseded-by` mostly "n/a"/"none" | Filtered out; only 9 real KEP→KEP replace links remain |
| Name variants: `liggitt` vs `liggit` | Needs human-confirmed alias list (merge step planned) |
| 15 team names in KEPs not in sigs.yaml | Typos, retired groups, placeholders — none own a KEP |
| `last-updated` empty in 443 of 684 KEPs | Treated as normal; blank ≠ stale |
| 2 kep.yaml files fail to parse | Skipped; non-numeric `kep-number` values skipped |
| `/sigs.yaml` sparse-checkout on Windows | Use `sigs.yaml` (no leading slash) — Windows git treats `/` as filesystem root |

---

## Test results

_To be filled in after evaluation runs._

### Test 1 — Reviewer prediction
Predict the top 3 reviewers for ~500 merged PRs; baseline is OWNERS-file approvers.

| Method | Top-3 hit rate |
|--------|---------------|
| Baseline (OWNERS approvers) | TBD |
| Lore (graph ranking) | TBD |

### Test 2 — Issue routing
Route ~500 closed issues to their slice-team label; baseline is LLM text only.

| Method | Accuracy |
|--------|---------|
| Baseline (LLM text only) | TBD |
| Lore (graph + LLM) | TBD |

---

## Data sources and licences

| Source | Licence | Credit |
|--------|---------|--------|
| [kubernetes/community](https://github.com/kubernetes/community) `sigs.yaml` | Apache 2.0 | The Kubernetes Authors |
| [kubernetes/enhancements](https://github.com/kubernetes/enhancements) `keps/**/kep.yaml` | Apache 2.0 | The Kubernetes Authors |
| GitHub API (issues, PRs, reviews, OWNERS) | Public data via GitHub API ToS | kubernetes/kubernetes |

Only public data is stored. GitHub usernames and public work roles only — no emails, employers, or other personal details.

---

## AI usage

See [AI_USAGE.md](AI_USAGE.md) for the full log.

This project uses AI assistance for code generation and documentation. All AI-generated content is reviewed and understood by the team before use. AI is not used to fabricate test results.
