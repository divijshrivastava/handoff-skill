#!/usr/bin/env python3
"""Read-only structure checks and template generation for HANDOFF.md."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
OWNER_RE = re.compile(r"\((?:owner|agent):\s*([^)]+)\)", re.IGNORECASE)
BOX_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")


@dataclass
class Task:
    heading: str
    owner: str | None
    line: int
    modern: bool
    in_progress: bool | None
    completed: bool | None
    steps: list[tuple[bool, str]]
    has_status: bool
    state: str
    errors: list[str]


def outside_fence_headings(lines: list[str]) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING_RE.match(line)
        if match:
            headings.append((index, match.group(1)))
    return headings


def checkbox_value(lines: Iterable[str], label: str) -> bool | None:
    wanted = label.casefold()
    for line in lines:
        match = BOX_RE.match(line)
        if match and match.group(2).strip().casefold() == wanted:
            return match.group(1).casefold() == "x"
    return None


def parse_tasks(text: str) -> list[Task]:
    lines = text.splitlines()
    headings = outside_fence_headings(lines)
    tasks: list[Task] = []

    for position, (start, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        block = lines[start + 1 : end]
        state_index = next(
            (index for index, line in enumerate(block) if line.strip() == "State:"),
            None,
        )
        steps_index = next(
            (index for index, line in enumerate(block) if line.strip() == "Steps:"),
            None,
        )
        modern = state_index is not None or steps_index is not None
        in_progress: bool | None = None
        completed: bool | None = None
        steps: list[tuple[bool, str]] = []
        errors: list[str] = []

        if modern:
            if state_index is None:
                errors.append("missing State section")
                state_lines: list[str] = []
            else:
                state_end = steps_index if steps_index is not None else len(block)
                state_lines = block[state_index + 1 : state_end]
            in_progress = checkbox_value(state_lines, "In progress")
            completed = checkbox_value(state_lines, "Completed")
            if in_progress is None:
                errors.append("missing In progress checkbox")
            if completed is None:
                errors.append("missing Completed checkbox")

            if steps_index is None:
                errors.append("missing Steps section")
            else:
                for line in block[steps_index + 1 :]:
                    if line.strip().startswith("Status:"):
                        break
                    match = BOX_RE.match(line)
                    if match:
                        label = match.group(2).strip()
                        if label.casefold() not in {"in progress", "completed"}:
                            steps.append((match.group(1).casefold() == "x", label))
                if not steps:
                    errors.append("no concrete steps")

            if completed and not in_progress:
                errors.append("Completed is checked while In progress is unchecked")
            if completed and any(not checked for checked, _ in steps):
                errors.append("completed task has unchecked steps")
            if in_progress is False and completed is False and any(checked for checked, _ in steps):
                errors.append("pending task has checked steps")

        has_status = any(line.strip().startswith("Status:") for line in block)
        if modern and not has_status:
            errors.append("missing Status line")

        if not modern:
            state = "legacy"
        elif in_progress is False and completed is False:
            state = "pending"
        elif in_progress is True and completed is False:
            state = "in_progress"
        elif in_progress is True and completed is True:
            state = "completed"
        else:
            state = "invalid"

        owner_match = OWNER_RE.search(heading)
        tasks.append(
            Task(
                heading=heading,
                owner=owner_match.group(1).strip() if owner_match else None,
                line=start + 1,
                modern=modern,
                in_progress=in_progress,
                completed=completed,
                steps=steps,
                has_status=has_status,
                state=state,
                errors=errors,
            )
        )
    return tasks


def find_repo_root(start: Path) -> Path:
    resolved = start.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    candidates = (resolved, *resolved.parents)
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    for candidate in candidates:
        if (candidate / "HANDOFF.md").exists():
            return candidate
    return resolved


def git_status(repo: Path) -> list[str] | None:
    if not (repo / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def ledger_report(repo: Path) -> dict[str, object]:
    ledger = repo / "HANDOFF.md"
    instructions = [
        name
        for name in ("AGENTS.md", "CLAUDE.md")
        if (repo / name).exists()
    ]
    if not ledger.exists():
        return {
            "root": str(repo),
            "ledger": None,
            "instructions": instructions,
            "git_status": git_status(repo),
            "tasks": [],
            "errors": ["HANDOFF.md not found"],
            "note": "Follow repository instructions before creating a ledger.",
        }

    tasks = parse_tasks(ledger.read_text(encoding="utf-8"))
    errors = [
        f"line {task.line} ({task.heading}): {error}"
        for task in tasks
        for error in task.errors
    ]
    return {
        "root": str(repo),
        "ledger": str(ledger),
        "instructions": instructions,
        "git_status": git_status(repo),
        "tasks": [asdict(task) for task in tasks],
        "errors": errors,
        "note": (
            "Task states are structural observations only. Audit later entries, "
            "commits, current source, and live ownership before deciding effective status."
        ),
    }


def print_human(report: dict[str, object]) -> None:
    print(f"Root: {report['root']}")
    print(f"Ledger: {report['ledger'] or 'missing'}")
    instruction_names = report["instructions"]
    print(f"Instructions: {', '.join(instruction_names) if instruction_names else 'none found'}")
    status_lines = report["git_status"]
    if status_lines is None:
        print("Git: unavailable")
    elif status_lines:
        print(f"Git: dirty ({len(status_lines)} paths)")
    else:
        print("Git: clean")

    tasks = report["tasks"]
    modern = [task for task in tasks if task["modern"]]
    legacy = [task for task in tasks if not task["modern"]]
    print(f"Tasks: {len(modern)} structured, {len(legacy)} legacy")
    for task in modern:
        owner = task["owner"] or "unassigned"
        print(f"- {task['state']}: {task['heading']} [owner: {owner}]")
    if legacy:
        print("Legacy entries require progressive review; their raw boxes were not classified.")

    errors = report["errors"]
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
    print(f"Note: {report['note']}")


def make_template(task_date: str, title: str, owner: str, steps: list[str]) -> str:
    step_lines = "\n".join(f"- [ ] {step}" for step in steps)
    return (
        f"## {task_date} - {title} (owner: {owner})\n\n"
        "State:\n\n"
        "- [ ] In progress\n"
        "- [ ] Completed\n\n"
        "Steps:\n\n"
        f"{step_lines}\n\n"
        "Status: Pending. No work has started.\n"
    )


def report_command(args: argparse.Namespace) -> int:
    repo = find_repo_root(Path(args.root))
    report = ledger_report(repo)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 1 if report["errors"] else 0


def template_command(args: argparse.Namespace) -> int:
    print(make_template(args.date, args.title, args.owner, args.step))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect HANDOFF.md structure or print a canonical task entry."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("doctor", "validate"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", default=".", help="Repository path or child path")
        command.add_argument("--json", action="store_true", help="Emit JSON")
        command.set_defaults(handler=report_command)

    template = subparsers.add_parser("template")
    template.add_argument("--date", default=date.today().isoformat())
    template.add_argument("--title", required=True)
    template.add_argument("--owner", required=True)
    template.add_argument("--step", action="append", required=True)
    template.set_defaults(handler=template_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
