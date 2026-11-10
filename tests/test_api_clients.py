"""實機用的客戶端（Api/）：以假的 HTTP 回應確認請求內容與回應解析，不連線到任何真實設備。"""
import base64
import json

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from Api.AgentAPI import AgentClient
from Api.NutClient import NutClient, build_ups_snapshot, error_snapshot
from Api.PteroAPI import PteroClient
from Api.WakeOnLan import is_valid_mac
from Core.config import Settings
from Core.drivers import DriverError, RealDrivers


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def calls(monkeypatch):
    """攔截 requests.get / post：記錄每次呼叫，並依序回傳 calls.responses 裡的回應。"""
    class Recorder(list):
        responses = []

    recorder = Recorder()

    def fake(method):
        def call(url, **kwargs):
            recorder.append({"method": method, "url": url, **kwargs})
            response = recorder.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return call

    monkeypatch.setattr(requests, "get", fake("GET"))
    monkeypatch.setattr(requests, "post", fake("POST"))
    return recorder


@pytest.fixture
def key_file(tmp_path):
    key = ed25519.Ed25519PrivateKey.generate()
    path = tmp_path / "private_key.pem"
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    return path, key.public_key()


# ---- Pterodactyl ----
def page(items, total_pages):
    return FakeResponse(body={"data": [{"attributes": item} for item in items],
                              "meta": {"pagination": {"total_pages": total_pages}}})


def test_ptero_lists_servers_across_pages(calls):
    calls.responses = [
        page([{"uuid": "11111111-aaaa", "name": "Rust", "node": 3}], 2),
        page([{"uuid": "22222222-bbbb", "name": "Valheim", "node": 4, "suspended": True}], 2),
    ]
    servers = PteroClient("https://panel.test", "app-key", "client-key").list_servers()
    assert [s["identifier"] for s in servers] == ["11111111", "22222222"]
    assert servers[1] == {"identifier": "22222222", "uuid": "22222222-bbbb", "name": "Valheim", "node_id": 4, "suspended": True}
    assert [c["params"]["page"] for c in calls] == [1, 2]
    assert calls[0]["url"] == "https://panel.test/api/application/servers"
    assert calls[0]["headers"]["Authorization"] == "Bearer app-key"


def test_ptero_resources_and_power_use_client_key(calls):
    client = PteroClient("https://panel.test", "app-key", "client-key")
    calls.responses = [
        FakeResponse(body={"attributes": {"current_state": "running", "resources": {"cpu_absolute": 12.5, "memory_bytes": 1024, "uptime": 5000}}}),
        FakeResponse(status_code=204),
        FakeResponse(status_code=500, text="boom"),
        requests.exceptions.ConnectionError("down"),
    ]
    assert client.server_resources("11111111") == {"state": "running", "cpu_percent": 12.5, "memory_bytes": 1024, "uptime_ms": 5000}
    assert client.send_power("11111111", "stop") is True
    assert client.send_power("11111111", "stop") is False
    assert client.send_power("11111111", "stop") is False   # 連線失敗只回報失敗，不拋出例外
    assert calls[1]["url"] == "https://panel.test/api/client/servers/11111111/power"
    assert calls[1]["json"] == {"signal": "stop"}
    assert all(c["headers"]["Authorization"] == "Bearer client-key" for c in calls)


def test_ptero_configured_needs_url_and_both_keys():
    assert PteroClient("https://panel.test", "a", "c").configured is True
    assert PteroClient("https://panel.test", "a", "").configured is False
    assert PteroClient("", "a", "c").configured is False


# ---- UPS_Agent ----
def test_agent_status_online_and_offline(calls):
    client = AgentClient("unused.pem")
    agent = {"name": "PVE", "ip": "192.168.50.250", "port": 5858, "mac": "AA:BB:CC:DD:EE:02"}
    calls.responses = [
        FakeResponse(body={"ok": True, "hostname": "pve", "uptime_seconds": 60}),
        requests.exceptions.ConnectTimeout("timed out"),
    ]
    online = client.status(agent, 2)
    assert (online["online"], online["hostname"], online["port"]) == (True, "pve", "5858")
    assert online["capabilities"] == ["status", "shutdown"]   # 舊版 Agent 沒回報時的預設
    assert calls[0]["url"] == "http://192.168.50.250:5858/status"
    offline = client.status(agent, 2)
    assert offline["online"] is False and "timed out" in offline["error"]
    assert client.status({"name": "x"}, 1)["error"] == "missing ip"


def test_agent_shutdown_request_is_signed(calls, key_file):
    path, public_key = key_file
    client = AgentClient(path)
    calls.responses = [FakeResponse(body={"ok": True, "message": "shutting down"})]
    assert client.shutdown({"ip": "192.168.50.250", "port": 5858}) == (True, "shutting down")
    sent = calls[0]
    assert sent["url"] == "http://192.168.50.250:5858/shutdown"
    payload = sent["json"]["payload"]
    assert payload["action"] == "shutdown" and payload["nonce"]
    # Agent 端用同樣的序列化方式驗證簽章；驗不過會拋出 InvalidSignature
    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    public_key.verify(base64.b64decode(sent["json"]["signature"]), message)


def test_agent_verify_reports_failures(calls, key_file):
    client = AgentClient(key_file[0])
    agent = {"ip": "192.168.50.250", "port": 5858}
    calls.responses = [
        FakeResponse(body={"ok": False, "reason": "invalid signature"}),
        FakeResponse(status_code=404, body={}),
        FakeResponse(status_code=502, text="bad gateway"),
    ]
    assert client.verify(agent) == (False, "回應錯誤: invalid signature")
    assert client.verify(agent)[1].startswith("Agent 不支援此端點")
    assert "bad gateway" in client.verify(agent)[1]
    assert calls[0]["url"].endswith("/verify") and calls[0]["json"]["payload"]["action"] == "verify"
    assert client.verify({"port": 5858})[0] is False   # 缺 ip 不會送出請求
    assert len(calls) == 3


# ---- NUT ----
def test_ups_snapshot_from_variables():
    snapshot = build_ups_snapshot({"ups.status": "OB DISCHRG", "battery.charge": "47.0", "ups.load": "58", "battery.runtime": "x"})
    assert (snapshot["ok"], snapshot["power"], snapshot["battery"], snapshot["load"], snapshot["runtime"]) == (True, False, 47, 58.0, None)
    assert build_ups_snapshot({"ups.status": "OL CHRG"})["power"] is True
    assert error_snapshot(OSError("refused")) == {"ok": False, "power": None, "status": "UNKNOWN", "battery": None, "error": "refused"}


def test_nut_client_reports_missing_config():
    client = NutClient("", None, "")
    assert client.target() == {"host": "", "port": "", "ups_name": "", "auth": False}
    with pytest.raises(ValueError, match="NUT_ServerIP"):
        client.variables()
    assert NutClient("10.0.0.5", 3493, "ups", "monuser", "pw").target() == {"host": "10.0.0.5", "port": "3493", "ups_name": "ups", "auth": True}


# ---- 其他 ----
def test_mac_validation():
    assert is_valid_mac("AA:BB:CC:DD:EE:FF") and is_valid_mac("aa-bb-cc-dd-ee-ff") and is_valid_mac("AABBCCDDEEFF")
    assert not is_valid_mac("AA:BB:CC:DD:EE") and not is_valid_mac(None)


def test_real_drivers_wire_settings_into_clients(monkeypatch, calls, tmp_path):
    for name, value in {
        "NUT_ServerIP": "10.0.0.5", "NUT_ServerPort": "3493", "NUT_UPS_NAME": "ups",
        "PteroApi_Url": "https://panel.test", "PteroApi_AppKey": "app", "PteroApi_ClientKey": "client",
        "AgentInfo": '[{"name":"PVE","ip":"192.168.50.250","port":5858}]', "PteroInfo": '[{"node":1,"agent":"PVE"}]',
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    settings.private_key_path = tmp_path / "missing.pem"
    drivers = RealDrivers(settings)
    assert drivers.nut_target() == {"host": "10.0.0.5", "port": "3493", "ups_name": "ups", "auth": False}
    assert drivers.ptero_configured() is True and drivers.ptero_url() == "https://panel.test"
    assert drivers.agent_configs() == ([{"name": "PVE", "ip": "192.168.50.250", "port": 5858}], "")
    assert drivers.ptero_info() == ([{"node": 1, "agent": "PVE"}], "")
    assert drivers.signing_key_check()[0] is False
    calls.responses = [requests.exceptions.ConnectionError("panel down")]
    with pytest.raises(DriverError, match="panel down"):
        drivers.ptero_list_servers()
