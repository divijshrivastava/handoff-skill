---
description: Show recorded HANDOFF.md progress overall and per owner
argument-hint: [repository path]
---

Report this repository's recorded ledger progress. Read-only: make no edits, run
no `apply`, and start no work.

Target repository (may be empty, meaning the current directory): $ARGUMENTS

Run the progress viewer's snapshot mode and show the summary above the task list:

```sh
handoff-tui --root <target> --once | sed -n '/^TASKS (ledger order)/q;p'
```

`handoff-tui` is the launcher on PATH. If it is not installed, fall back to the
viewer inside this skill, `python3 "$SKILL_DIR/scripts/handoff_tui.py"`, with the
same arguments. If `HANDOFF.md` does not exist, say so and stop; do not create
one. If the snapshot exits non-zero, show its error and stop.

Present the totals and the per-owner table as returned. Then add, in one or two
sentences, which entries are recorded as in progress or pending and who owns
them. Read the task list from the full snapshot for that, but do not paste it.

State plainly that these are **recorded** figures: they count checkboxes and
heading owners. They are not evidence that a task is finished, that an owner is
still active, or that a given owner performed a step. An old unchecked box is
frequently already satisfied by later commits. If the user wants effective
status rather than recorded status, point them at `/handoff:continue`, which
runs the progressive audit.

Mention the live dashboard only if it is useful: this command prints a snapshot
because a command session has no terminal to draw into. For the refreshing view
with per-owner drilldown, the user runs `handoff-tui` themselves in a separate
terminal.
