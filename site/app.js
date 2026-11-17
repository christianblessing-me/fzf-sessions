"use strict";

// This is an illustrative browser demo. It never reads history or runs commands.
const sessions = [
  {
    id: "webhooks",
    title: "Fix webhook retries",
    folder: "payments-api",
    agent: "Claude",
    age: "8m",
    open: true,
    goal: "Make webhook delivery recover from temporary failures.",
    progress: "Added bounded retries and checked duplicate delivery handling.",
    next: "Review the retry timeout before merging.",
    conversation:
      "The webhook endpoint returns a timeout during bursts. Add bounded retries and keep duplicate delivery safe.",
  },
  {
    id: "dashboard",
    title: "Finish the analytics view",
    folder: "dashboard",
    agent: "Codex",
    age: "21m",
    open: true,
    goal: "Finish the project analytics view.",
    progress: "Connected the charts and added an empty state for new projects.",
    next: "Check the mobile layout.",
    conversation:
      "Connect the analytics charts to the daily metrics. New projects need a useful empty state.",
  },
  {
    id: "finder",
    title: "Resume in a new workspace",
    folder: "fzf-sessions",
    agent: "Claude",
    age: "1h",
    open: true,
    goal: "Resume a closed session in its own Herdr workspace.",
    progress: "Updated the resume flow and the shortcut help.",
    next: "Check jumping to an existing pane.",
    conversation:
      "When resuming a closed session, create a new workspace in its original folder. Keep existing sessions in their current panes.",
  },
  {
    id: "cache",
    title: "Track down the cache miss",
    folder: "search-service",
    agent: "Codex",
    age: "3h",
    open: false,
    goal: "Understand why repeated searches miss the cache.",
    progress: "Found inconsistent query normalization in the cache key.",
    next: "Add a regression case for whitespace.",
    conversation:
      "Repeated searches are missing the cache. Normalize spaces in the query before making the cache key.",
  },
  {
    id: "api",
    title: "Clean up API error messages",
    folder: "public-api",
    agent: "Claude",
    age: "5h",
    open: false,
    goal: "Make API errors easier for developers to understand.",
    progress: "Updated validation messages and kept the response shape stable.",
    next: "Review the examples in the API docs.",
    conversation:
      "Make the validation errors from our API readable. Preserve the existing error codes and response shape.",
  },
  {
    id: "docs",
    title: "Write the getting-started guide",
    folder: "docs-site",
    agent: "Codex",
    age: "1d",
    open: false,
    goal: "Help a new user get to their first working session.",
    progress: "Added the install steps and a small example project.",
    next: "Try the instructions from a clean folder.",
    conversation:
      "Write a getting-started guide with installation, one small project, and clear steps to run it.",
  },
];

const queryInput = document.querySelector("#session-query");
const list = document.querySelector("#session-list");
const finder = document.querySelector("#finder");
const preview = document.querySelector("#session-preview");
const modeButton = document.querySelector("#search-mode");
const previewButton = document.querySelector("#preview-key");
const feedback = document.querySelector("#demo-feedback");
let mode = "metadata";
let selected = 0;
let matches = [...sessions];
let showPreview = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fuzzyMatch(text, term) {
  let position = 0;
  for (const character of term) {
    position = text.indexOf(character, position);
    if (position < 0) return false;
    position += 1;
  }
  return true;
}

function updateMatches() {
  const terms = queryInput.value
    .trim()
    .toLocaleLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  matches = sessions.filter((session) => {
    const text = (
      mode === "metadata"
        ? `${session.title} ${session.folder}`
        : session.conversation
    ).toLocaleLowerCase();
    return terms.every((term) =>
      mode === "metadata" ? fuzzyMatch(text, term) : text.includes(term),
    );
  });
  selected = 0;
  feedback.textContent = "";
  render();
}

function renderPreview() {
  preview.replaceChildren();
  const session = matches[selected];
  if (!session) {
    preview.append(element("p", "", "Select a session to see its context."));
    return;
  }
  preview.append(element("h3", "", session.title));
  preview.append(element("p", "preview-path", `~/projects/${session.folder}`));
  if (mode === "content" && queryInput.value.trim()) {
    preview.append(element("h4", "", "MATCHING PASSAGE"));
    const passage = element("p");
    const terms = queryInput.value.trim().split(/\s+/).filter(Boolean);
    const escaped = terms.map((term) =>
      term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
    );
    const pattern = new RegExp(`(${escaped.join("|")})`, "gi");
    for (const part of session.conversation.split(pattern)) {
      passage.append(
        terms.some(
          (term) => term.toLocaleLowerCase() === part.toLocaleLowerCase(),
        )
          ? element("mark", "", part)
          : document.createTextNode(part),
      );
    }
    preview.append(passage);
  } else {
    for (const [heading, text] of [
      ["GOAL", session.goal],
      ["PROGRESS", session.progress],
      ["NEXT", session.next],
    ]) {
      const section = element("div", "preview-section");
      section.append(element("h4", "", heading), element("p", "", text));
      preview.append(section);
    }
  }
}

function render() {
  list.replaceChildren();
  matches.forEach((session, index) => {
    const row = element(
      "div",
      `session-row${index === selected ? " selected" : ""}`,
    );
    row.id = `example-${session.id}`;
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", String(index === selected));
    row.setAttribute(
      "aria-label",
      `${session.title}, ${session.folder}, ${session.agent}${session.open ? ", open in Herdr" : ""}`,
    );
    row.append(
      element(
        "span",
        `row-status${session.open ? " is-open" : ""}`,
        session.open ? "●" : "–",
      ),
      element("span", "row-age", session.age),
      element(
        "span",
        `row-agent ${session.agent.toLowerCase()}`,
        session.agent,
      ),
      element("span", "row-title", session.title),
      element("span", "row-directory", session.folder),
    );
    row.addEventListener("click", () => {
      selected = index;
      render();
      queryInput.focus({ preventScroll: true });
    });
    row.addEventListener("dblclick", resumeExample);
    list.append(row);
  });
  document.querySelector("#query-count").textContent =
    `${matches.length}/${sessions.length}`;
  document.querySelector("#empty-results").hidden = matches.length > 0;
  if (matches[selected]) {
    queryInput.setAttribute(
      "aria-activedescendant",
      `example-${matches[selected].id}`,
    );
  } else {
    queryInput.removeAttribute("aria-activedescendant");
  }
  renderPreview();
}

function setMode(nextMode) {
  mode = nextMode;
  modeButton.textContent =
    mode === "metadata" ? "Directory / title" : "Conversation";
  modeButton.setAttribute(
    "aria-label",
    `Switch to ${mode === "metadata" ? "conversation" : "folder and title"} search`,
  );
  queryInput.placeholder =
    mode === "metadata" ? "Find a session…" : "Search saved messages…";
  updateMatches();
}

function toggleMode() {
  setMode(mode === "metadata" ? "content" : "metadata");
}

function togglePreview() {
  showPreview = !showPreview;
  preview.hidden = !showPreview;
  finder.classList.toggle("with-preview", showPreview);
  previewButton.setAttribute("aria-pressed", String(showPreview));
}

function resumeExample() {
  const session = matches[selected];
  if (!session) return;
  feedback.textContent = session.open
    ? `Demo: jump to “${session.title}” in Herdr. No real session is opened.`
    : `Demo: resume “${session.title}” in a new workspace. No command is run.`;
}

queryInput.addEventListener("input", updateMatches);
modeButton.addEventListener("click", toggleMode);
document.querySelector("#mode-key").addEventListener("click", toggleMode);
previewButton.addEventListener("click", togglePreview);
finder.addEventListener("keydown", (event) => {
  if (event.altKey && ["s", "p"].includes(event.key.toLowerCase())) {
    event.preventDefault();
    if (event.key.toLowerCase() === "s") toggleMode();
    else togglePreview();
    return;
  }
  if (event.target !== queryInput) return;
  if (["ArrowDown", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    if (!matches.length) return;
    selected = Math.max(
      0,
      Math.min(
        matches.length - 1,
        selected + (event.key === "ArrowDown" ? 1 : -1),
      ),
    );
    render();
  } else if (event.key === "Enter") {
    event.preventDefault();
    resumeExample();
  } else if (event.key === "Escape") {
    queryInput.blur();
  }
});

const tabs = [...document.querySelectorAll("[data-tab]")];
function activateTab(tab) {
  tabs.forEach((button) => {
    const active = button === tab;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    document.querySelector(`#panel-${button.dataset.tab}`).hidden = !active;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => activateTab(tab));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    let next =
      (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
      tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    activateTab(tabs[next]);
    tabs[next].focus();
  });
});

async function copyText(text) {
  try {
    if (!navigator.clipboard) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(text);
  } catch {
    const field = element("textarea");
    field.value = text;
    field.setAttribute("aria-label", "Installation commands");
    field.style.cssText = "position:fixed;top:0;left:-9999px;";
    const previous = document.activeElement;
    document.body.append(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    previous?.focus({ preventScroll: true });
    if (!copied) throw new Error("Copy failed");
  }
}

document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    const source = document.getElementById(button.dataset.copy);
    const text = [...source.querySelectorAll("code")]
      .map((code) => code.textContent.replace(/\s+/g, " ").trim())
      .join("\n");
    const label = button.querySelector(".copy-label");
    try {
      await copyText(text);
      label.textContent = "Copied";
      document.querySelector("#copy-status").textContent =
        "Installation commands copied.";
    } catch {
      label.textContent = "Select text";
      document.querySelector("#copy-status").textContent =
        "Could not copy. Select and copy the commands manually.";
    }
    clearTimeout(button.resetLabel);
    button.resetLabel = setTimeout(() => {
      label.textContent = "Copy";
    }, 2400);
  });
});

const screenshotDialog = document.querySelector("#screenshot-dialog");
document
  .querySelector("#open-screenshot")
  .addEventListener("click", (event) => {
    if (typeof screenshotDialog.showModal !== "function") return;
    event.preventDefault();
    screenshotDialog.showModal();
  });
screenshotDialog.addEventListener("click", (event) => {
  if (event.target !== screenshotDialog) return;
  const rect = screenshotDialog.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  ) {
    screenshotDialog.close();
  }
});
render();
