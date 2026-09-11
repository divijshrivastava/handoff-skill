from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
GUARD = SCRIPTS / "handoff_guard.py"
LEAD = SCRIPTS / "handoff_lead.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


handoff_guard = _load("handoff_guard", GUARD)
handoff_lead = _load("handoff_lead", LEAD)


class LeadTestCase(unittest.TestCase):
    """Shared fixture: a repository whose ledger a leader may write."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")

    def version(self) -> str:
        return handoff_guard.ledger_version(self.ledger.read_text(encoding="utf-8"))

    def text(self) -> str:
        return self.ledger.read_text(encoding="utf-8")

    def run_lead(self, *args: str, expect: int | None = 0) -> dict:
        result = subprocess.run(
            [sys.executable, str(LEAD), *args, "--root", str(self.root)],
            capture_output=True, text=True, encoding="utf-8", check=False)
        if expect is not None:
            self.assertEqual(result.returncode, expect,
                             f"stdout={result.stdout} stderr={result.stderr}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"stderr": result.stderr, "returncode": result.returncode}

    def claim(self, owner: str = "Epona", hours: float = 4) -> dict:
        return self.run_lead("claim", "--owner", owner, "--hours", str(hours),
                             "--expect-version", self.version())

    def assign(self, to: str = "Fenrir", title: str = "Add search",
               paths: str = "", owner: str = "Epona", needs: list[str] | None = None,
               accept_hours: float = 4, expect: int | None = 0) -> dict:
        args = ["assign", "--owner", owner, "--to", to, "--title", title,
                "--step", "Implement it.", "--step", "Verify it.",
                "--accept-hours", str(accept_hours),
                "--expect-version", self.version()]
        if paths:
            args += ["--paths", paths]
        for need in needs or []:
            args += ["--needs", need]
        return self.run_lead(*args, expect=expect)


class InertWithoutLeaderTests(LeadTestCase):
    """A repository that never designates a leader must be unchanged.

    This is the negative case that protects every existing user: the feature is
    opt-in, so its absence has to be indistinguishable from the feature not
    existing.
    """

    def test_a_ledger_with_no_lead_line_reports_no_leader(self) -> None:
        self.ledger.write_text(
            "# Handoff\n\n" + handoff_guard.make_template(
                "2026-09-11", "Plain task", "Fenrir", ["Do it."]), encoding="utf-8")
        self.assertIsNone(handoff_lead.read_lead(self.text()))
        self.assertEqual(handoff_lead.structure_findings(self.text()), [])
        status = self.run_lead("status")
        self.assertIsNone(status["lead"])
        self.assertEqual(status["assignments"], [])

    def test_assigning_without_a_mandate_is_refused(self) -> None:
        result = self.assign(expect=1)
        self.assertIn("No leader is designated", result["stderr"])

    def test_leadership_metadata_does_not_disturb_guard_parsing(self) -> None:
        # The guard owns entry structure. Leadership adds lines it must ignore.
        self.claim()
        self.assign(paths="src/search.ts")
        tasks = handoff_guard.parse_tasks(self.text())
        self.assertEqual(len(tasks), 1)
        self.assertEqual(handoff_guard.structure_findings(self.text()), [])
        self.assertEqual([label for _, label in tasks[0].steps],
                         ["Implement it.", "Verify it."])


class MandateTests(LeadTestCase):
    def test_a_second_agent_cannot_take_an_active_mandate(self) -> None:
        self.claim("Epona")
        result = self.run_lead("claim", "--owner", "Zorya", "--hours", "4",
                               "--expect-version", self.version(), expect=1)
        self.assertIn("Epona already holds an active mandate", result["stderr"])

    def test_a_stale_version_loses_the_race_for_leadership(self) -> None:
        stale = self.version()
        self.claim("Epona")
        result = self.run_lead("claim", "--owner", "Zorya", "--hours", "4",
                               "--expect-version", stale, expect=3)
        self.assertEqual(result["status"], "conflict")

    def test_an_expired_mandate_cannot_assign(self) -> None:
        """Time passing is not a ledger write, so CAS alone cannot catch this."""
        self.claim("Epona")
        self.assign(to="Fenrir")
        lead = handoff_lead.read_lead(self.text())
        self.ledger.write_text(
            self.text().replace(lead.expires, "2020-01-01T00:00:00Z"), encoding="utf-8")
        result = self.assign(to="Garuda", title="Later", expect=1)
        self.assertIn("expired", result["stderr"])

    def test_a_revoked_mandate_cannot_assign(self) -> None:
        self.claim("Epona")
        self.run_lead("resign", "--owner", "Epona", "--expect-version", self.version())
        result = self.assign(expect=1)
        self.assertIn("No leader is designated", result["stderr"])

    def test_a_replaced_leader_cannot_assign(self) -> None:
        self.claim("Epona")
        self.run_lead("resign", "--owner", "Epona", "--expect-version", self.version())
        self.claim("Zorya")
        result = self.assign(owner="Epona", expect=1)
        self.assertIn("does not hold the mandate", result["stderr"])

    def test_only_the_holder_may_resign_or_renew(self) -> None:
        self.claim("Epona")
        for command in ("resign", "renew"):
            result = self.run_lead(command, "--owner", "Zorya",
                                   "--expect-version", self.version(), expect=1)
            self.assertIn("does not hold the mandate", result["stderr"])

    def test_succession_is_not_automatic_by_default(self) -> None:
        # Inheriting authority the user granted to one agent is the user's call.
        self.claim("Epona")
        self.assertEqual(handoff_lead.read_lead(self.text()).succession, "none")


class AcceptanceTests(LeadTestCase):
    """Acceptance must be the assignee's own act, not a box the assigner ticks."""

    def test_assigned_work_starts_unaccepted_and_not_in_progress(self) -> None:
        self.claim()
        self.assign()
        task = handoff_guard.parse_tasks(self.text())[0]
        self.assertEqual(task.state, "pending")
        self.assertEqual(handoff_lead.read_assignment(self.text(), task).state, "offered")

    def test_accepting_records_in_progress_and_a_lease(self) -> None:
        self.claim()
        task_id = self.assign()["task_id"]
        self.run_lead("accept", "--owner", "Fenrir", "--task", task_id,
                      "--hours", "6", "--expect-version", self.version())
        task = handoff_guard.parse_tasks(self.text())[0]
        self.assertEqual(task.state, "in_progress")
        self.assertEqual(handoff_lead.read_assignment(self.text(), task).state, "accepted")
        # Accepted work always carries a deadline, so it cannot be parked forever.
        self.assertIsNotNone(task.lease)
        self.assertEqual(task.lease.owner, "Fenrir")
        self.assertEqual(handoff_guard.structure_findings(self.text()), [])

    def test_only_the_assignee_may_accept(self) -> None:
        self.claim()
        task_id = self.assign()["task_id"]
        result = self.run_lead("accept", "--owner", "Garuda", "--task", task_id,
                               "--expect-version", self.version(), expect=1)
        self.assertIn("assigned to Fenrir", result["stderr"])

    def test_declining_returns_the_work_unowned_with_a_reason(self) -> None:
        self.claim()
        task_id = self.assign()["task_id"]
        self.run_lead("decline", "--owner", "Fenrir", "--task", task_id,
                      "--reason", "Already superseded by later work.",
                      "--expect-version", self.version())
        task = handoff_guard.parse_tasks(self.text())[0]
        self.assertIsNone(task.owner)
        self.assertIn("Already superseded", self.text())
        self.assertEqual([label for _, label in task.steps],
                         ["Implement it.", "Verify it."])

    def test_accepted_work_cannot_be_declined(self) -> None:
        # A release has to be recorded as a release, not as a refusal.
        self.claim()
        task_id = self.assign()["task_id"]
        self.run_lead("accept", "--owner", "Fenrir", "--task", task_id,
                      "--expect-version", self.version())
        result = self.run_lead("decline", "--owner", "Fenrir", "--task", task_id,
                               "--reason", "Changed my mind.",
                               "--expect-version", self.version(), expect=1)
        self.assertIn("yield", result["stderr"])


class ReservationTests(LeadTestCase):
    """Two agents must never be handed the same bytes."""

    def test_overlapping_files_are_refused(self) -> None:
        self.claim()
        self.assign(to="Fenrir", paths="src/search.ts")
        result = self.assign(to="Garuda", title="Refactor", paths="src/search.ts", expect=1)
        self.assertIn("already holds", result["stderr"])

    def test_a_directory_reservation_covers_what_is_beneath_it(self) -> None:
        self.claim()
        self.assign(to="Fenrir", paths="src/")
        result = self.assign(to="Garuda", title="Refactor", paths="src/deep/file.ts", expect=1)
        self.assertIn("already holds", result["stderr"])

    def test_path_forms_that_mean_the_same_file_collide(self) -> None:
        self.claim()
        self.assign(to="Fenrir", paths="src/search.ts")
        result = self.assign(to="Garuda", title="Refactor", paths="./src/search.ts", expect=1)
        self.assertIn("already holds", result["stderr"])

    def test_distinct_files_are_assignable_in_parallel(self) -> None:
        self.claim()
        self.assign(to="Fenrir", paths="src/search.ts")
        self.assign(to="Garuda", title="Docs", paths="docs/search.md")
        self.assertEqual(len(handoff_guard.parse_tasks(self.text())), 2)

    def test_a_stale_availability_report_does_not_free_reserved_files(self) -> None:
        """Silence is not evidence that an agent stopped editing.

        This is the case where reassigning does the most damage, because the
        quiet agent may be mid-edit in exactly these files.
        """
        self.claim()
        self.assign(to="Fenrir", paths="src/search.ts")
        held = {path for path, _ in handoff_lead.reserved_paths(self.text())}
        self.assertEqual(held, {"src/search.ts"})
        result = self.assign(to="Garuda", title="Refactor", paths="src/search.ts", expect=1)
        self.assertIn("Fenrir already holds", result["stderr"])

    def test_completing_the_work_frees_its_reservation(self) -> None:
        self.claim()
        self.assign(to="Fenrir", paths="src/search.ts")
        self.ledger.write_text(self.text().replace("- [ ]", "- [x]"), encoding="utf-8")
        self.assertEqual(handoff_lead.reserved_paths(self.text()), [])
        self.assign(to="Garuda", title="Refactor", paths="src/search.ts")

    def test_a_declined_assignment_frees_its_reservation(self) -> None:
        self.claim()
        task_id = self.assign(to="Fenrir", paths="src/search.ts")["task_id"]
        self.run_lead("decline", "--owner", "Fenrir", "--task", task_id,
                      "--reason", "Not mine.", "--expect-version", self.version())
        self.assign(to="Garuda", title="Refactor", paths="src/search.ts")


class DependencyTests(LeadTestCase):
    def test_a_task_id_survives_retitling_and_reassignment(self) -> None:
        """Headings are not identifiers: they repeat and they get rewritten."""
        self.claim()
        task_id = self.assign(to="Fenrir")["task_id"]
        task = handoff_guard.parse_tasks(self.text())[0]
        moved = handoff_guard.reassign_task(self.text(), task.line, task.heading,
                                            "Zorya", "Moved by the user.")
        self.ledger.write_text(moved, encoding="utf-8")
        self.assertEqual(handoff_lead.read_task_id(
            self.text(), handoff_guard.parse_tasks(self.text())[0]), task_id)

    def test_an_unknown_dependency_is_refused_at_assign_time(self) -> None:
        self.claim()
        result = self.assign(needs=["tdeadbeef"], expect=1)
        self.assertIn("no entry declares", result["stderr"])

    def test_an_unmet_dependency_blocks_acceptance(self) -> None:
        self.claim()
        first = self.assign(to="Fenrir", title="Backend")["task_id"]
        second = self.assign(to="Garuda", title="Docs", needs=[first])["task_id"]
        result = self.run_lead("accept", "--owner", "Garuda", "--task", second,
                               "--expect-version", self.version(), expect=1)
        self.assertIn("Unmet dependencies", result["stderr"])

    def test_a_satisfied_dependency_releases_the_dependent_work(self) -> None:
        self.claim()
        first = self.assign(to="Fenrir", title="Backend")["task_id"]
        second = self.assign(to="Garuda", title="Docs", needs=[first])["task_id"]
        self.ledger.write_text(self.text().replace("- [ ]", "- [x]"), encoding="utf-8")
        status = self.run_lead("status")
        blocked = {row["task"]: row["blocked_by"] for row in status["assignments"]}
        self.assertEqual(blocked[second], [])

    def test_superseded_dependencies_can_be_overridden_deliberately(self) -> None:
        self.claim()
        first = self.assign(to="Fenrir", title="Backend")["task_id"]
        second = self.assign(to="Garuda", title="Docs", needs=[first])["task_id"]
        self.run_lead("accept", "--owner", "Garuda", "--task", second,
                      "--ignore-dependencies", "--expect-version", self.version())
        task = next(task for task in handoff_guard.parse_tasks(self.text())
                    if handoff_lead.read_task_id(self.text(), task) == second)
        self.assertEqual(handoff_lead.read_assignment(self.text(), task).state, "accepted")

    def test_a_dependency_cycle_is_a_structural_error(self) -> None:
        text = "# Handoff\n\n"
        for identifier, needs in (("taaaaaaa1", "tbbbbbbb2"), ("tbbbbbbb2", "taaaaaaa1")):
            entry = handoff_guard.make_template("2026-09-11", f"Task {identifier}",
                                                "Fenrir", ["Do it."])
            entry = entry.replace("Steps:", f"Task: id={identifier}\nAssigned: by=Epona; "
                                            f"to=Fenrir; state=offered; needs={needs}\n\nSteps:")
            text += entry + "\n"
        findings = handoff_lead.structure_findings(text)
        self.assertTrue(any("dependency cycle" in item for item in findings), findings)

    def test_duplicate_task_ids_are_a_structural_error(self) -> None:
        text = "# Handoff\n\n"
        for title in ("One", "Two"):
            entry = handoff_guard.make_template("2026-09-11", title, "Fenrir", ["Do it."])
            text += entry.replace("Steps:", "Task: id=tduplicate\n\nSteps:") + "\n"
        findings = handoff_lead.structure_findings(text)
        self.assertTrue(any("already used" in item for item in findings), findings)


class ReclaimTests(LeadTestCase):
    def test_an_unaccepted_offer_is_reclaimable_after_its_deadline(self) -> None:
        self.claim()
        self.assign(to="Fenrir", accept_hours=1)
        stale = self.text().replace(
            handoff_lead.read_assignment(
                self.text(), handoff_guard.parse_tasks(self.text())[0]).accept_by,
            "2020-01-01T00:00:00Z")
        self.ledger.write_text(stale, encoding="utf-8")
        result = self.run_lead("reclaim", "--owner", "Epona",
                               "--expect-version", self.version())
        self.assertEqual(len(result["reclaimed"]), 1)
        self.assertIn("never accepted", result["reclaimed"][0]["reason"])
        self.assertIsNone(handoff_guard.parse_tasks(self.text())[0].owner)

    def test_accepted_work_inside_its_window_is_not_reclaimable(self) -> None:
        self.claim()
        task_id = self.assign(to="Fenrir")["task_id"]
        self.run_lead("accept", "--owner", "Fenrir", "--task", task_id,
                      "--hours", "6", "--expect-version", self.version())
        result = self.run_lead("reclaim", "--owner", "Epona",
                               "--expect-version", self.version(), expect=1)
        self.assertIn("Nothing is reclaimable", result["stderr"])

    def test_an_expired_lease_makes_accepted_work_reclaimable(self) -> None:
        self.claim()
        task_id = self.assign(to="Fenrir")["task_id"]
        self.run_lead("accept", "--owner", "Fenrir", "--task", task_id,
                      "--hours", "6", "--expect-version", self.version())
        task = handoff_guard.parse_tasks(self.text())[0]
        self.ledger.write_text(
            self.text().replace(task.lease.expires, "2020-01-01T00:00:00Z"), encoding="utf-8")
        result = self.run_lead("reclaim", "--owner", "Epona",
                               "--expect-version", self.version())
        self.assertIn("lease", result["reclaimed"][0]["reason"])
        reclaimed = handoff_guard.parse_tasks(self.text())[0]
        self.assertIsNone(reclaimed.owner)
        # The lease went with the ownership: it was the prior owner's deadline.
        self.assertIsNone(reclaimed.lease)
        self.assertEqual(handoff_guard.structure_findings(self.text()), [])

    def test_reclaiming_preserves_steps_order_and_prior_owner(self) -> None:
        self.claim()
        self.assign(to="Fenrir", accept_hours=1)
        before = handoff_guard.parse_tasks(self.text())[0]
        stale = self.text().replace(
            handoff_lead.read_assignment(self.text(), before).accept_by,
            "2020-01-01T00:00:00Z")
        self.ledger.write_text(stale, encoding="utf-8")
        self.run_lead("reclaim", "--owner", "Epona", "--expect-version", self.version())
        after = handoff_guard.parse_tasks(self.text())[0]
        self.assertEqual([label for _, label in after.steps],
                         [label for _, label in before.steps])
        self.assertIn("Fenrir", self.text())
        self.assertIn("preserve uncommitted work", self.text())

    def test_only_the_leader_may_reclaim(self) -> None:
        self.claim()
        self.assign(to="Fenrir", accept_hours=1)
        result = self.run_lead("reclaim", "--owner", "Zorya",
                               "--expect-version", self.version(), expect=1)
        self.assertIn("does not hold the mandate", result["stderr"])


class CoexistenceTests(LeadTestCase):
    """Leadership must not break the ownership commands that already exist."""

    def test_a_user_viewer_move_invalidates_the_assignment_rather_than_erroring(self) -> None:
        """The user outranks the leader, so their move must simply win.

        An assignment whose `to=` no longer names the heading owner is stale by
        construction. Treating that as self-invalidating, rather than as an
        error, is what lets leadership coexist with every existing owner
        mutator without patching any of them.
        """
        self.claim()
        self.assign(to="Fenrir")
        task = handoff_guard.parse_tasks(self.text())[0]
        moved = handoff_guard.reassign_task(self.text(), task.line, task.heading,
                                            "Zorya", "Moved by the user in the viewer.")
        self.ledger.write_text(moved, encoding="utf-8")
        self.assertEqual(handoff_lead.structure_findings(self.text()), [])
        moved_task = handoff_guard.parse_tasks(self.text())[0]
        self.assertEqual(moved_task.owner, "Zorya")
        self.assertIsNone(handoff_lead.read_assignment(self.text(), moved_task))
        self.assertEqual(self.run_lead("status")["assignments"], [])

    def test_an_unassigned_release_also_invalidates_the_assignment(self) -> None:
        self.claim()
        self.assign(to="Fenrir")
        task = handoff_guard.parse_tasks(self.text())[0]
        self.ledger.write_text(
            handoff_guard.reassign_task(self.text(), task.line, task.heading, None,
                                        "Released."), encoding="utf-8")
        released = handoff_guard.parse_tasks(self.text())[0]
        self.assertIsNone(handoff_lead.read_assignment(self.text(), released))
        self.assertEqual(handoff_lead.structure_findings(self.text()), [])

    def test_freed_paths_can_be_reassigned_after_a_user_move(self) -> None:
        self.claim()
        self.assign(to="Fenrir", paths="src/search.ts")
        task = handoff_guard.parse_tasks(self.text())[0]
        self.ledger.write_text(
            handoff_guard.reassign_task(self.text(), task.line, task.heading, None,
                                        "Released."), encoding="utf-8")
        self.assign(to="Garuda", title="Refactor", paths="src/search.ts")


class RosterTests(LeadTestCase):
    def test_an_unregistered_or_silent_agent_is_not_eligible(self) -> None:
        """Unknown is never free. It is the case that does the most damage."""
        self.claim()
        self.assign(to="Fenrir", paths="src/search.ts")
        rows = {row["owner"]: row for row in self.run_lead("roster")["roster"]}
        self.assertFalse(rows["Fenrir"]["eligible"])
        self.assertIn("availability is", rows["Fenrir"]["why"])

    def test_the_roster_reports_load_reservations_and_the_leader(self) -> None:
        self.claim("Epona")
        self.assign(to="Fenrir", paths="src/search.ts")
        rows = {row["owner"]: row for row in self.run_lead("roster")["roster"]}
        self.assertEqual(rows["Fenrir"]["open_load"], 1)
        self.assertEqual(rows["Fenrir"]["reserved_paths"], ["src/search.ts"])
        self.assertTrue(rows["Epona"]["is_leader"])


class PathHelperTests(unittest.TestCase):
    def test_directory_prefixes_and_normalization(self) -> None:
        cases = [
            ("src/a.ts", "src/a.ts", True),
            ("./src/a.ts", "src/a.ts", True),
            ("src/", "src/a.ts", True),
            ("src/", "srcfile.ts", False),
            ("src/a.ts", "src/b.ts", False),
            ("docs/", "src/a.ts", False),
        ]
        for left, right, expected in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    handoff_lead.paths_overlap(handoff_lead.normalize_path(left),
                                               handoff_lead.normalize_path(right)),
                    expected)


if __name__ == "__main__":
    unittest.main()
