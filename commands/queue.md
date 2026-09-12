---
name: handoff-queue
description: Report the ledger assignments this session has not picked up yet
argument-hint: [all | owner name | repository path]
---

Pull this repository's recorded assignments into the session. Read-only with
respect to the repository: make no edits, run no `apply`, and start no work from
this command.

Argument (may be empty): $ARGUMENTS

Interpret the argument as one of: empty (this session's own queue), `all` (every
owner with unstarted work), an owner name, or a repository path. A path may be
combined with either of the others.

Resolve the repository root from a path argument when given, otherwise from the
current working directory. If `HANDOFF.md` is absent, say so and stop; do not
create one.

## Why this command exists

The viewer's task move writes `HANDOFF.md` and nothing else. Nothing pushes into
a CLI that is already running, so a session mid-turn does not see the assignment:
on Claude Code a hook carries the notice on that session's *next* event, and a
harness without such a hook never delivers it at all. Restarting the chat to pick
work up loses the session. This is the pull side of that gap.

## Report

```sh
python3 "$SKILL_DIR/scripts/handoff_guard.py" assignments --root <target>
```

Add `--all` for every owner, or `--owner <name>` for one other agent's queue. The
command claims no name: a session that has not run preflight reports no owner,
which is the honest answer rather than a reason to claim one here.

Name each entry with its heading, state, and the owner's own `Status:` words.
Where an entry carries `viewer_moves`, say who moved it, from whom, and on what
date — that is the difference between work a person handed over and work an agent
claimed for itself. Quote the reported figures as **recorded**: they count
checkboxes and heading labels, and are not evidence that a task is finished, that
its owner is still active, or that anyone has read the move.

An entry stays listed until a step box is checked, so a queue that looks
unchanged since the last run usually means exactly that.

## After reporting

Reporting is where this command stops. Do not audit entries, edit the ledger, or
begin the work from here.

The skill treats a viewer assignment as an execution request, so when the queue
is not empty, say plainly that `/handoff:continue` is what audits and resumes it,
and let the user choose. If they ask you to go ahead, run `/handoff:continue`
rather than working from this list: the list is one snapshot and has not been
audited against later entries, commits, or current source.

When another agent's queue is what you reported, this command has not told them
anything: it reads the ledger and sends nobody a message. Notifying a peer is
`handoff_channel.py nudge --to <session>`, a rate-limited request that is never
a verdict; read `references/agent-channel.md` before using it.
