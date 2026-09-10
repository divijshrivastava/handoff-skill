# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` holds the contributor conventions (style, commit and PR expectations); follow it as well. `CONTRIBUTING.md` holds the release procedure.

## What this repository is

The source repository for one agent skill. It is not a Python distribution, library, or service: nothing is installed, and no setup command runs when it is packaged. The shipped artifact is the `skills/handoff/` directory, published as a Claude Code plugin (via `.claude-plugin/`) and as ZIP/`.skill` archives on GitHub releases.

Everything outside `skills/handoff/` is build, test, and release machinery for that one directory. `scripts/` (root) is release tooling; `tests/` (root) tests that tooling; `skills/handoff/tests/` tests the shipped helper.

## Commands

Run from the repository root with Python 3.9+; no third-party packages.

```sh
python3 -m unittest discover -s skills/handoff/tests -v     # shipped helper
python3 -m unittest discover -s tests -v                    # packaging + eval summary
python3 -m unittest discover -s skills/handoff/tests -k test_apply -v   # one test or pattern
python3 scripts/check_versions.py                           # version triple must agree
python3 skills/handoff/scripts/handoff_guard.py validate --root .
python3 scripts/package_skill.py                            # writes dist/ (gitignored)
git diff --check
```

CI (`.github/workflows/ci.yml`) runs exactly those on Python 3.9 and 3.12, so run all of them before claiming a change is done.

## Architecture

### Two layers with a deliberate split of authority

`skills/handoff/SKILL.md` is the runtime source of truth: a prose contract telling the agent how to audit a progressive ledger. `skills/handoff/scripts/handoff_guard.py` is a dependency-free CLI that checks ledger **structure** only. The split is load-bearing — the helper cannot prove implementation, identify a live owner, or judge whether an old requirement is obsolete, and a passing `validate` is never evidence that a task is finished. Do not move semantic judgment into the helper or structural rules into prose.

`references/` carries conditional detail (`ledger-contract.md` is the ledger format spec, read before any ledger edit; `design-notes.md` is lineage). Keep `SKILL.md` the entry point and push detail into references.

### Helper command surface

`doctor`, `validate`, `read`, and `template` never write; `apply` and `purge` are the writing subcommands. `read` returns ledger text *and* its version hash from a single snapshot, because two separate reads bind an audit of old text to a newer version and lose a peer's entry.

`swap_ledger` is the one compare-and-swap, and every writer goes through it: `apply` and `purge` on the guard CLI, the channel's voluntary `yield`, and the viewer's task move. The payload is read first (so blocking stdin cannot stall peers), then an exclusive lock on the `HANDOFF.md.lock` sidecar wraps re-read, version check, and atomic replace. The hash check alone is not a CAS — without the lock two writers can both pass against the same revision. The lock lives in a sidecar rather than the ledger because `os.replace` swaps the ledger's inode. `atomic_write` restores the original file mode so collaborator access survives. Any change here must keep read, check, and replace inside one held lock, and a write path must not grow beside it. `purge` archives the replaced bytes inside that lock, writes an empty valid ledger in place, and refuses to create `HANDOFF.md` where none exists.

The viewer (`handoff_tui.py`) is otherwise a reader. Its one edit is reassigning a task's owner: `reassign_task` rewrites that heading's label and appends a dated note to the task's status, identifying the entry by line *and* heading so a stale position raises instead of editing its neighbour. It never moves an entry — ledger order records when work was raised, the label records who holds it. `--read-only` disables the keys.

Exit codes: `0` applied, `3` version conflict (the audit behind the edit is stale — re-audit, do not retry), `4` write would introduce structural errors, `1` usage or missing ledger.

### Two invariants CI enforces

**Version triple.** The version string appears in `skills/handoff/SKILL.md` (`metadata.version`), `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/plugin.json`, and `.cursor-plugin/marketplace.json`. `check_versions.py` fails on any drift, and on a release tag that is not `v<version>`. A version that does not change is never offered as an update to installed copies, so bump all five together.

**Packaging allowlist.** `RUNTIME_FILES` in `scripts/package_skill.py` explicitly lists what ships. Adding a runtime resource to the skill means adding it there and to `tests/test_package.py`, or it silently will not reach users. Archives are byte-reproducible (`ZIP_STORED`, fixed timestamps, fixed modes); do not introduce nondeterminism.

### The repository uses its own skill

`HANDOFF.md` here is a live ledger of work on this repository, and `validate --root .` runs in CI against it — ledger edits must stay structurally valid. When picking up work here, audit it per `SKILL.md` rather than treating unchecked boxes as pending.

### Evals

`skills/handoff/evals/evals.json` holds behavioral scenarios (prompts, fixtures, and graded expectations), not results. `scripts/run_evals.py` executes them against a harness CLI and writes the `eval-*/<config>/run-*` layout that `scripts/summarize_evals.py` consumes; the summarizer is unchanged by it, still raises on incomplete grading, and still reports missing token counts as `unknown` rather than estimating. Never report these scenarios as passing model evaluations unless they were actually run and graded.

The runner grades in two lanes. The deterministic lane needs no model: it matches command fragments in the response and checks the fixture repository, which is what makes a non-trigger testable — a scenario seeded with no ledger fails if a `HANDOFF.md` appeared. The judge lane is optional, blinded, and must return a verdict with evidence for every expectation; a run it cannot grade stays ungraded and the summarizer refuses the workspace. `eval_metadata.json` lists only what an invocation actually graded, so a judge-less run claims nothing about the prose expectations.

Each run gets a temporary `HOME` and a fixture repository outside this checkout. That is context isolation, not a security boundary, and it is a property of the harness's lookup rules rather than of the script: verify it with `--canary` before trusting a result. `without_skill` is a first-class configuration and a baseline, not a product failure. Model calls cost money and are not reproducible, so the runner is invoked by hand; CI runs only the graders, the schema validation, and the `SUITE_SIZE` assertion in `tests/test_evals.py`. Nothing under C ships: the runner is not in `RUNTIME_FILES`. `skills/handoff/evals/README.md` is the maintainer document.

## Working style for changes here

Before changing the workflow or helper, name the concrete failure case it fixes; add a regression test starting from that case. Keep helper code standard-library-only and Python 3.9 compatible (`from __future__ import annotations` for modern type syntax).

## Agent channel

`skills/handoff/scripts/handoff_channel.py` keeps a durable local inbox and explicit capability reports in gitignored `.handoff/`. Root `hooks/hooks.json` supplies Claude Code session registration, failure reporting, and inbox delivery. A StopFailure hook can report an unavailable model while its CLI remains open; it does not itself authorize takeover or prove child writers stopped. Exhaustion is handled by construction rather than detection: an owner declares a renewal deadline with guard `lease`, any peer releases what expired with `sweep`, and channel `challenge`/`attest` bind a capability proof to a nonce. Host hooks only write those records earlier; they never decide, because a verdict has to be computable on every harness from the ledger, the channel, and the clock. See `skills/handoff/references/agent-channel.md` for the workflow. All ownership changes still pass through `swap_ledger`.
