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


LABELS_OUTSIDE_BOX = """() => [...document.querySelectorAll('.tg-node, .tg-pill')].flatMap((group) => {
  const box = group.querySelector('rect').getBoundingClientRect()
  return [...group.querySelectorAll('text')]
    .filter((text) => text.getBoundingClientRect().right > box.right - 2)
    .map((text) => text.textContent)
})"""


def test_topology_labels_stay_inside_their_boxes(page):
    """SVG 文字不會自動截斷：方框裡的名稱要依實際寬度縮小或截斷，不能蓋到框外。"""
    for url, graph in (("/#/overview", ".v-overview .topo-graph"), ("/#/topology", ".v-topology .topo-graph")):
        page.goto(url)
        expect(page.locator(f'{graph} [data-node="ups"]')).to_be_visible()
        page.wait_for_function("document.fonts.status === 'loaded'")
        assert page.evaluate(LABELS_OUTSIDE_BOX) == []


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
    expect(page.locator('[data-check="logic.consistency"]')).to_be_visible(timeout=30_000)
    expect(page.locator(".results li.critical")).to_have_count(0)
    expect(page.locator('[data-check="agent.1.verify"]')).to_contain_text("通過")


def test_selftest_reports_injected_fault(page):
    page.request.post("/api/sim/agents/1/fault", data={"fault": "reject"})
    page.goto("/#/tests?tab=selftest")
    page.get_by_test_id("run-selftest").click()
    expect(page.locator('[data-check="agent.1.verify"]')).to_contain_text("invalid signature", timeout=30_000)
    expect(page.locator('[data-check="agent.2.verify"]')).to_contain_text("通過")


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


PHONE = {"width": 402, "height": 874}
PHONE_PAGES = ["overview", "topology", "ups", "nodes", "logs",
               "tests?tab=selftest", "tests?tab=drill", "tests?tab=scenarios", "tests?tab=simulator"]
# 每個 .grid 實際排出幾欄，以及整頁有沒有被撐出橫向捲軸
LAYOUT = """() => ({
  columns: [...document.querySelectorAll('.grid')].map((grid) => getComputedStyle(grid).gridTemplateColumns.split(' ').length),
  overflow: document.scrollingElement.scrollWidth - innerWidth,
})"""


def test_phone_layout_is_single_column_on_every_page(page):
    """窄螢幕下每一頁的磚都要佔滿整列：不能出現桌面版的 12 欄，也不能撐出橫向捲軸。"""
    page.set_viewport_size(PHONE)
    for name in PHONE_PAGES:
        page.goto(f"/#/{name}")
        expect(page.locator(f".v-{name.split('?')[0]}")).to_be_visible()
        layout = page.evaluate(LAYOUT)
        assert max(layout["columns"], default=0) <= 2, (name, layout)   # 情境測試分頁沒有用 .grid
        assert layout["overflow"] <= 0, (name, layout)


def test_phone_overview_without_ups_temperature(page):
    """很多 UPS 不回報溫度，這時輸出磚會加寬。曾經因為那條規則的權重較高，把手機版面撐成 12 欄。"""
    def without_temperature(route):
        response = route.fetch()
        data = response.json()
        data["ups"]["temperature"] = None
        data["ups"]["variables"]["ups.model"] = "CP1000PFCLCDa"
        route.fulfill(response=response, json=data)

    page.route("**/api/stream*", lambda route: route.abort())   # 固定在改過的那份狀態
    page.route("**/api/state", without_temperature)
    page.set_viewport_size(PHONE)
    page.goto("/#/overview")
    expect(page.locator(".v-overview .mini.out.wide")).to_be_visible()
    expect(page.locator(".v-overview .mini.temp")).to_have_count(0)
    layout = page.evaluate(LAYOUT)
    assert max(layout["columns"]) <= 2 and layout["overflow"] <= 0, layout
    hero = page.locator(".v-overview .hero").bounding_box()
    grid = page.locator(".v-overview").bounding_box()
    assert hero["width"] == grid["width"]
    # 數字和電池圖不能互相重疊
    number = page.get_by_test_id("battery").bounding_box()
    cell = page.locator(".v-overview .cell").bounding_box()
    assert number["x"] + number["width"] <= cell["x"]


def test_desktop_overview_uses_the_twelve_column_grid(page):
    page.goto("/#/overview")
    expect(page.locator(".v-overview .hero")).to_be_visible()
    assert page.evaluate(LAYOUT)["columns"][0] == 12
    hero = page.locator(".v-overview .hero").bounding_box()
    load = page.locator(".v-overview .load").bounding_box()
    assert hero["y"] == load["y"] and hero["x"] + hero["width"] < load["x"]
