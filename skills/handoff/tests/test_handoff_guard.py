from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
