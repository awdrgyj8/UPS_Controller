import re

import pytest
from fastapi.testclient import TestClient

from Web.server import STATIC_DIR, create_app


@pytest.fixture
def client(harness):
    return TestClient(create_app(harness.service, harness.diagnostics, harness.env, None))


def test_state_endpoint(client, harness):
    harness.service.monitor.read_ups()
    response = client.get("/api/state")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "simulation"
    assert body["ups"]["battery"] == 100
    assert body["settings"]["auth_required"] is False
    assert "web_token" not in body["settings"]


def test_sim_controls(client, harness):
    assert client.post("/api/sim/grid", json={"value": False}).status_code == 200
    assert harness.env.grid_online is False
    assert client.post("/api/sim/agents/1/fault", json={"fault": "offline"}).status_code == 200
    assert harness.env.agents[0].fault == "offline"
    assert client.post("/api/sim/agents/1/fault", json={"fault": "bogus"}).status_code == 400


def test_agent_actions(client):
    response = client.post("/api/agents/1/verify")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert client.post("/api/agents/99/status").status_code == 404


def test_token_required_when_configured(harness):
    harness.settings.web_token = "secret"
    client = TestClient(create_app(harness.service, harness.diagnostics, harness.env, None))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/state", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert client.get("/api/state?token=secret").status_code == 200


def test_frontend_served_without_build(client):
    """前端不需要編譯：首頁與 JS 模組直接從 Web/static 送出，且要求瀏覽器每次重新確認。"""
    index = client.get("/")
    assert index.status_code == 200
    assert 'type="importmap"' in index.text
    script = client.get("/js/main.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert script.headers["cache-control"] == "no-cache"
    assert client.get("/vendor/vue.esm-browser.prod.js").status_code == 200


def test_frontend_imports_resolve():
    """沒有打包工具幫忙檢查，所以由測試確認每個相對路徑的 import 與 index.html 引用的檔案都存在。"""
    missing = []
    for path in (STATIC_DIR / "js").rglob("*.js"):
        for target in re.findall(r"""(?:from|import)\s+['"](\.{1,2}/[^'"]+)['"]""", path.read_text(encoding="utf-8")):
            if not (path.parent / target).resolve().is_file():
                missing.append(f"{path.relative_to(STATIC_DIR)} -> {target}")
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for target in re.findall(r'(?:href|src)="((?:css|js|fonts|vendor)/[^"]+)"', index):
        if not (STATIC_DIR / target).is_file():
            missing.append(f"index.html -> {target}")
    assert not missing, missing
