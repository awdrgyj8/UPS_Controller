"""控制服務：原本 main.py 的控制迴圈，改寫成可在背景執行並回報進度的服務。

判斷邏輯與原本相同：
  * 節點為開機狀態，且 UPS 改由電池供電、電量 <= 門檻 → 關閉面板伺服器 → 關閉節點
  * 節點為關機狀態，且市電恢復 → 發送 Wake-on-LAN
"""
import datetime
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from Api import Logger
from Api.NutClient import buildUpsSnapshot, errorSnapshot
from Core.drivers import DriverError
from Core.state import PHASE_LABELS, describe_status_flags

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


def match_agent_node(agent, nodes):
    """把 Agent 對應到 Pterodactyl node：優先使用 AgentInfo 的 ptero_node，其次比對 fqdn / 名稱。"""
    ref = agent.get("ptero_node")
    if ref not in (None, ""):
        for node in nodes:
            if str(node["id"]) == str(ref) or node["name"] == str(ref):
                return node["id"]
    candidates = {agent.get("ip"), agent.get("hostname")} - {None, ""}
    for node in nodes:
        if node.get("fqdn") and node["fqdn"] in candidates:
            return node["id"]
    for node in nodes:
        if node.get("name") and node["name"] == agent.get("name"):
            return node["id"]
    return None


class PowerStateStore:
    """節點預期電源狀態（Data/powerState.json）。path 為 None 時只存在記憶體（模擬模式）。"""

    def __init__(self, path=None):
        self.path = path
        self._memory = {"AgentPowerState": True}
        self._lock = threading.Lock()

    def read(self):
        with self._lock:
            if self.path is None:
                return dict(self._memory)
            with open(self.path, "r") as f:
                return json.load(f)

    def write(self, data):
        with self._lock:
            if self.path is None:
                self._memory = dict(data)
                return
            with open(self.path, "w") as f:
                json.dump(data, f, indent=4)

    def writable(self):
        """只檢查權限，不實際寫入（供自檢使用）。"""
        if self.path is None:
            return True
        return os.access(self.path, os.W_OK) and os.access(os.path.dirname(self.path), os.W_OK)

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
        self._status_lock = threading.Lock()
        self._threads = []
        self._last_power = None
        self._nut_connected = None
        self._ptero_ok = None
        Logger.addHook(self._on_log)

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
        Logger.log(message, level=level, source=source)

    def _set_phase(self, phase, decision):
        self.state.update("controller", phase=phase, phase_label=PHASE_LABELS[phase], decision=decision)

    # ------------------------------------------------------------------ 生命週期
    def start(self, control=True):
        targets = [("ups-monitor", self._ups_monitor_loop), ("status-monitor", self._status_monitor_loop)]
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
        Logger.removeHook(self._on_log)

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

    # ------------------------------------------------------------------ 監控
    def _ups_monitor_loop(self):
        while not self._stop.is_set():
            try:
                self.read_ups()
            except Exception as e:  # 監控執行緒不可中止
                self.log(f"❌ UPS 監控發生未預期錯誤: {e}")
            self._stop.wait(self.settings.monitor_interval)

    def _status_monitor_loop(self):
        interval = min(self.settings.poll_interval, 15)
        while not self._stop.is_set():
            try:
                self.refresh_status()
            except Exception as e:
                self.log(f"❌ 狀態監控發生未預期錯誤: {e}")
            self._stop.wait(interval)

    def read_ups(self):
        started = time.monotonic()
        now = time.time()
        try:
            variables = self.drivers.ups_variables()
            latency = round((time.monotonic() - started) * 1000)
            snapshot = buildUpsSnapshot(variables)
        except (DriverError, ValueError) as e:
            snapshot = errorSnapshot(e)
            self.state.update("ups", ok=False, power=None, battery=None, status="UNKNOWN", status_flags=[],
                              error=str(e), updated_at=now)
            self.state.update("nut", connected=False, error=str(e), latency_ms=None, last_update=now)
            self.state.add_sample({"t": now, "battery": None, "load": None, "runtime": None,
                                   "input_voltage": None, "output_voltage": None, "power": None})
            if self._nut_connected is not False:
                self.log(f"❌ 讀取 UPS 狀態失敗: {e}", source="nut")
            self._nut_connected = False
            return snapshot

        if self._nut_connected is False:
            self.log("✅ NUT 連線恢復", source="nut")
        self._nut_connected = True
        self.state.update("ups", **snapshot, status_flags=describe_status_flags(snapshot["status"]),
                          variables=variables, updated_at=now)
        self.state.update("nut", connected=True, error="", latency_ms=latency, last_update=now)
        self.state.add_sample({
            "t": now,
            "battery": snapshot["battery"],
            "load": snapshot["load"],
            "runtime": snapshot["runtime"],
            "input_voltage": snapshot["input_voltage"],
            "output_voltage": snapshot["output_voltage"],
            "power": snapshot["power"],
        })
        if self._last_power is not None and snapshot["power"] != self._last_power:
            if snapshot["power"]:
                self.log(f"✅ 市電恢復（UPS 狀態 {snapshot['status']}）", source="nut")
            else:
                self.log(f"⚠️ 市電中斷，UPS 改由電池供電（電量 {snapshot['battery']}%）", source="nut")
        self._last_power = snapshot["power"]
        return snapshot

    def refresh_status(self):
        with self._status_lock:
            self.refresh_agents()
            self.refresh_ptero()

    def refresh_agents(self):
        configs, error = self.drivers.agent_configs()
        now = time.time()
        statuses = []
        if configs:
            with ThreadPoolExecutor(max_workers=min(8, len(configs))) as pool:
                statuses = list(pool.map(
                    lambda pair: self.drivers.agent_status(pair[1], pair[0]),
                    enumerate(configs, start=1),
                ))
        previous = {agent["index"]: agent for agent in self.state.get("agents")}
        for index, (config, status) in enumerate(zip(configs, statuses), start=1):
            old = previous.get(index)
            status["index"] = index
            status["ptero_node"] = config.get("ptero_node")
            status["checked_at"] = now
            status["last_seen"] = now if status["online"] else (old or {}).get("last_seen")
            status["mac_valid"] = self.drivers.valid_mac(status["mac"])
            if old is not None and old["online"] != status["online"]:
                if status["online"]:
                    self.log(f"✅ Agent {status['name']} ({status['ip']}) 已上線", source="agent")
                else:
                    self.log(f"⚠️ Agent {status['name']} ({status['ip']}) 離線: {status['error']}", source="agent")

        def apply(data):
            data["agents"] = statuses
            data["agent_config_error"] = error
            data["agents_updated_at"] = now
            self._link_topology(data)

        self.state.mutate(apply)
        return statuses

    def refresh_ptero(self):
        now = time.time()
        if not self.drivers.ptero_configured():
            self.state.update("ptero", configured=False, ok=None, servers=[], nodes=[], updated_at=now,
                              error="PteroApi_Url / PteroApi_AppKey / PteroApi_ClientKey 未設定")
            return
        try:
            servers = self.drivers.ptero_list_servers()
        except DriverError as e:
            self.state.update("ptero", configured=True, ok=False, error=str(e), updated_at=now)
            if self._ptero_ok is not False:
                self.log(f"❌ Pterodactyl 面板讀取失敗: {e}", source="ptero")
            self._ptero_ok = False
            return
        try:
            nodes = self.drivers.ptero_list_nodes()
        except DriverError:
            nodes = []

        def load_resources(server):
            try:
                server.update(self.drivers.ptero_server_resources(server["identifier"]))
                server["error"] = ""
            except DriverError as e:
                server.update(state="unknown", error=str(e))
            return server

        if servers:
            with ThreadPoolExecutor(max_workers=min(8, len(servers))) as pool:
                servers = list(pool.map(load_resources, servers))
        node_names = {node["id"]: node["name"] for node in nodes}
        for server in servers:
            server["node_name"] = node_names.get(server.get("node_id"), "")
        if self._ptero_ok is False:
            self.log("✅ Pterodactyl 面板連線恢復", source="ptero")
        self._ptero_ok = True

        def apply(data):
            data["ptero"].update(configured=True, ok=True, error="", servers=servers, nodes=nodes, updated_at=now)
            self._link_topology(data)

        self.state.mutate(apply)

    @staticmethod
    def _link_topology(data):
        """把 Agent 與 Pterodactyl node / 伺服器互相對應，供拓撲圖使用。"""
        nodes = data["ptero"].get("nodes") or []
        servers = data["ptero"].get("servers") or []
        node_to_agent = {}
        for agent in data["agents"]:
            node_id = match_agent_node(agent, nodes)
            agent["ptero_node_id"] = node_id
            if node_id is not None:
                node_to_agent[node_id] = agent["index"]
        for agent in data["agents"]:
            agent["servers"] = []
        by_index = {agent["index"]: agent for agent in data["agents"]}
        for server in servers:
            server["agent_index"] = node_to_agent.get(server.get("node_id"))
            if server["agent_index"] is not None:
                by_index[server["agent_index"]]["servers"].append(server["identifier"])

    def _update_server_state(self, identifier, server_state):
        def apply(data):
            for server in data["ptero"].get("servers") or []:
                if server["identifier"] == identifier:
                    server["state"] = server_state

        self.state.mutate(apply)

    # ------------------------------------------------------------------ 流程進度
    def _begin_sequence(self, kind, steps, title):
        sequence = {
            "kind": kind,
            "title": title,
            "result": "running",
            "detail": "",
            "started_at": time.time(),
            "finished_at": None,
            "steps": [{"id": step_id, "label": label, "status": "pending", "detail": "", "progress": None}
                      for step_id, label in steps],
        }
        self.state.update("controller", sequence=sequence)

    def _step(self, step_id, status, detail="", progress=None):
        def apply(data):
            sequence = data["controller"]["sequence"]
            for step in sequence["steps"]:
                if step["id"] == step_id:
                    step.update(status=status, detail=detail, progress=progress)

        self.state.mutate(apply)

    def _end_sequence(self, result, detail):
        def apply(data):
            sequence = data["controller"]["sequence"]
            sequence.update(result=result, detail=detail, finished_at=time.time())
            for step in sequence["steps"]:
                if step["status"] == "pending":
                    step["status"] = "skipped"
            data["controller"]["last_sequence"] = dict(sequence)

        self.state.mutate(apply)

    # ------------------------------------------------------------------ 控制
    def _control_loop(self):
        while not self._stop.is_set():
            try:
                if self.paused:
                    self.read_ups()
                    self._set_phase("paused", "自動控制已暫停：僅監控，不會執行關機或喚醒")
                else:
                    self.run_cycle()
            except Exception as e:  # 控制迴圈不可中止
                self.log(f"❌ 控制流程發生未預期錯誤: {e}")
            self.state.update("controller", next_cycle_at=time.time() + self.settings.poll_interval)
            self._wake.wait(self.settings.poll_interval)
            self._wake.clear()

    def run_cycle(self):
        with self._cycle_lock:
            data = self.power_store.read()
            expected = data["AgentPowerState"]
            controller = self.state.get("controller")
            self.state.update("controller", expected_power_state=expected, last_cycle_at=time.time(),
                              cycle_count=controller["cycle_count"] + 1)
            snapshot = self.read_ups()
            threshold = self.settings.shutdown_battery_threshold
            action = decide(snapshot, expected, threshold)

            if action == "skip":
                self.log(f"⚠️ 無法讀取 UPS 狀態，略過本輪控制流程: {snapshot['error']}")
                self._set_phase("nut_error", "無法讀取 UPS 狀態，略過本輪控制流程")
                self._show_console(snapshot, expected)
                return action

            if action == "shutdown":
                if not self._run_shutdown(data, snapshot):
                    return action
                self._set_phase("nodes_off", "關機程序完成，節點已關機，等待市電恢復")
            elif action == "wake":
                if self._run_wake(data, snapshot):
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

    def _run_shutdown(self, data, snapshot):
        threshold = self.settings.shutdown_battery_threshold
        self._begin_sequence("shutdown", SHUTDOWN_STEPS, "停電關機程序")
        self._set_phase("shutdown", f"電池供電且電量 {snapshot['battery']}% ≤ 門檻 {threshold}%，執行關機程序")
        self.log("正在執行關機程序", level="warning")
        self._step("trigger", "done", f"電池供電（{snapshot['status']}），電量 {snapshot['battery']}% ≤ {threshold}%")

        # 取得 Pterodactyl 所有伺服器 UUID
        self._step("list_servers", "running")
        try:
            identifiers = [server["identifier"] for server in self.drivers.ptero_list_servers()]
        except DriverError as e:
            self.log(f"Request failed: {e}", level="error", source="ptero")
            identifiers = []
        if len(identifiers) == 0:
            message = "未取得任何 Pterodactyl 伺服器 UUID，跳過節點關機流程"
            self.log(f"⚠️ {message}")
            self._step("list_servers", "failed", "未取得任何伺服器 UUID")
            self._end_sequence("aborted", message)
            return False
        self._step("list_servers", "done", f"共 {len(identifiers)} 台伺服器")

        self._step("stop_servers", "running")
        sent = sum(1 for identifier in identifiers if self.drivers.ptero_send_power(identifier, "stop"))
        self._step("stop_servers", "done" if sent == len(identifiers) else "warning",
                   f"已送出 {sent}/{len(identifiers)} 個停止訊號")

        # 檢查 Pterodactyl 所有伺服器是否皆以關閉
        max_attempts = self.settings.server_stop_max_attempts
        all_down = False
        self._step("wait_servers", "running", "檢查伺服器狀態中…", progress=0)
        for attempt in range(1, max_attempts + 1):
            pending = []
            for identifier in identifiers:
                try:
                    current = self.drivers.ptero_server_resources(identifier)["state"]
                except DriverError as e:
                    self.log(f"❌ 取得 {identifier} 電源狀態時發生錯誤: {e}", source="ptero")
                    current = "unknown"
                self._update_server_state(identifier, current)
                if current != "offline":
                    self.log(f"⌛ 正在等待伺服器 {identifier} 關機，目前狀態 {current}", level="info")
                    pending.append(identifier)
            if len(pending) == 0:
                self.log("✅ 面板伺服器皆已關機，開始進入節點關機流程")
                all_down = True
                break
            self._step("wait_servers", "running",
                       f"第 {attempt}/{max_attempts} 次檢查，尚有 {len(pending)} 台未關機：{', '.join(pending)}",
                       progress=attempt / max_attempts)
            # 給予伺服器關機緩衝時間
            if self._stop.wait(self.settings.server_stop_check_interval):
                return False
        if not all_down:
            message = "等待面板伺服器關機逾時，跳過節點關機流程"
            self.log(f"⚠️ {message}")
            self._step("wait_servers", "failed", f"逾時：{max_attempts} 次檢查後仍有伺服器未關機")
            self._end_sequence("aborted", message)
            return False
        self._step("wait_servers", "done", "全部伺服器皆為 offline", progress=1)

        # 節點關機程序
        self._step("shutdown_agents", "running")
        configs, error = self.drivers.agent_configs()
        accepted = not error
        if error:
            self.log(f"❌ {error}", source="agent")
        results = []
        for agent in configs:
            ok, message = self.drivers.agent_shutdown(agent)
            results.append(f"{agent.get('name', agent.get('ip', '?'))}: {'接受' if ok else message}")
            if not ok:
                accepted = False
        if not accepted:
            message = "部分或全部節點未接受關機請求，暫不更新節點關機狀態"
            self.log(f"⚠️ {message}")
            self._step("shutdown_agents", "failed", "；".join(results) or error)
            self._end_sequence("aborted", message)
            return False
        self._step("shutdown_agents", "done", "；".join(results) or "沒有設定任何 Agent")

        # 將目前節點狀態寫到powerState
        data["AgentPowerState"] = False
        self.power_store.write(data)
        self.state.update("controller", expected_power_state=False)
        self._step("save_state", "done", "AgentPowerState = false")
        self._end_sequence("success", "節點關機程序完成")
        return True

    def _run_wake(self, data, snapshot):
        self._begin_sequence("wake", WAKE_STEPS, "復電開機程序")
        self._set_phase("waking", "市電已恢復，發送 Wake-on-LAN 喚醒節點")
        self._step("trigger", "done", f"UPS 狀態 {snapshot['status']}，電量 {snapshot['battery']}%")
        configs, error = self.drivers.agent_configs()
        if error:
            self.log(f"❌ {error}", source="wol")
        for agent in configs:
            if "mac" not in agent:
                self.log(f"❌ AgentInfo 缺少 mac 欄位: {agent}", source="wol")
        macs = [agent["mac"] for agent in configs if "mac" in agent]

        attempts = self.settings.wol_attempts
        packets = 0
        for attempt in range(1, attempts + 1):
            self._step("wol", "running", f"第 {attempt}/{attempts} 輪，已送出 {packets} 個封包",
                       progress=attempt / attempts)
            for mac in macs:
                if self.drivers.wol(mac):
                    packets += 1
            if self._stop.wait(self.settings.wol_interval):
                return False

        if packets > 0:
            self._step("wol", "done", f"共送出 {packets} 個 WOL 封包（{len(macs)} 個 MAC × {attempts} 輪）", progress=1)
            data["AgentPowerState"] = True
            self.power_store.write(data)
            self.state.update("controller", expected_power_state=True)
            self._step("save_state", "done", "AgentPowerState = true")
            self._end_sequence("success", "已送出 Wake-on-LAN，等待節點開機")
            self.log(f"✅ 已送出 {packets} 個 Wake-on-LAN 封包，節點開機中", source="wol")
            return True
        message = "未成功送出 Wake-on-LAN 封包，暫不更新節點開機狀態"
        self.log(f"⚠️ {message}")
        self._step("wol", "failed", "沒有任何封包送出成功")
        self._end_sequence("aborted", message)
        return False

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
        threading.Thread(target=self.refresh_status, daemon=True).start()
        return {"ok": ok, "detail": detail, "elapsed_ms": elapsed}
