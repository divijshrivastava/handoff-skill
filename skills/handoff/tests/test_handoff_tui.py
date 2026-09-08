from __future__ import annotations

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


class DashboardTests(unittest.TestCase):
    def dashboard(self):
        watcher = tui.Watcher(Path("unused"))
        watcher.snapshot = tui.parse_snapshot(entry("First") + entry("Second", owner="Agent B"))
        return tui.Dashboard(watcher)

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
        dashboard.handle_key(9, FakeCurses, 5)
        self.assertEqual(dashboard.view, "agents")
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

    def test_counts_and_open_owners_appear(self):
        text = "# Handoff\n\n" + entry(title="A", owner="Ann", state="completed", steps=(True, True))
        text += entry(title="B", owner="Bo", state="in_progress", steps=(True, False))
        line = tui.bar_line(self.snapshot(text), color=False)
        self.assertIn("1/2 tasks", line)
        self.assertIn("3/4 steps", line)
        self.assertIn("Bo", line)
        self.assertNotIn("Ann", line)

    def test_open_owners_are_named_newest_first(self):
        """Ledger order, like the viewer's agent list: not alphabetical, not doubled."""
        text = ("# Handoff\n\n" + entry(title="C", owner="Zoe")
                + entry(title="B", owner="Ann") + entry(title="A", owner="Zoe"))
        line = tui.bar_line(self.snapshot(text), color=False)
        self.assertTrue(line.endswith(" Zoe, Ann"), line)

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

    def test_a_move_changes_ownership_only(self):
        before = tui.parse_tasks(self.read())[0]
        self.press(self.dashboard(), ord("x"), ord("a"))
        dashboard = self.dashboard()
        self.press(dashboard, ord("x"))
        dashboard.selected = 1
        self.press(dashboard, ord("p"))
        after = tui.parse_tasks(self.read())[0]
        self.assertEqual(after.owner, "Agent B")
        self.assertEqual((after.line, after.steps, after.state), (before.line, before.steps, before.state))
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
