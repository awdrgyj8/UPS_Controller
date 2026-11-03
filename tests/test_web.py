import pytest
from fastapi.testclient import TestClient

from Web.server import create_app


@pytest.fixture
def client(harness):
    return TestClient(create_app(harness.service, harness.diagnostics, harness.env, None))


def test_state_endpoint(client, harness):
    harness.service.read_ups()
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
