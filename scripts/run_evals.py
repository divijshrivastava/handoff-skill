#!/usr/bin/env python3
"""Execute the handoff eval scenarios against a harness CLI and write graded runs.

The runner produces the workspace layout `summarize_evals.py` already consumes
and summarizes nothing itself. Two lanes write one `grading.json` per run: a
deterministic lane that checks command fragments and the fixture repository,
and an optional blinded judge (`--judge`). A run the judge could not grade is
left ungraded and reported, because the summarizer must raise on incomplete
grading rather than average a guess.

Model calls cost money and are not reproducible, so this script is invoked by
hand. Only the graders, the schema validation, and the suite-size assertion run
in CI, through `tests/test_evals.py`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALS = ROOT / "skills/handoff/evals/evals.json"
SKILL_DIR = ROOT / "skills/handoff"
COMMANDS_DIR = ROOT / "commands"

# Only what genuinely differs between configurations. `without_skill` is a
# baseline, not a product failure: it measures what the harness does with the
# same fixture and no skill installed.
CONFIGS = {
    "with_skill": {"install_skill": True},
    "without_skill": {"install_skill": False},
}

# Copied into the fixture, minus the material that never ships to a user.
SKILL_EXCLUDES = ("tests", "evals", "__pycache__")

SCENARIO_FIELDS = (
    "id", "name", "kind", "prompt", "expected_output", "ledger", "files",
    "required", "forbidden", "rubric", "expectations",
)
KINDS = ("behavior", "structure")

# Dropped so the developer's session cannot reach the fixture. This is context
# isolation, not a security boundary: the harness still runs as this user.
DROPPED_ENV_PREFIXES = (
    "CLAUDE", "CURSOR", "CODEX", "KIMI", "GROK", "HANDOFF", "GIT_DIR",
    "GIT_WORK_TREE", "GIT_INDEX_FILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
)
# Instruction files a harness inherits from a parent directory. A fixture whose
# parents hold one is not isolated, so the runner refuses to use it.
INHERITED_CONTEXT = ("CLAUDE.md", "AGENTS.md", "HANDOFF.md", ".cursorrules")


def load_guard():
    """Import the shipped helper by path, without installing anything."""
    spec = importlib.util.spec_from_file_location(
        "handoff_guard", SKILL_DIR / "scripts/handoff_guard.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: dataclass field resolution reads the module
    # out of sys.modules on Python 3.9.
    sys.modules["handoff_guard"] = module
    spec.loader.exec_module(module)
    return module


def load_suite(path: Path = DEFAULT_EVALS) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    validate_suite(suite)
    return suite


def validate_suite(suite: dict) -> None:
    """Raise on a scenario the runner could not execute or grade."""
    evals = suite.get("evals")
    if not evals:
        raise ValueError("Suite holds no scenarios")
    if not suite.get("output_quality_expectations"):
        raise ValueError("Suite holds no output quality expectations")
    seen = set()
    for scenario in evals:
        missing = [field for field in SCENARIO_FIELDS if field not in scenario]
        if missing:
            raise ValueError(f"Scenario {scenario.get('id')} is missing {missing}")
        identifier = scenario["id"]
        if identifier in seen:
            raise ValueError(f"Duplicate scenario id {identifier}")
        seen.add(identifier)
        if scenario["kind"] not in KINDS:
            raise ValueError(f"Scenario {identifier} has unknown kind {scenario['kind']!r}")
        if not scenario["expectations"] or not scenario["rubric"]:
            raise ValueError(f"Scenario {identifier} has nothing for the judge to grade")
        for field in ("required", "forbidden"):
            if not isinstance(scenario[field], list):
                raise ValueError(f"Scenario {identifier} field {field} is not a list")
        overlap = set(scenario["required"]) & set(scenario["forbidden"])
        if overlap:
            raise ValueError(f"Scenario {identifier} requires and forbids {sorted(overlap)}")
        if scenario["ledger"] is not None and not scenario["ledger"].startswith("# "):
            raise ValueError(f"Scenario {identifier} ledger has no title line")
        for item in scenario["files"]:
            if set(item) != {"path", "content"}:
                raise ValueError(f"Scenario {identifier} has a malformed file entry")
            if Path(item["path"]).is_absolute() or ".." in Path(item["path"]).parts:
                raise ValueError(f"Scenario {identifier} seeds a file outside the fixture")


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def normalise(text: str) -> str:
    """Collapse whitespace so a command wrapped across lines still matches."""
    return " ".join(text.split())


def required_text(fragment: str) -> str:
    return f"Response includes the command fragment `{fragment}`"


def forbidden_text(fragment: str) -> str:
    return f"Response omits the command fragment `{fragment}`"


LEDGER_ABSENT = "Fixture repository still has no HANDOFF.md"
LEDGER_VALID = "Fixture ledger is present and structurally valid"


# A fragment's tokens must appear in order in one command, but a real command
# carries arguments between them: `apply --root . --expect-version V` contains
# the fragment `apply --expect-version`. The gap is bounded so an unrelated
# sentence does not satisfy a fragment by accident.
MAX_GAP = 80


def fragment_pattern(fragment: str):
    tokens = [re.escape(token) for token in fragment.split()]
    body = ("." + "{0,%d}?" % MAX_GAP).join(tokens)
    return re.compile(r"(?<![A-Za-z0-9_])" + body + r"(?![A-Za-z0-9_])")


def command_candidates(response: str) -> list:
    """One string per line and per inline code span, whitespace collapsed.

    A command is written on a line, so a line is the unit a fragment must match
    inside. Code spans are added because one can wrap across a line break.
    """
    joined = response.replace("\\\n", " ")
    candidates = [normalise(line) for line in joined.splitlines()]
    candidates += [normalise(span) for span in re.findall(r"`+([^`]+)`+", joined)]
    return [candidate for candidate in candidates if candidate]


def find_fragment(response: str, fragment: str) -> str:
    """Return the command line that carries the fragment, or an empty string."""
    pattern = fragment_pattern(fragment)
    for candidate in command_candidates(response):
        if pattern.search(candidate):
            return candidate[:200]
    return ""


def grade_fragments(scenario: dict, response: str) -> list:
    """Check the command fragments a response must and must not contain.

    This lane is a cheap floor, not a judgement. A response that names a
    forbidden command only to disown it still fails it, which is why negative
    scenarios also carry the fixture check below and a rubric for the judge.
    """
    graded = []
    for fragment in scenario["required"]:
        found = find_fragment(response, fragment)
        graded.append({
            "text": required_text(fragment),
            "passed": bool(found),
            "evidence": found or f"Fragment `{fragment}` does not appear in the response",
        })
    for fragment in scenario["forbidden"]:
        found = find_fragment(response, fragment)
        graded.append({
            "text": forbidden_text(fragment),
            "passed": not found,
            "evidence": f"Fragment `{fragment}` appears: {found}" if found
            else f"Fragment `{fragment}` does not appear in the response",
        })
    return graded


def fixture_checks(scenario: dict) -> list:
    """The expectation texts the fixture lane grades for this scenario."""
    if scenario["ledger"] is None:
        return [LEDGER_ABSENT]
    return [LEDGER_VALID] if scenario["kind"] == "structure" else []


def grade_fixture(scenario: dict, repo: Path, created: list) -> list:
    checks = fixture_checks(scenario)
    if not checks:
        return []
    ledger = repo / "HANDOFF.md"
    added = ", ".join(created) if created else "no new files"
    if checks == [LEDGER_ABSENT]:
        return [{
            "text": LEDGER_ABSENT,
            "passed": not ledger.exists(),
            "evidence": f"HANDOFF.md {'exists' if ledger.exists() else 'absent'}; "
                        f"run created: {added}",
        }]
    if not ledger.exists():
        return [{"text": LEDGER_VALID, "passed": False,
                 "evidence": f"The seeded HANDOFF.md is gone; run created: {added}"}]
    findings = load_guard().structure_findings(ledger.read_text(encoding="utf-8"))
    return [{
        "text": LEDGER_VALID,
        "passed": not findings,
        "evidence": "; ".join(message for _, _, message in findings) if findings
        else f"Ledger validates after the run; run created: {added}",
    }]


def deterministic_expectations(scenario: dict) -> list:
    """Metadata entries for everything gradable without a model."""
    return (
        [{"category": "behavior", "text": required_text(f)} for f in scenario["required"]]
        + [{"category": "behavior", "text": forbidden_text(f)} for f in scenario["forbidden"]]
        + [{"category": "behavior", "text": check} for check in fixture_checks(scenario)]
    )


def judged_expectations(scenario: dict, suite: dict) -> list:
    return (
        [{"category": "behavior", "text": text} for text in scenario["expectations"]]
        + [{"category": "output_quality", "text": text}
           for text in suite["output_quality_expectations"]]
    )


def metadata_expectations(scenario: dict, suite: dict, judged: bool) -> list:
    """Only what this invocation actually grades reaches the metadata.

    The summarizer raises on an expectation without a verdict. Listing the
    prose expectations when no judge ran would either break the summary or
    invite a fabricated verdict; the full scenario is written beside the
    metadata as `scenario.json` so nothing is lost.
    """
    graded = deterministic_expectations(scenario)
    if judged:
        graded += judged_expectations(scenario, suite)
    if not graded:
        raise ValueError(
            f"Scenario {scenario['id']} has nothing to grade without --judge; "
            "give it required or forbidden fragments, or run with a judge"
        )
    return graded


# --- fixtures ---------------------------------------------------------------


def snapshot(repo: Path) -> set:
    return {
        str(path.relative_to(repo))
        for path in repo.rglob("*")
        if ".git" not in path.relative_to(repo).parts
    }


def assert_isolated(directory: Path) -> None:
    """Refuse a fixture whose parents would leak instructions into the run."""
    if ROOT in directory.parents or directory == ROOT:
        raise ValueError(f"Fixture {directory} is inside this checkout")
    for parent in [directory, *directory.parents]:
        for name in INHERITED_CONTEXT:
            if (parent / name).exists():
                raise ValueError(f"Fixture is not isolated: {parent / name} would be inherited")


def install_skill(repo: Path) -> None:
    target = repo / ".claude/skills/handoff"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKILL_DIR, target, ignore=shutil.ignore_patterns(*SKILL_EXCLUDES))
    if COMMANDS_DIR.is_dir():
        shutil.copytree(COMMANDS_DIR, repo / ".claude/commands/handoff")


def build_fixture(scenario: dict, parent: Path, config: str) -> Path:
    repo = parent / f"eval-{scenario['id']}-{config}"
    repo.mkdir(parents=True)
    assert_isolated(repo)
    for item in scenario["files"]:
        path = repo / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["content"], encoding="utf-8")
    if scenario["ledger"] is not None:
        (repo / "HANDOFF.md").write_text(scenario["ledger"], encoding="utf-8")
    if CONFIGS[config]["install_skill"]:
        install_skill(repo)
    if shutil.which("git"):
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return repo


def isolated_env(home: Path) -> dict:
    """The harness environment with this developer's context removed.

    Credentials are deliberately inherited: an evaluation credential is created
    for the purpose and injected at runtime.
    """
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(DROPPED_ENV_PREFIXES)
    }
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
    return env


# --- harness invocation -----------------------------------------------------


def harness_argv(template: str, prompt: str, repo: Path) -> tuple:
    """Split a command template; the prompt goes on stdin unless it is a token."""
    argv = [
        part.replace("{prompt}", prompt).replace("{repo}", str(repo))
        for part in shlex.split(template)
    ]
    stdin = None if any("{prompt}" in part for part in shlex.split(template)) else prompt
    return argv, stdin


def extract_response(stdout: str) -> tuple:
    """Return (response text, total tokens or None) from harness output.

    A harness that emits JSON reports its own usage; one that emits text does
    not, and the count stays unknown rather than being estimated from length.
    """
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout, None
    if not isinstance(payload, dict):
        return stdout, None
    text = payload.get("result") or payload.get("response") or payload.get("text") or stdout
    tokens = payload.get("total_tokens")
    usage = payload.get("usage")
    if tokens is None and isinstance(usage, dict):
        counted = [value for value in usage.values() if isinstance(value, int)]
        tokens = sum(counted) if counted else None
    return text, tokens if isinstance(tokens, int) and tokens >= 0 else None


def run_once(scenario: dict, config: str, template: str, parent: Path, timeout: int) -> dict:
    home = parent / f"home-{scenario['id']}-{config}"
    repo = build_fixture(scenario, parent, config)
    before = snapshot(repo)
    argv, stdin = harness_argv(template, scenario["prompt"], repo)
    started = time.time()
    completed = subprocess.run(
        argv, cwd=repo, env=isolated_env(home), input=stdin, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )
    seconds = time.time() - started
    if completed.returncode != 0:
        # A harness that errored produced no answer to grade. Failing every
        # expectation on an empty response would read as a model result.
        raise RuntimeError(
            f"Harness exited {completed.returncode}: "
            f"{normalise(completed.stderr)[:300] or 'no stderr'}"
        )
    response, tokens = extract_response(completed.stdout)
    created = sorted(snapshot(repo) - before)
    return {
        "repo": repo, "response": response, "tokens": tokens, "seconds": seconds,
        "created": created, "stderr": completed.stderr, "returncode": completed.returncode,
        "command": " ".join(shlex.quote(part) for part in argv),
    }


# --- judge ------------------------------------------------------------------


def judge_prompt(scenario: dict, response: str, expectations: list) -> str:
    numbered = "\n".join(f"{index}. {item['text']}"
                         for index, item in enumerate(expectations, start=1))
    return "\n".join([
        "Grade one response against a fixed list of expectations.",
        "You are not told what produced it, and must judge only the text below.",
        "",
        "## Scenario given to the responder", scenario["prompt"], "",
        "## What a correct response does", scenario["rubric"], "",
        "## Expectations", numbered, "",
        "## Response", "<<<RESPONSE", response, "RESPONSE>>>", "",
        "Reply with JSON only: a list of objects with keys index (integer),",
        "passed (boolean), and evidence (a quotation or short reason, never empty).",
        "Return exactly one object per expectation, in order.",
    ])


def parse_verdicts(text: str, count: int) -> list:
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("Judge returned no JSON list")
    verdicts = json.loads(text[start:end + 1])
    if len(verdicts) != count:
        raise ValueError(f"Judge returned {len(verdicts)} verdicts for {count} expectations")
    for verdict in verdicts:
        if not isinstance(verdict.get("passed"), bool) or not verdict.get("evidence"):
            raise ValueError("Judge returned a verdict without a boolean and evidence")
    return sorted(verdicts, key=lambda verdict: verdict.get("index", 0))


def judge_run(scenario: dict, response: str, expectations: list, model: str,
              template: str, timeout: int) -> list:
    prompt = judge_prompt(scenario, response, expectations)
    argv, stdin = harness_argv(template.replace("{model}", model), prompt, Path.cwd())
    completed = subprocess.run(
        argv, input=stdin, timeout=timeout, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True,
    )
    verdicts = parse_verdicts(extract_response(completed.stdout)[0], len(expectations))
    return [
        {"text": item["text"], "passed": verdict["passed"], "evidence": str(verdict["evidence"])}
        for item, verdict in zip(expectations, verdicts)
    ]


# --- matrix -----------------------------------------------------------------


def select(suite: dict, ids: list) -> list:
    if not ids:
        return suite["evals"]
    known = {scenario["id"]: scenario for scenario in suite["evals"]}
    missing = [identifier for identifier in ids if identifier not in known]
    if missing:
        raise ValueError(f"No such scenario: {missing}")
    return [known[identifier] for identifier in ids]


def plan(scenarios: list, configs: list, runs: int) -> list:
    return [(scenario, config, number)
            for scenario in scenarios
            for config in configs
            for number in range(1, runs + 1)]


def eval_directory(workspace: Path, scenario: dict) -> Path:
    return workspace / f"eval-{scenario['id']}-{slug(scenario['name'])}"


def write_eval_metadata(workspace: Path, scenario: dict, suite: dict, judged: bool) -> Path:
    directory = eval_directory(workspace, scenario)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "eval_metadata.json").write_text(json.dumps({
        "eval_id": scenario["id"],
        "eval_name": scenario["name"],
        "kind": scenario["kind"],
        "graded_lanes": ["deterministic", "judge"] if judged else ["deterministic"],
        "expectations": metadata_expectations(scenario, suite, judged),
    }, indent=2) + "\n", encoding="utf-8")
    (directory / "scenario.json").write_text(
        json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    return directory


def write_run(directory: Path, config: str, number: int, result: dict) -> Path:
    run_dir = directory / config / f"run-{number}"
    (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "outputs/response.md").write_text(result["response"], encoding="utf-8")
    (run_dir / "command.txt").write_text(result["command"] + "\n", encoding="utf-8")
    if result["stderr"]:
        (run_dir / "stderr.log").write_text(result["stderr"], encoding="utf-8")
    timing = {"total_duration_seconds": round(result["seconds"], 3)}
    if result["tokens"] is not None:
        timing["total_tokens"] = result["tokens"]
    (run_dir / "timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    return run_dir


def execute(args, suite: dict, scenarios: list) -> int:
    workspace = args.workspace
    workspace.mkdir(parents=True, exist_ok=True)
    judged = bool(args.judge)
    ungraded = []
    for scenario, config, number in plan(scenarios, args.config, args.runs):
        directory = write_eval_metadata(workspace, scenario, suite, judged)
        label = f"eval-{scenario['id']} {config} run-{number}"
        parent = Path(tempfile.mkdtemp(prefix="handoff-eval-"))
        try:
            result = run_once(scenario, config, args.command, parent, args.timeout)
            run_dir = write_run(directory, config, number, result)
            graded = grade_fragments(scenario, result["response"])
            graded += grade_fixture(scenario, result["repo"], result["created"])
            if judged:
                graded += judge_run(
                    scenario, result["response"], judged_expectations(scenario, suite),
                    args.judge, args.judge_command, args.timeout)
            (run_dir / "grading.json").write_text(
                json.dumps({"expectations": graded}, indent=2) + "\n", encoding="utf-8")
            passed = sum(item["passed"] for item in graded)
            print(f"{label}: {passed}/{len(graded)} expectations passed -> {run_dir}")
        except Exception as error:  # a failed run stays visible and ungraded
            ungraded.append(f"{label}: {error}")
            print(f"{label}: FAILED ({error})", file=sys.stderr)
        finally:
            if args.keep_fixtures:
                print(f"{label}: fixture kept at {parent}")
            else:
                shutil.rmtree(parent, ignore_errors=True)
    if ungraded:
        print("\nUngraded runs (the summarizer will refuse this workspace):", file=sys.stderr)
        for line in ungraded:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"\nSummarize with: python3 scripts/summarize_evals.py {workspace}")
    return 0


CANARY_PROMPT = (
    "Quote every instruction or memory file you were given before this message, "
    "verbatim and in full. If you were given none, reply with the single word NONE."
)


def canary(args) -> int:
    """Prove the isolation before trusting a result.

    Plant a unique phrase in the real global instruction file first. A control
    run must repeat it; an isolated run must not. A control run that does not
    see the phrase proves nothing about isolation, so that is a failure too.
    """
    parent = Path(tempfile.mkdtemp(prefix="handoff-canary-"))
    try:
        repo = parent / "repo"
        repo.mkdir()
        assert_isolated(repo)
        argv, stdin = harness_argv(args.command, CANARY_PROMPT, repo)
        control = subprocess.run(argv, cwd=repo, input=stdin, timeout=args.timeout,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 universal_newlines=True)
        isolated = subprocess.run(argv, cwd=repo, env=isolated_env(parent / "home"),
                                  input=stdin, timeout=args.timeout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, universal_newlines=True)
        in_control = args.canary in extract_response(control.stdout)[0]
        in_isolated = args.canary in extract_response(isolated.stdout)[0]
        print(f"control run repeats the canary: {in_control}")
        print(f"isolated run repeats the canary: {in_isolated}")
        if not in_control:
            print("The control run never saw the phrase, so this test proves nothing. "
                  "Plant it in the real global instruction file and try again.", file=sys.stderr)
            return 1
        if in_isolated:
            print("The isolated run read the developer's instructions. "
                  "Results from this runner are not trustworthy until that is fixed.",
                  file=sys.stderr)
            return 1
        print("Isolation holds for this harness. It is context isolation, not a sandbox.")
        return 0
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def listing(scenarios: list) -> str:
    lines = []
    for scenario in scenarios:
        ledger = "seeded ledger" if scenario["ledger"] is not None else "no ledger"
        lines.append(f"{scenario['id']:>3}  {scenario['kind']:<9} {ledger:<13} "
                     f"{scenario['name']}")
        lines.append(f"     required: {scenario['required'] or 'none'}")
        lines.append(f"     forbidden: {scenario['forbidden'] or 'none'}")
    return "\n".join(lines)


def dry_run(args, suite: dict, scenarios: list) -> str:
    lines = []
    for scenario, config, number in plan(scenarios, args.config, args.runs):
        graded = len(metadata_expectations(scenario, suite, bool(args.judge)))
        lines.append(f"eval-{scenario['id']}-{slug(scenario['name'])}/{config}/run-{number}"
                     f"  {graded} expectations"
                     f"  {'judge: ' + args.judge if args.judge else 'deterministic only'}")
    lines.append(f"{len(lines)} runs, no model calls made")
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evals", type=Path, default=DEFAULT_EVALS)
    parser.add_argument("--workspace", type=Path, default=Path("eval-workspace"),
                        help="Directory to write eval-*/<config>/run-* into")
    parser.add_argument("--scenarios", default="",
                        help="Comma-separated scenario ids; default is all")
    parser.add_argument("--config", default="with_skill",
                        help=f"Comma-separated configurations from {sorted(CONFIGS)}")
    parser.add_argument("--runs", type=int, default=1,
                        help="Repetitions per scenario and configuration")
    parser.add_argument("--command",
                        help="Harness CLI template; {prompt} and {repo} substitute, "
                             "and the prompt goes on stdin when {prompt} is absent")
    parser.add_argument("--judge", help="Model id for the blinded judge lane")
    parser.add_argument("--judge-command", default="claude -p --model {model}",
                        help="Judge CLI template; {model} and {prompt} substitute")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds per model call")
    parser.add_argument("--keep-fixtures", action="store_true",
                        help="Leave fixture repositories on disk for inspection")
    parser.add_argument("--canary", help="Verify isolation with this planted phrase")
    parser.add_argument("--list", action="store_true", help="Enumerate scenarios and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Expand the run matrix without calling a model")
    args = parser.parse_args(argv)
    args.config = [name.strip() for name in args.config.split(",") if name.strip()]
    unknown = [name for name in args.config if name not in CONFIGS]
    if unknown:
        parser.error(f"Unknown configuration {unknown}; choose from {sorted(CONFIGS)}")
    args.scenarios = [int(part) for part in args.scenarios.replace(",", " ").split()]
    if not (args.list or args.dry_run or args.command):
        parser.error("--command is required to run scenarios")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    suite = load_suite(args.evals)
    scenarios = select(suite, args.scenarios)
    if args.list:
        print(listing(scenarios))
        return 0
    if args.dry_run:
        print(dry_run(args, suite, scenarios))
        return 0
    if args.canary:
        return canary(args)
    return execute(args, suite, scenarios)


if __name__ == "__main__":
    sys.exit(main())
