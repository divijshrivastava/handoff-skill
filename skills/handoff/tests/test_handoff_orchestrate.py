from __future__ import annotations

import json
import io
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import handoff_guard as guard
import handoff_managed as managed
import handoff_orchestrate as orchestration


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")
        managed.configure(self.ledger, self.version(), "managed", "codex", 60,
                          ("Lead", str(uuid.uuid4())))

    def text(self):
        return self.ledger.read_text(encoding="utf-8")

    def version(self):
        return guard.ledger_version(self.text())

    def create(self):
        result = orchestration.create_objective(
            self.ledger, self.version(), "Lead", "Ship the feature",
            ["The feature works", "The test passes"])
        self.assertEqual(result["status"], "applied", result)
        return result["id"]

    def child(self, title):
        identifier = orchestration.mint_task_id()
        entry = (f"## 2026-10-03 - {title} (owner: Worker)\n\nState:\n\n"
                 "- [x] In progress\n- [x] Completed\n\n"
                 f"Task: id={identifier}\n\nSteps:\n\n- [x] Finish the work.\n\n"
                 "Status: Completed. Verified.\n")
        result = guard.swap_ledger(self.ledger, self.version(),
                                   lambda text: guard.insert_entry(text, entry))
        self.assertEqual(result["status"], "applied", result)
        return identifier

    def test_objective_requires_completed_child_and_criterion_evidence(self):
        parent = self.create()
        child = self.child("Build")
        self.assertEqual(orchestration.link_child(
            self.ledger, self.version(), "Lead", parent, child)["status"], "applied")
        with self.assertRaisesRegex(ValueError, "one evidence"):
            orchestration.close_objective(self.ledger, self.version(), "Lead",
                                          parent, ["Build passes"])
        self.assertEqual(orchestration.close_objective(
            self.ledger, self.version(), "Lead", parent,
            ["Manual flow checked", "Unit suite passed"])["status"], "applied")
        view = orchestration.objective_view(self.text(), parent)
        self.assertEqual(view["state"], "completed")
        self.assertEqual(len(view["evidence"]), 2)
        self.assertEqual(guard.structure_findings(self.text()), [])

    def test_missing_child_blocks_close_and_duplicate_link(self):
        parent = self.create()
        child = self.child("Build")
        orchestration.link_child(self.ledger, self.version(), "Lead", parent, child)
        with self.assertRaisesRegex(ValueError, "already linked"):
            orchestration.link_child(self.ledger, self.version(), "Lead", parent, child)
        text = self.text().replace("- [x] Completed\n\nTask: id=" + child,
                                   "- [ ] Completed\n\nTask: id=" + child)
        self.ledger.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Every linked child"):
            orchestration.close_objective(self.ledger, self.version(), "Lead",
                                          parent, ["one", "two"])

    def test_existing_managed_objective_can_gain_criteria(self):
        managed.give_objective(self.ledger, self.version(), "Fix the parser")
        task = guard.parse_tasks(self.text())[0]
        identifier = orchestration.read_task_id(self.text(), task)
        result = orchestration.adopt_objective(
            self.ledger, self.version(), "Lead", identifier,
            ["The parser accepts valid input"])
        self.assertEqual(result["status"], "applied")
        self.assertEqual(orchestration.objective_view(
            self.text(), identifier)["criteria"], ["The parser accepts valid input"])
        self.assertEqual(guard.structure_findings(self.text()), [])

    def test_objective_links_cannot_form_cycle(self):
        first = self.create()
        second = self.create()
        orchestration.link_child(self.ledger, self.version(), "Lead", first, second)
        with self.assertRaisesRegex(ValueError, "cycle"):
            orchestration.link_child(self.ledger, self.version(), "Lead", second, first)

    def test_user_message_and_lead_report_are_durable(self):
        orchestration.post_event(self.ledger, self.version(), "user", "Lead",
                                 "Please report progress", "message")
        channel = orchestration.Channel(self.root)
        lead_session = channel.session_for_owner("Lead")
        self.assertIsNotNone(lead_session)
        self.assertEqual([item["body"] for item in channel.inbox(lead_session)],
                         ["Please report progress"])
        orchestration.post_event(self.ledger, self.version(), "Lead", "user",
                                 "Work is under review", "report")
        self.assertIn("Work is under review",
                      [item["body"] for item in channel.history()["messages"]])
        rows = orchestration.header_records(self.text(), orchestration.USER_EVENT)
        self.assertEqual([row["kind"] for row in rows], ["message", "report"])
        self.assertEqual(guard.structure_findings(self.text()), [])

    def test_capacity_default_requests_user_and_auto_enrolls_with_limit(self):
        result = orchestration.request_worker(
            self.ledger, self.version(), "Lead", "Need an independent test", "codex")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(managed.members(self.text()), [])
        self.assertEqual(orchestration.header_records(
            self.text(), orchestration.USER_EVENT)[0]["kind"], "capacity_request")
        orchestration.set_capacity(self.ledger, self.version(), "auto", 1)
        with patch.object(orchestration, "start_actor") as start:
            result = orchestration.request_worker(
                self.ledger, self.version(), "Lead", "Need a worker", "codex")
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(managed.members(self.text())), 1)
        start.assert_called_once()
        with self.assertRaisesRegex(ValueError, "limit reached"):
            orchestration.request_worker(
                self.ledger, self.version(), "Lead", "Need a second worker", "codex")

    def test_stale_objective_write_preserves_peer_change(self):
        old_version = self.version()
        managed.give_objective(self.ledger, old_version, "Peer objective")
        current = self.text()
        result = orchestration.create_objective(
            self.ledger, old_version, "Lead", "My objective", ["It works"])
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.text(), current)

    def test_interrupted_turn_needs_recovery_copy_and_explicit_stop_confirmation(self):
        actor = managed.actors(self.text())[0]
        path = managed.runtime_path(self.root, actor)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"state": "running", "child_pid": 1234,
                                    "note": "Turn stopped unexpectedly"}))
        view = orchestration.recovery_view(self.root)
        self.assertEqual(view["actors"][0]["action"],
                         "audit writers and preserve changes before recovery")
        self.assertEqual(json.loads(path.read_text())["state"], "running")
        recovery_dir = tempfile.TemporaryDirectory()
        self.addCleanup(recovery_dir.cleanup)
        copy = Path(recovery_dir.name) / "recovery.txt"
        copy.write_text("preserved work")
        inside = self.root / "unsafe-copy.txt"
        inside.write_text("inside tree")
        with self.assertRaisesRegex(ValueError, "outside"):
            orchestration.resume_interrupted(
                self.root, "Lead", self.version(), inside, True)
        with self.assertRaisesRegex(ValueError, "Confirm stopped"):
            orchestration.resume_interrupted(
                self.root, "Lead", self.version(), copy, False)
        with patch.object(orchestration, "start_actor") as start:
            result = orchestration.resume_interrupted(
                self.root, "Lead", self.version(), copy, True)
        self.assertEqual(result["status"], "restarted")
        self.assertEqual(json.loads(path.read_text())["state"], "stopped")
        start.assert_called_once()


class TeamCliTests(unittest.TestCase):
    def test_user_can_configure_team_and_create_objective_without_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "HANDOFF.md"
            ledger.write_text("# Handoff\n", encoding="utf-8")
            def call(*args):
                output = io.StringIO()
                version = guard.ledger_version(ledger.read_text(encoding="utf-8"))
                with redirect_stdout(output):
                    code = orchestration.main([
                        args[0], "--root", str(root), "--expect-version", version,
                        *args[1:]])
                self.assertEqual(code, 0, output.getvalue())
                return json.loads(output.getvalue())
            with patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(root / "names")}):
                config = call("team-configure", "--harness", "codex")
                self.assertEqual(config["status"], "applied")
                worker = call("team-enroll", "--harness", "codex")
                self.assertEqual(worker["status"], "applied")
                objective = call("team-objective", "--title", "Fix the parser",
                                 "--criterion", "The parser accepts valid input")
                self.assertEqual(objective["status"], "applied")
                output = io.StringIO()
                with redirect_stdout(output):
                    code = orchestration.main(["team-status", "--root", str(root)])
                self.assertEqual(code, 0)
                self.assertEqual(len(json.loads(output.getvalue())["actors"]), 2)
                self.assertEqual(len(guard.parse_tasks(ledger.read_text())), 1)


if __name__ == "__main__":
    unittest.main()
