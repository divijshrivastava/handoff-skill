---
name: handoff
description: "Coordinate progressive repository work across agents with a shared HANDOFF.md ledger. Use in repositories with a ledger, or on explicit handoff requests: /handoff:init, 'initialise the handoff', /handoff:continue, /handoff:status, /handoff:view, /handoff:purge, or 'use handoff'. After activation: handoff_guard.py name --root <repo> claims the session name; handoff_guard.py read --root <repo> returns ledger text and version in one snapshot. Audit later entries and code before treating unchecked boxes as unfinished. For ledger writes: handoff_guard.py apply --root <repo> --expect-version V with --entry FILE or --content FILE. On exit 3, re-read and re-audit; never retry the stale write. A user viewer assignment is required queued work: finish your current task, then audit and complete it without another prompt. Track investigations before research, even without code edits; a name claim is not a task."
license: MIT
metadata:
  version: "1.25.0"
allowed-tools: Bash, Read, Write, Edit, AskUserQuestion
---

# Handoff contract

Treat the ledger as progressive history, not a flat todo list. An old unchecked
box is an investigation cue. It is not proof that work remains: a later task,
commit, or source change may have completed, absorbed, narrowed, replaced, or
superseded it.

The repository's own instructions remain authoritative. This skill supplies a
reusable workflow; it never weakens `AGENTS.md`, `CLAUDE.md`, contribution
rules, ownership boundaries, verification requirements, or safety policy.

## Activation

Handoff work starts in a repository that already keeps a ledger, and elsewhere
only when the user asks for it. The triggers are:

- an existing `HANDOFF.md` in the repository. Someone put it there to track
  work this way, and a ledger nobody reads is worse than none: entries go
  stale, and the next agent trusts checkboxes no one has audited;
- the `/handoff:init` command, or the phrase "initialise the handoff" in a
  host without slash commands (Codex's default prompt supplies it);
- another explicit handoff request: `/handoff:continue`, `/handoff:status`,
  `/handoff:view`, `/handoff:purge`, or a direct instruction such as "use
  handoff", "record this in the ledger", "purge the handoff", or "take over
  <owner>'s tasks".

In a repository with no ledger and no such request, do none of this skill's
work: no session name, no preflight, no ledger creation, no task entry.
Multiple agents sharing the tree, or work that merely looks unfinished, do not
by themselves make a repository one that tracks work this way. Answer the
user's request under the repository's own instructions instead.

Activation is a lazy load, not a per-request ritual. Once any trigger
arrives, the whole contract below governs every repository task for the rest
of the session — preflight, intake, audit, ownership, safe writes, commit
discipline — with no further handoff mention needed. `/handoff:init` (or
"initialise the handoff") is how a repository without a ledger becomes one:
run the preflight, create `HANDOFF.md` from `references/ledger-contract.md`
when the repository prescribes no ledger and mutation is authorized, report
the recorded state, and start no task. Where a ledger already exists, it has
done that job already and init only reports the recorded state. A later
session activates the same way.

## Output discipline

Ground every statement in repository state, and say only what the decision
requires.

- Preserve existing task names, steps, and identifiers. Create concise titles
  and outcome-oriented steps for new requests from the user's instructions;
  proposed work is a plan, not evidence that it already exists.
- Ground owners, dates, paths, commits, and claims about existing behavior in
  the session or repository. Mark unknown details as unknown. Do not assume
  a UI structure, framework, or file layout from a feature name. Examples in
  `references/ledger-contract.md` illustrate shape, not repository facts.
- State the effective status, supporting evidence, and next action once.
  Explain intake when requested, without repeating the shared procedure for
  each scenario. Routine tool narration does not help the user decide.
- Show only necessary ledger snippets as Markdown. Avoid reproducing a whole
  entry for a single state transition or repeating a snippet in prose.

## Ledger before task work

In a repository that already keeps `HANDOFF.md`, every agent session follows
the same order whether it was opened from the viewer with **N**, wrapped with
`--with`, or started in a plain terminal: **record the task in the ledger
before substantive investigation or implementation**. A name claim or a recent
label in the viewer is not a task entry. Run preflight, write or update your
entry with `In progress` checked when you begin, and only then investigate or
implement. The viewer's WIP column reads only from those ledger entries.

A request to investigate, diagnose, audit, or review is tracked work even when
its deliverable is an answer and no source file changes. After the preflight
and ownership audit, record its scope and verification before task-specific
research; check steps as evidence is gathered, and record completion before
the final answer. An explicit instruction to make no writes takes precedence.
Simply displaying existing status (`/handoff:status` or `/handoff:view`) and
answering a follow-up from evidence already gathered do not create another
task. If that follow-up requires new investigation, record the new scope.

## Step 0: Preflight before task work

1. Run the bundled preflight, using the directory that contains this `SKILL.md`
   as `SKILL_DIR`. It claims this session's name, reads the ledger, checks its
   structure, and reports Git state from one snapshot:

   ```bash
   python3 "$SKILL_DIR/scripts/handoff_guard.py" preflight --root /absolute/repo/path
   ```

   `--root` accepts any path inside the repository; it resolves the repository
   root for you, so this does not wait on resolving it yourself.

   It returns:

   - `session.name`: the name you own every entry you write under. It is one of
     a hundred mythological figures, never a name an owner in this ledger
     already holds, and the same name every time this session asks. Use it
     verbatim; do not invent a name, reuse another session's, or rename yourself
     mid-task, because the label is how a later agent tells your work from a
     peer's. Record the tool you run in alongside it, with `template
     --harness auto` or a `(harness: ...)` field, so a reader can tell a Codex
     session from a Claude Code one; `HANDOFF_HARNESS` names a tool the helper
     cannot detect. If the Handoff SessionStart hook already supplied your
     claimed name and channel session ID, keep those: the hook performed this
     claim for you.
   - `version`: the ledger revision this snapshot describes. Pass it to `apply`.
   - `digest.open_tasks`: every unfinished or malformed entry, with its steps.
     This is the work; audit all of it.
   - `digest.recent_completed`: the newest finished entries, each as its heading
     and its own status line, with `completed_omitted` counting the rest.
   - `assigned_unstarted`: entries recorded to your name that nobody has started.
   - `errors`, `git_status`, `git_log`, and `instructions`.

2. Read every applicable repository instruction file before mutating anything.
3. Audit the digest's open entries newest to oldest. Do not stop at the first
   unchecked box. Finished history is summarized, not omitted: when an audit
   needs an older entry's steps or the exact ledger bytes, read them then.

   ```bash
   python3 "$SKILL_DIR/scripts/handoff_guard.py" read --root /absolute/repo/path
   ```

   Use `read` before any `--content` rewrite, and audit the text it returns
   against the version it returns. Auditing one snapshot and writing from
   another binds an audit of old text to a newer version, and the write deletes
   the peer entry that landed in between. `preflight --completed -1` keeps every
   finished entry when a review genuinely needs them all.
4. Inspect relevant recent history beyond the returned commits, and, if
   collaboration or agent-status tools exist, check which owners are actually
   active.
5. Before the first ledger edit, read `references/ledger-contract.md`.

The preflight reports structural state only. Never present its raw pending or
in-progress result as the effective status until the progressive audit below is
complete. `doctor` remains available for a structure-only check of an existing
ledger, and `name` for the name alone; preflight covers both.

If the repository has no ledger, follow its local instructions; when none are
prescribed and mutation is authorized, create `HANDOFF.md` from
`references/ledger-contract.md`. Never create a parallel ledger under another
name.

## Step 1: Turn every request into steps

Give each user request one dated task entry with:

- a concise task name and owner;
- separate `In progress` and `Completed` checkboxes;
- concrete, outcome-oriented steps, including expected files when known;
- verification and handoff/commit as explicit steps; and
- a factual status line.

Use the bundled template command to avoid format drift:

```bash
python3 "$SKILL_DIR/scripts/handoff_guard.py" template \
  --title "Task name" \
  --owner "$(python3 "$SKILL_DIR/scripts/handoff_guard.py" name --root /absolute/repo/path)" \
  --step "Implement the bounded change (path/to/file)." \
  --step "Verify behavior and update the handoff."
```

It prints Markdown and never writes the repository; apply the snippet with the
repository's normal editing tool.

Use task states literally:

| State | In progress | Completed |
| --- | --- | --- |
| Pending or queued | `[ ]` | `[ ]` |
| Actively being worked | `[x]` | `[ ]` |
| Finished and verified | `[x]` | `[x]` |

Record every new task in the ledger at intake—before task-specific research
or implementation—so the viewer shows who holds what and under which state.
If local instructions require a user choice before mutation, propose the entry
and write it only after that choice. Otherwise apply a pending entry while the
task waits behind other work, or check `In progress` in that same write when
this session begins the work now. A viewer assignment to an unfinished task
checks `In progress` in the ledger at once so the hand-off appears under WIP.

Check a step only after its outcome exists. Check `Completed` only after every
required step and proportionate verification finish. Leave `In progress` checked
on a completed task to preserve the transition history.

## Step 2: Perform the progressive-work audit

Audit each apparently unfinished entry against evidence in this order:

1. Later ledger entries, read from newest to oldest.
2. Commits named by those entries and relevant subsequent commits.
3. Current source, tests, generated output only when authoritative, and deployed
   state when deployment is part of the scope.
4. Live agent ownership and current working-tree changes.
5. The old entry's unchecked boxes and status text.

Prefer the latest specific evidence. A later verified implementation outweighs
an older unchecked plan. Current source outweighs stale prose. An active owner's
uncommitted work remains theirs even when another agent could finish it.

For every old entry, classify the effective scope as one of:

- **Complete:** evidence proves all required outcomes exist.
- **Partially complete:** preserve finished steps and name only what remains.
- **Superseded:** later work intentionally replaced the original approach or
  narrowed the requirement.
- **Unfinished:** a required outcome is genuinely absent.
- **Unknown:** evidence is insufficient; investigate or report uncertainty
  rather than guessing.

Preserve history: annotate the old entry with the resolving task or commit
rather than deleting it, rewriting it as though later work happened earlier, or
reopening obsolete scope. When scope changed, track the remaining outcome in a
new entry and mark the old form superseded.

## Step 3: Resolve ownership before implementation

If effective unfinished work exists when a new request arrives, report each
task's ledger name, its owner and whether that owner appears active, the
concrete remaining outcome, and any file overlap with the new request.

Only in that case, unless the user already chose, ask whether to:

1. finish eligible unfinished work first, or
2. leave it with its current owner and start the new task.

Do not implement either branch before the choice. Read-only investigation may
continue when it helps make the choice accurate. An explicit user ordering such
as "finish X first, then Y" is already the choice; do not ask again.

If the audit finds no effective unfinished work, proceed with the authorized
new task after the usual ownership and file checks; no pickup choice is needed.

When the user chooses **finish first**:

1. Keep the new request queued as pending.
2. Resume only the effective remainder of each agreed task, and do not redo a
   step later evidence already completed.
3. Take ownership only when it is unassigned, inactive, explicitly handed off,
   or the user authorizes the takeover.
4. Finish, verify, and record the older task before checking the queued task's
   `In progress` box and beginning it.

When the user chooses **start new work** while another owner remains active:

- leave that task and its checkboxes alone;
- record only the new task as yours;
- avoid the owner's files and uncommitted changes; and
- stop with a precise conflict report if safe separation is impossible.

An in-progress label is not proof that an owner is live. Check agent status
when possible, and treat unrecognized uncommitted changes as someone else's
regardless. The existence of unfinished work is never authority to adopt an
active owner's task.

### Viewer assignments are execution requests

A user assigning a task to you through `handoff-tui` (`x`/`p` or `P`) is an
explicit instruction to finish it after your current task. It supplies both
authorization and ordering; do not ask the pickup question above, wait for
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

### Optional leadership

A user may designate one agent to divide work and assign it to the others. This
is off unless a `Lead:` line exists, and a repository without one behaves
exactly as it always has. When leadership is in play, read
`references/leader.md` before writing anything through
`scripts/handoff_lead.py`.

A leader assigns by writing the ledger, never by sending a message: a peer
message cannot override ownership, so an assignment carried by one would be a
peer doing exactly that. Losing a notification therefore costs latency, not
correctness. A leader may assign unowned or its own work, and may reclaim only
an offer nobody accepted before its deadline or an entry whose owner let its
own lease expire. It may never take a live owner's work, override a user's
assignment, decide that an agent is exhausted, or delegate the mandate onward.
The user outranks the leader at all times.

Assigned work arrives `offered` and not in progress; the assignee records its
own acceptance, which also records a lease. Treat an assignment as an execution
request, exactly as a viewer assignment: finish and verify your current task,
audit the assigned entry, then accept it or decline with a reason.

### Communication and unavailable agents

When coordinating with a peer or investigating a stalled owner, read
`references/agent-channel.md`. It documents the local inbox, reported capability,
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

### Authorized takeover of another agent's bucket

A takeover begins only when the user explicitly directs it and names the prior
owner ("take over Codex's tasks"). That direction supplies the authority the
rules above otherwise withhold; without it, this protocol does not apply.

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

## Step 4: Keep state recoverable while working

Update the ledger at real transitions, not after reconstructing them from
memory:

- **Started:** check `In progress`; name the current step.
- **Step finished:** check only that step.
- **Paused:** leave `Completed` unchecked; record exact state and next action.
- **Blocked:** record the concrete blocker, evidence gathered, and required
  authority or external change.
- **Scope changed:** preserve the original entry, explain the change, and add or
  update the latest effective task.
- **Finished:** check every required step and both state boxes; record
  verification and commit/deployment identifiers when relevant.

At natural checkpoints, run:

```bash
python3 "$SKILL_DIR/scripts/handoff_guard.py" validate --root /absolute/repo/path
```

Fix structural errors without falsifying task state. The validator deliberately
does not decide whether source code proves completion; that judgment belongs to
the progressive audit.

When verification fails, the task stays `[x] In progress` and `[ ] Completed`.
Record the failure evidence, remaining work or blocker, and next action; queued
work stays pending.

### Writing when another agent may write too

Editing the ledger directly is correct for sequential handoffs and for separate
worktrees, where git surfaces any collision. When another agent may write the
same working tree during this session, route ledger writes through the guard so
a concurrent write cannot silently drop an entry:

```bash
python3 "$SKILL_DIR/scripts/handoff_guard.py" apply --root /absolute/repo/path \
  --expect-version <version from the read> \
  --entry /path/to/new-entry.md
```

Use `--entry` to insert one new task entry at the newest position, or
`--content` to replace the whole ledger after editing existing entries; either
accepts `-` for stdin. `apply` holds an exclusive lock across the re-read,
version check, and replacement, so two writers cannot both pass the check
against the same revision; the payload is read before the lock is taken, so
blocking input cannot stall peers. The replacement is atomic and preserves the
ledger's file mode, so no reader observes a partial ledger and collaborator
access is not revoked.

Editing `HANDOFF.md` directly is still a plain read-modify-write with no such
protection. Under concurrency, route every write through `apply`; the guarantee
belongs to the command, not to the file.

`purge` is the other writing subcommand. It empties the ledger through the
same compare-and-swap, archives the replaced bytes, and leaves `HANDOFF.md`
in place as an empty valid ledger so the repository stays one that tracks
work this way. It does not delete the file, create a parallel ledger, or
start a task. `/handoff:purge` (or "purge the handoff") is the
authorization; do not empty or delete the ledger any other way.

Exit `3` means another writer changed the ledger first. The read that informed
this edit is stale, so the audit behind it is stale too: re-read the ledger,
redo the Step 2 progressive audit against the new entries, and apply again with
the current version. Never retry with the old version or reconstruct the
intended file from memory.

Exit `4` means the write would introduce structural errors and nothing was
written. Fix the entry rather than checking boxes the evidence does not support.
`--allow-structure-errors` exists for repairing a ledger that is already
malformed, not for pushing past a failed check.

## Step 5: Commit and stop safely

Before committing or stopping:

1. Run `git status` again and distinguish your files from other owners' work.
2. Run verification proportionate to the files and risk.
3. Update the task's step boxes, state, owner, status, blocker, and next
   action, then validate the ledger.
4. Stage explicit paths only. Never sweep another agent's changes into a commit.
5. Re-read and audit your assigned bucket. Continue eligible viewer assignments
   under Step 3 before stopping; do not end with an available assignment merely
   marked pending. Report progress while continuing the queue.
6. Report the outcome, verification, commit identifier, and any effective
   unfinished work with its concrete blocker or user-directed deferral.

If the task pauses, another agent must be able to continue from the ledger and
repository alone, without this conversation.

## Optional live progress viewer

In task details, users can select a step with Up/Down or `j`/`k`, cut it with
`x`, and paste it to another agent with `p`. The moved step becomes an assigned
task with source context; its original entry retains the other steps and a
transfer record. Audit and execute it under the same assignment rules as a
whole task. `X` in details still moves the whole task. See
`references/progress-viewer.md` for the history and completion rules.

Users can run `python3 "$SKILL_DIR/scripts/handoff_tui.py" --root /absolute/repo/path`
in a separate terminal to watch recorded task and per-owner progress. It
refreshes as the ledger changes. Counts reflect checkboxes and heading owners;
they do not replace the progressive audit or establish live activity or per-step
authorship. The live view also lets the user hand one task to another agent
(`x` to cut, `p` to give), which rewrites that heading's owner label and
appends a dated note to its status through the same compare-and-swap as `apply`;
`--read-only` disables it. The move is a user execution request: finish your
current task, then audit and complete the assignment under Step 3 without
another prompt. Because that install path is version-pinned,
`scripts/handoff-tui` is a launcher users can copy onto PATH once; it resolves
the viewer at run time and takes the same arguments. See
`references/progress-viewer.md` for controls, snapshot mode, and counting rules,
and `references/harness-setup.md` for wiring `scripts/handoff-bar` into a host
status line, including which harnesses expose one.

`--with <agent>` runs any agent CLI under a live bottom bar whose `Ctrl-G` opens
that viewer in a popup; `--codex` is `--with codex`. When the user asks for the
viewer key, or reports that `Ctrl-G` does something else in their harness, run:

```bash
python3 "$SKILL_DIR/scripts/handoff_tui.py" --install-viewer-key
```

It writes a binding that actually fires where the terminal emulator allows one,
and releases the key in Claude Code's own keybindings where it cannot.
Plain Codex also uses `Ctrl-G` for its external editor; installing the skill
alone does not intercept it. Respect a user-requested shortcut through
`HANDOFF_VIEWER_KEY`; suggest `C-M-h` (Ctrl+Alt+H) for iTerm2 so Ctrl+V stays
available for Codex image paste. The iTerm2 installer creates a dynamic
viewer profile and merges a global “New Window with Profile” binding for the
selected root; it reports conflicts instead of replacing existing shortcuts and
removes previous keys pointing to that same viewer when changing the key.
`--emulator cursor` covers Cursor's integrated terminal, where the key runs a
workspace task rather than typing into the agent. Use
`/handoff:view` when the harness has no controlling terminal for curses. It
merges into existing config rather than replacing it, is idempotent, and refuses
to rewrite files that do not parse. Do not edit a user's keybindings any other
way, and do not run it unasked.

## Named failure modes

- **Checkbox literalism:** calling an old unchecked item unfinished without
  reading later history or current source.
- **History erasure:** rewriting, emptying, or deleting the ledger instead of
  annotating how later work resolved an entry. `/handoff:purge` is the
  authorized exception: it archives the whole file and replaces it with an
  empty valid ledger, and only when the user asked.
- **Silent takeover:** editing a task or files still owned by an active agent
  without an explicit handoff.
- **Silent reclaim:** resuming or re-editing a task the ledger shows
  transferred to another owner, instead of reporting the move.
- **Lost queued request:** finishing older work without preserving the user's
  newer request as a pending entry.
- **Premature completion:** checking `Completed` before required verification,
  commit, deployment, or handoff work is done.
- **Private-context handoff:** leaving "continue later" without state, evidence,
  blocker, and next action.
- **Broad staging:** catch-all staging in a shared working tree.
- **Blind overwrite:** writing the ledger from a read another agent has already
  superseded, or retrying a rejected write without redoing the audit.
- **Borrowed detail:** filling a real entry with an example's agent name, path,
  or commit id instead of the repository's own values.

## Gates

When effective unfinished work exists, resolve the pickup choice before
implementation unless the user has already supplied the ordering. In every
case, ownership and file overlap must be safe, the selected task must be marked
`In progress`, and any newer queued work must remain visible in the ledger. A
takeover needs the user's explicit direction, a stopped prior owner, preserved
uncommitted work, and one ledger write that moves the whole bucket with the
transfer recorded where the returning owner will see it.

Do not declare success until every claimed step has evidence, required
verification ran, the validator passes, and only genuinely unfinished outcomes
are reported as open.
