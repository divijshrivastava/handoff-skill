# Ownership: assignments, unavailable agents, and takeover

Read this before acting on a viewer assignment, when a peer has gone quiet or
reported failure, and before any takeover the user directs. `SKILL.md` Step 3
keeps the pickup choice and the rules that bind every session; this file holds
the procedure behind them.

## Viewer assignments are execution requests

A user assigning a task to you through `handoff-tui` (`x`/`p` or `P`) is an
explicit instruction to finish it after your current task. It supplies both
authorization and ordering; do not ask the Step 3 pickup question, wait for
another prompt, or merely report the assignment as pending and stop. This
obligation applies to every receiving agent, including the current session.

Check your assigned bucket during preflight, at real work checkpoints, after
finishing each task, and before stopping or reporting yourself waiting. Finish
and verify your current task first; keep assignments queued while doing so.
If idle, begin the assigned work immediately after its progressive audit.
Unless the user gives another order, process your eligible assignments oldest
first, ahead of optional or unassigned work.

For each assignment, audit later entries, code, prior work, and active writers.
The current heading and dated user reassignment override older "unclaimed" or
"waiting for pickup" prose. Preserve attribution and uncommitted work, record
your harness and takeover in the existing entry through `read`/`apply`, then
implement the effective remainder through verification and the required
handoff/commit. Do not duplicate entries, redo completed or superseded work,
or reclaim tasks assigned away from you. User assignment authorizes ownership;
it does not authorize overwriting a peer who is still writing the same files.

If a concrete blocker prevents completion, record its evidence, next action,
and required input or external change; continue other eligible assignments.
Missing a second user prompt is never a blocker. Re-read and audit the queue
after each completion until it is empty or every remainder is concretely
blocked. A later user stop, cancellation, or explicit ordering takes precedence.
The viewer persists the request; it cannot wake a stopped model. An agent that
resumes must discover and act on its assignments at its next preflight.

## Communication and unavailable agents

When coordinating with a peer or investigating a stalled owner, read
`agent-channel.md`. It documents the local inbox, reported capability,
and failure hooks in `scripts/handoff_channel.py`. Register your claimed name
once unless a hook already supplied a channel session ID; check messages before
shared edits and at task boundaries. The Claude plugin reports host failures
without needing another model turn. Other harnesses use the CLI unless an adapter
has actually been configured.

A process can remain open after token exhaustion. An explicit host error or user
report of exhaustion is evidence of unavailable capability; an open PID is not
contrary evidence. An unanswered ping or expired working report means unknown,
not permission to take over. A failure hook does not prove child writers stopped.
Preserve work and follow existing ownership authority before adopting it.

An agent that can still act may save its state, stop its writers, and use channel
`yield` to release its whole unfinished bucket through `swap_ledger`. Those
entries become unassigned with dated attribution, so another agent may audit and
claim them through guard `read`/`apply`. Check ownership again on returning;
released work must not be silently reclaimed. Messages and acknowledgements do
not establish task completion.

No signal for an exhausted model exists on every harness, so nothing here is
decided by detection. Declare your own contingent release instead: guard `lease`
records a renewal deadline on your unfinished bucket, and any peer can `sweep`
what expired, because expiry is arithmetic every harness computes alike. Renew
it at real checkpoints and clear it when you finish. Channel `nudge` asks a
silent peer to answer and is only a message: it decides nothing, changes no
state, and cannot be broadcast or repeated inside its interval. Channel
`challenge` and `attest` bind a proof of capability to a fresh nonce; read that
proof in one direction only, as reason not to take a peer's work. Silence
remains unknown.

## Authorized takeover of another agent's bucket

A takeover begins only when the user explicitly directs it and names the prior
owner ("take over Codex's tasks"). That direction supplies the authority the
ownership rules otherwise withhold; without it, this protocol does not apply.

Taking over:

1. Confirm the prior owner has stopped writing: either its process has exited,
   or an explicit host/user report establishes it cannot continue and its child
   writers have stopped. Watch its files and the ledger for concurrent changes.
   A resident CLI alone does not veto a takeover of an exhausted agent. If it is
   still writing, or the evidence is only silence, report that conflict.
2. Preserve its uncommitted work before any edit: copy the changed and
   untracked files to a recovery point outside the tree, so nothing it did can
   be lost by your edits or its own return.
3. Move the whole bucket, not a cherry-picked task: transfer every entry the
   prior owner still owns that is not recorded complete. For each, rewrite the
   `(owner: ...)` label to your name and append a dated status sentence naming
   the prior owner, the user's direction, and the recovery point. Move the
   bucket in one locked `apply --content` write so no reader ever sees it
   half-moved; the viewer's `x`/`p` move and the helper's `reassign_task`
   cover the single-task case.
4. Audit each adopted entry under Step 2 before resuming it: a transferred
   entry arrives assigned, not explained. The prior owner's preserved work is
   now yours to review and build on, never to silently discard.

Coming back: when your preflight or audit finds entries you owned now carrying
another owner and a transfer note naming your session, the bucket has moved.
Do not resume, re-edit, or take those entries back. Report the move and start
only genuinely new work as a new task; if the transfer looks wrong, say so and
let the user decide.
