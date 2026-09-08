from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BAR = SCRIPTS / "handoff-bar"

LEDGER = (
    "# Handoff\n\n## Task one (owner: Ann)\n\nState:\n- [x] In progress\n- [x] Completed\n\n"
    "Steps:\n- [x] Outcome.\n\nStatus: Done.\nNext action.\n\n"
    "## Task two (owner: Bo)\n\nState:\n- [x] In progress\n- [ ] Completed\n\n"
    "Steps:\n- [ ] Outcome.\n\nStatus: Open.\nNext action.\n"
)


# Same byte count as LEDGER: a checkbox flip never changes the file size.
COMPLETED = LEDGER.replace("- [ ] Completed", "- [x] Completed").replace("- [ ] Outcome.", "- [x] Outcome.")
assert len(COMPLETED) == len(LEDGER)


def run(payload, base, *args, script=None, **environment):
    env = dict(os.environ)
    env["HANDOFF_BAR_CACHE"] = str(base / "cache")
    env.pop("HANDOFF_TUI", None)
    env.update({k: str(v) for k, v in environment.items()})
    return subprocess.run(
        ["sh", str(script or BAR), *args],
        input=payload, capture_output=True, text=True, env=env, cwd=str(base),
    )


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        (self.base / "repo").mkdir()
        (self.base / "repo" / "HANDOFF.md").write_text(LEDGER, encoding="utf-8")
        self.addCleanup(self.dir.cleanup)

    def test_nested_workspace_payload(self):
        """Claude Code and Grok both send workspace.current_dir."""
        payload = json.dumps({"workspace": {"current_dir": str(self.base / "repo")}})
        result = run(payload, self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1/2 tasks", result.stdout)
        self.assertIn("Bo", result.stdout)

    def test_flat_cwd_payload(self):
        """Kimi sends a bare cwd with no workspace object."""
        payload = json.dumps({"model": "k3", "cwd": str(self.base / "repo")})
        self.assertIn("1/2 tasks", run(payload, self.base).stdout)

    def test_nested_wins_over_flat(self):
        payload = json.dumps({"cwd": str(self.base), "workspace": {"current_dir": str(self.base / "repo")}})
        self.assertIn("1/2 tasks", run(payload, self.base).stdout)

    def test_explicit_arguments_override_the_payload(self):
        payload = json.dumps({"cwd": "/nonexistent"})
        result = run(payload, self.base, "--root", str(self.base / "repo"))
        self.assertIn("1/2 tasks", result.stdout)

    def test_child_directory_finds_the_ledger_above_it(self):
        (self.base / "repo" / "src").mkdir()
        payload = json.dumps({"cwd": str(self.base / "repo" / "src")})
        self.assertIn("1/2 tasks", run(payload, self.base).stdout)

    def test_malformed_payload_is_not_fatal(self):
        for payload in ("", "not json", "{", "[]"):
            result = run(payload, self.base, "--root", str(self.base / "repo"))
            self.assertEqual(result.returncode, 0, payload)
            self.assertIn("1/2 tasks", result.stdout, payload)


class SilenceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        self.addCleanup(self.dir.cleanup)

    def test_no_ledger_prints_nothing_and_succeeds(self):
        """A status line in an unrelated repository must stay empty, not error."""
        empty = self.base / "empty"
        empty.mkdir()
        result = run(json.dumps({"cwd": str(empty)}), self.base)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_missing_viewer_prints_nothing(self):
        repo = self.base / "repo"
        repo.mkdir()
        (repo / "HANDOFF.md").write_text(LEDGER, encoding="utf-8")
        result = run(json.dumps({"cwd": str(repo)}), self.base,
                     HANDOFF_TUI=str(self.base / "absent.py"), HOME=str(self.base))
        self.assertEqual(result.returncode, 0)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.ledger = self.repo / "HANDOFF.md"
        self.ledger.write_text(LEDGER, encoding="utf-8")
        self.payload = json.dumps({"cwd": str(self.repo)})
        self.addCleanup(self.dir.cleanup)

    def test_second_run_matches_the_first(self):
        first = run(self.payload, self.base).stdout
        second = run(self.payload, self.base).stdout
        self.assertEqual(first, second)
        self.assertTrue(any((self.base / "cache").iterdir()))

    def test_cached_run_does_not_start_the_viewer(self):
        run(self.payload, self.base)
        # Point the interpreter at a failing command: a cache hit must not need it.
        cached = run(self.payload, self.base, HANDOFF_PYTHON="/nonexistent/python")
        self.assertIn("1/2 tasks", cached.stdout)

    def test_edited_ledger_invalidates_the_cache(self):
        self.assertIn("1/2 tasks", run(self.payload, self.base).stdout)
        self.ledger.write_text(COMPLETED, encoding="utf-8")
        self.assertIn("2/2 tasks", run(self.payload, self.base).stdout)

    def test_separate_ledgers_do_not_share_a_cache_entry(self):
        other = self.base / "other"
        other.mkdir()
        (other / "HANDOFF.md").write_text(COMPLETED, encoding="utf-8")
        self.assertIn("1/2 tasks", run(self.payload, self.base).stdout)
        self.assertIn("2/2 tasks", run(json.dumps({"cwd": str(other)}), self.base).stdout)


class ViewerResolutionTests(unittest.TestCase):
    """Regression: an old copy without --bar once won and blanked the row."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / "HANDOFF.md").write_text(LEDGER, encoding="utf-8")
        self.payload = json.dumps({"cwd": str(self.repo)})
        self.addCleanup(self.dir.cleanup)

    def installed(self):
        """A copy away from the scripts directory, so the sibling rule cannot apply."""
        target = self.base / "bin" / "handoff-bar"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BAR, target)
        return target

    def plant(self, *parts, supports_bar):
        target = self.base.joinpath(*parts) / "skills/handoff/scripts/handoff_tui.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        real = (SCRIPTS / "handoff_tui.py").read_text(encoding="utf-8")
        target.write_text(real if supports_bar else "import sys\nsys.exit(2)\n", encoding="utf-8")
        if supports_bar:
            for helper in ("handoff_guard.py",):
                (target.parent / helper).write_text(
                    (SCRIPTS / helper).read_text(encoding="utf-8"), encoding="utf-8")
        return target

    def test_old_copy_without_bar_is_skipped(self):
        self.plant(".agents", supports_bar=False)
        current = self.plant(".claude/plugins/cache/market/handoff/1.8.0", supports_bar=True)
        result = run(self.payload, self.base, script=self.installed(),
                     HOME=str(self.base), PATH="/usr/bin:/bin")
        self.assertIn("1/2 tasks", result.stdout)
        self.assertEqual((self.base / "cache" / "viewer").read_text().strip(), str(current))

    def test_newest_version_wins_over_an_older_install(self):
        self.plant(".claude/plugins/cache/market/handoff/1.2.0", supports_bar=True)
        newest = self.plant(".claude/plugins/cache/market/handoff/1.8.0", supports_bar=True)
        run(self.payload, self.base, script=self.installed(),
            HOME=str(self.base), PATH="/usr/bin:/bin")
        self.assertEqual((self.base / "cache" / "viewer").read_text().strip(), str(newest))

    def test_a_stale_remembered_viewer_is_replaced(self):
        current = self.plant(".claude/plugins/cache/market/handoff/1.8.0", supports_bar=True)
        (self.base / "cache").mkdir(parents=True, exist_ok=True)
        (self.base / "cache" / "viewer").write_text(str(self.base / "gone.py") + "\n", encoding="utf-8")
        result = run(self.payload, self.base, script=self.installed(),
                     HOME=str(self.base), PATH="/usr/bin:/bin")
        self.assertIn("1/2 tasks", result.stdout)
        self.assertEqual((self.base / "cache" / "viewer").read_text().strip(), str(current))


if __name__ == "__main__":
    unittest.main()
