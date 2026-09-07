# Handoff demo — two agents, one ledger.
#
#   ./make-fixture.sh --handoff /tmp/handoff-demo
#   cd /tmp/handoff-demo && vhs /path/to/demo.tape
#
# Session A is interrupted mid-task; session B takes it over cold. The comment
# lines typed at the prompt are the narration — without them the clip is two
# indistinguishable shells.
#
# The Sleep values around each claude session are the fragile part: they must
# exceed the real response time or the take truncates. Raise them rather than
# trimming the handoff. Check every render before publishing.

Output handoff.gif

Set Shell bash
Set FontSize 16
Set Width 1180
Set Height 620
Set Padding 22
Set Theme "Builtin Dark"
Set TypingSpeed 55ms
Set PlaybackSpeed 1.0

Hide
Type "export PS1='$ '" Enter
Type "clear" Enter
Show

# --- Session A --------------------------------------------------------------
Sleep 700ms
Type "# agent A picks up the task" Enter
Sleep 900ms
Type "cat HANDOFF.md" Enter
Sleep 3.5s

Type "claude" Enter
Sleep 3s
Type "Use handoff. Implement the open step in HANDOFF.md."
Sleep 500ms
Enter

# A writes the code, tests, and commits. Raise if your runs are slower.
Sleep 45s

# The session ends mid-task, before A closes the entry out.
Ctrl+C
Sleep 600ms
Ctrl+C
Sleep 1.2s
Type "# A's session ends here. mid-task." Enter
Sleep 900ms
Type "git log --oneline -1" Enter
Sleep 2.2s

# --- Session B --------------------------------------------------------------
Type "clear" Enter
Sleep 400ms
Type "# new session. no memory of anything above." Enter
Sleep 1.4s

Type "claude" Enter
Sleep 3s
Type "Use handoff. Tell me what is unfinished and finish it. Answer in three lines."
Sleep 600ms
Enter

# B audits, declines to redo A's commit, verifies, and closes the entry.
Sleep 45s

Type "/exit" Enter
Sleep 1.5s

# --- The receipt ------------------------------------------------------------
Hide
Type "clear" Enter
Show
Type "# one ledger, two agents, no work redone" Enter
Sleep 900ms
Type "git diff HANDOFF.md" Enter
Sleep 5s
