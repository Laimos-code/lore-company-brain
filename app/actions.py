"""app/actions.py — Team Member C's Action Router.

Implements the Approve button action, triage routing, and decision pings.
"""
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, HTTPException
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


@router.post("/approve", response_model=ApproveActionResponse)
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
    if repo.lower().startswith("kubernetes/"):
        raise ValueError("Refusing to act on a kubernetes/ repository")
    if not token:
        raise ValueError("DEMO_GITHUB_TOKEN is not set")
    return repo, token


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
    """List open issues (not PRs) in the practice repo."""
    try:
        repo, token = _demo_config()
    except ValueError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers=_headers(token),
            params={"state": "open", "per_page": 100},
        )
    if resp.status_code != 200:
        return JSONResponse(status_code=502, content={"ok": False, "error": _gh_error(resp)})
    return [
        {"number": i["number"], "title": i["title"], "body": i.get("body") or "", "url": i["html_url"]}
        for i in resp.json()
        if "pull_request" not in i
    ]


@demo_router.post("/approve")
async def approve_issue(req: ApproveIssueRequest):
    """Human-approved triage: post the comment and apply allowed labels + triage/lore-suggested."""
    try:
        repo, token = _demo_config()
    except ValueError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

    comment = req.comment.strip()
    if not comment:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Comment is empty"})
    if len(comment) > MAX_COMMENT_CHARS:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"Comment exceeds {MAX_COMMENT_CHARS} characters"},
        )
    bad = [label for label in req.labels if label not in ALLOWED_LABELS]
    if bad:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"Labels not allowed: {bad}"})
    labels = list(dict.fromkeys(req.labels + [LORE_LABEL]))

    base = f"{GITHUB_API}/repos/{repo}/issues/{req.issue_number}"
    async with httpx.AsyncClient(timeout=15.0, headers=_headers(token)) as client:
        c_resp = await client.post(f"{base}/comments", json={"body": comment})
        if c_resp.status_code != 201:
            return JSONResponse(status_code=502, content={"ok": False, "error": _gh_error(c_resp)})
        l_resp = await client.post(f"{base}/labels", json={"labels": labels})
        if l_resp.status_code != 200:
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": "Comment posted but labelling failed: " + _gh_error(l_resp)},
            )
    return {"ok": True, "comment_url": c_resp.json()["html_url"]}


@demo_router.get("/route-issue/{issue_number}")
async def route_demo_issue(issue_number: int):
    """Lore's suggestion (team, label, reviewers, draft comment) for a practice-repo issue. Nothing is posted."""
    try:
        repo, token = _demo_config()
    except ValueError as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{GITHUB_API}/repos/{repo}/issues/{issue_number}", headers=_headers(token))
    if resp.status_code != 200:
        return JSONResponse(status_code=502, content={"ok": False, "error": _gh_error(resp)})
    issue = resp.json()
    try:
        import asyncio
        from app import graph_tools
        allowed = sorted("sig-" + label.split("/", 1)[1] for label in ALLOWED_LABELS)
        suggestion = await asyncio.to_thread(
            graph_tools.route_issue, graph_tools.get_graph(), issue["title"], issue.get("body") or "", allowed)
    except Exception as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": f"Graph unavailable: {e}"})
    return {"ok": True, "issue": {"number": issue["number"], "title": issue["title"], "url": issue["html_url"]},
            **suggestion, "labels": [suggestion["label"]] if suggestion.get("label") else []}
