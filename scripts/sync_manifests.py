#!/usr/bin/env python3
"""Generate every plugin manifest from one source.

The version lives in `skills/handoff/SKILL.md` frontmatter and nowhere else.
Each host directory holds manifests in that host's own shape, and this script
writes them, so a release bumps one number rather than five files that a person
has to remember.

Only the *version* comes from the skill. The marketplace-facing description is
declared here, because a marketplace listing is read by a person choosing a
plugin while the skill description is read by a model deciding whether to
trigger. Those two texts drift apart on purpose, and sourcing one from the
other would let a change to the skill's trigger prose rewrite a storefront.

A host directory that is absent is skipped, not created: whether a host is
supported is a decision, and a generator that materialises directories makes it
silently. A host directory that exists but is not in HOSTS is reported, because
`check_versions.py` will check it and nothing here can generate it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# Text a person reads in a storefront listing. Not the skill description.
DISPLAY_NAME = "Handoff"
SHORT_DESCRIPTION = (
    "Coordinate progressive repository work across agents with a shared HANDOFF.md ledger."
)
MARKETPLACE_NAME = "divij-skills"
MARKETPLACE_DESCRIPTION = (
    "Agent skills for coordinating repository work across multiple agents."
)
AUTHOR_NAME = "Divij Shrivastava"
AUTHOR_URL = "https://github.com/divijshrivastava"
HOMEPAGE = "https://github.com/divijshrivastava/handoff-skill#readme"
REPOSITORY = "https://github.com/divijshrivastava/handoff-skill"
LICENSE = "MIT"
CATEGORY = "productivity"
KEYWORDS = ["handoff", "ledger", "multi-agent", "task-tracking"]

PLUGIN_NAME = "handoff"


def _claude_plugin(version: str) -> Dict[str, Any]:
    return {
        "name": PLUGIN_NAME,
        "version": version,
        "description": SHORT_DESCRIPTION,
        "author": {"name": AUTHOR_NAME},
        "homepage": HOMEPAGE,
        "repository": REPOSITORY,
        "license": LICENSE,
        "keywords": list(KEYWORDS),
    }


def _claude_marketplace(version: str) -> Dict[str, Any]:
    return {
        "name": MARKETPLACE_NAME,
        "owner": {"name": AUTHOR_NAME, "url": AUTHOR_URL},
        "description": MARKETPLACE_DESCRIPTION,
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": "./",
                "version": version,
                "displayName": DISPLAY_NAME,
                "description": SHORT_DESCRIPTION,
                "homepage": HOMEPAGE,
                "repository": REPOSITORY,
                "license": LICENSE,
                "category": CATEGORY,
                "tags": list(KEYWORDS),
            }
        ],
    }


def _cursor_plugin(version: str) -> Dict[str, Any]:
    return {
        "name": PLUGIN_NAME,
        "version": version,
        "description": SHORT_DESCRIPTION,
        "author": {"name": AUTHOR_NAME},
        "homepage": HOMEPAGE,
        "repository": REPOSITORY,
        "license": LICENSE,
        "keywords": list(KEYWORDS),
        "skills": "skills/handoff",
        "commands": "commands",
        "agents": "skills/handoff/agents",
    }


def _cursor_marketplace(version: str) -> Dict[str, Any]:
    return {
        "name": MARKETPLACE_NAME,
        "owner": {"name": AUTHOR_NAME},
        "metadata": {"description": MARKETPLACE_DESCRIPTION},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": "./",
                "version": version,
                "description": SHORT_DESCRIPTION,
                "homepage": HOMEPAGE,
                "repository": REPOSITORY,
                "license": LICENSE,
                "category": CATEGORY,
                "tags": list(KEYWORDS),
            }
        ],
    }


def _kimi_plugin(version: str) -> Dict[str, Any]:
    return {
        "name": PLUGIN_NAME,
        "version": version,
        "description": SHORT_DESCRIPTION,
        "keywords": list(KEYWORDS),
        "author": {"name": AUTHOR_NAME},
        "homepage": HOMEPAGE,
        "license": LICENSE,
        "skills": "./skills/",
        "commands": "./commands/",
        "interface": {
            "displayName": DISPLAY_NAME,
            "shortDescription": "Resume repository work with evidence and ownership",
        },
    }


# One entry per host: the directory it owns and the manifests it takes. A host
# absent from this table but present on disk is reported rather than guessed at,
# because writing a manifest in a shape nobody has verified ships a broken file.
HOSTS = {
    ".claude-plugin": {
        "plugin.json": _claude_plugin,
        "marketplace.json": _claude_marketplace,
    },
    ".cursor-plugin": {
        "plugin.json": _cursor_plugin,
        "marketplace.json": _cursor_marketplace,
    },
    ".kimi-plugin": {
        "plugin.json": _kimi_plugin,
    },
}


def skill_version(root: Path) -> str:
    """Read the one version this repository has."""
    text = (root / "skills/handoff/SKILL.md").read_text(encoding="utf-8")
    match = re.search(r'^  version: "([0-9]+\.[0-9]+\.[0-9]+)"$', text, re.M)
    if not match:
        raise SystemExit("skills/handoff/SKILL.md has no metadata.version")
    return match.group(1)


def host_directories(root: Path) -> List[Path]:
    """Every `*-plugin` directory present, in a stable order."""
    return sorted(path for path in root.glob("*-plugin") if path.is_dir())


# Width at or under which a scalar-only object or array is written on one line.
# The existing manifests were formatted by hand and keep short containers inline
# (`"author": { "name": "..." }`, `"keywords": [...]`) while expanding long ones
# (`"metadata"`, `"interface"`). Reproducing that costs one rule and buys a real
# guarantee: the generator's first run over a correct tree changes zero bytes, so
# the diff it produces is the drift it found and nothing else.
INLINE_WIDTH = 100


def _inline(value: Any) -> str:
    """One-line JSON. An inline object is padded inside its braces and an inline
    array is not, matching how the manifests are already written."""
    text = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    if isinstance(value, dict) and value:
        return "{ " + text[1:-1] + " }"
    return text


def _scalars_only(value: Any) -> bool:
    members = value.values() if isinstance(value, dict) else value
    return all(not isinstance(member, (dict, list)) for member in members)


def _render(value: Any, indent: int, prefix_width: int) -> str:
    """Serialise `value`, inlining a scalar-only container that fits the width."""
    if not isinstance(value, (dict, list)):
        return _inline(value)
    if _scalars_only(value):
        inline = _inline(value)
        if indent + prefix_width + len(inline) <= INLINE_WIDTH:
            return inline
    pad = " " * (indent + 2)
    if isinstance(value, dict):
        lines = [
            f"{pad}{_inline(key)}: {_render(item, indent + 2, len(_inline(key)) + 2)}"
            for key, item in value.items()
        ]
    else:
        lines = [f"{pad}{_render(item, indent + 2, 0)}" for item in value]
    open_brace, close_brace = ("{", "}") if isinstance(value, dict) else ("[", "]")
    return open_brace + "\n" + ",\n".join(lines) + "\n" + " " * indent + close_brace


def render(document: Dict[str, Any]) -> str:
    """Serialise a manifest with a trailing newline, as the manifests carry today."""
    return _render(document, 0, 0) + "\n"


def generate(root: Path) -> Dict[Path, str]:
    """Map every manifest this repository should have to its intended text."""
    version = skill_version(root)
    wanted: Dict[Path, str] = {}
    for directory in host_directories(root):
        builders = HOSTS.get(directory.name)
        if builders is None:
            continue
        for filename, builder in builders.items():
            wanted[directory / filename] = render(builder(version))
    return wanted


def unowned_hosts(root: Path) -> List[str]:
    """Host directories on disk that this script cannot generate."""
    return [path.name for path in host_directories(root) if path.name not in HOSTS]


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=None, help="Repository path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit non-zero when a manifest differs from what would be generated",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    wanted = generate(root)
    if not wanted:
        raise SystemExit("No known *-plugin directory found")

    stale: List[str] = []
    for path, text in sorted(wanted.items()):
        relative = path.relative_to(root)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        stale.append(str(relative))
        if not args.check:
            path.write_text(text, encoding="utf-8")

    for name in unowned_hosts(root):
        print(
            f"Warning: {name}/ is not in HOSTS, so it is checked but never generated. "
            "Add it to the host table or remove the directory.",
            file=sys.stderr,
        )

    version = skill_version(root)
    if args.check:
        if stale:
            for name in stale:
                print(f"  out of date  {name}", file=sys.stderr)
            raise SystemExit(
                "Manifests do not match skills/handoff/SKILL.md. "
                "Run python3 scripts/sync_manifests.py"
            )
        print(f"Every generated manifest matches version {version}")
        return 0

    if stale:
        for name in stale:
            print(f"  wrote  {name}")
    print(f"{len(wanted)} manifests at version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
