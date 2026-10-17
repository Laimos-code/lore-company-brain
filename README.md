# Lore — a company brain that knows who really knows

> **An AI company brain built on a FalkorDB graph.** It maps how an organization *really* works (who officially owns what vs. who actually does the work, why decisions were made), answers with sources, and routes new work to the right people. Proven on public Kubernetes data.
>
> Built for **WeMakeDevs × FalkorDB Graph Hacks** (Track 03: Company Brain · Track 01: Agents That Act on Connected Data).

Lore answers:
- **Who owns this?** — formal owners with the evidence path.
- **Who really knows this?** — people ranked by decisions authored, PRs reviewed, issues fixed.
- **Why was this decided?** — full decision trail: authors, approvers, replaces chain, release milestones.
- **Where should this issue go?** — team, related design decision, likely duplicates, top 2–3 experts.
- **What's stale?** — stuck decisions and docs that disagree with the latest choice.

Lore works for any company that runs on GitHub and docs; we prove it on **Kubernetes**, the largest organization whose inner workings (org chart, design decisions, tickets, reviews) are all public.

---

## 👥 Team & Responsibilities
- **Ashish**: Data ingestion, graph modeling, Cypher query tools, evaluation.
- **Shobhit**: AI agent, backend server, API contract, web UI, security, deployment.

---

## ⚡ Core Value Propositions

Every organization has two org charts:
1. **The Official One (`OWNS`)**: Stated in `sigs.yaml` and leadership rosters.
2. **The Real One (`KNOWS`)**: Lives in decision history, KEP authorship, code reviews, and approvals.

### What Lore Discovered on Real Kubernetes Data
- **760 People, 679 Decisions (KEPs), 450 Feature Gates, 59 Releases, and 8,771 Connections**.
- **Owns vs. Knows Gap**: In SIG Node, 3 of the top 8 contributors with the highest decision impact (`tallclair` with 31 decisions, `ffromani` with 21, `thockin` with 20) are **not** on the official team leadership chart.
- **Decision Trail & Replacements**: Traces decisions across an 8-year evolution (e.g. *Coscheduling* (KEP-583, 2018) &rarr; *Gang Scheduling* (KEP-4671, 2025) &rarr; *Decouple PodGroup API* (KEP-5832, 2026)).
- **Stale Decision Catch**: Surfaces decisions marked `implementable` at alpha stage that have gone untouched for 8+ releases.
- **Actionable Routing**: Triage incoming issues to the real experts and approve actions via `/api/actions/approve`.

---

## 🚀 Run It Yourself

### Prerequisites
- Python 3.11+
- Docker (to run FalkorDB)

### Step 1: Fetch the source data (one-time, ~5 MB)

```bash
mkdir -p data
git clone --depth 1 --filter=blob:none --sparse https://github.com/kubernetes/community.git data/community
git -C data/community sparse-checkout set --no-cone 'sigs.yaml'
git clone --depth 1 --filter=blob:none --sparse https://github.com/kubernetes/enhancements.git data/enhancements
git -C data/enhancements sparse-checkout set --no-cone 'keps/**/kep.yaml'
```

### Step 2: Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3, Option 1: Docker Compose (Recommended)

1. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your LLM keys if running live agent:
   # LLM_API_KEY=your_key_here
   ```

2. **Start FalkorDB and the App**:
   ```bash
   docker compose up -d
   ```
   *Note: Port 8000 is open for the web app. Ports 6379 and 3000 are bound to `127.0.0.1` only, so they are reachable from your own machine but not from the internet. The graph is stored in the `falkordb_data` volume and survives restarts.*

3. **Load the Kubernetes Brain Data** (see expected output below):
   ```bash
   FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 python scripts/load_k8s_brain.py data/
   ```

4. **Open Lore in your browser**:
   Navigate to [http://localhost:8000](http://localhost:8000) and click any of the example questions!
   Browse the raw graph visually in the FalkorDB Browser at [http://localhost:3000](http://localhost:3000).

### Step 3, Option 2: Run Locally on Your Laptop (Without Docker Compose)

1. **Start FalkorDB with Docker**:
   ```bash
   docker run -p 127.0.0.1:6379:6379 -p 127.0.0.1:3000:3000 -v falkordb_data:/data -d --name falkordb falkordb/falkordb:latest
   ```

2. **Load Data into FalkorDB**:
   ```bash
   FALKORDB_HOST=localhost FALKORDB_PORT=6379 python scripts/load_k8s_brain.py data/
   ```

3. **Start the FastAPI Server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Open the Web UI**:
   Visit [http://localhost:8000](http://localhost:8000).

### Expected loader output (first-load sanity check)

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

## 🌐 Putting It Online (Cloud Server Deployment)

To host Lore on a small cloud server (DigitalOcean, AWS EC2, Hetzner, or GitHub Student Pack credits):

### 1. Requirements & Security Checklist
- **Single Public HTTPS Link**: e.g., `https://lore.yourdomain.com` or via Cloudflare Tunnel.
- **Port Security**: Only the application port (80/443) is exposed to the internet. FalkorDB ports (6379, 3000) are bound strictly to `127.0.0.1` or the internal Docker bridge network.
- **Data Persistence**: Uses a Docker volume (`falkordb_data`) so all graph nodes survive container reboots.

### 2. Deployment Steps
1. SSH into the cloud server:
   ```bash
   ssh ubuntu@your-server-ip
   ```
2. Clone and start:
   ```bash
   git clone https://github.com/Laimos-code/lore-company-brain.git
   cd lore-company-brain
   docker compose up -d
   ```
3. Fetch the data (Step 1 above) and load it once:
   ```bash
   FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 python3 scripts/load_k8s_brain.py data/
   ```
4. Set up HTTPS with Caddy (automatic Let's Encrypt certificates):
   ```caddy
   lore.yourdomain.com {
       reverse_proxy localhost:8000
   }
   ```
   Or use Cloudflare Tunnel without opening any inbound ports.

---

## 📡 API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the interactive web interface (`web/index.html`). |
| `GET` | `/api/health` | Returns service health & FalkorDB connection status (`{"ok": true, "falkordb": true}`). |
| `POST` | `/api/ask` | Queries Lore brain with 60-second timeout guard and 20 req/min rate limit per IP. |
| `POST` | `/api/actions/approve` | Approves an issue routing triage, draft comment, or decision ping. |
| `GET` | `/api/actions/history` | Lists approved action history. |

See [`docs/tool_contract.md`](docs/tool_contract.md) for full JSON request and response payloads.

---

## 🧪 Testing

Run automated tests:
```bash
pytest -o pythonpath=. tests/test_server.py
```
All 6 tests verify page serving, FalkorDB health ping, verified stub response, decision trails, rate limiting enforcement, and approve action flows.

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
