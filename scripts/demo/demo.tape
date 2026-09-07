# Handoff demo — deterministic framing for a retake.
#
#   ./make-fixture.sh && cd /tmp/handoff-demo && vhs /path/to/demo.tape
#
# The Sleep values after the prompt are the only fragile part: they must exceed
# the model's actual response time or beat 4 truncates. Raise them rather than
# trimming the audit. Check every render before publishing.

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

# --- Beat 1: an open box from three days ago -------------------------------
Sleep 700ms
Type "tail -5 HANDOFF.md" Enter
Sleep 2.6s

# --- Beat 2: the work it describes is already done and tested ---------------
Type "python3 -m unittest discover -q" Enter
Sleep 2.4s

# --- Beat 3: ask for the audit ---------------------------------------------
Type "claude" Enter
Sleep 3s
Type "Use handoff to audit HANDOFF.md and tell me what is actually unfinished."
Sleep 600ms
Enter

# --- Beat 4: the audit. Raise this if your runs are slower. -----------------
Sleep 30s

Type "/exit" Enter
Sleep 1.5s

# --- Beat 5: the receipt ---------------------------------------------------
Hide
Type "clear" Enter
Show
Type "git diff HANDOFF.md" Enter
Sleep 4.5s
