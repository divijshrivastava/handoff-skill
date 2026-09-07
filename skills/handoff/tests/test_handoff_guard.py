from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
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
                capture_output=True, text=True,
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
            text=True,
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


if __name__ == "__main__":
    unittest.main()
