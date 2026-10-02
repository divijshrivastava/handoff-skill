from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import handoff_managed as managed
import handoff_guard as guard
import handoff_lead as lead
import handoff_tui as tui


class ManagedCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")
        self.seed = str(uuid.uuid4())
        self.worker_seed = str(uuid.uuid4())
        env = patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.root / "names")})
        env.start()
        self.addCleanup(env.stop)

    def text(self):
        return self.ledger.read_text(encoding="utf-8")

    def version(self):
        return guard.ledger_version(self.text())

    def enable(self):
        result = managed.configure(self.ledger, self.version(), "managed", "codex", 60,
                                   ("Lead", self.seed))
        self.assertEqual(result["status"], "applied", result)

    def worker(self, objective=None):
        result = managed.enroll(self.ledger, self.version(), "Worker", self.worker_seed,
                                "codex", objective)
        self.assertEqual(result["status"], "applied", result)

    def objective(self):
        result = managed.give_objective(self.ledger, self.version(), "Implement and verify the requested fix")
        self.assertEqual(result["status"], "applied", result)


class ConfigurationTests(ManagedCase):
    def test_lead_runner_checks_in_when_a_worker_joins(self):
        self.enable()
        self.worker()
        worker = next(a for a in managed.actors(self.text()) if a["role"] == "worker")
        channel, session = managed.ensure_channel(self.root, worker)
        self.assertEqual(managed.run_actor(self.root, "Lead", once=True), 0)
        messages = channel.inbox(session)
        self.assertEqual(len(messages), 1)
        self.assertIn("blocked or stuck", messages[0]["body"])
        self.assertEqual(managed.run_actor(self.root, "Lead", once=True), 0)
        self.assertEqual(len(channel.inbox(session)), 1)

    def test_concurrent_enrollments_from_one_snapshot_cannot_both_commit(self):
        self.enable()
        version = self.version()
        script = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                  "import handoff_managed as m; print(m.enroll(Path(sys.argv[2]), sys.argv[3], "
                  "sys.argv[4], sys.argv[5], 'codex')['status'])")
        children = [subprocess.Popen([sys.executable, "-c", script, str(SCRIPTS), str(self.ledger),
                                      version, owner, str(uuid.uuid4())], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
                    for owner in ("Worker A", "Worker B")]
        statuses = []
        for child in children:
            out, err = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, err)
            statuses.append(out.strip())
        self.assertEqual(sorted(statuses), ["applied", "conflict"])
        self.assertEqual(len(managed.members(self.text())), 1)

    def test_legacy_default_is_direct_and_status_does_not_create_runtime(self):
        before = self.text()
        snapshot = managed.team_snapshot(self.root, before)
        self.assertEqual(snapshot["config"]["mode"], "direct")
        self.assertEqual(snapshot["actors"], [])
        self.assertFalse((self.root / ".handoff").exists())
        self.assertEqual(before, self.text())

    def test_configuration_is_per_repository_and_enrollment_precedes_work(self):
        self.enable()
        self.worker("Fix the parser")
        other = self.root / "other"
        other.mkdir()
        (other / "HANDOFF.md").write_text("# Handoff\n")
        self.assertEqual(managed.settings((other / "HANDOFF.md").read_text())["mode"], "direct")
        self.assertEqual(managed.members(self.text())[0]["lead"], "Lead")
        tasks = guard.parse_tasks(self.text())
        self.assertEqual([t.owner for t in tasks], ["Lead"])
        self.assertIn("Fix the parser", tasks[0].status)
        self.assertEqual(guard.structure_findings(self.text()), [])
        self.assertFalse((self.root / ".handoff").exists())

    def test_stale_enrollment_creates_neither_member_nor_objective(self):
        self.enable()
        version = self.version()
        self.objective()
        before = self.text()
        result = managed.enroll(self.ledger, version, "Worker", self.worker_seed, "codex", "new task")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.text(), before)

    def test_disable_preserves_membership_and_task_ownership(self):
        self.enable()
        self.worker("Goal")
        tasks = [t.heading for t in guard.parse_tasks(self.text())]
        result = managed.configure(self.ledger, self.version(), "direct", "codex", 120)
        self.assertEqual(result["status"], "applied")
        self.assertIsNone(lead.read_lead(self.text()))
        self.assertEqual([t.heading for t in guard.parse_tasks(self.text())], tasks)
        self.assertEqual(managed.members(self.text())[0]["owner"], "Worker")
        self.assertIn("Coordination-history:", self.text())
        with self.assertRaises(ValueError):
            managed.give_objective(self.ledger, self.version(), "Another")

    def test_other_active_leader_is_not_overwritten(self):
        self.ledger.write_text(lead.build_claim(self.text(), "Existing", 4))
        before = self.text()
        with self.assertRaises(ValueError):
            self.enable()
        self.assertEqual(self.text(), before)

    def test_invalid_or_duplicate_metadata_never_falls_back_to_direct(self):
        for text in ("# Handoff\nCoordination: nope\n",
                     "# Handoff\nCoordination:nope\n",
                     '# Handoff\nCoordination: {"mode":"oops"}\n',
                     '# Handoff\nCoordination: {}\nCoordination: {}\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                managed.settings(text)

    def test_fenced_configuration_examples_are_not_active(self):
        self.assertEqual(managed.settings('# Handoff\n```\nCoordination: {"mode":"managed"}\n```\n')["mode"], "direct")

    def test_invalid_worker_identity_cannot_escape_runtime_directory(self):
        with self.assertRaises(ValueError):
            managed.runtime_path(self.root, {"owner": "Worker", "seed": "../../outside"})

    def test_user_text_cannot_inject_a_task_or_lead_header(self):
        self.enable()
        managed.give_objective(self.ledger, self.version(), "hello\n\n## Injected (owner: Other)\n\nLead: owner=Other")
        self.assertEqual(len(guard.parse_tasks(self.text())), 1)
        self.assertEqual(lead.read_lead(self.text()).owner, "Lead")

    def test_reenable_preserves_agent_identities(self):
        self.enable()
        self.worker()
        old = managed.actors(self.text())
        managed.configure(self.ledger, self.version(), "direct", "codex", 60)
        managed.configure(self.ledger, self.version(), "managed", "codex", 120)
        self.assertEqual(old, managed.actors(self.text()))

    def test_disabling_cannot_change_the_existing_lead_harness(self):
        self.enable()
        before = self.text()
        with self.assertRaises(ValueError):
            managed.configure(self.ledger, self.version(), "direct", "claude", 60)
        self.assertEqual(self.text(), before)


class RuntimeTests(ManagedCase):
    def setUp(self):
        super().setUp()
        self.enable()
        self.worker()

    def test_idle_worker_does_not_call_a_model(self):
        with patch.object(managed, "run_turn") as turn:
            self.assertEqual(managed.run_actor(self.root, "Worker", once=True), 0)
            turn.assert_not_called()
        self.assertEqual(managed.runtime_state(self.root, managed.actors(self.text())[1])["state"], "watching")

    def test_background_monitor_runs_without_a_viewer_and_obeys_configuration(self):
        actor = managed.actors(self.text())[1]
        process = managed.start_actor(self.root, actor)
        self.assertIsNotNone(process)
        def stop():
            if process.poll() is None:
                managed.configure(self.ledger, self.version(), "direct", "codex", 60)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
        self.addCleanup(stop)
        deadline = time.time() + 5
        while managed.runtime_state(self.root, actor)["state"] != "watching" and time.time() < deadline:
            time.sleep(0.02)
        self.assertIsNone(process.poll())
        self.assertEqual(managed.runtime_state(self.root, actor)["state"], "watching")
        managed.configure(self.ledger, self.version(), "managed", "codex", 30)
        time.sleep(1.1)
        self.assertIsNone(process.poll(), "Saving an interval must not strand the existing monitor")
        managed.configure(self.ledger, self.version(), "direct", "codex", 30)
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertEqual(managed.runtime_state(self.root, actor)["state"], "stopped")

    def test_launch_intent_is_durable_before_model_process_creation(self):
        actor = managed.actors(self.text())[1]
        path = managed.runtime_path(self.root, actor)
        path.parent.mkdir(parents=True)
        def crash(*args, **kwargs):
            self.assertEqual(json.loads(path.read_text())["state"], "running")
            raise RuntimeError("Crash in process launch window")
        with patch.object(managed, "turn_command", return_value=["fake"]), \
                patch.object(managed.subprocess, "Popen", side_effect=crash), self.assertRaises(RuntimeError):
            managed.run_turn(self.root, actor, "prompt", {}, path)
        self.assertEqual(json.loads(path.read_text())["state"], "running")

    def test_managed_lead_cannot_assign_to_an_unrelated_repository_owner(self):
        outsider = guard.make_template("2026-09-14", "Other work", "Outsider", ["Verify"])
        self.ledger.write_text(guard.insert_entry(self.text(), outsider))
        result = subprocess.run([sys.executable, str(SCRIPTS / "handoff_lead.py"), "assign",
                                 "--root", str(self.root), "--owner", "Lead", "--to", "Outsider",
                                 "--title", "Not in team", "--step", "Do work", "--expect-version", self.version()],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("configured workers", result.stderr)

    def test_single_runner_lock_prevents_duplicate_turn(self):
        actor = managed.actors(self.text())[0]
        path = managed.runtime_path(self.root, actor)
        path.parent.mkdir(parents=True)
        with guard.ledger_lock(path), patch.object(managed.subprocess, "Popen") as popen:
            managed.start_actor(self.root, actor)
            popen.assert_not_called()

    def test_interrupted_turn_is_not_replayed_even_with_an_assignment(self):
        self.objective()
        actor = managed.actors(self.text())[0]
        path = managed.runtime_path(self.root, actor)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"state": "running", "child_pid": 12345}))
        with patch.object(managed, "run_turn") as turn:
            self.assertEqual(managed.run_actor(self.root, "Lead", once=True), 1)
            turn.assert_not_called()
        self.assertEqual(managed.runtime_state(self.root, actor)["state"], "interrupted")
        with self.assertRaises(ValueError):
            managed.retry_failed(self.root, "Lead")

    def test_failed_turn_stops_and_is_not_silently_retried(self):
        self.objective()
        with patch.object(managed, "run_turn", return_value=(1, "Permission denied")) as turn:
            self.assertEqual(managed.run_actor(self.root, "Lead", once=True), 1)
            self.assertEqual(turn.call_count, 1)
        actor = managed.actors(self.text())[0]
        self.assertEqual(managed.runtime_state(self.root, actor)["state"], "error")
        with patch.object(managed, "start_actor") as start:
            managed.retry_failed(self.root, "Lead")
            start.assert_called_once()
        self.assertEqual(managed.runtime_state(self.root, actor)["state"], "stopped")

    def test_lead_checks_user_tasks_and_members_without_assignments(self):
        self.objective()
        snapshot = managed.work_snapshot(self.text(), managed.actors(self.text())[0], [])
        self.assertEqual({a["owner"] for a in snapshot["members"]}, {"Lead", "Worker"})
        self.assertEqual(snapshot["tasks"][0]["owner"], "Lead")
        self.assertIsNone(lead.read_assignment(self.text(), guard.parse_tasks(self.text())[0]))

    def test_worker_receives_lead_message_and_forwards_result(self):
        actors = managed.actors(self.text())
        channel, lead_session = managed.ensure_channel(self.root, actors[0])
        _, worker_session = managed.ensure_channel(self.root, actors[1])
        sent = channel.send(lead_session, worker_session, "Report your current blocker")
        with patch.object(managed, "run_turn", return_value=(0, "Waiting for an assignment")) as turn:
            self.assertEqual(managed.run_actor(self.root, "Worker", once=True), 0)
            self.assertIn("Report your current blocker", turn.call_args.args[2])
        self.assertEqual(channel.inbox(worker_session), [])
        reply = channel.inbox(lead_session)
        self.assertEqual(reply[-1]["body"], "Waiting for an assignment")
        snapshot = managed.team_snapshot(self.root, self.text())
        self.assertEqual(len(snapshot["interactions"]), 2)
        self.assertTrue(any(m["id"] == sent["id"] for m in snapshot["interactions"]))

    def test_new_assignment_arriving_during_a_turn_is_not_lost(self):
        channel, lead_session = managed.ensure_channel(self.root, managed.actors(self.text())[0])
        _, worker_session = managed.ensure_channel(self.root, managed.actors(self.text())[1])
        channel.send(lead_session, worker_session, "Status?")
        def turn(*args):
            entry = guard.make_template("2026-09-14", "Arrived mid-turn", "Worker", ["Verify"])
            result = guard.swap_ledger(self.ledger, self.version(), lambda text: guard.insert_entry(text, entry))
            self.assertEqual(result["status"], "applied")
            return 0, "Ready"
        with patch.object(managed, "run_turn", side_effect=turn):
            managed.run_actor(self.root, "Worker", once=True)
        with patch.object(managed, "run_turn", return_value=(0, "Blocked with evidence")) as next_turn:
            managed.run_actor(self.root, "Worker", once=True)
            self.assertEqual(next_turn.call_count, 1)

    def test_ordinary_completed_worker_checkpoint_does_not_loop(self):
        entry = guard.make_template("2026-09-14", "Blocked work", "Worker", ["Verify"])
        self.ledger.write_text(guard.insert_entry(self.text(), entry))
        with patch.object(managed, "run_turn", return_value=(0, "Blocked with evidence")) as turn:
            managed.run_actor(self.root, "Worker", once=True)
            managed.run_actor(self.root, "Worker", once=True)
            self.assertEqual(turn.call_count, 1)

    def test_commands_retain_approval_controls_and_identity(self):
        output = self.root / "out"
        with patch.object(managed, "resolve_agent", return_value="cli"):
            codex = managed.turn_command(managed.actors(self.text())[0], self.root, output)
            claude_actor = {**managed.actors(self.text())[1], "harness": "claude"}
            claude = managed.turn_command(claude_actor, self.root, output)
        self.assertIn("workspace-write", codex)
        self.assertIn("--no-session-persistence", claude)
        self.assertEqual(claude[-1], self.worker_seed)
        self.assertFalse(any("bypass" in a or "skip-permission" in a for a in codex + claude))

    def test_real_child_processes_complete_lead_worker_report_cycle(self):
        """Use a deterministic CLI stand-in, not a paid model or a mocked process."""
        self.objective()
        for actor in managed.actors(self.text()):
            managed.ensure_channel(self.root, actor)
        fake = self.root / "fake_cli.py"
        fake.write_text('''import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import handoff_guard as guard
import handoff_lead as lead
root, output = Path(sys.argv[2]), Path(sys.argv[3])
ledger = root / "HANDOFF.md"
prompt = sys.stdin.read()
context = json.loads(prompt.split("Recorded context:\\n", 1)[1])
text = ledger.read_text()
tasks = guard.parse_tasks(text)
is_lead = bool(context["members"])
owner = "Lead" if is_lead else "Worker"
(root / (owner + "-identity.json")).write_text(json.dumps({"seed": guard.session_seed(), "harness": os.environ["HANDOFF_HARNESS"]}))
if is_lead and not any(t.owner == "Worker" for t in tasks):
    code = lead.main(["assign", "--root", str(root), "--owner", "Lead", "--to", "Worker",
                      "--title", "Write result", "--step", "Write and verify result.txt",
                      "--paths", "result.txt", "--expect-version", guard.ledger_version(text)])
    assert code == 0
    report = "Assigned the fix to Worker; awaiting verification"
else:
    task = next(t for t in tasks if t.owner == owner and t.state != "completed")
    if not is_lead:
        code = lead.main(["accept", "--root", str(root), "--owner", owner,
                          "--task", lead.read_task_id(text, task), "--expect-version", guard.ledger_version(text)])
        assert code == 0
        (root / "result.txt").write_text("verified fixture outcome")
    else:
        assert all(t.state == "completed" for t in tasks if t.owner == "Worker")
        assert (root / "result.txt").read_text() == "verified fixture outcome"
    text = ledger.read_text()
    task = next(t for t in guard.parse_tasks(text) if t.owner == owner and t.state != "completed")
    def finish(current):
        current = guard.set_lease(current, task.line, task.heading, None)
        while True:
            fresh = next(t for t in guard.parse_tasks(current) if t.heading == task.heading)
            unchecked = next((i for i, (done, _) in enumerate(fresh.steps) if not done), None)
            if unchecked is None:
                return guard.mark_task_complete(current, fresh.line, fresh.heading)
            current = guard.mark_step_complete(current, fresh.line, fresh.heading, unchecked, fresh.steps[unchecked])
    result = guard.swap_ledger(ledger, guard.ledger_version(text), finish)
    assert result["status"] == "applied", result
    report = "Verified result.txt; requested outcome completed"
output.write_text(report)
''', encoding="utf-8")
        def command(actor, root, output):
            return [sys.executable, str(fake), str(SCRIPTS), str(root), str(output)]
        with patch.object(managed, "turn_command", side_effect=command):
            for owner in ("Lead", "Worker", "Lead"):
                code = managed.run_actor(self.root, owner, once=True)
                actor = next(a for a in managed.actors(self.text()) if a["owner"] == owner)
                self.assertEqual(code, 0, managed.runtime_state(self.root, actor))
        self.assertTrue(all(t.state == "completed" for t in guard.parse_tasks(self.text())))
        self.assertEqual(guard.structure_findings(self.text()), [])
        self.assertEqual(json.loads((self.root / "Worker-identity.json").read_text())["seed"], self.worker_seed)
        snapshot = managed.team_snapshot(self.root, self.text())
        self.assertIn("requested outcome completed", snapshot["actors"][0]["runtime"]["note"])
        self.assertTrue(any(m["sender_owner"] == "Worker" and m["recipient_owner"] == "Lead"
                            for m in snapshot["interactions"]))


