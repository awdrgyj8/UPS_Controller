"""控制服務：每一輪讀取 UPS，決定要不要關機或喚醒，並管理背景執行緒。

判斷邏輯：
  * 節點為開機狀態，且 UPS 改由電池供電、電量 <= 門檻 → 關閉面板伺服器 → 關閉節點
  * 節點為關機狀態，且市電恢復 → 發送 Wake-on-LAN

讀取現況在 monitor.py，關機與喚醒的實際步驟在 sequences.py。
"""
import datetime
import json
import os
import threading
import time

from Api import event_log
from Core.monitor import StatusMonitor
from Core.sequences import SequenceRunner
from Core.state import PHASE_LABELS


def decide(snapshot, expected_on, threshold):
    """控制判斷（與原本 main.py 相同）。

    回傳 skip / shutdown / hold_on / wake / hold_off。
    """
    if snapshot["ok"] is not True:
        return "skip"
    if expected_on:
        if snapshot["power"] is False and snapshot["battery"] is not None and snapshot["battery"] <= threshold:
            return "shutdown"
        return "hold_on"
    if snapshot["power"] is True:
        return "wake"
    return "hold_off"


class PowerStateStore:
    """節點預期電源狀態（Data/powerState.json）。path 為 None 時只存在記憶體（模擬模式）。"""

    def __init__(self, path=None):
        self.path = path
        self._memory = {"AgentPowerState": True}
        self._lock = threading.Lock()

    def read(self):
        """檔案還不存在（第一次執行）時視為節點開機中。"""
        with self._lock:
            if self.path is None:
                return dict(self._memory)
            try:
                with open(self.path) as f:
                    return json.load(f)
            except FileNotFoundError:
                return dict(self._memory)

    def write(self, data):
        with self._lock:
            if self.path is None:
                self._memory = dict(data)
                return
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(data, f, indent=4)

    def writable(self):
        """只檢查權限，不實際寫入（供自檢使用）。檔案還不存在時看能不能在資料夾裡建立。"""
        if self.path is None:
            return True
        folder = os.path.dirname(self.path)
        if not os.path.exists(self.path):
            return os.access(folder if os.path.isdir(folder) else os.path.dirname(folder), os.W_OK)
        return os.access(self.path, os.W_OK) and os.access(folder, os.W_OK)

    def expected(self):
        return self.read()["AgentPowerState"]

    def set_expected(self, value):
        data = self.read()
        data["AgentPowerState"] = bool(value)
        self.write(data)


class ControllerService:
    def __init__(self, settings, drivers, state, power_store, console_view=None):
        self.settings = settings
        self.drivers = drivers
        self.state = state
        self.power_store = power_store
        self.console_view = console_view
        self.paused = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._cycle_lock = threading.Lock()
        self._threads = []
        self.monitor = StatusMonitor(drivers, state)
        self.sequences = SequenceRunner(settings, drivers, state, power_store, self.monitor, self._stop)
        event_log.add_hook(self._on_log)

        state.update("nut", **drivers.nut_target())
        state.update("ptero", url=drivers.ptero_url(), configured=drivers.ptero_configured())
        try:
            state.update("controller", expected_power_state=power_store.expected())
        except (OSError, ValueError, KeyError) as e:
            self.log(f"❌ 無法讀取 powerState.json: {e}")

    # ------------------------------------------------------------------ 共用
    def _on_log(self, level, source, message):
        self.state.add_event(level, source, message)

    def log(self, message, level=None, source="controller"):
        event_log.log(message, level=level, source=source)

    def _set_phase(self, phase, decision):
        self.state.update("controller", phase=phase, phase_label=PHASE_LABELS[phase], decision=decision)

    # ------------------------------------------------------------------ 生命週期
    def start(self, control=True):
        targets = [
            ("ups-monitor", lambda: self._repeat(self.monitor.read_ups, self.settings.monitor_interval, "UPS 監控")),
            ("status-monitor", lambda: self._repeat(self.monitor.refresh_status,
                                                    min(self.settings.poll_interval, 15), "狀態監控")),
        ]
        if control:
            targets.append(("control-loop", self._control_loop))
        for name, target in targets:
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def run_forever(self):
        """不啟用 Web 時使用：監控在背景，控制迴圈在目前執行緒。"""
        self.start(control=False)
        self._control_loop()

    def stop(self):
        self._stop.set()
        self._wake.set()
        event_log.remove_hook(self._on_log)

    def _repeat(self, task, interval, name):
        """背景執行緒：固定間隔重複執行 task，出錯只記錄，不讓執行緒中止。"""
        while not self._stop.is_set():
            try:
                task()
            except Exception as e:
                self.log(f"❌ {name}發生未預期錯誤: {e}")
            self._stop.wait(interval)

    def trigger_poll(self):
        self._wake.set()

    def set_paused(self, paused):
        self.paused = bool(paused)
        self.state.update("controller", paused=self.paused)
        if self.paused:
            self._set_phase("paused", "自動控制已暫停：僅監控，不會執行關機或喚醒")
            self.log("⚠️ 自動控制已暫停（維護模式）", source="web")
        else:
            self.log("✅ 自動控制已恢復", source="web")
            self.trigger_poll()

    def set_expected_power_state(self, value):
        self.power_store.set_expected(value)
        self.state.update("controller", expected_power_state=bool(value))
        self.log(f"⚠️ 手動設定節點預期電源狀態為「{'開機' if value else '關機'}」", source="web")
        self.trigger_poll()

    # ------------------------------------------------------------------ 控制
    def _control_loop(self):
        while not self._stop.is_set():
            try:
                if self.paused:
                    self.monitor.read_ups()
                    self._set_phase("paused", "自動控制已暫停：僅監控，不會執行關機或喚醒")
                else:
                    self.run_cycle()
            except Exception as e:  # 控制迴圈不可中止
                self.log(f"❌ 控制流程發生未預期錯誤: {e}")
            self.state.update("controller", next_cycle_at=time.time() + self.settings.poll_interval)
            self._wake.wait(self.settings.poll_interval)
            self._wake.clear()

    def run_cycle(self):
        """跑一輪控制流程，回傳這一輪的判斷（skip / shutdown / hold_on / wake / hold_off）。"""
        with self._cycle_lock:
            data = self.power_store.read()
            expected = data["AgentPowerState"]
            self.state.update("controller", expected_power_state=expected, last_cycle_at=time.time(),
                              cycle_count=self.state.get("controller").cycle_count + 1)
            snapshot = self.monitor.read_ups()
            threshold = self.settings.shutdown_battery_threshold
            action = decide(snapshot, expected, threshold)

            if action == "skip":
                self.log(f"⚠️ 無法讀取 UPS 狀態，略過本輪控制流程: {snapshot['error']}")
                self._set_phase("nut_error", "無法讀取 UPS 狀態，略過本輪控制流程")
                self._show_console(snapshot, expected)
                return action

            if action == "shutdown":
                self._set_phase("shutdown", f"電池供電且電量 {snapshot['battery']}% ≤ 門檻 {threshold}%，執行關機程序")
                if not self.sequences.run_shutdown(data, snapshot):
                    return action
                self._set_phase("nodes_off", "關機程序完成，節點已關機，等待市電恢復")
            elif action == "wake":
                self._set_phase("waking", "市電已恢復，發送 Wake-on-LAN 喚醒節點")
                if self.sequences.run_wake(data, snapshot):
                    self._set_phase("monitoring", "已送出 Wake-on-LAN，等待節點開機上線")
                else:
                    self._set_phase("nodes_off", "Wake-on-LAN 未送出，下一輪重試")
            elif action == "hold_on":
                if snapshot["power"] is False:
                    self._set_phase("on_battery",
                                    f"電池供電中，電量 {snapshot['battery']}% > 門檻 {threshold}%，持續監控")
                else:
                    self._set_phase("monitoring", "市電正常，節點維持開機")
            else:
                self._set_phase("nodes_off", "節點已關機，市電仍中斷，等待市電恢復")

            expected = data["AgentPowerState"]
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            if self.settings.simulate:
                pass  # 模擬模式輪詢很頻繁，不在終端機輸出狀態行
            elif expected:
                print(f"{timestamp} 目前節點皆為開機狀態")
            else:
                print(f"{timestamp} 目前節點皆為關機狀態，正在持續檢測UPS狀態，若上電則開機節點")
            self._show_console(snapshot, expected)
            return action

    def _show_console(self, snapshot, expected):
        if self.console_view is not None and self.settings.console_table:
            self.console_view.show_status(snapshot, expected, self.state.get("agents"))

    # ------------------------------------------------------------------ 手動操作（Web）
    def agent_config(self, index):
        configs, error = self.drivers.agent_configs()
        if error or not 1 <= index <= len(configs):
            raise KeyError(f"找不到 Agent {index}")
        return configs[index - 1]

    def agent_action(self, index, action):
        agent = self.agent_config(index)
        started = time.monotonic()
        if action == "status":
            result = self.drivers.agent_status(agent, index)
            ok, detail = result["online"], (result["error"] or f"上線，hostname={result['hostname']}")
        elif action == "verify":
            ok, detail = self.drivers.agent_verify(agent)
        elif action == "wol":
            mac = agent.get("mac", "")
            if not self.drivers.valid_mac(mac):
                ok, detail = False, f"MAC 格式不正確: {mac!r}"
            else:
                ok = self.drivers.wol(mac)
                detail = f"已送出 WOL 封包到 {mac}" if ok else "WOL 封包送出失敗"
        else:
            raise ValueError(f"未知的操作: {action}")
        elapsed = round((time.monotonic() - started) * 1000)
        name = agent.get("name", f"Agent {index}")
        labels = {"status": "連線測試", "verify": "簽章驗證", "wol": "Wake-on-LAN"}
        self.log(f"{'✅' if ok else '❌'} [手動] {name} {labels[action]}：{detail}", source="web")
        threading.Thread(target=self.monitor.refresh_status, daemon=True).start()
        return {"ok": ok, "detail": detail, "elapsed_ms": elapsed}
