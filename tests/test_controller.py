"""控制流程測試：以模擬環境執行與實機相同的控制程式碼。"""
import pytest

from Core.controller import decide, match_agent_node


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


def test_match_agent_node_prefers_explicit_setting():
    nodes = [{"id": 1, "name": "wings-a", "fqdn": "10.0.0.1"}, {"id": 2, "name": "wings-b", "fqdn": "b.example.com"}]
    assert match_agent_node({"ip": "10.0.0.1", "ptero_node": "wings-b"}, nodes) == 2
    assert match_agent_node({"ip": "10.0.0.1"}, nodes) == 1
    assert match_agent_node({"ip": "10.0.0.9", "hostname": "b.example.com"}, nodes) == 2
    assert match_agent_node({"ip": "10.0.0.9", "name": "other"}, nodes) is None


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
