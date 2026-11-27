import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import community_automation as ca


class FakeClient:
    def __init__(
        self,
        *,
        stargazers=None,
        contributors=None,
        issues=None,
        comments=None,
        open_assigned=None,
        open_prs=None,
        merged_today=None,
        check_runs=None,
        workflow_runs=None,
        repo_owner="kuldeeep18",
    ):
        self._stargazers = {u.lower() for u in (stargazers or [])}
        self._contributors = {u.lower() for u in (contributors or [])}
        self._issues = issues or {}
        self._comments = comments or {}
        self._open_assigned = open_assigned or {}
        self._open_prs = open_prs or []
        self._merged_today = {k.lower(): v for k, v in (merged_today or {}).items()}
        self._check_runs = check_runs or {}
        self._workflow_runs = workflow_runs or {}
        self._repo_owner = repo_owner.lower()
        self.assigned_calls = []
        self.posted_comments = []
        self.added_labels = []
        self.merged_prs = []

    def is_stargazer(self, username):
        return username.lower() in self._stargazers

    def get_contributors(self):
        return self._contributors

    def has_raised_pr(self, username):
        return username.lower() in self._contributors

    def get_issue(self, number):
        return self._issues.get(number)

    def get_issue_comments(self, number):
        return self._comments.get(number, [])

    def get_open_assigned_issues(self, username):
        return self._open_assigned.get(username.lower(), [])

    def assign_issue(self, issue_number, username):
        self.assigned_calls.append((issue_number, username))

    def post_comment(self, number, body):
        self.posted_comments.append((number, body))
        self._comments.setdefault(number, []).append({"body": body})

    def get_open_prs(self, limit=50):
        return self._open_prs

    def get_pr(self, pr_number):
        for pr in self._open_prs:
            if pr["number"] == pr_number:
                return pr
        return None

    def get_merged_prs_today_count(self, username, utc_day):
        return self._merged_today.get(username.lower(), 0)

    def get_check_runs(self, sha):
        return self._check_runs.get(sha, [])

    def get_workflow_runs(self, sha):
        return self._workflow_runs.get(sha, [])

    def add_labels(self, number, labels):
        self.added_labels.append((number, labels))

    def merge_pr(self, pr_number):
        self.merged_prs.append(pr_number)


class ParsingHelperTests(unittest.TestCase):
    def test_wants_issue_assignment_patterns(self):
        self.assertTrue(ca.wants_issue_assignment("/assign"))
        self.assertTrue(ca.wants_issue_assignment("assign/"))
        self.assertTrue(ca.wants_issue_assignment("/claim"))
        self.assertTrue(ca.wants_issue_assignment("Hi @Kuldeeep18, please assign this issue to me"))
        self.assertTrue(ca.wants_issue_assignment("Hello, I would like to work on this issue. Could you please assign it to me?"))
        self.assertTrue(ca.wants_issue_assignment("I'd like to take this issue for WoCS 2026"))
        self.assertFalse(ca.wants_issue_assignment("Do not assign this yet"))
        self.assertFalse(ca.wants_issue_assignment("Looks good to me!"))

    def test_extract_linked_issue_numbers(self):
        self.assertEqual(ca.extract_linked_issue_numbers("Closes #746\nFixes #747"), [746, 747])
        self.assertEqual(
            ca.extract_linked_issue_numbers("Resolves https://github.com/Kuldeeep18/LeadOrbit/issues/750"),
            [750],
        )
        self.assertEqual(ca.extract_linked_issue_numbers("", "feat: save shortcut (#699)"), [699])

    def test_infer_level_label(self):
        self.assertEqual(ca.infer_level_label({"title": "LO-135 [Easy]: Fix", "labels": []}), "level 1")
        self.assertEqual(
            ca.infer_level_label({"title": "Improve CSV", "labels": [{"name": "level:intermediate"}]}),
            "level 2",
        )
        self.assertEqual(
            ca.infer_level_label({"title": "LO-147 [Advanced]: Enforce", "labels": []}),
            "level 3",
        )


class IssueCommentAutomationTests(unittest.TestCase):
    def test_non_stargazer_is_not_assigned_and_gets_star_prompt(self):
        client = FakeClient(
            stargazers=[],
            issues={746: {"number": 746, "state": "open", "assignees": []}},
        )
        ca.handle_issue_comment(client, 746, "newuser", "User", "/assign")
        self.assertEqual(client.assigned_calls, [])
        self.assertEqual(len(client.posted_comments), 1)
        self.assertIn("Repository Star Required Before Assignment", client.posted_comments[0][1])

    def test_stargazer_with_no_open_issues_is_assigned_immediately(self):
        client = FakeClient(
            stargazers=["alice"],
            issues={746: {"number": 746, "state": "open", "assignees": []}},
        )
        ca.handle_issue_comment(client, 746, "alice", "User", "/assign")
        self.assertEqual(client.assigned_calls, [(746, "alice")])
        self.assertIn("You have been **assigned**", client.posted_comments[0][1])

    def test_stargazer_with_existing_open_issue_hits_one_issue_limit(self):
        client = FakeClient(
            stargazers=["alice"],
            issues={747: {"number": 747, "state": "open", "assignees": []}},
            open_assigned={"alice": [{"number": 746}]},
        )
        ca.handle_issue_comment(client, 747, "alice", "User", "/assign")
        self.assertEqual(client.assigned_calls, [])
        self.assertIn("one issue at a time", client.posted_comments[0][1])


class PrAutomationTests(unittest.TestCase):
    def _make_pr(
        self,
        number=760,
        author="alice",
        body="Closes #746\n\nRemoved duplicate title tags from head.",
        created="2026-11-28T10:00:00Z",
        merge_state="CLEAN",
    ):
        return {
            "number": number,
            "title": "fix: remove duplicate title tags",
            "author": {"login": author, "is_bot": False},
            "body": body,
            "state": "OPEN",
            "createdAt": created,
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "mergeStateStatus": merge_state,
            "labels": [],
            "headRefOid": "abc123456789",
        }

    def _passing_checks(self):
        return [
            {"name": "backend-tests", "status": "completed", "conclusion": "success"},
            {"name": "frontend-checks", "status": "completed", "conclusion": "success"},
            {"name": "CodeRabbit", "status": "in_progress", "conclusion": None},
        ]

    def test_eligible_stargazer_pr_gets_labeled_and_merged(self):
        pr = self._make_pr()
        client = FakeClient(
            stargazers=["alice"],
            issues={746: {"number": 746, "state": "open", "title": "LO-135 [Easy]: Title", "assignees": [{"login": "alice"}], "labels": [{"name": "level:beginner"}], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            check_runs={"abc123456789": self._passing_checks()},
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 1)
        self.assertEqual(client.added_labels, [(760, ["wocs", "level 1"])])
        self.assertEqual(client.merged_prs, [760])

    def test_third_pr_same_day_is_held_under_two_per_day_limit(self):
        pr = self._make_pr(number=762)
        client = FakeClient(
            stargazers=["alice"],
            issues={746: {"number": 746, "state": "open", "title": "LO-135 [Easy]: Title", "assignees": [{"login": "alice"}], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            merged_today={"alice": 2},
            check_runs={"abc123456789": self._passing_checks()},
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertEqual(client.merged_prs, [])
        self.assertIn("2 merged PRs per day", client.posted_comments[0][1])

    def test_pr_without_linked_issue_is_blocked(self):
        pr = self._make_pr(body="Just a random refactor with no issue link")
        client = FakeClient(
            stargazers=["alice"],
            open_prs=[pr],
            check_runs={"abc123456789": self._passing_checks()},
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertIn("Issue-First Workflow", client.posted_comments[0][1])

    def test_pr_referencing_closed_issue_is_blocked(self):
        pr = self._make_pr(body="Closes #703\n\nFixing a closed issue again.")
        client = FakeClient(
            stargazers=["alice"],
            issues={703: {"number": 703, "state": "closed", "title": "Old issue", "assignees": [{"login": "alice"}], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            check_runs={"abc123456789": self._passing_checks()},
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertIn("already **closed**", client.posted_comments[0][1])

    def test_pr_with_trivial_empty_description_is_blocked(self):
        pr = self._make_pr(body="Closes #746")
        client = FakeClient(
            stargazers=["alice"],
            issues={746: {"number": 746, "state": "open", "title": "LO-135 [Easy]: Title", "assignees": [{"login": "alice"}], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            check_runs={"abc123456789": self._passing_checks()},
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertIn("Pull Request template", client.posted_comments[0][1])

    def test_old_gssoc_pr_before_active_epoch_is_ignored(self):
        pr = self._make_pr(number=682, created="2026-07-14T12:51:14Z")
        client = FakeClient(stargazers=["alice"], open_prs=[pr])
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertEqual(client.posted_comments, [])

    def test_failed_ci_blocks_merge(self):
        pr = self._make_pr()
        client = FakeClient(
            stargazers=["alice"],
            issues={746: {"number": 746, "state": "open", "title": "LO-135 [Easy]: Title", "assignees": [{"login": "alice"}], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            check_runs={
                "abc123456789": [
                    {"name": "backend-tests", "status": "completed", "conclusion": "failure"},
                    {"name": "frontend-checks", "status": "completed", "conclusion": "success"},
                ]
            },
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertEqual(client.merged_prs, [])

    def test_non_stargazer_with_unstable_ci_gets_star_reminder(self):
        pr = self._make_pr(number=765, author="newdev", merge_state="UNSTABLE")
        client = FakeClient(
            stargazers=[],
            issues={746: {"number": 746, "state": "open", "title": "LO-135 [Easy]: Title", "assignees": [{"login": "newdev"}], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            workflow_runs={
                "abc123456789": [{"name": "CI", "conclusion": "action_required", "html_url": "https://github.com/run/1"}]
            },
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertEqual(len(client.posted_comments), 1)
        self.assertIn("LeadOrbit Bot here!", client.posted_comments[0][1])

    def test_pre_cutoff_pr_merges_without_ci_once_author_stars(self):
        pr = self._make_pr(number=744, author="emam2006", created="2026-11-24T10:23:41Z")
        client = FakeClient(
            stargazers=["emam2006"],
            issues={746: {"number": 746, "state": "open", "title": "LO-108 [Easy]: Fix", "assignees": [], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            check_runs={"abc123456789": [{"name": "CodeRabbit", "status": "completed", "conclusion": "neutral"}]},
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 1)
        self.assertEqual(client.added_labels, [(744, ["wocs", "level 1"])])
        self.assertEqual(client.merged_prs, [744])

    def test_post_cutoff_unassigned_issue_is_blocked(self):
        pr = self._make_pr(number=766, author="bob", created="2026-11-28T10:00:00Z")
        client = FakeClient(
            stargazers=["bob"],
            issues={746: {"number": 746, "state": "open", "title": "LO-135 [Easy]: Title", "assignees": [], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            check_runs={"abc123456789": self._passing_checks()},
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertIn("comment `/assign` on issue #746 first", client.posted_comments[0][1])

    def test_action_required_ci_posts_approval_notice(self):
        pr = self._make_pr(number=759, author="wiwiwi2708", merge_state="UNSTABLE")
        client = FakeClient(
            stargazers=["wiwiwi2708"],
            issues={746: {"number": 746, "state": "open", "title": "LO-138 [Easy]: Title", "assignees": [{"login": "wiwiwi2708"}], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            workflow_runs={
                "abc123456789": [{"name": "CI", "conclusion": "action_required", "html_url": "https://github.com/run/46033247720"}]
            },
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertIn("Approve and run", client.posted_comments[0][1])
        self.assertIn("https://github.com/run/46033247720", client.posted_comments[0][1])

    def test_failed_ci_workflow_run_posts_failure_notice(self):
        pr = self._make_pr(number=767, author="alice", merge_state="UNSTABLE")
        client = FakeClient(
            stargazers=["alice"],
            issues={746: {"number": 746, "state": "open", "title": "LO-135 [Easy]: Title", "assignees": [{"login": "alice"}], "labels": [], "user": {"login": "kuldeeep18"}}},
            open_prs=[pr],
            workflow_runs={
                "abc123456789": [{"name": "CI", "conclusion": "failure", "html_url": "https://github.com/run/999"}]
            },
        )
        merged = ca.process_open_prs(client)
        self.assertEqual(merged, 0)
        self.assertIn("`CI` checks failed", client.posted_comments[0][1])
        self.assertIn("https://github.com/run/999", client.posted_comments[0][1])


if __name__ == "__main__":
    unittest.main()
