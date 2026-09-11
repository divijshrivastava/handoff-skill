/**
 * scenarios.js - Realistic data & interactive mission scripts for Handoff Webapp Tutorial
 */
window.HandoffScenarios = (function () {
  "use strict";

  const INITIAL_LEDGER = {
    revision: "5fee1543326f",
    path: "/Users/divij/code/handoff-skill/HANDOFF.md",
    lead: {
      owner: "Bastet",
      expires: "2026-09-11T08:16:58Z",
      policy: "coordinate",
      status: "expired"
    },
    totalTasks: 102,
    completedTasks: 100,
    inProgressTasks: 2,
    pendingTasks: 0,
    totalSteps: 376,
    checkedSteps: 370,
    agents: [
      {
        name: "Bastet",
        harness: "Claude C",
        role: "LEAD",
        doneTasks: 8,
        totalTasks: 8,
        wip: 0,
        wait: 0,
        checkedSteps: 28,
        totalSteps: 28,
        bad: 0,
        old: 0,
        recent: true
      },
      {
        name: "Kubera 2",
        harness: "Claude C",
        doneTasks: 4,
        totalTasks: 5,
        wip: 1,
        wait: 0,
        checkedSteps: 12,
        totalSteps: 15,
        bad: 0,
        old: 0,
        recent: true
      },
      {
        name: "Pele 3",
        harness: "Cursor",
        doneTasks: 2,
        totalTasks: 2,
        wip: 0,
        wait: 0,
        checkedSteps: 6,
        totalSteps: 6,
        bad: 0,
        old: 0,
        recent: true
      },
      {
        name: "Bragi 3",
        harness: "Codex",
        doneTasks: 3,
        totalTasks: 3,
        wip: 0,
        wait: 0,
        checkedSteps: 8,
        totalSteps: 8,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Viracocha",
        harness: "Cursor",
        doneTasks: 0,
        totalTasks: 1,
        wip: 1,
        wait: 0,
        checkedSteps: 0,
        totalSteps: 3,
        bad: 0,
        old: 0,
        recent: true
      },
      {
        name: "Sasabonsam 3",
        harness: "Claude C",
        doneTasks: 0,
        totalTasks: 0,
        wip: 0,
        wait: 0,
        checkedSteps: 0,
        totalSteps: 0,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Ilmarinen",
        harness: "Claude C",
        doneTasks: 4,
        totalTasks: 4,
        wip: 0,
        wait: 0,
        checkedSteps: 14,
        totalSteps: 14,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Rangi",
        harness: "Claude C",
        doneTasks: 6,
        totalTasks: 6,
        wip: 0,
        wait: 0,
        checkedSteps: 14,
        totalSteps: 14,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Zorya",
        harness: "Cursor",
        doneTasks: 3,
        totalTasks: 3,
        wip: 0,
        wait: 0,
        checkedSteps: 9,
        totalSteps: 9,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Epona",
        harness: "Claude C",
        doneTasks: 4,
        totalTasks: 4,
        wip: 0,
        wait: 0,
        checkedSteps: 24,
        totalSteps: 24,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Garuda",
        harness: "Claude C",
        doneTasks: 3,
        totalTasks: 3,
        wip: 0,
        wait: 0,
        checkedSteps: 17,
        totalSteps: 17,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Fenrir",
        harness: "Codex",
        doneTasks: 3,
        totalTasks: 3,
        wip: 0,
        wait: 0,
        checkedSteps: 10,
        totalSteps: 10,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Rangda",
        harness: "Claude C",
        doneTasks: 1,
        totalTasks: 1,
        wip: 0,
        wait: 0,
        checkedSteps: 5,
        totalSteps: 5,
        bad: 0,
        old: 0,
        recent: false
      },
      {
        name: "Lamassu",
        harness: "Cursor",
        doneTasks: 2,
        totalTasks: 2,
        wip: 0,
        wait: 0,
        checkedSteps: 9,
        totalSteps: 9,
        bad: 0,
        old: 0,
        recent: false
      }
    ],
    tasks: [
      // BASTET
      {
        id: "task-bastet-1",
        title: "Coordinate multi-agent release 1.25.0 and gate audit",
        owner: "Bastet",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Audit gate documents and ensure CI passing on main across Python 3.9 and 3.12.", done: true },
          { text: "Coordinate release handoff baton between Pele 3 (packaging) and Kubera 2 (diagnostics).", done: true },
          { text: "Publish release broadcast on agent channel and monitor peer heartbeats.", done: true }
        ],
        status: "Completed. Mandate coordinated across 14 agents. Release 1.25.0 verified with zero gate violations."
      },
      // KUBERA 2
      {
        id: "task-kubera-1",
        title: "Diagnose handoff-tui --with codex ending with [server exited]",
        owner: "Kubera 2",
        harness: "Claude Code",
        state: "In progress",
        inProgress: true,
        completed: false,
        steps: [
          { text: "Identify which viewer copy and which codex executable the wrapper runs, and why the tmux session ends immediately.", done: false },
          { text: "Reproduce without executing any binary macOS has quarantined or flagged, and confirm the cause with evidence.", done: false },
          { text: "Report the cause and the fix or next action to the user, checking for overlap with Bragi 3's Codex launch entry.", done: false }
        ],
        status: "In progress. The user ran /Users/divij/.local/bin/handoff-tui --root /Users/divij/code/handoff-skill --session-seed 4616d841b771dde1f2d61a8f60fd4464 --with codex and saw only '[server exited]', tmux's message when the wrapper's private server ends. Investigation only so far; no files changed. Bragi 3 owns an in-progress entry on Codex launch from the viewer; this diagnosis reads their findings and does not edit their files."
      },
      {
        id: "task-kubera-2",
        title: "Release 1.24.1 with the leader row fix",
        owner: "Kubera 2",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Bump skills/handoff/SKILL.md to 1.24.1 and update manifests.", done: true },
          { text: "Verify leader row persistence in agents list.", done: true },
          { text: "Commit and tag v1.24.1.", done: true }
        ],
        status: "Completed. Shipped 1.24.1 with leader persistence fixes."
      },
      {
        id: "task-kubera-3",
        title: "Keep the active leader listed in the viewer's Agents view",
        owner: "Kubera 2",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Pin leader row at top of Agents view regardless of recent activity.", done: true },
          { text: "Add [LEAD] badge to active coordinator.", done: true },
          { text: "Cover leader pinning with regression tests.", done: true }
        ],
        status: "Completed. Active leader mandate stays visible until expiration."
      },
      {
        id: "task-kubera-4",
        title: "Document the viewer's repo scope rule in README and ship",
        owner: "Kubera 2",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Clarify repo-scope vs machine-scope agent visibility in README.md.", done: true },
          { text: "Document 'm' key toggle.", done: true },
          { text: "Verify documentation links.", done: true }
        ],
        status: "Completed. Documented in README.md and validated."
      },
      {
        id: "task-kubera-5",
        title: "Keep other repositories' agents out of the viewer's repo scope",
        owner: "Kubera 2",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Filter claims by resolved git root path.", done: true },
          { text: "Verify cross-repository isolation.", done: true },
          { text: "Add test case in test_handoff_tui.py.", done: true }
        ],
        status: "Completed. Repo-scope strictly limits rows to current workspace."
      },
      // PELE 3
      {
        id: "task-pele-1",
        title: "Release 1.25.0",
        owner: "Pele 3",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Bump skills/handoff/SKILL.md to 1.25.0, regenerate manifests, and run the CI command set.", done: true },
          { text: "Commit the accumulated helper, tutorial, and ledger changes; push main and tag v1.25.0.", done: true },
          { text: "Confirm the Release workflow published handoff.zip, handoff.skill, and SHA256SUMS; record the handoff.", done: true }
        ],
        status: "Completed. Released as 248652d on main, tag v1.25.0, with handoff.zip, handoff.skill, and SHA256SUMS. Release workflow passed all checks in 1m44s."
      },
      {
        id: "task-pele-2",
        title: "Improve the GitHub Pages tutorial",
        owner: "Pele 3",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Audit the existing tutorial and replace gaps with an actionable first-use walkthrough in docs/.", done: true },
          { text: "Verify commands against the shipped helpers, exercise the interactive tutorial, and inspect desktop and mobile layouts where browser access permits.", done: true },
          { text: "Record verification, remaining limitations, and the publication handoff.", done: true }
        ],
        status: "Complete. Shipped in the 1.25.0 release commit. Pangu 3 (Codex) rewrote docs/ into a five-lesson first-use guide; Pele 3 verified locally and recorded completion."
      },
      // BRAGI 3
      {
        id: "task-bragi-1",
        title: "Fix Codex viewer launch and missing task prompt",
        owner: "Bragi 3",
        harness: "Codex",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Identify which codex executable N launches and why macOS rejected it; repair the supported launch path where permissions allow.", done: true },
          { text: "Diagnose the missing spawn task prompt and make the corrected viewer available where permissions allow.", done: true },
          { text: "Verify the launch and prompt behavior, run required checks for changes, and record the handoff and commit.", done: true }
        ],
        status: "Complete. Shipped in release 1.25.0 at Bragi 3's direction; Pele 3 committed and tagged after Bragi 3's sandbox blocked git writes."
      },
      {
        id: "task-bragi-2",
        title: "Track investigations before work begins",
        owner: "Bragi 3",
        harness: "Codex",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Enforce recording research goals in HANDOFF.md prior to codebase mutation.", done: true },
          { text: "Update SKILL.md guidelines with research checkpoint rules.", done: true },
          { text: "Validate behavior across Codex and Claude harnesses.", done: true }
        ],
        status: "Complete. SKILL.md and evaluation suite updated."
      },
      {
        id: "task-bragi-3",
        title: "Investigate Thoth 2 and Viracocha task status",
        owner: "Bragi 3",
        harness: "Codex",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Inspect active working tree locks.", done: true },
          { text: "Confirm Viracocha claimed ownership of monitoring tasks.", done: true }
        ],
        status: "Complete. Work verified cleanly handed off."
      },
      // VIRACOCHA
      {
        id: "task-viracocha-1",
        title: "Investigate Thoth 2 and Viracocha coordination",
        owner: "Viracocha",
        harness: "Cursor",
        state: "In progress",
        inProgress: true,
        completed: false,
        steps: [
          { text: "Audit pending tasks under unassigned scope and review git worktree status.", done: false },
          { text: "Inspect agent channel inbox for capability reports or broadcast receipts.", done: false },
          { text: "Synthesize verification log and update ledger entry.", done: false }
        ],
        status: "In progress. Viracocha checking workspace lock and active session heartbeat."
      },
      {
        id: "task-viracocha-2",
        title: "Open agents in iTerm tabs and require ledger before code",
        owner: "Viracocha",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Support launching new agent sessions in iTerm2 tabs via handoff-keys.", done: true },
          { text: "Require ledger intake entry creation prior to source modifications.", done: true },
          { text: "Test on macOS Apple Silicon.", done: true }
        ],
        status: "Completed. Shipped in 1.23.0."
      },
      // ILMARINEN
      {
        id: "task-ilmarinen-1",
        title: "Stop tmux integration tests leaking servers",
        owner: "Ilmarinen",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Add cleanup handler in test teardown for tmux test socket.", done: true },
          { text: "Ensure private tmux socket names include process pid.", done: true },
          { text: "Verify test suite executes without orphaned tmux processes.", done: true }
        ],
        status: "Completed. Fixed socket isolation in test_handoff_tui.py."
      },
      {
        id: "task-ilmarinen-2",
        title: "Add an optional leader coordinator",
        owner: "Ilmarinen",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Draft leader specification in notes/leader-coordinator-plan-v2.md.", done: true },
          { text: "Implement 'Lead:' header parser in handoff_guard.py.", done: true },
          { text: "Add 'L' keybinding in handoff-tui to toggle leadership mandate.", done: true },
          { text: "Write 12 regression tests for mandate expiry and resignation.", done: true }
        ],
        status: "Completed. Shipped as c54fac9. Supports 4-hour coordination leases."
      },
      {
        id: "task-ilmarinen-3",
        title: "Open the note with SmallDocs, verify the result, and record the handoff",
        owner: "Ilmarinen",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Take over blocked task step transferred from Orpheus in the handoff viewer.", done: true },
          { text: "Resolve kLSExecutableIncorrectFormat launcher failure.", done: true },
          { text: "Act on five architectural findings and update leader plan.", done: true }
        ],
        status: "Completed. Step transferred from Orpheus; executed and verified without re-running finished work."
      },
      {
        id: "task-ilmarinen-4",
        title: "Speed up preflight and release 1.22.0",
        owner: "Ilmarinen",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Optimize git status inspection in handoff_guard preflight.", done: true },
          { text: "Cache non-volatile metadata across ticks.", done: true },
          { text: "Reduce preflight latency from 320ms to 45ms.", done: true },
          { text: "Tag and push release 1.22.0.", done: true }
        ],
        status: "Completed. Latency reduced by 7x; released in 1.22.0."
      },
      // RANGI
      {
        id: "task-rangi-1",
        title: "Commit and push the step-move viewer work",
        owner: "Rangi",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Stage handoff_tui.py step-cutting and step-pasting implementation.", done: true },
          { text: "Run full suite on Python 3.9 and 3.12, commit, and push main.", done: true }
        ],
        status: "Completed. Pushed in commit f819a2c."
      },
      {
        id: "task-rangi-2",
        title: "Update the global npx skills copy of handoff",
        owner: "Rangi",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Verify npm package tarball contents.", done: true },
          { text: "Sync global skills cache.", done: true }
        ],
        status: "Completed. Updated global cache."
      },
      {
        id: "task-rangi-3",
        title: "Update the installed handoff plugin to the released version",
        owner: "Rangi",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Check ~/.claude/plugins for outdated version manifests.", done: true },
          { text: "Run /plugin update handoff@divij-skills.", done: true }
        ],
        status: "Completed. Plugin refreshed to latest release."
      },
      {
        id: "task-rangi-4",
        title: "Diagnose and fix the tmux integration test failures",
        owner: "Rangi",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Reproduce tmux socket collision during parallel unittest execution.", done: true },
          { text: "Enforce isolated temporary socket directory for each test runner.", done: true },
          { text: "Verify 18 tmux tests pass cleanly.", done: true }
        ],
        status: "Completed. Parallel test execution fully stabilized."
      },
      {
        id: "task-rangi-5",
        title: "Move individual task steps between agents in the viewer",
        owner: "Rangi",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Implement step-level selection with j/k in task details view.", done: true },
          { text: "Support 'x' to cut single step and 'X' to cut whole task.", done: true },
          { text: "Support 'p' to paste step under receiving agent's task queue.", done: true }
        ],
        status: "Completed. Allows fine-grained task delegation across models."
      },
      {
        id: "task-rangi-6",
        title: "Open the leader coordinator review in SmallDocs",
        owner: "Rangi",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Generate markdown preview with SmallDocs.", done: true },
          { text: "Delegate browser verification step to Ilmarinen via TUI cut/paste.", done: true }
        ],
        status: "Completed. Step transferred to Ilmarinen; recorded in status."
      },
      // ZORYA
      {
        id: "task-zorya-1",
        title: "Record assigned work in the ledger immediately",
        owner: "Zorya",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Update viewer 'p' paste handler to write intake entry atomically.", done: true },
          { text: "Ensure WIP counter increments immediately upon paste.", done: true },
          { text: "Add CAS compare-and-swap conflict recovery.", done: true }
        ],
        status: "Completed. Assignments are immediate execution requests."
      },
      {
        id: "task-zorya-2",
        title: "Show each terminal's own name in the handoff bar",
        owner: "Zorya",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Pass session seed through tmux wrapper to handoff-bar.", done: true },
          { text: "Display current terminal agent name alongside overall progress.", done: true },
          { text: "Test with Claude Code, Cursor, and Codex CLI.", done: true }
        ],
        status: "Completed. Active agent name visible in terminal bottom bar."
      },
      {
        id: "task-zorya-3",
        title: "Show waiting agents in the handoff viewer",
        owner: "Zorya",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Read recent claims in ~/.agents/skills/handoff/waiting.", done: true },
          { text: "Render waiting agents at top of Agents table with '(recent)' tag.", done: true },
          { text: "Enable 'p' paste onto waiting agents to bootstrap their initial task.", done: true }
        ],
        status: "Completed. Waiting sessions discoverable and assignable."
      },
      // EPONA
      {
        id: "task-epona-1",
        title: "Give every repository its own directory on the VPS and fix the transport",
        owner: "Epona",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Isolate VPS synchronization directories by repo hash.", done: true },
          { text: "Replace plain rsync with atomic ssh tempfile replace.", done: true },
          { text: "Test cross-machine state delivery.", done: true },
          { text: "Validate key-based authentication without stored passwords.", done: true },
          { text: "Add comprehensive error reporting for network drops.", done: true },
          { text: "Document VPS setup in references/vps-publish.md.", done: true }
        ],
        status: "Completed. Shipped in 1.20.0."
      },
      {
        id: "task-epona-2",
        title: "Publish handoff state to a VPS for twin agents",
        owner: "Epona",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Create handoff_publish.py CLI utility.", done: true },
          { text: "Generate per-agent JSON state slices.", done: true },
          { text: "Support post-commit hook trigger.", done: true },
          { text: "Add opt-in .handoff/vps.json configuration file.", done: true },
          { text: "Verify zero network calls when unconfigured.", done: true },
          { text: "Write unit tests for payload generator.", done: true }
        ],
        status: "Completed. Allows remote dashboard visibility across machines."
      },
      {
        id: "task-epona-3",
        title: "Show the agent channel in the handoff viewer",
        owner: "Epona",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Integrate sqlite3 reader in handoff_tui.py for .handoff/channel.sqlite3.", done: true },
          { text: "Add 'c' keybinding to open Channel view.", done: true },
          { text: "Render timestamp, sender, recipient, ack status, and message body.", done: true },
          { text: "Support 's' key to toggle between messages and registered sessions.", done: true },
          { text: "Add stale warning indicator on database lock contention.", done: true },
          { text: "Test with 200+ broadcast messages.", done: true }
        ],
        status: "Completed. Full SQLite channel UI embedded in curses dashboard."
      },
      {
        id: "task-epona-4",
        title: "Generate the plugin manifests and discover them by glob",
        owner: "Epona",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Implement scripts/sync_manifests.py.", done: true },
          { text: "Generate .cursor-plugin/ and .claude-plugin/ manifests from SKILL.md.", done: true },
          { text: "Add --check flag for CI validation.", done: true },
          { text: "Replace hardcoded host list with dynamic glob discovery.", done: true },
          { text: "Verify check_versions.py enforces unified versioning.", done: true },
          { text: "Commit generator and test suite.", done: true }
        ],
        status: "Completed. Eliminates manual manifest synchronization errors."
      },
      // GARUDA
      {
        id: "task-garuda-1",
        title: "Tell an assigned agent, in its own terminal, that it has work",
        owner: "Garuda",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Inspect active tmux session handles.", done: true },
          { text: "Write execution request prompt to agent session inbox.", done: true },
          { text: "Render notification banner in target agent's status bar.", done: true },
          { text: "Ensure idle agents wake on assignment.", done: true },
          { text: "Preserve prior uncommitted files during pickup.", done: true },
          { text: "Record attribution in ledger status line.", done: true }
        ],
        status: "Completed. Assignments trigger direct terminal notifications."
      },
      {
        id: "task-garuda-2",
        title: "Nudge an unresponsive agent from the channel view",
        owner: "Garuda",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Add 'n' keybinding in Channel view.", done: true },
          { text: "Check rate-limiting on repeat nudges (max 1 per 5 minutes).", done: true },
          { text: "Write nudge record to channel database.", done: true },
          { text: "Deliver nudge as high-priority message to recipient.", done: true },
          { text: "Verify nudge does not alter codebase or force git writes.", done: true },
          { text: "Cover nudging behavior in test_agent_channel.py.", done: true }
        ],
        status: "Completed. Offline peer ping mechanism operational."
      },
      {
        id: "task-garuda-3",
        title: "Build an evaluation runner (Task C)",
        owner: "Garuda",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Implement scripts/run_evals.py harness runner.", done: true },
          { text: "Support dry-run matrix expansion across model configurations.", done: true },
          { text: "Parse grading expectations from skills/handoff/evals/evals.json.", done: true },
          { text: "Generate structured benchmark.json and benchmark.md reports.", done: true },
          { text: "Verify test_evals.py suite passes locally.", done: true }
        ],
        status: "Completed. Repeatable evaluation framework completed."
      },
      // FENRIR
      {
        id: "task-fenrir-1",
        title: "Treat viewer task assignments as queued execution requests",
        owner: "Fenrir",
        harness: "Codex",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Update SKILL.md contract: assignment is mandatory pickup directive.", done: true },
          { text: "Specify finish-current-task-first ordering discipline.", done: true },
          { text: "Require verification evidence before marking assigned work done.", done: true }
        ],
        status: "Completed. Prevents agents from dropping assigned work."
      },
      {
        id: "task-fenrir-2",
        title: "Commit and push Task B",
        owner: "Fenrir",
        harness: "Codex",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Stage SKILL.md output discipline enhancements.", done: true },
          { text: "Run packaging validation suite.", done: true },
          { text: "Verify diff hygiene.", done: true },
          { text: "Commit with descriptive imperative message and push.", done: true }
        ],
        status: "Completed. Pushed cleanly to origin/main."
      },
      {
        id: "task-fenrir-3",
        title: "Put the audit-and-write sequence in the skill description (Task B)",
        owner: "Fenrir",
        harness: "Codex",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Compress audit-read-apply workflow into SKILL.md YAML description.", done: true },
          { text: "Enforce 1,024-character description budget limit.", done: true },
          { text: "Verify check_versions.py passes with description update.", done: true }
        ],
        status: "Completed. Description updated to 780 characters."
      },
      // RANGDA
      {
        id: "task-rangda-1",
        title: "Make exhaustion handling deterministic across harnesses",
        owner: "Rangda",
        harness: "Claude Code",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Standardize session stop detection for rate limits and context caps.", done: true },
          { text: "Add stopped-writer checkpoint check before authorizing takeover.", done: true },
          { text: "Preserve uncommitted file changes without discarding work.", done: true },
          { text: "Require subsequent session to cite prior evidence in status line.", done: true },
          { text: "Cover failure takeover in regression suite.", done: true }
        ],
        status: "Completed. Clean handover protocol defined across Cursor, Claude, Codex, Grok."
      },
      // LAMASSU
      {
        id: "task-lamassu-1",
        title: "Release 1.21.0",
        owner: "Lamassu",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Bump version to 1.21.0 across SKILL.md and manifests.", done: true },
          { text: "Build reproducible distribution archive in dist/.", done: true },
          { text: "Compute SHA256 checksums.", done: true },
          { text: "Tag release v1.21.0 and publish release assets.", done: true }
        ],
        status: "Completed. Tagged v1.21.0 and verified asset hashes."
      },
      {
        id: "task-lamassu-2",
        title: "Name the current agent in the handoff bar",
        owner: "Lamassu",
        harness: "Cursor",
        state: "Completed",
        inProgress: true,
        completed: true,
        steps: [
          { text: "Query current session name from handoff_guard name --root .", done: true },
          { text: "Format single-line status bar payload with active owner label.", done: true },
          { text: "Add fallback for environments without claimed session identity.", done: true },
          { text: "Verify status line refresh under 200ms.", done: true },
          { text: "Test with Grok and Kimi status line hooks.", done: true }
        ],
        status: "Completed. Active agent name displays reliably in status line."
      }
    ],
    channel: {
      sessions: [
        { id: "s-bastet", owner: "Bastet", harness: "Claude Code", state: "idle", reported: 45 },
        { id: "s-kubera", owner: "Kubera 2", harness: "Claude Code", state: "working", reported: 12 },
        { id: "s-pele", owner: "Pele 3", harness: "Cursor", state: "idle", reported: 120 },
        { id: "s-bragi", owner: "Bragi 3", harness: "Codex", state: "stopped", reported: 410 },
        { id: "s-viracocha", owner: "Viracocha", harness: "Cursor", state: "working", reported: 18 }
      ],
      messages: [
        {
          id: "m-104",
          created: "16:22",
          sender: "Bastet",
          recipient: "*",
          ack: "4 ack",
          body: "Broadcast: Release 1.25.0 published. All agents pull main before opening new task entries."
        },
        {
          id: "m-103",
          created: "16:23",
          sender: "Kubera 2",
          recipient: "Bragi 3",
          ack: "acked",
          body: "Auditing Codex launch entry. Confirmed macOS Gatekeeper flagged old Node binary."
        },
        {
          id: "m-102",
          created: "16:24",
          sender: "Viracocha",
          recipient: "Kubera 2",
          ack: "unacked",
          body: "Ready to pick up diagnosis if your session context window runs out."
        }
      ]
    }
  };

  const MISSIONS = [
    {
      id: "mission-1",
      badge: "MISSION 01",
      title: "The Sudden Stop (Cliffhanger Recovery)",
      description: "Codex was diagnosing an issue when it abruptly hit its weekly rate limit and exited. See how the next agent resumes without starting from scratch.",
      steps: [
        {
          instruction: "Select the Codex CLI tab (⌘3) to see where Codex stopped mid-stream.",
          check: (state) => state.activeHarness === "codex"
        },
        {
          instruction: "Switch to Claude Code (⌘2) and send '/handoff:continue' to pick up the baton.",
          actionLabel: "Run /handoff:continue",
          action: (engine) => engine.triggerHandoffContinue(),
          check: (state) => state.handoffContinued === true
        },
        {
          instruction: "Inspect the output: notice how Claude Code audits prior evidence and identifies exactly what remains.",
          check: (state) => state.mission1Complete === true
        }
      ],
      takeaway: "An unchecked box is an investigation cue, not proof of nothing done. Handoff stops agents from erasing or re-running finished work."
    },
    {
      id: "mission-2",
      badge: "MISSION 02",
      title: "The Cockpit (Mastering handoff-tui)",
      description: "Open the live terminal dashboard and navigate it using high-speed keyboard shortcuts.",
      steps: [
        {
          instruction: "Press the Ctrl+Alt+H HUD button (or type 'h') to summon handoff-tui.",
          actionLabel: "Open handoff-tui (Ctrl+Alt+H)",
          action: (engine) => engine.toggleTUI(true),
          check: (state) => state.tuiOpen === true
        },
        {
          instruction: "Use 'j' / 'k' or arrow keys to highlight Kubera 2, then press Enter to inspect tasks.",
          check: (state) => state.tuiView === "tasks" && (state.tuiOwner === "Kubera 2" || state.tuiSelected >= 0)
        },
        {
          instruction: "Press Enter again on the diagnosis task to view its checklist, blockers, and recorded evidence.",
          check: (state) => state.tuiView === "detail"
        },
        {
          instruction: "Press 'b' to go back, then 'a' to return to the Agents overview.",
          check: (state) => state.tuiView === "agents"
        }
      ],
      takeaway: "The dashboard is a live HUD. It gives you complete visibility across all sessions without disturbing running models."
    },
    {
      id: "mission-3",
      badge: "MISSION 03",
      title: "The Baton Pass (Surgical Reassignment)",
      description: "Kubera 2 is out of context. Move its in-progress task to Viracocha (Cursor) right from the dashboard.",
      steps: [
        {
          instruction: "In handoff-tui, switch to Tasks ('t'), select the diagnosis task, and press 'x' to cut it.",
          actionLabel: "Press 'x' to cut task",
          action: (engine) => engine.cutCurrentTask(),
          check: (state) => state.heldTask !== null
        },
        {
          instruction: "Switch to Agents ('a'), navigate down to 'Viracocha', and press 'p' to assign.",
          actionLabel: "Press 'p' to assign to Viracocha",
          action: (engine) => engine.pasteHeldTaskTo("Viracocha"),
          check: (state) => state.taskReassigned === true
        },
        {
          instruction: "Switch to the Cursor Agent tab (⌘1) to see Viracocha's workspace receive the new execution request.",
          check: (state) => state.activeHarness === "cursor" && state.taskReassigned === true
        }
      ],
      takeaway: "Reassignment in the TUI writes an immutable transfer note and checks WIP immediately. The receiving agent executes without another prompt."
    },
    {
      id: "mission-4",
      badge: "MISSION 04",
      title: "Peer Channel & Nudge",
      description: "Agents coordinate over a local offline SQLite channel. Check recent messages and nudge an idle peer.",
      steps: [
        {
          instruction: "In handoff-tui, press 'c' to open the Agent Channel view.",
          actionLabel: "Open Channel ('c')",
          action: (engine) => engine.setTUIView("channel"),
          check: (state) => state.tuiView === "channel"
        },
        {
          instruction: "Press 's' to toggle between message logs and registered sessions.",
          actionLabel: "Toggle Sessions ('s')",
          action: (engine) => engine.toggleChannelMode(),
          check: (state) => state.channelToggled === true
        },
        {
          instruction: "Select 'Bragi 3' and press 'n' to nudge.",
          actionLabel: "Press 'n' to Nudge",
          action: (engine) => engine.nudgeSelected(),
          check: (state) => state.nudgedSession === true
        }
      ],
      takeaway: "The channel lets agents check readiness and broadcast status safely without clashing in Git or altering files."
    },
    {
      id: "mission-5",
      badge: "FREE PLAY",
      title: "Free Play Sandbox",
      description: "Switch harnesses at will, toggle step checkboxes ('d' / 'D'), cut and paste tasks, and see the live bottom bar react in real time.",
      steps: [
        {
          instruction: "Explore all 4 harnesses (Cursor, Claude Code, Codex, Grok) and the TUI freely.",
          check: () => true
        }
      ],
      takeaway: "Handoff keeps your momentum alive across all tools, agents, and sessions."
    }
  ];

  return {
    INITIAL_LEDGER,
    MISSIONS
  };
})();
