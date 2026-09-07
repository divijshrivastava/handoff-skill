---
name: handoff
description: "Coordinate progressive repository work across agents with a shared HANDOFF.md ledger. Use before starting, continuing, checking, pausing, handing off, or committing a repository task whenever HANDOFF.md exists, multiple agents may be involved, the user mentions unfinished tasks or another agent, or work must be split into trackable steps. Audits later work and current code before treating old unchecked boxes as unfinished. Do not use for read-only questions that require no task tracking or repository mutation."
license: MIT
metadata:
  version: "1.3.0"
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

## Step 0: Preflight before task work

1. Resolve the repository root without assuming the current directory is it.
2. Read every applicable repository instruction file before mutating anything.
3. Read the whole handoff ledger, newest entry to oldest. Do not stop at the
   first unchecked box. When another agent may write this tree, take that text
   and its version from one snapshot rather than two separate reads:

   ```bash
   python3 "$SKILL_DIR/scripts/handoff_guard.py" read --root /absolute/repo/path
   ```

   Audit the text it returns and pass the version it returns. Reading the ledger
   and then asking separately for a version binds an audit of the old text to a
   newer version, and a `--content` write built from it deletes the peer entry
   that landed between the two reads.
4. Run the bundled read-only doctor, using the directory that contains this
   `SKILL.md` as `SKILL_DIR`:

   ```bash
   python3 "$SKILL_DIR/scripts/handoff_guard.py" doctor --root /absolute/repo/path
   ```

5. Run `git status` and inspect relevant recent history. If collaboration or
   agent-status tools exist, check which owners are actually active.
6. Before the first ledger edit, read `references/ledger-contract.md`.

The doctor reports structural state only. Never present its raw pending or
in-progress result as the effective status until the progressive audit below is
complete. The doctor's `Version` is a convenience for a single-writer tree; when
peers may write, use the snapshot from `read` instead, because only that binds
the audited text to the version.

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
  --owner "Agent name" \
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

Check `In progress` immediately before the first implementation step. Check a
step only after its outcome exists. Check `Completed` only after every required
step and proportionate verification finish. Leave `In progress` checked on a
completed task to preserve the transition history.

If local instructions require a user choice before mutation, propose the
pending entry and write it only after that choice. Otherwise record the request
as pending as intake begins, so it cannot disappear while older work finishes.

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
5. Report the outcome, verification, commit identifier, and any effective
   unfinished work.

If the task pauses, another agent must be able to continue from the ledger and
repository alone, without this conversation.

## Named failure modes

- **Checkbox literalism:** calling an old unchecked item unfinished without
  reading later history or current source.
- **History erasure:** rewriting or deleting an earlier task instead of
  annotating how later work resolved it.
- **Silent takeover:** editing a task or files still owned by an active agent
  without an explicit handoff.
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
`In progress`, and any newer queued work must remain visible in the ledger.

Do not declare success until every claimed step has evidence, required
verification ran, the validator passes, and only genuinely unfinished outcomes
are reported as open.
