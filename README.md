# UPS Controller

監控 NUT UPS 狀態，停電且電量低於門檻時依序關閉 Pterodactyl 遊戲伺服器與各節點（UPS_Agent），
市電恢復後以 Wake-on-LAN 喚醒節點。內建網頁介面，可查看完整連線拓撲、UPS 詳細數據，
並提供系統自檢、停電演練與模擬情境測試。網頁不需要編譯，也不需要 Node.js。

## 快速開始

```bash
uv sync
uv run main.py --simulate      # 模擬模式：不需要任何硬體，開啟 http://127.0.0.1:8080
```

實機執行（需先設定 `.env` 並以 `Tools/gen_keys.py` 產生金鑰）：

```bash
uv run main.py                 # 控制迴圈 + Web 介面
uv run main.py --no-web        # 只執行控制迴圈（與舊版相同）
uv run main.py --host 0.0.0.0 --port 8080
```

### AgentInfo 與 PteroInfo

- `AgentInfo`：每台裝了 UPS_Agent 的實體主機（name / ip / port / mac）。停電關機與復電 WOL 都依照這份清單。
- `PteroInfo`（選填）：每個 Pterodactyl node 跑在哪台主機上，只用於拓撲圖與自檢，不影響關機流程。
  一台主機可以有多個 node；跑在 VM 裡的 node 填它所在的實體主機。沒列出的 node 會用 FQDN = Agent IP 自動比對。

```
AgentInfo=[{"name":"Server-A","ip":"192.168.50.230","mac":"AA:BB:CC:DD:EE:01","port":5858},{"name":"PVE","ip":"192.168.50.250","mac":"AA:BB:CC:DD:EE:02","port":5858}]
PteroInfo=[{"node":3,"agent":"Server-A"},{"node":4,"agent":"Server-A"},{"node":1,"agent":"PVE"}]
```

> 對外開放介面時請設定 `WEB_TOKEN`，否則同網段任何人都能操作暫停控制、WOL 等功能。

## 網頁介面

| 頁面 | 內容 |
|---|---|
| 總覽 | 電量（含關機門檻）與續航、負載、市電、輸出、溫度、節點與伺服器在線數；精簡拓撲；關機條件即時檢查；目前或最近一次關機/喚醒流程的進度；電量與負載趨勢；最近事件 |
| 連線拓撲 | 市電 → UPS → NUT → Controller → 面板 / 各節點 → 遊戲伺服器。電力與網路線路分層顯示，停電、斷線即時標示；點選任一節點查看詳細資訊 |
| UPS 數據 | 型號/序號/韌體、ups.status 旗標說明、電池/輸入/輸出/溫度數據、四張歷史圖表（可切換資料表）、全部 NUT 變數（可搜尋） |
| 節點與伺服器 | 每個 Agent 的延遲、運行時間、CPU 負載、記憶體、磁碟、支援端點；手動連線測試、簽章驗證、發送 WOL；Pterodactyl 伺服器清單與資源使用 |
| 測試中心 | 系統自檢、停電演練（乾跑）、情境測試、模擬器控制台（後兩者僅模擬模式） |
| 事件紀錄 | 所有控制器 / NUT / 面板 / Agent / 測試事件，可依等級、來源篩選與匯出 |

## 測試功能

- **系統自檢**：檢查設定、私鑰、powerState 讀寫、NUT 連線與必要變數、UPS 狀態、關機時間餘裕、
  Pterodactyl Application/Client API、伺服器與 Agent 對應、每個 Agent 的 `/status` 與 `/verify` 簽章、MAC 格式。
  完全不會影響設備，實機模式也可放心執行。
- **停電演練（乾跑）**：照著真正的關機/復電流程走一遍：讀取類操作實際執行，
  stop 訊號、節點關機、WOL 只驗證不送出（節點關機改送 `/verify`，需更新 UPS_Agent）。
- **情境測試（模擬模式）**：自動操作模擬環境並驗證控制器行為，包含完整停電→關機→復電開機、短暫停電、
  伺服器卡住逾時、Agent 拒絕簽章、面板故障、NUT 斷線。
- **模擬器控制台（模擬模式）**：手動切斷市電、調整電量與放電倍速、中斷 NUT/面板、對每個節點注入故障
  （離線、拒絕簽章、高延遲、不支援 WOL）、讓指定伺服器無法關閉。

模擬模式執行的是與實機相同的控制程式碼（`Core/controller.py`），只是把 NUT / 面板 / Agent / WOL
換成 `Core/simulator.py` 的模擬實作；電源狀態只存在記憶體，不會寫入 `Data/powerState.json`。

## 自動化測試

```bash
uv run pytest                                        # 控制流程、自檢、設定、Api 客戶端、Web API（不連線任何真實設備）
uv run ruff check .                                  # lint
uv run --group e2e playwright install chromium       # 第一次跑瀏覽器測試前下載 Chromium
uv run --group e2e pytest tests/e2e                  # 瀏覽器 E2E 測試（沒裝 playwright 時自動略過）
```

## 架構

```
main.py              進入點（--simulate / --no-web / --host / --port）
Core/config.py       設定：唯一讀取環境變數與 .env 的地方（pydantic-settings）
Core/controller.py   控制迴圈、UPS/Agent/面板監控
Core/drivers.py      實機驅動：把 Api/ 的客戶端組起來
Core/simulator.py    模擬環境與模擬驅動（介面與實機驅動相同）
Core/diagnostics.py  系統自檢、停電演練
Core/scenarios.py    情境測試
Core/state.py        執行期共享狀態、事件、歷史資料
Api/                 對外連線的客戶端：NUT、Pterodactyl、UPS_Agent、Wake-on-LAN（設定由呼叫端傳入）
Web/server.py        FastAPI：REST API、SSE 即時串流（/api/stream）、直接送出 Web/static
Web/static/          前端（Vue 3，瀏覽器原生 ES modules，不需要編譯）
Data/powerState.json 節點預期的電源狀態（執行期產生，不進版控）
```

API 文件：啟動後開啟 `/api/docs`。

### 前端

前端是一般的靜態檔案，改完存檔、重新整理瀏覽器就生效，沒有編譯步驟。

```
Web/static/index.html         進入點；用 import map 把 `vue` 指到 vendor/ 裡的檔案
Web/static/vendor/            隨專案發佈的 Vue（更新方式見該資料夾的 README）
Web/static/fonts/             Bricolage Grotesque（拉丁字母與數字；中文用系統黑體）
Web/static/css/tokens.css     設計 token：顏色、字體、圓角。強調色跟著電源狀態切換（data-power）
Web/static/css/base.css       外框與共用元件（磚、按鈕、籤、表格、圖表…）
Web/static/css/views/         各頁專屬樣式，全部包在 .v-<頁名> 底下
Web/static/js/store.js        狀態：/api/state 快照加上 SSE 即時更新
Web/static/js/components/     共用元件
Web/static/js/views/          六個頁面
```

- 元件是純 JS 物件加上 `template` 字串（沒有 `.vue` 單檔元件），寫法可參考 `js/components/flow-stepper.js`。
- 所有資源都放在本機，不使用 CDN，停電或對外網路中斷時介面仍然可用。
- 伺服器對前端檔案回 `Cache-Control: no-cache`，更新版本後瀏覽器不會用到舊檔。
