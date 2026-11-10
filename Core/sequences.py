"""關機與喚醒流程：真正會動到設備的兩段程序，以及它們在介面上的逐步進度。"""
import time

from Api.event_log import log
from Core.drivers import DriverError
from Core.models import Sequence, SequenceStep

SHUTDOWN_STEPS = [
    ("trigger", "觸發條件成立"),
    ("list_servers", "取得面板伺服器清單"),
    ("stop_servers", "送出伺服器停止訊號"),
    ("wait_servers", "等待伺服器關機"),
    ("shutdown_agents", "送出節點關機請求"),
    ("save_state", "更新電源狀態為「關機」"),
]

WAKE_STEPS = [
    ("trigger", "市電恢復"),
    ("wol", "發送 Wake-on-LAN"),
    ("save_state", "更新電源狀態為「開機」"),
]


class SequenceRunner:
    """stop_event 被設定時（程式要結束）流程會提早中止並回傳 False。"""

    def __init__(self, settings, drivers, state, power_store, monitor, stop_event):
        self.settings = settings
        self.drivers = drivers
        self.state = state
        self.power_store = power_store
        self.monitor = monitor
        self._stop = stop_event

    # ------------------------------------------------------------------ 進度記錄
    def _begin(self, kind, steps, title):
        sequence = Sequence(kind=kind, title=title, started_at=time.time(),
                            steps=[SequenceStep(id=step_id, label=label) for step_id, label in steps])
        self.state.update("controller", sequence=sequence)

    def _step(self, step_id, status, detail="", progress=None):
        def apply(data):
            for step in data.controller.sequence.steps:
                if step.id == step_id:
                    step.status, step.detail, step.progress = status, detail, progress

        self.state.mutate(apply)

    def _end(self, result, detail):
        def apply(data):
            sequence = data.controller.sequence
            sequence.result, sequence.detail, sequence.finished_at = result, detail, time.time()
            for step in sequence.steps:
                if step.status == "pending":
                    step.status = "skipped"
            data.controller.last_sequence = sequence.model_copy(deep=True)

        self.state.mutate(apply)

    def _abort(self, step_id, step_detail, message):
        log(f"⚠️ {message}", source="controller")
        self._step(step_id, "failed", step_detail)
        self._end("aborted", message)
        return False

    # ------------------------------------------------------------------ 停電關機
    def run_shutdown(self, power_data, snapshot):
        """停止面板上所有伺服器 → 等它們都停下來 → 關閉節點 → 記錄為已關機。成功回傳 True。

        任何一步沒有完成就中止，而且不更新電源狀態，下一輪會重新嘗試。
        """
        threshold = self.settings.shutdown_battery_threshold
        self._begin("shutdown", SHUTDOWN_STEPS, "停電關機程序")
        log("正在執行關機程序", level="warning", source="controller")
        self._step("trigger", "done", f"電池供電（{snapshot['status']}），電量 {snapshot['battery']}% ≤ {threshold}%")

        identifiers = self._list_servers()
        if not identifiers:
            return self._abort("list_servers", "未取得任何伺服器 UUID", "未取得任何 Pterodactyl 伺服器 UUID，跳過節點關機流程")
        self._step("list_servers", "done", f"共 {len(identifiers)} 台伺服器")

        self._step("stop_servers", "running")
        sent = sum(1 for identifier in identifiers if self.drivers.ptero_send_power(identifier, "stop"))
        self._step("stop_servers", "done" if sent == len(identifiers) else "warning",
                   f"已送出 {sent}/{len(identifiers)} 個停止訊號")

        stopped = self._wait_for_servers(identifiers)
        if stopped is None:
            return False
        if not stopped:
            attempts = self.settings.server_stop_max_attempts
            return self._abort("wait_servers", f"逾時：{attempts} 次檢查後仍有伺服器未關機", "等待面板伺服器關機逾時，跳過節點關機流程")
        self._step("wait_servers", "done", "全部伺服器皆為 offline", progress=1)

        accepted, summary = self._shutdown_agents()
        if not accepted:
            return self._abort("shutdown_agents", summary, "部分或全部節點未接受關機請求，暫不更新節點關機狀態")
        self._step("shutdown_agents", "done", summary or "沒有設定任何 Agent")

        self._save_expected(power_data, False)
        self._step("save_state", "done", "AgentPowerState = false")
        self._end("success", "節點關機程序完成")
        return True

    def _list_servers(self):
        self._step("list_servers", "running")
        try:
            return [server["identifier"] for server in self.drivers.ptero_list_servers()]
        except DriverError as e:
            log(f"Request failed: {e}", level="error", source="ptero")
            return []

    def _wait_for_servers(self, identifiers):
        """反覆檢查直到全部 offline。回傳 True（都停了）、False（逾時）、None（程式要結束）。"""
        max_attempts = self.settings.server_stop_max_attempts
        self._step("wait_servers", "running", "檢查伺服器狀態中…", progress=0)
        for attempt in range(1, max_attempts + 1):
            pending = []
            for identifier in identifiers:
                try:
                    current = self.drivers.ptero_server_resources(identifier)["state"]
                except DriverError as e:
                    log(f"❌ 取得 {identifier} 電源狀態時發生錯誤: {e}", source="ptero")
                    current = "unknown"
                self.monitor.set_server_state(identifier, current)
                if current != "offline":
                    log(f"⌛ 正在等待伺服器 {identifier} 關機，目前狀態 {current}", level="info", source="controller")
                    pending.append(identifier)
            if not pending:
                log("✅ 面板伺服器皆已關機，開始進入節點關機流程", source="controller")
                return True
            self._step("wait_servers", "running",
                       f"第 {attempt}/{max_attempts} 次檢查，尚有 {len(pending)} 台未關機：{', '.join(pending)}",
                       progress=attempt / max_attempts)
            # 給伺服器關機的緩衝時間
            if self._stop.wait(self.settings.server_stop_check_interval):
                return None
        return False

    def _shutdown_agents(self):
        """對每台節點送出關機請求，回傳 (是否全部接受, 各節點結果的摘要)。"""
        self._step("shutdown_agents", "running")
        configs, error = self.drivers.agent_configs()
        accepted = not error
        if error:
            log(f"❌ {error}", source="agent")
        results = []
        for agent in configs:
            ok, message = self.drivers.agent_shutdown(agent)
            results.append(f"{agent.get('name', agent.get('ip', '?'))}: {'接受' if ok else message}")
            if not ok:
                accepted = False
        return accepted, "；".join(results) or error

    # ------------------------------------------------------------------ 復電喚醒
    def run_wake(self, power_data, snapshot):
        """對每台節點送出 Wake-on-LAN，至少送出一個封包才記錄為已開機。成功回傳 True。"""
        self._begin("wake", WAKE_STEPS, "復電開機程序")
        self._step("trigger", "done", f"UPS 狀態 {snapshot['status']}，電量 {snapshot['battery']}%")
        configs, error = self.drivers.agent_configs()
        if error:
            log(f"❌ {error}", source="wol")
        for agent in configs:
            if "mac" not in agent:
                log(f"❌ AgentInfo 缺少 mac 欄位: {agent}", source="wol")
        macs = [agent["mac"] for agent in configs if "mac" in agent]

        attempts = self.settings.wol_attempts
        packets = 0
        for attempt in range(1, attempts + 1):
            self._step("wol", "running", f"第 {attempt}/{attempts} 輪，已送出 {packets} 個封包",
                       progress=attempt / attempts)
            packets += sum(1 for mac in macs if self.drivers.wol(mac))
            if self._stop.wait(self.settings.wol_interval):
                return False

        if packets == 0:
            return self._abort("wol", "沒有任何封包送出成功", "未成功送出 Wake-on-LAN 封包，暫不更新節點開機狀態")
        self._step("wol", "done", f"共送出 {packets} 個 WOL 封包（{len(macs)} 個 MAC × {attempts} 輪）", progress=1)
        self._save_expected(power_data, True)
        self._step("save_state", "done", "AgentPowerState = true")
        self._end("success", "已送出 Wake-on-LAN，等待節點開機")
        log(f"✅ 已送出 {packets} 個 Wake-on-LAN 封包，節點開機中", source="wol")
        return True

    def _save_expected(self, power_data, expected):
        power_data["AgentPowerState"] = expected
        self.power_store.write(power_data)
        self.state.update("controller", expected_power_state=expected)
