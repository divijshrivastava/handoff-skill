from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import handoff_guard as guard
import handoff_tui as tui
sys.path.pop(0)


def entry(title="Task", owner="Agent A", state="in_progress", steps=(True, False)):
    progress = " " if state == "pending" else "x"
    completed = "x" if state == "completed" else " "
    suffix = f" (owner: {owner})" if owner else ""
    return (f"## {title}{suffix}\n\nState:\n- [{progress}] In progress\n"
            f"- [{completed}] Completed\n\nSteps:\n"
            + "".join(f"- [{'x' if done else ' '}] Outcome {i}.\n" for i, done in enumerate(steps))
            + "\nStatus: Recorded status.\nContinuation and next action.\n\n")


class FakeCurses:
    KEY_DOWN, KEY_UP, KEY_NPAGE, KEY_PPAGE = 258, 259, 338, 339
    KEY_ENTER, KEY_BACKSPACE, KEY_HOME, KEY_END = 343, 263, 262, 360
    A_BOLD, A_DIM, A_REVERSE = 1, 2, 4
    error = RuntimeError


class Screen:
    def __init__(self, height=24, width=100):
        self.height, self.width = height, width
        self.lines = {}
        self.frames = []

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.lines = {}

    def addstr(self, y, x, value, style=0):
        assert 0 <= y < self.height
        assert sum(tui.cell_width(c) for c in value) < self.width
        self.lines[y] = value

    def refresh(self):
        self.frames.append("\n".join(self.lines.values()))

    def keypad(self, enabled):
        pass

    def timeout(self, milliseconds):
        assert 1 <= milliseconds <= 250


class ProgressTests(unittest.TestCase):
    def test_steps_are_weighted_and_state_boxes_are_not_steps(self):
        text = (entry("Done", state="completed", steps=(True,))
                + entry("Active", steps=(True, False, False))
                + entry("Queued", owner="Agent B", state="pending", steps=(False, False)))
        snapshot = tui.parse_snapshot(text)
        counts = tui.count_tasks(snapshot.tasks)
        self.assertEqual((counts.completed, counts.tracked), (1, 3))
        self.assertEqual((counts.checked, counts.steps), (2, 6))
        self.assertEqual((counts.in_progress, counts.pending), (1, 1))
        groups = dict(tui.owner_counts(snapshot.tasks))
        self.assertEqual((groups["Agent A"].checked, groups["Agent A"].steps), (2, 4))
        self.assertEqual(groups["Agent B"].pending, 1)

    def test_invalid_and_legacy_entries_do_not_inflate_completion(self):
        text = (entry("False completion", state="completed")
                + "## Legacy (owner: Agent B)\n- [x] Old work\n\n"
                + entry("Valid", owner=None, state="completed", steps=(True,)))
        counts = tui.count_tasks(tui.parse_snapshot(text).tasks)
        self.assertEqual((counts.completed, counts.tracked, counts.checked, counts.steps), (1, 1, 1, 1))
        self.assertEqual((counts.invalid, counts.legacy), (1, 1))
        self.assertIn("unassigned", dict(tui.owner_counts(tui.parse_snapshot(text).tasks)))

    def test_fenced_examples_and_status_prose_do_not_change_counts(self):
        text = "```md\n" + entry("Example", state="completed", steps=(True,)) + "```\n"
        text += entry().replace("\nStatus:", "\n~~~\n- [x] Example step\n~~~\nStatus:")
        text += "The completed step was done by Agent B.\n"
        snapshot = tui.parse_snapshot(text)
        self.assertEqual(len(snapshot.tasks), 1)
        self.assertEqual(tui.count_tasks(snapshot.tasks).checked, 1)
        self.assertEqual(list(dict(tui.owner_counts(snapshot.tasks))), ["Agent A"])
        self.assertIn("Continuation and next action.", snapshot.statuses[0])
        self.assertNotIn("Example step", snapshot.statuses[0])

    def test_empty_ledger_has_no_invented_percentage(self):
        snapshot = tui.parse_snapshot("# Handoff\n")
        self.assertIn("n/a 0/0", tui.summary_lines(snapshot)[0])
        self.assertNotIn("100%", tui.progress(0, 0))

    def test_newest_owner_leads_the_agent_list(self):
        """Newest entries sit at the top, so the newest owner leads, not "Alpha"."""
        text = (entry("Newest", owner="Zeta")
                + entry("Older", owner="Alpha")
                + entry("Oldest", owner="Zeta", state="completed", steps=(True,)))
        owners = [owner for owner, _ in tui.owner_counts(tui.parse_snapshot(text).tasks)]
        self.assertEqual(owners, ["Zeta", "Alpha"])

    def test_harness_comes_from_the_owners_newest_entry_that_records_one(self):
        text = ("## New (owner: Zeta) (harness: Claude Code)\n\nState:\n- [x] In progress\n"
                "- [ ] Completed\n\nSteps:\n- [x] a\n\nStatus: s.\n\n"
                + entry("Older", owner="Zeta")
                + entry("Other", owner="Ann"))
        harnesses = tui.owner_harnesses(tui.parse_snapshot(text).tasks)
        self.assertEqual(harnesses, {"Zeta": "Claude Code"})

    def test_a_recent_claim_is_labelled_recent_and_never_live(self):
        harnesses = {"Zeta": "Claude Code"}
        self.assertEqual(tui.harness_label("Zeta", harnesses, {}), "Claude Code")
        label = tui.harness_label("Zeta", harnesses, {"Zeta": "Claude Code"})
        self.assertEqual(label, "Claude Code (recent)")
        self.assertNotIn("live", label)
        # A session that claimed a name but has written no entry yet.
        self.assertEqual(tui.harness_label("New", {}, {"New": "Codex"}), "Codex (recent)")
        self.assertEqual(tui.harness_label("New", {}, {"New": ""}), "unknown (recent)")

    def test_recent_claim_without_ledger_entry_appears_in_agent_rows(self):
        text = entry("First", owner="Agent A") + entry("Second", owner="Agent B")
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "waiting").write_text("Waiting Agent\nCursor\n", encoding="utf-8")
            with patch.object(tui, "recent_claims_for_ledger",
                              return_value=[guard.NameClaim("Waiting Agent", "Cursor")]):
                rows = tui.agent_rows(tui.parse_snapshot(text).tasks, Path("/repo/HANDOFF.md"))
        self.assertEqual([owner for owner, _ in rows[:3]],
                         ["Waiting Agent", "Agent A", "Agent B"])
        self.assertEqual(rows[0][1].tracked, 0)

    def test_ledger_owner_is_not_duplicated_when_also_recent(self):
        text = entry("First", owner="Agent A")
        with patch.object(tui, "recent_claims_for_ledger",
                          return_value=[guard.NameClaim("Agent A", "Cursor")]):
            rows = tui.agent_rows(tui.parse_snapshot(text).tasks, Path("/repo/HANDOFF.md"))
        self.assertEqual([owner for owner, _ in rows], ["Agent A"])

    def test_agent_rows_ignore_claims_for_other_repositories(self):
        text = entry("First", owner="Agent A")
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "names"
            cache.mkdir()
            here = Path(directory) / "here" / "HANDOFF.md"
            there = Path(directory) / "there" / "HANDOFF.md"
            here.parent.mkdir(parents=True)
            there.parent.mkdir(parents=True)
            (cache / "remote").write_text(
                f"Remote Agent\nCodex\n{there.resolve()}\n", encoding="utf-8")
            with patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(cache)}):
                rows = tui.agent_rows(tui.parse_snapshot(text).tasks, here)
        self.assertEqual([owner for owner, _ in rows], ["Agent A"])

    def test_repo_scope_excludes_a_claim_that_names_no_ledger(self):
        # A released helper writes "name\nharness\n" with no ledger line; such a
        # session working in another repository was listed in this one.
        text = entry("First", owner="Agent A")
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "names"
            cache.mkdir()
            here = Path(directory) / "here" / "HANDOFF.md"
            here.parent.mkdir(parents=True)
            here.write_text(text, encoding="utf-8")
            (cache / "elsewhere").write_text("Barong 2\nClaude Code\n", encoding="utf-8")
            with patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(cache)}):
                rows = tui.agent_rows(tui.parse_snapshot(text).tasks, here)
                watcher = tui.Watcher(here)
                watcher.poll()
                report = tui.plain_report(watcher)
                machine = tui.machine_agent_rows(here)
        self.assertEqual([owner for owner, _ in rows], ["Agent A"])
        self.assertNotIn("Barong 2", report)
        self.assertEqual([name for name, _ in machine], ["Barong 2"])

    def test_machine_agent_rows_list_every_recent_claim(self):
        claims = [
            guard.NameClaim("Beta", "Cursor", "/tmp/b/HANDOFF.md"),
            guard.NameClaim("Alpha", "Codex", "/tmp/a/HANDOFF.md"),
        ]
        with patch.object(tui, "recent_claims", return_value=claims):
            rows = tui.machine_agent_rows(Path("/tmp/a/HANDOFF.md"))
        self.assertEqual([name for name, _ in rows], ["Beta", "Alpha"])

    def test_repo_display_label_marks_the_current_ledger(self):
        ledger = Path("/tmp/handoff-skill/HANDOFF.md")
        self.assertEqual(tui.repo_display_label(str(ledger.resolve()), ledger), "here")
        self.assertEqual(tui.repo_display_label("/tmp/other/HANDOFF.md", ledger), "other")

    def test_plain_report_can_list_machine_wide_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            watcher = tui.Watcher(path)
            watcher.poll()
            claims = [guard.NameClaim("Alpha", "Codex", str(path.resolve()))]
            with patch.object(tui, "recent_claims", return_value=claims):
                report = tui.plain_report(watcher, agent_scope="machine")
            self.assertIn("AGENTS ON THIS MACHINE", report)
            self.assertIn("Alpha", report)
            self.assertIn("here", report)

    def test_owner_row_keeps_every_count_visible_when_a_harness_is_shown(self):
        counts = tui.Counts(tracked=2, completed=1, in_progress=1, checked=3, steps=4)
        plain = tui.owner_row("Zeta", counts, 110)
        with_harness = tui.owner_row("Zeta", counts, 110, "Claude Code")
        self.assertIn("Claude Code", with_harness)
        self.assertNotIn("Claude Code", plain)
        for line in (plain, with_harness):
            self.assertIn("1/2", line)
            self.assertIn("3/4", line)
        self.assertEqual(len(plain), len(with_harness))

    def test_terminal_text_is_sanitized_and_wide_names_fit(self):
        self.assertNotIn("\x1b", tui.clean_text("Agent\x1b[2J\x00"))
        self.assertNotIn("\u202e", tui.clean_text("Agent\u202e"))
        self.assertEqual(tui.fit("代理人abc", 5), "代理")
        self.assertEqual(tui.fit("代理人abc", 5, pad=True), "代理 ")


class WatcherTests(unittest.TestCase):
    def test_atomic_replacement_changes_snapshot_without_writing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            watcher = tui.Watcher(path)
            watcher.poll()
            first = watcher.snapshot.version
            replacement = path.with_suffix(".tmp")
            final = entry(state="completed", steps=(True, True))
            replacement.write_text(final, encoding="utf-8")
            replacement.replace(path)
            watcher.poll()
            self.assertNotEqual(watcher.snapshot.version, first)
            self.assertEqual(tui.count_tasks(watcher.snapshot.tasks).completed, 1)
            self.assertEqual(path.read_text(), final)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_missing_and_invalid_utf8_retain_last_readable_snapshot_and_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            watcher = tui.Watcher(path)
            watcher.poll()
            self.assertIsNone(watcher.snapshot)
            self.assertIsNotNone(watcher.error)
            path.write_text(entry(), encoding="utf-8")
            watcher.poll()
            first = watcher.snapshot
            path.unlink()
            watcher.poll()
            self.assertIs(watcher.snapshot, first)
            self.assertIn("stale", tui.plain_report(watcher))
            path.write_bytes(b"\xff")
            watcher.poll()
            self.assertIs(watcher.snapshot, first)
            self.assertIsNotNone(watcher.error)
            path.write_text(entry("Recovered"), encoding="utf-8")
            watcher.poll()
            self.assertIsNone(watcher.error)
            self.assertIn("Recovered", watcher.snapshot.tasks[0].heading)


class ChannelViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "HANDOFF.md"
        self.path.write_text(entry(), encoding="utf-8")
        self.channel = tui.Channel(self.root)
        watcher = tui.Watcher(self.path)
        watcher.poll()
        self.dashboard = tui.Dashboard(watcher, read_only=True)

    def press(self, *keys):
        for key in keys:
            self.dashboard.handle_key(key, FakeCurses, 5)

    def actors(self):
        a = self.channel.join("Alpha", "Codex")["session"]
        b = self.channel.join("Beta", "Claude Code")["session"]
        return a, b

    def test_empty_channel_is_visible_without_creating_local_state(self):
        self.press(ord("c"))
        screen = Screen()
        self.dashboard.draw(screen, FakeCurses)
        self.assertIn("[Channel]", screen.frames[-1])
        self.assertIn("No channel messages", screen.frames[-1])
        self.assertFalse((self.root / ".handoff").exists())

    def test_broadcast_rendering_details_and_reads_preserve_receipts_and_ledger(self):
        a, b = self.actors()
        self.channel.send(a, "*", "First line\nSecond line with 中文 and \x1b controls", "broadcast")
        before = self.channel.path.read_bytes(), self.path.read_bytes()
        self.press(ord("c"))
        screen = Screen()
        self.dashboard.draw(screen, FakeCurses)
        self.assertIn("Alpha -> all agents", screen.frames[-1])
        self.assertIn("0 ack", screen.frames[-1])
        self.press(10)
        self.assertIn("Second line", " ".join(self.dashboard.channel_detail_lines(80)))
        self.assertNotIn("\x1b", " ".join(self.dashboard.channel_detail_lines(80)))
        self.press(ord("G"))
        for height, width in ((14, 64), (24, 80), (40, 150)):
            self.dashboard.draw(Screen(height, width), FakeCurses)
        self.assertEqual((self.channel.path.read_bytes(), self.path.read_bytes()), before)
        self.assertEqual(len(self.channel.inbox(b)), 1)

    def test_refresh_keeps_message_selection_and_updates_acknowledgements(self):
        a, b = self.actors()
        self.channel.send(a, b, "First", "first")
        self.press(ord("c"), 10)
        self.channel.send(b, a, "Second", "second")
        self.channel.acknowledge(b, "first")
        self.dashboard.refresh()
        self.assertEqual(self.dashboard.rows()[self.dashboard.selected][0], "first")
        self.assertEqual(self.dashboard.channel_detail["acknowledged_by"], [b])
        self.assertIn("Acknowledged by: Beta", self.dashboard.channel_detail_lines(80))

    def test_session_selection_filters_messages_and_back_restores_sessions(self):
        a, b = self.actors()
        c = self.channel.join("Gamma", "Other")["session"]
        self.channel.send(a, b, "Direct", "direct")
        self.channel.send(a, "*", "Broadcast", "broadcast")
        self.press(ord("c"), ord("s"))
        self.dashboard.selected = next(i for i, row in enumerate(self.dashboard.rows()) if row[0] == c)
        self.assertEqual(self.dashboard.selected_session()["id"], c)
        self.press(10)
        self.assertEqual([row[0] for row in self.dashboard.rows()], ["broadcast"])
        self.assertEqual(self.dashboard.selected_session()["id"], c)
        self.press(ord("b"))
        self.assertEqual(self.dashboard.channel_mode, "sessions")
        self.assertIsNone(self.dashboard.channel_session)
        self.press(ord("s"), ord("t"))
        self.assertEqual(self.dashboard.view, "tasks")

    def test_failed_read_keeps_last_snapshot_and_recovers(self):
        a, b = self.actors()
        self.channel.send(a, b, "Saved", "saved")
        self.press(ord("c"))
        with patch.object(self.dashboard.channel, "history", side_effect=OSError("temporarily unreadable")):
            self.dashboard.refresh()
        screen = Screen()
        self.dashboard.draw(screen, FakeCurses)
        self.assertIn("STALE CHANNEL", screen.frames[-1])
        self.assertIn("Saved", screen.frames[-1])
        self.dashboard.refresh()
        self.assertIsNone(self.dashboard.channel_error)


class ChannelAbsentTests(unittest.TestCase):
    """The viewer must start where handoff_channel.py is not installed beside it.

    The bar resolves a viewer out of plugin caches and runs on every status-line
    tick, so a module-level channel import turned a missing module into a viewer
    that printed nothing at all. Degrade the one view instead.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.path = root / "HANDOFF.md"
        self.path.write_text(entry(), encoding="utf-8")
        self.original = tui.Channel
        tui.Channel = None
        self.addCleanup(setattr, tui, "Channel", self.original)
        watcher = tui.Watcher(self.path)
        watcher.poll()
        self.dashboard = tui.Dashboard(watcher, read_only=True)

    def test_the_dashboard_builds_without_a_channel(self):
        self.assertIsNone(self.dashboard.channel)
        self.assertIn("not installed", self.dashboard.channel_error)

    def test_the_channel_view_refreshes_empty_rather_than_raising(self):
        self.dashboard.view = "channel"
        self.dashboard.refresh()
        self.assertEqual(self.dashboard.channel_data,
                         {"sessions": [], "messages": [], "truncated": False})
        self.assertIn("not installed", self.dashboard.channel_error)

    def test_task_progress_still_reports(self):
        self.dashboard.refresh()
        self.assertTrue(self.dashboard.rows())


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.recent_patch = patch.object(tui, "recent_claims", return_value=[])
        self.recent_patch.start()
        self.addCleanup(self.recent_patch.stop)
        self.recent_ledger_patch = patch.object(tui, "recent_claims_for_ledger", return_value=[])
        self.recent_ledger_patch.start()
        self.addCleanup(self.recent_ledger_patch.stop)

    def dashboard(self):
        watcher = tui.Watcher(Path("unused"))
        watcher.snapshot = tui.parse_snapshot(entry("First") + entry("Second", owner="Agent B"))
        return tui.Dashboard(watcher)

    def test_back_from_owner_task_list_returns_to_agents_view(self):
        dashboard = self.dashboard()
        dashboard.handle_key(FakeCurses.KEY_DOWN, FakeCurses, 5)
        dashboard.handle_key(10, FakeCurses, 5)
        self.assertEqual((dashboard.view, dashboard.owner), ("tasks", "Agent B"))
        dashboard.handle_key(ord("b"), FakeCurses, 5)
        self.assertEqual(dashboard.view, "agents")
        self.assertIsNone(dashboard.owner)
        self.assertEqual(dashboard.rows()[dashboard.selected][0], "Agent B")

    def test_owner_drilldown_task_details_back_and_view_switch(self):
        dashboard = self.dashboard()
        dashboard.handle_key(FakeCurses.KEY_DOWN, FakeCurses, 5)
        dashboard.handle_key(10, FakeCurses, 5)
        self.assertEqual(dashboard.owner, "Agent B")
        self.assertEqual(len(dashboard.tasks()), 1)
        dashboard.handle_key(10, FakeCurses, 5)
        self.assertIn("Second", dashboard.detail.heading)
        self.assertIn("Continuation and next action.", " ".join(dashboard.detail_lines(80)))
        dashboard.handle_key(ord("b"), FakeCurses, 5)
        self.assertIsNone(dashboard.detail)
        dashboard.handle_key(ord("b"), FakeCurses, 5)
        self.assertIsNone(dashboard.owner)
        self.assertEqual(dashboard.view, "agents")
        self.assertEqual(dashboard.rows()[dashboard.selected][0], "Agent B")
        self.assertFalse(dashboard.handle_key(ord("q"), FakeCurses, 5))

    def test_vim_gg_and_g_shift_jump_to_the_ends(self):
        dashboard = self.dashboard()
        dashboard.view = "tasks"
        last = len(dashboard.rows()) - 1
        dashboard.handle_key(ord("G"), FakeCurses, 5)
        self.assertEqual(dashboard.selected, last)
        # One g arms the pair and moves nothing; idle polls must not disarm it.
        dashboard.handle_key(ord("g"), FakeCurses, 5)
        dashboard.handle_key(-1, FakeCurses, 5)
        self.assertEqual(dashboard.selected, last)
        dashboard.handle_key(ord("g"), FakeCurses, 5)
        self.assertEqual(dashboard.selected, 0)

    def test_a_lone_g_does_not_arm_the_next_keypress(self):
        dashboard = self.dashboard()
        dashboard.view = "tasks"
        dashboard.handle_key(ord("G"), FakeCurses, 5)
        dashboard.handle_key(ord("g"), FakeCurses, 5)
        dashboard.handle_key(ord("k"), FakeCurses, 5)
        dashboard.handle_key(ord("g"), FakeCurses, 5)
        self.assertEqual(dashboard.selected, 0)

    def test_gg_and_g_shift_scroll_the_detail_view(self):
        dashboard = self.dashboard()
        dashboard.handle_key(10, FakeCurses, 5)
        dashboard.handle_key(10, FakeCurses, 5)
        self.assertIsNotNone(dashboard.detail)
        dashboard.handle_key(ord("G"), FakeCurses, 5)
        self.assertEqual(dashboard.detail_offset, sys.maxsize)
        dashboard.handle_key(ord("g"), FakeCurses, 5)
        dashboard.handle_key(ord("g"), FakeCurses, 5)
        self.assertEqual(dashboard.detail_offset, 0)

    def test_new_entry_does_not_move_selection_to_another_task(self):
        dashboard = self.dashboard()
        dashboard.view = "tasks"
        dashboard.selected = 1
        dashboard.detail = dashboard.tasks()[1]
        with patch.object(dashboard.watcher, "poll") as poll:
            poll.side_effect = lambda: setattr(dashboard.watcher, "snapshot", tui.parse_snapshot(
                entry("New") + entry("First") + entry("Second", owner="Agent B", state="completed", steps=(True, True))))
            dashboard.refresh()
        self.assertEqual(dashboard.selected, 2)
        self.assertEqual(dashboard.detail.state, "completed")

    def test_machine_scope_draws_without_crashing(self):
        """Pressing m must not raise when rendering machine-wide agent rows."""
        dashboard = self.dashboard()
        dashboard.watcher.path = Path("/tmp/handoff-skill/HANDOFF.md")
        claim = guard.NameClaim("Waiting", "Codex", str(dashboard.watcher.path))
        with patch.object(tui, "recent_claims", return_value=[claim]):
            dashboard.handle_key(ord("m"), FakeCurses, 10)
            self.assertEqual(dashboard.agent_scope, "machine")
            screen = Screen(24, 100)
            dashboard.draw(screen, FakeCurses)
        self.assertIn("REPOSITORY", screen.frames[-1])
        self.assertIn("Waiting", screen.frames[-1])

    def test_draw_handles_resize_long_names_and_scrolled_details(self):
        dashboard = self.dashboard()
        for height, width in ((1, 1), (8, 30), (14, 64), (24, 80), (40, 150)):
            dashboard.draw(Screen(height, width), FakeCurses)
        dashboard.handle_key(10, FakeCurses, 5)
        dashboard.handle_key(10, FakeCurses, 5)
        dashboard.handle_key(FakeCurses.KEY_END, FakeCurses, 5)
        screen = Screen(14, 64)
        dashboard.draw(screen, FakeCurses)
        self.assertIn("TASK DETAILS", screen.frames[-1])
        self.assertLess(dashboard.detail_offset, sys.maxsize)

    def test_live_loop_refreshes_after_elapsed_interval_without_keyboard_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            watcher = tui.Watcher(path)
            screen = Screen()
            calls = 0

            def getch():
                nonlocal calls
                calls += 1
                if calls == 1:
                    path.write_text(entry(state="completed", steps=(True, True)), encoding="utf-8")
                    return -1
                return ord("q")

            screen.getch = getch
            curses = SimpleNamespace(**{k: v for k, v in vars(FakeCurses).items() if not k.startswith("__")})
            curses.curs_set = lambda value: None
            curses.wrapper = lambda callback: callback(screen)
            with patch.dict(sys.modules, {"curses": curses}), patch.object(tui.time, "monotonic", side_effect=range(20)):
                self.assertEqual(tui.run_live(watcher, 0.1), 0)
            self.assertIn("0/1 completed", screen.frames[0])
            self.assertIn("1/1 completed", screen.frames[-1])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "handoff_tui.py"), *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=5)

    def test_pipe_falls_back_to_snapshot_and_explicit_lowercase_file_works(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.md"
            path.write_text(entry(owner="代理人 Agent A"), encoding="utf-8")
            result = self.run_cli("--file", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("50% 1/2", result.stdout)
            self.assertIn("代理人 Agent A", result.stdout)
            self.assertNotIn("\x1b", result.stdout)

    def test_root_from_nested_directory_and_missing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            child = root / "nested"
            child.mkdir()
            result = self.run_cli("--once", "--root", str(child))
            self.assertEqual(result.returncode, 1)
            self.assertIn("READ ERROR", result.stdout)
            (root / "HANDOFF.md").write_text(entry(), encoding="utf-8")
            result = self.run_cli("--once", "--root", str(child))
            self.assertEqual(result.returncode, 0, result.stderr)
            # Windows temp paths can come back in 8.3 short form, so compare resolved.
            self.assertIn(str((root / "HANDOFF.md").resolve()), result.stdout)

    def test_invalid_structure_is_visible_and_returns_failure_in_snapshot_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(state="completed"), encoding="utf-8")
            result = self.run_cli("--once", "--file", str(path))
            self.assertEqual(result.returncode, 1)
            self.assertIn("1 invalid", result.stdout)
            self.assertIn("completed task has unchecked steps", result.stdout)

    def test_bad_intervals_fail_before_starting_terminal(self):
        for interval in ("0", "-1", "nan", "inf", "61", "abc"):
            with self.subTest(interval=interval):
                result = self.run_cli("--interval", interval)
                self.assertEqual(result.returncode, 2)
                self.assertIn("interval must be", result.stderr)


if __name__ == "__main__":
    unittest.main()


class BarTests(unittest.TestCase):
    def snapshot(self, text):
        return tui.parse_snapshot(text)

    def test_empty_when_nothing_is_tracked(self):
        self.assertEqual(tui.bar_line(self.snapshot("# Handoff\n")), "")
        self.assertEqual(tui.bar_line(None), "")

    def test_counts_appear_without_a_session_name(self):
        text = "# Handoff\n\n" + entry(title="A", owner="Ann", state="completed", steps=(True, True))
        text += entry(title="B", owner="Bo", state="in_progress", steps=(True, False))
        line = tui.bar_line(self.snapshot(text), color=False)
        self.assertIn("1/2 tasks", line)
        self.assertIn("3/4 steps", line)
        self.assertNotIn("Bo", line)
        self.assertNotIn("Ann", line)

    def test_session_name_trails_the_row(self):
        text = "# Handoff\n\n" + entry(title="A", owner="Ann", steps=(True, False))
        line = tui.bar_line(self.snapshot(text), color=False, session_name="Janus")
        self.assertTrue(line.endswith(" Janus"), line)
        self.assertNotIn("Ann", line)

    def test_no_color_omits_escape_codes(self):
        text = "# Handoff\n\n" + entry(steps=(True, False))
        self.assertNotIn("\033", tui.bar_line(self.snapshot(text), color=False))
        self.assertIn("\033", tui.bar_line(self.snapshot(text), color=True))

    def test_fully_complete_reads_green(self):
        text = "# Handoff\n\n" + entry(state="completed", steps=(True, True))
        self.assertIn("\033[32m", tui.bar_line(self.snapshot(text)))

    def test_bar_is_one_line(self):
        text = "# Handoff\n\n" + entry(title="A\nB", owner="Ann", steps=(True, False))
        self.assertNotIn("\n", tui.bar_line(self.snapshot(text), color=False))


class BarSessionNameTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        self.ledger = (self.base / "HANDOFF.md").resolve()
        self.ledger.write_text("# Handoff\n\n" + entry(owner="Other"), encoding="utf-8")
        self.cache = self.base / "names"
        self.bar_cache = self.base / "bar-cache"
        self.env = patch.dict(os.environ, {
            "HANDOFF_NAME_CACHE": str(self.cache),
            "HANDOFF_BAR_CACHE": str(self.bar_cache),
            "HANDOFF_SESSION": "",
            "CLAUDE_CODE_SESSION_ID": "",
            "TERM_SESSION_ID": "",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.dir.cleanup)

    def test_recall_from_payload_session_id(self):
        seed = "host-session-bar-tests-1"
        guard.claim_name(seed, self.ledger, set())
        payload = json.dumps({"session_id": seed, "cwd": str(self.base)})
        self.assertEqual(tui.bar_session_name(self.ledger, payload),
                         guard.recall_name(seed, self.ledger))

    def test_bar_cache_session_key_differs_by_session(self):
        one = json.dumps({"session_id": "session-alpha", "cwd": "/repo"})
        two = json.dumps({"session_id": "session-beta", "cwd": "/repo"})
        self.assertNotEqual(tui.bar_cache_session_key(one), tui.bar_cache_session_key(two))
        self.assertEqual(tui.bar_cache_session_key(None), "no-session")

    def test_bar_cli_prints_the_claimed_session(self):
        seed = "bar-cli-session-tests-1"
        claimed = guard.claim_name(seed, self.ledger, set())[0]
        payload = json.dumps({"session_id": seed, "cwd": str(self.base)})
        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "handoff_tui.py"), "--bar",
             "--file", str(self.ledger)],
            input=payload, capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(claimed, result.stdout)
        self.assertNotIn("Other", result.stdout)


class EncodingTests(unittest.TestCase):
    """Windows consoles default to a legacy codepage; encoding errors crashed the bar."""

    def test_ascii_fallback_avoids_block_characters(self):
        text = "# Handoff\n\n" + entry(state="completed", steps=(True, True))
        line = tui.bar_line(tui.parse_snapshot(text), color=False, blocks=False)
        line.encode("ascii")
        self.assertIn("#", line)
        self.assertNotIn("\u2588", line)

    def test_block_glyphs_are_used_when_the_encoding_allows(self):
        text = "# Handoff\n\n" + entry(state="completed", steps=(True, True))
        self.assertIn("\u2588", tui.bar_line(tui.parse_snapshot(text), color=False, blocks=True))

    def test_stdout_encodes_reports_what_the_stream_supports(self):
        self.assertTrue(tui.stdout_encodes("plain"))
        with patch.object(tui.sys, "stdout", SimpleNamespace(encoding="cp1252")):
            self.assertFalse(tui.stdout_encodes("\u2588\u2591"))
            self.assertTrue(tui.stdout_encodes("plain"))
        with patch.object(tui.sys, "stdout", SimpleNamespace(encoding="utf-8")):
            self.assertTrue(tui.stdout_encodes("\u2588\u2591"))

    def test_legacy_codepage_does_not_crash_the_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "HANDOFF.md"
            ledger.write_text("# Handoff\n\n" + entry(owner="\u5e73\u4e95"), encoding="utf-8")
            for mode in ("--once", "--bar"):
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / "handoff_tui.py"), mode, "--file", str(ledger)],
                    capture_output=True, text=True, encoding="utf-8",
                    env={**os.environ, "PYTHONIOENCODING": "cp1252"},
                )
                self.assertEqual(result.returncode, 0, (mode, result.stderr))


class StatusLineRootTests(unittest.TestCase):
    def test_workspace_directory_is_preferred(self):
        payload = '{"cwd": "/fallback", "workspace": {"current_dir": "/chosen"}}'
        self.assertEqual(tui.status_line_root(payload), Path("/chosen"))

    def test_cwd_is_the_fallback(self):
        self.assertEqual(tui.status_line_root('{"cwd": "/only"}'), Path("/only"))

    def test_unusable_payloads_return_none(self):
        for payload in ("", "not json", "[]", "{}", '{"cwd": 4}', '{"workspace": null}'):
            self.assertIsNone(tui.status_line_root(payload), payload)


class MoveTests(unittest.TestCase):
    """Handing a task to another agent is a ledger write, so each case checks the
    file on disk, not only the view."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "HANDOFF.md"
        self.write(entry("First") + entry("Second", owner="Agent B"))

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def read(self):
        return self.path.read_text(encoding="utf-8")

    def dashboard(self, read_only=False):
        watcher = tui.Watcher(self.path)
        watcher.poll()
        dashboard = tui.Dashboard(watcher, read_only=read_only)
        dashboard.view = "tasks"
        return dashboard

    def press(self, dashboard, *keys):
        for key in keys:
            dashboard.handle_key(key, FakeCurses, 5)
        return dashboard

    def owners(self):
        return [task.owner for task in tui.parse_tasks(self.read())]

    def test_cut_and_paste_hands_one_task_to_the_agent_selected_in_agents_view(self):
        dashboard = self.press(self.dashboard(), ord("x"), ord("a"))
        self.assertIsNotNone(dashboard.cut)
        dashboard.selected = [row[0] for row in dashboard.rows()].index("Agent B")
        self.press(dashboard, ord("p"))
        self.assertEqual(self.owners(), ["Agent B", "Agent B"])
        self.assertIsNone(dashboard.cut)
        self.assertIn("Agent B", dashboard.banner())

    def test_cut_and_paste_hands_one_task_to_a_waiting_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            cache.mkdir()
            (cache / "waiting").write_text(
                f"Waiting Agent\nCursor\n{self.path.resolve()}\n", encoding="utf-8")
            with patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(cache)}):
                dashboard = self.press(self.dashboard(), ord("x"), ord("a"))
                dashboard.selected = [row[0] for row in dashboard.rows()].index("Waiting Agent")
                self.press(dashboard, ord("p"))
        self.assertEqual(self.owners(), ["Waiting Agent", "Agent B"])
        self.assertIn("Waiting Agent must", self.read())

    def test_launching_an_agent_records_session_intake_in_the_ledger(self):
        dashboard = self.dashboard()
        dashboard.view = "spawn"
        dashboard.selected = 0
        with patch.object(tui, "recent_claims_for_ledger", return_value=[]):
            with patch.object(tui, "available_agents", return_value=["cursor-agent"]):
                with patch.object(tui, "seed_claim", return_value="Atalanta"):
                    with patch.object(tui, "open_agent", return_value=(0, "Opened.", "Atalanta")):
                        self.press(dashboard, 10, 10)
            task = tui.parse_tasks(self.read())[0]
            self.assertEqual(task.owner, "Atalanta")
            self.assertEqual(task.state, "in_progress")
            rows = tui.agent_rows(tui.parse_tasks(self.read()), self.path)
            self.assertEqual(rows[0][0], "Atalanta")
            self.assertEqual((rows[0][1].tracked, rows[0][1].in_progress), (1, 1))

    def test_spawn_prompt_records_a_user_task_and_passes_it_to_the_agent(self):
        dashboard = self.dashboard()
        dashboard.view = "spawn"
        dashboard.selected = 0
        with patch.object(tui, "available_agents", return_value=["cursor-agent"]):
            with patch.object(tui, "seed_claim", return_value="Atalanta"):
                with patch.object(tui, "open_agent", return_value=(0, "Opened.", "Atalanta")) as opened:
                    self.press(dashboard, 10, *map(ord, "Add login page"), 10)
        task = tui.parse_tasks(self.read())[0]
        self.assertIn("Add login page", task.heading)
        self.assertIn("Add login page", self.read())
        self.assertIn("Execution request: Atalanta must", self.read())
        opened.assert_called_once()
        self.assertEqual(opened.call_args.kwargs["task"], "Add login page")

    def test_spawn_prompt_allows_an_empty_task(self):
        dashboard = self.dashboard()
        dashboard.view = "spawn"
        dashboard.selected = 0
        with patch.object(tui, "available_agents", return_value=["cursor-agent"]):
            with patch.object(tui, "seed_claim", return_value="Atalanta"):
                with patch.object(tui, "open_agent", return_value=(0, "Opened.", "Atalanta")) as opened:
                    self.press(dashboard, 10, 10)
        task = tui.parse_tasks(self.read())[0]
        self.assertIn("Session work", task.heading)
        self.assertEqual(task.owner, "Atalanta")
        opened.assert_called_once()
        self.assertIsNone(opened.call_args.kwargs["task"])

    def test_spawned_agent_shows_task_counts_after_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            cache.mkdir()
            with patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(cache)}):
                name = guard.seed_claim("spawn-seed", self.path, "cursor-agent")
                rows_before = tui.agent_rows(tui.parse_tasks(self.read()), self.path)
                self.assertEqual(rows_before[0], (name, tui.Counts()))
                dashboard = self.press(self.dashboard(), ord("x"), ord("a"))
                dashboard.selected = [row[0] for row in dashboard.rows()].index(name)
                self.press(dashboard, ord("p"))
                rows_after = tui.agent_rows(tui.parse_tasks(self.read()), self.path)
        self.assertEqual([owner for owner, _ in rows_after], [name, "Agent B"])
        counts = rows_after[0][1]
        self.assertEqual((counts.tracked, counts.in_progress, counts.steps),
                         (1, 1, 2))

    def test_a_move_checks_in_progress_without_changing_steps(self):
        before = tui.parse_tasks(self.read())[0]
        self.press(self.dashboard(), ord("x"), ord("a"))
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        dashboard.selected = 1
        self.press(dashboard, ord("p"))
        after = tui.parse_tasks(self.read())[0]
        self.assertEqual(after.owner, "Agent B")
        self.assertEqual(after.line, before.line)
        self.assertEqual(after.steps, before.steps)
        self.assertEqual(after.state, "in_progress")
        self.assertEqual(tui.parse_tasks(self.read())[1].owner, "Agent B")
        self.assertEqual(guard.structure_findings(self.read()), [])

    def test_the_move_is_recorded_in_the_status_the_new_owner_reads(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        dashboard.selected = 1
        self.press(dashboard, ord("p"))
        status = tui.parse_snapshot(self.read()).statuses[0]
        self.assertIn("Recorded status.", status)
        self.assertIn("moved from Agent A to Agent B", status)
        self.assertNotIn("Reassigned", tui.parse_snapshot(self.read()).statuses[1])

    def test_pasting_onto_unassigned_clears_the_owner_label(self):
        self.write(entry("First") + entry("Second", owner=None))
        dashboard = self.press(self.dashboard(), ord("x"), ord("a"))
        dashboard.selected = [row[0] for row in dashboard.rows()].index("unassigned")
        self.press(dashboard, ord("p"))
        self.assertEqual(self.owners(), [None, None])
        self.assertNotIn("(owner:", self.read())

    def test_assignment_requires_execution_after_current_task_without_another_prompt(self):
        dashboard = self.press(self.dashboard(), ord("x"))
        dashboard.selected = 1
        self.press(dashboard, ord("p"))
        status = " ".join(tui.parse_snapshot(self.read()).statuses[0].split())
        self.assertIn("Agent B must finish its current task, then audit and complete this task", status)
        self.assertIn("without waiting for another user prompt", status)
        self.assertIn("verification", status)

    def test_reassigning_completed_work_does_not_request_execution_again(self):
        task = tui.parse_tasks(entry(state="completed", steps=(True, True)))[0]
        self.assertNotIn("must finish", tui.move_note(task, "Agent B"))

    def test_releasing_work_does_not_request_execution_by_unassigned(self):
        task = tui.parse_tasks(entry())[0]
        self.assertNotIn("must finish", tui.move_note(task, tui.UNASSIGNED))

    def test_a_typed_name_reaches_an_agent_with_no_ledger_entry_yet(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"), ord("P"))
        self.press(dashboard, *[ord(character) for character in "Agent C"])
        self.assertEqual(dashboard.prompt, "Agent C")
        self.press(dashboard, FakeCurses.KEY_BACKSPACE, ord("D"), 10)
        self.assertEqual(self.owners(), ["Agent D", "Agent B"])
        self.assertIsNone(dashboard.prompt)

    def test_the_prompt_swallows_keys_that_would_otherwise_quit_or_navigate(self):
        dashboard = self.press(self.dashboard(), ord("x"), ord("P"))
        self.assertTrue(dashboard.handle_key(ord("q"), FakeCurses, 5))
        self.assertTrue(dashboard.handle_key(ord("b"), FakeCurses, 5))
        self.assertEqual(dashboard.prompt, "qb")
        self.press(dashboard, 27)
        self.assertIsNone(dashboard.prompt)
        self.assertIsNotNone(dashboard.cut)
        self.assertEqual(self.owners(), ["Agent A", "Agent B"])

    def test_a_name_no_heading_can_carry_is_refused_without_writing(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"), ord("P"))
        self.press(dashboard, *[ord(character) for character in "A (b)"], 10)
        self.assertEqual(self.owners(), ["Agent A", "Agent B"])
        self.assertIn("Nothing was moved", dashboard.banner())

    def test_a_peer_write_after_the_cut_moves_nothing(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        peer = entry("First") + entry("Second", owner="Agent B") + entry("Third", owner="Agent C")
        self.write(peer)
        dashboard.selected = 1
        self.press(dashboard, ord("p"))
        self.assertEqual(self.read(), peer)
        self.assertIsNone(dashboard.cut)
        self.assertIn("ledger changed", dashboard.banner())

    def test_a_task_a_peer_removed_is_dropped_instead_of_moved(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        self.write(entry("Second", owner="Agent B"))
        dashboard.refresh()
        self.assertIsNone(dashboard.cut)
        self.assertIn("no longer in the ledger", dashboard.banner())

    def test_read_only_mode_never_writes(self):
        dashboard = self.dashboard(read_only=True)
        self.press(dashboard, ord("x"))
        self.assertIsNone(dashboard.cut)
        dashboard.selected = 1
        self.press(dashboard, ord("p"), ord("P"))
        self.assertEqual(self.owners(), ["Agent A", "Agent B"])
        self.assertIsNone(dashboard.prompt)
        self.assertIn("read-only", dashboard.banner())

    def test_paste_without_a_cut_and_cut_without_a_task_write_nothing(self):
        dashboard = self.dashboard()
        dashboard.selected = 1
        self.press(dashboard, ord("p"))
        self.assertIn("Nothing is held", dashboard.banner())
        self.press(dashboard, ord("a"), ord("x"))
        self.assertIn("select a task", dashboard.banner())
        self.assertEqual(self.owners(), ["Agent A", "Agent B"])

    def test_cutting_the_same_task_twice_releases_it(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"), ord("X"))
        self.assertIsNone(dashboard.cut)
        self.press(dashboard, ord("p"))
        self.assertEqual(self.owners(), ["Agent A", "Agent B"])

    def test_pasting_a_task_onto_its_own_owner_writes_nothing(self):
        version = tui.ledger_version(self.read())
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"), ord("p"))
        self.assertEqual(tui.ledger_version(self.read()), version)
        self.assertIn("already recorded", dashboard.banner())
        self.assertIsNone(dashboard.cut)

    def test_a_missing_ledger_reports_instead_of_creating_one(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        self.path.unlink()
        dashboard.selected = 1
        self.press(dashboard, ord("p"))
        self.assertFalse(self.path.exists())
        self.assertIn("no ledger", dashboard.banner())

    def test_an_owners_task_list_pastes_to_that_owner(self):
        self.write(entry("First") + entry("Second", owner="Agent B") + entry("Third", owner="Agent B"))
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        dashboard.view, dashboard.owner, dashboard.selected = "tasks", "Agent B", 0
        self.press(dashboard, ord("p"))
        self.assertEqual(self.owners(), ["Agent B", "Agent B", "Agent B"])

    def test_a_task_open_in_details_can_be_cut(self):
        dashboard = self.dashboard()
        self.press(dashboard, 10)
        self.assertIsNotNone(dashboard.detail)
        self.press(dashboard, ord("x"))
        self.assertEqual(dashboard.cut.heading, dashboard.detail.heading)

    def test_the_held_task_and_the_pending_move_are_visible_on_screen(self):
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        screen = Screen(24, 100)
        dashboard.draw(screen, FakeCurses)
        frame = screen.frames[-1]
        self.assertIn("*", frame.splitlines()[7][:1])
        self.assertIn("Cut 'First'", frame)
        self.press(dashboard, FakeCurses.KEY_DOWN)
        dashboard.draw(screen, FakeCurses)
        self.assertIn("HOLDING 'First' from Agent A", screen.frames[-1])
        self.assertIn("x cut", frame)
        self.assertNotIn("x cut", self.dashboard(read_only=True).banner())


class StepMoveTests(unittest.TestCase):
    """Details showed two checkboxes, but x silently selected their whole task."""

    setUp = MoveTests.setUp
    write = MoveTests.write
    read = MoveTests.read
    dashboard = MoveTests.dashboard
    press = MoveTests.press

    def test_select_second_step_and_paste_inside_another_owners_list(self):
        before = tui.count_tasks(tui.parse_tasks(self.read()))
        dashboard = self.press(self.dashboard(), 10, ord("j"), ord("x"), ord("a"))
        dashboard.selected = [row[0] for row in dashboard.rows()].index("Agent B")
        self.press(dashboard, 10, ord("p"))
        tasks = tui.parse_tasks(self.read())
        moved, source, other = tasks
        self.assertEqual((moved.owner, moved.steps, moved.state),
                         ("Agent B", [(False, "Outcome 1.")], "in_progress"))
        self.assertEqual((source.owner, source.steps, source.state),
                         ("Agent A", [(True, "Outcome 0.")], "in_progress"))
        self.assertEqual(other.steps, [(True, "Outcome 0."), (False, "Outcome 1.")])
        self.assertIn("Recorded status.", source.status)
        self.assertIn("Source task: First (owner: Agent A)", moved.status)
        self.assertIn("Agent B must finish its current task", moved.status)
        self.assertIn("> - [ ] Outcome 1.", self.read())
        self.assertEqual(guard.structure_findings(self.read()), [])
        after = tui.count_tasks(tasks)
        self.assertEqual((before.checked, before.steps), (after.checked, after.steps))
        self.assertEqual((dashboard.view, dashboard.owner), ("tasks", "Agent B"))
        self.assertEqual(dashboard.selected_task().heading, moved.heading)
        self.assertIsNone(dashboard.cut)

    def test_checked_step_keeps_its_recorded_completion(self):
        dashboard = self.press(self.dashboard(), 10, ord("x"), ord("P"))
        self.press(dashboard, *map(ord, "Agent C"), 10)
        moved, source, _ = tui.parse_tasks(self.read())
        self.assertEqual((moved.steps, moved.state), ([(True, "Outcome 0.")], "completed"))
        self.assertEqual(source.steps, [(False, "Outcome 1.")])
        self.assertNotIn("Execution request", moved.status)

    def test_x_marks_only_selected_step_and_uppercase_x_holds_whole_task(self):
        dashboard = self.press(self.dashboard(), 10, ord("j"), ord("x"))
        frame = "\n".join(dashboard.detail_lines(100))
        self.assertIn("* [ ] Outcome 1.", frame)
        self.assertNotIn("* [x] Outcome 0.", frame)
        self.assertIn("Outcome 1.", dashboard.banner())
        self.press(dashboard, ord("x"))
        self.assertIsNone(dashboard.cut)
        self.press(dashboard, ord("X"))
        self.assertIsNone(dashboard.cut_step)
        dashboard.view, dashboard.owner, dashboard.detail = "tasks", "Agent B", None
        self.press(dashboard, ord("p"))
        self.assertEqual(len(tui.parse_tasks(self.read())), 2)
        self.assertEqual(tui.parse_tasks(self.read())[0].owner, "Agent B")

    def test_read_only_details_allow_selection_but_never_cut_or_paste(self):
        before = self.read()
        dashboard = self.press(self.dashboard(read_only=True), 10, ord("j"), ord("x"), ord("P"))
        self.assertEqual(dashboard.detail_step, 1)
        self.assertIsNone(dashboard.cut)
        self.assertIsNone(dashboard.prompt)
        self.assertEqual(self.read(), before)

    def test_refresh_after_peer_reorders_steps_invalidates_the_cut(self):
        dashboard = self.press(self.dashboard(), 10, ord("j"), ord("x"))
        peer = self.read().replace("Outcome 1.", "Peer changed this step.", 1)
        self.write(peer)
        dashboard.refresh()
        self.assertIsNone(dashboard.cut)
        self.assertIn("ledger changed", dashboard.banner())
        dashboard.view, dashboard.owner, dashboard.detail = "tasks", "Agent B", None
        self.press(dashboard, ord("p"))
        self.assertEqual(self.read(), peer)

    def test_peer_write_without_refresh_is_rejected_by_cas(self):
        dashboard = self.press(self.dashboard(), 10, ord("j"), ord("x"))
        peer = self.read() + entry("New peer task", owner="Agent C")
        self.write(peer)
        dashboard.view, dashboard.owner, dashboard.detail = "tasks", "Agent B", None
        self.press(dashboard, ord("p"))
        self.assertEqual(self.read(), peer)
        self.assertIsNone(dashboard.cut)
        self.assertIn("ledger changed", dashboard.banner())

    def test_wrapped_steps_remain_selectable_in_a_small_terminal(self):
        self.write(entry(steps=(False, False, False)).replace("Outcome 0.", "A long step " * 30))
        dashboard = self.press(self.dashboard(), 10, ord("j"))
        screen = Screen(14, 64)
        dashboard.draw(screen, FakeCurses)
        self.assertIn("> [ ] Outcome 1.", screen.frames[-1])
        self.assertIn("x cut step | p give", screen.frames[-1])
        self.press(dashboard, ord("k"))
        dashboard.draw(screen, FakeCurses)
        self.assertIn("> [ ] A long step", screen.frames[-1])
        self.press(dashboard, FakeCurses.KEY_NPAGE)
        self.assertIsNone(dashboard.detail_step)
        self.press(dashboard, ord("x"))
        self.assertIsNone(dashboard.cut)
        self.assertIn("Select a step", dashboard.banner())

    def test_only_remaining_step_moves_original_task_and_clears_old_lease(self):
        text = entry("Only", steps=(False,)) + "\nLease: owner=Agent A; expires=2099-01-01T00:00:00Z; policy=release\n"
        self.write(text + entry("Other", owner="Agent B"))
        dashboard = self.press(self.dashboard(), 10, ord("x"), ord("a"))
        dashboard.selected = [row[0] for row in dashboard.rows()].index("Agent B")
        self.press(dashboard, ord("p"))
        tasks = tui.parse_tasks(self.read())
        self.assertEqual(len(tasks), 2)
        self.assertEqual((tasks[0].heading, tasks[0].steps),
                         ("Only (owner: Agent B)", [(False, "Outcome 0.")]))
        self.assertIsNone(tasks[0].lease)
        self.assertEqual(guard.structure_findings(self.read()), [])

    def test_release_to_unassigned_keeps_step_unchecked_and_pending(self):
        dashboard = self.press(self.dashboard(), 10, ord("j"), ord("x"), ord("P"))
        self.press(dashboard, *map(ord, "unassigned"), 10)
        moved = tui.parse_tasks(self.read())[0]
        self.assertIsNone(moved.owner)
        self.assertEqual((moved.steps, moved.state), ([(False, "Outcome 1.")], "pending"))
        self.assertNotIn("Execution request", moved.status)

    def test_helper_preserves_continuation_fences_and_source_context(self):
        text = self.read().replace("- [ ] Outcome 1.",
                                  "- [ ] Outcome 1.\n  A continuation.\n\n  ```md\n  - [ ] Example only.\n  ```", 1)
        task = tui.parse_tasks(text)[0]
        updated, heading = guard.transfer_step(text, task.line, task.heading, 1,
                                               task.steps[1], "Agent B")
        tasks = tui.parse_tasks(updated)
        self.assertEqual(tasks[0].heading, heading)
        self.assertEqual(tasks[0].steps, [(False, "Outcome 1.")])
        self.assertIn("  A continuation.\n\n  ```md", updated)
        self.assertIn(">   A continuation.", updated)
        self.assertIn("> Status: Recorded status.\n> Continuation and next action.", updated)
        self.assertEqual(guard.structure_findings(updated), [])

    def test_duplicate_step_text_moves_only_the_selected_occurrence(self):
        text = entry("Duplicates", steps=(False, False)).replace("Outcome 1.", "Outcome 0.")
        text = text.replace("- [ ] Outcome 0.\n", "- [ ] Outcome 0.\n  First context.\n", 1)
        task = tui.parse_tasks(text)[0]
        updated, _ = guard.transfer_step(text, task.line, task.heading, 1, task.steps[1], "Agent B")
        split = updated.index("## Duplicates")
        self.assertNotIn("First context", updated[:split])
        self.assertIn("  First context.", updated[split:])

    def test_helper_refuses_stale_step_and_malformed_source(self):
        text = self.read()
        task = tui.parse_tasks(text)[0]
        with self.assertRaisesRegex(ValueError, "selected step changed"):
            guard.transfer_step(text, task.line, task.heading, 1, (True, "Wrong"), "Agent B")
        malformed = text.replace("- [x] In progress", "- [ ] In progress", 1)
        with self.assertRaisesRegex(ValueError, "structure"):
            guard.transfer_step(malformed, task.line, task.heading, 1, task.steps[1], "Agent B")

    def test_split_keeps_source_lease_and_gives_recipient_no_borrowed_deadline(self):
        text = self.read().replace("\n## Second", "\nLease: owner=Agent A; expires=2099-01-01T00:00:00Z; policy=release\n\n## Second", 1)
        source = tui.parse_tasks(text)[0]
        updated, _ = guard.transfer_step(text, source.line, source.heading, 1, source.steps[1], "Agent B")
        moved, remaining, _ = tui.parse_tasks(updated)
        self.assertIsNone(moved.lease)
        self.assertEqual(remaining.lease.owner, "Agent A")
        self.assertEqual(guard.structure_findings(updated), [])

    def test_duplicate_destination_titles_remain_distinguishable(self):
        text = self.read()
        source = tui.parse_tasks(text)[0]
        first, heading = guard.transfer_step(text, source.line, source.heading, 1,
                                             source.steps[1], "Agent C", "2026-09-11")
        other = tui.parse_tasks(first)[-1]
        second, other_heading = guard.transfer_step(first, other.line, other.heading, 1,
                                                    other.steps[1], "Agent C", "2026-09-11")
        self.assertNotEqual(heading, other_heading)
        self.assertIn(heading, second)
        self.assertIn(other_heading, second)
        self.assertEqual(guard.structure_findings(second), [])

    def test_resize_keeps_selected_step_visible_without_another_keypress(self):
        self.write(entry().replace("Outcome 0.", "A long step " * 30))
        dashboard = self.press(self.dashboard(), 10, ord("j"))
        dashboard.draw(Screen(40, 150), FakeCurses)
        screen = Screen(14, 64)
        dashboard.draw(screen, FakeCurses)
        self.assertIn("> [ ] Outcome 1.", screen.frames[-1])


class MoveFeedbackTests(MoveTests):
    """The user could not tell whether a pasted task reached the target session.
    Each test here starts from one of the three reasons why."""

    LONG = "2026-09-08 - Add a live Handoff bar around Codex"
    TARGET = "Claude session 01LD89UW"

    def give(self):
        """Cut the first task and paste it onto the other agent, as the user did."""
        self.write(entry(self.LONG, owner="Codex bar session")
                   + entry("2026-09-07 - Verify Grok status lines", owner=self.TARGET))
        dashboard = self.press(self.dashboard(), ord("x"), ord("a"))
        dashboard.selected = [row[0] for row in dashboard.rows()].index(self.TARGET)
        return self.press(dashboard, ord("p"))

    def test_the_move_lands_on_the_receiving_agents_task_list(self):
        dashboard = self.give()
        self.assertEqual((dashboard.view, dashboard.owner), ("tasks", self.TARGET))
        rows = dashboard.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(tui.heading_title(rows[dashboard.selected][0]), self.LONG)
        screen = Screen(20, 80)
        dashboard.draw(screen, FakeCurses)
        moved_row = next(line for line in screen.frames[-1].splitlines() if self.LONG in line)
        self.assertTrue(moved_row.startswith("+"), moved_row)

    def test_the_receiving_agent_is_never_the_part_that_gets_clipped(self):
        dashboard = self.give()
        for width in (64, 80, 100):
            screen = Screen(20, width)
            dashboard.draw(screen, FakeCurses)
            banner = screen.frames[-1].splitlines()[-4]
            self.assertIn(self.TARGET, banner, f"width {width}: {banner}")

    def test_the_outcome_survives_looking_around(self):
        dashboard = self.give()
        self.press(dashboard, FakeCurses.KEY_DOWN, FakeCurses.KEY_UP, ord("b"))
        self.assertIsNone(dashboard.owner)
        self.assertIn(self.TARGET, dashboard.banner())
        screen = Screen(20, 80)
        dashboard.draw(screen, FakeCurses)
        self.assertIn(self.TARGET, screen.frames[-1])

    def test_a_new_cut_supersedes_the_previous_move(self):
        dashboard = self.give()
        self.press(dashboard, ord("x"))
        self.assertIsNone(dashboard.moved)
        self.assertNotIn("MOVED", dashboard.banner())

    def test_a_move_to_unassigned_lands_on_the_unassigned_list(self):
        dashboard = self.press(self.dashboard(), ord("x"), ord("P"))
        self.press(dashboard, *[ord(c) for c in "Agent B"], 10)
        self.assertEqual(dashboard.owner, "Agent B")
        self.assertEqual([tui.owner_name(t) for t in dashboard.tasks()], ["Agent B", "Agent B"])

    def test_a_peer_deleting_the_moved_task_drops_the_record(self):
        dashboard = self.give()
        self.write(entry("2026-09-07 - Verify Grok status lines", owner=self.TARGET))
        dashboard.refresh()
        self.assertIsNone(dashboard.moved)
        self.assertNotIn("MOVED", dashboard.banner())


class AssignmentBarTests(unittest.TestCase):
    """The bar is the only surface that redraws without a model turn.

    The failure case, reproduced by hand before this existed: the user assigns a
    task from the viewer to an agent that has finished its work, and that agent's
    row reads 'handoff 0/1 tasks - 0/2 steps - Beta', which is exactly what
    owning no work looks like.
    """

    def row(self, text, session_name="Beta"):
        return tui.bar_line(tui.parse_snapshot(text), color=False, session_name=session_name)

    def test_an_assignment_is_visible_to_the_agent_it_was_made_to(self):
        text = "# Handoff\n\n" + entry("Settings page", owner="Beta", state="pending", steps=(False, False))
        self.assertIn("1 assigned to you", self.row(text))

    def test_another_agents_assignment_never_appears_on_this_row(self):
        text = "# Handoff\n\n" + entry("Settings page", owner="Beta", state="pending", steps=(False, False))
        self.assertNotIn("assigned", self.row(text, session_name="Alpha"))

    def test_starting_the_work_clears_the_marker(self):
        text = "# Handoff\n\n" + entry("Settings page", owner="Beta", state="in_progress", steps=(True, False))
        self.assertNotIn("assigned", self.row(text))

    def test_a_session_that_has_not_claimed_a_name_is_told_nothing(self):
        text = "# Handoff\n\n" + entry("Settings page", owner="Beta", state="pending", steps=(False, False))
        self.assertNotIn("assigned", self.row(text, session_name=None))

    def test_the_count_covers_every_unstarted_entry(self):
        text = ("# Handoff\n\n" + entry("One", owner="Beta", state="pending", steps=(False, False))
                + entry("Two", owner="Beta", state="pending", steps=(False, False))
                + entry("Theirs", owner="Alpha", state="pending", steps=(False, False)))
        self.assertIn("2 assigned to you", self.row(text))

    def test_the_marker_keeps_the_row_on_one_line_and_colours_with_the_bar(self):
        text = "# Handoff\n\n" + entry("Settings page", owner="Beta", state="pending", steps=(False, False))
        self.assertNotIn("\n", self.row(text))
        coloured = tui.bar_line(tui.parse_snapshot(text), session_name="Beta")
        self.assertIn("assigned to you", coloured)
        self.assertIn("\033", coloured)

    def test_a_viewer_move_makes_the_marker_appear(self):
        """The reported path end to end, driven through the viewer's own move."""
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "HANDOFF.md"
            ledger.write_text("# Handoff\n\n" + entry("Settings page", owner=None,
                                                      state="pending", steps=(False, False)), encoding="utf-8")
            watcher = tui.Watcher(ledger)
            watcher.poll()
            self.assertNotIn("assigned", tui.bar_line(watcher.snapshot, color=False,
                                                      session_name="Beta"))
            dashboard = tui.Dashboard(watcher)
            dashboard.view = "tasks"
            dashboard.cut = watcher.snapshot.tasks[0]
            dashboard.move_task("Beta")
            watcher.poll()
            self.assertIn("1 assigned to you", tui.bar_line(watcher.snapshot, color=False,
                                                            session_name="Beta"))


class NudgeKeyTests(unittest.TestCase):
    """The nudge key on the channel view, and what it refuses to do.

    A nudge is a message, so it needs a real sender. The viewer is a window, not
    an agent: it speaks as the session whose terminal it runs in and refuses
    rather than borrowing another agent's identity.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "HANDOFF.md"
        self.path.write_text("# Handoff\n\n" + entry("Importer", owner="Beta"),
                             encoding="utf-8")
        self.cache = patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.root / "names"),
                                            "HANDOFF_SESSION": "viewer-terminal"})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.channel = tui.Channel(self.root)
        # The window belongs to the session that claimed a name against this seed.
        self.mine = guard.claim_name("viewer-terminal", self.path, set())[0]
        self.sender = self.channel.join(self.mine, "Claude Code")["session"]
        self.beta = self.channel.join("Beta", "Codex")["session"]

    def board(self, read_only=False, seed="viewer-terminal"):
        watcher = tui.Watcher(self.path)
        watcher.poll()
        dashboard = tui.Dashboard(watcher, read_only=read_only, seed=seed)
        dashboard.view, dashboard.channel_mode = "channel", "sessions"
        dashboard.refresh()
        rows = dashboard.rows()
        dashboard.selected = next(index for index, row in enumerate(rows)
                                  if row[1]["owner"] == "Beta")
        return dashboard

    def press(self, dashboard, *keys):
        for key in keys:
            dashboard.handle_key(key, FakeCurses, 5)

    def nudges(self):
        return [row for row in self.channel.inbox(self.beta) if row["kind"] == "nudge"]

    def test_the_key_sends_one_nudge_and_says_what_it_is_not(self):
        dashboard = self.board()
        self.press(dashboard, ord("n"))
        self.assertIn("Nudged Beta", dashboard.message)
        self.assertIn("not a verdict", dashboard.message)
        self.assertEqual(len(self.nudges()), 1)

    def test_the_nudge_records_that_the_user_raised_it_in_the_viewer(self):
        self.press(self.board(), ord("n"))
        body = json.loads(self.nudges()[0]["body"])
        self.assertEqual(body["via"], "handoff viewer, at the user's direction")
        self.assertEqual(self.nudges()[0]["sender_owner"], self.mine)

    def test_read_only_refuses_and_sends_nothing(self):
        dashboard = self.board(read_only=True)
        self.press(dashboard, ord("n"))
        self.assertIn("disabled in read-only mode", dashboard.message)
        self.assertEqual(self.nudges(), [])

    def test_a_window_with_no_session_of_its_own_refuses(self):
        # No seed and no host identifier: the window belongs to nobody, and the
        # environment fallbacks bar_session_name would try are gone too.
        with patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.root / "names")},
                        clear=True):
            dashboard = self.board(seed=None)
            self.press(dashboard, ord("n"))
        self.assertIn("no session of its own", dashboard.message)
        self.assertEqual(self.nudges(), [])

    def test_pressing_it_outside_the_channel_view_explains_where_it_works(self):
        dashboard = self.board()
        dashboard.view = "tasks"
        self.press(dashboard, ord("n"))
        self.assertIsNone(dashboard.message)
        self.assertEqual(self.nudges(), [])

    def test_selecting_this_windows_own_session_sends_nothing(self):
        dashboard = self.board()
        rows = dashboard.rows()
        dashboard.selected = next(index for index, row in enumerate(rows)
                                  if row[1]["owner"] == self.mine)
        self.press(dashboard, ord("n"))
        self.assertIn("own session", dashboard.message)
        self.assertEqual(self.nudges(), [])

    def test_a_second_press_reports_the_interval_rather_than_sending_again(self):
        dashboard = self.board()
        self.press(dashboard, ord("n"), ord("n"))
        self.assertIn("already nudged", dashboard.message)
        self.assertIn("buries the first request", dashboard.message)
        self.assertEqual(len(self.nudges()), 1)

    def test_the_key_row_offers_only_the_keys_that_work_here(self):
        """The row is truncated to the terminal width, so it cannot list everything."""
        screen = Screen()
        dashboard = self.board()
        dashboard.draw(screen, FakeCurses)
        footer = screen.lines[screen.height - 1]
        self.assertIn("n nudge", footer)
        # Cut and give act on a task; there is none to hold in the channel view.
        self.assertNotIn("x cut", footer)
        self.assertLess(len(footer), screen.width)
        dashboard.view = "tasks"
        dashboard.draw(screen, FakeCurses)
        footer = screen.lines[screen.height - 1]
        self.assertNotIn("n nudge", footer)
        self.assertIn("x cut", footer)
        read_only = self.board(read_only=True)
        read_only.draw(screen, FakeCurses)
        self.assertNotIn("n nudge", screen.lines[screen.height - 1])


class CompletionTests(unittest.TestCase):
    """User override to mark steps or whole tasks complete from the live view."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "HANDOFF.md"
        self.write("# Handoff\n\n" + entry("Work", steps=(False, False)))

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def read(self):
        return self.path.read_text(encoding="utf-8")

    def dashboard(self, read_only=False):
        watcher = tui.Watcher(self.path)
        watcher.poll()
        dashboard = tui.Dashboard(watcher, read_only=read_only)
        dashboard.view = "tasks"
        return dashboard

    def press(self, dashboard, *keys):
        for key in keys:
            dashboard.handle_key(key, FakeCurses, 5)
        return dashboard

    def test_d_marks_the_selected_step_complete(self):
        dashboard = self.press(self.dashboard(), 10, ord("j"), ord("d"))
        task = tui.parse_tasks(self.read())[0]
        self.assertEqual(task.steps, [(False, "Outcome 0."), (True, "Outcome 1.")])
        self.assertEqual(task.state, "in_progress")
        self.assertIn("Marked complete by user override", self.read())
        self.assertEqual(guard.structure_findings(self.read()), [])

    def test_d_on_the_last_open_step_completes_the_task(self):
        self.write("# Handoff\n\n" + entry("Work", steps=(True, False)))
        self.press(self.dashboard(), 10, ord("j"), ord("d"))
        task = tui.parse_tasks(self.read())[0]
        self.assertEqual(task.state, "completed")
        self.assertTrue(all(checked for checked, _ in task.steps))

    def test_D_marks_the_whole_task_from_the_tasks_view(self):
        self.press(self.dashboard(), ord("D"))
        task = tui.parse_tasks(self.read())[0]
        self.assertEqual(task.state, "completed")
        self.assertTrue(all(checked for checked, _ in task.steps))
        self.assertIn("Marked complete by user override", self.read())

    def test_D_marks_the_whole_task_from_task_details(self):
        self.press(self.dashboard(), 10, ord("D"))
        task = tui.parse_tasks(self.read())[0]
        self.assertEqual(task.state, "completed")
        self.assertTrue(all(checked for checked, _ in task.steps))

    def test_read_only_mode_refuses_completion(self):
        dashboard = self.press(self.dashboard(read_only=True), 10, ord("d"), ord("D"))
        task = tui.parse_tasks(self.read())[0]
        self.assertEqual(task.state, "in_progress")
        self.assertFalse(all(checked for checked, _ in task.steps))
        self.assertIn("read-only", dashboard.banner())

    def test_d_without_details_asks_to_open_them(self):
        dashboard = self.press(self.dashboard(), ord("d"))
        self.assertIn("Open task details", dashboard.banner())
        self.assertFalse(all(checked for checked, _ in tui.parse_tasks(self.read())[0].steps))


class LeaderViewerTests(unittest.TestCase):
    """The L key and leadership markers in the live viewer."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "HANDOFF.md"
        self.write("# Handoff\n\n" + entry("First", owner="Agent A")
                   + entry("Second", owner="Agent B"))

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def read(self):
        return self.path.read_text(encoding="utf-8")

    def dashboard(self, read_only=False):
        watcher = tui.Watcher(self.path)
        watcher.poll()
        dashboard = tui.Dashboard(watcher, read_only=read_only)
        dashboard.view = "agents"
        return dashboard

    def press(self, dashboard, *keys):
        for key in keys:
            dashboard.handle_key(key, FakeCurses, 5)
        return dashboard

    def agents(self, read_only=False):
        with patch.object(tui, "recent_claims", return_value=[]):
            return self.dashboard(read_only=read_only)

    def test_l_designates_the_selected_agent_as_leader(self):
        dashboard = self.agents()
        dashboard.selected = [row[0] for row in dashboard.rows()].index("Agent B")
        self.press(dashboard, ord("L"))
        self.assertIn("Lead: owner=Agent B", self.read())
        self.assertIn("Agent B is leader", dashboard.message)

    def test_l_on_the_current_leader_resigns(self):
        dashboard = self.agents()
        dashboard.selected = [row[0] for row in dashboard.rows()].index("Agent A")
        self.press(dashboard, ord("L"))
        self.assertIn("Lead: owner=Agent A", self.read())
        self.press(dashboard, ord("L"))
        self.assertNotIn("Lead:", self.read())
        self.assertIn("resigned", dashboard.message)

    def test_l_refuses_when_another_leader_is_active(self):
        dashboard = self.agents()
        dashboard.selected = [row[0] for row in dashboard.rows()].index("Agent A")
        self.press(dashboard, ord("L"))
        dashboard.selected = [row[0] for row in dashboard.rows()].index("Agent B")
        self.press(dashboard, ord("L"))
        self.assertIn("Lead: owner=Agent A", self.read())
        self.assertIn("already holds", dashboard.message)

    def test_read_only_mode_refuses_leadership_changes(self):
        dashboard = self.agents(read_only=True)
        self.press(dashboard, ord("L"))
        self.assertNotIn("Lead:", self.read())
        self.assertIn("read-only", dashboard.message)

    def test_lead_summary_appears_when_a_mandate_is_recorded(self):
        self.write(self.read().replace("# Handoff\n\n",
                                        "# Handoff\n\n"
                                        "Lead: owner=Agent A; expires=2099-01-01T00:00:00Z; "
                                        "policy=coordinate; succession=none\n\n"))
        snapshot = tui.parse_snapshot(self.read())
        lines = tui.summary_lines(snapshot)
        self.assertTrue(any(line.startswith("LEAD  Agent A") for line in lines))

    def lead(self, owner, expires="2099-01-01T00:00:00Z"):
        self.write(self.read().replace(
            "# Handoff\n\n", f"# Handoff\n\nLead: owner={owner}; expires={expires}; "
            "policy=coordinate; succession=none\n\n"))

    def test_an_active_leader_with_no_tasks_or_recent_claim_stays_listed(self):
        # Observed: the header named Bastet as leader while no Bastet row was
        # listed, because it held no tasks and its name claim had aged out.
        self.lead("Bastet")
        with patch.object(tui, "recent_claims_for_ledger", return_value=[]):
            dashboard = self.dashboard()
            rows = dashboard.rows()
            report = tui.plain_report(dashboard.watcher)
        self.assertEqual([owner for owner, _ in rows], ["Bastet", "Agent A", "Agent B"])
        self.assertEqual(rows[0][1].tracked, 0)
        self.assertIn("Bastet [LEAD]", report)

    def test_the_listed_leader_can_be_resigned_and_then_leaves_the_list(self):
        self.lead("Bastet")
        with patch.object(tui, "recent_claims_for_ledger", return_value=[]):
            dashboard = self.dashboard()
            dashboard.selected = 0
            self.press(dashboard, ord("L"))
            self.assertNotIn("Lead:", self.read())
            self.assertNotIn("Bastet", [owner for owner, _ in dashboard.rows()])

    def test_an_expired_leader_with_no_tasks_is_not_listed(self):
        self.lead("Bastet", expires="2000-01-01T00:00:00Z")
        with patch.object(tui, "recent_claims_for_ledger", return_value=[]):
            rows = self.dashboard().rows()
        self.assertNotIn("Bastet", [owner for owner, _ in rows])

    def test_a_leader_who_owns_tasks_is_listed_once_in_ledger_order(self):
        self.lead("Agent A")
        with patch.object(tui, "recent_claims_for_ledger", return_value=[]):
            rows = self.dashboard().rows()
        self.assertEqual([owner for owner, _ in rows], ["Agent A", "Agent B"])

    def test_assignment_provenance_appears_in_task_details(self):
        assigned = (
            "## Offered work (owner: Agent B)\n\nState:\n- [x] In progress\n- [ ] Completed\n\n"
            "Task: id=tabc1234\n"
            "Assigned: by=Agent A; to=Agent B; state=offered; accept-by=2099-01-01T00:00:00Z\n\n"
            "Steps:\n- [ ] Implement it.\n\nStatus: Offered.\n\n"
        )
        self.write("# Handoff\n\n" + assigned)
        dashboard = self.dashboard()
        dashboard.view = "tasks"
        dashboard.selected = 0
        self.press(dashboard, 10)
        rows = dashboard.detail_rows(80)
        joined = "\n".join(line for line, _ in rows)
        self.assertIn("assigned by Agent A", joined)
        self.assertIn("accept by", joined)

    def test_the_agents_footer_offers_the_leader_key(self):
        dashboard = self.agents()
        screen = Screen(width=120)
        dashboard.draw(screen, FakeCurses)
        self.assertIn("L leader", screen.lines[screen.height - 1])
