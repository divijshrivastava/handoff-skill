import hashlib
import os
import shutil
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_skill", ROOT / "scripts/package_skill.py")
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def test_reproducible_complete_and_runnable(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = package.build(base / "first")
            second = package.build(base / "second")
            self.assertEqual(first[0].read_bytes(), second[0].read_bytes())
            self.assertEqual(first[0].read_bytes(), first[1].read_bytes())
            self.assertIn(hashlib.sha256(first[0].read_bytes()).hexdigest(), first[2].read_text())
            with ZipFile(first[0]) as archive:
                self.assertIn("handoff/scripts/handoff_tui.py", archive.namelist())
                self.assertIn("handoff/scripts/handoff_codex.py", archive.namelist())
                self.assertIn("handoff/scripts/handoff-tui", archive.namelist())
                self.assertIn("handoff/scripts/handoff-bar", archive.namelist())
                self.assertIn("handoff/references/harness-setup.md", archive.namelist())
                self.assertIn("handoff/references/progress-viewer.md", archive.namelist())
                self.assertEqual(set(archive.namelist()), {
                    "handoff/" + name for name in (*package.RUNTIME_FILES, "LICENSE")
                })
                modes = {info.filename: info.external_attr >> 16 for info in archive.infolist()}
                self.assertEqual(modes["handoff/scripts/handoff-tui"], 0o100755)
                self.assertEqual(modes["handoff/scripts/handoff-bar"], 0o100755)
                self.assertEqual(modes["handoff/scripts/handoff_tui.py"], 0o100644)
                archive.extractall(base / "unpacked")
            helper = base / "unpacked/handoff/scripts/handoff_guard.py"
            result = subprocess.run(
                [sys.executable, str(helper), "template", "--title", "Example", "--owner", "Tester", "--step", "Verify."],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertIn("- [ ] Completed", result.stdout)
            ledger = base / "HANDOFF.md"
            ledger.write_text("# Handoff\n\n" + result.stdout, encoding="utf-8")
            viewer = helper.with_name("handoff_tui.py")
            report = subprocess.run(
                [sys.executable, str(viewer), "--once", "--file", str(ledger)],
                cwd=base, capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertIn("0/1 completed", report.stdout)
            self.assertIn("Tester", report.stdout)
            # The packaged launcher resolves the viewer beside it and forwards arguments.
            launcher = helper.with_name("handoff-tui")
            resolved = subprocess.run(
                [sys.executable, str(launcher), "--which"],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertEqual(Path(resolved.stdout.strip()), viewer.resolve())
            forwarded = subprocess.run(
                [sys.executable, str(launcher), "--once", "--file", str(ledger)],
                cwd=base, capture_output=True, text=True, encoding="utf-8", check=True,
            )
            # The snapshot header carries a clock time, so compare the ledger content.
            def content(text):
                return [line for line in text.splitlines() if "Revision:" not in line]
            self.assertEqual(content(forwarded.stdout), content(report.stdout))
            codex = subprocess.run(
                [sys.executable, str(launcher), "--codex"],
                cwd=base, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(codex.returncode, 1)
            self.assertIn("WSL" if sys.platform == "win32" else "interactive terminal", codex.stderr)
            self.assertNotIn("Traceback", codex.stderr)
            # The packaged status-line front-end runs from the extracted tree.
            # POSIX only; Windows uses the viewer's own --bar, exercised above.
            if sys.platform == "win32" or shutil.which("sh") is None:
                return
            bar = subprocess.run(
                ["sh", str(helper.with_name("handoff-bar")), "--file", str(ledger)],
                input="", capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "HANDOFF_BAR_CACHE": str(base / "barcache")},
            )
            self.assertEqual(bar.returncode, 0, bar.stderr)
            self.assertIn("0/1 tasks", bar.stdout)

    def test_missing_resource_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(FileNotFoundError):
                package.build(base / "output", root=base / "missing")
            self.assertFalse((base / "output").exists())


if __name__ == "__main__":
    unittest.main()
