(function () {
  "use strict";

  var STEPS = ["welcome", "terminal", "install", "practice-web", "practice-real", "done"];
  var state = {
    step: 0,
    terminal: "iterm2",
    repoPath: "",
    webPractice: false,
    realPractice: false,
  };

  var refs = {
    progress: document.getElementById("progress"),
    steps: STEPS.map(function (id) {
      return document.getElementById("step-" + id);
    }),
    back: document.getElementById("back"),
    next: document.getElementById("next"),
    repoPath: document.getElementById("repo-path"),
    command: document.getElementById("install-command"),
    copy: document.getElementById("copy-command"),
    practiceZone: document.getElementById("practice-zone"),
    practiceStatus: document.getElementById("practice-status"),
    keycaps: {
      ctrl: document.getElementById("key-ctrl"),
      alt: document.getElementById("key-alt"),
      h: document.getElementById("key-h"),
    },
    realYes: document.getElementById("real-yes"),
    realNo: document.getElementById("real-no"),
    realStatus: document.getElementById("real-status"),
    choices: Array.prototype.slice.call(document.querySelectorAll("[data-terminal]")),
  };

  function installCommand() {
    var root = state.repoPath.trim() || "/path/to/your/repo";
    if (state.terminal === "other") {
      return "HANDOFF_VIEWER_KEY=C-M-h handoff-tui --root " + root + " --codex";
    }
    var emulator = state.terminal === "cursor" ? "cursor" : "iterm2";
    return (
      "HANDOFF_VIEWER_KEY=C-M-h handoff-tui --install-viewer-key --tutorial-viewer-key " +
      "--emulator " + emulator + " --root " + root
    );
  }

  function renderProgress() {
    refs.progress.innerHTML = "";
    STEPS.forEach(function (_, index) {
      var bar = document.createElement("span");
      if (index < state.step) {
        bar.className = "done";
      } else if (index === state.step) {
        bar.className = "active";
      }
      refs.progress.appendChild(bar);
    });
  }

  function renderStep() {
    STEPS.forEach(function (_, index) {
      refs.steps[index].classList.toggle("active", index === state.step);
    });
    renderProgress();

    refs.back.disabled = state.step === 0;
    refs.next.hidden = state.step === STEPS.length - 1;
    refs.next.disabled = !canAdvance();

    if (state.step === 2) {
      refs.command.textContent = installCommand();
    }

    if (state.step === 4) {
      refs.realYes.classList.toggle("selected", state.realPractice === true);
      refs.realNo.classList.toggle("selected", state.realPractice === false);
      refs.realStatus.textContent = state.realPractice === true
        ? "Nice — you are ready to use Handoff day to day."
        : state.realPractice === false
          ? "Check the install command, reload iTerm2 or Cursor, and try again."
          : "";
      refs.realStatus.className = "practice-status" + (state.realPractice === true ? " ok" : "");
    }
  }

  function canAdvance() {
    if (state.step === 3) {
      return state.webPractice;
    }
    if (state.step === 4) {
      return state.realPractice !== null;
    }
    return true;
  }

  function setTerminal(value) {
    state.terminal = value;
    refs.choices.forEach(function (button) {
      button.classList.toggle("selected", button.dataset.terminal === value);
    });
    if (state.step === 2) {
      refs.command.textContent = installCommand();
    }
  }

  function flashKeycap(name) {
    var cap = refs.keycaps[name];
    if (!cap) {
      return;
    }
    cap.classList.add("pressed");
    window.setTimeout(function () {
      cap.classList.remove("pressed");
    }, 180);
  }

  function onPracticeKeydown(event) {
    if (state.step !== 3) {
      return;
    }
    var key = event.key.toLowerCase();
    if (event.ctrlKey) {
      flashKeycap("ctrl");
    }
    if (event.altKey) {
      flashKeycap("alt");
    }
    if (key === "h") {
      flashKeycap("h");
    }
    if (event.ctrlKey && event.altKey && key === "h") {
      event.preventDefault();
      state.webPractice = true;
      refs.practiceZone.classList.add("focused");
      refs.practiceStatus.textContent = "Got it — that is the chord.";
      refs.practiceStatus.className = "practice-status ok";
      renderStep();
    }
  }

  function copyCommand() {
    var text = refs.command.textContent;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        refs.copy.textContent = "Copied";
        window.setTimeout(function () {
          refs.copy.textContent = "Copy";
        }, 1400);
      });
      return;
    }
    window.prompt("Copy this command:", text);
  }

  refs.choices.forEach(function (button) {
    button.addEventListener("click", function () {
      setTerminal(button.dataset.terminal);
    });
  });

  refs.repoPath.addEventListener("input", function () {
    state.repoPath = refs.repoPath.value;
    refs.command.textContent = installCommand();
  });

  refs.copy.addEventListener("click", copyCommand);

  refs.back.addEventListener("click", function () {
    if (state.step === 0) {
      return;
    }
    state.step -= 1;
    renderStep();
  });

  refs.next.addEventListener("click", function () {
    if (!canAdvance() || state.step >= STEPS.length - 1) {
      return;
    }
    state.step += 1;
    if (state.step === 4) {
      state.realPractice = null;
    }
    renderStep();
    if (state.step === 3) {
      refs.practiceZone.focus();
    }
  });

  refs.realYes.addEventListener("click", function () {
    state.realPractice = true;
    renderStep();
  });

  refs.realNo.addEventListener("click", function () {
    state.realPractice = false;
    renderStep();
  });

  refs.practiceZone.addEventListener("focus", function () {
    refs.practiceZone.classList.add("focused");
  });

  refs.practiceZone.addEventListener("blur", function () {
    if (!state.webPractice) {
      refs.practiceZone.classList.remove("focused");
    }
  });

  document.addEventListener("keydown", onPracticeKeydown);

  setTerminal("iterm2");
  renderStep();
})();
