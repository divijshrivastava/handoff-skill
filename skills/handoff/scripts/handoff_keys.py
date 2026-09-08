"""Install viewer key bindings per terminal emulator and host harness."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

DEFAULT_KEY = "C-g"
MARKER_BEGIN = "# BEGIN handoff viewer key"
MARKER_END = "# END handoff viewer key"
CLAUDE_KEYBINDINGS = Path.home() / ".claude" / "keybindings.json"
HOST_CONTEXT = "Chat"
HOST_DISPLACED = {"ctrl+g": ("chat:externalEditor", "ctrl+e")}


def viewer_key() -> str | None:
    """The key the viewer claims; ``none`` gives it back to the agent."""
    key = os.environ.get("HANDOFF_VIEWER_KEY", DEFAULT_KEY).strip()
    if not key or key.lower() == "none":
        return None
    return key


def key_label(key: str) -> str:
    if len(key) > 2 and key[1] == "-" and key[0] in "cC":
        return "^" + key[2:].upper()
    return key


def host_key_name(key: str) -> str | None:
    """Spell a tmux key the way a host harness names it, or None if it cannot."""
    if len(key) == 3 and key[1] == "-" and key[0] in "cC" and key[2].isalpha():
        return "ctrl+" + key[2].lower()
    return None


def viewer_command(root: Path | None = None) -> str:
    """Shell command that opens the live viewer for one repository."""
    viewer = Path(__file__).resolve().with_name("handoff_tui.py")
    parts = [sys.executable, str(viewer)]
    if root is not None:
        parts.extend(["--root", str(root.resolve())])
    return " ".join(shlex.quote(part) for part in parts)


def detect_emulators() -> list[str]:
    """Return emulator ids implied by the current environment, best first."""
    found: list[str] = []
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if os.environ.get("WEZTERM_EXECUTABLE") or "wezterm" in term_program:
        found.append("wezterm")
    if os.environ.get("KITTY_WINDOW_ID") or term_program == "kitty":
        found.append("kitty")
    if os.environ.get("ITERM_SESSION_ID") or term_program == "iterm.app":
        found.append("iterm2")
    if os.environ.get("CLAUDE_CODE_SESSION_ID") or term_program == "claude":
        found.append("claude")
    return found


def install_claude_release(key: str | None, path: Path | None = None) -> str:
    """Stop Claude Code acting on the viewer key; it cannot run a command there."""
    if key is None:
        return "No viewer key is bound, so no host override is needed."
    host_key = host_key_name(key)
    if host_key is None:
        return f"Cannot express {key_label(key)} as a host binding; override skipped."
    target = path or CLAUDE_KEYBINDINGS
    displaced = HOST_DISPLACED.get(host_key)
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        existing = {"bindings": []}
    except (OSError, ValueError) as error:
        return f"Leaving {target} alone; it did not parse ({error})."
    if not isinstance(existing, dict) or not isinstance(existing.get("bindings"), list):
        return f"Leaving {target} alone; it is not a keybindings document."
    blocks = existing["bindings"]
    block = next((item for item in blocks
                  if isinstance(item, dict) and item.get("context") == HOST_CONTEXT
                  and isinstance(item.get("bindings"), dict)), None)
    if block is None:
        block = {"context": HOST_CONTEXT, "bindings": {}}
        blocks.append(block)
    if host_key in block["bindings"] and block["bindings"][host_key] is None:
        return (f"{target} already releases {host_key} for the viewer. "
                "Claude Code cannot bind a key to run a command; use /handoff:view "
                "or handoff-tui --with <agent> for a key that opens the viewer.")
    block["bindings"][host_key] = None
    if displaced is not None:
        action, moved_to = displaced
        if action not in block["bindings"].values():
            block["bindings"][moved_to] = action
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    if displaced is not None:
        return (f"Released {host_key} in {target}; {displaced[0]} now answers to "
                f"{displaced[1]}. Claude Code cannot bind a key to run a command; "
                "use /handoff:view or handoff-tui --with <agent> for a key that "
                "opens the viewer.")
    return (f"Released {host_key} in {target}. Claude Code cannot bind a key to "
            "run a command; use /handoff:view or handoff-tui --with <agent> for a "
            "key that opens the viewer.")


def _kitty_mods(key: str) -> tuple[str, str] | None:
    if len(key) == 3 and key[1] == "-" and key[0] in "cC" and key[2].isalpha():
        return "ctrl", key[2].lower()
    return None


def _wezterm_mods(key: str) -> tuple[str, str] | None:
    parsed = _kitty_mods(key)
    if parsed is None:
        return None
    return "CTRL", parsed[1].upper()


def kitty_snippet(key: str, command: str) -> str:
    mods = _kitty_mods(key)
    if mods is None:
        raise ValueError(f"Cannot express {key_label(key)} as a kitty binding.")
    mod, letter = mods
    return (f"map {mod}+{letter} launch --type=overlay --hold "
            f"sh -c {shlex.quote(command)}")


def wezterm_snippet(key: str, command: str) -> str:
    mods = _wezterm_mods(key)
    if mods is None:
        raise ValueError(f"Cannot express {key_label(key)} as a wezterm binding.")
    mod, letter = mods
    parts = shlex.split(command)
    args = ", ".join(repr(part) for part in parts)
    return (f"{{ key = '{letter}', mods = '{mod}', "
            f"action = wezterm.action.SpawnCommandInNewWindow {{ args = {{ {args} }} }} }},")


def iterm2_snippet(key: str, command: str) -> str:
    host_key = host_key_name(key)
    if host_key is None:
        raise ValueError(f"Cannot express {key_label(key)} as an iTerm2 binding.")
    return json.dumps({
        "Guid": "handoff-viewer-key",
        "Key Combination": host_key.replace("ctrl+", "0x") + " (control)",
        "Action": 12,
        "Text": command + "\n",
        "Tags": ["handoff"],
    }, indent=2)


def _config_candidates(emulator: str) -> list[Path]:
    home = Path.home()
    if emulator == "kitty":
        return [home / ".config/kitty/kitty.conf"]
    if emulator == "wezterm":
        return [home / ".wezterm.lua", home / ".config/wezterm/wezterm.lua"]
    if emulator == "iterm2":
        return [home / ".config/handoff/iterm2-viewer-key.json"]
    return []


def _append_marked_block(path: Path, block: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    if MARKER_BEGIN in existing:
        pattern = re.compile(
            re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
            re.DOTALL,
        )
        existing = pattern.sub("", existing)
    path.write_text(existing.rstrip() + "\n\n" + block + "\n", encoding="utf-8")


def install_terminal_binding(emulator: str, key: str | None, root: Path | None = None) -> str:
    """Write a terminal binding that runs the viewer, or refuse honestly."""
    if key is None:
        return "No viewer key is bound, so no terminal override is needed."
    command = viewer_command(root)
    if emulator == "claude":
        return install_claude_release(key)
    try:
        if emulator == "kitty":
            snippet = kitty_snippet(key, command)
        elif emulator == "wezterm":
            snippet = wezterm_snippet(key, command)
        elif emulator == "iterm2":
            snippet = iterm2_snippet(key, command)
        else:
            return (f"Unknown emulator {emulator!r}; supported: claude, kitty, "
                    "wezterm, iterm2.")
    except ValueError as error:
        return str(error)
    paths = _config_candidates(emulator)
    if not paths:
        return f"No configuration path is known for {emulator}."
    target = paths[0]
    if emulator == "iterm2":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(snippet + "\n", encoding="utf-8")
        return (f"Wrote an iTerm2 key preset to {target}. Import it from "
                f"Settings → Keys → Key Mappings, then {key_label(key)} runs "
                f"{command}.")
    block = "\n".join((MARKER_BEGIN, snippet, MARKER_END))
    _append_marked_block(target, block)
    return f"Wrote {key_label(key)} → viewer into {target}. Reload {emulator} to apply it."


def install(key: str | None = None, root: Path | None = None,
            emulator: str | None = None) -> str:
    """Install the best available viewer binding for this environment."""
    chosen = key if key is not None else viewer_key()
    if emulator is None or emulator == "auto":
        candidates = detect_emulators()
        if not candidates:
            return (f"No supported emulator detected; pass --emulator explicitly. "
                    f"Run {viewer_command(root)} in a terminal, or use "
                    "/handoff:view.")
        return install_terminal_binding(candidates[0], chosen, root)
    return install_terminal_binding(emulator, chosen, root)
