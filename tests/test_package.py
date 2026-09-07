import hashlib
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
                self.assertEqual(set(archive.namelist()), {
                    "handoff/" + name for name in (*package.RUNTIME_FILES, "LICENSE")
                })
                archive.extractall(base / "unpacked")
            helper = base / "unpacked/handoff/scripts/handoff_guard.py"
            result = subprocess.run(
                [sys.executable, str(helper), "template", "--title", "Example", "--owner", "Tester", "--step", "Verify."],
                capture_output=True, text=True, check=True,
            )
            self.assertIn("- [ ] Completed", result.stdout)

    def test_missing_resource_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(FileNotFoundError):
                package.build(base / "output", root=base / "missing")
            self.assertFalse((base / "output").exists())


if __name__ == "__main__":
    unittest.main()
