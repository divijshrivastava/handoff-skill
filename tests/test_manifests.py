"""Regression tests for manifest generation and discovery.

Every case starts from the observed failure: `.kimi-plugin/plugin.json` sat five
releases behind the other manifests while CI stayed green, because
`check_versions.py` named four manifest paths literally and that host was a
fifth.
"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / f"scripts/{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_versions = _load("check_versions")
sync_manifests = _load("sync_manifests")

REPO = Path(__file__).resolve().parents[1]

# The paths the previous check named literally. Kept here so the first test can
# show what that list did and did not see.
NAMED_PATHS = (
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".cursor-plugin/plugin.json",
    ".cursor-plugin/marketplace.json",
)


def build_tree(root: Path, version: str = "2.0.0", hosts=None) -> Path:
    """A minimal repository: one skill version plus the requested host manifests.

    `hosts` maps a directory name to the version its manifests declare. A value
    of None creates the directory with no manifest in it.
    """
    skill = root / "skills/handoff"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f'---\nname: handoff\nmetadata:\n  version: "{version}"\n---\n\n# Handoff\n',
        encoding="utf-8",
    )
    for name, host_version in (hosts or {}).items():
        directory = root / name
        directory.mkdir()
        if host_version is None:
            continue
        (directory / "plugin.json").write_text(
            json.dumps({"name": "handoff", "version": host_version}), encoding="utf-8"
        )
        (directory / "marketplace.json").write_text(
            json.dumps(
                {"name": "divij-skills", "plugins": [{"name": "handoff", "version": host_version}]}
            ),
            encoding="utf-8",
        )
    return root


class DiscoveryTests(unittest.TestCase):
    def test_glob_catches_the_host_a_named_list_missed(self):
        """The observed failure: four manifests agree, a fifth host is behind."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(
                Path(directory),
                hosts={".claude-plugin": "2.0.0", ".cursor-plugin": "2.0.0", ".kimi-plugin": "1.5.0"},
            )
            versions = check_versions.collect_versions(root)
            # The stale host is seen ...
            self.assertEqual(versions[".kimi-plugin/plugin.json"], "1.5.0")
            self.assertNotEqual(len(set(versions.values())), 1)
            # ... and the four paths the old check named would all have agreed.
            named = {path: versions[path] for path in NAMED_PATHS}
            self.assertEqual(set(named.values()), {"2.0.0"})

    def test_a_new_host_is_covered_with_no_edit_to_either_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(
                Path(directory),
                hosts={".claude-plugin": "2.0.0", ".brand-new-plugin": "2.0.0"},
            )
            versions = check_versions.collect_versions(root)
            self.assertIn(".brand-new-plugin/plugin.json", versions)
            self.assertIn(".brand-new-plugin/marketplace.json", versions)
            self.assertEqual(set(versions.values()), {"2.0.0"})

    def test_host_directory_without_a_manifest_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(Path(directory), hosts={".claude-plugin": "2.0.0", ".empty-plugin": None})
            with self.assertRaises(SystemExit):
                check_versions.collect_versions(root)

    def test_no_host_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(Path(directory), hosts={})
            with self.assertRaises(SystemExit):
                check_versions.collect_versions(root)

    def test_a_plugin_manifest_naming_something_else_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(Path(directory), hosts={".claude-plugin": "2.0.0"})
            manifest = root / ".claude-plugin/plugin.json"
            manifest.write_text(json.dumps({"name": "other", "version": "2.0.0"}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                check_versions.collect_versions(root)


class GeneratorTests(unittest.TestCase):
    def test_generating_this_repository_changes_no_tracked_manifest(self):
        """The generator must reproduce the manifests that already exist, so its
        first run over a correct tree is a no-op and any diff it makes is drift."""
        wanted = sync_manifests.generate(REPO)
        self.assertTrue(wanted)
        for path, text in wanted.items():
            if path.name == "plugin.json" and path.parent.name == ".kimi-plugin":
                continue  # untracked by the user's decision; may be absent
            self.assertTrue(path.exists(), f"{path} is generated but missing")
            self.assertEqual(path.read_text(encoding="utf-8"), text, f"{path} differs")

    def test_every_generated_manifest_carries_the_skill_version(self):
        version = sync_manifests.skill_version(REPO)
        for path, text in sync_manifests.generate(REPO).items():
            document = json.loads(text)
            declared = (
                document["plugins"][0]["version"]
                if "plugins" in document
                else document["version"]
            )
            self.assertEqual(declared, version, f"{path} declares {declared}")

    def test_a_stale_manifest_is_reported_as_differing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(Path(directory), hosts={".claude-plugin": "1.0.0"})
            wanted = sync_manifests.generate(root)
            manifest = root / ".claude-plugin/plugin.json"
            self.assertIn(manifest, wanted)
            self.assertNotEqual(manifest.read_text(encoding="utf-8"), wanted[manifest])
            self.assertIn('"version": "2.0.0"', wanted[manifest])

    def test_an_absent_host_directory_is_never_created(self):
        """Whether a host is supported is a decision, not a side effect."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(Path(directory), hosts={".claude-plugin": "2.0.0"})
            wanted = sync_manifests.generate(root)
            self.assertFalse((root / ".cursor-plugin").exists())
            self.assertFalse(any(path.parent.name == ".cursor-plugin" for path in wanted))

    def test_an_unowned_host_is_reported_but_still_checked(self):
        """A host the generator has no shape for must not be silently ignored:
        it cannot be written, and version discovery still covers it."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_tree(
                Path(directory), hosts={".claude-plugin": "2.0.0", ".brand-new-plugin": "1.0.0"}
            )
            self.assertEqual(sync_manifests.unowned_hosts(root), [".brand-new-plugin"])
            self.assertFalse(any(path.parent.name == ".brand-new-plugin" for path in sync_manifests.generate(root)))
            versions = check_versions.collect_versions(root)
            self.assertEqual(versions[".brand-new-plugin/plugin.json"], "1.0.0")

    def test_render_inlines_short_containers_and_expands_long_ones(self):
        text = sync_manifests.render(
            {"author": {"name": "Someone"}, "tags": ["one", "two"], "long": {"key": "v" * 120}}
        )
        self.assertIn('"author": { "name": "Someone" },', text)
        self.assertIn('"tags": ["one", "two"],', text)
        self.assertIn('"long": {\n', text)
        self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
