#!/usr/bin/env python3
"""Assert the skill and every plugin marketplace manifest declare the same version.

A plugin whose version never changes is never offered as an update, so a version
that drifts between these files silently strands every installed copy.
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


def marketplace_entry_version(path: Path, plugin_name: str) -> str:
    marketplace = json.loads(path.read_text(encoding="utf-8"))
    entries = [entry for entry in marketplace["plugins"] if entry["name"] == plugin_name]
    if len(entries) != 1:
        raise SystemExit(f"{path} must list {plugin_name} exactly once")
    return entries[0]["version"]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    plugin_name = "handoff"
    claude_plugin = json.loads((root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    cursor_plugin = json.loads((root / ".cursor-plugin/plugin.json").read_text(encoding="utf-8"))
    if claude_plugin["name"] != plugin_name or cursor_plugin["name"] != plugin_name:
        raise SystemExit("plugin.json manifests must name the handoff plugin")

    versions = {
        "skills/handoff/SKILL.md": skill_version(root),
        ".claude-plugin/plugin.json": claude_plugin["version"],
        ".claude-plugin/marketplace.json": marketplace_entry_version(
            root / ".claude-plugin/marketplace.json", plugin_name
        ),
        ".cursor-plugin/plugin.json": cursor_plugin["version"],
        ".cursor-plugin/marketplace.json": marketplace_entry_version(
            root / ".cursor-plugin/marketplace.json", plugin_name
        ),
    }
    if len(set(versions.values())) != 1:
        for name, value in versions.items():
            print(f"  {value}  {name}", file=sys.stderr)
        raise SystemExit("Version mismatch across skill and marketplace manifests")

    version = next(iter(versions.values()))
    if len(sys.argv) > 1:
        tag = sys.argv[1]
        if tag != "v" + version:
            raise SystemExit(f"Tag {tag} does not match version {version}")
        print(f"Tag {tag} matches version {version} in all manifests")
    else:
        print(f"Version {version} agrees across all manifests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
