# Live terminal progress

Run the viewer in a separate terminal while agents update the ledger:

```sh
python3 /path/to/skill/scripts/handoff_tui.py --root /path/to/repository
```

Use the script from the installed skill directory or from this repository's
`skills/handoff/scripts/` directory. Requires Python 3.9+. Live mode uses the
standard-library `curses` module, normally available on macOS and Linux; Python
builds without curses can use `--once`. These modes have no third-party dependencies;
the optional `--codex` mode described below needs tmux.

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
`$HANDOFF_TUI`, then a `handoff_tui.py` beside the launcher, then project and
global `.agents`/`.codex` skill installs, then the registered
plugin install, then the plugin cache and marketplace directories, then
`$HANDOFF_SKILL_REPO`. Preferring a sibling means a launcher run in place inside
a skill directory uses that copy, while one copied onto PATH resolves the newest
install. When several versioned directories match, version numbers are compared
numerically, so 1.10.0 outranks 1.5.0. Set `$CLAUDE_CONFIG_DIR` if the Claude
configuration is not at `~/.claude`. With no copy found, the launcher exits 1
and names both environment variables rather than guessing.

Project discovery walks up from the current directory, stopping at the first
Git root. Global discovery checks `~/.agents/skills/handoff`, then
`$CODEX_HOME/skills/handoff` (default `~/.codex/skills/handoff`). Codex mode skips
old installs missing `handoff_codex.py`; an explicit `$HANDOFF_TUI` that lacks
it reports an update error.

The default refresh interval is one second. The viewer re-reads the file,
including after an atomic replacement by `handoff_guard.py apply`. Progress
appears when an agent saves a ledger update; it does not monitor an agent
process or unsaved work.

The live view makes exactly one kind of edit: handing a task to another agent,
described in [Moving a task to another agent](#moving-a-task-to-another-agent).
Every other mode - `--once`, `--bar`, `--codex` - only reads; the Codex bar
opens that live view on `Ctrl-G` rather than editing anything itself, and
`--read-only` turns the move keys off in the live view and in that popup.

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
| x | Cut the selected task, or put a held one back |
| p | Give the held task to the selected agent or task's owner |
| P | Give the held task to an owner name you type |
| q, Ctrl-C | Quit and restore the terminal |

Resize the terminal as needed; live mode needs at least 64 columns and 14 rows.
Long headings are clipped in lists and available in task details. The screen
shows read errors and retains the last readable snapshot, labelled stale, until
the file becomes readable again. A missing file at startup is retried without
creating it.

## Moving a task to another agent

When an agent cannot finish its task - it is running out of context, it is
stopping for the day, or the work belongs elsewhere - the task can be handed
over from the live view. Select it in the Tasks view and press `x` to cut it,
then press `p` on the receiving agent in the Agents view, on any task that agent
already owns, or inside that agent's filtered task list. Press `P` instead to
type an owner name, which is how a task reaches an agent that has no ledger
entry yet. The held task is marked `*` and named in the line above the footer;
`x` again puts it back, and cutting is available from task details too.

After a successful paste the view opens the receiving agent's task list with the
moved task selected and marked `+`, so the task is visible under its new owner
rather than described by a message; the header names whose list it is, and `b`
returns to all tasks. The line above the footer keeps naming the receiving agent
until the next cut or move, so checking the result does not erase the evidence,
and it leads with that agent's name so a narrow terminal clips the task title
instead of the answer.

A move rewrites the `(owner: ...)` label in that one heading and appends a dated
sentence to the task's status naming the previous owner. It changes nothing
else: state boxes, steps, and the entry's position in ledger order all stay as
they were, because ledger order records when work was raised while the label
records who holds it. Pasting onto `unassigned` removes the label instead.

The write is the same compare-and-swap `handoff_guard.py apply` uses: the same
lock, the same version check against the revision on screen, and the same
refusal to introduce structural errors. If a peer changed the ledger after the
cut, nothing is written and the view reloads so the move can be reconsidered
against the new entries - that refusal is the point, so do not repeat the move
without reading what changed.

Moving a task assigns it; it does not perform it, notify anyone, or transfer
context. Tell the receiving agent, and expect that agent to record its own
takeover in the status text per the ledger contract. Use `--read-only` for a
terminal that should never write - a shared screen, or a session watching
someone else's repository:

```sh
handoff-tui --root /path/to/repository --read-only
```

## Status-line mode

`--bar` prints a single row for a host status bar and exits, instead of drawing
a dashboard:

```sh
handoff-tui --bar          # handoff █████████░ 17/18 tasks · 70/73 steps · Codex
```

It reads the host's session JSON on stdin when stdin is not a terminal, taking
`workspace.current_dir` (falling back to `cwd`) as the repository, so the bar
follows the session rather than the directory the host was launched from. An
explicit `--root` or `--file` wins over the payload; an unparsable payload is
ignored rather than fatal. `--no-color` omits the ANSI codes.

The row is deliberately silent and exits 0 when there is no ledger or nothing
tracked, so a status bar in an unrelated repository stays empty instead of
showing an error. Colour is green at full completion and amber otherwise, and
the trailing names are the owners of entries not recorded complete.

In Claude Code, `/handoff:status` wires this into `statusLine`; see the README.
Point any such configuration at the `handoff-tui` launcher rather than a
versioned plugin path, so it survives upgrades.

## Codex with a live bottom bar

```sh
handoff-tui --root /path/to/repository --codex
handoff-tui --root /path/to/repository --codex resume --last
```

This mode starts Codex inside a private tmux session and keeps one Handoff row
below it. It needs an interactive terminal, tmux 3.2+, and Codex CLI on PATH.
It works on macOS/Linux and in WSL. Viewer flags go before `--codex`; all
following arguments belong to Codex. `--once` and `--bar` cannot be combined
with this mode. Use `--interval` to change polling or `--no-color` for an
uncoloured row. Exit Codex normally to close the wrapper.

The ledger path stays fixed for the invocation. Details about directory
selection, tmux ownership, and verification are in
[Codex setup](harness-setup.md#codex-cli).

### Opening the viewer from the bar

The bar reports progress but cannot change it, so one key opens the full viewer
over Codex: press `Ctrl-G` and the live view appears in a popup, with the same
`x` and `p` keys for [moving a task to another
agent](#moving-a-task-to-another-agent). Press `q` to close the popup and return
to the Codex prompt exactly where it was; Codex keeps running underneath, and
the ledger is the same one the bar is reporting.

The row ends with `^G open` while the key is bound. `Ctrl-G` is the only key
this mode keeps for itself - the private session has no tmux prefix, so every
other key still reaches Codex. Set `$HANDOFF_VIEWER_KEY` to any tmux key name
to move it, or to `none` to give it back to Codex and drop the hint:

```sh
HANDOFF_VIEWER_KEY=M-h handoff-tui --root /path/to/repository --codex
HANDOFF_VIEWER_KEY=none handoff-tui --root /path/to/repository --codex
```

`--read-only` carries into the popup, so a bar started read-only opens a viewer
that cannot write. A tmux that will not accept the binding - one older than the
3.2 this mode requires, or an unknown key name - leaves Codex running and drops
the hint from the row rather than advertising a key that does nothing.

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
