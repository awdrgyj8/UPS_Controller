import { defineConfig } from '@playwright/test'

// E2E 測試：以模擬模式啟動 Controller（含編譯後的 WebUI），再用瀏覽器操作整個介面。
// 執行前請先 `npm run build`。
const PORT = Number(process.env.E2E_PORT || 8199)

export default defineConfig({
  testDir: './tests',
  timeout: 120_000,
  workers: 1, // 所有測試共用同一個模擬環境，必須依序執行
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 1000 },
    colorScheme: 'dark',
    trace: 'retain-on-failure',
    // 已有現成的 Chromium 時可指定路徑，否則請先執行 `npx playwright install chromium`
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  webServer: {
    command: `uv run main.py --simulate --port ${PORT}`,
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
