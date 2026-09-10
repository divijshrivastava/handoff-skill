import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock


ROOT = Path(__file__).resolve().parents[1]

# The suite size is asserted, not inferred: a scenario cannot be dropped
# without someone changing this number on purpose.
SUITE_SIZE = 14


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution so dataclass field resolution works on 3.9.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


summary = load("summarize_evals", "scripts/summarize_evals.py")
runner = load("run_evals", "scripts/run_evals.py")
guard = load("handoff_guard", "skills/handoff/scripts/handoff_guard.py")


class EvalSummaryTests(unittest.TestCase):
    def fixture(self, root):
        suite = root / "eval-0-fixture"
        run = suite / "with_skill/run-1"
        (run / "outputs").mkdir(parents=True)
        (run / "outputs/response.md").write_text("Two words")
        (suite / "eval_metadata.json").write_text(json.dumps({
            "eval_id": 0, "eval_name": "fixture",
            "expectations": [{"category": "behavior", "text": "Correct"},
                             {"category": "output_quality", "text": "Concise"}],
        }))
        (run / "grading.json").write_text(json.dumps({
            "expectations": [{"text": "Correct", "passed": True, "evidence": "Observed"},
                             {"text": "Concise", "passed": False, "evidence": "Repeated"}],
            "execution_metrics": {"output_chars": 9000},
        }))
        return run

    def test_actual_counts_unknown_tokens_and_separate_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            report = summary.summarize(root)
            stats = report["run_summary"]["with_skill"]
            self.assertEqual(stats["runs"], 1)
            self.assertEqual(report["metadata"]["runs_per_eval_configuration"], {"0": {"with_skill": 1}})
            self.assertIsNone(stats["tokens"]["mean"])
            self.assertIsNone(stats["output_words"]["stddev"])
            self.assertEqual(stats["output_chars"]["mean"], 9)
            self.assertEqual(stats["output_words"]["mean"], 2)
            self.assertEqual(stats["categories"]["behavior"]["mean"], 1)
            self.assertEqual(stats["categories"]["output_quality"]["mean"], 0)
            self.assertIn("unknown", summary.markdown(report))

    def test_uses_reported_tokens_and_counts_additional_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root)
            import shutil
            shutil.copytree(run, run.with_name("run-2"))
            (run / "timing.json").write_text(json.dumps({"total_tokens": 123, "total_duration_seconds": 4}))
            stats = summary.summarize(root)["run_summary"]["with_skill"]
            self.assertEqual(stats["runs"], 2)
            self.assertEqual(stats["tokens"]["mean"], 123)
            self.assertEqual(stats["tokens"]["count"], 1)

    def test_missing_grade_is_an_error_not_a_silent_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root)
            (run / "grading.json").write_text('{"expectations": []}')
            with self.assertRaises(ValueError):
                summary.summarize(root)



class SuiteSchemaTests(unittest.TestCase):
    """The scenarios the runner executes, checked without any model call."""

    def setUp(self):
        self.suite = json.loads(runner.DEFAULT_EVALS.read_text())

    def test_suite_size_is_declared_not_inferred(self):
        self.assertEqual(len(self.suite["evals"]), SUITE_SIZE)

    def test_shipped_suite_validates(self):
        runner.validate_suite(self.suite)

    def test_seeded_ledgers_are_structurally_valid(self):
        for scenario in self.suite["evals"]:
            if scenario["ledger"] is None:
                continue
            with self.subTest(scenario=scenario["id"]):
                self.assertEqual(guard.structure_findings(scenario["ledger"]), [])

    def test_validation_rejects_a_scenario_that_cannot_be_graded(self):
        broken = copy.deepcopy(self.suite)
        broken["evals"][0]["required"] = ["handoff_guard.py read"]
        broken["evals"][0]["forbidden"] = ["handoff_guard.py read"]
        with self.assertRaises(ValueError):
            runner.validate_suite(broken)

    def test_validation_rejects_a_missing_field(self):
        broken = copy.deepcopy(self.suite)
        del broken["evals"][0]["rubric"]
        with self.assertRaises(ValueError):
            runner.validate_suite(broken)

    def test_validation_rejects_a_fixture_file_outside_the_repository(self):
        broken = copy.deepcopy(self.suite)
        broken["evals"][0]["files"] = [{"path": "../escape.md", "content": "x"}]
        with self.assertRaises(ValueError):
            runner.validate_suite(broken)

    def test_suite_covers_the_non_triggers_the_description_argues_for(self):
        """The cases the skill description spends the most words on.

        A repository with no ledger must not be turned into one by a question
        or by other agents in the tree, and an explicit status request must not
        write. Each was untested until the runner existed.
        """
        unledgered = [scenario for scenario in self.suite["evals"]
                      if scenario["ledger"] is None]
        self.assertGreaterEqual(len(unledgered), 3)
        for scenario in unledgered:
            with self.subTest(scenario=scenario["id"]):
                self.assertEqual(scenario["required"], [])
                self.assertIn("handoff_guard.py name", scenario["forbidden"])
                self.assertEqual(runner.fixture_checks(scenario), [runner.LEDGER_ABSENT])
        self.assertTrue(any("/handoff:status" in scenario["prompt"]
                            for scenario in self.suite["evals"]))


class FragmentGraderTests(unittest.TestCase):
    """The deterministic lane, graded from recorded text and no model call."""

    LEDGER = "# Handoff\n"
    POSITIVE = {
        "id": 90, "name": "positive", "kind": "structure", "prompt": "p",
        "expected_output": "o", "ledger": LEDGER, "files": [],
        "required": ["handoff_guard.py name", "apply --expect-version"],
        "forbidden": ["--allow-structure-errors"], "rubric": "r",
        "expectations": ["Records the task"],
    }
    NEGATIVE = {
        "id": 91, "name": "negative", "kind": "behavior", "prompt": "p",
        "expected_output": "o", "ledger": None, "files": [],
        "required": [],
        "forbidden": ["handoff_guard.py name", "apply --expect-version"],
        "rubric": "r", "expectations": ["Does no handoff work"],
    }
    # The observed failure: the ledger is edited in place, which is a plain
    # read-modify-write of a file other agents are writing at the same time.
    DIRECT_EDIT = (
        "I claimed a session name with `handoff_guard.py name --root .`,\n"
        "then opened HANDOFF.md and added the entry with the editor,\n"
        "saving the file once the new task block was in place.\n"
    )
    GUARDED = (
        "1. `python3 skills/handoff/scripts/handoff_guard.py name --root .`\n"
        "2. `python3 skills/handoff/scripts/handoff_guard.py read --root .`\n"
        "3. `python3 skills/handoff/scripts/handoff_guard.py apply --root . "
        "--expect-version 9f2c --entry entry.md`\n"
        "Exit 3 means the audit is stale, so I re-read rather than retry.\n"
    )
    # The observed failure on the other side: the skill runs in a repository
    # that keeps no ledger and never asked for one.
    FALSE_TRIGGER = (
        "This repository has no ledger yet, so I claimed a name with\n"
        "`handoff_guard.py name --root .` and started tracking the work.\n"
    )

    def verdict(self, scenario, response, text):
        graded = runner.grade_fragments(scenario, response)
        found = [item for item in graded if item["text"] == text]
        self.assertEqual(len(found), 1, graded)
        self.assertTrue(found[0]["evidence"])
        return found[0]["passed"]

    def test_direct_ledger_edit_fails_the_apply_fragment(self):
        self.assertFalse(self.verdict(
            self.POSITIVE, self.DIRECT_EDIT,
            runner.required_text("apply --expect-version")))

    def test_guarded_write_passes_the_apply_fragment(self):
        self.assertTrue(self.verdict(
            self.POSITIVE, self.GUARDED,
            runner.required_text("apply --expect-version")))

    def test_fragment_tolerates_arguments_between_its_tokens(self):
        """`apply --root . --expect-version V` is the real command shape."""
        self.assertTrue(runner.find_fragment(
            "run `handoff_guard.py apply --root . --expect-version 9f2c --entry e.md`",
            "apply --expect-version"))

    def test_fragment_does_not_span_separate_commands(self):
        response = "First `handoff_guard.py apply --entry e.md`.\nThen read `--expect-version`.\n"
        self.assertFalse(runner.find_fragment(response, "apply --expect-version"))

    def test_fragment_respects_word_boundaries(self):
        self.assertFalse(runner.find_fragment("I will not reapply --expect-versions",
                                              "apply --expect-version"))

    def test_false_trigger_fails_the_negative_scenario(self):
        self.assertFalse(self.verdict(
            self.NEGATIVE, self.FALSE_TRIGGER,
            runner.forbidden_text("handoff_guard.py name")))

    def test_declining_to_act_passes_the_negative_scenario(self):
        response = ("This repository keeps no ledger and you have not asked for one, "
                    "so I am answering the question and recording nothing.\n")
        self.assertTrue(self.verdict(
            self.NEGATIVE, response,
            runner.forbidden_text("handoff_guard.py name")))

    def test_metadata_lists_only_what_this_invocation_grades(self):
        suite = {"evals": [self.POSITIVE], "output_quality_expectations": ["Concise"]}
        deterministic = runner.metadata_expectations(self.POSITIVE, suite, judged=False)
        self.assertNotIn("Records the task", [item["text"] for item in deterministic])
        judged = runner.metadata_expectations(self.POSITIVE, suite, judged=True)
        texts = [item["text"] for item in judged]
        self.assertIn("Records the task", texts)
        self.assertIn("Concise", texts)
        self.assertEqual([item["category"] for item in judged if item["text"] == "Concise"],
                         ["output_quality"])

    def test_a_scenario_with_no_deterministic_check_needs_a_judge(self):
        scenario = dict(self.NEGATIVE, forbidden=[], ledger="# Handoff\n", kind="behavior")
        suite = {"evals": [scenario], "output_quality_expectations": ["Concise"]}
        with self.assertRaises(ValueError):
            runner.metadata_expectations(scenario, suite, judged=False)


class FixtureLaneTests(unittest.TestCase):
    """The fixture repository is the authoritative signal for a false trigger."""

    def test_a_created_ledger_fails_a_repository_that_keeps_none(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "HANDOFF.md").write_text("# Handoff\n")
            graded = runner.grade_fixture(FragmentGraderTests.NEGATIVE, repo, ["HANDOFF.md"])
            self.assertEqual([item["passed"] for item in graded], [False])
            self.assertIn("HANDOFF.md", graded[0]["evidence"])

    def test_an_untouched_repository_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            graded = runner.grade_fixture(FragmentGraderTests.NEGATIVE, Path(directory), [])
            self.assertEqual([item["passed"] for item in graded], [True])

    def test_a_corrupted_ledger_fails_a_structure_scenario(self):
        scenario = dict(FragmentGraderTests.POSITIVE)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "HANDOFF.md").write_text(
                "# Handoff\n\n## 2026-04-06 - Broken (owner: Sekhmet) (harness: Codex)\n\n"
                "State:\n\n- [x] In progress\n- [x] Completed\n\n"
                "Steps:\n\n- [ ] Verify it.\n\nStatus: Marked complete with a step open.\n")
            graded = runner.grade_fixture(scenario, repo, [])
            self.assertEqual([item["passed"] for item in graded], [False])

    def test_a_behavior_scenario_with_a_ledger_has_no_fixture_check(self):
        scenario = dict(FragmentGraderTests.POSITIVE, kind="behavior")
        self.assertEqual(runner.fixture_checks(scenario), [])


class FixtureIsolationTests(unittest.TestCase):
    """Context isolation, not a security boundary; the runner refuses leaks."""

    def build(self, scenario, config):
        directory = tempfile.mkdtemp(prefix="handoff-eval-test-")
        self.addCleanup(lambda: __import__("shutil").rmtree(directory, ignore_errors=True))
        return runner.build_fixture(scenario, Path(directory), config)

    def test_fixture_seeds_the_ledger_and_files_outside_this_checkout(self):
        scenario = dict(FragmentGraderTests.POSITIVE,
                        files=[{"path": "src/app.py", "content": "value = 1\n"}])
        repo = self.build(scenario, "without_skill")
        self.assertNotIn(ROOT, repo.parents)
        self.assertEqual((repo / "HANDOFF.md").read_text(), scenario["ledger"])
        self.assertEqual((repo / "src/app.py").read_text(), "value = 1\n")
        self.assertFalse((repo / "CLAUDE.md").exists())
        self.assertFalse((repo / ".claude/skills/handoff").exists())

    def test_the_ablation_differs_only_by_the_installed_skill(self):
        with_skill = self.build(FragmentGraderTests.POSITIVE, "with_skill")
        self.assertTrue((with_skill / ".claude/skills/handoff/SKILL.md").exists())
        # Nothing that never ships to a user reaches the fixture.
        self.assertFalse((with_skill / ".claude/skills/handoff/evals").exists())
        self.assertFalse((with_skill / ".claude/skills/handoff/tests").exists())

    def test_a_fixture_inside_this_checkout_is_refused(self):
        with self.assertRaises(ValueError):
            runner.assert_isolated(ROOT / "scratch-fixture")

    def test_an_inherited_instruction_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            (parent / "CLAUDE.md").write_text("Global instructions\n")
            with self.assertRaises(ValueError) as raised:
                runner.assert_isolated(parent / "repo")
            self.assertIn("CLAUDE.md", str(raised.exception))

    def test_the_environment_drops_this_session_and_keeps_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            environment = dict(__import__("os").environ)
            environment.update({"CLAUDE_CODE_SESSION": "live", "HANDOFF_ROOT": "/repo",
                                "ANTHROPIC_API_KEY": "injected-for-evaluation"})
            with unittest.mock.patch.dict("os.environ", environment, clear=True):
                env = runner.isolated_env(home)
            self.assertNotIn("CLAUDE_CODE_SESSION", env)
            self.assertNotIn("HANDOFF_ROOT", env)
            self.assertEqual(env["ANTHROPIC_API_KEY"], "injected-for-evaluation")
            self.assertEqual(env["HOME"], str(home))
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(home / ".claude"))


class RunnerInterfaceTests(unittest.TestCase):
    def test_matrix_expands_scenarios_configurations_and_repetitions(self):
        scenarios = [FragmentGraderTests.POSITIVE, FragmentGraderTests.NEGATIVE]
        expanded = runner.plan(scenarios, ["with_skill", "without_skill"], 2)
        self.assertEqual(len(expanded), 8)
        self.assertEqual([number for _, _, number in expanded[:2]], [1, 2])

    def test_ablation_is_a_first_class_configuration(self):
        self.assertIn("without_skill", runner.CONFIGS)
        self.assertFalse(runner.CONFIGS["without_skill"]["install_skill"])

    def test_dry_run_expands_the_matrix_without_a_command(self):
        args = runner.parse_args(["--dry-run", "--scenarios", "1", "--config",
                                  "with_skill,without_skill"])
        suite = runner.load_suite()
        report = runner.dry_run(args, suite, runner.select(suite, args.scenarios))
        self.assertIn("with_skill/run-1", report)
        self.assertIn("without_skill/run-1", report)
        self.assertIn("2 runs, no model calls made", report)

    def test_running_scenarios_requires_a_harness_command(self):
        with self.assertRaises(SystemExit):
            runner.parse_args(["--workspace", "workspace"])

    def test_unknown_scenario_is_an_error_not_an_empty_run(self):
        with self.assertRaises(ValueError):
            runner.select(runner.load_suite(), [999])

    def test_harness_prompt_goes_on_stdin_unless_it_is_a_token(self):
        argv, stdin = runner.harness_argv("claude -p", "Explain", Path("/repo"))
        self.assertEqual((argv, stdin), (["claude", "-p"], "Explain"))
        repo = Path("/repo")
        argv, stdin = runner.harness_argv("claude -p {prompt} --cwd {repo}", "Explain", repo)
        self.assertEqual((argv, stdin),
                         (["claude", "-p", "Explain", "--cwd", str(repo)], None))

    def test_tokens_are_unknown_rather_than_estimated(self):
        self.assertEqual(runner.extract_response("plain text answer"),
                         ("plain text answer", None))
        payload = json.dumps({"result": "answer", "usage": {"input_tokens": 10,
                                                            "output_tokens": 5}})
        self.assertEqual(runner.extract_response(payload), ("answer", 15))

    def test_judge_prompt_names_no_configuration(self):
        prompt = runner.judge_prompt(FragmentGraderTests.POSITIVE, "a response",
                                     [{"category": "behavior", "text": "Records the task"}])
        self.assertNotIn("with_skill", prompt)
        self.assertNotIn("without_skill", prompt)
        self.assertIn("Records the task", prompt)

    def test_a_short_judge_reply_is_an_error_not_a_partial_grade(self):
        with self.assertRaises(ValueError):
            runner.parse_verdicts('[{"index": 1, "passed": true, "evidence": "ok"}]', 2)

    def test_a_judge_verdict_without_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            runner.parse_verdicts('[{"index": 1, "passed": true, "evidence": ""}]', 1)


if __name__ == "__main__":
    unittest.main()
