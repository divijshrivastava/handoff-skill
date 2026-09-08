# Handoff

> Keep AI agents from redoing finished work, overwriting active work, or losing context between sessions.

Handoff is an agent skill for repositories where work continues across multiple AI-agent sessions. It uses a shared `HANDOFF.md` ledger and repository evidence—Git history, current code, tests, and ownership—to determine what is **actually** unfinished.

![Handoff demo](scripts/demo/handoff.gif)

## Why Handoff?

An unchecked task is not always unfinished.

Another agent may have already implemented it. A commit may have satisfied it. The requirement may have changed. Or someone else may still own the affected files.

Before acting, Handoff helps an agent:

- Audit stale ledger entries against code, commits, and verification evidence
- Preserve work owned by another active agent
- Keep new requests visible without losing unfinished work
- Record a precise next action when a session stops mid-task
- Safely update the ledger when multiple agents share one working tree

## Install

### Claude Code

```bash
/plugin marketplace add divijshrivastava/handoff-skill
/plugin install handoff@divij-skills
```

Reload plugins or start a new Claude Code session after installation:

```bash
/reload-plugins
```

### Other agent hosts

```bash
npx skills add divijshrivastava/handoff-skill --skill handoff
```

Add `-g` to install globally.

**Requirements:** Git, an agent with repository read/edit access, and Python 3.9+ for the optional helper. The live dashboard needs a POSIX terminal; the optional Codex bar also needs tmux 3.2+. Handoff needs no API key, external service, or third-party Python package.

## Use it

Ask your agent to use Handoff explicitly:

```text
Use handoff to audit HANDOFF.md and tell me what is actually unfinished.
```

```text
Use handoff. Finish the unassigned migration first, then add the dashboard.
```

```text
Use handoff to pause this task with verification results and the exact next action.
```

Skill auto-selection depends on your host. Installing Handoff does not install hooks or guarantee it runs for every task.

## What happens

| Situation | Handoff does |
|---|---|
| An old task remains unchecked | Checks later commits, code, and ledger entries before treating it as unfinished |
| Work is already implemented | Records the evidence and resolves the stale entry instead of redoing it |
| Another agent owns related work | Preserves the work and reports the specific ownership conflict |
| A check fails | Keeps the task open with failure evidence and a concrete next action |
| A session ends mid-task | Leaves a useful, verifiable continuation point for the next agent |
| New work arrives | Queues it without silently discarding earlier unfinished work |

## The ledger

Handoff stores project work in a root-level `HANDOFF.md`. Each task records ownership, state, completed steps, evidence, and the next action.

```md
## 2026-09-07 — Add search (owner: Amaterasu)

State:
- [x] In progress
- [ ] Completed

Steps:
- [x] Implement search filtering.
- [ ] Verify empty-query and no-results behavior.
- [ ] Record verification and the next action.

Status: Filtering exists. Edge-case verification remains.
Next action: Add and run empty-query/no-results tests.
```

Completed tasks retain both state boxes checked, so the ledger remains useful as history. See the full [ledger contract](skills/handoff/references/ledger-contract.md) for formatting rules and examples.

## Live progress dashboard

Watch overall completion and each agent's recorded progress while they work:

```bash
python3 skills/handoff/scripts/handoff_tui.py --root /path/to/your/repo
```

Run this from a checkout of this repository, or use the script's path inside
your installed handoff skill. It refreshes every second as agents save ledger
updates. The Agents view shows completed tasks and checked steps per owner;
press Enter to browse an owner's tasks and inspect their steps and status.
Use Tab to switch views, arrow keys to navigate, and `q` to quit.

When an agent is about to run out of context, its task can be handed over from
the live view: select the task, press `x` to cut it, then press `p` on the
receiving agent (or `P` to type a name). That rewrites the task's owner label
and records the change in its status, using the same locked compare-and-swap as
the writer helper, and leaves state, steps, and ledger order untouched. Pass
`--read-only` for a terminal that must never write.

You can also hand one agent another agent's whole bucket: tell the receiving
agent to take over, naming the prior owner. It preserves the prior owner's
uncommitted work, moves every open entry in one locked ledger write, and
records the transfer in each entry's status, so the prior owner sees the move
the next time it audits the ledger and reports it instead of resuming.

Add `--once` for a plain-text snapshot, `--interval 2` to change the refresh
rate, or `--file /path/to/handoff.md` for an explicit ledger filename. Live mode
uses Python's standard-library curses module on macOS/Linux; snapshot mode also
works without curses. No package installation or service is needed.

A plugin install lives under a version-pinned directory, so a command line
naming one breaks at the next release. The skill ships a launcher that resolves
the viewer at run time; copy it once onto your PATH:

```bash
cp skills/handoff/scripts/handoff-tui ~/.local/bin/ && chmod +x ~/.local/bin/handoff-tui
handoff-tui --root /path/to/your/repo
```

It takes the same flags, plus `--which` to print the copy it resolved. Copy it
rather than symlinking, so it does not point back into a version-pinned path.

Percentages reflect recorded checkboxes and heading owners. They do not measure
effort or verify who performed a step; stale entries still need an audit.
See [controls and counting rules](skills/handoff/references/progress-viewer.md).

### Codex with the bar

Run Codex and keep a live Handoff progress bar at the bottom of the same terminal:

```bash
./skills/handoff/scripts/handoff-tui --codex
# Or, after copying the launcher onto PATH:
handoff-tui --root /path/to/your/repo --codex
handoff-tui --root /path/to/your/repo --codex resume --last
```

Requires Codex CLI and tmux 3.2+ on PATH (macOS/Linux or WSL). Put viewer
options such as `--root`, `--file`, `--interval 2`, and `--no-color` before
`--codex`; everything after it goes to Codex. The bar refreshes while idle and
shows recorded task and step counts plus open owners.

Press `Ctrl-G` to open the live viewer in a popup over Codex, hand a task to
another agent with `x` and `p`, then `q` to drop back to the Codex prompt. The
row ends with `^G open` while that key is bound; `$HANDOFF_VIEWER_KEY` moves it
to another tmux key or turns it off with `none`, and `--read-only` opens a
viewer that cannot write.

Codex's native footer exposes built-in items; this mode supplies the Handoff
row through a private tmux session. Exit Codex normally to return to your shell.

### Any agent with the bar

Nothing in that wrapper is Codex-specific. `--with` runs the same bar and the
same `Ctrl-G` viewer around any agent CLI on PATH, so one key opens the ledger
whichever agent you are in:

```bash
handoff-tui --with claude
handoff-tui --root /path/to/your/repo --with kimi
handoff-tui --root /path/to/your/repo --with grok -p "what is left?"
```

`--codex` is simply `--with codex`. No harness can bind a key to an arbitrary
command of its own - Claude Code's `keybindings.json` accepts only its own fixed
actions - so the key is bound in tmux's root table, which resolves it before the
agent sees it. In an *unwrapped* session, both Codex and Claude Code use
`Ctrl-G` for their external editor. Installing the skill does not intercept it.
To install the viewer key in a supported terminal, run:

```bash
handoff-tui --install-viewer-key
```

The installer detects the terminal. In iTerm2 it creates a dedicated Handoff
profile and merges a global shortcut that opens the viewer in a new window.
Set `HANDOFF_VIEWER_KEY=C-M-h` before the iTerm2 install command to use
`Ctrl+Alt+H` (`Control+Option+H` on macOS). Keep `Ctrl+V` for Codex image paste.
Changing the key removes previous shortcuts to the same repository's viewer.
The shortcut selects the repository where the installer runs; use `--root` to
choose another. In **Cursor** the same key works inside the integrated terminal:
`--emulator cursor` binds it to a `Handoff viewer` workspace task and adds that
command to `terminal.integrated.commandsToSkipShell`, so Cursor answers the key
instead of passing it to the shell. The Claude-only path releases `Ctrl-G` and
moves its editor action to `Ctrl-E`, but cannot launch the viewer itself. See
[the key and its host override](skills/handoff/references/harness-setup.md#releasing-the-key-in-the-host).
The launcher also discovers project `.agents/skills/handoff` and
`.codex/skills/handoff`, global `~/.agents/skills/handoff`, and
`$CODEX_HOME/skills/handoff` (default `~/.codex/skills/handoff`). See
[Codex setup and limits](skills/handoff/references/harness-setup.md#codex-cli).

## Slash commands

Installed as a Claude Code plugin, the skill adds three commands:

| Command | Purpose |
| --- | --- |
| `/handoff:view` | Open the live progress viewer in a separate terminal |
| `/handoff:status` | Turn on a live progress bar in the status line, and report progress |
| `/handoff:continue` | Audit the ledger and resume what is actually unfinished |

`/handoff:status` puts a live row at the bottom of Claude Code:

```
handoff █████████░ 17/18 tasks · 70/73 steps · Codex
```

It configures Claude Code's [status line](https://code.claude.com/docs/en/statusline)
to run `handoff-bar`, which prints one row and exits. With a refresh interval
set, the bar keeps updating while the session is idle, so progress moves as
other agents write the ledger. `/handoff:status off` removes it. The bar prints
nothing in a repository without a ledger, so it stays empty rather than erroring.

### Other agent harnesses

The bar is not Claude Code specific. `handoff-bar` reads the status-line payload
shapes all of these send, so the same script works unchanged:

| Harness | Live bar | Configure in |
| --- | --- | --- |
| Claude Code 2.1.260 | Yes | `~/.claude/settings.json` → `statusLine` |
| Grok CLI 1.0.13 | Yes | `~/.grok/config.toml` → `[ui.status_line]` |
| Kimi Code 0.41.0 | Yes | `~/.kimi-code/tui.toml` → `[status_line]` |
| Codex CLI 0.153.4 | Via tmux wrapper | `handoff-tui --codex` |
| Any agent CLI | Via tmux wrapper | `handoff-tui --with <agent>` |
| opencode 1.18.3 | Built-in segments only | — |
| Cursor agent | None found | — |

Claude Code, Grok, and Kimi rows were each confirmed in a live session. Grok
refreshes on session events, so its row appears once you interact rather than
on the first empty frame.

Harnesses without a status-line hook still get the full dashboard: run
`handoff-tui` in a second terminal, which needs nothing from the host. Exact
configuration and the measurements behind the design are in
[harness setup](skills/handoff/references/harness-setup.md).

On Windows the ledger helper and the snapshot and bar modes work, but the live
curses dashboard and the `handoff-bar` fast path do not; point the status line
at `python handoff_tui.py --bar`, or use WSL for the dashboard. CI runs the
suites on Ubuntu and Windows.

The command also reports the totals and per-owner table the bar has no room for.
Both show *recorded* progress; `/handoff:continue` is the one that runs the
progressive audit. For the full dashboard with drilldown, run `handoff-tui` in
your own terminal — Claude Code owns the one it is running in.

## Multi-agent safety

For normal sequential work—or separate Git worktrees—editing `HANDOFF.md` directly is fine.

When several agents share **one working tree**, use the bundled `apply` command. It performs a locked, compare-and-swap update so one agent cannot silently overwrite another agent's ledger change.

<details>
<summary>Safe concurrent update example</summary>

```bash
# Read a consistent snapshot and its version
python3 skills/handoff/scripts/handoff_guard.py read \
  --root /absolute/path/to/repo

# After auditing the returned text, write only if that version is still current
python3 skills/handoff/scripts/handoff_guard.py apply \
  --root /absolute/path/to/repo \
  --expect-version 98caeaf3ffbe \
  --entry new-entry.md
```

Exit code `3` means another writer changed the ledger first. Re-read, re-audit, and apply against the new version—do not retry stale content.

</details>

## Helper commands

```bash
# Diagnose ledger structure
python3 skills/handoff/scripts/handoff_guard.py doctor \
  --root /absolute/path/to/repo

# Validate structure, including machine-readable output
python3 skills/handoff/scripts/handoff_guard.py validate \
  --root /absolute/path/to/repo --json

# Name this session, to own its ledger entries under
python3 skills/handoff/scripts/handoff_guard.py name \
  --root /absolute/path/to/repo

# Generate a task-entry template
python3 skills/handoff/scripts/handoff_guard.py template \
  --title "Add search" \
  --owner "Amaterasu" \
  --step "Implement search filtering." \
  --step "Verify behavior and update the handoff."
```

Every session in a repository with Handoff installed claims a name as the
first thing it does, before it reads the ledger or reports anything, drawn from
a hundred mythological figures worldwide, so the ledger
and the dashboard read as named agents rather than a column of host session
ids. Names are handed out first come, first served, cycling initials A through
Z and wrapping to the next free A name after Z. A name is never one an owner
in that ledger already holds, and the same session asking twice gets the same
name. `$HANDOFF_SESSION` identifies a session whose host exposes no id of its
own, and `--seed` names one explicitly.

The helper validates ledger structure only. It cannot determine whether a feature is really implemented, whether ownership is active, or whether a requirement is obsolete—those are evidence-based decisions made by the agent.

## Updates

### Claude Code plugin

```bash
/plugin marketplace update divij-skills
/plugin update handoff@divij-skills
/reload-plugins
```

Third-party marketplaces have auto-updates disabled by default. Enable them from `/plugin` → **Marketplaces** → **divij-skills** → **Enable auto-update**.

### Skills CLI

```bash
# Project install
npx skills@latest update handoff -p

# Global install
npx skills@latest update handoff -g
```

## Manual installation

Clone this repository and copy the **entire** `skills/handoff` directory into your host's skills directory—for example:

```text
.claude/skills/handoff/
```

Do not copy only `SKILL.md`: the references and helper script are part of the skill.

## Development

```bash
python3 -m unittest discover -s skills/handoff/tests -v
python3 -m unittest discover -s tests -v
python3 scripts/package_skill.py
```

The packager creates release artifacts in `dist/`. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution and release guidance.

## Scope

Handoff is a coordination convention, not a permissions system or general-purpose lock manager. It never lets an agent take over another agent's work on its own initiative, commit unrelated changes, or publish changes. A takeover happens only when you direct it and name the prior owner; the agent must then find that owner stopped, preserve its uncommitted work, and record the transfer in the ledger where the prior owner will see it.

## License

[MIT](LICENSE)
