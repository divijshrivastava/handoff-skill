import hashlib
import os
import shutil
import importlib.util
import json
import re
import shlex
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


# Sources and enforcement distinctions: CONTRIBUTING.md, "Skill descriptions".
DESCRIPTION_CHARACTER_LIMITS = {
    "Agent Skills standard": 1024,
    "Claude Code skill listing": 1536,
    "Cursor authoring contract": 1024,
    "skills CLI parser": None,
}


class SkillDescriptionTests(unittest.TestCase):
    def setUp(self):
        skill = (ROOT / "skills/handoff/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        frontmatter = skill.split("---", 2)[1]
        # The source uses a JSON-compatible, quoted YAML scalar on one line.
        match = re.search(r'^description: (".*")$', frontmatter, re.MULTILINE)
        self.assertIsNotNone(match, "Expected the quoted frontmatter description")
        self.description = json.loads(match.group(1))

    def test_description_contains_guard_commands_in_order(self):
        commands = (
            "handoff_guard.py name --root <repo>",
            "handoff_guard.py read --root <repo>",
            "handoff_guard.py apply --root <repo> --expect-version V",
        )
        positions = []
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(command, self.description)
                positions.append(self.description.index(command))
        self.assertEqual(positions, sorted(positions), "Claim, read, then apply")

    def test_description_fits_recorded_character_limits(self):
        self.assertTrue(self.description.strip())
        for host, limit in DESCRIPTION_CHARACTER_LIMITS.items():
            if limit is not None:
                with self.subTest(host=host):
                    self.assertLessEqual(len(self.description), limit)


class PackageTests(unittest.TestCase):
    def test_plugin_hooks_register_report_failure_and_deliver_to_another_session(self):
        config = json.loads((ROOT / "hooks/hooks.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")

            def fire(event, session, **values):
                hook = config["hooks"][event][0]["hooks"][0]
                self.assertEqual(hook["type"], "command")
                command = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT))
                args = shlex.split(command)
                self.assertEqual(args[0], "python3")
                result = subprocess.run(
                    [sys.executable, *args[1:]], cwd=root,
                    input=json.dumps({"hook_event_name": event, "session_id": session, "cwd": str(root), **values}),
                    env={**os.environ, "HANDOFF_NAME_CACHE": str(root / "names")},
                    capture_output=True, text=True, encoding="utf-8", check=True,
                )
                return json.loads(result.stdout)

            fire("SessionStart", "first")
            fire("SessionStart", "second")
            fire("StopFailure", "first", error="rate_limit")
            received = fire("PostToolUse", "second")
            self.assertIn("host_failure", received["hookSpecificOutput"]["additionalContext"])
            self.assertIn("rate_limit", received["hookSpecificOutput"]["additionalContext"])
            self.assertEqual((root / "HANDOFF.md").read_text(), "# Handoff\n")

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
                self.assertIn("handoff/scripts/handoff_publish.py", archive.namelist())
                self.assertIn("handoff/references/vps-publish.md", archive.namelist())
                self.assertIn("handoff/scripts/handoff-tui", archive.namelist())
                self.assertIn("handoff/scripts/handoff-bar", archive.namelist())
                self.assertIn("handoff/references/harness-setup.md", archive.namelist())
                self.assertIn("handoff/references/progress-viewer.md", archive.namelist())
                self.assertIn("handoff/references/agent-channel.md", archive.namelist())
                self.assertIn("handoff/scripts/handoff_channel.py", archive.namelist())
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
            channel = subprocess.run(
                [sys.executable, str(helper.with_name("handoff_channel.py")), "--root", str(base), "peers"],
                cwd=base, capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertIn('"peers": []', channel.stdout)
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
