# Contributing

Keep `skills/handoff/SKILL.md` the runtime source of truth. Put conditional details in its references and keep the helper dependency-free. `doctor`, `validate`, `read`, and `template` and the standalone `handoff_tui.py` viewer and its `handoff-tui` launcher are read-only; `apply` is the one writer, and any change to it must keep the read, version check, and replacement inside a single held lock.

Before changing the workflow, describe a concrete failure case. Preserve progressive history, explicit ownership, and the distinction between structural checks and evidence of completion. Add a regression test when helper behavior changes. Behavioral scenarios belong in `skills/handoff/evals/evals.json`; do not report them as passing model evaluations unless they were actually run.

Run from the repository root:

```sh
python3 -m unittest discover -s skills/handoff/tests -v
python3 -m unittest discover -s tests -v
python3 skills/handoff/scripts/handoff_guard.py validate --root .
python3 scripts/package_skill.py
git diff --check
```

The release bundle deliberately includes only `SKILL.md`, `agents/openai.yaml`, `scripts/handoff_guard.py`, `scripts/handoff_tui.py`, `scripts/handoff-tui`, referenced Markdown files, and the license. Update the explicit allowlist and packaging tests if you add a runtime resource. `EXECUTABLE_FILES` in `scripts/package_skill.py` is a fixed set shipped at mode 0755, so launchers work once copied onto PATH; keep it constant so archives stay byte-reproducible.

## Publish a release

1. Update `metadata.version` in `skills/handoff/SKILL.md` and document user-visible changes in the GitHub release notes.
2. Run the checks above, inspect the archive, and commit the release changes.
3. Push a tag matching the version, for example `v1.1.0` for version `1.1.0`.
4. The release workflow validates and builds before publishing `handoff.zip`, `handoff.skill`, and `SHA256SUMS`.

Archive bytes are reproducible for identical source bytes. This is a source skill package, not a Python distribution. No installation or setup command runs when it is packaged.
