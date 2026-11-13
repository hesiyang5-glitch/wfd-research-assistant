// WFD Coding Assistant — single-page app (no build step).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = $("#app");
let STATUS = null, POLL = null;
const WB = { filter: "all", q: "", sel: null, data: null, section: "" };
const L = (zh, en) => (LANG === "zh" ? zh : en);
// Display names only (2026-10-06, label-only change): provider = company, API = programming interface, model = the
// identifier the backend already supplies. Internal ids (anthropic / openai), roles and modes are unchanged.
// coder names (owner rule 2026-10-07): the model family that codes — Claude / GPT. "OpenAI" stays where the company,
// account, API or bill is meant (OpenAI API, OpenAI coding budget, OpenAI request limit, OPENAI_* settings).
const PROV = { anthropic: "Claude", openai: "GPT", openai_compatible: "OpenAI-compatible" };
const PROV_API = { anthropic: "Anthropic API", openai: "OpenAI API", openai_compatible: "OpenAI-compatible API" };
const provApi = (p) => (PROV[p] ? `${PROV[p]} — ${PROV_API[p]}` : p);                       // "Claude — Anthropic API"
// coding lines name the model family (owner choice 2026-10-06): "Claude coding — Anthropic API", "GPT coding — OpenAI API"
const CODER = { anthropic: "Claude", openai: "GPT", openai_compatible: "OpenAI-compatible" };
const provCoding = (p) => (CODER[p] ? `${CODER[p]} ${L("编码", "coding")} — ${PROV_API[p]}` : p);
const SEARCH_API = { tavily: "Tavily Search API", brave: "Brave Search API", searxng: "SearXNG" };
const searchName = (n) => SEARCH_API[n] || n;
// model identifiers already supplied by /api/status (Claude: the model_name setting; OpenAI: OPENAI_MODEL on the server)
const provModel = (p) => (p === "anthropic" ? ((STATUS || {}).settings || {}).model_name : ((((STATUS || {}).providers || {}).openai) || {}).model) || "";
const ABBR = { API: ["应用程序编程接口", "Application Programming Interface"], OCR: ["光学字符识别", "Optical Character Recognition"], LSA: ["潜在语义分析", "Latent Semantic Analysis"], BM25: ["BM25 排序算法（Best Matching 25）", "Best Matching 25 ranking algorithm"] };
const abbr = (a) => `<abbr title="${esc(L(ABBR[a][0], ABBR[a][1]))}">${a}</abbr>`;
// Coding-provider choices (D-036): Claude and OpenAI are EQUAL independent providers; the human decides the final value.
const MODE_TEXT = {
  single: ["一个模型（旧案例的默认设置）", "One provider (default of older cases)"],
  anthropic_only: ["仅 Claude — Anthropic API", "Claude only — Anthropic API"],
  openai_only: ["仅 GPT — OpenAI API", "GPT only — OpenAI API"],
  dual_independent: ["Claude + GPT — 独立比较", "Claude + GPT — independent comparison"],
  anthropic_primary_openai_review: ["跨模型复核（历史记录，仅供审核）", "Cross-model review (historical, audit only)"],
  openai_primary_anthropic_review: ["跨模型复核（历史记录，仅供审核）", "Cross-model review (historical, audit only)"],
};
const MODE_HELP = {
  anthropic_only: ["做一次共享研究，然后由 Claude 编码。", "One shared research process, followed by coding with Claude."],
  openai_only: ["做一次共享研究，然后由 GPT 编码。", "One shared research process, followed by coding with GPT."],
  dual_independent: ["两个模型各自独立分析同样的现有证据，彼此看不到对方的答案。为了保持服务器响应，请求可能会依次处理。", "Both providers independently analyze the same available evidence. Requests may be processed sequentially to protect server responsiveness."],
};
const DUAL_NEUTRAL = ["两个模型各自独立分析同样的现有证据，不区分主次。", "Both providers independently analyze the same available evidence. Neither provider is labeled as primary or secondary."];
const DUAL_SEQ = ["为了保持服务器响应，请求可能会依次处理。", "Requests may be processed sequentially to protect server responsiveness."];
function modeModelsHtml(mode) {
  // model identifiers for a coding-provider choice (display only)
  const line = (p, withApi) => `<span class="small mono pmodel">${withApi ? `${esc(PROV[p])}: ${esc(PROV_API[p])} · ` : `${L("模型", "Model")}: `}<span class="nowrap">${esc(provModel(p) || "—")}</span></span>`;
  if (mode === "anthropic_only") return line("anthropic", false);
  if (mode === "openai_only") return line("openai", false);
  if (mode === "dual_independent") return line("anthropic", true) + line("openai", true);
  return "";
}
const modeText = (m) => (MODE_TEXT[m] ? L(MODE_TEXT[m][0], MODE_TEXT[m][1]) : m);
const modeHelp = (m) => (MODE_HELP[m] ? L(MODE_HELP[m][0], MODE_HELP[m][1]) : "");
const INTERP_TEXT = { independent: ["独立结果", "independent result"], cross_model_review: ["跨模型复核（看过另一模型的答案，仅供审核）", "cross-model review (saw the other model's answer — audit only)"] };
const interpText = (r) => (INTERP_TEXT[r] ? L(INTERP_TEXT[r][0], INTERP_TEXT[r][1]) : (r || ""));
const COMP_BADGE = { model_agreement: "ok", value_disagreement: "bad", evidence_disagreement: "warn", one_provider_blank: "warn", invalid_provider_output: "bad", needs_human_review: "dispute", human_approved: "ok" };
const COMP_TEXT = { model_agreement: ["模型一致", "Model agreement"], value_disagreement: ["取值不一致", "Value disagreement"], evidence_disagreement: ["证据不一致", "Evidence disagreement"], one_provider_blank: ["一方为空", "One provider blank"], invalid_provider_output: ["模型输出无效", "Invalid provider output"], both_insufficient: ["均证据不足", "Both insufficient"], needs_human_review: ["需人工复核", "Needs human review"], human_approved: ["人工已确认", "Human approved"] };
const compText = (c) => (COMP_TEXT[c] ? L(COMP_TEXT[c][0], COMP_TEXT[c][1]) : c);
const CELL_TEXT = { not_run: ["未运行", "Not run"], suggested: ["建议", "Suggested"], disputed: ["有争议", "Disputed"], partially_valid: ["部分有效", "Partially valid"], no_supported_value: ["无证据支持的值", "No supported value"], stopped: ["已停止", "Stopped"], failed: ["失败", "Failed"], invalid_output: ["输出无效", "Invalid output"], limit_reached: ["达到上限，未编码", "Limit reached"] };
const cellText = (st) => (CELL_TEXT[st] ? L(CELL_TEXT[st][0], CELL_TEXT[st][1]) : st);
// D-038: evidence status (how well the evidence supports the value) is separate from validation status (whether the
// reply passed the server checks). Older results have no evidence status: shown as "not recorded".
const ES_TEXT = { SUPPORTED: ["证据直接支持", "Supported"], INFERRED: ["推断", "Inferred"], AMBIGUOUS: ["有歧义", "Ambiguous"], INSUFFICIENT: ["证据不足", "Insufficient"], CONFLICTING: ["证据冲突", "Conflicting"], MIXED: ["各模型不同", "Differs by model"] };
const ES_HELP = { SUPPORTED: ["引用的证据直接满足编码手册定义", "The cited evidence directly satisfies the codebook definition"], INFERRED: ["最可能的解释，但需要证据未直接确立的推断；不会自动成为最终值", "Best interpretation, but it needs an inference the evidence does not directly establish; never becomes a final value automatically"], AMBIGUOUS: ["不止一个允许值都有合理依据", "More than one permitted value remains reasonably supported"], INSUFFICIENT: ["证据不足以确立可辩护的值", "The evidence does not establish a defensible value"], CONFLICTING: ["可信证据支持互不相容的解释", "Credible evidence supports incompatible interpretations"] };
const ES_BADGE = { SUPPORTED: "ok", INFERRED: "info", AMBIGUOUS: "warn", INSUFFICIENT: "", CONFLICTING: "bad", MIXED: "warn" };
const VS_TEXT = { valid: ["通过验证", "Valid"], partially_valid: ["部分通过验证", "Partially valid"], invalid: ["未通过验证", "Invalid"], not_applicable: ["不适用", "Not applicable"] };
const esText = (es) => (es ? (ES_TEXT[es] ? L(ES_TEXT[es][0], ES_TEXT[es][1]) : es) : L("未记录", "not recorded"));
const vsText = (vs) => (VS_TEXT[vs] ? L(VS_TEXT[vs][0], VS_TEXT[vs][1]) : (vs || L("未记录", "not recorded")));
function esBadge(es, recorded) {
  if (!es && !recorded) return "";
  return ` <span class="badge ${ES_BADGE[es] || "warn"} es-badge" data-es="${esc(es || "missing")}" title="${esc(ES_HELP[es] ? L(ES_HELP[es][0], ES_HELP[es][1]) : L("回复未给出证据状态", "The reply gave no evidence status"))}">${esc(esText(es))}</span>`;
}
// D-039 (owner decisions 2026-11-12): which meaning a model's -9 has
const MR_TEXT = { unknown: ["未知（所读资料未提及）", "Unknown (not mentioned in the sources read)"], not_applicable: ["不适用", "Not applicable"], not_stated: ["未说明（规则生效前保存）", "not stated (saved before the -9 reason rule)"], not_documented: ["未记录（所读资料未提及）", "Not documented (nothing found in the sources read)"] };
const mrBadge = (r) => (r && MR_TEXT[r] ? ` <span class="badge wrap ${r === "not_stated" ? "" : "info"} mr-badge" data-mr="${esc(r)}" title="${esc(L("缺失/未记录编码的含义", "Meaning of the missing / absence code"))}">${esc(L(MR_TEXT[r][0], MR_TEXT[r][1]))}</span>` : "");
function statusLines(m) {
  // evidence status and validation status, always shown as two separate facts
  const alts = (m.alternatives || []);
  return `<div class="small es-lines"><b>${L("证据状态", "Evidence status")}:</b> ${esc(esText(m.evidence_status))}${m.evidence_status && ES_HELP[m.evidence_status] ? ` <span class="muted">— ${esc(L(ES_HELP[m.evidence_status][0], ES_HELP[m.evidence_status][1]))}</span>` : (!m.evidence_recorded ? ` <span class="muted">${L("（此结果早于证据状态功能）", "(result predates evidence statuses)")}</span>` : "")}
    · <b>${L("验证状态", "Validation status")}:</b> ${esc(vsText(m.validation_state))}</div>
    ${alts.length ? `<div class="small"><b>${L("其他候选值", "Alternative values")}:</b> ${alts.map((a) => `<span class="mono">${esc(a.value)}</span>${a.provider ? ` (${esc(PROV[a.provider] || a.provider)})` : ""} [${(a.evidence || []).map((e) => esc(e.id)).join(", ")}]`).join("; ")}</div>` : ""}
    ${m.missing_reason ? `<div class="small"><b>${L("缺失/未记录编码的含义", "Meaning of the missing / absence code")}:</b>${mrBadge(m.missing_reason)}</div>` : ""}
    ${m.missing_evidence ? `<div class="small"><b>${L("缺少的证据", "Missing evidence")}:</b> ${esc(m.missing_evidence)}</div>` : ""}
    ${m.evidence_review_reason ? `<div class="small muted">${L("不会作为未复核值导出或用于推导字段", "Not exported as an unreviewed value or used for derived fields")}: ${esc(m.evidence_review_reason)}</div>` : ""}`;
}
function cellHtml(cell, row) {
  // One provider's cell. Each state has its own look so "not run", "no supported value", "stopped", "failed" and
  // "invalid output" can never be mistaken for one another or for a real value.
  const c = cell || { state: "not_run" };
  const stopNote = c.stopped_latest ? `<div><span class="cell-tag st-stopped">⏸ ${esc(L("最近一次已停止", "latest run stopped"))}</span></div>` : "";
  const roleNote = c.interpretation === "cross_model_review" ? ` <span class="badge warn" title="${esc(interpText("cross_model_review"))}">${L("跨模型复核", "cross-model")}</span>` : "";
  const esTag = ["suggested", "disputed", "partially_valid", "no_supported_value"].includes(c.state) ? esBadge(c.evidence_status, c.evidence_recorded) : "";
  if (["suggested", "disputed", "partially_valid"].includes(c.state) && c.value) {
    return `<div class="cell-val st-${c.state}"><span class="mono">${esc(c.value.slice(0, 48))}</span>${mrBadge(c.missing_reason)}${esTag}${c.state === "disputed" ? ` <span class="cell-tag st-disputed">${esc(cellText("disputed"))}</span>` : ""}${c.state === "partially_valid" ? ` <span class="cell-tag st-invalid_output" title="${esc(L("部分选项未通过验证，已被拒绝；保留的是有证据支持的选项", "Some selections failed validation and were rejected; the supported selections are kept"))}">${esc(cellText("partially_valid"))}</span>` : ""}${c.changed ? ` <span class="badge warn" title="${esc(L("上次", "previous") + ": " + (c.previous_value || "∅"))}">Δ</span>` : ""}${roleNote}</div>${stopNote}`;
  }
  const icon = { not_run: "—", no_supported_value: "∅", stopped: "⏸", failed: "✕", invalid_output: "⚠", limit_reached: "⛔", disputed: "≠" }[c.state] || "";
  return `<span class="cell-tag st-${esc(c.state)}">${icon} ${esc(cellText(c.state))}</span>${esTag}${roleNote}${stopNote}`;
}
const availModes = () => (STATUS.modes || []).filter((m) => m.available);
function providerCostRows(e) {
  return (e.providers || []).map((p) => `<div>${esc(provCoding(p.provider))}<br><span class="small muted">${esc(PROV[p.provider] || p.provider)} ${L("模型", "model")}: <span class="mono">${esc(p.model)}</span></span>${p.reasoning_effort ? `<br><span class="small muted" title="${esc(L("GPT 模型可以使用的内部推理量；越高可能越贵。", "How much internal reasoning the GPT model may use; higher can cost more."))}">${L("OpenAI 推理强度", "OpenAI reasoning effort")}: ${esc(p.reasoning_effort)}</span>` : ""}</div>
    <div>${p.calls != null ? `${p.calls} ${L("次请求", "request(s)")}${p.calls_uncached != null ? ` · ${L("缓存请求", "Cached requests")} ${p.calls - p.calls_uncached} · ${L("新的付费请求", "New paid requests")} ${p.calls_uncached}` : ""}<br>` : ""}${costPair(p.cost_low, p.cost_high)}${p.price_note ? ` <span class="badge warn" title="${esc(p.price_note)}">${L("价格需核对", "check price")}</span>` : ""}</div>`).join("");
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
  // language switch shows which language is active (display only)
  $("#langBtn").innerHTML = `<span class="${LANG === "en" ? "on" : "off"}">EN</span><span class="sep">/</span><span class="${LANG === "zh" ? "on" : "off"}">中文</span>`;
  $("#langBtn").title = L("切换界面语言", "Switch interface language");
  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  const tb = $("#themeBtn");
  if (tb) {
    tb.textContent = dark ? "☀" : "☾";
    tb.title = dark ? L("切换到浅色界面", "Switch to light theme") : L("切换到深色界面", "Switch to dark theme");
    tb.setAttribute("aria-label", tb.title);
  }
}
$("#langBtn").onclick = () => { setLang(LANG === "zh" ? "en" : "zh"); applyStaticText(); route(); };
// display theme only: stored in this browser, never sent to the server
if ($("#themeBtn")) $("#themeBtn").onclick = () => {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("wfd_theme", next); } catch (e) {}
  applyStaticText();
};
// variable names break only after an underscore, never in the middle of a word (display only)
const varName = (n) => esc(n).replace(/_/g, "_<wbr>");
const JOB_TEXT = { done: ["已完成", "Done"], running: ["运行中", "Running"], queued: ["排队中", "Queued"], needs_input: ["需要你处理", "Needs your input"], failed: ["失败", "Failed"], cancelled: ["已取消", "Cancelled"] };
const CASE_TEXT = { new: ["新建", "New"], review: ["待复核", "In review"], needs_sources: ["需要资料", "Sources needed"], sources_ready: ["来源已就绪（未分析）", "Sources ready (not analyzed)"] };
const stText = (map, s) => (map[s] ? L(map[s][0], map[s][1]) : s);
// D-045: search and analysis statuses, shown separately
const SEARCH_ST = { not_started: ["未开始", "not started", ""], running: ["进行中", "running", "info"], waiting: ["等待你的操作", "waiting for you", "warn"],
  complete: ["完成", "complete", "ok"], partial: ["完成（部分来源未能读取）", "complete — partial retrieval", "warn"],
  no_usable_content: ["没有可用内容", "no usable content", "warn"], failed: ["失败", "failed", "bad"], stopped: ["已停止", "stopped", ""] };
const ANALYSIS_ST = { not_requested: ["未请求", "not requested", ""], waiting_for_search: ["等待搜索完成", "waiting for search", "info"],
  running: ["进行中", "running", "info"], waiting: ["等待你的操作", "waiting for you", "warn"], complete: ["完成", "complete", "ok"],
  failed: ["失败", "failed", "bad"], stopped: ["已停止", "stopped", ""], not_run_no_content: ["未运行（没有可用内容）", "not run — no usable content", "warn"] };
function statusPills(sts) {
  if (!sts) return "";
  const s = SEARCH_ST[sts.search] || [sts.search, sts.search, ""], a = ANALYSIS_ST[sts.analysis] || [sts.analysis, sts.analysis, ""];
  return `<span class="badge ${s[2]}" title="${esc(sts.search)}">${L("搜索", "Search")}: ${esc(L(s[0], s[1]))}</span> <span class="badge ${a[2]}" title="${esc(sts.analysis)}">${L("分析", "Analysis")}: ${esc(L(a[0], a[1]))}</span>`;
}

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

// Settings display labels (label-only, 2026-10-06). The setting keys, values, defaults and save behaviour are unchanged;
// the internal key is kept only as a tooltip so researchers can still match it to the documentation.
const SET_LABELS = {
  search_provider: ["搜索服务", "Search service"],
  model_provider: ["已配置的模型提供方", "Configured model provider", "仅用于旧案例的“一个模型”设置（自动 = 有 Claude 密钥时用 Claude，否则用 OpenAI）。", "Used only by the older 'One provider' setting of existing cases (automatic = Claude when its key is configured, otherwise OpenAI)."],
  model_name: ["已配置的模型", "Configured model", "通过 Anthropic API 调用的 Claude 模型标识。OpenAI 模型由服务器的 OPENAI_MODEL 决定。", "Claude model identifier used with the Anthropic API. The OpenAI model is set on the server by OPENAI_MODEL."],
  max_search_rounds: ["最多搜索轮次", "Maximum search rounds"],
  max_queries: ["最多搜索次数", "Maximum search queries"],
  pages_per_query: ["每个搜索词的结果页数", "Pages per search query"],
  results_per_query: ["每个搜索词的结果数", "Results per search query"],
  max_fetch: ["最多读取的页面数", "Maximum pages to retrieve"],
  time_limit_minutes: ["研究时间上限（分钟）", "Research time limit (minutes)"],
  budget_usd: ["研究预算上限（美元）", "Research budget limit (USD)", "每个案例的总上限：所有模型编码 + 网页搜索，包含所有重新运行。", "Per case: all coding providers + web search, across every re-run."],
  passages_per_variable: ["每个变量的证据段落数", "Evidence passages per variable"],
  max_passages_per_call: ["每次模型请求的证据段落数", "Evidence passages per model request"],
  coding_mode: ["编码模型选择", "Coding-provider selection"],
  max_model_attempts_per_case: ["每个案例的模型请求上限", "Model-request limit per case", "发送给任何模型提供方的全部请求，包括重试和重新运行。", "Every request sent to any coding provider, including retries and re-runs."],
  openai_budget_usd: ["每个案例的 OpenAI 编码预算（美元）", "OpenAI coding budget per case (USD)", "包含在研究预算上限之内。", "Counted inside the research budget limit."],
  max_openai_attempts_per_case: ["每个案例的 OpenAI 请求上限", "OpenAI request limit per case"],
  openai_reasoning_effort: ["OpenAI 推理强度", "OpenAI reasoning effort", "GPT 模型可以使用的内部推理量；越高可能越贵。", "How much internal reasoning the GPT model may use; higher can cost more."],
  openai_reasoning_reserve_tokens: ["OpenAI 推理 token 额度", "OpenAI reasoning-token allowance", "加在可见输出额度之上的推理额度（推理也按输出计费）。", "Added to the visible-output allowance; reasoning counts as output."],
  openai_max_output_tokens: ["OpenAI 每次请求的最多输出 token", "OpenAI maximum output tokens per request"],
  openai_timeout_seconds: ["OpenAI 请求超时（秒）", "OpenAI request timeout (seconds)", "每次请求的读取超时；超时的请求不会自动重试。", "Per-request read timeout; a timed-out request is never retried."],
  follow_links: ["跟进来源中的链接", "Follow links found in sources"],
  require_approval_over_budget: ["超出预算时暂停并请求批准", "Pause for approval when over budget"],
};
const OPT_LABELS = {
  search_provider: { auto: ["自动（第一个已配置的服务）", "Automatic (first configured service)"], tavily: ["Tavily Search API", "Tavily Search API"], brave: ["Brave Search API", "Brave Search API"], searxng: ["SearXNG", "SearXNG"], none: ["无（只用手动资料）", "None (manual sources only)"] },
  model_provider: { auto: ["自动", "Automatic"], anthropic: ["Anthropic API（Claude）", "Anthropic API (Claude)"], openai: ["OpenAI API", "OpenAI API"], none: ["无（人工编码）", "None (manual coding)"] },
};
const optLabel = (n, o) => ((OPT_LABELS[n] || {})[o] ? L(OPT_LABELS[n][o][0], OPT_LABELS[n][o][1]) : o);
function setLabel(n) {
  const d = SET_LABELS[n];
  if (!d) return `<label>${esc(n)}</label>`;
  return `<label title="${esc(n)}">${esc(L(d[0], d[1]))}</label>${d[2] ? `<div class="small muted set-help">${esc(L(d[2], d[3]))}</div>` : ""}`;
}

// ------------------------------------------------------------------ home
function serviceList() {
  const s = STATUS;
  // Same status detection as before; only the wording and grouping changed (label-only, 2026-10-06).
  const li = (ok, label, text) => `<li><span class="dot ${ok}"></span><b>${label}</b> — ${text}</li>`;
  const prov = (ok, p, model, status) => `<li class="svc-prov" data-svc="${p}"><span class="dot ${ok}"></span><b>${esc(CODER[p])} ${L("编码", "coding")}</b> — ${esc(PROV[p] === "Claude" ? "Anthropic" : "OpenAI")} ${abbr("API")}
      <div class="small svc-sub">${L("模型", "Model")}: <span class="mono">${esc(model || "—")}</span><br>${L("状态", "Status")}: ${status}</div></li>`;
  const h = (txt) => `<li class="svc-head small muted">${txt}</li>`;
  return `<ul class="services" style="padding-left:0;list-style:none;margin:0">
    ${h(L("外部服务", "External services"))}
    ${li(s.search_provider ? (s.search_is_test ? "warn" : "ok") : "bad", t("svc_search"), s.search_provider ? (s.search_is_test ? t("svc_test") : esc(searchName(s.search_provider)).replace(" API", ` ${abbr("API")}`)) : t("svc_none_search"))}
    ${h(L("AI 编码模型", "AI coding providers"))}
    ${s.providers && (s.providers.anthropic.configured || s.providers.openai.configured) ? "" : li("warn", t("svc_model"), t("svc_none_model"))}
    ${s.providers ? prov(s.providers.anthropic.configured ? "ok" : "warn", "anthropic", provModel("anthropic"), s.providers.anthropic.configured ? L("已配置", "configured") : L("未配置（ANTHROPIC_API_KEY）", "not configured (ANTHROPIC_API_KEY)")) : ""}
    ${s.providers ? prov(s.providers.openai.configured ? (s.providers.openai.sdk_installed ? "ok" : "bad") : "warn", "openai", s.providers.openai.model, s.providers.openai.configured ? L("已配置", "configured") + (s.providers.openai.sdk_installed ? "" : L(" · 未安装 openai 软件包", " · openai package not installed")) : L("未配置（OPENAI_API_KEY）— OpenAI 选项不会显示", "not configured (OPENAI_API_KEY) — OpenAI options are hidden")) : ""}
    ${h(L("内部处理", "Internal processing"))}
    ${li(s.ocr_available ? "ok" : "warn", L("扫描文件文字识别", "Scanned-document text recognition"), s.ocr_available ? `Tesseract ${abbr("OCR")}` : (LANG === "zh" ? `Tesseract ${abbr("OCR")} 未安装 — 扫描页会被标记为未读取` : `Tesseract ${abbr("OCR")} not installed — scanned pages are reported as unread`))}
    ${li(s.embeddings ? "ok" : "warn", L("证据检索", "Evidence retrieval"), s.embeddings ? `${L("神经向量", "embeddings")} + ${abbr("BM25")}` : `${abbr("LSA")} + ${abbr("BM25")} <span class="small muted">${L("（LSA 是近似方法，非神经向量）", "(LSA approximation, not neural embeddings)")}</span>`)}
  </ul>
  <p class="small muted svc-abbr">${["API", "OCR", "LSA", "BM25"].map((a) => `${a} = ${esc(L(ABBR[a][0], ABBR[a][1]))}`).join(" · ")}</p>
  <p class="small muted" style="margin-top:10px">${LANG === "zh" ? "配置方法见“设置”页。" : "How to configure: see Settings."} <a href="#/settings">→</a></p>`;
}
function providerChoiceHtml(modes, sel) {
  // Three mutually exclusive, keyboard-accessible choices (native radio group). Disabled ones say why (D-036).
  return `<fieldset class="pchoice" id="providerChoice"><legend>${L("编码模型选择", "Coding-provider selection")}</legend>
    ${modes.map((m) => `<label class="pcard ${m.available ? "" : "off"} ${m.mode === sel ? "on" : ""}">
      <input type="radio" name="pmode" value="${esc(m.mode)}" ${m.mode === sel ? "checked" : ""} ${m.available ? "" : "disabled"} aria-describedby="ph_${esc(m.mode)}">
      <span><b>${esc(modeText(m.mode))}</b>${m.available ? modeModelsHtml(m.mode) : ""}<span class="small muted" id="ph_${esc(m.mode)}">${esc(m.available ? modeHelp(m.mode) : L("不可用：", "Unavailable: ") + (m.reason || ""))}</span></span></label>`).join("")}
    </fieldset>`;
}
const COST_HELP = ["预计费用：按典型输出量估算的低端值；最高估计费用：每次请求都用满全部额度的最坏情况（预算检查使用）。", "Expected cost: low end, from a typical output size. Maximum estimated cost: worst case with every request using its full allowance (used by the budget check)."];
const costPair = (lo, hi) => `<span title="${esc(L(COST_HELP[0], COST_HELP[1]))}">${L("预计费用", "Expected cost")} ${money(lo)} · ${L("最高估计费用", "Maximum estimated cost")} <b>${money(hi)}</b></span>`;
function estimateHtml(e) {
  // Labels only: every number below is the same value as before, shown with clearer names.
  const pl = (p) => p.selected
    ? `<div>${esc(provCoding(p.provider))} · <span class="mono">${esc(p.model)}</span></div><div>${costPair(p.cost_low, p.cost_high)}${p.provider === "openai" ? ` <span class="small muted">(${L("OpenAI 编码预算", "OpenAI coding budget")} ${money(e.openai_budget_usd)})</span>` : ""}${p.price_note ? ` <span class="badge warn" title="${esc(p.price_note)}">${L("价格需核对", "check price")}</span>` : ""}</div>`
    : `<div class="muted">${esc(provCoding(p.provider))}</div><div class="muted">${L("未选择", "Not selected")} — $0.00</div>`;
  return `<div class="kv">
      <div>${L("共享网页研究", "Shared web research")}${e.search_provider ? ` — ${esc(searchName(e.search_provider))}` : ""} <span class="small muted">${L("（只做一次）", "(runs once)")}</span></div><div>${!e.search_provider ? L("未配置搜索服务（只用手动添加的资料）", "no search service configured (manual sources only)") : e.search_cost_max != null ? `≤ ${money(e.search_cost_max)} <span class="small muted">(${e.search_queries_max} ${L("次查询上限", "queries max")})</span>` : L("未配置搜索价格", "no search price configured")}</div>
      ${(e.providers || []).map(pl).join("")}
      <div><b>${L("合计 — 最高估计费用", "Combined — maximum estimated cost")}</b></div><div><b>${money(e.combined_high)}</b> <span class="small muted">${L("模型：预计", "models: expected")} ${money(e.cost_low)} · ${L("最高", "maximum")} ${money(e.cost_high)}</span></div>
      <div>${L("本案例总上限", "Case cap (all providers + search)")}</div><div>${money(e.budget_usd)}</div>
      <div>${L("请求次数上限", "Request caps")}</div><div>${L("全部模型", "all providers")} ${e.max_model_attempts_per_case} · OpenAI API ${e.max_openai_attempts_per_case}</div></div>
    ${e.minimum_check ? `<div class="callout bad small">${esc(e.minimum_check)}</div>` : ""}
    ${!e.minimum_check && e.combined_high != null && (e.combined_high > e.budget_usd || (e.providers || []).some((p) => p.selected && p.provider === "openai" && p.cost_high > e.openai_budget_usd)) ? `<div class="callout warn small">${L("最坏情况高于本案例的上限。花费不会超过上限：编码开始前会暂停，请你把上限提高到一个明确的金额，或者停在那里。最坏情况假设每次请求都用满全部额度；目前唯一一次实测的完整 GPT 运行，实际花费约为最坏情况的 1/9。", "The worst case is above this case's cap. Spending never exceeds the cap: before coding, the run pauses and asks you to raise it to an explicit amount, or to stop. The worst case assumes every request uses its full allowance; in the one full GPT run measured so far, the actual cost was about 1/9 of the worst case.")}</div>` : ""}
    <p class="small muted">${L("初步估算：还不知道会找到哪些资料。最高值是预算检查使用的“最坏情况预留”。研究完成后、任何付费模型请求之前，会根据实际证据重新计算。", "Preliminary estimate: the sources are not known yet. The high end is the worst-case reserve used by the budget check. After research and before any paid model request, it is recalculated from the evidence actually found.")}</p>`;
}
// D-045: two mutually exclusive run modes on the first form. Search only is the default.
const RUN_MODES = {
  search_only: { title: ["只搜索", "Search only"], help: ["查找并整理相关来源，不运行编码分析。", "Find and organize relevant sources without running coding analysis."], start: ["搜索来源", "Search sources"] },
  search_analyze: { title: ["搜索并分析", "Search & analyze"], help: ["查找相关来源，并生成编码建议供人工复核。", "Find relevant sources and generate coding suggestions for human review."], start: ["搜索并分析", "Search & analyze"] },
};
function runModeHtml(sel) {
  return `<fieldset class="pchoice" id="runModeChoice"><legend>${L("运行方式", "What to run")}</legend>
    ${Object.entries(RUN_MODES).map(([k, m]) => `<label class="pcard ${k === sel ? "on" : ""}">
      <input type="radio" name="rmode" value="${k}" ${k === sel ? "checked" : ""} aria-describedby="rh_${k}">
      <span><b>${esc(L(m.title[0], m.title[1]))}</b><span class="small muted" id="rh_${k}">${esc(L(m.help[0], m.help[1]))}</span></span></label>`).join("")}
    </fieldset>`;
}
async function renderHome() {
  const st = STATUS.settings;
  const modes = STATUS.modes || [];
  const avail = modes.filter((m) => m.available);
  let rmode = "search_only";
  const startLabel = () => L(RUN_MODES[rmode].start[0], RUN_MODES[rmode].start[1]);
  // Safe default: Claude only when available; otherwise nothing is pre-selected (never silently a costlier option).
  let pmode = avail.some((m) => m.mode === "anthropic_only") ? "anthropic_only" : null;
  app.innerHTML = `<div class="hero">
    <div class="panel form">
      <h1>${t("hero_title")}</h1><p class="sub">${t("hero_sub")}</p>
      <label for="f_name">${t("f_name")}</label><input id="f_name" placeholder="${esc(t("f_name_ph"))}">
      <div class="grid2"><div><label for="f_location">${t("f_location")}</label><input id="f_location" placeholder="${esc(t("f_location_ph"))}"></div>
      <div><label for="f_date">${t("f_date")}</label><input id="f_date" placeholder="${esc(t("f_date_ph"))}"></div></div>
      <label for="f_aliases">${t("f_aliases")}</label><input id="f_aliases" placeholder="e.g. Kerr County flood; Camp Mystic flood">
      <details style="margin-top:10px"><summary>${t("f_details")} / ${t("f_links")}</summary>
        <label>${t("f_details")}</label><textarea id="f_details"></textarea>
        <label>${t("f_links")}</label><textarea id="f_links" placeholder="https://..."></textarea></details>
      <div id="analyzeOpts" hidden>
      ${avail.length ? providerChoiceHtml(modes, pmode) : `<div class="callout warn small" style="margin-top:12px"><b>${L("编码模型选择", "Coding-provider selection")}</b>: ${L("服务器没有配置任何模型密钥。研究照常进行，结果留给你手动编码。", "No model key is configured on the server. Research runs as usual and the results are left for manual coding.")}</div>`}
      ${avail.length ? `<label class="chk" style="margin-top:8px"><input type="checkbox" id="pauseChk" style="width:auto"> ${L("可选：研究完成后先暂停，等我批准再开始付费编码", "Optional: pause for my approval after research, before paid coding starts")}</label>` : ""}
      </div>
      <details style="margin-top:10px"><summary>${t("f_advanced")}</summary>
        <div class="grid3">
          <div><label>${t("s_rounds")}</label><input id="s_rounds" type="number" min="0" value="${st.max_search_rounds}"></div>
          <div><label>${t("s_queries")}</label><input id="s_queries" class="estIn" type="number" min="1" value="${st.max_queries}"></div>
          <div><label>${t("s_fetch")}</label><input id="s_fetch" type="number" min="1" value="${st.max_fetch}"></div>
          <div><label>${t("s_pages")}</label><input id="s_pages" type="number" min="1" max="5" value="${st.pages_per_query}"></div>
          <div><label>${t("s_time")}</label><input id="s_time" type="number" min="1" value="${st.time_limit_minutes}"></div>
          <div><label>${t("s_budget")}</label><input id="s_budget" class="estIn" type="number" min="0" step="0.5" value="${st.budget_usd}"></div>
          <div><label>${L("OpenAI 预算（美元）", "OpenAI budget ($)")}</label><input id="s_obudget" class="estIn" type="number" min="0" step="0.5" value="${st.openai_budget_usd}"></div>
        </div></details>
      <div class="panel" style="margin-top:12px" id="estBox" aria-live="polite"><h3 style="margin-top:0">${t("est_title")}</h3><div class="muted">${t("loading")}</div></div>
      ${runModeHtml(rmode)}
      <div class="row" style="margin-top:16px"><button class="primary" id="startBtn">${esc(startLabel())}</button><span class="spacer"></span></div>
    </div>
    <div>
      <div class="panel"><h3 style="margin-top:0">${t("services")}</h3>${serviceList()}</div>
    </div></div>`;
  let est = null;
  const formQuery = () => `budget_usd=${encodeURIComponent($("#s_budget").value)}&openai_budget_usd=${encodeURIComponent($("#s_obudget").value)}&max_queries=${encodeURIComponent($("#s_queries").value)}`;
  const refresh = async () => {
    if (rmode === "search_only") {  // no model is used: show only the search part of the estimate
      try {
        est = await api("GET", `/api/estimate_preview?mode=single&${formQuery()}`);
        $("#estBox").innerHTML = `<h3 style="margin-top:0">${t("est_title")} · <span class="small">${esc(L("只搜索", "Search only"))}</span></h3>
          <div class="kv"><div>${L("网页搜索", "Web search")}${est.search_provider ? ` — ${esc(searchName(est.search_provider))}` : ""}</div><div>${!est.search_provider ? L("未配置搜索服务（只用手动添加的资料）", "no search service configured (manual sources only)") : est.search_cost_max != null ? `≤ ${money(est.search_cost_max)} <span class="small muted">(${est.search_queries_max} ${L("次查询上限", "queries max")})</span>` : L("未配置搜索价格", "no search price configured")}</div>
          <div>${L("编码模型请求", "Coding-model requests")}</div><div>${L("无", "none")} — $0.00</div>
          <div>${L("本案例总上限", "Case cap")}</div><div>${money(est.budget_usd)}</div></div>
          <p class="small muted">${L("只做来源查找、去重、相关性检查、排序和读取。相关性检查是按事件名称、地点和年份做文字匹配，不用 AI。之后可以随时在案例里点“继续分析”。", "Only source discovery, de-duplication, relevance check, ranking and retrieval. The relevance check matches the incident name, place and year in the text; it does not use AI. You can continue to analysis later from the case.")}</p>`;
        $("#startBtn").disabled = false;
      } catch (err) { $("#estBox").innerHTML = `<div class="callout bad small">${esc(err.message)}</div>`; $("#startBtn").disabled = false; }
      return;
    }
    if (avail.length && !pmode) { $("#estBox").innerHTML = `<h3 style="margin-top:0">${t("est_title")}</h3><p class="muted">${L("请先选择编码模型。", "Choose a coding-provider option first.")}</p>`; $("#startBtn").disabled = true; return; }
    try {
      est = await api("GET", `/api/estimate_preview?mode=${encodeURIComponent(pmode || "single")}&${formQuery()}`);
      $("#estBox").innerHTML = `<h3 style="margin-top:0">${t("est_title")} · <span class="small">${esc(modeText(pmode || "single"))}</span></h3>${avail.length ? estimateHtml(est) : `<p>${t("svc_none_model")}</p>`}`;
      $("#startBtn").disabled = !!(avail.length && (!pmode || est.minimum_check));
    } catch (err) { $("#estBox").innerHTML = `<div class="callout bad small">${esc(err.message)}</div>`; $("#startBtn").disabled = true; }
  };
  $$("input[name=rmode]").forEach((r) => (r.onchange = () => {
    rmode = r.value;
    $$("#runModeChoice .pcard").forEach((c) => c.classList.toggle("on", c.querySelector("input").checked));
    $("#analyzeOpts").hidden = rmode !== "search_analyze";
    $("#startBtn").textContent = startLabel();
    refresh();
  }));
  $$("input[name=pmode]").forEach((r) => (r.onchange = () => {
    pmode = r.value;
    $$("#providerChoice .pcard").forEach((c) => c.classList.toggle("on", c.querySelector("input").checked));
    refresh();
  }));
  $$(".estIn").forEach((x) => (x.onchange = refresh));
  refresh();
  const confirmStart = (checks) => new Promise((resolve) => {
    const unverified = Object.entries(checks || {}).filter(([, v]) => !v.verified);
    $("#modalRoot").innerHTML = `<div class="modal-bg"><div class="modal" style="width:min(600px,100%)" role="dialog" aria-modal="true" aria-labelledby="csTitle">
      <header><b id="csTitle">${L("确认开始研究", "Confirm and start research")}</b></header><div class="body">
      <div class="kv"><div>${L("编码模型选择", "Coding-provider selection")}</div><div><b>${esc(modeText(pmode))}</b>${modeModelsHtml(pmode) ? `<br>${modeModelsHtml(pmode)}` : ""}</div>
        <div>${L("网页研究", "Web research")}</div><div>${L("一次共享搜索（不会因为选了两个模型而搜索两次）", "One shared search (never repeated because two providers are selected)")}</div></div>
      ${estimateHtml(est)}
      ${unverified.length ? `<div class="callout warn small">${unverified.map(([p, v]) => `${esc(provApi(p))}: ${esc(v.reason || L("暂时无法验证", "could not verify now"))}`).join("<br>")}</div>` : ""}
      <ul class="small">
        <li>${L("实际费用取决于找到的证据和模型的输出；服务器会强制执行上面的上限。", "Actual cost depends on the evidence retrieved and on model output; the caps above are enforced by the server.")}</li>
        <li>${L("已经发出的请求即使之后停止，也可能被计费。", "A request already sent may still be billed if you stop later.")}</li>
        <li>${$("#pauseChk") && $("#pauseChk").checked ? L("研究完成后会先暂停，显示精确估算，等你批准才开始付费编码。", "After research the job pauses with an exact estimate; paid coding starts only when you approve.") : L("研究完成后会直接开始编码（仍受上限约束）。", "Coding starts right after research (still within the caps).")}</li>
        ${pmode === "dual_independent" ? `<li>${esc(modeHelp("dual_independent"))}</li>` : ""}</ul>
      <div class="row" style="margin-top:12px"><button class="primary" id="csOk">${L("确认并开始", "Confirm and start")}</button><button id="csCancel">${L("取消", "Cancel")}</button></div></div></div></div>`;
    const done = (v) => { $("#modalRoot").innerHTML = ""; resolve(v); };
    $("#csOk").onclick = () => done(true); $("#csCancel").onclick = () => done(false); $("#csOk").focus();
  });
  $("#startBtn").onclick = async () => {
    const name = $("#f_name").value.trim();
    if (!name) { toast(t("f_name"), true); $("#f_name").focus(); return; }
    $("#startBtn").disabled = true; $("#startBtn").textContent = t("starting");
    const reset = () => { $("#startBtn").disabled = false; $("#startBtn").textContent = startLabel(); };
    const analyze = rmode === "search_analyze";
    try {
      let checks = {};
      if (analyze && pmode) {  // free, non-billable availability check before anything is created or searched
        checks = (await api("POST", "/api/providers/check", { mode: pmode })).providers || {};
        const bad = Object.entries(checks).filter(([, v]) => !v.ok);
        if (bad.length) { toast(bad.map(([p, v]) => `${provApi(p)}: ${v.reason}`).join(" · "), true); reset(); return; }
        if (!(await confirmStart(checks))) { reset(); return; }
      }
      const r = await api("POST", "/api/cases", {
        name, location: $("#f_location").value, date_text: $("#f_date").value, aliases: $("#f_aliases").value,
        details: $("#f_details").value, known_links: $("#f_links").value, start: true, run_mode: rmode,
        ...(analyze && pmode ? { mode: pmode, pause_before_coding: $("#pauseChk").checked } : {}),
        settings: { max_search_rounds: +$("#s_rounds").value, max_queries: +$("#s_queries").value, max_fetch: +$("#s_fetch").value,
          pages_per_query: +$("#s_pages").value, time_limit_minutes: +$("#s_time").value, budget_usd: +$("#s_budget").value,
          openai_budget_usd: +$("#s_obudget").value },
      });
      location.hash = `#/case/${r.id}/progress`;
    } catch (e) { toast(e.message, true); reset(); }
  };
}

// ------------------------------------------------------------------ cases
function statusBadge(job, caseStatus) {
  if (!job) return `<span class="badge" title="${esc(caseStatus)}">${esc(stText(CASE_TEXT, caseStatus))}</span>`;
  const cls = { done: "ok", running: "info", queued: "info", needs_input: "warn", failed: "bad", cancelled: "" }[job.status] || "";
  return `<span class="badge ${cls}" title="${esc(job.status)}">${esc(stText(JOB_TEXT, job.status))}${job.status === "running" ? " · " + esc(t("st_" + job.stage) || job.stage) : ""}</span>`;
}
async function renderCases() {
  const rows = await api("GET", "/api/cases");
  app.innerHTML = `<h1>${t("cases_title")}</h1><div class="panel" style="padding:0">
    <table><thead><tr><th>#</th><th>${t("c_name")}</th><th>${t("c_status")}</th><th>${t("c_sources")}</th><th>${t("c_confirmed")}</th><th>${t("c_created")}</th></tr></thead>
    <tbody>${rows.map((c) => `<tr class="click" data-id="${c.id}"><td>${c.id}</td><td><b>${esc(c.name)}</b><div class="small muted">${esc(c.location)} · ${esc(c.date_text)}</div></td>
    <td>${statusBadge(c.job, c.status)}<div class="small" style="margin-top:4px">${statusPills(c.statuses)}</div></td><td>${c.n_sources}</td><td>${c.n_confirmed}</td><td class="small">${fmtTime(c.created_at)}</td></tr>`).join("") ||
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
const STAGES_SEARCH_ONLY = ["identify", "search", "fetch", "sources"];  // D-045
async function tabProgress(c, body) {
  const draw = async () => {
    const j = await api("GET", `/api/cases/${c.id}/job`);
    if (!j) { body.innerHTML = `<div class="panel empty-state"><span>${L("这个案例还没有研究记录。", "No research has been run for this case yet.")}</span><button class="primary" id="runBtn">${t("rerun")}</button></div>`; $("#runBtn").onclick = () => startResearch(c.id); return; }
    const searchOnly = !!(j.params && j.params.search_only);
    const sts = (await api("GET", `/api/cases/${c.id}`)).statuses;
    const stages = searchOnly ? STAGES_SEARCH_ONLY : STAGES;
    const cur = stages.indexOf(j.stage);
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
        <div>${L("编码模型选择", "Coding-provider selection")}</div><div>${esc(modeText(st.coding_mode || "single"))}</div>
        <div>Model</div><div>${esc(e.model)}</div>${(e.providers || []).length > 1 ? providerCostRows(e) : ""}<div>${t("calls")}</div><div>${e.calls}</div><div>${t("input_tokens")}</div><div>${(e.input_tokens || 0).toLocaleString()}</div>
        <div>${t("est_cost")}</div><div>${money(e.cost_low)} – <b>${money(e.cost_high)}</b> ${t("worst_case")}</div>
        <div>${t("case_spend")}</div><div>${money(b.spent_usd)} / ${money(b.budget_usd)}</div>
        ${Object.values(ln).map((v) => `<div>${esc(v.label)}</div><div>${esc(v.current)} → <b>${esc(v.needed)}</b></div>`).join("")}</div>
        <div class="row"><button class="primary" id="approveBtn">${others.length ? L("批准以上明确数值", "Approve the explicit values above") : `${t("approve_to")} ${money(needed)}`}</button>
        <span>${t("raise_budget")}</span><input id="newBudget" type="number" min="0" max="1000" step="0.5" style="width:100px" value="${needed}"><button id="raiseBtn">OK</button>
        <button id="manualBtn">${t("manual_only")}</button></div>
        <p class="small muted">${t("budget_note")}</p></div>`;
    } else if (j.status === "needs_input" && st.awaiting === "coding_approval") {
      const e = st.estimate || {}; const b = st.budget || {};
      needs = `<div class="callout warn"><b>${L("研究已完成 — 还没有向任何模型发送请求", "Research finished — nothing has been sent to a model yet")}</b>
        <div class="kv" style="margin:8px 0"><div>${L("编码模型选择", "Coding-provider selection")}</div><div>${esc(modeText(st.coding_mode || "single"))}</div>
        ${providerCostRows(e)}<div><b>${L("合计（最坏情况）", "Combined (worst case)")}</b></div><div>${money(e.cost_low)} – <b>${money(e.cost_high)}</b></div>
        <div>${t("case_spend")}</div><div>${money(b.spent_usd)} / ${money(b.budget_usd)}</div></div>
        <p class="small">${L("这是根据实际找到的证据算出的精确估算。可以开始付费编码，也可以停在这里（不产生模型费用；研究结果会保留）。", "This estimate uses the evidence actually found. Start paid coding, or stop here at no model cost (the research is kept).")}</p>
        <div class="row"><button class="primary" id="codingOkBtn">${L("开始编码", "Start coding")}</button><button id="cancelBtn2">${L("停在这里", "Stop here")}</button></div></div>`;
    } else if (j.status === "needs_input" && st.awaiting === "interrupted") {
      needs = `<div class="callout warn"><b>${L("任务被服务器重启中断，已暂停", "Interrupted by a server restart — paused")}</b><p>${esc(j.message)}</p>
        <p class="small">${L("不会自动重新开始。点“继续”会从中断处接着做：已完成并缓存的批次免费复用，中断的那一批会重新发送（需要再次计费）。", "It will not restart by itself. Resume continues where it stopped: completed, cached batches are reused for free; the interrupted batch is sent again (billed again).")}</p>
        <div class="row"><button class="primary" id="resumeBtn">${t("resume")}</button><button class="danger" id="cancelBtn2">${t("cancel")}</button></div></div>`;
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
      <div class="stepper ${j.status === "running" ? "running" : ""}">${stages.map((s, i) => `<div class="st ${i < cur || j.status === "done" ? "done" : i === cur ? "cur" : ""}">${s === "sources" ? esc(L("来源已就绪", "Sources ready")) : t("st_" + s)}</div>`).join("")}</div>
      <div class="bar"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>
      <div class="row" style="margin-top:10px">${statusBadge(j)}<span>${esc(j.message || "")}</span><span class="spacer"></span>
      ${["running", "queued"].includes(j.status) ? `<button class="danger" id="cancelBtn">${t("cancel")}</button>`
        : searchOnly ? `<button id="rerunBtn">${t("rerun")}</button> <a href="${srcLink(c.id, "sources", false)}"><button>${L("导出来源清单", "Export source list")}</button></a> <button id="recodeBtn">${L("分析已选来源", "Analyze selected sources")}</button> <a href="#/case/${c.id}/sources"><button class="primary">${L("查看来源", "View sources")} →</button></a>`
        : `<button id="rerunBtn">${t("rerun")}</button> <button id="recodeBtn">${t("recode")}</button> <a href="#/case/${c.id}/review"><button class="primary">${t("tab_review")} →</button></a>`}</div>
      <div class="row small" style="margin-top:8px;gap:6px">${statusPills(sts)} <span class="muted">${L("· 自动保存：来源、正文和选择都已保存在服务器上，可以离开后再回来。", "· Saved automatically: sources, their text and your selections are stored on the server; you can leave and come back.")}</span></div>
      ${searchOnly && j.status === "done" ? `<div class="callout ok small">${L("只搜索已成功完成：来源查找、去重、相关性检查、排序和读取都已完成。没有运行证据缺口检查、补充搜索或编码分析——这是正常结果，不是分析失败。可以在“来源”页查看、选择和导出来源；需要时点“分析已选来源”。", "Search only finished successfully: source discovery, de-duplication, relevance check, ranking and retrieval are done. No evidence-gap check, follow-up search or coding analysis was run — this is the expected outcome, not a failed analysis. View, select and export sources on the Sources tab; choose Analyze selected sources when needed.")}</div>` : ""}
      ${j.error ? `<div class="callout bad">${esc(j.error)}</div>` : ""}${needs}
      ${providerPanel(j)}
      ${cov ? `<h3>${t("coverage")}</h3>${!cov.automatic_search_ran ? `<div class="callout warn">${LANG === "zh" ? "未进行自动网页搜索（未配置搜索服务，或本次只是重新分析）。结果只基于已有或手动补充的资料。" : "No automatic web search in this run (no search provider configured, or this was a re-analysis). Results rest only on existing or manually added sources."}</div>` : cov.research_complete ? `<div class="callout ok">${t("complete_note")}</div>` : `<div class="callout warn">${t("incomplete")}<br><span class="small">${esc((cov.limits_hit || []).join("; "))}</span></div>`}
        ${cov.search_is_test_fixture ? `<div class="callout bad">${t("svc_test")}</div>` : ""}
        <div class="kv"><div>${t("case_spend")}</div><div>${money(cov.spent_usd)} / ${money(cov.budget_usd)}${cov.search_provider && !cov.search_price_configured && !cov.search_is_test_fixture ? ` <span class="badge warn">${t("search_price_missing")}</span>` : ""}</div>
        <div>${LANG === "zh" ? "搜索服务" : "Search service"}</div><div>${esc(cov.search_provider ? searchName(cov.search_provider) : t("none"))}</div>
        <div>${LANG === "zh" ? "搜索（成功/失败）" : "Queries ok / failed"}</div><div>${cov.queries_ok} / ${cov.queries_failed} (${LANG === "zh" ? "轮次" : "rounds"} ${cov.rounds})</div>
        <div>${LANG === "zh" ? "已读取 / 获取失败" : "Sources read / failed"}</div><div>${cov.sources_ok} / ${cov.sources_failed}</div>
        <div>${LANG === "zh" ? "重复 / 转载" : "Duplicates / syndicated"}</div><div>${cov.exact_duplicates} / ${cov.near_duplicates}</div>
        <div>${LANG === "zh" ? "无关 / 相关性不确定" : "Irrelevant / uncertain"}</div><div>${cov.irrelevant} / ${cov.uncertain}</div>
        <div>${LANG === "zh" ? "扫描页未识别的来源" : "Sources with unread scanned pages"}</div><div>${cov.ocr_gaps}</div>
        <div>${LANG === "zh" ? "证据仍薄弱的变量" : "Variables still weak on evidence"}</div><div class="small">${cov.gaps_checked === false ? esc(L("未检查（只搜索）", "not checked (search only)")) : (cov.gaps_remaining || []).length ? `<details class="gap-list"><summary>${cov.gaps_remaining.length} ${L("个变量 — 点击展开", cov.gaps_remaining.length === 1 ? "variable — show" : "variables — show")}</summary><div class="var-chips">${cov.gaps_remaining.map((g) => `<span>${esc(g)}</span>`).join("")}</div></details>` : t("none")}</div></div>` : ""}
      ${st.coding_report ? `<p class="small muted">${LANG === "zh" ? "编码" : "Coding"}${st.coding_report.mode ? ` (${esc(modeText(st.coding_report.mode))})` : ""}: ${st.coding_report.calls} call(s), ${st.coding_report.failed_calls} failed${st.coding_report.cache_hits ? `, ${st.coding_report.cache_hits} ${L("个来自缓存（免费）", "from cache (free)")}` : ""}, ${esc(st.coding_report.semantic_method)}, ${st.coding_report.n_passages_indexed} passages indexed${st.coding_report.not_coded_budget?.length ? `, <b>${st.coding_report.not_coded_budget.length} not coded (limit)</b>` : ""}.
        ${(st.coding_report.providers || []).filter((r) => r.provider).map((r) => `<br>· ${esc(provApi(r.provider))} · <span class="mono">${esc(r.model || "")}</span> — ${r.role === "reviewer" ? esc(interpText("cross_model_review")) : esc(interpText("independent"))}: ${r.calls} call(s), ${r.failed_calls} failed, ${r.cache_hits || 0} cached, ${money(r.spent_usd)}`).join("")}
        ${st.coding_report.comparison && Object.keys(st.coding_report.comparison).length ? `<br>${L("比较", "Comparison")}: ${Object.entries(st.coding_report.comparison).map(([k, v]) => `${esc(compText(k))} ${v}`).join(" · ")} — ${L("模型一致不等于事实已核实。", "agreement is not verification.")}` : ""}</p>` : ""}
      <h3>${t("log")}</h3><div class="log">${(j.log || []).map((l) => `<div class="${l.level}">${new Date(l.at * 1000).toLocaleTimeString()} [${esc(l.stage)}] ${esc(l.message)}</div>`).join("")}</div></div>`;
    const on = (sel, fn) => { const el = $(sel, body); if (el) el.onclick = fn; };
    on("#cancelBtn", async () => { await api("POST", `/api/jobs/${j.id}/cancel`); draw(); });
    on("#cancelBtn2", async () => { await api("POST", `/api/jobs/${j.id}/cancel`); draw(); });
    on("#codingOkBtn", async () => { await api("POST", `/api/jobs/${j.id}/resume`, { coding_approved: true }); draw(); });
    $$("[data-stop-prov]", body).forEach((b) => (b.onclick = async () => {
      const prov = b.dataset.stopProv;
      const ok = await askDialog({ title: `${L("停止", "Stop")} ${provCoding(prov)}`,
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
    on("#rerunBtn", (ev) => startResearch(c.id, ev.currentTarget, true));
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
  return `<h3>${L("AI 编码模型", "AI coding providers")}</h3><div class="prov-ctl">${provs.map((p) => {
    const r = runs[p]; const stopReq = ctl[p] && ctl[p].stop_requested;
    const st = stopReq && ["pending", "running"].includes(r.status) ? ["正在停止…", "stopping…", "warn"] : (RS[r.status] || [r.status, r.status, ""]);
    const canStop = active && ["pending", "running"].includes(r.status) && !stopReq;
    const canResume = (stopReq && ["pending", "running"].includes(r.status)) || r.status === "stopped";
    return `<div class="prov-row" data-prov-row="${esc(p)}"><b>${esc(provApi(p))}</b> <span class="small mono">${esc(r.model || "")}</span> <span class="small muted">${esc(r.role === "reviewer" ? interpText("cross_model_review") : interpText("independent"))}</span>
      <span class="badge ${st[2]}">${esc(L(st[0], st[1]))}</span>
      ${r.calls != null ? `<span class="small muted">${r.calls} call(s) · ${r.failed_calls || 0} failed · ${r.cache_hits || 0} cached · ${money(r.spent_usd)}${(r.stopped_variables || []).length ? ` · ${r.stopped_variables.length} ${L("个变量已停止", "variable(s) stopped")}` : ""}</span>` : ""}
      <span class="spacer"></span>
      ${canStop ? `<button class="danger small" data-stop-prov="${esc(p)}">${L("停止", "Stop")} ${esc(PROV[p] || p)}</button>` : ""}
      ${canResume ? `<button class="small" data-resume-prov="${esc(p)}">${L("继续", "Resume")} ${esc(PROV[p] || p)}</button>` : ""}</div>`;
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
async function startResearch(id, btn, ask = false) {
  busy(btn, true);
  try {
    if (ask) {  // re-run: show pages already read vs this case's fetch limit, which counts every run (D-044)
      const c = await api("GET", `/api/cases/${id}`);
      const full = c.fetched_count >= c.max_fetch;
      let rm = (c.settings || {}).run_mode === "search_only" ? "search_only" : "search_analyze";  // older cases: full pipeline
      // K-61: Search & analyze in this dialog also asks which coding provider(s) to use (same choices as the first form)
      const av = availModes();
      const stored = (c.settings || {}).coding_mode;
      let pm = av.some((m) => m.mode === stored) ? stored : av.some((m) => m.mode === "anthropic_only") ? "anthropic_only" : (av[0] ? av[0].mode : null);
      const provBox = () => av.length ? providerChoiceHtml(STATUS.modes || [], pm)
        : `<div class="callout warn small">${L("服务器没有配置任何模型密钥：研究照常进行，结果留给你手动编码。", "No model key is configured on the server: research runs as usual and the results are left for manual coding.")}</div>`;
      const dlg = askDialog({
        title: t("rerun"),
        body: `${runModeHtml(rm)}<div id="rrProv" style="margin-top:8px" ${rm === "search_analyze" ? "" : "hidden"}>${provBox()}<p class="small muted" style="margin:4px 0 0">${L("读取完来源后会直接开始编码（仍受本案例的预算和请求上限约束）。想先看精确费用，可以选“只搜索”，之后点“分析已选来源”。", "Coding starts right after the sources are read (still within this case's budget and request caps). To see an exact estimate first, choose Search only and then Analyze selected sources.")}</p></div><div class="kv" style="margin-top:10px"><div>${L("本案例已读取的网页（所有运行）", "Pages already read for this case (all runs)")}</div><div><b>${c.fetched_count}</b></div>
          <div>${L("本案例的读取上限", "This case's reading limit")}</div><div><b>${c.max_fetch}</b></div></div>
          ${full ? `<div class="callout warn small">${L("已达到读取上限：不提高上限的话，这次运行会搜索，但不会读取新网页。", "The reading limit is reached: without raising it, this run will search but read no new pages.")}</div>` : ""}
          <p class="small muted">${L("新的搜索会用到 Tavily 额度（按每次 $0.016 计入本案例预算）。读取更多网页会让之后的编码费用变高。上限最高 300；每次修改都会记录。", "New searches use Tavily credits (counted at $0.016 each in this case's budget). Reading more pages makes later coding cost more. Maximum 300; every change is recorded.")}</p>`,
        okText: L("开始重新研究", "Start research"), cancelText: L("取消", "Cancel"),
        input: { label: L("读取上限（本案例所有运行合计）", "Reading limit (all runs of this case)"), value: String(full ? Math.min(c.fetched_count + 60, 300) : c.max_fetch) } });
      $$("#modalRoot input[name=pmode]").forEach((r) => (r.onchange = () => {
        pm = r.value; $$("#modalRoot #providerChoice .pcard").forEach((x) => x.classList.toggle("on", x.querySelector("input").checked));
      }));
      $$("#modalRoot input[name=rmode]").forEach((r) => (r.onchange = () => {
        rm = r.value; $$("#modalRoot #runModeChoice .pcard").forEach((x) => x.classList.toggle("on", x.querySelector("input").checked));
        $("#rrProv").hidden = rm !== "search_analyze";
        $("#dlgOk").textContent = rm === "search_only" ? L("开始搜索", "Search sources") : L("开始搜索并分析", "Search & analyze");
      }));
      $("#dlgOk").textContent = rm === "search_only" ? L("开始搜索", "Search sources") : L("开始搜索并分析", "Search & analyze");
      const v = await dlg;
      if (v === null) return;
      const n = parseInt(v, 10);
      if (!(n >= 1 && n <= 300)) { toast(L("读取上限必须是 1–300 之间的整数", "The reading limit must be a whole number from 1 to 300"), true); return; }
      if (n !== c.max_fetch) await api("POST", `/api/cases/${id}/limits`, { limits: { max_fetch: n }, reason: "set before re-running research" });
      await api("POST", `/api/cases/${id}/research`, { run_mode: rm, ...(rm === "search_analyze" && pm ? { mode: pm } : {}) });
      location.hash = `#/case/${id}/progress`; route(); return;
    }
    await api("POST", `/api/cases/${id}/research`, {}); location.hash = `#/case/${id}/progress`; route(); }
  catch (e) { toast(e.message, true); }
  finally { busy(btn, false); }
}
async function startRecode(id, variables, btn) {
  busy(btn, true, LANG === "zh" ? "正在估算费用…" : "Estimating cost…");
  try {
    const modes = availModes();
    const caseMode = ((await api("GET", `/api/cases/${id}`)).settings || {}).coding_mode || "single";
    const estFor = (mode) => api("GET", `/api/cases/${id}/estimate?mode=${encodeURIComponent(mode)}${variables ? "&variables=" + encodeURIComponent(variables.join(",")) : ""}`);
    let mode = modes.some((m) => m.mode === caseMode) ? caseMode : (modes[0] ? modes[0].mode : "single");
    let e = null;
    try { e = await estFor(mode); }
    catch (err) { toast((LANG === "zh" ? "无法估算费用：" : "Could not estimate the cost: ") + err.message, true); return; }
    const body = (e) => {
      const lg = e.ledger || {}; const lim = e.limits || {};
      const twoOrMore = (e.providers || []).length > 1;
      return `<label for="modeSel">${L("编码模型选择（只显示服务器已配置密钥的选项）", "Coding-provider selection (only options configured on the server)")}</label>
        <select id="modeSel">${modes.length ? modes.map((m) => `<option value="${esc(m.mode)}" ${m.mode === mode ? "selected" : ""}>${esc(modeText(m.mode))}</option>`).join("") : `<option value="single" selected>${esc(L("未配置模型（手动编码）", "No model configured (manual coding)"))}</option>`}</select>
        ${mode === "dual_independent" ? `<p class="small muted dual-neutral" style="margin:4px 0 0">${esc(L(DUAL_NEUTRAL[0], DUAL_NEUTRAL[1]))} ${esc(L(DUAL_SEQ[0], DUAL_SEQ[1]))}</p>`
          : (modeHelp(mode) ? `<p class="small muted" style="margin:4px 0 0">${esc(modeHelp(mode))}</p>` : "")}
        ${e.manual ? `<p>${t("svc_none_model")}</p>` : `<div class="kv" style="margin-top:8px">${providerCostRows(e)}
          ${twoOrMore ? `<div><b>${L("合计", "Combined")}</b></div><div>${costPair(e.cost_low, e.cost_high)}</div>` : ""}
          ${e.cost_high_new != null && e.cost_high - e.cost_high_new > 0.005 ? `<div>${L("新增费用上限（不含缓存批次）", "Max additional cost (cached batches are free)")}</div><div><b>${money(e.cost_high_new)}</b></div>` : ""}
          <div>${t("case_spend")}</div><div>${money(lg.spent_total)} / ${money(lim.budget_usd)}</div>
          <div>${L("已花费：Claude 编码 / GPT 编码 / 网页搜索", "Spent: Claude coding / GPT coding / web search")}</div><div>${money((lg.spent_by || {}).anthropic || 0)} / ${money((lg.spent_by || {}).openai || 0)} / ${money((lg.spent_by || {}).search || 0)}</div>
          <div>${L("OpenAI 编码预算", "OpenAI coding budget")}</div><div>${money((lg.spent_by || {}).openai || 0)} / ${money(lim.openai_budget_usd)}</div>
          <div>${L("模型请求次数（本案例）", "Model requests (this case)")}</div><div>${lg.attempts_total || 0} / ${lim.max_model_attempts_per_case} · OpenAI API ${(lg.attempts_by || {}).openai || 0} / ${lim.max_openai_attempts_per_case}</div></div>
          ${Object.keys(e.limit_needs || {}).length ? `<div class="callout warn small">${L("这次运行可能超过上限；开始后会暂停，请你按明确数值批准：", "This run could exceed a limit; it will pause and ask you to approve explicit values:")} ${Object.values(e.limit_needs).map((v) => `${esc(v.label)} ${esc(v.current)} → ${esc(v.needed)}`).join("; ")}</div>` : ""}
          ${(e.price_notes || []).length ? `<div class="callout warn small">${esc(e.price_notes.join("; "))}</div>` : ""}
          ${mode === "dual_independent" ? `<p class="small">${L("不一致的变量会交给人工复核。模型一致不代表事实已核实；最终值由研究人员决定。", "Disagreements go to human review. Agreement is not verification; the researcher decides the final value.")}</p>` : ""}`}
        ${e.manual ? "" : `<details style="margin-top:8px"><summary>${L("本案例的上限（明确数值）", "This case's limits (explicit values)")}</summary>
          <div class="grid2">${[["budget_usd", L("研究预算上限（美元）", "Research budget limit ($)")], ["openai_budget_usd", L("每个案例的 OpenAI 编码预算（美元）", "OpenAI coding budget per case ($)")], ["max_openai_attempts_per_case", L("每个案例的 OpenAI 请求上限", "OpenAI request limit per case")], ["max_model_attempts_per_case", L("每个案例的模型请求上限", "Model-request limit per case")]].map(([k, lab]) => `<div><label>${esc(lab)}</label><input data-limit="${k}" value="${esc((e.limits || {})[k])}"></div>`).join("")}</div>
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
const CAT_BADGE = { confirmed: "ok", pending: "info", insufficient: "", disputed: "dispute", rule_missing: "bad", not_analyzed: "" };
function codeLabel(row, v) {
  if (!v) return "";
  const m = {}; (row.codes || []).forEach((c) => (m[String(c.code).toUpperCase()] = c.label));
  return v.split(/[;,]/).map((p) => p.trim()).filter(Boolean).map((p) => m[p.toUpperCase()] ? `${p} = ${m[p.toUpperCase()]}` : p).join("; ");
}
async function tabReview(c, body) {
  WB.data = await api("GET", `/api/cases/${c.id}/results`);
  WB.srcMap = Object.fromEntries(WB.data.sources.map((s) => [s.id, s]));
  const cats = ["all", "pending", "confirmed", "insufficient", "disputed", "rule_missing", ...(WB.data.analyzed ? [] : ["not_analyzed"])];
  if (!cats.includes(WB.filter)) WB.filter = "all";
  const counts = { all: WB.data.rows.length }; WB.data.rows.forEach((r) => (counts[r.category] = (counts[r.category] || 0) + 1));
  const sections = [...new Set(WB.data.rows.map((r) => r.section).filter(Boolean))];
  body.innerHTML = `${WB.data.analyzed ? "" : `<div class="callout warn" style="margin-bottom:10px"><b>${L("这个案例还没有分析", "This case has not been analyzed")}</b> — ${L("没有任何编码建议。下面的变量是“未分析”，不代表证据不足、验证失败或模型不一致。来源可以在“来源”页查看和导出；需要时点“分析已选来源”。", "there are no coding suggestions. The variables below are “Not analyzed”: this is not insufficient evidence, a validation failure or a model disagreement. View and export sources on the Sources tab; choose Analyze selected sources when needed.")} <a href="#/case/${c.id}/sources">→ ${t("tab_sources")}</a></div>`}<div class="workbench"><div>
      <div class="row wb-tools"><div class="chips">${cats.map((k) => `<span class="chip ${WB.filter === k ? "on" : ""}" data-f="${k}" role="button" tabindex="0">${t("filter_" + k)} <span class="n">${counts[k] || 0}</span></span>`).join("")}</div><span class="spacer"></span>
      <button id="bulkBtn" class="small" disabled title="${esc(L("两个模型给出相同有效值的变量（同一次运行，或不同运行并附警告）；需要你逐一勾选并确认", "Variables where Claude and GPT gave the same valid value (same run, or separate runs with a warning); you review and confirm them"))}">${L("确认模型一致的变量…", "Confirm model agreements…")}</button></div>
      <div class="row" style="margin-bottom:8px"><input id="wbq" placeholder="${esc(t("search_vars"))}" value="${esc(WB.q)}" style="max-width:260px">
      <select id="wbsec" style="max-width:260px"><option value="">— section —</option>${sections.map((s) => `<option ${WB.section === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
      <span class="small muted">${t("filter_note")}</span></div>
      <div class="wb-table"><table id="wbTable"><thead><tr><th>#</th><th>${t("col_var")}</th><th>${L("Claude 建议", "Claude suggestion")}</th><th>${L("GPT 建议", "GPT suggestion")}</th><th>${L("人工最终值", "Human final")}</th><th>${L("比较", "Comparison")}</th><th>${L("复核状态", "Review status")}</th></tr></thead><tbody id="wbRows"></tbody></table></div>
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
        <td><b class="var-name">${varName(r.name)}</b>${r.issues.length ? ` <span class="badge warn" title="${esc(r.issues.join("\n"))}">!</span>` : ""}${s.stale ? ` <span class="badge bad">stale</span>` : ""}</td>
        ${provCells}
        <td class="val human-final">${final ? `<span class="final-val mono">${esc((rv.value || "∅").slice(0, 60))}</span>${rv.source_provider ? `<div class="small muted">${esc(L("采纳自", "from"))} ${esc(PROV[rv.source_provider] || rv.source_provider)}</div>` : ""}` : rv && rv.action === "deferred" ? `<span class="muted small">${L("暂缓", "deferred")}</span>` : `<span class="muted small">—</span>`}</td>
        <td class="ag-cell">${r.agreement ? `<span class="badge ${agText(r.agreement.status).length > 16 ? "wrap" : ""} ${AG_BADGE[r.agreement.status] || ""}" title="${esc(r.agreement.reason || "")}">${esc(agText(r.agreement.status))}</span>` : r.comparison ? `<span class="badge ${COMP_BADGE[r.comparison.model_status] || ""}">${esc(compText(r.comparison.model_status))}</span>${r.comparison.kind === "cross_model_review" ? `<div class="small muted">${L("跨模型复核（非独立）", "cross-model (not independent)")}</div>` : r.comparison.kind === "cross_version" ? `<div class="small muted">${L("跨版本", "cross-version")}</div>` : ""}` : `<span class="muted small">—</span>`}</td>
        <td><span class="badge ${CAT_BADGE[r.category]}">${t("filter_" + r.category)}</span></td></tr>`;
    }).join("");
    $$("#wbRows tr").forEach((tr) => (tr.onclick = () => { WB.sel = tr.dataset.v; drawRows(); drawDetail(c); }));
  };
  $$(".chip", body).forEach((ch) => {
    ch.onclick = () => { WB.filter = ch.dataset.f; tabReview(c, body); };
    ch.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ch.click(); } };
  });
  const nElig = WB.data.rows.filter((r) => r.agreement && r.agreement.eligible).length;
  if (nElig) { $("#bulkBtn").disabled = false; $("#bulkBtn").classList.add("primary"); $("#bulkBtn").textContent = `${L("确认", "Confirm")} ${nElig} ${L("个模型一致的变量…", nElig === 1 ? "model agreement…" : "model agreements…")}`; }
  $("#bulkBtn").onclick = () => openBulkConfirm(c);
  $("#wbq").oninput = (e) => { WB.q = e.target.value; drawRows(); };
  $("#wbsec").onchange = (e) => { WB.section = e.target.value; drawRows(); };
  drawRows();
  if (WB.sel) drawDetail(c);
}
const AG_BADGE = { eligible: "info", eligible_evidence_difference: "info", eligible_cross_version: "warn", cross_version_disagreement: "bad", confirmed: "ok", cross_model_review: "warn", value_disagreement: "bad", both_insufficient: "", claude_only: "", openai_only: "", validation_failed: "bad", pending: "dispute" };
const AG_TEXT = { eligible: ["独立一致 — 分析版本相同", "Independent agreement — matched analysis version"], eligible_cross_version: ["跨版本一致 — 请核对版本差异", "Cross-version agreement — review version differences"], cross_version_disagreement: ["跨版本不一致 — 模型差异和输入差异都可能有影响", "Cross-version disagreement — model and input differences may both contribute"], cross_model_review: ["跨模型复核（仅供审核）— 非独立", "Cross-model review (audit only) — not independent"], eligible_evidence_difference: ["独立一致 — 分析版本相同（支持来源不同）", "Independent agreement — matched analysis version (different supporting sources)"], confirmed: ["独立一致 — 已人工确认", "Independent model agreement — human confirmed"], value_disagreement: ["取值不一致", "Value disagreement"], both_insufficient: ["均证据不足", "Both insufficient"], claude_only: ["仅 Claude", "Claude only"], openai_only: ["仅 GPT", "GPT only"], validation_failed: ["验证失败", "Validation failed"], pending: ["待人工复核", "Pending human review"] };
const agText = (s) => (AG_TEXT[s] ? L(AG_TEXT[s][0], AG_TEXT[s][1]) : s);
async function openBulkConfirm(c) {
  let d;
  try { d = await api("GET", `/api/cases/${c.id}/bulk_agreements`); } catch (e) { toast(e.message, true); return; }
  if (!d.eligible.length) { toast(L("没有可批量确认的变量", "No variables are eligible")); return; }
  $("#modalRoot").innerHTML = `<div class="modal-bg"><div class="modal" style="width:min(880px,100%)" role="dialog" aria-modal="true">
    <header><b>${L("确认模型一致的变量", "Confirm independent model agreements")}</b></header><div class="body">
    <div class="callout warn small"><b>${L("两个模型一致并不能独立证明取值正确。", "Agreement between two models does not independently prove a value is correct.")}</b>
      ${L("只有你勾选并点击“确认”后，才会写入“人工最终值”；之后仍可在每个变量里撤销或修改。", "Nothing is written until you click Confirm. Each value can still be reset or edited afterwards in that variable's review panel.")}</div>
    <p class="small">${L("可确认", "Eligible")}: <b id="bulkN">${d.eligible.length}</b> · ${L("不符合条件（保持待复核）", "Excluded (stay pending)")}: <b>${d.excluded_count}</b>
      ${Object.keys(d.excluded).length ? `<span class="muted">(${Object.entries(d.excluded).map(([k, v]) => `${esc(agTextFromLabel(k))}: ${v}`).join("; ")})</span>` : ""}</p>
    <div class="wb-table" style="max-height:52vh"><table id="bulkTable"><thead><tr><th><input type="checkbox" id="bulkAll" ${d.eligible.some((x) => x.cross_version) ? "" : "checked"} style="width:auto"></th><th>${t("col_var")}</th><th>${L("一致的取值", "Agreed value")}</th><th>Claude</th><th>GPT</th><th>${L("备注", "Note")}</th></tr></thead><tbody>
    ${d.eligible.map((x) => `<tr><td><input type="checkbox" class="bulkChk" style="width:auto" value="${esc(x.variable)}" data-cross="${x.cross_version ? 1 : 0}" ${x.cross_version ? "" : "checked"}></td><td class="mono">${esc(x.variable)}</td>
      <td><b class="mono">${esc(x.value)}</b>${x.value_label ? `<div class="small muted">${esc(x.value_label)}</div>` : ""}</td>
      <td class="small mono">${esc(x.claude.model || "")}<div class="muted">#${x.claude.suggestion_id}</div></td><td class="small mono">${esc(x.openai.model || "")}<div class="muted">#${x.openai.suggestion_id}</div></td>
      <td class="small">${x.cross_version ? `<div><span class="badge warn">${L("跨版本：取值相同，但分析版本不同", "Cross-version: same suggested value, different analysis versions")}</span></div><div class="muted">${L("不同之处", "Differs in")}: ${esc((x.differences || []).join(", "))}</div>` : ""}${x.reused_from_cache ? `<div><span class="badge info">${L("有结果从已验证缓存复用", "reused from validated cache")}</span></div>` : ""}${x.evidence_difference ? `<span class="badge warn">${L("证据来源不同（均已通过验证）", "different evidence (both validated)")}</span>` : ""}</td></tr>`).join("")}</tbody></table></div>
    <div class="callout warn small" id="xvBox" style="display:none"><b>${L("跨版本结果", "Cross-version results")}</b><p style="margin:4px 0">${esc(d.cross_version_warning || "")}</p>
      <label class="chk"><input type="checkbox" id="xvAck" style="width:auto"> ${L("我已核对版本差异和支持证据", "I have reviewed the version differences and supporting evidence")}</label></div>
    <div class="row" style="margin-top:14px"><button class="primary" id="bulkOk">${L("确认所选", "Confirm selected")} (<span id="bulkK">${d.eligible.filter((x) => !x.cross_version).length}</span>)</button><button id="bulkCancel">${L("取消", "Cancel")}</button></div></div></div></div>`;
  const upd = () => {
    const sel = $$(".bulkChk").filter((x) => x.checked); const xv = sel.some((x) => x.dataset.cross === "1");
    $("#bulkK").textContent = sel.length; $("#xvBox").style.display = xv ? "" : "none";
    $("#bulkOk").disabled = sel.length === 0 || (xv && !$("#xvAck").checked);
  };
  $("#xvAck").onchange = upd;
  $$(".bulkChk").forEach((x) => (x.onchange = upd));
  $("#bulkAll").onchange = (e) => { $$(".bulkChk").forEach((x) => (x.checked = e.target.checked)); upd(); };
  upd();
  $("#bulkCancel").onclick = () => ($("#modalRoot").innerHTML = "");
  $("#bulkOk").onclick = async () => {
    const vars = $$(".bulkChk").filter((x) => x.checked).map((x) => x.value);
    $("#bulkOk").disabled = true;
    try {
      const r = await api("POST", `/api/cases/${c.id}/bulk_confirm`, { variables: vars, confirmed: true, acknowledged_cross_version: $("#xvAck").checked });
      $("#modalRoot").innerHTML = "";
      toast(`${L("已确认", "Confirmed")}: ${r.confirmed.length}${r.skipped.length ? ` · ${L("跳过", "skipped")}: ${r.skipped.length} (${r.skipped.map((s) => s.variable + ": " + s.reason).join("; ")})` : ""}`, r.skipped.length > 0);
      tabReview(c, $("#tabBody"));
    } catch (e) { toast(e.message, true); $("#bulkOk").disabled = false; }
  };
}
function agTextFromLabel(label) { const k = Object.keys(AG_TEXT).find((x) => AG_TEXT[x][1] === label); return k ? agText(k) : label; }
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
  d.innerHTML = `<div class="row"><h2 class="var-name" style="margin:0;font-size:15px">${varName(r.name)}</h2><span class="spacer"></span><span class="badge ${CAT_BADGE[r.category]}">${t("filter_" + r.category)}</span></div>
    <div class="small muted">${esc(r.section || "")} · ${esc(r.type)}${r.multi ? " · multi-select" : ""} · class: ${esc(r.field_class)}</div>
    <h3>${t("definition")}</h3><div class="def">${esc(r.definition || "—")}
      ${r.codes.length ? `<ul class="codes">${r.codes.map((cd) => `<li><b>${esc(cd.code)}</b> = ${esc(cd.label)}</li>`).join("")}</ul>` : ""}
      ${r.open_options.length ? `<div class="small muted" style="margin-top:6px">Listed options (open): ${esc(r.open_options.join("; "))}</div>` : ""}
      ${r.missing_codes.length ? `<div class="small" style="margin-top:6px">${L("此变量定义的特殊缺失值", "Special missing value(s) for this variable")}: <b>${esc(r.missing_codes.map((m) => (r.missing_labels || {})[m] ? `${m} = ${r.missing_labels[m]}` : m).join("; "))}</b> <span class="muted">${L("（编码手册原文；仅在来源表明未知/不适用时使用）", "(codebook wording; use only when the sources indicate it)")}</span></div>` : `<div class="small muted" style="margin-top:6px">No special missing value defined — leave blank when not established.</div>`}
      <div class="small muted" style="margin-top:6px">${t("codebook_ref")}: ${esc(r.codebook_ref || "—")}</div></div>
    ${(r.rule_flags || []).length ? `<div class="callout bad small rule-flags"><b>${L("编码手册规则检查（人工最终值）", "Codebook rule check (human-final values)")}</b><ul style="margin:4px 0 0;padding-left:18px">${r.rule_flags.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>` : ""}
    ${r.issues.length ? `<div class="callout warn small"><b>${t("rule_issues")}</b><ul style="margin:4px 0 0;padding-left:18px">${r.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>` : ""}
    ${r.agreement ? `<div class="small" style="margin:6px 0"><span class="badge ${AG_BADGE[r.agreement.status] || ""}">${esc(agText(r.agreement.status))}</span> ${r.agreement.reason ? `<span class="muted">${esc(r.agreement.reason)}</span>` : ""}${r.review && (r.review.method === "bulk_independent_agreement" || r.review.method === "bulk_separate_run_agreement") ? ` <span class="muted">${L("（通过批量确认写入；可用“撤销复核”或“修改”更正）", "(written by bulk confirmation; use Reset or Edit to correct)")}</span>` : ""}</div>` : ""}
    ${r.comparison ? `<div class="callout ${r.comparison.model_status === "model_agreement" ? "ok" : "warn"} small"><b>${esc(compText(r.comparison.status))}</b>${r.comparison.status === "human_approved" ? ` (${L("模型比较", "models")}: ${esc(compText(r.comparison.model_status))})` : ""}${r.comparison.note ? " — " + esc(r.comparison.note) : ""}
      ${r.comparison.kind === "cross_model_review" ? `<br>${L("跨模型复核：一个模型看过另一个模型的答案，不算独立结果（仅供审核）。", "Cross-model review: one model saw the other's answer; not an independent result (audit only).")}` : ""}
      ${r.comparison.kind === "cross_version" ? `<br><b>${r.comparison.same_value ? L("取值相同，但分析版本不同。", "Same suggested value, different analysis versions.") : L("结果不同，但两个模型用的分析输入也不同。", "Results differ, but the models also used different analysis inputs.")}</b> ${L("这不是相同输入下的对照比较。", "This is not a controlled same-input comparison.")}
        <details id="vdBox" style="margin-top:4px"><summary>${L("查看版本差异", "Show version differences")}</summary><div id="vdOut" class="small">${t("loading")}</div></details>` : ""}
      ${r.comparison.reused_from_cache ? `<br>${L("有结果是从已验证的缓存中复用的（保留原始运行记录）。", "One or more results reused from validated cache (original run kept).")}` : ""}
      <br>${L("模型一致不等于事实已核实；最终值以人工复核为准。", "Model agreement is not verification; the human-reviewed value is final.")}</div>` : ""}
    ${(r.providers || []).length >= 1 ? `<h3>${L("各模型的建议（互不覆盖）", "Suggestions by model (never overwrite each other)")}</h3>${["anthropic", "openai"].filter((k) => !(r.providers || []).some((m) => (m.provider === "openai_compatible" ? "openai" : m.provider) === k)).map((k) => `<div class="panel small" style="padding:8px 12px;margin:6px 0"><b>${esc(PROV[k])}</b> ${cellHtml((r.cells || {})[k], r)}</div>`).join("")}${r.providers.map((m) => `<div class="panel" style="padding:10px 12px;margin:6px 0">
      <div class="row"><b>${esc(L(`${PROV[m.provider === "openai_compatible" ? "openai_compatible" : m.provider] || m.provider} 建议`, `${PROV[m.provider] || m.provider} suggestion`))}</b> <span class="small muted">${esc(PROV_API[m.provider] || "")}</span><span class="small mono">${esc(m.model || "")}</span>${m.interpretation === "cross_model_review" ? `<span class="badge warn">${esc(interpText(m.interpretation))}</span>` : ""}
      ${cellHtml((r.cells || {})[m.provider === "openai_compatible" ? "openai" : m.provider], r)}${m.cache_status && m.cache_status !== "new" ? `<span class="badge info">${L("缓存", "cache")}</span>` : ""}<span class="spacer"></span>
      <button class="small" data-accept-sid="${m.id}" ${m.value && !["model_error", "validation_failed"].includes(m.status) ? "" : "disabled"}>${L("接受此建议", "Accept this")}</button></div>
      <div class="val" style="margin:4px 0">${esc(m.value) || `<span class="muted">(blank)</span>`}${m.value && r.codes.length ? ` <span class="small">${esc(codeLabel(r, m.value))}</span>` : ""}</div>
      ${statusLines(m)}
      ${m.rationale ? `<div class="small"><b>${t("rationale")}:</b> ${esc(m.rationale)}</div>` : ""}
      ${m.unresolved ? `<div class="small"><b>${t("unresolved")}:</b> ${esc(m.unresolved)}</div>` : ""}
      ${((m.validation || {}).selections || []).some((x) => x.outcome === "rejected") ? `<div class="callout warn small"><b>${L("被拒绝的选项", "Rejected selections")}:</b> ${m.validation.selections.filter((x) => x.outcome === "rejected").map((x) => `<span class="mono">${esc(x.code)}</span> (${esc((x.reasons || []).join(", "))})`).join("; ")}<br>${L("保留的选项", "Kept")}: <span class="mono">${esc(m.value || "—")}</span></div>` : ""}
      ${((m.validation || {}).errors || []).length ? `<div class="callout bad small">${esc(m.validation.errors.join("; "))}</div>` : ""}
      ${(m.evidence || []).map(evHtml).join("")}${(m.counter || []).map(evHtml).join("")}</div>`).join("")}<h3>${s.display_kind === "two_providers" ? L("两个模型的综合视图（一致时为共同取值，不一致时为空）", "Both providers — combined view (the shared value when they agree, blank when they differ)") : t("suggestion")}</h3>` : `<h3>${t("suggestion")}</h3>`}
    ${s.status ? `<div class="row"><span class="badge">${esc(s.status)}</span><span class="small muted">${t("basis")}: ${esc(s.basis || "")}${s.provider ? ` · ${esc(PROV[s.provider] || s.provider)} ${esc(s.model || "")}` : ""}</span></div>
      <div class="val" style="font-size:14px;margin:6px 0">${esc(s.value) || `<span class="muted">(blank)</span>`}</div>
      ${s.value && r.codes.length ? `<div class="small">${esc(codeLabel(r, s.value))}</div>` : ""}
      ${s.basis === "model" ? (s.display_kind === "two_providers" ? `<div class="small es-lines"><b>${L("证据状态", "Evidence status")}:</b> ${Object.entries(s.evidence_statuses || {}).map(([p, es]) => `${esc(PROV[p] || p)}: ${esc(esText(es))}`).join(" · ")} <span class="muted">${L("（模型一致不会提升证据状态）", "(agreement never upgrades an evidence status)")}</span> · <b>${L("验证状态", "Validation status")}:</b> ${esc(vsText(s.validation_state))}</div>${s.evidence_review_reason ? `<div class="small muted">${esc(s.evidence_review_reason)}</div>` : ""}` : statusLines(s)) : ""}
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
    <div class="act-group"><button class="primary" id="acceptBtn" ${s.value && !(r.comparison && r.comparison.model_status !== "model_agreement") ? "" : "disabled"} title="${r.comparison && r.comparison.model_status !== "model_agreement" ? esc(L("模型不一致：请在上方选择要接受的建议，或直接修改", "Models differ: accept a specific model's suggestion above, or edit")) : ""}">${t("accept")}</button><button id="deferBtn">${t("defer")}</button><button class="danger" id="clearBtn">${t("clear")}</button>${rv ? `<button id="resetBtn">${t("reset")}</button>` : ""}</div>
    <label>${t("value")}</label>${editor}
    <label>${t("reason")}</label><input id="edReason">
    <div class="act-group"><button id="editBtn">${t("edit")} → ${t("save")}</button><span class="spacer"></span>
      ${["sourced", "judgment"].includes(r.field_class) && !r.rule_missing ? `<button id="recodeVar" title="${esc(L("只重新分析这一个变量；会先显示模式和费用估算", "Re-analyze only this variable; shows the mode and cost estimate first"))}">${L("只重新分析此变量", "Re-analyze this variable")}</button>` : ""}</div>
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
  if ($("#vdBox")) $("#vdBox").ontoggle = async () => {
    if (!$("#vdBox").open) return;
    try {
      const v = await api("GET", `/api/cases/${c.id}/version_diff?variable=${encodeURIComponent(r.name)}`);
      const rowv = (lab, k) => `<tr><td>${lab}</td><td class="mono">${esc(v.claude[k] ?? L("未记录", "not recorded"))}</td><td class="mono">${esc(v.openai[k] ?? L("未记录", "not recorded"))}</td></tr>`;
      const lst = (o) => (o ? `${L("仅 Claude 版本", "only in Claude's version")}: ${esc((o.only_in_claude_version || []).join(", ") || "—")}; ${L("仅 GPT 版本", "only in GPT's version")}: ${esc((o.only_in_openai_version || []).join(", ") || "—")}${o.changed_text ? `; ${L("文字有变化", "text changed")}: ${esc(o.changed_text.join(", ") || "—")}` : ""}` : L("未记录（版本化之前的结果）", "not recorded (result from before versioning)"));
      $("#vdOut").innerHTML = `<div><b>${L("不同之处", "Differs in")}:</b> ${esc((v.differences || []).join(", ") || "—")}</div>
        <table class="small" style="margin:6px 0"><thead><tr><th></th><th>Claude</th><th>GPT</th></tr></thead><tbody>
        ${rowv(L("证据版本", "Evidence version"), "evidence_snapshot_id")}${rowv(L("编码手册版本", "Codebook version"), "codebook_version")}${rowv(L("提示词版本", "Prompt version"), "prompt_version")}${rowv(L("分析版本", "Analysis version"), "analysis_spec_id")}${rowv(L("模型", "Model"), "model")}${rowv(L("原始运行", "Original run"), "original_run_id")}
        <tr><td>${L("生成时间", "Generated")}</td><td>${esc(fmtTime(v.claude.generated_at))}</td><td>${esc(fmtTime(v.openai.generated_at))}</td></tr>${rowv(L("缓存", "Cache"), "cache_status")}</tbody></table>
        <div><b>${L("来源", "Sources")}:</b> ${"sources" in v ? lst(v.sources) : "—"}</div>
        <div><b>${L("段落", "Passages")}:</b> ${"passages" in v ? lst(v.passages) : "—"}</div>
        ${v.analysis ? `<div><b>${L("分析设置的差异", "Analysis differences")}:</b> ${esc(Object.keys(v.analysis).join(", "))}</div>` : ""}`;
    } catch (err) { $("#vdOut").textContent = err.message; }
  };
  if ($("#recodeOne")) $("#recodeOne").onclick = () => startRecode(c.id, [r.name]);
  if ($("#recodeVar")) $("#recodeVar").onclick = (ev) => startRecode(c.id, [r.name], ev.currentTarget);
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

// ------------------------------------------------------------------ sources (D-046: grouped by the project's source-priority convention)
const TYPES = ["aar", "government", "regulatory", "legislative", "academic", "ngo_technical", "media", "unknown"];
const TYPE_TEXT = { aar: ["事后评估报告", "After-action report"], government: ["政府", "Government"], regulatory: ["监管", "Regulatory"], legislative: ["立法", "Legislative"],
  academic: ["学术", "Academic"], ngo_technical: ["技术报告", "Technical report"], media: ["新闻", "News media"], unknown: ["其他 / 未分类", "Other / unclassified"] };
const SRC_GROUPS = [["aar", ["事后评估报告", "After-action reports"], ["aar"]], ["gov", ["政府与监管文件", "Government and regulatory documents"], ["government", "regulatory"]],
  ["legis", ["立法文件", "Legislative documents"], ["legislative"]], ["acad", ["学术与技术报告", "Academic and technical reports"], ["academic", "ngo_technical"]],
  ["media", ["新闻媒体", "News media"], ["media"]], ["other", ["其他来源 / 未分类", "Other sources / unclassified"], []]];
// Kept for the D-041 test: type rank (AAR, official, legislative, academic / technical, news, other)
const SRC_TYPE_RANK = { aar: 0, government: 1, regulatory: 1, legislative: 2, academic: 3, ngo_technical: 3, media: 4 };
const REL_RANK = { relevant: 0, background: 1, uncertain: 2, unchecked: 2, irrelevant: 3 };
const REL_TEXT = { relevant: ["直接相关", "Directly relevant", "neutral"], background: ["背景资料", "Background", "neutral"], uncertain: ["需要复核", "Needs review", "warn"],
  unchecked: ["未评估", "Not assessed", "warn"], irrelevant: ["无关", "Irrelevant", "neutral"] };  // relevance is never green/red: it is a topic match, not accuracy
const CONTENT_TEXT = { full_text: ["有文档正文", "Document text available", "ok"], partial: ["部分内容 / 摘要", "Partial content / abstract", "info"],
  no_usable_text: ["没有可用的文档正文", "No usable document text", "bad"], not_retrieved: ["未读取", "Not retrieved", "bad"], interrupted: ["读取未完成", "Retrieval incomplete", "bad"] };
const SRC_SORTS = ["type", "length", "found"];  // "type" = within-group default: relevance tier, usable text first, length
let SRC_SORT = (() => { try { const v = localStorage.getItem("wfd_src_sort"); return SRC_SORTS.includes(v) ? v : "type"; } catch (e) { return "type"; } })();
const SRC_FILTER = { type: "", rel: "", content: "", lang: "", sel: "", run: "", q: "" };
const SRC_OPEN = {};  // collapsed groups / expanded version lists, this page view only
const contentOf = (s) => s.content_status || (s.fetch_status === "ok" ? "" : "not_retrieved");
const usableText = (s) => s.fetch_status === "ok" && ["full_text", "partial", ""].includes(contentOf(s));
const groupOf = (s) => (SRC_GROUPS.find((g) => g[2].includes(s.source_type)) || SRC_GROUPS[5])[0];
function sortSources(rows, mode) {
  // Authority group order is always kept (D-046); the mode only orders sources INSIDE each group.
  const rank = (s) => (s.source_type in SRC_TYPE_RANK ? SRC_TYPE_RANK[s.source_type] : 5);
  const len = (a, b) => (b.n_pages || 0) - (a.n_pages || 0) || (b.n_passages || 0) - (a.n_passages || 0);
  const inner = mode === "length" ? (a, b) => len(a, b) || a.id - b.id
    : mode === "found" ? (a, b) => a.id - b.id
    : (a, b) => (REL_RANK[a.relevance_status] ?? 2) - (REL_RANK[b.relevance_status] ?? 2) || (usableText(a) ? 0 : 1) - (usableText(b) ? 0 : 1) || len(a, b) || a.id - b.id;
  return rows.slice().sort((a, b) => rank(a) - rank(b) || inner(a, b));
}
const srcLink = (id, fmt, all) => `/api/cases/${id}/export?format=${fmt}&all=${all ? 1 : 0}`;  // D-045 sources-only export
function srcPassesFilter(s, f) {
  if (f.type && groupOf(s) !== f.type) return false;
  if (f.rel && (s.relevance_status || "unchecked") !== f.rel) return false;
  if (f.content && (contentOf(s) || "unchecked") !== f.content) return false;
  if (f.lang && (s.language || "?") !== f.lang) return false;
  if (f.sel === "selected" && s.excluded) return false;
  if (f.sel === "not_selected" && !s.excluded) return false;
  if (f.sel === "eligible" && !s.eligible) return false;
  if (f.sel === "not_eligible" && s.eligible) return false;
  if (f.run && String(s.job_id || "manual") !== f.run) return false;
  if (f.q) { const q = f.q.toLowerCase(); if (!`${s.title || ""} ${s.publisher || ""} ${s.url || ""}`.toLowerCase().includes(q)) return false; }
  return true;
}
function rqHtml(r) {  // D-047 retrieval-quality report (read-only)
  const tbl = (head, rows) => `<table class="small" style="width:auto;margin:6px 0 12px"><thead><tr>${head.map((x) => `<th>${x}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${head.length}" class="muted">—</td></tr>`}</tbody></table>`;
  const GL = { aar: ["事后评估报告", "After-action reports"], gov: ["政府与监管", "Government and regulatory"], legis: ["立法", "Legislative"], acad: ["学术与技术", "Academic and technical"], media: ["新闻媒体", "News media"], other: ["其他 / 未分类", "Other / unclassified"] };
  return `<div style="color:var(--ink)">
    <p class="muted">${esc(L("只统计本案例已经保存的内容。“缺口”表示没有保存到可用的文档，并不代表这种文档不存在。生成这份报告不会搜索、下载或调用模型。", r.note))}</p>
    <h4 style="margin:8px 0 4px">${L("缺口", "Gaps")}</h4>${r.gaps.length ? `<ul>${r.gaps.map((g) => `<li>${esc(L(g.zh, g.en))}</li>`).join("")}</ul>` : `<p class="muted">${L("没有发现明显缺口。", "No obvious gaps.")}</p>`}
    ${r.official_bodies.length ? `<h4 style="margin:8px 0 4px">${L("官方机构（按网站搜索）", "Official bodies (site-restricted searches)")}</h4>` + tbl([L("机构", "Body"), L("网站", "Site"), L("搜索次数", "Searched"), L("搜索结果", "Results"), L("已保存", "Saved"), L("有可用正文", "Usable text"), L("来源", "Sources")],
      r.official_bodies.map((b) => `<tr><td>${esc(b.name)}</td><td class="mono">${esc(b.site)}</td><td>${b.searched}</td><td>${b.results}</td><td>${b.saved}</td><td><b>${b.usable}</b></td><td>${esc(b.examples.join(", "))}</td></tr>`)) : ""}
    <h4 style="margin:8px 0 4px">${L("语言", "Languages")}</h4>${tbl([L("语言", "Language"), L("已保存", "Saved"), L("有可用正文", "Usable text"), L("直接相关", "Directly relevant"), L("网页声明 / 按文字估计", "Declared / estimated from text")],
      r.languages.map((l) => `<tr><td>${esc(l.name)}${r.local_language && l.code === r.local_language.split("-")[0] ? ` <span class="badge info">${L("当地语言", "local language")}</span>` : ""}</td><td>${l.saved}</td><td><b>${l.usable}</b></td><td>${l.relevant}</td><td>${l.declared} / ${l.estimated}</td></tr>`))}
    <h4 style="margin:8px 0 4px">${L("文档类型", "Document types")}</h4>${tbl([L("类型", "Type"), L("已保存", "Saved"), L("有可用正文", "Usable text"), L("直接相关", "Directly relevant")],
      r.types.map((t) => `<tr><td>${esc(L(GL[t.group][0], GL[t.group][1]))}</td><td>${t.saved}</td><td><b>${t.usable}</b></td><td>${t.relevant}</td></tr>`))}
    <h4 style="margin:8px 0 4px">${L("各类搜索的收获", "What each kind of search produced")}</h4>${tbl([L("搜索类型", "Kind of query"), L("次数", "Queries"), L("失败", "Failed"), L("不同结果网址", "Distinct results"), L("已保存", "Saved"), L("有可用正文", "Usable text"), L("直接相关", "Directly relevant")],
      r.query_yield.map((y) => `<tr><td>${esc(y.kind)}</td><td>${y.queries}</td><td>${y.failed}</td><td>${y.results}</td><td>${y.saved}</td><td><b>${y.usable}</b></td><td>${y.relevant}</td></tr>`))}
    <p class="muted">${L("语言：网页声明了就用声明；否则按正文中的常用虚词估计（本地规则，可能不准）。一个来源可能被多种搜索找到，所以各行之和可能大于来源总数。", "Language: the page's declaration when present, otherwise an estimate from common function words in the saved text (local rule; may be wrong). A source found by several kinds of query is counted in each row, so rows can add up to more than the total.")}</p></div>`;
}
async function tabSources(c, body) {
  const all = await api("GET", `/api/cases/${c.id}/sources`);
  const cnt = await api("GET", `/api/cases/${c.id}/source_counts${SRC_FILTER.run && SRC_FILTER.run !== "manual" ? "?run=" + encodeURIComponent(SRC_FILTER.run) : ""}`);
  const job = await api("GET", `/api/cases/${c.id}/job`);
  const busyJob = job && ["running", "queued"].includes(job.status);
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
  const shown = sortSources(all.filter((s) => srcPassesFilter(s, SRC_FILTER)), SRC_SORT);
  // document groups: one representative row (usable text first, then type priority) with the other versions under it
  const byGroup = {};
  shown.forEach((s) => { if (s.doc_group) (byGroup[s.doc_group] = byGroup[s.doc_group] || []).push(s); });
  const repOf = {};
  Object.values(byGroup).forEach((ms) => { const rep = ms.slice().sort((a, b) => (usableText(a) ? 0 : 1) - (usableText(b) ? 0 : 1) || (b.n_passages || 0) - (a.n_passages || 0) || a.id - b.id)[0]; ms.forEach((m) => (repOf[m.id] = rep.id)); });
  const sortNames = { type: L("相关性优先（默认）", "Relevance first (default)"), length: L("篇幅（页数，其次段落数）", "Length (pages, then passages)"), found: L("找到顺序（S 编号）", "Order found (S number)") };
  const langs = [...new Set(all.map((s) => s.language || "?"))].sort();
  const runs = [...new Set(all.map((s) => String(s.job_id || "manual")))].sort((a, b) => (a === "manual") - (b === "manual") || +a - +b);
  const shownStats = { n: shown.length, text: shown.filter(usableText).length, rel: shown.filter((s) => s.relevance_status === "relevant").length, eligible: shown.filter((s) => s.eligible).length };
  const runCnt = cnt.run || null;
  const scopeRow = (label, k, fmt) => `<tr><td>${label}</td><td><b>${fmt(cnt)}</b></td><td>${runCnt ? `<b>${fmt(runCnt)}</b>` : "—"}</td></tr>`;
  const badge = (map, k) => { const m = map[k] || [k, k, ""]; return `<span class="badge ${m[2]}">${esc(L(m[0], m[1]))}</span>`; };
  const row = (s, alt) => {
    const cs = contentOf(s);
    const others = !alt && s.doc_group ? byGroup[s.doc_group].filter((m) => m.id !== s.id) : [];
    return `<tr data-sid="${s.id}" class="${alt ? "alt-version" : ""}" ${alt && !SRC_OPEN["v" + repOf[s.id]] ? "hidden" : ""}>
      <td class="mono small">S${s.id}</td>
      <td><b>${esc(s.title || s.url || "")}</b>${alt ? ` <span class="badge neutral">${L("另一版本", "other version")}</span>` : ""}
        <div class="small muted">${[s.publisher || host(s.url || s.final_url), s.published_date && (L("发布 ", "published ") + s.published_date), s.language && (L("语言 ", "language ") + s.language)].filter(Boolean).map(esc).join(" · ")}</div>
        <div class="small">${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${L("原始链接", "Original link")}</a>` : ""}${s.fetch_status === "ok" && s.n_passages ? ` · <a href="#" data-open="${s.id}">${L("查看保存的正文", "View saved text")}</a>` : ""}
          ${(JSON.parse(s.topic_tags || "[]")).map((x) => `<span class="badge neutral" title="${esc(L("主题提示，仅供参考，不是编码", "Topic hint only — not coding"))}">${esc(x.replace(/_/g, " "))}</span>`).join(" ")}</div>
        ${others.length ? `<button class="small linkish" data-vers="${s.id}">${SRC_OPEN["v" + s.id] ? "▾" : "▸"} ${L("同一文档的其他版本", "Other versions of this document")} (${others.length})</button>` : ""}
        <details class="small"><summary>${L("细节", "Details")}</summary>
          <div class="muted">${L("发现方式", "Found via")}: ${esc(s.found_via || s.origin || "")}${s.job_id ? ` · ${L("搜索运行", "search run")} ${s.job_id}` : ` · ${L("用户添加", "added by user")}`}</div>
          ${s.final_url && s.final_url !== s.url ? `<div class="muted">${L("跳转到", "Redirected to")}: ${esc(s.final_url)}</div>` : ""}
          ${s.type_reason ? `<div class="muted">${L("类型依据", "Type basis")}: ${esc(s.type_reason)}</div>` : ""}
          ${s.relevance_reason ? `<div class="muted">${L("相关性依据", "Relevance basis")}: ${esc(s.relevance_reason)}</div>` : ""}
          ${s.content_reason ? `<div class="muted">${L("内容检查", "Content check")}: ${esc(s.content_reason)}</div>` : ""}
          ${s.fetch_error ? `<div class="muted">${L("读取记录", "Retrieval record")}: ${esc(s.fetch_error)}</div>` : ""}
          ${s.ocr_status && !["not_needed", "not_applicable"].includes(s.ocr_status) ? `<div class="muted">${esc(s.ocr_status)}</div>` : ""}
          ${s.fetch_status !== "ok" && s.snippet ? `<div><span class="badge neutral">${L("搜索结果摘要 — 不是读取到的正文", "Search-result snippet — not retrieved text")}</span> <span class="muted">${esc(s.snippet.slice(0, 300))}</span></div>` : ""}
          ${s.duplicate_of ? `<div class="muted">${t("dup_of")} S${s.duplicate_of}</div>` : ""}${s.near_duplicate_of ? `<div class="muted">${t("near_of")} S${s.near_duplicate_of} (${Math.round((s.similarity || 0) * 100)}%)</div>` : ""}
          <div class="muted">${L("规则版本", "Rule version")}: ${esc(s.rule_version || L("较早的规则", "earlier rules"))} · <a href="#" data-hist="${s.id}">${L("修改记录", "Change history")}</a></div>
        </details></td>
      <td><select data-type="${s.id}" style="width:auto" aria-label="${esc(L("文档类型", "Document type"))}">${TYPES.map((x) => `<option value="${x}" ${x === s.source_type ? "selected" : ""}>${esc(L(TYPE_TEXT[x][0], TYPE_TEXT[x][1]))}</option>`).join("")}</select>
        <div class="small muted">${s.type_subtype ? esc(s.type_subtype.replace(/_/g, " ")) + " · " : ""}${s.type_basis === "human" ? L("人工确认", "human-confirmed") : L("自动判断", "automatic")}</div></td>
      <td>${badge(REL_TEXT, s.relevance_status || "unchecked")}<div class="small muted">${s.relevance_basis === "human" ? L("人工确认", "human-confirmed") : L("自动判断", "automatic")} · ${esc((s.relevance_reason || "").split(";")[0].slice(0, 120))}</div></td>
      <td>${cs ? badge(CONTENT_TEXT, cs) : `<span class="badge neutral">${L("已保存正文 — 尚未按新规则检查", "Text saved — not yet checked by current rules")}</span>`}
        <div class="small muted">${s.fetch_status === "ok" ? `${s.n_pages ? s.n_pages + " pp · " : ""}${s.n_passages || 0} passages` : ""}</div></td>
      <td class="small">${s.excluded ? `<span class="badge neutral">${L("未选中", "Not selected")}</span>` : `<span class="badge info">${L("已选中", "Selected")}</span>`}
        <div>${s.eligible ? `<span class="badge ok">${L("可用于分析", "Eligible for analysis")}</span>` : `<span class="muted">${L("不会用于分析", "Not used in analysis")}</span>`}</div></td>
      <td class="actions"><div class="row"><button class="small" data-excl="${s.id}" data-on="${s.excluded ? 0 : 1}" title="${esc(L("只改变是否用于分析；不会删除来源，也不会改动搜索记录或已完成的分析", "Only changes whether it is used in analysis; never deletes the source, the search record or a finished analysis"))}">${s.excluded ? L("选中", "Select") : L("取消选中", "Deselect")}</button>
        <select class="small" data-rel="${s.id}" style="width:auto" aria-label="${esc(L("更正相关性", "Correct relevance"))}"><option value="">${L("更正相关性…", "relevance…")}</option>${["relevant", "background", "uncertain", "irrelevant"].map((x) => `<option value="${x}">${esc(L(REL_TEXT[x][0], REL_TEXT[x][1]))}</option>`).join("")}</select></div></td></tr>`;
  };
  const groupsHtml = SRC_GROUPS.map(([gk, gl]) => {
    const members = shown.filter((s) => groupOf(s) === gk);
    const reps = members.filter((s) => !s.doc_group || repOf[s.id] === s.id);
    const total = all.filter((s) => groupOf(s) === gk).length;
    const open = SRC_OPEN["g" + gk] !== false;
    return `<tbody class="src-group" data-group="${gk}"><tr class="grp-h"><td colspan="7"><button class="linkish" data-grp="${gk}">${open ? "▾" : "▸"} <b>${esc(L(gl[0], gl[1]))}</b></button>
        <span class="small muted">${members.length}${members.length !== total ? ` ${L("条（筛选后）/ 共", "shown /")} ${total}` : ""}</span></td></tr>
      ${open ? reps.map((s) => row(s, false) + (s.doc_group ? byGroup[s.doc_group].filter((m) => m.id !== s.id).map((m) => row(m, true)).join("") : "")).join("") : ""}</tbody>`;
  }).join("");
  const sel = (id, label, opts) => `<label class="small" style="margin:0">${label}<select id="${id}" class="small" style="width:auto;display:block">${opts}</select></label>`;
  const opt = (v, label, cur) => `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(label)}</option>`;
  body.innerHTML = `
    <div class="panel" id="srcHead"><div class="row" style="align-items:center;gap:10px;flex-wrap:wrap">
      <b>${esc(c.name)}</b><span class="small muted">${L("来源范围", "Scope")}: ${L("本案例全部搜索运行累计", "all search runs of this case, cumulative")} (${all.length} ${L("条已保存", "saved")}, ${(cnt.runs || []).length} ${L("次搜索运行", "search runs")})</span>
      <span class="spacer"></span>${sel("fRun", L("搜索运行", "Search run"), opt("", L("全部运行", "All runs"), SRC_FILTER.run) + runs.map((r) => opt(r, r === "manual" ? L("用户添加", "Added by user") : L("运行 ", "Run ") + r, SRC_FILTER.run)).join(""))}</div></div>
    <div class="panel" style="margin-top:12px" id="srcCounts"><h3 style="margin-top:0">${L("来源与读取质量", "Sources and retrieval quality")}</h3>
      <table class="small" style="width:auto"><thead><tr><th></th><th>${L("全案例（所有运行）", "Case-wide (all runs)")}</th><th>${SRC_FILTER.run && SRC_FILTER.run !== "manual" ? L("所选运行 ", "Run ") + esc(SRC_FILTER.run) : L("所选运行", "Selected run")}</th></tr></thead><tbody>
        ${scopeRow(L("搜索发现（不同网址）", "Discovered (distinct addresses in results)"), "d", (x) => x.discovered)}
        ${scopeRow(L("已保存的来源", "Saved sources"), "s", (x) => x.stored)}
        ${scopeRow(L("有文档正文（全文或部分）", "Document text available (full or partial)"), "t", (x) => x.text_available)}
        ${scopeRow(L("没有可用的文档正文", "No usable document text"), "n", (x) => x.no_usable_text)}
        ${scopeRow(L("未读取 / 被拒 / 未完成", "Not retrieved / blocked / incomplete"), "f", (x) => x.failed)}
        ${scopeRow(L("直接相关 · 背景 · 无关", "Directly relevant · background · irrelevant"), "r", (x) => `${x.relevant} · ${x.background} · ${x.irrelevant}`)}
        ${scopeRow(L("已选中 · 可用于分析", "Selected · eligible for analysis"), "e", (x) => `${x.selected} · ${x.usable_for_analysis}`)}
      </tbody></table>
      <p class="small muted" style="margin:6px 0 0">${L("这几行的分母不同，不是一条漏斗：“搜索发现”数的是搜索结果里的网址；其余数的是已保存的来源。“有文档正文”不代表内容准确或完整；“可用于分析”= 已读取、有可用正文、已选中、不是重复、未标为无关。当前显示：", "These rows have different denominators and are not one funnel: Discovered counts addresses in search results; the others count saved sources. Text available does not mean accurate or complete; Eligible = retrieved, usable text, selected, not a duplicate, not irrelevant. Shown now: ")}<b>${shownStats.n}</b> ${L("条（文本可用", "(text available")} ${shownStats.text} · ${L("直接相关", "directly relevant")} ${shownStats.rel} · ${L("可用于分析", "eligible")} ${shownStats.eligible})</p>
      ${busyJob ? `<p class="small"><b>${L("任务正在运行：这里显示的是到目前为止已保存的来源，不会自动更新，请点“刷新”。", "A task is running: this shows the sources saved so far; it does not update by itself — use Refresh.")}</b></p>` : ""}
      ${cnt.not_on_current_rules ? `<div class="callout warn small" style="margin-top:8px">${cnt.not_on_current_rules} ${L("条来源还没有用当前规则检查内容、相关性和类型。", "source(s) have not been checked with the current content, relevance and type rules.")} <button class="small" id="srPreview">${L("预览重新评估（不会改动任何内容）", "Preview reassessment (changes nothing)")}</button></div>` : `<p class="small muted">${L("所有来源都已按当前规则", "All sources are on the current rules")} (${esc(cnt.rule_version_current || "")}) ${L("检查。", "")}</p>`}</div>
    <details class="panel" style="margin-top:12px" id="rqPanel"><summary><b>${L("检索质量", "Retrieval quality")}</b> <span class="small muted">${L("（语言、来源类型、官方机构、缺口；只统计已保存的数据）", "(languages, document types, official bodies, gaps; counts saved data only)")}</span></summary><div id="rqBody" class="small muted">${L("正在载入…", "Loading…")}</div></details>
    <div class="panel" style="margin-top:12px" id="srcTools">
      <div class="row" style="gap:8px;flex-wrap:wrap;align-items:flex-end">
        ${sel("fType", L("文档类型", "Document type"), opt("", L("全部", "All"), SRC_FILTER.type) + SRC_GROUPS.map(([k, l]) => opt(k, L(l[0], l[1]), SRC_FILTER.type)).join(""))}
        ${sel("fRel", L("相关性", "Incident relevance"), opt("", L("全部", "All"), SRC_FILTER.rel) + ["relevant", "background", "uncertain", "irrelevant", "unchecked"].map((k) => opt(k, L(REL_TEXT[k][0], REL_TEXT[k][1]), SRC_FILTER.rel)).join(""))}
        ${sel("fContent", L("读取质量", "Retrieval quality"), opt("", L("全部", "All"), SRC_FILTER.content) + Object.keys(CONTENT_TEXT).map((k) => opt(k, L(CONTENT_TEXT[k][0], CONTENT_TEXT[k][1]), SRC_FILTER.content)).join("") + opt("unchecked", L("尚未检查", "Not yet checked"), SRC_FILTER.content))}
        ${sel("fLang", L("语言", "Language"), opt("", L("全部", "All"), SRC_FILTER.lang) + langs.map((l) => opt(l, l === "?" ? L("未知", "unknown") : l, SRC_FILTER.lang)).join(""))}
        ${sel("fSel", L("选择 / 分析", "Selection / analysis"), opt("", L("全部", "All"), SRC_FILTER.sel) + [["selected", L("已选中", "Selected")], ["not_selected", L("未选中", "Not selected")], ["eligible", L("可用于分析", "Eligible for analysis")], ["not_eligible", L("不会用于分析", "Not used in analysis")]].map(([k, l]) => opt(k, l, SRC_FILTER.sel)).join(""))}
        <label class="small" style="margin:0">${L("标题 / 发布者关键词", "Title or publisher keyword")}<input id="fQ" class="small" value="${esc(SRC_FILTER.q)}" style="display:block;width:200px"></label>
        ${sel("srcSort", L("组内排序", "Order within groups"), SRC_SORTS.map((x) => opt(x, sortNames[x], SRC_SORT)).join(""))}
        <button class="small" id="fClear">${L("清除筛选", "Clear filters")}</button><button class="small" id="srcRefresh">${L("刷新", "Refresh")}</button></div>
      <p class="small muted" style="margin:6px 0 0">${L("筛选和排序只改变显示，不会改变选择、分析输入或导出。分组顺序是本项目的来源优先约定（事后评估报告、政府/监管、立法、学术/技术、新闻、其他），不是对可信度的独立排名。", "Filters and sorting change the view only — never selections, analysis inputs or exports. Group order is the project's source-priority convention (after-action reports, government / regulatory, legislative, academic / technical, news, other), not an independent ranking of truthfulness.")}</p>
      <div class="row" style="gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap" id="srcExport">
        <a id="srcXlsx" href="${srcLink(c.id, "sources", false)}"><button class="small">${L("导出来源清单（Excel）", "Export source list (Excel)")}</button></a><a id="srcCsv" href="${srcLink(c.id, "sources_csv", false)}"><button class="small">CSV</button></a>
        <label class="chk small" style="margin:0"><input type="checkbox" id="srcAll" style="width:auto"> ${L("包括未选中的来源", "Include deselected sources")}</label>
        <span class="small muted" id="srcExpNote">${L("导出内容：全部已选中的来源（不受上面的筛选影响）。", "Export contains: all selected sources (filters above do not apply).")}</span>
        <span class="spacer"></span><button class="small primary" id="recodeAll" ${cnt.usable_for_analysis ? "" : "disabled"} title="${esc(L("用已保存的已选来源正文做编码分析，不会重新搜索", "Code the saved text of the selected sources; no new search"))}">${L("分析已选来源", "Analyze selected sources")}</button></div>
      <div id="affBox"></div></div>
    <div class="panel" style="padding:0;margin-top:12px"><table id="srcTable"><thead><tr><th>#</th><th>${L("文档", "Document")}</th><th>${L("文档类型", "Document type")}</th><th>${L("事件相关性", "Incident relevance")}</th><th>${L("内容 / 读取", "Content / retrieval")}</th><th>${L("选择 / 分析", "Selected / analysis")}</th><th></th></tr></thead>
      ${shown.length ? groupsHtml : `<tbody><tr><td colspan="7" class="muted">${all.length ? L("没有符合筛选条件的来源。", "No sources match the filters.") : t("none")}</td></tr></tbody>`}</table></div>
    <details class="panel" style="margin-top:12px" id="srcAdd"><summary><b>${t("src_add")}</b> <span class="small muted">${L("（可选，手动补充）", "(optional, manual)")}</span></summary>
      <div class="grid3" style="margin-top:8px"><div class="add-box"><label>${t("add_url")}</label><input id="addUrl" placeholder="https://"><button id="addUrlBtn" class="add-btn">${t("add")}</button></div>
      <div class="add-box"><label>${t("add_file")} (PDF, HTML, DOCX, TXT)</label><input id="addFile" type="file" multiple><button id="addFileBtn" class="add-btn">${t("add")}</button></div>
      <div class="add-box"><label>${t("add_text")}</label><input id="addTitle" placeholder="${t("src_title")}"><textarea id="addText" style="margin-top:4px"></textarea><button id="addTextBtn" class="add-btn">${t("add")}</button></div></div>
      <p class="small muted">${LANG === "zh" ? "不会绕过登录或付费墙；无法访问的来源可在有合法访问权时手动补充正文。" : "Logins and paywalls are never bypassed; add text manually if you have legitimate access."}</p></details>`;
  const rerender = () => tabSources(c, body);
  $("#rqPanel").ontoggle = async () => {
    if (!$("#rqPanel").open || $("#rqPanel").dataset.loaded) return;
    try { $("#rqBody").innerHTML = rqHtml(await api("GET", `/api/cases/${c.id}/retrieval_quality`)); $("#rqPanel").dataset.loaded = "1"; }
    catch (e) { $("#rqBody").textContent = e.message; }
  };
  const add = async (payload) => { try { const s = await api("POST", `/api/cases/${c.id}/sources`, payload); toast(`S${s.id}: ${s.fetch_status}${s.fetch_error ? " — " + s.fetch_error : ""}`, s.fetch_status !== "ok"); rerender(); } catch (e) { toast(e.message, true); } };
  $("#srcAll").onchange = (ev) => { $("#srcXlsx").href = srcLink(c.id, "sources", ev.target.checked); $("#srcCsv").href = srcLink(c.id, "sources_csv", ev.target.checked);
    $("#srcExpNote").textContent = ev.target.checked ? L("导出内容：全部来源，包括未选中的（不受上面的筛选影响）。", "Export contains: all sources, including deselected ones (filters above do not apply).") : L("导出内容：全部已选中的来源（不受上面的筛选影响）。", "Export contains: all selected sources (filters above do not apply)."); };
  $("#addUrlBtn").onclick = () => add({ kind: "url", url: $("#addUrl").value.trim() });
  $("#addTextBtn").onclick = () => add({ kind: "text", title: $("#addTitle").value, text: $("#addText").value });
  $("#addFileBtn").onclick = async () => { for (const f of $("#addFile").files) await add({ kind: "file", filename: f.name, data: await fileToB64(f) }); };
  $("#recodeAll").onclick = (ev) => startRecode(c.id, null, ev.currentTarget);
  $("#srcRefresh").onclick = rerender;
  $("#srcSort").onchange = (ev) => { SRC_SORT = ev.target.value; try { localStorage.setItem("wfd_src_sort", SRC_SORT); } catch (e) {} rerender(); };
  [["fType", "type"], ["fRel", "rel"], ["fContent", "content"], ["fLang", "lang"], ["fSel", "sel"], ["fRun", "run"]].forEach(([id, k]) => ($("#" + id).onchange = (ev) => { SRC_FILTER[k] = ev.target.value; rerender(); }));
  $("#fQ").onchange = (ev) => { SRC_FILTER.q = ev.target.value.trim(); rerender(); };
  $("#fClear").onclick = () => { Object.keys(SRC_FILTER).forEach((k) => (SRC_FILTER[k] = "")); rerender(); };
  $$("[data-grp]", body).forEach((b) => (b.onclick = () => { SRC_OPEN["g" + b.dataset.grp] = SRC_OPEN["g" + b.dataset.grp] === false; rerender(); }));
  $$("[data-vers]", body).forEach((b) => (b.onclick = () => { SRC_OPEN["v" + b.dataset.vers] = !SRC_OPEN["v" + b.dataset.vers]; rerender(); }));
  $$("[data-open]", body).forEach((b) => (b.onclick = (ev) => { ev.preventDefault(); openSource(+b.dataset.open); }));
  $$("[data-hist]", body).forEach((b) => (b.onclick = async (ev) => {
    ev.preventDefault();
    const h = await api("GET", `/api/sources/${b.dataset.hist}/history`);
    await askDialog({ title: `S${b.dataset.hist} — ${L("修改记录", "Change history")}`, okText: t("close"), cancelText: t("close"),
      body: h.length ? `<table class="small"><thead><tr><th>${L("时间", "When")}</th><th>${L("字段", "Field")}</th><th>${L("原值", "Before")}</th><th>${L("新值", "After")}</th><th>${L("方式", "By")}</th><th>${L("原因", "Reason")}</th></tr></thead><tbody>${h.map((x) => `<tr><td>${fmtTime(x.at)}</td><td>${esc(x.field)}</td><td>${esc(x.old_value ?? "—")}</td><td>${esc(x.new_value ?? "—")}</td><td>${esc(x.basis === "human" ? (x.changed_by || L("复核者", "reviewer")) : L("规则 ", "rule ") + (x.rule_version || "") + (x.changed_by ? " · " + x.changed_by : ""))}</td><td>${esc(x.reason || "")}</td></tr>`).join("")}</tbody></table>` : `<p class="small muted">${L("还没有修改记录。", "No changes recorded yet.")}</p>` });
  }));
  if ($("#srPreview")) $("#srPreview").onclick = async (ev) => {
    const btn = ev.currentTarget;  // currentTarget is null after an await
    busy(btn, true, L("正在计算…", "Calculating…"));
    let d;
    try { d = await api("GET", `/api/cases/${c.id}/source_review`); } catch (e) { toast(e.message, true); busy(btn, false); return; }
    busy(btn, false);
    const ex = Object.entries(d.examples || {}).map(([k, xs]) => `<div style="margin-top:6px"><b>${esc(k)}</b>${xs.map((x) => `<div class="small">${esc(x.source)} ${esc(x.title)}: <span class="muted">${esc(String(x.before ?? "—"))}</span> → <b>${esc(String(x.after ?? "—"))}</b>${x.reason ? `<div class="muted">${esc(x.reason)}</div>` : ""}</div>`).join("")}</div>`).join("");
    const ok = await askDialog({ title: L("重新评估已保存的来源 — 预览", "Reassess saved sources — preview"), okText: L("应用这些修改", "Apply these changes"), cancelText: L("取消", "Cancel"),
      body: `<p class="small">${esc(d.note)}</p><p class="small">${L("规则版本", "Rule version")} ${esc(d.rule_version)} · ${d.sources_changing} / ${d.sources} ${L("条来源会改变", "sources would change")} · ${L("保留的人工标签", "human labels kept")}: ${L("类型", "type")} ${d.human_labels_kept.type}, ${L("相关性", "relevance")} ${d.human_labels_kept.relevance}</p>
        <ul class="small">${Object.entries(d.changes).map(([k, n]) => `<li>${esc(k)}: <b>${n}</b></li>`).join("") || `<li>${L("没有需要修改的", "Nothing to change")}</li>`}</ul>
        ${d.analyses_to_review.length ? `<div class="callout warn small">${L("这些已完成的分析用到了现在被判定为“没有可用正文”的来源，请复核（不会重新运行，也不会改动结论）：", "These finished analyses used sources now found to have no usable text — please review them (they are not rerun or rewritten):")} ${d.analyses_to_review.map((f) => `run ${f.run} (${esc(f.sources.join(", "))})`).join("; ")}</div>` : ""}
        <div style="max-height:320px;overflow:auto">${ex}</div>` });
    if (!ok) return;
    try { const r = await api("POST", `/api/cases/${c.id}/source_review`, { confirm: true }); toast(L("已应用；每处修改都已记录。", "Applied; every change was recorded.") + ` (${r.sources_changing})`); rerender(); }
    catch (e) { toast(e.message, true); }
  };
  const showAffected = (r) => { if (r.affected_variables && r.affected_variables.length) { $("#affBox").innerHTML = `<div class="callout warn">${t("affected")}: <span class="mono">${esc(r.affected_variables.join(", "))}</span> <button class="small" id="reAff">${t("reanalyze_affected")}</button></div>`; $("#reAff").onclick = () => startRecode(c.id, r.affected_variables); } };
  $$("[data-excl]", body).forEach((b) => (b.onclick = async () => {
    let reason = "";
    if (b.dataset.on === "1") {
      reason = await askDialog({ title: L("取消选中这份来源", "Deselect this source"), body: `<p class="small">${L("这份来源会保留在列表和搜索记录里，只是不用于之后的分析。正在进行或已完成的分析不受影响。", "The source stays in the list and the search record; it is just not used in later analysis. Running or finished analyses are not affected.")}</p>`,
        input: { label: L("理由（可选）", "Reason (optional)") }, okText: L("取消选中", "Deselect"), cancelText: LANG === "zh" ? "取消" : "Cancel" });
      if (reason === null) return;
    }
    const r = await api("PATCH", `/api/sources/${b.dataset.excl}`, { excluded: b.dataset.on === "1", reason });
    await rerender(); showAffected(r);
  }));
  $$("[data-rel]", body).forEach((s) => (s.onchange = async () => { if (!s.value) return; const r = await api("PATCH", `/api/sources/${s.dataset.rel}`, { relevance_status: s.value }); await rerender(); showAffected(r); }));
  $$("[data-type]", body).forEach((s) => (s.onchange = async () => { await api("PATCH", `/api/sources/${s.dataset.type}`, { source_type: s.value }); toast(t("saved")); await rerender(); }));
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
    $("#mapRows").innerHTML = s.fields.filter((f) => !issuesOnly || f.issues.length).map((f) => `<tr><td class="small">${f.position}</td><td class="mono small">${f.raw_header ? varName(f.raw_header) : "(blank)"}</td>
      <td><span class="badge ${f.mapping === "exact" ? "ok" : f.mapping === "none" ? "bad" : "warn"}">${esc(f.mapping)}</span><div class="small muted">${varName(f.codebook_name || "")}</div></td>
      <td class="small">${esc(f.type)}${f.multi ? " · multi" : ""}${f.missing_codes?.length ? " · " + esc(f.missing_codes.join(",")) : ""}</td><td class="small">${esc(f.field_class)}</td>
      <td class="small">${f.codes.map((c) => esc(c.code)).join(", ")}</td><td class="small">${f.issues.map((i) => `<div>• ${esc(i)}</div>`).join("")}</td>
      <td class="actions"><button class="small" data-edit="${esc(f.name)}">${t("edit_rule")}</button></td></tr>`).join("");
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
    ${(() => {
      // grouping and order are display only; every field keeps its data-set key, value and options
      const sel = (n, opts) => `<div>${setLabel(n)}<select data-set="${n}">${opts.map((o) => `<option value="${o}" ${s[n] === o ? "selected" : ""}>${esc(optLabel(n, o))}</option>`).join("")}</select></div>`;
      const inp = (n) => `<div>${setLabel(n)}<input data-set="${n}" value="${esc(s[n])}"></div>`;
      const yesno = (n) => `<div>${setLabel(n)}<select data-set="${n}"><option value="true" ${s[n] ? "selected" : ""}>${t("yes")}</option><option value="false" ${!s[n] ? "selected" : ""}>${t("no")}</option></select></div>`;
      const sec = (zh, en) => `<div class="set-section">${L(zh, en)}</div>`;
      const oa = STATUS.providers && STATUS.providers.openai.configured;
      return [
        sec("网页研究", "Web research"),
        sel("search_provider", ["auto", "tavily", "brave", "searxng", "none"]),
        ...["max_search_rounds", "max_queries", "pages_per_query", "results_per_query", "max_fetch"].map(inp),
        yesno("follow_links"),
        sec("编码", "Coding"),
        `<div>${setLabel("coding_mode")}<select data-set="coding_mode"><option value="single" ${(s.coding_mode || "single") === "single" ? "selected" : ""}>${esc(modeText("single"))}</option>${availModes().map((m) => `<option value="${esc(m.mode)}" ${s.coding_mode === m.mode ? "selected" : ""}>${esc(modeText(m.mode))}</option>`).join("")}</select></div>`,
        sel("model_provider", ["auto", "anthropic", "openai", "none"]),
        inp("model_name"),
        inp("passages_per_variable"), inp("max_passages_per_call"),
        sec("上限（每个案例）", "Limits (per case)"),
        inp("budget_usd"), inp("time_limit_minutes"), inp("max_model_attempts_per_case"), yesno("require_approval_over_budget"),
        ...(oa ? [inp("openai_budget_usd"), inp("max_openai_attempts_per_case"),
          sec("OpenAI 请求设置", "OpenAI request settings"),
          `<div>${setLabel("openai_reasoning_effort")}<select data-set="openai_reasoning_effort">${["low", "medium", "high", "xhigh", "max"].map((o) => `<option value="${o}" ${s.openai_reasoning_effort === o ? "selected" : ""}>${o}</option>`).join("")}</select></div>`,
          inp("openai_reasoning_reserve_tokens"), inp("openai_max_output_tokens"), inp("openai_timeout_seconds")] : []),
      ].join("");
    })()}
    </div><button class="primary" id="saveSet" style="margin-top:10px">${t("save_settings")}</button>
    <p class="small muted">${LANG === "zh" ? "“每次模型请求的证据段落数”是批量大小，不是上限：证据更多时会分成更多次请求。" : "Evidence passages per model request is a batch size, not a cap: more evidence means more requests."}</p>
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
