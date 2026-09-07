# Handoff demo recording

Produces the ~25 second GIF for the README hero and the launch tweet.

The clip has one job: show an agent refusing to redo work that a later commit
already finished. That is the skill's headline claim, so the demo has to be the
claim actually happening — not a re-enactment of it.

## Ground rules

- **Never edit the agent's output.** If the audit gets it wrong, that is a skill
  bug to fix and re-record, not a take to trim until it looks right. A faked
  demo on a repo whose selling point is evidence would be the end of it.
- Real terminal, real session, real repo. The fixture is constructed, the audit
  is not.
- If a take is 40 seconds, keep it. `agg --speed` fixes length; a rushed prompt
  that skips the reasoning does not.

## 1. Build the fixture

```sh
./make-fixture.sh              # creates /tmp/handoff-demo
```

Two commits. The first opens `Verify empty queries and no-result behavior.` as
an unchecked step. The second implements exactly that and adds `test_search.py`,
and — as actually happens in real repositories — never goes back to tick the box.

Verify before recording:

```sh
cd /tmp/handoff-demo
python3 -m unittest discover -q     # 3 tests, OK
git log --oneline                   # 2 commits
```

Install the skill into the fixture the way a user would, so the clip shows the
real install path:

```sh
cd /tmp/handoff-demo
claude
/plugin marketplace add divijshrivastava/handoff-skill
/plugin install handoff@divij-skills
```

Then exit, `rm -rf /tmp/handoff-demo`, and rebuild the fixture so the recording
starts from a clean tree with the plugin already available.

## 2. Terminal setup

| Setting | Value | Why |
| --- | --- | --- |
| Columns × rows | 92 × 26 | Wide enough for the ledger, short enough to stay legible in a timeline |
| Font size | 15–16pt | Readable at 600px wide on a phone |
| Theme | Your normal dark theme | Consistent with everything else you post |
| Prompt | `$ ` only | Strip the path, git branch, and hostname — they are noise and they leak your directory layout |

```sh
export PS1='$ '
clear
```

## 3. The shot list

Two sessions, one terminal. The point of the skill is that the second agent
picks up the first one's work correctly, so the clip has to show two distinct
agents — a single session auditing its own ledger only demonstrates half of it,
and a viewer can reasonably ask why `git log` would not do.

Build the fixture in handoff mode, where nothing implements the open step yet:

```sh
./make-fixture.sh --handoff /tmp/handoff-demo && cd /tmp/handoff-demo
```

The clip has no voiceover, so the terminal narrates itself with comment lines
typed at the prompt. They are part of the demo, not setup.

### Session A — the agent that gets interrupted

**Beat 1 — the task (0:00–0:05).**

```sh
# agent A picks up the task
cat HANDOFF.md
```

The whole entry, not a fragment: task name, the ticked step, the open one.

**Beat 2 — A works (0:05–0:14).**

```sh
claude
```

```
Use handoff. Implement the open step in HANDOFF.md.
```

A checks `In progress`, writes the empty-query handling and its tests, and
commits.

**Beat 3 — the session dies (0:14–0:17).** Close it mid-task, before A records
verification and closes the entry out. Do not ask it to stop politely — an
interrupted session is the actual scenario, and the ledger is what has to
survive it.

```sh
# A's session ends here. mid-task.
git log --oneline -1
```

### Session B — the agent that takes over

**Beat 4 — a cold start (0:17–0:21).** The boundary has to be unmistakable, so
clear the screen and say so.

```sh
clear
# new session. no memory of anything above.
```

**Beat 5 — B picks it up (0:21–0:34).**

```sh
claude
```

```
Use handoff. Tell me what is unfinished and finish it.
```

This is the payload, and what has to be legible:

- B knows a task is open and **who owns it**
- B sees that the implementation is already done, in A's commit, and **does not
  redo it**
- B verifies rather than trusting the ledger
- B finishes only the genuinely remaining step and closes the entry

The one sentence the whole clip exists for is B saying, in effect: *agent A
already implemented this in `<sha>`; I am not rewriting it — what is left is the
verification.* If your take buries that under tool narration, fix the output
discipline before recording again.

Keep the answer short. Add "answer in three lines" to the prompt if the model
sprawls; a thousand characters flashing past in one frame reads as noise.

**Beat 6 — the receipt (0:34–0:40).** End on the ledger, and hold it.

```sh
# one ledger, two agents, no work redone
git diff HANDOFF.md
```

Give this frame extra time on export with `--last-frame-duration 4`.

### If you want the stronger version

Run the two sessions in side-by-side `tmux` panes and record the pane pair, so
both agents are on screen at once and the takeover is spatial rather than
sequential. It is a harder take to land — two live sessions and no `clear` to
hide behind — but nobody has to be told there are two agents.

The default `./make-fixture.sh` (no flag) still builds the older single-session
scenario, where the work is already committed and one agent audits the stale
box. Keep it for a shorter clip.

## 4. Record

`asciinema` is the primary route: it records real time and compresses dead air,
which is what you want when a model takes eleven seconds to answer.

```sh
cd /tmp/handoff-demo
asciinema rec handoff.cast --idle-time-limit 1.5 --cols 92 --rows 26
# ... perform the five beats, then Ctrl-D
```

Convert and compress:

```sh
agg handoff.cast handoff.gif \
  --font-size 16 \
  --speed 1.0 \
  --theme asciinema \
  --idle-time-limit 5 \
  --last-frame-duration 8

gifsicle -O3 --lossy=60 --colors 128 handoff.gif -o handoff-opt.gif
ls -lh handoff-opt.gif
```

**Lead-in.** asciinema starts timing before your first keystroke, so the clip can open on a
blank terminal -- which is the frame a README and a link preview both show. Trim it in the cast
rather than lowering `--idle-time-limit`, which compresses every pause in the recording and can
make the verdict unreadable:

```sh
python3 - <<'EOF'
import json
lines = open('handoff.cast').read().splitlines()
events = [json.loads(l) for l in lines[1:] if l.strip()]
shift = events[0][0] - 0.2
open('handoff.cast', 'w').write('\n'.join(
    [lines[0]] + [json.dumps([round(t - shift, 6), k, d]) for t, k, d in events]) + '\n')
EOF
```

**Size targets.** Under 5 MB or X will transcode it into mush; under 3 MB is
better. GitHub renders up to 10 MB but a slow README hero costs you the visit.
If it is too big, shorten the `cat HANDOFF.md` frame before you touch beats 5 and 6 —
the verdict and the receipt are the product.

## 5. VHS alternative

For a deterministic retake with tighter framing, `vhs demo.tape` (see the tape
file next to this one). It re-runs the commands itself, so every take is framed
identically — but its `Sleep` values are fixed, and a slow model response will
truncate beat 4. Check the output before publishing, and raise the sleeps rather
than trimming the audit.

## 6. Where it goes

- **README** — immediately under the first paragraph, above `## Install`. The
  install instructions are the fourth thing a visitor needs; the demo is the
  first.
- **Launch tweet** — attached directly, not as a link to the repo. Media posts
  out-reach link posts roughly sixfold.
- Keep `handoff.cast` in the repo. It is small, it is text, and it lets anyone
  re-render the GIF at a different size without re-recording.
