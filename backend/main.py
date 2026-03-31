"""FastAPI server that orchestrates GitHub issue triage using the Devin API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEVIN_API_KEY = os.environ.get("DEVIN_API_KEY", "")
DEVIN_ORG_ID = os.environ.get("DEVIN_ORG_ID", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # e.g. "owner/repo"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

DEVIN_API_BASE = f"https://api.devin.ai/v3/organizations/{DEVIN_ORG_ID}"
GITHUB_API_BASE = "https://api.github.com"

POLL_INTERVAL_SECONDS = 10
MAX_POLL_DURATION_SECONDS = 20 * 60  # 20 minutes

logger = logging.getLogger("issueops")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class IssueStatus(str, Enum):
    queued = "queued"
    triaging = "triaging"
    triage_done = "triage_done"
    fixing = "fixing"
    fix_pr_opened = "fix_pr_opened"
    failed = "failed"


class Complexity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TrackedIssue(BaseModel):
    issue_number: int
    title: str
    labels: list[str] = Field(default_factory=list)
    status: IssueStatus = IssueStatus.queued
    devin_session_id: Optional[str] = None
    devin_session_url: Optional[str] = None
    pr_url: Optional[str] = None
    triage_summary: Optional[str] = None
    complexity: Optional[Complexity] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# In-memory store
issue_store: dict[int, TrackedIssue] = {}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="IssueOps", description="Automated GitHub Issue Triage with Devin")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _devin_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json",
    }


def _github_headers() -> dict[str, str]:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _touch(issue: TrackedIssue) -> None:
    """Update the updated_at timestamp."""
    issue.updated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


async def github_post_comment(issue_number: int, body: str) -> None:
    """Post a comment on a GitHub issue."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues/{issue_number}/comments"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_github_headers(), json={"body": body})
        resp.raise_for_status()


async def github_get_issue(issue_number: int) -> dict:
    """Fetch a single issue from the GitHub API."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues/{issue_number}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_github_headers())
        resp.raise_for_status()
        return resp.json()


async def github_list_open_issues(page: int = 1, per_page: int = 100) -> list[dict]:
    """Fetch open issues from the GitHub API."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues"
    params = {"state": "open", "per_page": per_page, "page": page}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_github_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def github_search_prs(issue_number: int) -> Optional[str]:
    """Search recent open PRs for one mentioning the issue number."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/pulls"
    params = {"state": "open", "per_page": 30, "sort": "created", "direction": "desc"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_github_headers(), params=params)
        resp.raise_for_status()
        for pr in resp.json():
            pr_title = pr.get("title", "")
            pr_body = pr.get("body", "") or ""
            if f"#{issue_number}" in pr_title or f"#{issue_number}" in pr_body:
                return pr.get("html_url")
    return None


# ---------------------------------------------------------------------------
# Slack helper
# ---------------------------------------------------------------------------


async def send_slack_notification(message: str) -> None:
    """Send a notification via Slack incoming webhook if configured."""
    if not SLACK_WEBHOOK_URL:
        return
    async with httpx.AsyncClient() as client:
        try:
            await client.post(SLACK_WEBHOOK_URL, json={"text": message})
        except Exception:
            logger.warning("Failed to send Slack notification", exc_info=True)


# ---------------------------------------------------------------------------
# Devin session helpers
# ---------------------------------------------------------------------------


async def create_devin_session(prompt: str, idempotency_key: str) -> dict:
    """Create a Devin session via the API."""
    url = f"{DEVIN_API_BASE}/sessions"
    payload = {
        "prompt": prompt,
        "idempotency_key": idempotency_key,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url, headers=_devin_headers(), json=payload, timeout=30.0
        )
        resp.raise_for_status()
        return resp.json()


async def poll_devin_session(session_id: str) -> dict:
    """Poll a Devin session until it reaches a terminal state or times out."""
    url = f"{DEVIN_API_BASE}/sessions/{session_id}"
    terminal_states = {"finished", "stopped", "error", "suspended"}
    elapsed = 0
    data = {}
    async with httpx.AsyncClient() as client:
        while elapsed < MAX_POLL_DURATION_SECONDS:
            resp = await client.get(url, headers=_devin_headers(), timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status_enum", "")
            if status in terminal_states:
                return data
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS
    return data  # return last known state on timeout


async def get_devin_session_messages(session_id: str) -> list[dict]:
    """Fetch messages from a Devin session."""
    url = f"{DEVIN_API_BASE}/sessions/{session_id}/messages"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_devin_headers(), timeout=30.0)
        resp.raise_for_status()
        return resp.json()


def extract_last_assistant_message(messages: list[dict]) -> str:
    """Extract the last assistant message content from session messages."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return msg.get("content", "") or msg.get("message", "")
    return ""


def parse_complexity(text: str) -> Optional[Complexity]:
    """Best-effort regex to parse complexity from triage summary."""
    match = re.search(r"complexity:\s*(low|medium|high)", text, re.IGNORECASE)
    if match:
        return Complexity(match.group(1).lower())
    return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_triage_prompt(
    issue_number: int,
    repo: str,
    title: str,
    body: str,
    labels: list[str],
) -> str:
    """Build a detailed triage prompt for a Devin session."""
    label_str = ", ".join(labels) if labels else "None"
    return (
        f"You are triaging GitHub issue #{issue_number} in the repository {repo}.\n"
        f"\n"
        f"## Issue context\n"
        f"- **Number:** #{issue_number}\n"
        f"- **Title:** {title}\n"
        f"- **Labels:** {label_str}\n"
        f"\n"
        f"### Description\n"
        f"{body}\n"
        f"\n"
        f"## Investigation steps\n"
        f"1. **Search the codebase** for keywords from the issue title and body:\n"
        f"   - Use `grep -rn` or `rg` to find relevant symbols, error messages, "
        f"and identifiers.\n"
        f"   - Run `git log --oneline -20` and `git log --all --oneline --grep=\"<keyword>\"` "
        f"to check recent commits for related changes.\n"
        f"   - Read test files in the affected area to understand expected behaviour.\n"
        f"   - Inspect any stack traces or error strings mentioned in the issue.\n"
        f"2. **Check for duplicates** — search closed issues and PRs for similar "
        f"titles or error messages to see if this was previously fixed or discussed.\n"
        f"3. Identify the **root cause** and all **affected files** (full paths).\n"
        f"\n"
        f"## Required output format\n"
        f"Return a structured triage report with **exactly** these sections:\n"
        f"\n"
        f"### Root Cause\n"
        f"A concise explanation of why the issue occurs.\n"
        f"\n"
        f"### Affected Files\n"
        f"A bullet list of every file path that would need changes, e.g.:\n"
        f"- `src/module/foo.py` — brief reason\n"
        f"\n"
        f"### Complexity: <low | medium | high>\n"
        f"Classify the fix effort:\n"
        f"- **low** — isolated change in one or two files, no API/schema changes.\n"
        f"- **medium** — touches several files or requires moderate refactoring.\n"
        f"- **high** — cross-cutting change, new dependencies, or design decisions needed.\n"
        f"\n"
        f"### Confidence: <\U0001f7e2 | \U0001f7e0 | \U0001f534>\n"
        f"- \U0001f7e2 High — root cause is clear and fix is straightforward.\n"
        f"- \U0001f7e0 Medium — likely root cause identified but some uncertainty remains.\n"
        f"- \U0001f534 Low — root cause is unclear or issue may be environment-specific.\n"
        f"\n"
        f"### Suggested Fix Approach\n"
        f"Step-by-step outline of what the fix should do.\n"
        f"\n"
        f"### Risks & Side Effects\n"
        f"Anything that could break, edge cases to watch, or areas needing extra testing.\n"
        f"\n"
        f"### Duplicate / Related Issues\n"
        f"List any closed or open issues/PRs that are related, or state \"None found\".\n"
    )


def build_fix_prompt(
    issue_number: int,
    repo: str,
    title: str,
    body: str,
    triage_summary: str,
) -> str:
    """Build a detailed fix prompt for a Devin session."""
    return (
        f"You are fixing GitHub issue #{issue_number} in the repository {repo}.\n"
        f"\n"
        f"## Issue context\n"
        f"- **Number:** #{issue_number}\n"
        f"- **Title:** {title}\n"
        f"\n"
        f"### Description\n"
        f"{body}\n"
        f"\n"
        f"## Triage summary (already completed — do NOT redo investigation)\n"
        f"{triage_summary}\n"
        f"\n"
        f"## Instructions\n"
        f"\n"
        f"### Branch & commits\n"
        f"- Create a branch named **`fix/{issue_number}-<short-description>`** from the "
        f"default branch (e.g. `fix/{issue_number}-handle-null-input`).\n"
        f"- Use lowercase kebab-case for the short description.\n"
        f"- Keep commits small and focused.\n"
        f"\n"
        f"### Implementation guardrails\n"
        f"- **Only touch files related to this issue.** Do not refactor, reformat, or "
        f"modify unrelated code.\n"
        f"- **Prefer the simplest correct fix.** Avoid over-engineering.\n"
        f"- Write or update tests to cover the fix. If no test framework exists, add a "
        f"minimal regression test.\n"
        f"- If you encounter a blocker (missing context, ambiguous requirements, "
        f"external dependency), document it clearly in the PR description instead "
        f"of guessing.\n"
        f"\n"
        f"### Pre-PR checklist\n"
        f"Before opening the pull request you **must** run and pass:\n"
        f"1. **Lint** — run the project linter (e.g. `ruff`, `eslint`, `flake8`).\n"
        f"2. **Type check** — run the type checker if configured (e.g. `mypy`, `pyright`, `tsc`).\n"
        f"3. **Tests** — run the full test suite and confirm no regressions.\n"
        f"\n"
        f"### Pull request requirements\n"
        f"- **Title format:** `fix: #{issue_number} \u2014 <short description>`\n"
        f"- In the PR body:\n"
        f"  - Reference the issue with `Closes #{issue_number}`.\n"
        f"  - Summarise what was changed and why.\n"
        f"  - Note any risks, follow-ups, or things reviewers should pay attention to.\n"
        f"- Do **not** merge the PR yourself.\n"
    )


# ---------------------------------------------------------------------------
# Triage flow
# ---------------------------------------------------------------------------


async def run_triage(issue_number: int) -> None:
    """Run the triage flow for a tracked issue."""
    issue = issue_store.get(issue_number)
    if not issue:
        logger.error("Issue %d not found in store", issue_number)
        return

    issue.status = IssueStatus.triaging
    _touch(issue)

    try:
        # Post initial comment
        await github_post_comment(
            issue_number,
            "\U0001f916 **IssueOps** \u2014 Devin is investigating this issue...",
        )

        # Fetch full issue details for the prompt
        gh_issue = await github_get_issue(issue_number)
        issue_body = gh_issue.get("body", "") or "No description provided."
        issue_labels = [l["name"] for l in gh_issue.get("labels", [])]

        prompt = build_triage_prompt(
            issue_number=issue_number,
            repo=GITHUB_REPO,
            title=issue.title,
            body=issue_body,
            labels=issue_labels,
        )

        # Create Devin session
        session_data = await create_devin_session(
            prompt=prompt,
            idempotency_key=f"triage-{issue_number}",
        )
        session_id = session_data.get("session_id", "")
        session_url = session_data.get("url", "")
        issue.devin_session_id = session_id
        issue.devin_session_url = session_url
        _touch(issue)

        # Poll until session completes
        await poll_devin_session(session_id)

        # Fetch messages and extract summary
        messages = await get_devin_session_messages(session_id)
        summary = extract_last_assistant_message(messages)
        issue.triage_summary = summary or "No summary available."
        issue.complexity = parse_complexity(summary)
        issue.status = IssueStatus.triage_done
        _touch(issue)

        # Post triage report as GitHub comment
        complexity_str = issue.complexity.value if issue.complexity else "unknown"
        comment_body = (
            "## \U0001f916 IssueOps \u2014 Triage Report\n\n"
            f"{issue.triage_summary}\n\n"
            f"**Complexity:** {complexity_str}\n\n"
            f"\U0001f517 [Devin Session]({session_url})\n\n"
            "---\n"
            "\U0001f449 To auto-fix this issue, add the `devin-fix` label."
        )
        await github_post_comment(issue_number, comment_body)

        # Slack notification
        await send_slack_notification(
            f"\u2705 Triage complete for issue #{issue_number} ({issue.title}) "
            f"\u2014 Complexity: {complexity_str}. "
            f"Session: {session_url}"
        )

    except Exception:
        logger.exception("Triage failed for issue #%d", issue_number)
        issue.status = IssueStatus.failed
        _touch(issue)
        try:
            await github_post_comment(
                issue_number,
                "\u274c **IssueOps** \u2014 Triage failed. Check logs for details.",
            )
        except Exception:
            logger.warning("Failed to post failure comment", exc_info=True)


# ---------------------------------------------------------------------------
# Fix flow
# ---------------------------------------------------------------------------


async def run_fix(issue_number: int) -> None:
    """Run the fix flow for a tracked issue."""
    issue = issue_store.get(issue_number)
    if not issue:
        logger.error("Issue %d not found in store", issue_number)
        return

    issue.status = IssueStatus.fixing
    _touch(issue)

    try:
        # Post initial comment
        await github_post_comment(
            issue_number,
            "\U0001f916 **IssueOps** \u2014 Devin is working on a fix...",
        )

        # Fetch full issue details
        gh_issue = await github_get_issue(issue_number)
        issue_body = gh_issue.get("body", "") or "No description provided."

        triage_summary = issue.triage_summary or "No triage summary available."

        prompt = build_fix_prompt(
            issue_number=issue_number,
            repo=GITHUB_REPO,
            title=issue.title,
            body=issue_body,
            triage_summary=triage_summary,
        )

        # Create Devin session
        session_data = await create_devin_session(
            prompt=prompt,
            idempotency_key=f"fix-{issue_number}",
        )
        session_id = session_data.get("session_id", "")
        session_url = session_data.get("url", "")
        issue.devin_session_id = session_id
        issue.devin_session_url = session_url
        _touch(issue)

        # Poll until session completes
        await poll_devin_session(session_id)

        # Search for a PR mentioning this issue
        pr_url = await github_search_prs(issue_number)
        if pr_url:
            issue.pr_url = pr_url
            issue.status = IssueStatus.fix_pr_opened
            _touch(issue)

            comment_body = (
                "## \U0001f916 IssueOps \u2014 Fix PR Opened\n\n"
                f"Devin has opened a pull request to fix this issue:\n"
                f"\U0001f517 [Pull Request]({pr_url})\n\n"
                f"\U0001f517 [Devin Session]({session_url})"
            )
            await github_post_comment(issue_number, comment_body)

            await send_slack_notification(
                f"\U0001f527 Fix PR opened for issue #{issue_number} ({issue.title}): "
                f"{pr_url}"
            )
        else:
            # Session finished but no PR found
            messages = await get_devin_session_messages(session_id)
            last_msg = extract_last_assistant_message(messages)

            comment_body = (
                "## \U0001f916 IssueOps \u2014 Fix Session Complete\n\n"
                "Devin's fix session has completed but no PR was detected.\n\n"
                f"**Session output:**\n{last_msg[:2000] if last_msg else 'No output.'}\n\n"
                f"\U0001f517 [Devin Session]({session_url})"
            )
            await github_post_comment(issue_number, comment_body)
            issue.status = IssueStatus.triage_done  # revert to triage_done
            _touch(issue)

    except Exception:
        logger.exception("Fix failed for issue #%d", issue_number)
        issue.status = IssueStatus.failed
        _touch(issue)
        try:
            await github_post_comment(
                issue_number,
                "\u274c **IssueOps** \u2014 Fix attempt failed. Check logs for details.",
            )
        except Exception:
            logger.warning("Failed to post failure comment", exc_info=True)


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def verify_github_signature(payload: bytes, signature: str) -> bool:
    """Verify the HMAC-SHA256 signature from GitHub."""
    if not GITHUB_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    expected_signature = f"sha256={expected}"
    return hmac.compare_digest(expected_signature, signature)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
):
    """Receive GitHub issue webhooks."""
    body = await request.body()

    # Verify HMAC-SHA256 signature
    if not verify_github_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    if x_github_event != "issues":
        return {"status": "ignored", "reason": "not an issues event"}

    action = payload.get("action", "")
    if action not in ("opened", "labeled"):
        return {"status": "ignored", "reason": f"action '{action}' not handled"}

    issue_data = payload.get("issue", {})
    issue_number = issue_data.get("number")
    if not issue_number:
        return {"status": "ignored", "reason": "no issue number"}

    title = issue_data.get("title", "")
    labels = [l["name"] for l in issue_data.get("labels", [])]

    # Upsert into store
    if issue_number not in issue_store:
        issue_store[issue_number] = TrackedIssue(
            issue_number=issue_number,
            title=title,
            labels=labels,
        )
    else:
        issue_store[issue_number].labels = labels
        issue_store[issue_number].title = title
        _touch(issue_store[issue_number])

    tracked = issue_store[issue_number]

    # Decide action based on labels and status
    if "devin-triage" in labels and tracked.status == IssueStatus.queued:
        background_tasks.add_task(run_triage, issue_number)
        return {"status": "triage_started", "issue_number": issue_number}

    if "devin-fix" in labels and tracked.status == IssueStatus.triage_done:
        background_tasks.add_task(run_fix, issue_number)
        return {"status": "fix_started", "issue_number": issue_number}

    return {"status": "tracked", "issue_number": issue_number}


@app.get("/api/issues")
async def list_issues():
    """Return all tracked issues sorted by updated_at descending."""
    sorted_issues = sorted(
        issue_store.values(), key=lambda i: i.updated_at, reverse=True
    )
    return [issue.model_dump(mode="json") for issue in sorted_issues]


@app.get("/api/issues/{number}")
async def get_issue(number: int):
    """Return a single tracked issue."""
    issue = issue_store.get(number)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue.model_dump(mode="json")


@app.get("/api/stats")
async def get_stats():
    """Return aggregate counts by status and complexity."""
    status_counts: dict[str, int] = {}
    complexity_counts: dict[str, int] = {}

    for issue in issue_store.values():
        status_counts[issue.status.value] = (
            status_counts.get(issue.status.value, 0) + 1
        )
        if issue.complexity:
            complexity_counts[issue.complexity.value] = (
                complexity_counts.get(issue.complexity.value, 0) + 1
            )

    return {
        "total": len(issue_store),
        "by_status": status_counts,
        "by_complexity": complexity_counts,
    }


@app.post("/api/issues/{number}/triage")
async def manual_triage(number: int, background_tasks: BackgroundTasks):
    """Manually trigger triage for an issue (fetches from GitHub API first)."""
    # Fetch issue from GitHub
    try:
        gh_issue = await github_get_issue(number)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"GitHub API error: {e.response.text}",
        )

    title = gh_issue.get("title", "")
    labels = [l["name"] for l in gh_issue.get("labels", [])]

    # Upsert into store
    if number not in issue_store:
        issue_store[number] = TrackedIssue(
            issue_number=number,
            title=title,
            labels=labels,
        )
    else:
        issue_store[number].title = title
        issue_store[number].labels = labels
        _touch(issue_store[number])

    background_tasks.add_task(run_triage, number)
    return {"status": "triage_started", "issue_number": number}


@app.post("/api/issues/{number}/fix")
async def manual_fix(number: int, background_tasks: BackgroundTasks):
    """Manually trigger a fix for an issue."""
    issue = issue_store.get(number)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found in store")

    background_tasks.add_task(run_fix, number)
    return {"status": "fix_started", "issue_number": number}


@app.post("/api/bulk-import")
async def bulk_import():
    """Fetch all open issues from GITHUB_REPO and add to store."""
    if not GITHUB_REPO:
        raise HTTPException(status_code=400, detail="GITHUB_REPO not configured")

    imported = 0
    page = 1
    while True:
        issues = await github_list_open_issues(page=page)
        if not issues:
            break
        for gh_issue in issues:
            # Skip pull requests (GitHub returns them as issues too)
            if gh_issue.get("pull_request"):
                continue
            number = gh_issue["number"]
            title = gh_issue.get("title", "")
            labels = [l["name"] for l in gh_issue.get("labels", [])]
            if number not in issue_store:
                issue_store[number] = TrackedIssue(
                    issue_number=number,
                    title=title,
                    labels=labels,
                )
                imported += 1
            else:
                issue_store[number].title = title
                issue_store[number].labels = labels
                _touch(issue_store[number])
        page += 1

    return {"status": "ok", "imported": imported, "total_tracked": len(issue_store)}
