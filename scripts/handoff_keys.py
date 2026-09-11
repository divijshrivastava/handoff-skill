"""Install viewer key bindings per terminal emulator and host harness."""

from __future__ import annotations

import json
import os
import platform
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import uuid
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
    if re.fullmatch(r"C-M-[a-z]", key, re.IGNORECASE):
        return "Ctrl+Alt+" + key[-1].upper()
    if len(key) > 2 and key[1] == "-" and key[0] in "cC":
        return "^" + key[2:].upper()
    return key


def host_key_name(key: str) -> str | None:
    """Spell a tmux key the way a host harness names it, or None if it cannot."""
    if len(key) == 3 and key[1] == "-" and key[0] in "cC" and key[2].isalpha():
        return "ctrl+" + key[2].lower()
    return None


def viewer_command(root: Path | None = None, *, read_only: bool = False) -> str:
    """Shell command that opens the live viewer for one repository."""
    viewer = Path(__file__).resolve().with_name("handoff_tui.py")
    parts = [sys.executable, str(viewer)]
    if root is not None:
        parts.extend(["--root", str(root.resolve())])
    if read_only:
        parts.append("--read-only")
    return " ".join(shlex.quote(part) for part in parts)


def opener_seed() -> str | None:
    """The host identifier of the session asking for a viewer, if it has one.

    Only a real identifier is carried. `session_seed` invents a random one when a
    host exposes none, and forwarding that would name a session that does not
    exist. This is deliberately not baked into installed key bindings: it belongs
    to the window being opened now, not to every future one.
    """
    for variable in ("HANDOFF_SESSION", "CLAUDE_CODE_SESSION_ID", "TERM_SESSION_ID"):
        value = os.environ.get(variable)
        if value and value.strip():
            return value.strip()
    return None


KNOWN_AGENTS = (
    "claude", "codex", "kimi", "grok", "gemini", "opencode", "amp", "cline",
    "cursor-agent", "droid", "kimi-code-cli",
)

_PATH_ENRICHED = False


def agent_path_entries() -> list[str]:
    """Common install locations GUI and task shells often omit from PATH."""
    home = Path.home()
    entries: list[Path] = [
        home / ".local" / "bin",
        home / ".kimi-code" / "bin",
        home / ".grok" / "bin",
        home / ".opencode" / "bin",
        home / ".cargo" / "bin",
    ]
    nvm = home / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        for version in sorted((path for path in nvm.iterdir() if path.is_dir()),
                              reverse=True):
            bindir = version / "bin"
            if bindir.is_dir():
                entries.append(bindir)
                break
    cursor_root = home / ".local" / "share" / "cursor-agent" / "versions"
    if cursor_root.is_dir():
        for version in sorted((path for path in cursor_root.iterdir() if path.is_dir()),
                              reverse=True):
            entries.append(version)
            break
    return [str(path) for path in entries if path.is_dir()]


def enrich_path() -> None:
    """Prepend known agent install directories once per process."""
    global _PATH_ENRICHED
    if _PATH_ENRICHED:
        return
    additions = agent_path_entries()
    if additions:
        current = os.environ.get("PATH", "")
        os.environ["PATH"] = ":".join(additions + ([current] if current else []))
    _PATH_ENRICHED = True


def resolve_agent(name: str) -> str | None:
    """Locate one agent CLI, including common paths task shells strip away."""
    enrich_path()
    return shutil.which(name)


def available_agents() -> list[str]:
    """Return known agent CLIs that are on PATH, in a stable order."""
    enrich_path()
    return [name for name in KNOWN_AGENTS if shutil.which(name)]


def agent_launch_command(root: Path | None, agent: str,
                         seed: str | None = None) -> str:
    """Shell command that runs one agent CLI under the handoff bar."""
    launcher = shutil.which("handoff-tui")
    if launcher:
        parts = [launcher]
    else:
        viewer = Path(__file__).resolve().with_name("handoff_tui.py")
        parts = [sys.executable, str(viewer)]
    if root is not None:
        parts.extend(["--root", str(root.resolve())])
    if seed:
        parts.extend(["--session-seed", seed])
    parts.extend(["--with", agent])
    return " ".join(shlex.quote(part) for part in parts)


def viewer_launch_command(root: Path | None = None, *, read_only: bool = False) -> str:
    """Prefer the PATH launcher so opened terminals survive skill upgrades."""
    launcher = shutil.which("handoff-tui")
    seed = opener_seed()
    if launcher:
        parts = [launcher]
        if root is not None:
            parts.extend(["--root", str(root.resolve())])
        if read_only:
            parts.append("--read-only")
        if seed:
            parts.extend(["--session-seed", seed])
        return " ".join(shlex.quote(part) for part in parts)
    command = viewer_command(root, read_only=read_only)
    return command if not seed else f"{command} --session-seed {shlex.quote(seed)}"


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
    if term_program == "vscode" and cursor_user_dir().is_dir():
        found.append("cursor")
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


def iterm2_snippet(key: str, profile_guid: str) -> str:
    """An importable keymap that opens a terminal, never types into the agent."""
    parsed = re.fullmatch(r"C-(M-)?([a-z])", key, re.IGNORECASE)
    if parsed is None:
        raise ValueError(f"Cannot express {key_label(key)} as an iTerm2 binding.")
    # iTermKeyBindingAction.h: 26 = New Window with Profile; 12 = Send Text.
    # AppKit: Control is 1 << 18; Option (tmux Meta/Alt) is 1 << 19.
    modifiers = 0x40000 | (0x80000 if parsed[1] else 0)
    serialized = f"0x{ord(parsed[2].lower()):x}-0x{modifiers:x}"
    return json.dumps({
        "Key Mappings": {serialized: {"Action": 26, "Text": profile_guid}},
        "Touch Bar Items": {},
    }, indent=2)


def install_iterm2_binding(key: str, root: Path | None = None) -> str:
    """Install a dynamic viewer profile and merge one global shortcut on macOS."""
    if platform.system() != "Darwin":
        return "iTerm2 key installation requires macOS."
    directory = (root or Path.cwd()).resolve()
    guid = str(uuid.uuid5(uuid.NAMESPACE_URL, "handoff-tui:" + str(directory)))
    try:
        snippet = iterm2_snippet(key, guid)
    except ValueError as error:
        return str(error)
    mapping = json.loads(snippet)["Key Mappings"]
    serialized = next(iter(mapping))
    domain = "com.googlecode.iterm2"
    defaults = "/usr/bin/defaults"
    try:
        exported = subprocess.run([defaults, "export", domain, "-"],
                                  capture_output=True, check=True).stdout
        settings = plistlib.loads(exported)
        if not isinstance(settings, dict):
            raise ValueError("preferences are not a dictionary")
        global_map = settings.get("GlobalKeyMap", {})
        if not isinstance(global_map, dict):
            raise ValueError("GlobalKeyMap is not a dictionary")
        # A profile binding wins over the global map. Do not claim installation
        # succeeded when an existing local mapping would still steal this key.
        for profile in settings.get("New Bookmarks", []):
            for bound in profile.get("Keyboard Map", {}):
                if bound == serialized or bound.startswith(serialized + "-"):
                    return (f"Profile {profile.get('Name', '(unnamed)')!r} already binds "
                            f"{key_label(key)}; its profile mapping overrides global keys. "
                            "Choose another HANDOFF_VIEWER_KEY or remove that mapping.")
        for bound, action in global_map.items():
            if bound == serialized or bound.startswith(serialized + "-"):
                if action != mapping[serialized]:
                    return (f"iTerm2 already binds {key_label(key)} to another action; "
                            "choose another HANDOFF_VIEWER_KEY or remove that mapping.")
    except (OSError, ValueError, plistlib.InvalidFileException,
            subprocess.CalledProcessError) as error:
        return f"Leaving iTerm2 preferences alone; could not read them ({error})."

    config = Path.home() / ".config/handoff"
    profiles = Path.home() / "Library/Application Support/iTerm2/DynamicProfiles"
    target = profiles / f"handoff-viewer-{guid}.json"
    # Explicit Python avoids relying on the GUI application's PATH for the
    # launcher's /usr/bin/env shebang. The launcher still resolves skill upgrades.
    launcher = shutil.which("handoff-tui")
    command = (" ".join(shlex.quote(part) for part in
                       [sys.executable, launcher, "--root", str(directory)])
               if launcher else viewer_command(directory))
    profile = {"Profiles": [{
        "Name": "Handoff — " + directory.name, "Guid": guid,
        "Custom Command": "Yes", "Command": command,
        "Custom Directory": "Yes", "Working Directory": str(directory),
        "Close Sessions On End": True,
    }]}
    if target.exists():
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(previous, dict) or not isinstance(previous.get("Profiles"), list):
                raise ValueError("not a dynamic-profile document")
        except (OSError, ValueError) as error:
            return f"Leaving {target} alone; it did not parse ({error})."
    backup = config / "iterm2-before-viewer-key.plist"
    preset = config / "iterm2-viewer-key.itermkeymap"
    try:
        config.mkdir(parents=True, exist_ok=True)
        profiles.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                stream.write(exported)
        target.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
        preset.write_text(snippet + "\n", encoding="utf-8")
    except OSError as error:
        return f"Could not prepare the iTerm2 viewer files ({error}); key not installed."
    # -dict-add merges only these entries. If no custom map exists, retain the
    # shipped defaults that creating a GlobalKeyMap would otherwise hide.
    additions = {}
    if "GlobalKeyMap" not in settings:
        bundled = Path("/Applications/iTerm.app/Contents/Resources/DefaultGlobalKeyMap.plist")
        try:
            additions.update(plistlib.loads(bundled.read_bytes()))
        except (OSError, ValueError, plistlib.InvalidFileException) as error:
            return f"Could not load iTerm2's default shortcuts ({error}); key not installed."
    additions.update(mapping)
    # Changing the shortcut must release the previous key (for example Ctrl+V
    # for image paste). Only retire mappings to this repository's exact viewer
    # action; another repository's profile and unrelated user shortcuts survive.
    retired = [bound for bound, action in global_map.items()
               if bound != serialized and action == mapping[serialized]]
    operation = "-dict-add"
    if retired:
        additions = {bound: action for bound, action in global_map.items()
                     if bound not in retired}
        additions.update(mapping)
        operation = "-dict"
    arguments = [defaults, "write", domain, "GlobalKeyMap", operation]
    for bound, action in additions.items():
        arguments.extend([bound, plistlib.dumps(action).decode("utf-8")])
    try:
        subprocess.run(arguments, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        return (f"Viewer profile prepared, but the shortcut could not be installed ({error}). "
                f"Import {preset} in iTerm2 Settings → Keys → Key Mappings.")
    return (f"Installed {key_label(key)} → Handoff in iTerm2 for {directory}. "
            "The key opens a separate viewer window; q closes it. "
            "If an existing window keeps the old binding, restart iTerm2 when convenient. "
            f"Previous preferences: {backup}.")


TASK_LABEL = "Handoff viewer"
RUN_TASK = "workbench.action.tasks.runTask"


def cursor_user_dir() -> Path:
    """Where Cursor keeps the user's keybindings and settings on this platform."""
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return home / "Library/Application Support/Cursor/User"
    if system == "Windows":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else home / "AppData/Roaming") / "Cursor/User"
    return home / ".config/Cursor/User"


def vscode_key_name(key: str) -> str | None:
    """Spell a tmux key the way VS Code and Cursor name it, or None."""
    parsed = re.fullmatch(r"C-(M-)?([a-z])", key, re.IGNORECASE)
    if parsed is None:
        return None
    return ("ctrl+alt+" if parsed[1] else "ctrl+") + parsed[2].lower()


def _strip_jsonc(text: str) -> str:
    """Drop // and /* */ comments so a VS Code config parses as JSON."""
    out, index, length = [], 0, len(text)
    while index < length:
        char = text[index]
        if char == '"':
            end = index + 1
            while end < length:
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == '"':
                    break
                end += 1
            out.append(text[index:end + 1])
            index = end + 1
            continue
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end == -1 else end
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _load_jsonc(path: Path, default):
    """Parse a VS Code config, or raise ValueError describing why it cannot be."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    stripped = _strip_jsonc(raw).strip()
    if not stripped:
        return default
    return json.loads(stripped)


def _insert_binding(path: Path, binding: dict) -> None:
    """Append one binding, keeping the file's own comments and formatting."""
    entry = json.dumps(binding, indent=4)
    entry = "\n".join("    " + line for line in entry.splitlines())
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raw = ""
    close = raw.rfind("]")
    if close == -1:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[\n" + entry + "\n]\n", encoding="utf-8")
        return
    head = raw[:close].rstrip()
    separator = "\n" if head.endswith("[") else ",\n"
    path.write_text(head + separator + entry + "\n" + raw[close:], encoding="utf-8")


def cursor_task(directory: Path) -> dict:
    """A workspace task that opens the viewer in its own terminal panel."""
    launcher = shutil.which("handoff-tui")
    # viewer_command with no root omits --root, which the task supplies itself.
    command = (" ".join(shlex.quote(part) for part in [sys.executable, launcher])
               if launcher else viewer_command(None))
    # Cursor task shells often inherit a bare PATH. Run through a login shell
    # in the command itself; options.shell is not reliable across hosts.
    shell = os.environ.get("SHELL") or "/bin/zsh"
    inner = command + ' --root "${workspaceFolder}"'
    return {
        "label": TASK_LABEL,
        "type": "shell",
        # ${workspaceFolder} keeps this file portable: the same task opens
        # whichever repository the window has open.
        "command": f"{shell} -lic {shlex.quote(inner)}",
        "presentation": {"reveal": "always", "panel": "dedicated", "focus": True,
                         "clear": True},
        "problemMatcher": [],
    }


def install_cursor_binding(key: str, root: Path | None = None) -> str:
    """Bind the viewer key in Cursor, running a task rather than typing a command."""
    binding_key = vscode_key_name(key)
    if binding_key is None:
        return f"Cannot express {key_label(key)} as a Cursor binding."
    directory = (root or Path.cwd()).resolve()
    user_dir = cursor_user_dir()
    keybindings = user_dir / "keybindings.json"
    settings = user_dir / "settings.json"
    tasks = directory / ".vscode/tasks.json"
    try:
        bindings = _load_jsonc(keybindings, [])
        configuration = _load_jsonc(settings, {})
        document = _load_jsonc(tasks, {"version": "2.0.0", "tasks": []})
    except (OSError, ValueError) as error:
        return f"Leaving Cursor configuration alone; it did not parse ({error})."
    if not isinstance(bindings, list):
        return f"Leaving {keybindings} alone; it is not a keybindings array."
    if not isinstance(configuration, dict):
        return f"Leaving {settings} alone; it is not a settings object."
    if not isinstance(document, dict) or not isinstance(document.get("tasks"), list):
        return f"Leaving {tasks} alone; it is not a tasks document."
    wanted = {"key": binding_key, "command": RUN_TASK, "args": TASK_LABEL}
    for bound in bindings:
        if not isinstance(bound, dict) or bound.get("key") != binding_key:
            continue
        if bound.get("command") == RUN_TASK and bound.get("args") == TASK_LABEL:
            wanted = None
            break
        return (f"Cursor already binds {key_label(key)} to {bound.get('command')!r}; "
                "choose another HANDOFF_VIEWER_KEY or remove that binding.")
    task = cursor_task(directory)
    document["tasks"] = [item for item in document["tasks"]
                         if not (isinstance(item, dict) and item.get("label") == TASK_LABEL)]
    document["tasks"].append(task)
    document.setdefault("version", "2.0.0")
    # With the terminal focused, Cursor sends keystrokes to the shell unless the
    # command is listed here, which is exactly the case the user asked about.
    skip = configuration.get("terminal.integrated.commandsToSkipShell", [])
    if not isinstance(skip, list):
        return (f"Leaving {settings} alone; "
                "terminal.integrated.commandsToSkipShell is not a list.")
    added_skip = RUN_TASK not in skip
    try:
        tasks.parent.mkdir(parents=True, exist_ok=True)
        tasks.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        if added_skip:
            configuration["terminal.integrated.commandsToSkipShell"] = skip + [RUN_TASK]
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps(configuration, indent=2) + "\n", encoding="utf-8")
        if wanted is not None:
            _insert_binding(keybindings, wanted)
    except OSError as error:
        return f"Could not write the Cursor configuration ({error}); key not installed."
    already = "" if wanted is not None else " The keybinding was already present."
    return (f"Installed {key_label(key)} -> Handoff in Cursor for {directory}. "
            f"It runs the {TASK_LABEL!r} task from {tasks}, which opens the viewer in "
            f"its own terminal panel; q closes it.{already} "
            "Reload the Cursor window to pick up the new keybinding. Every repository "
            "needs its own task file, and the key opens whichever repository the "
            "window has open.")


def _config_candidates(emulator: str) -> list[Path]:
    home = Path.home()
    if emulator == "kitty":
        return [home / ".config/kitty/kitty.conf"]
    if emulator == "wezterm":
        return [home / ".wezterm.lua", home / ".config/wezterm/wezterm.lua"]
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
    if emulator == "iterm2":
        return install_iterm2_binding(key, root)
    if emulator == "cursor":
        return install_cursor_binding(key, root)
    try:
        if emulator == "kitty":
            snippet = kitty_snippet(key, command)
        elif emulator == "wezterm":
            snippet = wezterm_snippet(key, command)
        else:
            return (f"Unknown emulator {emulator!r}; supported: claude, kitty, "
                    "wezterm, iterm2, cursor.")
    except ValueError as error:
        return str(error)
    paths = _config_candidates(emulator)
    if not paths:
        return f"No configuration path is known for {emulator}."
    target = paths[0]
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


def _macos_app_installed(name: str) -> bool:
    for location in (Path("/Applications"), Path("/System/Applications/Utilities")):
        if (location / f"{name}.app").is_dir():
            return True
    return False


def open_candidates() -> list[str]:
    """Return terminal emulators to try, best first."""
    found = [emulator for emulator in detect_emulators() if emulator != "claude"]
    if found:
        return found
    if platform.system() != "Darwin":
        return []
    candidates: list[str] = []
    if _macos_app_installed("iTerm"):
        candidates.append("iterm2")
    if _macos_app_installed("Terminal"):
        candidates.append("terminal")
    return candidates


def _open_iterm2(command: str) -> None:
    script = (
        'tell application "iTerm2"\n'
        "  activate\n"
        "  create window with default profile\n"
        "  tell current session of current window\n"
        f"    write text {json.dumps(command)}\n"
        "  end tell\n"
        "end tell"
    )
    subprocess.run(["osascript", "-e", script], check=True)


def _open_terminal_app(command: str) -> None:
    subprocess.run(
        ["osascript", "-e", f'tell application "Terminal" to do script {json.dumps(command)}'],
        check=True,
    )


def _open_kitty(command: str) -> None:
    subprocess.run(
        ["kitty", "@", "launch", "--type=window", "sh", "-c", command + "; exec $SHELL"],
        check=True,
    )


def _open_wezterm(command: str) -> None:
    subprocess.run(["wezterm", "cli", "spawn", "--"] + shlex.split(command), check=True)


def _open_linux(command: str) -> None:
    for name in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal"):
        terminal = shutil.which(name)
        if terminal is None:
            continue
        if name == "gnome-terminal":
            subprocess.run([terminal, "--", "sh", "-c", command + "; exec $SHELL"], check=True)
        else:
            subprocess.run([terminal, "-e", command], check=True)
        return
    raise FileNotFoundError("no terminal emulator on PATH")


def _open_in_terminal(command: str) -> tuple[int, str]:
    """Run a shell command in a new terminal window; return (code, message)."""
    errors: list[str] = []
    for emulator in open_candidates():
        try:
            if emulator == "iterm2":
                _open_iterm2(command)
                return 0, "iTerm2"
            if emulator == "terminal":
                _open_terminal_app(command)
                return 0, "Terminal"
            if emulator == "kitty":
                _open_kitty(command)
                return 0, "kitty"
            if emulator == "wezterm":
                _open_wezterm(command)
                return 0, "wezterm"
        except (OSError, subprocess.CalledProcessError) as error:
            errors.append(f"{emulator}: {error}")
    if platform.system() == "Linux":
        try:
            _open_linux(command)
            return 0, "a new terminal"
        except OSError as error:
            errors.append(str(error))
    detail = "; ".join(errors) if errors else "no terminal emulator found"
    return 1, (f"Could not open a terminal ({detail}). "
               f"Run {command} in your own terminal.")


def open_viewer(root: Path | None = None, *, read_only: bool = False) -> tuple[int, str]:
    """Spawn the live viewer in a real terminal and return immediately."""
    command = viewer_launch_command(root, read_only=read_only)
    code, detail = _open_in_terminal(command)
    if code == 0:
        return 0, f"Opened the handoff viewer in {detail}."
    return code, detail


def open_agent(root: Path | None, agent: str,
               seed: str | None = None) -> tuple[int, str]:
    """Spawn one agent CLI under the handoff bar in a new terminal."""
    from handoff_guard import find_repo_root, seed_claim

    seed = seed or os.urandom(16).hex()
    repo = find_repo_root(root or Path.cwd())
    name = seed_claim(seed, repo / "HANDOFF.md", agent)
    command = agent_launch_command(root, agent, seed=seed)
    code, detail = _open_in_terminal(command)
    if code == 0:
        label = f"{agent} as {name}" if name else agent
        return 0, f"Opened {label} with the handoff bar in {detail}."
    return code, detail
