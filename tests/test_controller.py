"""控制流程測試：以模擬環境執行與實機相同的控制程式碼。"""
import pytest

from Core.controller import decide, estimate_realpower, map_nodes_to_agents


@pytest.mark.parametrize("snapshot, expected_on, action", [
    ({"ok": False, "power": None, "battery": None}, True, "skip"),
    ({"ok": True, "power": True, "battery": 100}, True, "hold_on"),
    ({"ok": True, "power": False, "battery": 51}, True, "hold_on"),
    ({"ok": True, "power": False, "battery": 50}, True, "shutdown"),
    ({"ok": True, "power": False, "battery": None}, True, "hold_on"),
    ({"ok": True, "power": True, "battery": 40}, False, "wake"),
    ({"ok": True, "power": False, "battery": 40}, False, "hold_off"),
])
def test_decide_matches_original_logic(snapshot, expected_on, action):
    assert decide(snapshot, expected_on, 50) == action


NODES = [{"id": 1, "name": "PVE-Ubuntu", "fqdn": "vm.example.com"},
         {"id": 3, "name": "Server-SystemSSD", "fqdn": "a.example.com"},
         {"id": 4, "name": "Server-External-SSD", "fqdn": "192.168.50.230"}]
AGENTS = [{"index": 1, "name": "Server", "ip": "192.168.50.230"}, {"index": 2, "name": "PVE", "ip": "192.168.50.250"}]


def test_ptero_info_maps_nodes_to_hosts():
    info = [{"node": 3, "agent": "Server"}, {"node": "PVE-Ubuntu", "agent": "192.168.50.250"}]
    mapping, problems = map_nodes_to_agents(AGENTS, NODES, info)
    # node 4 沒寫在 PteroInfo，但 fqdn 等於 Server 的 IP，自動對應
    assert mapping == {3: 1, 1: 2, 4: 1}
    assert problems == []


def test_ptero_info_reports_unknown_references():
    info = [{"node": 9, "agent": "Server"}, {"node": 3, "agent": "Nope"}]
    mapping, problems = map_nodes_to_agents(AGENTS, NODES, info)
    assert mapping == {4: 1}
    assert len(problems) == 2


def test_load_ptero_info(monkeypatch):
    from Core.config import load_ptero_info
    monkeypatch.setenv("PteroInfo", '[{"node":1,"agent":"PVE"},{"node":2}]')
    entries, error = load_ptero_info()
    assert entries == [{"node": 1, "agent": "PVE"}]
    assert "第 2 筆" in error
    monkeypatch.setenv("PteroInfo", "not json")
    assert load_ptero_info()[1].startswith("PteroInfo JSON")
    monkeypatch.delenv("PteroInfo")
    assert load_ptero_info() == ([], "")


def test_link_topology_uses_ptero_info(harness, monkeypatch):
    harness.drivers.ptero_info = lambda: ([{"node": 3, "agent": "Server"}, {"node": 4, "agent": "Server"},
                                          {"node": 1, "agent": "PVE"}], "")
    data = {
        "agents": [dict(agent) for agent in AGENTS],
        "ptero": {"nodes": NODES, "servers": [{"identifier": "aaa", "node_id": 3}, {"identifier": "bbb", "node_id": 4},
                                              {"identifier": "ccc", "node_id": 1}]},
    }
    harness.service._link_topology(data)
    assert data["agents"][0]["servers"] == ["aaa", "bbb"]
    assert data["agents"][0]["ptero_node_ids"] == [3, 4]
    assert data["agents"][1]["servers"] == ["ccc"]


def test_normal_power_keeps_nodes_on(harness):
    assert harness.service.run_cycle() == "hold_on"
    assert harness.state.get("controller")["phase"] == "monitoring"
    assert harness.power_store.expected() is True


def test_on_battery_above_threshold_only_monitors(harness):
    harness.outage(80)
    assert harness.service.run_cycle() == "hold_on"
    assert harness.state.get("controller")["phase"] == "on_battery"
    assert all(agent.shutdown_requests == 0 for agent in harness.env.agents)


def test_full_shutdown_then_wake(harness):
    harness.outage(50)
    assert harness.service.run_cycle() == "shutdown"
    sequence = harness.state.get("controller")["sequence"]
    assert sequence["result"] == "success"
    assert [step["status"] for step in sequence["steps"]] == ["done"] * 6
    assert all(server.state == "offline" for server in harness.env.servers)
    assert all(agent.shutdown_requests == 1 for agent in harness.env.agents)
    assert harness.power_store.expected() is False

    harness.advance(3)
    assert all(agent.power == "off" for agent in harness.env.agents)
    assert harness.service.run_cycle() == "hold_off"

    harness.env.set_grid(True)
    assert harness.service.run_cycle() == "wake"
    assert harness.state.get("controller")["sequence"]["result"] == "success"
    assert harness.power_store.expected() is True
    harness.advance(7)
    assert all(agent.power == "on" for agent in harness.env.agents)


def test_stuck_server_times_out_without_shutting_down_nodes(harness):
    harness.settings.server_stop_max_attempts = 3
    harness.settings.server_stop_check_interval = 0.05
    harness.env.servers[0].stuck = True
    harness.outage(50)
    harness.service.run_cycle()
    sequence = harness.state.get("controller")["sequence"]
    assert sequence["result"] == "aborted"
    assert {step["id"]: step["status"] for step in sequence["steps"]}["wait_servers"] == "failed"
    assert all(agent.shutdown_requests == 0 for agent in harness.env.agents)
    assert harness.power_store.expected() is True


def test_rejected_signature_keeps_power_state(harness):
    harness.env.set_agent_fault(1, "reject")
    harness.outage(50)
    harness.service.run_cycle()
    steps = {step["id"]: step for step in harness.state.get("controller")["sequence"]["steps"]}
    assert steps["shutdown_agents"]["status"] == "failed"
    assert "invalid signature" in steps["shutdown_agents"]["detail"]
    assert harness.power_store.expected() is True
    # 現行邏輯：其他節點仍會收到關機請求
    assert [agent.shutdown_requests for agent in harness.env.agents][1:] == [1] * (len(harness.env.agents) - 1)


def test_panel_down_skips_node_shutdown(harness):
    harness.env.set_ptero_reachable(False)
    harness.outage(50)
    harness.service.run_cycle()
    steps = {step["id"]: step for step in harness.state.get("controller")["sequence"]["steps"]}
    assert steps["list_servers"]["status"] == "failed"
    assert all(agent.shutdown_requests == 0 for agent in harness.env.agents)


def test_nut_unreachable_skips_cycle(harness):
    harness.env.set_nut_reachable(False)
    assert harness.service.run_cycle() == "skip"
    assert harness.state.get("controller")["phase"] == "nut_error"
    assert harness.state.get("nut")["connected"] is False


def test_paused_controller_does_not_act(harness):
    harness.service.set_paused(True)
    assert harness.state.get("controller")["phase"] == "paused"
    harness.service.set_paused(False)
    assert harness.state.get("controller")["paused"] is False


def test_monitoring_links_servers_to_agents(harness):
    harness.service.refresh_status()
    agents = harness.state.get("agents")
    servers = harness.state.get("ptero")["servers"]
    assert all(agent["online"] for agent in agents)
    assert sum(len(agent["servers"]) for agent in agents) == len(servers)
    assert all(server["agent_index"] is not None for server in servers)


def test_ups_history_is_recorded(harness):
    harness.service.read_ups()
    harness.service.read_ups()
    samples = harness.state.history()
    assert len(samples) == 2
    assert samples[-1]["battery"] == 100


def test_estimate_realpower():
    # 有回報 ups.realpower 就直接用
    assert estimate_realpower({"ups.realpower": "481", "ups.load": "53"}) == \
        {"realpower": 481, "realpower_nominal": None, "realpower_estimated": False}
    # CyberPower：只有負載 % 與額定功率
    cps = {"ups.load": "20", "ups.realpower.nominal": "600"}
    assert estimate_realpower(cps) == {"realpower": 120, "realpower_nominal": 600.0, "realpower_estimated": True}
    # 手動設定的額定功率優先
    assert estimate_realpower(cps, 900)["realpower"] == 180
    # 缺少額定功率時無法估算
    assert estimate_realpower({"ups.load": "20"})["realpower"] is None
