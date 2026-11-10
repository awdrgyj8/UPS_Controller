"""共享狀態的型別：寫進去的資料要符合 Core/models.py 的宣告，外部資料格式不對時不能讓監控或控制流程中斷。"""
import time

import pytest

from Api.agent_client import AgentClient
from Api.nut_client import build_ups_snapshot, error_snapshot
from Core.models import AgentState, ServerState, UpsState
from Core.scenarios import ScenarioRunner


def test_unknown_field_name_is_rejected(harness):
    with pytest.raises(ValueError, match="batery"):
        harness.state.update("ups", batery=78)
    with pytest.raises(AttributeError):
        harness.state.update("upss", battery=78)


def test_get_returns_a_copy(harness):
    harness.state.update("ups", battery=78)
    copy = harness.state.get("ups")
    copy.battery = 1
    assert harness.state.get("ups").battery == 78


def test_everything_written_during_an_outage_matches_the_declared_types(harness):
    """跑過監控、關機、喚醒、自檢、演練與情境測試後，整份狀態都要能通過嚴格輸出（值與宣告的型別一致）。"""
    harness.service.monitor.refresh_status()
    harness.outage(50)
    assert harness.service.run_cycle() == "shutdown"
    harness.state.snapshot(strict=True)
    harness.advance(3)
    harness.env.set_grid(True)
    assert harness.service.run_cycle() == "wake"
    harness.advance(7)
    harness.service.monitor.refresh_status()
    harness.diagnostics.run_sync("selftest")
    harness.diagnostics.run_sync("drill")
    harness.state.set("simulation", harness.env.to_dict())

    harness.service.start()
    runner = ScenarioRunner(harness.service, harness.env)
    assert runner.start("power_blip")
    deadline = time.time() + 60
    while harness.state.get("scenario").running and time.time() < deadline:
        time.sleep(0.2)

    snapshot = harness.state.snapshot(strict=True)
    assert snapshot["controller"]["last_sequence"]["kind"] in ("shutdown", "wake")
    assert snapshot["diagnostics"]["summary"]
    assert snapshot["scenario"]["result"] in ("pass", "warn")
    assert snapshot["agents"] and snapshot["ptero"]["servers"] and snapshot["events"]


def test_malformed_agent_status_becomes_an_offline_entry(harness):
    """Agent 回傳奇怪的資料時，那一台顯示為離線並附上原因，其他台與整個監控不受影響。"""
    real = harness.drivers.agent_status

    def broken(agent, index):
        status = real(agent, index)
        if index == 2:
            status["latency_ms"] = {"not": "a number"}
            status["hostname"] = None
        return status

    harness.drivers.agent_status = broken
    agents = harness.service.monitor.refresh_agents()
    assert [agent.online for agent in agents] == [True, False, True]
    assert "格式不正確" in agents[1].error and agents[1].name == "Node-2"
    harness.state.snapshot(strict=True)


def test_malformed_ups_reading_does_not_stop_the_control_cycle(harness):
    """UPS 回傳無法解析的電量時，這一輪照常判斷（電量未知就不關機），不會因為型別錯誤而拋出例外。"""
    harness.env.set_grid(False)
    real = harness.drivers.ups_variables
    harness.drivers.ups_variables = lambda: {**real(), "battery.runtime": "n/a", "ups.load": None}
    assert harness.service.run_cycle() == "hold_on"
    assert harness.state.get("ups").runtime is None


def test_real_client_output_fits_the_models(monkeypatch):
    """實機客戶端產生的資料欄位，要和狀態模型對得起來（模擬驅動已由其他測試涵蓋）。"""
    import requests

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "hostname": "pve", "uptime_seconds": 60.5, "capabilities": ["status"],
                    "system": {"cpu_count": 8}}

    monkeypatch.setattr(requests, "get", lambda url, **kwargs: Response())
    status = AgentClient("unused.pem").status({"name": "PVE", "ip": "192.168.50.250", "port": 5858, "mac": "AA"}, 1)
    agent = AgentState.model_validate({**status, "index": 1, "checked_at": 1.0, "last_seen": 1.0, "mac_valid": False})
    assert agent.online and agent.port == "5858"

    listed = {"identifier": "11111111", "uuid": "11111111-aaaa", "name": "Rust", "node_id": 3, "suspended": False}
    resources = {"state": "running", "cpu_percent": 12.5, "memory_bytes": 1024, "uptime_ms": 5000}
    assert ServerState.model_validate({**listed, **resources, "error": "", "node_name": "n"}).state == "running"

    ups = UpsState()
    for name, value in {**build_ups_snapshot({"ups.status": "OL", "battery.charge": "100"}), **error_snapshot("x")}.items():
        setattr(ups, name, value)   # 欄位名稱對不上會在這裡報錯


def test_api_docs_describe_the_state(harness):
    from fastapi.testclient import TestClient

    from Web.server import create_app
    schema = TestClient(create_app(harness.service, harness.diagnostics, harness.env, None)).get("/api/openapi.json").json()
    schemas = schema["components"]["schemas"]
    assert {"Snapshot", "UpsState", "AgentState", "ServerState", "Sequence"} <= set(schemas)
    assert "battery" in schemas["UpsState"]["properties"]
