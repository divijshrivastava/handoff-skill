# Publishing handoff state to a VPS

Read this before running `handoff_publish.py`, and before relying on anything a
twin displays.

`handoff_publish.py` captures the ledger and the channel, slices the result by
owner, and writes it to a path on a host you configured beforehand. Each agent's
twin on that host reads its own file: the entries that owner holds, the messages
it sent and received, and the state it last reported.

## One way, by design

A twin observes. Nothing flows back.

Two machines editing one ledger would need `swap_ledger`'s compare-and-swap to
hold across a network. It does not: both would pass the version check against
the same revision, and one entry would be lost. That is the defect this project
already fixed once locally, and a network makes it harder rather than easier.
Ownership transfer between machines is a separate design; do not add it as a
flag on this one.

## Setup

The destination and the agent map live in `.handoff/vps.json`, which is
gitignored, so no credential and no machine detail reaches a commit. Write it by
hand: this file describes machines the repository cannot discover.

```sh
python3 skills/handoff/scripts/handoff_publish.py example > .handoff/vps.json
```

```json
{
  "destination": { "host": "you@vps.example.com", "path": "/srv/handoff/your-repo" },
  "agents": [
    { "owner": "Epona", "harness": "Claude Code", "twin": "Epona" },
    { "owner": "Fenrir", "harness": "Codex", "twin": "Fenrir" }
  ]
}
```

`owner` is the ledger label. `harness` is the tool that owner runs in, and it is
checked: a twin configured as Codex whose owner's entries record Claude Code is
reported, because the harness is part of the identity being mirrored. `twin`
defaults to the owner name and is the file the twin reads.

Transport is `ssh`, using keys you already have. Nothing new is installed and no
secret is stored.

## Commands

```sh
handoff_publish.py check    --root .            # config, ledger version, warnings
handoff_publish.py snapshot --root . --out DIR  # build the tree locally, send nothing
handoff_publish.py publish  --root .            # build and send
handoff_publish.py publish  --root . --dry-run  # build, print the remote command, send nothing
```

## What lands on the host

```text
<path>/snapshot.json        the whole capture
<path>/ledger.md            the ledger text
<path>/agents/<twin>.json   one file per configured agent
```

The tree is unpacked into a staging directory and swapped into place in one
move, so a twin reading during a publish sees the previous state or the next
one, never half of each. The prior state stays as `<path>.previous`.

## What it is not

**Not a liveness signal.** Every field is what a store said at capture time. A
slice carries `reported_at` and `report_age_seconds`; it never carries "online".
Silence cannot separate an exhausted agent from an idle healthy one, and a twin
that renders a stale report as presence will mislead whoever reads it.

**Not authority.** A twin reading its slice has not been handed the work. The
ledger in this repository remains the only record of ownership, and a takeover
still needs the user's explicit direction, a stopped prior owner, and preserved
uncommitted work.

**Not a backup.** Only what the ledger and channel hold is published. Uncommitted
source, the working tree, and git history are not.

## Message bodies leave the machine

Bodies are published, by decision. They contain paths, commit hashes, and quoted
work. Two consequences:

- Home directories are rewritten to `/Users/<user>` and `/home/<user>` before
  anything is written out, including in a local `snapshot`, so a tree on disk is
  already safe to move. Redaction covers home paths and nothing else: it is not
  a secret scrubber, and a message body is only as safe as what an agent wrote
  into it.
- Point the destination at a host and path you control. Publishing to a shared
  or public location publishes every agent's conversation with it.

## Capture is one moment

The ledger and the channel have independent writers. Reading them in sequence
can describe a state that never existed, so the capture re-reads the ledger
version after reading the channel and starts over when it moved. A tree under
steady concurrent writes fails the capture rather than publishing a blend of two
moments; retry when it settles.

Message rows come from the channel's own `history` query and reported state from
`silence`, rather than a third query over the same tables. An installed channel
too old to have `history` still publishes reported state, and records in
`messages_available` that bodies were not included.
