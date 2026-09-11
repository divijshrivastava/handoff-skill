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

The live view makes two kinds of edit: handing a task to another agent,
described in [Moving a task to another agent](#moving-a-task-to-another-agent),
and marking work complete at the user's direction, described in
[Marking work complete](#marking-work-complete). Every other mode - `--once`,
`--bar`, `--codex` - only reads; the Codex bar opens that live view on `Ctrl-G`
rather than editing anything itself, and `--read-only` turns those write keys off
in the live view and in that popup.

## Views and controls

Overall completed tasks and checked steps stay visible above the current view.
When a `Lead:` mandate is recorded, a **LEAD** summary line names who coordinates
and how long the mandate has left. In the Agents list that owner is tagged
`[LEAD]`. In Tasks, entries with leader assignment metadata show compact
provenance and dependency markers; open a task for the full assignment line,
reserved paths, and any unmet `needs`.
The **Agents** view lists every agent the user can hand work to. By default it
shows **this repository** only: **waiting** agents lead the list — sessions
that claimed a name for this ledger on this machine within the last fifteen
minutes but hold no ledger tasks yet, newest claim first. Opening an agent
with **N** also asks for an optional task, writes one in-progress intake entry
for that name (a **Session work** placeholder or a task entry with your
direction), and passes a typed task to the agent CLI as its opening prompt, so
its Done/Task and WIP counters update immediately. Below them,
**recorded owners** appear in ledger order rather than alphabetically, so the
agent who most recently raised work leads that section; the header says
`newest first`. Press **`m`** to switch to **machine** scope and see every
recent name claim on this machine, with harness and repository (`here` marks
this ledger). That view is read-only for task browsing: press **`m`** again
to return to this repository's agents before pressing Enter on an owner.
Each repo-scoped row shows completed/total tasks, in-progress tasks, pending
tasks, and step progress. Beside a name sits the harness that owner recorded,
taken from their newest entry that names one, so a ledger written by Claude
Code, Codex and Cursor sessions reads as more than a list of names. `(recent)`
marks a waiting agent or a recorded owner whose name was also claimed recently:
a session refreshes that record only when it asks for its name, so it evidences
a recent claim, never a running process or current work. Unowned ledger entries
appear as `unassigned`. Press Enter on an owner to browse their tasks, then
Enter on a task to read its steps and full status text. Select a waiting agent
and press `p` while holding a cut task to assign it the same way as a recorded
owner.

| Key | Action |
| --- | --- |
| Tab, a, t | Switch views, or open Agents / Tasks directly |
| m (Agents) | Toggle agent scope between this repository and every recent claim on this machine |
| L (Agents) | Designate the selected agent as leader for four hours; press again on the current leader to resign |
| N (Agents) | Pick an agent CLI on PATH, optionally type a task, and open it in a new terminal under the handoff bar; the viewer writes one in-progress intake entry for that agent (a **Session work** placeholder when the task is left blank, or a task entry carrying your direction and an execution request when you typed one) so Done/Task and WIP counters update before the agent edits the ledger, and a typed task is also passed to the agent CLI as its opening prompt |
| c | Open the local agent channel |
| s (Channel) | Toggle messages and registered sessions |
| Up/Down, k/j | Select a row; in task details, select an individual step |
| Page Up/Page Down, Home/End | Move through long lists or details |
| gg, G | Jump to the first or last line, in a list or in details |
| Enter | Open tasks or details; in Channel, filter by session or read a message |
| b, Escape, Backspace | Close details, then return to Agents with the owner still selected |
| r | Refresh immediately |
| x | Cut the selected task or detail step; repeat on it to put it back |
| X | Cut the whole task, including from task details |
| p | Give the held task or step to the selected agent or task's owner |
| P | Give the held task to an owner name you type |
| d (details) | Mark the selected step complete at your direction |
| D | Mark the selected task complete at your direction |
| q, Ctrl-C | Quit and restore the terminal |

Resize the terminal as needed; live mode needs at least 64 columns and 14 rows.

### Agent channel

Press `c` to read who sent what to whom from the repository's local
`.handoff/channel.sqlite3`. The list shows the newest 200 messages, local send
time, sender, recipient, acknowledgement, and a body preview. A notice appears
when older messages are omitted. Enter opens the full body, message kind and
ID, reply reference, and the names of agents that acknowledged it. Broadcasts
show `all agents` and the count of recorded receipts; this count is not a
delivery or completion total.

Press `s` for registered sessions, with each agent's harness and reported state
and report age. Enter on a session filters the recent messages to those it sent
or received, including broadcasts. `b` returns to the session list after closing
message details; `s` returns to all messages. Reports are claims with an age,
not a live-process check. Receipts establish acknowledgement, not task progress.

The channel refreshes at the existing interval and with `r`, independently of
ledger changes, while preserving selection by message or session ID. It reads
sessions, messages and receipts in one read-only transaction, creates no channel
when one is absent, and never acknowledges on an agent's behalf. A failed read
keeps the last snapshot with a visible stale warning until the next good read.
Channel reading works under `--read-only`; the snapshot and bar modes retain
their existing ledger summaries.
Long headings are clipped in lists and available in task details. The screen
shows read errors and retains the last readable snapshot, labelled stale, until
the file becomes readable again. A missing file at startup is retried without
creating it.

## Marking work complete

When you know a step or whole task is done but the ledger still shows it open,
mark it complete from the live view. This is a user override: it checks boxes and
appends a dated note naming the override; it does not prove an agent finished the
work or replace a proper audit.

Open a task with Enter. Use Up/Down or `j`/`k` to select a step, then press `d`
to check that step, ensure `In progress` is checked, and record which step you
marked. When `d` checks the last open step, it also checks `Completed` and
clears any lease, so the task reads as finished. Press `D` from the Tasks view or
from task details to check every step at once,
check both `In progress` and `Completed`, clear any lease on that entry, and
append a dated completion note. Already-complete steps and tasks are left alone.
Structural problems in the entry are refused until the ledger is repaired.

The write uses the same compare-and-swap path as moves and `handoff_guard.py
apply`: one lock, one version check against the revision on screen, and refusal
to introduce structural errors. If a peer changed the ledger after you opened the
view, nothing is written and the view reloads so you can read what changed.
Read-only mode disables both `d` and `D`.

## Moving a task to another agent

When an agent cannot finish its task - it is running out of context, it is
stopping for the day, or the work belongs elsewhere - the task can be handed
over from the live view. Select it in the Tasks view and press `x` to cut it,
then press `p` on the receiving agent in the Agents view, on any task that agent
already owns, or inside that agent's filtered task list. Press `P` instead to
type an owner name, which is how a task reaches an agent that has no ledger
entry yet. The held task is marked `*` and named in the line above the footer;
`x` again on the held item puts it back. In task details, `x` cuts the selected
step and `X` cuts the whole task.

### Moving one step

Open a task with Enter. Use Up/Down or `j`/`k` to select a checkbox, then press
`x`. Press `a` to open Agents, select the receiving agent, and press `p`; you can
also open that agent's task list with Enter and paste there. `P` lets you type a
new owner name. The selected step is highlighted, and the held step is marked
`*` and named above the footer. Page Up/Page Down and `gg`/`G` scroll the details
so long status text remains readable; use `j`/`k` to select a step again.

Pasting one step creates an entry in the receiving agent's task list, with the
step's checkbox and continuation text preserved. The original task keeps its
owner, remaining steps, state, and status; a dated transfer note and a quoted
copy of the moved step preserve its history without counting it twice. The new
entry names the source task and includes its prior status for the receiving
agent's audit. An unchecked step becomes assigned work with the same execution
request as a whole-task move; a checked step retains its recorded completion.
The remaining source task is never automatically marked complete.

If the selected step is the only one left, its original task moves intact.
The prior owner's lease is cleared on that move; a new assignee must declare
its own deadline. When splitting a task, its lease stays with the source and
is not copied to the new entry. Pasting to `unassigned` releases the selected
scope. Read-only mode disables both step and whole-task moves.

### Seeing and preserving the result

After a successful paste the view opens the receiving agent's task list with the
moved task selected and marked `+`, so the task is visible under its new owner
rather than described by a message; the header names whose list it is, and `b`
returns to all tasks. The line above the footer keeps naming the receiving agent
until the next cut or move, so checking the result does not erase the evidence,
and it leads with that agent's name so a narrow terminal clips the task title
instead of the answer.

A move rewrites the `(owner: ...)` label in that one heading and appends a dated
sentence to the task's status naming the previous owner. For an unfinished task
handed to a named agent, it also checks `In progress` so the assignment shows
under WIP immediately; steps and the entry's position in ledger order stay as
they were, because ledger order records when work was raised while the label
records who holds it. Pasting onto `unassigned` removes the label instead and
does not check `In progress`.

The write is the same compare-and-swap `handoff_guard.py apply` uses: the same
lock, the same version check against the revision on screen, and the same
refusal to introduce structural errors. If a peer changed the ledger after the
cut, nothing is written and the held item is cleared, including when an automatic
refresh sees the change before paste. The view reloads so the move can be reconsidered
against the new entries - that refusal is the point, so do not repeat the move
without reading what changed.

Moving an unfinished task to an agent is a user execution request. The saved
note directs that agent to finish its current task, then audit and complete the
assignment, including verification, without another user prompt. An idle agent
starts after its audit. Agents must check their bucket at task boundaries and
before stopping, continue eligible assignments, and record concrete blockers.
Completed tasks are not reopened; moving to `unassigned` releases ownership.

The viewer persists this instruction but does not wake a stopped model or
transfer its context. The receiving agent discovers the assignment on its next
audit and records its own takeover under the ledger contract. Use `--read-only` for a
terminal that should never write - a shared screen, or a session watching
someone else's repository:

```sh
handoff-tui --root /path/to/repository --read-only
```

## Designating a leader

When optional leadership is in play, press `L` on an agent in the Agents view
to designate it as leader for four hours. The mandate is written above the first
entry as a `Lead:` line, using the same compare-and-swap as every other ledger
write. Press `L` again on the current leader to resign. If another agent already
holds an active mandate, the viewer refuses rather than replacing it silently.
Use `scripts/handoff_lead.py` for renew, assign, and the full assignment
lifecycle; see `references/leader.md`. `--read-only` disables the key, as it
disables the move keys.

## Nudging a silent agent

In the Channel view, `n` asks the selected session to answer: read its inbox,
acknowledge it, and report where the work stands, or release it with `yield`. It
sends a message and nothing else. It moves no task, changes no ownership, and
does not touch that peer's reported state, so pressing it while you are unsure
whether an agent is alive costs nothing and settles nothing.

Press `s` for the session list if you are looking at messages. `--read-only`
disables the key, as it disables the move keys.

A nudge needs a real sender, because it is a message. The viewer is a window, not
an agent: it speaks as the session whose terminal it runs in, and refuses rather
than borrowing another agent's identity. A viewer opened from an agent session
carries that session's identity, which the launcher passes as `--session-seed`
because a newly opened terminal inherits nothing. A viewer started by hand in a
terminal that claimed no name has no session to send as and says so. The message
records `via: handoff viewer, at the user's direction`, so the receiving agent can
tell a keypress from the sending session's own decision.

A second press within ten minutes returns the first nudge rather than sending
another: repeating the request adds no information, and burying an inbox is how a
returning owner misses the message that mattered. What silence means afterwards is
unchanged - unknown. `references/agent-channel.md` carries the rest.

## What the agent you assigned sees

A move writes the ledger and nothing else, which is deliberate: `HANDOFF.md`
decides ownership, and a notification that could be missed or duplicated must not
become a second answer to who owns a task. The assignment reaches the agent from
that record, on two surfaces:

- its status line, if it runs one, gains `N assigned to you` for the name it
  claimed. The host re-runs that command on a timer, so this is the only thing
  that appears in a terminal sitting idle;
- its next event - a tool call, a prompt, or a session start - carries a hook
  notice naming the entries, on hosts with the Claude adapter installed.

Both clear when the agent checks In progress, and neither is evidence it has read
anything. An agent with no status line and no turn to take shows nothing until
someone types into it; if you need to know it picked the work up, look for the
entry moving to In progress in this viewer, not at the agent's terminal.

## Status-line mode

`--bar` prints a single row for a host status bar and exits, instead of drawing
a dashboard:

```sh
handoff-tui --bar          # handoff █████████░ 17/18 tasks · 70/73 steps · Janus
```

It reads the host's session JSON on stdin when stdin is not a terminal, taking
`workspace.current_dir` (falling back to `cwd`) as the repository, so the bar
follows the session rather than the directory the host was launched from. When
the payload carries `session_id`, that id is used to recall the name this
session already claimed at preflight. An explicit `--root` or `--file` wins over
the payload; an unparsable payload is ignored rather than fatal. `--no-color`
omits the ANSI codes.

The row is deliberately silent and exits 0 when there is no ledger or nothing
tracked, so a status bar in an unrelated repository stays empty instead of
showing an error. Colour is green at full completion and amber otherwise. The
trailing name is the current session's claimed owner label, not the owners of
open tasks; per-owner progress belongs in the viewer's Agents list. Before
preflight claims a name, the bar omits the trailer rather than guessing.

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

The same key works around any agent, not only Codex: `--with claude`,
`--with kimi` and `--with grok` all run under this bar, and `--codex` is
`--with codex`. The key is bound in tmux's root table, so it is resolved before
the agent it wraps ever sees it - which is why it works even in harnesses that
cannot bind a key to a command themselves. To stop an unwrapped Claude Code
session answering `ctrl+g` with its own editor action, run
`handoff-tui --install-viewer-key` once; see
[releasing the key in the host](harness-setup.md#releasing-the-key-in-the-host).
In Claude Code, `/handoff:view` opens the viewer in a separate terminal because
the harness has no controlling terminal for curses.

The row ends with `^G open` while the key is bound. `Ctrl-G` is the only key
this mode keeps for itself - the private session has no tmux prefix, so every
other key still reaches the agent. Set `$HANDOFF_VIEWER_KEY` to any tmux key
name to move it, or to `none` to give it back to the agent and drop the hint:

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

# List every recent name claim on this machine instead of this repository only
python3 /path/to/skill/scripts/handoff_tui.py --root /path/to/repository --once --agents machine

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
