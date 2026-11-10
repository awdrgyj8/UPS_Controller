import re

from playwright.sync_api import expect

PAGES = ["topology", "ups", "nodes", "tests", "logs", "overview"]


def test_overview_shows_live_data(page):
    page.goto("/")
    expect(page.get_by_text("模擬模式").first).to_be_visible()
    expect(page.get_by_test_id("headline")).to_have_text("市電供電中")
    expect(page.get_by_test_id("battery")).to_contain_text("100")
    expect(page.get_by_test_id("nodes-online")).to_have_text("3/3")
    expect(page.get_by_test_id("verdict")).to_have_text("不會關機")
    expect(page.locator('[data-node="ups"]')).to_be_visible()
    expect(page.locator('[data-node^="agent-"]')).to_have_count(3)
    expect(page.locator('[data-tile^="agent-"]')).to_have_count(3)


def test_navigation_reaches_every_page(page):
    page.goto("/")
    for name in PAGES:
        page.locator(f'[data-nav="{name}"]').click()
        expect(page.locator(f".v-{name}")).to_be_visible()
        expect(page.locator(f'[data-nav="{name}"]')).to_have_attribute("aria-current", "page")


def test_topology_node_details(page):
    page.goto("/#/topology")
    detail = page.get_by_test_id("topology-detail")
    page.locator('[data-node="nut"]').click()
    expect(detail).to_contain_text("192.168.50.10")
    page.locator('[data-node="agent-2"]').click()
    expect(detail).to_contain_text("Node-2")
    page.locator('[data-node^="server-"]').first.click()
    expect(detail).to_contain_text("CPU")
    # 關掉伺服器圖層後，伺服器不再畫出來
    page.locator('[data-layer="servers"]').click()
    expect(page.locator('[data-node^="server-"]')).to_have_count(0)


def test_ups_page_variable_search(page):
    page.goto("/#/ups")
    variables = page.get_by_test_id("nut-variables")
    expect(variables).to_contain_text("battery.charge")
    page.get_by_test_id("nut-search").fill("input.voltage")
    expect(variables).to_contain_text("input.voltage")
    expect(variables).not_to_contain_text("battery.charge")


def test_selftest_passes(page):
    page.goto("/#/tests?tab=selftest")
    page.get_by_test_id("run-selftest").click()
    expect(page.locator('[data-test-id="logic.consistency"]')).to_be_visible(timeout=30_000)
    expect(page.locator(".results li.critical")).to_have_count(0)
    expect(page.locator('[data-test-id="agent.1.verify"]')).to_contain_text("通過")


def test_selftest_reports_injected_fault(page):
    page.request.post("/api/sim/agents/1/fault", data={"fault": "reject"})
    page.goto("/#/tests?tab=selftest")
    page.get_by_test_id("run-selftest").click()
    expect(page.locator('[data-test-id="agent.1.verify"]')).to_contain_text("invalid signature", timeout=30_000)
    expect(page.locator('[data-test-id="agent.2.verify"]')).to_contain_text("通過")


def test_simulator_outage_updates_whole_ui(page):
    page.goto("/#/tests?tab=simulator")
    headline = page.get_by_test_id("headline")
    page.get_by_test_id("toggle-grid").click()
    expect(headline).to_have_attribute("data-phase", "on_battery")
    expect(headline).to_contain_text("停電")
    # 強調色跟著電源切換
    expect(page.locator("html")).to_have_attribute("data-power", "battery")
    page.locator('[data-nav="topology"]').click()
    expect(page.locator('[data-edge="grid-ups"]')).to_have_attribute("data-state", "broken")
    page.locator('[data-nav="tests"]').click()
    page.locator('[data-tab="simulator"]').click()
    page.get_by_test_id("toggle-grid").click()
    expect(headline).to_have_attribute("data-phase", "monitoring")
    expect(page.locator("html")).to_have_attribute("data-power", "mains")


def test_node_verify_action(page):
    page.goto("/#/nodes")
    page.locator('[data-agent="1"] [data-action="verify"]').click()
    expect(page.locator('[data-agent="1"] .last-result')).to_contain_text("signature verified")


def test_log_filter_by_level(page):
    page.request.post("/api/sim/grid", data={"value": False})
    page.goto("/#/logs")
    log = page.get_by_test_id("log-list")
    expect(log).to_contain_text("市電中斷")
    page.locator('[data-level="success"]').click()
    expect(log).not_to_contain_text("市電中斷")


def test_full_outage_scenario(page):
    page.goto("/#/tests?tab=scenarios")
    page.locator('[data-scenario="full_outage"]').click()
    # 關機程序進行時，標題要顯示目前階段
    expect(page.get_by_test_id("headline")).to_have_attribute("data-phase", "shutdown", timeout=60_000)
    expect(page.get_by_test_id("scenario-result")).to_have_text(re.compile("通過"), timeout=120_000)
    expect(page.locator(".steps li.critical")).to_have_count(0)


def test_theme_toggle_persists(page):
    page.goto("/")
    html = page.locator("html")
    before = html.get_attribute("data-theme")
    page.get_by_role("button", name=re.compile("切換成")).click()
    after = "light" if before == "dark" else "dark"
    expect(html).to_have_attribute("data-theme", after)
    page.reload()
    expect(html).to_have_attribute("data-theme", after)
