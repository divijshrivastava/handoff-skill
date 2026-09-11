(function () {
  "use strict";

  var byId = function (id) { return document.getElementById(id); };
  var all = function (selector) { return Array.from(document.querySelectorAll(selector)); };
  var genericInstall = "npx skills add divijshrivastava/handoff-skill --skill handoff -g";
  var pathInput = byId("repo-path");
  var terminal = "iterm2";
  var validPath = false;
  var copyTimers = new Map();

  // Quote user input as one POSIX shell argument, including literal apostrophes.
  function shellQuote(value) {
    return "'" + value.replace(/'/g, "'\\''") + "'";
  }

  function resetVerification() {
    all('input[name="verified"]').forEach(function (input) { input.checked = false; });
    byId("verify-feedback").textContent = "Not verified yet. Try the current command in your selected terminal.";
    byId("verify-feedback").classList.remove("success");
  }

  function updateCommands() {
    var path = pathInput.value;
    validPath = path.startsWith("/") && !/[\x00-\x1f\x7f]/.test(path);
    var hasInput = path.length > 0;
    pathInput.setAttribute("aria-invalid", String(hasInput && !validPath));
    byId("path-error").textContent = hasInput && !validPath
      ? "Use a full macOS, Linux, or WSL path starting with /. Paste one path without line breaks."
      : "";
    var quotedRoot = shellQuote(validPath ? path : "/absolute/path/to/your-project");
    byId("viewer-command").textContent = "handoff-tui --root " + quotedRoot;
    var prefix = "HANDOFF_VIEWER_KEY=C-M-h handoff-tui ";
    byId("shortcut-command").textContent = terminal === "tmux"
      ? prefix + "--root " + quotedRoot + " --with " + byId("agent-cli").value
      : prefix + "--install-viewer-key --emulator " + terminal + " --root " + quotedRoot;
    all('[data-copy="viewer-command"], [data-copy="shortcut-command"]').forEach(function (button) {
      clearTimeout(copyTimers.get(button));
      button.disabled = !validPath;
      button.textContent = validPath ? "Copy ⧉" : "Enter a path first";
    });
    resetVerification();
  }

  var terminalNotes = {
    iterm2: "iTerm2: installs a global key binding and a dedicated profile that opens this repository’s dashboard in a new window. If iTerm2 asks to load changed preferences, reload them before trying the key.",
    cursor: "Cursor: installs a Handoff viewer workspace task and a terminal shortcut. Reload the Cursor window after installation, then focus the integrated terminal and press the key. Install separately for each workspace.",
    tmux: "tmux: launches the selected agent with a live Handoff bar. Press the shortcut inside that wrapped session to open a popup; q returns to the agent. This does not install an iTerm2 or Cursor binding."
  };

  all('input[name="host"]').forEach(function (input) {
    input.addEventListener("change", function () {
      var claude = input.value === "claude";
      byId("skill-command").textContent = claude
        ? "/plugin marketplace add divijshrivastava/handoff-skill\n/plugin install handoff@divij-skills\n/reload-plugins"
        : genericInstall;
      byId("install-context").textContent = claude
        ? "IN CLAUDE CODE · RUN EACH LINE SEPARATELY"
        : "IN YOUR TERMINAL · FROM YOUR PROJECT";
      byId("install-note").textContent = claude
        ? "These are Claude Code commands, not shell commands. Add the marketplace, install the plugin, then reload plugins or start a new session in your project."
        : "This uses the skills CLI and requires Node.js/npm. Select your agent in the installer, then open a new agent session in your project. The -g flag makes the skill available across projects.";
      if (input.value === "codex" || claude) {
        byId("agent-cli").value = claude ? "claude" : "codex";
        updateCommands();
      }
    });
  });

  all('input[name="terminal"]').forEach(function (input) {
    input.addEventListener("change", function () {
      terminal = input.value;
      byId("cli-field").hidden = terminal !== "tmux";
      byId("terminal-note").textContent = terminalNotes[terminal];
      byId("shortcut-context").textContent = terminal === "tmux"
        ? "IN YOUR TERMINAL · LAUNCH A WRAPPED AGENT"
        : "IN YOUR TERMINAL · INSTALL THE BINDING";
      updateCommands();
    });
  });
  pathInput.addEventListener("input", updateCommands);
  byId("agent-cli").addEventListener("change", updateCommands);

  all("[data-copy]").forEach(function (button) {
    button.addEventListener("click", async function () {
      var command = byId(button.dataset.copy);
      var originalLabel = button.textContent;
      clearTimeout(copyTimers.get(button));
      try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) { throw new Error("Clipboard unavailable"); }
        await navigator.clipboard.writeText(command.textContent);
        button.textContent = "Copied ✓";
        byId("copy-status").textContent = button.getAttribute("aria-label") + ": copied.";
      } catch (_) {
        var range = document.createRange();
        range.selectNodeContents(command);
        var selection = window.getSelection();
        if (selection) {
          selection.removeAllRanges();
          selection.addRange(range);
        }
        button.textContent = "Select & copy";
        byId("copy-status").textContent = "Clipboard access is unavailable. The text is selected; use your browser’s Copy command.";
      }
      copyTimers.set(button, setTimeout(function () {
        button.textContent = originalLabel.indexOf("Enter a path") >= 0 ? originalLabel : "Copy ⧉";
      }, 2200));
    });
  });

  var scenes = [
    {
      owner: "Atlas", count: "0 / 2", done: false,
      evidence: "Task recorded before editing. Next: inspect the repository and write the map.",
      lesson: "A name alone is not progress. The task entry makes the planned work visible."
    },
    {
      owner: "Atlas", count: "1 / 2", done: true,
      evidence: "PROJECT_MAP.md is written. Its paths have not been checked. Paused; next action: compare every listed path with the repository.",
      lesson: "The task stays open. A precise next action is more useful than “continue later.”"
    },
    {
      owner: "Themis", count: "1 / 2", done: true,
      evidence: "Atlas stopped writing. The user authorized a takeover. Themis preserved the existing document and audited later entries and commits. Path verification still remains.",
      lesson: "Ownership changes; finished work stays finished. Themis verifies the paths before marking the task complete."
    }
  ];
  all("[data-scene]").forEach(function (button) {
    button.addEventListener("click", function () {
      var scene = scenes[Number(button.dataset.scene)];
      all("[data-scene]").forEach(function (item) {
        item.setAttribute("aria-pressed", String(item === button));
      });
      byId("example-owner").textContent = scene.owner;
      byId("example-count").textContent = scene.count;
      byId("example-step-one").textContent = (scene.done ? "✓" : "□") + " Write PROJECT_MAP.md";
      byId("example-step-one").classList.toggle("done", scene.done);
      byId("example-evidence").textContent = scene.evidence;
      byId("scene-lesson").textContent = scene.lesson;
    });
  });

  var answers = {
    rewrite: "Start with an audit. The document may already satisfy the writing step; rewriting can duplicate or overwrite finished work.",
    audit: "Exactly. Check the current file, later ledger entries, and commits. Verify only what still remains, then record the evidence.",
    complete: "An existing document does not prove verification happened. Inspect the evidence and finish any missing check before marking the task complete."
  };
  all("[data-answer]").forEach(function (button) {
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", function () {
      all("[data-answer]").forEach(function (item) { item.setAttribute("aria-pressed", String(item === button)); });
      byId("answer-feedback").textContent = answers[button.dataset.answer];
      byId("answer-feedback").classList.toggle("correct", button.dataset.answer === "audit");
    });
  });

  all('input[name="verified"]').forEach(function (input) {
    input.addEventListener("change", function () {
      var success = input.value === "yes";
      byId("verify-feedback").classList.toggle("success", success);
      byId("verify-feedback").textContent = success
        ? "Confirmed by you: the shortcut opened your project’s dashboard. Use q to return to your work."
        : "Shortcut not verified. Try the viewer command directly first, then follow “Ctrl+Alt+H does nothing” in Get unstuck below. You can continue using the ledger meanwhile.";
    });
  });

  var navLinks = all('.guide-nav nav a');
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) { return; }
        navLinks.forEach(function (link) {
          if (link.hash === "#" + entry.target.id) { link.setAttribute("aria-current", "step"); }
          else { link.removeAttribute("aria-current"); }
        });
      });
    }, { rootMargin: "-8% 0px -65% 0px", threshold: 0 });
    navLinks.forEach(function (link) { observer.observe(byId(link.hash.slice(1))); });
  }
  updateCommands();
})();
