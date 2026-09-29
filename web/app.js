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
      const suffix = item.enabled && item.secret_available ? "ready" : "disabled";
      return `<option value="${escapeHtml(name)}" ${name===models.default_provider?"selected":""}>${escapeHtml(name)} · ${suffix}</option>`;
    }).join("") || '<option value="">provider not configured</option>';

    const ready = Object.entries(providers)
      .filter(([,item])=>item.enabled && item.secret_available)
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

async function loadRAGDocuments() {
  try {
    const data = await api("/api/tooru_ai/rag/documents?limit=50");
    $("#ai-rag-results").textContent = JSON.stringify(data.documents || [], null, 2);
  } catch (e) {
    $("#ai-rag-results").textContent = e.message;
  }
}

async function ingestRAGDocument() {
  const text = $("#ai-rag-text").value.trim();
  if (!text) return;
  try {
    const data = await api("/api/tooru_ai/rag/ingest", {
      method:"POST",
      body:JSON.stringify({
        text,
        title:$("#ai-rag-title").value.trim() || null,
        source:$("#ai-rag-source").value.trim() || "web",
      }),
    });
    $("#ai-rag-text").value = "";
    $("#ai-rag-results").textContent = JSON.stringify(data.document, null, 2);
    appendConsole("RAG", `indexed ${data.document.chunk_count} chunks · ${data.document.id.slice(0,8)}`);
    toast("Документ проиндексирован");
  } catch (e) {
    appendConsole("ERROR", "rag ingest: " + e.message, true);
    toast(e.message, true);
  }
}

async function searchRAGDocuments() {
  const query = $("#ai-memory-input").value.trim() || $("#ai-chat-input").value.trim();
  if (!query) return;
  try {
    const data = await api(`/api/tooru_ai/rag/search?q=${encodeURIComponent(query)}&limit=10`);
    $("#ai-rag-results").textContent = JSON.stringify(data.chunks || [], null, 2);
  } catch (e) {
    $("#ai-rag-results").textContent = e.message;
    toast(e.message, true);
  }
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
    control:["Control Plane","Supervisor, Gateway, deployments и consumers"],
    audit:["Audit","Lifecycle, events и consumer integrity"],
  };
  $("#page-title").textContent = titles[name][0];
  $("#page-subtitle").textContent = titles[name][1];
  if(name==="tasks") loadTasks();
  if(name==="workflow") loadWorkflow();
  if(name==="events") loadEvents();
  if(name==="agent") { loadAgent(); loadAIRuntime(); loadRAGDocuments(); }
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
$("#ai-rag-ingest").addEventListener("click",ingestRAGDocument);
$("#ai-rag-search").addEventListener("click",searchRAGDocuments);
$("#ai-rag-refresh").addEventListener("click",loadRAGDocuments);
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
