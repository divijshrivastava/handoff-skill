# Handoff

## 2026-09-10 - Treat viewer task assignments as queued execution requests (owner: Fenrir) (harness: Codex)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Update the runtime protocol and repository guidance so viewer assignments must run after the current task without another prompt.
- [x] Put the execution directive in viewer reassignment notes and add regression and behavioral coverage.
- [x] Verify and publish the protocol changes to origin/main.
- [x] Continue directly with the channel-view task already assigned to Fenrir.

Status: In progress. Concrete failure: the user assigned the channel-view task to Fenrir through the viewer, but Fenrir merely reported it pending and waited for another prompt after finishing Task B. The user now explicitly requires every agent to finish its current task, then audit and execute viewer-assigned work through verification. Implement and publish that protocol now, then continue the existing channel-view assignment. Garuda owns the nudge implementation and Epona owns cloud publishing; their work is preserved.


Verified 2026-09-10: the move-note regression failed before implementation and passes after it. The exact staged publication tree passes 270 helper tests and 54 repository tests on Python 3.9.10, version and manifest checks, packaging, and whitespace checks. Two behavioral scenarios were added (16 total); model evaluations were not run. The shared tree separately passes 311 helper tests with peers' work present. Publication is next, then immediate continuation of the existing channel-view assignment.


Complete 2026-09-10: protocol commit e0fd1d0 was pushed to origin/main successfully. Fenrir is continuing the assigned channel-view task immediately under the new rule.

## 2026-09-10 - Publish handoff state to a VPS for twin agents (owner: Epona) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Settle whether a VPS twin observes its slice or continues the work, because the second needs ownership transfer across machines.
- [x] Define the per-owner slice: the entries that owner holds, its sent and received messages, and its reported state.
- [x] Add the capture with the ledger-version re-check, composing Fenrir's Channel.history and Garuda's Channel.silence rather than a third query.
- [x] Add the SSH publish to a configured VPS path, writing the whole snapshot, the ledger text, and one file per owner.
- [x] Add the user-written agent map (local owner and harness to VPS agent) and refuse to publish an owner it does not name.
- [x] Redact home directory paths from message bodies before they leave the machine.
- [x] Reconcile the README no-external-service claim with what ships.
- [x] Add tests and run the full CI set; record verification and the handoff.

Status: Complete, uncommitted. The user chose a simple hosted VPS with agents configured beforehand, and observe-only twins. `skills/handoff/scripts/handoff_publish.py` captures the ledger and channel, slices by owner, and sends the tree over `ssh` to a path named in gitignored `.handoff/vps.json`. Each configured agent gets `agents/<twin>.json` holding the entries that owner holds, the messages it sent or received, its broadcast traffic, and its last reported state; `ledger.md` and `snapshot.json` carry the whole picture so an unmapped owner's work still arrives. Twins observe: nothing flows back, because `swap_ledger`'s compare-and-swap does not hold across a network and two machines would both pass the version check against one revision.

Four properties the tests start from, each a concrete failure. Capture re-reads the ledger version after reading the channel and retries, because reading two independently written stores in sequence otherwise publishes a state that never existed; under steady concurrent writes it fails rather than publishing a blend. Home directories are rewritten to `/Users/<user>` before anything is written out, including a local `snapshot`, since the user chose to include message bodies and those carry absolute paths. A harness mismatch is reported, so a Codex twin is not handed work the ledger records as Claude Code. The remote unpacks into a staging directory and swaps it in one move, so a twin reading mid-publish sees one state or the other rather than half of each. A twin name containing a path separator is refused.

Deliberately not built: any write path back from the VPS, and any liveness claim. A slice carries `reported_at` and `report_age_seconds` and never "online". `references/vps-publish.md` documents the setup, the commands, and what the feature is not, and `README.md`'s requirements line now says the local claim plainly and points at the one opt-in feature that leaves the machine.

Verification: 20 new tests in `skills/handoff/tests/test_handoff_publish.py` pass on Python 3.9.10 and 3.12.7, as do 54 root tests, `check_versions.py` (1.22.0 across 6 manifests), `sync_manifests.py --check`, `validate --root .`, `package_skill.py`, and `git diff --check`. The new script and reference are in `RUNTIME_FILES` and asserted in `tests/test_package.py`, so they reach users. Exercised live in this checkout: `check`, and `snapshot --out`, which produced the three agent files with 15 messages, zero home-path leaks, and six redaction markers.

Two helper tests fail in this tree and are not from this task: `test_handoff_bar.ViewerResolutionTests.test_old_copy_without_bar_is_skipped` and `test_a_stale_remembered_viewer_is_replaced`, caused by the module-level `from handoff_channel import Channel` that Fenrir's in-flight `handoff_tui.py` adds, which stops a planted or cached viewer copy starting without that module beside it. Reported to Fenrir with a reproduction; their file, their fix.

Next action for whoever picks this up: nothing is committed, and `Channel.history` and the viewer work it depends on are also uncommitted, so a commit of this task should follow theirs.

## 2026-09-10 - Show the agent channel in the handoff viewer (owner: Epona) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add a read-only channel query to handoff_channel.py returning sender, recipient, time, acknowledgement, and body for the repository's messages.
- [x] Add a channel view to handoff_tui.py showing who messaged whom and what, with the existing refresh and key conventions.
- [x] Document the view and its counting rules in references/progress-viewer.md.
- [x] Add tests covering rendering, an empty channel, and a broadcast recipient.
- [x] Run the full CI set and record verification and the handoff.

Status: Complete, uncommitted. This entry reached Epona through the viewer, unassigned to Fenrir to Epona, and was audited before being resumed rather than treated as explained by its arrival. Most of it was already built by Fenrir before the move and that work stands: `Channel.history` returns sessions, messages newest first with sender and recipient owners and acknowledging sessions, and a truncation flag, reading through a read-only transaction that neither migrates the schema nor mutates acknowledgements; the viewer gained `c` to open the channel, `s` to toggle sessions and messages, Enter to filter a session's conversation and open one message, and a selection that survives refresh.

What Epona added was the defect that work introduced. `handoff_tui.py` imported `handoff_channel` at module scope, so a viewer copy installed without that module beside it raised at startup: two `test_handoff_bar.ViewerResolutionTests` cases failed, and Garuda confirmed the cause independently by swapping only that file for the HEAD version. It mattered past the fixture, because `handoff-bar` resolves a viewer out of plugin caches and runs on every status-line tick, so a viewer that cannot start prints nothing at all and the bar silently loses its progress line. The import is now guarded and the channel is constructed only when the module is present; the one view reports itself unavailable while task progress, agents, and moves keep working, which matches how `history` already treats an absent channel.

Verification: 343 helper tests and 54 root tests pass on Python 3.9.10 and 3.12.7, including three new `ChannelAbsentTests` that start from the failure - the dashboard builds with no channel, the channel view refreshes empty instead of raising, and task progress still reports. The two bar tests pass again. Also run: check_versions (1.22.0 across 6 manifests), sync_manifests --check, validate --root ., package_skill, and git diff --check. Reproduced by hand both ways: a viewer planted beside only handoff_guard.py exited 1 on import before the fix and now prints its progress line and exits 0.

Garuda's nudge key is the coordinated follow-up and remains Garuda's; nothing here claims it.

## 2026-09-10 - Nudge an unresponsive agent from the channel view (owner: Garuda) (harness: Claude Code)

State:

- [x] In progress
- [ ] Completed

Steps:

- [x] Define non-response from evidence the channel already holds: unacknowledged messages plus report age. Record what it cannot establish.
- [x] Add a nudge write to handoff_channel.py that is a message, not a capability verdict, with a repeat interval so nudging cannot be spammed.
- [ ] Add the key to the channel view in handoff_tui.py, disabled under --read-only.
- [x] Document that a nudge and its silence prove nothing about availability or takeover authority.
- [ ] Add tests for the interval, the read-only refusal, and an unanswered nudge leaving state unknown.
- [ ] Run the full CI set and record verification and the handoff.

Status: In progress. The channel half is built, tested and documented; one step is blocked on another owner's task and one test in step 5 belongs to it.

Done. `silence_record` in handoff_channel.py defines non-response from what the channel and the clock already hold: unacknowledged messages addressed to a peer, the age of the oldest, its report age, its freshness label, its open challenges and last attestation, and when it was last nudged. `silent` requires both an unanswered message past a two-minute grace period and a report past its freshness window, because a message that arrived a moment ago is not silence - the peer may not have taken a turn since. `silent` describes the record and not the peer: it cannot distinguish an exhausted agent from an idle healthy one, and it is not a takeover timer. `nudge` publishes a message of kind `nudge` asking for an inbox read, an acknowledgement and a report, or a `yield`; it refuses broadcast and self, and a second nudge from the same session to the same peer inside ten minutes returns the first rather than burying the inbox, per sender and subject so two waiters never silence each other. It touches no ledger, no ownership and not even the subject's reported state, and its return says so. No schema change was needed: nudges ride the existing messages table, so a channel created before this version works unmigrated, which a test asserts. `silence` is the read-only companion, exposing the row fields Fenrir's channel view asked for. 14 tests in `NudgeTests` in skills/handoff/tests/test_handoff_channel.py cover the interval and its expiry, the refusals, an unanswered nudge leaving availability unknown, acknowledgement ending silence without refreshing capability, the untouched ledger, and the CLI. Documented in references/agent-channel.md as a section that decides nothing, and in SKILL.md and CLAUDE.md.

Blocked, deliberately. Step 3 wants the key on the channel view in handoff_tui.py, and no channel view exists: Fenrir owns that task and replied on the channel that they have not started or edited handoff_tui.py and asked that this task stay on the channel-side half. So handoff_tui.py is untouched by this session, and the read-only refusal test in step 5 waits with it - there is no key yet to refuse. Fenrir will coordinate the shared read query with `silence_record` and Epona's proposed snapshot helper before building the view.

Verified so far on Python 3.9.10 and 3.12.7: 305 helper tests (14 new) and 54 root tests pass, check_versions.py at 1.22.0 across 6 manifests, sync_manifests.py --check, validate --root ., package_skill.py, and git diff --check clean. Used in anger once: `silence` on this repository's live channel reports five sessions silent with reports 6 to 14 hours old and broadcast messages unread for four and a half hours, and Rangda was nudged with a question about who commits handoff_channel.py, whose lease/sweep work is still uncommitted in the same file this task edited. Nothing here is committed.

Original claim: In progress under Garuda on Claude Code, claimed after the view task above acquired an owner, as this entry required. Coordination on the channel: Fenrir owns 'Show the agent channel in the handoff viewer' and its last report is 4.5 hours old, so whether that session is live is unknown and its view does not exist yet. This task therefore starts on the half that shares no file with it - the non-response definition, the nudge write in handoff_channel.py, its tests, and the documentation - and holds the handoff_tui.py key until Fenrir's channel view lands or Fenrir says they have not started it. Nothing here is a capability verdict: a nudge is a message, and an unanswered nudge leaves availability unknown.

Original brief: Pending and unclaimed, offered to any session. Raised by the user as an option inside the channel view above, so it depends on that task's structure and both touch handoff_tui.py and handoff_channel.py. Two sessions must not hold these at once: claim this only after the view task has an owner, and coordinate on the channel. The design constraint is already settled by the skill: silence is not evidence, so a nudge is a message and never a capability verdict or takeover authority. Whoever claims this writes its own name and harness into the heading before starting.
Reassigned 2026-09-10: moved from unassigned to Garuda in the handoff viewer at
the user's direction. No state or step boxes were changed, and the entry keeps
its place in ledger order.

## 2026-09-10 - Commit and push Task B (owner: Fenrir) (harness: Codex)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Prepare an isolated commit containing Task B, the requested README explanation, and its handoff history.
- [x] Verify the exact commit contents and push to origin/main.
- [x] Record the commit and remote result in the handoff.

Status: In progress. The user requested push after Task B. Task A is complete but uncommitted under Epona; Task C remains active under Garuda. Preserve their files and ledger entries. Prepare Task B from committed main plus its specific changes in an isolated checkout, because this shared tree carries unrelated work and its .git is read-only in this session.

Status: Blocked on publication. The user also requested that explanations go into README.md. Added a concise explanation of the always-visible command sequence, re-auditing on exit 3, tests and host limits, plus the name command in the safe-update example. Prepared commit c802848f714ef55fdbe5762fea68815ca2bfa391 in /private/tmp/handoff-task-b-push-9agfd6vy on the verified remote base b845b09; its only changed paths are CONTRIBUTING.md, HANDOFF.md (Task B entry only), README.md (Task B explanation only), skills/handoff/SKILL.md (description only), and tests/test_package.py. The prepared checkout is clean, and /tmp/handoff-task-b.bundle plus /tmp/handoff-task-b.patch preserve the commit. Its origin is https://github.com/divijshrivastava/handoff-skill.git.

Verification of the isolated publication tree: 8 root tests pass; versions agree at 1.21.0; packaging, ledger validation, and git diff --check pass. The 264 unchanged helper tests ran with the same two pre-existing tmux integration failures (262 pass), previously reproduced on unchanged HEAD. No unrelated 1.22.0 work or Task A/C source changes enter this commit. Epona created local commit f10f92f while this task was being prepared; the shared branch and its index were not changed by this task.

Publication failed: shell Git cannot resolve github.com. The connected GitHub read tool verified remote main at b845b09, but create_tree was rejected with "MCP tool call requires approval, but approval policy is never". No remote object or branch was changed by this session. The session cannot request the required approval. Next action: from an authorized shell, run git -C /private/tmp/handoff-task-b-push-9agfd6vy push origin main after checking the current remote; if it advanced, rebase this prepared commit onto it before pushing, without force. Reconcile the shared branch with the resulting remote while preserving the other owners' work. Garuda now records Task C complete; it remains separate.

Retry 2026-09-10 at the user's explicit direction: git push origin HEAD:main from the clean prepared checkout failed with exit 128, "Could not resolve host: github.com". The connected GitHub read again confirmed remote main at b845b09. Retrying the prepared create_tree request was again rejected because approval is required and the session's approval policy is never. Commit c802848 remains ready in the isolated checkout and verified bundle; no remote write occurred. Publication remains blocked on access, not on user authorization or unfinished implementation.

Status: In progress again. The session now has filesystem and network access. At the user's request, replied to Epona's ping confirming that Fenrir retains the push and will rebase the prepared commit onto origin/main, preserving Task A and Task C, then verify and push without force. Epona has not been asked to take over.

Status: Complete. With access enabled, rebased c802848 onto origin/main at 24fba89, preserving Task A f10f92f and Task C 24fba89. The only conflict was both tasks inserting ledger entries at the top; preserved both complete entries through guard read/apply. The resulting Task B commit is 2a1680a843cf6551151489ce33a37cbb6fa54167. Pushed without force and verified refs/heads/main at that exact SHA with git ls-remote. It contains the Task B description, regression tests, maintainer notes, README explanation and name-command example, and Task B ledger history; unrelated working-tree changes remain with their owners.

Final verification of the rebased tree on Python 3.9.10: all 54 root tests and 264 helper tests pass, including both tmux integration tests that failed under the previous restricted environment. check_versions.py reports 1.21.0 consistently; sync_manifests.py --check, package_skill.py, guard validate, and git diff --check pass. No tag, release, or model evaluation was run. Replied to Epona confirming ownership and the plan; publication is now achieved and no permission blocker remains.

## 2026-09-10 - Build an evaluation runner (Task C) (owner: Garuda) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Extend the evals.json schema with kind, ledger, required, forbidden, and rubric, and add the three negative scenarios.
- [x] Add scripts/run_evals.py with isolated fixtures, --list, --dry-run, config matrix, deterministic grader, optional blinded judge, and --canary.
- [x] Add tests/test_evals.py grader and schema regression tests starting from the direct-edit and false-trigger failures.
- [x] Write the maintainer document covering isolation limits, grading honesty, and the ablation baseline.
- [x] Run the full CI set and record verification and the handoff.

Status: Complete. `scripts/run_evals.py` runs each scenario in a fixture repository created outside this checkout under a temporary HOME, and writes the `eval-*/<config>/run-*` layout `summarize_evals.py` already consumes; the summarizer is untouched. Two lanes grade: a deterministic one that matches command fragments as ordered tokens within one command line (so `apply --root . --expect-version V` satisfies `apply --expect-version`) and checks the fixture repository, and an optional blinded judge that must return evidence for every expectation or the run stays ungraded. `eval_metadata.json` lists only what an invocation graded, so a judge-less run claims nothing about the prose expectations. The suite is 14 scenarios: the 11 existing ones gained fixtures and fragments, and 12, 13, and 14 cover the non-triggers the description spends its words on - a read-only question with no ledger, two agents in a tree with no ledger, and an explicit /handoff:status against one. A seeded-no-ledger scenario fails deterministically if a HANDOFF.md appeared, which is what made a non-trigger testable at all. `skills/handoff/evals/README.md` is the maintainer document and records that isolation is context isolation and not a security boundary, that judge scores are evidence and not ground truth, that a small score movement without repetitions is not a regression, and that missing token counts stay unknown. Verified on Python 3.9.10 and 3.12.7: check_versions.py, sync_manifests.py --check, both unittest suites (291 helper, 54 root), guard validate --root ., package_skill.py, and git diff --check all pass; --list, --dry-run, a full 14-scenario two-configuration matrix, and --canary in both directions were exercised against stand-in CLIs, which are not model results and are not reported as evaluations. No model has been run against this suite. Committed as 24fba89 and pushed to origin/main, which also published Epona's f10f92f ahead of it; the remote moved from b845b09 to 24fba89. Staging used git hash-object and update-index to commit file contents rather than whole working-tree files, because CLAUDE.md and CONTRIBUTING.md also carry Rangda's and Fenrir's uncommitted lines: the commit holds this task's Evals paragraph and behavioral-scenarios sentence only, and HANDOFF.md at that commit carries this entry alone. Their working-tree lines are untouched and still theirs to commit, and the CLAUDE.md gap Epona flagged is now closed for the Evals section but still open for the manifest rule. The exact committed tree was verified before pushing on Python 3.9.10 and 3.12.7: 52 root tests, 264 helper tests, check_versions.py at 1.21.0 across 5 manifests, sync_manifests.py --check, validate --root ., package_skill.py, and git diff --check.

## 2026-09-10 - Generate the plugin manifests and discover them by glob (owner: Epona) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add scripts/sync_manifests.py generating every known *-plugin manifest from the SKILL.md frontmatter and one host table.
- [x] Rewrite scripts/check_versions.py to discover *-plugin/ directories by glob so a new host cannot be missed.
- [x] Add tests/test_manifests.py starting from the stale untracked .kimi-plugin case.
- [x] Regenerate the manifests so the drifted copy matches, leaving tracked manifests byte-identical.
- [x] Run sync_manifests.py --check in CI and record the decision in CLAUDE.md.
- [x] Verify the full CI set and record the handoff.

Status: Complete. The version is written by hand in one place, `skills/handoff/SKILL.md`, and `scripts/sync_manifests.py` generates every manifest under `*-plugin/` from it plus one host table. `scripts/check_versions.py` now discovers manifests by globbing `*-plugin/` instead of naming four paths, which is why the drift was invisible: `.kimi-plugin/plugin.json` sat at 1.17.0 through five releases with CI green, and Rangda's step recording a bump across "the five manifests" counted the five the old check knew. The glob now reports six.

Two boundaries are deliberate. A host directory absent from disk is never created, because whether a host is supported is a decision rather than a side effect; a host present but absent from the generator's `HOSTS` table is checked and reported but never written, because no verified shape for it exists and inventing one ships a broken manifest. Per the user's choice, `.kimi-plugin/` stays untracked, so CI sees two hosts and the local copy stays consistent.

Only the version is taken from the skill. The listing description is a constant in the generator, so Fenrir's Task B rewrite of the model-visible description cannot reach a storefront. That preserves the decision Fenrir recorded in CONTRIBUTING.md.

Verification: the full CI set passed on Python 3.9.10 and 3.12.7 - check_versions (1.22.0 across 6 manifests), the new `sync_manifests.py --check`, 291 helper tests, 19 root tests (8 new in `tests/test_manifests.py`), `validate --root .` exit 0, package_skill, and `git diff --check` clean. The failure was reproduced live before the fix: the rewritten check exited 1 listing `.kimi-plugin/plugin.json` at 1.17.0 against five at 1.22.0. The generator reproduces all four tracked manifests byte-for-byte, so its first run rewrote exactly one file, the drifted one; a test asserts that byte identity so a later formatting change cannot quietly rewrite the tracked manifests. Nothing ships: the generator is root tooling and is not in `RUNTIME_FILES`.

Also updated: `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` release step 1, and the README version sentence. Nothing is committed. `CONTRIBUTING.md` is edited by Fenrir in parallel; my change is confined to release step 1 and their Task B paragraphs are intact.

Commit: f10f92f on main, not pushed. At the user's direction only files with no other
owner's changes in them were staged: `scripts/sync_manifests.py`,
`scripts/check_versions.py`, `tests/test_manifests.py`, `.github/workflows/ci.yml`, and
`AGENTS.md`. The doc updates in `CLAUDE.md`, `CONTRIBUTING.md` release step 1, and the
README version sentence are correct in the working tree but stayed uncommitted, because
those three files also carry Rangda's and Fenrir's completed work and git stages whole
files. Known gap for whoever commits them next: at f10f92f the committed `CLAUDE.md`
still describes the superseded five-manifest rule while the committed code generates
the manifests. Garuda's in-flight Task C files and the untracked `.kimi-plugin/` were
not staged. Committed to `main` rather than a branch because two peers are working this
same tree on `main` and switching HEAD would move it under them; every release in this
ledger landed on `main`.

Verified against the CI scenario the untracked decision creates: a clean clone of
f10f92f has no `.kimi-plugin/`, and there `check_versions.py` reports 5 manifests in
agreement and `sync_manifests.py --check` passes, with all 12 new tests green.

## 2026-09-10 - Put the audit-and-write sequence in the skill description (Task B) (owner: Fenrir) (harness: Codex)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Confirm host description limits and record the budget and manifest-description decision.
- [x] Reproduce the missing-command failure in tests/test_package.py, then rewrite skills/handoff/SKILL.md description.
- [x] Run repository checks and record verification and the handoff.

Status: In progress. Audited all 68 earlier entries against later resolutions, recent history, and current source; no effective unfinished task overlaps Task B. Rangda's completed 1.22.0 work is uncommitted and preserved. Failure case: the description has no guard command, so a model that misses the body may edit HANDOFF.md directly and lose a concurrent write. Host research establishes a 1024-character portable budget; next add the failing regression before changing the description.

Checkpoint: Added the two description tests first; the original 871-character description failed all three command subtests (saved in /tmp/handoff-task-b-regression-before.log). The rewritten 751-character description passes command presence/order and all recorded finite budgets. CONTRIBUTING.md records the 1024-character portable budget, Claude Code's 1536-character default listing limit, Cursor's 1024-character authoring contract with runtime enforcement unverified, and no cap in the skills CLI parser. Marketplace descriptions keep the capability sentence. Epona is now independently implementing Task A in non-overlapping files; its channel message confirms the generator will retain that listing description. Full repository checks and final handoff remain.

Status: Complete for Task B. Only the SKILL.md description, tests/test_package.py, CONTRIBUTING.md, and this entry were changed by Fenrir. The description now gives name/read/apply in order, snapshot and audit instructions, a payload argument, and the exit-3 re-audit rule; it shrank from 871 to 751 characters. No guard behavior changed.

Verification on Python 3.9.10: 19 repository tests passed (including both new description tests); check_versions.py agrees at 1.22.0 across six files, sync_manifests.py --check passes, guard validate exits 0, package_skill.py builds, the archived SKILL.md is byte-identical to the source, and git diff --check passes. The full helper suite ran 291 tests: 289 passed, with one error and one failure in the two existing TmuxIntegrationTests. Diagnostic reruns report missing temporary tmux socket files. Both failures reproduce from a temporary git archive of unchanged HEAD b845b09, establishing they predate this change; logs are /tmp/handoff-task-b-helper-tests.log and /tmp/handoff-task-b-baseline-tmux.log. Those unrelated tmux failures were not altered or hidden. The optional external skill-creator quick_validate.py could not run because that interpreter lacks PyYAML; repository checks remain standard-library-only. No model evaluations were run or claimed.

Handoff: No Task B implementation remains; changes are uncommitted and no release was requested. Epona owns Task A and Garuda owns Task C, both independently active in the ledger, and all prior changes are preserved. Their subsequent changes may require their own verification. The existing CI matrix runs the description tests on Python 3.9 and 3.12; this session ran them locally on 3.9.10 only.

Publication 2026-09-10: Task B and the requested README explanation are pushed in 2a1680a843cf6551151489ce33a37cbb6fa54167, rebased onto the published Task A/C history. Final checks pass: 54 root and 264 helper tests, including the previously blocked tmux integration tests. See the completed Commit and push Task B entry for the publication evidence.

## 2026-09-09 - Make exhaustion handling deterministic across harnesses (owner: Rangda) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add ledger lease parsing, validation, and the lease/sweep commands to the guard (skills/handoff/scripts/handoff_guard.py).
- [x] Add nonce challenge/attest to the channel with per-peer cost limits (skills/handoff/scripts/handoff_channel.py).
- [x] Document the three-layer protocol in references/agent-channel.md and SKILL.md.
- [x] Add regression tests for expiry, renewal, conflicts, and unanswered challenges.
- [x] Bump the version across the five manifests and run the full CI set.

Status: Complete. Exhaustion is now handled by construction rather than detection, because no signal for an exhausted model exists on every harness and silence cannot separate an exhausted agent from an idle healthy one. Guard `lease` records an owner-declared renewal deadline as a `Lease:` line on that owner's whole unfinished bucket, `lease_state` decides expiry from the ledger and the clock alone, and any peer runs `sweep` to perform the release the owner authorized in advance, through `swap_ledger` with the entry's boxes, order, and status preserved. Channel `challenge`/`attest` bind a capability proof to a fresh nonce, checked against the current ledger version; it cannot be broadcast and a repeat probe inside five minutes returns the open challenge, because probing spends the budget being asked about. An attestation clears an `unavailable` state that a poll still cannot; a released session stays released. Host hooks are unchanged and are now documented as layer 3: they write records earlier, they never decide.

Verification: the whole CI set passed on Python 3.9.10, the older of the two versions CI runs - 291 helper tests (26 new), 6 packaging/eval tests, check_versions.py (1.22.0 agrees across all five manifests), validate --root . (exit 0), package_skill.py, and git diff --check. The new tests start from the failure cases: a lease naming another owner, a non-UTC deadline treated as invalid rather than expired, a fenced example read as documentation, sweep leaving active and invalid leases alone and releasing nothing on a stale version (exit 3), a wrong or replayed or third-party attestation refused, and silence leaving capability unknown. Exercised live in this checkout: a lease was declared on this entry, reported as active, and cleared before completion; a two-session challenge round trip was run in a scratch repository. No new files ship, so the packaging allowlist is unchanged. The version was bumped but nothing was committed, tagged, or released.

## 2026-09-09 - Release 1.21.0 (owner: Lamassu) (harness: Cursor)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Commit the bar-naming work and version bump.
- [x] Run the full CI set on the release commit.
- [x] Tag v1.21.0 and push main plus the tag.
- [x] Confirm the release workflow published the archives.

Status: Complete. Committed b288944 on main and tagged v1.21.0. The release workflow (run 34351216330) passed check_versions, both suites, validate, and package_skill, and published handoff.zip, handoff.skill, and SHA256SUMS at https://github.com/divijshrivastava/handoff-skill/releases/tag/v1.21.0. Local dist/ SHA256 matches the published asset (6e3f1a0f).

## 2026-09-09 - Push the agent-channel work and release 1.20.0 (owner: Janus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Push the two agent-channel commits to origin/main.
- [x] Verify the release commit against a clean checkout rather than the shared working tree.
- [x] Tag v1.20.0 on the release commit and push the tag.
- [x] Confirm the release workflow published the archives and that their bytes match a local build.

Status: Complete. Pushed a2f0c22..cf118c8 to origin/main and tagged v1.20.0 at cf118c8. The release workflow (run 34349864894) passed check_versions, both suites, validate, and package_skill, and published handoff.zip, handoff.skill, and SHA256SUMS at https://github.com/divijshrivastava/handoff-skill/releases/tag/v1.20.0.

Verification: the checks were run in a clean clone at cf118c8, not in this working tree, because Kanaloa holds uncommitted edits to skills/handoff/scripts/handoff_tui.py and handoff_guard.py, both of which ship in the archive. A build from the dirty tree hashed f29d3ec9, while the clean checkout, the release workflow, and the downloaded asset all hash 42c52d4e - reproducible, and free of in-flight work. Local dist/ was replaced with the tagged build so no dirty-tree archive is left behind.

Note: v1.19.0 exists in the manifests' history but was never tagged, so the published sequence goes v1.18.0 to v1.20.0. Kanaloa's in-progress bar-naming task is unaffected and remains its own; nothing of theirs was staged, committed, or released.

## 2026-09-09 - Name the current agent in the handoff bar (owner: Lamassu) (harness: Cursor)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Recall this session's claimed name and show it in --bar and the tmux footer instead of open-task owners (skills/handoff/scripts/handoff_guard.py, handoff_tui.py, handoff_codex.py).
- [x] Give each wrapped agent session its own HANDOFF_SESSION seed so the footer can resolve its name (skills/handoff/scripts/handoff_codex.py).
- [x] Invalidate the handoff-bar cache when a name claim lands (skills/handoff/scripts/handoff_guard.py).
- [x] Update the bar, TUI, and Codex tests plus the progress-viewer reference.
- [x] Run both unittest suites, validate the ledger, and hand off.

Status: Complete. Originally owned by Kanaloa (harness: Kimi Code), who left uncommitted work on `handoff_guard.py` and `handoff_tui.py`. Lamassu took over at the user's direction on 2026-09-09 to finish the remainder. Added `recall_name`, `bar_session_name`, and `bar_cache_key`/`invalidate_bar_cache` (matching `handoff-bar`'s `cksum` key); `--bar` and the tmux footer now trail the claiming session's name rather than open-task owners; `--with`/`--codex` seeds `HANDOFF_SESSION` for the wrapped agent. Shipped in b288944 as release 1.21.0.

## 2026-09-09 - Coordinate agent availability and explicit work handoffs (owner: Janus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add a durable repository channel for messages, capability reports, and acknowledgements.
- [x] Support explicit release and guarded pickup of unfinished work when an agent cannot continue.
- [x] Integrate the channel into skill and continue instructions, documentation, evaluations, and packaging.
- [x] Verify crash, retry, concurrent pickup, and exhausted-but-running cases; run repository checks and record the handoff.

Status: In progress. Failure case: a CLI remains resident after token exhaustion, and peers mistake that process for an agent able to work. Implementing a durable local inbox and explicit availability reports; a self-release will unassign unfinished tasks through the existing guarded ledger write. Timeouts report unknown capability rather than silently authorize takeover. The earlier Iara ledger closure and unrelated .kimi-plugin/ are preserved.

Checkpoint: 22 channel regression tests pass, including failure-hook reporting with a resident process, durable cross-process delivery, retry deduplication, voluntary whole-bucket release, notification failure after release, and two peers competing to claim one ledger revision. Added Claude SessionStart/StopFailure/PostToolUse/UserPromptSubmit command hooks; these run outside the model. Source version is 1.20.0. Full repository checks and final handoff remain. No live quota was exhausted; the failure evidence so far is native-shaped fixture events.

Transfer: Taken over by Janus from Iara on 2026-09-09 at the user's explicit direction ("take over Iara's tasks"). Iara's uncommitted work is preserved in full at /Users/divij/.handoff-recovery/2026-09-09T1723-iara-coordinate-agent-availability - all 18 modified and untracked paths, a git diff of the tracked ones, and the HEAD they were taken against (a2f0c22); nothing was moved out of the working tree. Iara's Codex CLI (PID 4209) was still resident but not writing: no source file changed after 16:56, and its CPU time held at 0:17.38 across the observation window. Originally owned by Iara.

Verification: Janus ran the whole CI set on Python 3.12 after the transfer, all passing - 258 helper tests, 6 packaging/eval tests, check_versions.py (1.20.0 agrees across all five manifests), guard validate --root . (exit 0), package_skill.py (handoff.zip carries scripts/handoff_channel.py and references/agent-channel.md), and git diff --check. The 25 channel regression tests cover each case this step names: crash (test_crashed_message_writer_rolls_back_and_releases_database_lock, test_process_death_after_ledger_release_cannot_reclaim_work), retry (test_send_retries_deduplicate_but_reused_ids_cannot_change_messages, test_parallel_sends_with_one_id_store_one_message), concurrent pickup (test_two_peers_cannot_both_claim_the_same_released_snapshot, test_yield_conflict_does_not_publish_or_change_capability), and exhausted-but-running (test_failure_hook_notifies_peers_while_process_is_still_alive, test_stale_report_and_inbox_poll_do_not_establish_liveness, test_unavailable_report_does_not_release_owned_work). Beyond the fixtures, the channel was exercised live in this checkout: join created .handoff/ with a self-ignoring .gitignore and left git status unchanged at 18 paths, and peers returned the reported-capability note. That run also showed Iara had never registered, which is why its capability read as unknown rather than unavailable and why the resident PID alone could not authorize the pickup.

Status: Complete. The channel, release/pickup path, integration, and verification are all in place and checked. Committed on main in f8094b1, staging 17 explicit paths; the untracked .kimi-plugin/ was deliberately left out, being unrelated to this task, still at 1.17.0, and covered by neither check_versions.py nor the packaging tests. No release bump was needed, since 1.20.0 already names this work. Next action: none for this task; publishing the 1.20.0 tag is separate work under CONTRIBUTING.md.

## 2026-09-09 - Restore the original README lead GIF (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Restore assets/dashboard-session.gif and the original top README embed; leave the TUI GIF in the dashboard section.
- [x] Commit, push origin/main, and record the identifier.

Status: In progress. The 4:44 TUI GIF belongs only in the Live progress dashboard section. Restoring assets/dashboard-session.gif as the lead image.


Resolved 2026-09-09 by Iara (harness: Codex) during handoff:continue. Haetae already completed the restoration in a2f0c22a50d77f4802eb184b1bd3ea71eb50e938; only this closing record remained. README.md embeds assets/dashboard-session.gif at line 11 and assets/handoff-tui.gif in the Live progress dashboard section at line 199. Both asset blobs match their earlier committed originals. main and the local origin/main reference point at a2f0c22, and the origin/main reflog records update by push. A fresh remote check could not resolve github.com, so remote state was not independently rechecked. No Grok process was observed and no uncommitted changes touched this task; Haetae retains attribution for the implementation. Verified: 233 helper tests and 5 repository tests pass, versions agree at 1.19.0, archives build, and the pre-edit ledger validation and git diff --check pass. Complete. This audit note remains uncommitted; the implementation commit and push predate it. No implementation work remains. The unrelated untracked .kimi-plugin/ is unchanged. Next action: none for the restoration.

## 2026-09-09 - Use the 4:44 handoff-tui GIF as the README lead image (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Point the README lead image at assets/handoff-tui.gif from the 4:44 recording (README.md).
- [x] Remove the older assets/dashboard-session.gif.
- [x] Commit, push origin/main, and record the identifier.

Status: Complete. The 4:44 AM screen recording is assets/handoff-tui.gif. It is now the README lead image and the Live progress dashboard embed. Removed assets/dashboard-session.gif. Pushed as 2297574 and 32bb5d7. Next action: none.

## 2026-09-09 - Add a handoff-tui GIF to the README dashboard section (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Convert the latest TUI screen recording to an optimized GIF (assets/handoff-tui.gif).
- [x] Embed it in the Live progress dashboard section (README.md).
- [x] Commit, push origin/main, and record the identifier.

Status: Complete. Converted the 4:44 AM screen recording of handoff-tui: trimmed the 3s blank terminal lead-in, scaled to 1000x533 at 10 fps, palette-quantized and gifsicle-optimized to 2.5MB / 32.5s looping. Embedded under Live progress dashboard in README.md. Committed and pushed as 538a483. Next action: none.

## 2026-09-09 - Center the README logo (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Center the logo image in README.md so GitHub renders it in the middle of the column.
- [x] Commit, push origin/main, and record the identifier.

Status: Complete. Replaced the left-aligned markdown image with a GitHub-allowed centered HTML img (width 192). Committed and pushed as 6b5e62c. Next action: none.

## 2026-09-09 - Remove the old README GIF after testing purge (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Run the purge tests and a live helper smoke test in a throwaway directory.
- [x] Remove scripts/demo/handoff.gif (README.md no longer embeds it).
- [x] Commit, push origin/main, and record the identifier.

Status: Complete. Purge verified before the deletion: 11 PurgeTests, 233 helper tests, and 5 repository tests pass; versions agree at 1.19.0. Live smoke in /tmp/handoff-purge-smoke-EJ0t covered missing confirm (exit 2), dry-run, apply-with-archive, missing ledger (exit 1, no file created), and stale version (exit 3). This repository's ledger was not purged. Deleted scripts/demo/handoff.gif and the untracked handoff-opt.gif leftover. Committed and pushed as 466390b. Next action: none.

## 2026-09-09 - Put the dashboard GIF at the top of the README (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Replace the top README demo image with assets/dashboard-session.gif and remove the duplicate lower down (README.md).
- [x] Commit, push origin/main, and record the identifier.

Status: Complete. The lead image is now assets/dashboard-session.gif; the duplicate under Live progress dashboard is gone. scripts/demo/handoff.gif remains in the tree as a recording asset and is no longer embedded. Committed and pushed as 40b6484. Next action: none.

## 2026-09-09 - Commit the README dashboard GIF and push (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Stage README.md, assets/dashboard-session.gif, and the 1.19.0 purge files the README now documents.
- [x] Commit, push origin/main, and record the identifier.

Status: Complete. Committed as 7372d6d (work) and e5599e8 (ledger note). Pushed d9c0980..e5599e8 to origin/main. The README on GitHub now embeds assets/dashboard-session.gif and documents /handoff:purge at 1.19.0. Left untracked: .kimi-plugin/ and scripts/demo/handoff-opt.gif. Next action: none for this push. Installed plugin copies still need a 1.19.0 release before they see purge.

## 2026-09-09 - Add /handoff:purge for an authorized clean slate (owner: Haetae) (harness: Grok)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add helper purge through swap_ledger with archive (skills/handoff/scripts/handoff_guard.py, skills/handoff/tests/test_handoff_guard.py).
- [x] Add the /handoff:purge command and document the trigger (commands/purge.md, SKILL.md, README.md, references/ledger-contract.md, CONTRIBUTING.md, CLAUDE.md, evals.json).
- [x] Bump the version to 1.19.0 across the five manifests.
- [x] Verify both test suites, versions, validate, package, and git diff --check.
- [x] Record the handoff.

Status: Complete. Failure case: an agent told to start fresh deletes HANDOFF.md (dropping the activation trigger) or writes empty content without a version check (racing peers and losing uncommitted history). Purge is a helper subcommand that goes through swap_ledger: it archives the replaced bytes under the lock, writes an empty valid ledger in place, and refuses to create a ledger where none exists. `--confirm purge` is required. Verified: 233 helper tests and 5 repository tests pass, check_versions.py v1.19.0 agrees, validate exits 0, package_skill.py builds, git diff --check is clean. This repository's ledger was not purged. README.md also still carries the user's uncommitted dashboard GIF; staging that file for a later commit would include it. Next action: commit the purge work on explicit paths if the user wants it shipped; a release is needed before installed copies see 1.19.0.

## 2026-09-09 - Release 1.18.0 (owner: Daedalus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Verify the manifests already agree at 1.18.0 and run the release checks.
- [x] Tag v1.18.0, push it, and confirm the published release against a clean-checkout build.
- [x] Record the handoff.

Status: In progress. No version bump is needed: the Enkidu session already moved all five manifests and SKILL.md to 1.18.0 in fab6602, which added the Cursor marketplace and taught check_versions.py to inspect five files, and check_versions.py v1.18.0 agrees. The release therefore carries fab6602 and the logo commit 696207a on top of 1.17.0. Two things are deliberately outside it: .kimi-plugin/plugin.json is untracked, still declares 1.17.0, and is not inspected by check_versions.py, so the release cannot contain it and CI will not catch that drift; and the untracked demo GIF stays with its earlier entry. Agent sessions are still live in this tree, so the archive will be built from a clean worktree at the tagged commit. Complete. Validate run 34283761497 on the logo commit passed before tagging. No bump was made or needed: check_versions.py v1.18.0 agrees across all five manifests and SKILL.md. Verified before tagging: 222 helper tests and 5 repository tests pass, validate exits 0, git diff --check is clean, and a clean worktree build at aa8c520 carries 13 files, reports 1.18.0, and correctly excludes assets/handoff.svg, which is a repository asset rather than a runtime resource. Tag v1.18.0 pushed. Release run 34283915512 succeeded and the release published at 22:03:51Z; the downloaded handoff.zip and handoff.skill hash to d218262fc69327385043b574be9fb307db284f3bfa5f9d88be7377e0c8a548fc, identical to that clean build. Validate run 34283905786 succeeded on ubuntu and windows for Python 3.9 and 3.12. The release carries fab6602, the Cursor marketplace manifests written by the Enkidu session, and 696207a, the logo. Still outside it and unresolved: .kimi-plugin/plugin.json is untracked, declares 1.17.0, and is not inspected by check_versions.py, so it is outside version control, outside the release, and outside CI's drift check at once; it belongs to a session that was live at the time and was left alone. Next action: none for the release. An installed plugin copy needs its marketplace updated before it sees 1.18.0.

## 2026-09-09 - Add the Handoff logo to the repository (owner: Daedalus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add the logo at assets/handoff.svg.
- [x] Show it at the top of the README (README.md).
- [x] Run the repository checks and record the handoff.

Status: In progress. The user supplied ~/Downloads/handoff.svg as the project logo. Inspected before adding: 256x192, no <script> and no external href, transparent background with slate #5B6B7C and amber #E08A1E strokes, so it reads on both GitHub themes; 7736 of its 8731 bytes are an embedded C2PA provenance manifest, which is kept rather than stripped. No marketplace manifest in this machine's installed marketplaces carries an icon or logo field, so none is invented; the logo is a repository asset, not a runtime resource, and does not belong in the packaging allowlist. Complete. The file is at assets/handoff.svg, byte-identical to the source, in a new assets/ directory because scripts/demo holds demo recordings rather than brand assets. README shows it above the title with alt text Handoff, matching the plain-markdown style of the existing demo image. Verified: the file parses as XML, 222 helper tests and 5 repository tests pass, versions agree at 1.18.0, ledger validation and git diff --check pass, and the built archive still carries exactly 13 files with the logo excluded, which is correct because it is not a runtime resource and the packaging allowlist was not touched. Not verified: how the logo renders on GitHub's light and dark themes; its strokes are slate #5B6B7C and amber #E08A1E on a transparent background, which should read on both, but no rendering was observed. Next action: none. Note for the next session: the repository is at 1.18.0 with a Cursor marketplace committed in fab6602 but no v1.18.0 tag or release yet, and .kimi-plugin/plugin.json is untracked and still declares 1.17.0, outside what check_versions.py inspects.

## 2026-09-09 - Commit and release 1.17.0 (owner: Daedalus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Bump the version triple to 1.17.0 and run the release checks.
- [x] Commit the release change and push main.
- [x] Tag v1.17.0, push it, and confirm the published release against a clean-checkout build.
- [x] Record the handoff.

Status: In progress. Seven commits sit unpushed and none of their user-visible work is in 1.16.0: the harness field and its display (2c50f00), the activation gate (e3a024a), the narrowing that makes an existing ledger a trigger (adf5a98), the reconciled gate documents and evals (42daeb9), and Enkidu's Codex default prompt (34e0209). All ship in SKILL.md, README, references, handoff_guard.py and handoff_tui.py, so they reach installed copies only through a release. 1.16.0 is tagged at 92da65c, so the triple moves to 1.17.0. Three agent sessions are live in this tree, so the archive will be built from a clean worktree at the release commit and a watch runs before the bump. Complete. A watch before the bump reported one write, this session's own release entry, a pure addition with no deletions. Triple moved to 1.17.0 and check_versions.py v1.17.0 agrees. Verified before tagging: 222 helper tests and 5 repository tests pass, validate exits 0, git diff --check is clean, and a clean worktree build at f070e71 carries 13 files, reports 1.17.0, and ships the Activation section, the existing-ledger trigger, detect_harness and harness_label. Pushed 6a19778..f070e71 and tag v1.17.0. Release run 34281140009 succeeded and the release published at 21:32:31Z; the downloaded handoff.zip and handoff.skill hash to e005bf99e6a174eb4da195a3fdb2d2880b9a54d081c69d8109faed6ca44b42f3, identical to that clean build and to the published SHA256SUMS, and opening the published archive confirmed 1.17.0 with both activation rules present. Validate run 34281137712 succeeded on ubuntu and windows for Python 3.9 and 3.12. The user's installed plugin was then updated from 1.16.0 to 1.17.0, its record pointing at f070e71, and the installed copy carries the four commands including init.md; it applies on restart, so this session still runs 1.16.0. Next action: none.

## 2026-09-09 - Commit the Codex init prompt (owner: Enkidu) (harness: Kimi Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Commit agents/openai.yaml, the last uncommitted piece of this session's activation-gate work.
- [x] Record the handoff.

Status: Complete. Committed as 34e0209 at the user's "commit your changes". Everything else this session wrote was already committed by then: e3a024a carries the SKILL.md gate, 42daeb9 carries commands/init.md, README.md, and evals.json after Daedalus reconciled them, at the user's direction, with the narrowed rule of adf5a98 (an existing HANDOFF.md activates the skill; the init gate applies to repositories without one). This session's two earlier entries describe the wider rule as shipped in e3a024a; the narrower rule above is the effective one, per Daedalus's later entries. The working tree is now clean of this session's work; only the untracked scripts/demo/handoff-opt.gif, which no session here owns, remains. Verified: ledger validation and git diff --check pass, versions agree at 1.16.0. Next action: none.

## 2026-09-09 - Reconcile the gate documents with the narrowed rule (owner: Daedalus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Rewrite eval scenario 6 so it grades the narrowed rule (skills/handoff/evals/evals.json).
- [x] Correct the README activation section, trigger table, and command list (README.md).
- [x] Correct the init command's description of the gate (commands/init.md).
- [x] Check the Codex default prompt still holds (skills/handoff/agents/openai.yaml).
- [x] Run the repository checks and record the handoff.

Status: In progress. adf5a98 made an existing HANDOFF.md a trigger, but the documents describing the gate are uncommitted work of the live Enkidu session (kimi-code, pid 66690) and still state the wider rule: eval scenario 6 grades doing no handoff work in a repository that has a ledger, README says the skill does not engage on its own "not even in a repository with a HANDOFF.md", and commands/init.md calls itself the activation gate. The user directed this reconciliation explicitly. Enkidu's four files were copied to /tmp/handoff-enkidu-preserve-025033 before any edit. Complete. Scenario 6 now poses a repository with no HANDOFF.md, shared agents and work that looks unfinished, and grades doing no handoff work and creating no ledger; it also asks the answer to distinguish a repository that already keeps one. A new scenario 7 grades the converse, that an existing ledger activates the skill without being asked, which nothing tested before. README no longer says the skill does not engage "not even in a repository with a HANDOFF.md"; the trigger table gains an existing-ledger row, the never-auto-selects paragraph is narrowed to repositories without a ledger and carries the reason, and the command list describes init as how a repository without a ledger becomes one. commands/init.md says the same. agents/openai.yaml needed no change: its default prompt asks to initialise, claim a name, audit the ledger and report, which holds under either rule. Enkidu's files were copied to /tmp/handoff-enkidu-preserve-025033 first, and a 90-second watch over all four reported no peer write; they had been unchanged since 02:45:03 and 02:34:54. Verified: 222 helper tests and 5 repository tests pass, evals.json parses with 7 scenarios, versions agree at 1.16.0, archives build, ledger validation and git diff --check pass. Not verified: scenarios 6 and 7 were authored, not run against a model, so they must not be reported as passing evaluations. Next action: none; the gate documents and the shipped contract now agree, and a release would need the triple bumped past 1.16.0.

## 2026-09-09 - Let an existing ledger activate the skill (owner: Daedalus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Narrow the Activation section and description so a repository that already keeps HANDOFF.md activates the skill (skills/handoff/SKILL.md).
- [x] Run the repository checks and record the handoff, including what the change leaves inconsistent.

Status: In progress. The gate committed as e3a024a suppresses all handoff work until explicit activation, including in a repository that already keeps a ledger. The user reports that init was meant for repositories with no ledger, and directs that an existing HANDOFF.md activate the skill on its own. Narrowing it accordingly: the ledger's presence becomes a trigger, while multiple agents or unfinished-looking work in a repository without one stay non-triggers. This edits the section the Enkidu session is actively rewriting, at the user's explicit direction; its other uncommitted files are left alone. Complete. An existing HANDOFF.md is now the first listed trigger, with the reason recorded: someone put it there to track work this way, and a ledger nobody reads is worse than none. The description says the skill is active in any repository that keeps a ledger and starts on explicit activation elsewhere. What stays a non-trigger is narrower and truer: multiple agents, or work that merely looks unfinished, in a repository that keeps no ledger. init is now described as how a repository without a ledger becomes one, and as reporting recorded state where a ledger already exists. Enkidu's newer lazy-load paragraph was preserved. SKILL.md had been quiet from 02:45:03 through the edit, verified by a 90-second watch whose only change was this session's own ledger write. Verified: 222 helper tests and 5 repository tests pass, versions agree at 1.16.0, archives build, ledger validation and git diff --check pass. Left inconsistent on purpose, because it belongs to a live owner: skills/handoff/evals/evals.json is uncommitted work of the Enkidu session, and its new scenario 6 grades the opposite of this change, expecting no handoff work in a repository that has a HANDOFF.md and no init. That scenario now contradicts the shipped contract and needs rewriting by its owner or by explicit direction. README.md, agents/openai.yaml and the untracked commands/init.md are also that session's and were not touched; they may describe the wider gate. Next action: none here; the eval and those documents need reconciling before a release.

## 2026-09-09 - Clarify that handoff:init lazy-loads the full workflow (owner: Enkidu) (harness: Kimi Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] State lazy-load semantics in the Activation section (skills/handoff/SKILL.md).
- [x] Say the same in the README Use it section and commands/init.md.
- [x] Run the repository checks and record the handoff.

Status: Complete. The user clarified the gate's intent: once /handoff:init (or "initialise the handoff") is invoked, the whole repository works with full handoff functionality for the rest of the session — init is a lazy load, not a per-request ritual. The Activation section now says the whole contract governs every repository task after any trigger, with no further handoff mention needed, and that init only turns it on; the README Use it section and commands/init.md say the same. Prose-only change on top of e3a024a. Also recorded here, per Daedalus's annotation on the earlier init-gate entry: f3443f4 was split at the user's direction into 2c50f00 (Daedalus's harness work) and e3a024a (this session's SKILL.md gate, committed unchanged by Daedalus with attribution), and the uncommitted README.md edits interleaved with this task's belong to a cursor-agent session that ran 02:34:35-02:36:05 under "update the readme with as much detail as possible", not to Daedalus. Verified: 222 helper tests and 5 repository tests pass, validate exits 0, git diff --check is clean. Left uncommitted: this change's SKILL.md/README/init.md edits plus the earlier entry's openai.yaml and evals.json changes; committing README.md waits on the cursor session's work being claimed or set aside by the user. Next action: none.

## 2026-09-09 - Start handoff only on handoff:init or 'initialise the handoff' (owner: Enkidu) (harness: Kimi Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add the /handoff:init command that initialises tracking (commands/init.md).
- [x] Gate the skill on explicit activation in the description and a new Activation section (skills/handoff/SKILL.md).
- [x] Point the Codex default prompt at the phrase (skills/handoff/agents/openai.yaml).
- [x] Document the gate and the new command (README.md).
- [x] Update eval scenarios for activation and add a gate scenario (skills/handoff/evals/evals.json).
- [x] Run the repository checks and record the handoff.

Status: Complete. Failure case: hosts auto-selected the skill whenever HANDOFF.md existed, so handoff preflight and ledger work ran on requests the user never asked to track. The skill's description no longer lists repository conditions as triggers and states that an existing HANDOFF.md, multiple agents, or unfinished-looking work are not triggers; a new Activation section confines handoff work to the /handoff:init command, the phrase "initialise the handoff" (which the Codex default_prompt in agents/openai.yaml now runs), or an explicit handoff request, and says init establishes tracking without starting a task. commands/init.md defines the command: claim the session name, preflight, read or create the ledger, report effective status, start nothing. README leads with init, shows the Codex phrase, and lists four commands. Evals 1-5 now state handoff is initialised; new eval 6 grades doing no handoff work without activation. Packaging unchanged: commands/ ships via the plugin, not RUNTIME_FILES. Verified: 222 helper tests pass (an earlier run flaked 219 with 2 failures and 1 error before these edits were reverted-independent; three consecutive full runs are green), 5 repository tests pass, evals.json parses, versions agree at 1.16.0, validate exits 0, package_skill.py builds, git diff --check is clean. Not verified: eval 6 was authored, not run against a model. Commit state: while this session worked, the concurrent Daedalus session committed f3443f4 ("Show each session's harness beside its name") and swept this task's uncommitted SKILL.md description and Activation section into that commit; the harness field in this entry's heading and the harness prose in SKILL.md Step 0 are Daedalus's work from that commit. Left uncommitted in the working tree: commands/init.md, openai.yaml, evals.json, this entry, and README.md, where Daedalus's own uncommitted edits (the Version line, the workflow and task-state sections, the activation-triggers table) are interleaved with this task's, so committing README.md would sweep an active owner's work. Next action: none for the gate itself; committing README.md waits on Daedalus, and a release would need the version triple bumped past 1.16.0. Annotation added 2026-09-09 by Daedalus, which is not adopting or editing this task: the commit state above is now out of date, because f3443f4 has been split at the user's direction. 2c50f00 carries the harness work, and e3a024a carries this entry's SKILL.md description rewrite and Activation section, unchanged and attributed to this session. The resulting tree is identical to f3443f4, and commands/init.md, openai.yaml and evals.json remain uncommitted and untouched. One correction offered for this entry's owner to judge: Daedalus holds no uncommitted README.md edits. Its README work landed in f12fea2 and 627159d. A cursor-agent session ran in this repository from 02:34:35 to 02:36:05 under the prompt 'update the readme with as much detail as possible', with README.md written at 02:35:59 inside that window, so some of what this entry reads as Daedalus's may be that session's.

## 2026-09-09 - Show each session's harness beside its name (owner: Daedalus) (harness: Claude Code)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Detect the harness and record it in the heading and the session cache (skills/handoff/scripts/handoff_guard.py).
- [x] Show the recorded harness and a live marker in the agents view, the plain report, and the bar (skills/handoff/scripts/handoff_tui.py). The bar was deliberately left unchanged and the marker reads "(recent)", not "live"; both are explained in the status.
- [x] Drop the harness field when a task is reassigned, since it describes the owner.
- [x] Cover both with regression tests (skills/handoff/tests/).
- [x] Document the heading field and the new column (references/ledger-contract.md, references/progress-viewer.md, SKILL.md).
- [x] Run the repository checks and record the handoff.

Status: In progress. The viewer shows owner labels only, so a reader cannot tell which tool a session ran in; with Claude Code, Codex and Cursor sessions in this repository at once, the names alone do not say who is who. OWNER_RE forbids parentheses inside a name, so the harness cannot go in the label. At the user's direction the harness is recorded both ways: a separate optional heading field, `(harness: ...)`, written when an entry is created, so every reader and every past owner keeps it; and the per-session name-cache record, so the viewer can also mark which of those sessions is still running on this machine. Old entries simply lack the field. Complete. HARNESS_RE parses an optional `(harness: ...)` field beside the owner label, Task carries it, detect_harness reads HANDOFF_HARNESS then CLAUDECODE and CLAUDE_CODE_SESSION_ID, CODEX_HOME and CODEX_SANDBOX, and TERM_PROGRAM with CURSOR_TRACE_ID, template --harness auto writes it, and the session cache record now holds name and harness on separate lines so older single-line records still parse. replace_owner strips the field, because it describes the session that held the task. The viewer shows it in the agents view and the plain report, taken from the newest entry an owner recorded one in. This entry carries the field itself. Two deliberate deviations from the plan above. The bar was left unchanged, because its one line already carries owner names and doubling them would crowd a status line. And the marker reads (recent), not live: the liveness idea did not survive contact with the evidence, because NAME_CLAIM_SECONDS is a twelve-hour reservation that stops two sessions sharing a name, and it had marked Bakunawa live two hours after that session ended. A separate RECENT_CLAIM_SECONDS of fifteen minutes now backs a marker that claims only what a refreshed record proves, a recent claim on this machine, never a running process. The existing suite also caught a real defect introduced on the way: reading a record first line raised IndexError on an empty file where the previous strip() did not, now fixed and covered. Verified: 222 helper tests and 5 repository tests pass, versions agree at 1.16.0, ledger validation and git diff --check pass. Not verified: the curses agents view under a real terminal; its row rendering is covered by unit tests and the plain report was checked against this ledger. Next action: none, unless a release is wanted, which would need the triple bumped past 1.16.0.

## 2026-09-09 - Commit and release 1.16.0 (owner: Daedalus)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Bump the version triple to 1.16.0 and run the release checks.
- [x] Commit the release change and push main.
- [x] Tag v1.16.0, push it, and confirm the published release against a clean-checkout build.
- [x] Record the handoff.

Status: In progress. The user asked to release the viewer work adopted from the Codex session and committed as 6a3f9d8: ledger-order agent lists and the gg/G jump keys, which ship in handoff_tui.py and progress-viewer.md and so reach installed copies only through a release. 1.15.0 is tagged and deliberately excluded that work, so the triple moves to 1.16.0. Complete. Triple moved to 1.16.0 and check_versions.py v1.16.0 agrees. Verified before tagging: 212 helper tests and 5 repository tests pass, validate exits 0, git diff --check is clean, and a clean worktree build at 92da65c carries 13 files, reports 1.16.0, ships jump_to_end in handoff_tui.py and the gg/G row in progress-viewer.md. Pushed 1efba4b..92da65c and tag v1.16.0. Release run 34271308883 succeeded and the release published at 19:50:55Z; the downloaded handoff.zip and handoff.skill hash to ab151bc7aa057ee95ab2d034e8395853912532a46bd3149604ce1fbc696a8bf3, identical to that clean build. Validate run 34271305828 succeeded on ubuntu and windows for Python 3.9 and 3.12. Next action: none. An installed plugin copy needs /plugin marketplace update divij-skills before it sees 1.16.0.

## 2026-09-09 - Order the agent list newest first and add vim jump keys (owner: Daedalus)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Group the viewer's agent list and the bar's owner trailer in ledger order (skills/handoff/scripts/handoff_tui.py).
- [x] Add gg and G jumps that also serve Home and End, in lists and in details (skills/handoff/scripts/handoff_tui.py).
- [x] Cover both with regression tests (skills/handoff/tests/test_handoff_tui.py).
- [x] Document the new keys and the ordering (skills/handoff/references/progress-viewer.md).
- [x] Run the repository checks and record the handoff.

Status: In progress. Adopted 2026-09-09 by Daedalus at the user's explicit direction, from the Codex session that owns Cernunnos and had left this work uncommitted with no ledger entry of its own; the user reported that session out of context. Its files were quiet from 01:09:34 to the takeover at 01:15 and are preserved at /tmp/handoff-takeover2-daedalus-20260909-011518. Audited rather than assumed: owner_counts and bar_line now keep ledger order so the newest entry's owner leads instead of whoever sorts first alphabetically, jump_to_end backs gg, G, Home and End in both the list and the detail pane, a lone g arms only the next real keypress and an idle -1 poll does not disarm it, and the viewer header, footer and plain report say "newest first". Five regression tests cover it and all 212 helper tests pass. What is missing is documentation: references/progress-viewer.md still lists only Home/End in its controls table and describes neither the new keys nor the ordering. Completed by Daedalus: progress-viewer.md now lists gg and G in the controls table, states that the Agents view is in ledger order with the newest owner leading, and says the bar trailer follows the same order. The adopted code and tests were not rewritten. Verified: 212 helper tests and 5 repository tests pass, versions agree at 1.15.0, ledger validation and git diff --check pass. The peer files were byte-identical to the preserved copies at commit time, so nothing of the prior session was lost. Not verified: the keys under a real curses terminal; the tests drive handle_key directly. Next action: none. This shipped work is not in 1.15.0, which was tagged before it; a release would need the triple bumped past 1.15.0.

## 2026-09-09 - Commit and release 1.15.0 (owner: Daedalus)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Bump the version triple to 1.15.0 and run the release checks.
- [x] Commit the release change and push main.
- [x] Tag v1.15.0, push it, and confirm the published release against a clean-checkout build.
- [x] Record the handoff.

Status: In progress. The user asked to release the Cursor viewer key, committed as 627159d, which ships in SKILL.md, harness-setup.md and handoff_keys.py and so reaches installed copies only through a release. 1.14.0 is tagged, so the triple moves to 1.15.0. package_skill.py reads the working tree and scripts/handoff_tui.py is in RUNTIME_FILES, while another session holds uncommitted changes to that file, so the archive will be inspected from a clean checkout of the release commit rather than from this tree. Complete. Triple moved to 1.15.0 and check_versions.py v1.15.0 agrees. Verified before tagging: 212 helper tests and 5 repository tests pass, validate exits 0, git diff --check is clean. The archive was built and inspected from a detached worktree at 1efba4b rather than from this tree, because package_skill.py reads the working tree and another session holds uncommitted changes to scripts/handoff_tui.py: that clean build carries 13 files, reports 1.15.0, ships install_cursor_binding and the Cursor section, and correctly omits the peer work. Pushed f290f65..1efba4b and tag v1.15.0. Release run 34270610694 and Validate run 34270607213 both succeeded, and the published handoff.zip and handoff.skill hash to 110e56bb5b8d87cd92767690a3906274531016b221a326d06324701835793958, identical to that clean build. Next action: none. An installed plugin copy needs /plugin marketplace update divij-skills before it sees 1.15.0.

## 2026-09-09 - Open the viewer with the same key in Cursor's terminal (owner: Daedalus)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add a cursor target to the key installer that runs the viewer as a workspace task (skills/handoff/scripts/handoff_keys.py).
- [x] Cover the new target with regression tests (skills/handoff/tests/test_handoff_keys.py).
- [x] Document the Cursor path (skills/handoff/references/harness-setup.md, README.md, skills/handoff/SKILL.md).
- [x] Install it locally, verify the key opens the viewer in Cursor, run the repository checks, and record the handoff.

Status: In progress. Ctrl+Alt+H is an iTerm2 GlobalKeyMap entry, so it exists only in iTerm2; Cursor's integrated terminal has no binding and the user asked for the same key there. Cursor is VS Code based, so the equivalent that never types into the running agent is a keybinding on workbench.action.tasks.runTask plus a workspace task that launches the viewer. Planned: a constant task label so one global keybinding serves every repository, ${workspaceFolder} as --root so the task file stays portable, and workbench.action.tasks.runTask added to terminal.integrated.commandsToSkipShell so the key still fires while the terminal has focus. Complete. handoff_keys.py gained a cursor target: vscode_key_name spells C-M-h as ctrl+alt+h, cursor_task writes a Handoff viewer task using --root '${workspaceFolder}' so one constant label serves every repository, and install_cursor_binding merges the keybinding textually so the file keeps its comments, refuses a key another command owns, and leaves configuration that does not parse untouched. detect_emulators reports cursor when TERM_PROGRAM is vscode and Cursor config exists. Seven regression tests cover it. .vscode/tasks.json is gitignored because the generated command names this machine's interpreter. Installed locally for this repository: keybindings.json kept its comment and the existing cmd+i binding, settings.json kept all 41 previous keys unchanged with commandsToSkipShell added, and the task command /usr/local/bin/python3 /Users/divij/.local/bin/handoff-tui --root <workspace> rendered the live ledger. Backups: ~/.config/handoff/cursor-keybindings-before-viewer-key.json and cursor-settings-before-viewer-key.json. Not verified: the physical keystroke inside a Cursor window, which needs a window reload and a human at the keyboard. Verified: 212 helper tests and 5 repository tests pass, versions agree at 1.14.0, ledger validation and git diff --check pass. Note for the next session: skills/handoff/scripts/handoff_tui.py and tests/test_handoff_tui.py carry another session's uncommitted work (owner ordering and gg/G keys, no ledger entry yet); they were excluded from this commit and left alone. Next action: none, unless a release is wanted, which would need the version triple bumped past 1.14.0.

## 2026-09-09 - Commit and release 1.14.0 (owner: Daedalus)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Bump the version triple to 1.14.0 and run the release checks.
- [x] Commit the release change and push main.
- [x] Tag v1.14.0, push it, and confirm the published release.
- [x] Record the handoff.

Status: Complete. The user asked to tag and push. main is ahead of origin/main by b969f18 (Ctrl+Alt+H viewer shortcut) and f12fea2 (name claimed first at preflight), both user-visible and both in shipped files, so they reach installed copies only through a release. 1.13.0 is already tagged at 2a257ea, so the triple moves to 1.14.0. Triple moved to 1.14.0 and check_versions.py v1.14.0 agrees. Verified before tagging: 200 helper tests and 5 repository tests pass, validate exits 0, archives build, git diff --check is clean, and the built archive carries 13 files with handoff/SKILL.md reporting 1.14.0 and Step 0 opening on the name claim. Pushed b0d438b..e36189d to main and tag v1.14.0. Release workflow run 34269419130 succeeded and the GitHub release published at 19:31:23Z with handoff.zip, handoff.skill, and SHA256SUMS; the downloaded assets hash to a66240facbec1e8687d4ff7c1eb8b36a406018560038b88b012d83427a0f3343, identical to the local build. Staged by explicit path throughout; the untracked scripts/demo/handoff-opt.gif stays with its earlier entry. Validate run 34269416113 on main succeeded across all four legs (ubuntu and windows, Python 3.9 and 3.12). Status: Complete. Next action: none. An installed plugin copy needs /plugin marketplace update divij-skills before it sees 1.14.0.

## 2026-09-09 - Claim the session name as the first preflight step (owner: Daedalus)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Move name claiming to the first Step 0 item and renumber the rest (skills/handoff/SKILL.md).
- [x] Align the wording that describes when a session claims its name (README.md, skills/handoff/references/ledger-contract.md).
- [x] Run the repository checks, validate the ledger, and record the handoff.

Status: Complete. Recorded pending at intake: the user asked that a session claim its handoff name before anything else, and SKILL.md claimed it at item 6 of 7 in Step 0, after the ledger read, the doctor and git status, so any earlier report or write was unattributed. This session followed the rule it was asked to write, claiming the name Daedalus before recording this entry. Work was blocked at first because the two files it edits, skills/handoff/SKILL.md and README.md, carried uncommitted changes from Cernunnos (Codex pids 80950/80951, started 00:24:41; an earlier note here named pid 34851, which is a different Codex session in the same directory). The user then directed the takeover of Cernunnos's bucket because it had reached its context limit, which lifted the block. Step 0 now claims the name as item 1 and renumbers the rest 2-7 with no other wording changed; the item records why it is first (names are first come, first served, and work before the claim is unattributed) and that --root accepts any path inside the repository, so it does not depend on the root resolution that now follows it. README.md and references/ledger-contract.md were aligned to say the claim happens first rather than merely at preflight. Verified: 200 helper tests and 5 repository tests pass, versions agree at 1.13.0, archives build, ledger validation and git diff --check pass. Note for the next session: this changes shipped SKILL.md prose, so installed copies will not see it until the version triple is bumped and released; no release was requested.

## 2026-09-09 - Move the viewer shortcut off Codex image paste (owner: Daedalus)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Support Ctrl+Alt+H in the iTerm2 installer and replace previous Handoff keys for the same repository.
- [x] Update shortcut guidance and verify migration with regression tests and repository checks.
- [x] Apply the local shortcut change and record the handoff.

Status: In progress. Ctrl+V currently opens the Handoff iTerm2 profile and intercepts Codex image paste. The user requests a different shortcut. Implement Ctrl+Alt+H (Control+Option+H on macOS), preserving unrelated bindings and removing the old binding only for this repository's viewer. Prior tasks are complete or superseded by later entries and releases; Bakunawa's completed uncommitted installer work is the starting point, preserved in /tmp/handoff-shortcut-cernunnos. No other agent is active in this thread; the demo GIF remains untouched. Transferred 2026-09-09 from Cernunnos to Daedalus at the user's explicit direction, because Cernunnos reached its context limit and can no longer continue. Cernunnos was not observed writing after 00:31:55; its Codex process (pids 80950/80951) was still resident when the transfer was recorded. Its uncommitted work is preserved at /tmp/handoff-takeover-daedalus-20260909-004135 (working copies, the full diff, git status, HEAD, and a copy of Cernunnos's own /tmp/handoff-shortcut-cernunnos). Completed 2026-09-09 by Daedalus. The installer work Cernunnos left in the working tree was audited rather than redone: handoff_keys.py labels and encodes C-M-<letter> as Control+Option (0xc0000), and retires only global mappings whose action opens this repository's own viewer profile, so switching the key releases the previous one. Applied it with HANDOFF_VIEWER_KEY=C-M-h against this checkout. Verified by reading macOS preferences back: GlobalKeyMap now holds 0x68-0xc0000 -> Action 26 for profile 78db3b8a-002d-59be-891a-52375a4c34ad, the former 0x76-0x40000 (Ctrl+V) mapping is gone so Codex image paste is free, and the unrelated 0xd-0x20000-0x24 binding is unchanged. The profile's exact command, /usr/local/bin/python3 /Users/divij/.local/bin/handoff-tui --root /Users/divij/code/handoff-skill, rendered the live ledger when run directly. Verified: 200 helper tests and 5 repository tests pass, versions agree at 1.13.0, archives build, ledger validation and git diff --check pass. Not verified: the physical keystroke in the user's running iTerm2, which may need an iTerm2 restart to reload its keymap. Source changes remain uncommitted and no release was requested; a release would need the version triple bumped.

## 2026-09-09 - Fix the viewer shortcut opening Cursor in Codex (owner: Bakunawa)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Correct the iTerm2 shortcut installer and the Codex shortcut guidance.
- [x] Apply a working viewer shortcut to the local setup.
- [x] Verify the key path, run the repository checks, and record the handoff.

Status: Complete. The user reported Ctrl+V opening Cursor from plain Codex
0.153.4. Codex documents Ctrl+G as its external-editor key and ~/.zshrc sets
VISUAL to cursor --wait; no clarification arrived, so the installed shortcut
uses the requested Ctrl+V. The former iTerm2 installer only wrote an invalid,
unimported preset with Action 12 (Send Text). It now creates a dynamic viewer
profile and merges Action 26 (New Window with Profile) into GlobalKeyMap,
using valid numeric key encoding. It saves a private preference backup,
preserves existing shortcuts, refuses conflicting bindings or malformed input,
and writes a valid .itermkeymap fallback. README, SKILL.md, and harness setup
now state that plain Codex claims Ctrl+G and that the skill alone binds no key.

Applied the corrected installer from this checkout with HANDOFF_VIEWER_KEY=C-v
and --root /Users/divij/code/handoff-skill. The key is pinned to this repository.
Backup: ~/.config/handoff/iterm2-before-viewer-key.plist. The dynamic profile
uses explicit Python to run ~/.local/bin/handoff-tui, which resolves the
installed viewer across skill upgrades. Reading macOS preferences back proved
0x76-0x40000 selects the generated profile and every pre-existing global
shortcut remains identical. macOS preference writes required elevated execution
because the sandbox denied them; the authorized install succeeded.

Verified: 195 helper tests and 5 repository tests pass, versions agree at
1.13.0, archives build, ledger validation and git diff --check pass. The exact
profile command rendered the live ledger in a tool-managed terminal, and q
exited with status 0. An earlier hand-built PTY test rendered the ledger but
stalled during exit; the managed-terminal check verified input and clean exit.
Not verified: the physical shortcut in the user's running iTerm2 window,
because desktop automation denies iTerm2 access. An existing window may need
an iTerm2 restart to reload its keymap; no user sessions were restarted.
Source changes are uncommitted; no release was requested. The previous tasks
are completed or superseded by later releases, and the untracked demo GIF is
untouched. No further implementation work remains for this fix.

## 2026-09-08 - Commit and release 1.13.0 (owner: Airavata)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Bump the version triple to 1.13.0 and run the release checks.
- [x] Commit on a branch, open a pull request, and merge after CI passes.
- [x] Tag v1.13.0 and confirm the published release.
- [x] Run the repository checks and record the handoff.

Status: Complete. Released at the user's direction. Version triple moved to
1.13.0 and `check_versions.py v1.13.0` agrees. Verified before tagging: 188
helper, viewer, launcher, bar, codex, and keys tests and 5 repository tests
pass, `validate --root .` exits 0, archives build, and `git diff --check` is
clean. PR #6 passed all four CI legs (ubuntu and windows, Python 3.9 and 3.12,
run 34198063536) and was squash-merged as `2a257ea`. Tag `v1.13.0` pushed;
release workflow run 34198194734 succeeded and the GitHub release published at
07:12Z with `handoff.zip`, `handoff.skill`, and `SHA256SUMS`. The built archive
carries 13 files, `handoff/SKILL.md` reports 1.13.0, and includes
`handoff_keys.py`, so FCFS session naming, `/handoff:view`, and per-emulator
key installation now reach installed copies. Staged by explicit path throughout;
the untracked `scripts/demo/handoff-opt.gif` stays with its earlier entry. Next
action: none. An installed plugin copy needs `/plugin marketplace update
divij-skills` before it sees 1.13.0.

## 2026-09-08 - Hand out session names in alphabetical order, first come first served (owner: Heimdall)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Replace the per-seed hash ordering in name_order with a first-come-first-served order that cycles initials A to Z and wraps: the first session claims the first free A name, the next the first free B name, and so on, starting over at the next free A name after Z (skills/handoff/scripts/handoff_guard.py).
- [x] Update the naming regression tests for alphabetical first-come-first-served order (skills/handoff/tests/test_handoff_guard.py).
- [x] Update the documentation that describes per-session hash ordering.
- [x] Run the repository checks and record the handoff.

Status: Complete. Finished by Airavata at the user's direction after `origin/main`
was already up to date at `c82bb46`. Replaced `name_order(seed)` with a locked
`fcfs-slot` counter and `name_for_slot`, which cycles initials A through Z and
skips exhausted letters such as W. The first two unrecorded sessions now receive
`Airavata` then `Bakunawa`; slot 26 wraps back to the next free A name. Updated
README.md, `references/ledger-contract.md`, and the naming regression tests,
including FCFS wrap and stale-claim cases. Verified: 188 helper, viewer,
launcher, bar, codex, and keys tests and 5 repository tests pass,
`validate --root .` exits 0, versions agree at 1.12.0, archives build, and
`git diff --check` is clean. Not done: nothing is committed; this reaches no
installed copy until the next release.

## 2026-09-08 - Commit and release 1.12.0 (owner: Zahhak)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Rebase or merge origin/main into bar-viewer-key-and-session-names and bump the version triple to 1.12.0.
- [x] Push the branch, open a pull request, and merge after CI passes.
- [x] Tag v1.12.0 and confirm the published release.
- [x] Run the repository checks and record the handoff.

Status: Complete. Released at the user's direction, closing the "not merged, version triple left at 1.11.1" lines the three entries below carried. Merging origin/main into the branch raised a ledger conflict with the README scope-claim entry (#4); resolved by keeping both new entries newest-first rather than dropping either side. Version triple moved to 1.12.0 and check_versions.py agrees. Verified before tagging: 179 helper, viewer, launcher, bar and codex tests and 5 repository tests pass, validate --root . exits 0, archives build, git diff --check is clean. PR #5 passed all four CI legs (ubuntu and windows, Python 3.9 and 3.12, run 34190002499) and was squash-merged as 4d66f15. Tag v1.12.0 pushed; release workflow run 34190148803 succeeded and the GitHub release published at 05:19Z with handoff.zip, handoff.skill, and SHA256SUMS. The downloaded archive was inspected: handoff/SKILL.md reports 1.12.0 and the zip carries the expected 12 files, so the any-agent wrapper, session naming, and the Ctrl-G viewer key now reach installed copies. Staged by explicit path throughout; the untracked scripts/demo/handoff-opt.gif stays with its earlier entry. Left for the next release, per the user's choice to ship now: the pending viewer-key task this session owns. Next action: none. An installed plugin copy needs /plugin marketplace update divij-skills before it sees 1.12.0.
## 2026-09-08 - Make the viewer key work without the tmux wrapper (owner: Zahhak)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add a /handoff:view slash command that opens the viewer with no setup and no wrapper (commands/view.md).
- [x] Replace --install-viewer-key with an installer that writes a binding that actually fires, per emulator (skills/handoff/scripts/handoff_keys.py).
- [x] Cover the installer and the refusals with regression tests.
- [x] Document the shortcut honestly and run the repository checks.

Status: Complete. Finished by Airavata at the user's direction, closing the gap
this entry opened in 1.12.0. Added `commands/view.md`, which opens the live
viewer in a real terminal because command sessions have no curses surface, and
`skills/handoff/scripts/handoff_keys.py`, which `--install-viewer-key` now
calls with `--emulator auto|claude|kitty|wezterm|iterm2`. Claude Code still
cannot bind a key to run a command, so that path only releases `ctrl+g` and
states the limit honestly; kitty, wezterm, and iTerm2 receive config snippets
that run `handoff_tui`, and iTerm2 ships a JSON preset to import. Documented
the split in README.md, `SKILL.md`, `references/harness-setup.md`, and
`references/progress-viewer.md`. Verified: 188 helper, viewer, launcher, bar,
codex, and keys tests and 5 repository tests pass, `validate --root .` exits 0,
versions agree at 1.12.0, archives build with `handoff_keys.py` in the
allowlist, and `git diff --check` is clean. Not verified: no live kitty,
wezterm, or iTerm2 session was driven; only the written snippets and Claude
release path were exercised. Not done: nothing is committed; this reaches no
installed copy until the next release.
Reassigned 2026-09-08: moved from Sobek to Chiron in the handoff viewer at the
user's direction. No state or step boxes were changed, and the entry keeps its
place in ledger order.
Reassigned 2026-09-08: moved from Chiron to Zahhak in the handoff viewer at the
user's direction. No state or step boxes were changed, and the entry keeps its
place in ledger order.

## 2026-09-08 - Correct the README scope claim that 1.11.0 falsified (owner: Claude session handoff-skill-b5)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Narrow the scope sentence so it matches the shipped takeover protocol (README.md).
- [x] Run repository checks and record verification.

Status: Complete. The user asked to update the README. Audited it before writing anything, and no feature was missing: `--codex` is documented under `Codex with the bar`, and the viewer's `x`/`p` handoff and `--read-only` under the dashboard section. The real defect was a contradiction 1.11.0 introduced and 1.11.1 did not fix. `## Scope` claimed Handoff "does not authorize an agent to take over another agent's work", which was true before that release and is now contradicted by the same file's own dashboard section describing a bucket takeover, and by `SKILL.md`, which ships `Authorized takeover of another agent's bucket`. Narrowed rather than deleted, because the constraint did not disappear, only its scope: an agent still may not take over on its own initiative, and a takeover needs the user's explicit direction, a stopped prior owner, preserved uncommitted work, and a recorded transfer. Worked on a branch in a separate worktree rather than the shared checkout: while this edit was in progress a live Codex session moved that checkout onto `viewer-move-feedback` and committed a 1.11.1 release, so the first attempt landed on that branch by accident; both changes were saved, reverted there so that session's tree was left exactly as it was, and reapplied from `origin/main`. That session's work has since reached main as `d815782` and `cc6f51d`, and this branch was rebuilt on top of it rather than hand-resolving the ledger conflict the two entries created. Verified after the rebuild: 5 repository tests pass, `validate --root .` exits 0, `git diff --check` is clean, and versions agree at 1.11.1. The helper suite was not rerun, because no helper code changed.

## 2026-09-08 - Open the viewer with Ctrl-G from any agent session (owner: Chiron)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Generalise the Codex bar into an any-agent wrapper so claude, codex, kimi and grok all run under it (skills/handoff/scripts/handoff_codex.py, handoff_tui.py).
- [x] Install a host keybinding override so Ctrl-G stops reaching the host's own action (~/.claude/keybindings.json).
- [x] Have the skill ensure the override at preflight (skills/handoff/SKILL.md, references/harness-setup.md).
- [x] Cover the wrapper, the key and the override with regression tests.
- [x] Document the shortcut and run the repository checks.

Status: Complete. The user pressed `Ctrl-G` in Claude Code and Cursor opened,
and asked for one key that opens the viewer from Claude, Codex, Kimi or Grok.
The cause was not a defect: `Ctrl-G` is bound in the private tmux session
`--codex` creates, so it existed only around Codex, and in Claude Code
`ctrl+g` is its own `chat:externalEditor`, which launches whatever editor is on
PATH. No harness can fix this from its own configuration - Claude Code's
`keybindings.json` accepts only its fixed `chat:`/`app:` actions, with no
run-a-command action - so the fix is the tmux root table, which resolves the
key before the wrapped agent sees it, plus releasing the key in the host for
sessions that are not wrapped.

`Ctrl-G` was kept after checking the alternatives rather than by default: it is
ASCII BEL, so unlike `Ctrl-H`/`Ctrl-I`/`Ctrl-M` it aliases no terminal key,
unlike `Ctrl-C`/`Ctrl-Z`/`Ctrl-\` carries no signal, unlike `Ctrl-S`/`Ctrl-Q`
is not flow control, and Codex does not use it. Function keys lose to macOS
media keys by default and `Alt` keys to iTerm2's Option handling, so both were
rejected; `Ctrl-Y` and `Ctrl-K` are free in Claude Code and Codex and remain
available through `$HANDOFF_VIEWER_KEY`. Kimi and Grok string-match nearly the
whole control alphabet, which is a bundled keymap table rather than evidence of
real bindings, so neither was used as a constraint - the wrapper shadows the key
from them regardless.

Changes: `run_codex` became `run_agent(..., agent=)` and `CodexSession` became
`AgentSession`, since nothing in the footer, the binding or the exit shim was
ever Codex-specific; `run_codex` remains as a wrapper so `--codex` keeps
working, and the diagnostics now name the agent the user asked for. `--with
<agent>` is the new flag and `--codex` is `--with codex`. `--install-viewer-key`
writes `~/.claude/keybindings.json`, releasing `ctrl+g` and moving
`chat:externalEditor` to `ctrl+e`, the alternative Claude Code's own docs use;
it merges rather than replaces, is idempotent, and refuses to rewrite a file
that does not parse, because the user's own bindings live there. Only control
keys get a host spelling: `M-` and function keys have host names too, but the
harnesses disagree about them and a wrong guess writes a binding that silently
never fires.

The module keeps the filename `handoff_codex.py` deliberately. Renaming a
shipped runtime file means moving `RUNTIME_FILES`, `tests/test_package.py`, the
import and the test module together, which is churn this change does not need;
the symbols inside it now carry the general names.

Verified: 179 helper, viewer, launcher, bar and codex tests and 5 repository
tests pass, `validate --root .` exits 0, versions agree at 1.11.1, archives
build, and `git diff --check` is clean. End to end on tmux 3.6a through a sized
pty, a stand-in CLI named `myagent` - deliberately not `codex` - ran under
`--with`, its banner reached the pane, the bar showed `0/1 tasks` and the
`^G open` hint, a real `Ctrl-G` byte opened the viewer, `q` closed it, and the
agent was still running afterwards. `--install-viewer-key` was run against the
user's real `~/.claude/keybindings.json`, which did not previously exist, and
re-running it reported the key already released. Not verified: no live Claude,
Kimi or Grok CLI was driven under `--with`, only a stand-in child, and the
override was not exercised against a pre-existing hand-written keybindings file
outside the tests. Not done: the version triple is deliberately left at 1.11.1
for whoever cuts the next release, so this reaches no installed copy until
then.

## 2026-09-08 - Give every session a mythological name (owner: Claude session 01N7DGVQ)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add a read-only `name` subcommand to `handoff_guard.py` carrying 100 names from mythologies worldwide.
- [x] Return a name no ledger owner already holds, stable for a given session seed.
- [x] Instruct the skill to claim a name at preflight and use it as its owner label (`SKILL.md`, `references/ledger-contract.md`).
- [x] Cover naming with tests, document it, and run the repository checks.

Status: Complete. Sessions previously invented their own owner labels, which is
why this ledger carries `Codex`, `Codex TUI session`, and six different `Claude
session <id>` spellings; the user asked that a repository with the skill
installed name every session instead. `handoff_guard.py name` is a new
read-only subcommand carrying 100 single-word ASCII names from nineteen
traditions worldwide, from Greek and Norse through Mesopotamian, Japanese,
Pacific, Mesoamerican, Andean and African. ASCII and single-word is a
constraint, not a preference: the label passes through headings, tmux status
formats, and clipped viewer columns. The roster is ordered per session by
`sha256(seed + name)` rather than `random.shuffle`, so the order does not
depend on a random module's internals staying stable between Python versions,
and it skips every name an owner in that ledger already holds - completed
entries included, since reusing a retired owner's name makes the history
ambiguous. The assignment is remembered in a cache file keyed by seed and
ledger under `$TMPDIR/handoff-names-<uid>` (`$HANDOFF_NAME_CACHE` moves it):
without it, an agent re-running preflight after recording its own entry would
be handed a second name and its own work would read as a peer's. Claims
younger than 12 hours also reserve their names, so two sessions that have not
written entries yet cannot pick the same one, while older claims stop
reserving so a busy machine does not exhaust the roster; an unwritable cache
costs stability across calls, not the name. The seed is `--seed`, then
`$HANDOFF_SESSION`, `$CLAUDE_CODE_SESSION_ID`, `$TERM_SESSION_ID`, then random,
so an unidentified session is distinct rather than sharing everyone's first
name. Wiring: `SKILL.md` Step 0 gained a numbered claim step and its template
example now takes the owner from the command; `references/ledger-contract.md`
carries the rule agents read before writing; the README documents the command
and its example ledger now shows a named owner; `evals/evals.json` gained
scenario 5 for the behaviour - a scenario only, not a run or a result. No new
runtime file, so the packaging allowlist is unchanged. Verified: 171 helper,
viewer, launcher, bar and codex tests and 5 repository tests pass on Python
3.9.10 and 3.12.7, `validate --root .` exits 0, versions agree at 1.11.1,
archives build, and `git diff --check` is clean. End to end in a scratch
repository, two sessions were named `Jatayu` and `Thoth`, the first kept
`Jatayu` when it asked again after writing its entry, and the dashboard
grouped both. One defect was found in my own tests and fixed rather than
retried: the in-process cases read `$HANDOFF_NAME_CACHE` from the real
environment and wrote six claim records into the developer's `$TMPDIR`; the
suite now isolates the variable in `setUp`, and those files were removed. Not
done: this session's own two entries keep the `Claude session 01N7DGVQ` label
they were opened under, because renaming mid-task is precisely what the new
contract forbids - the next session in this repository is the first to be
named. Committed in `1f84573` on
`bar-viewer-key-and-session-names`, which is not merged into `main`; the
version triple is deliberately left at 1.11.1 for whoever cuts the next
release, so neither this nor the Ctrl-G shortcut reaches an installed copy
until then.

## 2026-09-08 - Open the viewer from the Codex bar with Ctrl-G (owner: Claude session 01N7DGVQ)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Bind a configurable root-table key in the Codex tmux session that opens the live viewer in a popup (`skills/handoff/scripts/handoff_codex.py`).
- [x] Advertise the shortcut in the bottom bar and carry `--read-only` into the popup.
- [x] Cover the binding, its configuration, and the hint with regression tests.
- [x] Document the shortcut and run the repository checks.

Status: Complete. The bar reported progress but could not change it, so the
user asked for a key that opens the viewer in the session. `Ctrl-G` now opens
the live view in a tmux popup over Codex, with the same `x`/`p` move keys, and
`q` returns to the Codex prompt with Codex still running underneath. The
binding is a root-table one, which is what the private session's disabled
prefix requires, and it is the only key Codex no longer receives;
`$HANDOFF_VIEWER_KEY` moves it to another tmux key name or takes it back with
`none`. The popup opens the ledger the bar is reporting, at the same
`--interval`, and `--read-only` now reaches Codex mode so a read-only bar opens
a viewer that cannot write. `CodexSession.call` was split over a new `run` so
the binding can be attempted without `check=True` killing the session:
`bind_viewer` returns whether tmux accepted it, and a tmux that rejects the
command or the key name leaves Codex running and drops the `^G open` hint
instead of advertising a dead key. The hint is appended after `clean_text`, so
a ledger owner label cannot forge one. Verified: 159 helper, viewer, launcher,
bar and codex tests and 5 repository tests pass, `validate --root .` exits 0,
versions agree at 1.11.1, and `git diff --check` is clean. Beyond the unit and
real-tmux tests, the keypress path itself was driven end to end on tmux 3.6a:
a client attached on a pty, `Ctrl-G` written to it, the viewer confirmed
running by pid from a popup, `q` confirmed to end that pid, and the Codex pane
confirmed alive afterwards (`pane_dead` 0). Not verified: no live Codex CLI
session was driven, only a stand-in child, and the popup was not exercised on
tmux 3.2 itself. Committed in `1f84573` on
`bar-viewer-key-and-session-names`, which is not merged into `main`. Not done:
the version triple is deliberately left at 1.11.1 for whoever cuts the next
release, so this reaches no installed copy until then.

## 2026-09-08 - Commit and release 1.11.1 (owner: Claude session 01Gjkh6S)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Bump the version triple and run the release checks.
- [x] Commit on a branch, open a pull request, and merge after CI passes.
- [x] Tag v1.11.1 and confirm the published release.

Status: Complete. Released at the user's direction, and this entry resolves the
`Not done: nothing is committed` line in `Show where a moved task landed in the
viewer` above, which was true when written. Chose a patch bump: the change fixes
a defect in a feature 1.11.0 already shipped rather than adding scope, though it
does alter one visible behaviour, the view moving to the receiving agent's list
after a paste, which the release notes state. Version triple moved to 1.11.1 and
`check_versions.py v1.11.1` agrees. Not committed directly to main: the work
went to branch `viewer-move-feedback` and PR #3, all four CI legs passed
(ubuntu and windows, Python 3.9 and 3.12, run 34186017598), and it was
squash-merged as `d815782`. Tag `v1.11.1` (annotated `e84e78e`) points at that
commit; release workflow run 34186126926 succeeded and the GitHub release
published at 04:12Z with `handoff.zip`, `handoff.skill`, and `SHA256SUMS`. The
built archive was inspected before tagging and carries `show_landing`, the
`MOVED to` status line, the updated `references/progress-viewer.md`, and version
1.11.1, so the fix reaches installed copies rather than only this tree. Staged
by explicit path: no other session's work was swept in. Left untouched
deliberately: the untracked `scripts/demo/handoff-opt.gif`, which belongs to an
earlier entry, and Claude session handoff-skill-b5's README correction, which
that session committed to branch `docs/scope-takeover` and has not merged. Next
action: none. An installed plugin copy needs `/plugin marketplace update
divij-skills` before it sees 1.11.1.

## 2026-09-08 - Show where a moved task landed in the viewer (owner: Claude session 01Gjkh6S)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Land the view on the receiving agent's task list with the moved task selected and marked.
- [x] Lead the confirmation with the receiving agent and keep it legible at 64 and 80 columns.
- [x] Keep the outcome visible until the next cut or move instead of the next keypress.
- [x] Cover the three failures with regression tests, document the behaviour, and run repository checks.

Status: Complete. Each of the three reproduced failures has a fix and a
regression test that fails without it. The view now lands on the receiving
agent's task list after a successful move, with the moved task selected and
marked `+`, so the answer is the task sitting in that agent's list rather than a
sentence claiming it; the paste previously left the user in the Agents view,
where no task rows are drawn. The line above the footer now leads with the
receiving agent, `MOVED to <agent> | + <title>`, so a narrow terminal clips the
title rather than the name the user is checking; verified rendered at 64, 80,
and 100 columns. That line is held in new `Dashboard.moved` state until the next
cut or move instead of the `message` channel that `handle_key` clears on the
next keypress, so navigating to check no longer erases the outcome. The record
is dropped if a peer deletes the task, and a new cut supersedes it. Verified:
150 helper, viewer, launcher, bar and codex tests and 5 repository tests pass on
Python 3.9.10 and 3.12, versions agree at 1.11.0, `validate --root .` exits 0,
archives build, and `git diff --check` is clean. The original reproduction was
re-run and now shows the receiving agent in the header, the marked task in its
list, and the full name in the banner both immediately and after a keypress.
Not verified: rendered through the test harness's fake screen, not a live curses
terminal. Not done: nothing is committed, and 1.11.0 is already released, so
this fix reaches no installed copy until a later version ships; the version
triple was deliberately left at 1.11.0 for whoever cuts that release. Next
action: none for this entry.

## 2026-09-08 - Commit and release 1.11.0 (owner: Claude session handoff-skill-b5)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Confirm the takeover-protocol entry is complete and its owner has verified it.
- [x] Commit the finished work with each change attributed to the session that wrote it.
- [x] Run the release checks and push the `v1.11.0` tag.

Status: Complete, and released, but the first attempt failed and the failure is the useful part of this record. `bf8a965` committed four sessions' work; `v1.11.0` on it failed the release build on Linux with `AssertionError: 1 != 7`, so nothing was published. Every local check had passed, because all of this code was untracked until that commit and CI had therefore never run it; the caveat recorded before the push, that the four-leg matrix had never exercised `handoff_codex.py`, is exactly what came true. CI was the only Linux available, so PR #2 first added diagnostics to the assertion rather than guessing, and the next run answered it: `tmux='tmux 3.4' raw_state='1:'`. Three defects followed, two of them real product bugs, not test problems. First, on tmux 3.4 a dead pane sets `pane_dead` but leaves `pane_dead_status` empty, so `exit_status` took its `else 1` branch and `handoff-tui --codex` reported exit 1 for every Codex run whatever Codex returned; macOS with tmux 3.6a populates the field, which is why it passed here and failed there. The pane shim now waits for Codex instead of exec'ing it, records the child's own status, and ignores SIGINT so Ctrl-C still reaches Codex alone. Second, two Codex tests compared rendered paths against POSIX string literals and failed on Windows. Third, fixing those let Windows reach the packaging suite for the first time, which exposed the broadest bug: Windows has no exec that replaces the running process, so `os.execv` spawned the viewer and the launcher exited 0, meaning every viewer failure had been reported as success on Windows since the launcher shipped in 1.5.0, including `--bar` in a status line and `--once`. The launcher now forwards the viewer's status there. Each fix carries a regression test starting from the failing case, including one that would have caught the launcher bug on either platform, where the existing launcher tests only ever compared stdout. Verified: PR #2 passed all four legs, was squash-merged as `376fca2`, and `v1.11.0` was moved from the failing commit to it, which was safe because the failed build published nothing and `gh release view v1.11.0` had reported no release. Release run 34184577404 succeeded and published `handoff.zip`, `handoff.skill`, and `SHA256SUMS` at 118661 bytes each for the archives; `v1.11.0` is now the latest release, replacing 1.9.1. Locally 127 helper, viewer, launcher, bar, and codex tests and 5 repository tests pass. Left undone deliberately: `scripts/demo/handoff-opt.gif` is still untracked, because no completed entry claims it and no owner has said what it is. Not verified: no live Codex session was driven through the released build; the end-to-end evidence is the real-tmux integration test plus a stand-in `codex` on macOS tmux 3.6a, and tmux 3.4 is now covered by CI rather than by hand.
## 2026-09-08 - Hand a task to another agent from the viewer (owner: Claude session 01Gjkh6S)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add cut and paste keys that reassign a task through one shared compare-and-swap.
- [x] Cover moves, refusals, and concurrent writes with regression tests.
- [x] Document the move, the read-only flag, and the viewer's changed write surface.
- [x] Run repository checks and record the handoff.

Status: Complete. The viewer can now hand one task to another agent: `x` cuts
the selected task, `p` gives it to the agent selected in the Agents view, to the
owner of the task under the cursor, or to the owner whose task list is open, and
`P` gives it to a typed name so a task can reach an agent with no ledger entry
yet. The write goes through `swap_ledger`, extracted from `apply` so both
writers share one lock, one version check, and one structural refusal rather
than growing a second write path; `apply`'s behaviour is unchanged and its
existing tests still pass. `reassign_task` rewrites only that heading's owner
label and appends a dated note naming the previous owner, and it identifies the
entry by line and heading together, so a stale position raises instead of
editing a neighbouring entry. Entries never move: ledger order records when work
was raised, the label records who holds it. A peer write after the cut is
refused as a conflict, the view reloads, and nothing is written; a task a peer
deleted is dropped rather than moved. `--read-only` disables the keys for a
terminal that must never write, and `--once`, `--bar` and `--codex` remain
read-only. Verified: 125 helper/viewer/launcher/bar/codex tests and 5 repository
tests pass on Python 3.9.10 and 3.12, versions agree at 1.11.0, ledger
validation, archive build, and whitespace checks pass; the cut, hold, type-a-
name, and applied-move frames were rendered and the resulting ledger re-parsed
to confirm state, steps, and order were untouched. Not verified: no run inside a
real curses terminal, so key delivery for `P` and Backspace is covered by the
fake-screen tests rather than a live session. Concurrent context: another
session was editing this working tree throughout, bumped the version triple to
1.11.0, and added a takeover convention to `ledger-contract.md`; this entry's
note wording was aligned to that convention and its uncommitted work was left
untouched. Next action: none for this task. Nothing here is committed; the tree
holds this work alongside that session's.

## 2026-09-08 - Write an agent takeover protocol (owner: Claude session 01Gjkh6S)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Define the takeover flow: user-authorized adoption of another agent's tasks and uncommitted work, building on the viewer handover (skills/handoff/SKILL.md).
- [x] Add a transfer annotation format so the moved-from owner sees the move when it returns (skills/handoff/references/ledger-contract.md).
- [x] Verify with repository checks and record the handoff.

Status: Complete. Adopted from Kimi session bb679340 at the user's direction and
finished by Claude session 01Gjkh6S; the transfer record is the paragraph above.
Audit at adoption, against the tree rather than the boxes: steps 1 and 2 were
already satisfied by the prior owner's uncommitted work and are checked here on
that evidence, not redone. `SKILL.md` carries `Authorized takeover of another
agent's bucket` with the four-step flow, and the `Coming back` rule telling a
returning owner that finds a transfer note naming it to report the move instead
of resuming. `references/ledger-contract.md` carries the transfer annotation
format and the returning-agent rule. Only the third step was outstanding. That
step's own protocol was exercised on itself while closing it, which is the
strongest evidence this entry has: the owner was not assumed stopped but
observed, its process (pid 10770) found alive, idle at its prompt in this
repository with `AGENTS.md` open, and its files and the ledger watched unchanged
for 80 seconds; this session stopped and reported the conflict rather than
adopting, exactly as step 1 requires, and resumed only after the user directed
the session to be ended and its exit was confirmed twice. The uncommitted work
was copied to a recovery point outside the tree before any edit, at
/private/tmp/claude-502/-Users-divij-code-handoff-skill/e270a92e-5b1d-494a-a9a1-5bd60bb447f1/scratchpad/recovery-2026-09-08-0853
(21 files, a 1739-line patch of tracked changes, and HEAD dc827ca), and the
bucket - one entry, enumerated rather than assumed - was moved in one locked
compare-and-swap using the helper's own `reassign_task`. One defect found and
fixed while verifying, outside this entry's steps and disclosed rather than
folded in: `CONTRIBUTING.md` still said the viewer and its launcher were
read-only and that `apply` was the one writer, which the viewer's task move had
falsified; it now names both write paths, `swap_ledger` as the single
compare-and-swap, and `--read-only`. The ledger records this same file drifting
the same way once before, so it is a recurring gap rather than a one-off.
Verified against the tree as it now stands: 125 helper, viewer, launcher, bar
and codex tests and 5 repository tests pass on Python 3.9.10 and 3.12, versions
agree at 1.11.0, `validate --root .` exits 0 with no structural errors, archives
build, and `git diff --check` is clean. Verified specifically for this entry,
because its deliverables ship: `dist/handoff.zip` contains 12 files and its
`SKILL.md` and `references/ledger-contract.md` carry the takeover section, the
`Coming back` rule, and the transfer format, so the protocol reaches an
installed copy rather than only this tree. Not done: nothing is committed, so
HEAD is still dc827ca and no installed copy has any of it. Next action: none for
this entry; the pending `Commit and release 1.11.0` entry above records the
release the user deferred, and its first step - confirming this entry complete
and verified - is now satisfied.

Taken over by Claude session 01Gjkh6S from Kimi session bb679340 on 2026-09-08
at the user's explicit direction, after Kimi session bb679340's process (pid
10770) was confirmed exited; that session's uncommitted work is preserved at
/private/tmp/claude-502/-Users-divij-code-handoff-
skill/e270a92e-5b1d-494a-a9a1-5bd60bb447f1/scratchpad/recovery-2026-09-08-0853.
Originally owned by Kimi session bb679340. Adopted assigned, not explained: its
two documentation steps are checked here against the tree they produced, and
only the verification step was outstanding at transfer.

Prior status, recorded by Kimi session bb679340 before the transfer and
restored here after this session's first closing write deleted it: "In
progress. Audited the ledger on intake: the Codex bar task was completed by
Claude session handoff-skill-b5 after the user stopped the Codex session, and
the ledger-reassignment feature it left behind is pending and unassigned;
neither blocks this documentation task. Current step: define the takeover flow
in SKILL.md." That reading was stale by the time of the transfer: the step it
names as current was already done in the working tree.


## 2026-09-08 - Test and document the ledger reassignment feature (owner: Claude session handoff-skill-b5)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Cover `reassign_task`, `replace_owner`, `owner_label_error`, `swap_ledger`, and the viewer's cut/paste move with regression tests.
- [x] Document the `x`/`p`/`P` keys and `--read-only` in `references/progress-viewer.md`.
- [x] Correct the three statements the feature falsified in that reference.
- [x] Run repository checks and record verification.

Status: Superseded as a task, kept as the verification record. Read `Hand a task to another agent from the viewer` (owner: Claude session 01Gjkh6S) above as the authoritative entry for this feature: that session requested and built it, and its entry carries the reason the user asked for it. This entry is not a competing claim. It was opened by this session at 07:45 on 2026-09-08, when the reassignment code sat uncommitted in the working tree with no ledger entry of any kind, having been left by the stopped Codex bar session; recording it was the only way to keep it from being read as part of the Codex bar task or lost at release. Session 01Gjkh6S recorded its own entry afterwards, which makes the two overlap, and that one wins on history. What is genuinely this session's and is not duplicated anywhere: the verification. Run against the tree after the tests and documentation landed, 125 helper, viewer, launcher, bar, and codex tests and 5 repository tests pass, versions agree at 1.11.0, `validate --root .` exits 0, archives build, and `git diff --check` is clean. That evidence satisfies the remaining step of the entry above, whose box is deliberately left unchecked here because it belongs to its owner, not to this session. Also corrected for the record: the third statement in this entry's step 3 needed no edit, because the minimum terminal height returned to 14 rows in `dashboard.draw`, which is what `references/progress-viewer.md` already said. Nothing here is committed; none of it reaches an installed copy until 1.11.0 is released.
## 2026-09-08 - Add a live Handoff bar around Codex (owner: Claude session handoff-skill-b5)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Check Codex's status-line surface and choose an integration.
- [x] Add Codex launch mode with a refreshing bottom bar and Codex skill discovery.
- [x] Cover launching, rendering, cleanup, and packaged execution with regression tests.
- [x] Document setup, run repository checks, and record verification.

Status: Complete. Implemented by the Codex bar session, which holds authorship of `skills/handoff/scripts/handoff_codex.py`, `skills/handoff/tests/test_handoff_codex.py`, and the launcher, viewer, packaging, and documentation changes this entry covers. That session was stopped at the user's explicit direction and this session took the task over on 2026-09-08 at 07:42, after confirming its process had exited and that no other writer held the tree; its uncommitted work was copied to a recovery point before any edit and none of it was rewritten. `handoff-tui --codex` runs Codex inside a private tmux server on its own socket, with `TMUX` and `TMUX_PANE` cleared so it nests inside an existing session, the prefix disabled so keys reach Codex, arguments passed base64-encoded through a Python `execv` shim so tmux's `;` parser cannot reinterpret them, and `remain-on-exit` set so Codex's own exit status is returned rather than the attach client's. The launcher gained `.agents` and `.codex` skill discovery, walking up to the first Git root, and a `usable()` gate so `--codex` skips installs that predate `handoff_codex.py`. Verification added by this session, closing the gap the previous status recorded: that session reported its sandbox rejected tmux sockets, but the failure reproduced here was only a socket path over the macOS length limit, and tmux 3.6a works normally in this session. `TmuxIntegrationTests`, which had been skipping, passes against a real pane, covering argument forwarding, typed input reaching the child, `#` format escaping, and exit status 7 propagating. A full end-to-end run with a stand-in `codex` on PATH rendered `handoff █████████░ 22/24 tasks · 90/96 steps · Codex, Codex bar session` on the bottom row while the child ran above it, with `resume --last` forwarded intact. Verified: 97 helper, viewer, launcher, bar, and codex tests and 5 repository tests pass, versions agree at 1.10.0, and `validate --root .` exits 0. Not done: nothing is committed or released, so no installed copy has `--codex`. Separately, that session had also begun a ledger-reassignment feature that none of this entry's steps covers; it is recorded as its own pending entry above rather than folded in here, because it is untested and its documentation is wrong. Next action: release 1.10.0, after deciding the reassignment entry.

## 2026-09-08 - Verify Grok and Kimi status lines and stop the bar waiting on stdin (owner: Claude session 01LD89UW)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Configure and observe the bar in live Grok and Kimi sessions.
- [x] Fix the blocking stdin read the verification exposed.
- [x] Record the verified matrix and the refresh behavior each host shows.
- [x] Run repository checks and record the handoff.

Status: Complete. Both remaining harnesses are now verified live, closing the gap the previous two entries recorded. Kimi Code 0.41.0: configured `~/.kimi-code/tui.toml` with `[status_line] command`, drove kimi under a pseudo-terminal, and captured the rendered footer, `context: 0% (0/256k) handoff █████████░ 21/22 tasks · 85/88 steps · Codex`; the row joins Kimi's own segments rather than replacing them, and `kimi doctor` reports the file valid. Grok CLI 1.0.13: confirmed by the user in their own terminal, after this session failed to drive Grok's interactive UI synthetically. That failure was diagnosed rather than assumed: a control run with the original config stalled at the same five bytes, so the `[ui.status_line]` block was not the cause, and `grok doctor` ran normally under the same harness, isolating the problem to Grok's interactive startup. The user reported the row appears after a few keypresses rather than on the first frame, which matches Grok's documented model: the row is event-driven on session state changes, with `refresh_interval` adding a timer on top. That observation is now documented, along with the workspace-trust gate, since `grok inspect` reports `Project trusted: no` for this directory. Verification also exposed a real defect: `handoff-bar` read its payload with `payload=$(cat)`, which waits for end of input, so a host that writes the payload and holds stdin open stalls the row until its own timeout. Measured against a FIFO whose writer stayed open six seconds, the old form took 6.1s and reading a single line takes 0.1s; all three hosts document a single-line JSON payload, and the working-directory fallback stays correct because hosts run the command in the session's directory. Added a regression test that fails if the bar waits for stdin to close. Verified: 80 helper/viewer/launcher/bar tests and 5 repository tests pass, versions agree at 1.9.1, ledger validation, archive build, and whitespace checks pass. Left in place on this machine: the status-line configuration in `~/.grok/config.toml` and `~/.kimi-code/tui.toml`, with backups beside each. Outstanding and unrelated: `grok inspect` lists three colliding `handoff` skills from leftover snapshot copies under `~/.agents/skills/handoff-workspace`, which no owner has been asked to remove.

## 2026-09-08 - Test on Windows and fix what it exposed (owner: Claude session 01LD89UW)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add windows-latest to the CI matrix.
- [x] Fix the product and test defects Windows CI reported.
- [x] Document the platform matrix and the portable status-line path.
- [x] Get all four matrix legs passing and record the handoff.

Status: Complete. Every Windows claim in this repository had been design intent read off the source: CI ran ubuntu-latest only, and the `msvcrt` lock branch carries `pragma: no cover - selected by platform`. Added `windows-latest` with `fail-fast: false`. It failed immediately and found four defects, one of them a real product bug. The product bug: `handoff_tui.py` wrote its output to a stdout that defaults to cp1252 on Windows, so `--once` and `--bar` raised `UnicodeEncodeError` and exited 1 — breaking the exact path documented as the portable Windows status line, and any ledger containing non-ASCII. Fixed by reconfiguring stdout to UTF-8 with `errors="replace"`, plus an ASCII glyph fallback in the bar when the stream still cannot encode block characters. That fix then exposed a second one: the suites decoded child output with the locale codepage, so Windows raised `UnicodeDecodeError` and left stdout `None`; every `subprocess.run` in both suites now decodes UTF-8 explicitly. The remaining three were POSIX-only test assumptions, skipped or adapted rather than weakened: `os.mkfifo` for parking a writer, permission bits Windows does not have, and 8.3 short temp paths, now compared resolved. Also added `.gitattributes` forcing LF, because a CRLF checkout breaks the shell scripts under Git Bash and WSL and changes ledger hashes. Documented the platform matrix in `references/harness-setup.md` and the README: the live curses dashboard cannot run on native Windows because stdlib Python ships no `curses` there, and `handoff-bar` needs POSIX `sh`; the portable status line on Windows is `python handoff_tui.py --bar`. Verified: all four CI legs pass (ubuntu and windows, Python 3.9 and 3.12) on run 34176454390; locally 79 helper/viewer/launcher/bar tests and 5 repository tests pass, versions agree at 1.9.0, ledger validation, archive build, and whitespace checks pass. Not verified: no live Windows agent session was run, so the Windows status-line configuration is documented from the host's own schema rather than observed; Grok and Kimi status lines remain unexercised in live sessions from the earlier entry. Next action: merge PR #1 and release 1.9.0.

## 2026-09-08 - Fix status-line viewer resolution in handoff-bar (owner: Claude session 01LD89UW)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Fix resolution so a current install beats an older leftover copy.
- [x] Add regression tests that run the script the way an installed copy runs.
- [x] Verify from the installed path and record the handoff.

Status: Complete. 1.8.0 shipped `handoff-bar` with a resolution bug that only appeared once the script was installed onto PATH. Its search loop assigned every existing candidate without breaking, so the last directory in the list won: `~/.agents/skills/handoff` here, holding a 1.0.0 snapshot with no `--bar` flag. That copy exited non-zero, the row came back empty, and the bar silently showed nothing. The repository tests missed it because they ran the script from its own scripts directory, where the sibling-viewer shortcut returns before the loop is reached; the same blind spot the launcher tests had. Fixed by resolving in priority order and breaking on the first hit, sorting the versioned plugin glob newest-first, requiring a candidate to contain `--bar` before accepting it, and caching the resolved viewer path separately from the row so the resolution cost is paid once rather than on every ledger change. Added three regression tests that copy the script to a PATH-like directory first: an old copy without `--bar` is skipped, the newest version wins over an older install, and a stale remembered path is replaced. Verified from the installed copy at `~/.local/bin/handoff-bar`: it now resolves the 1.8.0 plugin viewer and renders for both the nested `workspace.current_dir` and the flat `cwd` payload; 75 helper/viewer/launcher/bar tests and 5 repository tests pass, versions agree at 1.8.1, ledger validation, archive build, and whitespace checks pass, and steady-state cost is unchanged at about 32ms per cached run. Still unverified end to end: Grok and Kimi status lines, as recorded in the previous entry. Next action: release 1.8.1 so installed copies stop resolving a stale viewer.

## 2026-09-08 - Make the live progress bar work across agent harnesses (owner: Claude session 01LD89UW)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Determine which harnesses expose a status-line command hook and what payload each sends.
- [x] Add a status-line front-end fast enough for the strictest host budget.
- [x] Cover payload shapes, silence, and cache invalidation with tests.
- [x] Document per-harness setup and run repository checks.

Status: Complete. Surveyed the installed harnesses by reading shipped documentation or inspecting binaries on 2026-09-08: Claude Code 2.1.260 (`statusLine` command, `workspace.current_dir`/`cwd`, `refreshInterval`), Grok CLI 1.0.13 (`[ui.status_line] type = "command"`, same payload names, `refresh_interval`), and Kimi Code 0.41.0 (`[status_line] command` in `tui.toml`, flat `cwd`, first stdout line only, 300ms timeout) support a custom command. Codex CLI 0.153.4 exposes `status_line`/`status_line_use_colors` among TUI display toggles with no command hook found, opencode 1.18.3 has built-in segments only, and cursor-agent 2026.09.02 has none; these are recorded as "no hook found at that version" from binary inspection rather than as permanent limits. `--bar` already read both payload shapes, so no per-host parsing was needed. Added `skills/handoff/scripts/handoff-bar`, a POSIX sh front-end, because timing showed the existing path did not fit Kimi's budget: Python startup alone is about 100ms here and the Python launcher pays it twice, measured at 253ms against a 300ms cap. The bar caches the rendered row and starts Python only when the ledger changes, measured at 31ms per cached run against a 33KB ledger versus 136ms for the viewer alone. Its cache key is a `cksum` of the ledger contents, not modification time and size: a regression test proves a checkbox flip keeps the byte count identical (247 bytes before and after), so a size stamp would have served a stale row for exactly the edit this bar exists to show. Shipped both the script and `references/harness-setup.md` through the allowlist, with `handoff-bar` in `EXECUTABLE_FILES` at mode 0755. Verified on Python 3.9.10 and 3.12: 72 helper/viewer/launcher/bar tests and 5 repository tests pass, versions agree at 1.8.0, `claude plugin validate .` passes, `validate --root .` exits 0, archives build, whitespace clean; payload shapes, missing ledger, missing viewer, malformed stdin, cache reuse, and cache invalidation were each exercised. Not done and worth naming: the Grok and Kimi configurations are documented and their payload shapes are covered by tests, but neither was exercised inside a running Grok or Kimi session, so they are unverified end to end; a bar was installed only into Claude Code on this machine. Nothing is committed or released. Next action: release 1.8.0, then confirm the Grok and Kimi rows in live sessions and correct the matrix if a host disagrees.

## 2026-09-08 - Make /handoff:status show a live status-line bar (owner: Claude session 01LD89UW)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add a one-row status-line mode to the viewer.
- [x] Make the command install and remove the bar, keeping the snapshot report.
- [x] Cover the new mode with tests and document it.
- [x] Run repository checks and record the handoff.

Status: Complete. The previous `/handoff:status` could only print a snapshot, because Claude Code owns the terminal and curses has nowhere to draw. Claude Code's own status line is the right surface: a row at the bottom that re-runs a command, supports ANSI colour, and takes a `refreshInterval` (minimum 1s) that re-runs it on a timer even while the session is idle, which is exactly when peer agents write the ledger. Added `--bar` to `handoff_tui.py`, printing one row (`handoff █████████░ 17/18 tasks · 70/73 steps · Codex`) and exiting, plus `--no-color`. It reads the host's session JSON from stdin when stdin is not a terminal and takes `workspace.current_dir`, falling back to `cwd`, so the bar follows the session's directory; an explicit `--root`/`--file` still wins, and an unparsable payload is ignored rather than fatal. It is silent and exits 0 when there is no ledger or nothing tracked, so a status bar in an unrelated repository stays empty instead of showing an error; trailing names are owners of entries not recorded complete. Rewrote `commands/status.md`: it now installs `statusLine` pointing at the PATH launcher rather than a versioned plugin path, so the bar survives upgrades, refuses to overwrite a `statusLine` it did not add, accepts `off` to remove it, verifies by piping a sample payload before claiming success, and still reports the totals and per-owner table the bar has no room for. Verified: 60 helper/viewer/launcher tests and 5 repository tests pass, versions agree at 1.7.0, `claude plugin validate .` passes, `validate --root .` exits 0, archives build, whitespace clean; `--bar` was exercised for the plain, coloured, non-ledger, and malformed-stdin cases. Not done: nothing is committed or released, so no installed copy has `--bar` yet, and no `statusLine` has been written to this machine's settings. Next action: release 1.7.0 and update the plugin, then run the command to install the bar.

## 2026-09-08 - Add a /handoff:status command for recorded progress (owner: Claude session 01LD89UW)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add the command that reports recorded overall and per-owner progress.
- [x] Document it alongside the existing continue command.
- [x] Run repository checks and record the handoff.

Status: Complete. Added `commands/status.md`, giving `/handoff:status` next to the existing `/handoff:continue`. It runs the viewer's snapshot mode through the `handoff-tui` launcher, falling back to `$SKILL_DIR/scripts/handoff_tui.py`, and trims the output at the `TASKS (ledger order)` heading so the command returns the totals and the per-owner table rather than the whole ledger; unfiltered, this repository's snapshot is roughly 32KB. The command is read-only by construction: it forbids edits, `apply`, and starting work, and stops rather than creating a missing ledger. It states that the figures are recorded rather than effective, and points at `/handoff:continue` for the progressive audit, so the command cannot be read as contradicting the skill's central claim that a checkbox is not evidence. Deliberately not live: a command session has no controlling terminal, so curses cannot draw into it; the command says so and tells the user to run `handoff-tui` in their own terminal for the refreshing view with drilldown. Commands ship through the plugin rather than the `.skill` archive, so `RUNTIME_FILES` is unchanged; the version triple moved to 1.6.0 so installed copies are offered the update. Verified: 52 helper/viewer/launcher tests and 5 repository tests pass, versions agree at 1.6.0, `claude plugin validate .` passes, `validate --root .` exits 0, archives build, `git diff --check` is clean, and the documented pipeline was run against this repository, returning 17 lines. Not done: nothing is committed, tagged, or released, so the command does not yet exist in any installed copy. Next action: commit, push, and tag v1.6.0, then update the plugin, if the user wants the command available.

## 2026-09-08 - Ship a PATH-stable launcher for the progress viewer (owner: Claude session 01LD89UW)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add a launcher that resolves the viewer at run time instead of a version-pinned path.
- [x] Ship it in the release archives as an executable runtime file.
- [x] Cover resolution order, version ordering, and failure modes with tests.
- [x] Document the launcher and run the repository checks.

Status: Complete. The viewer's install path is version-pinned (`.../handoff/1.4.0/...`), so any command line naming it breaks at the next release. Added `skills/handoff/scripts/handoff-tui`, a stdlib-only launcher that resolves `handoff_tui.py` at run time and forwards every argument unchanged, plus its own `--which` for reporting the copy it chose. Resolution order is `$HANDOFF_TUI`, a sibling `handoff_tui.py`, the `installed_plugins.json` install, the plugin cache and marketplace globs, then `$HANDOFF_SKILL_REPO`; the sibling rule is deliberate, so a launcher run in place uses its own skill directory while one copied onto PATH tracks the newest install. Matching is keyed on the plugin name rather than the `divij-skills` marketplace, version directories are ordered numerically so 1.10.0 outranks 1.5.0, and `$CLAUDE_CONFIG_DIR` is honored. Packaging: added the launcher to `RUNTIME_FILES` and introduced `EXECUTABLE_FILES`, a fixed set shipped at mode 0755 so a copied launcher runs; the set is constant, so archives stay byte-reproducible, and a test now asserts both modes. Docs recommend copying rather than symlinking, since a symlink points back into the version-pinned directory the launcher exists to escape. Verified on Python 3.9.10 and 3.12: 64 helper/viewer/launcher tests and 5 repository tests pass, versions agree at 1.5.0, `validate --root .` exits 0, archives build, `git diff --check` is clean. Two of my own test assertions were wrong and were corrected rather than retried: one compared an unresolved temp path against the launcher's resolved `__file__` (macOS `/var` vs `/private/var`), and one compared two snapshots byte-for-byte though the header carries a clock time, which failed roughly one run in five; the repository suite now passes 15 consecutive runs. Not done: the launcher is not installed onto this machine's PATH by this change, and nothing is committed or published. Next action for a follow-up owner: none required; a user who wants the command runs the documented `cp` into a PATH directory.

## 2026-09-08 - Add a live terminal progress dashboard (owner: Codex TUI session)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Implement a read-only live TUI with overall, per-owner, and task progress.
- [x] Add regression coverage for counts, refresh, terminal behavior, and packaged execution.
- [x] Document usage and include the utility in release archives.
- [x] Run repository checks and record the handoff.

Status: Complete. Added skills/handoff/scripts/handoff_tui.py: a read-only curses dashboard with one-second polling, overall task and step progress, totals by recorded owner, owner-to-task drilldown, full step/status details, keyboard navigation, resize handling, stale-read recovery, and --once/pipe snapshots. Reuses the guard parser; invalid and legacy entries are excluded from totals, and the viewer explicitly distinguishes checkbox/heading attribution from verified completion, live activity, or per-step authorship. Documented controls and counting rules, included both runtime files in reproducible archives, and bumped all three version declarations to 1.4.0. Verified on Python 3.9.10: 40 helper/viewer tests and 5 repository tests pass, including execution of the extracted viewer; version agreement, ledger validation, archive build, and git diff --check pass. Real curses terminal verification covered task details, per-owner navigation, automatic refresh after the guarded ledger update (this task moved from 0/4 to 3/4), and clean exit. No model evaluations were run or claimed. Changes remain uncommitted; no publication requested. The pre-existing scripts/demo/handoff-opt.gif and earlier owners/history are untouched. No remaining implementation work for this request.

## 2026-09-07 - Record the two-agent demo GIF (owner: Cursor session)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Build the --handoff fixture and run session A (implement + commit).
- [x] Run session B (audit, verify, close entry).
- [x] Export cast/GIF, copy to scripts/demo/, verify checks, commit.

Status: Complete. Took over from Claude session divij-demo at the user's direction. `claude -p` remained blocked by the session limit (resets 12:20am IST), so both agent roles ran via `scripts/demo/record-two-agent.sh`: real code, commits, tests, and a `handoff_guard apply` ledger close — with comment-line narration and a three-line verdict on stdout instead of live `claude` UI. Recorded with `asciinema rec -c` after fixing `git log` pager hang and a compare-and-swap version conflict when the script wrote the ledger before `apply`. Exported with `agg` and `gifsicle`; result is 85K. Updated README caption for the two-agent scenario. Verified: 25 helper tests and 5 repository tests pass, version 1.3.0 agrees, `validate --root .` exits 0, `package_skill.py` builds, `git diff --check` clean. A future take can swap in live `claude` sessions without changing the fixture or shot list.

## 2026-09-07 - Make the demo narrate itself (owner: Claude session divij-demo)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Rewrite the shot list so each beat is labelled in the terminal (scripts/demo/RECORDING.md).
- [x] Update the VHS tape to match the narrated beats (scripts/demo/demo.tape).
- [x] Verify repository checks and commit.

Status: Complete. Two changes, after the user pointed out that a single agent auditing its own ledger demonstrates only half the skill. First, the terminal now narrates itself: each beat is introduced by a typed comment line, the whole ledger entry is shown instead of a `tail -5` fragment, and the clip ends held on the annotated diff via `--last-frame-duration 4`. Second, the scenario is now a real takeover. `make-fixture.sh --handoff` stops after the first commit so a live agent A implements the open step on camera and is interrupted mid-task, and a cold second session reads the ledger, declines to redo A's commit, verifies, and closes the entry; the unflagged fixture still builds the older single-session stale-box scenario. `demo.tape` matches the new beats. Also documented the lead-in trim as a cast edit rather than a lower `--idle-time-limit`, which compresses every pause and made the verdict unreadable when tried. Verified: both fixture modes build (`--handoff` stops at 4f25835; default reaches e5c6918), `bash -n` passes, 25 helper tests and 5 repository tests pass, ledger validation and whitespace checks pass. Re-recorded under the `Record the two-agent demo GIF` entry above; `handoff.cast` and `handoff.gif` now show the two-agent takeover.

## 2026-09-07 - Publish the demo GIF and README changes (owner: Claude session divij-demo)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Commit the pending README.md and HANDOFF.md changes from the prior sessions.
- [x] Push the demo cast, GIF, and README changes to origin/main.
- [x] Confirm the GIF renders on the public repository.

Status: Complete. Audited on 2026-09-07 by Cursor session at `/handoff continue`: `main` is clean and matches `origin/main` at `be6f336`. README embedding landed in `14d434d`; cast and GIF in `1582f52`; both are on the remote. Public GIF at `scripts/demo/handoff.gif` returns HTTP 200 (130178 bytes). The re-export trim attempt noted below was discarded and is unchanged. Re-recording the two-agent scenario is tracked in the entry above, not here.

## 2026-09-07 - Correct skill update instructions (owner: Codex review session)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Correct Claude Code auto-update setup and activation instructions in README.md.
- [x] Document project and global updates for skills CLI installations in README.md.
- [x] Verify the documentation and required repository checks, then record the handoff.

Status: Complete. README.md now explains how to enable auto-updates for the divij-skills marketplace and load updated plugins, refreshes the marketplace before the on-demand plugin update, and documents named skills CLI updates with -p from the original project and -g for global installs. Linked the official Claude Code and skills CLI documentation supporting these instructions. Verified: 25 helper tests and 5 repository tests pass; version agreement remains 1.3.0; ledger validation, archive packaging, and whitespace checks pass. Reviewed the diff and preserved the pre-existing README introduction edits and all older ledger entries. No installer or plugin update command was executed. Changes are uncommitted; no commit or publication was requested. No remaining work for this documentation fix. The demo recording tasks remain open with their existing owners and recorded blockers.

## 2026-09-07 - Finish the demo take and lead README with the problem (owner: Claude session handoff-skill-b5)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Verify the requested recording tools and remove the stale manual Claude skill copy.
- [x] Record the real fixture audit and export the source cast and optimized GIF.
- [x] Lead README.md with the problem and place the GIF above Install.
- [x] Run the required repository checks and record the handoff.

Status: Blocked after partial progress. Codex continued at the user's explicit direction, preserving the original Claude attribution and the pre-existing Kimi continuation below. README.md now opens with the stale-checklist problem. All four existing tools execute from ~/.local/bin (asciinema 2.4.0, agg 1.9.0, gifsicle 1.96, vhs 0.11.0), but the requested Homebrew install failed because this session cannot write Homebrew directories. Automatic approval review rejected forced removal; the safer `rm -r ~/.claude/skills/handoff` failed with Operation not permitted. That manual copy remains and reports 1.2.2. Built a separate fixture at /tmp/handoff-demo-codex-20260907, preserving the earlier /tmp/handoff-demo; its two commits are 4f25835 and e5c6918, its three tests pass, and its ledger validates. Claude's real audit preflight with the installed 1.3.0 plugin exited 1 with Not logged in; `claude auth status` reports loggedIn false and authMethod none. No cast or GIF was produced and no missing image was linked. Verified: 25 helper tests and 5 repository tests pass, versions agree at 1.3.0, archives build, and whitespace and ledger structure checks pass. Changes remain uncommitted. Next action: use a session with filesystem access to finish Homebrew installation and stale-copy removal, sign in to Claude, then record the five beats in scripts/demo/RECORDING.md against a clean fixture. Export and inspect the actual cast/GIF, retain both in the repository, and embed the GIF between the README introduction and Install. The original recording task's remaining capture, integration, and commit steps are still open; this entry records the current blockers rather than superseding its history. Annotation added 2026-09-07 by Claude session handoff-skill-94, which is not adopting or editing this task: the outcomes this entry was blocked on now exist. The recording, export, and README placement were completed under the `Record the README demo GIF` entry above and committed in `1582f52`; the two blockers named here no longer hold, because the tools are installed at `~/.local/bin` and the `claude -p` audit ran successfully in this session. The stale manual copy at `~/.claude/skills/handoff` and the Homebrew permission fix are both still outstanding. Checkboxes here are left for this entry's owner.
Reassigned 2026-09-08: moved from Codex to Claude session handoff-skill-b5 in
the handoff viewer at the user's direction. No state or step boxes were
changed, and the entry keeps its place in ledger order.

Resolved 2026-09-08 by Claude session handoff-skill-b5, which took this entry over after the user moved it from Codex in the live viewer; the dated line above is the viewer's mechanical record of that move, and this paragraph is the takeover and the audit behind it. Codex's uncommitted work is not at risk here: that session was stopped earlier today under the `Add a live Handoff bar around Codex` entry, and its tree was preserved to a recovery point then. No step was redone. Step-by-step evidence, audited against the tree rather than these boxes. The recording and export were completed under `Record the README demo GIF` and committed in `1582f52`, which added `scripts/demo/handoff.cast` and `scripts/demo/handoff.gif`. The README outcome was completed and committed in `14d434d`: `README.md` now opens with the stale-checklist problem and carries the GIF above `## Install`. All four tools this entry asked to verify run from `~/.local/bin`: asciinema, agg, gifsicle, and vhs. The stale-copy half of the first step is checked as obsolete rather than performed, and the distinction matters: the copy this entry objected to reported 1.2.2 and shadowed the plugin, and it no longer exists. What sits at `~/.claude/skills/handoff` today is a symlink to `~/.agents/skills/handoff`, a copy created on 2026-09-08 that reports 1.11.0, so it is current rather than stale and removing it was not done and should not be. The `handoff-workspace` snapshot copies named in a later entry are also gone. Outstanding but deliberately not tracked as a step here, because it never was one and this session cannot do it: the Homebrew fix in the prose above still needs `sudo chown -R divij /usr/local/share/man/man8`, and `ttyd` remains uninstalled behind it, so `vhs` cannot run. Neither blocks this entry, because the recording took the asciinema route `scripts/demo/RECORDING.md` prescribes and its output is committed. Verified for this closure: 127 helper, viewer, launcher, bar, and codex tests and 5 repository tests pass, versions agree at 1.11.0, and `validate --root .` exits 0.
## 2026-09-07 - Record the README demo GIF (owner: Claude session handoff-skill-94)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Install the recording tools `scripts/demo/RECORDING.md` names (asciinema, agg, gifsicle, vhs).
- [x] Record a real session against the demo fixture and export the GIF.
- [x] Reference the GIF from `README.md` and verify the repository checks.
- [x] Commit and record verification.

Status: Complete. Correcting the record first: this entry's owner, Claude session handoff-skill-94, has been active in this tree throughout, so the Kimi Code CLI session's status text asserting otherwise was wrong and is replaced here; its factual observations are kept below. Tools: Homebrew refuses to install anything in this environment because `/usr/local/share/man/man8` is root-owned and needs `sudo chown -R divij /usr/local/share/man/man8`, so the four tools were installed without it and all run from `~/.local/bin` - asciinema 2.4.0 (pipx), agg 1.9.0 and vhs 0.11.0 (upstream release binaries), gifsicle 1.96 (built from source). vhs additionally needs ttyd and ffmpeg, which are still missing and still blocked behind that same Homebrew fix, so the recording took the primary asciinema route as `RECORDING.md` prescribes. Recording: the fixture was rebuilt clean and the five beats ran unattended, with the audit itself a real `claude -p` session against `/tmp/handoff-demo` - it read the ledger, ran `python3 -m unittest test_search` rather than crediting the diff, named `e5c6918` as the commit that satisfied the open box, and annotated the entry instead of redoing the work, which beat 5 shows as a 28-line ledger diff. Two earlier takes were discarded and re-recorded rather than trimmed: one died under memory pressure, the other hung because `git diff` opened a pager, and its audit only reported without writing, so the prompt now asks for the audit and the update. Nothing in the agent's output was edited. Export: `agg --speed 1 --idle-time-limit 5` then `gifsicle -O3 --lossy=60 --colors 128`, with per-frame delays retimed so the audit frame holds 6 seconds; the result is 20.4 seconds and 127K, well under the 3 MB target. `scripts/demo/handoff.cast` is kept so the GIF can be re-rendered without re-recording. Verified: 25 helper tests and 5 packaging tests pass, `check_versions.py` reports 1.3.0, `validate --root .` exits 0, `package_skill.py` builds, and `git diff --check` is clean; the GIF was inspected frame by frame rather than assumed. Committed in `1582f52`, which stages only `scripts/demo/handoff.cast` and `scripts/demo/handoff.gif`. `README.md` now carries the GIF between the introduction and `## Install`, but it is left uncommitted on purpose: that file also holds Codex's introduction rewrite and its install-instruction corrections, and this ledger holds two other agents' entries, so staging either would sweep another owner's in-flight work into this session's commit. Whoever commits them should attribute those parts to their authors.

## 2026-09-07 - Add CLAUDE.md and commit the instruction files (owner: Claude session 01L6aEop)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Write CLAUDE.md covering commands and the architecture spanning several files.
- [x] Commit AGENTS.md and CLAUDE.md as separate changes, preserving authorship.
- [x] Verify the repository checks and record the handoff.

Status: Complete. Wrote `CLAUDE.md` in response to the user's `/init`: it defers to `AGENTS.md` for style and commit conventions rather than restating them, and documents the authority split between `SKILL.md` and the structural helper, the compare-and-swap design of `apply` with its exit codes, the version-triple and packaging-allowlist invariants CI enforces, and this repository's use of its own ledger. Committed in `ecd858f`. `AGENTS.md` was authored by Codex in an earlier session and left uncommitted; the user asked for it here, so it was committed unchanged and separately in `4e4e2ec`, with authorship stated in the commit body rather than absorbed into this session's work. Neither file is a runtime resource: both sit outside `RUNTIME_FILES` and outside the skill and command components, so no version bump or release was needed and `v1.3.0` is unaffected. Verified: 25 helper tests and 5 packaging tests pass, `check_versions.py` reports 1.3.0 agreeing, `validate --root .` exits 0, `package_skill.py` builds, and `git diff --check` is clean. Not pushed; the user asked only for commits. Next action for whoever continues: push `main`, and exercise `/continue` end to end, which remains untested from the earlier entry.

## 2026-09-07 - Add a /continue command that resumes ledger work (owner: Claude session 01L6aEop)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Add the slash command (`commands/continue.md`).
- [x] Bump the version triple so installed copies are offered the update.
- [x] Verify tests, version agreement, ledger validation, packaging, and whitespace.

Status: Complete. Added `commands/continue.md`, a plugin slash command that invokes this skill to audit the ledger and resume only the effective remainder. It refuses to create a ledger or invent scope, takes `$ARGUMENTS` as an optional task focus, and resolves ownership from evidence rather than the `In progress` label, stopping on a live owner or conflicting uncommitted work. It ships through the plugin path only: `marketplace.json` sets `source: "./"`, so the repository root is the plugin root, while `RUNTIME_FILES` in `scripts/package_skill.py` stays skill-runtime only because the ZIP targets hosts that have no slash commands. Version bumped 1.2.2 to 1.3.0 across `SKILL.md`, `plugin.json`, and `marketplace.json`. Verified: 25 helper tests and 5 packaging tests pass, `check_versions.py` reports 1.3.0 agreeing across all three files, `validate --root .` exits 0, `package_skill.py` builds the three artifacts, and `git diff --check` is clean. Not verified end to end: the command was never executed, because the installed plugin cache is 1.2.2 from the GitHub marketplace and does not load this working tree. Committed in `fe57e75` and tagged `v1.3.0` locally on `main`; not pushed, so installed copies remain on 1.2.2 and will not see `/continue` until the tag is pushed and the release workflow publishes the artifacts. Next action for whoever continues: push `main` and `v1.3.0`, then install the updated plugin and exercise `/continue` against a repository with a genuinely unfinished entry.

## 2026-09-07 - Add repository contributor guide (owner: Codex)

State:

- [x] In progress
- [x] Completed

Steps:

- [x] Inspect repository structure, contribution rules, and recent history.
- [x] Create AGENTS.md if absent with concise repository-specific guidance.
- [x] Verify the guide and record the handoff.

Status: Complete. Created the 382-word AGENTS.md contributor guide using exclusive file creation after confirming it was absent. Verified repository-specific paths and commands; 25 helper tests and 5 repository tests pass, versions agree, ledger validation passes, archives build, and whitespace checks are clean. No commit or publication requested. Earlier evaluation and release entries remain with Claude session divij-f8, whose activity is not observable through this session's agent list; their implementation commits are in current history and v1.2.2 exists locally, but current-skill evaluation results and remote release publication are not verified here. No implementation-file overlap; earlier entries are preserved. No remaining work for this guide. Committed unchanged later in `4e4e2ec` by Claude session 01L6aEop at the user's request; authorship remains Codex's.

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
- [x] Completed

Steps:

- [x] Serialize apply's read, version check, and replacement under an exclusive lock (skills/handoff/scripts/handoff_guard.py).
- [x] Read the payload before taking the lock so blocking input cannot stall peers.
- [x] Preserve the ledger's file mode across the atomic replace.
- [x] Add a read command binding audited text to its version in one snapshot.
- [x] Reject duplicate and contradictory task-level state checkboxes.
- [x] Add an overlapping-writer regression test and confirm it fails without the fix.
- [x] Correct the SKILL.md, README.md, and CONTRIBUTING.md claims about the guarantee.
- [x] Close the recheck findings: lock-requiring regression test and crash-safe fallback.
- [x] Commit, publish 1.2.2, and record verification.

Status: In progress. An external review of `781441f` reported that the 1.2.0 compare-and-swap was not atomic. Reproduced with two unmodified CLI processes: writer A parked reading a FIFO payload after its version check while writer B completed; both returned `applied` and exit 0 and A's replace discarded B's entry. The hash comparison was a check-then-act, not a compare-and-swap, because nothing serialized the sequence. `apply` now holds an exclusive lock on a `HANDOFF.md.lock` sidecar across the re-read, check, and replacement, and the same reproduction now returns exit 3 for A with both entries preserved after retry. The new regression test was confirmed to fail against `781441f`. Also fixed from the same review: `atomic_write` reset the ledger from 0644 to 0600 via `mkstemp`; `checkbox_value` returned the first match so contradictory duplicate state boxes validated clean; the documented preflight read the ledger and the version separately, which could bind an audit to a version it never saw; and `CONTRIBUTING.md` still called the helper read-only. Verified on Python 3.9 and 3.14: 24 helper tests and 5 packaging tests pass, validate passes, the archive builds. A recheck of `fa1d0f0` confirmed the three original findings fixed and raised two more, both reproduced here. First, the overlapping-writer test parked writer A while it read its payload, which now happens before the ledger read, so the test passed with `ledger_lock` removed and did not guard the serialization at all; a second test now parks A inside `atomic_write`, past the version check and holding the lock, and it fails when the lock is removed while the original test still passes. Second, the no-fcntl fallback acquired an exclusive-create lock file removed only in `finally`, so a writer killed mid-write stranded every later writer past the timeout; the fallback is now `msvcrt` on Windows and the command refuses to write at all when no OS lock primitive exists, since both real primitives are released by the OS on process death. Verified by killing a lock holder with `os._exit` inside the critical section: the next writer proceeded in 0s rather than timing out. Verified on Python 3.9 and 3.14: 25 helper tests and 5 packaging tests pass, validate passes, the archive builds. Next action is to commit and publish 1.2.2. The four scenario evaluations are unchanged and were not re-run; the earlier model scores must not be presented as 1.2.1 or 1.2.2 benchmark results. Closed on 2026-09-07 by the audit in Claude session handoff-skill-94: the final step is done. `fa1d0f0` and `3a6bffb` are in `main`, the remote tag `v1.2.2` points at `3a6bffb`, GitHub release `v1.2.2` published at 09:02Z from Release run 34103785217, and this status already records the verification. The evaluation caveat above still stands and is tracked in the guidance/release entry below.

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
- [x] Completed

Steps:

- [x] Apply conditional ordering, grounded planning, and concise output guidance.
- [x] Review helper and packaging behavior; expand and run behavioral evaluations.
- [x] Correct benchmark reporting and verify the final release archive.
- [x] Commit, publish the versioned release, and record verification.

Status: In progress. The prior publication task is complete and the starting tree is clean at `559edee`. Applying the five requested review changes. Failure cases: the unconditional pickup gate can block a new task with no unfinished work; the output rules prohibit creating new steps; saved evaluations repeat procedure and assume a list/table UI. Review also covers helper and archive behavior before a versioned release. Shell access to GitHub currently fails DNS resolution; publication access will be checked after preparing the release. Originally owned by Codex; Claude session divij-f8 took over the remaining steps 2-4 on 2026-09-07 at the user's explicit direction. Codex's liveness was never confirmed either way, so this is an authorized takeover, not an inactivity finding. Codex's uncommitted work was reviewed and retained unmodified: the CommonMark fence masking in `outside_fence_lines` now applies to all parsing rather than headings only (4 tests), evaluation 4 and `output_quality_expectations` were added to `skills/handoff/evals/evals.json`, and `scripts/summarize_evals.py` with `tests/test_evals.py` report benchmarks without estimating missing metrics. Step 2 is partially complete: evaluation content is expanded, but the only saved runs are in `~/code/handoff-skill-workspace/iteration-3`, contain no `grading.json`, and were produced against the `skill-snapshot-v1.1.0` copy, so they predate both this task's SKILL.md changes and the compare-and-swap task. Step 3 is split: the reporting code is correct and tested, but `scripts/summarize_evals.py` raises `FileNotFoundError` on those ungraded runs, so no benchmark exists; the release archive half is verified, building byte-identical twice (`1b7379e7836bed51297770b74289fa3d74d618034955fce12f15d7feec83741a`) and extracting to a working helper at version 1.2.0. Step 4 is partially complete: the work is committed in `0ba13d9` on branch `handoff-cas-and-guidance`, which is not yet merged to `main`, and no version tag or GitHub release was created and publication was not attempted. Next action is to re-run the four evaluations against the current skill, grade them, then generate the benchmark and decide on publication. Audited on 2026-09-07 by Claude session handoff-skill-94. Step 4 is now complete: `0ba13d9` is in `main` history, and tags `v1.2.2` and `v1.3.0` are pushed with both GitHub releases published (Release runs 34103785217 and 34118057548 succeeded). Steps 2 and 3 remain open only in their evaluation half. `~/code/handoff-skill-workspace/iteration-4`, written at 13:52 local, is a partial run, not a benchmark: 3 of its 6 run directories contain no `response.md`, no `grading.json` exists anywhere in the workspace, and its `provenance.json` names `with_skill` version 1.2.0 with a `SKILL.md` hash (`3a0282e9`) that does not match the shipped 1.3.0 file (`7aa52c3c`). No graded result exists for any released version, so none may be reported. Remaining outcome: run the four `evals.json` scenarios against 1.3.0, grade them, and summarize with `scripts/summarize_evals.py`. Resumed on 2026-09-07 by Claude session handoff-skill-94 at the user's direction, taking over that remainder from Claude session divij-f8, which the agent list shows as idle with no uncommitted work in this tree; earlier steps, attribution, and the rest of the entry are unchanged. Staged `~/code/handoff-skill-workspace/iteration-5` against the shipped 1.3.0 skill (`SKILL.md` `7aa52c3c`) and the 1.1.0 snapshot, three runs per configuration, 25 graded expectations per run. Complete. Six runs executed and graded, and `scripts/summarize_evals.py` wrote `benchmark.json` and `benchmark.md` in that workspace. Result over three suite runs per configuration: behavior 98% for both 1.3.0 and the 1.1.0 snapshot (each configuration lost one of 63 behavior expectations - 1.1.0 by writing `Implement search over the existing list view`, inventing a UI structure it had not observed; 1.3.0 by omitting a concrete verification step from a proposed search entry), and output quality 83% for 1.3.0 against 67% for 1.1.0, the difference coming entirely from repeatedly printing complete entries where a state transition would do. This is three runs per configuration graded by the orchestrating session against the 25 recorded expectations, not an independent benchmark: it is too small to establish variance, and behavior is indistinguishable between the two versions on this suite. Token usage and wall-clock time were not captured and are reported as unknown rather than estimated. Results live in the workspace, not this repository, because `evals.json` holds scenarios and not results.

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
