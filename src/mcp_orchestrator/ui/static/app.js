const state = {
  domain: "power_bi",
  lastConfirmationId: null,
};

const elements = {
  healthStatus: document.querySelector("#healthStatus"),
  serverStatus: document.querySelector("#serverStatus"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  messageInput: document.querySelector("#messageInput"),
  allowExecution: document.querySelector("#allowExecution"),
  confirmationInput: document.querySelector("#confirmationInput"),
  confirmButton: document.querySelector("#confirmButton"),
  clearChat: document.querySelector("#clearChat"),
  lastStatus: document.querySelector("#lastStatus"),
  lastCorrelation: document.querySelector("#lastCorrelation"),
  lastConfirmation: document.querySelector("#lastConfirmation"),
  sourcesList: document.querySelector("#sourcesList"),
  traceOutput: document.querySelector("#traceOutput"),
};

document.querySelectorAll(".segment").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.domain = button.dataset.domain || null;
  });
});

elements.clearChat.addEventListener("click", () => {
  elements.messages.innerHTML = "";
  updateDetails(null);
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
  appendMessage("user", `Executar confirmacao ${confirmationId}`);
  await executeConfirmation(confirmationId);
});

async function boot() {
  await Promise.all([loadHealth(), loadServers()]);
  appendMessage(
    "assistant",
    "Pronto. Escolha Power BI, Postgres ou Auto e envie uma pergunta."
  );
}

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    elements.healthStatus.textContent = data.status === "ok" ? "online" : "indisponivel";
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
      : `<div class="status-item"><span>nenhum servidor</span></div>`;
  } catch {
    elements.serverStatus.innerHTML = `<div class="status-item"><span>erro ao carregar</span></div>`;
  }
}

function serverStatusTemplate(server) {
  return `
    <div class="status-item">
      <span>${escapeHtml(server.name)}</span>
      <span class="dot" title="${escapeHtml(server.kind)}"></span>
    </div>
  `;
}

async function sendChat(message) {
  setBusy(true);
  const metadata = {};
  const confirmationId = elements.confirmationInput.value.trim();
  if (elements.allowExecution.checked) metadata.allow_execution = true;
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
    if (!response.ok) throw new Error(data.detail || "Falha no chat");
    handleChatResponse(data);
  } catch (error) {
    appendMessage("assistant error", error.message);
  } finally {
    setBusy(false);
  }
}

async function executeConfirmation(confirmationId) {
  setBusy(true);
  try {
    const response = await fetch(`/chat/confirmations/${encodeURIComponent(confirmationId)}/execute`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Falha na confirmacao");
    handleChatResponse(data);
    elements.allowExecution.checked = false;
  } catch (error) {
    appendMessage("assistant error", error.message);
  } finally {
    setBusy(false);
  }
}

function handleChatResponse(data) {
  appendMessage("assistant", data.message || "Sem resposta.");
  const orchestration = data.orchestration || {};
  state.lastConfirmationId = data.confirmation_id || orchestration.confirmation_id || null;
  if (state.lastConfirmationId) {
    elements.confirmationInput.value = state.lastConfirmationId;
  }
  elements.confirmButton.disabled = !state.lastConfirmationId;
  updateDetails(orchestration);
}

function appendMessage(role, text) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.textContent = text;
  elements.messages.appendChild(item);
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function updateDetails(orchestration) {
  if (!orchestration) {
    elements.lastStatus.textContent = "-";
    elements.lastCorrelation.textContent = "-";
    elements.lastConfirmation.textContent = "-";
    elements.sourcesList.innerHTML = "";
    elements.traceOutput.textContent = "Aguardando primeira mensagem.";
    state.lastConfirmationId = null;
    elements.confirmButton.disabled = true;
    return;
  }

  elements.lastStatus.textContent = orchestration.status || "-";
  elements.lastCorrelation.textContent = orchestration.correlation_id || "-";
  elements.lastConfirmation.textContent = orchestration.confirmation_id || "-";

  const sources = orchestration.sources_used || [];
  elements.sourcesList.innerHTML = sources.length
    ? sources.map((source) => `<li>${escapeHtml(source)}</li>`).join("")
    : "<li>sem fontes</li>";

  const trace = orchestration.debug?.orchestration_trace || orchestration.mcp_trace || {};
  elements.traceOutput.textContent = JSON.stringify(trace, null, 2);
}

function setBusy(isBusy) {
  elements.chatForm.querySelectorAll("button, textarea").forEach((control) => {
    if (control.id === "confirmButton") {
      control.disabled = isBusy || !state.lastConfirmationId;
      return;
    }
    control.disabled = isBusy;
  });
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
