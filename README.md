# WFD Coding Assistant · 预警失效数据库编码助手

A local web app for the **Warning Failure Database (WFD)**: you type an incident name, location and approximate date; the app searches the web for sources, reads them, finds evidence for each codebook variable, suggests codes, and gives you a review workbench and Excel export.
一个在你电脑上运行的网页工具：输入事件名称、地点和大致日期，应用自动搜索并读取资料，为每个编码手册（codebook）变量检索证据、提出编码建议，然后由你人工复核并导出 Excel。

> **All model output is a suggestion until you accept it.** Blank is the default when evidence is insufficient.
> **所有模型结果在你确认前都只是建议。** 证据不足时默认留空。

---

## 1. Start it · 启动

**You need / 需要：** Python 3.10 or newer（[python.org/downloads](https://www.python.org/downloads/)；Windows 安装时勾选 “Add python.exe to PATH”）。

1. Unzip the folder anywhere. 解压文件夹到任意位置。
2. **Mac:** double-click `start.command` (first time: right-click → Open). **Windows:** double-click `start.bat`.
   **Mac：** 双击 `start.command`（第一次需右键 → 打开）。**Windows：** 双击 `start.bat`。
3. The first run installs packages (~1 min), then your browser opens **http://127.0.0.1:8765**.
   首次运行会安装依赖（约 1 分钟），然后浏览器自动打开 **http://127.0.0.1:8765**。
4. To stop: close the terminal window (or press `Ctrl+C` in it). Your data is kept in the `data/` folder.
   停止：关闭终端窗口（或按 `Ctrl+C`）。数据保存在 `data/` 文件夹，不会丢失。

Manual start (any OS) / 手动启动：
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip ...
cp .env.example .env
.venv/bin/python -m app.server
```

## 2. Add your keys · 配置密钥

Open the file **`.env`** in the app folder with any text editor (it is created on first start from `.env.example`), fill in keys, save, and restart the app. Keys never reach the browser.
用文本编辑器打开应用文件夹里的 **`.env`**（首次启动时自动生成），填入密钥，保存后重启应用。密钥只保存在你的电脑上，浏览器看不到。

| What · 用途 | Setting · 配置项 | Without it · 未配置时 |
|---|---|---|
| **Automatic web search** 自动搜索 | `TAVILY_API_KEY` **or** `BRAVE_API_KEY` **or** `SEARXNG_URL` | No automatic discovery. You can still add links, upload files, or paste text. 无法自动搜索；仍可手动添加。 |
| **Coding suggestions** 编码建议 | `ANTHROPIC_API_KEY` (default model `claude-sonnet-5-5`); optional `OPENAI_API_KEY` (+ `OPENAI_MODEL`, default `gpt-6.1-sol`) for OpenAI via the Responses API, alone or alongside Claude (see DEPLOY.md); or `OPENAI_BASE_URL` for a free local OpenAI-compatible model (Ollama) | Fallback mode: evidence retrieval + manual coding; no codes are generated. 降级模式：证据检索 + 人工选码。 |
| Semantic retrieval 语义检索 (optional) | `EMBEDDING_MODEL` (+ base URL) | LSA (latent semantic analysis 潜在语义分析) + BM25 keyword ranking. |
| OCR for scanned PDFs 扫描件识别 (optional) | Install [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html) | Scanned pages are reported as "not read" — never silently skipped. 扫描页会被标记为未读取。 |

**Two separate services, two separate bills.** A language-model key does **not** give the app search ability; search is a different API. Enter your search plan's price in **Settings → Pricing** so cost tracking is complete (model prices are pre-filled from Anthropic's pricing page, checked 2026-09-30; edit if your account differs).
**搜索和模型是两个独立服务、分别计费。** 只有模型密钥不代表能搜索。请在“设置 → 价格”填写你的搜索套餐单价（模型价格已按 Anthropic 官网 2026-09-30 的价格预填）。

## 3. Use it · 使用流程

1. **研究事件 / Research** page → enter name, location, date → **开始研究 / Start research**. The right-hand panel shows which services are active and a rough cost range.
2. **进度 / Progress** shows the stages: 确认事件 → 搜索来源 → 获取与去重 → 检查证据缺口 → 补充搜索 → 编码与验证 → 待人工复核. The run pauses and asks you only when:
   - several incidents share the name (pick the right one), or
   - the precise model-cost estimate exceeds your budget (approve, raise the budget, or code manually), or
   - no source text could be obtained (add sources).
3. **来源 / Sources**: inspect every source (type, relevance, duplicates, retrieval errors, OCR status); exclude a source or add your own. Excluding a source marks suggestions that cited it as stale and offers "re-analyze affected variables".
4. **复核工作台 / Review**: left = all workbook fields in order; right = definition, permitted codes, suggestion, rationale, supporting and opposing evidence (click **查看原文 / View text** to jump to the highlighted passage), unresolved questions, validation results. **Accept / Edit (reason required) / Clear (reason required) / Defer / Undo.** Filters (待复核 / 已确认 / 证据不足 / 存在争议 / 规则缺失) are review states, not WFD codes.
5. **导出 / Export**: reviewed values only (default) or including unreviewed suggestions (marked UNREVIEWED) as Excel review workbook, 4-column TSV, workbook-aligned case row, or JSON.
6. **编码规则 / Schema**: field mapping between codebook and workbook, with flagged problems. Upload a new codebook (.docx) + workbook (.xlsx) to create a new version; edit a rule (creates a new version, old ones kept).

**Recommended first step:** on the Schema page, upload the original `CODEBOOK v1.3.docx` together with your workbook. The bundled default was built from a plain-text copy of the codebook's variable section.
**建议第一步：** 在“编码规则”页上传原始 `CODEBOOK v1.3.docx` 和工作簿。内置默认版本来自 codebook 变量部分的文本副本。

## 4. How to check that it really works · 如何验证

With keys configured, research one incident you already coded by hand (e.g. from your pilot workbook) and check:
配置密钥后，用一个你已人工编码过的事件测试，逐项检查：

- **搜索记录 / Search log**: provider name is `tavily`/`brave`/`searxng` (never `TEST-FIXTURE`); queries cover AAR, government, investigation, corrections, reforms, hearings; later rounds say `gap: <VARIABLE>`.
- **来源 / Sources**: no unrelated incidents marked relevant; failed retrievals show a reason; reprints are flagged as syndicated/duplicate.
- **复核 / Review**: pick 5 variables with values → click every citation → the highlighted passage must contain the quote and support the code. Variables without evidence must be blank.
- A causal variable (e.g. `FAILURE_TYPE`, `TRAINING_AND_PROCEDURAL_CONTEXT`) with conflicting accounts should show "disputed" with the competing passages, not a confident code.
- Edit one value, click **重新分析 / Re-analyze** → your edited value is unchanged; a Δ mark shows where the new suggestion differs.
- Export → open the **Case_Row** sheet → headers match your workbook exactly, in order; unreviewed cells are blank.

Automated tests (no internet needed) / 自动测试：
```bash
.venv/bin/python -m tests.test_pipeline    # 44 checks: schema, retrieval, dedupe, validation, review, export, persistence
.venv/bin/python -m tests.test_ui_flow     # browser click-through (needs: pip install playwright && playwright install chromium)
.venv/bin/python -m tests.test_auth        # 24 checks: login, lockout, tampered sessions, CSRF guard, reviewer names
.venv/bin/python -m tests.test_costs       # 29 checks: output limits, retry policy, per-case budget, worst-case checks, no caching of truncated replies
```
The tests need sample PDFs: set `WFD_TEST_PDFS=/path/to/folder` containing the Texas-flood source PDFs from the project.

## 5. What is and isn't verified · 验证状态（2026-10-01 更新）

Full, current status: `PROJECT_SPEC.md`, `TEST_PLAN.md`, `KNOWN_ISSUES.md`. 完整的最新状态见这三个文件。

| | Status 状态 |
|---|---|
| Codebook v1.3 + workbook v1.7 parsing, field mapping, conflict flags | **Tested** on the real files (82 fields; 33 flagged issues) |
| PDF/HTML extraction with page numbers, header/ad cleanup, dedupe, syndication, relevance | **Tested** on 11 real project PDFs + local test pages |
| Pipeline stages, gap-driven follow-up, link following, retrieval-failure recording, budgets, resume | **Tested** with a local test web server and a **TEST-FIXTURE** search provider (labeled in UI and logs) |
| Validator (invented codes, fabricated quotes, unknown IDs, per-option evidence, `-9` rules, disputes) | **Tested** with a scripted fake model — tests the rules, not model quality |
| Review, history, reanalysis without overwriting, exports | **Tested** (API and browser click-through) |
| **Live web search** | **Tavily: verified live** on Render (Marshall Fire, 13 queries, 2026-10-01). Brave/SearXNG: not verified. |
| **Real Claude calls, actual coding quality, real costs** | **Not yet verified.** First live run failed (all calls rejected because of `temperature`; fixed in `de5aece`); a successful live run has not been observed yet. OpenAI: not verified. |
| Docker build, Render deployment, data kept after redeploy | **Verified live** (2026-10-01) |
| Neural embeddings, OCR on a truly scanned PDF | Not verified (no scanned sample; OCR engine present) |

## 6. Defaults chosen (change any in Settings) · 默认选择

- **Stack:** Python standard-library web server + SQLite + a no-build HTML/JS interface, instead of React/FastAPI. Reason: runs with one install step, no Node.js build, and was fully testable here. 技术栈选择理由：安装简单、无需构建，且可在此环境完整测试。
- Search: 10 initial query templates by source type × 2 result pages; up to 3 gap-driven follow-up rounds; ≤40 queries; ≤60 sources read; 20-minute limit per run; **$3 cost cap per case**, summed across all runs and covering Claude and Tavily (checked at worst case before every call; approval raises the cap to a set amount, never removes it). Stopping at a limit is reported as "research incomplete".
- Model: `claude-sonnet-5-5` (no `temperature` parameter — this model rejects it); evidence batch = 40 passages per call (a batch size, not a cap); 8 top passages per variable.
- Admin/derived fields (`VERSION_ENTRY_DATE`, `WFD_ID`, `INCIDENT_DURATION`, source counts/URLs, `DATA_EXTRACTION_METHOD`, `RECORD_STATUS`, `REVISION_HISTORY`) are generated or calculated with a stated basis — never presented as sourced facts. Analyst-comment fields are left for humans.
- Uploaded files without a URL get source type `unknown` (set it on the Sources page) rather than a guess.

## 7. Issues found in the current codebook/workbook · 当前规则中发现的问题

The Schema page lists all 33; highlights for the PI / 重点：
- `FAILURE_TYPE` is "single-select, though multiple secondary codes may be noted", but the workbook and disagreement log contain `2, 5`. → decide whether cells may hold several codes.
- `ALERTING_AUTHORITY_TYPE` says both "single-select" and "multiple values are permitted".
- `MESSAGE_RECEPTION_DOCUMENTATION` codes start at 2 (no code 1), yet 13 workbook rows use `1`.
- `DELIVERY_COVERAGE`: percentage bands vs. "add the specific number" — record band or exact figure?
- `-9` is defined only for 7 variables, but the workbook uses it in many others (e.g. `ALERT_APPROVAL_PROCESS`, `POLICY_CHANGE_LEVEL`). The app allows `-9` only where the codebook defines it.
- Several workbook cells contain dates like `2026-01-03` in multi-code fields — almost certainly "1, 3" auto-converted by Excel.
- Workbook column 77 has a blank header; column 76 header contains extra text (`Albert | Elise`).
- `LAT/LONG` is one column; the codebook defines `LATITUDE / LONGITUDE`.

## 8. Deployment · 部署

- **本机使用 / On your computer:** runs on `127.0.0.1` with login off. Back up by copying the `data/` folder.
  默认只在本机运行，不需要登录。备份方法：复制 `data/` 文件夹。
- **网站 / As a website:** see **DEPLOY.md** for step-by-step Render instructions (Docker image with OCR, persistent disk, team password login). Setting `WFD_PASSWORD` turns on the login screen; without it the server refuses to listen on a public address.
  上线步骤见 **DEPLOY.md**。设置 `WFD_PASSWORD` 后会启用登录；没有密码时程序拒绝在公开地址启动。

## 9. Project layout · 目录

```
app/schema_loader.py   codebook + workbook → versioned variable dictionary, mapping, issue flags
app/search/providers.py Tavily / Brave / SearXNG adapters (+ TEST-FIXTURE for offline tests)
app/ingest.py          fetch, HTML/PDF/DOCX extraction, OCR status, passages, dedupe, source typing
app/research.py        pipeline: identity → search → fetch → gaps → follow-up → coding
app/retrieval.py       BM25 + semantic (embeddings or LSA) hybrid retrieval
app/llm/               model adapters (Anthropic, OpenAI-compatible), embeddings, cost
app/coding.py          evidence packets, prompt rules, derived/admin fields
app/validator.py       server-side validation of codes, quotes, evidence IDs
app/export.py          TSV / XLSX / case row / JSON
app/server.py, jobs.py HTTP API, background jobs; web/ = interface; data/ = your database & files
reference/             default codebook text + workbook; config/pricing.json = editable prices
```
