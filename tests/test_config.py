"""設定讀取：環境變數對應、AgentInfo / PteroInfo 解析，以及不會把金鑰送到網頁介面。"""
import pytest
from pydantic import ValidationError

from Core.config import Settings, load_settings, parse_agent_info, parse_ptero_info


def settings_from(monkeypatch, **env):
    """只看測試給的環境變數，不讀開發機上的 .env。"""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_env_names_map_to_fields(monkeypatch):
    s = settings_from(
        monkeypatch,
        POLL_INTERVAL="12.5", SHUTDOWN_BATTERY_THRESHOLD="40", WEB_ENABLED="false", SIMULATION="true",
        NUT_ServerIP="10.0.0.5", NUT_ServerPort="3493", NUT_UPS_NAME="ups", NUT_Login="monuser",
        PteroApi_Url="https://panel.test", PteroApi_AppKey="app", PteroApi_ClientKey="client",
    )
    assert (s.poll_interval, s.shutdown_battery_threshold, s.web_enabled, s.simulate) == (12.5, 40, False, True)
    assert (s.nut_host, s.nut_port, s.nut_ups_name, s.nut_login) == ("10.0.0.5", 3493, "ups", "monuser")
    assert (s.ptero_url, s.ptero_app_key, s.ptero_client_key) == ("https://panel.test", "app", "client")


def test_blank_values_fall_back_to_defaults(monkeypatch):
    s = settings_from(monkeypatch, POLL_INTERVAL="", NUT_Login="", WEB_TOKEN="")
    assert s.poll_interval == 30
    assert s.nut_login is None
    assert s.web_token == ""


def test_invalid_number_is_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        settings_from(monkeypatch, POLL_INTERVAL="soon")


def test_public_dict_never_exposes_secrets(monkeypatch):
    s = settings_from(
        monkeypatch, WEB_TOKEN="web-secret", NUT_Password="nut-secret",
        PteroApi_AppKey="app-secret", PteroApi_ClientKey="client-secret", AgentInfo='[{"ip":"1.2.3.4"}]',
    )
    public = s.public_dict()
    assert public["auth_required"] is True
    assert not any("secret" in str(value) for value in public.values())
    assert "secret" not in repr(s)
    assert not {"web_token", "nut_password", "ptero_app_key", "ptero_client_key", "agent_info_raw"} & set(public)


def test_simulation_uses_short_intervals(monkeypatch):
    monkeypatch.setenv("POLL_INTERVAL", "30")
    assert load_settings(simulate=True).poll_interval == 2


def test_agent_info(monkeypatch):
    s = settings_from(monkeypatch, AgentInfo='[{"name":"PVE","ip":"192.168.50.250","port":5858}]')
    assert s.agent_info() == ([{"name": "PVE", "ip": "192.168.50.250", "port": 5858}], "")
    assert parse_agent_info(None) == ([], "AgentInfo 環境變數未設定")
    assert parse_agent_info("not json") == ([], "AgentInfo JSON 格式錯誤")
    assert parse_agent_info('{"ip":"1.2.3.4"}') == ([], "AgentInfo 必須是 JSON 陣列")


def test_ptero_info():
    entries, error = parse_ptero_info('[{"node":1,"agent":"PVE"},{"node":2}]')
    assert entries == [{"node": 1, "agent": "PVE"}]
    assert "第 2 筆" in error
    assert parse_ptero_info("not json")[1].startswith("PteroInfo JSON")
    assert parse_ptero_info(None) == ([], "")
    assert parse_ptero_info("  ") == ([], "")
