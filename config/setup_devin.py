#!/usr/bin/env python3
"""Set up Devin knowledge notes, playbooks, and a schedule for automated GitHub issue triage.

Uses the Devin API v3. Requires DEVIN_API_KEY and DEVIN_ORG_ID environment variables.
"""

import os
import sys

import requests

API_KEY = os.environ.get("DEVIN_API_KEY")
ORG_ID = os.environ.get("DEVIN_ORG_ID")

if not API_KEY or not ORG_ID:
    print("Error: DEVIN_API_KEY and DEVIN_ORG_ID environment variables are required.")
    sys.exit(1)

BASE_URL = f"https://api.devin.ai/v3/organizations/{ORG_ID}"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# ---------------------------------------------------------------------------
# Knowledge notes
# ---------------------------------------------------------------------------

KNOWLEDGE_NOTES = [
    {
        "name": "FinServ Monorepo — Coding Standards",
        "trigger": "When writing or reviewing code in the finserv monorepo",
        "body": (
            "TypeScript strict mode is required for all packages. "
            "Use Prettier for formatting and ESLint for linting. "
            "Write tests with Jest. "
            "Follow conventional commits (e.g. feat:, fix:, chore:). "
            "Keep PRs under 400 lines of diff. "
            "Use the Result<T, E> pattern for error handling instead of throwing exceptions. "
            "Use structured logging (JSON) via the observability package."
        ),
    },
    {
        "name": "FinServ Monorepo — Repository Structure",
        "trigger": "When navigating the finserv codebase",
        "body": (
            "The finserv monorepo uses pnpm workspaces with Turborepo for orchestration. "
            "Top-level layout:\n"
            "  /packages — shared libraries: core, api, web, mobile, workers, observability, config\n"
            "  /services — deployable services: auth, payments, notifications, reporting\n"
            "Database access is handled via Prisma (schema in /packages/core). "
            "The frontend (/packages/web) uses Next.js with the app router."
        ),
    },
    {
        "name": "FinServ — Common Issue Patterns",
        "trigger": "When triaging GitHub issues",
        "body": (
            "Common issue patterns in the finserv monorepo:\n"
            "1. Type errors after dependency updates — usually caused by breaking changes in @types packages\n"
            "2. Flaky E2E tests — often tied to race conditions in test setup/teardown or network timeouts\n"
            "3. Payment reconciliation timezone issues — date math must use UTC; check day-boundary logic\n"
            "4. Auth token refresh edge cases — look for expired-token handling in middleware and retry logic\n"
            "5. Worker job failures — check dead-letter queues and retry policies in the workers package\n"
            "6. API response shape changes — downstream consumers may not have updated their types\n"
            "7. Next.js hydration mismatches — usually caused by server/client state divergence or conditional rendering on window\n"
            "8. Memory leaks in long-running workers — look for unclosed DB connections and growing in-memory caches"
        ),
    },
]

# ---------------------------------------------------------------------------
# Playbooks
# ---------------------------------------------------------------------------

PLAYBOOKS = [
    {
        "name": "Issue Triage",
        "instructions": (
            "Triage a GitHub issue using the following steps:\n\n"
            "1. **Understand the issue** — Read the title, description, and any linked discussions or screenshots. "
            "Identify what the reporter expects vs. what is happening.\n\n"
            "2. **Search the codebase** — Use the issue details to locate the relevant files, functions, and recent commits. "
            "Check git blame and recent PRs for related changes.\n\n"
            "3. **Root cause analysis** — Trace the code path to determine the underlying cause. "
            "Reproduce the issue locally if possible.\n\n"
            "4. **Classify the issue:**\n"
            "   - **Category:** bug | feature | refactor\n"
            "   - **Complexity:** low (< 1 hr) | medium (1–4 hrs) | high (4+ hrs)\n"
            "   - **Confidence:** green (root cause confirmed) | yellow (likely cause identified) | red (needs more investigation)\n\n"
            "5. **Write a structured triage report** as a comment on the issue:\n"
            "   - Summary of findings\n"
            "   - Affected files and packages\n"
            "   - Suggested fix approach\n"
            "   - Classification (category, complexity, confidence)\n"
            "   - Any open questions or blockers"
        ),
    },
    {
        "name": "Issue Fix",
        "instructions": (
            "Fix a GitHub issue starting from the triage report:\n\n"
            "1. **Review the triage report** — Read the triage comment on the issue to understand the root cause, "
            "affected files, and suggested fix approach.\n\n"
            "2. **Create a feature branch** — Branch from main using the naming convention: "
            "fix/<issue-number>-<short-description> for bugs, feat/<issue-number>-<short-description> for features.\n\n"
            "3. **Implement a minimal, correct fix** — Make the smallest change that fully resolves the issue. "
            "Follow the coding standards (TypeScript strict mode, Result<T, E> pattern, structured logging). "
            "Do not refactor unrelated code.\n\n"
            "4. **Write tests** — Add or update Jest tests that cover the fix. "
            "Include a test case that reproduces the original bug to prevent regression.\n\n"
            "5. **Run quality checks** — Execute lint, typecheck, and test suites:\n"
            "   pnpm lint && pnpm typecheck && pnpm test\n\n"
            "6. **Open a pull request** — Use a conventional commit title that links to the issue "
            "(e.g. 'fix(payments): resolve timezone offset in reconciliation #42'). "
            "Include a description summarizing the root cause and the fix."
        ),
    },
]

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

SCHEDULE = {
    "prompt": (
        "Scan the GitHub issue tracker for untriaged issues older than 7 days. "
        "Assess the top 10 by priority and recency. For each issue, post a summary comment "
        "with an initial classification (category, complexity, confidence) and suggested next steps. "
        "If an issue already has a triage comment, skip it."
    ),
    "cron_schedule": "0 8 * * 1-5",
    "timezone": "America/New_York",
}


def create_resource(endpoint: str, payload: dict, label: str) -> dict:
    """POST a resource to the Devin API and return the response JSON."""
    url = f"{BASE_URL}/{endpoint}"
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    data = response.json()
    print(f"  Created {label}: {data}")
    return data


def main() -> None:
    # --- Knowledge notes ---
    print("Creating knowledge notes...")
    for note in KNOWLEDGE_NOTES:
        create_resource("knowledge/notes", note, f"note '{note['name']}'")

    # --- Playbooks ---
    print("\nCreating playbooks...")
    for playbook in PLAYBOOKS:
        create_resource("playbooks", playbook, f"playbook '{playbook['name']}'")

    # --- Schedule ---
    print("\nCreating schedule...")
    create_resource("schedules", SCHEDULE, "schedule (weekday 8 AM ET sweep)")

    print("\nSetup complete.")


if __name__ == "__main__":
    main()
