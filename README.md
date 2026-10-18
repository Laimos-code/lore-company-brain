# Lore — The Kubernetes Company Brain

> **An AI company brain built on a FalkorDB graph.** It maps how an organization *really* works (who officially owns what vs. who actually does the work, why decisions were made), answers with sources, and routes new work to the right people. Proven on public Kubernetes data. Built for **WeMakeDevs × FalkorDB Graph Hacks**.

---

## 👥 Team & Responsibilities
- **Ashish ([@Laimos-code](https://github.com/Laimos-code))**: data loading, graph model, graph tools (`app/tools.py`), web page.
- **Shobhit ([@shobhitagnihotri69](https://github.com/shobhitagnihotri69))**: FastAPI server, API contract, security and rate limits, AI agent (`app/agent.py`).
- **[@Mulaydm10](https://github.com/Mulaydm10)**: Live Triage actions (`app/actions.py`), graph answers without an AI model (`app/brain.py`), reviewer evaluation.

---

## ⚡ The problem

Every organization has two org charts:
1. **The official one (`OWNS`)**: team leads in `sigs.yaml`, approvers in `OWNERS` files.
2. **The real one (`KNOWS`)**: who writes the design decisions, reviews the code and answers the issues.

They drift apart. New people ask the official owner, who may not be the one doing the work; decisions get stuck
with nobody noticing; issues land with the wrong team. Kubernetes publishes both charts and all of its history,
so Lore proves the idea there: it puts both into one FalkorDB graph and answers from it, with sources.

### What Lore Discovered on Real Kubernetes Data
- **1,633 People, 679 Decisions (KEPs), 2,078 Merged PRs, 986 Issues, 645 Code Folders, 450 Feature Gates, 59 Releases, and 57,000+ Connections**.
- **Owns vs. Knows Gap**: In SIG Node, 3 of the top 8 contributors with the highest decision impact (`tallclair` with 31 decisions, `ffromani` with 21, `thockin` with 20) are **not** on the official team leadership chart.
- **Same gap in code review**: In each of the 5 teams we loaded, 5 or 6 of the top 8 PR reviewers are not that team's official leaders. `liggitt` (a SIG Auth lead) is a top-2 reviewer in all five.
- **Decision Trail & Replacements**: Traces decisions across an 8-year evolution (e.g. *Gang Scheduling* (KEP-4671, 2025) replaces both *Coscheduling* (KEP-583, 2018) and *Decouple PodGroup API* (KEP-5832, 2026), as its `kep.yaml` says).
- **Stale Decision Catch**: Surfaces decisions marked `implementable` at alpha stage that have gone untouched for 8+ releases.
- **Actionable Routing**: Triage incoming issues to the real experts and a person approves the draft before it is posted (`/api/route-issue/{n}` then `/api/approve`).

### Official vs. actual: top 8 PR reviewers per team

Score = REVIEWED + LGTM + APPROVED edges on the team's merged PRs (Oct 2025 – Oct 2026); ★ = official leader of that team.

| # | sig-node | sig-scheduling | sig-auth | sig-storage | sig-network |
|---|---|---|---|---|---|
| 1 | liggitt 616 | macsko ★ 513 | liggitt ★ 506 | liggitt 177 | aojea ★ 177 |
| 2 | SergeyKanzhelev ★ 461 | liggitt 390 | dims 104 | jsafrane ★ 128 | liggitt 175 |
| 3 | pohly 303 | dom4ha ★ 185 | jpbetz 79 | xing-yang ★ 97 | danwinship ★ 145 |
| 4 | dims 252 | pohly 143 | enj ★ 63 | dims 96 | dims 83 |
| 5 | ffromani 135 | ania-borowiec 141 | soltysh 39 | gnufied ★ 70 | thockin ★ 42 |
| 6 | tallclair 125 | dims 108 | pohly 38 | jpbetz 67 | jpbetz 41 |
| 7 | haircommander ★ 123 | tosi3k 97 | thockin 33 | carlory 38 | sbangari 32 |
| 8 | bart0sh 116 | mm4tt 90 | wojtek-t 33 | thockin 36 | Verolop 27 |
| **not leaders** | **6 of 8** | **6 of 8** | **6 of 8** | **5 of 8** | **5 of 8** |

---

## ⚙️ How it works

1. **Load** (`scripts/`): teams and leaders from `sigs.yaml`, design decisions from every `kep.yaml`, 12 months of
   PRs and issues from the GitHub API, and official code owners from `OWNERS` files go into one FalkorDB graph, `k8s`.
2. **Tools** (`app/tools.py`): five Cypher-backed tools: `who_owns`, `who_knows` (counts real evidence, can look
   back in time with `as_of`), `why` (decision trail), `whats_stale` and `route_issue`. Each returns a summary,
   the data, a small evidence map and source links.
3. **Answer** (`app/agent.py`, `app/brain.py`): with an AI model configured, the agent picks the tools and writes
   a cited answer. Without one, or if the model fails or hits its quota, Lore answers straight from the graph.
4. **Show and act** (`web/index.html`): the chat page shows the answer, official owners vs. the people who do the
   work, the evidence map and sources. For a new issue, a person reviews Lore's draft and approves posting it to
   our practice repo; nothing is ever posted to real Kubernetes repos.

---

## 🚀 Run It Yourself

### Option 1: Docker Compose (Recommended)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Laimos-code/lore-company-brain.git
   cd lore-company-brain
   ```

2. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   # All optional. LLM_API_KEY turns on the AI agent (without it Lore answers from the graph);
   # DEMO_REPO + DEMO_GITHUB_TOKEN turn on Live Triage; set APPROVE_PASSCODE on a public server.
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
   To also load PRs, issues and code owners, follow [📥 Load the data](#-load-the-data).

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
   To also load PRs, issues and code owners, follow [📥 Load the data](#-load-the-data).

5. **Start the FastAPI Server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. **Open the Web UI**:
   Visit [http://localhost:8000](http://localhost:8000).

---

## 📥 Load the data

Run these from the repo root while FalkorDB is up. Downloads stay in `data/`, which is not committed.

1. **Teams and design decisions (KEPs).** Download `sigs.yaml` and the KEPs (Option 2, step 3), then:
   ```bash
   FALKORDB_HOST=localhost python scripts/load_k8s_brain.py data/
   ```
   This step starts the `k8s` graph from scratch. Steps 2 and 3 only add to it, so they are safe to re-run.

2. **GitHub PRs and issues** for sig-node, sig-scheduling, sig-auth, sig-storage and sig-network (12 months).
   Put `GITHUB_TOKEN=...` in `.env`. Every answer is cached in `data/raw/`, so a re-run continues where it stopped.
   ```bash
   python scripts/fetch_github.py
   FALKORDB_HOST=localhost python scripts/load_github.py
   ```

3. **Official code owners** from the `OWNERS` files of `kubernetes/kubernetes` (downloads only those files, about 6 MB):
   ```bash
   git clone --depth 1 --filter=blob:none --sparse https://github.com/kubernetes/kubernetes data/k8s-owners
   git -C data/k8s-owners sparse-checkout set --no-cone "**/OWNERS" "/OWNERS_ALIASES"
   FALKORDB_HOST=localhost python scripts/load_owners.py
   ```
   On Windows Git Bash, start the `sparse-checkout` line with `MSYS_NO_PATHCONV=1`. Otherwise Git Bash turns
   `/OWNERS_ALIASES` into a Windows path and that file is never downloaded.

## 🧠 Graph model (FalkorDB graph `k8s`)

Counts from the full load on 2026-10-18: **6,849 nodes and 57,379 edges**.
GitHub data: `kubernetes/kubernetes` PRs merged and issues created from 2025-10-18 to 2026-10-18 with a
`sig/node`, `sig/scheduling`, `sig/auth`, `sig/storage` or `sig/network` label.

| Node | Key properties | Count | Loaded by |
| :--- | :--- | ---: | :--- |
| `Person` | `login` (lowercase), `display` | 1,633 | every loader |
| `Team` | `key` (e.g. `sig-node`), `name`, `kind` | 52 | `load_k8s_brain.py` (`sigs.yaml`) |
| `Subproject` | `name` | 240 | `load_k8s_brain.py` |
| `KEP` | `num`, `title`, `status`, `stage`, `created`, `latest`, `path` (its folder in kubernetes/enhancements) | 679 | `load_k8s_brain.py` (`kep.yaml`) |
| `FeatureGate` | `name` | 450 | `load_k8s_brain.py` |
| `Component` | `name` | 27 | `load_k8s_brain.py` |
| `Release` | `version` | 59 | `load_k8s_brain.py` |
| `PR` | `num`, `title`, `created`, `merged` | 2,078 | `load_github.py` |
| `Issue` | `num`, `title`, `created`, `closed`, `state` | 986 | `load_github.py` |
| `Folder` | `path` (e.g. `pkg/scheduler/framework`) | 645 | `load_github.py` |

```
DECISIONS (load_k8s_brain.py)                            count
(Person)-[:LEADS {role}]->(Team)                           174
(Team)-[:HAS_SUBPROJECT]->(Subproject)                     241
(Person)-[:AUTHORED]->(KEP)                              1,149
(Person)-[:REVIEWED]->(KEP)                              1,952
(Person)-[:APPROVED]->(KEP)                              1,286
(KEP)-[:OWNED_BY]->(Team)                                  683
(KEP)-[:INVOLVES]->(Team)                                  487
(KEP)-[:REPLACES]->(KEP)                                     9
(KEP)-[:SEE_ALSO]->(KEP)                                   298
(KEP)-[:INTRODUCES]->(FeatureGate)                         478
(FeatureGate)-[:USED_IN]->(Component)                      741
(KEP)-[:REACHED {stage}]->(Release)                      1,273

WORK (load_github.py)
(Person)-[:AUTHORED {at}]->(PR)                          2,078
(Person)-[:REVIEWED {at, state}]->(PR)                   3,328
(Person)-[:LGTM {at}]->(PR)                              2,136   a comment had a /lgtm line
(Person)-[:APPROVED {at}]->(PR)                          1,600   a comment had an /approve line
(Person)-[:AUTHORED {at}]->(Issue)                         986
(Person)-[:COMMENTED {at}]->(Issue)                      2,484
(Person)-[:ASSIGNED]->(Issue)                              614
(PR)-[:FOR_TEAM]->(Team)                                 3,131
(Issue)-[:FOR_TEAM]->(Team)                              1,046
(PR)-[:TOUCHES]->(Folder)                               10,172

OFFICIAL CODE OWNERS (load_owners.py, from OWNERS files)
(Person)-[:APPROVER_OF {source}]->(Folder)               9,285
(Person)-[:REVIEWER_OF {source}]->(Folder)              11,748
```

How to read it:
- **One Person per login.** Logins are lowercased, fixed with `data/aliases.yaml` and bots are dropped (one shared rule in `scripts/logins.py`).
- **`AUTHORED`, `REVIEWED` and `APPROVED` point to both KEPs and PRs**, so always label the target in queries: `(k:KEP)` or `(pr:PR)`.
- **`at`** is the person's earliest date on that PR or issue (ISO text such as `2026-01-05T12:34:56Z`, which sorts correctly as text).
- **`REVIEWED`** is one edge per person per PR. `state` is their strongest verdict: `APPROVED`, then `CHANGES_REQUESTED`, then `COMMENTED`.
- **The author doesn't count as their own reviewer.** A PR author's own reviews, `/lgtm` and `/approve` aren't counted, and neither are comments on their own issue.
- **`FOR_TEAM`** links an item to every slice team whose `sig/*` label it has (519 PRs have two or more).
- **`Folder`** is the first 3 folder levels of a changed file. Under `staging/src/` it's the 3 levels after that (e.g. `staging/src/k8s.io/kubelet/pkg`), so each staging library gets its own folders.
- **`APPROVER_OF` / `REVIEWER_OF`** follow Prow's rules: the nearest OWNERS file plus its parents, stopping at `no_parent_owners`. `source` is the OWNERS file that lists the person, e.g. `pkg/scheduler/OWNERS`.

### Example Cypher queries

1. Top PR reviewers of a team, marked if they are official leaders (`scripts/load_github.py` prints this for all 5 teams):
```cypher
MATCH (:Team {key:$team})<-[:FOR_TEAM]-(:PR)<-[e:REVIEWED|LGTM|APPROVED]-(p:Person)
WITH p, count(e) AS total ORDER BY total DESC LIMIT 8
OPTIONAL MATCH (p)-[:LEADS]->(lt:Team)
RETURN p.display, total, $team IN collect(lt.key) AS official_leader ORDER BY total DESC
```

2. Official owners vs. who does the work in a code folder (`who_owns` / `who_knows`):
```cypher
MATCH (f:Folder {path:'pkg/kubelet/cm'})<-[:TOUCHES]-(pr:PR)<-[e:REVIEWED|LGTM|APPROVED]-(p:Person)
WITH f, p, count(DISTINCT pr) AS prs ORDER BY prs DESC LIMIT 8
OPTIONAL MATCH (p)-[a:APPROVER_OF]->(f)
RETURN p.login, prs, a IS NOT NULL AS official_approver, a.source AS owners_file
```

3. Decision trail: what a KEP replaced and what replaced it (`why`):
```cypher
MATCH (k:KEP {num:'4671'})
OPTIONAL MATCH (newer:KEP)-[:REPLACES*1..6]->(k)
OPTIONAL MATCH (k)-[:REPLACES*1..6]->(older:KEP)
RETURN k.title, collect(DISTINCT newer.num) AS replaced_by, collect(DISTINCT older.num) AS replaces
```

## ⚠️ Data quirks

- OWNERS files are today's version, not historical, so the reviewer test compares against today's official list.
- `/lgtm cancel` and `/approve cancel` count as LGTM and APPROVED: the download keeps only a yes/no flag per comment, not its text.
- The download keeps the first 100 changed files and 50 reviews of a PR; 74 PRs have more files and 74 more reviews.
- `ASSIGNED` has no date: the download doesn't include when someone was assigned.
- Files in the repo root (`go.mod`, `go.sum`, ...) have no `Folder`.
- Misspelled logins in KEP files are merged via `data/aliases.yaml` only after a check against the GitHub API
  (the wrong name has no account, the right one is active in the same team): `liggit`, `gnuified`,
  `mattcarry`, `sjennning`. Five other likely typos (`dnishi`, `jinxu97`, `ligitt`, `saadali`, `yujihong`)
  are real, different accounts, so they are kept as they are.
- In `OWNERS` files, every list under `filters:` is merged. So `staging/OWNERS`'s approvers for `go.mod`/`go.sum` count as approvers of every staging folder.

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
3. Load the data once: run the three steps in [📥 Load the data](#-load-the-data) with
   `FALKORDB_HOST=127.0.0.1` (FalkorDB needs about 11 MB of memory for the full graph; a dump is 1.5 MB).
   Put the server's settings in `.env` (see `.env.example`), and set `APPROVE_PASSCODE` before going public.
4. Set up HTTPS with Caddy (automatic Let's Encrypt certificates):
   ```caddy
   lore.yourdomain.com {
       reverse_proxy localhost:8000
   }
   ```
   Or use Cloudflare Tunnel without opening any inbound ports.

---

## 📊 Evaluation: predicting real reviewers

`FALKORDB_HOST=localhost python scripts/eval_reviewers.py 2026-08-01` reads everything from the graph.
Test set: merged PRs of the 5 slice teams with `merged >= 2026-08-01` that have a reviewer other than the
author. No peeking: for each test PR, Lore only sees evidence dated before the day that PR was opened, so a
PR's own reviews never help predict it. hit@k = share of test PRs where at least one of
the top k suggestions really reviewed, `/lgtm`-ed or `/approve`-d it. This is the scope of the number, not an
overall accuracy claim. Caveat: OWNERS files are today's, not the ones in force at the cutoff.

| Method (446 test PRs) | hit@1 | hit@3 | hit@5 |
| :--- | ---: | ---: | ---: |
| **Lore** (`_knowers` on touched folders, then team) | 50% | 77% | 84% |
| Busiest reviewers before the PR was opened | 18% | 43% | 57% |
| Random OWNERS approvers of touched folders | 6% | 16% | 27% |
| Random OWNERS approvers + reviewers | 4% | 13% | 21% |
| Random official SIG leads of the PR's team | 12% | 34% | 45% |

Raw output: [`docs/eval_reviewers.json`](docs/eval_reviewers.json).

---

## 📡 API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the interactive web interface (`web/index.html`). |
| `GET` | `/api/health` | Returns service health & FalkorDB connection status (`{"ok": true, "falkordb": true}`). |
| `POST` | `/api/ask` | Queries Lore brain with 60-second timeout guard and 20 req/min rate limit per IP. |
| `POST` | `/api/actions/approve` | Deprecated stub kept for the contract; posts nothing. |
| `GET` | `/api/actions/history` | Lists approved action history. |
| `GET` | `/api/demo-issues` | Lists open issues in the practice repo (`DEMO_REPO`). |
| `GET` | `/api/route-issue/{n}` | `app.tools.route_issue` on a practice issue: team, `sig/*` label, people, draft comment. Posts nothing. 10/min per visitor. |
| `POST` | `/api/approve` | Human-approved triage: posts the comment and adds allowed `sig/*` labels plus `triage/lore-suggested`. 3/min per visitor, `APPROVE_DAILY_CAP`/day, optional `APPROVE_PASSCODE`; only `DEMO_REPO_OWNER` repos. |

See [`docs/tool_contract.md`](docs/tool_contract.md) for full JSON request and response payloads.

---

## 🧪 Testing

```bash
pytest -o pythonpath=. tests/
```
49 tests: the server and its safety limits (`test_server.py`), the agent's tool loop with a scripted fake model
(`test_agent.py`; no test calls a real AI model), and the graph tools on the real graph (`test_tools.py`; contract
in [`docs/tool_contract.md`](docs/tool_contract.md) section 4). The graph tests skip themselves until all three
loaders in [📥 Load the data](#-load-the-data) have run.

---

## 📚 Data sources and licences

| Data | Source | Licence |
| :--- | :--- | :--- |
| Teams, leaders, subprojects | [`kubernetes/community`](https://github.com/kubernetes/community) `sigs.yaml` | Apache-2.0 |
| Design decisions (KEPs) | [`kubernetes/enhancements`](https://github.com/kubernetes/enhancements) `kep.yaml` files | Apache-2.0 |
| Official code owners | [`kubernetes/kubernetes`](https://github.com/kubernetes/kubernetes) `OWNERS` / `OWNERS_ALIASES` | Apache-2.0 |
| PRs, reviews, issues | GitHub GraphQL API, public `kubernetes/kubernetes` data | GitHub Terms of Service |

Only public GitHub logins and public work activity are stored: no emails, names, employers or comment text.
Lore's own code is MIT-licensed (`LICENSE`).

## 🤖 AI usage

Parts of this project were written with help from an AI coding assistant. Every change was read, run and
tested by the team before it was committed; the evaluation numbers come from our own scripts. Details in
[`AI_USAGE.md`](AI_USAGE.md).
