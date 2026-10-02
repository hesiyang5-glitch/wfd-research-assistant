// WFD Coding Assistant — single-page app (no build step).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = $("#app");
let STATUS = null, POLL = null;
const WB = { filter: "all", q: "", sel: null, data: null, section: "" };
const L = (zh, en) => (LANG === "zh" ? zh : en);
const PROV = { anthropic: "Claude (Anthropic)", openai: "OpenAI", openai_compatible: "OpenAI-compatible" };
const MODE_TEXT = {
  single: ["默认（单一模型，按 model_provider）", "Default (one model, per model_provider)"],
  anthropic_only: ["仅 Claude", "Claude only"],
  openai_only: ["仅 OpenAI", "OpenAI only"],
  dual_independent: ["双模型独立编码（Claude + OpenAI）", "Dual independent coding (Claude + OpenAI)"],
  anthropic_primary_openai_review: ["Claude 主编码，OpenAI 复核", "Claude primary, OpenAI review"],
  openai_primary_anthropic_review: ["OpenAI 主编码，Claude 复核", "OpenAI primary, Claude review"],
};
const modeText = (m) => (MODE_TEXT[m] ? L(MODE_TEXT[m][0], MODE_TEXT[m][1]) : m);
const ROLE_TEXT = { primary: ["主编码", "primary"], independent: ["独立编码", "independent"], reviewer: ["复核（看过主模型结果，非独立）", "reviewer (saw primary result — not independent)"] };
const roleText = (r) => (ROLE_TEXT[r] ? L(ROLE_TEXT[r][0], ROLE_TEXT[r][1]) : (r || ""));
const COMP_BADGE = { model_agreement: "ok", value_disagreement: "bad", evidence_disagreement: "warn", one_provider_blank: "warn", invalid_provider_output: "bad", needs_human_review: "dispute", human_approved: "ok" };
const COMP_TEXT = { model_agreement: ["模型一致", "Model agreement"], value_disagreement: ["取值不一致", "Value disagreement"], evidence_disagreement: ["证据不一致", "Evidence disagreement"], one_provider_blank: ["一方为空", "One provider blank"], invalid_provider_output: ["模型输出无效", "Invalid provider output"], needs_human_review: ["需人工复核", "Needs human review"], human_approved: ["人工已确认", "Human approved"] };
const compText = (c) => (COMP_TEXT[c] ? L(COMP_TEXT[c][0], COMP_TEXT[c][1]) : c);
const CELL_TEXT = { not_run: ["未运行", "Not run"], suggested: ["建议", "Suggested"], disputed: ["有争议", "Disputed"], no_supported_value: ["无证据支持的值", "No supported value"], stopped: ["已停止", "Stopped"], failed: ["失败", "Failed"], invalid_output: ["输出无效", "Invalid output"], limit_reached: ["达到上限，未编码", "Limit reached"] };
const cellText = (st) => (CELL_TEXT[st] ? L(CELL_TEXT[st][0], CELL_TEXT[st][1]) : st);
function cellHtml(cell, row) {
  // One provider's cell. Each state has its own look so "not run", "no supported value", "stopped", "failed" and
  // "invalid output" can never be mistaken for one another or for a real value.
  const c = cell || { state: "not_run" };
  const stopNote = c.stopped_latest ? `<div><span class="cell-tag st-stopped">⏸ ${esc(L("最近一次已停止", "latest run stopped"))}</span></div>` : "";
  const roleNote = c.role === "reviewer" ? ` <span class="badge warn" title="${esc(L("看过主模型结果，非独立", "saw the primary model's result; not independent"))}">${L("复核", "review")}</span>` : "";
  if (["suggested", "disputed"].includes(c.state) && c.value) {
    return `<div class="cell-val st-${c.state}"><span class="mono">${esc(c.value.slice(0, 48))}</span>${c.state === "disputed" ? ` <span class="cell-tag st-disputed">${esc(cellText("disputed"))}</span>` : ""}${c.changed ? ` <span class="badge warn" title="${esc(L("上次", "previous") + ": " + (c.previous_value || "∅"))}">Δ</span>` : ""}${roleNote}</div>${stopNote}`;
  }
  const icon = { not_run: "—", no_supported_value: "∅", stopped: "⏸", failed: "✕", invalid_output: "⚠", limit_reached: "⛔", disputed: "≠" }[c.state] || "";
  return `<span class="cell-tag st-${esc(c.state)}">${icon} ${esc(cellText(c.state))}</span>${roleNote}${stopNote}`;
}
const availModes = () => (STATUS.modes || []).filter((m) => m.available);
function providerCostRows(e) {
  return (e.providers || []).map((p) => `<div>${esc(PROV[p.provider] || p.provider)} · ${esc(p.model)}<br><span class="small muted">${esc(roleText(p.role))}${p.reasoning_effort ? " · effort " + esc(p.reasoning_effort) : ""}</span></div>
    <div>${p.calls != null ? `${p.calls} ${L("次调用", "call(s)")}${p.calls_uncached != null ? ` (${p.calls_uncached} ${L("个需新调用", "new")})` : ""} · ` : ""}${money(p.cost_low)} – <b>${money(p.cost_high)}</b>${p.price_note ? ` <span class="badge warn" title="${esc(p.price_note)}">${L("价格需核对", "check price")}</span>` : ""}</div>`).join("");
}

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== "/api/login") { showLogin(); const e = new Error(t("login_needed")); e.login = true; throw e; }
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function showLogin(msg) {
  clearInterval(POLL); POLL = null;
  $("#userBox").innerHTML = "";
  app.innerHTML = `<div class="panel" style="max-width:420px;margin:40px auto">
    <h1>${t("login_title")}</h1><p class="sub">${t("login_sub")}</p>
    <form id="loginForm"><label for="lgName">${t("login_name")}</label><input id="lgName" autocomplete="name" required>
    <label for="lgPw">${t("login_pw")}</label><input id="lgPw" type="password" autocomplete="current-password" required>
    <div id="lgErr" class="callout bad small" ${msg ? "" : "hidden"}>${esc(msg || "")}</div>
    <button class="primary" style="margin-top:12px" type="submit">${t("login_btn")}</button></form></div>`;
  try { $("#lgName").value = localStorage.getItem("wfd_name") || ""; } catch (e) {}
  $("#loginForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("POST", "/api/login", { name: $("#lgName").value, password: $("#lgPw").value });
      try { localStorage.setItem("wfd_name", $("#lgName").value); } catch (err) {}
      route();
    } catch (err) { const b = $("#lgErr"); b.hidden = false; b.textContent = err.message; }
  };
}
async function drawUser() {
  try {
    const me = await (await fetch("/api/me")).json();
    $("#userBox").innerHTML = me.login_required && me.user ? `<span class="small" style="color:#cfd9e2">${esc(me.user)}</span> <button class="small" id="logoutBtn">${t("logout")}</button>` : "";
    if ($("#logoutBtn")) $("#logoutBtn").onclick = async () => { await api("POST", "/api/logout", {}); showLogin(); };
  } catch (e) {}
}
function toast(msg, err) {
  const d = document.createElement("div"); d.className = "toast" + (err ? " err" : ""); d.textContent = msg;
  document.body.appendChild(d); setTimeout(() => d.remove(), err ? 6000 : 2600);
}
const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleString() : "";
const money = (v) => v == null ? "?" : "$" + Number(v).toFixed(v < 1 ? 3 : 2);
function fileToB64(file) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1]); r.onerror = rej; r.readAsDataURL(file); });
}
function applyStaticText() {
  $$("[data-t]").forEach((el) => (el.textContent = t(el.dataset.t)));
  document.documentElement.lang = LANG;
}
$("#langBtn").onclick = () => { setLang(LANG === "zh" ? "en" : "zh"); applyStaticText(); route(); };

// ------------------------------------------------------------------ router
async function route() {
  clearInterval(POLL); POLL = null;
  const h = location.hash.replace(/^#/, "") || "/";
  const parts = h.split("/").filter(Boolean);
  $$("header nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === (parts[0] === "case" ? "cases" : parts[0] || "home")));
  try {
    STATUS = await api("GET", "/api/status");
    drawUser();
    if (!parts.length) return renderHome();
    if (parts[0] === "cases") return renderCases();
    if (parts[0] === "case") return renderCase(+parts[1], parts[2] || "progress");
    if (parts[0] === "schema") return renderSchema();
    if (parts[0] === "settings") return renderSettings();
    renderHome();
  } catch (e) { if (!e.login) app.innerHTML = `<div class="callout bad">${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ home
function serviceList() {
  const s = STATUS;
  const li = (ok, label, text) => `<li><span class="dot ${ok}"></span><b>${label}</b> — ${text}</li>`;
  return `<ul class="services" style="padding-left:0;list-style:none;margin:0">
    ${li(s.search_provider ? (s.search_is_test ? "warn" : "ok") : "bad", t("svc_search"), s.search_provider ? (s.search_is_test ? t("svc_test") : esc(s.search_provider)) : t("svc_none_search"))}
    ${li(s.model ? "ok" : "warn", t("svc_model"), s.model ? esc(`${s.model.provider}: ${s.model.name}`) : t("svc_none_model"))}
    ${s.providers ? li(s.providers.anthropic.configured ? "ok" : "warn", "Claude (Anthropic)", s.providers.anthropic.configured ? L("已配置", "configured") : L("未配置（ANTHROPIC_API_KEY）", "not configured (ANTHROPIC_API_KEY)")) : ""}
    ${s.providers ? li(s.providers.openai.configured ? (s.providers.openai.sdk_installed ? "ok" : "bad") : "warn", "OpenAI", s.providers.openai.configured ? esc(`${L("已配置", "configured")} · ${s.providers.openai.model}`) + (s.providers.openai.sdk_installed ? "" : L(" · 未安装 openai 软件包", " · openai package not installed")) : L("未配置（OPENAI_API_KEY）— OpenAI 选项不会显示", "not configured (OPENAI_API_KEY) — OpenAI options are hidden")) : ""}
    ${li(s.ocr_available ? "ok" : "warn", t("svc_ocr"), s.ocr_available ? "tesseract" : (LANG === "zh" ? "未安装 — 扫描页会被标记为未读取" : "not installed — scanned pages are reported as unread"))}
    ${li(s.embeddings ? "ok" : "warn", t("svc_sem"), s.embeddings ? "embeddings" : (LANG === "zh" ? "LSA 近似（非神经向量）+ BM25 关键词" : "LSA approximation (not neural) + BM25 keywords"))}
  </ul>
  <p class="small muted" style="margin-top:10px">${LANG === "zh" ? "配置方法见“设置”页。" : "How to configure: see Settings."} <a href="#/settings">→</a></p>`;
}
async function renderHome() {
  const st = STATUS.settings;
  app.innerHTML = `<div class="hero">
    <div class="panel form">
      <h1>${t("hero_title")}</h1><p class="sub">${t("hero_sub")}</p>
      <label>${t("f_name")}</label><input id="f_name" placeholder="${esc(t("f_name_ph"))}">
      <div class="grid2"><div><label>${t("f_location")}</label><input id="f_location" placeholder="${esc(t("f_location_ph"))}"></div>
      <div><label>${t("f_date")}</label><input id="f_date" placeholder="${esc(t("f_date_ph"))}"></div></div>
      <label>${t("f_aliases")}</label><input id="f_aliases" placeholder="e.g. Kerr County flood; Camp Mystic flood">
      <details style="margin-top:10px"><summary>${t("f_details")} / ${t("f_links")}</summary>
        <label>${t("f_details")}</label><textarea id="f_details"></textarea>
        <label>${t("f_links")}</label><textarea id="f_links" placeholder="https://..."></textarea></details>
      <details style="margin-top:10px"><summary>${t("f_advanced")}</summary>
        <div class="grid3">
          <div><label>${t("s_rounds")}</label><input id="s_rounds" type="number" min="0" value="${st.max_search_rounds}"></div>
          <div><label>${t("s_queries")}</label><input id="s_queries" type="number" min="1" value="${st.max_queries}"></div>
          <div><label>${t("s_fetch")}</label><input id="s_fetch" type="number" min="1" value="${st.max_fetch}"></div>
          <div><label>${t("s_pages")}</label><input id="s_pages" type="number" min="1" max="5" value="${st.pages_per_query}"></div>
          <div><label>${t("s_time")}</label><input id="s_time" type="number" min="1" value="${st.time_limit_minutes}"></div>
          <div><label>${t("s_budget")}</label><input id="s_budget" type="number" min="0" step="0.5" value="${st.budget_usd}"></div>
        </div></details>
      <div class="row" style="margin-top:16px"><button class="primary" id="startBtn">${t("start")}</button><span class="spacer"></span></div>
    </div>
    <div>
      <div class="panel"><h3 style="margin-top:0">${t("services")}</h3>${serviceList()}</div>
      <div class="panel" style="margin-top:12px" id="estBox"><h3 style="margin-top:0">${t("est_title")}</h3><div class="muted">${t("loading")}</div></div>
    </div></div>`;
  api("GET", "/api/estimate_preview").then((e) => {
    $("#estBox").innerHTML = `<h3 style="margin-top:0">${t("est_title")}</h3>
      ${STATUS.model || availModes().length > 1 ? `<div class="kv"><div>${L("编码模式", "Coding mode")}</div><div>${esc(modeText(e.mode))}</div>${(e.providers || []).length > 1 ? providerCostRows(e) : ""}<div>${LANG === "zh" ? "模型" : "Model"}</div><div>${esc(e.model)}</div>
      <div>${LANG === "zh" ? "需编码变量" : "Variables to code"}</div><div>${e.n_fields}</div>
      <div>${LANG === "zh" ? "预计模型费用" : "Est. model cost"}</div><div><b>${money(e.cost_low)} – ${money(e.cost_high)}</b></div>
      <div>${t("s_budget")}</div><div>${money(e.budget_usd)}</div>
      ${e.search_cost_max != null ? `<div>${LANG === "zh" ? "搜索费用上限（每次运行）" : "Max search cost per run"}</div><div>${money(e.search_cost_max)}</div>` : ""}</div>` : `<p>${t("svc_none_model")}</p>`}
      <p class="small muted">${t("est_note")}</p><p class="small muted">${t("search_cost_note")}</p>`;
  }).catch(() => {});
  $("#startBtn").onclick = async () => {
    const name = $("#f_name").value.trim();
    if (!name) return toast(t("f_name"), true);
    $("#startBtn").disabled = true; $("#startBtn").textContent = t("starting");
    try {
      const r = await api("POST", "/api/cases", {
        name, location: $("#f_location").value, date_text: $("#f_date").value, aliases: $("#f_aliases").value,
        details: $("#f_details").value, known_links: $("#f_links").value, start: true,
        settings: { max_search_rounds: +$("#s_rounds").value, max_queries: +$("#s_queries").value, max_fetch: +$("#s_fetch").value,
          pages_per_query: +$("#s_pages").value, time_limit_minutes: +$("#s_time").value, budget_usd: +$("#s_budget").value },
      });
      location.hash = `#/case/${r.id}/progress`;
    } catch (e) { toast(e.message, true); $("#startBtn").disabled = false; $("#startBtn").textContent = t("start"); }
  };
}

// ------------------------------------------------------------------ cases
function statusBadge(job, caseStatus) {
  if (!job) return `<span class="badge">${esc(caseStatus)}</span>`;
  const cls = { done: "ok", running: "info", queued: "info", needs_input: "warn", failed: "bad", cancelled: "" }[job.status] || "";
  return `<span class="badge ${cls}">${esc(job.status)}${job.status === "running" ? " · " + esc(t("st_" + job.stage) || job.stage) : ""}</span>`;
}
async function renderCases() {
  const rows = await api("GET", "/api/cases");
  app.innerHTML = `<h1>${t("cases_title")}</h1><div class="panel" style="padding:0">
    <table><thead><tr><th>#</th><th>${t("c_name")}</th><th>${t("c_status")}</th><th>${t("c_sources")}</th><th>${t("c_confirmed")}</th><th>${t("c_created")}</th></tr></thead>
    <tbody>${rows.map((c) => `<tr class="click" data-id="${c.id}"><td>${c.id}</td><td><b>${esc(c.name)}</b><div class="small muted">${esc(c.location)} · ${esc(c.date_text)}</div></td>
    <td>${statusBadge(c.job, c.status)}</td><td>${c.n_sources}</td><td>${c.n_confirmed}</td><td class="small">${fmtTime(c.created_at)}</td></tr>`).join("") ||
    `<tr><td colspan="6" class="muted">${t("none")}</td></tr>`}</tbody></table></div>`;
  $$("tr.click").forEach((tr) => (tr.onclick = () => (location.hash = `#/case/${tr.dataset.id}/progress`)));
  if (rows.some((c) => c.job && ["running", "queued"].includes(c.job.status))) POLL = setInterval(() => location.hash === "#/cases" && renderCases(), 4000);
}

// ------------------------------------------------------------------ case shell
async function renderCase(id, tab) {
  const c = await api("GET", `/api/cases/${id}`);
  const tabs = ["progress", "review", "sources", "searches", "export"];
  app.innerHTML = `<div class="row"><div><h1>${esc(c.name)}</h1><div class="muted">${esc(c.location)} · ${esc(c.date_text)} · case #${c.id}</div></div></div>
    <div class="tabs">${tabs.map((x) => `<a href="#/case/${id}/${x}" class="${x === tab ? "active" : ""}">${t("tab_" + x)}</a>`).join("")}</div>
    <div id="tabBody"><div class="muted">${t("loading")}</div></div>`;
  const body = $("#tabBody");
  if (tab === "progress") return tabProgress(c, body);
  if (tab === "review") return tabReview(c, body);
  if (tab === "sources") return tabSources(c, body);
  if (tab === "searches") return tabSearches(c, body);
  if (tab === "export") return tabExport(c, body);
}

// ------------------------------------------------------------------ progress
const STAGES = ["identify", "search", "fetch", "gaps", "followup", "coding", "review"];
async function tabProgress(c, body) {
  const draw = async () => {
    const j = await api("GET", `/api/cases/${c.id}/job`);
    if (!j) { body.innerHTML = `<div class="panel">${t("none")} <button class="primary" id="runBtn">${t("rerun")}</button></div>`; $("#runBtn").onclick = () => startResearch(c.id); return; }
    const cur = STAGES.indexOf(j.stage);
    const st = j.state || {};
    const cov = st.coverage;
    let needs = "";
    if (j.status === "needs_input" && st.awaiting === "identity") {
      const ident = (await api("GET", `/api/cases/${c.id}`)).identity || {};
      needs = `<div class="callout warn"><b>${t("choose_incident")}</b><p>${t("choose_help")}</p>
        ${(ident.candidates || []).map((k) => `<div class="ev"><div class="row"><b>${esc(k.year)}</b><span class="badge">${k.count} results</span><span class="spacer"></span>
        ${k.year !== "(no year)" ? `<button class="small primary" data-year="${esc(k.year)}">${LANG === "zh" ? "选择此事件" : "Choose"}</button>` : ""}</div>
        ${k.examples.map((e) => `<div class="small"><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title || e.url)}</a></div>`).join("")}</div>`).join("")}
        <button class="small" id="identAll">${LANG === "zh" ? "按我输入的信息继续" : "Continue with my input as entered"}</button></div>`;
    } else if (j.status === "needs_input" && st.awaiting === "budget") {
      const e = st.estimate || {}; const b = st.budget || {}; const ln = st.limit_needs || {};
      const needed = ln.budget_usd ? ln.budget_usd.needed : Math.ceil(((b.spent_usd || 0) + (e.cost_high || 0)) * 100) / 100;
      const others = Object.entries(ln).filter(([k]) => k !== "budget_usd");
      needs = `<div class="callout warn"><b>${t("budget_q")}</b><div class="kv" style="margin:8px 0">
        <div>${L("模式", "Mode")}</div><div>${esc(modeText(st.coding_mode || "single"))}</div>
        <div>Model</div><div>${esc(e.model)}</div>${(e.providers || []).length > 1 ? providerCostRows(e) : ""}<div>${t("calls")}</div><div>${e.calls}</div><div>${t("input_tokens")}</div><div>${(e.input_tokens || 0).toLocaleString()}</div>
        <div>${t("est_cost")}</div><div>${money(e.cost_low)} – <b>${money(e.cost_high)}</b> ${t("worst_case")}</div>
        <div>${t("case_spend")}</div><div>${money(b.spent_usd)} / ${money(b.budget_usd)}</div>
        ${Object.values(ln).map((v) => `<div>${esc(v.label)}</div><div>${esc(v.current)} → <b>${esc(v.needed)}</b></div>`).join("")}</div>
        <div class="row"><button class="primary" id="approveBtn">${others.length ? L("批准以上明确数值", "Approve the explicit values above") : `${t("approve_to")} ${money(needed)}`}</button>
        <span>${t("raise_budget")}</span><input id="newBudget" type="number" min="0" max="1000" step="0.5" style="width:100px" value="${needed}"><button id="raiseBtn">OK</button>
        <button id="manualBtn">${t("manual_only")}</button></div>
        <p class="small muted">${t("budget_note")}</p></div>`;
    } else if (j.status === "needs_input" && st.awaiting === "provider") {
      needs = `<div class="callout bad"><b>${L("模型服务未配置", "Model provider not configured")}</b><p>${esc(j.message)}</p>
        <div class="row"><button id="recodeBtn2">${t("recode")}</button><button id="manualBtn">${t("manual_only")}</button></div></div>`;
    } else if (j.status === "needs_input" && st.awaiting === "price") {
      needs = `<div class="callout warn"><b>${t("price_missing")}</b><p>${esc(j.message)}</p>
        <div class="row"><a href="#/settings"><button>${t("nav_settings")} →</button></a><button class="primary" id="resumeBtn">${t("resume")}</button>
        <button id="manualBtn">${t("manual_only")}</button></div></div>`;
    } else if (j.status === "needs_input") {
      needs = `<div class="callout warn"><b>${t("need_sources")}</b><p>${esc(j.message)}</p><a href="#/case/${c.id}/sources">→ ${t("tab_sources")}</a></div>`;
    }
    body.innerHTML = `<div class="panel">
      <div class="stepper">${STAGES.map((s, i) => `<div class="st ${i < cur || j.status === "done" ? "done" : i === cur ? "cur" : ""}">${t("st_" + s)}</div>`).join("")}</div>
      <div class="bar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>
      <div class="row" style="margin-top:10px">${statusBadge(j)}<span>${esc(j.message || "")}</span><span class="spacer"></span>
      ${["running", "queued"].includes(j.status) ? `<button class="danger" id="cancelBtn">${t("cancel")}</button>` : `<button id="rerunBtn">${t("rerun")}</button> <button id="recodeBtn">${t("recode")}</button> <a href="#/case/${c.id}/review"><button class="primary">${t("tab_review")} →</button></a>`}</div>
      ${j.error ? `<div class="callout bad">${esc(j.error)}</div>` : ""}${needs}
      ${providerPanel(j)}
      ${cov ? `<h3>${t("coverage")}</h3>${!cov.automatic_search_ran ? `<div class="callout warn">${LANG === "zh" ? "未进行自动网页搜索（未配置搜索服务，或本次只是重新分析）。结果只基于已有或手动补充的资料。" : "No automatic web search in this run (no search provider configured, or this was a re-analysis). Results rest only on existing or manually added sources."}</div>` : cov.research_complete ? `<div class="callout ok">${t("complete_note")}</div>` : `<div class="callout warn">${t("incomplete")}<br><span class="small">${esc((cov.limits_hit || []).join("; "))}</span></div>`}
        ${cov.search_is_test_fixture ? `<div class="callout bad">${t("svc_test")}</div>` : ""}
        <div class="kv"><div>${t("case_spend")}</div><div>${money(cov.spent_usd)} / ${money(cov.budget_usd)}${cov.search_provider && !cov.search_price_configured && !cov.search_is_test_fixture ? ` <span class="badge warn">${t("search_price_missing")}</span>` : ""}</div>
        <div>${LANG === "zh" ? "搜索服务" : "Search provider"}</div><div>${esc(cov.search_provider || t("none"))}</div>
        <div>${LANG === "zh" ? "搜索（成功/失败）" : "Queries ok / failed"}</div><div>${cov.queries_ok} / ${cov.queries_failed} (${LANG === "zh" ? "轮次" : "rounds"} ${cov.rounds})</div>
        <div>${LANG === "zh" ? "已读取 / 获取失败" : "Sources read / failed"}</div><div>${cov.sources_ok} / ${cov.sources_failed}</div>
        <div>${LANG === "zh" ? "重复 / 转载" : "Duplicates / syndicated"}</div><div>${cov.exact_duplicates} / ${cov.near_duplicates}</div>
        <div>${LANG === "zh" ? "无关 / 相关性不确定" : "Irrelevant / uncertain"}</div><div>${cov.irrelevant} / ${cov.uncertain}</div>
        <div>${LANG === "zh" ? "扫描页未识别的来源" : "Sources with unread scanned pages"}</div><div>${cov.ocr_gaps}</div>
        <div>${LANG === "zh" ? "证据仍薄弱的变量" : "Variables still weak on evidence"}</div><div class="small">${esc((cov.gaps_remaining || []).join(", ")) || t("none")}</div></div>` : ""}
      ${st.coding_report ? `<p class="small muted">${LANG === "zh" ? "编码" : "Coding"}${st.coding_report.mode ? ` (${esc(modeText(st.coding_report.mode))})` : ""}: ${st.coding_report.calls} call(s), ${st.coding_report.failed_calls} failed${st.coding_report.cache_hits ? `, ${st.coding_report.cache_hits} ${L("个来自缓存（免费）", "from cache (free)")}` : ""}, ${esc(st.coding_report.semantic_method)}, ${st.coding_report.n_passages_indexed} passages indexed${st.coding_report.not_coded_budget?.length ? `, <b>${st.coding_report.not_coded_budget.length} not coded (limit)</b>` : ""}.
        ${(st.coding_report.providers || []).filter((r) => r.provider).map((r) => `<br>· ${esc(PROV[r.provider] || r.provider)} ${esc(r.model || "")} — ${esc(roleText(r.role))}: ${r.calls} call(s), ${r.failed_calls} failed, ${r.cache_hits || 0} cached, ${money(r.spent_usd)}`).join("")}
        ${st.coding_report.comparison && Object.keys(st.coding_report.comparison).length ? `<br>${L("比较", "Comparison")}: ${Object.entries(st.coding_report.comparison).map(([k, v]) => `${esc(compText(k))} ${v}`).join(" · ")} — ${L("模型一致不等于事实已核实。", "agreement is not verification.")}` : ""}</p>` : ""}
      <h3>${t("log")}</h3><div class="log">${(j.log || []).map((l) => `<div class="${l.level}">${new Date(l.at * 1000).toLocaleTimeString()} [${esc(l.stage)}] ${esc(l.message)}</div>`).join("")}</div></div>`;
    const on = (sel, fn) => { const el = $(sel, body); if (el) el.onclick = fn; };
    on("#cancelBtn", async () => { await api("POST", `/api/jobs/${j.id}/cancel`); draw(); });
    $$("[data-stop-prov]", body).forEach((b) => (b.onclick = async () => {
      const prov = b.dataset.stopProv;
      const ok = await askDialog({ title: `${L("停止", "Stop")} ${PROV[prov] || prov}`,
        body: `<p>${L("只停止这个模型；另一个模型继续运行。", "Only this provider stops; the other provider keeps running.")}</p>
          <ul class="small"><li>${L("尚未发送的批次不会再发送，也不会计费。", "Batches not yet sent will not be sent and are not billed.")}</li>
          <li><b>${L("已经发出的请求无法撤回：它可能仍会完成，并可能仍然计费；结果会保留。", "A request already sent to the API cannot be recalled: it may still finish and may still be billed; its result is kept.")}</b></li>
          <li>${L("已完成和已缓存的结果全部保留。之后可以点“继续”只补做停止的部分。", "Completed and cached results are kept. Later, Resume codes only what was stopped.")}</li></ul>`,
        okText: `${L("停止", "Stop")} ${PROV[prov] || prov}`, cancelText: L("不停止", "Keep running") });
      if (!ok) return;
      try { const r = await api("POST", `/api/jobs/${j.id}/providers/${prov}/stop`); toast(r.warning ? L("已请求停止。已发出的请求仍可能完成并计费。", "Stop requested. A request already sent may still finish and be billed.") : "ok"); draw(); }
      catch (e) { toast(e.message, true); }
    }));
    $$("[data-resume-prov]", body).forEach((b) => (b.onclick = async () => {
      const prov = b.dataset.resumeProv;
      try { const r = await api("POST", `/api/jobs/${j.id}/providers/${prov}/resume`); toast(r.resumed_in_place ? L("已撤回停止请求", "Stop request withdrawn") : `${L("已排队继续", "Resume queued")}: ${r.variables.length} ${L("个变量", "variable(s)")}`); draw(); }
      catch (e) { toast(e.message, true); }
    }));
    on("#rerunBtn", (ev) => startResearch(c.id, ev.currentTarget));
    on("#recodeBtn", (ev) => startRecode(c.id, null, ev.currentTarget));
    on("#recodeBtn2", (ev) => startRecode(c.id, null, ev.currentTarget));
    on("#approveBtn", async () => { await api("POST", `/api/jobs/${j.id}/resume`, { approve_over_budget: true }); draw(); });
    on("#raiseBtn", async () => { await api("POST", `/api/jobs/${j.id}/resume`, { budget_usd: +$("#newBudget").value }); draw(); });
    on("#manualBtn", async () => { await api("POST", `/api/jobs/${j.id}/resume`, { manual_only: true }); draw(); });
    on("#resumeBtn", async () => { await api("POST", `/api/jobs/${j.id}/resume`, {}); draw(); });
    on("#identAll", async () => { await api("POST", `/api/jobs/${j.id}/resume`, { identity_confirmed: true }); draw(); });
    $$("[data-year]", body).forEach((b) => (b.onclick = async () => { await api("POST", `/api/jobs/${j.id}/resume`, { identity_year: b.dataset.year }); draw(); }));
    if (!["running", "queued"].includes(j.status)) { clearInterval(POLL); POLL = null; }
    else if (!POLL) POLL = setInterval(() => { if (location.hash.includes(`/case/${c.id}/progress`)) draw(); else { clearInterval(POLL); POLL = null; } }, 2000);
  };
  draw();
}
function providerPanel(j) {
  const runs = (j.state || {}).provider_runs || {};
  const ctl = j.provider_controls || {};
  const provs = Object.keys(runs);
  if (!provs.length) return "";
  const RS = { pending: ["等待中", "waiting", ""], running: ["运行中", "running", "info"], stopped: ["已停止", "stopped", "warn"], done: ["已完成", "done", "ok"], failed: ["失败（配置错误）", "failed (configuration)", "bad"] };
  const active = ["queued", "running", "needs_input"].includes(j.status);
  return `<h3>${L("模型", "Model providers")}</h3><div class="prov-ctl">${provs.map((p) => {
    const r = runs[p]; const stopReq = ctl[p] && ctl[p].stop_requested;
    const st = stopReq && ["pending", "running"].includes(r.status) ? ["正在停止…", "stopping…", "warn"] : (RS[r.status] || [r.status, r.status, ""]);
    const canStop = active && ["pending", "running"].includes(r.status) && !stopReq;
    const canResume = (stopReq && ["pending", "running"].includes(r.status)) || r.status === "stopped";
    return `<div class="prov-row" data-prov-row="${esc(p)}"><b>${esc(PROV[p] || p)}</b> <span class="small mono">${esc(r.model || "")}</span> <span class="small muted">${esc(roleText(r.role))}</span>
      <span class="badge ${st[2]}">${esc(L(st[0], st[1]))}</span>
      ${r.calls != null ? `<span class="small muted">${r.calls} call(s) · ${r.failed_calls || 0} failed · ${r.cache_hits || 0} cached · ${money(r.spent_usd)}${(r.stopped_variables || []).length ? ` · ${r.stopped_variables.length} ${L("个变量已停止", "variable(s) stopped")}` : ""}</span>` : ""}
      <span class="spacer"></span>
      ${canStop ? `<button class="danger small" data-stop-prov="${esc(p)}">${L("停止", "Stop")} ${esc(PROV[p] === "Claude (Anthropic)" ? "Claude" : PROV[p] || p)}</button>` : ""}
      ${canResume ? `<button class="small" data-resume-prov="${esc(p)}">${L("继续", "Resume")} ${esc(PROV[p] === "Claude (Anthropic)" ? "Claude" : PROV[p] || p)}</button>` : ""}</div>`;
  }).join("")}</div>
  <p class="small muted">${L("“停止”只影响该模型，另一个模型不受影响。已经发出的请求无法撤回，可能仍会完成并计费。", "Stop affects only that provider; the other keeps running. A request already sent cannot be recalled and may still finish and be billed.")}</p>
  ${(j.queued_after || []).length ? `<p class="small">${L("之后排队的任务", "Queued after this job")}: ${j.queued_after.length}</p>` : ""}`;
}
// In-page dialog. Browser confirm()/prompt() can be silently blocked (settings or extensions), which made buttons
// look dead, so every confirmation is shown inside the page instead. Resolves to true / the typed text, or null.
function askDialog({ title, body = "", okText, cancelText, input = null }) {
  return new Promise((resolve) => {
    $("#modalRoot").innerHTML = `<div class="modal-bg"><div class="modal" style="width:min(560px,100%)" role="dialog" aria-modal="true">
      <header><b>${esc(title)}</b></header><div class="body">${body}
      ${input !== null ? `<label for="dlgInput">${esc(input.label || "")}</label><input id="dlgInput" value="${esc(input.value || "")}">` : ""}
      <div class="row" style="margin-top:14px"><button class="primary" id="dlgOk">${esc(okText || t("save"))}</button>
      <button id="dlgCancel">${esc(cancelText || t("close"))}</button></div></div></div></div>`;
    const done = (v) => { $("#modalRoot").innerHTML = ""; resolve(v); };
    $("#dlgOk").onclick = () => done(input !== null ? $("#dlgInput").value : true);
    $("#dlgCancel").onclick = () => done(null);
    (input !== null ? $("#dlgInput") : $("#dlgOk")).focus();
  });
}
function busy(btn, on, text) {
  if (!btn) return;
  if (on) { btn.dataset.label = btn.textContent; btn.disabled = true; if (text) btn.textContent = text; }
  else { btn.disabled = false; if (btn.dataset.label) btn.textContent = btn.dataset.label; }
}
async function startResearch(id, btn) {
  busy(btn, true);
  try { await api("POST", `/api/cases/${id}/research`, {}); location.hash = `#/case/${id}/progress`; route(); }
  catch (e) { toast(e.message, true); }
  finally { busy(btn, false); }
}
async function startRecode(id, variables, btn) {
  busy(btn, true, LANG === "zh" ? "正在估算费用…" : "Estimating cost…");
  try {
    const modes = availModes();
    const caseMode = (STATUS.settings || {}).coding_mode || "single";
    const estFor = (mode) => api("GET", `/api/cases/${id}/estimate?mode=${encodeURIComponent(mode)}${variables ? "&variables=" + encodeURIComponent(variables.join(",")) : ""}`);
    let mode = modes.some((m) => m.mode === caseMode) ? caseMode : "single";
    let e = null;
    try { e = await estFor(mode); }
    catch (err) { toast((LANG === "zh" ? "无法估算费用：" : "Could not estimate the cost: ") + err.message, true); return; }
    const body = (e) => {
      const lg = e.ledger || {}; const lim = e.limits || {};
      const twoOrMore = (e.providers || []).length > 1;
      return `<label for="modeSel">${L("编码模式（OpenAI 选项仅在服务器配置了密钥时显示）", "Coding mode (OpenAI options appear only when its key is configured on the server)")}</label>
        <select id="modeSel">${modes.map((m) => `<option value="${esc(m.mode)}" ${m.mode === mode ? "selected" : ""}>${esc(modeText(m.mode))}</option>`).join("")}</select>
        ${e.manual ? `<p>${t("svc_none_model")}</p>` : `<div class="kv" style="margin-top:8px">${providerCostRows(e)}
          ${twoOrMore ? `<div><b>${L("合计", "Combined")}</b></div><div>${money(e.cost_low)} – <b>${money(e.cost_high)}</b> ${t("worst_case")}</div>` : ""}
          ${e.cost_high_new != null && e.cost_high - e.cost_high_new > 0.005 ? `<div>${L("新增费用上限（不含缓存批次）", "Max additional cost (cached batches are free)")}</div><div><b>${money(e.cost_high_new)}</b></div>` : ""}
          <div>${t("case_spend")}</div><div>${money(lg.spent_total)} / ${money(lim.budget_usd)}</div>
          <div>${L("已花费：Claude / OpenAI / 搜索", "Spent: Claude / OpenAI / search")}</div><div>${money((lg.spent_by || {}).anthropic || 0)} / ${money((lg.spent_by || {}).openai || 0)} / ${money((lg.spent_by || {}).search || 0)}</div>
          <div>${L("OpenAI 预算", "OpenAI budget")}</div><div>${money((lg.spent_by || {}).openai || 0)} / ${money(lim.openai_budget_usd)}</div>
          <div>${L("模型请求次数（本案例）", "Model attempts (this case)")}</div><div>${lg.attempts_total || 0} / ${lim.max_model_attempts_per_case} · OpenAI ${(lg.attempts_by || {}).openai || 0} / ${lim.max_openai_attempts_per_case}</div></div>
          ${Object.keys(e.limit_needs || {}).length ? `<div class="callout warn small">${L("这次运行可能超过上限；开始后会暂停，请你按明确数值批准：", "This run could exceed a limit; it will pause and ask you to approve explicit values:")} ${Object.values(e.limit_needs).map((v) => `${esc(v.label)} ${esc(v.current)} → ${esc(v.needed)}`).join("; ")}</div>` : ""}
          ${(e.price_notes || []).length ? `<div class="callout warn small">${esc(e.price_notes.join("; "))}</div>` : ""}
          ${mode === "dual_independent" ? `<p class="small">${L("两个模型拿到相同证据、彼此看不到对方结果；不一致的变量会交给人工复核。模型一致不代表事实已核实。", "Both models get the same evidence and never see each other's result; disagreements go to human review. Agreement is not verification.")}</p>` : ""}
          ${mode.endsWith("_review") ? `<p class="small">${L("复核模型会看到主模型的建议，因此不是独立编码。", "The reviewer sees the primary model's suggestions, so it is not an independent coder.")}</p>` : ""}`}
        ${e.manual ? "" : `<details style="margin-top:8px"><summary>${L("本案例的上限（明确数值）", "This case's limits (explicit values)")}</summary>
          <div class="grid2">${[["budget_usd", L("总预算（美元）", "Combined budget ($)")], ["openai_budget_usd", L("OpenAI 预算（美元）", "OpenAI budget ($)")], ["max_openai_attempts_per_case", L("OpenAI 请求次数上限", "OpenAI attempts")], ["max_model_attempts_per_case", L("所有模型请求次数上限", "All model attempts")]].map(([k, lab]) => `<div><label>${esc(lab)}</label><input data-limit="${k}" value="${esc((e.limits || {})[k])}"></div>`).join("")}</div>
          <button class="small" id="saveLimits" style="margin-top:6px">${L("保存上限", "Save limits")}</button><span class="small muted"> ${L("可以提高或降低；不能取消。每次修改都会记录。", "Raise or lower; never removed. Every change is recorded.")}</span></details>`}
        <p class="small muted">${LANG === "zh" ? "费用计入本案例的预算上限。只使用已读取的资料，不会产生新的搜索费用。" : "This counts toward the case's budget cap. It uses the sources already read, with no new search cost."}</p>`;
    };
    const ok = await new Promise((resolve) => {
      $("#modalRoot").innerHTML = `<div class="modal-bg"><div class="modal" style="width:min(640px,100%)" role="dialog" aria-modal="true">
        <header><b>${esc(t("recode"))}${variables ? ": " + esc(variables.join(", ")) : ""}</b></header><div class="body"><div id="rcBody">${body(e)}</div>
        <div class="row" style="margin-top:14px"><button class="primary" id="dlgOk">${LANG === "zh" ? "开始重新分析" : "Start re-analysis"}</button>
        <button id="dlgCancel">${LANG === "zh" ? "取消" : "Cancel"}</button></div></div></div></div>`;
      const wire = () => {
        if ($("#saveLimits")) $("#saveLimits").onclick = async () => {
          const limits = {}; $$("[data-limit]").forEach((el) => (limits[el.dataset.limit] = +el.value));
          try { await api("POST", `/api/cases/${id}/limits`, { limits, reason: "set in re-analysis dialog" }); e = await estFor(mode); $("#rcBody").innerHTML = body(e); wire(); toast(t("saved")); }
          catch (err) { toast(err.message, true); }
        };
        $("#modeSel").onchange = async (ev) => {
          mode = ev.target.value; $("#dlgOk").disabled = true;
          try { e = await estFor(mode); $("#rcBody").innerHTML = body(e); wire(); }
          catch (err) { toast(err.message, true); }
          finally { $("#dlgOk").disabled = false; }
        };
      };
      wire();
      const done = (v) => { $("#modalRoot").innerHTML = ""; resolve(v); };
      $("#dlgOk").onclick = () => {
        if (!e.manual && e.cost_high == null) { toast(LANG === "zh" ? "缺少模型价格，无法估算费用。请在设置 → 价格中填写。" : "No model price, so the cost can't be estimated. Add it under Settings → Pricing.", true); return; }
        done(true);
      };
      $("#dlgCancel").onclick = () => done(null);
      $("#dlgOk").focus();
    });
    if (!ok) return;
    await api("POST", `/api/cases/${id}/recode`, { variables: variables || null, mode });
    toast(LANG === "zh" ? "已开始重新分析" : "Re-analysis started");
    location.hash = `#/case/${id}/progress`; route();
  } catch (err) { toast(err.message, true); }
  finally { busy(btn, false); }
}

// ------------------------------------------------------------------ review workbench
const CAT_BADGE = { confirmed: "ok", pending: "info", insufficient: "", disputed: "dispute", rule_missing: "bad" };
function codeLabel(row, v) {
  if (!v) return "";
  const m = {}; (row.codes || []).forEach((c) => (m[String(c.code).toUpperCase()] = c.label));
  return v.split(/[;,]/).map((p) => p.trim()).filter(Boolean).map((p) => m[p.toUpperCase()] ? `${p} = ${m[p.toUpperCase()]}` : p).join("; ");
}
async function tabReview(c, body) {
  WB.data = await api("GET", `/api/cases/${c.id}/results`);
  WB.srcMap = Object.fromEntries(WB.data.sources.map((s) => [s.id, s]));
  const cats = ["all", "pending", "confirmed", "insufficient", "disputed", "rule_missing"];
  const counts = { all: WB.data.rows.length }; WB.data.rows.forEach((r) => (counts[r.category] = (counts[r.category] || 0) + 1));
  const sections = [...new Set(WB.data.rows.map((r) => r.section).filter(Boolean))];
  body.innerHTML = `<div class="workbench"><div>
      <div class="chips">${cats.map((k) => `<span class="chip ${WB.filter === k ? "on" : ""}" data-f="${k}">${t("filter_" + k)} ${counts[k] || 0}</span>`).join("")}</div>
      <div class="row" style="margin-bottom:8px"><input id="wbq" placeholder="${esc(t("search_vars"))}" value="${esc(WB.q)}" style="max-width:260px">
      <select id="wbsec" style="max-width:260px"><option value="">— section —</option>${sections.map((s) => `<option ${WB.section === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <span class="small muted">${t("filter_note")}</span></div>
      <div class="wb-table"><table id="wbTable"><thead><tr><th>#</th><th>${t("col_var")}</th><th>${L("Claude 建议", "Claude suggestion")}</th><th>${L("OpenAI 建议", "OpenAI suggestion")}</th><th>${L("人工最终值", "Human final")}</th><th>${L("比较", "Comparison")}</th><th>${L("复核状态", "Review status")}</th></tr></thead><tbody id="wbRows"></tbody></table></div>
    </div><div class="wb-detail panel" id="wbDetail"><p class="muted">${t("select_var")}</p></div></div>`;
  const drawRows = () => {
    const rows = WB.data.rows.filter((r) => (WB.filter === "all" || r.category === WB.filter) && (!WB.section || r.section === WB.section) &&
      (!WB.q || r.name.toLowerCase().includes(WB.q.toLowerCase())));
    $("#wbRows").innerHTML = rows.map((r) => {
      const s = r.suggestion || {}; const rv = r.review;
      const final = rv && ["accepted", "edited", "cleared"].includes(rv.action);
      const sys = r.system && !(r.providers || []).length ? r.system : null;
      const notModel = !["sourced", "judgment"].includes(r.field_class) || r.rule_missing;
      const provCells = notModel && !(r.providers || []).length
        ? `<td colspan="2" class="val"><span class="cell-tag st-system">${esc(r.rule_missing ? L("无编码规则", "no codebook rule") : r.field_class === "analyst_note" ? L("分析员填写", "analyst note") : r.field_class === "derived" ? L("计算得出（非模型）", "derived (not model-coded)") : r.field_class === "admin" ? L("系统生成（非模型）", "generated (not model-coded)") : L("非模型编码", "not model-coded"))}</span>${sys && sys.value ? ` <span class="mono">${esc(sys.value.slice(0, 50))}</span>` : ""}</td>`
        : sys
        ? `<td colspan="2" class="val"><span class="cell-tag st-system">${esc(sys.basis === "retrieval_only" ? L("仅候选证据（人工编码）", "candidates only (manual coding)") : sys.basis === "derived" ? L("计算得出", "derived") : sys.basis === "generated" ? L("系统生成", "generated") : sys.status)}</span> <span class="mono">${esc((sys.value || "").slice(0, 60))}</span></td>`
        : `<td class="val pc-anthropic">${cellHtml((r.cells || {}).anthropic, r)}</td><td class="val pc-openai">${cellHtml((r.cells || {}).openai, r)}</td>`;
      return `<tr class="click ${WB.sel === r.name ? "sel" : ""}" data-v="${esc(r.name)}"><td class="small muted">${r.position}</td>
        <td><b class="mono">${esc(r.name)}</b>${r.issues.length ? ` <span class="badge warn" title="${esc(r.issues.join("\n"))}">!</span>` : ""}${s.stale ? ` <span class="badge bad">stale</span>` : ""}</td>
        ${provCells}
        <td class="val human-final">${final ? `<span class="final-val mono">${esc((rv.value || "∅").slice(0, 60))}</span>${rv.source_provider ? `<div class="small muted">${esc(L("采纳自", "from"))} ${esc(PROV[rv.source_provider] || rv.source_provider)}</div>` : ""}` : rv && rv.action === "deferred" ? `<span class="muted small">${L("暂缓", "deferred")}</span>` : `<span class="muted small">—</span>`}</td>
        <td>${r.comparison ? `<span class="badge ${COMP_BADGE[r.comparison.model_status] || ""}">${esc(compText(r.comparison.model_status))}</span>${r.comparison.kind === "reviewer" ? `<div class="small muted">${L("复核（非独立）", "review (not independent)")}</div>` : r.comparison.kind === "separate_runs" ? `<div class="small muted">${L("不同次运行", "separate runs")}</div>` : ""}` : `<span class="muted small">—</span>`}</td>
        <td><span class="badge ${CAT_BADGE[r.category]}">${t("filter_" + r.category)}</span></td></tr>`;
    }).join("");
    $$("#wbRows tr").forEach((tr) => (tr.onclick = () => { WB.sel = tr.dataset.v; drawRows(); drawDetail(c); }));
  };
  $$(".chip", body).forEach((ch) => (ch.onclick = () => { WB.filter = ch.dataset.f; tabReview(c, body); }));
  $("#wbq").oninput = (e) => { WB.q = e.target.value; drawRows(); };
  $("#wbsec").onchange = (e) => { WB.section = e.target.value; drawRows(); };
  drawRows();
  if (WB.sel) drawDetail(c);
}
function evHtml(ev) {
  const src = WB.srcMap[ev.source_id] || {};
  const loc = ev.page ? `p. ${ev.page}` : ev.para ? `para ${ev.para}` : "";
  return `<div class="ev ${esc(ev.stance || "supports")}"><div class="row"><span class="mono small">${esc(ev.id)}</span>
    <span class="badge">${esc(ev.stance || "")}</span><span class="loc">S${ev.source_id} · ${esc(src.source_type || "")} · ${loc}</span><span class="spacer"></span>
    <button class="small" data-open="${ev.source_id}" data-pid="${esc(ev.id)}">${t("view")}</button></div>
    <div><q>${esc(ev.quote)}</q></div><div class="loc">${esc((src.title || "").slice(0, 100))} ${src.excluded ? `<span class="badge bad">${t("excluded")}</span>` : ""}</div></div>`;
}
function drawDetail(c) {
  const r = WB.data.rows.find((x) => x.name === WB.sel); if (!r) return;
  const s = r.suggestion || {}; const rv = r.review; const v = s.validation || {};
  const d = $("#wbDetail");
  const editor = r.type === "categorical" && r.codes.length
    ? (r.multi ? `<div>${r.codes.concat((r.missing_codes || []).map((m) => ({ code: m, label: "special missing value" }))).map((cd) => `<label style="display:flex;gap:6px;margin:2px 0;color:var(--ink)"><input type="checkbox" style="width:auto" value="${esc(cd.code)}" class="mcode">${esc(cd.code)} = ${esc(cd.label)}</label>`).join("")}</div>`
      : `<select id="edVal"><option value="">(blank)</option>${r.codes.concat((r.missing_codes || []).map((m) => ({ code: m, label: "special missing value" }))).map((cd) => `<option value="${esc(cd.code)}">${esc(cd.code)} = ${esc(cd.label)}</option>`).join("")}</select>`)
    : `<textarea id="edVal">${esc(rv ? rv.value : s.value || "")}</textarea>`;
  d.innerHTML = `<div class="row"><h2 class="mono" style="margin:0">${esc(r.name)}</h2><span class="spacer"></span><span class="badge ${CAT_BADGE[r.category]}">${t("filter_" + r.category)}</span></div>
    <div class="small muted">${esc(r.section || "")} · ${esc(r.type)}${r.multi ? " · multi-select" : ""} · class: ${esc(r.field_class)}</div>
    <h3>${t("definition")}</h3><div class="def">${esc(r.definition || "—")}
      ${r.codes.length ? `<ul class="codes">${r.codes.map((cd) => `<li><b>${esc(cd.code)}</b> = ${esc(cd.label)}</li>`).join("")}</ul>` : ""}
      ${r.open_options.length ? `<div class="small muted" style="margin-top:6px">Listed options (open): ${esc(r.open_options.join("; "))}</div>` : ""}
      ${r.missing_codes.length ? `<div class="small" style="margin-top:6px">Special missing value(s) for this variable: <b>${esc(r.missing_codes.join(", "))}</b></div>` : `<div class="small muted" style="margin-top:6px">No special missing value defined — leave blank when not established.</div>`}
      <div class="small muted" style="margin-top:6px">${t("codebook_ref")}: ${esc(r.codebook_ref || "—")}</div></div>
    ${r.issues.length ? `<div class="callout warn small"><b>${t("rule_issues")}</b><ul style="margin:4px 0 0;padding-left:18px">${r.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>` : ""}
    ${r.comparison ? `<div class="callout ${r.comparison.model_status === "model_agreement" ? "ok" : "warn"} small"><b>${esc(compText(r.comparison.status))}</b>${r.comparison.status === "human_approved" ? ` (${L("模型比较", "models")}: ${esc(compText(r.comparison.model_status))})` : ""}${r.comparison.note ? " — " + esc(r.comparison.note) : ""}
      ${r.comparison.kind === "reviewer" ? `<br>${L("复核模型看过主模型的结果，不是独立编码。", "The reviewer saw the primary model's result; it is not an independent coder.")}` : ""}
      <br>${L("模型一致不等于事实已核实；最终值以人工复核为准。", "Model agreement is not verification; the human-reviewed value is final.")}</div>` : ""}
    ${(r.providers || []).length >= 1 ? `<h3>${L("各模型的建议（互不覆盖）", "Suggestions by model (never overwrite each other)")}</h3>${["anthropic", "openai"].filter((k) => !(r.providers || []).some((m) => (m.provider === "openai_compatible" ? "openai" : m.provider) === k)).map((k) => `<div class="panel small" style="padding:8px 12px;margin:6px 0"><b>${esc(PROV[k])}</b> ${cellHtml((r.cells || {})[k], r)}</div>`).join("")}${r.providers.map((m) => `<div class="panel" style="padding:10px 12px;margin:6px 0">
      <div class="row"><b>${esc(m.provider_label || m.provider)}</b><span class="small mono">${esc(m.model || "")}</span><span class="badge ${m.role === "reviewer" ? "warn" : ""}">${esc(roleText(m.role))}</span>
      ${cellHtml((r.cells || {})[m.provider === "openai_compatible" ? "openai" : m.provider], r)}${m.cache_status && m.cache_status !== "new" ? `<span class="badge info">${L("缓存", "cache")}</span>` : ""}<span class="spacer"></span>
      <button class="small" data-accept-sid="${m.id}" ${m.value && !["model_error", "validation_failed"].includes(m.status) ? "" : "disabled"}>${L("接受此建议", "Accept this")}</button></div>
      <div class="val" style="margin:4px 0">${esc(m.value) || `<span class="muted">(blank)</span>`}${m.value && r.codes.length ? ` <span class="small">${esc(codeLabel(r, m.value))}</span>` : ""}</div>
      ${m.rationale ? `<div class="small"><b>${t("rationale")}:</b> ${esc(m.rationale)}</div>` : ""}
      ${m.unresolved ? `<div class="small"><b>${t("unresolved")}:</b> ${esc(m.unresolved)}</div>` : ""}
      ${((m.validation || {}).errors || []).length ? `<div class="callout bad small">${esc(m.validation.errors.join("; "))}</div>` : ""}
      ${(m.evidence || []).map(evHtml).join("")}${(m.counter || []).map(evHtml).join("")}</div>`).join("")}<h3>${L("默认采用的建议（主模型或最近一次运行）", "Default suggestion (primary or most recent run)")}</h3>` : `<h3>${t("suggestion")}</h3>`}
    ${s.status ? `<div class="row"><span class="badge">${esc(s.status)}</span><span class="small muted">${t("basis")}: ${esc(s.basis || "")}${s.provider ? ` · ${esc(PROV[s.provider] || s.provider)} ${esc(s.model || "")}` : ""}</span></div>
      <div class="val" style="font-size:14px;margin:6px 0">${esc(s.value) || `<span class="muted">(blank)</span>`}</div>
      ${s.value && r.codes.length ? `<div class="small">${esc(codeLabel(r, s.value))}</div>` : ""}
      ${s.stale ? `<div class="callout bad small">${t("stale")}: ${esc(s.stale_reason)} <button class="small" id="recodeOne">${t("recode")}</button></div>` : ""}
      ${r.previous ? `<div class="diff">${t("prev_run")}: <b class="mono">${esc(r.previous.value || "(blank)")}</b> (${esc(r.previous.status)}) → <b class="mono">${esc(s.value || "(blank)")}</b> (${esc(s.status)})</div>` : ""}
      ${s.rationale ? `<p><b>${t("rationale")}:</b> ${esc(s.rationale)}</p>` : ""}
      ${s.unresolved ? `<div class="callout warn small"><b>${t("unresolved")}:</b> ${esc(s.unresolved)}</div>` : ""}
      ${(v.errors || []).length ? `<div class="callout bad small"><b>${t("validation")}:</b> ${esc(v.errors.join("; "))}${v.proposed_value ? `<br>proposed: <span class="mono">${esc(v.proposed_value)}</span>` : ""}</div>` : ""}
      ${(v.warnings || []).length ? `<div class="callout warn small">${esc(v.warnings.join("; "))}</div>` : ""}
      ${(v.options || []).length > 1 ? `<div class="small"><b>Per-option evidence:</b> ${v.options.map((o) => `${esc(o.code)}: ${o.evidence.map((e) => esc(e.id)).join(", ")}`).join(" · ")}</div>` : ""}
      ${(s.evidence || []).length ? `<h3>${s.status === "manual_needed" ? t("candidates") : t("support")}</h3>${s.evidence.map(evHtml).join("")}` : ""}
      ${(s.counter || []).length ? `<h3>${t("counter")}</h3>${s.counter.map(evHtml).join("")}` : ""}` : `<p class="muted">${t("none")}</p>`}
    <h3>${t("review")}</h3>
    <div class="callout ${rv && ["accepted", "edited", "cleared"].includes(rv.action) ? "ok" : ""} small"><b>${L("人工确认的最终值", "Human-approved final value")}:</b>
      ${rv && ["accepted", "edited", "cleared"].includes(rv.action) ? `<span class="mono">${esc(rv.value || "∅")}</span> — ${esc(rv.action)}${rv.source_provider ? ` (${L("采纳自", "from")} ${esc(PROV[rv.source_provider] || rv.source_provider)})` : ""}${rv.reviewer ? " · " + esc(rv.reviewer) : ""} ${rv.reason ? "— " + esc(rv.reason) : ""} (${fmtTime(rv.updated_at)})` : `<span class="muted">${L("尚未确认（模型建议不会自动成为最终值）", "not yet approved (model suggestions never become final on their own)")}</span>`}</div>
    ${rv && rv.action === "deferred" ? `<div class="small">Current: <b>deferred</b>${rv.reviewer ? " (" + esc(rv.reviewer) + ")" : ""}</div>` : ""}
    <div class="row" style="margin:6px 0"><button class="primary" id="acceptBtn" ${s.value && !(r.comparison && r.comparison.model_status !== "model_agreement") ? "" : "disabled"} title="${r.comparison && r.comparison.model_status !== "model_agreement" ? esc(L("模型不一致：请在上方选择要接受的建议，或直接修改", "Models differ: accept a specific model's suggestion above, or edit")) : ""}">${t("accept")}</button><button id="deferBtn">${t("defer")}</button><button class="danger" id="clearBtn">${t("clear")}</button>${rv ? `<button id="resetBtn">${t("reset")}</button>` : ""}</div>
    <label>${t("value")}</label>${editor}
    <label>${t("reason")}</label><input id="edReason">
    <div class="row" style="margin-top:6px"><button id="editBtn">${t("edit")} → ${t("save")}</button></div>
    <details style="margin-top:14px"><summary>${t("manual_search")}</summary><div class="row" style="margin-top:6px"><input id="msq" placeholder="${esc(t("manual_search_ph"))}"><button id="msBtn">${t("find")}</button></div><div id="msOut"></div></details>
    <details style="margin-top:8px" id="histBox"><summary>${t("history")}</summary><div id="histOut" class="small"></div></details>`;
  if (r.type === "categorical" && r.codes.length) {
    const cur = (rv ? rv.value : s.value || "").split(/[;,]/).map((x) => x.trim());
    if (r.multi) $$(".mcode", d).forEach((cb) => (cb.checked = cur.includes(cb.value)));
    else if ($("#edVal")) $("#edVal").value = cur[0] || "";
  }
  const send = async (action, extra = {}) => {
    try { await api("POST", `/api/cases/${c.id}/review`, { variable: r.name, action, reason: $("#edReason").value, ...extra }); toast(t("saved")); tabReview(c, $("#tabBody")); }
    catch (e) { toast(e.message, true); }
  };
  $("#acceptBtn").onclick = () => send("accept");
  $$("[data-accept-sid]", d).forEach((b) => (b.onclick = () => send("accept", { suggestion_id: +b.dataset.acceptSid })));
  $("#deferBtn").onclick = () => send("defer");
  $("#clearBtn").onclick = () => send("clear");
  if ($("#resetBtn")) $("#resetBtn").onclick = () => send("reset");
  $("#editBtn").onclick = () => {
    const val = r.multi && r.type === "categorical" && r.codes.length ? $$(".mcode", d).filter((x) => x.checked).map((x) => x.value).join(", ") : $("#edVal").value;
    send("edit", { value: val });
  };
  if ($("#recodeOne")) $("#recodeOne").onclick = () => startRecode(c.id, [r.name]);
  $$("[data-open]", d).forEach((b) => (b.onclick = () => openSource(+b.dataset.open, b.dataset.pid)));
  $("#msBtn").onclick = async () => {
    const res = await api("GET", `/api/cases/${c.id}/evidence_search?q=${encodeURIComponent($("#msq").value)}`);
    $("#msOut").innerHTML = `<div class="small muted">${esc(res.method)}</div>` + res.hits.map((h) => evHtml({ id: h.id, source_id: h.source_id, page: h.page, para: h.para, quote: h.text.slice(0, 400), stance: "candidate" })).join("");
    $$("[data-open]", $("#msOut")).forEach((b) => (b.onclick = () => openSource(+b.dataset.open, b.dataset.pid)));
  };
  $("#histBox").ontoggle = async () => {
    if (!$("#histBox").open) return;
    const h = await api("GET", `/api/cases/${c.id}/history?variable=${encodeURIComponent(r.name)}`);
    $("#histOut").innerHTML = `<b>Suggestions</b>${h.suggestions.map((x) => `<div>${fmtTime(x.created_at)} · run ${x.run_id} · ${esc(x.status)} · <span class="mono">${esc(x.value || "∅")}</span>${x.stale ? " (stale)" : ""}</div>`).join("")}
      <b>Reviews</b>${h.reviews.map((x) => `<div>${fmtTime(x.at)} · ${esc(x.action)}${x.reviewer ? " · " + esc(x.reviewer) : ""} · <span class="mono">${esc(x.old_value ?? "∅")} → ${esc(x.new_value ?? "∅")}</span> ${esc(x.reason || "")}</div>`).join("") || t("none")}`;
  };
}
async function openSource(sid, pid) {
  const d = await api("GET", `/api/sources/${sid}/passages`);
  const s = d.source;
  $("#modalRoot").innerHTML = `<div class="modal-bg"><div class="modal"><header><b>S${s.id}</b><span>${esc(s.title || "")}</span><span class="spacer"></span><button id="mClose">${t("close")}</button></header>
    <div class="body"><div class="small muted">${esc(s.source_type)} · ${esc(s.publisher || "")} · ${esc(s.published_date || "")} · ${s.final_url || s.url ? `<a href="${esc(s.final_url || s.url)}" target="_blank" rel="noopener">${esc(s.final_url || s.url)}</a>` : esc(s.found_via)}</div>
    ${s.ocr_status && s.ocr_status !== "not_needed" && s.ocr_status !== "not_applicable" ? `<div class="callout warn small">${esc(s.ocr_status)}</div>` : ""}
    ${d.passages.map((p) => `<div class="passage ${p.id === pid ? "hl" : ""}" id="p-${esc(p.id)}"><span class="pid">${esc(p.id)} ${p.page ? "· p." + p.page : ""} ${p.para ? "· ¶" + p.para : ""}</span><div>${esc(p.text)}</div></div>`).join("")}</div></div></div>`;
  $("#mClose").onclick = () => ($("#modalRoot").innerHTML = "");
  $(".modal-bg").onclick = (e) => { if (e.target.classList.contains("modal-bg")) $("#modalRoot").innerHTML = ""; };
  if (pid) setTimeout(() => { const el = document.getElementById("p-" + pid); if (el) el.scrollIntoView({ block: "center" }); }, 50);
}

// ------------------------------------------------------------------ sources
const TYPES = ["aar", "government", "regulatory", "legislative", "academic", "ngo_technical", "media", "unknown"];
async function tabSources(c, body) {
  const rows = await api("GET", `/api/cases/${c.id}/sources`);
  body.innerHTML = `<div class="panel"><h3 style="margin-top:0">${t("src_add")}</h3>
    <div class="grid3"><div><label>${t("add_url")}</label><div class="row"><input id="addUrl" placeholder="https://"><button id="addUrlBtn">${t("add")}</button></div></div>
    <div><label>${t("add_file")} (PDF, HTML, DOCX, TXT)</label><div class="row"><input id="addFile" type="file" multiple><button id="addFileBtn">${t("add")}</button></div></div>
    <div><label>${t("add_text")}</label><input id="addTitle" placeholder="${t("src_title")}"><textarea id="addText" style="margin-top:4px"></textarea><button id="addTextBtn" style="margin-top:4px">${t("add")}</button></div></div>
    <p class="small muted">${LANG === "zh" ? "不会绕过登录或付费墙；无法访问的来源可在有合法访问权时手动补充正文。补充后点击“重新分析”。" : "Logins and paywalls are never bypassed; add text manually if you have legitimate access. Re-analyze after adding."}
    <button class="small" id="recodeAll">${t("recode")}</button></p><div id="affBox"></div></div>
    <div class="panel" style="padding:0;margin-top:12px"><table><thead><tr><th>#</th><th>${t("src_title")}</th><th>${t("src_type")}</th><th>${t("src_rel")}</th><th>${t("src_status")}</th><th>${t("src_flags")}</th><th></th></tr></thead><tbody>
    ${rows.map((s) => `<tr><td class="mono small">S${s.id}</td><td><b>${esc((s.title || s.url || "").slice(0, 110))}</b>
      <div class="small muted">${esc(s.publisher || "")} ${esc(s.published_date || "")} · ${esc(s.found_via || s.origin)}</div>
      ${s.url ? `<div class="small"><a href="${esc(s.final_url || s.url)}" target="_blank" rel="noopener">${esc((s.final_url || s.url).slice(0, 90))}</a></div>` : ""}</td>
      <td><select data-type="${s.id}" style="width:auto">${TYPES.map((x) => `<option ${x === s.source_type ? "selected" : ""}>${x}</option>`).join("")}</select></td>
      <td><span class="badge ${s.relevance_status === "relevant" ? "ok" : s.relevance_status === "irrelevant" ? "bad" : "warn"}">${esc(s.relevance_status)}</span>
        <div class="small muted">${esc(s.relevance_reason || "")}</div></td>
      <td>${s.fetch_status === "ok" ? `<span class="badge ok">ok</span><div class="small muted">${s.n_pages ? s.n_pages + " pp · " : ""}${s.n_passages || 0} passages</div>` : `<span class="badge bad">${esc(s.fetch_status)}</span><div class="small">${esc(s.fetch_error || "")}</div>`}</td>
      <td class="small">${s.duplicate_of ? `<span class="badge bad">${t("dup_of")} S${s.duplicate_of}</span> ` : ""}${s.near_duplicate_of ? `<span class="badge warn">${t("near_of")} S${s.near_duplicate_of} (${Math.round((s.similarity || 0) * 100)}%)</span> ` : ""}${s.excluded ? `<span class="badge bad">${t("excluded")}</span> ${esc(s.exclude_reason || "")}` : ""}
        ${s.ocr_status && !["not_needed", "not_applicable"].includes(s.ocr_status) ? `<div class="muted">${esc(s.ocr_status)}</div>` : ""}</td>
      <td class="row">${s.fetch_status === "ok" ? `<button class="small" data-open="${s.id}">${t("view")}</button>` : ""}
        <button class="small" data-excl="${s.id}" data-on="${s.excluded ? 0 : 1}">${s.excluded ? t("include") : t("exclude")}</button>
        <select class="small" data-rel="${s.id}" style="width:auto"><option value="">relevance…</option><option>relevant</option><option>uncertain</option><option>irrelevant</option></select></td></tr>`).join("") || `<tr><td colspan="7" class="muted">${t("none")}</td></tr>`}
    </tbody></table></div>`;
  const add = async (payload) => { try { const s = await api("POST", `/api/cases/${c.id}/sources`, payload); toast(`S${s.id}: ${s.fetch_status}${s.fetch_error ? " — " + s.fetch_error : ""}`, s.fetch_status !== "ok"); tabSources(c, body); } catch (e) { toast(e.message, true); } };
  $("#addUrlBtn").onclick = () => add({ kind: "url", url: $("#addUrl").value.trim() });
  $("#addTextBtn").onclick = () => add({ kind: "text", title: $("#addTitle").value, text: $("#addText").value });
  $("#addFileBtn").onclick = async () => { for (const f of $("#addFile").files) await add({ kind: "file", filename: f.name, data: await fileToB64(f) }); };
  $("#recodeAll").onclick = (ev) => startRecode(c.id, null, ev.currentTarget);
  $$("[data-open]", body).forEach((b) => (b.onclick = () => openSource(+b.dataset.open)));
  const showAffected = (r) => { if (r.affected_variables && r.affected_variables.length) { $("#affBox").innerHTML = `<div class="callout warn">${t("affected")}: <span class="mono">${esc(r.affected_variables.join(", "))}</span> <button class="small" id="reAff">${t("reanalyze_affected")}</button></div>`; $("#reAff").onclick = () => startRecode(c.id, r.affected_variables); } };
  $$("[data-excl]", body).forEach((b) => (b.onclick = async () => {
    let reason = "";
    if (b.dataset.on === "1") {
      reason = await askDialog({ title: LANG === "zh" ? "排除这份来源" : "Exclude this source", input: { label: LANG === "zh" ? "排除理由" : "Reason for excluding" },
        okText: t("exclude"), cancelText: LANG === "zh" ? "取消" : "Cancel" });
      if (reason === null) return;
    }
    const r = await api("PATCH", `/api/sources/${b.dataset.excl}`, { excluded: b.dataset.on === "1", reason });
    await tabSources(c, body); showAffected(r);
  }));
  $$("[data-rel]", body).forEach((s) => (s.onchange = async () => { if (!s.value) return; const r = await api("PATCH", `/api/sources/${s.dataset.rel}`, { relevance_status: s.value }); await tabSources(c, body); showAffected(r); }));
  $$("[data-type]", body).forEach((s) => (s.onchange = async () => { await api("PATCH", `/api/sources/${s.dataset.type}`, { source_type: s.value }); toast(t("saved")); }));
}

// ------------------------------------------------------------------ search log
async function tabSearches(c, body) {
  const qs = await api("GET", `/api/cases/${c.id}/searches`);
  body.innerHTML = `<div class="panel" style="padding:0"><table><thead><tr><th>${t("q_round")}</th><th>${t("q_purpose")}</th><th>${t("q_query")}</th><th>${t("q_provider")}</th><th>${t("q_results")}</th></tr></thead><tbody>
    ${qs.map((q) => `<tr><td>${q.round}</td><td class="small">${esc(q.purpose)}</td><td><span class="mono">${esc(q.query)}</span> <span class="small muted">p${q.page}</span>
      ${q.error ? `<div class="small" style="color:var(--bad)">${esc(q.error)}</div>` : ""}
      <details><summary class="small">${q.results.length} results</summary>${q.results.map((r) => `<div class="small" style="margin:3px 0"><span class="badge ${r.fetched ? "ok" : ""}">${r.fetched ? t("fetched") : t("not_fetched")}</span>
        <span class="badge">id ${Number(r.identity_score).toFixed(2)}</span> <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title || r.url)}</a><div class="muted">${esc((r.snippet || "").slice(0, 200))}</div></div>`).join("")}</details></td>
      <td><span class="badge ${q.provider === "TEST-FIXTURE" ? "bad" : ""}">${esc(q.provider)}</span></td><td><span class="badge ${q.status === "ok" ? "ok" : "bad"}">${esc(q.status)}</span> ${q.result_count}</td></tr>`).join("") ||
    `<tr><td colspan="5" class="muted">${t("none")}</td></tr>`}</tbody></table></div>
    <p class="small muted">${LANG === "zh" ? "搜索摘要只是发现线索，不代表已读取全文。“id”为事件身份匹配分数（名称、地点、年份）。" : "Snippets are discovery leads, not evidence of full-text reading. 'id' = identity match score (name, location, year)."}</p>`;
}

// ------------------------------------------------------------------ export & runs
async function tabExport(c, body) {
  const u = await api("GET", `/api/cases/${c.id}/usage`);
  const link = (fmt, unrev) => `/api/cases/${c.id}/export?format=${fmt}&unreviewed=${unrev ? 1 : 0}`;
  const btns = (unrev) => ["xlsx", "tsv", "caserow", "json"].map((f) => `<a href="${link(f, unrev)}"><button class="${unrev ? "" : "primary"}">${{ xlsx: "Excel (XLSX)", tsv: "TSV 4-col", caserow: "Case row (XLSX)", json: "JSON" }[f]}</button></a>`).join(" ");
  body.innerHTML = `<div class="grid2"><div class="panel"><h3 style="margin-top:0">${t("exp_title")}</h3>
      <p><b>${t("exp_reviewed")}</b></p><div class="row">${btns(false)}</div>
      <p style="margin-top:16px"><b>${t("exp_unrev")}</b></p><div class="callout warn small">${LANG === "zh" ? "未复核的建议会标为 UNREVIEWED（文件名、说明列和黄色底色）。" : "Unreviewed suggestions are marked UNREVIEWED (file name, explanation column, yellow fill)."}</div><div class="row">${btns(true)}</div>
      <p class="small muted">${LANG === "zh" ? "导出保留全部字段、原顺序和真正的空白；不会修改原始工作簿。多选编码以文本写入，避免 Excel 把“1, 3”自动变成日期。" : "Exports keep all fields in workbook order with genuine blanks; the original workbook is never modified. Multi-codes are written as text so Excel cannot turn '1, 3' into a date."}</p></div>
    <div class="panel"><h3 style="margin-top:0">${t("usage")}</h3><div class="kv">
      <div>Model cost</div><div>${money(u.totals.model_usd)}</div><div>Tokens in / out</div><div>${u.totals.input_tokens.toLocaleString()} / ${u.totals.output_tokens.toLocaleString()}</div>
      <div>Search queries billed</div><div>${u.totals.search_queries_billed}</div><div>Search cost</div><div>${u.totals.search_price_unknown ? (LANG === "zh" ? "未知（未填写单价）" : "unknown (price not configured)") : money(u.totals.search_usd)}</div></div>
      <h3>${t("runs")}</h3>${u.runs.map((r) => `<div class="small">run ${r.id} · ${esc(r.mode)} · ${esc(r.model || "")} · schema v${r.schema_version_id} · ${fmtTime(r.created_at)}</div>`).join("") || t("none")}
      <div class="row" style="margin-top:10px"><button id="reBtn">${t("recode")}</button></div></div></div>`;
  $("#reBtn").onclick = (ev) => startRecode(c.id, null, ev.currentTarget);
}

// ------------------------------------------------------------------ schema
async function renderSchema() {
  const vers = await api("GET", "/api/schemas");
  const act = vers.find((v) => v.active) || vers[0];
  const s = act ? await api("GET", `/api/schemas/${act.id}`) : null;
  let issuesOnly = false;
  app.innerHTML = `<h1>${t("schema_title")}</h1><p class="sub">${t("schema_sub")}</p>
    <div class="grid2"><div class="panel"><h3 style="margin-top:0">${t("versions")}</h3>${vers.map((v) => `<div class="row small" style="margin:4px 0">${v.active ? `<span class="badge ok">${t("active")}</span>` : `<button class="small" data-act="${v.id}">${t("activate")}</button>`}
      <b>v${v.id}</b> ${esc(v.label)} <span class="muted">${fmtTime(v.created_at)} ${esc(v.change_note || "")}</span></div>`).join("")}</div>
    <div class="panel"><h3 style="margin-top:0">${t("upload_schema")}</h3><label>${t("codebook_file")}</label><input type="file" id="cbF" accept=".docx,.txt,.md">
      <label>${t("workbook_file")}</label><input type="file" id="wbF" accept=".xlsx"><label><input type="checkbox" id="actF" style="width:auto" checked> ${t("activate")}</label>
      <button class="primary" id="upBtn" style="margin-top:8px">${t("upload_schema")}</button></div></div>
    ${s ? `<div class="panel" style="margin-top:12px"><div class="row"><h3 style="margin:0">${t("mapping")} — ${esc(s.label)}</h3><span class="spacer"></span>
      <span class="small">${s.stats.n_fields} fields · ${s.stats.n_mapped} mapped · ${s.stats.n_rule_missing} rule missing · ${s.stats.n_with_issues} with issues${s.codebook_only?.length ? ` · codebook-only: ${esc(s.codebook_only.join(", "))}` : ""}</span>
      <label style="margin:0 0 0 10px"><input type="checkbox" id="issOnly" style="width:auto"> ${t("issues_only")}</label></div>
      <div style="max-height:65vh;overflow:auto;margin-top:8px"><table><thead><tr><th>#</th><th>Workbook header</th><th>Mapping</th><th>Type</th><th>Class</th><th>Codes</th><th>Issues</th><th></th></tr></thead><tbody id="mapRows"></tbody></table></div></div>` : ""}`;
  $$("[data-act]").forEach((b) => (b.onclick = async () => { await api("POST", `/api/schemas/${b.dataset.act}/activate`); renderSchema(); }));
  $("#upBtn").onclick = async () => {
    const cb = $("#cbF").files[0], wb = $("#wbF").files[0];
    if (!cb || !wb) return toast("codebook + workbook", true);
    try { const r = await api("POST", "/api/schemas", { codebook: { filename: cb.name, data: await fileToB64(cb) }, workbook: { filename: wb.name, data: await fileToB64(wb) }, activate: $("#actF").checked });
      toast(`v${r.id}: ${r.stats.n_fields} fields, ${r.stats.n_with_issues} with issues`); renderSchema(); } catch (e) { toast(e.message, true); }
  };
  if (!s) return;
  const draw = () => {
    $("#mapRows").innerHTML = s.fields.filter((f) => !issuesOnly || f.issues.length).map((f) => `<tr><td class="small">${f.position}</td><td class="mono small">${esc(f.raw_header || "(blank)")}</td>
      <td><span class="badge ${f.mapping === "exact" ? "ok" : f.mapping === "none" ? "bad" : "warn"}">${esc(f.mapping)}</span><div class="small muted">${esc(f.codebook_name || "")}</div></td>
      <td class="small">${esc(f.type)}${f.multi ? " · multi" : ""}${f.missing_codes?.length ? " · " + esc(f.missing_codes.join(",")) : ""}</td><td class="small">${esc(f.field_class)}</td>
      <td class="small">${f.codes.map((c) => esc(c.code)).join(", ")}</td><td class="small">${f.issues.map((i) => `<div>• ${esc(i)}</div>`).join("")}</td>
      <td><button class="small" data-edit="${esc(f.name)}">${t("edit_rule")}</button></td></tr>`).join("");
    $$("[data-edit]").forEach((b) => (b.onclick = () => editRule(s, s.fields.find((f) => f.name === b.dataset.edit))));
  };
  $("#issOnly").onchange = (e) => { issuesOnly = e.target.checked; draw(); };
  draw();
}
function editRule(s, f) {
  $("#modalRoot").innerHTML = `<div class="modal-bg"><div class="modal"><header><b class="mono">${esc(f.name)}</b><span class="spacer"></span><button id="mClose">${t("close")}</button></header><div class="body">
    <div class="callout info small">${LANG === "zh" ? "修改会生成新的规则版本（旧版本保留），并设为当前版本。已完成的分析记录其使用的版本。" : "Saving creates a new schema version (old versions are kept) and activates it. Past runs record the version they used."}</div>
    <label>Definition</label><textarea id="rDef">${esc(f.definition || "")}</textarea>
    <div class="grid3"><div><label>Type</label><select id="rType">${["categorical", "open_list", "numeric", "date", "text"].map((x) => `<option ${x === f.type ? "selected" : ""}>${x}</option>`).join("")}</select></div>
    <div><label>Multi-select</label><select id="rMulti"><option value="0">no</option><option value="1" ${f.multi ? "selected" : ""}>yes</option></select></div>
    <div><label>Class</label><select id="rClass">${["sourced", "judgment", "derived", "admin", "analyst_note", "unmapped"].map((x) => `<option ${x === f.field_class ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>
    <label>Codes (one per line: code = label)</label><textarea id="rCodes" style="min-height:120px">${esc(f.codes.map((c) => `${c.code} = ${c.label}`).join("\n"))}</textarea>
    <label>Special missing values for this variable (comma-separated, e.g. -9; empty = none)</label><input id="rMiss" value="${esc((f.missing_codes || []).join(", "))}">
    ${f.issues.length ? `<label>Mark issues as resolved</label>${f.issues.map((i, k) => `<label style="display:flex;gap:6px;color:var(--ink)"><input type="checkbox" class="rIss" data-k="${k}" style="width:auto">${esc(i)}</label>`).join("")}` : ""}
    <label>${t("change_note")} *</label><input id="rNote" placeholder="e.g. PI confirmed FAILURE_TYPE allows secondary codes (meeting 2026-10-02)">
    <div class="row" style="margin-top:10px"><button class="primary" id="rSave">${t("save")}</button></div></div></div></div>`;
  $("#mClose").onclick = () => ($("#modalRoot").innerHTML = "");
  $("#rSave").onclick = async () => {
    if (!$("#rNote").value.trim()) return toast(t("change_note"), true);
    const codes = $("#rCodes").value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf("="); return i > 0 ? { code: l.slice(0, i).trim(), label: l.slice(i + 1).trim() } : { code: l, label: "" }; });
    const resolve = $$(".rIss").filter((x) => x.checked).map((x) => f.issues[+x.dataset.k]);
    try {
      await api("PUT", `/api/schemas/${s.id}/fields/${encodeURIComponent(f.name)}`, { definition: $("#rDef").value, type: $("#rType").value, multi: $("#rMulti").value === "1",
        field_class: $("#rClass").value, codes, missing_codes: $("#rMiss").value.split(",").map((x) => x.trim()).filter(Boolean), resolve_issues: resolve, change_note: $("#rNote").value });
      $("#modalRoot").innerHTML = ""; toast(t("saved")); renderSchema();
    } catch (e) { toast(e.message, true); }
  };
}

// ------------------------------------------------------------------ settings
async function renderSettings() {
  const s = STATUS.settings, k = STATUS.secrets;
  const yn = (b) => `<span class="badge ${b ? "ok" : ""}">${b ? t("yes") : t("no")}</span>`;
  app.innerHTML = `<h1>${t("settings_title")}</h1>
  <div class="grid2"><div class="panel"><h3 style="margin-top:0">${t("keys_title")}</h3><p class="small muted">${t("keys_help")}</p>
    <div class="kv">${Object.entries(k).map(([n, v]) => `<div class="mono">${esc(n)}</div><div>${yn(v)}</div>`).join("")}</div>
    <h3>${t("services")}</h3>${serviceList()}
    <p class="small muted">Data folder: <span class="mono">${esc(STATUS.data_dir)}</span></p></div>
  <div class="panel"><h3 style="margin-top:0">${t("defaults")}</h3><div class="grid2">
    ${[["search_provider", ["auto", "tavily", "brave", "searxng", "none"]], ["model_provider", ["auto", "anthropic", "openai", "none"]]].map(([n, opts]) => `<div><label>${n}</label><select data-set="${n}">${opts.map((o) => `<option ${s[n] === o ? "selected" : ""}>${o}</option>`).join("")}</select></div>`).join("")}
    ${["model_name", "max_search_rounds", "max_queries", "pages_per_query", "results_per_query", "max_fetch", "time_limit_minutes", "budget_usd", "passages_per_variable", "max_passages_per_call"].map((n) => `<div><label>${n}</label><input data-set="${n}" value="${esc(s[n])}"></div>`).join("")}
    <div><label>coding_mode</label><select data-set="coding_mode">${availModes().map((m) => `<option value="${esc(m.mode)}" ${s.coding_mode === m.mode ? "selected" : ""}>${esc(modeText(m.mode))}</option>`).join("")}</select></div>
    <div><label>max_model_attempts_per_case</label><input data-set="max_model_attempts_per_case" value="${esc(s.max_model_attempts_per_case)}"></div>
    ${STATUS.providers && STATUS.providers.openai.configured ? `
    <div><label>openai_budget_usd</label><input data-set="openai_budget_usd" value="${esc(s.openai_budget_usd)}"></div>
    <div><label>max_openai_attempts_per_case</label><input data-set="max_openai_attempts_per_case" value="${esc(s.max_openai_attempts_per_case)}"></div>
    <div><label>openai_reasoning_effort</label><select data-set="openai_reasoning_effort">${["low", "medium", "high", "xhigh", "max"].map((o) => `<option ${s.openai_reasoning_effort === o ? "selected" : ""}>${o}</option>`).join("")}</select></div>
    <div><label>openai_reasoning_reserve_tokens</label><input data-set="openai_reasoning_reserve_tokens" value="${esc(s.openai_reasoning_reserve_tokens)}"></div>
    <div><label>openai_max_output_tokens</label><input data-set="openai_max_output_tokens" value="${esc(s.openai_max_output_tokens)}"></div>
    <div><label>openai_timeout_seconds</label><input data-set="openai_timeout_seconds" value="${esc(s.openai_timeout_seconds)}"></div>` : ""}
    <div><label>follow_links</label><select data-set="follow_links"><option value="true" ${s.follow_links ? "selected" : ""}>true</option><option value="false" ${!s.follow_links ? "selected" : ""}>false</option></select></div>
    <div><label>require_approval_over_budget</label><select data-set="require_approval_over_budget"><option value="true" ${s.require_approval_over_budget ? "selected" : ""}>true</option><option value="false" ${!s.require_approval_over_budget ? "selected" : ""}>false</option></select></div>
    </div><button class="primary" id="saveSet" style="margin-top:10px">${t("save_settings")}</button>
    <p class="small muted">${LANG === "zh" ? "max_passages_per_call 是每次模型调用的批量大小，不是上限：证据更多时会分成更多批次。" : "max_passages_per_call is a batch size, not a cap: more evidence means more calls."}</p>
    <p class="small muted">${L("OpenAI 模型由服务器环境变量 OPENAI_MODEL 决定（默认 gpt-6.1-sol）。新案例使用这里的默认值；已有案例保留创建时的设置，上限可在暂停时按明确数值提高。", "The OpenAI model is set by the server's OPENAI_MODEL environment variable (default gpt-6.1-sol). New cases use these defaults; existing cases keep the settings they were created with, and their limits can be raised to explicit values when a run pauses.")}</p></div></div>
  <div class="panel" style="margin-top:12px"><h3 style="margin-top:0">${t("pricing")}</h3><p class="small muted">${LANG === "zh" ? "应用不会联网获取实时价格。请按你的账户价格修改（美元）。" : "The app never fetches live prices. Edit to match your account (USD)."}</p>
    <textarea id="priceJson" style="min-height:260px" class="mono">${esc(JSON.stringify(STATUS.pricing, null, 2))}</textarea><button id="savePrice" style="margin-top:6px">${t("save")}</button></div>`;
  $("#saveSet").onclick = async () => {
    const body = {};
    $$("[data-set]").forEach((el) => { let v = el.value; if (v === "true" || v === "false") v = v === "true"; else if (!isNaN(+v) && v !== "" && !["model_name"].includes(el.dataset.set)) v = +v; body[el.dataset.set] = v; });
    try { await api("PUT", "/api/settings", body); toast(t("saved")); route(); } catch (e) { toast(e.message, true); }
  };
  $("#savePrice").onclick = async () => { try { await api("PUT", "/api/pricing", JSON.parse($("#priceJson").value)); toast(t("saved")); } catch (e) { toast(e.message, true); } };
}

applyStaticText();
route();
