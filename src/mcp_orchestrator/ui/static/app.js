const state = {
  domain: "power_bi",
  lastConfirmationId: null,
  responseProfile: "business",
  activeDetailsPanel: "execution",
  lastReportContext: null,
  leftCollapsed: localStorage.getItem("leftCollapsed") === "1",
  rightCollapsed: localStorage.getItem("rightCollapsed") !== "1",
  loadingMessageId: null,
};

const elements = {
  appShell: document.querySelector(".app-shell"),
  toggleLeftSidebar: document.querySelector("#toggleLeftSidebar"),
  toggleRightSidebar: document.querySelector("#toggleRightSidebar"),
  toastContainer: document.querySelector("#toastContainer"),
  healthStatus: document.querySelector("#healthStatus"),
  serverStatus: document.querySelector("#serverStatus"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  sendButton: document.querySelector("#sendButton"),
  messageInput: document.querySelector("#messageInput"),
  allowExecution: document.querySelector("#allowExecution"),
  responseProfile: document.querySelector("#responseProfile"),
  confirmationInput: document.querySelector("#confirmationInput"),
  confirmButton: document.querySelector("#confirmButton"),
  clearChat: document.querySelector("#clearChat"),
  lastStatus: document.querySelector("#lastStatus"),
  lastCorrelation: document.querySelector("#lastCorrelation"),
  lastConfirmation: document.querySelector("#lastConfirmation"),
  lastReport: document.querySelector("#lastReport"),
  lastInstance: document.querySelector("#lastInstance"),
  sourcesList: document.querySelector("#sourcesList"),
  traceOutput: document.querySelector("#traceOutput"),
  detailTabs: Array.from(document.querySelectorAll(".details-tab")),
  detailPanels: Array.from(document.querySelectorAll(".details-panel")),
};

const icon = (name) => `<svg class="icon"><use href="/static/icons.svg#${name}"></use></svg>`;

document.querySelectorAll(".segment").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.domain = button.dataset.domain || null;
  });
});

elements.responseProfile.addEventListener("change", () => {
  state.responseProfile = elements.responseProfile.value || "business";
});

elements.detailTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    state.activeDetailsPanel = tab.dataset.panel || "execution";
    updateDetailsPanelVisibility();
  });
});

elements.toggleLeftSidebar.addEventListener("click", () => {
  state.leftCollapsed = !state.leftCollapsed;
  localStorage.setItem("leftCollapsed", state.leftCollapsed ? "1" : "0");
  applySidebarState();
});

elements.toggleRightSidebar.addEventListener("click", () => {
  state.rightCollapsed = !state.rightCollapsed;
  localStorage.setItem("rightCollapsed", state.rightCollapsed ? "1" : "0");
  applySidebarState();
});

elements.clearChat.addEventListener("click", () => {
  elements.messages.innerHTML = "";
  updateDetails(null);
  pushToast("Conversa limpa.", "info");
});

elements.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = elements.messageInput.value.trim();
  if (!message) return;
  elements.messageInput.value = "";
  appendMessage("user", message);
  await sendChat(message);
});

elements.confirmButton.addEventListener("click", async () => {
  const confirmationId = elements.confirmationInput.value.trim() || state.lastConfirmationId;
  if (!confirmationId) return;
  appendMessage("user", `Executar confirmação ${confirmationId}`);
  await executeConfirmation(confirmationId);
});

async function boot() {
  applySidebarState();
  await Promise.all([loadHealth(), loadServers()]);
  updateDetailsPanelVisibility();
  appendMessage("assistant", "Pronto. Escolha Power BI, Postgres ou Auto e envie uma pergunta.");
}

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    elements.healthStatus.textContent = data.status === "ok" ? "online" : "indisponível";
  } catch {
    elements.healthStatus.textContent = "offline";
  }
}

async function loadServers() {
  try {
    const response = await fetch("/mcp-servers/status");
    const data = await response.json();
    const servers = data.servers || [];
    elements.serverStatus.innerHTML = servers.length
      ? servers.map(serverStatusTemplate).join("")
      : `<div class="status-item"><span>Nenhum servidor</span></div>`;
  } catch {
    elements.serverStatus.innerHTML = `<div class="status-item"><span>Erro ao carregar</span></div>`;
  }
}

function serverStatusTemplate(server) {
  return `<div class="status-item"><span>${escapeHtml(server.name)}</span><span class="dot" title="${escapeHtml(server.kind)}"></span></div>`;
}

async function sendChat(message) {
  setBusy(true);
  pushToast("Analisando pergunta...", "info");
  state.loadingMessageId = appendLoadingMessage();

  const metadata = {};
  const confirmationId = elements.confirmationInput.value.trim();
  if (elements.allowExecution.checked) metadata.allow_execution = true;
  metadata.response_profile = state.responseProfile;
  if (confirmationId) metadata.confirmation_id = confirmationId;

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        domain_hint: state.domain,
        tags: state.domain ? [state.domain] : [],
        metadata,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Falha no chat.");
    removeLoadingMessage(state.loadingMessageId);
    state.loadingMessageId = null;
    handleChatResponse(data);
    pushToast("Resposta pronta.", "success");
  } catch (error) {
    removeLoadingMessage(state.loadingMessageId);
    state.loadingMessageId = null;
    appendMessage("assistant error", error.message || "Erro inesperado.");
    pushToast("Falha ao consultar.", "error");
  } finally {
    setBusy(false);
  }
}

async function executeConfirmation(confirmationId) {
  setBusy(true);
  pushToast("Executando confirmação...", "info");
  try {
    const response = await fetch(`/chat/confirmations/${encodeURIComponent(confirmationId)}/execute`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Falha na confirmação.");
    handleChatResponse(data);
    elements.allowExecution.checked = false;
    pushToast("Confirmação executada.", "success");
  } catch (error) {
    appendMessage("assistant error", error.message || "Erro inesperado.");
    pushToast("Falha ao executar confirmação.", "error");
  } finally {
    setBusy(false);
  }
}

function handleChatResponse(data) {
  appendMessage("assistant", data.message || "Sem resposta.", data.presentation || null);
  const orchestration = data.orchestration || {};
  const effectiveConfirmationId = data.confirmation_id || orchestration.confirmation_id || null;
  state.lastConfirmationId = effectiveConfirmationId;
  if (state.lastConfirmationId) elements.confirmationInput.value = state.lastConfirmationId;
  elements.confirmButton.disabled = !state.lastConfirmationId;
  updateDetails(orchestration, data.presentation || null, effectiveConfirmationId);
}

function appendMessage(role, text, presentation = null) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  if (role.startsWith("assistant") && presentation && typeof presentation === "object") {
    const rendered = renderAssistantStructuredMessage(text, presentation);
    item.innerHTML = rendered || renderMarkdownLite(text);
  } else {
    item.innerHTML = role.startsWith("assistant") ? renderMarkdownLite(text) : escapeHtml(text);
  }
  elements.messages.appendChild(item);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return item.dataset.messageId || null;
}

function appendLoadingMessage() {
  const id = `loading-${Date.now()}`;
  const item = document.createElement("div");
  item.className = "message assistant loading";
  item.dataset.messageId = id;
  item.innerHTML = `<div class="loading-line">${icon("loader")}<span>Analisando</span><span class="dot-typing"><span></span><span></span><span></span></span></div>`;
  elements.messages.appendChild(item);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return id;
}

function removeLoadingMessage(id) {
  if (!id) return;
  const node = elements.messages.querySelector(`[data-message-id="${id}"]`);
  if (node) node.remove();
}

function updateDetails(orchestration, presentation = null, effectiveConfirmationId = null) {
  if (!orchestration) {
    elements.lastStatus.textContent = "-";
    elements.lastCorrelation.textContent = "-";
    elements.lastConfirmation.textContent = "-";
    elements.lastReport.textContent = "-";
    elements.lastInstance.textContent = "-";
    elements.sourcesList.innerHTML = "";
    elements.traceOutput.innerHTML = "Aguardando primeira mensagem.";
    state.lastConfirmationId = null;
    state.lastReportContext = null;
    elements.confirmButton.disabled = true;
    updateDetailsPanelVisibility();
    return;
  }

  elements.lastStatus.textContent = orchestration.status || "-";
  elements.lastCorrelation.textContent = orchestration.correlation_id || "-";
  elements.lastConfirmation.textContent = effectiveConfirmationId || orchestration.confirmation_id || "-";

  const reportContext = resolveReportContext(orchestration, presentation);
  elements.lastReport.textContent = reportContext?.title || "-";
  elements.lastInstance.textContent = reportContext?.process ? `${reportContext.process}${reportContext.port ? `:${reportContext.port}` : ""}` : "-";

  const sources = orchestration.sources_used || [];
  elements.sourcesList.innerHTML = sources.length ? sources.map((source) => `<li>${escapeHtml(source)}</li>`).join("") : "<li>Sem fontes.</li>";

  const sections = orchestration.debug?.execution_trace_sections;
  const rawTrace = orchestration.debug?.execution_trace_raw || orchestration.debug?.orchestration_trace || orchestration.mcp_trace || {};
  elements.traceOutput.innerHTML = sections && typeof sections === "object"
    ? renderTraceSections(sections, rawTrace)
    : `<pre>${escapeHtml(JSON.stringify(rawTrace, null, 2))}</pre>`;
  updateDetailsPanelVisibility();
}

function setBusy(isBusy) {
  const sendText = elements.sendButton.querySelector("span");
  if (sendText) sendText.textContent = isBusy ? "Enviando..." : "Enviar";
  elements.chatForm.querySelectorAll("button, textarea").forEach((control) => {
    if (control.id === "confirmButton") {
      control.disabled = isBusy || !state.lastConfirmationId;
      return;
    }
    control.disabled = isBusy;
  });
}

function pushToast(message, type = "info") {
  const iconName = type === "success" ? "check-circle" : type === "error" ? "alert-circle" : "info";
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <div class="toast-content">${icon(iconName)}<span>${escapeHtml(message)}</span></div>
    <button type="button" aria-label="Fechar">${icon("x")}</button>
  `;
  const button = toast.querySelector("button");
  button.addEventListener("click", () => toast.remove());
  elements.toastContainer.appendChild(toast);
  const timeoutMs = type === "error" ? 5000 : 3500;
  setTimeout(() => {
    toast.classList.add("hide");
    setTimeout(() => toast.remove(), 220);
  }, timeoutMs);
}

function renderAssistantStructuredMessage(fallbackText, presentation) {
  const metric = presentation.primary_metric_name;
  const value = presentation.primary_value;
  if (!metric || value === null || value === undefined || value === "") return null;

  const lines = [];
  const period = presentation.period_label ? ` (${escapeHtml(presentation.period_label)})` : "";
  lines.push(`<div class="metric-line"><span class="metric-name">${escapeHtml(metric)}${period}</span><span class="metric-value">${escapeHtml(value)}</span></div>`);

  if (presentation.comparison_value) lines.push(`<div class="metric-subline">Comparação: ${escapeHtml(presentation.comparison_value)}</div>`);
  if (presentation.delta_value || presentation.delta_percent) {
    const deltaParts = [presentation.delta_value, presentation.delta_percent].filter(Boolean).map((v) => escapeHtml(v));
    lines.push(`<div class="metric-subline">Variação: ${deltaParts.join(" ")}</div>`);
  }

  lines.push(`<hr class="metric-separator">`);
  if (presentation.insight_summary) lines.push(`<div class="metric-note">${escapeHtml(presentation.insight_summary)}</div>`);
  if (presentation.recommended_next_step) lines.push(`<div class="metric-note"><strong>Próximo passo:</strong> ${escapeHtml(presentation.recommended_next_step)}</div>`);

  if (Array.isArray(presentation.reasoning_summary) && presentation.reasoning_summary.length) {
    const items = presentation.reasoning_summary.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    lines.push(`<details class="reasoning"><summary>Como pensei</summary><ul>${items}</ul></details>`);
  }

  const cleanFallback = (fallbackText || "").trim();
  if (cleanFallback && cleanFallback.indexOf(":") === -1 && !presentation.insight_summary) {
    lines.push(`<div class="metric-note">${escapeHtml(cleanFallback)}</div>`);
  }
  return lines.join("");
}

function renderMarkdownLite(text) {
  const safe = escapeHtml(text || "");
  return safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/^---$/gm, "<hr>").replace(/\n/g, "<br>");
}

function resolveReportContext(orchestration, presentation) {
  const presentationContext = presentation?.report_context;
  if (presentationContext?.title || presentationContext?.process || presentationContext?.port) {
    state.lastReportContext = presentationContext;
    return presentationContext;
  }

  const connectionContext = orchestration?.structured_data?.power_bi?.connection;
  if (connectionContext?.parentWindowTitle || connectionContext?.parentProcessName || connectionContext?.port) {
    const normalized = {
      title: connectionContext.parentWindowTitle || null,
      process: connectionContext.parentProcessName || null,
      port: connectionContext.port || null,
    };
    state.lastReportContext = normalized;
    return normalized;
  }
  return state.lastReportContext || {};
}

function updateDetailsPanelVisibility() {
  elements.detailTabs.forEach((tab) => {
    const isActive = (tab.dataset.panel || "execution") === state.activeDetailsPanel;
    tab.classList.toggle("active", isActive);
  });
  elements.detailPanels.forEach((panel) => {
    const isActive = (panel.dataset.panel || "execution") === state.activeDetailsPanel;
    panel.classList.toggle("active", isActive);
  });
}

function renderTraceSections(sections, rawTrace) {
  const blocks = [];
  blocks.push(renderTraceSectionBlock("Executado", sections.executado || []));
  blocks.push(renderTraceSectionBlock("Validação", sections.validacao || []));
  blocks.push(renderTraceSectionBlock("Cálculo", sections.calculo || []));
  blocks.push(renderTraceSectionBlock("Resultado", sections.resultado || []));
  blocks.push(`<details><summary>JSON bruto</summary><pre>${escapeHtml(JSON.stringify(rawTrace || {}, null, 2))}</pre></details>`);
  return blocks.join("");
}

function renderTraceSectionBlock(title, entries) {
  if (!Array.isArray(entries) || !entries.length) {
    return `<section class="trace-section"><h4>${escapeHtml(title)}</h4><p>Sem dados.</p></section>`;
  }
  const items = entries.map((entry, index) => `<details ${index === 0 ? "open" : ""}><summary>Item ${index + 1}</summary><pre>${escapeHtml(JSON.stringify(entry, null, 2))}</pre></details>`).join("");
  return `<section class="trace-section"><h4>${escapeHtml(title)}</h4>${items}</section>`;
}

function applySidebarState() {
  elements.appShell.classList.toggle("left-collapsed", state.leftCollapsed);
  elements.appShell.classList.toggle("right-collapsed", state.rightCollapsed);
  elements.toggleLeftSidebar.innerHTML = state.leftCollapsed ? icon("chevrons-right") : icon("chevrons-left");
  elements.toggleRightSidebar.innerHTML = state.rightCollapsed ? icon("chevrons-left") : icon("chevrons-right");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

boot();
