import importlib.util
import json
import os
import plistlib
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

spec = importlib.util.spec_from_file_location("handoff_keys", SCRIPT_DIR / "handoff_keys.py")
keys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keys)


class HandoffKeysTests(unittest.TestCase):
    def path(self) -> Path:
        return Path(tempfile.mkdtemp()) / "keybindings.json"

    def test_claude_release_rehomes_the_displaced_action(self) -> None:
        target = self.path()
        message = keys.install_claude_release("C-g", target)
        self.assertIn("ctrl+g", message)
        written = json.loads(target.read_text(encoding="utf-8"))
        block = written["bindings"][0]
        self.assertIsNone(block["bindings"]["ctrl+g"])
        self.assertEqual(block["bindings"]["ctrl+e"], "chat:externalEditor")

    def test_claude_release_is_idempotent_and_honest(self) -> None:
        target = self.path()
        keys.install_claude_release("C-g", target)
        again = keys.install_claude_release("C-g", target)
        self.assertIn("already", again)
        self.assertIn("cannot bind a key to run a command", again)

    def test_an_unparseable_claude_file_is_left_alone(self) -> None:
        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{not json", encoding="utf-8")
        message = keys.install_claude_release("C-g", target)
        self.assertIn("Leaving", message)
        self.assertEqual(target.read_text(encoding="utf-8"), "{not json")

    def test_kitty_install_writes_a_firing_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "kitty.conf"
            with patch.object(keys, "_config_candidates", return_value=[config]):
                message = keys.install_terminal_binding("kitty", "C-g", Path("/tmp/repo"))
            self.assertIn(str(config), message)
            text = config.read_text(encoding="utf-8")
            self.assertIn("map ctrl+g launch", text)
            self.assertIn("handoff_tui.py", text)

    def test_wezterm_install_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "wezterm.lua"
            with patch.object(keys, "_config_candidates", return_value=[config]):
                keys.install_terminal_binding("wezterm", "C-g", None)
                first = config.read_text(encoding="utf-8").count("BEGIN handoff viewer key")
                keys.install_terminal_binding("wezterm", "C-g", None)
                second = config.read_text(encoding="utf-8").count("BEGIN handoff viewer key")
            self.assertEqual(first, 1)
            self.assertEqual(second, 1)

    def test_iterm2_shortcuts_open_a_profile_instead_of_typing_a_command(self) -> None:
        for key, code, modifiers in (("C-g", "67", "40000"),
                                     ("C-M-h", "68", "c0000")):
            payload = json.loads(keys.iterm2_snippet(key, "viewer-guid"))
            self.assertEqual(payload["Key Mappings"], {
                f"0x{code}-0x{modifiers}": {"Action": 26, "Text": "viewer-guid"},
            })
            self.assertEqual(payload["Touch Bar Items"], {})

    def test_control_alt_key_label_names_both_modifiers(self) -> None:
        self.assertEqual(keys.key_label("C-M-h"), "Ctrl+Alt+H")
        self.assertEqual(keys.key_label("C-g"), "^G")

    def iterm_install(self, directory, settings, key="C-v"):
        run = Mock(return_value=subprocess.CompletedProcess(
            [], 0, stdout=plistlib.dumps(settings)))
        with patch.object(keys.Path, "home", return_value=Path(directory)), \
                patch.object(keys.platform, "system", return_value="Darwin"), \
                patch.object(keys.subprocess, "run", run), \
                patch.object(keys.shutil, "which", return_value="/tmp/bin with space/handoff-tui"):
            message = keys.install_terminal_binding("iterm2", key, Path(directory) / "repo space")
        return message, run

    def test_iterm2_install_merges_the_key_and_prepares_a_live_viewer_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = {"GlobalKeyMap": {"0xd-0x20000": {"Action": 12, "Text": "\\n"}}}
            message, run = self.iterm_install(directory, settings)
            self.assertIn("Installed ^V", message)
            arguments = run.call_args.args[0]
            self.assertEqual(arguments[:5], ["/usr/bin/defaults", "write",
                                             "com.googlecode.iterm2", "GlobalKeyMap", "-dict-add"])
            self.assertEqual(arguments[5], "0x76-0x40000")
            action = plistlib.loads(arguments[6].encode())
            profile_path = next((Path(directory) / "Library/Application Support/iTerm2/DynamicProfiles").glob("*.json"))
            profile = json.loads(profile_path.read_text())["Profiles"][0]
            self.assertEqual(action, {"Action": 26, "Text": profile["Guid"]})
            self.assertEqual(profile["Custom Command"], "Yes")
            self.assertEqual(keys.shlex.split(profile["Command"]), [
                sys.executable, "/tmp/bin with space/handoff-tui", "--root",
                str((Path(directory) / "repo space").resolve()),
            ])
            backup = Path(directory) / ".config/handoff/iterm2-before-viewer-key.plist"
            self.assertEqual(plistlib.loads(backup.read_bytes()), settings)

    def test_iterm2_reinstall_preserves_the_original_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = {"GlobalKeyMap": {}}
            self.iterm_install(directory, original)
            profile_path = next((Path(directory) / "Library/Application Support/iTerm2/DynamicProfiles").glob("*.json"))
            profile = json.loads(profile_path.read_text())["Profiles"][0]
            installed = {"GlobalKeyMap": {"0x76-0x40000": {"Action": 26, "Text": profile["Guid"]}}}
            message, run = self.iterm_install(directory, installed)
            self.assertIn("Installed", message)
            backup = Path(directory) / ".config/handoff/iterm2-before-viewer-key.plist"
            self.assertEqual(plistlib.loads(backup.read_bytes()), original)
            self.assertEqual(len(list(profile_path.parent.glob("*.json"))), 1)

    def test_iterm2_switch_releases_image_paste_and_preserves_other_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.iterm_install(directory, {"GlobalKeyMap": {}})
            profile_path = next((Path(directory) / "Library/Application Support/iTerm2/DynamicProfiles").glob("*.json"))
            guid = json.loads(profile_path.read_text())["Profiles"][0]["Guid"]
            viewer = {"Action": 26, "Text": guid}
            unrelated = {
                "0x67-0x40000": {"Action": 12, "Text": "user binding"},
                "0x6a-0xc0000": {"Action": 26, "Text": "another-repo-guid"},
            }
            installed = {"GlobalKeyMap": dict(unrelated, **{
                "0x76-0x40000": viewer, "0x76-0x40000-0x9": viewer,
            })}
            message, run = self.iterm_install(directory, installed, key="C-M-h")
            self.assertIn("Installed Ctrl+Alt+H", message)
            arguments = run.call_args.args[0]
            self.assertEqual(arguments[:5], ["/usr/bin/defaults", "write",
                                             "com.googlecode.iterm2", "GlobalKeyMap", "-dict"])
            updated = {key: plistlib.loads(value.encode())
                       for key, value in zip(arguments[5::2], arguments[6::2])}
            self.assertEqual(updated, dict(unrelated, **{"0x68-0xc0000": viewer}))
            # Reinstalling the new key leaves it alone and does not resurrect Ctrl+V.
            message, run = self.iterm_install(directory, {"GlobalKeyMap": updated}, key="C-M-h")
            self.assertIn("Installed Ctrl+Alt+H", message)
            self.assertEqual(run.call_args.args[0][4], "-dict-add")
            self.assertEqual(run.call_args.args[0][5], "0x68-0xc0000")

    def test_iterm2_switch_refuses_a_new_key_conflict_before_removing_old_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            installed = {"GlobalKeyMap": {
                "0x76-0x40000": {"Action": 26, "Text": "viewer-guid"},
                "0x68-0xc0000": {"Action": 12, "Text": "user binding"},
            }}
            message, run = self.iterm_install(directory, installed, key="C-M-h")
            self.assertIn("already binds", message)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_iterm2_keeps_a_ctrl_v_binding_that_does_not_open_its_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = {"GlobalKeyMap": {
                "0x76-0x40000": {"Action": 12, "Text": "user paste binding"},
            }}
            message, run = self.iterm_install(directory, settings, key="C-M-h")
            self.assertIn("Installed", message)
            self.assertEqual(run.call_args.args[0][4], "-dict-add")
            self.assertEqual(run.call_args.args[0][5], "0x68-0xc0000")

    def test_iterm2_file_permission_failure_does_not_change_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(keys.Path, "write_text", side_effect=PermissionError("denied")):
                message, run = self.iterm_install(directory, {"GlobalKeyMap": {}}, key="C-M-h")
            self.assertIn("key not installed", message)
            self.assertEqual(run.call_count, 1)

    def test_iterm2_refuses_a_shadowing_profile_key_or_existing_global_key(self) -> None:
        for settings in (
            {"New Bookmarks": [{"Name": "Default", "Keyboard Map": {"0x76-0x40000-0x9": {"Action": 12}}}]},
            {"GlobalKeyMap": {"0x76-0x40000": {"Action": 12, "Text": "something"}}},
            {"GlobalKeyMap": []},
        ):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory:
                message, run = self.iterm_install(directory, settings)
                self.assertNotIn("Installed", message)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_iterm2_invalid_preferences_are_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(keys.platform, "system", return_value="Darwin"), \
                    patch.object(keys.Path, "home", return_value=Path(directory)), \
                    patch.object(keys.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, stdout=b"not a plist")) as run:
                message = keys.install_terminal_binding("iterm2", "C-v")
            self.assertIn("Leaving", message)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_unmappable_keys_are_refused(self) -> None:
        self.assertIn("skipped", keys.install_claude_release("F5", self.path()))
        with self.assertRaises(ValueError):
            keys.kitty_snippet("F5", "handoff-tui")

    def test_auto_detect_prefers_the_current_emulator(self) -> None:
        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "1"}, clear=True):
            with patch.object(keys, "install_terminal_binding", return_value="ok") as install:
                self.assertEqual(keys.install(emulator="auto"), "ok")
                install.assert_called_once_with("kitty", keys.viewer_key(), None)

    def test_open_iterm2_uses_an_interactive_shell(self) -> None:
        with patch.object(keys, "open_candidates", return_value=["iterm2"]):
            with patch.object(keys, "viewer_launch_command", return_value="handoff-tui --root /repo"):
                with patch.object(keys.subprocess, "run") as run:
                    code, message = keys.open_viewer(Path("/repo"))
        self.assertEqual(code, 0)
        self.assertIn("iTerm2", message)
        script = run.call_args.args[0][2]
        self.assertIn("write text", script)
        self.assertNotIn("create window with default profile command", script)

    def test_open_falls_back_when_spawn_fails(self) -> None:
        with patch.object(keys, "open_candidates", return_value=["iterm2"]):
            with patch.object(keys, "viewer_launch_command", return_value="handoff-tui --root /repo"):
                with patch.object(keys.subprocess, "run", side_effect=keys.subprocess.CalledProcessError(1, "osascript")):
                    code, message = keys.open_viewer(Path("/repo"))
        self.assertEqual(code, 1)
        self.assertIn("Could not open a terminal", message)
        self.assertIn("handoff-tui --root /repo", message)

    def test_open_candidates_include_installed_iterm_on_macos(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(keys.platform, "system", return_value="Darwin"):
                with patch.object(keys, "_macos_app_installed", side_effect=lambda name: name == "iTerm"):
                    self.assertEqual(keys.open_candidates(), ["iterm2"])


if __name__ == "__main__":
    unittest.main()
