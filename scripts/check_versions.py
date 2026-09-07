#!/usr/bin/env python3
"""Assert the skill, plugin, and marketplace all declare the same version.

A plugin whose version never changes is never offered as an update, so a version
that drifts between these three files silently strands every installed copy.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def skill_version(root: Path) -> str:
    text = (root / "skills/handoff/SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'^  version: "([0-9]+\.[0-9]+\.[0-9]+)"$', text, re.M)
    if not match:
        raise SystemExit("skills/handoff/SKILL.md has no metadata.version")
    return match.group(1)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    entries = [p for p in marketplace["plugins"] if p["name"] == plugin["name"]]
    if len(entries) != 1:
        raise SystemExit(f"marketplace.json must list {plugin['name']} exactly once")

    versions = {
        "skills/handoff/SKILL.md": skill_version(root),
        ".claude-plugin/plugin.json": plugin["version"],
        ".claude-plugin/marketplace.json": entries[0]["version"],
    }
    if len(set(versions.values())) != 1:
        for name, value in versions.items():
            print(f"  {value}  {name}", file=sys.stderr)
        raise SystemExit("Version mismatch across skill, plugin, and marketplace manifests")

    version = next(iter(versions.values()))
    if len(sys.argv) > 1:
        tag = sys.argv[1]
        if tag != "v" + version:
            raise SystemExit(f"Tag {tag} does not match version {version}")
        print(f"Tag {tag} matches version {version} in all three files")
    else:
        print(f"Version {version} agrees across all three files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
