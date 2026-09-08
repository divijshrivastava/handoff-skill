---
name: handoff-status
description: Show a live handoff progress bar in the status line, or a snapshot
argument-hint: [off | repository path]
---

Show this repository's recorded ledger progress. Read-only with respect to the
repository: make no edits, run no `apply`, and start no work.

Argument (may be empty): $ARGUMENTS

If the argument is `off`, remove the `statusLine` field this command added from
`~/.claude/settings.json`, confirm it is gone, and stop. Leave a `statusLine`
this command did not add alone; say so instead.

Otherwise do both of the following.

## 1. Turn on the live bar

Claude Code's status line is a row at the bottom that re-runs a command and
redraws. Point it at the viewer's one-line mode so ledger progress stays visible
while work happens.

Check that both scripts are on PATH (`command -v handoff-bar handoff-tui`). If
either is missing, copy them from this skill first:

```sh
cp "$SKILL_DIR/scripts/handoff-bar" "$SKILL_DIR/scripts/handoff-tui" ~/.local/bin/
chmod +x ~/.local/bin/handoff-bar ~/.local/bin/handoff-tui
```

Use `handoff-bar`, not `handoff-tui --bar`: hosts cap how long a status-line
command may take, and the bar caches its row so a tick costs about 31ms rather
than 250ms. `references/harness-setup.md` carries the per-harness configuration
for Claude Code, Grok, and Kimi, and records which harnesses have no such hook.

Then add this to `~/.claude/settings.json`, preserving every other setting:

```json
"statusLine": {
  "type": "command",
  "command": "$HOME/.local/bin/handoff-bar",
  "padding": 0,
  "refreshInterval": 2
}
```

If the host is not Claude Code, use its own status-line configuration from
`references/harness-setup.md` instead of the JSON above. Use the PATH script,
never a versioned plugin path, so the bar survives skill upgrades. `refreshInterval` re-runs the command on a timer, so the bar keeps
moving while the session is idle and other agents write the ledger.

If `statusLine` already holds something else, do not overwrite it. Report what is
there and ask before replacing.

Verify before claiming it works: pipe a sample payload through the command and
show the row it prints.

```sh
echo '{"workspace":{"current_dir":"'"$PWD"'"}}' | ~/.local/bin/handoff-bar
```

The bar prints nothing outside a repository that has a ledger, which is intended:
the status line stays empty rather than showing an error. Tell the user the bar
appears on their next interaction.

## 2. Report current progress

Show the totals and the per-owner table, which the bar has no room for:

```sh
handoff-tui --root <target> --once | sed -n '/^TASKS (ledger order)/q;p'
```

If `HANDOFF.md` does not exist, say so and stop; do not create one. Add one or
two sentences naming the entries recorded as in progress or pending and their
owners, reading the task list from the full snapshot without pasting it.

State plainly that these are **recorded** figures: they count checkboxes and
heading owners. They are not evidence that a task is finished, that an owner is
still active, or that a given owner performed a step. For effective status, point
the user at `/handoff:continue`, which runs the progressive audit.

For the full dashboard, with per-owner drilldown and task detail, the user runs
`handoff-tui` in a separate terminal. A command session cannot host it, because
Claude Code owns this terminal.
