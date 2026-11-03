"""模擬環境：模擬 UPS / NUT、Pterodactyl 面板、各節點 Agent 與 Wake-on-LAN。

控制器在模擬模式下透過 SimDrivers 存取這個環境，執行的仍是與實機相同的控制流程，
因此可以完整測試「停電 → 關閉伺服器 → 關閉節點 → 復電 → WOL 開機」的整個過程，
而且不會對任何真實設備送出指令。
"""
import json
import os
import random
import re
import threading
import time
import uuid

from Core.drivers import DriverError

# 故障注入選項
AGENT_FAULTS = {
    "none": "正常",
    "offline": "網路中斷（無法連線）",
    "reject": "拒絕簽章（invalid signature）",
    "slow": "回應緩慢（高延遲）",
    "no_wol": "不支援 WOL（無法喚醒）",
}

_DEFAULT_AGENTS = [
    {"name": "Node-1", "ip": "192.168.50.101", "mac": "AA:BB:CC:00:00:01", "port": 5858},
    {"name": "Node-2", "ip": "192.168.50.102", "mac": "AA:BB:CC:00:00:02", "port": 5858},
    {"name": "Node-3", "ip": "192.168.50.103", "mac": "AA:BB:CC:00:00:03", "port": 5858},
]

_GAME_SERVERS = [
    "Minecraft 生存服", "Minecraft 創造服", "Palworld", "Terraria", "Valheim",
    "ARK 方舟", "Rust", "Satisfactory", "7 Days to Die", "Project Zomboid",
]

# 電池模型：滿電在 30% 負載下可撐 1500 秒（模擬時間），充滿需要 1800 秒
_RUNTIME_AT_30_LOAD = 1500.0
_FULL_CHARGE_SECONDS = 1800.0
_AGENT_BOOT_SECONDS = 6.0
_AGENT_SHUTDOWN_SECONDS = 2.0


def _load_agent_templates():
    raw = os.getenv("AgentInfo")
    if raw:
        try:
            agents = json.loads(raw)
            if isinstance(agents, list) and agents:
                return agents
        except json.JSONDecodeError:
            pass
    return _DEFAULT_AGENTS


class SimAgent:
    def __init__(self, index, template):
        self.index = index
        self.name = template.get("name", f"Agent {index}")
        self.ip = template.get("ip", f"192.168.50.{100 + index}")
        self.port = template.get("port", 5858)
        self.mac = template.get("mac", f"AA:BB:CC:00:00:{index:02X}")
        self.hostname = re.sub(r"[^a-z0-9-]", "-", self.name.lower())
        self.cpu_count = random.choice([4, 8, 12, 16])
        self.mem_total = random.choice([16, 32, 64]) * 1024 ** 3
        self.disk_total = random.choice([512, 1024, 2048]) * 1024 ** 3
        self.disk_used_ratio = random.uniform(0.25, 0.7)
        self.reset()

    def reset(self):
        self.power = "on"            # on / off / booting / shutting_down
        self.fault = "none"
        self.timer = 0.0
        self.booted_at = time.time() - random.randint(3600, 86400 * 5)
        self.agent_started_at = self.booted_at + 15
        self.shutdown_requests = 0
        self.wol_received = 0

    @property
    def reachable(self):
        return self.power == "on" and self.fault != "offline"

    def to_dict(self):
        return {
            "index": self.index,
            "name": self.name,
            "ip": self.ip,
            "mac": self.mac,
            "power": self.power,
            "fault": self.fault,
            "timer": round(max(self.timer, 0), 1),
            "shutdown_requests": self.shutdown_requests,
            "wol_received": self.wol_received,
        }


class SimServer:
    def __init__(self, agent_index, name, stays_starting=False):
        # stays_starting：模擬面板偵測不到「啟動完成」訊息的程式（例如 Discord Bot），狀態會一直停在 starting
        self.stays_starting = stays_starting
        self.uuid = str(uuid.uuid4())
        self.identifier = self.uuid[:8]
        self.name = name
        self.agent_index = agent_index
        self.memory_limit = random.choice([2, 4, 6, 8]) * 1024 ** 3
        self.reset()

    def reset(self):
        self.state = "starting" if self.stays_starting else "running"   # running / stopping / offline / starting
        self.stuck = False
        self.timer = 0.0
        self.started_at = time.time() - (random.randint(7200, 86400 * 60) if self.stays_starting
                                         else random.randint(600, 86400))

    def to_dict(self):
        return {
            "identifier": self.identifier,
            "name": self.name,
            "agent_index": self.agent_index,
            "state": self.state,
            "stuck": self.stuck,
        }


class SimEnvironment:
    TICK_SECONDS = 0.25

    def __init__(self, on_change=None, log=None):
        self._lock = threading.RLock()
        self._on_change = on_change
        self._log = log or (lambda level, message: None)
        templates = _load_agent_templates()
        self.agents = [SimAgent(index, template) for index, template in enumerate(templates, start=1)]
        names = list(_GAME_SERVERS)
        random.shuffle(names)
        self.servers = []
        for agent in self.agents:
            for _ in range(random.choice([2, 3])):
                name = names.pop() if names else f"Server {len(self.servers) + 1}"
                self.servers.append(SimServer(agent.index, name))
        if self.agents:
            self.servers.append(SimServer(self.agents[0].index, "Discord Bot", stays_starting=True))
        self.serial = f"SIM{random.randint(100000, 999999)}"
        self.reset()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sim-tick", daemon=True)

    # ---- 生命週期 ----
    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def reset(self):
        with self._lock:
            self.speed = 10.0
            self.grid_online = True
            self.battery = 100.0
            self.nut_reachable = True
            self.ptero_reachable = True
            self.depleted = False
            self.temperature = 31.0
            self.wol_packets = 0
            self.outage_started_at = None
            for agent in self.agents:
                agent.reset()
            for server in self.servers:
                server.reset()
        self._changed()

    def _changed(self):
        if self._on_change:
            self._on_change(self.to_dict())

    def _run(self):
        last = time.monotonic()
        while not self._stop.wait(self.TICK_SECONDS):
            now = time.monotonic()
            self.tick(now - last)
            last = now

    # ---- 物理模型 ----
    def load_percent(self):
        with self._lock:
            load = 6.0
            for agent in self.agents:
                if agent.power in ("on", "booting", "shutting_down"):
                    load += 10.0
            for server in self.servers:
                if server.state in ("running", "starting", "stopping"):
                    load += 2.5
            return min(load, 98.0)

    def runtime_seconds(self):
        with self._lock:
            load = max(self.load_percent(), 5.0)
            full = _RUNTIME_AT_30_LOAD * (30.0 / load) ** 1.05
            return max(self.battery, 0) / 100.0 * full

    def tick(self, dt):
        with self._lock:
            sim_dt = dt * self.speed
            if self.grid_online:
                self.depleted = False
                if self.battery < 100:
                    self.battery = min(100.0, self.battery + sim_dt * 100.0 / _FULL_CHARGE_SECONDS)
                self.temperature += (31.0 - self.temperature) * 0.01
            elif not self.depleted:
                load = max(self.load_percent(), 5.0)
                full = _RUNTIME_AT_30_LOAD * (30.0 / load) ** 1.05
                self.battery = max(0.0, self.battery - sim_dt * 100.0 / full)
                self.temperature += (36.0 - self.temperature) * 0.01
                if self.battery <= 0:
                    self._deplete()

            for agent in self.agents:
                if agent.power in ("booting", "shutting_down"):
                    agent.timer -= dt
                    if agent.timer <= 0:
                        if agent.power == "booting":
                            agent.power = "on"
                            agent.booted_at = time.time()
                            agent.agent_started_at = time.time()
                            self._log("success", f"[模擬] {agent.name} 開機完成")
                        else:
                            agent.power = "off"
                            self._log("info", f"[模擬] {agent.name} 已關機")
            for server in self.servers:
                host = self.agents[server.agent_index - 1]
                if host.power != "on" and host.power != "shutting_down":
                    server.state = "offline"
                    continue
                if server.state in ("stopping", "starting"):
                    if server.stuck or (server.state == "starting" and server.stays_starting):
                        continue
                    server.timer -= dt
                    if server.timer <= 0:
                        server.state = "offline" if server.state == "stopping" else "running"
                        if server.state == "running":
                            server.started_at = time.time()
        self._changed()

    def _deplete(self):
        self.depleted = True
        self._log("error", "[模擬] UPS 電池耗盡，所有節點斷電！")
        for agent in self.agents:
            agent.power = "off"
            agent.timer = 0
        for server in self.servers:
            server.state = "offline"

    # ---- 測試控制 ----
    def set_grid(self, online):
        with self._lock:
            self.grid_online = bool(online)
            self.outage_started_at = None if online else time.time()
        self._log("warning" if not online else "success", f"[模擬] 市電{'恢復' if online else '中斷'}")
        self._changed()

    def set_battery(self, value):
        with self._lock:
            self.battery = max(0.0, min(100.0, float(value)))
            if self.battery > 0:
                self.depleted = False
        self._changed()

    def set_speed(self, value):
        with self._lock:
            self.speed = max(0.0, min(500.0, float(value)))
        self._changed()

    def set_nut_reachable(self, reachable):
        with self._lock:
            self.nut_reachable = bool(reachable)
        self._log("info", f"[模擬] NUT Server {'恢復連線' if reachable else '中斷連線'}")
        self._changed()

    def set_ptero_reachable(self, reachable):
        with self._lock:
            self.ptero_reachable = bool(reachable)
        self._log("info", f"[模擬] Pterodactyl 面板 {'恢復連線' if reachable else '中斷連線'}")
        self._changed()

    def set_agent_fault(self, index, fault):
        if fault not in AGENT_FAULTS:
            raise ValueError(f"未知的故障類型: {fault}")
        with self._lock:
            agent = self._agent(index)
            agent.fault = fault
        self._log("info", f"[模擬] {agent.name} 故障設定：{AGENT_FAULTS[fault]}")
        self._changed()

    def set_agent_power(self, index, power):
        with self._lock:
            agent = self._agent(index)
            if power == "on" and agent.power != "on":
                agent.power = "booting"
                agent.timer = _AGENT_BOOT_SECONDS
            elif power == "off":
                agent.power = "off"
                agent.timer = 0
        self._changed()

    def set_server_stuck(self, identifier, stuck):
        with self._lock:
            server = self._server(identifier)
            server.stuck = bool(stuck)
        self._log("info", f"[模擬] 伺服器 {server.name} {'設為無法關閉' if stuck else '恢復正常'}")
        self._changed()

    def _agent(self, index):
        for agent in self.agents:
            if agent.index == int(index):
                return agent
        raise KeyError(f"找不到 Agent {index}")

    def _server(self, identifier):
        for server in self.servers:
            if server.identifier == identifier:
                return server
        raise KeyError(f"找不到伺服器 {identifier}")

    def to_dict(self):
        with self._lock:
            return {
                "grid_online": self.grid_online,
                "battery": round(self.battery, 2),
                "speed": self.speed,
                "load": round(self.load_percent(), 1),
                "runtime": round(self.runtime_seconds()),
                "nut_reachable": self.nut_reachable,
                "ptero_reachable": self.ptero_reachable,
                "depleted": self.depleted,
                "wol_packets": self.wol_packets,
                "outage_started_at": self.outage_started_at,
                "agents": [agent.to_dict() for agent in self.agents],
                "servers": [server.to_dict() for server in self.servers],
                "agent_faults": AGENT_FAULTS,
            }

    # ---- NUT 變數 ----
    def nut_variables(self):
        with self._lock:
            if not self.nut_reachable:
                raise DriverError("[模擬] Connection refused (NUT server 無回應)")
            load = self.load_percent()
            battery = max(self.battery, 0)
            if self.depleted:
                status = "OB DISCHRG LB OFF"
            elif self.grid_online:
                status = "OL CHRG" if battery < 99.5 else "OL"
            else:
                status = "OB DISCHRG" + (" LB" if battery <= 20 else "")
            jitter = random.uniform(-1.5, 1.5)
            input_voltage = 220.0 + jitter if self.grid_online else 0.0
            output_voltage = 0.0 if self.depleted else 220.0 + random.uniform(-0.6, 0.6)
            return {
                "battery.charge": f"{int(battery)}",
                "battery.charge.low": "20",
                "battery.charge.warning": "50",
                "battery.runtime": f"{int(self.runtime_seconds())}",
                "battery.runtime.low": "300",
                "battery.type": "PbAc",
                "battery.voltage": f"{20.0 + 7.2 * battery / 100:.1f}",
                "battery.voltage.nominal": "24",
                "battery.mfr.date": "2024/03/18",
                "device.mfr": "SimPower",
                "device.model": "SIM-1500VA",
                "device.serial": self.serial,
                "device.type": "ups",
                "driver.name": "usbhid-ups (simulated)",
                "driver.version": "2.8.2",
                "driver.parameter.pollinterval": "2",
                "driver.parameter.port": "auto",
                "input.voltage": f"{input_voltage:.1f}",
                "input.voltage.nominal": "220",
                "input.frequency": f"{60.0 + random.uniform(-0.05, 0.05):.2f}" if self.grid_online else "0.00",
                "input.transfer.high": "264",
                "input.transfer.low": "170",
                "output.voltage": f"{output_voltage:.1f}",
                "output.frequency": "60.0",
                "output.voltage.nominal": "220",
                "ups.beeper.status": "enabled",
                "ups.delay.shutdown": "20",
                "ups.firmware": "SIM 1.0.4",
                "ups.load": f"{int(load)}",
                "ups.mfr": "SimPower",
                "ups.model": "SIM-1500VA",
                "ups.power.nominal": "1500",
                "ups.realpower": f"{int(900 * load / 100)}",
                "ups.realpower.nominal": "900",
                "ups.serial": self.serial,
                "ups.status": status,
                "ups.temperature": f"{self.temperature:.1f}",
                "ups.test.result": "Done and passed",
                "ups.timer.shutdown": "-1",
            }


class SimDrivers:
    """與 RealDrivers 相同介面的模擬實作。"""
    mode = "simulation"

    def __init__(self, env):
        self.env = env

    # ---- NUT ----
    def nut_target(self):
        return {
            "host": os.getenv("NUT_ServerIP") or "192.168.50.10",
            "port": os.getenv("NUT_ServerPort") or "3493",
            "ups_name": os.getenv("NUT_UPS_NAME") or "ups",
            "auth": False,
        }

    def ups_variables(self):
        time.sleep(random.uniform(0.005, 0.02))
        return self.env.nut_variables()

    # ---- Pterodactyl ----
    def ptero_configured(self):
        return True

    def ptero_url(self):
        return os.getenv("PteroApi_Url") or "https://panel.example.com"

    def ptero_info(self):
        # 模擬的 node 與 Agent 一對一且 fqdn = Agent IP，自動比對即可；不讀取實機的 PteroInfo
        return [], ""

    def _require_panel(self):
        if not self.env.ptero_reachable:
            raise DriverError("[模擬] Pterodactyl 面板無法連線 (502 Bad Gateway)")

    def ptero_list_servers(self):
        self._require_panel()
        with self.env._lock:
            return [{
                "identifier": server.identifier,
                "uuid": server.uuid,
                "name": server.name,
                "node_id": server.agent_index,
                "suspended": False,
            } for server in self.env.servers]

    def ptero_list_nodes(self):
        self._require_panel()
        with self.env._lock:
            return [{
                "id": agent.index,
                "name": agent.name,
                "fqdn": agent.ip,
                "maintenance_mode": False,
            } for agent in self.env.agents]

    def ptero_server_resources(self, identifier):
        self._require_panel()
        with self.env._lock:
            server = self.env._server(identifier)
            running = server.state in ("running", "starting")
            return {
                "state": server.state,
                "cpu_percent": round(random.uniform(5, 60), 1) if running else 0,
                "memory_bytes": int(server.memory_limit * random.uniform(0.3, 0.8)) if running else 0,
                "uptime_ms": int((time.time() - server.started_at) * 1000) if running else 0,
            }

    def ptero_send_power(self, identifier, action):
        if not self.env.ptero_reachable:
            return False
        with self.env._lock:
            server = self.env._server(identifier)
            host = self.env.agents[server.agent_index - 1]
            if action in ("stop", "kill") and server.state in ("running", "starting"):
                server.state = "stopping"
                server.timer = 0.2 if action == "kill" else random.uniform(1.5, 3.5)
            elif action == "start" and server.state == "offline" and host.power == "on":
                server.state = "starting"
                server.timer = random.uniform(2, 4)
                server.started_at = time.time()
        self.env._log("success", f"✅ [模擬] 已對 {identifier} 伺服器發送 '{action}'")
        return True

    # ---- Agents ----
    def agent_configs(self):
        with self.env._lock:
            return [{
                "name": agent.name,
                "ip": agent.ip,
                "port": agent.port,
                "mac": agent.mac,
                "sim_index": agent.index,
            } for agent in self.env.agents], ""

    def _agent_for(self, agent):
        return self.env._agent(agent.get("sim_index", 0))

    def agent_status(self, agent, index):
        sim = self._agent_for(agent)
        status = {
            "name": sim.name, "ip": sim.ip, "port": str(sim.port), "mac": sim.mac,
            "online": False, "hostname": "", "uptime_seconds": None, "latency_ms": None,
            "error": "", "capabilities": [], "system": None,
        }
        if not sim.reachable:
            status["error"] = (f"[模擬] HTTPConnectionPool(host='{sim.ip}', port={sim.port}): "
                               "Max retries exceeded (Connection timed out)")
            return status
        now = time.time()
        latency = random.uniform(900, 1600) if sim.fault == "slow" else random.uniform(1.5, 8)
        mem_available = int(sim.mem_total * random.uniform(0.35, 0.6))
        status.update({
            "online": True,
            "hostname": sim.hostname,
            "uptime_seconds": int(now - sim.agent_started_at),
            "latency_ms": round(latency),
            "capabilities": ["status", "shutdown", "verify"],
            "system": {
                "platform": "Linux-6.8.0-sim-x86_64-with-glibc2.39",
                "python": "3.13.1",
                "cpu_count": sim.cpu_count,
                "uptime_seconds": int(now - sim.booted_at),
                "load_avg": [round(random.uniform(0.2, sim.cpu_count * 0.4), 2) for _ in range(3)],
                "memory": {"total": sim.mem_total, "available": mem_available},
                "disk": {"total": sim.disk_total, "used": int(sim.disk_total * sim.disk_used_ratio),
                         "free": int(sim.disk_total * (1 - sim.disk_used_ratio))},
            },
        })
        return status

    def _signed_request(self, agent):
        sim = self._agent_for(agent)
        if not sim.reachable:
            return sim, False, f"[模擬] 發送到 {sim.ip} 發生錯誤: Connection timed out"
        if sim.fault == "reject":
            return sim, False, "回應錯誤: invalid signature"
        return sim, True, ""

    def agent_shutdown(self, agent):
        sim, ok, message = self._signed_request(agent)
        if not ok:
            self.env._log("error", f"❌ [模擬] 節點 {sim.ip} 關機請求失敗: {message}")
            return False, message
        with self.env._lock:
            sim.shutdown_requests += 1
            sim.power = "shutting_down"
            sim.timer = _AGENT_SHUTDOWN_SECONDS
        self.env._log("success", f"✅ [模擬] 節點 {sim.ip} 已收到 且回應開始執行關機")
        return True, "shutdown accepted"

    def agent_verify(self, agent):
        sim, ok, message = self._signed_request(agent)
        if not ok:
            return False, message
        return True, "signature verified"

    def signing_key_check(self):
        return True, "模擬模式不需要私鑰（不會送出真實簽章請求）"

    # ---- Wake-on-LAN ----
    def wol(self, mac):
        with self.env._lock:
            self.env.wol_packets += 1
            for agent in self.env.agents:
                if agent.mac.lower() != str(mac).lower():
                    continue
                agent.wol_received += 1
                if agent.fault == "no_wol" or self.env.depleted:
                    continue
                if agent.power == "off":
                    agent.power = "booting"
                    agent.timer = _AGENT_BOOT_SECONDS
                    self.env._log("info", f"[模擬] {agent.name} 收到 WOL 封包，開機中")
        return True

    def valid_mac(self, mac):
        from Api.WakeOnLan import isValidMac
        return isValidMac(mac)
