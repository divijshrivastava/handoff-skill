---
name: handoff-continue
description: Audit HANDOFF.md and resume the work that is actually unfinished
argument-hint: [task name or hint]
---

Use the handoff skill to resume work already recorded in this repository's ledger.

Requested focus (may be empty): $ARGUMENTS

Scope: this command resumes existing work. Do not invent new scope. Do not create
a ledger if none exists. If `HANDOFF.md` is absent, or the audit finds nothing
effectively unfinished, say so and stop rather than manufacturing a task.

Run the skill's preflight and progressive audit before changing anything. Report
each apparently unfinished entry's effective status rather than trusting its
checkboxes: later entries, commits, and current source may already have
completed, narrowed, or superseded it.

Then choose what to resume:

- With a focus above, resume the entry it names. Without one, finish your current
  task, then complete your viewer-assigned queue oldest first before considering
  other effectively unfinished work, unless the user gave another ordering.
  A viewer assignment is an execution request; it needs no further pickup
  choice or user prompt. If idle, audit and start it now.
- Resume only the remainder. Never redo a step that later evidence already
  completed.

Ownership: decide from evidence, not from the `In progress` label or an open CLI
process. Read references/agent-channel.md when a peer is involved. Check the
channel's capability reports and inbox; a failure hook can report that a model
cannot respond even while its process remains resident. Silence alone establishes
neither exhaustion nor permission to take over. Take the task
over when it is unassigned, explicitly handed off, or its owner is not observably
active and no unrecognized working-tree changes touch its files; preserve the
prior owner's attribution in the status line. If there is evidence of a live
owner or of conflicting uncommitted work, stop and report the conflict instead of
editing their task. Explicitly released tasks are unassigned: preserve any
uncommitted work, audit it, and claim through guard read/apply before editing.
An entry whose owner let its own declared lease expire is released the same way,
by guard sweep; the expiry is that owner's prior authorization, not evidence
about its model.
For an authorized takeover of an exhausted owner, use the skill's stopped-writer
checks; do not demand that an unavailable CLI exit merely to prove inactivity.

Finish as the skill requires: check boxes only against real outcomes, run
verification proportionate to the change, record the evidence and the next
action, and validate the ledger. If verification fails, leave the task open with
the failure evidence and the next action.

After each completion and before stopping, re-read and audit your assigned
bucket. Continue until every eligible assignment is verified complete or the
remainder has concrete blockers; a missing second prompt is not a blocker.
