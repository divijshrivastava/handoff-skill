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
    between agents must change that label and nothing else."""

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


if __name__ == "__main__":
    unittest.main()


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
