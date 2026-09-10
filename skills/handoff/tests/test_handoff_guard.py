from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "handoff_guard.py"
SPEC = importlib.util.spec_from_file_location("handoff_guard", SCRIPT)
assert SPEC and SPEC.loader
handoff_guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = handoff_guard
SPEC.loader.exec_module(handoff_guard)


class HandoffGuardTests(unittest.TestCase):
    def test_ignores_template_heading_inside_fence(self) -> None:
        text = """# Handoff

```md
## YYYY-MM-DD - Template (owner: agent)
```

## 2026-09-06 - Real task (owner: Codex)

State:

- [ ] In progress
- [ ] Completed

Steps:

- [ ] Do the work.

Status: Pending. No work has started.
"""
        tasks = handoff_guard.parse_tasks(text)
        self.assertEqual([task.heading for task in tasks], ["2026-09-06 - Real task (owner: Codex)"])

    def test_parses_all_three_valid_states(self) -> None:
        blocks = []
        for title, progress, completed, step in (
            ("Pending", " ", " ", " "),
            ("Active", "x", " ", " "),
            ("Done", "x", "x", "x"),
        ):
            blocks.append(
                f"""## 2026-09-06 - {title} (owner: Codex)

State:

- [{progress}] In progress
- [{completed}] Completed

Steps:

- [{step}] Work.

Status: Current.
"""
            )
        tasks = handoff_guard.parse_tasks("\n".join(blocks))
        self.assertEqual([task.state for task in tasks], ["pending", "in_progress", "completed"])
        self.assertFalse(any(task.errors for task in tasks))

    def test_fenced_example_cannot_supply_missing_task_state(self) -> None:
        text = """## Real task (owner: Tester)

```md
State:
- [x] In progress
- [x] Completed
Status: Complete.
```

Steps:
- [ ] Verify real work.
"""
        task = handoff_guard.parse_tasks(text)[0]
        self.assertIsNone(task.completed)
        self.assertIn("missing State section", task.errors)
        self.assertIn("missing Status line", task.errors)

    def test_fenced_unchecked_steps_do_not_reopen_completed_task(self) -> None:
        text = """## Real task (owner: Tester)
State:
- [x] In progress
- [x] Completed
Steps:
- [x] Verified real work.
```md
- [ ] Example work.
```
Status: Complete.
"""
        task = handoff_guard.parse_tasks(text)[0]
        self.assertEqual(task.steps, [(True, "Verified real work.")])
        self.assertEqual(task.errors, [])

    def test_fences_require_matching_marker_and_sufficient_length(self) -> None:
        real = handoff_guard.make_template("2026-09-07", "Real", "Tester", ["Verify."])
        for opening, inner, closing in (
            ("````md", "```", "````"),
            ("~~~md", "```", "~~~~"),
            ("```md", "~~~", "````"),
        ):
            with self.subTest(opening=opening):
                example = f"{opening}\n{inner}\n## Hidden example\n{closing}\n\n"
                tasks = handoff_guard.parse_tasks(example + real)
                self.assertEqual(len(tasks), 1)
                self.assertIn("Real", tasks[0].heading)
                self.assertEqual(tasks[0].line, 6)

    def test_validate_cli_reports_errors_without_editing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = root / "HANDOFF.md"
            text = handoff_guard.make_template("2026-09-07", "Real", "Tester", ["Verify."])
            text = text.replace("- [ ] Completed", "- [x] Completed")
            ledger.write_text(text)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "validate", "--root", str(root), "--json"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(json.loads(result.stdout)["errors"])
            self.assertEqual(ledger.read_text(), text)

    def test_rejects_completed_task_with_unchecked_step(self) -> None:
        text = """## 2026-09-06 - Broken (owner: Codex)

State:

- [x] In progress
- [x] Completed

Steps:

- [ ] Verification.

Status: Complete.
"""
        task = handoff_guard.parse_tasks(text)[0]
        self.assertIn("completed task has unchecked steps", task.errors)

    def test_doctor_reports_missing_ledger_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = handoff_guard.ledger_report(root)
            self.assertIn("HANDOFF.md not found", report["errors"])
            self.assertFalse((root / "HANDOFF.md").exists())

    def test_template_has_separate_state_boxes_and_steps(self) -> None:
        output = handoff_guard.make_template(
            "2026-09-06", "Ship feature", "Codex", ["Implement.", "Verify."]
        )
        self.assertIn("- [ ] In progress", output)
        self.assertIn("- [ ] Completed", output)
        self.assertIn("- [ ] Implement.", output)
        self.assertIn("- [ ] Verify.", output)


MINIMAL_LEDGER = """# Handoff

## 2026-09-06 - Existing task (owner: Codex)

State:

- [x] In progress
- [ ] Completed

Steps:

- [ ] Finish the work.

Status: In progress.
"""


class CompareAndSwapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text(MINIMAL_LEDGER, encoding="utf-8")

    def run_apply(self, *args: str) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "apply", "--root", str(self.root), "--json", *args],
            capture_output=True,
            text=True, encoding="utf-8",
            check=False,
        )
        return result.returncode, json.loads(result.stdout)

    def entry_file(self, title: str, owner: str) -> str:
        path = self.root / f"{owner}-entry.md"
        path.write_text(
            handoff_guard.make_template("2026-09-07", title, owner, ["Do the work."]),
            encoding="utf-8",
        )
        return str(path)

    def current_version(self) -> str:
        return handoff_guard.ledger_version(self.ledger.read_text(encoding="utf-8"))

    def test_doctor_reports_the_version_used_for_writes(self) -> None:
        report = handoff_guard.ledger_report(self.root)
        self.assertEqual(report["version"], self.current_version())

    def test_apply_inserts_a_new_entry_above_existing_tasks(self) -> None:
        code, result = self.run_apply(
            "--expect-version", self.current_version(),
            "--entry", self.entry_file("Newest task", "Claude"),
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "applied")
        text = self.ledger.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Handoff\n"))
        self.assertLess(text.index("Newest task"), text.index("Existing task"))
        self.assertEqual(result["new_version"], self.current_version())

    def test_concurrent_writer_loses_the_race_instead_of_the_entry(self) -> None:
        stale = self.current_version()
        first_code, _ = self.run_apply(
            "--expect-version", stale, "--entry", self.entry_file("Task A", "A")
        )
        self.assertEqual(first_code, 0)

        second_code, conflict = self.run_apply(
            "--expect-version", stale, "--entry", self.entry_file("Task B", "B")
        )
        self.assertEqual(second_code, 3)
        self.assertEqual(conflict["status"], "conflict")
        self.assertNotEqual(conflict["current_version"], stale)

        text = self.ledger.read_text(encoding="utf-8")
        self.assertIn("Task A", text)
        self.assertNotIn("Task B", text)

        retry_code, _ = self.run_apply(
            "--expect-version", self.current_version(),
            "--entry", self.entry_file("Task B", "B"),
        )
        self.assertEqual(retry_code, 0)
        retried = self.ledger.read_text(encoding="utf-8")
        self.assertIn("Task A", retried)
        self.assertIn("Task B", retried)

    def test_apply_accepts_an_unambiguous_version_prefix(self) -> None:
        code, _ = self.run_apply(
            "--expect-version", self.current_version()[:12],
            "--entry", self.entry_file("Prefixed", "Claude"),
        )
        self.assertEqual(code, 0)

    def test_apply_rejects_a_version_prefix_that_is_too_short(self) -> None:
        code, result = self.run_apply(
            "--expect-version", self.current_version()[:6],
            "--entry", self.entry_file("Too short", "Claude"),
        )
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "conflict")

    def test_apply_refuses_a_rewrite_that_falsifies_task_state(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        content = self.root / "rewritten.md"
        content.write_text(before.replace("- [ ] Completed", "- [x] Completed", 1), encoding="utf-8")
        code, result = self.run_apply(
            "--expect-version", self.current_version(), "--content", str(content)
        )
        self.assertEqual(code, 4)
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(any("unchecked steps" in error for error in result["errors"]))
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_pre_existing_errors_do_not_block_an_unrelated_entry(self) -> None:
        self.ledger.write_text(
            MINIMAL_LEDGER.replace("- [ ] Finish the work.", "- [x] Finish the work."),
            encoding="utf-8",
        )
        code, result = self.run_apply(
            "--expect-version", self.current_version(),
            "--entry", self.entry_file("Unrelated", "Claude"),
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["errors"], [])

    def test_dry_run_reports_without_writing(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        code, result = self.run_apply(
            "--expect-version", self.current_version(),
            "--entry", self.entry_file("Not written", "Claude"),
            "--dry-run",
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_apply_leaves_no_temporary_files(self) -> None:
        self.run_apply(
            "--expect-version", self.current_version(),
            "--entry", self.entry_file("Clean", "Claude"),
        )
        self.assertEqual([path.name for path in self.root.glob(".handoff-*")], [])

    def test_apply_errors_when_the_ledger_is_missing(self) -> None:
        self.ledger.unlink()
        code, result = self.run_apply(
            "--expect-version", "0" * 64, "--entry", self.entry_file("Nowhere", "Claude")
        )
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertFalse(self.ledger.exists())


class OverlappingWriterTests(unittest.TestCase):
    """Two writers whose critical sections genuinely overlap.

    CompareAndSwapTests waits for the first write to return before starting the second,
    so it can only prove stale-version rejection. These start the second writer while
    the first is parked inside apply, which is the case that actually loses entries.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text("# Handoff\n", encoding="utf-8")

    def entry_file(self, owner: str) -> Path:
        path = self.root / f"{owner}.md"
        path.write_text(
            handoff_guard.make_template("2026-09-07", f"Task {owner}", owner, ["Work."]),
            encoding="utf-8",
        )
        return path

    def version(self) -> str:
        return handoff_guard.ledger_version(self.ledger.read_text(encoding="utf-8"))

    def apply_process(self, entry: str, version: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "apply", "--root", str(self.root),
             "--json", "--expect-version", version, "--entry", entry],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs a POSIX FIFO to park a writer")
    def test_overlapping_writers_do_not_lose_an_entry(self) -> None:
        """A parked writer must not overwrite a peer that completed while it waited."""
        stale = self.version()
        pipe = self.root / "payload.fifo"
        os.mkfifo(pipe)
        slow = self.entry_file("A")
        fast = self.entry_file("B")

        # Writer A blocks reading its payload from the pipe, inside apply.
        result: dict = {}
        def run_slow() -> None:
            result["proc"] = self.apply_process(str(pipe), stale)
        thread = threading.Thread(target=run_slow)
        thread.start()

        # Writer B completes end to end while A is still parked.
        fast_proc = self.apply_process(str(fast), stale)
        self.assertEqual(fast_proc.returncode, 0, fast_proc.stdout + fast_proc.stderr)

        # Release A's payload and let it finish.
        with open(pipe, "w") as handle:
            handle.write(slow.read_text(encoding="utf-8"))
        thread.join(timeout=60)
        self.assertFalse(thread.is_alive(), "slow writer did not finish")

        slow_proc = result["proc"]
        self.assertEqual(slow_proc.returncode, 3,
                         f"expected conflict, got {slow_proc.returncode}: {slow_proc.stdout}")
        self.assertEqual(json.loads(slow_proc.stdout)["status"], "conflict")

        text = self.ledger.read_text(encoding="utf-8")
        self.assertIn("Task B", text)
        self.assertNotIn("Task A", text)

        # Retrying against the current version preserves both entries.
        retry = self.apply_process(str(slow), self.version())
        self.assertEqual(retry.returncode, 0, retry.stdout)
        retried = self.ledger.read_text(encoding="utf-8")
        self.assertIn("Task A", retried)
        self.assertIn("Task B", retried)

    # Worker that parks inside atomic_write: past the version check, still holding the
    # lock. Monkeypatching keeps the pause out of the shipped helper.
    PARKED_WORKER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("parked_guard", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard
spec.loader.exec_module(guard)
real_write = guard.atomic_write
def parked_write(path, text):
    print("READY", flush=True)
    sys.stdin.read(1)
    real_write(path, text)
guard.atomic_write = parked_write
parsed = guard.build_parser().parse_args(sys.argv[2:])
sys.exit(parsed.handler(parsed))
"""

    def test_second_writer_waits_while_the_critical_section_is_held(self) -> None:
        """B must block while A holds the lock, then conflict without losing A's entry.

        test_overlapping_writers_do_not_lose_an_entry parks A before it reads the
        ledger, so it passes even with the lock removed. This one parks A after the
        version check, which only the lock can serialize.
        """
        version = self.version()
        slow = self.entry_file("A")
        fast = self.entry_file("B")
        args = ["apply", "--root", str(self.root), "--json",
                "--expect-version", version, "--entry"]

        parked = subprocess.Popen(
            [sys.executable, "-c", self.PARKED_WORKER, str(SCRIPT), *args, str(slow)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        other = None
        try:
            self.assertEqual(parked.stdout.readline().strip(), "READY")
            other = subprocess.Popen(
                [sys.executable, str(SCRIPT), *args, str(fast)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            )
            # B must not get through while A holds the lock.
            with self.assertRaises(subprocess.TimeoutExpired):
                other.communicate(timeout=1.0)

            parked.stdin.write("x")
            parked.stdin.flush()
            slow_out, _ = parked.communicate(timeout=30)
            fast_out, _ = other.communicate(timeout=30)
        finally:
            for proc in (parked, other):
                if proc is not None and proc.poll() is None:
                    proc.kill()
                    proc.wait()

        self.assertEqual(parked.returncode, 0, slow_out)
        self.assertEqual(other.returncode, 3, fast_out)
        self.assertEqual(json.loads(fast_out)["status"], "conflict")
        self.assertIn("Task A", self.ledger.read_text(encoding="utf-8"))

    @unittest.skipIf(sys.platform == "win32", "Windows has no POSIX permission bits")
    def test_apply_preserves_the_ledger_file_mode(self) -> None:
        os.chmod(self.ledger, 0o644)
        proc = self.apply_process(str(self.entry_file("C")), self.version())
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(os.stat(self.ledger).st_mode & 0o777, 0o644)

    def test_read_binds_the_returned_text_to_the_returned_version(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "read", "--root", str(self.root)],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(proc.returncode, 0)
        payload = json.loads(proc.stdout)
        self.assertEqual(handoff_guard.ledger_version(payload["text"]), payload["version"])


class DuplicateStateBoxTests(unittest.TestCase):
    def test_contradictory_completed_boxes_are_an_error(self) -> None:
        text = """# Handoff

## 2026-09-07 - Contradictory (owner: X)

State:

- [x] In progress
- [x] Completed
- [ ] Completed

Steps:

- [x] Done.

Status: Complete.
"""
        task = handoff_guard.parse_tasks(text)[0]
        self.assertIn("duplicate Completed checkbox", task.errors)
        self.assertIn("contradictory Completed checkbox", task.errors)
        self.assertEqual(task.state, "invalid")

    def test_single_state_boxes_still_parse(self) -> None:
        task = handoff_guard.parse_tasks(MINIMAL_LEDGER)[0]
        self.assertEqual(task.errors, [])
        self.assertEqual(task.state, "in_progress")


class ReassignTests(unittest.TestCase):
    """The heading label is the only record of who holds a task, so moving one
    between agents must change that label; a viewer hand-off also checks In
    progress when the entry is not complete."""

    def test_owner_label_is_replaced_and_the_entry_keeps_its_place(self) -> None:
        text = handoff_guard.reassign_task(
            MINIMAL_LEDGER, 3, "2026-09-06 - Existing task (owner: Codex)", "Claude"
        )
        task = handoff_guard.parse_tasks(text)[0]
        self.assertEqual(task.owner, "Claude")
        self.assertEqual(task.line, 3)
        self.assertEqual(task.state, "in_progress")
        self.assertEqual(task.steps, [(False, "Finish the work.")])
        self.assertEqual(handoff_guard.structure_findings(text), [])

    def test_the_headings_own_agent_wording_survives_the_move(self) -> None:
        text = MINIMAL_LEDGER.replace("owner: Codex", "agent: Codex")
        moved = handoff_guard.reassign_task(
            text, 3, "2026-09-06 - Existing task (agent: Codex)", "Claude"
        )
        self.assertIn("## 2026-09-06 - Existing task (agent: Claude)", moved)

    def test_an_unlabelled_task_gains_a_label_and_can_lose_it_again(self) -> None:
        plain = MINIMAL_LEDGER.replace(" (owner: Codex)", "")
        labelled = handoff_guard.reassign_task(plain, 3, "2026-09-06 - Existing task", "Claude")
        self.assertIn("## 2026-09-06 - Existing task (owner: Claude)", labelled)
        cleared = handoff_guard.reassign_task(
            labelled, 3, "2026-09-06 - Existing task (owner: Claude)", None
        )
        self.assertIn("## 2026-09-06 - Existing task\n", cleared)
        self.assertIsNone(handoff_guard.parse_tasks(cleared)[0].owner)

    def test_a_note_joins_the_status_paragraph_it_belongs_to(self) -> None:
        text = MINIMAL_LEDGER.replace(
            "Status: In progress.", "Status: In progress.\nNext action is the CLI."
        )
        moved = handoff_guard.reassign_task(
            text, 3, "2026-09-06 - Existing task (owner: Codex)", "Claude",
            "Reassigned: Codex to Claude.",
        )
        lines = moved.splitlines()
        self.assertEqual(lines[lines.index("Next action is the CLI.") + 1],
                         "Reassigned: Codex to Claude.")
        self.assertEqual(handoff_guard.structure_findings(moved), [])

    def test_a_moved_task_between_others_leaves_its_neighbours_alone(self) -> None:
        second = MINIMAL_LEDGER.replace("# Handoff\n\n", "").replace(
            "Existing task (owner: Codex)", "Older task (owner: Kimi)")
        text = MINIMAL_LEDGER + "\n" + second
        task = handoff_guard.parse_tasks(text)[1]
        moved = handoff_guard.reassign_task(text, task.line, task.heading, "Claude",
                                            "Reassigned: Kimi to Claude.")
        owners = [entry.owner for entry in handoff_guard.parse_tasks(moved)]
        self.assertEqual(owners, ["Codex", "Claude"])
        self.assertNotIn("Reassigned", moved[: moved.index("Older task")])

    def test_a_stale_position_refuses_to_edit_whatever_now_sits_there(self) -> None:
        with self.assertRaises(ValueError):
            handoff_guard.reassign_task(MINIMAL_LEDGER, 3, "2026-09-06 - Renamed task", "Claude")
        with self.assertRaises(ValueError):
            handoff_guard.reassign_task(MINIMAL_LEDGER, 900, "2026-09-06 - Existing task", "Claude")

    def test_a_name_a_heading_cannot_carry_is_refused(self) -> None:
        for name in ("", "   ", "Age(nt)", "line\nbreak", "x" * 81):
            self.assertIsNotNone(handoff_guard.owner_label_error(name))
            with self.assertRaises(ValueError):
                handoff_guard.reassign_task(
                    MINIMAL_LEDGER, 3, "2026-09-06 - Existing task (owner: Codex)", name
                )
        self.assertIsNone(handoff_guard.owner_label_error("Claude session 01LD89UW"))

    def test_mark_in_progress_checks_a_pending_hand_off(self) -> None:
        pending = MINIMAL_LEDGER.replace("- [x] In progress", "- [ ] In progress")
        moved = handoff_guard.reassign_task(
            pending, 3, "2026-09-06 - Existing task (owner: Codex)", "Claude",
            mark_in_progress=True,
        )
        task = handoff_guard.parse_tasks(moved)[0]
        self.assertEqual(task.owner, "Claude")
        self.assertEqual(task.state, "in_progress")
        self.assertEqual(handoff_guard.structure_findings(moved), [])

    def test_mark_in_progress_leaves_a_completed_entry_alone(self) -> None:
        done = MINIMAL_LEDGER.replace("- [ ] Completed", "- [x] Completed").replace(
            "- [ ] Finish the work.", "- [x] Finish the work.")
        moved = handoff_guard.reassign_task(
            done, 3, "2026-09-06 - Existing task (owner: Codex)", "Claude",
            mark_in_progress=True,
        )
        self.assertEqual(handoff_guard.parse_tasks(moved)[0].state, "completed")

    def test_a_fenced_example_is_never_mistaken_for_the_task_to_move(self) -> None:
        text = MINIMAL_LEDGER + """
```md
## 2026-09-06 - Template (owner: agent)

Status: Example.
```
"""
        moved = handoff_guard.reassign_task(
            text, 3, "2026-09-06 - Existing task (owner: Codex)", "Claude",
            "Reassigned: Codex to Claude.",
        )
        # The note belongs to the real task, not to the fenced example below it.
        self.assertLess(moved.index("Reassigned:"), moved.index("```md"))
        self.assertIn("## 2026-09-06 - Template (owner: agent)", moved)


class SwapLedgerTests(unittest.TestCase):
    """Every writer shares one compare-and-swap, so a viewer's move is refused on
    the same terms as an apply."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Path(self.directory.name) / "HANDOFF.md"
        self.ledger.write_text(MINIMAL_LEDGER, encoding="utf-8")

    def version(self) -> str:
        return handoff_guard.ledger_version(self.ledger.read_text(encoding="utf-8"))

    def test_a_stale_version_conflicts_and_writes_nothing(self) -> None:
        stale = self.version()
        self.ledger.write_text(MINIMAL_LEDGER + "\nA peer wrote this.\n", encoding="utf-8")
        peer = self.ledger.read_text(encoding="utf-8")
        result = handoff_guard.swap_ledger(self.ledger, stale, lambda text: "# Wiped\n")
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), peer)

    def test_a_write_that_would_break_structure_is_refused(self) -> None:
        result = handoff_guard.swap_ledger(
            self.ledger, self.version(),
            lambda text: text.replace("- [ ] Finish the work.", "- [x] Finish the work.")
                             .replace("- [ ] Completed", "- [x] Completed")
                             .replace("- [x] In progress", "- [ ] In progress"),
        )
        self.assertEqual(result["status"], "rejected")
        self.assertTrue(result["errors"])
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), MINIMAL_LEDGER)

    def test_an_applied_swap_reports_the_version_the_next_writer_needs(self) -> None:
        result = handoff_guard.swap_ledger(
            self.ledger, self.version(),
            lambda text: handoff_guard.reassign_task(
                text, 3, "2026-09-06 - Existing task (owner: Codex)", "Claude"),
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["new_version"], self.version())
        self.assertIn("(owner: Claude)", self.ledger.read_text(encoding="utf-8"))


class PurgeTests(unittest.TestCase):
    """Purge empties the ledger through swap_ledger and keeps the file."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text(MINIMAL_LEDGER, encoding="utf-8")

    def version(self) -> str:
        return handoff_guard.ledger_version(self.ledger.read_text(encoding="utf-8"))

    def run_purge(self, *args: str) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "purge", "--root", str(self.root), *args],
            capture_output=True,
            text=True, encoding="utf-8",
            check=False,
        )
        return result.returncode, result.stdout, result.stderr

    def run_purge_json(self, *args: str) -> tuple[int, dict]:
        code, stdout, stderr = self.run_purge("--json", *args)
        self.assertFalse(stderr, stderr)
        return code, json.loads(stdout)

    def test_empty_ledger_is_structurally_valid(self) -> None:
        self.assertEqual(handoff_guard.structure_findings(handoff_guard.EMPTY_LEDGER), [])

    def test_purge_empties_the_ledger_and_archives_the_previous_bytes(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        version = self.version()
        code, result = self.run_purge_json(
            "--expect-version", version, "--confirm", "purge",
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), handoff_guard.EMPTY_LEDGER)
        self.assertTrue(self.ledger.exists())
        archive = Path(result["archive"])
        self.assertEqual(archive.name, f"HANDOFF.md.{version[:12]}.bak")
        self.assertEqual(archive.resolve().parent, self.ledger.resolve().parent)
        self.assertEqual(archive.read_text(encoding="utf-8"), before)
        self.assertEqual(result["new_version"], self.version())

    def test_purge_refuses_to_run_without_confirm(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        code, stdout, stderr = self.run_purge("--expect-version", self.version())
        self.assertEqual(code, 2)
        self.assertIn("--confirm", stderr)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)
        self.assertEqual(list(self.root.glob("HANDOFF.md.*.bak")), [])

    def test_purge_errors_when_the_ledger_is_missing_and_creates_nothing(self) -> None:
        self.ledger.unlink()
        code, result = self.run_purge_json(
            "--expect-version", "0" * 64, "--confirm", "purge",
        )
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertFalse(self.ledger.exists())
        self.assertEqual(list(self.root.glob("HANDOFF.md.*.bak")), [])
        self.assertIn("does not create a ledger", result["note"])

    def test_stale_version_conflicts_and_writes_neither_ledger_nor_archive(self) -> None:
        stale = self.version()
        self.ledger.write_text(MINIMAL_LEDGER + "\nA peer wrote this.\n", encoding="utf-8")
        peer = self.ledger.read_text(encoding="utf-8")
        code, result = self.run_purge_json(
            "--expect-version", stale, "--confirm", "purge",
        )
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), peer)
        self.assertIsNone(result.get("archive"))
        self.assertEqual(list(self.root.glob("HANDOFF.md.*.bak")), [])

    def test_dry_run_reports_without_writing_ledger_or_archive(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        code, result = self.run_purge_json(
            "--expect-version", self.version(), "--confirm", "purge", "--dry-run",
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)
        self.assertIsNone(result.get("archive"))
        self.assertEqual(list(self.root.glob("HANDOFF.md.*.bak")), [])

    def test_no_archive_empties_the_ledger_without_a_sidecar(self) -> None:
        code, result = self.run_purge_json(
            "--expect-version", self.version(), "--confirm", "purge", "--no-archive",
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), handoff_guard.EMPTY_LEDGER)
        self.assertIsNone(result.get("archive"))
        self.assertEqual(list(self.root.glob("HANDOFF.md.*.bak")), [])

    def test_custom_archive_path_is_used(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        archive = self.root / "kept.md"
        code, result = self.run_purge_json(
            "--expect-version", self.version(), "--confirm", "purge",
            "--archive", str(archive),
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["archive"], str(archive))
        self.assertEqual(archive.read_text(encoding="utf-8"), before)
        self.assertEqual(list(self.root.glob("HANDOFF.md.*.bak")), [])

    def test_existing_different_archive_refuses_and_leaves_the_ledger(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        archive = self.root / "kept.md"
        archive.write_text("someone else's backup\n", encoding="utf-8")
        code, result = self.run_purge_json(
            "--expect-version", self.version(), "--confirm", "purge",
            "--archive", str(archive),
        )
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)
        self.assertEqual(archive.read_text(encoding="utf-8"), "someone else's backup\n")

    def test_matching_archive_from_a_crashed_attempt_is_reusable(self) -> None:
        before = self.ledger.read_text(encoding="utf-8")
        archive = self.root / "kept.md"
        archive.write_text(before, encoding="utf-8")
        code, result = self.run_purge_json(
            "--expect-version", self.version(), "--confirm", "purge",
            "--archive", str(archive),
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), handoff_guard.EMPTY_LEDGER)
        self.assertEqual(archive.read_text(encoding="utf-8"), before)

    @unittest.skipIf(sys.platform == "win32", "Windows has no POSIX permission bits")
    def test_purge_preserves_the_ledger_file_mode(self) -> None:
        os.chmod(self.ledger, 0o644)
        code, _ = self.run_purge_json(
            "--expect-version", self.version(), "--confirm", "purge",
        )
        self.assertEqual(code, 0)
        self.assertEqual(os.stat(self.ledger).st_mode & 0o777, 0o644)


if __name__ == "__main__":
    unittest.main()


class HarnessFieldTests(unittest.TestCase):
    """The optional `(harness: ...)` heading field beside the owner label."""

    def heading(self, text):
        body = ("# Handoff\n\n## " + text + "\n\nState:\n\n- [x] In progress\n"
                "- [ ] Completed\n\nSteps:\n\n- [x] Done.\n\nStatus: Recorded.\n")
        return handoff_guard.parse_tasks(body)[0]

    def test_harness_is_parsed_beside_the_owner_and_stays_optional(self):
        task = self.heading("2026-09-09 - T (owner: Daedalus) (harness: Claude Code)")
        self.assertEqual((task.owner, task.harness), ("Daedalus", "Claude Code"))
        plain = self.heading("2026-09-09 - T (owner: Daedalus)")
        self.assertEqual((plain.owner, plain.harness), ("Daedalus", None))
        self.assertEqual(plain.errors, [])

    def test_owner_name_never_absorbs_the_harness_field(self):
        task = self.heading("2026-09-09 - T (owner: Daedalus) (harness: Codex)")
        self.assertEqual(task.owner, "Daedalus")

    def test_reassigning_drops_the_previous_owners_harness(self):
        heading = "2026-09-09 - T (owner: Cernunnos) (harness: Codex)"
        self.assertEqual(handoff_guard.replace_owner(heading, "Daedalus"),
                         "2026-09-09 - T (owner: Daedalus)")
        # Removing the owner entirely also removes a harness that described it.
        self.assertEqual(handoff_guard.replace_owner(heading, None),
                         "2026-09-09 - T")

    def test_template_records_a_harness_only_when_asked(self):
        with_harness = handoff_guard.make_template("2026-09-09", "T", "Daedalus",
                                                   ["step"], "Claude Code")
        self.assertIn("(owner: Daedalus) (harness: Claude Code)", with_harness)
        without = handoff_guard.make_template("2026-09-09", "T", "Daedalus", ["step"])
        self.assertIn("(owner: Daedalus)\n", without)
        self.assertNotIn("harness", without)
        self.assertEqual(handoff_guard.parse_tasks(with_harness)[0].errors, [])

    def test_detection_prefers_an_explicit_override(self):
        with unittest.mock.patch.dict(os.environ, {"HANDOFF_HARNESS": "Weird Tool",
                                     "CLAUDECODE": "1"}, clear=True):
            self.assertEqual(handoff_guard.detect_harness(), "Weird Tool")
        with unittest.mock.patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=True):
            self.assertEqual(handoff_guard.detect_harness(), "Claude Code")
        with unittest.mock.patch.dict(os.environ, {"CODEX_HOME": "/x"}, clear=True):
            self.assertEqual(handoff_guard.detect_harness(), "Codex")
        with unittest.mock.patch.dict(os.environ, {"TERM_PROGRAM": "vscode",
                                     "CURSOR_TRACE_ID": "z"}, clear=True):
            self.assertEqual(handoff_guard.detect_harness(), "Cursor")
        with unittest.mock.patch.dict(os.environ, {"TERM_PROGRAM": "iTerm.app"}, clear=True):
            self.assertIsNone(handoff_guard.detect_harness())

    def test_recent_claims_orders_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "older").write_text("Alpha\nCodex\n", encoding="utf-8")
            (cache / "newer").write_text("Beta\nCursor\n", encoding="utf-8")
            now = time.time()
            os.utime(cache / "older", (now - 120, now - 120))
            os.utime(cache / "newer", (now - 30, now - 30))
            self.assertEqual(handoff_guard.recent_claims(cache),
                             [("Beta", "Cursor"), ("Alpha", "Codex")])

    def test_recent_sessions_report_their_harness_within_a_short_window(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "one").write_text("Daedalus\nClaude Code\n", encoding="utf-8")
            # An older record format, from before the harness was recorded.
            (cache / "two").write_text("Bakunawa\n", encoding="utf-8")
            (cache / "empty").write_text("", encoding="utf-8")
            self.assertEqual(handoff_guard.held_sessions(cache),
                             {"Daedalus": "Claude Code", "Bakunawa": ""})
            # The name reservation window is far longer than the recency window;
            # a claim old enough to have stopped must not be reported.
            old = time.time() - handoff_guard.RECENT_CLAIM_SECONDS - 60
            os.utime(cache / "one", (old, old))
            self.assertNotIn("Daedalus", handoff_guard.held_sessions(cache))
            self.assertIn("Daedalus", handoff_guard.held_names(cache, cache / "none"))

    def test_an_empty_record_does_not_break_name_claiming(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / "empty").write_text("", encoding="utf-8")
            self.assertEqual(handoff_guard.held_names(cache, cache / "none"), set())


class SessionNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = self.root / "HANDOFF.md"
        self.ledger.write_text(MINIMAL_LEDGER, encoding="utf-8")
        self.cache = self.root / "names"
        # In-process calls read the environment too; without this they would
        # claim names in the developer's own cache directory.
        patch = unittest.mock.patch.dict(os.environ, {"HANDOFF_NAME_CACHE": str(self.cache)})
        patch.start()
        self.addCleanup(patch.stop)

    def run_name(self, *args: str, cache: Path | None = None) -> str:
        environment = dict(os.environ)
        environment["HANDOFF_NAME_CACHE"] = str(cache or self.cache)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "name", "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", check=True, env=environment,
        )
        return result.stdout.strip()

    def test_the_roster_is_a_hundred_distinct_single_word_names(self) -> None:
        names = handoff_guard.MYTHIC_NAMES
        self.assertEqual(len(names), 100)
        self.assertEqual(len(set(names)), 100)
        for name in names:
            with self.subTest(name=name):
                # A label crosses headings, tmux formats, and clipped columns.
                self.assertTrue(name.isascii() and name.isalpha(), name)
                self.assertIsNone(handoff_guard.owner_label_error(name))

    def test_a_session_keeps_its_name_across_calls_and_differs_from_others(self) -> None:
        first = self.run_name("--seed", "session-one")
        self.assertEqual(first, self.run_name("--seed", "session-one"))
        self.assertIn(first, handoff_guard.MYTHIC_NAMES)
        self.assertNotEqual(first, self.run_name("--seed", "session-two"))

    def test_a_name_is_kept_after_the_session_writes_it_into_the_ledger(self) -> None:
        # Without the record, an agent re-running preflight after recording its
        # own entry would be handed a second name for the same session.
        name = self.run_name("--seed", "session-one")
        self.ledger.write_text(
            handoff_guard.make_template("2026-09-08", "Task", name, ["Do the work."]),
            encoding="utf-8")
        self.assertEqual(self.run_name("--seed", "session-one"), name)

    def test_a_name_an_owner_already_holds_is_never_handed_out_again(self) -> None:
        wanted = handoff_guard.names_starting_with("A")[0]
        self.ledger.write_text(
            handoff_guard.make_template("2026-09-08", "Task", wanted, ["Do the work."]),
            encoding="utf-8")
        chosen = self.run_name("--seed", "session-one")
        self.assertNotEqual(chosen, wanted)
        self.assertEqual(chosen, handoff_guard.names_starting_with("A")[1])

    def test_a_completed_owner_still_holds_its_name(self) -> None:
        wanted = handoff_guard.names_starting_with("A")[0]
        self.ledger.write_text(
            f"# Handoff\n\n## 2026-09-08 - Done (owner: {wanted})\n\nState:\n\n"
            "- [x] In progress\n- [x] Completed\n\nSteps:\n\n- [x] Done.\n\n"
            "Status: Complete.\n", encoding="utf-8")
        self.assertNotEqual(self.run_name("--seed", "session-one"), wanted)

    def test_two_unrecorded_sessions_cycle_a_to_b(self) -> None:
        # First come, first served: the first session claims an A name, the next a B name.
        first = handoff_guard.claim_name("session-one", self.ledger, set())[0]
        second = handoff_guard.claim_name("session-two", self.ledger, set())[0]
        self.assertEqual(first, handoff_guard.names_starting_with("A")[0])
        self.assertEqual(second, handoff_guard.names_starting_with("B")[0])
        self.assertNotEqual(second, first)

    def test_an_exhausted_roster_numbers_repeats_instead_of_failing(self) -> None:
        order = list(handoff_guard.MYTHIC_NAMES)
        self.assertEqual(handoff_guard.free_name(order, set(order)), order[0] + " 2")
        self.assertEqual(
            handoff_guard.free_name(order, set(order) | {order[0] + " 2"}), order[1] + " 2")

    def test_an_unwritable_cache_still_names_the_session(self) -> None:
        unwritable = self.root / "missing" / "cache"
        with unittest.mock.patch.object(Path, "mkdir", side_effect=OSError("read-only")):
            name, remembered = handoff_guard.claim_name("session-one", self.ledger, set(),)
        self.assertIn(name, handoff_guard.MYTHIC_NAMES)
        self.assertFalse(remembered)
        self.assertFalse(unwritable.exists())

    def test_a_repository_with_no_ledger_still_names_the_session(self) -> None:
        self.ledger.unlink()
        self.assertIn(self.run_name("--seed", "session-one"), handoff_guard.MYTHIC_NAMES)

    def test_json_reports_the_ledger_the_name_belongs_to(self) -> None:
        report = json.loads(self.run_name("--seed", "session-one", "--json"))
        # Compare resolved paths: macOS reports this temp path under /private.
        self.assertEqual(Path(report["ledger"]).resolve(), self.ledger.resolve())
        self.assertEqual(report["roster"], 100)
        self.assertFalse(report["remembered"])
        self.assertTrue(json.loads(self.run_name("--seed", "session-one", "--json"))["remembered"])

    def test_the_host_session_id_names_the_session_when_no_seed_is_given(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"HANDOFF_SESSION": "from-the-host"}):
            self.assertEqual(handoff_guard.session_seed(), "from-the-host")
            self.assertEqual(handoff_guard.session_seed("explicit"), "explicit")
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "host-id"}):
            os.environ.pop("HANDOFF_SESSION", None)
            self.assertEqual(handoff_guard.session_seed(), "host-id")
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            # An unidentified session gets a distinct seed, not a shared one.
            self.assertNotEqual(handoff_guard.session_seed(), handoff_guard.session_seed())

    def test_a_stale_claim_stops_reserving_its_name(self) -> None:
        wanted = handoff_guard.names_starting_with("A")[0]
        slot_path = self.cache / handoff_guard.FCFS_SLOT_FILE
        self.cache.mkdir(parents=True, exist_ok=True)
        slot_path.write_text("0\n", encoding="utf-8")
        stale = self.cache / "stale-claim"
        stale.write_text(wanted + "\n", encoding="utf-8")
        aged = time.time() - handoff_guard.NAME_CLAIM_SECONDS - 60
        os.utime(stale, (aged, aged))
        self.assertEqual(self.run_name("--seed", "session-one"), wanted)

    def test_fcfs_wraps_from_z_back_to_a(self) -> None:
        slot_path = self.cache / handoff_guard.FCFS_SLOT_FILE
        slot_path.parent.mkdir(parents=True, exist_ok=True)
        slot_path.write_text("26\n", encoding="utf-8")
        chosen = handoff_guard.claim_name("wrap-session", self.ledger, set())[0]
        self.assertEqual(chosen, handoff_guard.names_starting_with("A")[0])

    def test_recall_name_reads_without_claiming(self) -> None:
        claimed = handoff_guard.claim_name("session-one", self.ledger, set())[0]
        self.assertEqual(handoff_guard.recall_name("session-one", self.ledger), claimed)
        self.assertIsNone(handoff_guard.recall_name("session-two", self.ledger))

    def test_a_new_name_claim_invalidates_the_bar_cache(self) -> None:
        bar_cache = self.root / "bar-cache"
        bar_cache.mkdir(parents=True, exist_ok=True)
        prefix = handoff_guard.bar_cache_key(self.ledger)
        legacy = bar_cache / prefix
        per_session = bar_cache / f"{prefix}-session-a"
        legacy.write_text("stale\nrow\n", encoding="utf-8")
        per_session.write_text("stale\nrow\n", encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"HANDOFF_BAR_CACHE": str(bar_cache)}):
            handoff_guard.claim_name("session-one", self.ledger, set())
        self.assertFalse(legacy.exists())
        self.assertFalse(per_session.exists())


class LeaseTests(unittest.TestCase):
    """A lease is the owner's own contingent release, and expiry is arithmetic.

    The failure case: no signal for an exhausted model exists on every harness,
    and silence cannot separate an exhausted agent from an idle healthy one, so a
    peer either waits forever or takes work from an owner who comes back writing.
    A deadline the owner declared is decidable by every peer from the same bytes.
    """

    PAST = "2020-01-01T00:00:00Z"
    FUTURE = "2099-01-01T00:00:00Z"

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = self.root / "HANDOFF.md"

    def entry(self, title: str, owner: str, lease: str | None = None,
              completed: bool = False) -> str:
        text = handoff_guard.make_template("2026-09-09", title, owner, ["Do the work."])
        text = text.replace("- [ ] In progress", "- [x] In progress", 1)
        if completed:
            text = text.replace("- [ ] Completed", "- [x] Completed", 1)
            text = text.replace("- [ ] Do the work.", "- [x] Do the work.", 1)
        return text + (f"\n{lease}\n" if lease else "")

    def write(self, *entries: str) -> str:
        self.ledger.write_text("# Handoff\n\n" + "\n".join(entries), encoding="utf-8")
        return handoff_guard.ledger_version(self.ledger.read_text(encoding="utf-8"))

    def lease_line(self, owner: str, expires: str, policy: str = "release") -> str:
        return f"Lease: owner={owner}; expires={expires}; policy={policy}"

    def run_guard(self, *args: str) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--root", str(self.root)],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        return result.returncode, json.loads(result.stdout)

    def states(self) -> list[str]:
        text = self.ledger.read_text(encoding="utf-8")
        return [handoff_guard.lease_state(task) for task in handoff_guard.parse_tasks(text)]

    def test_a_lease_parses_without_disturbing_structure(self) -> None:
        self.write(self.entry("One", "Alpha", self.lease_line("Alpha", self.FUTURE)))
        text = self.ledger.read_text(encoding="utf-8")
        self.assertEqual(handoff_guard.structure_findings(text), [])
        task = handoff_guard.parse_tasks(text)[0]
        self.assertEqual(task.lease.owner, "Alpha")
        self.assertEqual(task.lease.policy, "release")
        self.assertEqual(handoff_guard.lease_state(task), "active")

    def test_a_lease_naming_another_owner_is_a_structural_error(self) -> None:
        self.write(self.entry("One", "Alpha", self.lease_line("Beta", self.FUTURE)))
        text = self.ledger.read_text(encoding="utf-8")
        errors = [error for _, error, _ in handoff_guard.structure_findings(text)]
        self.assertIn("lease owner does not match the heading owner", errors)
        self.assertEqual(self.states(), ["invalid"])

    def test_a_deadline_without_utc_is_invalid_rather_than_expired(self) -> None:
        # A local-time deadline resolves differently on two machines reading the
        # same ledger, so it authorizes nothing instead of expiring somewhere.
        for expires in ("2020-01-01 00:00:00", "2020-01-01T00:00:00", "yesterday"):
            self.write(self.entry("One", "Alpha", self.lease_line("Alpha", expires)))
            self.assertEqual(self.states(), ["invalid"], expires)
            errors = [error for _, error, _ in
                      handoff_guard.structure_findings(self.ledger.read_text(encoding="utf-8"))]
            self.assertIn("lease expiry is not an ISO-8601 UTC timestamp", errors)

    def test_an_unsupported_policy_is_invalid(self) -> None:
        self.write(self.entry("One", "Alpha", self.lease_line("Alpha", self.FUTURE, "transfer")))
        self.assertEqual(self.states(), ["invalid"])

    def test_a_completed_task_may_not_carry_a_lease(self) -> None:
        self.write(self.entry("One", "Alpha", self.lease_line("Alpha", self.PAST), completed=True))
        errors = [error for _, error, _ in
                  handoff_guard.structure_findings(self.ledger.read_text(encoding="utf-8"))]
        self.assertIn("completed task carries a lease; clear it with "
                      "lease --clear before recording completion", errors)
        self.assertEqual(self.states(), ["invalid"])

    def test_a_lease_inside_a_fence_is_documentation_not_a_claim(self) -> None:
        self.ledger.write_text(
            "# Handoff\n\n```md\n" + self.lease_line("Alpha", self.PAST) + "\n```\n\n"
            + self.entry("One", "Alpha"), encoding="utf-8")
        self.assertEqual(self.states(), ["none"])

    def test_lease_covers_the_whole_unfinished_bucket_and_skips_completed_work(self) -> None:
        version = self.write(self.entry("One", "Alpha"), self.entry("Two", "Alpha"),
                             self.entry("Done", "Alpha", completed=True),
                             self.entry("Peer", "Beta"))
        code, result = self.run_guard("lease", "--owner", "Alpha", "--hours", "6",
                                      "--expect-version", version)
        self.assertEqual(code, 0)
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(self.states(), ["active", "active", "none", "none"])

    def test_renewing_replaces_the_line_instead_of_adding_a_second(self) -> None:
        version = self.write(self.entry("One", "Alpha"))
        _, first = self.run_guard("lease", "--owner", "Alpha", "--hours", "1",
                                  "--expect-version", version)
        _, second = self.run_guard("lease", "--owner", "Alpha", "--hours", "8",
                                   "--expect-version", first["new_version"])
        self.assertEqual(second["status"], "applied")
        text = self.ledger.read_text(encoding="utf-8")
        self.assertEqual(text.count("Lease: owner=Alpha"), 1)
        self.assertNotEqual(first["lease"], second["lease"])
        self.assertEqual(self.states(), ["active"])

    def test_clearing_a_lease_restores_the_original_bytes(self) -> None:
        version = self.write(self.entry("One", "Alpha"))
        before = self.ledger.read_text(encoding="utf-8")
        _, applied = self.run_guard("lease", "--owner", "Alpha", "--hours", "6",
                                    "--expect-version", version)
        code, _ = self.run_guard("lease", "--owner", "Alpha", "--clear",
                                 "--expect-version", applied["new_version"])
        self.assertEqual(code, 0)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_lease_without_an_owner_reports_state_and_writes_nothing(self) -> None:
        self.write(self.entry("One", "Alpha", self.lease_line("Alpha", self.PAST)))
        before = self.ledger.read_text(encoding="utf-8")
        code, result = self.run_guard("lease")
        self.assertEqual(code, 0)
        self.assertEqual([row["state"] for row in result["leases"]], ["expired"])
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_sweep_releases_only_the_expired_lease_and_records_the_expiry(self) -> None:
        version = self.write(self.entry("Expired", "Alpha", self.lease_line("Alpha", self.PAST)),
                             self.entry("Active", "Beta", self.lease_line("Beta", self.FUTURE)),
                             self.entry("Unleased", "Gamma"))
        code, result = self.run_guard("sweep", "--expect-version", version)
        self.assertEqual(code, 0)
        self.assertEqual(len(result["released_tasks"]), 1)
        text = self.ledger.read_text(encoding="utf-8")
        tasks = handoff_guard.parse_tasks(text)
        self.assertEqual([task.owner for task in tasks], [None, "Beta", "Gamma"])
        # Order records when work was raised, so a release must not reorder it.
        self.assertEqual([task.heading.split(" - ")[1].split(" (")[0] for task in tasks],
                         ["Expired", "Active", "Unleased"])
        self.assertNotIn("Lease: owner=Alpha", text)
        self.assertIn("Released", text)
        self.assertIn("child writers were not verified", text)
        self.assertEqual(handoff_guard.structure_findings(text), [])

    def test_sweep_writes_nothing_when_no_lease_has_expired(self) -> None:
        version = self.write(self.entry("One", "Alpha", self.lease_line("Alpha", self.FUTURE)))
        before = self.ledger.read_text(encoding="utf-8")
        code, result = self.run_guard("sweep", "--expect-version", version)
        self.assertEqual(code, 0)
        self.assertEqual(result["released_tasks"], [])
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_sweep_leaves_an_invalid_lease_alone(self) -> None:
        # An unreadable deadline is not a release anyone authorized.
        version = self.write(self.entry("One", "Alpha", self.lease_line("Alpha", "2020-01-01")))
        before = self.ledger.read_text(encoding="utf-8")
        code, result = self.run_guard("sweep", "--expect-version", version)
        self.assertEqual((code, result["released_tasks"]), (0, []))
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_sweep_on_a_stale_version_releases_nothing(self) -> None:
        version = self.write(self.entry("One", "Alpha", self.lease_line("Alpha", self.PAST)))
        self.write(self.entry("One", "Alpha", self.lease_line("Alpha", self.PAST)),
                   self.entry("Two", "Beta"))
        before = self.ledger.read_text(encoding="utf-8")
        code, result = self.run_guard("sweep", "--expect-version", version)
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)

    def test_lease_refuses_an_owner_with_no_unfinished_work(self) -> None:
        version = self.write(self.entry("Done", "Alpha", completed=True))
        code, result = self.run_guard("lease", "--owner", "Alpha", "--expect-version", version)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")

    def test_writing_a_lease_without_a_version_is_a_usage_error(self) -> None:
        self.write(self.entry("One", "Alpha"))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "lease", "--root", str(self.root), "--owner", "Alpha"],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("--expect-version is required", result.stderr)


class AssignedPendingTests(unittest.TestCase):
    """Work recorded to an owner that nobody has started.

    The failure case: the user assigns a task from the viewer, which writes the
    owner label and leaves both state boxes unchecked. Nothing else in the
    system could name that situation, so no surface could report it.
    """

    def tasks(self, text):
        return handoff_guard.parse_tasks(text)

    def entry(self, title, owner, state="pending"):
        text = handoff_guard.make_template("2026-09-10", title, owner, ["Build it.", "Verify it."])
        if state == "in_progress":
            return text.replace("- [ ] In progress", "- [x] In progress")
        if state == "completed":
            return text.replace("- [ ]", "- [x]")
        return text

    def test_a_pending_task_is_reported_to_its_own_owner_only(self):
        text = "# Handoff\n\n" + self.entry("Settings page", "Beta")
        tasks = self.tasks(text)
        self.assertEqual([task.heading for task in handoff_guard.assigned_pending(tasks, "Beta")],
                         [task.heading for task in tasks])
        self.assertEqual(handoff_guard.assigned_pending(tasks, "Alpha"), [])

    def test_starting_the_task_clears_it(self):
        started = self.tasks("# Handoff\n\n" + self.entry("Settings page", "Beta", "in_progress"))
        self.assertEqual(handoff_guard.assigned_pending(started, "Beta"), [])
        done = self.tasks("# Handoff\n\n" + self.entry("Settings page", "Beta", "completed"))
        self.assertEqual(handoff_guard.assigned_pending(done, "Beta"), [])

    def test_no_owner_reports_nothing_rather_than_everything(self):
        tasks = self.tasks("# Handoff\n\n" + self.entry("Settings page", "Beta"))
        for owner in (None, ""):
            self.assertEqual(handoff_guard.assigned_pending(tasks, owner), [])

    def test_a_malformed_entry_is_not_reported_as_an_assignment(self):
        broken = ("## 2026-09-10 - Broken (owner: Beta) (harness: Codex)\n\nState:\n\n"
                  "- [ ] In progress\n- [x] Completed\n\nSteps:\n\n- [ ] Verify it.\n\n"
                  "Status: Completed box checked with progress unchecked.\n")
        tasks = self.tasks("# Handoff\n\n" + broken)
        self.assertTrue(tasks[0].errors)
        self.assertEqual(handoff_guard.assigned_pending(tasks, "Beta"), [])

    def test_several_assignments_are_all_reported_in_ledger_order(self):
        text = ("# Handoff\n\n" + self.entry("Newest", "Beta") + "\n"
                + self.entry("Older", "Beta") + "\n" + self.entry("Someone else", "Alpha"))
        names = [task.heading for task in handoff_guard.assigned_pending(self.tasks(text), "Beta")]
        self.assertEqual(len(names), 2)
        self.assertIn("Newest", names[0])
        self.assertIn("Older", names[1])


class AssignedUnstartedTests(unittest.TestCase):
    def entry(self, title, owner, state="pending", steps=(False, False)):
        labels = ["Build it.", "Verify it."]
        text = handoff_guard.make_template("2026-09-10", title, owner, labels)
        if state == "in_progress":
            text = text.replace("- [ ] In progress", "- [x] In progress")
        if state == "completed":
            text = text.replace("- [ ]", "- [x]")
        for label, done in zip(labels, steps):
            if done:
                text = text.replace(f"- [ ] {label}", f"- [x] {label}")
        return text

    def test_a_viewer_hand_off_with_no_steps_counts_as_unstarted(self):
        text = "# Handoff\n\n" + self.entry("Settings page", "Beta", "in_progress", (False, False))
        tasks = handoff_guard.parse_tasks(text)
        self.assertEqual(handoff_guard.assigned_unstarted(tasks, "Beta"), tasks)
        self.assertEqual(handoff_guard.assigned_pending(tasks, "Beta"), [])

    def test_checking_a_step_clears_an_in_progress_hand_off(self):
        text = "# Handoff\n\n" + self.entry("Settings page", "Beta", "in_progress", (True, False))
        tasks = handoff_guard.parse_tasks(text)
        self.assertEqual(handoff_guard.assigned_unstarted(tasks, "Beta"), [])


class PreflightTests(unittest.TestCase):
    """One call must answer preflight without re-reading the ledger per step.

    The failure case: a session ran name, read, doctor, and git separately, so a
    long ledger was parsed several times and every finished entry was returned
    in full. That is slow, and the separate reads let a peer write land between
    two of them, binding an audit of old text to a newer version.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = self.root / "HANDOFF.md"
        self.cache = self.root / "names"
        patch = unittest.mock.patch.dict(
            os.environ, {"HANDOFF_NAME_CACHE": str(self.cache)})
        patch.start()
        self.addCleanup(patch.stop)

    def entry(self, title: str, owner: str, state: str = "pending") -> str:
        text = handoff_guard.make_template(
            "2026-09-10", title, owner, ["Build it.", "Verify it."])
        if state == "in_progress":
            text = text.replace("- [ ] In progress", "- [x] In progress")
        if state == "completed":
            text = text.replace("- [ ]", "- [x]")
        return text.replace(
            "Status: Pending. No work has started.", f"Status: {title} is {state}.")

    def write(self, *entries: str) -> None:
        self.ledger.write_text("# Handoff\n\n" + "\n".join(entries), encoding="utf-8")

    def run_preflight(self, *args: str) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "preflight", "--root", str(self.root), *args],
            capture_output=True, text=True, encoding="utf-8", check=False,
            env={**os.environ, "HANDOFF_NAME_CACHE": str(self.cache)},
        )
        return result.returncode, json.loads(result.stdout)

    def test_one_call_returns_the_name_version_and_digest_together(self) -> None:
        self.write(self.entry("Open work", "Alpha", "in_progress"),
                   self.entry("Old work", "Beta", "completed"))
        code, result = self.run_preflight("--seed", "session-one")
        self.assertEqual(code, 0)
        self.assertIn(result["session"]["name"], handoff_guard.MYTHIC_NAMES)
        self.assertEqual(
            result["version"],
            handoff_guard.ledger_version(self.ledger.read_text(encoding="utf-8")))
        self.assertEqual(result["digest"]["counts"],
                         {"total": 2, "open": 1, "completed": 1})
        self.assertEqual(result["errors"], [])

    def test_the_version_belongs_to_the_digest_it_was_returned_with(self) -> None:
        # The whole point of one snapshot: a later peer write must not make the
        # returned version describe text the audit never saw.
        self.write(self.entry("Open work", "Alpha", "in_progress"))
        _, first = self.run_preflight("--seed", "session-one")
        self.write(self.entry("Peer work", "Gamma", "in_progress"),
                   self.entry("Open work", "Alpha", "in_progress"))
        _, second = self.run_preflight("--seed", "session-one")
        self.assertNotEqual(first["version"], second["version"])
        self.assertEqual(len(first["digest"]["open_tasks"]), 1)
        self.assertEqual(len(second["digest"]["open_tasks"]), 2)

    def test_open_entries_keep_their_steps_and_finished_ones_are_summarized(self) -> None:
        self.write(self.entry("Open work", "Alpha", "in_progress"),
                   self.entry("Old work", "Beta", "completed"))
        _, result = self.run_preflight("--seed", "session-one")
        open_task = result["digest"]["open_tasks"][0]
        self.assertEqual([step["text"] for step in open_task["steps"]],
                         ["Build it.", "Verify it."])
        self.assertEqual(open_task["steps_done"], "0/2")
        done = result["digest"]["recent_completed"][0]
        self.assertNotIn("steps", done)
        self.assertEqual(done["status"], "Old work is completed.")
        self.assertEqual(done["steps_done"], "2/2")

    def test_finished_history_is_capped_newest_first_and_the_rest_counted(self) -> None:
        entries = [self.entry(f"Task {index}", "Beta", "completed") for index in range(6)]
        self.write(*entries)
        _, result = self.run_preflight("--seed", "session-one", "--completed", "2")
        shown = [task["heading"] for task in result["digest"]["recent_completed"]]
        self.assertEqual(len(shown), 2)
        self.assertIn("Task 0", shown[0])
        self.assertIn("Task 1", shown[1])
        self.assertEqual(result["digest"]["completed_omitted"], 4)

        _, everything = self.run_preflight("--seed", "session-one", "--completed", "-1")
        self.assertEqual(len(everything["digest"]["recent_completed"]), 6)
        self.assertEqual(everything["digest"]["completed_omitted"], 0)

    def test_a_malformed_finished_entry_is_reported_as_open_work(self) -> None:
        # A completed entry with unchecked steps is not settled history; hiding
        # it in the summarized tail would hide the thing that needs deciding.
        broken = self.entry("Broken", "Beta", "completed").replace(
            "- [x] Verify it.", "- [ ] Verify it.")
        self.write(broken)
        code, result = self.run_preflight("--seed", "session-one")
        self.assertEqual(code, 0)
        self.assertEqual(result["digest"]["counts"]["open"], 1)
        self.assertTrue(result["errors"])
        self.assertIn("completed task has unchecked steps",
                      result["digest"]["open_tasks"][0]["errors"])

    def test_work_assigned_to_this_session_is_named_back_to_it(self) -> None:
        _, first = self.run_preflight("--seed", "session-one")
        name = first["session"]["name"]
        self.write(self.entry("Handed over", name, "in_progress"))
        _, result = self.run_preflight("--seed", "session-one")
        self.assertTrue(result["session"]["remembered"])
        self.assertEqual(result["session"]["name"], name)
        self.assertEqual(len(result["assigned_unstarted"]), 1)

    def test_a_missing_ledger_still_names_the_session_and_says_so(self) -> None:
        code, result = self.run_preflight("--seed", "session-one")
        self.assertEqual(code, 1)
        self.assertIsNone(result["ledger"])
        self.assertIsNone(result["version"])
        self.assertIn(result["session"]["name"], handoff_guard.MYTHIC_NAMES)
        self.assertEqual(result["errors"], ["HANDOFF.md not found"])

    def test_preflight_never_writes_the_ledger(self) -> None:
        self.write(self.entry("Open work", "Alpha", "in_progress"))
        before = self.ledger.read_bytes()
        self.run_preflight("--seed", "session-one")
        self.assertEqual(self.ledger.read_bytes(), before)
