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

Five beats. Times are targets for the finished GIF, not a stopwatch for the take.

**Beat 1 — the setup (0:00–0:04).** The looping frame. This is what a scrolling
reader sees, so it has to state the problem without narration.

```sh
tail -5 HANDOFF.md
```

Shows `- [ ] Verify empty queries and no-result behavior.` — an open box from
three days ago.

**Beat 2 — the contradiction (0:04–0:07).**

```sh
python3 -m unittest discover -q
```

Three tests, OK. The box is open. The work is done. Anyone who has run an agent
over a stale checklist knows what happens next.

**Beat 3 — the prompt (0:07–0:09).** Type it, don't paste it:

```
Use handoff to audit HANDOFF.md and tell me what is actually unfinished.
```

**Beat 4 — the audit (0:09–0:20).** The payload. What has to be visible:

- it reads the ledger
- it checks `git log` / the source rather than trusting the box
- it names the commit that satisfied the step
- it says it is annotating rather than redoing

If the run buries this under tool narration, that is worth fixing in `SKILL.md`
before you record again — the output discipline section already asks for exactly
this and the demo is the test of whether it works.

**Beat 5 — the receipt (0:20–0:25).**

```sh
git diff --stat HANDOFF.md && git diff HANDOFF.md | head -20
```

The ledger now carries the resolution and the evidence. End on this frame.

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
  --speed 1.35 \
  --theme asciinema \
  --idle-time-limit 1.5

gifsicle -O3 --lossy=60 --colors 128 handoff.gif -o handoff-opt.gif
ls -lh handoff-opt.gif
```

**Size targets.** Under 5 MB or X will transcode it into mush; under 3 MB is
better. GitHub renders up to 10 MB but a slow README hero costs you the visit.
If it is too big, cut beat 2 before you cut the audit — the audit is the product.

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
