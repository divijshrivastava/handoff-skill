---
description: Open the live handoff progress viewer
argument-hint: [repository path]
---

Open the live curses dashboard for this repository's ledger. Read-only with
respect to the repository unless the user asks otherwise: do not edit the
ledger, run no `apply`, and start no work.

Argument (may be empty): $ARGUMENTS

Resolve the repository root from the argument when given, otherwise from the
current working directory. If `HANDOFF.md` is absent, say so and stop; do not
create one.

## Open the viewer immediately

A command session has no controlling terminal, so curses cannot draw into it.
Run **one** command that spawns a real terminal and returns; do not assemble
AppleScript or emulator-specific launchers yourself:

```sh
handoff-tui --open --root <target>
```

If `handoff-tui` is missing from PATH, copy the launcher first:

```sh
cp "$SKILL_DIR/scripts/handoff-tui" ~/.local/bin/
chmod +x ~/.local/bin/handoff-tui
```

Use the repository copy when the installed skill is older than the `--open`
flag:

```sh
python3 "$SKILL_DIR/scripts/handoff_tui.py" --open --root <target>
```

If stdout is a terminal and the user is already at a shell, `--open` is
optional: `handoff-tui --root <target>` in the foreground also works; tell
them to press `q` to return.

## What to report

Name the repository, confirm the opener ran (or quote its error), and that the
viewer refreshes as the ledger changes. Mention `x`/`p`/`P` for handing a task
to another agent when write access is allowed, and `--read-only` when it is not.
Point at `/handoff:status` for a one-line snapshot when a full dashboard is not
needed.

State plainly that host harnesses such as Claude Code and Cursor cannot bind a
key to run this command; `handoff-tui --install-viewer-key` writes a binding
only where the terminal emulator allows one, and the `--with` wrapper remains
the way to get `Ctrl-G` inside an agent session.
