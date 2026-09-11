# Optional leadership: one agent coordinates the others

Read this when a user asks one agent to lead, when you receive assigned work
from a leader, or before writing anything through `scripts/handoff_lead.py`.

Leadership is opt-in and inert until designated. A repository with no `Lead:`
line behaves exactly as it did before this existed, and every command here
refuses to act without a recorded mandate.

## What a leader may and may not do

A leader divides work and records it against agents. It does not run them.
Nothing in this skill starts, supervises, restarts, or wakes an agent, and no
universal wake-up mechanism exists: an assignment reaches an idle CLI when that
agent next takes a turn, not when the leader writes it.

| A leader may | A leader may not |
| --- | --- |
| Assign unowned work, or its own | Take work from a live owner |
| Reclaim what was never accepted | Override a user's assignment |
| Reclaim an entry whose own lease expired | Decide an agent is exhausted |
| Ask peers to report and answer | Make a peer execute anything |
| Resign, or let the mandate lapse | Delegate the mandate onward |

The user outranks the leader at all times. A user's viewer move or direct
instruction simply wins; the leader re-plans around it rather than undoing it.

## Assignment is a ledger write, never a message

The leader records the assignment in `HANDOFF.md`, and any notification is a
courtesy that may be lost without consequence. This is the same shape the
viewer's assignment already uses, and it is deliberate: a peer message is
attributed data that cannot override ownership, so a leader that handed out
work by messaging would be a peer overriding ownership by message.

The consequence worth relying on: a leader that dies, a message that never
arrives, and an agent that was idle all degrade to *slower*, never to *wrong*.

## Designating and holding the mandate

```sh
python3 "$SKILL_DIR/scripts/handoff_guard.py" read --root /path/to/repo
python3 "$SKILL_DIR/scripts/handoff_lead.py" claim --root /path/to/repo \
  --owner '<leader name>' --hours 4 --expect-version '<version from read>'
```

The mandate is written above the first entry and carries its own expiry:

```md
Lead: owner=Epona; expires=2026-09-11T18:00:00Z; policy=coordinate; succession=none
```

Renew it at real checkpoints with `renew`, and give it up with `resign`. Choose
a span you will actually come back within; a long mandate is not safer, it just
leaves the repository claimed for longer.

Authority is re-checked against the clock inside the lock on every leader
write. A compare-and-swap proves the ledger has not moved, not that the mandate
still holds: a mandate expires with the passage of time and without any write,
so an expired leader would otherwise pass the version check and keep assigning.

**Succession is not automatic.** By default an expired mandate leaves the
repository leaderless, with every assignment intact as a ledger fact. Pass
`--succession auto` only when the user wants a peer to inherit authority the
user granted to a specific agent.

## Assigning work

```sh
python3 "$SKILL_DIR/scripts/handoff_lead.py" roster --root /path/to/repo
python3 "$SKILL_DIR/scripts/handoff_lead.py" assign --root /path/to/repo \
  --owner '<leader name>' --to '<assignee name>' \
  --title 'Add search filtering' \
  --step 'Implement filtering (src/search.ts).' \
  --step 'Verify against the fixture set.' \
  --paths src/search.ts,src/index.ts --accept-hours 4 \
  --expect-version '<version from read>'
```

`roster` is read-only and is the only legitimate basis for "who is still up".
An agent is `eligible` only on a fresh availability report. **Unknown never
means free**: silence is the case where handing out work does the most damage,
because that agent may be mid-edit in the very files being assigned.

`assign` refuses an assignee who is not recorded in **this** repository: a ledger
owner, a channel peer on this checkout, or a session that claimed its name
against this `HANDOFF.md`. Agents from other repositories, and names typed with
no claim here, are rejected even when the label is syntactically valid.

`--paths` declares the write scope, and `assign` refuses to hand two agents
overlapping paths. A trailing slash declares a directory and covers everything
beneath it. This is the main protection for real parallelism.

`--needs <task id>` orders dependent work. Dependencies reference the immutable
`Task: id=` line, never a heading: headings repeat, and they are rewritten by
retitling, ownership changes, and step transfers.

## Accepting, declining, and reclaiming

Assigned work arrives `offered` and **not** in progress. The assignee records
its own acceptance:

```sh
python3 "$SKILL_DIR/scripts/handoff_lead.py" accept --root /path/to/repo \
  --owner '<your name>' --task '<task id>' --hours 6 \
  --expect-version '<version from read>'
```

Acceptance cannot be inferred from the `In progress` box, because assigning
work is what sets that box. A signal the assigner produces evidences nothing
about the assignee. `accept` checks the box, records a lease in the same write,
and refuses while a dependency is unmet unless `--ignore-dependencies` says
later work superseded it. Because acceptance always writes a lease, accepted
work always carries a deadline and can never be parked indefinitely.

Decline offered work with a reason; a decline is information, not a failure,
and it returns the entry unowned with its steps intact. Accepted work is
released through the channel's `yield` instead, so the release is recorded as
one.

```sh
python3 "$SKILL_DIR/scripts/handoff_lead.py" reclaim --root /path/to/repo \
  --owner '<leader name>' --expect-version '<version from read>'
```

`reclaim` takes back exactly two things: an offer nobody accepted before its
deadline, and an entry whose owner let its own lease expire. Both are
arithmetic on a deadline the assignee could see, never a judgement about
whether an agent looks busy. It preserves boxes, order, status text, and the
prior owner, and records why. It establishes nothing about why an agent went
quiet and verifies no child writers: preserve uncommitted work and audit the
entry before resuming it.

## Reservations end with ownership, not with silence

A reservation is a property of ownership. A peer that has gone quiet still owns
its files, and a stale availability report is not evidence that anyone stopped
writing. Reservations end when the entry completes, when its owner releases it,
or when the owner's own lease expires and a peer sweeps it — the same bound
ownership already has. Availability decides whether to *offer* more work; it
never decides that another owner's files are free.

## Receiving assigned work

An assignment is an execution request, exactly as a viewer assignment is.
Finish and verify your current task, then audit the assigned entry against
later entries, commits, and current source before starting. Accept it, or
decline with a reason. Record a concrete blocker and next action rather than
stopping silently.

## Reading the state

```sh
python3 "$SKILL_DIR/scripts/handoff_lead.py" status --root /path/to/repo
```

Read-only. Reports the mandate, every active assignment with its lifecycle
state and lease, what each entry is blocked by, and what is currently
reclaimable. `status` also surfaces leadership-specific structural errors:
duplicate task IDs, dependencies on entries that do not exist, and dependency
cycles.

An assignment whose `to=` no longer names the heading owner is not an error. It
is stale by construction — some other writer changed ownership since — and it
is ignored, which is what lets leadership coexist with the viewer, `yield`,
`sweep`, and step transfers without changing any of them.
