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

**Requirements:** Git, an agent with repository read/edit access, and Python 3.9+ for the optional helper. Handoff needs no API key, external service, Python package, or background process.

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
## 2026-09-07 — Add search (owner: agent-a)

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

## Slash commands

Installed as a Claude Code plugin, the skill adds two commands:

| Command | Purpose |
| --- | --- |
| `/handoff:status` | Print recorded progress overall and per owner, read-only |
| `/handoff:continue` | Audit the ledger and resume what is actually unfinished |

`/handoff:status` prints a snapshot rather than the live dashboard, because a
command session has no terminal to draw into. Run `handoff-tui` yourself in a
separate terminal for the refreshing view. It reports *recorded* progress;
`/handoff:continue` is the one that runs the progressive audit.

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

# Generate a task-entry template
python3 skills/handoff/scripts/handoff_guard.py template \
  --title "Add search" \
  --owner "agent-a" \
  --step "Implement search filtering." \
  --step "Verify behavior and update the handoff."
```

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

Handoff is a coordination convention, not a permissions system or general-purpose lock manager. It does not authorize an agent to take over another agent's work, commit unrelated changes, or publish changes.

## License

[MIT](LICENSE)
