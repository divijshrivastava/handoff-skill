# Repository Guidelines

## Project Structure & Module Organization

This repository ships an agent skill, not a Python distribution or web service.
`skills/handoff/SKILL.md` is the runtime source of truth; `references/` holds
workflow details, `agents/openai.yaml` holds host metadata, and
`scripts/handoff_guard.py` provides the ledger CLI within that skill directory.
Helper tests live in `skills/handoff/tests/`; repository packaging and evaluation
summary tests live in `tests/`. Root `scripts/` contains release utilities and
`scripts/demo/` contains recording assets. `.claude-plugin/` defines distribution
manifests; `.github/workflows/` defines CI and releases. Generated archives go
in ignored `dist/`. Root `commands/` holds one Markdown file per slash
command; manifests point at the directory, so adding a command needs no
manifest edit.

## Build, Test, and Development Commands

Use Python 3.9+ and run commands from the repository root. No third-party Python
packages or local server are required.

- `python3 -m unittest discover -s skills/handoff/tests -v`: test ledger parsing,
  validation, and concurrent writes.
- `python3 -m unittest discover -s tests -v`: test packaging and evaluation summaries.
- `python3 skills/handoff/scripts/handoff_guard.py validate --root .`: check
  ledger structure; this does not prove task completion.
- `python3 scripts/check_versions.py`: verify that the skill and every manifest
  under `*-plugin/` declare one version.
- `python3 scripts/sync_manifests.py`: write those manifests from
  `skills/handoff/SKILL.md`. `--check` writes nothing and fails on a difference.
- `python3 scripts/package_skill.py`: build reproducible `handoff.zip`,
  `handoff.skill`, and `SHA256SUMS` under `dist/`.
- `git diff --check`: catch whitespace errors.

## Coding Style & Naming Conventions

Follow existing Python style: four-space indentation, `snake_case` functions,
`UPPER_SNAKE_CASE` constants, and descriptive names. Use type annotations for
helper APIs and keep runtime code standard-library-only and Python 3.9 compatible.
Use concise Markdown instructions and fenced command examples. No dedicated
formatter or linter is configured.

## Testing Guidelines

Use `unittest`, with `test_*.py` files and `test_*` methods. Add regression tests
for helper behavior changes, starting from a concrete failure case. CI runs both
suites on Python 3.9 and 3.12; no numeric coverage threshold is configured.
Behavioral prompts live in `skills/handoff/evals/evals.json` and are executed by
`scripts/run_evals.py`, which is invoked by hand because model calls cost money
and are not reproducible; CI runs only its graders, schema validation, and suite-size
assertion. See `skills/handoff/evals/README.md`, and claim model results only for
scenarios actually run and graded.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects, matching history such as
“Serialize compare-and-swap writes and fix related defects.” Keep changes focused.
PR descriptions should explain the failure case, resulting behavior, and
verification commands and outcomes; link relevant issues when available.
When adding runtime resources, update the packaging allowlist and tests.

## Agent Workflow

Read `CONTRIBUTING.md` and audit `HANDOFF.md` against later entries and code before
resuming work. Preserve history and ownership; record steps and verification.
When agents share a working tree, use the helper's `read`/`apply` workflow for
ledger updates and re-audit after version conflicts.

A user assignment through `handoff-tui` is a required execution request for
every receiving agent. Finish the current task, then audit and complete assigned
work, including verification and publication when required, without another
prompt. Check your queue at task boundaries and before stopping. Record concrete
blockers and continue other eligible assignments; preserve prior work and owners.
