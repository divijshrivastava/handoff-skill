---
description: Purge the handoff ledger and leave a clean slate
argument-hint: [repository path]
---

Purge this repository's `HANDOFF.md` to an empty valid ledger. This is
authorized history erasure: every entry is replaced at once. It is not a
per-task close, and it does not delete the file — an existing `HANDOFF.md`
is what keeps the repository one that tracks work this way.

Argument (may be empty): $ARGUMENTS

The user invoking this command, or writing "purge the handoff", is the
authorization. Do not empty or delete the ledger any other way, and do not
run this because a ledger looks long, stale, or messy.

Resolve the repository root from the argument when given, otherwise from the
current working directory, then:

1. Claim this session's name with the helper's `name` command.
2. Read the whole ledger with the helper's `read` command so the text and
   version come from one snapshot. If `HANDOFF.md` is absent, say so and
   stop; do not create one. Init is how a repository without a ledger
   becomes one.
3. Run the read-only `doctor` and `git status`. Report the recorded task
   count and any live name-cache holders once, as what is about to be
   replaced, not as a second confirmation.
4. Purge through the helper, passing the version from that read:

```sh
python3 "$SKILL_DIR/scripts/handoff_guard.py" purge --root <target> \
  --expect-version <version from the read> \
  --confirm purge
```

The helper holds the same compare-and-swap lock as `apply`: it archives the
replaced bytes next to the ledger (`HANDOFF.md.<version prefix>.bak`), then
writes an empty valid ledger (`# Handoff`) in place. It does not start a
task, touch the session name cache, or create a parallel ledger under
another name. The archive is a recovery sidecar, not a ledger; do not read
it as `HANDOFF.md`.

Exit `3` means another writer changed the ledger first. Re-read, redo the
report, and purge again with the current version. Never retry with the stale
version. Exit `1` means there was no ledger, or the archive path already
holds different bytes; nothing was written.

5. Report once: that the ledger is empty but present, the archive path (or
   that `--no-archive` was used), and that later work starts as new entries.
   Do not commit the archive or the emptied ledger unless the user asks.
   Leave other owners' uncommitted files alone.

`--archive <path>` chooses the sidecar; `--no-archive` skips it when git
already holds the history the user wants to keep. `--dry-run` reports
without writing.
