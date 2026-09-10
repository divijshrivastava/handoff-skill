# Live progress bar per agent harness

`scripts/handoff-bar` prints one row of recorded ledger progress and exits. It
is the piece a host status line runs; `handoff-tui` is the full dashboard a
person runs in a terminal.

## What each harness supports

Determined by reading each tool's shipped documentation or inspecting its
installed binary on 2026-09-08, at the versions named. Treat a "no" as "no hook
found at that version", not as a permanent limit; re-check after upgrades.

| Harness | Version checked | Custom status line | Payload shape |
| --- | --- | --- | --- |
| Claude Code | 2.1.260 | Yes, `statusLine` command | `workspace.current_dir`, `cwd` |
| Grok CLI | 1.0.13 | Yes, `[ui.status_line] type = "command"` (verified) | `workspace.current_dir`, `cwd` |
| Kimi Code | 0.41.0 | Yes, `[status_line] command` in `tui.toml` (verified) | flat `cwd` |
| Codex CLI | 0.153.4 | No command hook found; use `handoff-tui --codex` | Private tmux footer |
| opencode | 1.18.3 | Built-in segments only | — |
| Cursor agent | 2026.09.02 | None found | — |

`handoff-bar` reads `workspace.current_dir` and falls back to `cwd`, so all
three supported payload shapes work without per-host configuration. A harness
with no status line still gets the dashboard: run `handoff-tui` in a second
terminal, which needs nothing from the host.

## Platform support

| Piece | Linux, macOS | Windows |
| --- | --- | --- |
| The skill contract itself | Yes | Yes, it is prose and needs no runtime |
| `handoff_guard.py` | Yes, `fcntl` lock | Yes, `msvcrt` lock |
| `handoff_tui.py --once` and `--bar` | Yes | Yes, neither path imports curses |
| `handoff_tui.py` live dashboard | Yes | **No.** Stdlib Python has no `curses` on Windows; use WSL |
| `handoff-bar` | Yes | **No.** Needs POSIX `sh`, `sed`, `cksum` |
| `handoff-tui --codex` | Yes, tmux 3.2+ required | Use WSL with Codex and tmux installed inside WSL |

On Windows, point the status line at the viewer directly, which needs only
Python:

```json
"statusLine": {
  "type": "command",
  "command": "python \"%USERPROFILE%\\\\handoff\\\\scripts\\\\handoff_tui.py\" --bar",
  "refreshInterval": 2
}
```

That path costs a Python start per tick rather than `handoff-bar`'s cached
row, which is acceptable where no host imposes a tight timeout. `handoff-bar`
is a POSIX fast path, not the portable one.

Everything here needs Python 3.9+. Nothing needs Node: most agent harnesses
ship native binaries, and an npm-delivered one usually vendors a compiled
binary rather than running from source.

## Codex CLI

```sh
handoff-tui --codex
handoff-tui --root /path/to/repo --interval 2 --codex
handoff-tui --root /path/to/repo --codex resume --last
```

Run these in your terminal. Codex CLI and tmux 3.2+ must be on PATH. From a
checkout, use `./skills/handoff/scripts/handoff-tui` before installing the
launcher. No Codex configuration edit is needed.

## Any agent CLI

Nothing in the wrapper is specific to Codex, so `--with` runs the same bar and
the same viewer key around any agent CLI on PATH. `--codex` is `--with codex`:

```sh
handoff-tui --with claude
handoff-tui --root /path/to/repo --with kimi
handoff-tui --root /path/to/repo --with grok -p "what is left?"
```

This matters most for the harnesses whose own status line already works. A
status line shows progress; it cannot open the viewer, because no harness in
the table above can bind a key to an arbitrary command - Claude Code's
`keybindings.json` accepts only its own fixed `chat:` and `app:` actions. Under
`--with`, the key is bound in tmux's root table, which resolves it before the
agent is reached, so one key opens the viewer in every harness including those
that have no key hook at all.

The current [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
defines `tui.status_line` as a list of built-in footer item identifiers. No
custom command hook was found in Codex CLI 0.153.4. This wrapper reserves one
bottom row through tmux and runs the normal Codex TUI above it. It cannot add
a bar to the Codex desktop app or a CLI session that is already running.

Put Handoff options before `--codex`; the rest are passed literally to Codex.
`--root` sets the starting directory and selects its repository ledger;
`--file` selects an exact ledger and starts Codex in its parent directory.
The bar stays pinned to that ledger. Use `--root` to select the project, and
choose the same project when resuming; a forwarded Codex `-C`/`--cd` or a
resume-time directory switch does not retarget the bar.

The bar polls once a second by default, including while Codex is idle. Missing
ledgers show a waiting row; unreadable files label retained counts as stale.
All counts remain recorded progress, not completion evidence.

Each invocation owns a private tmux socket, ignores `~/.tmux.conf`, and removes
its server when the agent exits or the wrapper stops. It does not modify an
existing tmux server. Prefix shortcuts are disabled in the private server so
keys reach the agent, with one exception: `Ctrl-G` opens the live viewer in a
popup over it, so a task can be moved to another agent without leaving the
session. Set `$HANDOFF_VIEWER_KEY` to another tmux key name to move it, or to
`none` to give that key back. When launched inside tmux, the outer session's
prefix still belongs to the outer session. Exit the agent normally; the wrapper
returns its exit code. Detaching or stopping the wrapper closes its agent too.

### Releasing the key in the host

`Ctrl-G` was chosen because it is ASCII BEL: it aliases no terminal key the way
`Ctrl-H`, `Ctrl-I` and `Ctrl-M` alias Backspace, Tab and Enter, carries no
signal like `Ctrl-C`, `Ctrl-Z` or `Ctrl-\`, is not flow control like `Ctrl-S`
and `Ctrl-Q`, and can be intercepted by tmux. Function keys lose to macOS media keys by
default and `Alt` keys lose to the terminal's Option handling, which is why
neither is the default.

Both Claude Code and Codex claim it: Claude Code runs `chat:externalEditor`,
and [Codex opens the editor set by VISUAL or EDITOR](https://learn.chatgpt.com/docs/cli-customization).
Inside a `--with` session tmux resolves the key first. In a plain `codex`
session, installing the skill alone does not bind the viewer key. Install a
terminal shortcut to use it without the wrapper:

```sh
handoff-tui --install-viewer-key
```

That detects the current terminal emulator when it can. For **Claude Code** it
rewrites `~/.claude/keybindings.json` to release the key and move
`chat:externalEditor` onto `ctrl+e`, the alternative Claude Code's own
documentation uses for this rebinding. Claude Code cannot bind a key to run an
external command, so that step only stops the host from stealing the key; use
`/handoff:view` or `handoff-tui --with <agent>` for a key that actually opens
the viewer. For **kitty** and **wezterm** it writes a marked configuration
snippet. **iTerm2 on macOS** receives a dynamic Handoff profile and a global
shortcut using “New Window with Profile.” It merges the key into `GlobalKeyMap`,
backs up previous preferences, and also writes an importable `.itermkeymap`.
It never sends a command into the running agent. Existing conflicting global
or profile bindings are reported without overwriting them.
Pass `--emulator` to choose explicitly. It merges rather
than replaces where possible, running twice reports that the key is already
released or installed, and a file that does not parse is left untouched rather
than replaced. It follows `$HANDOFF_VIEWER_KEY`, and skips with a message for a
key that has no supported spelling. The iTerm2 installer also accepts `C-M-`
letter combinations for Control+Option; the Claude-only override does not.

Use **Ctrl+Alt+H** (**Control+Option+H** on macOS) in iTerm2, even in a plain
Codex session. This leaves **Ctrl+V** available for pasting images into Codex:

```sh
HANDOFF_VIEWER_KEY=C-M-h handoff-tui --install-viewer-key --emulator iterm2 --root /path/to/repo
```

Changing the key removes previous shortcuts to the same repository's Handoff
profile, including an earlier Ctrl+V binding. Other shortcuts and other
repositories' viewer bindings are preserved. The
[iTerm2 shortcut](https://iterm2.com/documentation-preferences-profiles-keys.html)
is pinned to that repository. It opens a separate window;
`q` closes the viewer. If an existing window retains the previous binding,
restart iTerm2 when convenient. This does not change `VISUAL` or `EDITOR`.
**Cursor** (and any VS Code based editor with Cursor's configuration layout)
takes a different route, because its integrated terminal is not an emulator with
a key table of its own:

```sh
HANDOFF_VIEWER_KEY=C-M-h handoff-tui --install-viewer-key --emulator cursor --root /path/to/repo
```

That writes three things. A `Handoff viewer` task in the repository's
`.vscode/tasks.json`, whose command runs the launcher with
`--root "${workspaceFolder}"`, so the file stays portable and the key opens
whichever repository the window has open. A keybinding on
`workbench.action.tasks.runTask` in the user's `keybindings.json`, inserted
textually so the file's comments and existing bindings survive. And
`workbench.action.tasks.runTask` in `terminal.integrated.commandsToSkipShell`
in `settings.json`, without which Cursor forwards the keystroke to the shell
whenever the terminal has focus - the case this exists for. The task label is
the same constant in every repository, so one global keybinding serves all of
them, and a window whose workspace has no such task reports that the task is
missing rather than opening the wrong ledger. The key runs a task; it never
sends a command into the running agent. A repository that has not been
installed into needs its own `--emulator cursor` run, and the generated task
file names this machine's interpreter, so it belongs in `.gitignore` rather
than in version control. Reload the window after installing.

For a popup inside the same terminal, run
`HANDOFF_VIEWER_KEY=C-M-h handoff-tui --codex` instead, without an iTerm2
binding for the same key, and with Option configured to send Esc+ so tmux
receives it.

Verification: argument forwarding, refresh, stale data, format escaping,
failure cleanup, and packaged loading have regression tests. The optional
real-tmux test exercises a stand-in CLI's input and exit status. A live Codex
session has not been observed with this wrapper: the development sandbox
denies tmux server sockets.

## Setup

Copy both scripts once onto PATH, then point the host at `handoff-bar`:

```sh
cp "$SKILL_DIR/scripts/handoff-bar" "$SKILL_DIR/scripts/handoff-tui" ~/.local/bin/
chmod +x ~/.local/bin/handoff-bar ~/.local/bin/handoff-tui
```

**Claude Code** — `~/.claude/settings.json`:

```json
"statusLine": {
  "type": "command",
  "command": "$HOME/.local/bin/handoff-bar",
  "padding": 0,
  "refreshInterval": 2
}
```

**Grok CLI** — `~/.grok/config.toml`. Grok reads this section at startup, so
restart it afterwards:

```toml
[ui.status_line]
type = "command"
command = "~/.local/bin/handoff-bar"
refresh_interval = 2
```

**Kimi Code** — `~/.kimi-code/tui.toml`, not `config.toml`:

```toml
[status_line]
command = "~/.local/bin/handoff-bar"
```

Kimi renders only the first stdout line, which is all the bar prints. Verified
in a live session: the row joins Kimi's own footer segments rather than
replacing them.

Grok's row is event-driven — session start, turn end, a model switch, a HEAD
move — and `refresh_interval` adds a timer on top. In a live session the row
appeared after the first interaction rather than on the empty startup screen,
so expect it to arrive once something happens, not necessarily on the first
frame. If it never appears, check `grok inspect`: a status-line command is
gated behind workspace trust, and an untrusted project reports
`Project trusted: no`.

## Why a separate script instead of `handoff-tui --bar`

A status line re-runs its command on every render, and hosts cap how long it may
take: Kimi's cap is 300ms, and Claude Code and Grok debounce at 300ms. Starting
Python costs roughly 100ms before any work, and going through the `handoff-tui`
launcher pays that twice, measured at about 250ms per run — inside Kimi's cap
only by a margin that machine load erases.

`handoff-bar` is POSIX `sh`. It caches the rendered row and re-runs the viewer
only when the ledger's contents change, which took a measured 31ms per cached
run against a 33KB ledger, against 136ms for the viewer alone.

The cache key is a `cksum` of the ledger's contents, deliberately not its
modification time and size, plus a per-session suffix derived from the host's
`session_id` and the same environment fallbacks the bar uses to recall a claimed
name. Checking a box rewrites `[ ]` as `[x]` and leaves the byte count
identical, so a size stamp serves a stale row for exactly the edit the bar
exists to show. Without the session suffix, every terminal in one repository
would show whichever agent's name warmed the cache first. A regression test
covers both cases.

## Behavior worth knowing

- No ledger, or nothing tracked: prints nothing and exits 0, so a status line in
  an unrelated repository stays empty rather than showing an error.
- Malformed or absent payload: falls back to the working directory rather than
  failing.
- `--root` and `--file` override the payload; `HANDOFF_TUI` pins the viewer,
  `HANDOFF_PYTHON` the interpreter, and `HANDOFF_BAR_CACHE` the cache directory.
- The row reports **recorded** progress: checkboxes and heading owners. It is
  not evidence that work is finished, that an owner is active, or that an owner
  performed a step. See `progress-viewer.md` for the counting rules.
