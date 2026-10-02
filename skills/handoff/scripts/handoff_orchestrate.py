#!/usr/bin/env python3
"""Durable objective, user update, capacity, and recovery commands for a lead."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from handoff_channel import Channel
from handoff_guard import (find_repo_root, insert_entry, ledger_lock, ledger_version,
                           outside_fence_lines, parse_tasks, swap_ledger, task_block_end,
                           atomic_write)
from handoff_lead import (insert_into_entry, mint_task_id, read_lead, read_task_id,
                          replace_line, require_lead)
from handoff_managed import (actors, configure, enroll, ensure_channel, members,
                             new_identity, require_managed, runtime_path,
                             runtime_state, settings, start_actor, start_team,
                             team_snapshot)


OBJECTIVE = "Objective: "
USER_EVENT = "Leader-event: "
CAPACITY = "Leader-capacity: "
MAX_TEXT = 4000


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bounded(value: str, label: str) -> str:
    value = value.strip()
    if not value or len(value) > MAX_TEXT or "\n" in value or "\r" in value:
        raise ValueError(f"{label} must be one line with 1-{MAX_TEXT} characters")
    return value


def header_records(text: str, prefix: str) -> list[dict]:
    records = []
    for line in outside_fence_lines(text.splitlines()):
        if line.startswith("## "):
            break
        if line.startswith(prefix):
            value = json.loads(line[len(prefix):])
            if not isinstance(value, dict):
                raise ValueError(f"{prefix.strip()} must contain a JSON object")
            records.append(value)
    return records


def add_header(text: str, prefix: str, value: dict) -> str:
    lines = text.splitlines()
    at = next((i for i, line in enumerate(outside_fence_lines(lines))
               if line.startswith("## ")), len(lines))
    lines[at:at] = [prefix + json.dumps(value, ensure_ascii=False, sort_keys=True), ""]
    return "\n".join(lines) + "\n"


def unique_tasks(text: str) -> dict[str, object]:
    result = {}
    for task in parse_tasks(text):
        identifier = read_task_id(text, task)
        if identifier:
            if identifier in result:
                raise ValueError(f"Duplicate task ID: {identifier}")
            result[identifier] = task
    return result


def objective_record(text: str, task: object) -> tuple[dict, int]:
    lines = outside_fence_lines(text.splitlines())
    end = task_block_end(lines, task.line)
    found = [(json.loads(lines[i][len(OBJECTIVE):]), i + 1)
             for i in range(task.line, end) if lines[i].startswith(OBJECTIVE)]
    if len(found) != 1 or not isinstance(found[0][0], dict):
        raise ValueError("Task must have exactly one Objective record")
    record, line = found[0]
    if not isinstance(record.get("criteria"), list) or not record["criteria"]:
        raise ValueError("Objective needs completion criteria")
    if not isinstance(record.get("children"), list):
        raise ValueError("Objective needs a child task list")
    return record, line


def objective_view(text: str, identifier: str) -> dict:
    tasks = unique_tasks(text)
    task = tasks.get(identifier)
    if task is None:
        raise ValueError(f"Unknown task ID: {identifier}")
    record, _ = objective_record(text, task)
    children = []
    for child_id in record["children"]:
        child = tasks.get(child_id)
        children.append({"id": child_id, "heading": child.heading if child else None,
                         "owner": child.owner if child else None,
                         "state": child.state if child else "missing"})
    return {"id": identifier, "heading": task.heading, "owner": task.owner,
            "state": task.state, "criteria": record["criteria"],
            "evidence": record.get("evidence", []), "children": children,
            "ready_for_review": bool(children) and all(c["state"] == "completed" for c in children)}


def create_objective(ledger: Path, version: str, owner: str, title: str,
                     criteria: list[str]) -> dict:
    title = bounded(title, "title")
    if len(title) > 160 or "(owner:" in title.casefold():
        raise ValueError("Title is too long or contains an owner label")
    criteria = [bounded(item, "criterion") for item in criteria]
    if not criteria:
        raise ValueError("Give at least one completion criterion")
    identifier = mint_task_id()
    date = datetime.now(timezone.utc).date().isoformat()

    def build(text: str) -> str:
        require_lead(text, owner)
        if identifier in unique_tasks(text):
            raise ValueError("New task ID collides with an existing task")
        entry = (f"## {date} - {title} (owner: {owner})\n\n"
                 "State:\n\n- [x] In progress\n- [ ] Completed\n\n"
                 f"Task: id={identifier}\n\n"
                 + OBJECTIVE + json.dumps({"criteria": criteria, "children": [],
                                           "evidence": []}, ensure_ascii=False, sort_keys=True)
                 + "\n\nSteps:\n\n"
                 "- [ ] Plan and assign the required work.\n"
                 "- [ ] Review all child tasks and completion evidence.\n"
                 "- [ ] Verify the user objective and report the result.\n\n"
                 "Status: In progress. Plan the work and record child task IDs.\n")
        return insert_entry(text, entry)

    return {**swap_ledger(ledger, version, build), "id": identifier}


def adopt_objective(ledger: Path, version: str, owner: str, identifier: str,
                    criteria: list[str]) -> dict:
    criteria = [bounded(item, "criterion") for item in criteria]
    if not criteria:
        raise ValueError("Give at least one completion criterion")

    def build(text: str) -> str:
        require_lead(text, owner)
        task = unique_tasks(text).get(identifier)
        if task is None or task.owner != owner or task.completed:
            raise ValueError("Lead must own an open task with this ID")
        masked = outside_fence_lines(text.splitlines())
        if any(row.startswith(OBJECTIVE)
               for row in masked[task.line:task_block_end(masked, task.line)]):
            raise ValueError("Task already has an Objective record")
        return insert_into_entry(text, task, [OBJECTIVE + json.dumps(
            {"criteria": criteria, "children": [], "evidence": []},
            ensure_ascii=False, sort_keys=True)])

    return swap_ledger(ledger, version, build)


def link_child(ledger: Path, version: str, owner: str, objective: str,
               child_id: str) -> dict:
    def build(text: str) -> str:
        require_lead(text, owner)
        tasks = unique_tasks(text)
        parent = tasks.get(objective)
        child = tasks.get(child_id)
        if parent is None or child is None or parent.owner != owner:
            raise ValueError("Objective and child must exist; lead must own the objective")
        if objective == child_id or parent.completed:
            raise ValueError("Cannot link an objective to itself or change a completed objective")
        record, line = objective_record(text, parent)
        if child_id in record["children"]:
            raise ValueError("Child is already linked")
        records = {}
        masked = outside_fence_lines(text.splitlines())
        for task_id, other in tasks.items():
            if any(row.startswith(OBJECTIVE)
                   for row in masked[other.line:task_block_end(masked, other.line)]):
                records[task_id] = objective_record(text, other)[0]
        if any(child_id in item["children"] for task_id, item in records.items()
               if task_id != objective):
            raise ValueError("A child already belongs to another objective")
        seen = set()
        pending = [child_id]
        while pending:
            candidate = pending.pop()
            if candidate == objective:
                raise ValueError("Objective links must not form a cycle")
            if candidate in seen:
                continue
            seen.add(candidate)
            pending.extend(records.get(candidate, {}).get("children", []))
        record["children"].append(child_id)
        return replace_line(text, line, OBJECTIVE + json.dumps(
            record, ensure_ascii=False, sort_keys=True))

    return swap_ledger(ledger, version, build)


def close_objective(ledger: Path, version: str, owner: str, identifier: str,
                    evidence: list[str]) -> dict:
    evidence = [bounded(item, "evidence") for item in evidence]

    def build(text: str) -> str:
        require_lead(text, owner)
        view = objective_view(text, identifier)
        task = unique_tasks(text)[identifier]
        if task.owner != owner or task.completed:
            raise ValueError("Lead must own an open objective")
        if not view["ready_for_review"]:
            raise ValueError("Every linked child must exist and be complete")
        if len(evidence) != len(view["criteria"]):
            raise ValueError("Give one evidence item for each completion criterion")
        record, line = objective_record(text, task)
        record["evidence"] = evidence
        text = replace_line(text, line, OBJECTIVE + json.dumps(
            record, ensure_ascii=False, sort_keys=True))
        lines = text.splitlines()
        end = task_block_end(lines, task.line)
        for i in range(task.line, end):
            if lines[i] == "- [ ] Completed":
                lines[i] = "- [x] Completed"
            elif lines[i].startswith("- [ ] "):
                lines[i] = "- [x] " + lines[i][6:]
            elif lines[i].startswith("Status:"):
                lines[i] = ("Status: Completed " + stamp() + ". Criteria evidence: "
                            + " | ".join(evidence))
                break
        return "\n".join(lines) + "\n"

    return swap_ledger(ledger, version, build)


def post_event(ledger: Path, version: str, sender: str, recipient: str,
               body: str, kind: str) -> dict:
    body = bounded(body, "message")
    identifier = uuid.uuid4().hex

    def build(text: str) -> str:
        if kind in ("report", "capacity_request"):
            require_lead(text, sender)
        elif kind == "message":
            lead = read_lead(text)
            if lead is None or lead.owner != recipient or lead.state() != "active":
                raise ValueError("There is no active lead for this message")
        else:
            raise ValueError("Invalid event type")
        return add_header(text, USER_EVENT, {"id": identifier, "created": stamp(),
                                             "from": sender, "to": recipient,
                                             "kind": kind, "body": body})

    result = {**swap_ledger(ledger, version, build), "id": identifier}
    if result.get("status") == "applied":
        # The ledger is authoritative. Channel delivery only wakes a resident
        # managed lead sooner and can fail without rolling the ledger back.
        try:
            channel = Channel(ledger.parent)
            lead_owner = recipient if kind == "message" else sender
            lead_session = channel.session_for_owner(lead_owner)
            if lead_session is None:
                current = ledger.read_text(encoding="utf-8")
                actor = next((item for item in actors(current)
                              if item["role"] == "lead" and item["owner"] == lead_owner), None)
                if actor is not None:
                    channel, lead_session = ensure_channel(ledger.parent, actor)
            if lead_session is not None:
                user_session = channel.session_for_owner("HandoffUser")
                if user_session is None:
                    user_session = channel.join("HandoffUser", "User")["session"]
                source, target = ((user_session, lead_session) if kind == "message"
                                  else (lead_session, user_session))
                channel.send(source, target, body, message_id=identifier)
                result["delivery"] = "channel"
            else:
                result["delivery"] = "ledger only; lead has no channel session"
        except (OSError, ValueError) as error:
            result["delivery_error"] = str(error)
    return result


def capacity_policy(text: str) -> dict:
    rows = header_records(text, CAPACITY)
    if len(rows) > 1:
        raise ValueError("More than one capacity policy")
    value = rows[0] if rows else {"mode": "request", "max_workers": 0}
    if value.get("mode") not in ("request", "auto") or not isinstance(
            value.get("max_workers"), int) or not 0 <= value["max_workers"] <= 16:
        raise ValueError("Invalid capacity policy")
    return value


def set_capacity(ledger: Path, version: str, mode: str, max_workers: int) -> dict:
    if mode not in ("request", "auto") or not 0 <= max_workers <= 16:
        raise ValueError("Invalid capacity policy")

    def build(text: str) -> str:
        require_managed(text)
        lines = text.splitlines()
        for i, row in enumerate(outside_fence_lines(lines)):
            if row.startswith(CAPACITY):
                lines[i] = "Leader-capacity-history: " + row[len(CAPACITY):]
        return add_header("\n".join(lines) + "\n", CAPACITY,
                          {"mode": mode, "max_workers": max_workers})

    return swap_ledger(ledger, version, build)


def request_worker(ledger: Path, version: str, owner: str, reason: str,
                   harness: str) -> dict:
    reason = bounded(reason, "reason")
    if harness not in ("codex", "claude"):
        raise ValueError("Worker harness must be codex or claude")
    root = ledger.parent
    text = ledger.read_text(encoding="utf-8")
    if ledger_version(text) != version:
        return {"status": "conflict", "current_version": ledger_version(text)}
    config = require_managed(text)
    require_lead(text, owner)
    if config["owner"] != owner:
        raise ValueError("Only the managed lead can request a worker")
    policy = capacity_policy(text)
    if policy["mode"] == "request":
        return post_event(ledger, version, owner, "user", reason, "capacity_request")
    if len(members(text)) >= policy["max_workers"]:
        raise ValueError("Worker limit reached; ask the user to change the policy")
    identity = new_identity(ledger, harness)
    result = enroll(ledger, version, identity[0], identity[1], harness)
    if result["status"] == "applied":
        actor = next(a for a in actors(ledger.read_text(encoding="utf-8"))
                     if a["owner"] == identity[0])
        try:
            start_actor(root, actor)
            result["worker"] = identity[0]
        except (OSError, ValueError) as error:
            result["worker"] = identity[0]
            result["start_error"] = str(error)
    return result


def recovery_view(root: Path) -> dict:
    ledger = root / "HANDOFF.md"
    text = ledger.read_text(encoding="utf-8")
    rows = []
    try:
        managed_actors = actors(text)
    except ValueError:
        managed_actors = []
    for actor in managed_actors:
        state = runtime_state(root, actor)
        status = state.get("state", "unknown")
        rows.append({"owner": actor["owner"], "role": actor["role"],
                     "state": status, "child_pid": state.get("child_pid"),
                     "note": state.get("note"),
                     "action": ("audit writers and preserve changes before recovery"
                                if status in ("running", "interrupted")
                                else "review failure before explicit retry"
                                if status == "error" else "start runner"
                                if status in ("not started", "monitor stopped")
                                else "review recorded work")})
    changed = subprocess.run(["git", "status", "--short"], cwd=root,
                             capture_output=True, text=True, timeout=5, check=False)
    return {"version": ledger_version(text), "actors": rows,
            "open_tasks": [{"id": read_task_id(text, task), "heading": task.heading,
                            "owner": task.owner, "state": task.state}
                           for task in parse_tasks(text) if task.state != "completed"],
            "working_tree": changed.stdout.splitlines() if changed.returncode == 0 else [],
            "working_tree_error": changed.stderr.strip() if changed.returncode else None}


def resume_interrupted(root: Path, owner: str, version: str,
                       preservation: Path, confirm_stopped: bool) -> dict:
    if not confirm_stopped or not preservation.is_file():
        raise ValueError("Confirm stopped writers and give an existing recovery copy")
    try:
        preservation.resolve().relative_to(root.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("Keep the recovery copy outside the working tree")
    ledger = root / "HANDOFF.md"
    text = ledger.read_text(encoding="utf-8")
    if ledger_version(text) != version:
        raise ValueError("Ledger changed; re-audit before recovery")
    require_managed(text)
    actor = next((a for a in actors(text) if a["owner"] == owner), None)
    if actor is None:
        raise ValueError("Unknown managed actor")
    path = runtime_path(root, actor)
    with ledger_lock(path, timeout=0):
        state = runtime_state(root, actor)
        if state.get("state") not in ("running", "interrupted"):
            raise ValueError("Actor has no interrupted turn")
        state.update(state="stopped", child_pid=None, seen=None,
                     note=f"Recovery copy: {preservation.resolve()}; writer stop confirmed")
        atomic_write(path, json.dumps(state))
    start_actor(root, actor)
    return {"owner": owner, "status": "restarted", "preservation": str(preservation)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    def common(name: str, write: bool = True) -> argparse.ArgumentParser:
        command = sub.add_parser(name)
        command.add_argument("--root", default=".")
        if write:
            command.add_argument("--expect-version", required=True)
        return command
    create = common("objective-create")
    create.add_argument("--owner", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--criterion", action="append", required=True)
    adopt = common("objective-adopt")
    adopt.add_argument("--owner", required=True)
    adopt.add_argument("--objective", required=True)
    adopt.add_argument("--criterion", action="append", required=True)
    link = common("objective-link")
    link.add_argument("--owner", required=True)
    link.add_argument("--objective", required=True)
    link.add_argument("--child", required=True)
    close = common("objective-close")
    close.add_argument("--owner", required=True)
    close.add_argument("--objective", required=True)
    close.add_argument("--evidence", action="append", required=True)
    status = common("objective-status", False)
    status.add_argument("--objective", required=True)
    event = common("message")
    event.add_argument("--from", dest="sender", required=True)
    event.add_argument("--to", dest="recipient", required=True)
    event.add_argument("--body", required=True)
    event.add_argument("--kind", choices=("message", "report"), required=True)
    common("messages", False)
    policy = common("capacity-set")
    policy.add_argument("--mode", choices=("request", "auto"), required=True)
    policy.add_argument("--max-workers", type=int, required=True)
    worker = common("worker-request")
    worker.add_argument("--owner", required=True)
    worker.add_argument("--reason", required=True)
    worker.add_argument("--harness", choices=("codex", "claude"), default="codex")
    common("recovery", False)
    resume = common("resume-interrupted")
    resume.add_argument("--owner", required=True)
    resume.add_argument("--preservation", type=Path, required=True)
    resume.add_argument("--confirm-stopped", action="store_true")
    team_configure = common("team-configure")
    team_configure.add_argument("--harness", choices=("codex", "claude"), default="codex")
    team_configure.add_argument("--interval", type=int, choices=(30, 60, 120, 300),
                                default=60)
    team_enroll = common("team-enroll")
    team_enroll.add_argument("--harness", choices=("codex", "claude"), default="codex")
    team_enroll.add_argument("--objective")
    team_enroll.add_argument("--start", action="store_true")
    team_objective = common("team-objective")
    team_objective.add_argument("--title", required=True)
    team_objective.add_argument("--criterion", action="append", required=True)
    common("team-start", False)
    common("team-status", False)
    args = parser.parse_args(argv)
    try:
        root = find_repo_root(Path(args.root))
        ledger = root / "HANDOFF.md"
        if args.command == "objective-create":
            result = create_objective(ledger, args.expect_version, args.owner,
                                      args.title, args.criterion)
        elif args.command == "objective-adopt":
            result = adopt_objective(ledger, args.expect_version, args.owner,
                                     args.objective, args.criterion)
        elif args.command == "objective-link":
            result = link_child(ledger, args.expect_version, args.owner,
                                args.objective, args.child)
        elif args.command == "objective-close":
            result = close_objective(ledger, args.expect_version, args.owner,
                                     args.objective, args.evidence)
        elif args.command == "objective-status":
            result = objective_view(ledger.read_text(encoding="utf-8"), args.objective)
        elif args.command == "message":
            result = post_event(ledger, args.expect_version, args.sender,
                                args.recipient, args.body, args.kind)
        elif args.command == "messages":
            result = {"messages": header_records(ledger.read_text(encoding="utf-8"),
                                                   USER_EVENT)}
        elif args.command == "capacity-set":
            result = set_capacity(ledger, args.expect_version, args.mode,
                                  args.max_workers)
        elif args.command == "worker-request":
            result = request_worker(ledger, args.expect_version, args.owner,
                                    args.reason, args.harness)
        elif args.command == "recovery":
            result = recovery_view(root)
        elif args.command == "resume-interrupted":
            result = resume_interrupted(root, args.owner, args.expect_version,
                                        args.preservation, args.confirm_stopped)
        elif args.command == "team-configure":
            current = settings(ledger.read_text(encoding="utf-8"))
            identity = None if current["owner"] else new_identity(ledger, args.harness)
            result = configure(ledger, args.expect_version, "managed", args.harness,
                               args.interval, identity)
            if result.get("status") == "applied":
                result["lead"] = current["owner"] or identity[0]
        elif args.command == "team-enroll":
            identity = new_identity(ledger, args.harness)
            result = enroll(ledger, args.expect_version, identity[0], identity[1],
                            args.harness, args.objective)
            if result.get("status") == "applied":
                result["worker"] = identity[0]
                if args.start:
                    actor = next(a for a in actors(ledger.read_text(encoding="utf-8"))
                                 if a["owner"] == identity[0])
                    try:
                        start_actor(root, actor)
                    except (OSError, ValueError) as error:
                        result["start_error"] = str(error)
        elif args.command == "team-objective":
            current = ledger.read_text(encoding="utf-8")
            config = require_managed(current)
            result = create_objective(ledger, args.expect_version, config["owner"],
                                      args.title, args.criterion)
        elif args.command == "team-start":
            start_team(root)
            result = {"status": "started"}
        else:
            result = team_snapshot(root, ledger.read_text(encoding="utf-8"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in ("conflict", "rejected") else 3
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
