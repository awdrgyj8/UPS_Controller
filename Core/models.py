"""共享狀態的形狀：控制迴圈、監控執行緒與網頁介面看到的是同一份資料，欄位都定義在這裡。

/api/state 送出的就是 Snapshot；啟動後可在 /api/docs 看到完整欄位。

型別只在「由外部資料建立物件」時檢查（見 StatusMonitor）；之後對屬性賦值不再檢查，
所以設備回傳奇怪的資料時不會讓控制流程因為型別錯誤而中斷。寫錯欄位名稱則一定會報錯。
"""
from typing import Any

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- 控制器 ----
class SequenceStep(Model):
    id: str
    label: str
    status: str = "pending"          # pending / running / done / warning / failed / skipped
    detail: str = ""
    progress: float | None = None    # 0–1，只有等待類的步驟會填


class Sequence(Model):
    """一次關機或喚醒流程的進度。"""
    kind: str                        # shutdown / wake
    title: str
    result: str = "running"          # running / success / aborted
    detail: str = ""
    started_at: float
    finished_at: float | None = None
    steps: list[SequenceStep] = []


class ControllerState(Model):
    hostname: str = ""
    phase: str = "starting"          # 見 state.PHASE_LABELS
    phase_label: str = ""
    decision: str = ""
    expected_power_state: bool | None = None   # 節點應該開著（True）還是關著（False）
    paused: bool = False
    cycle_count: int = 0
    last_cycle_at: float | None = None
    next_cycle_at: float | None = None
    sequence: Sequence | None = None
    last_sequence: Sequence | None = None


# ---- UPS / NUT ----
class NutState(Model):
    host: str = ""
    port: str = ""
    ups_name: str = ""
    auth: bool = False
    connected: bool | None = None
    latency_ms: int | None = None
    error: str = ""
    last_update: float | None = None


class StatusFlag(Model):
    code: str
    label: str
    level: str


class UpsState(Model):
    ok: bool | None = None           # None：還沒讀過；False：讀取失敗
    power: bool | None = None        # True 市電供電，False 電池供電
    status: str = "UNKNOWN"          # NUT 的 ups.status 原始字串
    status_flags: list[StatusFlag] = []
    battery: int | None = None
    error: str = ""
    runtime: float | None = None
    load: float | None = None
    input_voltage: float | None = None
    output_voltage: float | None = None
    input_frequency: float | None = None
    battery_voltage: float | None = None
    temperature: float | None = None
    variables: dict[str, Any] = {}   # 全部 NUT 變數
    updated_at: float | None = None
    on_battery_since: float | None = None


# ---- 節點 ----
class AgentState(Model):
    index: int
    name: str = ""
    ip: str = ""
    port: str = ""
    mac: str = ""
    mac_valid: bool = False
    online: bool = False
    hostname: str = ""
    uptime_seconds: float | None = None
    latency_ms: int | None = None
    error: str = ""
    capabilities: list[str] = []
    system: dict[str, Any] | None = None       # Agent 回報的 CPU / 記憶體 / 磁碟，格式由 Agent 決定
    checked_at: float | None = None
    last_seen: float | None = None
    ptero_node_ids: list[Any] = []             # 這台主機上跑的 Pterodactyl node
    servers: list[str] = []                    # 這台主機上的伺服器 identifier


# ---- Pterodactyl ----
class ServerState(Model):
    identifier: str
    uuid: str = ""
    name: str = ""
    node_id: Any = None
    node_name: str = ""
    suspended: bool = False
    state: str = "unknown"           # running / starting / stopping / offline / unknown
    cpu_percent: float | None = None
    memory_bytes: float | None = None
    uptime_ms: float | None = None
    error: str = ""
    agent_index: int | None = None   # 所在主機；None 代表對應不到


class PteroNode(Model):
    id: Any = None
    name: str = ""
    fqdn: str = ""
    maintenance_mode: bool = False


class PteroState(Model):
    configured: bool | None = None
    url: str = ""
    ok: bool | None = None
    error: str = ""
    servers: list[ServerState] = []
    nodes: list[PteroNode] = []
    updated_at: float | None = None


# ---- 測試中心 ----
class CheckResult(Model):
    id: str
    group: str
    label: str
    status: str = "running"          # running / pass / warn / fail / skip
    detail: str = ""
    duration_ms: int | None = None
    dry_run: bool = False


class DiagnosticsState(Model):
    kind: str                        # selftest / drill
    title: str
    running: bool = True
    started_at: float
    finished_at: float | None = None
    summary: dict[str, int] | None = None      # 各狀態的筆數
    results: list[CheckResult] = []


class ScenarioStep(Model):
    label: str
    status: str = "running"          # running / pass / warn / fail / skip
    detail: str = ""
    started_at: float
    duration_ms: int | None = None


class ScenarioState(Model):
    id: str
    title: str
    running: bool = True
    result: str = "running"          # running / pass / warn / fail / cancelled
    detail: str = ""
    started_at: float
    finished_at: float | None = None
    steps: list[ScenarioStep] = []


# ---- 事件與歷史 ----
class Event(Model):
    id: int
    ts: float
    level: str                       # info / success / warning / error
    source: str
    message: str


class Sample(Model):
    """一次 UPS 讀數，供趨勢圖使用。"""
    seq: int
    t: float
    battery: int | None = None
    load: float | None = None
    runtime: float | None = None
    input_voltage: float | None = None
    output_voltage: float | None = None
    power: bool | None = None


# ---- 整體 ----
class AppState(Model):
    mode: str                        # real / simulation
    started_at: float
    controller: ControllerState = ControllerState()
    nut: NutState = NutState()
    ups: UpsState = UpsState()
    agents: list[AgentState] = []
    agent_config_error: str = ""
    agents_updated_at: float | None = None
    ptero: PteroState = PteroState()
    diagnostics: DiagnosticsState | None = None
    scenario: ScenarioState | None = None
    simulation: dict[str, Any] | None = None   # 模擬環境的狀態，格式見 SimEnvironment.to_dict


class Snapshot(AppState):
    """/api/state 與 SSE 送出的內容。"""
    events: list[Event]
    version: int
    server_time: float
    settings: dict[str, Any]
