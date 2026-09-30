// Demo layer for the static interface preview: replaces the server API with captured data.
const DEMO = JSON.parse(document.getElementById("demo-data").textContent);
const DEMO_MSG = () => LANG === "zh"
  ? "演示版不能执行此操作：需要在你电脑上运行完整应用（搜索、模型、导出都需要服务器）。"
  : "Not available in the preview: this needs the full app running on your computer (search, model and export need the server).";
const clone = (x) => JSON.parse(JSON.stringify(x));
const DEMO_HIST = {};

function recomputeCategory(row) {
  const s = row.suggestion, r = row.review;
  const VAL = ["suggested", "derived", "admin_generated", "rule_unclear"];
  if (r && ["accepted", "edited", "cleared"].includes(r.action)) return "confirmed";
  if (row.rule_missing || (s && s.status === "rule_missing")) return "rule_missing";
  if (s && (s.status === "disputed" || (VAL.includes(s.status) && (s.counter || []).length))) return "disputed";
  if (s && VAL.includes(s.status) && s.value) return "pending";
  if (r && r.action === "deferred") return "pending";
  if (s && s.status === "analyst_note") return "pending";
  return "insufficient";
}

async function api(method, path, body) {
  await new Promise((r) => setTimeout(r, 40));
  const [p, qs] = path.split("?");
  const q = new URLSearchParams(qs || "");
  if (method === "GET") {
    if (DEMO[p] !== undefined) return clone(DEMO[p]);
    if (p === "/api/cases/1/history") {
      const v = q.get("variable");
      const row = DEMO["/api/cases/1/results"].rows.find((r) => r.name === v);
      return { suggestions: row && row.suggestion ? [row.suggestion] : [], reviews: DEMO_HIST[v] || [] };
    }
    if (p === "/api/cases/1/evidence_search") {
      const words = (q.get("q") || "").toLowerCase().split(/\W+/).filter((w) => w.length > 2);
      const all = Object.keys(DEMO).filter((k) => k.startsWith("/api/sources/"))
        .flatMap((k) => DEMO[k].source.relevance_status === "irrelevant" ? [] : DEMO[k].passages.map((x) => ({ ...x, source_id: DEMO[k].source.id })));
      const hits = all.map((x) => ({ ...x, score: words.reduce((n, w) => n + (x.text.toLowerCase().split(w).length - 1), 0) }))
        .filter((x) => x.score > 0).sort((a, b) => b.score - a.score).slice(0, 12);
      return { method: LANG === "zh" ? "演示版：浏览器内简单关键词匹配（完整应用使用 BM25 + 语义检索）" : "Preview: simple in-browser keyword match (the full app uses BM25 + semantic retrieval)", hits };
    }
    throw new Error(DEMO_MSG());
  }
  if (p === "/api/cases/1/review") {
    const row = DEMO["/api/cases/1/results"].rows.find((r) => r.name === body.variable);
    const s = row.suggestion || {};
    const old = row.review;
    const reason = (body.reason || "").trim();
    let value = "", action;
    const hist = (DEMO_HIST[row.name] = DEMO_HIST[row.name] || []);
    if (body.action === "accept") {
      if (!s.value) throw new Error(LANG === "zh" ? "没有可接受的建议值" : "Nothing to accept");
      value = s.value; action = "accepted";
    } else if (body.action === "edit") {
      if (!reason) throw new Error(LANG === "zh" ? "修改时必须填写理由" : "A reason is required when editing a value");
      value = String(body.value || "").trim();
      if (row.type === "categorical" && value) {
        const allowed = row.codes.map((c) => String(c.code).toUpperCase()).concat((row.missing_codes || []).map((m) => m.toUpperCase()));
        const parts = value.split(/[;,]/).map((x) => x.trim()).filter(Boolean);
        const bad = parts.filter((x) => !allowed.includes(x.toUpperCase()));
        if (bad.length) throw new Error(`${LANG === "zh" ? "不是 codebook 中的编码" : "Not a codebook code"} (${row.name}): ${bad.join(", ")}`);
        if (!row.multi && parts.length > 1) throw new Error(`${row.name} ${LANG === "zh" ? "在当前 codebook 中是单选" : "is single-select in the active codebook"}`);
      }
      action = "edited";
    } else if (body.action === "clear") {
      if (!reason) throw new Error(LANG === "zh" ? "清空时必须填写理由" : "A reason is required when clearing");
      action = "cleared";
    } else if (body.action === "defer") {
      value = old ? old.value : ""; action = "deferred";
    } else if (body.action === "reset") {
      row.review = null; row.category = recomputeCategory(row);
      hist.push({ at: Date.now() / 1000, action: "reset", old_value: old && old.value, new_value: null, reason });
      return { ok: true };
    }
    row.review = { value, action, reason, updated_at: Date.now() / 1000 };
    row.category = recomputeCategory(row);
    hist.push({ at: Date.now() / 1000, action, old_value: old ? old.value : null, new_value: value, reason });
    setTimeout(() => toast(LANG === "zh" ? "已保存（仅在本预览页面内，刷新后消失）" : "Saved (in this preview only; gone on reload)"), 50);
    return { ok: true };
  }
  const m = p.match(/^\/api\/sources\/(\d+)$/);
  if (m && method === "PATCH") {
    const sid = +m[1];
    const s = DEMO["/api/cases/1/sources"].find((x) => x.id === sid);
    if ("excluded" in body) { s.excluded = body.excluded ? 1 : 0; s.exclude_reason = body.reason || ""; }
    if (body.relevance_status) s.relevance_status = body.relevance_status;
    if (body.source_type) s.source_type = body.source_type;
    const affected = [];
    if (body.excluded || body.relevance_status === "irrelevant") {
      DEMO["/api/cases/1/results"].rows.forEach((r) => {
        if (r.suggestion && (r.suggestion.evidence || []).concat(r.suggestion.counter || []).some((e) => e.source_id === sid && e.stance !== "candidate")) {
          r.suggestion.stale = 1; r.suggestion.stale_reason = `cites excluded source S${sid}`; affected.push(r.name);
        }
      });
    }
    return { ok: true, affected_variables: affected };
  }
  throw new Error(DEMO_MSG());
}

// Buttons that need the server show a clear message instead of failing silently.
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href^='/api/']");
  if (a) { e.preventDefault(); toast(DEMO_MSG(), true); return; }
  const b = e.target.closest("#startBtn, #rerunBtn, #recodeBtn, #reBtn, #recodeAll, #reAff, #recodeOne, #addUrlBtn, #addFileBtn, #addTextBtn, #upBtn, #saveSet, #savePrice");
  if (b) { e.preventDefault(); e.stopImmediatePropagation(); toast(DEMO_MSG(), true); }
}, true);

if (!location.hash) history.replaceState(null, "", "#/case/1/review");
WB.sel = "ALERT_APPROVAL_PROCESS";
