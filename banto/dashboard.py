from __future__ import annotations


DASHBOARD_HTML = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Banto Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --ink: #172026;
      --muted: #5f6b75;
      --line: #d9dee3;
      --alive: #0f7b4f;
      --down: #b42318;
      --unknown: #6a5d00;
      --focus: #1168a8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 650;
      letter-spacing: 0;
    }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 1fr) minmax(360px, 520px);
      gap: 18px;
      padding: 18px;
    }
    section {
      min-width: 0;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }
    h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 650;
      letter-spacing: 0;
    }
    button {
      min-height: 34px;
      border: 1px solid #b7c3cc;
      border-radius: 6px;
      background: #ffffff;
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      padding: 0 12px;
    }
    button.primary {
      border-color: var(--focus);
      background: var(--focus);
      color: #ffffff;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
      overflow-wrap: anywhere;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      background: #fbfcfd;
    }
    tr[role="button"] { cursor: pointer; }
    tr.selected { background: #e9f3fb; }
    .state {
      display: inline-flex;
      align-items: center;
      min-width: 76px;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }
    .state.alive { color: var(--alive); background: #e5f5ee; }
    .state.down { color: var(--down); background: #fde8e6; }
    .state.unknown { color: var(--unknown); background: #fff6c7; }
    .details {
      display: grid;
      gap: 12px;
      padding: 16px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid #b7c3cc;
      border-radius: 6px;
      color: var(--ink);
      font: inherit;
      padding: 9px 10px;
      background: #ffffff;
    }
    textarea {
      min-height: 110px;
      resize: vertical;
    }
    pre {
      min-height: 120px;
      max-height: 42vh;
      margin: 0;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #111820;
      color: #eaf2f8;
      padding: 12px;
      white-space: pre-wrap;
    }
    .muted { color: var(--muted); }
    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .inline-check {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
    }
    .inline-check input {
      width: auto;
      margin: 0;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 150px;
      gap: 10px;
    }
    @media (max-width: 860px) {
      header { align-items: flex-start; flex-direction: column; }
      main { grid-template-columns: 1fr; padding: 12px; }
      .grid { grid-template-columns: 1fr; }
      th:nth-child(3), td:nth-child(3) { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Banto Dashboard</h1>
      <div class="muted" id="summary">Loading agents...</div>
    </div>
    <div class="toolbar">
      <label class="inline-check">
        <input id="autoRefresh" type="checkbox" checked>
        Auto refresh
      </label>
      <button id="refresh" type="button">Refresh</button>
    </div>
  </header>
  <main>
    <section>
      <div class="section-head">
        <h2>Agents</h2>
        <span class="muted" id="updated"></span>
      </div>
      <table>
        <thead>
          <tr>
            <th style="width: 34%">Agent</th>
            <th style="width: 110px">State</th>
            <th>Status</th>
            <th style="width: 150px">Last heartbeat</th>
          </tr>
        </thead>
        <tbody id="agents"></tbody>
      </table>
    </section>
    <section>
      <div class="section-head">
        <h2>Context</h2>
        <span class="muted" id="selected">No agent selected</span>
      </div>
      <div class="details">
        <div class="grid">
          <label>Agent
            <select id="agentSelect"></select>
          </label>
          <label>Format
            <select id="format">
              <option value="raw">raw</option>
              <option value="summary">summary</option>
            </select>
          </label>
        </div>
        <label>Query
          <textarea id="query" placeholder="Context query"></textarea>
        </label>
        <div class="toolbar">
          <button class="primary" id="sendContext" type="button">Query context</button>
          <button id="fanoutContext" type="button">Query all agents</button>
        </div>
        <label>Cached status
          <pre id="status">{}</pre>
        </label>
        <label>Context response
          <pre id="contextResult">{}</pre>
        </label>
      </div>
    </section>
  </main>
  <script>
    const state = { agents: [], selected: null, refreshTimer: null };
    const REFRESH_INTERVAL_MS = 5000;
    const byId = (id) => document.getElementById(id);

    function pretty(value) {
      return JSON.stringify(value, null, 2);
    }

    function selectAgent(agentId) {
      state.selected = state.agents.find((agent) => agent.agent_id === agentId) || null;
      byId("selected").textContent = state.selected ? state.selected.agent_id : "No agent selected";
      byId("agentSelect").value = state.selected ? state.selected.agent_id : "";
      byId("status").textContent = pretty(state.selected || {});
      renderAgents();
    }

    function renderAgents() {
      const tbody = byId("agents");
      tbody.innerHTML = "";
      for (const agent of state.agents) {
        const row = document.createElement("tr");
        row.setAttribute("role", "button");
        row.tabIndex = 0;
        if (state.selected && state.selected.agent_id === agent.agent_id) row.classList.add("selected");
        row.innerHTML = `
          <td>${escapeHtml(agent.agent_id)}</td>
          <td><span class="state ${escapeHtml(agent.state)}">${escapeHtml(agent.state)}</span></td>
          <td>${escapeHtml(JSON.stringify(agent.status || {}))}</td>
          <td>${escapeHtml(agent.last_heartbeat_at || "")}</td>
        `;
        row.addEventListener("click", () => selectAgent(agent.agent_id));
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") selectAgent(agent.agent_id);
        });
        tbody.appendChild(row);
      }
    }

    function renderSelect() {
      const select = byId("agentSelect");
      select.innerHTML = "";
      for (const agent of state.agents) {
        const option = document.createElement("option");
        option.value = agent.agent_id;
        option.textContent = agent.agent_id;
        select.appendChild(option);
      }
      select.disabled = state.agents.length === 0;
      byId("sendContext").disabled = state.agents.length === 0;
      byId("fanoutContext").disabled = state.agents.length === 0;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    async function refreshAgents(options = {}) {
      if (!options.quiet) byId("summary").textContent = "Loading agents...";
      const response = await fetch("/agents");
      if (!response.ok) throw new Error(`GET /agents failed: ${response.status}`);
      const body = await response.json();
      state.agents = body.agents || [];
      byId("summary").textContent = `${state.agents.length} registered agent(s)`;
      byId("updated").textContent = new Date().toLocaleString();
      renderSelect();
      if (state.selected && state.agents.some((agent) => agent.agent_id === state.selected.agent_id)) {
        selectAgent(state.selected.agent_id);
      } else if (state.agents.length > 0) {
        selectAgent(state.agents[0].agent_id);
      } else {
        selectAgent("");
      }
      renderAgents();
    }

    function setAutoRefresh(enabled) {
      if (state.refreshTimer) {
        clearInterval(state.refreshTimer);
        state.refreshTimer = null;
      }
      if (!enabled) return;
      state.refreshTimer = setInterval(() => {
        refreshAgents({ quiet: true }).catch(showError);
      }, REFRESH_INTERVAL_MS);
    }

    async function querySingleContext() {
      const agentId = byId("agentSelect").value;
      const payload = { query: byId("query").value, format: byId("format").value };
      const response = await fetch(`/agents/${encodeURIComponent(agentId)}/context`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      byId("contextResult").textContent = pretty(response.ok ? body : { status: response.status, detail: body.detail });
    }

    async function queryFanoutContext() {
      const payload = {
        query: byId("query").value,
        format: byId("format").value,
        scope: state.agents.map((agent) => agent.agent_id)
      };
      const response = await fetch("/context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      byId("contextResult").textContent = pretty(response.ok ? body : { status: response.status, detail: body.detail });
    }

    byId("refresh").addEventListener("click", () => refreshAgents().catch(showError));
    byId("autoRefresh").addEventListener("change", (event) => setAutoRefresh(event.target.checked));
    byId("agentSelect").addEventListener("change", (event) => selectAgent(event.target.value));
    byId("sendContext").addEventListener("click", () => querySingleContext().catch(showError));
    byId("fanoutContext").addEventListener("click", () => queryFanoutContext().catch(showError));

    function showError(error) {
      byId("contextResult").textContent = pretty({ error: error.message });
      byId("summary").textContent = error.message;
    }

    refreshAgents().catch(showError);
    setAutoRefresh(byId("autoRefresh").checked);
  </script>
</body>
</html>
"""
