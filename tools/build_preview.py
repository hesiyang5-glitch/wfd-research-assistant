"""Builds the static interface preview (demo) from the real web app + captured data. Not part of the app itself."""
import json
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-0/demo_data.json"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/claude-0/wfd_preview.html"

css = open("web/styles.css").read()
i18n = open("web/i18n.js").read()
app = open("web/app.js").read()
data = open(DATA).read().replace("</", "<\\/")

start = app.index("async function api(method, path, body) {")
end = app.index("function toast(")
app = app[:start] + "/* api() is provided by the demo layer below */\n" + app[end:]
app = app.replace("applyStaticText();\nroute();", "")
mock = open("tools/demo_layer.js").read()

banner_css = """
:root { color-scheme: light; }
body { background: var(--bg); color: var(--ink); }
.demo-bar { background: #fff4c7; color: #4a3b00; border-bottom: 1px solid #e6d27a; padding: 9px 22px; font-size: 13px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.demo-bar b { color: #3a2e00; }
.demo-bar a { color: #1f5f8b; font-weight: 600; }
.panel { overflow-x: auto; }
.wb-detail.panel { overflow-x: hidden; }
.workbench > div, .hero > div, .grid2 > div, .grid3 > div { min-width: 0; }
.wb-table, .panel { max-width: 100%; }
header.top nav { flex-wrap: wrap; }
@media (max-width: 600px) { .kv { grid-template-columns: 1fr; } .tabs { overflow-x: auto; } .chips { gap: 4px; } main { padding: 14px 16px 40px; } header.top { padding: 10px 16px; } .demo-bar { padding: 9px 16px; } }
"""

bar = """<div class="demo-bar"><b>界面预览（演示）· Interface preview (demo)</b>
<span>不能搜索、不调用模型、不能导出。数据来自 11 份项目 PDF 在本地的一次真实无模型运行；标有“界面示例 UI ILLUSTRATION”的两条是手写示例，不是模型输出。<br>
No search, model calls or export. Data comes from a real no-model run on 11 project PDFs; the two entries marked "UI ILLUSTRATION" are hand-written examples, not model output.</span>
<span><a href="#/case/1/review">复核工作台 Review</a> · <a href="#/case/1/sources">来源 Sources</a> · <a href="#/schema">编码规则 Schema</a> · <a href="#/">首页 Home</a></span></div>"""

header = """<header class="top">
  <div class="brand">WFD Coding Assistant<small data-t="brand_sub"></small></div>
  <nav>
    <a href="#/" data-nav="home" data-t="nav_research"></a>
    <a href="#/cases" data-nav="cases" data-t="nav_cases"></a>
    <a href="#/schema" data-nav="schema" data-t="nav_schema"></a>
    <a href="#/settings" data-nav="settings" data-t="nav_settings"></a>
  </nav>
  <div class="lang"><button class="small" id="langBtn">EN / 中文</button></div>
</header>"""

html = ("<title>WFD Coding Assistant Preview</title>\n<style>" + css + banner_css + "</style>\n" + bar + "\n" + header +
        '\n<main id="app"></main>\n<div id="modalRoot"></div>\n'
        '<script type="application/json" id="demo-data">' + data + "</script>\n"
        "<script>" + i18n + "</script>\n<script>\n" + app + "\n" + mock + "\napplyStaticText();\nroute();\n</script>\n")
open(OUT, "w").write(html)
print(len(html) // 1024, "KB ->", OUT)
