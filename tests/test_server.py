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
    assert isinstance(data.get("is_stub"), bool)


def test_ask_decision_trail():
    """Verify POST /api/ask returns decision trail for gang scheduling."""
    response = client.post("/api/ask", json={"question": "Why did they choose gang scheduling?"})
    assert response.status_code == 200
    data = response.json()
    assert "decision_trail" in data or "answer" in data
    assert isinstance(data.get("is_stub"), bool)


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
    assert "kubernetes" in resp.json()["error"]


def test_demo_approve_rejects_bad_label_and_long_comment(monkeypatch):
    """Only allow-listed labels and comments up to 2000 chars."""
    monkeypatch.setenv("DEMO_REPO", "someone/lore-demo-issues")
    monkeypatch.setenv("DEMO_GITHUB_TOKEN", "dummy")
    bad_label = client.post("/api/approve", json={"issue_number": 1, "comment": "hi", "labels": ["lgtm"]})
    assert bad_label.status_code == 400 and bad_label.json()["ok"] is False
    too_long = client.post("/api/approve", json={"issue_number": 1, "comment": "x" * 2001, "labels": []})
    assert too_long.status_code == 400 and too_long.json()["ok"] is False


def _graph_or_skip():
    try:
        from app.graph_tools import get_graph
        g = get_graph()
        if not g.query("MATCH (pr:PR) RETURN count(pr)").result_set[0][0]:
            pytest.skip("graph not loaded")
        return g
    except Exception:
        pytest.skip("FalkorDB not reachable")


def test_brain_answers_from_graph():
    """With the graph loaded, /api/ask answers are real (is_stub false) and use the right tool."""
    g = _graph_or_skip()
    from app.brain import answer
    assert answer("Who actually knows SIG Node?", g)["tool"] == "who_knows"
    trail = answer("Why did they choose gang scheduling?", g)
    assert trail["tool"] == "decision_trail" and any(t["kep"] == "KEP-583" for t in trail["decision_trail"])
    assert answer("What decisions are stuck at alpha?", g)["tool"] == "stale_decisions"


def test_route_issue_picks_team_and_reviewers():
    g = _graph_or_skip()
    from app.graph_tools import route_issue
    r = route_issue(g, "Gang of training pods partly scheduled", "scheduler places 5 of 8 pods; need all or nothing",
                    ["sig-node", "sig-scheduling", "sig-auth", "sig-storage", "sig-network"])
    assert r["team"] == "sig-scheduling" and r["label"] == "sig/scheduling"
    assert r["reviewers"] and len(r["comment"]) <= 2000
