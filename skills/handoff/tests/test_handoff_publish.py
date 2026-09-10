"""Regression tests for publishing handoff state to a VPS.

Each case starts from a concrete failure the publisher exists to prevent:
straddling a peer's write, sending a home directory to another machine, handing
Codex work to a Claude twin, and leaving a reader with half of two publishes.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import handoff_publish as publish  # noqa: E402

LEDGER = """# Handoff

## 2026-09-10 - Publish state (owner: Epona) (harness: Claude Code)

State:

- [x] In progress
- [ ] Completed

Steps:

- [ ] Build it in /Users/someone/code/thing.

Status: In progress. Working from /home/other/checkout.

## 2026-09-09 - Earlier work (owner: Fenrir) (harness: Codex)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Done.

Status: Complete.
"""

CONFIG = {
    "destination": {"host": "user@vps.example", "path": "/srv/handoff/repo"},
    "agents": [
        {"owner": "Epona", "harness": "Claude Code", "twin": "Epona"},
        {"owner": "Fenrir", "harness": "Codex", "twin": "Fenrir"},
    ],
}


def build_repo(root: Path, ledger: str = LEDGER, config=CONFIG) -> Path:
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "HANDOFF.md").write_text(ledger, encoding="utf-8")
    if config is not None:
        (root / ".handoff").mkdir(exist_ok=True)
        (root / ".handoff" / "vps.json").write_text(json.dumps(config), encoding="utf-8")
    return root


class ConfigTests(unittest.TestCase):
    def test_absent_config_names_the_file_to_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory), config=None)
            with self.assertRaises(publish.PublishError) as caught:
                publish.load_config(root)
            self.assertIn("vps.json", str(caught.exception))

    def test_destination_and_agents_are_required(self):
        for broken in ({"agents": CONFIG["agents"]},
                       {"destination": {"host": "h"}, "agents": CONFIG["agents"]},
                       {"destination": CONFIG["destination"], "agents": []},
                       {"destination": CONFIG["destination"], "agents": [{"owner": "A"}]}):
            with tempfile.TemporaryDirectory() as directory:
                root = build_repo(Path(directory), config=broken)
                with self.assertRaises(publish.PublishError):
                    publish.load_config(root)

    def test_twin_defaults_to_the_owner_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory), config={
                "destination": CONFIG["destination"],
                "agents": [{"owner": "Epona", "harness": "Claude Code"}]})
            self.assertEqual(publish.load_config(root)["agents"][0]["twin"], "Epona")

    def test_a_duplicate_owner_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory), config={
                "destination": CONFIG["destination"],
                "agents": [{"owner": "Epona", "harness": "Claude Code"},
                           {"owner": "Epona", "harness": "Codex"}]})
            with self.assertRaises(publish.PublishError):
                publish.load_config(root)


class RedactionTests(unittest.TestCase):
    def test_home_directories_are_rewritten(self):
        self.assertEqual(publish.redact("see /Users/divij/code/x"), "see /Users/<user>/code/x")
        self.assertEqual(publish.redact("at /home/ci/repo"), "at /home/<user>/repo")

    def test_redaction_reaches_nested_message_bodies(self):
        value = publish.redact_deep({"messages": [{"body": "/Users/someone/secret"}]})
        self.assertEqual(value["messages"][0]["body"], "/Users/<user>/secret")

    def test_a_captured_snapshot_carries_no_home_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory))
            text = json.dumps(publish.capture(root))
            self.assertNotIn("/Users/someone", text)
            self.assertNotIn("/home/other", text)
            self.assertIn("/Users/<user>", text)


class CaptureTests(unittest.TestCase):
    def test_capture_retries_when_the_ledger_moves_mid_read(self):
        """The failure: reading the ledger, then the channel, then publishing a
        state that never existed because a peer wrote in between."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory))
            ledger = root / "HANDOFF.md"
            calls = []

            def moving_channel(_root, limit=publish.MESSAGE_LIMIT):
                calls.append(1)
                if len(calls) == 1:      # a peer writes during the first capture
                    ledger.write_text(LEDGER + "\n## 2026-09-11 - Later (owner: Peer)\n",
                                      encoding="utf-8")
                return {"sessions": [], "messages": [], "messages_available": True,
                        "truncated": False}

            original = publish.channel_state
            publish.channel_state = moving_channel
            try:
                snapshot = publish.capture(root)
            finally:
                publish.channel_state = original
            self.assertEqual(len(calls), 2)
            self.assertEqual(snapshot["ledger"]["version"],
                             publish.ledger_version(ledger.read_text(encoding="utf-8")))

    def test_capture_gives_up_rather_than_publishing_a_blend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory))
            ledger = root / "HANDOFF.md"
            counter = [0]

            def always_moving(_root, limit=publish.MESSAGE_LIMIT):
                counter[0] += 1
                ledger.write_text(LEDGER + f"\n## 2026-09-1{counter[0]} - X (owner: P)\n",
                                  encoding="utf-8")
                return {"sessions": [], "messages": [], "messages_available": True}

            original = publish.channel_state
            publish.channel_state = always_moving
            try:
                with self.assertRaises(publish.PublishError):
                    publish.capture(root, attempts=3)
            finally:
                publish.channel_state = original

    def test_a_repository_without_a_ledger_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            with self.assertRaises(publish.PublishError):
                publish.capture(root)


class SliceTests(unittest.TestCase):
    def snapshot(self, root):
        original = publish.channel_state
        publish.channel_state = lambda _r, limit=200: {
            "sessions": [{"id": "s1", "owner": "Epona", "harness": "Claude Code"},
                         {"id": "s2", "owner": "Fenrir", "harness": "Codex"}],
            "messages": [{"id": "m1", "sender": "s1", "recipient": "s2", "body": "hi"},
                         {"id": "m2", "sender": "s2", "recipient": "*", "body": "all"}],
            "messages_available": True, "truncated": False}
        try:
            return publish.capture(root)
        finally:
            publish.channel_state = original

    def test_each_twin_gets_only_its_owner_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory))
            snapshot = self.snapshot(root)
            epona = publish.slice_for(snapshot, CONFIG["agents"][0])
            fenrir = publish.slice_for(snapshot, CONFIG["agents"][1])
            self.assertEqual(len(epona["entries"]), 1)
            self.assertIn("owner: Epona", epona["entries"][0])
            self.assertNotIn("owner: Fenrir", epona["entries"][0])
            self.assertIn("owner: Fenrir", fenrir["entries"][0])

    def test_a_slice_carries_the_configured_harness_for_the_twin(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.snapshot(build_repo(Path(directory)))
            self.assertEqual(publish.slice_for(snapshot, CONFIG["agents"][1])["harness"], "Codex")

    def test_a_broadcast_reaches_every_slice(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.snapshot(build_repo(Path(directory)))
            for agent in CONFIG["agents"]:
                ids = [row["id"] for row in publish.slice_for(snapshot, agent)["messages"]]
                self.assertIn("m2", ids)

    def test_a_harness_mismatch_is_reported(self):
        """A Codex twin must not be handed work done in Claude Code."""
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.snapshot(build_repo(Path(directory)))
            wrong = {"destination": CONFIG["destination"],
                     "agents": [{"owner": "Epona", "harness": "Codex", "twin": "Epona"}]}
            problems = publish.harness_mismatches(snapshot, wrong)
            self.assertEqual(len(problems), 1)
            self.assertIn("Epona", problems[0])
            self.assertEqual(publish.harness_mismatches(snapshot, CONFIG), [])

    def test_only_unfinished_unmapped_owners_are_warned_about(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.snapshot(build_repo(Path(directory)))
            only_fenrir = {"destination": CONFIG["destination"],
                           "agents": [{"owner": "Fenrir", "harness": "Codex", "twin": "Fenrir"}]}
            # Epona's entry is open, so it is named; Fenrir's is complete and mapped.
            self.assertEqual(publish.unmapped_owners(snapshot, only_fenrir), ["Epona"])
            # With Epona mapped as well, a completed unmapped owner raises nothing.
            self.assertEqual(publish.unmapped_owners(snapshot, CONFIG), [])

    def test_build_files_names_one_file_per_twin(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.snapshot(build_repo(Path(directory)))
            files = publish.build_files(snapshot, CONFIG)
            self.assertEqual(sorted(files), ["agents/Epona.json", "agents/Fenrir.json",
                                             "ledger.md", "snapshot.json"])
            self.assertEqual(files["ledger.md"], snapshot["ledger"]["text"])

    def test_a_twin_name_that_would_escape_the_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.snapshot(build_repo(Path(directory)))
            hostile = {"destination": CONFIG["destination"],
                       "agents": [{"owner": "Epona", "harness": "Claude Code",
                                   "twin": "../../etc/passwd"}]}
            with self.assertRaises(publish.PublishError):
                publish.build_files(snapshot, hostile)


class TransportTests(unittest.TestCase):
    def test_the_remote_command_swaps_a_directory_rather_than_copying_files(self):
        """The failure: a reader seeing half of one publish and half of the next."""
        command = publish.remote_command("/srv/handoff/repo")
        self.assertIn("tar -xf - -C", command)
        self.assertIn(".incoming", command)
        self.assertIn("mv", command)

    def test_a_destination_path_with_a_space_is_quoted(self):
        command = publish.remote_command("/srv/my handoff; rm -rf /")
        self.assertNotIn("; rm -rf /;", command)
        self.assertIn("'/srv/my handoff; rm -rf /'", command)

    def test_dry_run_writes_the_tree_and_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_repo(Path(directory) / "repo")
            out = Path(directory) / "out"
            original = publish.channel_state
            publish.channel_state = lambda _r, limit=200: {
                "sessions": [], "messages": [], "messages_available": True}
            try:
                snapshot = publish.capture(root)
                result = publish.publish(publish.build_files(snapshot, CONFIG),
                                         CONFIG["destination"], dry_run=True, out=out)
            finally:
                publish.channel_state = original
            self.assertFalse(result["published"])
            self.assertTrue((out / "agents" / "Epona.json").is_file())
            self.assertTrue((out / "ledger.md").is_file())


if __name__ == "__main__":
    unittest.main()
