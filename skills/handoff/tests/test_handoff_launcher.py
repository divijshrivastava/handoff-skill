from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
LAUNCHER = SCRIPTS / "handoff-tui"
SPEC = importlib.util.spec_from_loader(
    "handoff_launcher", importlib.machinery.SourceFileLoader("handoff_launcher", str(LAUNCHER))
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def viewer_at(base: Path, *parts: str) -> Path:
    """Create a stand-in handoff_tui.py at an installed-skill layout."""
    path = base.joinpath(*parts) / "skills" / "handoff" / "scripts" / "handoff_tui.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# stand-in viewer\n", encoding="utf-8")
    return path


def installed_copy(base: Path) -> Path:
    """Copy the launcher onto a PATH-like directory, away from any sibling viewer."""
    destination = base / "bin" / "handoff-tui"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LAUNCHER, destination)
    return destination


def which(base: Path, script: Path | None = None, **environment) -> subprocess.CompletedProcess:
    """Run a PATH-installed launcher against an isolated Claude configuration."""
    env = dict(os.environ)
    env.pop("HANDOFF_TUI", None)
    env.pop("HANDOFF_SKILL_REPO", None)
    env["CLAUDE_CONFIG_DIR"] = str(base / "claude")
    env["HOME"] = env["USERPROFILE"] = str(base / "home")
    env["CODEX_HOME"] = str(base / "home" / ".codex")
    env.update(environment)
    return subprocess.run(
        [sys.executable, str(script or installed_copy(base)), "--which"],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=base,
    )


class RankTests(unittest.TestCase):
    def test_version_directories_order_numerically(self):
        paths = [Path(f"/plugins/handoff/{version}/x.py") for version in ("1.4.0", "1.10.0", "1.5.0")]
        self.assertEqual(max(paths, key=launcher.rank).parts[3], "1.10.0")

    def test_unversioned_path_ranks_below_a_versioned_one(self):
        plain = Path("/plugins/handoff/main/x.py")
        numbered = Path("/plugins/handoff/0.1.0/x.py")
        self.assertEqual(max([plain, numbered], key=launcher.rank), numbered)


class ResolutionTests(unittest.TestCase):
    def test_registry_install_wins_over_the_cache_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            registered = viewer_at(base, "elsewhere", "handoff", "2.0.0")
            viewer_at(base, "claude", "plugins", "cache", "market", "handoff", "9.9.9")
            registry = base / "claude" / "plugins" / "installed_plugins.json"
            registry.write_text(json.dumps({"plugins": {"handoff@market": [
                {"installPath": str(base / "elsewhere" / "handoff" / "2.0.0")}
            ]}}), encoding="utf-8")
            self.assertEqual(which(base).stdout.strip(), str(registered))

    def test_stale_registry_falls_back_to_the_newest_cached_version(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cache = ("claude", "plugins", "cache", "market", "handoff")
            viewer_at(base, *cache, "1.4.0")
            newest = viewer_at(base, *cache, "1.10.0")
            viewer_at(base, *cache, "1.5.0")
            self.assertEqual(which(base).stdout.strip(), str(newest))

    def test_registry_ignores_other_plugins_sharing_the_marketplace(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            other = viewer_at(base, "other", "1.0.0")
            registry = base / "claude" / "plugins" / "installed_plugins.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(json.dumps({"plugins": {"unrelated@market": [
                {"installPath": str(other.parents[3])}
            ]}}), encoding="utf-8")
            result = which(base)
            self.assertEqual(result.returncode, 1)
            self.assertIn("no handoff_tui.py found", result.stderr)

    def test_marketplace_clone_is_used_when_no_install_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            clone = viewer_at(base, "claude", "plugins", "marketplaces", "market")
            self.assertEqual(which(base).stdout.strip(), str(clone))

    def test_repository_checkout_is_the_last_resort(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = viewer_at(base, "checkout")
            result = which(base, HANDOFF_SKILL_REPO=str(base / "checkout"))
            self.assertEqual(result.stdout.strip(), str(checkout))

    def test_explicit_override_outranks_every_installed_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            viewer_at(base, "claude", "plugins", "cache", "market", "handoff", "9.9.9")
            chosen = viewer_at(base, "chosen")
            self.assertEqual(which(base, HANDOFF_TUI=str(chosen)).stdout.strip(), str(chosen))

    def test_missing_override_reports_the_path_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            viewer_at(base, "claude", "plugins", "cache", "market", "handoff", "9.9.9")
            result = which(base, HANDOFF_TUI=str(base / "absent.py"))
            self.assertEqual(result.returncode, 1)
            self.assertIn("is not a file", result.stderr)

    def test_no_installed_copy_reports_the_recovery_options(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result = which(base)
            self.assertEqual(result.returncode, 1)
            self.assertIn("$HANDOFF_TUI", result.stderr)
            self.assertIn("$HANDOFF_SKILL_REPO", result.stderr)


class CodexSkillsTests(unittest.TestCase):
    def test_global_agents_skill_without_claude_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            viewer = viewer_at(base, "home", ".agents")
            result = which(base)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()).resolve(), viewer.resolve())

    def test_custom_codex_home(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            viewer = viewer_at(base, "custom codex")
            result = which(base, CODEX_HOME=str(base / "custom codex"))
            self.assertEqual(Path(result.stdout.strip()).resolve(), viewer.resolve())

    def test_project_skill_precedes_global_and_plugin_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = viewer_at(base, ".agents")
            viewer_at(base, "home", ".agents")
            viewer_at(base, "claude", "plugins", "cache", "market", "handoff", "9.9.9")
            self.assertEqual(Path(which(base).stdout.strip()).resolve(), project.resolve())

    def test_parent_project_skill_and_repository_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            parent = viewer_at(base, ".agents")
            child = base / "child"
            child.mkdir()
            self.assertEqual(Path(which(child).stdout.strip()).resolve(), parent.resolve())
            (child / ".git").mkdir()
            self.assertEqual(which(child).returncode, 1)

    def test_codex_mode_skips_a_stale_skill_in_favor_of_an_updated_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            viewer_at(base, ".agents")
            updated = viewer_at(base, "claude", "plugins", "cache", "market", "handoff", "1.10.0")
            updated.with_name("handoff_codex.py").write_text("# Codex support\n", encoding="utf-8")
            script = installed_copy(base)
            env = {**os.environ, "CLAUDE_CONFIG_DIR": str(base / "claude"),
                   "HOME": str(base / "home"), "USERPROFILE": str(base / "home"),
                   "CODEX_HOME": str(base / "home" / ".codex")}
            env.pop("HANDOFF_TUI", None)
            result = subprocess.run([sys.executable, str(script), "--which", "--codex"],
                                    env=env, cwd=base, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()).resolve(), updated.resolve())


class InPlaceTests(unittest.TestCase):
    def test_a_sibling_viewer_is_preferred_so_running_in_place_works(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            viewer_at(base, "claude", "plugins", "cache", "market", "handoff", "9.9.9")
            result = which(base, script=LAUNCHER)
            self.assertEqual(result.stdout.strip(), str(SCRIPTS / "handoff_tui.py"))

    def test_arguments_reach_the_viewer(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "HANDOFF.md"
            ledger.write_text(
                "# Handoff\n\n## Task (owner: Tester)\n\nState:\n- [x] In progress\n"
                "- [ ] Completed\n\nSteps:\n- [ ] Outcome.\n\nStatus: Recorded.\nNext action.\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(LAUNCHER), "--once", "--file", str(ledger)],
                capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertIn("0/1 completed", result.stdout)
            self.assertIn("Tester", result.stdout)


if __name__ == "__main__":
    unittest.main()
