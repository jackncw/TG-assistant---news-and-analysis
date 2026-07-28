# CLAUDE.md — Personal Assistant(24小時個人助理)

## 項目係乜

一個全免費基建嘅個人資訊助理:

- **收集層**:GitHub Actions 每日 3 次定時跑 Python 拉原始數據(RSS 新聞、yfinance 港股),再用 Claude Code headless(`claude -p`)分析並產出繁體中文報告
- **展示層**:GitHub Pages 靜態 dashboard,client-side 用 Chart.js 畫圖
- **推送層**:每次 run 完自動 push 簡報去 Telegram
- **問答層**:Telegram bot(Cloudflare Worker 收 webhook)→ trigger GitHub Actions → Claude Code 基於最近數據回答 → 覆返 Telegram

詳細規格、架構圖、分 Phase 驗收標準:見 `docs/spec.md`。**必須逐 Phase 做,每個 Phase 完成並通過驗收先落下一個 Phase。**

## 最重要嘅設計原則:慳 quota

用戶用 Claude Pro 訂閱(經 `CLAUDE_CODE_OAUTH_TOKEN` 認證),額度有限,同用戶日常開發共用。所以:

1. **粗重嘢一律用普通 Python 做**(拉 RSS、拉股價、計技術指標、整理數據)— 零 quota
2. Claude Code 每次 run 只做**一次** `claude -p` 調用:收一份已整理好嘅精簡輸入,輸出分析報告
3. `claude -p` 必須帶 `--max-turns` 上限(briefing:25;問答:15)
4. WebSearch 喺 prompt 入面明確限制次數(briefing 每次 ≤5 個 search,只用喺 RSS 覆蓋唔到嘅熱門話題;問答預設唔 search)
5. 餵畀 Claude 嘅輸入要精簡:headline + 一句摘要,唔好成篇文章;指標畀數字,唔好畀成個 time series

## 技術棧

- Python 3.11+:`feedparser`、`yfinance`、`pandas`(唔需要 matplotlib,圖表 client-side 畫)
- Claude Code CLI:`npm install -g @anthropic-ai/claude-code`,headless 模式 `claude -p`
  - 認證:env `CLAUDE_CODE_OAUTH_TOKEN`(訂閱 OAuth token,唔係 API key)
  - **唔好用 `--bare`**(bare mode 會跳過 OAuth,要 API key)
- GitHub Actions(cron + workflow_dispatch)、GitHub Pages
- Dashboard:單一 `docs/index.html`,vanilla JS + Chart.js(CDN),讀 `data/latest/*.json`
- Cloudflare Worker:vanilla JS,`worker/` 目錄,用 wrangler deploy

## 目錄結構

```
personal-assistant/
├── CLAUDE.md
├── docs/
│   ├── spec.md
│   └── index.html          # dashboard(GitHub Pages serve /docs)
├── config/config.json       # RSS 來源、股票清單、參數
├── prompts/
│   ├── briefing.md          # 畀 claude -p 嘅分析指令模板
│   └── answer.md            # 畀 claude -p 嘅問答指令模板
├── scripts/
│   ├── fetch_market.py
│   ├── fetch_news.py
│   ├── prepare_input.py     # 合併原始數據 → claude_input.json(精簡版)
│   ├── notify.py            # Telegram 推送
│   └── cleanup.py           # 清理過期 archive
├── worker/
│   ├── index.js
│   └── wrangler.toml
├── data/
│   ├── latest/              # 最新一次 run 嘅輸出
│   └── archive/YYYY-MM-DD/  # 歷史(保留 14 日)
└── .github/workflows/
    ├── briefing.yml         # cron 3次/日
    └── answer.yml           # workflow_dispatch(問答)
```

## 規則

1. **報告輸出語言**:繁體中文(書面語)。程式碼、註釋、commit message 用英文
2. **絕對唔可以 commit 任何 secret**。所有 token 經 GitHub repo secrets / Cloudflare Worker secrets 注入。code 入面用 `os.environ` / `env` 讀
3. Repo 係 public(GitHub Free 嘅 Pages 要 public repo),所以任何個人資料(chat_id 等)都唔可以出現喺 code 或 data 檔案入面
4. 股票分析報告底部必須包含免責聲明:「以上分析僅供參考,並非投資建議」
5. 每個 fetch script 要可以獨立執行同測試(`python scripts/fetch_market.py` 直接跑到),失敗時 exit code 非零
6. 網絡請求全部要有 timeout 同 try/except;個別 RSS source 死咗唔可以令成個 run 失敗(跳過並喺 output 記低)
7. 唔好過度工程:唔需要 database、唔需要 framework、唔需要 class hierarchy。平面 script + JSON 檔就夠
8. 改動只限於當前 Phase 範圍,唔好順手重構其他部分
9. 每個 Phase 完成後:用真實數據測試、show 輸出畀用戶睇、等用戶確認先 commit 同進入下一 Phase

## 測試方式

- Phase 1–2 喺本機直接跑 script 驗證(用戶部機係 Windows,注意路徑同 encoding:所有檔案讀寫指明 `encoding="utf-8"`)
- Phase 3 起經 `workflow_dispatch` 手動 trigger Actions 驗證
- `claude -p` 本機測試時用戶已 login,直接跑得;Actions 上用 secret
