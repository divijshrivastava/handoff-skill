from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import handoff_guard as guard
from handoff_channel import Channel


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")
        self.cache = patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.root / "names")})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.channel = Channel(self.root)

    def actors(self):
        a = self.channel.join("Alpha", "Claude Code", "native-alpha")["session"]
        b = self.channel.join("Beta", "Other harness")["session"]
        return a, b

    def cli(self, *args, input=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "handoff_channel.py"), "--root", str(self.root), *args],
            input=input, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )

    def task(self, title, owner, completed=False):
        text = guard.make_template("2026-09-09", title, owner, ["Save work.", "Verify."])
        return text.replace("- [ ]", "- [x]") if completed else text.replace("- [ ] In progress", "- [x] In progress")

    def work(self):
        text = ("# Handoff\n\n" + self.task("One", "Alpha") + "\n" + self.task("Two", "Alpha")
                + "\n" + self.task("Done", "Alpha", True) + "\n" + self.task("Peer", "Beta"))
        self.ledger.write_text(text, encoding="utf-8")
        return guard.ledger_version(text)

    def hook(self, event="StopFailure", **values):
        return {"hook_event_name": event, "session_id": "native-alpha", "cwd": str(self.root),
                "error": "rate_limit", **values}

    def test_peers_without_channel_does_not_create_files(self):
        self.assertEqual(self.channel.peers(), [])
        self.assertFalse((self.root / ".handoff").exists())

    def test_join_requires_a_ledger_and_keeps_messages_untracked(self):
        self.ledger.unlink()
        with self.assertRaises(ValueError):
            self.channel.join("Alpha", "Test")
        self.assertFalse((self.root / ".handoff").exists())
        self.ledger.write_text("# Handoff\n", encoding="utf-8")
        self.actors()
        self.assertEqual((self.root / ".handoff/.gitignore").read_text(), "*\n")

    def test_duplicate_owner_cannot_replace_a_session(self):
        a, _ = self.actors()
        with self.assertRaises(ValueError):
            self.channel.join("Alpha", "Another harness")
        self.assertIn(a, [row["id"] for row in self.channel.peers()])

    def test_offline_recipient_gets_durable_message_from_another_process(self):
        a, b = self.actors()
        sent = self.cli("send", "--session", a, "--to", b, "--body", "Ready for review", "--id", "retry-1")
        self.assertEqual(sent.returncode, 0, sent.stderr)
        received = self.cli("inbox", "--session", b)
        self.assertEqual(received.returncode, 0, received.stderr)
        self.assertEqual(json.loads(received.stdout)["messages"][0]["body"], "Ready for review")
        # A fresh process and repeated reads see it until explicitly acknowledged.
        self.assertEqual(len(Channel(self.root).inbox(b)), 1)
        self.channel.acknowledge(b, "retry-1")
        self.assertEqual(Channel(self.root).inbox(b), [])

    def test_send_retries_deduplicate_but_reused_ids_cannot_change_messages(self):
        a, b = self.actors()
        self.channel.send(a, b, "Saved", "same")
        self.assertTrue(self.channel.send(a, b, "Saved", "same")["duplicate"])
        with self.assertRaises(ValueError):
            self.channel.send(a, b, "Different", "same")
        self.assertEqual(len(self.channel.inbox(b)), 1)

    def test_parallel_sends_with_one_id_store_one_message(self):
        a, b = self.actors()
        argv = [sys.executable, str(SCRIPTS / "handoff_channel.py"), "--root", str(self.root),
                "send", "--session", a, "--to", b, "--body", "Saved", "--id", "parallel"]
        first = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        second = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for child in (first, second):
            stdout, stderr = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, stderr)
        self.assertEqual(len(self.channel.inbox(b)), 1)

    def test_reply_and_broadcast_acknowledgements_are_per_recipient(self):
        a, b = self.actors()
        c = self.channel.join("Gamma", "Test")["session"]
        sent = self.channel.send(a, "*", "Can anyone verify?")
        self.channel.acknowledge(b, sent["id"])
        self.assertEqual(self.channel.inbox(b), [])
        self.assertEqual(len(self.channel.inbox(c)), 1)
        reply = self.channel.send(b, a, "I can", reply_to=sent["id"])
        self.assertEqual(self.channel.inbox(a)[0]["id"], reply["id"])
        with self.assertRaises(ValueError):
            self.channel.acknowledge(c, reply["id"])

    def test_unknown_recipient_or_reply_does_not_save_a_message(self):
        a, b = self.actors()
        for kwargs in ({"recipient": "missing"}, {"recipient": b, "reply_to": "missing"}):
            with self.assertRaises(ValueError):
                self.channel.send(a, body="Hello", **kwargs)
        self.assertEqual(self.channel.inbox(b), [])

    def test_stale_report_and_inbox_poll_do_not_establish_liveness(self):
        a, _ = self.actors()
        self.channel.report(a, "working", "Running checks")
        with self.channel.connect() as connection, connection:
            connection.execute("UPDATE sessions SET reported=? WHERE id=?", (time.time() - 500, a))
        before = next(row for row in self.channel.peers() if row["id"] == a)
        self.channel.inbox(a)
        after = next(row for row in self.channel.peers() if row["id"] == a)
        self.assertEqual(after["availability"], "unknown")
        self.assertEqual(after["reported"], before["reported"])
        self.assertEqual(self.ledger.read_text(), "# Handoff\n")

    def test_unavailable_report_does_not_release_owned_work(self):
        a, _ = self.actors()
        self.work()
        before = self.ledger.read_bytes()
        self.channel.report(a, "unavailable", "Token quota exhausted")
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.channel.peers()[0]["availability"], "unavailable")

    def test_failure_hook_notifies_peers_while_process_is_still_alive(self):
        a, b = self.actors()
        self.work()
        before = self.ledger.read_bytes()
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.channel.report(a, "working", "Editing")
            result = self.cli("claude-hook", input=json.dumps(self.hook()))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(child.poll())
            self.assertEqual(self.channel.peers()[0]["availability"], "unavailable")
            message = self.channel.inbox(b)[0]
            self.assertEqual(message["kind"], "host_failure")
            self.assertIn("rate_limit", message["body"])
            self.assertEqual(self.ledger.read_bytes(), before)
        finally:
            child.terminate()
            child.wait(timeout=5)

    def test_failure_hook_does_not_copy_error_text_or_assert_exhaustion(self):
        _, b = self.actors()
        self.channel.claude_hook(self.hook(error="max_output_tokens", error_details="private-data"))
        message = self.channel.inbox(b)[0]["body"]
        self.assertIn("max_output_tokens", message)
        self.assertIn("quota exhaustion and stopped child writers are not established", message)
        self.assertNotIn("private-data", message)

    def test_compaction_and_unbound_hooks_cannot_change_capability(self):
        a, b = self.actors()
        self.channel.report(a, "working", "Editing")
        for payload in (self.hook("PreCompact"), self.hook("PostCompact"), self.hook(session_id="unbound")):
            self.assertEqual(self.channel.claude_hook(payload), {})
        self.assertEqual(self.channel.peers()[0]["availability"], "working")
        self.assertEqual(self.channel.inbox(b), [])

    def test_hook_cannot_update_a_different_repository(self):
        self.actors()
        with self.assertRaises(ValueError):
            self.channel.claude_hook(self.hook(cwd=str(self.root.parent)))

    def test_session_start_is_idempotent_and_inbox_hook_does_not_clear_failure(self):
        started = self.channel.claude_hook(self.hook("SessionStart"))
        a = self.channel.peers()[0]["id"]
        self.assertIn(a, started["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.channel.claude_hook(self.hook("SessionStart")), started)
        b = self.channel.join("Other", "Other harness")["session"]
        self.channel.claude_hook(self.hook())
        sent = self.channel.send(b, a, "Can I help?")
        context = self.channel.claude_hook(self.hook("PostToolUse"))
        self.assertIn(sent["id"], context["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(next(row for row in self.channel.peers() if row["id"] == a)["availability"], "unavailable")
        self.assertEqual(len(self.channel.inbox(a)), 1)

    def test_hook_in_untracked_repository_does_nothing(self):
        self.ledger.unlink()
        self.assertEqual(self.channel.claude_hook(self.hook("SessionStart")), {})
        self.assertFalse((self.root / ".handoff").exists())

    def test_malformed_hook_input_returns_an_error_without_a_traceback(self):
        for payload in ("{", "[]", json.dumps(self.hook(session_id=[]))):
            result = self.cli("claude-hook", input=payload)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.channel.claude_hook(self.hook(hook_event_name=[])), {})

    def test_yield_releases_whole_unfinished_bucket_preserving_history(self):
        a, b = self.actors()
        version = self.work()
        before = guard.parse_tasks(self.ledger.read_text())
        result = self.channel.yield_work(a, version, "token-limit", "Saved files. Next: verify.\n## not a new task")
        self.assertEqual(result["status"], "applied")
        after = guard.parse_tasks(self.ledger.read_text())
        self.assertEqual([task.owner for task in after], [None, None, "Alpha", "Beta"])
        self.assertEqual([task.steps for task in after], [task.steps for task in before])
        self.assertEqual([task.state for task in after], [task.state for task in before])
        self.assertFalse(any(task.errors for task in after))
        self.assertIn("by Alpha", self.ledger.read_text())
        self.assertEqual(self.channel.inbox(b)[0]["kind"], "release")

    def test_yield_conflict_does_not_publish_or_change_capability(self):
        a, b = self.actors()
        version = self.work()
        self.ledger.write_text(self.ledger.read_text() + "\n")
        before = self.ledger.read_bytes()
        result = self.channel.yield_work(a, version, "token-limit", "Next: verify")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.channel.inbox(b), [])
        self.assertNotEqual(self.channel.peers()[0]["state"], "released")

    def test_notification_failure_keeps_release_recoverable_in_ledger(self):
        a, _ = self.actors()
        version = self.work()
        with patch.object(Channel, "publish", side_effect=sqlite3.OperationalError("disk full")):
            result = self.channel.yield_work(a, version, "token-limit", "Next: verify")
        self.assertEqual(result["status"], "applied")
        self.assertIn("notification_error", result)
        self.assertIsNone(guard.parse_tasks(self.ledger.read_text())[0].owner)
        self.assertIn("Released", self.ledger.read_text())

    def test_crashed_message_writer_rolls_back_and_releases_database_lock(self):
        a, b = self.actors()
        code = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from handoff_channel import Channel
channel = Channel(Path(sys.argv[2]))
with channel.connect() as connection:
    connection.execute('BEGIN IMMEDIATE')
    channel.publish(connection, sys.argv[3], sys.argv[4], 'Saved', message_id='crashed')
    os._exit(13)
"""
        result = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(self.root), a, b], timeout=10)
        self.assertEqual(result.returncode, 13)
        self.assertEqual(self.channel.inbox(b), [])
        self.channel.send(a, b, "Saved", "crashed")
        self.assertEqual(len(self.channel.inbox(b)), 1)

    def test_process_death_after_ledger_release_cannot_reclaim_work(self):
        a, _ = self.actors()
        version = self.work()
        code = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from handoff_channel import Channel
channel = Channel(Path(sys.argv[2]))
Channel.publish = staticmethod(lambda *a, **kw: os._exit(13))
channel.yield_work(sys.argv[3], sys.argv[4], 'token-limit', 'Next: verify')
"""
        result = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(self.root), a, version], timeout=10)
        self.assertEqual(result.returncode, 13)
        text = self.ledger.read_text()
        self.assertIsNone(guard.parse_tasks(text)[0].owner)
        self.assertIn("Released", text)
        # Channel rollback can leave old presence data, but cannot restore ownership.
        self.channel.report(a, "working", "Resumed; checking the ledger")
        with self.assertRaises(ValueError):
            self.channel.yield_work(a, guard.ledger_version(text), "token-limit", "Retry")
        self.assertEqual(self.ledger.read_text(), text)

    def test_yield_requires_stopped_confirmation_and_owned_tasks(self):
        a, _ = self.actors()
        result = self.cli("yield", "--session", a, "--expect-version", guard.ledger_version(self.ledger.read_text()),
                          "--reason", "token-limit", "--summary", "Next: verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("confirm-stopped", result.stderr)
        with self.assertRaises(ValueError):
            self.channel.yield_work(a, guard.ledger_version(self.ledger.read_text()), "token-limit", "Next: verify")

    def test_two_peers_cannot_both_claim_the_same_released_snapshot(self):
        a, _ = self.actors()
        self.channel.yield_work(a, self.work(), "token-limit", "Next: verify")
        text = self.ledger.read_text()
        version = guard.ledger_version(text)
        task = guard.parse_tasks(text)[0]
        processes = []
        for owner in ("Beta", "Gamma"):
            path = self.root / (owner + ".md")
            path.write_text(guard.reassign_task(text, task.line, task.heading, owner, "Adopted after audit."))
            processes.append(subprocess.Popen(
                [sys.executable, str(SCRIPTS / "handoff_guard.py"), "apply", "--root", str(self.root),
                 "--expect-version", version, "--content", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ))
        codes = []
        for process in processes:
            process.communicate(timeout=15)
            codes.append(process.returncode)
        self.assertEqual(sorted(codes), [0, 3])
        self.assertIn(guard.parse_tasks(self.ledger.read_text())[0].owner, {"Beta", "Gamma"})
        self.assertIn("Released", self.ledger.read_text())

    def test_waiting_inbox_receives_a_message_from_a_separate_process(self):
        a, b = self.actors()
        child = subprocess.Popen(
            [sys.executable, str(SCRIPTS / "handoff_channel.py"), "--root", str(self.root),
             "inbox", "--session", b, "--wait", "5"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.channel.send(a, b, "Next: finish the checks")
        stdout, stderr = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["messages"][0]["body"], "Next: finish the checks")


if __name__ == "__main__":
    unittest.main()
