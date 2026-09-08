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
| Grok CLI | 1.0.13 | Yes, `[ui.status_line] type = "command"` | `workspace.current_dir`, `cwd` |
| Kimi Code | 0.41.0 | Yes, `[status_line] command` in `tui.toml` | flat `cwd` |
| Codex CLI | 0.153.4 | No command hook found | — |
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

Kimi renders only the first stdout line, which is all the bar prints.

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
modification time and size. Checking a box rewrites `[ ]` as `[x]` and leaves
the byte count identical, so a size stamp serves a stale row for exactly the
edit the bar exists to show. A regression test covers that case.

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
