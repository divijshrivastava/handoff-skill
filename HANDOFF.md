# Handoff

## 2026-09-07 - Add demo recording assets for the README GIF (owner: Claude session divij-demo)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add the fixture builder (scripts/demo/make-fixture.sh).
- [x] Add the recording shot list and export pipeline (scripts/demo/RECORDING.md).
- [x] Add the VHS tape alternative (scripts/demo/demo.tape).
- [x] Verify the fixture builds, validates, and its tests pass.
- [x] Commit and record verification.

Status: Complete. Assets added under `scripts/demo/`: `make-fixture.sh` builds a two-commit fixture at /tmp/handoff-demo whose ledger leaves `Verify empty queries and no-result behavior.` unchecked while the second commit implements it and adds `test_search.py`, so a recorded audit has real evidence to find rather than a staged result; `RECORDING.md` carries the five-beat shot list, terminal settings, and the asciinema/agg/gifsicle pipeline; `demo.tape` is the VHS alternative. No runtime skill files, packaging, or CI change. Verified: the fixture builds from the committed copy, its three tests pass, and `validate --root /tmp/handoff-demo` exits 0; in this repository 25 helper tests and 5 packaging tests pass on Python 3.9, `validate --root .` passes, `package_skill.py` builds, and `git diff --check` is clean. Recording tools (asciinema, agg, gifsicle, vhs) are not installed on this machine, so no GIF was produced and none is claimed. Separately observed, not changed: a stale manual copy of this skill at `~/.claude/skills/handoff/` reports version 1.1.0 and lacks the `read` and `apply` commands, while the plugin cache holds 1.2.2 — the ambiguity README.md warns about, reproduced on the author's own machine. Committed in `3da7246` on `main`; not pushed. No GIF exists yet: recording it needs the tools above installed and one real session against the fixture.

## 2026-09-07 - Distribute as a Claude Code plugin marketplace (owner: Claude session divij-f8)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add the plugin and marketplace manifests (.claude-plugin/plugin.json, .claude-plugin/marketplace.json).
- [x] Assert one version across the skill, plugin, and marketplace manifests (scripts/check_versions.py).
- [x] Run that check in CI and replace the release workflow's single-file tag assertion.
- [x] Document the plugin install and update path, and the stale-copy conflict (README.md).
- [x] Verify installation end to end and record what the plugin actually ships.
- [x] Commit and record verification.

Status: Complete. Installed and uninstalled locally to verify rather than trusting the manifest: `claude plugin validate .` passes, the plugin installs as `handoff@divij-skills` version 1.2.2, enabled, and the helper runs from the installed copy at `~/.claude/plugins/cache/divij-skills/handoff/1.2.2/skills/handoff/`. Updates key off the version string, so `scripts/check_versions.py` fails CI when the three manifests disagree; drift was confirmed to exit 1. Known trade-off: `source: "./"` makes the plugin root the repository root, so an install copies the whole repository (416K locally) including `README.md`, `CONTRIBUTING.md`, `tests/`, `.github/`, and this ledger, rather than the allowlisted bundle `scripts/package_skill.py` builds. Git-sourced installs exclude gitignored paths such as `dist/` and `HANDOFF.md.lock`. Narrowing this would require moving `skills/handoff/` under a `plugins/handoff/` root and updating every path in CI, packaging, and documentation; it was not done. Verified on Python 3.9 and 3.14: 25 helper tests and 5 packaging tests pass, validate passes, the archive builds.

## 2026-09-07 - Fix compare-and-swap race and recheck findings from external review (owner: Claude session divij-f8)

State:

- [x] In progress
- [ ] Completed

Steps:

- [x] Serialize apply's read, version check, and replacement under an exclusive lock (skills/handoff/scripts/handoff_guard.py).
- [x] Read the payload before taking the lock so blocking input cannot stall peers.
- [x] Preserve the ledger's file mode across the atomic replace.
- [x] Add a read command binding audited text to its version in one snapshot.
- [x] Reject duplicate and contradictory task-level state checkboxes.
- [x] Add an overlapping-writer regression test and confirm it fails without the fix.
- [x] Correct the SKILL.md, README.md, and CONTRIBUTING.md claims about the guarantee.
- [x] Close the recheck findings: lock-requiring regression test and crash-safe fallback.
- [ ] Commit, publish 1.2.2, and record verification.

Status: In progress. An external review of `781441f` reported that the 1.2.0 compare-and-swap was not atomic. Reproduced with two unmodified CLI processes: writer A parked reading a FIFO payload after its version check while writer B completed; both returned `applied` and exit 0 and A's replace discarded B's entry. The hash comparison was a check-then-act, not a compare-and-swap, because nothing serialized the sequence. `apply` now holds an exclusive lock on a `HANDOFF.md.lock` sidecar across the re-read, check, and replacement, and the same reproduction now returns exit 3 for A with both entries preserved after retry. The new regression test was confirmed to fail against `781441f`. Also fixed from the same review: `atomic_write` reset the ledger from 0644 to 0600 via `mkstemp`; `checkbox_value` returned the first match so contradictory duplicate state boxes validated clean; the documented preflight read the ledger and the version separately, which could bind an audit to a version it never saw; and `CONTRIBUTING.md` still called the helper read-only. Verified on Python 3.9 and 3.14: 24 helper tests and 5 packaging tests pass, validate passes, the archive builds. A recheck of `fa1d0f0` confirmed the three original findings fixed and raised two more, both reproduced here. First, the overlapping-writer test parked writer A while it read its payload, which now happens before the ledger read, so the test passed with `ledger_lock` removed and did not guard the serialization at all; a second test now parks A inside `atomic_write`, past the version check and holding the lock, and it fails when the lock is removed while the original test still passes. Second, the no-fcntl fallback acquired an exclusive-create lock file removed only in `finally`, so a writer killed mid-write stranded every later writer past the timeout; the fallback is now `msvcrt` on Windows and the command refuses to write at all when no OS lock primitive exists, since both real primitives are released by the OS on process death. Verified by killing a lock holder with `os._exit` inside the critical section: the next writer proceeded in 0s rather than timing out. Verified on Python 3.9 and 3.14: 25 helper tests and 5 packaging tests pass, validate passes, the archive builds. Next action is to commit and publish 1.2.2. The four scenario evaluations are unchanged and were not re-run; the earlier model scores must not be presented as 1.2.1 or 1.2.2 benchmark results.

## 2026-09-07 - Add compare-and-swap ledger writes (owner: Claude session divij-f8)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add version reporting and the apply compare-and-swap write (skills/handoff/scripts/handoff_guard.py).
- [x] Cover conflict, rejection, and atomic-write behavior with tests (skills/handoff/tests/test_handoff_guard.py).
- [x] Document the concurrent-write flow (skills/handoff/SKILL.md, README.md).
- [x] Run both suites, validate, and package.
- [x] Commit and record verification.

Status: Complete. `doctor` and `validate` now report a ledger `version`; `apply` performs a compare-and-swap write gated on it, inserting an entry with `--entry` or replacing the ledger with `--content`, through an atomic replace. Exit codes: 0 applied, 3 version conflict, 4 would introduce structural errors, 1 usage or missing ledger. 19 helper tests and 5 packaging tests pass on Python 3.9 and 3.14; `validate --root .` and `package_skill.py` succeed and `git diff --check` is clean. Committed together with the Codex task below at the user's direction, because `skills/handoff/SKILL.md` and `skills/handoff/scripts/handoff_guard.py` carry both tasks' changes and no commit could contain only one task's work. Verified on Python 3.9 and 3.14; committed in `0ba13d9` on branch `handoff-cas-and-guidance`.

## 2026-09-07 - Refine handoff guidance, verify behavior, and release (owner: Claude session divij-f8)

State:

- [x] In progress
- [ ] Completed

Steps:

- [x] Apply conditional ordering, grounded planning, and concise output guidance.
- [ ] Review helper and packaging behavior; expand and run behavioral evaluations.
- [ ] Correct benchmark reporting and verify the final release archive.
- [ ] Commit, publish the versioned release, and record verification.

Status: In progress. The prior publication task is complete and the starting tree is clean at `559edee`. Applying the five requested review changes. Failure cases: the unconditional pickup gate can block a new task with no unfinished work; the output rules prohibit creating new steps; saved evaluations repeat procedure and assume a list/table UI. Review also covers helper and archive behavior before a versioned release. Shell access to GitHub currently fails DNS resolution; publication access will be checked after preparing the release. Originally owned by Codex; Claude session divij-f8 took over the remaining steps 2-4 on 2026-09-07 at the user's explicit direction. Codex's liveness was never confirmed either way, so this is an authorized takeover, not an inactivity finding. Codex's uncommitted work was reviewed and retained unmodified: the CommonMark fence masking in `outside_fence_lines` now applies to all parsing rather than headings only (4 tests), evaluation 4 and `output_quality_expectations` were added to `skills/handoff/evals/evals.json`, and `scripts/summarize_evals.py` with `tests/test_evals.py` report benchmarks without estimating missing metrics. Step 2 is partially complete: evaluation content is expanded, but the only saved runs are in `~/code/handoff-skill-workspace/iteration-3`, contain no `grading.json`, and were produced against the `skill-snapshot-v1.1.0` copy, so they predate both this task's SKILL.md changes and the compare-and-swap task. Step 3 is split: the reporting code is correct and tested, but `scripts/summarize_evals.py` raises `FileNotFoundError` on those ungraded runs, so no benchmark exists; the release archive half is verified, building byte-identical twice (`1b7379e7836bed51297770b74289fa3d74d618034955fce12f15d7feec83741a`) and extracting to a working helper at version 1.2.0. Step 4 is partially complete: the work is committed in `0ba13d9` on branch `handoff-cas-and-guidance`, which is not yet merged to `main`, and no version tag or GitHub release was created and publication was not attempted. Next action is to re-run the four evaluations against the current skill, grade them, then generate the benchmark and decide on publication.

## 2026-09-07 - Package and publish handoff skill (owner: Codex)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Package the supplied skill and its supporting resources in `skills/handoff/`.
- [x] Add public documentation, license, CI, and a reproducible release archive.
- [x] Verify helper behavior and package contents.
- [x] Commit and publish the new GitHub repository; record the result.

Status: Complete. Published commit `143adaf` to https://github.com/divijshrivastava/handoff-skill (public, main). Five helper tests and two packaging tests pass locally and in GitHub CI on Python 3.9 and 3.12 (run 34070412714). The skill-creator validator passes using an isolated PyYAML environment. Both archives build reproducibly and the extracted helper runs. The public installer lists exactly one skill, `handoff`. No installed skills were replaced. Release automation is ready; no version tag or GitHub release was requested or created. No remaining implementation work.
