# Running the handoff evaluations

`evals.json` holds the scenarios. `../../../scripts/run_evals.py` executes them
against a harness CLI and writes graded runs; `../../../scripts/summarize_evals.py`
turns a workspace of those runs into `benchmark.json` and `benchmark.md`. The
runner produces input for the summarizer and replaces none of it.

None of this ships to users. The runner lives in the root `scripts/` directory,
is tested by the root `tests/`, and is deliberately absent from `RUNTIME_FILES`
in `scripts/package_skill.py`.

## Commands

```sh
python3 scripts/run_evals.py --list                     # enumerate scenarios
python3 scripts/run_evals.py --dry-run                  # expand the matrix, no model calls
python3 scripts/run_evals.py --command 'claude -p --output-format json' \
    --scenarios 1,7 --config with_skill,without_skill --runs 3 --workspace ws
python3 scripts/summarize_evals.py ws                   # writes ws/benchmark.{json,md}
```

`--command` is a template. `{prompt}` and `{repo}` substitute; when `{prompt}`
is absent the prompt goes to the command's stdin, which is what `claude -p`
wants. A harness that emits JSON has its own usage counted; one that emits text
leaves the token count unknown.

`--judge MODEL` adds the judge lane and `--judge-command` sets how that model is
called. `--keep-fixtures` leaves the fixture repositories on disk to inspect.

## The scenario schema

| Field | Purpose |
|---|---|
| `id`, `name` | identity; `name` also names the `eval-<id>-<slug>` directory |
| `kind` | `structure` also checks the fixture ledger still validates after the run; `behavior` grades the response alone |
| `prompt` | what the harness is asked |
| `expected_output` | prose summary of a correct answer, for a human reading the suite |
| `ledger` | the `HANDOFF.md` the fixture starts from, or `null` for a repository that keeps none |
| `files` | source files seeded into the fixture, so evidence in the prompt exists on disk |
| `required` | command fragments that must appear in the response |
| `forbidden` | command fragments that must not |
| `rubric` | one sentence telling the judge what a correct response does |
| `expectations` | the prose expectations the judge grades |

A fragment's tokens must appear in order inside one command line, with bounded
gaps, so `apply --root . --expect-version V` satisfies `apply --expect-version`.

## The two grading lanes

The **deterministic lane** always runs. It checks the command fragments and the
fixture repository: a scenario whose `ledger` is `null` fails if a `HANDOFF.md`
appeared, and a `structure` scenario fails if the seeded ledger no longer
validates. It needs no model and no credential, and its graders are tested in
`tests/test_evals.py`.

It is a floor, not a judgement. Fragment matching is blunt: a response that
names a forbidden command only to disown it still fails that check. The fixture
state is the authoritative signal that the skill did or did not trigger; read
the fragment verdicts alongside it rather than on their own.

The **judge lane** is optional and blinded: the judge sees the scenario, the
rubric, the expectations and the response, and is not told which configuration
produced it. It must return one verdict per expectation, each with evidence. A
reply the runner cannot parse into a complete set leaves that run ungraded and
reported, and `summarize_evals.py` then refuses the workspace. That is
deliberate — an incomplete grading must not average into a score.

`eval_metadata.json` lists only what the invocation actually graded, so a
judge-less run reports its fragment and fixture checks and claims nothing about
the prose expectations. The full scenario is written beside it as
`scenario.json`.

## Configurations

`with_skill` copies the skill into the fixture at `.claude/skills/handoff/` and
the commands at `.claude/commands/handoff/`. `without_skill` copies neither and
is otherwise identical.

`without_skill` is a baseline, not a product failure. It measures what the
harness does with the same fixture and no skill installed; a scenario the
baseline already passes tells you the skill is not what produced the behaviour.
`summarize_evals.py` sorts `with_skill` first and takes configuration names from
the directory, so the sibling directory needs no change to the summarizer.

## Isolation, and what it is not

Each run gets a temporary `HOME`, a fixture repository created in the system
temporary directory rather than inside this checkout, and an environment with
this developer's session variables removed. The runner refuses a fixture whose
parent directories hold a `CLAUDE.md`, `AGENTS.md`, `HANDOFF.md`, or
`.cursorrules`, because the harness would read it.

**This is context isolation, not a security boundary.** The harness still runs
as you, with your filesystem, your network, and your credentials. Nothing here
contains a model that decides to write outside the fixture. Do not point the
runner at a command you would not run by hand.

Credentials are inherited on purpose. Use a credential created for evaluation
and injected at runtime. A personal credential does not belong in CI and does
not belong in a stored trace.

### Verify the isolation before trusting a result

1. Plant a unique phrase in the real global instruction file, for example a line
   reading `CANARY-7Q2F-DO-NOT-REPEAT` in `~/.claude/CLAUDE.md`.
2. Run `python3 scripts/run_evals.py --command '<harness>' --canary CANARY-7Q2F-DO-NOT-REPEAT`.
3. The control run must repeat the phrase and the isolated run must not. A
   control run that never saw it proves nothing — the phrase was not planted
   where that harness reads, so fix that before drawing any conclusion.
4. Remove the phrase afterwards.

Repeat this whenever the harness, its configuration, or its version changes.
Isolation is a property of the harness's own lookup rules, not of this script.

## Reading the numbers honestly

- Judge scores are evidence, not ground truth. A model graded these; another
  model, or the same one tomorrow, may grade them differently.
- A small score movement is not a regression. Without repetitions
  (`--runs`) there is no variance to compare against, and one run establishes
  neither reliability nor a trend.
- Missing token counts are reported as `unknown`. `summarize_evals.py` never
  estimates them from output length, and neither should a summary written by
  hand from these runs.
- Do not report these scenarios as passing evaluations unless they were actually
  run and graded. The suite existing is not a result, and a green
  `tests/test_evals.py` means the graders and the schema hold, not that a model
  passed anything.

## What CI does and does not run

CI runs the graders, the schema validation, and the suite-size assertion through
`tests/test_evals.py`. It never calls a model: the calls cost money and are not
reproducible, so the runner is invoked by hand.

`SUITE_SIZE` in `tests/test_evals.py` is asserted against `evals.json`, so a
scenario cannot be dropped without someone changing that number deliberately.
