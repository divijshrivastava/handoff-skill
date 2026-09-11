#!/usr/bin/env python3
"""Optional leadership: one agent divides work and assigns it to peers.

Nothing here is active until a user designates a leader, and a repository with
no `Lead:` line behaves exactly as it did before this file existed.

Two rules shape everything below.

The leader assigns by writing the ledger, never by sending a message. A peer
message is attributed data that cannot override ownership, so a leader that
handed out work by messaging would be a peer overriding ownership by message.
The write is the assignment; the notification only makes a peer notice sooner,
and losing it costs latency rather than correctness.

Authority is checked against the clock inside the lock. A compare-and-swap
proves the ledger did not move, not that the mandate still holds: a mandate
expires with the passage of time and without any write at all, so a stale
leader would otherwise pass the version check and keep assigning.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from handoff_guard import (
    APPLY_EXIT, LEASE_TIME_FORMAT, Task, find_repo_root, insert_entry,
    lease_epoch, lease_state, ledger_version, make_template, mark_task_in_progress,
    outside_fence_lines, owner_label_error, parse_tasks, reassign_task, set_lease,
    status_paragraph_end, swap_ledger, task_block_end,
)


# `Lead:` sits above the first task heading, so it belongs to no entry and a
# reader that does not know the field simply skips a line of prose.
LEAD_RE = re.compile(
    r"^Lead:\s*owner=(?P<owner>.+?);\s*expires=(?P<expires>[^;]+?);"
    r"\s*policy=(?P<policy>[A-Za-z][A-Za-z0-9_-]*)"
    r"(?:;\s*succession=(?P<succession>[A-Za-z][A-Za-z0-9_-]*))?\s*$"
)
TASK_ID_RE = re.compile(r"^Task:\s*id=(?P<id>[A-Za-z0-9_-]{4,64})\s*$")
ASSIGNED_RE = re.compile(r"^Assigned:\s*(?P<fields>.+?)\s*$")
HISTORY_PREFIX = "Assigned-history:"

LEAD_POLICIES = ("coordinate",)
SUCCESSIONS = ("none", "auto")
# Assignment states. `offered` is the leader's request; every other state is
# reached by the assignee's own recorded act or by arithmetic on a deadline.
ASSIGNMENT_STATES = ("offered", "accepted", "declined")
MAX_LEAD_HOURS = 168
MAX_ACCEPT_HOURS = 72


def utc_stamp(seconds_from_now: float) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    return moment.strftime(LEASE_TIME_FORMAT)


def mint_task_id() -> str:
    """A short, unique, immutable handle for one entry.

    Dependencies point at this rather than at a heading. A heading is not an
    identifier: two entries may carry identical headings and both parse
    cleanly, and headings are rewritten by retitling, ownership changes, and
    step transfers, any of which would silently break a reference.
    """
    return "t" + uuid.uuid4().hex[:8]


def parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in text.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            fields[key.strip().casefold()] = value.strip()
    return fields


def split_paths(value: str) -> list[str]:
    return [normalize_path(item) for item in value.split(",") if item.strip()]


def normalize_path(value: str) -> str:
    """Collapse a declared path to one comparable form.

    Reservations are compared textually, so `./src/a.ts` and `src/a.ts` must
    not read as different files.
    """
    cleaned = value.strip().replace("\\", "/").lstrip("./")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    return cleaned.rstrip("/") + ("/" if value.strip().endswith("/") else "")


def paths_overlap(left: str, right: str) -> bool:
    """Whether two declared paths could put two agents in the same bytes.

    A trailing slash declares a directory, which covers everything beneath it.
    """
    if left == right:
        return True
    for a, b in ((left, right), (right, left)):
        if a.endswith("/") and b.startswith(a):
            return True
    return False


class Lead:
    """The recorded mandate: who coordinates, until when, and what follows."""

    def __init__(self, owner: str, expires: str, policy: str,
                 succession: str = "none", line: int = 0):
        self.owner = owner
        self.expires = expires
        self.policy = policy
        self.succession = succession
        self.line = line
        self.epoch = lease_epoch(expires)

    def state(self, now: float | None = None) -> str:
        if self.epoch is None or self.policy not in LEAD_POLICIES:
            return "invalid"
        return "active" if (now or time.time()) < self.epoch else "expired"

    def render(self) -> str:
        return (f"Lead: owner={self.owner}; expires={self.expires}; "
                f"policy={self.policy}; succession={self.succession}")

    def as_dict(self, now: float | None = None) -> dict:
        return {"owner": self.owner, "expires": self.expires, "policy": self.policy,
                "succession": self.succession, "state": self.state(now)}


class Assignment:
    """One leader-recorded handover of one entry, and its lifecycle state."""

    def __init__(self, fields: dict[str, str], line: int):
        self.by = fields.get("by", "")
        self.to = fields.get("to", "")
        self.state = fields.get("state", "offered").casefold()
        self.accept_by = fields.get("accept-by", "")
        self.paths = split_paths(fields.get("paths", ""))
        self.needs = [item.strip() for item in fields.get("needs", "").split(",")
                      if item.strip() and item.strip().casefold() != "none"]
        self.line = line
        self.epoch = lease_epoch(self.accept_by) if self.accept_by else None

    def render(self) -> str:
        parts = [f"by={self.by}", f"to={self.to}", f"state={self.state}"]
        if self.accept_by:
            parts.append(f"accept-by={self.accept_by}")
        if self.paths:
            parts.append("paths=" + ",".join(self.paths))
        if self.needs:
            parts.append("needs=" + ",".join(self.needs))
        return "Assigned: " + "; ".join(parts)

    def as_dict(self) -> dict:
        return {"by": self.by, "to": self.to, "state": self.state,
                "accept_by": self.accept_by or None, "paths": self.paths,
                "needs": self.needs}


def read_lead(text: str) -> Lead | None:
    for index, line in enumerate(outside_fence_lines(text.splitlines())):
        match = LEAD_RE.match(line.strip())
        if match:
            return Lead(match.group("owner").strip(), match.group("expires").strip(),
                        match.group("policy").strip().casefold(),
                        (match.group("succession") or "none").strip().casefold(),
                        index + 1)
    return None


def entry_lines(text: str, task: Task) -> list[str]:
    lines = outside_fence_lines(text.splitlines())
    return lines[task.line - 1: task_block_end(text.splitlines(), task.line)]


def read_task_id(text: str, task: Task) -> str | None:
    for line in entry_lines(text, task):
        match = TASK_ID_RE.match(line.strip())
        if match:
            return match.group("id")
    return None


def read_assignment(text: str, task: Task) -> Assignment | None:
    """This entry's active assignment, if it still describes the current owner.

    An assignment whose `to=` no longer matches the heading owner is stale by
    construction: some other writer - a user's viewer move, a yield, a sweep,
    a step transfer - has since changed ownership, and ownership in the heading
    is what decides. Treating the mismatch as self-invalidating rather than as
    an error is what lets leadership coexist with every existing owner mutator
    without patching any of them.
    """
    start = task.line
    for offset, line in enumerate(entry_lines(text, task)):
        stripped = line.strip()
        if stripped.startswith(HISTORY_PREFIX):
            continue
        match = ASSIGNED_RE.match(stripped)
        if match:
            assignment = Assignment(parse_fields(match.group("fields")), start + offset)
            return assignment if assignment.to == (task.owner or "") else None
    return None


def structure_findings(text: str) -> list[str]:
    """Problems only leadership can see; the guard keeps owning entry structure."""
    findings: list[str] = []
    lead = read_lead(text)
    if lead and lead.state() == "invalid":
        findings.append(f"line {lead.line}: Lead line is not a usable mandate")
    if lead and lead.succession not in SUCCESSIONS:
        findings.append(f"line {lead.line}: Lead succession is not "
                        + " or ".join(SUCCESSIONS))

    tasks = parse_tasks(text)
    identifiers: dict[str, int] = {}
    for task in tasks:
        task_id = read_task_id(text, task)
        if task_id is None:
            continue
        if task_id in identifiers:
            findings.append(f"line {task.line}: task id {task_id} is already used on "
                            f"line {identifiers[task_id]}")
        identifiers[task_id] = task.line

    for task in tasks:
        assignment = read_assignment(text, task)
        if assignment is None:
            continue
        if assignment.state not in ASSIGNMENT_STATES:
            findings.append(f"line {assignment.line}: assignment state is not "
                            + " or ".join(ASSIGNMENT_STATES))
        if assignment.accept_by and assignment.epoch is None:
            findings.append(f"line {assignment.line}: accept-by is not an "
                            "ISO-8601 UTC timestamp")
        for needed in assignment.needs:
            if needed not in identifiers:
                findings.append(f"line {assignment.line}: needs {needed}, which no "
                                "entry declares")
    findings.extend(cycle_findings(text, tasks, identifiers))
    return findings


def cycle_findings(text: str, tasks: list[Task], identifiers: dict[str, int]) -> list[str]:
    """A dependency that eventually requires itself can never be satisfied."""
    graph: dict[str, list[str]] = {}
    for task in tasks:
        task_id = read_task_id(text, task)
        assignment = read_assignment(text, task)
        if task_id and assignment:
            graph[task_id] = [need for need in assignment.needs if need in identifiers]

    findings: list[str] = []
    colour: dict[str, int] = {}

    def walk(node: str, trail: list[str]) -> None:
        colour[node] = 1
        for neighbour in graph.get(node, []):
            if colour.get(neighbour) == 1:
                cycle = trail[trail.index(neighbour):] + [neighbour]
                findings.append(f"line {identifiers[node]}: dependency cycle "
                                + " -> ".join(cycle))
            elif colour.get(neighbour, 0) == 0:
                walk(neighbour, trail + [neighbour])
        colour[node] = 2

    for node in graph:
        if colour.get(node, 0) == 0:
            walk(node, [node])
    return findings


def completed_ids(text: str) -> set[str]:
    """Entries a dependency may treat as satisfied.

    Structural errors disqualify an entry: a malformed record is not evidence
    that work finished, and letting it release dependent work would start that
    work on a false premise.
    """
    done = set()
    for task in parse_tasks(text):
        task_id = read_task_id(text, task)
        if task_id and task.state == "completed" and not task.errors:
            done.add(task_id)
    return done


def reserved_paths(text: str, exclude_line: int | None = None) -> list[tuple[str, str]]:
    """Paths currently spoken for, as (path, owner).

    A reservation is a property of ownership, never of availability. A peer
    that has gone quiet still owns its files: silence cannot free them, and a
    stale availability report is not evidence that anyone stopped writing. The
    bound already exists and is the same one ownership has - the entry
    finishing, or its owner's own lease expiring and being swept.
    """
    claimed: list[tuple[str, str]] = []
    for task in parse_tasks(text):
        if task.line == exclude_line or task.state == "completed" or not task.owner:
            continue
        assignment = read_assignment(text, task)
        if assignment and assignment.state != "declined":
            claimed.extend((path, task.owner) for path in assignment.paths)
    return claimed


def insert_into_entry(text: str, task: Task, new_lines: list[str]) -> str:
    """Place leadership metadata directly beneath the entry's State block.

    It goes above `Steps:` so a reader meets ownership, state, and provenance
    together, and so the guard's step parsing - which stops at `Status:` - is
    untouched.
    """
    lines = text.splitlines()
    masked = outside_fence_lines(lines)
    end = task_block_end(lines, task.line)
    anchor = next((index for index in range(task.line, end)
                   if masked[index].strip() == "Steps:"), None)
    if anchor is None:
        anchor = end
    lines[anchor:anchor] = new_lines + [""]
    return "\n".join(lines) + "\n"


def replace_line(text: str, line: int, replacement: str | None) -> str:
    lines = text.splitlines()
    if replacement is None:
        del lines[line - 1]
        if line - 1 < len(lines) and not lines[line - 1].strip():
            del lines[line - 1]
    else:
        lines[line - 1] = replacement
    return "\n".join(lines) + "\n"


def append_status(text: str, task: Task, note: str) -> str:
    lines = text.splitlines()
    masked = outside_fence_lines(lines)
    end = status_paragraph_end(masked, task.line, task_block_end(lines, task.line))
    if end is None:
        return text
    lines.insert(end + 1, note)
    return "\n".join(lines) + "\n"


def find_task(text: str, task_id: str) -> Task:
    for task in parse_tasks(text):
        if read_task_id(text, task) == task_id:
            return task
    raise ValueError(f"No entry declares task id {task_id}")


def require_lead(text: str, owner: str) -> Lead:
    """Confirm this owner still holds an unexpired mandate, right now.

    Called inside swap_ledger's build callback, which runs under the held lock
    against the current text, because neither half can be established earlier:
    the ledger may have been rewritten since it was read, and the deadline may
    have passed without any write at all.
    """
    lead = read_lead(text)
    if lead is None:
        raise ValueError("No leader is designated; run `claim` or ask the user to "
                         "designate one")
    if lead.owner != owner:
        raise ValueError(f"{owner} does not hold the mandate; {lead.owner} does")
    state = lead.state()
    if state != "active":
        raise ValueError(f"The mandate held by {owner} is {state}; renew it before "
                         "assigning work")
    return lead


def claim_command(args: argparse.Namespace) -> int:
    """Designate a leader, or renew an existing mandate.

    Claiming is a compare-and-swap like every other ledger write, so two agents
    reaching for leadership at the same version cannot both win.
    """
    if not 0 < args.hours <= MAX_LEAD_HOURS:
        return fail(f"--hours must be above 0 and at most {MAX_LEAD_HOURS}")
    problem = owner_label_error(args.owner)
    if problem or ";" in args.owner:
        return fail(f"owner label rejected ({problem or 'owner name cannot contain a semicolon'})")

    renewing = args.command == "renew"

    def build(text: str) -> str:
        current = read_lead(text)
        if renewing:
            if current is None:
                raise ValueError("No mandate exists to renew")
            if current.owner != args.owner:
                raise ValueError(f"{args.owner} does not hold the mandate; "
                                 f"{current.owner} does")
        elif current is not None and current.state() == "active" and current.owner != args.owner:
            raise ValueError(
                f"{current.owner} already holds an active mandate until {current.expires}. "
                "Ask that leader to resign, or wait for it to expire.")
        lead = Lead(args.owner, utc_stamp(args.hours * 3600), "coordinate",
                    args.succession if not renewing else (current.succession if current else "none"))
        if current is not None:
            return replace_line(text, current.line, lead.render())
        lines = text.splitlines()
        anchor = next((index for index, line in enumerate(outside_fence_lines(lines))
                       if line.startswith("## ")), len(lines))
        # Keep a blank line on each side so the mandate reads as its own
        # paragraph rather than running into the title or the first entry.
        block = ([""] if anchor and lines[anchor - 1].strip() else []) + [lead.render(), ""]
        lines[anchor:anchor] = block
        return "\n".join(lines) + "\n"

    return emit(swap_ledger(ledger_of(args), args.expect_version, build,
                            dry_run=args.dry_run), args)


def resign_command(args: argparse.Namespace) -> int:
    def build(text: str) -> str:
        current = read_lead(text)
        if current is None:
            raise ValueError("No mandate exists to resign")
        if current.owner != args.owner:
            raise ValueError(f"{args.owner} does not hold the mandate; {current.owner} does")
        return replace_line(text, current.line, None)

    return emit(swap_ledger(ledger_of(args), args.expect_version, build,
                            dry_run=args.dry_run), args)


def assign_command(args: argparse.Namespace) -> int:
    """Record one unit of work against one agent, as a ledger fact.

    The entry is created owned and `offered`. It is not accepted: the assignee
    records that itself, because the box this write could set is one the write
    already sets, and a signal a leader can produce alone evidences nothing
    about the assignee.
    """
    problem = owner_label_error(args.to)
    if problem or ";" in args.to:
        return fail(f"assignee label rejected ({problem or 'owner name cannot contain a semicolon'})")
    if not 0 < args.accept_hours <= MAX_ACCEPT_HOURS:
        return fail(f"--accept-hours must be above 0 and at most {MAX_ACCEPT_HOURS}")

    task_id = mint_task_id()
    declared = [normalize_path(path) for path in (args.paths or "").split(",") if path.strip()]

    def build(text: str) -> str:
        require_lead(text, args.owner)
        known = {read_task_id(text, task) for task in parse_tasks(text)}
        for needed in args.needs or []:
            if needed not in known:
                raise ValueError(f"needs {needed}, which no entry declares")
        for path in declared:
            for taken, holder in reserved_paths(text):
                if paths_overlap(path, taken) and holder != args.to:
                    raise ValueError(
                        f"{holder} already holds {taken}, which overlaps {path}. "
                        "Narrow the paths or wait for that entry to finish or be released.")
        entry = make_template(date.today().isoformat(), args.title, args.to, args.step,
                              harness=None)
        entry = entry.replace("- [ ] In progress", "- [ ] In progress", 1)
        assignment = Assignment({
            "by": args.owner, "to": args.to, "state": "offered",
            "accept-by": utc_stamp(args.accept_hours * 3600),
            "paths": ",".join(declared), "needs": ",".join(args.needs or []),
        }, 0)
        entry = entry.replace("Steps:", f"Task: id={task_id}\n{assignment.render()}\n\nSteps:", 1)
        entry = entry.replace(
            "Status: Pending. No work has started.",
            f"Status: Offered. {args.owner} assigned this to {args.to} as leader. "
            f"Accept with `handoff_lead.py accept --owner {args.to} --task {task_id}` "
            "before starting, or decline with a reason. Accepting records a lease; "
            "leaving it unaccepted past the deadline lets the leader reclaim it.")
        return insert_entry(text, entry)

    result = swap_ledger(ledger_of(args), args.expect_version, build, dry_run=args.dry_run)
    if result.get("status") in {"applied", "dry-run"}:
        result["task_id"] = task_id
    return emit(result, args)


def accept_command(args: argparse.Namespace) -> int:
    """The assignee's own recorded act of taking the work on.

    Acceptance cannot be inferred from `In progress`, because a viewer
    assignment and this tool both check that box when the work is handed over.
    A signal the assigner sets says nothing about the assignee. Accepting
    writes a lease in the same swap, so accepted work always carries a deadline
    and can never be parked indefinitely.
    """
    if not 0 < args.hours <= MAX_ACCEPT_HOURS:
        return fail(f"--hours must be above 0 and at most {MAX_ACCEPT_HOURS}")

    def build(text: str) -> str:
        task = find_task(text, args.task)
        assignment = read_assignment(text, task)
        if assignment is None:
            raise ValueError("That entry carries no active assignment; its ownership "
                             "changed after it was assigned")
        if assignment.to != args.owner:
            raise ValueError(f"{args.task} is assigned to {assignment.to}, not {args.owner}")
        if assignment.state == "accepted":
            raise ValueError("That assignment is already accepted")
        unmet = [need for need in assignment.needs if need not in completed_ids(text)]
        if unmet and not args.ignore_dependencies:
            raise ValueError("Unmet dependencies: " + ", ".join(unmet)
                             + ". Finish them first, or pass --ignore-dependencies "
                               "when later work has superseded them.")
        assignment.state = "accepted"
        result = replace_line(text, assignment.line, assignment.render())
        task = find_task(result, args.task)
        # Accepting is the moment work actually starts, so this is where the
        # In progress box belongs. The assign write deliberately leaves it
        # unchecked: a box the leader ticks says nothing about the assignee.
        result = mark_task_in_progress(result, task.line, task.heading)
        task = find_task(result, args.task)
        result = set_lease(result, task.line, task.heading,
                           f"Lease: owner={args.owner}; expires={utc_stamp(args.hours * 3600)}; "
                           "policy=release")
        task = find_task(result, args.task)
        return append_status(result, task, (
            f" Accepted {date.today().isoformat()} by {args.owner}, which recorded a lease. "
            "Renew it at real checkpoints; letting it expire authorizes a peer to sweep "
            "this entry."))

    return emit(swap_ledger(ledger_of(args), args.expect_version, build,
                            dry_run=args.dry_run), args)


def decline_command(args: argparse.Namespace) -> int:
    """Refuse offered work, with a reason. A decline is information, not failure."""

    def build(text: str) -> str:
        task = find_task(text, args.task)
        assignment = read_assignment(text, task)
        if assignment is None:
            raise ValueError("That entry carries no active assignment")
        if assignment.to != args.owner:
            raise ValueError(f"{args.task} is assigned to {assignment.to}, not {args.owner}")
        if assignment.state == "accepted":
            raise ValueError("That assignment was accepted; release it with the channel's "
                             "`yield` instead, so the release is recorded as one")
        assignment.state = "declined"
        result = replace_line(text, assignment.line, assignment.render())
        task = find_task(result, args.task)
        result = append_status(result, task, (
            f" Declined {date.today().isoformat()} by {args.owner}: {args.reason} "
            "The leader should reassign or re-plan; the entry keeps its steps."))
        task = find_task(result, args.task)
        return reassign_task(result, task.line, task.heading, None, "", mark_in_progress=False)

    return emit(swap_ledger(ledger_of(args), args.expect_version, build,
                            dry_run=args.dry_run), args)


def reclaim_command(args: argparse.Namespace) -> int:
    """Take back assignments nobody accepted, and entries whose lease expired.

    Both are decided by arithmetic on a deadline the assignee itself could see,
    never by a judgement about whether that agent looks busy.
    """
    reclaimed: list[dict] = []

    def build(text: str) -> str:
        require_lead(text, args.owner)
        now = time.time()
        result = text
        while True:
            for task in parse_tasks(result):
                assignment = read_assignment(result, task)
                if assignment is None or assignment.state == "declined":
                    continue
                expired_offer = (assignment.state == "offered" and assignment.epoch
                                 is not None and now >= assignment.epoch)
                expired_lease = lease_state(task, now) == "expired"
                if not (expired_offer or expired_lease):
                    continue
                why = ("was never accepted before its deadline" if expired_offer
                       else "carried a lease its owner let expire")
                if read_task_id(result, task) in {item["task"] for item in reclaimed}:
                    continue
                note = (f" Reclaimed {date.today().isoformat()} by {args.owner} as leader: "
                        f"this assignment {why}. The status above is the prior owner's last "
                        "recorded state. Nothing here establishes why that agent went quiet, "
                        "and its writers were not verified: preserve uncommitted work and "
                        "audit before resuming.")
                reclaimed.append({"task": read_task_id(result, task),
                                  "heading": task.heading, "reason": why,
                                  "prior_owner": task.owner})
                result = set_lease(result, task.line, task.heading, None)
                task = find_task(result, reclaimed[-1]["task"])
                result = reassign_task(result, task.line, task.heading, None, note,
                                       mark_in_progress=False)
                break
            else:
                break
        if not reclaimed:
            raise ValueError("Nothing is reclaimable: no offer passed its deadline and no "
                             "lease expired")
        return result

    result = swap_ledger(ledger_of(args), args.expect_version, build, dry_run=args.dry_run)
    if result.get("status") in {"applied", "dry-run"}:
        result["reclaimed"] = reclaimed
    return emit(result, args)


def roster_command(args: argparse.Namespace) -> int:
    """Who may be given work, and on what evidence. Read-only.

    Eligibility requires positive evidence of availability. An agent whose
    report has gone stale is `unknown`, and unknown never means free: silence
    is the case where handing out more work does the most damage, because the
    agent may be mid-edit in the very files being reassigned.
    """
    repo = find_repo_root(Path(args.root))
    text = ledger_of(args).read_text(encoding="utf-8")
    tasks = parse_tasks(text)

    peers: dict[str, dict] = {}
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from handoff_channel import Channel
        for peer in Channel(repo).peers():
            peers[peer["owner"]] = peer
    except Exception:  # pragma: no cover - the channel is optional
        peers = {}

    owners = {task.owner for task in tasks if task.owner} | set(peers)
    lead = read_lead(text)
    # The leader belongs on its own roster even before it owns anything, so a
    # reader can always see who is coordinating.
    if lead:
        owners.add(lead.owner)
    rows = []
    for owner in sorted(owners):
        peer = peers.get(owner, {})
        availability = peer.get("availability", "unregistered")
        open_tasks = [task for task in tasks
                      if task.owner == owner and task.state != "completed"]
        holds = [path for task in open_tasks
                 for path in (read_assignment(text, task).paths
                              if read_assignment(text, task) else [])]
        rows.append({
            "owner": owner,
            "harness": peer.get("harness") or next(
                (task.harness for task in tasks if task.owner == owner and task.harness), None),
            "availability": availability,
            "attested_seconds": peer.get("attested_seconds"),
            "open_load": len(open_tasks),
            "reserved_paths": holds,
            "is_leader": bool(lead and lead.owner == owner),
            "eligible": availability in {"working", "waiting"},
            "why": ("available and reporting" if availability in {"working", "waiting"}
                    else f"availability is {availability}; assigning on silence risks "
                         "handing out work an agent is already editing"),
        })
    print(json.dumps({
        "root": str(repo), "version": ledger_version(text),
        "lead": lead.as_dict() if lead else None,
        "roster": rows,
        "note": ("Eligibility requires a fresh report. Unknown is not free: it is the case "
                 "where assigning more work does the most damage."),
    }, indent=2))
    return 0


def status_command(args: argparse.Namespace) -> int:
    """The mandate, every active assignment, and what blocks what. Read-only."""
    text = ledger_of(args).read_text(encoding="utf-8")
    lead = read_lead(text)
    done = completed_ids(text)
    assignments = []
    for task in parse_tasks(text):
        assignment = read_assignment(text, task)
        if assignment is None:
            continue
        unmet = [need for need in assignment.needs if need not in done]
        assignments.append({
            "task": read_task_id(text, task), "heading": task.heading,
            "owner": task.owner, "state": task.state,
            "assignment": assignment.as_dict(),
            "lease": lease_state(task),
            "blocked_by": unmet,
            "reclaimable": (assignment.state == "offered" and assignment.epoch is not None
                            and time.time() >= assignment.epoch) or lease_state(task) == "expired",
        })
    print(json.dumps({
        "version": ledger_version(text),
        "lead": lead.as_dict() if lead else None,
        "assignments": assignments,
        "errors": structure_findings(text),
        "note": ("Assignments are ledger facts. A leader may reclaim only what was never "
                 "accepted or whose own lease expired; live owners keep their work."),
    }, indent=2))
    return 0


def ledger_of(args: argparse.Namespace) -> Path:
    return find_repo_root(Path(args.root)) / "HANDOFF.md"


def fail(message: str) -> int:
    print(f"handoff-lead: {message}", file=sys.stderr)
    return 1


def emit(result: dict, args: argparse.Namespace) -> int:
    print(json.dumps(result, indent=2))
    return APPLY_EXIT.get(str(result.get("status")), 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser, writes: bool = True) -> None:
        command.add_argument("--root", default=".", help="Repository path or child path")
        if writes:
            command.add_argument("--expect-version", required=True,
                                 help="Ledger version read before this edit")
            command.add_argument("--dry-run", action="store_true",
                                 help="Report without writing")

    for name in ("claim", "renew"):
        command = subparsers.add_parser(
            name, help="Designate this owner as leader" if name == "claim"
            else "Extend this owner's mandate")
        common(command)
        command.add_argument("--owner", required=True, help="The leader's ledger name")
        command.add_argument("--hours", type=float, default=4.0,
                             help="Mandate length; pick a span you will come back within")
        command.add_argument("--succession", default="none", choices=SUCCESSIONS,
                             help="Whether a peer may inherit an expired mandate")
        command.set_defaults(handler=claim_command)

    resign = subparsers.add_parser("resign", help="Give up the mandate")
    common(resign)
    resign.add_argument("--owner", required=True)
    resign.set_defaults(handler=resign_command)

    assign = subparsers.add_parser("assign", help="Record one unit of work against one agent")
    common(assign)
    assign.add_argument("--owner", required=True, help="The leader making the assignment")
    assign.add_argument("--to", required=True, help="The assignee's ledger name")
    assign.add_argument("--title", required=True)
    assign.add_argument("--step", action="append", required=True)
    assign.add_argument("--paths", default="", help="Comma-separated files or dirs/ this work writes")
    assign.add_argument("--needs", action="append", help="Task id this work depends on")
    assign.add_argument("--accept-hours", type=float, default=4.0,
                        help="How long the assignee has to accept before it is reclaimable")
    assign.set_defaults(handler=assign_command)

    accept = subparsers.add_parser("accept", help="Take on assigned work and record a lease")
    common(accept)
    accept.add_argument("--owner", required=True, help="The assignee")
    accept.add_argument("--task", required=True, help="Task id from the entry")
    accept.add_argument("--hours", type=float, default=6.0, help="Lease length")
    accept.add_argument("--ignore-dependencies", action="store_true",
                        help="Accept although a dependency is unmet, when later work superseded it")
    accept.set_defaults(handler=accept_command)

    decline = subparsers.add_parser("decline", help="Refuse offered work, with a reason")
    common(decline)
    decline.add_argument("--owner", required=True)
    decline.add_argument("--task", required=True)
    decline.add_argument("--reason", required=True)
    decline.set_defaults(handler=decline_command)

    reclaim = subparsers.add_parser(
        "reclaim", help="Take back unaccepted offers and lease-expired entries")
    common(reclaim)
    reclaim.add_argument("--owner", required=True, help="The leader reclaiming")
    reclaim.set_defaults(handler=reclaim_command)

    roster = subparsers.add_parser("roster", help="Who may be given work, and why")
    common(roster, writes=False)
    roster.set_defaults(handler=roster_command)

    status = subparsers.add_parser("status", help="Mandate, assignments, and blockers")
    common(status, writes=False)
    status.set_defaults(handler=status_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ValueError as error:
        return fail(str(error))


if __name__ == "__main__":
    sys.exit(main())
