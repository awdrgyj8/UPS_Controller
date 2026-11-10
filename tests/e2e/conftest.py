"""瀏覽器 E2E 測試：以模擬模式啟動 Controller，再用 Chromium 操作整個介面。

需要 Playwright（不在預設相依套件裡）：
    uv run --group e2e playwright install chromium
    uv run --group e2e pytest tests/e2e
沒有安裝時這些測試會自動略過。已經有現成的 Chromium 可以用 PW_CHROMIUM_PATH 指定路徑。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="未安裝 playwright，略過瀏覽器測試")

ROOT = Path(__file__).resolve().parents[2]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    port = int(os.environ.get("E2E_PORT") or _free_port())
    url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, CONSOLE_TABLE="false")
    env.pop("AgentInfo", None)  # 一律使用內建的模擬節點
    process = subprocess.Popen(
        [sys.executable, "main.py", "--simulate", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 60
        while True:
            try:
                urllib.request.urlopen(f"{url}/api/health", timeout=1)
                break
            except OSError:
                if process.poll() is not None or time.time() > deadline:
                    raise RuntimeError("Controller 沒有成功啟動")
                time.sleep(0.3)
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as p:
        options = {}
        if os.environ.get("PW_CHROMIUM_PATH"):
            options["executable_path"] = os.environ["PW_CHROMIUM_PATH"]
        try:
            instance = p.chromium.launch(**options)
        except sync_api.Error as e:
            pytest.skip(f"無法啟動 Chromium：{e}")
        yield instance
        instance.close()


@pytest.fixture
def page(browser, base_url):
    """每個測試前把模擬環境還原，並確認頁面沒有任何 JS 錯誤。"""
    context = browser.new_context(base_url=base_url, viewport={"width": 1440, "height": 1000})
    context.request.post("/api/sim/reset")
    page = context.new_page()
    page.set_default_timeout(15_000)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    yield page
    context.close()
    assert not errors, f"頁面出現 JS 錯誤：{errors}"
