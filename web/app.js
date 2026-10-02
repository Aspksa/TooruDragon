const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];

const state = {
  main: null,
  supervisor: null,
  platform: null,
  observability: null,
  tasks: [],
  events: [],
  deployments: {},
  activePage: "dashboard",
  liveSource: null,
  selectedWorkflow: null,
  latencyHistory: [],
  aiConversationId: null,
  garage: {
    employees: [],
    vehicles: [],
    summary: null,
    statements: [],
    waybills: [],
    stats: null,
  },
  documents: {
    items: [],
    selectedId: null,
    selected: null,
    stats: null,
    legacyMigrationAttempted: false,
  },
  timesheet: {
    employees: [],
    calendar: null,
    summary: null,
    overtime: null,
    anomalies: [],
    customColumns: [],
  },
};

const coreNames = {
  main: ["♛","Главное ядро"],
  tooru_ai: ["🐉","Tooru/AI"],
  laboratory: ["⚗","Лаборатория"],
  home: ["⌂","Дом"],
  work: ["▣","Работа"],
  mobile: ["▯","Mobile"],
};

function api(path, options={}) {
  return fetch(path, {
    cache: "no-store",
    headers: {"Content-Type":"application/json", ...(options.headers||{})},
    ...options,
  }).then(async r => {
    const text = await r.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = {raw:text}; }
    if (!r.ok) {
      const err = new Error(data.message || data.error || `HTTP ${r.status}`);
      err.data = data;
      throw err;
    }
    return data;
  });
}

function toast(message, bad=false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.className="toast", 3200);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[c]));
}

function fmtUptime(sec) {
  sec = Number(sec || 0);
  const d = Math.floor(sec/86400);
  const h = Math.floor((sec%86400)/3600);
  const m = Math.floor((sec%3600)/60);
  return d ? `${d}д ${h}ч` : `${h}ч ${m}м`;
}

function fmtBytes(n) {
  n = Number(n || 0);
  if (!n) return "—";
  const u=["B","KB","MB","GB"];
  let i=0;
  while(n>=1024 && i<u.length-1){n/=1024;i++}
  return `${n.toFixed(i<2?0:1)} ${u[i]}`;
}

function drawLineChart(canvas, values, formatter) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(320, Math.floor(rect.width));
  const height = Number(canvas.getAttribute("height") || 150);
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  const clean = values.filter(v => Number.isFinite(v));
  if (!clean.length) {
    ctx.fillStyle = "#9ba4c0";
    ctx.font = "12px Segoe UI";
    ctx.fillText("Нет данных", 12, 24);
    return;
  }

  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = Math.max(1e-9, max - min);
  const pad = 18;

  ctx.strokeStyle = "rgba(155,164,192,.16)";
  ctx.lineWidth = 1;
  for (let i=0;i<4;i++) {
    const y = pad + (height-pad*2) * i / 3;
    ctx.beginPath(); ctx.moveTo(pad,y); ctx.lineTo(width-pad,y); ctx.stroke();
  }

  ctx.strokeStyle = "#a96cff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  clean.forEach((v,i)=>{
    const x = pad + (width-pad*2) * (clean.length===1 ? 1 : i/(clean.length-1));
    const y = height-pad - (v-min)/span*(height-pad*2);
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  });
  ctx.stroke();

  ctx.fillStyle = "#9ba4c0";
  ctx.font = "11px Segoe UI";
  ctx.fillText(formatter(max), pad, 12);
  ctx.fillText(formatter(min), pad, height-4);
}

function renderTelemetryCharts() {
  const recent = state.observability?.observability?.recent || [];
  const ram = recent.map(x=>Number(x.rss_bytes||0)/(1024*1024));
  const cpu = recent.map((x,i)=>{
    if(i===0) return 0;
    const prev = recent[i-1];
    const dt = Number(x.timestamp||0)-Number(prev.timestamp||0);
    const cpuNow = Number(x.user_cpu_seconds||0)+Number(x.system_cpu_seconds||0);
    const cpuPrev = Number(prev.user_cpu_seconds||0)+Number(prev.system_cpu_seconds||0);
    return dt>0 ? Math.max(0,(cpuNow-cpuPrev)/dt*100) : 0;
  });
  drawLineChart($("#ram-chart"), ram, v=>`${v.toFixed(1)} MB`);
  drawLineChart($("#cpu-chart"), cpu, v=>`${v.toFixed(1)}%`);
  drawLineChart($("#latency-chart"), state.latencyHistory, v=>`${v.toFixed(1)} ms`);
}

function appendConsole(role, message, isError=false) {
  const root = $("#agent-console");
  if (!root) return;
  const entry = document.createElement("div");
  entry.className = "console-entry";
  const label = document.createElement("span");
  label.className = "console-role" + (isError ? " error" : role==="SYSTEM" ? " system" : "");
  label.textContent = role;
  const text = document.createElement("span");
  text.textContent = message;
  entry.append(label, text);
  root.appendChild(entry);
  root.scrollTop = root.scrollHeight;
}

function workflowDepthMap(tasks) {
  const byId = new Map(tasks.map(t=>[t.id,t]));
  const memo = new Map();
  const depth = id => {
    if(memo.has(id)) return memo.get(id);
    const t = byId.get(id);
    if(!t || !t.parent_id || !byId.has(t.parent_id)) { memo.set(id,0); return 0; }
    const value = Math.min(12, depth(t.parent_id)+1);
    memo.set(id,value);
    return value;
  };
  tasks.forEach(t=>depth(t.id));
  return memo;
}

function renderWorkflowGraph(tasks) {
  const svg = $("#workflow-graph");
  const list = $("#workflow-task-list");
  if (!svg || !list) return;
  if (!tasks.length) {
    svg.innerHTML = '<text x="30" y="50" fill="#9ba4c0">Нет задач workflow</text>';
    list.innerHTML = '<div class="empty">Нет задач</div>';
    return;
  }

  const depth = workflowDepthMap(tasks);
  const levels = new Map();
  tasks.forEach(t=>{
    const d=depth.get(t.id)||0;
    if(!levels.has(d)) levels.set(d,[]);
    levels.get(d).push(t);
  });

  const positions = new Map();
  const maxDepth = Math.max(...levels.keys());
  const width = Math.max(1000,(maxDepth+1)*230);
  const maxRows = Math.max(...[...levels.values()].map(x=>x.length));
  const height = Math.max(420,maxRows*110+80);
  svg.setAttribute("viewBox",`0 0 ${width} ${height}`);

  [...levels.entries()].forEach(([d,items])=>{
    items.forEach((t,i)=>{
      positions.set(t.id,{x:40+d*220,y:40+i*105});
    });
  });

  const edges = tasks.filter(t=>t.parent_id && positions.has(t.parent_id)).map(t=>{
    const a=positions.get(t.parent_id), b=positions.get(t.id);
    return `<path class="workflow-edge" d="M ${a.x+160} ${a.y+32} C ${a.x+190} ${a.y+32}, ${b.x-30} ${b.y+32}, ${b.x} ${b.y+32}"/>`;
  }).join("");

  const nodes = tasks.map(t=>{
    const p=positions.get(t.id);
    return `<g class="workflow-node ${escapeHtml(t.state)}" data-task-id="${escapeHtml(t.id)}" transform="translate(${p.x},${p.y})">
      <rect width="160" height="64"></rect>
      <text x="12" y="24">${escapeHtml(t.kind.slice(0,21))}</text>
      <text class="sub" x="12" y="43">${escapeHtml(t.state)} · ${escapeHtml((t.id||"").slice(0,8))}</text>
    </g>`;
  }).join("");
  svg.innerHTML = edges + nodes;

  list.innerHTML = tasks.map(t=>`<div class="stack-item" data-task-id="${escapeHtml(t.id)}">
    <strong>${escapeHtml(t.kind)}</strong>
    <div class="subtitle">${escapeHtml(t.state)} · ${escapeHtml((t.id||"").slice(0,8))}</div>
  </div>`).join("");
}

async function loadTaskTransitions(taskId) {
  try {
    const data = await api(`/api/main/api/task/transitions?task_id=${encodeURIComponent(taskId)}`);
    $("#workflow-transitions").textContent = JSON.stringify(data.transitions || [], null, 2);
  } catch(e) {
    $("#workflow-transitions").textContent = e.message;
  }
}

async function loadWorkflow() {
  try {
    const data = await api("/api/main/api/tasks?limit=200");
    state.tasks = data.tasks || [];
    const workflows = [...new Set(state.tasks.map(t=>t.workflow_id).filter(Boolean))];
    const select = $("#workflow-select");
    const current = state.selectedWorkflow && workflows.includes(state.selectedWorkflow)
      ? state.selectedWorkflow
      : workflows[0] || "";
    state.selectedWorkflow = current;
    select.innerHTML = workflows.map(id=>`<option value="${escapeHtml(id)}" ${id===current?"selected":""}>${escapeHtml(id.slice(0,12))}</option>`).join("");
    const tasks = state.tasks
      .filter(t=>t.workflow_id===current)
      .sort((a,b)=>(a.created_at||"").localeCompare(b.created_at||""));
    renderWorkflowGraph(tasks);
  } catch(e){toast(e.message,true)}
}

async function loadAudit() {
  try {
    const [history, events, consumers] = await Promise.all([
      api("/api/main/api/core/history?limit=100"),
      api("/api/main/events?limit=100"),
      api("/api/main/events/consumers"),
    ]);
    const actions = history.history || [];
    const eventItems = events.events || [];
    const consumerItems = consumers.consumers || [];
    $("#audit-core-count").textContent = actions.length;
    $("#audit-event-count").textContent = eventItems.length;
    $("#audit-dlq-count").textContent = consumers.event_fabric?.dead_letters ?? "—";
    $("#audit-gap-count").textContent = consumerItems.filter(x=>x.retention_gap).length;
    $("#audit-core-body").innerHTML = actions.map(x=>`<tr>
      <td>${escapeHtml((x.created_at||"").replace("T"," ").slice(0,19))}</td>
      <td>${escapeHtml(x.core_name)}</td>
      <td>${escapeHtml(x.action)}</td>
      <td>${x.ok ? "✓" : "✕"}</td>
      <td>${escapeHtml(x.message||"")}</td>
    </tr>`).join("") || '<tr><td colspan="5" class="empty">Нет записей</td></tr>';
    $("#audit-consumer-body").innerHTML = consumerItems.map(x=>`<tr>
      <td>${escapeHtml(x.consumer)}</td><td>${escapeHtml(x.sequence)}</td>
      <td>${escapeHtml(x.lag)}</td><td>${x.retention_gap?"⚠":"✓"}</td>
    </tr>`).join("") || '<tr><td colspan="4" class="empty">Consumers ещё не зарегистрированы</td></tr>';
  } catch(e){toast(e.message,true)}
}

function startLiveEvents() {
  if (state.liveSource) state.liveSource.close();
  const source = new EventSource("/stream/events");
  state.liveSource = source;
  const badge = $("#live-stream-badge");
  source.addEventListener("open",()=>{
    badge.textContent="LIVE";
    badge.className="status-pill online";
  });
  source.addEventListener("durable_event",event=>{
    try {
      const item=JSON.parse(event.data);
      state.events = [item, ...state.events.filter(x=>x.id!==item.id)].slice(0,100);
      if(state.activePage==="events") renderEventLog();
    } catch {}
  });
  source.addEventListener("stream_error",()=>{
    badge.textContent="LIVE DEGRADED";
    badge.className="status-pill";
  });
  source.onerror=()=>{
    badge.textContent="RECONNECTING";
    badge.className="status-pill";
  };
}

function renderEventLog() {
  $("#event-log").innerHTML = state.events.map(e => `<li>
    <div><strong>${escapeHtml(e.topic)}</strong> <span class="muted">#${escapeHtml(e.sequence)} · ${escapeHtml(e.source)}</span></div>
    <div class="muted">${escapeHtml((e.created_at||"").replace("T"," ").slice(0,19))}</div>
    <div>${escapeHtml(JSON.stringify(e.payload))}</div>
  </li>`).join("") || '<li class="empty">Событий пока нет</li>';
}

async function loadDashboard() {
  const [main, supervisor, platform, obs] = await Promise.allSettled([
    api("/api/main/api/cores"),
    api("/api/supervisor/status"),
    api("/api/main/platform"),
    api("/api/main/observability"),
  ]);
  state.main = main.status==="fulfilled" ? main.value : null;
  state.supervisor = supervisor.status==="fulfilled" ? supervisor.value : null;
  state.platform = platform.status==="fulfilled" ? platform.value : null;
  state.observability = obs.status==="fulfilled" ? obs.value : null;
  renderDashboard();
  renderCores();
  renderTelemetryCharts();
  updateConnection();
}

function healthPercent() {
  const cores = state.main?.manager?.cores || {};
  const values = Object.values(cores);
  if (!values.length) return 0;
  const online = values.filter(x=>x.online).length;
  const control = [
    state.supervisor?.status==="ok",
    state.supervisor?.gateway?.online === true,
  ];
  return Math.round((online + control.filter(Boolean).length) / (values.length + control.length) * 100);
}

function renderDashboard() {
  const cores = state.main?.manager?.cores || {};
  const online = Object.values(cores).filter(x=>x.online).length;
  const total = Object.keys(cores).length;
  const score = healthPercent();
  const obs = state.observability?.observability?.current || {};
  const latencyValues = Object.values(cores).map(x=>Number(x.latency_ms)).filter(Number.isFinite);
  const avgLatency = latencyValues.length ? latencyValues.reduce((a,b)=>a+b,0)/latencyValues.length : 0;
  state.latencyHistory.push(avgLatency);
  state.latencyHistory = state.latencyHistory.slice(-30);
  const ef = state.observability?.event_fabric || {};
  const safe = !!state.supervisor?.safe_mode;
  $("#health-score").innerHTML = `${score}<small>%</small>`;
  $("#health-text").textContent = safe ? "SAFE MODE" : (score === 100 ? "Все системы готовы" : "Есть деградация");
  $("#metric-cores").textContent = `${online}/${total}`;
  $("#metric-memory").textContent = fmtBytes(obs.rss_bytes);
  $("#metric-events").textContent = ef.events ?? "—";
  $("#metric-uptime").textContent = fmtUptime(state.supervisor?.uptime_seconds);
  $("#safe-mode-badge").textContent = safe ? "SAFE MODE ВКЛЮЧЁН" : "Safe Mode выключен";
  $("#safe-mode-badge").className = "status-pill " + (safe ? "" : "online");
  $("#deployment-count").textContent = Object.keys(state.supervisor?.deployments || {}).length;
}

function renderCores() {
  const cores = state.main?.manager?.cores || {};
  const root = $("#core-grid");
  if (!Object.keys(cores).length) {
    root.innerHTML = '<div class="empty card">Main Core недоступен</div>';
    return;
  }
  const html = Object.entries(cores).map(([key,c]) => {
    const [icon,name] = coreNames[key] || ["⚙",key];
    return `<article class="card core-card">
      <div class="core-head">
        <div class="core-title">${icon} ${escapeHtml(name)}</div>
        <span class="status-pill ${c.online?"online":""}">${c.online?"ONLINE":"OFFLINE"}</span>
      </div>
      <div class="meta">
        <div>Версия<strong>${escapeHtml(c.version||"—")}</strong></div>
        <div>Порт<strong>:${escapeHtml(c.port)}</strong></div>
        <div>PID<strong>${escapeHtml(c.pid||"—")}</strong></div>
        <div>Latency<strong>${c.latency_ms==null?"—":escapeHtml(c.latency_ms)+" ms"}</strong></div>
      </div>
      <div class="card-actions">
        <button class="btn good" data-core-action="start" data-core="${key}">Start</button>
        <button class="btn" data-core-action="restart" data-core="${key}">Restart</button>
        <button class="btn danger" data-core-action="stop" data-core="${key}">Stop</button>
      </div>
    </article>`;
  }).join("");
  root.innerHTML = html;
  const secondary = $("#core-grid-secondary");
  if (secondary) secondary.innerHTML = html;
}

async function coreAction(core, action) {
  try {
    await api("/api/supervisor/core/action", {
      method:"POST",
      body:JSON.stringify({core,action})
    });
    toast(`${core}: ${action} выполнено`);
    setTimeout(loadDashboard, 600);
  } catch (e) { toast(e.message, true); }
}

async function setSafeMode(enabled) {
  try {
    await api(`/api/supervisor/safe-mode/${enabled?"enable":"disable"}`, {
      method:"POST", body:"{}"
    });
    toast(enabled ? "Safe Mode включён" : "Safe Mode выключен");
    await loadDashboard();
  } catch(e){toast(e.message,true)}
}

async function loadTasks() {
  try {
    const data = await api("/api/main/api/tasks?limit=100");
    state.tasks = data.tasks || [];
    $("#tasks-body").innerHTML = state.tasks.map(t => `<tr>
      <td class="code">${escapeHtml(t.id?.slice(0,8))}</td>
      <td>${escapeHtml(t.kind)}</td>
      <td><span class="status-pill ${t.state==="completed"?"online":""}">${escapeHtml(t.state)}</span></td>
      <td>${escapeHtml(t.priority)}</td>
      <td>${escapeHtml(t.attempts)}/${escapeHtml(t.max_attempts)}</td>
      <td class="code">${escapeHtml(t.workflow_id?.slice(0,8))}</td>
      <td>${escapeHtml((t.created_at||"").replace("T"," ").slice(0,19))}</td>
    </tr>`).join("") || '<tr><td colspan="7" class="empty">Задач пока нет</td></tr>';
  } catch(e){toast(e.message,true)}
}

async function createTask() {
  try {
    const payload = JSON.parse($("#task-payload").value || "{}");
    const body = {
      kind: $("#task-kind").value.trim(),
      payload,
      priority:Number($("#task-priority").value||100),
      max_attempts:Number($("#task-attempts").value||3),
      required_capability:$("#task-capability").value.trim() || null,
      idempotency_key:$("#task-idempotency").value.trim() || null,
    };
    await api("/api/main/api/task/create",{method:"POST",body:JSON.stringify(body)});
    toast("Задача создана");
    await loadTasks();
  } catch(e){toast(e.message,true)}
}

async function loadEvents() {
  try {
    const data = await api("/api/main/events?limit=80");
    state.events = data.events || [];
    renderEventLog();
  } catch(e){toast(e.message,true)}
}

async function loadControlPlane() {
  try {
    const [sup, gateway, consumers] = await Promise.all([
      api("/api/supervisor/status"),
      api("/api/gateway/routes"),
      api("/api/main/events/consumers"),
    ]);
    state.supervisor = sup;
    state.deployments = sup.deployments || {};
    $("#control-json").textContent = JSON.stringify({
      supervisor:sup,
      gateway,
      consumers,
    }, null, 2);
    $("#deployments-body").innerHTML = Object.entries(state.deployments).map(([core,d])=>`<tr>
      <td>${escapeHtml(core)}</td>
      <td>${escapeHtml(d.candidate?.port)}</td>
      <td>${escapeHtml(d.candidate?.pid)}</td>
      <td>${escapeHtml(d.previous?.slot||"canonical")}</td>
      <td>
        <button class="btn" data-deployment-action="complete" data-core="${core}">Complete</button>
        <button class="btn danger" data-deployment-action="rollback" data-core="${core}">Rollback</button>
      </td>
    </tr>`).join("") || '<tr><td colspan="5" class="empty">Активных deployment нет</td></tr>';
  } catch(e){toast(e.message,true)}
}

async function deploymentAction(core, action) {
  try {
    await api(`/api/supervisor/deployment/${action}`,{
      method:"POST",body:JSON.stringify({core})
    });
    toast(`${core}: deployment ${action}`);
    await Promise.all([loadControlPlane(),loadDashboard()]);
  } catch(e){toast(e.message,true)}
}

function renderAIConversation(messages) {
  const root = $("#ai-chat-thread");
  root.innerHTML = "";
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "chat-message system";
    empty.textContent = "Новый диалог. Настройте provider в config/system.json и отправьте сообщение.";
    root.appendChild(empty);
    return;
  }
  for (const item of messages) {
    if (!["user","assistant","system"].includes(item.role)) continue;
    const box = document.createElement("div");
    box.className = "chat-message " + item.role;
    const body = document.createElement("div");
    body.textContent = item.content;
    box.appendChild(body);
    const meta = document.createElement("div");
    meta.className = "chat-meta";
    meta.textContent = [
      item.provider,
      item.model,
      item.trace_id ? "trace " + item.trace_id.slice(0,8) : null,
    ].filter(Boolean).join(" · ");
    if (meta.textContent) box.appendChild(meta);
    root.appendChild(box);
  }
  root.scrollTop = root.scrollHeight;
}

async function loadAIRuntime() {
  try {
    const [runtimeData, conversationData] = await Promise.all([
      api("/api/tooru_ai/runtime"),
      api("/api/tooru_ai/conversations?limit=50"),
    ]);
    const models = runtimeData.runtime?.models || {};
    const providers = models.providers || {};
    const providerSelect = $("#ai-provider");
    const names = Object.keys(providers);
    providerSelect.innerHTML = names.map(name => {
      const item = providers[name];
      const suffix = item.enabled && item.secret_available && item.model_configured ? "ready" : "setup";
      return `<option value="${escapeHtml(name)}" ${name===models.default_provider?"selected":""}>${escapeHtml(name)} · ${suffix}</option>`;
    }).join("") || '<option value="">provider not configured</option>';

    const ready = Object.entries(providers)
      .filter(([,item])=>item.enabled && item.secret_available && item.model_configured)
      .map(([name])=>name);
    $("#ai-runtime-status").textContent = ready.length
      ? `Model Router ready: ${ready.join(", ")} · retrieval=${runtimeData.runtime?.memory?.retrieval || "—"}`
      : "Model Router настроен, но активного provider пока нет. Включите local/openai provider в config/system.json.";

    const conversations = conversationData.conversations || [];
    const select = $("#ai-conversation");
    select.innerHTML = '<option value="">Новый диалог</option>' + conversations.map(item =>
      `<option value="${escapeHtml(item.id)}" ${item.id===state.aiConversationId?"selected":""}>${escapeHtml((item.title || item.id).slice(0,30))}</option>`
    ).join("");

    if (state.aiConversationId) {
      await loadAIConversation(state.aiConversationId);
    } else {
      renderAIConversation([]);
    }
  } catch (e) {
    $("#ai-runtime-status").textContent = "Tooru/AI runtime недоступен: " + e.message;
    renderAIConversation([]);
  }
}

async function loadAIConversation(conversationId) {
  state.aiConversationId = conversationId || null;
  if (!conversationId) {
    renderAIConversation([]);
    return;
  }
  try {
    const data = await api(`/api/tooru_ai/conversation?conversation_id=${encodeURIComponent(conversationId)}`);
    renderAIConversation(data.messages || []);
  } catch (e) {
    toast(e.message, true);
  }
}

async function sendAIChat() {
  const input = $("#ai-chat-input");
  const message = input.value.trim();
  if (!message) return;

  const body = {
    message,
    conversation_id: state.aiConversationId,
    provider: $("#ai-provider").value || null,
    model: $("#ai-model").value.trim() || null,
  };

  $("#ai-chat-send").disabled = true;
  appendConsole("CHAT", "user → " + message);
  try {
    const data = await api("/api/tooru_ai/chat", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const chat = data.chat;
    state.aiConversationId = chat.conversation_id;
    input.value = "";
    appendConsole(
      "CHAT",
      `${chat.provider}/${chat.model} → ${chat.content}`
    );
    await loadAIRuntime();
    $("#ai-conversation").value = state.aiConversationId;
  } catch (e) {
    appendConsole("ERROR", "chat: " + e.message, true);
    const details = e.data?.models;
    if (details) {
      $("#ai-runtime-status").textContent =
        "Provider недоступен: " + e.message + " · " + JSON.stringify(details);
    }
    toast(e.message, true);
  } finally {
    $("#ai-chat-send").disabled = false;
  }
}

async function saveAIMemory() {
  const input = $("#ai-memory-input");
  const content = input.value.trim();
  if (!content) return;
  try {
    const data = await api("/api/tooru_ai/memory/remember", {
      method: "POST",
      body: JSON.stringify({content, source:"web"}),
    });
    input.value = "";
    $("#ai-memory-results").textContent = JSON.stringify(data.memory, null, 2);
    appendConsole("MEMORY", "saved " + data.memory.id.slice(0,8));
    toast("Память сохранена");
  } catch (e) {
    appendConsole("ERROR", "memory: " + e.message, true);
    toast(e.message, true);
  }
}

async function searchAIMemory() {
  const query = $("#ai-memory-input").value.trim() || $("#ai-chat-input").value.trim();
  if (!query) return;
  try {
    const data = await api(`/api/tooru_ai/memory/search?q=${encodeURIComponent(query)}&limit=10`);
    $("#ai-memory-results").textContent = JSON.stringify(data.memories || [], null, 2);
  } catch (e) {
    $("#ai-memory-results").textContent = e.message;
    toast(e.message, true);
  }
}

const documentTypeLabels = {
  service_memo:"Служебная записка",
  contract:"Договор",
  invoice_offer:"Счёт-оферта",
  invoice:"Счёт",
  act:"Акт",
  order:"Приказ",
  timesheet:"Табель",
  vehicle_document:"Документ на технику",
  other:"Прочее",
};

function renderDocumentStats(stats) {
  const docs = stats?.documents || {};
  const issues = stats?.open_issues || {};
  const ingest = stats?.ingest || {};
  const failedCount = Number(ingest?.by_status?.failed || 0);
  $("#doc-metric-active").textContent = docs.active ?? 0;
  $("#doc-metric-archived").textContent = docs.archived ?? 0;
  $("#doc-metric-errors").textContent = Number(issues.error || 0) + failedCount;
  $("#doc-metric-warnings").textContent = issues.warning ?? 0;

  const failures = ingest?.recent_failures || [];
  $("#document-ingest-failure-badge").textContent = failures.length;
  $("#document-ingest-failure-badge").className = "status-pill " + (failures.length ? "" : "online");
  $("#document-ingest-failures").innerHTML = failures.map(item =>
    '<div class="document-issue error">'+
      '<div><strong>'+escapeHtml(item.filename || "Без имени")+'</strong> · '+escapeHtml(item.error_type || "error")+'</div>'+
      '<div>'+escapeHtml(item.message || "Не удалось изучить документ")+'</div>'+
      '<small>'+escapeHtml((item.created_at || "").replace("T"," ").slice(0,19))+'</small>'+
    '</div>'
  ).join("") || '<div class="empty">Неудачных загрузок нет.</div>';
}

function renderDocumentsList(items) {
  state.documents.items = items || [];
  const root = $("#documents-list");
  if (!root) return;
  root.innerHTML = state.documents.items.map(item => {
    const selected = item.id === state.documents.selectedId ? " selected" : "";
    const issueCount = Number(item.issue_count || 0);
    return '<button class="document-row'+selected+'" data-document-id="'+escapeHtml(item.id)+'">'+
      '<div class="document-row-top"><strong>'+escapeHtml(item.title)+'</strong>'+
      '<span class="status-pill '+(issueCount ? "" : "online")+'">'+escapeHtml(issueCount)+' проверок</span></div>'+
      '<div class="document-row-meta">'+
        '<span>'+escapeHtml(documentTypeLabels[item.document_type] || item.document_type)+'</span>'+
        '<span>v'+escapeHtml(item.version)+'</span>'+
        (item.document_number ? '<span>№ '+escapeHtml(item.document_number)+'</span>' : '')+
        (item.year ? '<span>'+escapeHtml(item.year)+'</span>' : '')+
      '</div>'+
      '<small>'+escapeHtml(item.archive_path || "")+'</small>'+
    '</button>';
  }).join("") || '<div class="empty">Документов пока нет.</div>';
}

function renderDocumentDetail(item) {
  state.documents.selected = item;
  state.documents.selectedId = item?.id || null;
  const empty = $("#document-empty");
  const detail = $("#document-detail");
  if (!item) {
    empty.hidden = false;
    detail.hidden = true;
    return;
  }
  empty.hidden = true;
  detail.hidden = false;
  $("#document-title").textContent = item.title || "Документ";
  $("#document-meta").textContent = [
    documentTypeLabels[item.document_type] || item.document_type,
    "v"+item.version,
    item.document_number ? "№ "+item.document_number : null,
    item.document_date,
    item.archive_path,
  ].filter(Boolean).join(" · ");
  $("#document-passport").textContent = JSON.stringify(item.passport || {}, null, 2);
  $("#document-dna").textContent = JSON.stringify(item.dna || {}, null, 2);
  $("#document-text").textContent = item.text_content || "";

  $("#document-facts").innerHTML = (item.facts || []).map(fact => {
    const p = fact.provenance || {};
    return '<div class="document-fact">'+
      '<div class="document-fact-head"><strong>'+escapeHtml(fact.fact_key)+'</strong>'+
      '<span>'+Math.round(Number(fact.confidence || 0)*100)+'%</span></div>'+
      '<div>'+escapeHtml(fact.value_text)+'</div>'+
      (p.excerpt ? '<small>'+escapeHtml(p.excerpt)+'</small>' : '')+
    '</div>';
  }).join("") || '<div class="empty">Факты не извлечены.</div>';

  $("#document-issues").innerHTML = (item.issues || []).map(issue =>
    '<div class="document-issue '+escapeHtml(issue.severity)+'">'+
      '<div><strong>'+escapeHtml(issue.severity.toUpperCase())+'</strong> · '+escapeHtml(issue.issue_type)+'</div>'+
      '<div>'+escapeHtml(issue.message)+'</div>'+
    '</div>'
  ).join("") || '<div class="empty">Тоору не нашла проблем.</div>';

  $("#document-relations").innerHTML = (item.relations || []).map(rel =>
    '<button class="stack-item document-relation" data-document-id="'+escapeHtml(rel.target_document_id)+'">'+
      '<strong>'+escapeHtml(rel.relation_type)+'</strong> · '+escapeHtml(rel.target_title || rel.target_document_id)+
      '<div class="subtitle">score '+escapeHtml(rel.score)+'</div>'+
    '</button>'
  ).join("") || '<div class="empty">Связей с другими документами пока нет.</div>';

  renderDocumentsList(state.documents.items);
}

async function loadDocuments() {
  const query = $("#documents-search")?.value.trim() || "";
  const type = $("#documents-type-filter")?.value || "";
  try {
    const statsPromise = api("/api/work/documents/stats");
    let listPromise;
    if (query) {
      listPromise = api("/api/work/documents/search?q="+encodeURIComponent(query)+"&limit=100");
    } else {
      const params = new URLSearchParams({limit:"100"});
      if (type) params.set("type", type);
      listPromise = api("/api/work/documents?"+params.toString());
    }
    const [statsData, listData] = await Promise.all([statsPromise, listPromise]);
    state.documents.stats = statsData.stats || {};
    if (
      Number(state.documents.stats.legacy_rag_documents || 0) > 0 &&
      !state.documents.legacyMigrationAttempted
    ) {
      state.documents.legacyMigrationAttempted = true;
      const migration = await api("/api/work/documents/migrate-legacy-rag", {
        method:"POST",
        body:"{}",
      });
      const result = migration.migration || {};
      toast(
        "Старый RAG объединён: " +
        Number(result.migrated || 0) + " перенесено, " +
        Number(result.duplicates || 0) + " дублей"
      );
      return loadDocuments();
    }
    renderDocumentStats(state.documents.stats);
    renderDocumentsList(listData.documents || []);
    if (state.documents.selectedId) {
      const stillVisible = (listData.documents || []).some(item=>item.id===state.documents.selectedId);
      if (!stillVisible && !query) renderDocumentDetail(null);
    }
  } catch (e) {
    toast("Документы: "+e.message, true);
  }
}

async function openDocument(documentId) {
  if (!documentId) return;
  try {
    const data = await api("/api/work/documents/get?id="+encodeURIComponent(documentId));
    renderDocumentDetail(data.document);
  } catch (e) {
    toast(e.message, true);
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
    reader.onload = () => {
      const bytes = new Uint8Array(reader.result);
      let binary = "";
      const step = 0x8000;
      for (let i=0; i<bytes.length; i+=step) {
        binary += String.fromCharCode(...bytes.subarray(i, i+step));
      }
      resolve(btoa(binary));
    };
    reader.readAsArrayBuffer(file);
  });
}

async function ingestDocumentFile() {
  const file = $("#doc-file").files?.[0];
  if (!file) {
    toast("Выберите файл", true);
    return;
  }
  if (file.size > 12_000_000) {
    toast("Файл больше 12 МБ", true);
    return;
  }
  const button = $("#doc-file-ingest");
  button.disabled = true;
  button.textContent = "Изучаю...";
  try {
    const contentBase64 = await fileToBase64(file);
    const data = await api("/api/work/documents/file-ingest", {
      method:"POST",
      body:JSON.stringify({
        filename:file.name,
        content_base64:contentBase64,
        title:$("#doc-file-title").value.trim() || null,
        document_type:$("#doc-file-type").value || null,
        source:"web_file",
      }),
    });
    $("#doc-file").value = "";
    $("#doc-file-title").value = "";
    await loadDocuments();
    await openDocument(data.document.id);
    toast(data.document.duplicate ? "Дубликат уже был изучен" : "Документ изучен");
  } catch (e) {
    toast("Документ: "+e.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Изучить файл";
  }
}

async function ingestDocumentText() {
  const text = $("#doc-text-content").value.trim();
  if (!text) {
    toast("Вставьте текст документа", true);
    return;
  }
  try {
    const data = await api("/api/work/documents/ingest", {
      method:"POST",
      body:JSON.stringify({
        title:$("#doc-text-title").value.trim() || "Документ",
        text,
        source:"web_text",
      }),
    });
    $("#doc-text-content").value = "";
    $("#doc-text-title").value = "";
    await loadDocuments();
    await openDocument(data.document.id);
    toast(data.document.duplicate ? "Дубликат уже был изучен" : "Документ изучен");
  } catch (e) {
    toast("Документ: "+e.message, true);
  }
}

async function reanalyzeDocument() {
  const id = state.documents.selectedId;
  if (!id) return;
  try {
    const data = await api("/api/work/documents/reanalyze", {
      method:"POST",
      body:JSON.stringify({document_id:id}),
    });
    await loadDocuments();
    renderDocumentDetail(data.document);
    toast("Документ переизучен");
  } catch (e) { toast(e.message, true); }
}

async function archiveDocument() {
  const id = state.documents.selectedId;
  if (!id) return;
  try {
    await api("/api/work/documents/archive", {
      method:"POST",
      body:JSON.stringify({document_id:id}),
    });
    state.documents.selectedId = null;
    renderDocumentDetail(null);
    await loadDocuments();
    toast("Документ перенесён в архив");
  } catch (e) { toast(e.message, true); }
}

async function loadAgent() {
  const id = $("#agent-id").value.trim() || "tooru_ai";
  try {
    const data = await api(`/api/main/agents/tools?agent_id=${encodeURIComponent(id)}`);
    $("#agent-tools").innerHTML = (data.tools||[]).map(t =>
      `<span class="badge">${escapeHtml(t.name)} · ${escapeHtml(t.capability)}</span>`
    ).join(" ") || '<span class="muted">Нет разрешённых tools</span>';
  } catch(e){toast(e.message,true)}
}

async function invokeAgentTool() {
  const agent = $("#agent-id").value.trim() || "tooru_ai";
  const tool = $("#tool-name").value.trim();
  try {
    const payload = JSON.parse($("#tool-payload").value || "{}");
    const data = await api("/api/main/agents/tool/invoke",{
      method:"POST",body:JSON.stringify({agent_id:agent,tool,payload})
    });
    $("#agent-result").textContent = JSON.stringify(data,null,2);
    appendConsole("TOOL", `${tool} → ${JSON.stringify(data.result)}`);
    toast("Tool выполнен");
  } catch(e){appendConsole("ERROR",e.message,true);toast(e.message,true)}
}

async function submitPlan() {
  const agent = $("#agent-id").value.trim() || "tooru_ai";
  try {
    const steps = JSON.parse($("#plan-steps").value || "[]");
    const data = await api("/api/main/agents/plan",{
      method:"POST",body:JSON.stringify({agent_id:agent,steps})
    });
    $("#agent-result").textContent = JSON.stringify(data,null,2);
    appendConsole("PLAN", `workflow=${data.plan?.workflow_id || "—"} trace=${data.plan?.trace_id || "—"}`);
    toast("План создан");
    await loadTasks();
  } catch(e){toast(e.message,true)}
}

function updateConnection() {
  const ok = !!state.main && state.supervisor?.status==="ok";
  $("#conn-dot").className = "dot" + (ok?" ok":"");
  $("#conn-text").textContent = ok ? "Control Plane подключён" : "Есть недоступные компоненты";
}


function garageMonthDefault() {
  return new Date().toISOString().slice(0,7);
}

function ensureGarageDefaults() {
  const month = $("#garage-month");
  if (month && !month.value) month.value = garageMonthDefault();
  const today = new Date().toISOString().slice(0,10);
  if ($("#garage-waybill-date") && !$("#garage-waybill-date").value) $("#garage-waybill-date").value = today;
  if ($("#garage-assignment-date") && !$("#garage-assignment-date").value) $("#garage-assignment-date").value = today;
}

function garageNumber(value, digits=2) {
  return Number(value || 0).toLocaleString("ru-RU", {
    minimumFractionDigits:0,
    maximumFractionDigits:digits,
  });
}

function renderGarageSelects() {
  const employees = state.garage.employees || [];
  const vehicles = state.garage.vehicles || [];
  const employeeOptions = employees
    .filter(item=>item.active)
    .map(item=>'<option value="'+escapeHtml(item.id)+'">'+escapeHtml(item.full_name)+' · № '+escapeHtml(item.personnel_number)+'</option>')
    .join("");
  for (const id of ["garage-driver","garage-waybill-driver"]) {
    const el = $("#"+id);
    if (!el) continue;
    const current = el.value;
    el.innerHTML = employeeOptions || '<option value="">Нет сотрудников</option>';
    if (current && employees.some(item=>item.id===current)) el.value = current;
  }

  const vehicleOptions = vehicles
    .filter(item=>item.active)
    .map(item=>'<option value="'+escapeHtml(item.id)+'">'+escapeHtml(item.registration_number)+' · '+escapeHtml([item.make,item.model].filter(Boolean).join(" "))+'</option>')
    .join("");
  for (const id of ["garage-driver-vehicle","garage-waybill-vehicle"]) {
    const el = $("#"+id);
    if (!el) continue;
    const current = el.value;
    el.innerHTML = vehicleOptions || '<option value="">Нет автомобилей</option>';
    if (current && vehicles.some(item=>item.id===current)) el.value = current;
  }
}

function renderGarageDirectory() {
  const root = $("#garage-driver-directory");
  if (!root) return;
  root.innerHTML = (state.garage.employees || []).map(item => {
    const vehicle = item.registration_number
      ? item.registration_number+" · "+[item.make,item.model].filter(Boolean).join(" ")
      : "автомобиль не привязан";
    return '<div class="garage-driver-row">'+
      '<div><strong>'+escapeHtml(item.full_name)+'</strong><small>№ '+escapeHtml(item.personnel_number)+' · '+escapeHtml(item.department || "без подразделения")+'</small></div>'+
      '<div><span>Карта</span><strong>'+escapeHtml(item.fuel_card_number || "—")+'</strong></div>'+
      '<div><span>Авто</span><strong>'+escapeHtml(vehicle)+'</strong></div>'+
    '</div>';
  }).join("") || '<div class="empty">Добавьте сотрудников в справочник.</div>';
}

function renderGarageSummary(summary) {
  const statement = summary?.statement || {};
  const waybills = summary?.waybills || {};
  $("#garage-month-statement-liters").textContent = garageNumber(statement.liters, 3);
  $("#garage-month-statement-amount").textContent = garageNumber(statement.amount, 2);
  $("#garage-month-distance").textContent = garageNumber(waybills.distance_km, 1);
  $("#garage-month-consumption").textContent = garageNumber(waybills.consumption_l, 3);
  $("#garage-month-norm").textContent = garageNumber(waybills.norm_l, 3);
  $("#garage-month-deviation").textContent = garageNumber(waybills.deviation_l, 3);

  const body = $("#garage-summary-body");
  body.innerHTML = (summary?.rows || []).map(item => {
    const diff = Number(item.statement_vs_waybill_liters || 0);
    const dev = Number(item.deviation_liters || 0);
    return '<tr>'+
      '<td><strong>'+escapeHtml(item.registration_number)+'</strong><br><span class="muted">'+escapeHtml(item.vehicle_name || "")+'</span></td>'+
      '<td>'+escapeHtml(item.full_name)+'</td>'+
      '<td>'+garageNumber(item.statement_liters,3)+'</td>'+
      '<td>'+garageNumber(item.waybill_issued_liters,3)+'</td>'+
      '<td class="'+(Math.abs(diff)>0.01?'ts-negative':'ts-positive')+'">'+garageNumber(diff,3)+'</td>'+
      '<td>'+garageNumber(item.distance_km,1)+'</td>'+
      '<td>'+garageNumber(item.consumption_liters,3)+'</td>'+
      '<td>'+garageNumber(item.norm_liters,3)+'</td>'+
      '<td class="'+(dev>0?'ts-negative':dev<0?'ts-positive':'')+'">'+garageNumber(dev,3)+'</td>'+
    '</tr>';
  }).join("") || '<tr><td colspan="9" class="empty">Нет связанных данных за месяц</td></tr>';

  const unresolved = summary?.unresolved_cards || [];
  $("#garage-unresolved-badge").textContent = unresolved.length;
  $("#garage-unresolved-badge").className = "status-pill " + (unresolved.length ? "" : "online");
  $("#garage-unresolved-list").innerHTML = unresolved.map(item =>
    '<div class="garage-unresolved-card">'+
      '<div><strong>'+escapeHtml(item.card_number)+'</strong>'+(item.holder_label?' · '+escapeHtml(item.holder_label):'')+'</div>'+
      '<div class="subtitle">'+escapeHtml(item.transactions)+' операций · '+garageNumber(item.liters,3)+' л · '+garageNumber(item.amount,2)+' ₽</div>'+
      '<small>'+escapeHtml(item.first_date)+' → '+escapeHtml(item.last_date)+'</small>'+
    '</div>'
  ).join("") || '<div class="empty">Все карты за месяц привязаны.</div>';
}

function renderGarageStatements(items) {
  $("#garage-statements-list").innerHTML = (items || []).map(item =>
    '<div class="stack-item">'+
      '<strong>'+escapeHtml(item.period_start)+' — '+escapeHtml(item.period_end)+'</strong>'+
      '<div class="subtitle">'+escapeHtml(item.original_name || "Выписка ГСМ")+'</div>'+
      '<div class="garage-statement-meta">'+
        '<span>'+escapeHtml(item.card_count)+' карт</span>'+
        '<span>'+escapeHtml(item.transaction_count)+' операций</span>'+
        '<span>'+garageNumber(item.total_liters,3)+' л</span>'+
        '<span>'+garageNumber(item.total_amount,2)+' ₽</span>'+
        '<span class="'+(Number(item.unresolved_transactions||0)?'ts-negative':'ts-positive')+'">'+escapeHtml(item.unresolved_transactions || 0)+' не привязано</span>'+
      '</div>'+
    '</div>'
  ).join("") || '<div class="empty">Выписки ГСМ ещё не загружены.</div>';
}

function renderGarageWaybills(items) {
  $("#garage-waybills-body").innerHTML = (items || []).map(item => {
    const dev = Number(item.deviation_l || 0);
    return '<tr>'+
      '<td>'+escapeHtml(item.trip_date)+'</td>'+
      '<td>'+escapeHtml(item.waybill_number || "—")+'</td>'+
      '<td>'+escapeHtml(item.registration_number)+'</td>'+
      '<td>'+escapeHtml(item.full_name)+'</td>'+
      '<td>'+garageNumber(item.distance_km,1)+'</td>'+
      '<td>'+garageNumber(item.fuel_issued_l,3)+'</td>'+
      '<td>'+garageNumber(item.actual_consumption_l,3)+'</td>'+
      '<td>'+garageNumber(item.norm_consumption_l,3)+'</td>'+
      '<td class="'+(dev>0?'ts-negative':dev<0?'ts-positive':'')+'">'+garageNumber(dev,3)+'</td>'+
    '</tr>';
  }).join("") || '<tr><td colspan="9" class="empty">Путевых листов за месяц нет</td></tr>';
}

async function loadGarage() {
  ensureGarageDefaults();
  const month = $("#garage-month")?.value || garageMonthDefault();
  try {
    const [statsData, employeeData, vehicleData, summaryData, statementData, waybillData] = await Promise.all([
      api("/api/work/garage/stats"),
      api("/api/work/garage/employees"),
      api("/api/work/garage/vehicles"),
      api("/api/work/garage/fuel/summary?month="+encodeURIComponent(month)),
      api("/api/work/garage/fuel/statements"),
      api("/api/work/garage/waybills?month="+encodeURIComponent(month)),
    ]);
    state.garage.stats = statsData.stats || {};
    state.garage.employees = employeeData.employees || [];
    state.garage.vehicles = vehicleData.vehicles || [];
    state.garage.summary = summaryData.summary || null;
    state.garage.statements = statementData.statements || [];
    state.garage.waybills = waybillData.waybills || [];

    $("#garage-metric-vehicles").textContent = state.garage.stats.vehicles ?? 0;
    $("#garage-metric-cards").textContent = state.garage.stats.active_fuel_cards ?? 0;
    $("#garage-metric-statements").textContent = state.garage.stats.fuel_statements ?? 0;
    $("#garage-metric-unresolved").textContent = state.garage.stats.unresolved_transactions ?? 0;
    renderGarageSelects();
    renderGarageDirectory();
    renderGarageSummary(state.garage.summary);
    renderGarageStatements(state.garage.statements);
    renderGarageWaybills(state.garage.waybills);
    syncGarageDriverVehicle();
  } catch (e) {
    toast("Гараж: "+e.message, true);
  }
}

function syncGarageDriverVehicle() {
  const driverId = $("#garage-waybill-driver")?.value;
  if (!driverId) return;
  const employee = (state.garage.employees || []).find(item=>item.id===driverId);
  if (employee?.vehicle_id && $("#garage-waybill-vehicle")) {
    $("#garage-waybill-vehicle").value = employee.vehicle_id;
    const vehicle = (state.garage.vehicles || []).find(item=>item.id===employee.vehicle_id);
    if (vehicle?.default_norm_l_per_100km != null && $("#garage-waybill-norm") && !$("#garage-waybill-norm").value) {
      $("#garage-waybill-norm").value = vehicle.default_norm_l_per_100km;
    }
  }
}

async function saveGarageVehicle() {
  try {
    await api("/api/work/garage/vehicle/save", {
      method:"POST",
      body:JSON.stringify({
        registration_number:$("#garage-vehicle-reg").value.trim(),
        vin:$("#garage-vehicle-vin").value.trim(),
        make:$("#garage-vehicle-make").value.trim(),
        model:$("#garage-vehicle-model").value.trim(),
        department:$("#garage-vehicle-department").value.trim(),
        fuel_type:$("#garage-vehicle-fuel-type").value,
        default_norm_l_per_100km:$("#garage-vehicle-norm").value || null,
        active:true,
      }),
    });
    $("#garage-vehicle-reg").value = "";
    $("#garage-vehicle-vin").value = "";
    $("#garage-vehicle-make").value = "";
    $("#garage-vehicle-model").value = "";
    $("#garage-vehicle-norm").value = "";
    toast("Автомобиль добавлен в гараж");
    await loadGarage();
  } catch (e) { toast(e.message, true); }
}

async function assignGarageFuelCard() {
  const employeeId = $("#garage-driver").value;
  try {
    await api("/api/work/garage/fuel-card/assign", {
      method:"POST",
      body:JSON.stringify({
        employee_id:employeeId,
        card_number:$("#garage-card-number").value.trim(),
        valid_from:$("#garage-assignment-date").value || null,
      }),
    });
    $("#garage-card-number").value = "";
    toast("Топливная карта привязана");
    await loadGarage();
  } catch (e) { toast(e.message, true); }
}

async function assignGarageVehicle() {
  try {
    await api("/api/work/garage/driver-vehicle/assign", {
      method:"POST",
      body:JSON.stringify({
        employee_id:$("#garage-driver").value,
        vehicle_id:$("#garage-driver-vehicle").value,
        valid_from:$("#garage-assignment-date").value || null,
      }),
    });
    toast("Автомобиль привязан к водителю");
    await loadGarage();
  } catch (e) { toast(e.message, true); }
}

async function saveGarageWaybill() {
  try {
    const data = await api("/api/work/garage/waybill/save", {
      method:"POST",
      body:JSON.stringify({
        trip_date:$("#garage-waybill-date").value,
        waybill_number:$("#garage-waybill-number").value.trim(),
        employee_id:$("#garage-waybill-driver").value,
        vehicle_id:$("#garage-waybill-vehicle").value,
        odometer_start:$("#garage-odo-start").value || null,
        odometer_end:$("#garage-odo-end").value || null,
        fuel_open_l:$("#garage-fuel-open").value || 0,
        fuel_issued_l:$("#garage-fuel-issued").value || 0,
        fuel_close_l:$("#garage-fuel-close").value || 0,
        norm_l_per_100km:$("#garage-waybill-norm").value || null,
        note:$("#garage-waybill-note").value.trim(),
      }),
    });
    const w = data.waybill || {};
    toast("Путевой лист: расход "+garageNumber(w.actual_consumption_l,3)+" л, отклонение "+garageNumber(w.deviation_l,3)+" л");
    $("#garage-waybill-number").value = "";
    $("#garage-odo-start").value = "";
    $("#garage-odo-end").value = "";
    $("#garage-fuel-open").value = "0";
    $("#garage-fuel-issued").value = "0";
    $("#garage-fuel-close").value = "0";
    $("#garage-waybill-note").value = "";
    await loadGarage();
  } catch (e) { toast(e.message, true); }
}

async function reconcileGarageFuel() {
  try {
    const data = await api("/api/work/garage/fuel/reconcile", {
      method:"POST",
      body:"{}",
    });
    toast("Пересвязано операций: "+Number(data.result?.linked || 0));
    await loadGarage();
  } catch (e) { toast(e.message, true); }
}

function defaultTimesheetMonth() {
  return new Date().toISOString().slice(0,7);
}

function ensureTimesheetDefaults() {
  const month = $("#timesheet-month");
  if (month && !month.value) month.value = defaultTimesheetMonth();
  const workDate = $("#ts-entry-date");
  if (workDate && !workDate.value) workDate.value = new Date().toISOString().slice(0,10);
}

function renderTimesheetMatrix(calendarData) {
  const table = $("#timesheet-matrix");
  if (!table) return;
  const days = calendarData?.days || [];
  const rows = calendarData?.rows || [];
  if (!rows.length) {
    table.innerHTML = '<tbody><tr><td class="empty">Добавьте сотрудников, чтобы появился табель.</td></tr></tbody>';
    return;
  }
  const head = '<thead><tr><th class="ts-person">Сотрудник</th>' +
    days.map(day => '<th class="'+(day.weekend?'ts-weekend':'')+'">'+escapeHtml(day.day)+'</th>').join('') +
    '</tr></thead>';
  const body = rows.map(row => {
    const person = row.employee;
    const cells = row.days.map(cell => {
      const entry = cell.entry;
      const classes = [
        'ts-cell',
        cell.weekend ? 'ts-weekend' : '',
        cell.missing ? 'ts-missing' : '',
        entry ? 'ts-filled' : '',
      ].filter(Boolean).join(' ');
      const code = entry ? (entry.status_code || entry.status || '') : (cell.missing ? '·' : '');
      const hours = entry && Number(entry.actual_hours) ? '<small>'+escapeHtml(entry.actual_hours)+'</small>' : '';
      const title = entry
        ? (entry.work_date+' · '+(entry.status_code||entry.status)+' · '+entry.actual_hours+' ч')
        : (cell.missing ? 'Нет записи за плановый день' : cell.date);
      return '<td class="'+classes+'" data-ts-cell="1" data-employee-id="'+escapeHtml(person.id)+
        '" data-work-date="'+escapeHtml(cell.date)+'" title="'+escapeHtml(title)+'"><span>'+escapeHtml(code)+'</span>'+hours+'</td>';
    }).join('');
    return '<tr><th class="ts-person"><strong>'+escapeHtml(person.full_name)+'</strong><small>№ '+escapeHtml(person.personnel_number)+'</small></th>'+cells+'</tr>';
  }).join('');
  table.innerHTML = head + '<tbody>'+body+'</tbody>';
}

function renderTimesheetSummary(summary) {
  const totals = summary?.totals || {};
  $("#ts-metric-employees").textContent = totals.employees ?? 0;
  $("#ts-metric-planned").textContent = totals.planned_hours ?? 0;
  $("#ts-metric-actual").textContent = totals.actual_hours ?? 0;
  $("#ts-metric-overtime").textContent = totals.overtime_hours ?? 0;
  $("#ts-metric-missing").textContent = totals.missing_days ?? 0;
  $("#ts-metric-anomalies").textContent = totals.anomalies ?? 0;

  const rows = summary?.employees || [];
  $("#timesheet-summary-body").innerHTML = rows.map(item => {
    const balance = Number(item.balance_hours || 0);
    return '<tr>'+
      '<td><strong>'+escapeHtml(item.employee.full_name)+'</strong><br><span class="muted">№ '+escapeHtml(item.employee.personnel_number)+'</span></td>'+
      '<td>'+escapeHtml(item.planned_norm_hours)+'</td>'+
      '<td>'+escapeHtml(item.actual_hours)+'</td>'+
      '<td class="'+(balance<0?'ts-negative':balance>0?'ts-positive':'')+'">'+escapeHtml(balance)+'</td>'+
      '<td>'+escapeHtml(item.overtime_hours)+'</td>'+
      '<td>'+escapeHtml(item.night_hours)+'</td>'+
      '<td>'+escapeHtml(item.missing_days)+'</td>'+
    '</tr>';
  }).join('') || '<tr><td colspan="7" class="empty">Нет сотрудников</td></tr>';
}

function renderTimesheetAnomalies(items) {
  $("#timesheet-anomaly-badge").textContent = items.length;
  $("#timesheet-anomaly-badge").className = "status-pill " + (items.length ? "" : "online");
  $("#timesheet-anomalies").innerHTML = items.map(item => {
    const severity = item.severity || 'info';
    return '<div class="ts-anomaly '+escapeHtml(severity)+'">'+
      '<div><strong>'+escapeHtml(item.full_name)+'</strong>'+
      (item.date ? ' · '+escapeHtml(item.date) : '')+'</div>'+
      '<div class="subtitle">'+escapeHtml(item.message || item.type)+'</div>'+
    '</div>';
  }).join('') || '<div class="empty">Тоору не нашла проблем в табеле за выбранный месяц.</div>';
}

function renderTimesheetCustomColumns(items, entry=null) {
  state.timesheet.customColumns = items || [];
  const list = $("#ts-custom-columns-list");
  if (list) {
    list.innerHTML = state.timesheet.customColumns.map(item =>
      '<div class="custom-field-chip '+(item.active?'':'inactive')+'">'+
        '<div><strong>'+escapeHtml(item.label)+'</strong><small>'+escapeHtml(item.value_type)+' · '+escapeHtml(item.key)+'</small></div>'+
        '<span>#'+escapeHtml(item.sort_order)+'</span>'+
      '</div>'
    ).join('') || '<div class="empty">Пользовательских полей пока нет.</div>';
  }
  renderTimesheetCustomEntryFields(entry);
}

function renderTimesheetCustomEntryFields(entry=null) {
  const root = $("#ts-custom-entry-fields");
  if (!root) return;
  const active = (state.timesheet.customColumns || []).filter(item=>item.active);
  const values = entry?.custom_values || {};
  root.innerHTML = active.map(item => {
    const stored = values[item.id]?.value;
    if (item.value_type === "checkbox") {
      return '<div class="field ts-custom-field"><label>'+escapeHtml(item.label)+'</label>'+
        '<label class="checkbox-field"><input type="checkbox" data-ts-custom-id="'+escapeHtml(item.id)+'" '+(stored?'checked':'')+'> <span>Да</span></label></div>';
    }
    const type = item.value_type === "number" ? "number" : "text";
    const step = item.value_type === "number" ? ' step="any"' : "";
    return '<div class="field ts-custom-field"><label>'+escapeHtml(item.label)+'</label>'+
      '<input type="'+type+'"'+step+' data-ts-custom-id="'+escapeHtml(item.id)+'" value="'+escapeHtml(stored ?? "")+'"></div>';
  }).join('') || '<div class="empty">Добавьте свои поля в конструкторе колонок.</div>';
}

function collectTimesheetCustomValues() {
  const values = {};
  document.querySelectorAll("[data-ts-custom-id]").forEach(input => {
    const id = input.dataset.tsCustomId;
    values[id] = input.type === "checkbox" ? input.checked : input.value;
  });
  return values;
}

function renderTimesheetOvertime(report) {
  const totals = report?.totals || {};
  $("#ts-ot-month-excess").textContent = totals.month_excess_hours ?? 0;
  $("#ts-ot-daily-excess").textContent = totals.daily_excess_hours ?? 0;
  $("#ts-ot-declared").textContent = totals.declared_overtime_hours ?? 0;
  $("#ts-ot-weekend").textContent = totals.weekend_hours ?? 0;
  $("#ts-ot-night").textContent = totals.night_hours ?? 0;
  $("#ts-ot-deficit").textContent = totals.deficit_hours ?? 0;
  $("#ts-overtime-note").textContent = report?.calculation_basis?.note || "";

  const rows = report?.employees || [];
  $("#timesheet-overtime-body").innerHTML = rows.map(item => {
    const balance = Number(item.balance_hours || 0);
    return '<tr>'+
      '<td><strong>'+escapeHtml(item.employee.full_name)+'</strong><br><span class="muted">№ '+escapeHtml(item.employee.personnel_number)+'</span></td>'+
      '<td>'+escapeHtml(item.norm_hours)+'</td>'+
      '<td>'+escapeHtml(item.actual_hours)+'</td>'+
      '<td class="'+(balance<0?'ts-negative':balance>0?'ts-positive':'')+'">'+escapeHtml(balance)+'</td>'+
      '<td>'+escapeHtml(item.declared_overtime_hours)+'</td>'+
      '<td>'+escapeHtml(item.daily_excess_hours)+'</td>'+
      '<td class="ts-positive">'+escapeHtml(item.month_excess_hours)+'</td>'+
      '<td>'+escapeHtml(item.weekend_hours)+'</td>'+
      '<td>'+escapeHtml(item.night_hours)+'</td>'+
      '<td class="'+(Number(item.deficit_hours)>0?'ts-negative':'')+'">'+escapeHtml(item.deficit_hours)+'</td>'+
    '</tr>';
  }).join('') || '<tr><td colspan="10" class="empty">Нет данных за выбранный месяц</td></tr>';
}

function renderTimesheetEmployees(items) {
  state.timesheet.employees = items || [];
  const select = $("#ts-entry-employee");
  if (!select) return;
  const current = select.value;
  select.innerHTML = state.timesheet.employees.map(item =>
    '<option value="'+escapeHtml(item.id)+'">№ '+escapeHtml(item.personnel_number)+' · '+escapeHtml(item.full_name)+'</option>'
  ).join('') || '<option value="">Сначала добавьте сотрудника</option>';
  if (current && state.timesheet.employees.some(item=>item.id===current)) select.value = current;
}

async function loadTimesheet() {
  ensureTimesheetDefaults();
  const month = $("#timesheet-month")?.value || defaultTimesheetMonth();
  try {
    const [employeesData, calendarData, summaryData, overtimeData, anomalyData, customData] = await Promise.all([
      api("/api/work/timesheet/employees?active=true"),
      api("/api/work/timesheet/calendar?month="+encodeURIComponent(month)),
      api("/api/work/timesheet/summary?month="+encodeURIComponent(month)),
      api("/api/work/timesheet/overtime?month="+encodeURIComponent(month)),
      api("/api/work/timesheet/anomalies?month="+encodeURIComponent(month)),
      api("/api/work/timesheet/custom-columns"),
    ]);
    renderTimesheetEmployees(employeesData.employees || []);
    state.timesheet.calendar = calendarData.calendar || null;
    state.timesheet.summary = summaryData.summary || null;
    state.timesheet.overtime = overtimeData.overtime || null;
    state.timesheet.anomalies = anomalyData.anomalies || [];
    renderTimesheetCustomColumns(customData.columns || []);
    renderTimesheetMatrix(state.timesheet.calendar);
    renderTimesheetSummary(state.timesheet.summary);
    renderTimesheetOvertime(state.timesheet.overtime);
    renderTimesheetAnomalies(state.timesheet.anomalies);
  } catch (e) {
    toast("Табель: "+e.message, true);
  }
}

async function saveTimesheetEmployee() {
  const body = {
    personnel_number: $("#ts-employee-number").value.trim(),
    full_name: $("#ts-employee-name").value.trim(),
    department: $("#ts-employee-department").value.trim(),
    position: $("#ts-employee-position").value.trim(),
    schedule_type: $("#ts-employee-schedule").value.trim() || "5/2",
    weekly_hours: Number($("#ts-employee-weekly").value || 40),
    fuel_card_number: $("#ts-employee-fuel-card").value.trim(),
    active: true,
  };
  try {
    await api("/api/work/timesheet/employee/save", {
      method:"POST",
      body:JSON.stringify(body),
    });
    $("#ts-employee-number").value = "";
    $("#ts-employee-name").value = "";
    $("#ts-employee-fuel-card").value = "";
    toast("Сотрудник добавлен в справочник");
    await loadTimesheet();
  } catch (e) {
    toast(e.message, true);
  }
}

async function saveTimesheetCustomColumn() {
  const label = $("#ts-custom-label").value.trim();
  if (!label) {
    toast("Введите название пользовательского поля", true);
    return;
  }
  try {
    await api("/api/work/timesheet/custom-column/save", {
      method:"POST",
      body:JSON.stringify({
        label,
        value_type:$("#ts-custom-type").value,
        sort_order:Number($("#ts-custom-order").value || 100),
        active:true,
      }),
    });
    $("#ts-custom-label").value = "";
    toast("Произвольное поле добавлено");
    await loadTimesheet();
  } catch (e) {
    toast(e.message, true);
  }
}

async function saveTimesheetEntry() {
  const employeeId = $("#ts-entry-employee").value;
  if (!employeeId) {
    toast("Сначала добавьте сотрудника", true);
    return;
  }
  const body = {
    employee_id: employeeId,
    work_date: $("#ts-entry-date").value,
    status: $("#ts-entry-status").value,
    planned_hours: Number($("#ts-entry-planned").value || 0),
    actual_hours: Number($("#ts-entry-actual").value || 0),
    overtime_hours: Number($("#ts-entry-overtime").value || 0),
    night_hours: Number($("#ts-entry-night").value || 0),
    note: $("#ts-entry-note").value.trim(),
    custom_values: collectTimesheetCustomValues(),
    source: "web",
  };
  try {
    await api("/api/work/timesheet/entry/save", {
      method:"POST",
      body:JSON.stringify(body),
    });
    toast("День табеля сохранён");
    await loadTimesheet();
  } catch (e) {
    toast(e.message, true);
  }
}

function openTimesheetCell(employeeId, workDate) {
  const row = state.timesheet.calendar?.rows?.find(item=>item.employee.id===employeeId);
  const cell = row?.days?.find(item=>item.date===workDate);
  if (!cell) return;
  $("#ts-entry-employee").value = employeeId;
  $("#ts-entry-date").value = workDate;
  if (cell.entry) {
    $("#ts-entry-status").value = cell.entry.status || "work";
    $("#ts-entry-planned").value = cell.entry.planned_hours ?? cell.planned_default ?? 0;
    $("#ts-entry-actual").value = cell.entry.actual_hours ?? 0;
    $("#ts-entry-overtime").value = cell.entry.overtime_hours ?? 0;
    $("#ts-entry-night").value = cell.entry.night_hours ?? 0;
    $("#ts-entry-note").value = cell.entry.note || "";
    renderTimesheetCustomEntryFields(cell.entry);
  } else {
    $("#ts-entry-status").value = "work";
    $("#ts-entry-planned").value = cell.planned_default ?? 0;
    $("#ts-entry-actual").value = cell.planned_default ?? 0;
    $("#ts-entry-overtime").value = 0;
    $("#ts-entry-night").value = 0;
    $("#ts-entry-note").value = "";
    renderTimesheetCustomEntryFields(null);
  }
}

function showPage(name) {
  state.activePage = name;
  $$(".page").forEach(p=>p.classList.toggle("active",p.dataset.page===name));
  $$(".nav button").forEach(b=>b.classList.toggle("active",b.dataset.page===name));
  const titles = {
    dashboard:["Обзор","Состояние всей системы"],
    cores:["Ядра","Управление lifecycle через External Supervisor"],
    tasks:["Задачи","Durable Workflow Engine"],
    workflow:["Workflow","Граф зависимостей durable-задач"],
    events:["События","Durable Event Fabric · live SSE"],
    agent:["Agent Console","Tool Router, Planner и execution transcript"],
    documents:["Документы Тоору","Паспорт, ДНК, версии, связи, проверки и автоматическое изучение"],
    garage:["Гараж · ГСМ","Карты, водители, автомобили, путевые листы и месячная сверка топлива"],
    timesheet:["Табель","Рабочее время, нормы, фактические часы и контроль отклонений"],
    control:["Control Plane","Supervisor, Gateway, deployments и consumers"],
    audit:["Audit","Lifecycle, events и consumer integrity"],
  };
  $("#page-title").textContent = titles[name][0];
  $("#page-subtitle").textContent = titles[name][1];
  if(name==="tasks") loadTasks();
  if(name==="workflow") loadWorkflow();
  if(name==="events") loadEvents();
  if(name==="agent") { loadAgent(); loadAIRuntime(); }
  if(name==="documents") loadDocuments();
  if(name==="garage") loadGarage();
  if(name==="timesheet") loadTimesheet();
  if(name==="control") loadControlPlane();
  if(name==="audit") loadAudit();
  if(innerWidth<760) $("#sidebar").classList.remove("open");
}

$$(".nav button").forEach(b=>b.addEventListener("click",()=>showPage(b.dataset.page)));
$("#mobile-menu").addEventListener("click",()=>$("#sidebar").classList.toggle("open"));
$("#refresh").addEventListener("click",async()=>{
  await loadDashboard();
  if(state.activePage==="tasks") await loadTasks();
  if(state.activePage==="workflow") await loadWorkflow();
  if(state.activePage==="events") await loadEvents();
  if(state.activePage==="documents") await loadDocuments();
  if(state.activePage==="garage") await loadGarage();
  if(state.activePage==="timesheet") await loadTimesheet();
  if(state.activePage==="control") await loadControlPlane();
  if(state.activePage==="audit") await loadAudit();
  toast("Данные обновлены");
});

document.addEventListener("click", event => {
  const coreButton = event.target.closest("[data-core-action]");
  if (coreButton) {
    coreAction(coreButton.dataset.core, coreButton.dataset.coreAction);
    return;
  }
  const timesheetCell = event.target.closest("[data-ts-cell]");
  if (timesheetCell) {
    openTimesheetCell(timesheetCell.dataset.employeeId, timesheetCell.dataset.workDate);
    return;
  }
  const documentRow = event.target.closest("[data-document-id]");
  if (documentRow && (documentRow.classList.contains("document-row") || documentRow.classList.contains("document-relation"))) {
    openDocument(documentRow.dataset.documentId);
    return;
  }
  const documentTab = event.target.closest("[data-document-tab]");
  if (documentTab) {
    const name = documentTab.dataset.documentTab;
    $(".document-tabs button").forEach(button=>button.classList.toggle("active", button.dataset.documentTab===name));
    $("[data-document-panel]").forEach(panel=>panel.classList.toggle("active", panel.dataset.documentPanel===name));
    return;
  }
    const deploymentButton = event.target.closest("[data-deployment-action]");
  if (deploymentButton) {
    deploymentAction(deploymentButton.dataset.core, deploymentButton.dataset.deploymentAction);
  }
});

$("#safe-mode-enable").addEventListener("click",()=>setSafeMode(true));
$("#safe-mode-disable").addEventListener("click",()=>setSafeMode(false));
$("#tasks-refresh").addEventListener("click",loadTasks);
$("#task-create").addEventListener("click",createTask);
$("#events-refresh").addEventListener("click",loadEvents);
$("#garage-refresh").addEventListener("click",loadGarage);
$("#garage-month").addEventListener("change",loadGarage);
$("#garage-reconcile").addEventListener("click",reconcileGarageFuel);
$("#garage-vehicle-save").addEventListener("click",saveGarageVehicle);
$("#garage-card-assign").addEventListener("click",assignGarageFuelCard);
$("#garage-vehicle-assign").addEventListener("click",assignGarageVehicle);
$("#garage-waybill-save").addEventListener("click",saveGarageWaybill);
$("#garage-waybill-driver").addEventListener("change",syncGarageDriverVehicle);
$("#timesheet-refresh").addEventListener("click",loadTimesheet);
$("#timesheet-month").addEventListener("change",loadTimesheet);
$("#ts-employee-save").addEventListener("click",saveTimesheetEmployee);
$("#ts-entry-save").addEventListener("click",saveTimesheetEntry);
$("#ts-custom-save").addEventListener("click",saveTimesheetCustomColumn);
$("#agent-id").addEventListener("input",loadAgent);
$("#agent-tool-invoke").addEventListener("click",invokeAgentTool);
$("#agent-plan-submit").addEventListener("click",submitPlan);
$("#ai-chat-send").addEventListener("click",sendAIChat);
$("#ai-chat-input").addEventListener("keydown",event=>{
  if((event.ctrlKey || event.metaKey) && event.key==="Enter"){
    event.preventDefault();
    sendAIChat();
  }
});
$("#ai-conversation").addEventListener("change",event=>loadAIConversation(event.target.value));
$("#ai-memory-save").addEventListener("click",saveAIMemory);
$("#ai-memory-search").addEventListener("click",searchAIMemory);
$("#documents-refresh").addEventListener("click",loadDocuments);
$("#documents-search-btn").addEventListener("click",loadDocuments);
$("#documents-search").addEventListener("keydown",event=>{
  if(event.key==="Enter") loadDocuments();
});
$("#documents-type-filter").addEventListener("change",loadDocuments);
$("#doc-file-ingest").addEventListener("click",ingestDocumentFile);
$("#doc-text-ingest").addEventListener("click",ingestDocumentText);
$("#document-reanalyze").addEventListener("click",reanalyzeDocument);
$("#document-archive").addEventListener("click",archiveDocument);
$("#control-refresh").addEventListener("click",loadControlPlane);
$("#workflow-refresh").addEventListener("click",loadWorkflow);
$("#workflow-select").addEventListener("change",event=>{
  state.selectedWorkflow=event.target.value;
  const tasks=state.tasks.filter(t=>t.workflow_id===state.selectedWorkflow);
  renderWorkflowGraph(tasks);
});
$("#workflow-graph").addEventListener("click",event=>{
  const node=event.target.closest("[data-task-id]");
  if(node) loadTaskTransitions(node.dataset.taskId);
});
$("#workflow-task-list").addEventListener("click",event=>{
  const item=event.target.closest("[data-task-id]");
  if(item) loadTaskTransitions(item.dataset.taskId);
});
$("#audit-refresh").addEventListener("click",loadAudit);
$("#agent-console-clear").addEventListener("click",()=>{$("#agent-console").innerHTML="";});

window.coreAction=coreAction;
window.setSafeMode=setSafeMode;
window.createTask=createTask;
window.deploymentAction=deploymentAction;
window.loadAgent=loadAgent;
window.invokeAgentTool=invokeAgentTool;
window.submitPlan=submitPlan;
window.loadTasks=loadTasks;
window.loadEvents=loadEvents;
window.loadControlPlane=loadControlPlane;

appendConsole("SYSTEM","Agent Console готова: Chat Runtime, Model Router, retrieval memory, Tool Router и Planner.");
loadDashboard();
startLiveEvents();
setInterval(loadDashboard, 5000);
