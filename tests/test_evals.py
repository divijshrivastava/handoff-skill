import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "summarize_evals", Path(__file__).resolve().parents[1] / "scripts/summarize_evals.py"
)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


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


if __name__ == "__main__":
    unittest.main()
