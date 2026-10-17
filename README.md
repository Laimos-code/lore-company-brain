# Lore — The Kubernetes Company Brain

> **An AI company brain built on a FalkorDB graph.** It maps how an organization *really* works (who officially owns what vs. who actually does the work, why decisions were made), answers with sources, and routes new work to the right people. Proven on public Kubernetes data. Built for **WeMakeDevs × FalkorDB Graph Hacks**.

---

## 👥 Team & Responsibilities
- **Ashish**: Data ingestion, graph modeling, query tools, and web interface.
- **A**: AI Agent (`app/agent.py` implementing `ask(question)`).
- **You (Shobhit)**: Backend server, API contracts, security, rate limiting, and deployment.
- **C**: Action router (`app/actions.py` implementing the Approve button) and demo video.

---

## ⚡ Core Value Propositions

Every organization has two org charts:
1. **The Official One (`OWNS`)**: Stated in `sigs.yaml` and leadership rosters.
2. **The Real One (`KNOWS`)**: Lives in decision history, KEP authorship, code reviews, and approvals.

### What Lore Discovered on Real Kubernetes Data
- **760+ People, 679 Decisions (KEPs), 450 Feature Gates, 59 Releases, and 8,700+ Connections**.
- **Owns vs. Knows Gap**: In SIG Node, 3 of the top 8 contributors with the highest decision impact (`tallclair` with 31 decisions, `ffromani` with 21, `thockin` with 20) are **not** on the official team leadership chart.
- **Decision Trail & Replacements**: Traces decisions across an 8-year evolution (e.g. *Coscheduling* (KEP-583, 2018) &rarr; *Gang Scheduling* (KEP-4671, 2025) &rarr; *Decouple PodGroup API* (KEP-5832, 2026)).
- **Stale Decision Catch**: Surfaces decisions marked `implementable` at alpha stage that have gone untouched for 8+ releases.
- **Actionable Routing**: Triage incoming issues to the real experts and approve actions via `/api/actions/approve`.

---

## 🚀 Run It Yourself

### Option 1: Docker Compose (Recommended)

1. **Clone the repository and switch to branch `server`**:
   ```bash
   git clone https://github.com/Laimos-code/lore-company-brain.git
   cd lore-company-brain
   git checkout server
   ```

2. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your LLM keys if running live agent:
   # FALKORDB_HOST=falkordb
   # FALKORDB_PORT=6379
   # LLM_API_KEY=your_key_here
   ```

3. **Start FalkorDB and the App**:
   ```bash
   docker compose up -d
   ```
   *Note: Port 8000 is open for the web app. Ports 6379 and 3000 are kept private for database security.*

4. **Load the Kubernetes Brain Data**:
   Download the Kubernetes community and enhancement data (or use provided data sample), then run:
   ```bash
   # From host (connecting to localhost:6379 forwarded internally):
   FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 python scripts/load_k8s_brain.py data/
   ```

5. **Open Lore in your browser**:
   Navigate to [http://localhost:8000](http://localhost:8000) and click any of the example questions!

---

### Option 2: Run Locally on Your Laptop (Without Docker Compose)

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start FalkorDB with Docker**:
   ```bash
   docker run -p 127.0.0.1:6379:6379 -d --name falkordb falkordb/falkordb:latest
   ```

3. **Fetch Kubernetes Data**:
   ```bash
   mkdir -p data/community data/enhancements
   # Download Kubernetes SIGs registry:
   curl -sSL https://raw.githubusercontent.com/kubernetes/community/master/sigs.yaml -o data/community/sigs.yaml
   # Clone or sparse-checkout enhancements KEPs:
   git clone --depth 1 --filter=blob:none --sparse https://github.com/kubernetes/enhancements.git data/enhancements_repo
   cd data/enhancements_repo && git sparse-checkout set keps && cd ../..
   mv data/enhancements_repo/keps data/enhancements/keps
   ```

4. **Load Data into FalkorDB**:
   ```bash
   FALKORDB_HOST=localhost FALKORDB_PORT=6379 python scripts/load_k8s_brain.py data/
   ```

5. **Start the FastAPI Server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Open the Web UI**:
   Visit [http://localhost:8000](http://localhost:8000).

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
3. Load the data once:
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

## 🧠 Graph Model (FalkorDB graph `k8s`)

| Node | Source |
| :--- | :--- |
| `Person`, `Team` (SIG/WG) | `kubernetes/community` `sigs.yaml` |
| `KEP`, `FeatureGate`, `Release` | `kubernetes/enhancements` `kep.yaml` files |
| `Dir` | `OWNERS` / `OWNERS_ALIASES` in `kubernetes/kubernetes` (585 dirs) |
| `PR` | 3,135 merged `kubernetes/kubernetes` PRs, Jan–Oct 2026 (GitHub GraphQL) |

Relationships: `LEADS`, `AUTHORED`, `REVIEWED`, `APPROVED`, `OWNED_BY`, `REPLACES`, `INTRODUCES`, `REACHED` (decisions);
`OWNS_CODE {role}` (Person→Dir), `LABELED` (Dir→Team), `TOUCHES` (PR→Dir), `TAGGED` (PR→Team),
`OPENED`, `REVIEWED_PR`, `LGTM`, `APPROVED_PR` (Person→PR), and `SAME_AS` for entity resolution
(e.g. `liggit`, `ligitt` → `liggitt`; a login one edit away from a 3×-more-active login).

Build it:
```bash
python scripts/load_k8s_brain.py                                  # decisions graph
GITHUB_TOKEN=... python scripts/fetch_k8s_prs.py data/prs.jsonl   # merged PRs + reviews
python scripts/load_k8s_activity.py data/k8s_repo data/prs.jsonl  # OWNERS + PR activity
```

### Key Cypher queries (`app/graph_tools.py`)

Who actually knows a team (official chart vs. real work):
```cypher
MATCH (t:Team {key:$team})
OPTIONAL MATCH (p0:Person)-[:AUTHORED|REVIEWED|APPROVED]->(k:KEP)-[:OWNED_BY]->(t)
OPTIONAL MATCH (p0)-[:SAME_AS]->(c:Person)
WITH t, coalesce(c, p0) AS p, count(DISTINCT k) AS decisions ...
```
Team reviewers weighted by focus (so repo-wide reviewers don't drown out specialists):
```cypher
MATCH (p:Person)-[:REVIEWED_PR|LGTM|APPROVED_PR]->(pr:PR)-[:TAGGED]->(:Team {key:$t})
WITH p, count(DISTINCT pr) AS n WHERE n >= 3
MATCH (p)-[:REVIEWED_PR|LGTM|APPROVED_PR]->(all:PR)
WITH p, n, count(DISTINCT all) AS total
RETURN p.login, n, total, n * (n * 1.0 / total) AS s ORDER BY s DESC
```
Reviewer prediction for changed files: people with recency-decayed (90-day half-life) review activity on PRs
that `TOUCHES` the same `Dir` (weight 1.0), sibling dirs (0.3) or the same `Team` (0.2), role-weighted
(approve 2.0, lgtm 1.5, review 1.0). Decision trails follow `REPLACES*`; stale decisions are
`implementable` alpha KEPs last touched 8+ releases ago.

`/api/ask` answers from these queries when no LLM is configured (`app/brain.py`, `is_stub: false`).

### Evaluation: predicting real reviewers

`scripts/eval_reviewers.py`: graph built only from PRs merged **before 2026-08-01**; test set = the **846**
merged `kubernetes/kubernetes` PRs from 2026-08-01 to 2026-10-17 in our fetch. Truth = people who reviewed,
`/lgtm`-ed or `/approve`-d the PR (author excluded). Metric = hit@k (at least one true reviewer in the top k).
This is the scope of the number: it is not an overall accuracy claim.

| Method | hit@1 | hit@3 | hit@5 |
| :--- | ---: | ---: | ---: |
| **Lore graph ranking** | **0.233** | **0.609** | **0.709** |
| Most active reviewers repo-wide | 0.197 | 0.317 | 0.492 |
| Random OWNERS of the touched files (expected) | 0.097 | 0.264 | 0.389 |
| Official SIG leads (`sigs.yaml`) | 0.053 | 0.241 | 0.369 |

Raw output: [`docs/eval_reviewers.json`](docs/eval_reviewers.json).

---

## 📡 API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the interactive web interface (`web/index.html`). |
| `GET` | `/api/health` | Returns service health & FalkorDB connection status (`{"ok": true, "falkordb": true}`). |
| `POST` | `/api/ask` | Queries Lore brain with 60-second timeout guard and 20 req/min rate limit per IP. |
| `POST` | `/api/actions/approve` | Approves an issue routing triage, draft comment, or decision ping. |
| `GET` | `/api/actions/history` | Lists approved action history. |
| `GET` | `/api/demo-issues` | Lists open issues in the practice repo (`DEMO_REPO`). |
| `GET` | `/api/route-issue/{n}` | Graph suggestion for a practice issue: team, `sig/*` label, focused reviewers, draft comment. Posts nothing. |
| `POST` | `/api/approve` | Human-approved triage: posts the comment and adds allowed `sig/*` labels plus `triage/lore-suggested`. |

See [`docs/tool_contract.md`](docs/tool_contract.md) for full JSON request and response payloads.

---

## 🧪 Testing

Run automated tests:
```bash
pytest -o pythonpath=. tests/test_server.py
```
All 6 tests verify page serving, FalkorDB health ping, verified stub response, decision trails, rate limiting enforcement, and approve action flows.
