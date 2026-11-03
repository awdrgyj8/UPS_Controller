"""Controller 設定：全部由環境變數（.env）與命令列參數決定。"""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _env_number(name, default, cast=float):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return cast(value)
    except ValueError:
        raise ValueError(f"{name} 必須是數字")


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    simulate: bool = False
    # 控制流程
    poll_interval: float = 30
    monitor_interval: float = 5
    shutdown_battery_threshold: int = 50
    server_stop_check_interval: float = 5
    server_stop_max_attempts: int = 20
    wol_attempts: int = 20
    wol_interval: float = 1
    # Web 介面
    web_enabled: bool = True
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_token: str = field(default="", repr=False)
    console_table: bool = True
    power_state_path: Path = BASE_DIR / "Data" / "powerState.json"

    def public_dict(self):
        data = asdict(self)
        data.pop("web_token")
        data["power_state_path"] = str(self.power_state_path) if not self.simulate else "(模擬模式：記憶體)"
        data["auth_required"] = bool(self.web_token)
        return data


def load_settings(simulate=None):
    if simulate is None:
        simulate = _env_bool("SIMULATION", False)
    settings = Settings(
        simulate=simulate,
        poll_interval=_env_number("POLL_INTERVAL", 30),
        monitor_interval=_env_number("MONITOR_INTERVAL", 5),
        shutdown_battery_threshold=_env_number("SHUTDOWN_BATTERY_THRESHOLD", 50, int),
        server_stop_check_interval=_env_number("SERVER_STOP_CHECK_INTERVAL", 5),
        server_stop_max_attempts=_env_number("SERVER_STOP_MAX_ATTEMPTS", 20, int),
        wol_attempts=_env_number("WOL_ATTEMPTS", 20, int),
        wol_interval=_env_number("WOL_INTERVAL", 1),
        web_enabled=_env_bool("WEB_ENABLED", True),
        web_host=os.getenv("WEB_HOST") or "127.0.0.1",
        web_port=_env_number("WEB_PORT", 8080, int),
        web_token=os.getenv("WEB_TOKEN") or "",
        console_table=_env_bool("CONSOLE_TABLE", True),
    )
    if simulate:
        # 模擬模式固定使用較短的間隔，方便觀察整個流程（不受實機 .env 的間隔設定影響）
        settings.poll_interval = 2
        settings.monitor_interval = 1
        settings.server_stop_check_interval = 0.5
        settings.wol_attempts = 5
        settings.wol_interval = 0.2
        settings.console_table = False
    return settings


def load_ptero_info():
    """讀取 PteroInfo（每個 Pterodactyl node 跑在哪台 UPS_Agent 主機上），回傳 (清單, 錯誤訊息)。

    格式：[{"node": node id 或名稱, "agent": AgentInfo 的 name 或 ip}, ...]
    只用於拓撲圖與自檢；停電時一律停止面板上的全部伺服器，不受這份設定影響。
    """
    raw = os.getenv("PteroInfo")
    if raw is None or raw.strip() == "":
        return [], ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [], f"PteroInfo JSON 格式錯誤: {e}"
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        return [], 'PteroInfo 必須是 JSON 陣列，例如 [{"node":1,"agent":"PVE"}]'
    valid = [item for item in data if item.get("node") not in (None, "") and item.get("agent") not in (None, "")]
    if len(valid) != len(data):
        missing = [str(i) for i, item in enumerate(data, start=1) if item not in valid]
        return valid, f"PteroInfo 第 {', '.join(missing)} 筆缺少 node 或 agent 欄位"
    return valid, ""
