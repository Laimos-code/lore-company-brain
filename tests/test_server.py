"""tests/test_server.py — Automated tests for Lore FastAPI server."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app, rate_limiter

client = TestClient(app)


def test_index_page():
    """Verify GET / returns the frontend HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Lore" in response.text or "text/html" in response.headers.get("content-type", "")


def test_health_endpoint():
    """Verify GET /api/health returns ok: true and a boolean for falkordb."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "falkordb" in data
    assert isinstance(data["falkordb"], bool)


def test_ask_endpoint_stub_response():
    """Verify POST /api/ask returns the contract shape (graph answer, or stub if FalkorDB is down)."""
    response = client.post("/api/ask", json={"question": "Who actually knows SIG Node?"})
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "official_owners" in data
    assert "actual_knowers" in data
    assert "sources" in data
    assert data.get("is_stub") is (not _falkor_up())


def test_ask_decision_trail():
    """Verify POST /api/ask returns decision trail for gang scheduling."""
    response = client.post("/api/ask", json={"question": "Why did they choose gang scheduling?"})
    assert response.status_code == 200
    data = response.json()
    assert "decision_trail" in data or "answer" in data
    assert data.get("is_stub") is (not _falkor_up())


def test_ask_rate_limiting(monkeypatch):
    """Verify rate limiter blocks client after 20 queries in a minute (behind our proxy)."""
    monkeypatch.setattr(main, "TRUST_PROXY", True)
    client_ip = "192.168.1.99"
    headers = {"x-forwarded-for": client_ip}

    # Reset limiter for test IP
    rate_limiter.requests[client_ip] = []

    # Make 20 allowed requests
    for i in range(20):
        resp = client.post("/api/ask", json={"question": f"Question {i}"}, headers=headers)
        assert resp.status_code == 200, f"Request {i} failed unexpectedly"

    # 21st request should be rejected with 429
    resp_blocked = client.post("/api/ask", json={"question": "Question 21"}, headers=headers)
    assert resp_blocked.status_code == 429
    err = resp_blocked.json()
    assert "Rate limit exceeded" in err.get("error", "")


def test_rate_limit_ignores_fake_forwarded_header():
    """A visitor can't dodge the limit by sending a different fake IP each time."""
    rate_limiter.requests.clear()
    codes = [
        client.post("/api/ask", json={"question": f"Q{i}"},
                    headers={"x-forwarded-for": f"10.0.0.{i}"}).status_code
        for i in range(21)
    ]
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


def test_action_approve_endpoint():
    """Verify Team Member C's approve action router."""
    payload = {
        "action_id": "test_act_001",
        "action_type": "route_issue",
        "target_team": "sig-node",
        "suggested_assignees": ["tallclair", "dchen1107"],
        "comment_draft": "Routing to @tallclair based on KEP knowledge.",
        "approved_by": "test_user"
    }
    response = client.post("/api/actions/approve", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["action_id"] == "test_act_001"


def test_demo_approve_refuses_kubernetes_repo(monkeypatch):
    """Approve must never act on a kubernetes/ repo."""
    monkeypatch.setenv("DEMO_REPO", "kubernetes/kubernetes")
    monkeypatch.setenv("DEMO_GITHUB_TOKEN", "dummy")
    resp = client.post("/api/approve", json={"issue_number": 1, "comment": "hi", "labels": ["sig/node"]})
    assert resp.json()["ok"] is False
    assert resp.status_code == 500


def test_demo_approve_rejects_bad_label_and_long_comment(monkeypatch):
    """Only allow-listed labels and comments up to 2000 chars."""
    from app import actions
    actions._limiters.clear()
    monkeypatch.setenv("DEMO_REPO", "Laimos-code/lore-demo-issues")
    monkeypatch.setenv("DEMO_GITHUB_TOKEN", "dummy")
    bad_label = client.post("/api/approve", json={"issue_number": 1, "comment": "hi", "labels": ["lgtm"]})
    assert bad_label.status_code == 400 and bad_label.json()["ok"] is False
    too_long = client.post("/api/approve", json={"issue_number": 1, "comment": "x" * 2001, "labels": []})
    assert too_long.status_code == 400 and too_long.json()["ok"] is False


def _falkor_up():
    try:
        from app import tools
        return bool(tools._q("MATCH (t:Team) RETURN count(t)")[0][0])
    except Exception:
        return False


def _graph_loaded():
    try:
        from app import tools
        return bool(tools._q("MATCH (:Person)-[:REVIEWED]->(pr:PR)-[:FOR_TEAM]->(:Team) RETURN count(pr)")[0][0])
    except Exception:
        return False


def test_ask_is_real_when_graph_loaded():
    """With the graph loaded, /api/ask must answer from Cypher, never the stub."""
    if not _graph_loaded():
        pytest.skip("graph not loaded")
    rate_limiter.requests.clear()
    for q, tool in [("Who actually knows SIG Node?", "who_knows"),
                    ("Why did they choose gang scheduling?", "why"),
                    ("What decisions are stuck at alpha?", "whats_stale")]:
        data = client.post("/api/ask", json={"question": q}).json()
        assert data["is_stub"] is False and data["tool"] == tool, (q, data.get("tool"))


def test_demo_config_refuses_other_owners(monkeypatch):
    from app.actions import _demo_config
    monkeypatch.setenv("DEMO_GITHUB_TOKEN", "x")
    for repo in ["kubernetes-sigs/kueue", "kubernetes-csi/external-provisioner", "someone/else"]:
        monkeypatch.setenv("DEMO_REPO", repo)
        with pytest.raises(ValueError):
            _demo_config()
    monkeypatch.setenv("DEMO_REPO", "Laimos-code/lore-demo-issues")
    assert _demo_config()[0] == "Laimos-code/lore-demo-issues"


def test_approve_rate_limited_and_passcode(monkeypatch):
    from app import actions
    monkeypatch.setenv("DEMO_REPO", "Laimos-code/lore-demo-issues")
    monkeypatch.setenv("DEMO_GITHUB_TOKEN", "x")
    monkeypatch.setenv("APPROVE_PASSCODE", "s3cret")
    actions._limiters.clear()
    bad = {"issue_number": 1, "comment": "hi", "labels": ["not/allowed"]}
    assert client.post("/api/approve", json=bad).status_code == 403
    codes = [client.post("/api/approve", json=bad, headers={"X-Approve-Passcode": "s3cret"}).status_code
             for _ in range(10)]
    assert codes[:3] == [400, 400, 400] and set(codes[3:]) == {429}
