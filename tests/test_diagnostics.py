from Core.scenarios import ScenarioRunner


def test_selftest_passes_on_healthy_simulation(harness):
    harness.service.monitor.refresh_status()
    result = harness.diagnostics.run_sync("selftest")
    failures = [r for r in result.results if r.status not in ("pass", "skip")]
    assert failures == []
    assert result.summary["pass"] >= 20


def test_selftest_reports_failures(harness):
    harness.env.set_nut_reachable(False)
    harness.env.set_agent_fault(2, "reject")
    result = harness.diagnostics.run_sync("selftest")
    statuses = {r.id: r.status for r in result.results}
    assert statuses["nut.connect"] == "fail"
    assert statuses["nut.variables"] == "skip"
    assert statuses["agent.2.verify"] == "fail"
    assert statuses["agent.1.verify"] == "pass"


def test_drill_has_no_side_effects(harness):
    result = harness.diagnostics.run_sync("drill")
    assert result.summary.get("fail", 0) == 0
    assert all(server.state in ("running", "starting") for server in harness.env.servers)
    assert all(agent.power == "on" and agent.shutdown_requests == 0 for agent in harness.env.agents)
    assert harness.env.wol_packets == 0
    assert any(r.dry_run for r in result.results)


def test_full_outage_scenario_end_to_end(harness):
    import time
    harness.service.start()
    runner = ScenarioRunner(harness.service, harness.env)
    assert runner.start("full_outage")
    deadline = time.time() + 120
    while harness.state.get("scenario").running and time.time() < deadline:
        time.sleep(0.2)
    scenario = harness.state.get("scenario")
    assert scenario.result == "pass", [s for s in scenario.steps if s.status != "pass"]
