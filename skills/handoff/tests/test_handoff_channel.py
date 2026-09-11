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
from handoff_channel import SCHEMA, Channel


def _release_sqlite_under(root: Path) -> None:
    """Windows keeps SQLite files locked until every handle drops."""
    if os.name != "nt":
        return
    import gc
    gc.collect()
    for path in root.rglob("channel.sqlite3*"):
        try:
            path.unlink()
        except OSError:
            pass


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
        self.addCleanup(_release_sqlite_under, self.root)
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

    def test_history_without_channel_does_not_create_files(self):
        self.assertEqual(self.channel.history(), {"sessions": [], "messages": [], "truncated": False})
        self.assertFalse((self.root / ".handoff").exists())

    def test_history_returns_broadcast_receipts_without_acknowledging_messages(self):
        a, b = self.actors()
        c = self.channel.join("Gamma", "Codex")["session"]
        self.channel.send(a, b, "Direct body", "direct")
        self.channel.send(a, "*", "Broadcast body", "broadcast")
        self.channel.acknowledge(b, "broadcast")
        before = self.channel.path.read_bytes()
        data = self.channel.history()
        self.assertEqual([row["id"] for row in data["messages"]], ["broadcast", "direct"])
        broadcast, direct = data["messages"]
        self.assertEqual(broadcast["recipient_owner"], "all agents")
        self.assertEqual(broadcast["acknowledged_by"], [b])
        self.assertEqual((direct["sender_owner"], direct["recipient_owner"], direct["body"]),
                         ("Alpha", "Beta", "Direct body"))
        self.assertEqual(direct["acknowledged_by"], [])
        self.assertEqual({row["id"] for row in data["sessions"]}, {a, b, c})
        self.assertFalse(data["truncated"])
        self.assertEqual(self.channel.path.read_bytes(), before)
        self.assertEqual(len(self.channel.inbox(c)), 1)

    def test_history_limit_keeps_newest_messages_and_reports_truncation(self):
        a, b = self.actors()
        for i in range(3):
            self.channel.send(a, b, str(i), str(i))
        self.assertEqual([row["id"] for row in self.channel.history(limit=2)["messages"]], ["2", "1"])
        self.assertTrue(self.channel.history(limit=2)["truncated"])
        for limit in (0, 201):
            with self.assertRaises(ValueError):
                self.channel.history(limit=limit)

    def test_history_reads_an_old_channel_without_migrating_schema(self):
        a, b = self.actors()
        self.channel.send(a, b, "Saved", "saved")
        with sqlite3.connect(str(self.channel.path)) as connection:
            for table in ("attestations", "challenges"):
                connection.execute("DROP TABLE IF EXISTS " + table)
        before = self.channel.path.read_bytes()
        self.assertEqual(self.channel.history()["messages"][0]["body"], "Saved")
        self.assertEqual(self.channel.path.read_bytes(), before)

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


class ChallengeTests(unittest.TestCase):
    """A nonce-bound round trip proves a peer is up; silence still proves nothing.

    The failure case: a report written an hour ago still reads as a report, so a
    peer either trusts stale evidence or reads an owner that has resumed as
    unavailable and takes work it is actively writing.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")
        self.cache = patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.root / "names")})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.addCleanup(_release_sqlite_under, self.root)
        self.channel = Channel(self.root)
        self.a = self.channel.join("Alpha", "Claude Code")["session"]
        self.b = self.channel.join("Beta", "Kimi Code")["session"]

    def version(self):
        return guard.ledger_version(self.ledger.read_text(encoding="utf-8"))

    def peer(self, session):
        return next(row for row in self.channel.peers() if row["id"] == session)

    def test_a_challenge_cannot_be_broadcast_or_aimed_at_itself(self):
        # Each recipient pays a turn out of the budget being asked about.
        for target in ("*", self.a):
            with self.assertRaises(ValueError):
                self.channel.challenge(self.a, target)

    def test_a_second_probe_inside_the_interval_returns_the_open_challenge(self):
        first = self.channel.challenge(self.a, self.b)
        second = self.channel.challenge(self.a, self.b)
        self.assertTrue(first["issued"])
        self.assertFalse(second["issued"])
        self.assertEqual(first["nonce"], second["nonce"])
        self.assertEqual(len(self.channel.inbox(self.b)), 1)

    def test_an_answer_carrying_the_current_ledger_version_proves_a_turn(self):
        nonce = self.channel.challenge(self.a, self.b)["nonce"]
        result = self.channel.attest(self.b, nonce, self.version(), "Finishing the parser step.")
        self.assertTrue(result["attested"])
        answered = next(row for row in self.channel.inbox(self.a) if row["kind"] == "attestation")
        self.assertEqual(json.loads(answered["body"])["nonce"], nonce)
        self.assertEqual(answered["sender_owner"], "Beta")
        self.assertLess(self.peer(self.b)["attested_seconds"], 30)

    def test_an_attestation_clears_an_unavailable_state_a_poll_could_not(self):
        # A host failure marks the session unavailable; the owner's wait then
        # resumes at the reset. Leaving the stale state would invite a takeover
        # of work that session is writing again.
        self.channel.report(self.b, "unavailable", "Host reported a rate limit")
        nonce = self.channel.challenge(self.a, self.b)["nonce"]
        self.channel.attest(self.b, nonce, self.version(), "Back after the reset; resuming step two.")
        self.assertEqual(self.peer(self.b)["availability"], "working")

    def test_a_released_session_stays_released_after_attesting(self):
        with self.channel.connect() as connection, connection:
            connection.execute("UPDATE sessions SET state='released' WHERE id=?", (self.b,))
        nonce = self.channel.challenge(self.a, self.b)["nonce"]
        result = self.channel.attest(self.b, nonce, self.version(), "Alive, but I gave the work up.")
        self.assertFalse(result["state_changed"])
        self.assertEqual(self.peer(self.b)["state"], "released")

    def test_a_wrong_ledger_version_is_not_an_answer(self):
        nonce = self.channel.challenge(self.a, self.b)["nonce"]
        with self.assertRaises(ValueError):
            self.channel.attest(self.b, nonce, "0" * 64, "Guessing.")
        self.assertIsNone(self.peer(self.b)["attested_seconds"])

    def test_an_answered_nonce_cannot_be_replayed(self):
        nonce = self.channel.challenge(self.a, self.b)["nonce"]
        self.channel.attest(self.b, nonce, self.version(), "First answer.")
        with self.assertRaises(ValueError):
            self.channel.attest(self.b, nonce, self.version(), "Replay.")

    def test_only_the_addressed_session_can_answer(self):
        third = self.channel.join("Gamma", "Codex")["session"]
        nonce = self.channel.challenge(self.a, self.b)["nonce"]
        with self.assertRaises(ValueError):
            self.channel.attest(third, nonce, self.version(), "Answering for a peer.")

    def test_an_expired_challenge_cannot_be_answered(self):
        nonce = self.channel.challenge(self.a, self.b, ttl=60)["nonce"]
        with self.channel.connect() as connection, connection:
            connection.execute("UPDATE challenges SET expires=? WHERE nonce=?",
                               (time.time() - 1, nonce))
        with self.assertRaises(ValueError):
            self.channel.attest(self.b, nonce, self.version(), "Too late.")

    def test_silence_leaves_capability_unknown_rather_than_unavailable(self):
        self.channel.report(self.b, "working", "Editing the parser")
        self.channel.challenge(self.a, self.b)
        self.assertEqual(self.peer(self.b)["open_challenges"], 1)
        # An hour later the peer has still said nothing and the nonce has lapsed.
        # An idle healthy agent on any harness looks exactly like this, so the
        # verdict stays unknown: nothing here is evidence its model is gone.
        with patch("handoff_channel.time.time", return_value=time.time() + 3600):
            row = self.peer(self.b)
        self.assertEqual(row["availability"], "unknown")
        self.assertEqual(row["state"], "working")
        self.assertEqual(row["open_challenges"], 0)
        self.assertIsNone(row["attested_seconds"])

    def test_a_channel_made_before_challenges_existed_still_works(self):
        older = Path(self.temp.name).resolve() / "older"
        older.mkdir()
        (older / "HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")
        legacy = Channel(older)
        legacy.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        before, _, after = SCHEMA.partition("CREATE TABLE IF NOT EXISTS challenges")
        with sqlite3.connect(str(legacy.path)) as connection:
            # The schema as it shipped before challenges existed: everything but
            # that one table. A channel already on disk must carry forward.
            connection.executescript(before + after.split(");", 1)[1])
        with sqlite3.connect(str(legacy.path)) as connection:
            tables = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name='challenges'")]
        self.assertEqual(tables, [])
        one = legacy.join("Delta", "Grok")["session"]
        two = legacy.join("Epsilon", "Cursor")["session"]
        self.assertTrue(legacy.challenge(one, two)["issued"])


class NudgeTests(unittest.TestCase):
    """Asking a silent peer to answer, without deciding anything about it.

    The failure case: a peer's task is unfinished, its report has aged out and
    its inbox is unread, so the only moves available are to guess it is gone and
    take work it may be writing, or to spend its remaining budget on a
    challenge. There was no way to say 'you have mail' and leave the record
    exactly as uncertain as it was.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")
        self.cache = patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.root / "names")})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.addCleanup(_release_sqlite_under, self.root)
        self.channel = Channel(self.root)
        self.a = self.channel.join("Alpha", "Claude Code")["session"]
        self.b = self.channel.join("Beta", "Kimi Code")["session"]

    def record(self, session=None):
        return self.channel.silence(session or self.b)[0]

    def peer(self, session):
        return next(row for row in self.channel.peers() if row["id"] == session)

    def unread(self, age):
        """One message to Beta, sent `age` seconds ago and never acknowledged."""
        with patch("handoff_channel.time.time", return_value=time.time() - age):
            self.channel.send(self.a, self.b, "Are you still on the parser task?")

    def stale_report(self, age):
        with patch("handoff_channel.time.time", return_value=time.time() - age):
            self.channel.report(self.b, "working", "Editing the parser")

    def test_a_nudge_cannot_be_broadcast_or_aimed_at_itself(self):
        for target in ("*", self.a):
            with self.assertRaises(ValueError):
                self.channel.nudge(self.a, target)

    def test_a_nudge_leaves_the_peer_state_and_capability_exactly_as_it_was(self):
        self.stale_report(600)
        before = self.peer(self.b)
        result = self.channel.nudge(self.a, self.b)
        after = self.peer(self.b)
        self.assertTrue(result["sent"])
        # Being asked is not evidence, so nothing about the peer may move.
        for field in ("state", "note", "reported", "availability", "attested_seconds"):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual(after["availability"], "unknown")

    def test_an_unanswered_nudge_leaves_availability_unknown(self):
        self.stale_report(600)
        self.channel.nudge(self.a, self.b)
        # An hour later Beta has still said nothing. An idle healthy agent looks
        # exactly like this, so the record must not have hardened into a verdict.
        with patch("handoff_channel.time.time", return_value=time.time() + 3600):
            row = self.peer(self.b)
            record = self.record()
        self.assertEqual(row["availability"], "unknown")
        self.assertEqual(row["state"], "working")
        self.assertTrue(record["silent"])
        self.assertIsNone(record["attested_seconds"])

    def test_a_second_nudge_inside_the_interval_returns_the_first(self):
        self.unread(300)
        first = self.channel.nudge(self.a, self.b)
        second = self.channel.nudge(self.a, self.b)
        self.assertTrue(first["sent"])
        self.assertFalse(second["sent"])
        self.assertEqual(first["message"], second["message"])
        self.assertGreater(second["repeat_in_seconds"], 0)
        # One nudge reached the inbox, beside the message it is about.
        kinds = [row["kind"] for row in self.channel.inbox(self.b)]
        self.assertEqual(kinds.count("nudge"), 1)

    def test_the_interval_expires_and_another_peer_is_never_blocked(self):
        self.unread(300)
        self.channel.nudge(self.a, self.b)
        later = time.time() + 601
        with patch("handoff_channel.time.time", return_value=later):
            self.assertTrue(self.channel.nudge(self.a, self.b)["sent"])
        # The interval is per sender and subject: a third session waiting on the
        # same peer is not silenced by someone else's recent nudge.
        c = self.channel.join("Gamma", "Cursor")["session"]
        self.assertTrue(self.channel.nudge(c, self.b)["sent"])

    def test_silence_needs_both_an_aged_message_and_a_stale_report(self):
        self.assertFalse(self.record()["silent"])
        # A message that arrived a moment ago is not silence; the peer may not
        # have taken a turn since.
        self.unread(5)
        self.channel.report(self.b, "working", "Editing the parser")
        self.assertFalse(self.record()["silent"])
        self.unread(600)
        self.assertFalse(self.record()["silent"])
        self.stale_report(600)
        self.assertTrue(self.record()["silent"])

    def test_acknowledging_ends_the_silence_without_a_reply(self):
        self.unread(600)
        self.stale_report(600)
        record = self.record()
        self.assertTrue(record["silent"])
        self.assertEqual(record["unacknowledged"], 1)
        for row in self.channel.inbox(self.b):
            self.channel.acknowledge(self.b, row["id"])
        after = self.record()
        self.assertEqual(after["unacknowledged"], 0)
        self.assertIsNone(after["oldest_unacknowledged_seconds"])
        self.assertFalse(after["silent"])
        # Reading the mail is not a capability report, so the stale report stands.
        self.assertEqual(after["availability"], "unknown")

    def test_the_nudge_body_asks_for_a_report_and_disclaims_authority(self):
        self.unread(600)
        self.stale_report(600)
        self.channel.nudge(self.a, self.b, "Waiting on the viewer file.")
        message = [row for row in self.channel.inbox(self.b) if row["kind"] == "nudge"][0]
        body = json.loads(message["body"])
        self.assertEqual(body["from_owner"], "Alpha")
        self.assertEqual(body["note"], "Waiting on the viewer file.")
        self.assertIn("report", body["asks"])
        self.assertIn("yield", body["asks"])
        self.assertIn("Nothing about your capability", body["establishes"])
        self.assertEqual(body["observed"]["unacknowledged"], 1)
        # Whole seconds; a recipient cannot act on sub-second precision.
        self.assertIsInstance(body["observed"]["report_age_seconds"], int)

    def test_a_nudge_does_not_touch_the_ledger_or_ownership(self):
        text = ("# Handoff\n\n"
                + guard.make_template("2026-09-10", "Parser", "Beta", ["Write it.", "Verify."])
                .replace("- [ ] In progress", "- [x] In progress"))
        self.ledger.write_text(text, encoding="utf-8")
        version = guard.ledger_version(text)
        self.unread(600)
        self.stale_report(600)
        self.channel.nudge(self.a, self.b)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), text)
        self.assertEqual(guard.ledger_version(self.ledger.read_text(encoding="utf-8")), version)
        self.assertEqual([task.owner for task in guard.parse_tasks(text)], ["Beta"])

    def test_nudging_a_peer_that_is_not_silent_says_so_rather_than_refusing(self):
        self.channel.report(self.b, "working", "Editing the parser")
        result = self.channel.nudge(self.a, self.b)
        self.assertTrue(result["sent"])
        self.assertFalse(result["silence"]["silent"])
        self.assertIn("not silent by the record", result["note"])

    def test_silence_reports_every_peer_and_an_unknown_session_is_an_error(self):
        owners = [row["owner"] for row in self.channel.silence()]
        self.assertEqual(sorted(owners), ["Alpha", "Beta"])
        with self.assertRaises(ValueError):
            self.channel.silence("not-a-session")

    def test_a_bad_interval_or_oversized_note_is_refused(self):
        for interval in (0, 59, 86401):
            with self.assertRaises(ValueError):
                self.channel.nudge(self.a, self.b, interval=interval)
        with self.assertRaises(ValueError):
            self.channel.nudge(self.a, self.b, "x" * 2001)
        with self.assertRaises(ValueError):
            self.channel.nudge(self.a, self.b, "   ")
        self.assertEqual(self.channel.inbox(self.b), [])

    def test_a_channel_made_before_nudges_existed_still_works(self):
        """Nudges ride the messages table, so an existing channel needs no migration."""
        older = self.root / "older"
        older.mkdir()
        (older / "HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")
        legacy = Channel(older)
        legacy.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with sqlite3.connect(str(legacy.path)) as connection:
            connection.executescript(SCHEMA)
        one = legacy.join("Delta", "Grok")["session"]
        two = legacy.join("Epsilon", "Cursor")["session"]
        self.assertTrue(legacy.nudge(one, two)["sent"])
        self.assertEqual([row["kind"] for row in legacy.inbox(two)], ["nudge"])

    def test_cli_nudge_and_silence_emit_json_and_refuse_broadcast(self):
        script = SCRIPTS / "handoff_channel.py"

        def cli(*args):
            return subprocess.run([sys.executable, str(script), "--root", str(self.root), *args],
                                  capture_output=True, text=True, encoding="utf-8", timeout=15)

        self.unread(600)
        self.stale_report(600)
        listed = json.loads(cli("silence").stdout)
        self.assertIn("authorizes taking work", listed["note"])
        self.assertTrue(any(row["silent"] for row in listed["peers"]))
        sent = json.loads(cli("nudge", "--session", self.a, "--to", self.b).stdout)
        self.assertTrue(sent["sent"])
        refused = cli("nudge", "--session", self.a, "--to", "*")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("cannot be broadcast", json.loads(refused.stderr)["error"])


class AssignmentNoticeTests(unittest.TestCase):
    """An assignment made in the viewer has to reach the assignee's own terminal.

    The failure case, reproduced before this existed: the user assigns a task
    from the viewer to an agent that has finished its work. The move writes the
    ledger and publishes nothing, so that agent's inbox stays empty and its next
    tool use carries no hook context. The assignment is invisible to it.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")
        self.cache = patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.root / "names")})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.addCleanup(_release_sqlite_under, self.root)
        self.channel = Channel(self.root)
        self.session = self.channel.join("Beta", "Claude Code", "native-beta")["session"]

    def entry(self, title, owner, state="pending"):
        text = guard.make_template("2026-09-10", title, owner, ["Build it.", "Verify it."])
        if state == "in_progress":
            return text.replace("- [ ] In progress", "- [x] In progress")
        if state == "completed":
            return text.replace("- [ ]", "- [x]")
        return text

    def assign(self, owner="Beta", state="pending"):
        self.ledger.write_text("# Handoff\n\n" + self.entry("Settings page", owner, state),
                               encoding="utf-8")

    def hook(self, event="PostToolUse"):
        return self.channel.claude_hook({"hook_event_name": event, "session_id": "native-beta",
                                         "cwd": str(self.root)})

    def context(self, event="PostToolUse"):
        return self.hook(event).get("hookSpecificOutput", {}).get("additionalContext", "")

    def test_an_empty_ledger_says_nothing_on_a_tool_use(self):
        self.assertEqual(self.hook(), {})

    def test_an_assignment_reaches_the_assignee_on_its_next_event(self):
        self.assign()
        for event in ("PostToolUse", "UserPromptSubmit"):
            with self.subTest(event=event):
                context = self.context(event)
                self.assertIn("Settings page", context)
                self.assertIn("recorded to Beta", context)
                self.assertIn("read from HANDOFF.md and not from a peer", context)

    def test_the_notice_is_not_a_claim_that_anyone_read_it(self):
        self.assign()
        self.assertIn("repeats until", self.context())
        self.assertNotIn("acknowledged", self.context())

    def test_another_agents_assignment_is_not_delivered_here(self):
        self.assign(owner="Alpha")
        self.assertEqual(self.hook(), {})

    def test_starting_the_task_clears_the_notice(self):
        self.assign()
        self.assertIn("Settings page", self.context())
        started = self.entry("Settings page", "Beta", "in_progress").replace(
            "- [ ] Build it.", "- [x] Build it.")
        self.ledger.write_text("# Handoff\n\n" + started, encoding="utf-8")
        self.assertEqual(self.hook(), {})

    def test_a_session_start_names_the_work_already_waiting_for_it(self):
        self.assign()
        context = self.context("SessionStart")
        self.assertIn("Handoff claimed your name", context)
        self.assertIn("Settings page", context)

    def test_an_assignment_and_a_message_are_both_delivered(self):
        peer = self.channel.join("Alpha", "Codex")["session"]
        self.channel.send(peer, self.session, "Please look at the importer.")
        self.assign()
        context = self.context()
        self.assertIn("Handoff inbox", context)
        self.assertIn("Please look at the importer.", context)
        self.assertIn("Settings page", context)

    def test_a_failure_hook_still_reports_only_the_failure(self):
        self.assign()
        self.channel.claude_hook({"hook_event_name": "StopFailure", "session_id": "native-beta",
                                  "cwd": str(self.root), "error": "rate_limit"})
        row = next(item for item in self.channel.peers() if item["id"] == self.session)
        self.assertEqual(row["state"], "unavailable")
        self.assertIn("StopFailure", row["note"])

    def test_a_malformed_entry_is_not_announced_as_an_assignment(self):
        self.ledger.write_text(
            "# Handoff\n\n## 2026-09-10 - Broken (owner: Beta) (harness: Codex)\n\nState:\n\n"
            "- [ ] In progress\n- [x] Completed\n\nSteps:\n\n- [ ] Verify it.\n\n"
            "Status: Completed while In progress is unchecked.\n", encoding="utf-8")
        self.assertEqual(self.hook(), {})

    def test_many_assignments_name_the_first_three_and_count_the_rest(self):
        entries = "".join(self.entry(f"Task {index}", "Beta") + "\n" for index in range(5))
        self.ledger.write_text("# Handoff\n\n" + entries, encoding="utf-8")
        context = self.context()
        self.assertIn("5 task(s)", context)
        self.assertIn("and 2 more", context)
