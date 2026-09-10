#!/usr/bin/env python3
"""Publish handoff state to a VPS so each agent's twin can read its own work.

One command captures the ledger and the channel, slices the result by owner, and
writes it to a path on a host the user configured beforehand. Publishing is one
way. A twin reads its slice; nothing flows back. Two machines editing one ledger
would need `swap_ledger`'s compare-and-swap to hold over a network, and it does
not: both would pass the version check against the same revision and one entry
would be lost. That is a separate design, not a flag on this one.

Three properties this file exists to keep:

*One moment.* The ledger and the channel have independent writers, so reading
them in sequence can publish a state that never existed. Capture re-reads the
ledger version after reading the channel and retries when it moved, the same
discipline `read` uses to bind audited text to the version it was audited at.

*Nothing is a liveness claim.* Every field is what a store said at capture time.
`reported_at` and `report_age_seconds` are published; "online" is not, because
silence cannot separate an exhausted agent from an idle healthy one.

*Nothing leaves unredacted.* Message bodies carry absolute paths. Home
directories are rewritten before anything is written out, including in a local
dry run, so a snapshot on disk is already safe to move.

Transport is `ssh`, which needs no new dependency and no credential in the
repository: it reuses keys the user has already configured, which is what makes
"the agents are set up beforehand" true rather than aspirational.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

from handoff_guard import find_repo_root, ledger_version, parse_tasks

SCHEMA_VERSION = 1
CONFIG_NAME = "vps.json"
# `.handoff/` is gitignored, so machine-local destination and agent mapping live
# beside the channel rather than in a tracked file.
CONFIG_DIR = ".handoff"
MESSAGE_LIMIT = 200
CAPTURE_ATTEMPTS = 5

HOME_PATTERN = re.compile(r"/(Users|home)/[^/\s\"']+")


class PublishError(Exception):
    """A problem the user has to fix: configuration, destination, or transport."""


# ── Configuration ──────────────────────────────────────────

def config_path(root: Path) -> Path:
    return root / CONFIG_DIR / CONFIG_NAME


def load_config(root: Path) -> Dict[str, Any]:
    """Read the user's destination and agent map.

    The map is the authority on which twins exist. It is written by hand,
    because this file describes machines the repository cannot discover.
    """
    path = config_path(root)
    if not path.is_file():
        raise PublishError(
            f"No {CONFIG_DIR}/{CONFIG_NAME}. Write one naming the destination and the "
            "agents configured on it; see `handoff_publish.py example`."
        )
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PublishError(f"{path} is not valid JSON: {error}") from error

    destination = config.get("destination")
    if not isinstance(destination, dict):
        raise PublishError(f"{path} needs a destination object with host and path")
    for field in ("host", "path"):
        if not isinstance(destination.get(field), str) or not destination[field].strip():
            raise PublishError(f"{path}: destination.{field} must be a non-empty string")

    agents = config.get("agents")
    if not isinstance(agents, list) or not agents:
        raise PublishError(f"{path} needs a non-empty agents list")
    seen = set()
    for agent in agents:
        if not isinstance(agent, dict):
            raise PublishError(f"{path}: each agent must be an object")
        for field in ("owner", "harness"):
            if not isinstance(agent.get(field), str) or not agent[field].strip():
                raise PublishError(f"{path}: every agent needs a non-empty {field}")
        agent.setdefault("twin", agent["owner"])
        if agent["owner"] in seen:
            raise PublishError(f"{path}: {agent['owner']} is listed twice")
        seen.add(agent["owner"])
    return config


EXAMPLE_CONFIG = {
    "destination": {"host": "you@vps.example.com", "path": "/srv/handoff/your-repo"},
    "agents": [
        {"owner": "Epona", "harness": "Claude Code", "twin": "Epona"},
        {"owner": "Fenrir", "harness": "Codex", "twin": "Fenrir"},
        {"owner": "Garuda", "harness": "Claude Code", "twin": "Garuda"},
    ],
}


# ── Redaction ──────────────────────────────────────────────

def redact(value: str) -> str:
    """Rewrite home directories out of text bound for another machine."""
    return HOME_PATTERN.sub(lambda match: f"/{match.group(1)}/<user>", value)


def redact_deep(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_deep(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_deep(item) for key, item in value.items()}
    return value


# ── Capture ────────────────────────────────────────────────

def channel_state(root: Path, limit: int = MESSAGE_LIMIT) -> Dict[str, Any]:
    """Sessions and messages, through the channel's own read API.

    `Channel.history` is Fenrir's read-only query and `Channel.silence` is
    Garuda's per-peer record. Both are consumed rather than reimplemented: a
    third query over the same tables would drift from theirs. When `history` is
    not present in the installed channel yet, state is still published and the
    absence is recorded rather than papered over with a private query.
    """
    try:
        from handoff_channel import Channel
    except ImportError:
        return {"sessions": [], "messages": [], "messages_available": False,
                "truncated": False, "note": "channel module not importable"}

    channel = Channel(root)
    state: Dict[str, Any] = {"sessions": [], "messages": [],
                             "messages_available": False, "truncated": False}
    history = getattr(channel, "history", None)
    if callable(history):
        try:
            found = history(limit=limit)
        except Exception as error:  # a missing channel must not fail a publish
            state["note"] = f"history unavailable: {error}"
            return state
        state["sessions"] = [dict(row) for row in found.get("sessions", [])]
        state["messages"] = [dict(row) for row in found.get("messages", [])]
        state["messages_available"] = True
        state["truncated"] = bool(found.get("truncated"))
        return state

    # Older channel: publish reported state without bodies, and say so.
    state["note"] = "channel has no history query; message bodies were not published"
    try:
        state["sessions"] = [dict(row) for row in channel.silence()]
    except Exception as error:
        state["note"] = f"channel unreadable: {error}"
    return state


def capture(root: Path, limit: int = MESSAGE_LIMIT,
            attempts: int = CAPTURE_ATTEMPTS) -> Dict[str, Any]:
    """One snapshot of the ledger and the channel, taken at one moment.

    Reading the two stores in sequence can straddle a peer's write. The version
    is re-read after the channel and the capture restarts when it moved, so the
    document describes a state that actually existed.
    """
    ledger = root / "HANDOFF.md"
    if not ledger.is_file():
        raise PublishError(f"No HANDOFF.md under {root}")
    for _ in range(attempts):
        text = ledger.read_text(encoding="utf-8")
        version = ledger_version(text)
        channel = channel_state(root, limit=limit)
        if ledger_version(ledger.read_text(encoding="utf-8")) != version:
            continue
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "captured_at": time.time(),
            "repo": {"root": root.name, "remote": git_remote(root)},
            "ledger": {"version": version, "text": text},
            "channel": channel,
        }
        return redact_deep(snapshot)
    raise PublishError(
        f"The ledger changed during {attempts} capture attempts; a peer is writing "
        "steadily. Retry when the tree settles."
    )


def git_remote(root: Path) -> Optional[str]:
    try:
        done = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


# ── Slicing ────────────────────────────────────────────────

def entry_texts(text: str) -> Dict[str, List[str]]:
    """Every task entry's full text, grouped by owner.

    Uses the guard's own parser. Entry boundaries come from the parsed line
    numbers, so a heading inside a fenced example cannot start a slice.
    """
    lines = text.splitlines(True)
    tasks = parse_tasks(text)
    grouped: Dict[str, List[str]] = {}
    for index, task in enumerate(tasks):
        start = task.line - 1
        end = tasks[index + 1].line - 1 if index + 1 < len(tasks) else len(lines)
        if task.owner:
            grouped.setdefault(task.owner, []).append("".join(lines[start:end]).rstrip() + "\n")
    return grouped


def slice_for(snapshot: Dict[str, Any], agent: Dict[str, str]) -> Dict[str, Any]:
    """One agent's own work: its entries, its messages, its reported state."""
    owner = agent["owner"]
    entries = entry_texts(snapshot["ledger"]["text"]).get(owner, [])
    channel = snapshot["channel"]
    sessions = [row for row in channel["sessions"] if row.get("owner") == owner]
    ids = {row.get("id") or row.get("session") for row in sessions}
    messages = [
        row for row in channel["messages"]
        if row.get("sender") in ids or row.get("recipient") in ids
        or row.get("sender_owner") == owner or row.get("recipient_owner") == owner
        or row.get("recipient") == "*"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": snapshot["captured_at"],
        "twin": agent.get("twin", owner),
        "owner": owner,
        "harness": agent["harness"],
        "ledger_version": snapshot["ledger"]["version"],
        "entries": entries,
        "sessions": sessions,
        "messages": messages,
        "messages_available": channel.get("messages_available", False),
    }


def build_files(snapshot: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
    """Everything the destination should hold, keyed by relative path."""
    files = {
        "snapshot.json": json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        "ledger.md": snapshot["ledger"]["text"],
    }
    for agent in config["agents"]:
        piece = slice_for(snapshot, agent)
        name = piece["twin"]
        if "/" in name or name.startswith("."):
            raise PublishError(f"Unusable twin name: {name!r}")
        files[f"agents/{name}.json"] = json.dumps(piece, indent=2, sort_keys=True) + "\n"
    return files


def unmapped_owners(snapshot: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    """Owners holding *unfinished* entries that the agent map does not name.

    Their work still reaches the destination inside the whole ledger; what they
    do not get is a twin file, because the map is what says a twin exists.

    Only unfinished work is worth a warning. A ledger accumulates every owner
    that ever held a completed task, and naming two dozen retired sessions on
    every publish trains the reader to skip the line that matters.
    """
    mapped = {agent["owner"] for agent in config["agents"]}
    open_owners = {
        task.owner for task in parse_tasks(snapshot["ledger"]["text"])
        if task.owner and not task.completed
    }
    return sorted(open_owners - mapped)


def harness_mismatches(snapshot: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
    """Agents whose configured harness disagrees with what the ledger records.

    A Codex twin must not be handed work done in Claude Code: the harness is
    part of the identity the user asked to preserve.
    """
    recorded: Dict[str, set] = {}
    for task in parse_tasks(snapshot["ledger"]["text"]):
        if task.owner and task.harness:
            recorded.setdefault(task.owner, set()).add(task.harness)
    problems = []
    for agent in config["agents"]:
        seen = recorded.get(agent["owner"])
        if seen and agent["harness"] not in seen:
            problems.append(
                f"{agent['owner']} is configured as {agent['harness']} but the ledger "
                f"records {', '.join(sorted(seen))}"
            )
    return problems


# ── Transport ──────────────────────────────────────────────

def remote_command(path: str) -> str:
    """Unpack a tar stream into a staging directory, then swap it into place.

    A per-file copy leaves a reader seeing half of one publish and half of the
    next. One directory swap does not.
    """
    quoted = shlex.quote(path)
    staging = shlex.quote(path + ".incoming")
    previous = shlex.quote(path + ".previous")
    return (
        f"set -e; rm -rf {staging}; mkdir -p {staging}; tar -xf - -C {staging}; "
        f"rm -rf {previous}; if [ -d {quoted} ]; then mv {quoted} {previous}; fi; "
        f"mkdir -p \"$(dirname {quoted})\"; mv {staging} {quoted}"
    )


def write_tree(directory: Path, files: Dict[str, str]) -> None:
    for name, content in sorted(files.items()):
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def publish(files: Dict[str, str], destination: Dict[str, str],
            dry_run: bool = False, out: Optional[Path] = None) -> Dict[str, Any]:
    """Write the tree locally, then hand it to the destination over ssh."""
    result: Dict[str, Any] = {"files": sorted(files), "host": destination["host"],
                              "path": destination["path"], "published": False}
    with tempfile.TemporaryDirectory() as staging:
        directory = Path(staging)
        write_tree(directory, files)
        if out is not None:
            write_tree(out, files)
            result["out"] = str(out)
        if dry_run:
            result["command"] = remote_command(destination["path"])
            return result
        try:
            stream = subprocess.run(["tar", "-cf", "-", "-C", str(directory), "."],
                                    capture_output=True, check=True)
            done = subprocess.run(
                ["ssh", destination["host"], remote_command(destination["path"])],
                input=stream.stdout, capture_output=True, timeout=120)
        except FileNotFoundError as error:
            raise PublishError(f"{error.filename} is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise PublishError(f"{destination['host']} did not answer in time") from error
        except subprocess.CalledProcessError as error:
            raise PublishError(f"Could not pack the snapshot: {error}") from error
        if done.returncode != 0:
            raise PublishError(
                f"ssh to {destination['host']} failed: "
                f"{done.stderr.decode('utf-8', 'replace').strip() or done.returncode}"
            )
    result["published"] = True
    return result


# ── CLI ────────────────────────────────────────────────────

def report(result: Dict[str, Any], warnings: List[str]) -> None:
    for line in warnings:
        print(f"Warning: {line}", file=sys.stderr)
    for name in result["files"]:
        print(f"  {name}")
    if result.get("out"):
        print(f"Wrote {len(result['files'])} files to {result['out']}")
    if result["published"]:
        print(f"Published to {result['host']}:{result['path']}")
    else:
        print(f"Dry run; nothing was sent to {result['host']}:{result['path']}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["publish", "snapshot", "example", "check"])
    parser.add_argument("--root", default=".", help="Repository path or child path")
    parser.add_argument("--out", help="Also write the tree here")
    parser.add_argument("--limit", type=int, default=MESSAGE_LIMIT,
                        help="Most recent messages to include")
    parser.add_argument("--dry-run", action="store_true", help="Build but do not send")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    if args.command == "example":
        print(json.dumps(EXAMPLE_CONFIG, indent=2))
        return 0

    try:
        root = find_repo_root(Path(args.root).resolve())
        config = load_config(root)
        snapshot = capture(root, limit=args.limit)
        warnings = harness_mismatches(snapshot, config)
        unmapped = unmapped_owners(snapshot, config)
        if unmapped:
            warnings.append(
                "no twin configured for " + ", ".join(unmapped)
                + "; their entries ship inside ledger.md but get no agent file"
            )
        if args.command == "check":
            payload = {"config": str(config_path(root)), "warnings": warnings,
                       "ledger_version": snapshot["ledger"]["version"],
                       "messages_available": snapshot["channel"].get("messages_available"),
                       "agents": [agent["owner"] for agent in config["agents"]]}
            print(json.dumps(payload, indent=2) if args.json else
                  "\n".join([f"Config: {payload['config']}",
                             f"Ledger version: {payload['ledger_version']}",
                             f"Agents: {', '.join(payload['agents'])}"]
                            + [f"Warning: {line}" for line in warnings]))
            return 0
        files = build_files(snapshot, config)
        result = publish(files, config["destination"],
                         dry_run=args.dry_run or args.command == "snapshot",
                         out=Path(args.out).resolve() if args.out else None)
    except PublishError as error:
        print(f"handoff publish: {error}", file=sys.stderr)
        return 1
    if args.json:
        result["warnings"] = warnings
        print(json.dumps(result, indent=2))
    else:
        report(result, warnings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
