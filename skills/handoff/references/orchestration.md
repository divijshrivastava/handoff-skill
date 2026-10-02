# Leader orchestration

Read this when a lead owns a user objective, the user requests status from the
lead, the lead needs more workers, or a managed turn stops unexpectedly.
The ledger remains the authority for task ownership. All writes in
`handoff_orchestrate.py` use the guard's locked compare-and-swap. Read the
ledger first and pass its version with `--expect-version`.

## Objectives

Create one objective with explicit completion criteria. This records an ordinary
lead-owned task with an immutable task ID and an `Objective:` JSON record.
The command prints its ID.

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" objective-create --root <repo> \
  --expect-version V --owner '<lead>' --title 'Ship search' \
  --criterion 'Search returns matching items' \
  --criterion 'Required tests pass'
```

If an older lead-owned task already records the user request, add criteria
to it with `objective-adopt --objective '<task ID>'` and one or more
`--criterion` arguments. This keeps the original request.

Assign child work with `handoff_lead.py assign`. That command writes the
assignment. Link each returned child task ID to the objective:

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" objective-link --root <repo> \
  --expect-version V --owner '<lead>' --objective '<objective ID>' \
  --child '<task ID>'
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" objective-status --root <repo> \
  --objective '<objective ID>'
```

The lead must review the work. Child checkboxes alone do not prove the result.
Close the objective only after all linked children are complete and the lead has
one evidence item for each criterion:

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" objective-close --root <repo> \
  --expect-version V --owner '<lead>' --objective '<objective ID>' \
  --evidence 'Manual search returned the expected item' \
  --evidence 'The required test suite passed'
```

An objective without children remains open. A missing or unfinished child
blocks closure. A user override of a child stays in the ledger; the lead must
review that change before it closes the objective.

## User messages

`message` records a user question or a lead report in the ledger as a
`Leader-event:` header record. `messages` reads the record. It also sends
a channel notification when the lead has a channel session. A running managed
lead gets a turn after a new channel message. `team-status` shows the
channel copy. The ledger record remains if channel delivery fails.

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" message --root <repo> \
  --expect-version V --kind message --from user --to '<lead>' \
  --body 'What remains?'
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" message --root <repo> \
  --expect-version V --kind report --from '<lead>' --to user \
  --body 'The code is complete. Review and release remain.'
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" messages --root <repo>
```

The lead reads new messages during each review turn. In managed mode, an
unfinished objective causes periodic review turns. A user can also resume an
idle direct-mode lead through the existing viewer session link.

## Worker capacity

The default policy is `request`. The lead's `worker-request` records a
request for the user. It starts no process. Only a user-selected `auto` policy
allows the lead to enroll and start a managed worker. Set a worker limit before
using that policy. A new worker receives no task until the lead assigns one.

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" capacity-set --root <repo> \
  --expect-version V --mode auto --max-workers 3
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" worker-request --root <repo> \
  --expect-version V --owner '<lead>' --harness codex \
  --reason 'An independent test can run in a separate file.'
```

Return to `--mode request` to stop new automatic worker creation. This does
not stop existing workers or change their tasks. The command refuses a full
team. A successful enrollment is a ledger fact. If process start fails, the
command reports the error and leaves the member recorded for recovery.

## Recovery

`recovery` reads the ledger, managed runner records, and working-tree status.
It changes nothing. A running or interrupted record means the previous turn
is uncertain. It does not prove that the child process is live or stopped.

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" recovery --root <repo>
```

Before a restart, check for writers, preserve partial work in a recovery copy,
and audit the ledger and source. Then use `resume-interrupted` with the
version from that audit and an existing recovery-copy path:

```sh
python3 "$SKILL_DIR/scripts/handoff_orchestrate.py" resume-interrupted \
  --root <repo> --expect-version V --owner '<agent>' \
  --preservation /path/to/recovery-copy --confirm-stopped
```

This explicit command resets an interrupted runner and starts its next turn.
It is not an automatic replay after a crash. Do not use it while another
writer can still change the same work. A cleanly exited failed turn follows
the existing managed-team retry path.
