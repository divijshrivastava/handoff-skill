# Managed teams

Read this when `Coordination:` in the ledger selects `managed`, or when a
managed runner gives you a lead or worker turn. Direct mode is the default.
The commands below run from this skill's `scripts/` directory. Read the
ledger before each write and use the current version for `--expect-version`.
Each command writes through the guard's locked compare-and-swap.

## User setup

The user selects a lead CLI and review interval. Configuration creates a
dedicated lead identity and mandate before any process starts. The user then
enrolls workers and starts the team. Managed turns use the installed Codex or
Claude Code CLI, the user's account, and normal approval controls.

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" team-configure --root <repo> \
  --expect-version V --harness codex --interval 60
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" team-enroll --root <repo> \
  --expect-version V --harness codex
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" team-start --root <repo>
```

Create a lead objective with completion criteria by using
`handoff_orchestrate.py team-objective`. Use `team-status` to read the team,
runner state, and channel interactions. See `orchestration.md` for child
tasks, user messages, worker capacity, and recovery.

## Lead turn

The user setting supplies the coordination mandate. Read `leader.md` for
offers, acceptance, path reservations, dependencies, and leases.

1. Audit user objectives, worker tasks, reports, and blockers. A runner
   heartbeat proves only that the monitor ran. Check reported results.
2. Assign bounded work to recorded team workers through
   `handoff_lead.py assign`. Send status questions through the channel.
   Assignments are ledger writes, not messages.
3. Check completed work and required verification before closing the parent
   objective. Preserve user assignments and other agents' ownership.
4. Record a concise report for the user. State completed results, current
   work, blockers, and the next action.

Do not type into another terminal or take over a worker's files. The default
capacity policy asks the user for another worker. Only a user-selected
`auto` policy permits the lead to enroll one within its recorded limit.

## Worker turn

Keep the owner and session seed that the runner supplies. Audit your task
bucket before each turn. Accept an offer yourself with
`handoff_lead.py accept`. Finish current work before later assignments.
Update the ledger at checkpoints. Renew the task lease while working and
clear it before completion. A normal lead message does not assign work.

Each invocation is one bounded turn. Do not sleep or poll inside the model
turn. The runner checks again. End with a progress report or concrete blocker.

## Persistence and limits

`Coordination:` and `Managed-agent:` are ledger header records. They keep
settings, lead identity, and worker membership. Per-owner runtime state and
logs live in gitignored `.handoff/managed/`. One OS lock prevents two runners
for the same logical owner. Runners are independent of a viewer or terminal.

Codex uses `exec --sandbox workspace-write`. Claude uses print mode without
session persistence. Both reconstruct each turn from the ledger, channel,
and reports. Neither adapter bypasses approvals. An unavailable CLI, denied
operation, or nonzero exit is reported without continuous retry.

An interrupted turn is never replayed automatically. The old child process
or another writer can remain active. Preserve partial work and establish that
writers stopped before explicit recovery. See `orchestration.md`.

Managed execution supports Codex and Claude Code. A different active manual
leader mandate prevents the configuration save until the user resolves it.
