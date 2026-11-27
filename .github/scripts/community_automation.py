#!/usr/bin/env python3
"""
LeadOrbit Community & Maintainer Automation.

Enforces repository contribution rules for Winter of Code Social (WoCS):
1. Issue comments:
   - Welcomes new contributors who haven't contributed yet.
   - Fast auto-assignment when a user requests assignment (/assign, assign/, /claim, etc.),
     provided:
       * They have starred the repository.
       * The issue is open and unassigned.
       * They do not already have another open assigned issue (1 issue at a time).
2. Pull requests:
   - Evaluates open PRs created on or after ACTIVE_EPOCH_ISO (2026-11-01T00:00:00Z).
   - Verifies author starred the repository (posts a reminder once if not).
   - Verifies an open/linked issue exists (`Closes #...`) and respects assignment.
   - Verifies CI checks pass and PR is clean/mergeable (no `hold` / `do-not-merge` label).
   - Enforces the maximum 2 merged PRs per contributor per UTC day rule.
   - Applies `wocs` + `level 1` / `level 2` / `level 3` labels from the linked issue.
   - Auto-merges eligible stargazer PRs and posts a summary comment.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import time
from typing import Any


DEFAULT_REPO = os.environ.get("GITHUB_REPOSITORY", "Kuldeeep18/LeadOrbit")
ACTIVE_EPOCH_ISO = os.environ.get("LEADORBIT_ACTIVE_EPOCH", "2026-11-01T00:00:00Z")
MAX_MERGES_PER_DAY = int(os.environ.get("LEADORBIT_MAX_PRS_PER_DAY", "2"))
REQUIRED_CI_CHECK_NAMES = tuple(
    name.strip()
    for name in os.environ.get("LEADORBIT_REQUIRED_CHECKS", "backend-tests,frontend-checks").split(",")
    if name.strip()
)
ADVISORY_CHECK_SUBSTRINGS = ("coderabbit",)
MIN_PR_BODY_LENGTH = 15
BLOCKING_LABELS = frozenset({"hold", "do-not-merge", "wip", "needs-human-review"})
BOT_LOGINS = frozenset({"github-actions", "github-actions[bot]", "web-flow", "coderabbitai[bot]", "dependabot[bot]"})

ASSIGN_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:/assign|assign/|/claim|claim/)(?:\s|$|[.,!?])",
    re.IGNORECASE,
)
ASSIGN_PHRASE_RE = re.compile(
    r"\b(?:please\s+assign|assign\s+(?:this\s+)?(?:issue\s+)?to\s+me|assign\s+me|"
    r"i(?:'d| would)\s+like\s+to\s+(?:take|work\s+on)|can\s+i\s+(?:work\s+on|take)|"
    r"want\s+to\s+work\s+on)\b",
    re.IGNORECASE,
)
NEGATIVE_ASSIGN_RE = re.compile(r"\b(?:do\s+not|don't|unassign|already\s+assigned)\b", re.IGNORECASE)

ISSUE_LINK_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
    r"(?:https?://github\.com/[^/\s]+/[^/\s]+/issues/|#)(\d+)\b",
    re.IGNORECASE,
)
TITLE_ISSUE_RE = re.compile(r"\(#(\d+)\)")


class GitHubClient:
    """Thin wrapper over `gh` CLI so API calls are easily testable."""

    def __init__(self, repo: str = DEFAULT_REPO, dry_run: bool = False):
        self.repo = repo
        self.dry_run = dry_run
        self._stargazers_cache: set[str] | None = None
        self._contributors_cache: set[str] | None = None
        self._repo_owner: str = repo.split("/", 1)[0].lower()

    def run_gh(self, args: list[str]) -> str:
        cmd = ["gh"] + args
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            raise RuntimeError(f"Command {' '.join(cmd)} failed: {res.stderr.strip()}")
        return res.stdout

    def api_json(self, endpoint: str, paginate: bool = False) -> Any:
        args = ["api"]
        if paginate:
            args.append("--paginate")
            # Ensure paginated array merges cleanly via --slurp if needed, or jq
            args.extend(["--slurp", endpoint])
            raw = self.run_gh(args)
            pages = json.loads(raw) if raw.strip() else []
            merged: list[Any] = []
            for page in pages:
                if isinstance(page, list):
                    merged.extend(page)
                elif isinstance(page, dict):
                    merged.append(page)
            return merged
        args.append(endpoint)
        raw = self.run_gh(args)
        return json.loads(raw) if raw.strip() else None

    def get_stargazers(self) -> set[str]:
        if self._stargazers_cache is None:
            raw = self.run_gh(["api", "--paginate", f"repos/{self.repo}/stargazers", "--jq", ".[].login"])
            self._stargazers_cache = {line.strip().lower() for line in raw.splitlines() if line.strip()}
        return self._stargazers_cache

    def is_stargazer(self, username: str) -> bool:
        return username.lower() in self.get_stargazers()

    def get_contributors(self) -> set[str]:
        if self._contributors_cache is None:
            try:
                raw = self.run_gh(["api", "--paginate", f"repos/{self.repo}/contributors", "--jq", ".[].login"])
                self._contributors_cache = {line.strip().lower() for line in raw.splitlines() if line.strip()}
            except RuntimeError:
                self._contributors_cache = set()
        return self._contributors_cache

    def has_raised_pr(self, username: str) -> bool:
        try:
            raw = self.run_gh([
                "api",
                f"search/issues?q=repo:{self.repo}+type:pr+author:{username}",
                "--jq",
                ".total_count",
            ])
            return int(raw.strip() or "0") > 0
        except (RuntimeError, ValueError):
            return False

    def get_issue(self, issue_number: int) -> dict[str, Any] | None:
        try:
            return self.api_json(f"repos/{self.repo}/issues/{issue_number}")
        except RuntimeError:
            return None

    def get_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        try:
            data = self.api_json(f"repos/{self.repo}/issues/{issue_number}/comments", paginate=True)
            return data if isinstance(data, list) else []
        except RuntimeError:
            return []

    def get_open_assigned_issues(self, username: str) -> list[dict[str, Any]]:
        items = self.api_json(f"repos/{self.repo}/issues?state=open&assignee={username}&per_page=100") or []
        return [item for item in items if "pull_request" not in item]

    def assign_issue(self, issue_number: int, username: str) -> None:
        if self.dry_run:
            print(f"[DRY-RUN] Assign #{issue_number} to @{username}")
            return
        self.run_gh(["issue", "edit", str(issue_number), "--repo", self.repo, "--add-assignee", username])

    def post_comment(self, number: int, body: str) -> None:
        if self.dry_run:
            first_line = body.strip().splitlines()[0] if body.strip() else ""
            print(f"[DRY-RUN] Comment on #{number}: {first_line}")
            return
        self.run_gh(["issue", "comment", str(number), "--repo", self.repo, "--body", body])

    def get_open_prs(self, limit: int = 50) -> list[dict[str, Any]]:
        raw = self.run_gh([
            "pr", "list", "--repo", self.repo, "--state", "open", "--limit", str(limit),
            "--json", "number,title,author,body,createdAt,isDraft,mergeable,mergeStateStatus,labels,headRefOid,statusCheckRollup",
        ])
        return json.loads(raw)

    def get_pr(self, pr_number: int) -> dict[str, Any] | None:
        try:
            raw = self.run_gh([
                "pr", "view", str(pr_number), "--repo", self.repo,
                "--json", "number,title,author,body,state,createdAt,isDraft,mergeable,mergeStateStatus,labels,headRefOid,statusCheckRollup",
            ])
            return json.loads(raw)
        except RuntimeError:
            return None

    def get_merged_prs_today_count(self, username: str, utc_day: str) -> int:
        raw = self.run_gh([
            "pr", "list", "--repo", self.repo, "--state", "merged", "--author", username,
            "--limit", "20", "--json", "number,mergedAt",
        ])
        prs = json.loads(raw)
        return sum(1 for pr in prs if (pr.get("mergedAt") or "").startswith(utc_day))

    def get_check_runs(self, commit_sha: str) -> list[dict[str, Any]]:
        if not commit_sha:
            return []
        try:
            data = self.api_json(f"repos/{self.repo}/commits/{commit_sha}/check-runs")
            return data.get("check_runs", []) if isinstance(data, dict) else []
        except RuntimeError:
            return []

    def add_labels(self, number: int, labels: list[str]) -> None:
        if not labels:
            return
        if self.dry_run:
            print(f"[DRY-RUN] Add labels {labels} to #{number}")
            return
        self.run_gh(["pr", "edit", str(number), "--repo", self.repo, "--add-label", ",".join(labels)])

    def merge_pr(self, pr_number: int) -> None:
        if self.dry_run:
            print(f"[DRY-RUN] Merge PR #{pr_number}")
            return
        self.run_gh(["pr", "merge", str(pr_number), "--repo", self.repo, "--merge"])


def is_bot_user(username: str, user_type: str = "User") -> bool:
    return (
        not username
        or user_type == "Bot"
        or username.lower() in BOT_LOGINS
        or username.lower().endswith("[bot]")
    )


def wants_issue_assignment(comment_body: str) -> bool:
    text = (comment_body or "").strip()
    if not text or NEGATIVE_ASSIGN_RE.search(text):
        return False
    return bool(ASSIGN_COMMAND_RE.search(text) or ASSIGN_PHRASE_RE.search(text))


def extract_linked_issue_numbers(pr_body: str, pr_title: str = "") -> list[int]:
    """Extract issue numbers referenced via `Closes #N`, `Fixes #N`, `Resolves #N`, or `(#N)` in title."""
    numbers: list[int] = []
    seen: set[int] = set()
    for match in ISSUE_LINK_RE.finditer(pr_body or ""):
        num = int(match.group(1))
        if num not in seen:
            seen.add(num)
            numbers.append(num)
    for match in TITLE_ISSUE_RE.finditer(pr_title or ""):
        num = int(match.group(1))
        if num not in seen:
            seen.add(num)
            numbers.append(num)
    return numbers


def infer_level_label(issue: dict[str, Any] | None) -> str:
    """Map an issue's labels or title difficulty tag to `level 1`, `level 2`, or `level 3`."""
    if not issue:
        return "level 1"
    label_names = {str(lbl.get("name", "")).lower() for lbl in issue.get("labels", [])}
    title = str(issue.get("title", "")).lower()

    if any(k in label_names for k in ("level 3", "level:advanced", "level:critical", "challenging")) or "[advanced]" in title or "[hard]" in title:
        return "level 3"
    if any(k in label_names for k in ("level 2", "level:intermediate")) or "[intermediate]" in title or "[medium]" in title:
        return "level 2"
    return "level 1"


def has_comment_marker(comments: list[dict[str, Any]], marker: str) -> bool:
    return any(marker in (c.get("body") or "") for c in comments)


def evaluate_ci_checks(
    check_runs: list[dict[str, Any]],
    required_checks: tuple[str, ...] = REQUIRED_CI_CHECK_NAMES,
) -> tuple[bool, str]:
    """Ensure required CI check runs completed with success and no repo check failed."""
    by_name: dict[str, dict[str, Any]] = {}
    for run in check_runs:
        name = str(run.get("name") or "")
        lowered = name.lower()
        # Ignore our own automation workflow and advisory third-party bots.
        if "community automation" in lowered or any(sub in lowered for sub in ADVISORY_CHECK_SUBSTRINGS):
            continue
        by_name[name] = run

    for name, run in by_name.items():
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status != "completed":
            return False, f"CI check '{name}' is still {status}."
        if conclusion not in ("success", "neutral", "skipped"):
            return False, f"CI check '{name}' finished with conclusion '{conclusion}'."

    for req in required_checks:
        run = by_name.get(req)
        if not run:
            return False, f"Required CI check '{req}' has not reported yet."
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            return False, f"Required CI check '{req}' status={run.get('status')} conclusion={run.get('conclusion')}."

    return True, "All CI checks passed."


def handle_issue_comment(client: GitHubClient, issue_number: int, commenter: str, commenter_type: str, comment_body: str) -> None:
    if is_bot_user(commenter, commenter_type):
        print(f"Skipping bot comment by @{commenter}.")
        return

    if commenter.lower() == client._repo_owner:
        print(f"Skipping maintainer comment by @{commenter}.")
        return

    issue = client.get_issue(issue_number)
    if not issue or "pull_request" in issue or issue.get("state") != "open":
        print(f"Issue #{issue_number} is closed or a PR. Skipping.")
        return

    comments = client.get_issue_comments(issue_number)
    is_starred = client.is_stargazer(commenter)
    asks_assign = wants_issue_assignment(comment_body)

    # 1. Welcome first-time commenters who haven't contributed yet (unless they are about to get an assign message).
    contributors = client.get_contributors()
    is_newcomer = (
        commenter.lower() not in contributors
        and not client.has_raised_pr(commenter)
    )
    welcome_marker = f"<!-- leadorbit-bot:welcome:@{commenter.lower()} -->"
    legacy_welcome = f"Hi @{commenter}, **LeadOrbit Bot** here!"
    already_welcomed = has_comment_marker(comments, welcome_marker) or any(legacy_welcome in (c.get("body") or "") for c in comments)

    if is_newcomer and not asks_assign and not already_welcomed:
        client.post_comment(
            issue_number,
            f"{welcome_marker}\n"
            f"👋 Hi @{commenter}, **LeadOrbit Bot** here!\n\n"
            "Welcome to **LeadOrbit**! Before starting:\n\n"
            "- ⭐ **Star** this repository\n"
            "- 🍴 **Fork** the repository\n"
            "- 📖 Read the [CONTRIBUTING.md](https://github.com/Kuldeeep18/LeadOrbit/blob/main/CONTRIBUTING.md) guide\n\n"
            "Want to work on this issue? Once you've starred the repo, comment `/assign` and I'll assign it to you right away (one open issue per contributor at a time)!\n\n"
            "Happy coding! 🚀",
        )
        return

    if not asks_assign:
        print(f"Comment by @{commenter} on #{issue_number} is not an assignment request.")
        return

    # 2. Handle assignment request.
    assignees = [a.get("login", "") for a in issue.get("assignees", []) if a.get("login")]
    if any(a.lower() == commenter.lower() for a in assignees):
        print(f"@{commenter} is already assigned to #{issue_number}.")
        return

    if assignees:
        marker = f"<!-- leadorbit-bot:already-assigned:@{commenter.lower()} -->"
        if not has_comment_marker(comments, marker):
            assignee_list = ", ".join(f"@{a}" for a in assignees)
            client.post_comment(
                issue_number,
                f"{marker}\n"
                f"Hi @{commenter} 👋 — this issue is already assigned to {assignee_list}. "
                "Please pick another open unassigned issue so everyone has a fair chance to contribute!",
            )
        return

    if not is_starred:
        marker = f"<!-- leadorbit-bot:star-to-assign:@{commenter.lower()} -->"
        if not has_comment_marker(comments, marker):
            client.post_comment(
                issue_number,
                f"{marker}\n"
                f"Hi @{commenter} 👋 — thanks for offering to work on this issue!\n\n"
                "⭐ **Repository Star Required Before Assignment**:\n"
                "Please **star** this repository (and fork it) first, then comment `/assign` again — "
                "I'll automatically assign this issue to you right away.\n\n"
                "Also remember: one open issue per contributor at a time, and please read "
                "[CONTRIBUTING.md](https://github.com/Kuldeeep18/LeadOrbit/blob/main/CONTRIBUTING.md) before starting.",
            )
        return

    open_assigned = [i for i in client.get_open_assigned_issues(commenter) if i.get("number") != issue_number]
    if open_assigned:
        marker = f"<!-- leadorbit-bot:one-issue-limit:@{commenter.lower()} -->"
        if not has_comment_marker(comments, marker):
            existing_nums = ", ".join(f"#{i['number']}" for i in open_assigned[:3])
            client.post_comment(
                issue_number,
                f"{marker}\n"
                f"Hi @{commenter} 👋 — you currently already have an open assigned issue ({existing_nums}).\n\n"
                "To keep contributions fair across the community and prevent issue hoarding, we assign **one issue at a time**. "
                "Please submit your PR for that issue first, and then comment `/assign` here!",
            )
        return

    # Eligible! Assign immediately.
    client.assign_issue(issue_number, commenter)
    assigned_marker = f"<!-- leadorbit-bot:assigned:@{commenter.lower()} -->"
    if not has_comment_marker(comments, assigned_marker):
        client.post_comment(
            issue_number,
            f"{assigned_marker}\n"
            f"Hi @{commenter} 👋\n\n"
            "You have been **assigned** to this issue! ✅ (Repository ⭐ star verified — thank you!)\n\n"
            "Before opening your Pull Request:\n"
            "- 🍴 Work on a dedicated branch from your fork (never commit directly to `main`)\n"
            "- 🧪 Test your changes locally and verify every line yourself (no purely automated/AI-dumped PRs)\n"
            f"- 🔗 Include `Closes #{issue_number}` in your PR description\n"
            "- ⏱️ Note our **max 2 PRs merged per day** limit per contributor\n\n"
            "Happy coding! 🚀",
        )


def evaluate_pr(
    client: GitHubClient,
    pr: dict[str, Any],
    merged_today_cache: dict[str, int],
    utc_day: str,
) -> bool:
    """Evaluate one open PR against all repo rules; returns True if merged."""
    pr_num = pr["number"]
    author = (pr.get("author") or {}).get("login", "")
    author_type = "Bot" if (pr.get("author") or {}).get("is_bot") else "User"
    created_at = pr.get("createdAt") or ""

    if is_bot_user(author, author_type):
        print(f"PR #{pr_num}: skipping bot author @{author}.")
        return False

    if created_at and created_at < ACTIVE_EPOCH_ISO:
        print(f"PR #{pr_num}: created before active epoch ({created_at} < {ACTIVE_EPOCH_ISO}); skipping.")
        return False

    if pr.get("isDraft"):
        print(f"PR #{pr_num}: draft PR; skipping.")
        return False

    pr_labels = {str(lbl.get("name", "")).lower() for lbl in pr.get("labels", [])}
    if pr_labels & BLOCKING_LABELS:
        print(f"PR #{pr_num}: has blocking label {pr_labels & BLOCKING_LABELS}; skipping.")
        return False

    comments = client.get_issue_comments(pr_num)

    # Rule 1: Stargazer check
    if author.lower() != client._repo_owner and not client.is_stargazer(author):
        marker = f"<!-- leadorbit-bot:pr-star-required:@{author.lower()} -->"
        already_notified = (
            has_comment_marker(comments, marker)
            or any("We noticed that you haven't starred the repository yet" in (c.get("body") or "") for c in comments)
        )
        if not already_notified:
            client.post_comment(
                pr_num,
                f"{marker}\n"
                f"Hi @{author} 👋\n\n"
                "**LeadOrbit Bot here!**\n\n"
                "Thanks for opening a pull request and contributing to the project.\n\n"
                "⭐ **Repository Star Required**:\n"
                "We noticed that you haven't starred the repository yet. Please ⭐ **star** the repository — "
                "once you've starred it, the workflow will automatically continue processing your PR!\n\n"
                "Thanks for contributing! 🚀",
            )
        else:
            print(f"PR #{pr_num}: @{author} still has not starred (already reminded).")
        return False

    # Rule 2: Issue-first check (must reference a valid issue; cannot hijack someone else's assigned issue)
    linked_nums = extract_linked_issue_numbers(pr.get("body") or "", pr.get("title") or "")
    linked_issue: dict[str, Any] | None = None
    for num in linked_nums:
        candidate = client.get_issue(num)
        if candidate and "pull_request" not in candidate:
            linked_issue = candidate
            break

    if not linked_issue and author.lower() != client._repo_owner:
        marker = f"<!-- leadorbit-bot:missing-issue:{pr.get('headRefOid', '')[:12]} -->"
        if not has_comment_marker(comments, marker):
            client.post_comment(
                pr_num,
                f"{marker}\n"
                f"Hi @{author} 👋\n\n"
                "Per our [CONTRIBUTING.md](https://github.com/Kuldeeep18/LeadOrbit/blob/main/CONTRIBUTING.md) **Issue-First Workflow**, "
                "every Pull Request must reference an open, approved issue (for example `Closes #123` in the PR description).\n\n"
                "Please open an issue first or get assigned to an existing issue, then update your PR description with `Closes #<issue-number>`.",
            )
        return False

    if linked_issue and author.lower() != client._repo_owner:
        if linked_issue.get("state") != "open":
            marker = f"<!-- leadorbit-bot:closed-issue:{linked_issue['number']} -->"
            if not has_comment_marker(comments, marker):
                client.post_comment(
                    pr_num,
                    f"{marker}\n"
                    f"Hi @{author} 👋 — linked issue #{linked_issue['number']} is already **closed**.\n\n"
                    "Please open a new issue or reference an active open issue before requesting review/merge.",
                )
            return False
        issue_assignees = [a.get("login", "").lower() for a in linked_issue.get("assignees", []) if a.get("login")]
        issue_author = (linked_issue.get("user") or {}).get("login", "").lower()
        if issue_assignees and author.lower() not in issue_assignees:
            marker = f"<!-- leadorbit-bot:wrong-assignee:{linked_issue['number']} -->"
            if not has_comment_marker(comments, marker):
                assigned_names = ", ".join(f"@{a}" for a in issue_assignees)
                client.post_comment(
                    pr_num,
                    f"{marker}\n"
                    f"Hi @{author} 👋 — linked issue #{linked_issue['number']} is currently assigned to {assigned_names}.\n\n"
                    "Please make sure you are assigned to an issue before submitting a PR for it.",
                )
            return False
        if not issue_assignees and issue_author != author.lower():
            marker = f"<!-- leadorbit-bot:issue-not-assigned:{linked_issue['number']} -->"
            if not has_comment_marker(comments, marker):
                client.post_comment(
                    pr_num,
                    f"{marker}\n"
                    f"Hi @{author} 👋 — please comment `/assign` on issue #{linked_issue['number']} first so it is assigned to you "
                    "(per our Issue-First & 1-issue-at-a-time policy) before auto-merge can proceed.",
                )
            return False

    if author.lower() != client._repo_owner and len((pr.get("body") or "").strip()) < MIN_PR_BODY_LENGTH:
        marker = f"<!-- leadorbit-bot:pr-description-needed:{pr.get('headRefOid', '')[:12]} -->"
        if not has_comment_marker(comments, marker):
            client.post_comment(
                pr_num,
                f"{marker}\n"
                f"Hi @{author} 👋 — please fill out the Pull Request template with a brief summary of your changes and how you tested them locally.",
            )
        return False

    # Rule 3: Merge conflict / branch cleanliness check
    mergeable = pr.get("mergeable")
    merge_state = pr.get("mergeStateStatus")
    if mergeable == "CONFLICTING" or merge_state == "DIRTY":
        marker = f"<!-- leadorbit-bot:conflict:{pr.get('headRefOid', '')[:12]} -->"
        if not has_comment_marker(comments, marker):
            client.post_comment(
                pr_num,
                f"{marker}\n"
                f"Hi @{author} 👋 — this PR currently has merge conflicts with `main`. "
                "Please pull/rebase the latest `main` and push the resolved changes so CI can re-run.",
            )
        return False

    if mergeable != "MERGEABLE" or merge_state != "CLEAN":
        print(f"PR #{pr_num}: not ready yet (mergeable={mergeable}, mergeStateStatus={merge_state}).")
        return False

    # Rule 4: CI check runs must pass
    head_sha = pr.get("headRefOid") or ""
    check_runs = client.get_check_runs(head_sha)
    ci_ok, ci_msg = evaluate_ci_checks(check_runs)
    if not ci_ok:
        print(f"PR #{pr_num}: {ci_msg}")
        return False

    # Rule 5: 2 PRs merged per day cap per contributor (UTC day)
    author_key = author.lower()
    if author_key not in merged_today_cache:
        merged_today_cache[author_key] = client.get_merged_prs_today_count(author, utc_day)

    if author_key != client._repo_owner and merged_today_cache[author_key] >= MAX_MERGES_PER_DAY:
        marker = f"<!-- leadorbit-bot:daily-limit:{utc_day} -->"
        if not has_comment_marker(comments, marker):
            client.post_comment(
                pr_num,
                f"{marker}\n"
                f"Hi @{author} 👋\n\n"
                f"Your PR passes all checks, but you have reached the **{MAX_MERGES_PER_DAY} merged PRs per day** limit for `{utc_day}` (UTC).\n\n"
                "This PR will remain queued and will be merged automatically on the next UTC day!",
            )
        return False

    # Rule 6: Apply WoCS + Level labels and merge!
    level_label = infer_level_label(linked_issue)
    desired_labels = [lbl for lbl in ("wocs", level_label) if lbl.lower() not in pr_labels]
    if desired_labels:
        client.add_labels(pr_num, desired_labels)

    client.merge_pr(pr_num)
    merged_today_cache[author_key] += 1
    new_count = merged_today_cache[author_key]

    merged_marker = "<!-- leadorbit-bot:merged -->"
    if not has_comment_marker(comments, merged_marker):
        client.post_comment(
            pr_num,
            f"{merged_marker}\n"
            f"Thank you @{author} for your contribution to **LeadOrbit** under **Winter of Code Social**! 🎉\n\n"
            f"- ⭐ Verified repository star\n"
            f"- ✅ All CI checks passed\n"
            f"- 🏷️ Applied labels: `wocs`, `{level_label}`\n"
            f"- 📊 Daily merge count (`{utc_day}` UTC): **{new_count}/{MAX_MERGES_PER_DAY}**\n\n"
            "Merged automatically! 🚀",
        )
    return True


def process_open_prs(client: GitHubClient, pr_number: int | None = None) -> int:
    utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    merged_today_cache: dict[str, int] = {}

    if pr_number is not None:
        pr = client.get_pr(pr_number)
        if not pr or pr.get("state") != "OPEN":
            print(f"PR #{pr_number} is not open or not found.")
            return 0
        prs = [pr]
    else:
        prs = client.get_open_prs(limit=40)
        # Process oldest eligible PRs first so merge order is fair and deterministic.
        prs = sorted(prs, key=lambda item: item.get("number", 0))

    merged_count = 0
    for pr in prs:
        num = pr["number"]
        # Re-fetch individual PR if a prior merge in this run advanced `main`.
        if merged_count > 0:
            time.sleep(2)
            refreshed = client.get_pr(num)
            if not refreshed or refreshed.get("state") != "OPEN":
                continue
            pr = refreshed
        if evaluate_pr(client, pr, merged_today_cache, utc_day):
            merged_count += 1
    return merged_count


def main() -> int:
    parser = argparse.ArgumentParser(description="LeadOrbit GitHub automation runner.")
    parser.add_argument("--mode", choices=("issue_comment", "pr", "sweep"), required=True)
    parser.add_argument("--issue", type=int, help="Issue number (for issue_comment mode)")
    parser.add_argument("--user", type=str, help="Commenter GitHub username (for issue_comment mode)")
    parser.add_argument("--user-type", type=str, default="User", help="GitHub account type")
    parser.add_argument("--comment-body", type=str, default="", help="Comment body text")
    parser.add_argument("--pr", type=int, help="Pull Request number (for pr mode)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without mutating GitHub")
    args = parser.parse_args()

    client = GitHubClient(repo=DEFAULT_REPO, dry_run=args.dry_run)

    if args.mode == "issue_comment":
        if not args.issue or not args.user:
            print("--issue and --user are required in issue_comment mode.", file=sys.stderr)
            return 2
        comment_body = args.comment_body or os.environ.get("COMMENT_BODY", "")
        handle_issue_comment(client, args.issue, args.user, args.user_type, comment_body)
        return 0

    if args.mode == "pr":
        if not args.pr:
            print("--pr is required in pr mode.", file=sys.stderr)
            return 2
        merged = process_open_prs(client, pr_number=args.pr)
        print(f"Processed PR #{args.pr}; merged={merged}")
        return 0

    merged = process_open_prs(client, pr_number=None)
    print(f"Sweep complete; merged={merged} PR(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
