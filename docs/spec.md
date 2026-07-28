# spec.md — Personal Assistant 規格書

## 1. 目標

一個 24 小時運作嘅個人資訊助理,零伺服器成本(GitHub Free + Cloudflare Free + Claude Pro 訂閱):

1. 每日 3 次自動收集並分析:
   - 當日重點新聞(香港、英國為主,加世界性大新聞)
   - 港股市場:恆指走勢分析 + 技術上/宏觀上最有機會升值嘅股票(排名)
   - AI 界最新消息(特別關注 Anthropic/Claude、OpenAI/ChatGPT 等龍頭)
   - 當前熱門話題(香港、英國、全球)
2. 產出:結構化 JSON + 繁體中文短報告 + dashboard 圖表
3. 每次 run 完主動 push 簡報去 Telegram
4. 用戶隨時喺 Telegram 問任何問題,bot 基於最近收集嘅資料回答

## 2. 架構

```
┌── GitHub Actions: briefing.yml(cron 每日3次)────────────┐
│ 1. fetch_market.py  → data/latest/market.json            │
│ 2. fetch_news.py    → data/latest/news.json              │
│ 3. prepare_input.py → data/latest/claude_input.json      │
│ 4. claude -p @prompts/briefing.md                        │
│      → data/latest/report.json + report.md               │
│ 5. notify.py        → Telegram 推送簡報                   │
│ 6. commit & push(latest + archive)                      │
└──────────────────────┬───────────────────────────────────┘
                       │
        GitHub Pages(docs/index.html 讀 data/latest/)
                       │
┌── Cloudflare Worker(Telegram webhook,常駐)─────────────┐
│ 收到問題 → 驗證 chat_id → 即時 ack「收到,分析緊…」        │
│ → GitHub API workflow_dispatch(answer.yml, 帶問題)       │
└──────────────────────┬───────────────────────────────────┘
                       │
┌── GitHub Actions: answer.yml(workflow_dispatch)─────────┐
│ claude -p @prompts/answer.md(問題 + 最近3日 report.json)│
│ → notify.py 將答案 send 返 Telegram                       │
└──────────────────────────────────────────────────────────┘
```

認證:Claude Code 用訂閱 OAuth token(`claude setup-token` 產生,存 repo secret `CLAUDE_CODE_OAUTH_TOKEN`),食 Pro 訂閱 quota,零 API 費用。

## 3. 排程(UTC)

| Run | UTC cron | 倫敦(夏令) | 內容重點 |
|---|---|---|---|
| morning | `0 6 * * *` | 07:00 | 隔夜英美新聞、港股上午市況、AI 消息 |
| hk-close | `30 8 * * *` | 09:30 | 港股全日總結、技術指標更新、候選股排名 |
| evening | `0 17 * * *` | 18:00 | 英國/世界當日新聞、熱門話題總結 |

註:GitHub cron 用 UTC,英國冬令時間會偏移一小時,接受此誤差。每次 run 帶一個 `run_type` 參數(morning/hk-close/evening),prompt 按類型調整分析重點。`workflow_dispatch` 可手動 trigger 任何 run_type。

## 4. 數據來源(config/config.json 可配置)

**新聞 RSS(免費、無限)**
- 香港:RTHK 即時新聞、明報、SCMP
- 英國:BBC News UK、Guardian UK、Sky News
- 世界:BBC World、Reuters(如有公開 feed)
- AI:Anthropic News、OpenAI Blog、TechCrunch AI、The Verge AI、Hacker News front page(篩 AI 相關)
- 熱門話題:Google Trends daily RSS(geo=HK 同 geo=GB)、Reddit r/HongKong 及 r/unitedkingdom hot(JSON API)

實施註:以上係候選清單,Phase 1 逐個驗證邊啲 feed 實際可用,死鏈就換。每個 source 記 `name/url/region/category`。

**港股(yfinance)**
- 恆指 `^HSI` + 國企指數 `^HSCE`:日線 250 日
- 股票池:恆指成分股(config 列明 ticker,可 reuse 用戶 Route A 項目嘅 constituents)
- 每股計:收市價、20/50/200 日 MA、RSI(14)、20 日動量、成交量比率(vs 20日均量)、52 週高低位距離
- 附帶:恒指期貨/夜期如 yfinance 有;冇就略過

**WebSearch(Claude 內置,限 ≤5 次/run)**
- 只用喺:熱門話題深挖、RSS 覆蓋唔到嘅突發大新聞驗證

## 5. 數據檔案格式

`data/latest/` 每次 run 覆寫;同時 copy 一份去 `data/archive/YYYY-MM-DD/{run_type}/`。archive 保留 14 日(cleanup.py 每次 run 順手清)。

**market.json**(fetch_market.py 輸出)
```json
{
  "generated_at": "ISO8601",
  "hsi": {"close": 0, "change_pct": 0, "ma20": 0, "ma50": 0, "ma200": 0,
           "rsi14": 0, "history_30d": [{"date": "", "close": 0}]},
  "stocks": [{"ticker": "0700.HK", "name": "騰訊", "close": 0, "change_pct": 0,
               "rsi14": 0, "momentum_20d_pct": 0, "vol_ratio": 0,
               "above_ma50": true, "above_ma200": true, "pct_from_52w_high": 0}]
}
```

**news.json**(fetch_news.py 輸出;每類最多 25 條,每條 title + 一句 summary + source + url + published)

**claude_input.json**(prepare_input.py 輸出)— 精簡合併版:市場指標摘要 + 各類新聞 headline 列表 + run_type + 上次 report 嘅一段結論(畀 Claude 連貫性)。目標 <8k tokens。

**report.json**(Claude 輸出,schema 喺 prompts/briefing.md 內指明)
```json
{
  "generated_at": "", "run_type": "",
  "news_hk": {"summary": "", "items": [{"headline": "", "why_it_matters": ""}]},
  "news_uk": {...}, "news_world": {...},
  "market": {"hsi_analysis": "", "hsi_outlook": "",
              "top_picks": [{"ticker": "", "name": "", "technical_reason": "", "macro_reason": ""}]},
  "ai": {"summary": "", "items": [...]},
  "trending": {"hk": "", "uk": "", "global": ""},
  "one_line_digest": ""
}
```
`top_picks` 最多 5 隻,必須基於 market.json 嘅實際指標,唔可以老作數字。

**report.md** — 由 report.json 排版而成嘅繁中報告(Claude 同步輸出),底部固定免責聲明。

## 6. Dashboard(docs/index.html)

單一 HTML 檔,Chart.js(CDN),fetch `../data/latest/*.json`(相對路徑;注意 Pages serve /docs 為 root,data 喺 repo root — 用 raw.githubusercontent.com URL 或將 latest 同步 copy 一份去 docs/data/,實施時二選一,後者簡單)。

內容:
- 頂部:one_line_digest + 更新時間 + run_type
- 恆指 30 日走勢圖(line)+ RSI + 分析文字
- top_picks 卡片(指標 + 理由)
- 四個新聞/話題 section(collapsible)
- 手機優先排版(用戶主要用手機睇)

## 7. Telegram 推送(notify.py)

- 每次 briefing run 完:send 簡報(one_line_digest + 每 section 兩三行 + dashboard link),Markdown 格式,長訊息分段(Telegram 上限 4096 字元)
- run 失敗時:send 失敗通知(邊步死咗)
- env:`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`

## 8. 問答流程

**worker/index.js(Cloudflare Worker)**
1. Telegram webhook POST 入嚟
2. 驗證:`message.chat.id` 必須等於 secret `ALLOWED_CHAT_ID`,否則靜默忽略
3. 每日上限:Workers KV 計數(key=日期),超過 30 條就覆「今日額度用完」唔 trigger
4. 即時覆 ack:「收到,分析緊,大約一分鐘 📊」
5. POST GitHub API:`/repos/{owner}/{repo}/actions/workflows/answer.yml/dispatches`,inputs = `{question}`(用 fine-grained PAT,secret `GH_PAT`,只有呢個 repo 嘅 actions:write + contents:read)
6. Worker secrets:`TELEGRAM_BOT_TOKEN`、`ALLOWED_CHAT_ID`、`GH_PAT`、KV binding `QA_COUNTER`

**answer.yml**
1. checkout(淨係需要 data/ + prompts/)
2. 裝 Claude Code CLI
3. 組 context:最近 3 日所有 report.json + 最新 market.json
4. `claude -p`(prompts/answer.md + 問題 + context),`--max-turns 15`,預設唔用 WebSearch(prompt 講明:資料唔夠答先可以 search,上限 2 次)
5. notify.py send 答案返 Telegram(繁中)

## 9. 失敗處理

- briefing.yml:`claude -p` 步驟失敗(quota 爆/網絡)→ retry 一次(隔 30 分鐘,用 workflow 內 sleep 或 re-run 機制,實施時揀簡單嗰個);再失敗 → Telegram 通知 + 保留舊 data/latest 唔覆寫
- fetch scripts:個別 source 失敗跳過,全部失敗先算 run 失敗
- answer.yml 失敗 → Telegram 覆「答唔到,遲啲再試」
- Actions 要 `permissions: contents: write` 先 commit 得;commit 用 `github-actions[bot]` 身份,push 前 `git pull --rebase` 避免兩個 run 撞

## 10. Phase 計劃

### Phase 0 — Scaffold
建齊目錄結構、config/config.json(RSS 清單 + 股票池 + 參數)、requirements.txt、.gitignore、README 一句話。
**驗收**:結構齊全,config 有齊 4 類 RSS source 同至少 30 隻恆指成分股。

### Phase 1 — 數據收集
fetch_market.py、fetch_news.py、prepare_input.py、cleanup.py。
**驗收**:本機跑 `python scripts/fetch_market.py && python scripts/fetch_news.py && python scripts/prepare_input.py` 全綠;market.json 指標數字合理(同行情 app 對到);news.json 每類有料;claude_input.json <8k tokens;死一個 RSS source 唔會 crash。

### Phase 2 — 分析層
prompts/briefing.md(含 report.json schema、輸出規則、WebSearch ≤5、繁中要求、免責聲明);本機測 `claude -p "$(cat prompts/briefing.md)" --max-turns 25`(實際 file 引用方式實施時定)。
**驗收**:本機跑出合法 report.json + report.md;top_picks 引用嘅數字同 market.json 一致;報告係通順繁中;一次調用完成。

### Phase 3 — 自動化 + Dashboard
briefing.yml(3 個 cron + workflow_dispatch + run_type 參數 + commit/push + archive)、docs/index.html。
**驗收**:手動 dispatch 一次 run 全綠,data/latest 更新,Pages 開到 dashboard,手機睇正常,圖表有數據。

### Phase 4 — Telegram 推送
notify.py + 接入 briefing.yml(成功簡報 + 失敗通知)。
**驗收**:dispatch 一次,Telegram 收到排版正常嘅繁中簡報;人為整死一步,收到失敗通知。

### Phase 5 — 問答
worker/(index.js + wrangler.toml)、answer.yml、prompts/answer.md。
**驗收**:Telegram 問「恆指今日點?」→ 收 ack → 一分鐘內收到基於最新數據嘅答案;第二個 chat_id 發訊息被忽略;問答內容引用嘅數字同 data 一致。

### Phase 6 — 加固
retry 機制、KV 每日上限、cleanup 驗證、README 完整化(含 setup 步驟)。
**驗收**:模擬 quota 失敗會 retry + 通知;archive 只剩 14 日;README 跟住做可以由零 setup。

## 11. 用戶手動 setup 清單(Claude Code 做唔到嘅嘢)

Phase 3 前:
1. GitHub 開 public repo,push 全部檔案
2. 本機行 `claude setup-token`,將 token 加做 repo secret `CLAUDE_CODE_OAUTH_TOKEN`
3. Telegram 搵 @BotFather 開 bot,攞 bot token → repo secret `TELEGRAM_BOT_TOKEN`
4. 向自己個 bot send 一句嘢,然後開 `https://api.telegram.org/bot<TOKEN>/getUpdates` 搵自己 chat id → repo secret `TELEGRAM_CHAT_ID`
5. Repo Settings → Actions → General → Workflow permissions 揀 Read and write
6. Repo Settings → Pages → Deploy from branch → main /docs

Phase 5 前:
7. 開 Cloudflare 帳戶(免費),裝 wrangler,`wrangler login`
8. GitHub 開 fine-grained PAT(只限呢個 repo,Actions: write,Contents: read)
9. `wrangler secret put` 三個 secret + 開 KV namespace,`wrangler deploy`
10. 設 Telegram webhook:`https://api.telegram.org/bot<TOKEN>/setWebhook?url=<worker url>`

(每步詳細指令 Phase 6 寫入 README)

## 12. 免責

report.md 及所有股票相關輸出固定包含:「以上分析僅供參考,並非投資建議。投資涉及風險,買賣決定請自行判斷。」
