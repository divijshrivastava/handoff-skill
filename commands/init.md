---
name: handoff-init
description: Initialise handoff tracking for this repository and session
argument-hint: [repository path]
---

Initialise the handoff workflow. In a repository that keeps no `HANDOFF.md`,
this command is the activation gate: nothing handoff-related — no session name,
preflight, or ledger creation — runs before the user calls it or writes
"initialise the handoff". Where a `HANDOFF.md` already exists, that ledger has
already made the repository one that tracks work this way, and this command
only reports its recorded state.

Argument (may be empty): $ARGUMENTS

Resolve the repository root from the argument when given, otherwise from the
current working directory, then run the handoff skill's preflight in order:

1. Run the helper's `preflight` command. It claims this session's name — use it
   verbatim as the owner label of every entry this session writes — and, when a
   ledger exists, returns its digest, structure errors, and Git state from one
   snapshot.
2. Read every applicable repository instruction file.
3. If `HANDOFF.md` exists, audit the open entries the preflight returned, and
   use the helper's `read` command when an audit needs the exact ledger bytes.
   If none exists, follow the repository's local instructions; when none are
   prescribed and mutation is authorized, create `HANDOFF.md` from the skill's
   `references/ledger-contract.md`. Never create a parallel ledger under
   another name.

Then report, once: the session name, whether a ledger was found or created,
and — when a ledger exists — each entry's effective status after the
progressive audit, not its raw checkboxes.

Initialising lazy-loads the skill: from then on the full handoff workflow
governs every repository request for the rest of the session, with no further
invocation needed. Initialising itself starts no task — do not start, resume,
or take over any task here; task work begins with the user's next request,
recorded per the skill's intake steps.
