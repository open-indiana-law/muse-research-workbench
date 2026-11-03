import { newTurnSignal, turnFinished } from "/static/voice.js";

const form = document.getElementById("form");
const statusEl = document.getElementById("status");
const spendEl = document.getElementById("spend");
const out = document.getElementById("out");
const summary = document.getElementById("summary");
const catchEl = document.getElementById("catch");
const trace = document.getElementById("trace");
const cards = document.getElementById("cards");
const question = document.getElementById("question");
const openedSources = document.getElementById("opened-sources");
const sourceButtons = document.getElementById("source-buttons");
const sourceReader = document.getElementById("source-reader");
const sourceTitle = document.getElementById("source-title");
const sourceText = document.getElementById("source-text");
const sourceNotice = document.getElementById("source-notice");
const traceDetails = document.getElementById("trace-details");
let selectedSourceButton = null;
document.getElementById("close-source").addEventListener("click", () => {
  sourceReader.hidden = true;
  if (selectedSourceButton) {
    selectedSourceButton.setAttribute("aria-expanded", "false");
    selectedSourceButton.focus();
  }
});
let requestedMode = "auto";
question.addEventListener("input", () => { requestedMode = "auto"; });
const recordMode = new URLSearchParams(window.location.search).has("record");
// Presentation changes only scale and declutter the real interface; no model,
// source selection, research result, or progress is synthesized here.
if (new URLSearchParams(window.location.search).has("presentation")) {
  document.body.classList.add("presentation");
}
const evictionDemo = new URLSearchParams(window.location.search).get("demo") === "eviction";
if (recordMode) {
  document.body.classList.add("record");
  const clock = document.getElementById("clock");
  clock.hidden = false;
  let started = 0;
  const beats = evictionDemo ? [
    [0, "Public question"], [15, "Constitution / rules"], [40, "Code"],
    [70, "Opinions / catch"], [110, "Limits / close"], [175, "End card"],
  ] : [
    [0, "Title / problem"],
    [15, "Statute"],
    [55, "Currency"],
    [95, "Horton"],
    [145, "Close — skip bad cite if late"],
    [175, "End card"],
  ];
  function beatLabel(elapsed) {
    let label = beats[0][1];
    for (const [at, name] of beats) {
      if (elapsed >= at) {
        label = name;
      }
    }
    return label;
  }
  function renderClock() {
    if (!started) {
      return;
    }
    const elapsed = Math.floor((Date.now() - started) / 1000);
    const left = Math.max(0, 180 - elapsed);
    const minutes = String(Math.floor(left / 60));
    const seconds = String(left % 60).padStart(2, "0");
    clock.textContent = `${minutes}:${seconds} · ${beatLabel(elapsed)}`;
    clock.classList.toggle("warn", left <= 20);
  }
  let ticking = 0;
  clock.addEventListener("click", () => {
    started = Date.now();
    renderClock();
    if (!ticking) {
      ticking = window.setInterval(renderClock, 250);
    }
  });
  fetch("/warmup").catch(() => {
    /* first Ask still talks to the hosted MCP */
  });
}

async function refreshStatus() {
  const response = await fetch("/health");
  let data;
  try {
    data = await response.json();
  } catch {
    statusEl.textContent = `Request failed (HTTP ${response.status}); no completed answer received.`;
    turnFinished();
    return;
  }
  const spend = data.spend || {};
  spendEl.textContent = spend.note || "Spend ledger unavailable.";
  window.museVoiceReady = Boolean(data.voice_transcribe);
  if (recordMode) {
    statusEl.textContent = data.spark_ready
      ? "Muse Spark is available. Ask a question to begin research."
      : "Live Muse is closed. Choose the explicitly labeled rehearsal to inspect public sources.";
    return;
  }
  if (data.spark_ready) {
    statusEl.textContent = "Spark key is present. Auto mode will call Muse Spark.";
  } else {
    statusEl.textContent =
      "Live Muse is closed until credit readiness is verified. Rehearsal uses scripted text and real public-source retrieval.";
  }
}

document.querySelectorAll(".chips button").forEach((button) => {
  button.addEventListener("click", () => {
    question.value = button.dataset.q;
    requestedMode = button.dataset.mode || "auto";
    statusEl.textContent = requestedMode === "rehearsal"
      ? "Rehearsal selected: scripted answer, real public sources; no live Muse inference."
      : "Live research selected; credit gate applies.";
  });
});

// Format only two small Markdown constructs with DOM nodes. All other text
// (including raw HTML and unsupported link schemes) stays inert text.
function renderNote(text) {
  summary.replaceChildren();
  for (const block of String(text || "").split(/\n\s*\n/)) {
    const paragraph = document.createElement("p");
    const tokens = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*\n]+)\*\*/g;
    let at = 0;
    for (const match of block.matchAll(tokens)) {
      paragraph.append(document.createTextNode(block.slice(at, match.index)));
      const element = document.createElement(match[3] ? "strong" : "a");
      element.textContent = match[3] || match[1];
      if (match[2]) { element.href = match[2]; element.rel = "noreferrer"; }
      paragraph.append(element);
      at = match.index + match[0].length;
    }
    paragraph.append(document.createTextNode(block.slice(at)));
    summary.append(paragraph);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const signal = newTurnSignal();
  statusEl.textContent = "Finding unofficial sources…";
  out.hidden = true;
  sourceReader.hidden = true;
  traceDetails.open = false;
  selectedSourceButton = null;
  const payload = {
    question: question.value,
    as_of: document.getElementById("as_of").value || null,
    mode: requestedMode,
  };
  let response;
  try {
    response = await fetch("/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      statusEl.textContent = "Turn cancelled.";
      return;
    }
    statusEl.textContent = "Request failed.";
    turnFinished();
    return;
  }
  let data;
  try {
    data = await response.json();
  } catch {
    statusEl.textContent = `Request failed (HTTP ${response.status}); no completed answer received.`;
    turnFinished();
    return;
  }
  if (!response.ok) {
    statusEl.textContent = data.detail || "Request failed.";
    turnFinished();
    return;
  }
  statusEl.textContent = data.mode === "replay" ? "RECORDED MUSE RESULT · no new inference" : data.mode === "rehearsal" ? "REHEARSAL · scripted answer · real public-source retrieval · no live Muse"
    : data.spark_ready
    ? `Planner: ${data.planner}`
    : `Planner: ${data.planner} (fixture; Spark closed)`;
  renderNote(data.summary);
  sourceButtons.replaceChildren();
  const sourcesById = new Map();
  for (const source of data.opened_sources || []) {
    if (!source || typeof source.id !== "string" || typeof source.text !== "string"
        || sourcesById.has(source.id)) continue;
    sourcesById.set(source.id, source);
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.sourceId = source.id;
    button.textContent = source.title || "Retrieved source";
    button.setAttribute("aria-controls", "source-reader");
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", () => {
      const selected = sourcesById.get(button.dataset.sourceId);
      if (!selected) return;
      if (selectedSourceButton) selectedSourceButton.setAttribute("aria-expanded", "false");
      selectedSourceButton = button;
      button.setAttribute("aria-expanded", "true");
      sourceTitle.textContent = selected.title || "Retrieved source";
      sourceText.textContent = selected.text;
      const total = Number.isSafeInteger(selected.characters_total) && selected.characters_total >= 0
        ? selected.characters_total.toLocaleString("en-US") : "unknown";
      sourceNotice.textContent = selected.truncated
        ? `Truncated display · ${total} characters in retrieved source. This panel contains only the displayed portion.`
        : `Retrieved text · ${total} characters. Dated unofficial copy; verify at the official source.`;
      sourceReader.hidden = false;
      sourceTitle.focus({ preventScroll: true });
      sourceReader.scrollIntoView({ block: "nearest", behavior: "auto" });
    });
    sourceButtons.append(button);
  }
  openedSources.hidden = sourcesById.size === 0;
  if (data.catch) {
    catchEl.hidden = false;
    catchEl.textContent = data.catch;
  } else {
    catchEl.hidden = true;
  }
  if (data.quotes_ok === false) {
    statusEl.textContent += " Quote check failed.";
  }
  if (data.complete === false) statusEl.textContent += " Research incomplete.";
  cards.replaceChildren();
  for (const card of data.source_cards || []) {
    const item = document.createElement("li");
    item.className = "card";
    const title = document.createElement("strong");
    title.textContent = card.title || card.section_id || "Source";
    const meta = document.createElement("p");
    meta.textContent = [
      card.role,
      card.court,
      card.date_filed || (card.snapshot_year ? `snapshot ${card.snapshot_year}` : ""),
      card.decision_form,
      card.citability,
      card.cluster_id ? `cluster ${card.cluster_id}` : "",
      card.section_id ? `IC ${card.section_id}` : "",
      card.doc_id,
      card.page ? `page ${card.page}` : "",
      card.compiled_on ? `compiled ${card.compiled_on}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    item.append(title, meta);
    if (card.url && /^https?:\/\//i.test(card.url)) {
      const link = document.createElement("a");
      link.href = card.url;
      link.textContent = card.url;
      item.append(link);
    }
    if (card.official_url && /^https?:\/\//i.test(card.official_url)) {
      const link = document.createElement("a");
      link.href = card.official_url;
      link.textContent = "Official opinion · link checked November 2, 2026";
      item.append(link);
    }
    if (card.note) {
      const note = document.createElement("p");
      note.className = "note";
      note.textContent = card.note;
      item.append(note);
    }
    cards.append(item);
  }
  trace.replaceChildren();
  for (const step of data.steps || []) {
    const item = document.createElement("li");
    const args = document.createElement("code");
    args.textContent = `${step.tool} ${JSON.stringify(step.arguments)}`;
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(step.result, null, 2);
    item.append(args, pre);
    trace.append(item);
  }
  out.hidden = false;
  turnFinished();
});

refreshStatus().catch(() => {
  statusEl.textContent = "Local server is not reachable.";
});
