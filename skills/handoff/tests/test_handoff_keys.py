import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_iterm2_install_writes_a_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            preset = Path(directory) / "iterm2-viewer-key.json"
            with patch.object(keys, "_config_candidates", return_value=[preset]):
                message = keys.install_terminal_binding("iterm2", "C-g", Path("/tmp/repo"))
            self.assertIn("Import", message)
            payload = json.loads(preset.read_text(encoding="utf-8"))
            self.assertIn("handoff_tui.py", payload["Text"])

    def test_unmappable_keys_are_refused(self) -> None:
        self.assertIn("skipped", keys.install_claude_release("F5", self.path()))
        with self.assertRaises(ValueError):
            keys.kitty_snippet("F5", "handoff-tui")

    def test_auto_detect_prefers_the_current_emulator(self) -> None:
        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "1"}, clear=True):
            with patch.object(keys, "install_terminal_binding", return_value="ok") as install:
                self.assertEqual(keys.install(emulator="auto"), "ok")
                install.assert_called_once_with("kitty", keys.viewer_key(), None)


if __name__ == "__main__":
    unittest.main()
