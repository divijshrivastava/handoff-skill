---
name: handoff
description: "Coordinate progressive repository work across agents with a shared HANDOFF.md ledger. Use in repositories with a ledger, or on explicit handoff requests: /handoff:init, 'initialise the handoff', /handoff:continue, /handoff:status, /handoff:view, /handoff:queue, /handoff:purge, or 'use handoff'. After activation: handoff_guard.py name --root <repo> claims the session name; handoff_guard.py read --root <repo> returns ledger text and version in one snapshot. Audit later entries and code before treating unchecked boxes as unfinished. For ledger writes: handoff_guard.py apply --root <repo> --expect-version V with --entry FILE or --content FILE. On exit 3, re-read and re-audit; never retry the stale write. A user viewer assignment is required queued work: finish your current task, then audit and complete it without another prompt. Track investigations before research, even without code edits; a name claim is not a task."
license: MIT
metadata:
  version: "1.27.1"
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
  `/handoff:view`, `/handoff:queue`, `/handoff:purge`, or a direct instruction
  such as "use handoff", "record this in the ledger", "purge the handoff", or
  "take over <owner>'s tasks".

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
**Every task the user gives gets its own entry, and the number of times they
have asked never changes that.** A repeat of an earlier request, a request you
believe you already satisfied, a correction, a narrowing, a "do it again" - each
is a task in its own right and is recorded before the work resumes. Do not
reason that an existing entry already covers it: if the user had to ask again,
the ledger is not showing what they think they asked for, and a second entry is
how that becomes visible. Writing the entry is the first action, ahead of
answering, investigating, or editing.

Only two things are not tasks and so create no entry: displaying existing status
(`/handoff:status`, `/handoff:view`, or `/handoff:queue`), and answering a
question from evidence already gathered. If either turns into work - the answer
requires new investigation, or the user asks for a change - record it first.

## Step 0: Preflight before task work

1. Run the bundled preflight, using the directory that contains this `SKILL.md`
   as `SKILL_DIR`. It claims this session's name, reads the ledger, checks its
   structure, and reports Git state from one snapshot:

   ```bash
   python3 "$SKILL_DIR/scripts/handoff_guard.py" preflight --root /absolute/repo/path
   ```

   `--root` accepts any path inside the repository.

   It returns:

   - `session.name`: the name you own every entry under. Use it verbatim; never
     invent one, borrow a peer's, or rename yourself mid-task, because the
     label is how a later agent tells your work from a peer's. Record your
     harness beside it (`template --harness auto`; `HANDOFF_HARNESS` names a
     tool the helper cannot detect). A name and channel session ID supplied by
     the SessionStart hook are this claim already; keep them.
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
This holds however many times the same thing is asked: a repeated request is a
new entry, never a reason to skip one.
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
authorization and ordering: do not ask the pickup question, wait for another
prompt, or report it as pending and stop. Check your assigned bucket at
preflight, at checkpoints, and before stopping; finish and verify your current
task, then work eligible assignments oldest first. Missing a second user prompt
is never a blocker. Before acting on one, read `references/ownership.md` for
the audit, attribution, and blocker rules.

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

### Unavailable agents and authorized takeover

Before coordinating with a peer, investigating a stalled owner, releasing or
leasing your own bucket, or taking over another agent's work, read
`references/ownership.md`; `references/agent-channel.md` documents the channel
commands it uses. The binding rules: silence, an unanswered ping, an expired
working report, or an open PID decides nothing; nobody's work moves by
detection, only by the owner's own `yield`, an expired `lease` that a peer
`sweep`s, or the user's explicit direction naming the prior owner. A takeover
then needs stopped writers, preserved uncommitted work, and one locked write
moving the whole bucket. When your own entries now carry another owner and a
transfer note naming you, report the move and do not take them back.

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

Direct edits suit sequential handoffs and separate worktrees. When another agent
may write the same working tree, route every ledger write through the guard:

```bash
python3 "$SKILL_DIR/scripts/handoff_guard.py" apply --root /absolute/repo/path \
  --expect-version <version from the read> \
  --entry /path/to/new-entry.md
```

`--entry` inserts one new entry at the newest position; `--content` replaces
the whole ledger after editing existing entries. Exit `3` means another writer
changed the ledger first, so the audit behind this edit is stale: re-read,
redo the Step 2 audit, and apply with the current version, never retrying the
old one or rebuilding the file from memory. Exit `4` means the write would add
structural errors and nothing was written; fix the entry, not the evidence.
Empty the ledger only with `purge`, and only on `/handoff:purge` or "purge the
handoff". `references/ledger-contract.md` explains the lock, purge, and
`--allow-structure-errors`.

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

Users watch recorded progress with
`python3 "$SKILL_DIR/scripts/handoff_tui.py" --root /absolute/repo/path`, or the
`scripts/handoff-tui` launcher copied onto PATH; `/handoff:view` opens it where
the harness has no terminal for curses. Its counts reflect checkboxes and
heading owners, not live activity, and never replace the progressive audit. A
user moving a task or a single step to you there (`x`/`p`, `X`) is a viewer
assignment under Step 3. Read `references/progress-viewer.md` for controls and
counting rules, and `references/harness-setup.md` for status lines,
`--with <agent>`, and the viewer key.

Run `handoff_tui.py --install-viewer-key` only when the user asks for the
viewer key or reports `Ctrl-G` doing something else in their harness. Respect a
shortcut they chose through `HANDOFF_VIEWER_KEY`, and never edit a user's
keybindings any other way.

## Pulling an assignment the session was never sent

The viewer's task move writes `HANDOFF.md` and nothing else. No signal reaches a
CLI that is already running: a Claude Code hook carries the notice on that
session's next event, and a harness without such a hook never delivers it.
`handoff_guard.py assignments --root <repo>` is the pull side, and
`/handoff:queue` is its command. It reports entries recorded to a name with no
step checked yet, and names the viewer move behind each one, so work a user
handed over is distinguishable from work an agent claimed for itself.

It reads one snapshot and writes nothing, including no name claim. What it
returns is recorded, never evidence that a move was read or that an owner is
active, so audit before acting and resume through this skill rather than from
that list. Messaging a *peer* is a different act entirely,
`handoff_channel.py nudge`, a rate-limited request that decides nothing; see
`references/agent-channel.md`.

## Leader and follower messages

The channel carries two kinds of message, and the kind decides what the
recipient owes in return.

A **normal message** (`send`) asks or tells: a leader checking status, an answer
about work in flight, ordinary conversation. It obliges nothing beyond reading
and acknowledging it.

A **task message** (`assign-task --to <session> --title T --step S`) assigns
work. It carries the title and steps so the follower records what was actually
asked rather than its own paraphrase, and it cannot be broadcast, because an
assignment needs exactly one owner.

A task message assigns nothing by itself. It becomes real only when the follower
writes it into the ledger, which is the same rule everything else here obeys: a
message can be missed, duplicated, or read by a session that no longer exists,
so a message must never be the thing that decided who owns work.

On receiving a task message the follower, before doing any of the work:

1. reads it with `tasks`, which lists task messages it has not yet recorded;
2. records it with `record --id <message> --expect-version V`, which writes the
   entry through the one compare-and-swap and tells the sender the heading.

Then, and only then, the work. `record` defaults to a **pending** entry, which is
the mid-task case: a follower already working records the new task so it is
visible to everyone, returns to what it was doing, and picks the new entry up
from the ledger when it is free — `/handoff:queue` lists exactly that. Pass
`--start` only when this session is free and begins immediately. Recording twice
is refused rather than duplicated, so a retried `record` is safe.

Never skip the recording step because the work looks quick. The entry is what
survives this session; an unrecorded task that dies with its agent is
indistinguishable from one that was never sent.

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
