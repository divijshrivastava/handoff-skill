# Contributing

Keep `skills/handoff/SKILL.md` the runtime source of truth. Put conditional details in its references and keep the helper dependency-free. `doctor`, `validate`, `preflight`, `read`, and `template` are read-only, as are the viewer's `--once`, `--bar`, and `--codex` modes and the `handoff-tui` launcher. Four callers write the ledger: `apply`, `purge`, the channel's voluntary `yield`, and the live viewer's task move, which `--read-only` disables. All four go through the one compare-and-swap, `swap_ledger`, and any change to it must keep the read, version check, and replacement inside a single held lock; do not add a write path beside it. `purge` archives the replaced bytes under that lock, leaves `HANDOFF.md` in place as an empty valid ledger, and does not create a ledger where none exists.

Before changing the workflow, describe a concrete failure case. Preserve progressive history, explicit ownership, and the distinction between structural checks and evidence of completion. Add a regression test when helper behavior changes. Behavioral scenarios belong in `skills/handoff/evals/evals.json`; run them with `scripts/run_evals.py` and read `skills/handoff/evals/README.md` first, and do not report them as passing model evaluations unless they were actually run and graded. Adding or removing a scenario means changing `SUITE_SIZE` in `tests/test_evals.py` on purpose.

Run from the repository root:

```sh
python3 -m unittest discover -s skills/handoff/tests -v
python3 -m unittest discover -s tests -v
python3 skills/handoff/scripts/handoff_guard.py validate --root .
python3 scripts/package_skill.py
git diff --check
```

The release bundle deliberately includes only `SKILL.md`, `agents/openai.yaml`, `scripts/handoff_guard.py`, `scripts/handoff_channel.py`, `scripts/handoff_tui.py`, `scripts/handoff_codex.py`, `scripts/handoff-tui`, `scripts/handoff-bar`, referenced Markdown files, and the license. Update the explicit allowlist and packaging tests if you add a runtime resource. `EXECUTABLE_FILES` in `scripts/package_skill.py` is a fixed set shipped at mode 0755, so launchers work once copied onto PATH; keep it constant so archives stay byte-reproducible. Codex mode additionally needs tmux 3.2+; its real-terminal integration test skips on Windows, missing tmux, or a sandbox that forbids sockets.

## Skill descriptions

The always-visible `SKILL.md` description carries the activation cues and the
ordered guard `name`, `read`, and `apply --expect-version` sequence. A model that
does not load the body must still see how to avoid an unguarded ledger write.
Keep the longer activation explanation in the body. `tests/test_package.py`
checks the frontmatter alone for the literal commands, their order, and the
character limits; the existing CI suite runs those checks on Python 3.9 and 3.12.

The portable budget is 1,024 characters, measured on the decoded description,
with these source checks made on 2026-09-10:

| Target | Limit and evidence |
| --- | --- |
| Agent Skills format | [The specification](https://agentskills.io/specification#description-field) requires 1–1,024 characters. This is the shared authoring budget. |
| Claude Code, including plugin skills | [The skill frontmatter reference](https://code.claude.com/docs/en/skills#frontmatter-reference) documents truncation of the combined `description` and `when_to_use` listing text at 1,536 characters by default. This is a listing limit, not a documented loader rejection at 1,024; this skill has no `when_to_use`. User settings and the aggregate skill-listing budget can further restrict visibility. |
| Cursor | The bundled `~/.cursor/skills-cursor/create-skill/SKILL.md` metadata table specifies a 1,024-character maximum. [Cursor's public format reference](https://cursor.com/docs/skills#frontmatter-fields) describes the required field without a numeric cap. We follow the bundled authoring contract; runtime truncation or rejection was not independently established. |
| Vercel `skills` CLI | [`parseSkillMd`](https://github.com/vercel-labs/skills/blob/main/src/skills.ts) checks for a non-empty string and passes it through [`sanitizeMetadata`](https://github.com/vercel-labs/skills/blob/main/src/sanitize.ts), which removes terminal escapes and normalizes whitespace without truncation. That parser enforces no separate character cap; installation still targets hosts with their own limits. |

These values are constants in `DESCRIPTION_CHARACTER_LIMITS` in
`tests/test_package.py`; `None` records the absence of a CLI parser cap instead
of inventing one. Recheck the sources before changing the budget. The
`<repo>`, `V`, and `FILE` command arguments are placeholders for the repository,
the version returned by `read`, and the prepared ledger payload.

Plugin and marketplace descriptions retain the short capability sentence,
"Coordinate progressive repository work across agents with a shared HANDOFF.md
ledger." Their audience is browsing a listing; the procedure belongs in the
model-visible skill description. The manifest generator in requirement A must
preserve that choice rather than copy or truncate the procedure into a listing.
Task B's structural checks do not demonstrate a behavioral improvement; that
requires actual executed and graded evaluations under requirement C.

## Publish a release

1. Update `metadata.version` in `skills/handoff/SKILL.md`, then run
   `python3 scripts/sync_manifests.py` to write every manifest under
   `*-plugin/` from it. That is the only hand-edited version; do not edit a
   manifest directly. Document user-visible changes in the GitHub release notes.
2. Run the checks above, inspect the archive, and commit the release changes.
3. Push a tag matching the version, for example `v1.1.0` for version `1.1.0`.
4. The release workflow validates and builds before publishing `handoff.zip`, `handoff.skill`, and `SHA256SUMS`.

Archive bytes are reproducible for identical source bytes. This is a source skill package, not a Python distribution. No installation or setup command runs when it is packaged.

The local channel stores messages and reported capability in gitignored `.handoff/`. Only its `yield` operation changes task ownership, through `swap_ledger`. Claude plugin hooks live in root `hooks/hooks.json`; they ship through the plugin path, while the adapter and its reference ship in the allowlisted archives. Tests must distinguish an unavailable model from a resident process, and compaction from failure. Hook payload tests do not establish live provider quota exhaustion.
