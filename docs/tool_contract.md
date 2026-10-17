# Lore Company Brain — Tool & API Contract

This document defines the schema, graph model, and API contracts for **Lore**, the AI company brain built on FalkorDB using public Kubernetes organizational and decision records.

---

## 1. Graph Database Model (FalkorDB)

The graph name in FalkorDB is **`k8s`**.

### Node Labels & Properties

| Label | Primary Key / Index | Key Properties | Description |
| :--- | :--- | :--- | :--- |
| `Person` | `login` (lowercase) | `login`, `display` | A GitHub contributor, chair, reviewer, or author |
| `Team` | `key` | `key`, `name`, `kind` (`sig`, `workinggroup`, `committee`) | A Kubernetes Special Interest Group (SIG) or committee |
| `KEP` | `num` (string number) | `num`, `title`, `status`, `stage`, `created`, `latest`, `latest_minor` | Kubernetes Enhancement Proposal (written design decision) |
| `FeatureGate` | `name` | `name` | An on/off switch for a feature |
| `Release` | `version` | `version` | Kubernetes milestone release (e.g. `v1.30`) |
| `Component` | `name` | `name` | Binary/subsystem component (e.g. `kube-apiserver`, `kubelet`) |
| `Subproject` | `name` | `name` | Code repository / initiative managed by a team |

### Relationships & Semantics

- `(:Person)-[:LEADS {role: 'chair'|'tech_lead'}]->(:Team)`: Official leadership from `sigs.yaml`.
- `(:Person)-[:AUTHORED]->(:KEP)`: Authored design proposal.
- `(:Person)-[:REVIEWED]->(:KEP)`: Reviewed design proposal.
- `(:Person)-[:APPROVED]->(:KEP)`: Final approval on design proposal.
- `(:KEP)-[:OWNED_BY]->(:Team)`: Primary SIG responsible for the KEP.
- `(:KEP)-[:INVOLVES]->(:Team)`: Secondary or participating SIGs.
- `(:KEP)-[:REPLACES]->(:KEP)`: Decision history lineage (newer replaces older).
- `(:KEP)-[:SEE_ALSO]->(:KEP)`: Cross-decision reference.
- `(:KEP)-[:INTRODUCES]->(:FeatureGate)`: Feature flag toggling this design.
- `(:FeatureGate)-[:USED_IN]->(:Component)`: Subsystem where the flag takes effect.
- `(:KEP)-[:REACHED {stage: 'alpha'|'beta'|'stable'}]->(:Release)`: Release progression.

---

## 2. API Contract

### Base URL
- Local: `http://localhost:8000`
- Production: `https://<public-domain>`

---

### Endpoints

#### 1. `GET /`
- **Description**: Serves the single-page application frontend.
- **Response**: `200 OK` with `text/html` (`web/index.html`).

---

#### 2. `GET /api/health`
- **Description**: Verifies service readiness and FalkorDB connectivity.
- **Behavior**: Executes `RETURN 1` (or graph query `RETURN 1`) against FalkorDB.
- **Success Response (`200 OK`)**:
  ```json
  {
    "ok": true,
    "falkordb": true
  }
  ```
- **FalkorDB Offline Response (`200 OK`)**:
  ```json
  {
    "ok": true,
    "falkordb": false
  }
  ```

---

#### 3. `POST /api/ask`
- **Description**: Submits an organizational or design decision query to the Lore AI Agent.
- **Rate Limit**: **20 requests per minute** per client IP. Returns `429 Too Many Requests` on violation.
- **Timeout & Failure Protection**: 60-second execution deadline. If the agent crashes or exceeds 60 seconds, returns `500 Internal Server Error` with `{"error": "..."}`. Never returns a blank response.
- **Stub Behavior**: Until `app.agent.ask()` is implemented by Agent developer A, returns the verifiable stub response below with `"is_stub": true`.

##### Request:
- **Headers**: `Content-Type: application/json`
- **Body**:
  ```json
  {
    "question": "Who actually knows SIG Node?"
  }
  ```

##### Response (`200 OK`):
```json
{
  "question": "Who actually knows SIG Node?",
  "answer": "While SIG Node has 5 official leaders (dchen1107, mrunalp, SergeyKanzhelev, derekwaynecarr, haircommander), the evidence from 679 design decisions shows that engineers tallclair (31 decisions), ffromani (21 decisions), and thockin (20 decisions) are among the top contributors despite not being on the official leadership roster.",
  "official_owners": [
    {
      "login": "dchen1107",
      "role": "chair",
      "team": "sig-node"
    },
    {
      "login": "mrunalp",
      "role": "chair",
      "team": "sig-node"
    },
    {
      "login": "SergeyKanzhelev",
      "role": "tech_lead",
      "team": "sig-node"
    },
    {
      "login": "derekwaynecarr",
      "role": "chair",
      "team": "sig-node"
    },
    {
      "login": "haircommander",
      "role": "tech_lead",
      "team": "sig-node"
    }
  ],
  "actual_knowers": [
    {
      "login": "dchen1107",
      "decisions_count": 63,
      "is_official": true
    },
    {
      "login": "mrunalp",
      "decisions_count": 62,
      "is_official": true
    },
    {
      "login": "SergeyKanzhelev",
      "decisions_count": 56,
      "is_official": true
    },
    {
      "login": "derekwaynecarr",
      "decisions_count": 43,
      "is_official": true
    },
    {
      "login": "haircommander",
      "decisions_count": 36,
      "is_official": true
    },
    {
      "login": "tallclair",
      "decisions_count": 31,
      "is_official": false
    },
    {
      "login": "ffromani",
      "decisions_count": 21,
      "is_official": false
    },
    {
      "login": "thockin",
      "decisions_count": 20,
      "is_official": false
    }
  ],
  "sources": [
    {
      "type": "KEP",
      "ref": "KEP-1287",
      "title": "In-Place Pod Vertical Scaling"
    },
    {
      "type": "KEP",
      "ref": "KEP-753",
      "title": "Node Resource Topology"
    },
    {
      "type": "REGISTRY",
      "ref": "sigs.yaml",
      "title": "SIG Node Leadership"
    }
  ],
  "graph": {
    "nodes": [
      {
        "id": "sig-node",
        "label": "SIG Node",
        "type": "Team"
      },
      {
        "id": "tallclair",
        "label": "tallclair",
        "type": "Person",
        "status": "knower"
      },
      {
        "id": "dchen1107",
        "label": "dchen1107",
        "type": "Person",
        "status": "owner_and_knower"
      }
    ],
    "edges": [
      {
        "source": "tallclair",
        "target": "sig-node",
        "relation": "KNOWS",
        "weight": 31
      },
      {
        "source": "dchen1107",
        "target": "sig-node",
        "relation": "LEADS",
        "weight": 63
      }
    ]
  },
  "is_stub": true
}
```

##### Error Response (`500 Internal Server Error`):
```json
{
  "error": "Agent execution failed: [detailed error message]"
}
```

##### Rate Limit Exceeded (`429 Too Many Requests`):
```json
{
  "error": "Rate limit exceeded. Maximum 20 questions per minute allowed."
}
```

---

#### 4. `POST /api/actions/approve` (C's Action Router)
- **Description**: Approves a proposed routing triage, draft comment, or ping to stale decision owners.
- **Request Body**:
  ```json
  {
    "action_id": "act_triage_8891",
    "action_type": "route_issue",
    "target_team": "sig-node",
    "suggested_assignees": ["tallclair", "dchen1107"],
    "comment_draft": "Routing to @sig-node-leads. Based on KEP-1287 history, @tallclair and @dchen1107 are the primary subject matter experts.",
    "approved_by": "maintainer"
  }
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "status": "approved",
    "action_id": "act_triage_8891",
    "applied_at": "2026-10-18T00:00:00Z",
    "message": "Action successfully approved and queued."
  }
  ```

---

## 3. Environment Configuration

All environment variables are loaded from `.env`:
- `FALKORDB_HOST`: Hostname of FalkorDB (`localhost` locally, `falkordb` in Docker Compose).
- `FALKORDB_PORT`: Port number of FalkorDB (`6379`).
- `LLM_BASE_URL`: OpenAI-compatible or provider API endpoint.
- `LLM_API_KEY`: API authentication key.
- `LLM_MODEL`: Target model identifier (e.g. `gpt-4o`, `gemini-1.5-pro`, `deepseek-chat`).
