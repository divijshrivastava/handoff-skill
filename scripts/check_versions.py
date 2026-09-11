#!/usr/bin/env python3
"""Assert the skill and every plugin manifest declare the same version.

A plugin whose version never changes is never offered as an update, so a version
that drifts between these files silently strands every installed copy.

Manifests are discovered by globbing `*-plugin/` rather than named literally.
A named list only checks the hosts someone remembered to add to it: this
repository carried a `.kimi-plugin/plugin.json` a full five releases behind
while CI stayed green, because the check named four paths and that was a fifth.
Discovery makes a new host directory covered the moment it exists.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

PLUGIN_NAME = "handoff"


def skill_version(root: Path) -> str:
    text = (root / "skills/handoff/SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'^  version: "([0-9]+\.[0-9]+\.[0-9]+)"$', text, re.M)
    if not match:
        raise SystemExit("skills/handoff/SKILL.md has no metadata.version")
    return match.group(1)


def plugin_version(path: Path) -> str:
    plugin = json.loads(path.read_text(encoding="utf-8"))
    if plugin.get("name") != PLUGIN_NAME:
        raise SystemExit(f"{path} must name the {PLUGIN_NAME} plugin")
    if "version" not in plugin:
        raise SystemExit(f"{path} has no version")
    return plugin["version"]


def marketplace_entry_version(path: Path) -> str:
    marketplace = json.loads(path.read_text(encoding="utf-8"))
    entries = [entry for entry in marketplace["plugins"] if entry["name"] == PLUGIN_NAME]
    if len(entries) != 1:
        raise SystemExit(f"{path} must list {PLUGIN_NAME} exactly once")
    return entries[0]["version"]


def collect_versions(root: Path) -> Dict[str, str]:
    """Every declared version, keyed by the path that declares it."""
    versions = {"skills/handoff/SKILL.md": skill_version(root)}
    directories = sorted(path for path in root.glob("*-plugin") if path.is_dir())
    if not directories:
        raise SystemExit("No *-plugin directory found")
    for directory in directories:
        found: List[str] = []
        for filename, read in (
            ("plugin.json", plugin_version),
            ("marketplace.json", marketplace_entry_version),
        ):
            manifest = directory / filename
            if not manifest.exists():
                continue
            found.append(filename)
            versions[manifest.relative_to(root).as_posix()] = read(manifest)
        if not found:
            raise SystemExit(
                f"{directory.relative_to(root)}/ holds no plugin.json or marketplace.json"
            )
    return versions


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    versions = collect_versions(root)
    if len(set(versions.values())) != 1:
        for name, value in sorted(versions.items()):
            print(f"  {value}  {name}", file=sys.stderr)
        raise SystemExit("Version mismatch across skill and plugin manifests")

    version = next(iter(versions.values()))
    if len(sys.argv) > 1:
        tag = sys.argv[1]
        if tag != "v" + version:
            raise SystemExit(f"Tag {tag} does not match version {version}")
        print(f"Tag {tag} matches version {version} in all manifests")
    else:
        print(f"Version {version} agrees across {len(versions)} manifests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
