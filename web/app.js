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
  root.innerHTML = Object.entries(cores).map(([key,c]) => {
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
        <button class="btn good" onclick="coreAction('${key}','start')">Start</button>
        <button class="btn" onclick="coreAction('${key}','restart')">Restart</button>
        <button class="btn danger" onclick="coreAction('${key}','stop')">Stop</button>
      </div>
    </article>`;
  }).join("");
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
    $("#event-log").innerHTML = state.events.map(e => `<li>
      <div><strong>${escapeHtml(e.topic)}</strong> <span class="muted">#${escapeHtml(e.sequence)} · ${escapeHtml(e.source)}</span></div>
      <div class="muted">${escapeHtml((e.created_at||"").replace("T"," ").slice(0,19))}</div>
      <div>${escapeHtml(JSON.stringify(e.payload))}</div>
    </li>`).join("") || '<li class="empty">Событий пока нет</li>';
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
        <button class="btn" onclick="deploymentAction('${core}','complete')">Complete</button>
        <button class="btn danger" onclick="deploymentAction('${core}','rollback')">Rollback</button>
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
    toast("Tool выполнен");
  } catch(e){toast(e.message,true)}
}

async function submitPlan() {
  const agent = $("#agent-id").value.trim() || "tooru_ai";
  try {
    const steps = JSON.parse($("#plan-steps").value || "[]");
    const data = await api("/api/main/agents/plan",{
      method:"POST",body:JSON.stringify({agent_id:agent,steps})
    });
    $("#agent-result").textContent = JSON.stringify(data,null,2);
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
    events:["События","Durable Event Fabric"],
    agent:["Агент","Capability-gated Agent Runtime"],
    control:["Control Plane","Supervisor, Gateway, deployments и consumers"],
  };
  $("#page-title").textContent = titles[name][0];
  $("#page-subtitle").textContent = titles[name][1];
  if(name==="tasks") loadTasks();
  if(name==="events") loadEvents();
  if(name==="agent") loadAgent();
  if(name==="control") loadControlPlane();
  if(innerWidth<760) $("#sidebar").classList.remove("open");
}

$$(".nav button").forEach(b=>b.addEventListener("click",()=>showPage(b.dataset.page)));
$("#mobile-menu").addEventListener("click",()=>$("#sidebar").classList.toggle("open"));
$("#refresh").addEventListener("click",async()=>{
  await loadDashboard();
  if(state.activePage==="tasks") await loadTasks();
  if(state.activePage==="events") await loadEvents();
  if(state.activePage==="control") await loadControlPlane();
  toast("Данные обновлены");
});

window.coreAction=coreAction;
window.setSafeMode=setSafeMode;
window.createTask=createTask;
window.deploymentAction=deploymentAction;
window.loadAgent=loadAgent;
window.invokeAgentTool=invokeAgentTool;
window.submitPlan=submitPlan;

loadDashboard();
setInterval(loadDashboard, 5000);
