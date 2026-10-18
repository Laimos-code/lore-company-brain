"""app/actions.py — Team Member C's Action Router.

Implements the Approve button action, triage routing, and decision pings.
"""
import asyncio
import hmac
import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/actions", tags=["actions"])

# In-memory store for approved actions
_APPROVED_ACTIONS: List[Dict[str, Any]] = []


class ApproveActionRequest(BaseModel):
    action_id: Optional[str] = Field(default_factory=lambda: f"act_{int(datetime.now().timestamp())}")
    action_type: str = Field(default="route_issue", description="Type of action: route_issue, ping_stale_owners, approve_plan")
    target_team: Optional[str] = Field(default=None, description="Target team or SIG (e.g. sig-node)")
    suggested_assignees: Optional[List[str]] = Field(default_factory=list, description="Recommended experts/assignees")
    comment_draft: Optional[str] = Field(default=None, description="Draft response or triage comment")
    approved_by: Optional[str] = Field(default="maintainer", description="Approving user or admin")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Arbitrary action payload")


class ApproveActionResponse(BaseModel):
    status: str
    action_id: str
    applied_at: str
    message: str
    details: Dict[str, Any]


@router.post("/approve", response_model=ApproveActionResponse, deprecated=True)
async def approve_action(req: ApproveActionRequest) -> ApproveActionResponse:
    """Approve a proposed recommendation, triage routing, or stale decision ping."""
    applied_at = datetime.now(timezone.utc).isoformat()
    record = {
        "action_id": req.action_id,
        "action_type": req.action_type,
        "target_team": req.target_team,
        "suggested_assignees": req.suggested_assignees,
        "comment_draft": req.comment_draft,
        "approved_by": req.approved_by,
        "applied_at": applied_at,
        "metadata": req.metadata,
    }
    _APPROVED_ACTIONS.append(record)

    msg = f"Action '{req.action_id}' ({req.action_type}) approved successfully."
    if req.target_team:
        msg += f" Routed to {req.target_team} with assignees {req.suggested_assignees}."

    return ApproveActionResponse(
        status="approved",
        action_id=req.action_id or "act_unknown",
        applied_at=applied_at,
        message=msg,
        details=record,
    )


@router.get("/history")
async def list_action_history() -> Dict[str, Any]:
    """Retrieve history of approved actions."""
    return {
        "count": len(_APPROVED_ACTIONS),
        "actions": list(reversed(_APPROVED_ACTIONS)),
    }


# ── GitHub demo triage (practice repo only) ─────────────────────────

GITHUB_API = "https://api.github.com"
ALLOWED_LABELS = {"sig/node", "sig/scheduling", "sig/auth", "sig/storage", "sig/network"}
LORE_LABEL = "triage/lore-suggested"
MAX_COMMENT_CHARS = 2000

demo_router = APIRouter(prefix="/api", tags=["demo-triage"])


class ApproveIssueRequest(BaseModel):
    issue_number: int = Field(..., gt=0)
    comment: str = Field(..., min_length=1)
    labels: List[str] = Field(default_factory=list)


def _demo_config() -> tuple:
    """Repo and token come only from .env, never from the request."""
    repo = os.getenv("DEMO_REPO", "").strip()
    token = os.getenv("DEMO_GITHUB_TOKEN", "").strip()
    if not repo or repo.count("/") != 1:
        raise ValueError("DEMO_REPO is not set (expected owner/repo)")
    owner = repo.split("/", 1)[0].lower()
    allowed_owner = (os.getenv("DEMO_REPO_OWNER") or "Laimos-code").strip().lower()
    if owner.startswith("kubernetes") or owner != allowed_owner:
        raise ValueError("Refusing to act on a repository outside the demo owner")
    if not token:
        raise ValueError("DEMO_GITHUB_TOKEN is not set")
    return repo, token


log = logging.getLogger("lore.actions")
APPROVE_PER_MINUTE = 3
ROUTE_PER_MINUTE = 10
DEMO_ISSUES_TTL_S = 60.0
_limiters: Dict[str, Any] = {}
_daily = {"day": None, "posts": 0}
_issues_cache: Dict[str, Any] = {"at": 0.0, "repo": None, "issues": None}


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": message})


async def _limited(request: Request, name: str, per_minute: int) -> bool:
    """True if this visitor is over the per-minute limit for `name` (reuses main's limiter and IP rule)."""
    from app.main import SlidingWindowRateLimiter, get_client_ip
    if name not in _limiters:
        _limiters[name] = SlidingWindowRateLimiter(max_requests=per_minute, window_seconds=60.0)
    return not await _limiters[name].is_allowed(get_client_ip(request))


def _daily_cap_reached() -> bool:
    cap = int(os.getenv("APPROVE_DAILY_CAP") or "50")
    if _daily["day"] != date.today():
        _daily.update(day=date.today(), posts=0)
    return _daily["posts"] >= cap


def _passcode_ok(request: Request) -> bool:
    expected = os.getenv("APPROVE_PASSCODE") or ""
    given = request.headers.get("x-approve-passcode", "")
    # compare_digest takes the same time however many characters match, so guessing gets no hints
    return not expected or hmac.compare_digest(given.encode(), expected.encode())


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_error(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("message", "")
    except ValueError:
        detail = resp.text[:200]
    return f"GitHub API {resp.status_code}: {detail}"


@demo_router.get("/demo-issues")
async def list_demo_issues():
    """List open issues (not PRs) in the practice repo. Cached for 60 s to save the token's quota."""
    try:
        repo, token = _demo_config()
    except ValueError as e:
        log.error("demo config: %s", e)
        return _err(503, "Live Triage is not set up on this server (DEMO_REPO / DEMO_GITHUB_TOKEN)")
    if _issues_cache["repo"] == repo and time.time() - _issues_cache["at"] < DEMO_ISSUES_TTL_S:
        return _issues_cache["issues"]
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers=_headers(token),
            params={"state": "open", "per_page": 100},
        )
    if resp.status_code != 200:
        log.error("list issues: %s", _gh_error(resp))
        return _err(502, "GitHub request failed")
    issues = [
        {"number": i["number"], "title": i["title"], "body": i.get("body") or "", "url": i["html_url"]}
        for i in resp.json()
        if "pull_request" not in i
    ]
    _issues_cache.update(at=time.time(), repo=repo, issues=issues)
    return issues


@demo_router.post("/approve")
async def approve_issue(req: ApproveIssueRequest, request: Request):
    """Human-approved triage: post the comment and apply allowed labels + triage/lore-suggested.
    Limited to 3 posts/min per visitor and APPROVE_DAILY_CAP (default 50) per day; requires the
    X-Approve-Passcode header when APPROVE_PASSCODE is set."""
    if not _passcode_ok(request):
        return _err(403, "Wrong or missing approve passcode")
    if await _limited(request, "approve", APPROVE_PER_MINUTE):
        return _err(429, "Too many approvals, try again in a minute")
    if _daily_cap_reached():
        return _err(429, "Daily approval limit reached")
    try:
        repo, token = _demo_config()
    except ValueError as e:
        log.error("demo config: %s", e)
        return _err(503, "Live Triage is not set up on this server (DEMO_REPO / DEMO_GITHUB_TOKEN)")

    comment = req.comment.strip()
    if not comment:
        return _err(400, "Comment is empty")
    if len(comment) > MAX_COMMENT_CHARS:
        return _err(400, f"Comment exceeds {MAX_COMMENT_CHARS} characters")
    bad = [label for label in req.labels if label not in ALLOWED_LABELS]
    if bad:
        return _err(400, f"Labels not allowed: {bad}")
    labels = list(dict.fromkeys(req.labels + [LORE_LABEL]))

    base = f"{GITHUB_API}/repos/{repo}/issues/{req.issue_number}"
    async with httpx.AsyncClient(timeout=15.0, headers=_headers(token)) as client:
        c_resp = await client.post(f"{base}/comments", json={"body": comment})
        if c_resp.status_code != 201:
            log.error("post comment: %s", _gh_error(c_resp))
            return _err(502, "GitHub refused the comment")
        _daily["posts"] += 1
        l_resp = await client.post(f"{base}/labels", json={"labels": labels})
        if l_resp.status_code != 200:
            log.error("add labels: %s", _gh_error(l_resp))
            return _err(502, "Comment posted but labelling failed")
    return {"ok": True, "comment_url": c_resp.json()["html_url"]}


@demo_router.get("/route-issue/{issue_number}")
async def route_demo_issue(issue_number: int, request: Request):
    """Lore's suggestion (team, label, people, draft comment) for a practice-repo issue, from
    app.tools.route_issue (Cypher on the k8s graph). Nothing is posted."""
    if await _limited(request, "route", ROUTE_PER_MINUTE):
        return _err(429, "Too many requests, try again in a minute")
    try:
        repo, token = _demo_config()
    except ValueError as e:
        log.error("demo config: %s", e)
        return _err(503, "Live Triage is not set up on this server (DEMO_REPO / DEMO_GITHUB_TOKEN)")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{GITHUB_API}/repos/{repo}/issues/{issue_number}", headers=_headers(token))
    if resp.status_code != 200:
        log.error("get issue: %s", _gh_error(resp))
        return _err(502, "GitHub request failed")
    issue = resp.json()
    try:
        from app import tools
        env = await asyncio.to_thread(tools.route_issue, issue["title"], issue.get("body") or "")
    except Exception:
        log.exception("route_issue failed")
        return _err(503, "Graph unavailable")
    data = env.get("data") or {}
    label = data.get("label")
    return {"ok": True, "issue": {"number": issue["number"], "title": issue["title"], "url": issue["html_url"]},
            "summary": env.get("summary"), "team": data.get("team"),
            "team_scores": data.get("team_scores", []), "people": data.get("suggested_people", []),
            "related_keps": data.get("related_keps", []), "comment": data.get("draft_comment", ""),
            "labels": [label] if label in ALLOWED_LABELS else [], "sources": env.get("sources", []),
            "evidence": env.get("evidence"), "is_stub": env.get("is_stub", False)}
