"""Controller 設定：全部由環境變數（.env）與命令列參數決定。"""
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
