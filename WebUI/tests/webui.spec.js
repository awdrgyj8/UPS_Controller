import { expect, test } from '@playwright/test'

test.beforeEach(async ({ request }) => {
  await request.post('/api/sim/reset')
})

test('總覽頁顯示 UPS 數據、拓撲與觸發條件', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('模擬模式').first()).toBeVisible()
  await expect(page.getByTestId('decision')).toContainText('市電正常')
  for (const label of ['市電', '電池電量', '預估續航', 'UPS 負載', '輸入電壓', '節點在線']) {
    await expect(page.locator('.tile', { hasText: label }).first()).toBeVisible()
  }
  await expect(page.locator('[data-node="ups"]')).toBeVisible()
  await expect(page.locator('[data-node^="agent-"]')).toHaveCount(3)
  await expect(page.getByText('自動關機觸發條件')).toBeVisible()
})

test('側邊選單可以切換所有頁面', async ({ page }) => {
  await page.goto('/')
  const pages = {
    topology: '系統連線拓撲',
    ups: '全部 NUT 變數',
    nodes: 'Pterodactyl 遊戲伺服器',
    tests: '系統自檢',
    logs: '事件紀錄',
  }
  for (const [id, heading] of Object.entries(pages)) {
    await page.locator(`[data-nav="${id}"]`).click()
    await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible()
  }
})

test('點選拓撲節點顯示詳細資訊', async ({ page }) => {
  await page.goto('/#/topology')
  await page.locator('[data-node="nut"]').click()
  await expect(page.getByTestId('topology-detail')).toContainText('192.168.50.10')
  await page.locator('[data-node="agent-2"]').click()
  await expect(page.getByTestId('topology-detail')).toContainText('Node-2')
  await expect(page.locator('[data-node^="server-"]').first()).toBeVisible()
})

test('系統自檢全部通過', async ({ page }) => {
  await page.goto('/#/tests?tab=selftest')
  await page.getByTestId('run-selftest').click()
  await expect(page.locator('[data-test-id="logic.consistency"]')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.results li.critical')).toHaveCount(0)
  await expect(page.locator('[data-test-id="agent.1.verify"]')).toContainText('通過')
})

test('故障注入：Agent 拒絕簽章時自檢會失敗', async ({ page, request }) => {
  await request.post('/api/sim/agents/1/fault', { data: { fault: 'reject' } })
  await page.goto('/#/tests?tab=selftest')
  await page.getByTestId('run-selftest').click()
  await expect(page.locator('[data-test-id="agent.1.verify"]')).toContainText('invalid signature', { timeout: 30_000 })
  await expect(page.locator('[data-test-id="agent.2.verify"]')).toContainText('通過')
})

test('模擬器：切斷市電後介面即時更新', async ({ page }) => {
  await page.goto('/#/tests?tab=simulator')
  await page.getByTestId('toggle-grid').click()
  await expect(page.getByTestId('decision')).toContainText('電池供電', { timeout: 15_000 })
  await page.locator('[data-nav="topology"]').click()
  await expect(page.locator('[data-edge="grid-ups"]')).toHaveAttribute('data-state', 'broken')
  await page.locator('[data-nav="tests"]').click()
  await page.locator('[data-tab="simulator"]').click()
  await page.getByTestId('toggle-grid').click()
  await expect(page.getByTestId('decision')).toContainText('市電正常', { timeout: 15_000 })
})

test('節點卡片的簽章驗證按鈕', async ({ page }) => {
  await page.goto('/#/nodes')
  await page.locator('[data-agent="1"] [data-action="verify"]').click()
  await expect(page.locator('[data-agent="1"] .last-result')).toContainText('signature verified')
})

test('情境測試：完整停電 → 自動關機 → 復電開機', async ({ page }) => {
  await page.goto('/#/tests?tab=scenarios')
  await page.locator('[data-scenario="full_outage"]').click()
  // 關機程序進行時，頂部狀態列要顯示目前階段
  await expect(page.getByTestId('decision')).toContainText('執行關機程序', { timeout: 60_000 })
  await expect(page.getByTestId('scenario-result')).toHaveText(/通過/, { timeout: 120_000 })
  await expect(page.locator('.steps li.critical')).toHaveCount(0)
})
