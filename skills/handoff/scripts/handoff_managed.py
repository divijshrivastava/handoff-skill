#!/usr/bin/env python3
"""Repository-configured lead and worker runners, backed by the handoff ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

from handoff_channel import Channel
from handoff_guard import (
    atomic_write, find_repo_root, harness_for_agent, insert_entry, ledger_lock,
    ledger_version, outside_fence_lines, owner_label_error, parse_tasks,
    claim_name, taken_names, session_intake_entry, swap_ledger,
)
from handoff_keys import resolve_agent
from handoff_lead import (build_claim, build_resign, check_in_peers, read_lead,
                          read_task_id, mint_task_id)


HARNESSES = ("codex", "claude")
INTERVALS = (30, 60, 120, 300)
CONFIG = "Coordination: "
MEMBER = "Managed-agent: "
DEFAULTS = {"mode": "direct", "harness": "codex", "interval": 60,
            "owner": "", "seed": "", "generation": ""}


def header_records(text: str, prefix: str) -> list[dict]:
    records = []
    for line in outside_fence_lines(text.splitlines()):
        line = line.strip()
        if line.startswith("## "):
            break
        if line.startswith(prefix.rstrip()):
            value = json.loads(line[len(prefix.rstrip()):].strip())
            if not isinstance(value, dict):
                raise ValueError(f"{prefix.strip()} must contain a JSON object")
            records.append(value)
    return records


def valid_identity(owner: str, seed: str) -> None:
    if not isinstance(owner, str) or owner_label_error(owner) or ";" in owner:
        raise ValueError("Invalid managed agent owner")
    try:
        if str(uuid.UUID(seed)) != seed:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Managed agent seed must be a canonical UUID")


def settings(text: str) -> dict:
    rows = header_records(text, CONFIG)
    if len(rows) > 1:
        raise ValueError("More than one repository coordination setting")
    config = {**DEFAULTS, **(rows[0] if rows else {})}
    if config["mode"] not in ("direct", "managed"):
        raise ValueError("Coordination mode must be direct or managed")
    if config["harness"] not in HARNESSES or config["interval"] not in INTERVALS:
        raise ValueError("Unsupported lead CLI or review interval")
    if config["owner"] or config["mode"] == "managed":
        valid_identity(config["owner"], config["seed"])
    return config


def members(text: str) -> list[dict]:
    rows = header_records(text, MEMBER)
    owners, seeds = set(), set()
    for row in rows:
        valid_identity(row.get("owner"), row.get("seed"))
        if row.get("harness") not in HARNESSES or not row.get("lead"):
            raise ValueError("Invalid managed worker membership")
        if row["owner"] in owners or row["seed"] in seeds:
            raise ValueError("Duplicate managed worker membership")
        owners.add(row["owner"])
        seeds.add(row["seed"])
    return rows


def add_header(text: str, prefix: str, value: dict) -> str:
    lines = text.splitlines()
    masked = outside_fence_lines(lines)
    at = next((i for i, line in enumerate(masked) if line.startswith("## ")), len(lines))
    lines[at:at] = [prefix + json.dumps(value, ensure_ascii=False, sort_keys=True), ""]
    return "\n".join(lines) + "\n"


def require_managed(text: str) -> dict:
    config = settings(text)
    lead = read_lead(text)
    if config["mode"] != "managed":
        raise ValueError("This repository uses direct mode")
    if lead is None or lead.owner != config["owner"] or lead.state() != "active":
        raise ValueError("Managed lead mandate is missing, replaced, or expired; review Config")
    return config


def configure(ledger: Path, version: str, mode: str, harness: str, interval: int,
              identity: tuple[str, str] | None = None) -> dict:
    """A user config save appoints the lead before any managed process can run."""
    def build(text: str) -> str:
        old = settings(text)
        config = {**old, "mode": mode, "harness": harness, "interval": interval}
        if old["owner"] and old["harness"] != harness:
            raise ValueError("Keep the existing lead CLI; changing it requires a new lead identity")
        if mode == "managed":
            if not config["owner"]:
                if identity is None:
                    raise ValueError("A claimed lead identity is required")
                config["owner"], config["seed"] = identity
            valid_identity(config["owner"], config["seed"])
            text = build_claim(text, config["owner"], 168)
        elif mode == "direct":
            lead = read_lead(text)
            if lead and lead.owner == old["owner"]:
                text = build_resign(text, lead.owner)
        config["generation"] = str(uuid.uuid4())
        # Preserve old settings as history, never erase task entries.
        lines = text.splitlines()
        for i, line in enumerate(outside_fence_lines(lines)):
            if line.startswith("## "):
                break
            if line.startswith(CONFIG):
                lines[i] = "Coordination-history: " + line[len(CONFIG):]
        text = add_header("\n".join(lines) + "\n", CONFIG, config)
        settings(text)  # Reject invalid options inside the same locked write.
        return text
    return swap_ledger(ledger, version, build)


def new_identity(ledger: Path, harness: str) -> tuple[str, str]:
    seed = str(uuid.uuid4())
    text = ledger.read_text(encoding="utf-8")
    reserved = taken_names(text) | {a["owner"] for a in actors(text)}
    owner, _ = claim_name(seed, ledger.resolve(), reserved, harness=harness_for_agent(harness))
    return owner, seed


def objective_entry(owner: str, body: str) -> str:
    if not body.strip() or len(body) > 8000:
        raise ValueError("A lead objective must contain 1–8000 characters")
    # Keep user text inside the status paragraph, not as injectable ledger lines.
    entry = session_intake_entry(owner, task=" ".join(body.split()))
    entry = entry.replace("Steps:", f"Task: id={mint_task_id()}\n\nSteps:", 1)
    entry = entry.replace("Implement the requested outcome.",
                          "Coordinate the requested outcome through the managed workers.")
    return entry


def give_objective(ledger: Path, version: str, body: str) -> dict:
    def build(text: str) -> str:
        config = require_managed(text)
        return insert_entry(text, objective_entry(config["owner"], body))
    return swap_ledger(ledger, version, build)


def enroll(ledger: Path, version: str, owner: str, seed: str, harness: str,
           objective: str | None = None) -> dict:
    valid_identity(owner, seed)
    if harness not in HARNESSES:
        raise ValueError("Managed workers currently support Codex and Claude Code")
    def build(text: str) -> str:
        config = require_managed(text)
        existing = members(text)
        if owner == config["owner"] or any(r["owner"] == owner or r["seed"] == seed for r in existing):
            raise ValueError("That agent already belongs to the team")
        text = add_header(text, MEMBER, {"owner": owner, "seed": seed,
                                        "harness": harness, "lead": config["owner"]})
        if objective and objective.strip():
            text = insert_entry(text, objective_entry(config["owner"], objective))
        return text
    return swap_ledger(ledger, version, build)


def actors(text: str) -> list[dict]:
    config = settings(text)
    if not config["owner"]:
        return []
    if any(row["owner"] == config["owner"] or row["seed"] == config["seed"] for row in members(text)):
        raise ValueError("A lead and worker cannot share an identity")
    return [{"owner": config["owner"], "seed": config["seed"],
             "harness": config["harness"], "role": "lead", "lead": config["owner"]}] + [
        {**row, "role": "worker"} for row in members(text) if row["lead"] == config["owner"]]


def runtime_path(root: Path, actor: dict) -> Path:
    valid_identity(actor["owner"], actor["seed"])
    return root / ".handoff" / "managed" / (actor["seed"] + ".json")


def runtime_state(root: Path, actor: dict) -> dict:
    path = runtime_path(root, actor)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Runtime record is not an object")
    except FileNotFoundError:
        return {"state": "not started", "note": "Press r in Team to start the runners"}
    except (OSError, ValueError) as error:
        return {"state": "error", "note": str(error)}
    if state.get("state") == "watching" and time.time() - state.get("checked", 0) > 10:
        state = {**state, "state": "monitor stopped", "note": "Press r to resume monitoring"}
    return state


def start_actor(root: Path, actor: dict) -> subprocess.Popen | None:
    """Only explicit managed-mode actions call this; status rendering never spawns."""
    path = runtime_path(root, actor)
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent.parent / ".gitignore").write_text("*\n", encoding="utf-8")
    # A live runner owns this lock throughout every child invocation.
    try:
        with ledger_lock(path, timeout=0):
            pass
    except TimeoutError:
        return
    if path.exists():
        state = runtime_state(root, actor).get("state")
        if state == "error":
            raise ValueError(f"{actor['owner']} has a failed turn. Review its report in Team, resolve the blocker, then press R")
        if state in ("running", "interrupted"):
            raise ValueError(f"{actor['owner']} has an interrupted or running turn; audit its process and work before recovery")
    with path.with_suffix(".runner.log").open("ab") as log:
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", "--root", str(root),
                                 "--owner", actor["owner"]], cwd=root, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, **options)


def start_team(root: Path) -> None:
    text = (root / "HANDOFF.md").read_text(encoding="utf-8")
    require_managed(text)
    for actor in actors(text):
        if not resolve_agent(actor["harness"]):
            raise ValueError(f"{actor['harness']} is not installed or not on PATH")
    for actor in actors(text):
        start_actor(root, actor)


def retry_failed(root: Path, owner: str) -> None:
    """Explicit user retry of a cleanly exited failure; never recover a crash by inference."""
    text = (root / "HANDOFF.md").read_text(encoding="utf-8")
    require_managed(text)
    actor = next((a for a in actors(text) if a["owner"] == owner), None)
    if actor is None:
        raise ValueError("Select a managed actor")
    path = runtime_path(root, actor)
    with ledger_lock(path, timeout=0):
        state = runtime_state(root, actor)
        if state.get("state") != "error" or state.get("child_pid") is not None:
            raise ValueError("Only a cleanly exited failed turn can be retried here; audit interrupted writers separately")
        state.update(state="stopped", seen=None, note="User requested retry after reviewing the failure")
        atomic_write(path, json.dumps(state))
    start_actor(root, actor)


def team_snapshot(root: Path, text: str) -> dict:
    config = settings(text)
    tasks = parse_tasks(text)
    rows = []
    for actor in actors(text):
        owned = [t for t in tasks if t.owner == actor["owner"]]
        rows.append({**actor, "runtime": runtime_state(root, actor),
                     "open": sum(t.state != "completed" for t in owned),
                     "completed": sum(t.state == "completed" for t in owned)})
    channel = Channel(root)
    history = channel.history() if channel.path.exists() else {"sessions": [], "messages": []}
    names = {a["owner"] for a in rows}
    ids = {s["id"] for s in history["sessions"] if s["owner"] in names}
    interactions = [m for m in history["messages"] if m["sender"] in ids or m["recipient"] in ids]
    return {"config": config, "actors": rows, "interactions": interactions,
            "lead": read_lead(text).as_dict() if read_lead(text) else None}


def ensure_channel(root: Path, actor: dict) -> tuple[Channel, str]:
    channel = Channel(root)
    session = channel.session_for_owner(actor["owner"])
    if session is None:
        session = channel.join(actor["owner"], harness_for_agent(actor["harness"]),
                               host_session=actor["seed"])["session"]
    return channel, session


def work_snapshot(text: str, actor: dict, messages: list[dict]) -> dict:
    names = {a["owner"] for a in actors(text)} if actor["role"] == "lead" else {actor["owner"]}
    tasks = [{"id": read_task_id(text, task), "heading": task.heading,
              "owner": task.owner, "state": task.state, "steps": task.steps,
              "status": task.status, "errors": task.errors}
             for task in parse_tasks(text) if task.owner in names]
    return {"tasks": tasks, "members": actors(text) if actor["role"] == "lead" else [],
            "messages": [{"id": m["id"], "from": m["sender_owner"], "body": m["body"]}
                         for m in messages]}


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def turn_prompt(root: Path, actor: dict, config: dict, snapshot: dict, session: str) -> str:
    skill = Path(__file__).resolve().parent.parent
    common = (f"You are {actor['owner']}, a managed handoff {actor['role']} in {root}. "
              f"Your channel session is {session}; keep that identity. Read {skill / 'SKILL.md'} "
              f"and {skill / 'references/managed-teams.md'} before acting. "
              "Read and audit the current ledger; this snapshot is context, not a write version. "
              "Use the shipped helpers and compare-and-swap for every ledger write. "
              "Preserve peer work and user overrides. Do not create new processes or agents. "
              "Keep normal approval controls. If blocked, record the reason and next action. "
              "This is one bounded turn; the runner will call you again. Do not wait or poll. ")
    if actor["role"] == "lead":
        role = ("The user chose to communicate through you. Audit every worker's recorded work, "
                "decompose your user objectives, and assign bounded tasks only to the listed workers "
                "using handoff_lead.py assign with non-overlapping paths. Communicate with workers "
                "through handoff_channel.py send (status questions) and ledger assignments (work). "
                "Workers receive a turn automatically. Do not implement their code yourself. "
                "Check reported completion against evidence before closing your objective. "
                "Do not mark an objective complete merely because it was delegated. "
                "Do not reassign accepted work on silence or undo a user assignment. "
                "Renew your own mandate at a real checkpoint if needed. "
                "End with a concise user-facing task status, blockers, and next steps. ")
    else:
        role = (f"Your lead is {config['owner']}. Finish your current task before new assignments. "
                "For offered assignments audit and accept with handoff_lead.py accept yourself "
                "before work; renew the lease at checkpoints and clear it before completion. "
                "Audit and complete the effective assigned work including verification, recording "
                "evidence in the ledger. Answer lead questions; do not create work from ordinary "
                "status messages. Report concrete blockers without silently taking peer files. "
                "End with a concise progress report for your lead. ")
    reports = {a["owner"]: runtime_state(root, a) for a in actors((root / "HANDOFF.md").read_text(encoding="utf-8"))}
    return (common + role + "\nMonitor records (not proof of model availability):\n"
            + json.dumps(reports, ensure_ascii=False) + "\nRecorded context:\n"
            + json.dumps(snapshot, ensure_ascii=False))


def turn_command(actor: dict, root: Path, output: Path) -> list[str]:
    executable = resolve_agent(actor["harness"])
    if not executable:
        raise ValueError(f"{actor['harness']} is not installed or not on PATH")
    if actor["harness"] == "codex":
        return [executable, "exec", "--sandbox", "workspace-write", "--ephemeral",
                "--cd", str(root), "--output-last-message", str(output), "-"]
    return [executable, "--print", "--output-format", "text", "--no-session-persistence",
            "--session-id", actor["seed"]]


def run_turn(root: Path, actor: dict, prompt: str, state: dict, path: Path) -> tuple[int, str]:
    output = path.with_suffix(".reply.txt")
    # Codex writes its final answer separately; never mistake an older reply for a new one.
    output.write_text("", encoding="utf-8")
    command = turn_command(actor, root, output)
    env = {**os.environ, "HANDOFF_SESSION": actor["seed"],
           "HANDOFF_HARNESS": harness_for_agent(actor["harness"])}
    # Record intent BEFORE process creation. A crash in either side of Popen is
    # uncertain and must never leave a replayable "watching" record.
    state.update(state="running", child_pid=None, started=time.time())
    atomic_write(path, json.dumps(state))
    with path.with_suffix(".turn.log").open("w", encoding="utf-8") as log:
        try:
            child = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.PIPE,
                                     stdout=log, stderr=log, text=True, encoding="utf-8")
        except OSError as error:
            state.update(state="error", note=str(error))
            atomic_write(path, json.dumps(state))
            raise
        with child:
            state.update(state="running", child_pid=child.pid, started=time.time())
            atomic_write(path, json.dumps(state))
            child.communicate(prompt)
            code = child.returncode
    if actor["harness"] == "claude" or code:
        report = path.with_suffix(".turn.log").read_text(encoding="utf-8", errors="replace")[-7000:]
    else:
        report = output.read_text(encoding="utf-8", errors="replace")[-7000:]
    return code, report.strip() or f"{actor['harness']} exited {code} without a final report"


def run_actor(root: Path, owner: str, once: bool = False) -> int:
    ledger = root / "HANDOFF.md"
    text = ledger.read_text(encoding="utf-8")
    config = require_managed(text)
    actor = next((a for a in actors(text) if a["owner"] == owner), None)
    if actor is None:
        raise ValueError("This owner is not a member of the configured team")
    path = runtime_path(root, actor)
    path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_lock(path, timeout=0):
        state = runtime_state(root, actor)
        if state.get("state") in ("running", "interrupted", "error"):
            state.update(state="interrupted", note="Prior turn needs audit; no work was replayed")
            atomic_write(path, json.dumps(state))
            return 1
        channel, session = ensure_channel(root, actor)
        last_turn = float("-inf")
        while True:
            text = ledger.read_text(encoding="utf-8")
            current = settings(text)
            if current["mode"] != "managed" or current["owner"] != config["owner"]:
                state.update(state="stopped", note="Repository configuration changed; no new turns started")
                atomic_write(path, json.dumps(state))
                return 0
            config = current
            require_managed(text)
            if owner not in {a["owner"] for a in actors(text)}:
                raise ValueError("Team membership changed")
            if actor["role"] == "lead":
                # Newly joined workers may register after the lead's first turn.
                # Stable message IDs make later scans harmless.
                check_in_peers(root, owner)
            messages = channel.inbox(session)
            snapshot = work_snapshot(text, actor, messages)
            signature = fingerprint(snapshot)
            has_work = any(t["state"] != "completed" for t in snapshot["tasks"]) or bool(messages)
            changed = signature != state.get("seen")
            periodic = actor["role"] == "lead" and has_work
            due = time.monotonic() - last_turn >= config["interval"]
            if due and ((changed and has_work) or periodic):
                channel.report(session, "working", f"Managed {actor['role']} turn; recorded progress is in HANDOFF.md")
                prompt = turn_prompt(root, actor, config, snapshot, session)
                code, report = run_turn(root, actor, prompt, state, path)
                state.update(state="error" if code else "watching", note=report,
                             finished=time.time(), checked=time.time(), child_pid=None)
                channel.report(session, "unavailable" if code else "waiting", report)
                if code:
                    atomic_write(path, json.dumps(state))
                    return code
                for message in messages:
                    channel.acknowledge(session, message["id"])
                if actor["role"] == "worker":
                    lead_session = channel.session_for_owner(config["owner"])
                    if lead_session:
                        channel.send(session, lead_session, report)
                latest = ledger.read_text(encoding="utf-8")
                # Suppress the worker's own checkpoint writes, but do not consume new messages.
                accounted = work_snapshot(latest, actor, [])
                original = {t["id"] or t["heading"] for t in snapshot["tasks"]}
                accounted["tasks"] = [t for t in accounted["tasks"] if (t["id"] or t["heading"]) in original]
                state["seen"] = fingerprint(accounted)
                state["reviewed_version"] = ledger_version(text)
                last_turn = time.monotonic()
            state.update(checked=time.time())
            if state.get("state") not in ("error", "watching"):
                state.update(state="watching", note="Watching for assignments and lead messages")
            atomic_write(path, json.dumps(state))
            if once:
                return 0
            time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "start", "run"))
    parser.add_argument("--root", default=".")
    parser.add_argument("--owner")
    parser.add_argument("--once", action="store_true", help="Check once without a polling loop")
    args = parser.parse_args(argv)
    root = find_repo_root(Path(args.root))
    try:
        if args.command == "status":
            print(json.dumps(team_snapshot(root, (root / "HANDOFF.md").read_text(encoding="utf-8")), indent=2))
        elif args.command == "start":
            start_team(root)
        else:
            return run_actor(root, args.owner, args.once)
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        if args.command == "run" and args.owner:
            try:
                actor = next(a for a in actors((root / "HANDOFF.md").read_text(encoding="utf-8"))
                             if a["owner"] == args.owner)
                path = runtime_path(root, actor)
                with ledger_lock(path, timeout=0):
                    state = runtime_state(root, actor)
                    state.update(state="interrupted" if state.get("state") == "running" else "error",
                                 note=str(error), checked=time.time())
                    atomic_write(path, json.dumps(state))
            except (OSError, ValueError, RuntimeError, StopIteration):
                pass
        print(f"handoff-managed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
