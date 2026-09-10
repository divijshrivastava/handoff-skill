# Ledger contract

Read this reference before creating or editing a handoff ledger.

Every name, path, date, and commit id below is a placeholder illustrating
shape. Copy the structure; never copy the literal values. Use the ledger's own
task names, the real owner, and real identifiers. If a value is unknown, write
what the ledger actually says or record it as unknown - do not fill the gap
with an example value.

Preserve existing titles and steps. For a new request, write a concise title
and proposed outcomes based on the request; leave repository-specific details
unknown until inspected. Show only the ledger content needed for the decision
or transition being explained.

## Canonical task entry

Place newest entries at the top of the task list unless repository instructions
specify another order.

```md
## YYYY-MM-DD - Task name (owner: agent name)

State:

- [ ] In progress
- [ ] Completed

Steps:

- [ ] First concrete outcome (`expected/file.ts`).
- [ ] Second concrete outcome.
- [ ] Verification and handoff update.

Status: Pending. No work has started.
```

Use the repository's existing punctuation and date style when it already has a
canonical template.

## State examples

Pending:

```md
State:

- [ ] In progress
- [ ] Completed

Status: Pending. Queued behind task X at the user's direction.
```

Active:

```md
State:

- [x] In progress
- [ ] Completed

Status: In progress. Parsing is complete; next action is to implement the
validated schema in `src/schema.ts`.
```

Paused or blocked:

```md
State:

- [x] In progress
- [ ] Completed

Status: Blocked. The public deployment requires approval because the resolved
access policy is shared. The version is saved but no deployment was started;
next action is to obtain explicit approval for the existing shared access.
```

Completed:

```md
State:

- [x] In progress
- [x] Completed

Status: Complete. Tests and production build pass; committed in `abc1234`.
```

## Progressive resolution examples

Later work completed an old unchecked step:

```md
- [x] Add the route. Resolved by the later workspace task in `abc1234`.

Status: Complete. This entry was stale; the later workspace task retained and
verified the route.
```

Later work changed the scope:

```md
- [x] Preserve the original experimental assets.
- [x] Mark the active rendering approach superseded by the later readable-piece
      task in `def5678`.

Status: Superseded. Assets remain for attribution and rollback, while the later
task owns the current rendering requirement.
```

Only part of an old task remains:

```md
Status: Partially complete. The route and tests landed in `abc1234`; the visible
navigation entry is still absent and is tracked as a separate unassigned task
above.
```

## Ownership notes

An owner label names one session. Claim yours once, from the helper, as the
first step of preflight rather than at the first write:

```bash
python3 "$SKILL_DIR/scripts/handoff_guard.py" name --root /absolute/repo/path
```

It answers with one of a hundred mythological names, skipping every name an
owner in this ledger already holds - completed entries included, because
reusing a retired owner's name makes the ledger's own history ambiguous about
who did which work. Names are handed out first come, first served, cycling
initials A through Z and wrapping to the next free A name after Z. The same
session is given the same name each time it asks,
so an agent that re-runs preflight after recording an entry keeps owning it.
Write the name exactly as printed; a label the helper did not issue, or a
second name adopted mid-task, breaks the one thing attribution rests on.

A heading may also carry the tool that session ran in, as a separate field
after the owner label:

```md
## YYYY-MM-DD - Task name (owner: agent name) (harness: Claude Code)
```

The field is optional and additive: entries without one stay valid, and the
name must keep its own parentheses-free label, which is why the harness is not
folded into it. `template --harness auto` records what the helper detects, and
`HANDOFF_HARNESS` names a tool it cannot. Because the field describes the
session that held the task, reassigning an entry removes it: the new owner's
tool is unknown until that agent records its own.

A name identifies a session, not a person or a model, and it proves nothing
about who performed a step: it is how a later agent tells your entries from a
peer's, and how the viewer groups them.

When taking over eligible work, preserve prior attribution:

```md
Status: In progress. Originally owned by <prior owner>; <your agent name>
picked up the remaining verification step after the user requested
finish-first and <prior owner> was no longer active.
```

When the user directs a takeover of another agent's bucket, move every entry
that owner still owns, rewrite each heading's owner label, and record the
transfer where the returning owner will see it:

```md
## YYYY-MM-DD - Task name (owner: <your agent name>)

Status: In progress. Taken over by <your agent name> from <prior owner> on
YYYY-MM-DD at the user's direction; <prior owner>'s uncommitted work is
preserved at <recovery point>. Originally owned by <prior owner>.
```

A returning agent that finds its own name in the transfer note treats the task
as moved: it reports the transfer instead of resuming the entry.

A user moving one task in the live viewer writes the same record mechanically:
the heading's owner label is rewritten and a dated line naming the previous
owner is appended to that task's status. For unfinished work assigned to an
agent, the note also records a user execution request: finish the current task,
then audit and complete the assignment through verification without another
prompt. The receiving agent records its own takeover and harness in the
existing entry. Older "unclaimed" prose does not override the current owner
and user transfer. Agents check their bucket before stopping and continue
eligible assignments; concrete blockers must include evidence and a next action.
The note itself never proves work or verification, and completed tasks remain
complete. Removing the owner releases work instead of assigning execution.

When another owner remains active:

```md
Status: In progress with <active owner>. <your agent name> is not adopting or
editing this task; the user's new request is tracked separately.
```

## Formatting invariants

- Keep `In progress` and `Completed` as separate task-level boxes.
- Put step boxes under `Steps:` and make each one independently verifiable.
- Include a status line for every modern task entry.
- A completed task keeps `In progress` checked.
- A completed task has no unchecked required steps.
- A pending task has no checked implementation steps.
- Never use a checked box to mean attempted, reviewed, or no longer desired.
  Use `Superseded`, `Obsolete`, or a factual status annotation instead.

## Empty ledger

A ledger with no tasks is valid and is exactly:

```md
# Handoff
```

That is what `/handoff:purge` leaves behind. Keep the file: deleting it would
stop the repository being one that tracks work this way. Do not treat a
`HANDOFF.md.*.bak` sidecar as a ledger.
