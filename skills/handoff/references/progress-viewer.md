# Live terminal progress

Run the viewer in a separate terminal while agents update the ledger:

```sh
python3 /path/to/skill/scripts/handoff_tui.py --root /path/to/repository
```

Use the script from the installed skill directory or from this repository's
`skills/handoff/scripts/` directory. Requires Python 3.9+. Live mode uses the
standard-library `curses` module, normally available on macOS and Linux; Python
builds without curses can use `--once`. There are no third-party dependencies.

A plugin install lives under a version-pinned directory, so a command line
naming one stops working at the next release. `scripts/handoff-tui` is a
launcher that resolves the viewer at run time; copy it once onto PATH and it
survives upgrades:

```sh
cp "$SKILL_DIR/scripts/handoff-tui" ~/.local/bin/ && chmod +x ~/.local/bin/handoff-tui
handoff-tui --root /path/to/repository
```

Copy the launcher rather than symlinking it: a symlink points back into the
version-pinned directory and breaks on the next upgrade, which is the problem
the launcher exists to solve.

It forwards every argument to `handoff_tui.py` unchanged and adds one flag of
its own, `--which`, which prints the copy it resolved. Resolution order is
`$HANDOFF_TUI`, then a `handoff_tui.py` beside the launcher, then the registered
plugin install, then the plugin cache and marketplace directories, then
`$HANDOFF_SKILL_REPO`. Preferring a sibling means a launcher run in place inside
a skill directory uses that copy, while one copied onto PATH resolves the newest
install. When several versioned directories match, version numbers are compared
numerically, so 1.10.0 outranks 1.5.0. Set `$CLAUDE_CONFIG_DIR` if the Claude
configuration is not at `~/.claude`. With no copy found, the launcher exits 1
and names both environment variables rather than guessing.

The default refresh interval is one second. The viewer re-reads the file,
including after an atomic replacement by `handoff_guard.py apply`. It never
edits the ledger or acquires the writer's lock. Progress appears when an agent
saves a ledger update; it does not monitor an agent process or unsaved work.

## Views and controls

Overall completed tasks and checked steps stay visible above the current view.
The **Agents** view groups totals by the exact owner label in each heading and
shows completed/total tasks, in-progress tasks, pending tasks, and step progress.
Unowned entries appear as `unassigned`. Press Enter on an owner to browse their
tasks, then Enter on a task to read its steps and full status text.

| Key | Action |
| --- | --- |
| Tab, a, t | Switch views, or open Agents / Tasks directly |
| Up/Down, k/j | Select a row or scroll task details |
| Page Up/Page Down, Home/End | Move through long lists or details |
| Enter | Open the selected owner's tasks or task details |
| b, Escape, Backspace | Close details, then clear the owner filter |
| r | Refresh immediately |
| q, Ctrl-C | Quit and restore the terminal |

Resize the terminal as needed; live mode needs at least 64 columns and 14 rows.
Long headings are clipped in lists and available in task details. The screen
shows read errors and retains the last readable snapshot, labelled stale, until
the file becomes readable again. A missing file at startup is retried without
creating it.

## Counting rules

- Task completion is the number of valid structured tasks with `Completed`
  checked, divided by the number of valid structured tasks.
- Step completion is checked steps divided by total steps across valid tasks.
  Each step has equal weight; task-level state boxes are not steps. An empty
  denominator displays `n/a`, and percentages are rounded to whole numbers.
- Invalid and legacy entries are listed but excluded from progress totals.
  `!` and `?` in the owner table count invalid and legacy entries respectively.
  Open task details for structural errors, and use the guard's `validate`
  command to check the ledger.
- Fenced examples do not count, following the guard's parser. Status prose does
  not override checkboxes. All entries remain visible in ledger order, including
  stale or superseded entries; use the progressive audit to resolve them.
- Ownership comes from the heading, including `(owner: ...)` or `(agent: ...)`.
  A takeover recorded only in prose does not change attribution. These totals
  show progress assigned to recorded owners; they cannot prove who performed
  each step, effort spent, or whether an owner is currently running.

## Snapshot and path options

```sh
# Print once; also the default when input or output is not a terminal
python3 /path/to/skill/scripts/handoff_tui.py --root /path/to/repository --once

# Use a specific ledger filename, including a lowercase handoff.md
python3 /path/to/skill/scripts/handoff_tui.py --file /path/to/handoff.md

# Adjust polling (0.1 to 60 seconds)
python3 /path/to/skill/scripts/handoff_tui.py --root /path/to/repository --interval 2
```

`--root` accepts a repository or child directory and defaults to the current
directory, using the same root discovery as the guard. `--file` selects an exact
path instead and cannot be combined with `--root`. Snapshot mode emits plain
text without terminal controls and exits 1 on a read or structural error, 0
otherwise. Live mode keeps displaying errors while waiting for corrections.
