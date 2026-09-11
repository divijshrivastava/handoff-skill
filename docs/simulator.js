/**
 * simulator.js - Core Reactive Engine & Interactive Terminal/TUI Emulator for Handoff
 */
(function () {
  "use strict";

  // Deep clone helper
  function clone(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  // Reactive State Store
  const state = {
    ledger: clone(window.HandoffScenarios.INITIAL_LEDGER),
    activeHarness: "cursor", // "cursor" | "claude" | "codex" | "grok" | "tui"
    tuiOpen: false,          // floating modal HUD
    tuiView: "agents",       // "agents" | "tasks" | "channel" | "detail" | "spawn"
    tuiOwner: null,          // filter tasks by owner
    tuiSelected: 0,
    tuiStepSelected: 0,
    heldTask: null,          // cut task
    heldStep: null,          // cut step
    bannerMessage: "Ready. Use j/k to move, Enter to open, x to cut, p to give.",
    bannerType: "normal",    // "normal" | "held" | "success" | "alert"
    channelMode: "messages", // "messages" | "sessions"
    channelToggled: false,
    nudgedSession: false,
    handoffContinued: false,
    taskReassigned: false,
    mission1Complete: false,
    currentMissionIndex: 0,
    claudeInputText: "",
    viracochaAccepted: false
  };

  const missions = window.HandoffScenarios.MISSIONS;

  // DOM elements cache
  const el = {};

  function initElements() {
    el.wrap = document.getElementById("interactive-simulator") || document.getElementById("handoff-simulator");
    if (!el.wrap) return false;

    el.missionPills = document.querySelectorAll(".sim-mission-pill");
    el.missionBadge = document.getElementById("sim-mission-badge");
    el.missionTitle = document.getElementById("sim-mission-title");
    el.missionDesc = document.getElementById("sim-mission-desc");
    el.missionStep = document.getElementById("sim-mission-step");
    el.missionAction = document.getElementById("sim-mission-action");
    el.hudTrigger = document.getElementById("sim-hud-trigger");

    el.tabBtns = document.querySelectorAll(".sim-tab-btn");
    el.screens = {
      cursor: document.getElementById("sim-screen-cursor"),
      claude: document.getElementById("sim-screen-claude"),
      codex: document.getElementById("sim-screen-codex"),
      grok: document.getElementById("sim-screen-grok"),
      tui: document.getElementById("sim-screen-tui")
    };

    // Modal HUD
    el.tuiModal = document.getElementById("sim-tui-modal");
    el.tuiModalClose = document.getElementById("sim-tui-modal-close");

    // Dynamic containers for TUI
    el.tuiTaskBars = document.querySelectorAll(".sim-dyn-task-bar");
    el.tuiStepBars = document.querySelectorAll(".sim-dyn-step-bar");
    el.tuiStatSummaries = document.querySelectorAll(".sim-dyn-stat-summary");
    el.tuiTableBodies = document.querySelectorAll(".sim-dyn-tui-body");
    el.tuiBanners = document.querySelectorAll(".sim-dyn-tui-banner");
    el.tuiNavTabs = document.querySelectorAll(".sim-dyn-tui-nav");
    el.tmuxBars = document.querySelectorAll(".sim-tmux-agent-bar");

    // Claude inputs
    el.claudeInput = document.getElementById("sim-claude-input");
    el.claudeRunBtn = document.getElementById("sim-claude-run-btn");
    el.claudeStream = document.getElementById("sim-claude-stream");

    // Cursor elements
    el.cursorComposer = document.getElementById("sim-cursor-composer-body");
    el.cursorEditor = document.getElementById("sim-cursor-editor-content");

    // Guided Tour elements
    el.startTourBtn = document.getElementById("sim-start-tour-btn");
    el.tourCard = document.getElementById("sim-tour-card");
    el.tourBadge = document.getElementById("sim-tour-badge");
    el.tourTitle = document.getElementById("sim-tour-title");
    el.tourBody = document.getElementById("sim-tour-body");
    el.tourDots = document.getElementById("sim-tour-dots");
    el.tourPrev = document.getElementById("sim-tour-prev");
    el.tourNext = document.getElementById("sim-tour-next");
    el.tourAct = document.getElementById("sim-tour-act");
    el.tourClose = document.getElementById("sim-tour-close");
    return true;
  }

  // Engine Actions & Public API
  const engine = {
    setHarness(harnessId) {
      state.activeHarness = harnessId;
      if (el.tabBtns) {
        el.tabBtns.forEach(btn => {
          btn.classList.toggle("active", btn.dataset.harness === harnessId);
        });
      }
      if (el.screens) {
        Object.keys(el.screens).forEach(id => {
          if (el.screens[id]) {
            el.screens[id].classList.toggle("active", id === harnessId);
          }
        });
      }
      checkMissionProgress();
      renderAll();
    },

    toggleTUI(forceOpen) {
      const target = typeof forceOpen === "boolean" ? forceOpen : !state.tuiOpen;
      state.tuiOpen = target;
      if (el.tuiModal) {
        el.tuiModal.classList.toggle("open", state.tuiOpen);
      }
      checkMissionProgress();
      renderTUI();
    },

    setTUIView(view, owner = null) {
      state.tuiView = view;
      state.tuiOwner = owner;
      state.tuiSelected = 0;
      state.tuiStepSelected = 0;
      checkMissionProgress();
      renderTUI();
    },

    toggleChannelMode() {
      state.channelMode = state.channelMode === "messages" ? "sessions" : "messages";
      state.channelToggled = true;
      state.bannerMessage = `Switched to Channel ${state.channelMode}. Press 's' to toggle, 'n' to nudge.`;
      state.bannerType = "normal";
      checkMissionProgress();
      renderTUI();
    },

    nudgeSelected() {
      let targetName = "Bragi 3";
      if (state.tuiView === "channel" && state.channelMode === "sessions") {
        const session = state.ledger.channel.sessions[state.tuiSelected];
        if (session) targetName = session.owner;
      }
      state.nudgedSession = true;
      state.bannerMessage = `Nudged ${targetName}. Offline ping recorded in .handoff/channel.sqlite3.`;
      state.bannerType = "success";
      checkMissionProgress();
      renderTUI();
    },

    cutCurrentTask() {
      const task = getCurrentTask();
      if (!task) return;
      state.heldTask = clone(task);
      state.heldStep = null;
      state.bannerMessage = `* HELD: "${task.title}" (Press 'p' on receiving agent in Agents view, or 'x' to cancel)`;
      state.bannerType = "held";
      checkMissionProgress();
      renderTUI();
    },

    pasteHeldTaskTo(targetAgentName) {
      if (!state.heldTask) return;
      const targetAgent = state.ledger.agents.find(a => a.name.toLowerCase() === targetAgentName.toLowerCase());
      if (!targetAgent) return;

      const previousOwner = state.heldTask.owner;
      const taskIndex = state.ledger.tasks.findIndex(t => t.id === state.heldTask.id);

      if (taskIndex >= 0) {
        state.ledger.tasks[taskIndex].owner = targetAgent.name;
        state.ledger.tasks[taskIndex].harness = targetAgent.harness;
        state.ledger.tasks[taskIndex].status += ` Reassigned to ${targetAgent.name} from ${previousOwner} via handoff-tui.`;
      }

      // Update counters
      targetAgent.wip += 1;
      const prevAgent = state.ledger.agents.find(a => a.name === previousOwner);
      if (prevAgent && prevAgent.wip > 0) {
        prevAgent.wip -= 1;
      }

      state.taskReassigned = true;
      state.bannerMessage = `+ Moved "${state.heldTask.title}" to ${targetAgent.name}. Added execution request!`;
      state.bannerType = "success";
      state.heldTask = null;

      // Also trigger response in Cursor Agent if target was Viracocha
      if (targetAgent.name === "Viracocha") {
        state.viracochaAccepted = true;
      }

      checkMissionProgress();
      renderAll();
    },

    toggleStepComplete(stepIndex) {
      const task = getCurrentTask();
      if (!task || !task.steps[stepIndex]) return;

      const step = task.steps[stepIndex];
      step.done = !step.done;

      // Update task check counts
      const allDone = task.steps.every(s => s.done);
      task.completed = allDone;
      task.state = allDone ? "Completed" : "In progress";

      recalcLedgerTotals();
      state.bannerMessage = `Toggled step ${stepIndex + 1}. Ledger version updated.`;
      state.bannerType = "normal";
      renderAll();
    },

    toggleTaskComplete() {
      const task = getCurrentTask();
      if (!task) return;
      const targetDone = !task.completed;
      task.completed = targetDone;
      task.state = targetDone ? "Completed" : "In progress";
      task.steps.forEach(s => (s.done = targetDone));

      recalcLedgerTotals();
      state.bannerMessage = `Marked task "${task.title}" as ${task.state}.`;
      state.bannerType = "success";
      renderAll();
    },

    triggerHandoffContinue() {
      state.handoffContinued = true;
      state.activeHarness = "claude";

      // Append stream item in Claude
      if (el.claudeStream) {
        const streamItem = document.createElement("div");
        streamItem.className = "sim-claude-stream-item";
        streamItem.innerHTML = `
          <div style="color: #ff9857; margin-bottom: 4px;"><strong>● /handoff:continue</strong></div>
          <div class="sim-claude-tool-call">
            <div class="sim-claude-tool-title">● Bash(python3 scripts/handoff_guard.py preflight --root .)</div>
            <div style="color: #7ee787; font-size: 11.5px;">
              Session: Kubera 2 (Claude Code)<br>
              Digest: 2 open tasks found · Auditing previous work...<br>
              Evidence check: Bragi 3 investigated Node executable conflict. Task 1 remains open with 3 unchecked steps.
            </div>
          </div>
          <div style="background: rgba(255, 255, 255, 0.05); border-left: 3px solid #ff9857; padding: 10px 14px; border-radius: 4px; font-size: 12px; margin-top: 8px;">
            <strong>Audit Result:</strong><br>
            Codex exited due to rate limit after identifying that the launcher chose an older Node binary. Step 1 (reproduce) is partially verified by Bragi 3's logs.<br>
            <span style="color: #48e596;">✓ I am resuming the diagnosis from Step 2 without erasing prior investigation.</span>
          </div>
        `;
        el.claudeStream.appendChild(streamItem);
        el.claudeStream.scrollTop = el.claudeStream.scrollHeight;
      }

      setTimeout(() => {
        state.mission1Complete = true;
        checkMissionProgress();
        renderAll();
      }, 700);

      renderAll();
    }
  };

  function getCurrentTask() {
    if (state.tuiView === "detail" && state.detailTask) {
      return state.detailTask;
    }
    const tasks = getVisibleTasks();
    return tasks[state.tuiSelected] || null;
  }

  function getVisibleTasks() {
    if (state.tuiOwner) {
      return state.ledger.tasks.filter(t => t.owner === state.tuiOwner);
    }
    return state.ledger.tasks;
  }

  function recalcLedgerTotals() {
    let totalS = 0;
    let checkedS = 0;
    let completedT = 0;
    let inProgT = 0;

    state.ledger.tasks.forEach(task => {
      if (task.completed) completedT++;
      else inProgT++;
      task.steps.forEach(s => {
        totalS++;
        if (s.done) checkedS++;
      });
    });

    state.ledger.totalTasks = state.ledger.tasks.length;
    state.ledger.completedTasks = completedT;
    state.ledger.inProgressTasks = inProgT;
    state.ledger.totalSteps = totalS;
    state.ledger.checkedSteps = checkedS;
  }

  // Keyboard navigation inside TUI
  function handleTUIKey(key, e) {
    const harnessKeys = { "1": "cursor", "2": "claude", "3": "codex", "4": "grok", "5": "tui" };
    if (!state.tuiOpen && (harnessKeys[key] || (e.metaKey && harnessKeys[key]) || (e.ctrlKey && harnessKeys[key]))) {
      e.preventDefault();
      engine.setHarness(harnessKeys[key]);
      return;
    }

    if (!state.tuiOpen && state.activeHarness !== "tui") {
      // Check global shortcut: Ctrl+Alt+H or 'h'
      if ((e.ctrlKey && e.altKey && key.toLowerCase() === "h") || (e.altKey && e.metaKey && key.toLowerCase() === "h") || key === "h") {
        e.preventDefault();
        engine.toggleTUI();
      }
      return;
    }

    // Modal or tab is active
    if (key === "Escape" || key === "q") {
      if (state.tuiOpen) {
        engine.toggleTUI(false);
      } else if (state.tuiView !== "agents") {
        engine.setTUIView("agents");
      }
      return;
    }

    if (key === "j" || key === "ArrowDown") {
      e.preventDefault();
      moveSelection(1);
    } else if (key === "k" || key === "ArrowUp") {
      e.preventDefault();
      moveSelection(-1);
    } else if (key === "Enter") {
      e.preventDefault();
      handleEnterKey();
    } else if (key === "b" || key === "Backspace") {
      e.preventDefault();
      handleBackKey();
    } else if (key === "a") {
      engine.setTUIView("agents");
    } else if (key === "t") {
      engine.setTUIView("tasks");
    } else if (key === "c") {
      engine.setTUIView("channel");
    } else if (key === "s" && state.tuiView === "channel") {
      engine.toggleChannelMode();
    } else if (key === "n" && state.tuiView === "channel") {
      engine.nudgeSelected();
    } else if (key === "x") {
      if (state.heldTask) {
        state.heldTask = null;
        state.bannerMessage = "Canceled cut.";
        state.bannerType = "normal";
        renderTUI();
      } else {
        engine.cutCurrentTask();
      }
    } else if (key === "p") {
      handlePasteKey();
    } else if (key === "d" && state.tuiView === "detail") {
      engine.toggleStepComplete(state.tuiStepSelected);
    } else if (key === "D") {
      engine.toggleTaskComplete();
    }
  }

  function moveSelection(delta) {
    if (state.tuiView === "agents") {
      const len = state.ledger.agents.length;
      state.tuiSelected = (state.tuiSelected + delta + len) % len;
    } else if (state.tuiView === "tasks") {
      const len = getVisibleTasks().length;
      if (len > 0) state.tuiSelected = (state.tuiSelected + delta + len) % len;
    } else if (state.tuiView === "channel") {
      const list = state.channelMode === "messages" ? state.ledger.channel.messages : state.ledger.channel.sessions;
      const len = list.length;
      if (len > 0) state.tuiSelected = (state.tuiSelected + delta + len) % len;
    } else if (state.tuiView === "detail" && state.detailTask) {
      const len = state.detailTask.steps.length;
      if (len > 0) state.tuiStepSelected = (state.tuiStepSelected + delta + len) % len;
    }
    renderTUI();
  }

  function handleEnterKey() {
    if (state.tuiView === "agents") {
      const agent = state.ledger.agents[state.tuiSelected];
      if (agent) {
        state.tuiOwner = agent.name;
        state.tuiView = "tasks";
        state.tuiSelected = 0;
      }
    } else if (state.tuiView === "tasks") {
      const task = getVisibleTasks()[state.tuiSelected];
      if (task) {
        state.detailTask = task;
        state.tuiView = "detail";
        state.tuiStepSelected = 0;
      }
    }
    checkMissionProgress();
    renderTUI();
  }

  function handleBackKey() {
    if (state.tuiView === "detail") {
      state.tuiView = "tasks";
    } else if (state.tuiView === "tasks") {
      state.tuiView = "agents";
      state.tuiOwner = null;
    }
    checkMissionProgress();
    renderTUI();
  }

  function handlePasteKey() {
    if (!state.heldTask) {
      state.bannerMessage = "Nothing cut. Select a task and press 'x' first.";
      state.bannerType = "alert";
      renderTUI();
      return;
    }

    if (state.tuiView === "agents") {
      const targetAgent = state.ledger.agents[state.tuiSelected];
      if (targetAgent) {
        engine.pasteHeldTaskTo(targetAgent.name);
      }
    } else if (state.tuiView === "tasks") {
      const targetTask = getVisibleTasks()[state.tuiSelected];
      if (targetTask) {
        engine.pasteHeldTaskTo(targetTask.owner);
      }
    }
  }

  // Mission Progression Check
  function checkMissionProgress() {
    const cur = missions[state.currentMissionIndex];
    if (!cur) return;

    let allStepsDone = true;
    for (let i = 0; i < cur.steps.length; i++) {
      if (!cur.steps[i].check(state)) {
        allStepsDone = false;
        break;
      }
    }

    renderMissionCard();
  }

  function renderMissionCard() {
    const cur = missions[state.currentMissionIndex];
    if (!cur) return;

    if (el.missionBadge) el.missionBadge.textContent = cur.badge;
    if (el.missionTitle) el.missionTitle.textContent = cur.title;
    if (el.missionDesc) el.missionDesc.textContent = cur.description;

    // Find first unfinished step
    let stepIndex = 0;
    while (stepIndex < cur.steps.length && cur.steps[stepIndex].check(state)) {
      stepIndex++;
    }

    const completed = stepIndex >= cur.steps.length;

    if (el.missionStep) {
      if (completed) {
        el.missionStep.innerHTML = `<span style="color: #48e596;">🎉 <strong>Mission complete!</strong> ${cur.takeaway}</span>`;
      } else {
        const s = cur.steps[stepIndex];
        el.missionStep.innerHTML = `<span><strong>Step ${stepIndex + 1}:</strong> ${s.instruction}</span>`;
      }
    }

    if (el.missionAction) {
      el.missionAction.innerHTML = "";
      if (completed) {
        if (state.currentMissionIndex < missions.length - 1) {
          const nextBtn = document.createElement("button");
          nextBtn.className = "sim-action-btn";
          nextBtn.textContent = "Next Mission →";
          nextBtn.onclick = () => {
            state.currentMissionIndex++;
            renderMissionCard();
            renderAll();
          };
          el.missionAction.appendChild(nextBtn);
        }
      } else {
        const s = cur.steps[stepIndex];
        if (s.actionLabel && s.action) {
          const actBtn = document.createElement("button");
          actBtn.className = "sim-action-btn";
          actBtn.textContent = s.actionLabel;
          actBtn.onclick = () => {
            s.action(engine);
          };
          el.missionAction.appendChild(actBtn);
        }
      }
    }

    // Update mission pills
    if (el.missionPills) {
      el.missionPills.forEach((pill, idx) => {
        pill.classList.toggle("active", idx === state.currentMissionIndex);
        let missionDone = true;
        if (missions[idx]) {
          missions[idx].steps.forEach(s => {
            if (!s.check(state)) missionDone = false;
          });
        }
        pill.classList.toggle("completed", missionDone && idx !== 4);
      });
    }
  }

  // Render High-Fidelity TUI View
  function renderTUI() {
    const l = state.ledger;
    const taskPct = Math.round((l.completedTasks / l.totalTasks) * 100);
    const stepPct = Math.round((l.checkedSteps / l.totalSteps) * 100);

    // Update headers and summary bars
    if (el.tuiTaskBars) {
      el.tuiTaskBars.forEach(bar => {
        bar.innerHTML = `TASKS&nbsp;&nbsp;[###########-]&nbsp;&nbsp;${taskPct}%&nbsp;${l.completedTasks}/${l.totalTasks} completed&nbsp;&nbsp;&nbsp;${l.inProgressTasks} in progress / ${l.pendingTasks} pending`;
      });
    }

    if (el.tuiStepBars) {
      el.tuiStepBars.forEach(bar => {
        bar.innerHTML = `STEPS&nbsp;&nbsp;[###########-]&nbsp;&nbsp;${stepPct}%&nbsp;${l.checkedSteps}/${l.totalSteps} checked`;
      });
    }

    // Update navigation tabs
    if (el.tuiNavTabs) {
      el.tuiNavTabs.forEach(nav => {
        const activeLabel = state.tuiView === "agents" ? `[Agents | repo]&nbsp;&nbsp;Tasks&nbsp;&nbsp;c: Channel`
          : state.tuiView === "tasks" ? `Agents&nbsp;&nbsp;[Tasks: ${state.tuiOwner || "all"}]&nbsp;&nbsp;c: Channel`
          : state.tuiView === "channel" ? `Agents&nbsp;&nbsp;Tasks&nbsp;&nbsp;[Channel: ${state.channelMode}]`
          : `[Task Details]&nbsp;&nbsp;b: back`;
        nav.innerHTML = `<span>${activeLabel}</span><span class="tui-nav-hint">Enter: select · j/k: move · x: cut · p: give · q: close</span>`;
      });
    }

    // Update Banner
    if (el.tuiBanners) {
      el.tuiBanners.forEach(b => {
        b.textContent = state.bannerMessage;
        b.className = `tui-banner ${state.bannerType}`;
      });
    }

    // Update Table Content
    if (el.tuiTableBodies) {
      el.tuiTableBodies.forEach(body => {
        body.innerHTML = "";
        if (state.tuiView === "agents") {
          renderTUIAgentsTable(body);
        } else if (state.tuiView === "tasks") {
          renderTUITasksTable(body);
        } else if (state.tuiView === "channel") {
          renderTUIChannelTable(body);
        } else if (state.tuiView === "detail") {
          renderTUIDetailView(body);
        }
      });
    }

    // Update bottom tmux agent status line across screens
    if (el.tmuxBars) {
      el.tmuxBars.forEach(bar => {
        bar.innerHTML = `
          <div class="sim-tmux-left">
            <span class="sim-tmux-handoff-tag">handoff</span>
            <span class="sim-tmux-progress">[|||||||||||] ${l.completedTasks}/${l.totalTasks} tasks · ${l.checkedSteps}/${l.totalSteps} steps</span>
            <span class="sim-tmux-agents">Active: ${l.agents.filter(a => a.wip > 0).map(a => a.name).join(", ") || "None"}</span>
          </div>
          <div class="sim-tmux-right">
            <span>-- INSERT -- ▶▶ bypass permissions on</span>
            <span class="sim-tmux-hud-key" onclick="window.HandoffSimulator.toggleTUI(true)">[ ⌥⌘H / Ctrl+Alt+H ]</span>
          </div>
        `;
      });
    }
  }

  function renderTUIAgentsTable(container) {
    const header = document.createElement("div");
    header.className = "tui-table-header";
    header.innerHTML = `
      <div class="tui-col-name">WAITING / OWNER</div>
      <div class="tui-col-harness">HARNESS</div>
      <div class="tui-col-done">DONE/TASK</div>
      <div class="tui-col-wip">WIP</div>
      <div class="tui-col-wait">WAIT</div>
      <div class="tui-col-steps">CHECKED STEPS</div>
      <div class="tui-col-flags">!bad ?old</div>
    `;
    container.appendChild(header);

    state.ledger.agents.forEach((agent, idx) => {
      const row = document.createElement("div");
      row.className = `tui-row ${idx === state.tuiSelected ? "selected" : ""}`;
      const prefix = idx === state.tuiSelected ? ">" : " ";
      const roleTag = agent.role ? `[${agent.role}] ` : "";
      const stepPct = agent.totalSteps > 0 ? Math.round((agent.checkedSteps / agent.totalSteps) * 100) : "n/a";
      const stepBar = agent.totalSteps > 0 ? `[########] ${stepPct}%` : `[--------] n/a`;

      row.innerHTML = `
        <div class="tui-col-name">${prefix}${roleTag}${agent.name}</div>
        <div class="tui-col-harness">${agent.harness}</div>
        <div class="tui-col-done">${agent.doneTasks}/${agent.totalTasks}</div>
        <div class="tui-col-wip">${agent.wip}</div>
        <div class="tui-col-wait">${agent.wait}</div>
        <div class="tui-col-steps">${stepBar} ${agent.checkedSteps}/${agent.totalSteps}</div>
        <div class="tui-col-flags">!${agent.bad} ?${agent.old}</div>
      `;

      row.onclick = () => {
        state.tuiSelected = idx;
        handleEnterKey();
      };
      container.appendChild(row);
    });
  }

  function renderTUITasksTable(container) {
    const header = document.createElement("div");
    header.className = "tui-table-header";
    header.innerHTML = `
      <div class="tui-col-task-state">STATE</div>
      <div class="tui-col-task-steps">STEPS</div>
      <div class="tui-col-task-title">TASK / OWNER (ledger order)</div>
    `;
    container.appendChild(header);

    const tasks = getVisibleTasks();
    if (tasks.length === 0) {
      const empty = document.createElement("div");
      empty.style.padding = "16px";
      empty.style.color = "var(--tui-dim)";
      if (state.tuiOwner === "Sasabonsam 3") {
        empty.innerHTML = `
          <div style="color: #00f0ff; font-weight: bold; margin-bottom: 6px;">[WAITING AGENT] Sasabonsam 3 (Claude Code)</div>
          <div>This session claimed a name recently on this machine, but holds no tasks in the ledger yet.</div>
          <div style="margin-top: 10px; color: #f8a838;">
            💡 <strong>Assign work from another agent:</strong><br>
            1. Press <kbd style="background: rgba(0,0,0,0.4); padding: 1px 5px; border-radius: 3px;">b</kbd> to return to all tasks or Agents.<br>
            2. Select an open task and press <kbd style="background: rgba(0,0,0,0.4); padding: 1px 5px; border-radius: 3px;">x</kbd> to cut it.<br>
            3. Highlight <strong>Sasabonsam 3</strong> in Agents (<kbd style="background: rgba(0,0,0,0.4); padding: 1px 5px; border-radius: 3px;">a</kbd>) and press <kbd style="background: rgba(0,0,0,0.4); padding: 1px 5px; border-radius: 3px;">p</kbd> to give the task!
          </div>
        `;
      } else {
        empty.textContent = "No tasks found for this filter. Press 'b' to return to Agents.";
      }
      container.appendChild(empty);
      return;
    }

    tasks.forEach((task, idx) => {
      const row = document.createElement("div");
      const isSelected = idx === state.tuiSelected;
      const isHeld = state.heldTask && state.heldTask.id === task.id;
      row.className = `tui-row ${isSelected ? "selected" : ""} ${isHeld ? "held" : ""}`;

      const mark = isHeld ? "*" : isSelected ? ">" : " ";
      const checkedCount = task.steps.filter(s => s.done).length;
      const stateColor = task.completed ? "var(--tui-green)" : "var(--tui-amber)";

      row.innerHTML = `
        <div class="tui-col-task-state" style="color: ${isSelected ? 'inherit' : stateColor};">${mark} ${task.state}</div>
        <div class="tui-col-task-steps">${checkedCount}/${task.steps.length}</div>
        <div class="tui-col-task-title">${task.title} <span class="tui-subtext">(${task.owner})</span></div>
      `;

      row.onclick = () => {
        state.tuiSelected = idx;
        handleEnterKey();
      };
      container.appendChild(row);
    });
  }

  function renderTUIChannelTable(container) {
    const header = document.createElement("div");
    header.className = "tui-table-header";
    header.innerHTML = state.channelMode === "messages"
      ? `<div style="width: 70px;">TIME</div><div style="width: 220px;">SENDER -> RECIPIENT</div><div style="width: 80px;">STATUS</div><div style="flex: 1;">BODY</div>`
      : `<div style="width: 200px;">SESSION / HARNESS</div><div style="width: 140px;">STATE</div><div style="flex: 1;">LAST HEARTBEAT</div>`;
    container.appendChild(header);

    if (state.channelMode === "messages") {
      state.ledger.channel.messages.forEach((msg, idx) => {
        const row = document.createElement("div");
        row.className = `tui-row ${idx === state.tuiSelected ? "selected" : ""}`;
        row.innerHTML = `
          <div style="width: 70px;">${msg.created}</div>
          <div style="width: 220px;">${msg.sender} -> ${msg.recipient}</div>
          <div style="width: 80px; color: var(--tui-cyan);">${msg.ack}</div>
          <div style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${msg.body}</div>
        `;
        row.onclick = () => {
          state.tuiSelected = idx;
          renderTUI();
        };
        container.appendChild(row);
      });
    } else {
      state.ledger.channel.sessions.forEach((s, idx) => {
        const row = document.createElement("div");
        row.className = `tui-row ${idx === state.tuiSelected ? "selected" : ""}`;
        row.innerHTML = `
          <div style="width: 200px;">${s.owner} (${s.harness})</div>
          <div style="width: 140px; color: ${s.state === 'working' ? 'var(--tui-green)' : 'var(--tui-dim)'};">${s.state}</div>
          <div style="flex: 1;">${s.reported}s ago (healthy heartbeat)</div>
        `;
        row.onclick = () => {
          state.tuiSelected = idx;
          renderTUI();
        };
        container.appendChild(row);
      });
    }
  }

  function renderTUIDetailView(container) {
    const task = state.detailTask;
    if (!task) return;

    const detailWrap = document.createElement("div");
    detailWrap.className = "tui-detail-view";

    detailWrap.innerHTML = `
      <div class="tui-detail-title">${task.title}</div>
      <div class="tui-detail-meta">Owner: <strong>${task.owner}</strong> · Harness: <strong>${task.harness}</strong> · State: <strong>${task.state}</strong></div>
      <div style="font-size: 11px; color: var(--tui-dim); margin-top: 4px;">Press 'd' to toggle step checkbox, 'D' to toggle task complete, 'x' to cut step.</div>
      <div class="tui-steps-list">
        ${task.steps.map((step, idx) => `
          <div class="tui-step-item ${idx === state.tuiStepSelected ? 'selected' : ''}" onclick="window.HandoffSimulator.selectStep(${idx})">
            <span>${step.done ? '[x]' : '[ ]'}</span>
            <span style="flex: 1;">${step.text}</span>
          </div>
        `).join("")}
      </div>
      <div class="tui-detail-status-box">
        <strong>RECORDED STATUS:</strong><br>${task.status}
      </div>
    `;

    container.appendChild(detailWrap);
  }

  function renderAll() {
    renderTUI();
    renderMissionCard();

    // Render Viracocha update in Cursor composer if reassigned
    if (state.viracochaAccepted && el.cursorComposer) {
      el.cursorComposer.innerHTML = `
        <div class="sim-composer-msg">
          <span style="color: #48e596; font-weight: bold;">● Execution Request Received from handoff-tui</span><br>
          Assigned task: <em>Diagnose handoff-tui --with codex ending with [server exited]</em><br>
          Prior owner: Kubera 2 · Status: In progress
        </div>
        <div class="sim-composer-msg agent">
          <strong>Viracocha (Cursor Agent):</strong><br>
          Audit complete. Inspecting <code>scripts/handoff_keys.py</code> and verifying NVM path resolution precedence...
        </div>
      `;
    }
  }

  // Interactive Guided Walkthrough Tour Manager
  const TourManager = {
    currentStep: 0,
    isActive: false,

    steps: [
      {
        badge: "STEP 1 OF 8",
        title: "Multi-Harness Coordination",
        body: "In modern multi-agent development, work happens across disparate tools (Cursor, Claude Code, Codex, Grok). Notice the harness switcher at the top. Each tool retains its native workflow while sharing a single source of truth.",
        target: ".sim-harness-tabs",
        setup: () => {
          engine.toggleTUI(false);
          engine.setHarness("cursor");
        },
        actionText: "Switch to Codex (3)",
        action: () => engine.setHarness("codex")
      },
      {
        badge: "STEP 2 OF 8",
        title: "The Sudden Stop Cliffhanger",
        body: "Codex was investigating an NVM binary resolution bug when it abruptly hit an API rate limit and exited with error 1. Without Handoff, these diagnostic insights would vanish in a closed terminal.",
        target: "#sim-screen-codex",
        setup: () => {
          engine.toggleTUI(false);
          engine.setHarness("codex");
        },
        actionText: "Switch to Claude Code (2)",
        action: () => engine.setHarness("claude")
      },
      {
        badge: "STEP 3 OF 8",
        title: "Audit & Resume via Claude Code",
        body: "Now switch to Claude Code (<code>Kubera 2</code>). Running <code>/handoff:continue</code> audits the shared ledger, identifies Codex's partial findings, and resumes without losing an ounce of progress!",
        target: ".sim-claude-layout",
        setup: () => {
          engine.toggleTUI(false);
          engine.setHarness("claude");
        },
        actionText: "Run /handoff:continue",
        action: () => engine.triggerHandoffContinue()
      },
      {
        badge: "STEP 4 OF 8",
        title: "Real-Time Ledger Status Bar",
        body: "Look at the terminal status line at the bottom. The shared ledger tracks overall tasks, checked steps, and active agents across every harness in real-time. Every change is committed atomically using CAS protection in <code>HANDOFF.md</code>.",
        target: ".sim-tmux-agent-bar",
        setup: () => {
          engine.toggleTUI(false);
        },
        actionText: "Open handoff-tui HUD",
        action: () => engine.toggleTUI(true)
      },
      {
        badge: "STEP 5 OF 8",
        title: "Full Cockpit: handoff-tui",
        body: "Press <code>Ctrl+Alt+H</code> (or <code>h</code>) anytime to summon the curses cockpit! Here you see all 14 active and waiting agents, their WIP, and assigned tasks. Press <code>j/k</code> to move down/up and <code>Enter</code> to inspect.",
        target: "#sim-tui-modal .sim-tui-modal-window",
        setup: () => {
          engine.toggleTUI(true);
          engine.setTUIView("agents");
        },
        actionText: "Inspect Kubera 2",
        action: () => {
          engine.setTUIView("tasks", "Kubera 2");
        }
      },
      {
        badge: "STEP 6 OF 8",
        title: "Task Evidence & Step Checklists",
        body: "Tasks aren't vague black boxes. Each task contains an actionable checklist with explicit reproduction steps, logs, and verification commands. Press <code>Enter</code> to view full task details or <code>d</code> to check steps.",
        target: "#sim-tui-modal .sim-dyn-tui-body",
        setup: () => {
          engine.toggleTUI(true);
          const task = state.ledger.tasks.find(t => t.owner === "Kubera 2") || state.ledger.tasks[0];
          if (task) {
            state.detailTask = task;
            engine.setTUIView("detail");
          }
        },
        actionText: "Toggle Verification Step",
        action: () => {
          engine.toggleStepComplete(0);
        }
      },
      {
        badge: "STEP 7 OF 8",
        title: "Surgical Cut & Paste Reassignment",
        body: "Need to delegate or balance workloads across agents? Press <code>x</code> to cut a task, switch to Agents view (<code>a</code>), select another agent (e.g. <code>Viracocha</code> in Cursor), and press <code>p</code> to paste!",
        target: "#sim-tui-modal .tui-keys-footer",
        setup: () => {
          engine.toggleTUI(true);
          engine.setTUIView("agents");
        },
        actionText: "Reassign to Viracocha",
        action: () => {
          const task = state.ledger.tasks.find(t => t.owner === "Kubera 2") || state.ledger.tasks[0];
          if (task) {
            state.heldTask = clone(task);
            engine.pasteHeldTaskTo("Viracocha");
          }
        }
      },
      {
        badge: "STEP 8 OF 8",
        title: "Autonomous Execution in Cursor",
        body: "Close the TUI and switch to Cursor IDE. Viracocha instantly receives the execution request in Composer and begins investigating the fix! That's seamless multi-agent collaboration with <code>handoff-skill</code>.",
        target: "#sim-screen-cursor",
        setup: () => {
          engine.toggleTUI(false);
          engine.setHarness("cursor");
        },
        actionText: "Finish Tour 🎉",
        action: () => {
          TourManager.endTour(true);
        }
      }
    ],

    startTour() {
      this.isActive = true;
      if (el.startTourBtn) el.startTourBtn.classList.add("active");
      if (el.tourCard) el.tourCard.classList.add("visible");
      if (el.wrap) {
        el.wrap.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      this.showStep(0);
    },

    endTour(completed = false) {
      this.isActive = false;
      this.clearSpotlight();
      if (el.startTourBtn) {
        el.startTourBtn.classList.remove("active");
        if (completed) {
          el.startTourBtn.textContent = "✓ Tour Completed";
          setTimeout(() => {
            if (el.startTourBtn) el.startTourBtn.textContent = "▶ Guided Walkthrough";
          }, 4000);
        }
      }
      if (el.tourCard) el.tourCard.classList.remove("visible");
    },

    showStep(idx) {
      if (idx < 0 || idx >= this.steps.length) return;
      this.currentStep = idx;
      const s = this.steps[idx];

      // Run step setup
      if (s.setup) s.setup();

      // Update card texts
      if (el.tourBadge) el.tourBadge.textContent = s.badge;
      if (el.tourTitle) el.tourTitle.textContent = s.title;
      if (el.tourBody) el.tourBody.innerHTML = s.body;

      // Update buttons
      if (el.tourPrev) {
        el.tourPrev.disabled = idx === 0;
      }
      if (el.tourNext) {
        el.tourNext.textContent = idx === this.steps.length - 1 ? "Finish ✓" : "Next →";
      }
      if (el.tourAct) {
        if (s.actionText) {
          el.tourAct.style.display = "inline-block";
          el.tourAct.textContent = s.actionText;
          el.tourAct.onclick = () => {
            if (s.action) s.action();
            el.tourAct.textContent = "✓ Done";
          };
        } else {
          el.tourAct.style.display = "none";
        }
      }

      // Update dots
      if (el.tourDots) {
        el.tourDots.innerHTML = this.steps.map((_, i) => {
          let cls = "sim-tour-dot";
          if (i === idx) cls += " active";
          else if (i < idx) cls += " done";
          return `<span class="${cls}" onclick="window.HandoffSimulator.goToTourStep(${i})"></span>`;
        }).join("");
      }

      // Highlight target element
      this.clearSpotlight();
      setTimeout(() => {
        const targetEl = document.querySelector(s.target);
        if (targetEl) {
          targetEl.classList.add("sim-spotlight-pulse");
          if (!state.tuiOpen) {
            targetEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
        }
      }, 70);
    },

    nextStep() {
      if (this.currentStep < this.steps.length - 1) {
        this.showStep(this.currentStep + 1);
      } else {
        this.endTour(true);
      }
    },

    prevStep() {
      if (this.currentStep > 0) {
        this.showStep(this.currentStep - 1);
      }
    },

    clearSpotlight() {
      document.querySelectorAll(".sim-spotlight-pulse").forEach(node => {
        node.classList.remove("sim-spotlight-pulse");
      });
    }
  };

  // Setup Event Listeners
  function setupEvents() {
    // Tab switching
    if (el.tabBtns) {
      el.tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
          engine.setHarness(btn.dataset.harness);
        });
      });
    }

    // Mission pill click
    if (el.missionPills) {
      el.missionPills.forEach((pill, idx) => {
        pill.addEventListener("click", () => {
          state.currentMissionIndex = idx;
          renderMissionCard();
          renderAll();
        });
      });
    }

    // HUD trigger button
    if (el.hudTrigger) {
      el.hudTrigger.addEventListener("click", () => {
        engine.toggleTUI(true);
      });
    }

    // Tour trigger button
    if (el.startTourBtn) {
      el.startTourBtn.addEventListener("click", () => {
        TourManager.startTour();
      });
    }
    if (el.tourNext) {
      el.tourNext.addEventListener("click", () => {
        TourManager.nextStep();
      });
    }
    if (el.tourPrev) {
      el.tourPrev.addEventListener("click", () => {
        TourManager.prevStep();
      });
    }
    if (el.tourClose) {
      el.tourClose.addEventListener("click", () => {
        TourManager.endTour(false);
      });
    }

    // Close HUD modal
    if (el.tuiModalClose) {
      el.tuiModalClose.addEventListener("click", () => {
        engine.toggleTUI(false);
      });
    }
    if (el.tuiModal) {
      el.tuiModal.addEventListener("click", e => {
        if (e.target === el.tuiModal) {
          engine.toggleTUI(false);
        }
      });
    }

    // Keyboard navigation
    window.addEventListener("keydown", e => {
      // Don't capture keys if user is typing in standard text inputs outside simulator
      const tag = e.target.tagName.toLowerCase();
      if (tag === "input" && e.target.id !== "sim-claude-input") return;
      if (tag === "textarea") return;

      if (TourManager.isActive) {
        if (e.key === "ArrowRight") {
          e.preventDefault();
          TourManager.nextStep();
          return;
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          TourManager.prevStep();
          return;
        } else if (e.key === "Escape" && !state.tuiOpen) {
          e.preventDefault();
          TourManager.endTour(false);
          return;
        }
      }

      handleTUIKey(e.key, e);
    });

    // Claude input enter
    if (el.claudeRunBtn && el.claudeInput) {
      el.claudeRunBtn.addEventListener("click", () => {
        if (el.claudeInput.value.includes("/handoff:continue") || el.claudeInput.value.includes("continue")) {
          engine.triggerHandoffContinue();
        }
      });
      el.claudeInput.addEventListener("keydown", e => {
        if (e.key === "Enter") {
          if (el.claudeInput.value.includes("/handoff:continue") || el.claudeInput.value.includes("continue")) {
            engine.triggerHandoffContinue();
          }
        }
      });
    }
  }

  // Public Exposure for HTML onclick bindings
  window.HandoffSimulator = {
    init() {
      if (!initElements()) return;
      setupEvents();
      renderAll();
    },
    engine,
    startTour() {
      TourManager.startTour();
    },
    endTour() {
      TourManager.endTour();
    },
    goToTourStep(idx) {
      TourManager.showStep(idx);
    },
    selectStep(idx) {
      state.tuiStepSelected = idx;
      renderTUI();
    },
    toggleTUI(open) {
      engine.toggleTUI(open);
    },
    setMission(idx) {
      state.currentMissionIndex = idx;
      renderMissionCard();
      renderAll();
    }
  };

  // Auto initialize on DOMContentLoaded
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => window.HandoffSimulator.init());
  } else {
    window.HandoffSimulator.init();
  }
})();
