"""Controller 設定：唯一讀取環境變數與 .env 的地方，其他模組一律從 Settings 物件拿值。"""
import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]

# 會送到網頁介面的欄位。金鑰與密碼不在裡面，新增欄位時也要自己決定要不要公開。
PUBLIC_FIELDS = (
    "simulate", "poll_interval", "monitor_interval", "shutdown_battery_threshold",
    "server_stop_check_interval", "server_stop_max_attempts", "wol_attempts", "wol_interval",
    "web_enabled", "web_host", "web_port", "console_table",
)


class Settings(BaseSettings):
    """環境變數名稱不分大小寫；沒有另外標明的欄位，變數名稱就是欄位名稱的大寫（例如 POLL_INTERVAL）。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,   # 留空的變數（例如 NUT_Login=）視為沒有設定
        extra="ignore",
        populate_by_name=True,
    )

    simulate: bool = Field(False, validation_alias="SIMULATION")
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
    web_token: str = Field("", repr=False)
    console_table: bool = True
    # NUT
    nut_host: str = Field("", validation_alias="NUT_ServerIP")
    nut_port: int | None = Field(None, validation_alias="NUT_ServerPort")
    nut_ups_name: str = Field("", validation_alias="NUT_UPS_NAME")
    nut_login: str | None = Field(None, validation_alias="NUT_Login")
    nut_password: str | None = Field(None, validation_alias="NUT_Password", repr=False)
    # Pterodactyl
    ptero_url: str = Field("", validation_alias="PteroApi_Url")
    ptero_app_key: str = Field("", validation_alias="PteroApi_AppKey", repr=False)
    ptero_client_key: str = Field("", validation_alias="PteroApi_ClientKey", repr=False)
    # 節點清單與 node 對應：保留原始字串，格式錯誤時由 agent_info() / ptero_info() 回報，不讓程式起不來
    agent_info_raw: str | None = Field(None, validation_alias="AgentInfo")
    ptero_info_raw: str | None = Field(None, validation_alias="PteroInfo")
    # 檔案位置
    power_state_path: Path = BASE_DIR / "Data" / "powerState.json"
    private_key_path: Path = BASE_DIR / "Keys" / "private_key.pem"

    def agent_info(self):
        """AgentInfo：裝了 UPS_Agent 的主機清單。回傳 (清單, 錯誤訊息)。"""
        return parse_agent_info(self.agent_info_raw)

    def ptero_info(self):
        """PteroInfo：每個 Pterodactyl node 跑在哪台主機上。回傳 (清單, 錯誤訊息)。"""
        return parse_ptero_info(self.ptero_info_raw)

    def public_dict(self):
        data = {name: getattr(self, name) for name in PUBLIC_FIELDS}
        data["power_state_path"] = str(self.power_state_path) if not self.simulate else "(模擬模式：記憶體)"
        data["auth_required"] = bool(self.web_token)
        return data


def _blank(raw):
    return raw is None or raw.strip() == ""


def parse_agent_info(raw):
    """格式：[{"name": ..., "ip": ..., "port": ..., "mac": ...}, ...]"""
    if _blank(raw):
        return [], "AgentInfo 環境變數未設定"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [], "AgentInfo JSON 格式錯誤"
    if not isinstance(data, list):
        return [], "AgentInfo 必須是 JSON 陣列"
    return data, ""


def parse_ptero_info(raw):
    """格式：[{"node": node id 或名稱, "agent": AgentInfo 的 name 或 ip}, ...]

    只用於拓撲圖與自檢；停電時一律停止面板上的全部伺服器，不受這份設定影響。
    """
    if _blank(raw):
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


def load_settings(simulate=None):
    """讀取設定。simulate 給 True / False 時覆蓋環境變數 SIMULATION（命令列的 --simulate）。"""
    settings = Settings()
    if simulate is not None:
        settings.simulate = simulate
    if settings.simulate:
        # 模擬模式固定使用較短的間隔，方便觀察整個流程（不受實機 .env 的間隔設定影響）
        settings.poll_interval = 2
        settings.monitor_interval = 1
        settings.server_stop_check_interval = 0.5
        settings.wol_attempts = 5
        settings.wol_interval = 0.2
        settings.console_table = False
    return settings
