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

## Why a separate terminal

A command session has no controlling terminal, so curses cannot draw into it.
Opening the viewer means running `handoff-tui` where the user can see it.

Check that `handoff-tui` is on PATH (`command -v handoff-tui`). If it is
missing, copy the launcher from this skill first:

```sh
cp "$SKILL_DIR/scripts/handoff-tui" ~/.local/bin/
chmod +x ~/.local/bin/handoff-tui
```

## Open the viewer

If stdout is a terminal, run the viewer in the foreground and tell the user to
press `q` to return:

```sh
handoff-tui --root <target>
```

Otherwise spawn a new terminal that keeps running until the user closes the
viewer. Prefer the emulator the environment names; fall back to the first option
that exists on PATH.

**iTerm2 on macOS**

```sh
osascript -e 'tell application "iTerm2" to create window with default profile command "handoff-tui --root '"'"'<target>'"'"'"'
```

**Terminal.app on macOS**

```sh
osascript -e 'tell application "Terminal" to do script "handoff-tui --root '"'"'<target>'"'"'"'
```

**Linux or other Unix**

```sh
x-terminal-emulator -e handoff-tui --root <target>
```

If none of these work, tell the user to run `handoff-tui --root <target>` in
their own terminal.

## What to report

Name the repository, the command you ran or asked the user to run, and that the
viewer refreshes as the ledger changes. Mention `x`/`p`/`P` for handing a task
to another agent when write access is allowed, and `--read-only` when it is not.
Point at `/handoff:status` for a one-line snapshot when a full dashboard is not
needed.

State plainly that host harnesses such as Claude Code cannot bind a key to run
this command; `handoff-tui --install-viewer-key` writes a binding only where the
terminal emulator allows one, and the `--with` wrapper remains the way to get
`Ctrl-G` inside an agent session.
