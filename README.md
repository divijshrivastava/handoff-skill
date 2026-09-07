# Handoff

**Pick up the work. Keep the history. Know what is actually left.**

An agent skill for continuing repository work across sessions and agents using one shared `HANDOFF.md` ledger.

An unchecked box from yesterday does not always mean unfinished work today. Handoff checks later entries, commits, current code, and ownership before deciding what to resume. It keeps new requests visible, protects work owned by another agent, and leaves enough context for the next session to continue.

## Install

From an Agent Skills compatible host:

```sh
npx skills add divijshrivastava/handoff-skill --skill handoff
```

Add `-g` for installation across projects. The installer lets you select your agent.

For a manual, project-local installation, clone the repository to a new directory and copy the **entire** `skills/handoff` directory into your host's skills directory. For example, Claude Code uses `.claude/skills/handoff/` within a project. Do not copy only `SKILL.md`: the references and helper script are part of the skill. If you already have a `handoff` skill installed, review it before replacing it.

Release archives are ZIP files containing a single `handoff/` skill directory, also available with a `.skill` extension. They contain the instructions, references, helper, and license; repository maintenance files are excluded.

Requires an agent with repository read/edit access, Git, and Python 3.9+ for the helper. No Python packages, API keys, network service, or background process are needed by the skill. The installer itself requires Node.js and network access.

## Use it

Ask your agent:

```text
Use handoff to audit HANDOFF.md and tell me what is actually unfinished.
```

```text
Use handoff. Finish the unassigned migration first, then add the dashboard.
```

```text
Use handoff to pause this task with the verification results and exact next action.
```

Invoke the skill explicitly through your host's skill picker when needed. Automatic selection depends on the host. Installing this skill does not install hooks or guarantee that every task uses it.

## What changes

| Situation | Handoff behavior |
| --- | --- |
| An old box is unchecked but later code implements it | Audit the evidence and annotate the resolution. |
| A new request arrives while work remains | Keep the new request queued; resolve ordering and ownership. |
| Another agent owns overlapping changes | Preserve that work and report the concrete conflict. |
| Verification fails | Keep the task open with failure evidence and the next action. |
| A session ends midway | Record the current state so the next agent can continue. |

The agent makes the semantic decisions. The Python helper checks ledger structure only; it cannot prove implementation, identify a live owner, or decide whether an old requirement is obsolete.

## The ledger

This is an illustrative entry, not a record of work in your repository:

```markdown
## YYYY-MM-DD - Add search (owner: actual agent name)

State:

- [x] In progress
- [ ] Completed

Steps:

- [x] Implement search filtering.
- [ ] Verify empty queries and no-result behavior.
- [ ] Record verification and the next action.

Status: In progress. Filtering exists; edge-case verification remains.
```

Completed tasks retain both state boxes checked. Earlier entries remain history. Detailed examples and formatting rules live in [the ledger contract](skills/handoff/references/ledger-contract.md).

## Helper commands

From this source checkout, replace `/absolute/path/to/repo` with the repository to inspect:

```sh
python3 skills/handoff/scripts/handoff_guard.py doctor --root /absolute/path/to/repo
python3 skills/handoff/scripts/handoff_guard.py validate --root /absolute/path/to/repo --json
python3 skills/handoff/scripts/handoff_guard.py template \
  --title "Add search" \
  --owner "Your agent name" \
  --step "Implement search filtering." \
  --step "Verify behavior and update the handoff."
```

`doctor` and `validate` currently run the same structural checks, with exit code 1 for a missing ledger or structural errors and 0 otherwise. Legacy sections are reported for manual review, not migrated automatically. An empty or legacy-only ledger can pass structural validation; this is not evidence of task completion. Instruction discovery lists root-level files only: the agent must also read applicable ancestor and nested instructions. `template` prints Markdown to stdout. `doctor`, `validate`, and `template` never edit the repository.

### Concurrent writers

Editing `HANDOFF.md` directly is fine for sequential handoffs and for separate worktrees, where git surfaces collisions. When several agents share one working tree, two of them can read the same ledger and the second write silently drops the first entry. `apply` is the compare-and-swap write that prevents it:

```sh
python3 skills/handoff/scripts/handoff_guard.py doctor --root /absolute/path/to/repo --json
# note the reported "version", then:
python3 skills/handoff/scripts/handoff_guard.py apply --root /absolute/path/to/repo \
  --expect-version 98caeaf3ffbe \
  --entry new-entry.md
```

`--entry` inserts one task entry at the newest position; `--content` replaces the whole ledger after editing existing entries. Both accept `-` for stdin, take a full hash or a prefix of at least 8 characters, and write through an atomic replace so no reader sees a partial ledger. `--dry-run` reports without writing.

Exit codes: `0` applied, `3` version conflict (another writer got there first), `4` the write would introduce structural errors and was not applied, `1` usage or missing ledger. On `3` the read behind the edit is stale, so the progressive audit is stale too — re-read, re-audit, and apply against the current version rather than retrying the same content.

## Development and releases

```sh
python3 -m unittest discover -s skills/handoff/tests -v
python3 -m unittest discover -s tests -v
python3 scripts/package_skill.py
```

The packager creates `dist/handoff.zip`, `dist/handoff.skill`, and `dist/SHA256SUMS`. CI runs helper and packaging tests on Python 3.9 and 3.12. Pushing a `v*` tag runs validation, checks that the tag matches the skill version, and publishes those artifacts to a GitHub release. See [CONTRIBUTING.md](CONTRIBUTING.md) for release steps.

The included [behavioral scenarios](skills/handoff/evals/evals.json) cover stale boxes, live ownership, and explicit task ordering. They are evaluation prompts, not a claim that automated model benchmarks have been run.

## Design and attribution

Built from Divij's handoff skill. Packaging and workflow presentation are inspired by [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill): a focused runtime skill, bundled helper commands, progressive references, and an installable public repository. No Last30Days code or research engine is included.

The skill is a coordination convention, not a lock manager. It respects repository instructions and user authorization; it does not grant permission to adopt another agent's work, commit unrelated changes, or publish anything.

[MIT licensed](LICENSE).
