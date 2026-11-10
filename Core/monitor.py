"""監控：讀取 UPS、節點與面板的現況並寫進共享狀態，只負責觀察，不做任何控制動作。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError

from Api.event_log import log
from Api.nut_client import build_ups_snapshot, error_snapshot
from Core.drivers import DriverError
from Core.models import AgentState, PteroNode, ServerState
from Core.state import describe_status_flags


def map_nodes_to_agents(agents, nodes, ptero_info):
    """決定每個 Pterodactyl node 跑在哪台 Agent 主機上，回傳 ({node id: agent index}, 設定問題清單)。

    agents、nodes 都是 dict 的清單。先套用 PteroInfo（node 填 id 或名稱，agent 填 AgentInfo 的 name 或 ip）；
    沒寫在 PteroInfo 的 node 再自動比對：node fqdn 等於 Agent 的 ip / hostname，其次名稱相同。
    """
    indexed = [(agent.get("index", position), agent) for position, agent in enumerate(agents, start=1)]
    mapping = {}
    problems = []
    for entry in ptero_info:
        node_ref = str(entry.get("node"))
        agent_ref = str(entry.get("agent"))
        node = next((n for n in nodes if str(n["id"]) == node_ref or n.get("name") == node_ref), None)
        agent_index = next((i for i, a in indexed if a.get("name") == agent_ref or a.get("ip") == agent_ref), None)
        if node is None:
            problems.append(f"找不到 Pterodactyl node「{node_ref}」")
        elif agent_index is None:
            problems.append(f"找不到 Agent「{agent_ref}」（請填 AgentInfo 的 name 或 ip）")
        else:
            mapping[node["id"]] = agent_index
    for node in nodes:
        if node["id"] in mapping:
            continue
        by_fqdn = [i for i, a in indexed if node.get("fqdn") and node["fqdn"] in {a.get("ip"), a.get("hostname")}]
        by_name = [i for i, a in indexed if node.get("name") and node["name"] == a.get("name")]
        if by_fqdn or by_name:
            mapping[node["id"]] = (by_fqdn or by_name)[0]
    return mapping, problems


def link_topology(data, ptero_info):
    """把 Pterodactyl node 與伺服器掛到對應的 Agent 主機下，供拓撲圖使用。data 是 AppState。"""
    agents = [agent.model_dump(include={"index", "name", "ip", "hostname"}) for agent in data.agents]
    nodes = [node.model_dump() for node in data.ptero.nodes]
    mapping, _ = map_nodes_to_agents(agents, nodes, ptero_info)
    by_index = {agent.index: agent for agent in data.agents}
    for agent in data.agents:
        agent.ptero_node_ids = [node_id for node_id, index in mapping.items() if index == agent.index]
        agent.servers = []
    for server in data.ptero.servers:
        server.agent_index = mapping.get(server.node_id)
        if server.agent_index in by_index:
            by_index[server.agent_index].servers.append(server.identifier)


def _first_problem(error):
    problem = error.errors()[0]
    return f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"


class StatusMonitor:
    def __init__(self, drivers, state):
        self.drivers = drivers
        self.state = state
        self._status_lock = threading.Lock()
        self._last_power = None
        self._on_battery_since = None
        self._nut_connected = None
        self._ptero_ok = None

    # ------------------------------------------------------------------ UPS
    def read_ups(self):
        """讀一次 UPS，更新狀態與趨勢資料，回傳控制流程用的快照（見 nut_client.build_ups_snapshot）。"""
        started = time.monotonic()
        now = time.time()
        try:
            variables = self.drivers.ups_variables()
            latency = round((time.monotonic() - started) * 1000)
            snapshot = build_ups_snapshot(variables)
        except (DriverError, ValueError) as e:
            snapshot = error_snapshot(e)
            self.state.update("ups", ok=False, power=None, battery=None, status="UNKNOWN", status_flags=[],
                              error=str(e), updated_at=now)
            self.state.update("nut", connected=False, error=str(e), latency_ms=None, last_update=now)
            self.state.add_sample(t=now)
            if self._nut_connected is not False:
                log(f"❌ 讀取 UPS 狀態失敗: {e}", source="nut")
            self._nut_connected = False
            return snapshot

        if self._nut_connected is False:
            log("✅ NUT 連線恢復", source="nut")
        self._nut_connected = True
        # 記下改由電池供電的起點，介面用來顯示已經停電多久
        if snapshot["power"]:
            self._on_battery_since = None
        elif self._on_battery_since is None:
            self._on_battery_since = now
        self.state.update("ups", **snapshot, status_flags=describe_status_flags(snapshot["status"]),
                          variables=variables, updated_at=now, on_battery_since=self._on_battery_since)
        self.state.update("nut", connected=True, error="", latency_ms=latency, last_update=now)
        self.state.add_sample(
            t=now, battery=snapshot["battery"], load=snapshot["load"], runtime=snapshot["runtime"],
            input_voltage=snapshot["input_voltage"], output_voltage=snapshot["output_voltage"], power=snapshot["power"],
        )
        if self._last_power is not None and snapshot["power"] != self._last_power:
            if snapshot["power"]:
                log(f"✅ 市電恢復（UPS 狀態 {snapshot['status']}）", source="nut")
            else:
                log(f"⚠️ 市電中斷，UPS 改由電池供電（電量 {snapshot['battery']}%）", source="nut")
        self._last_power = snapshot["power"]
        return snapshot

    # ------------------------------------------------------------------ 節點與面板
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
        previous = {agent.index: agent for agent in self.state.get("agents")}
        agents = []
        for index, status in enumerate(statuses, start=1):
            old = previous.get(index)
            agent = self._agent_state(index, status, now, old)
            agents.append(agent)
            if old is not None and old.online != agent.online:
                if agent.online:
                    log(f"✅ Agent {agent.name} ({agent.ip}) 已上線", source="agent")
                else:
                    log(f"⚠️ Agent {agent.name} ({agent.ip}) 離線: {agent.error}", source="agent")

        ptero_info, _ = self.drivers.ptero_info()

        def apply(data):
            data.agents = agents
            data.agent_config_error = error
            data.agents_updated_at = now
            link_topology(data, ptero_info)

        self.state.mutate(apply)
        return agents

    def _agent_state(self, index, status, now, old):
        """把驅動回傳的狀態轉成 AgentState；格式不對時當成離線並把原因寫進 error，不讓整批更新失敗。"""
        mac = status.get("mac", "")
        try:
            return AgentState.model_validate({
                **status,
                "index": index,
                "checked_at": now,
                "last_seen": now if status.get("online") else (old.last_seen if old else None),
                "mac_valid": self.drivers.valid_mac(mac),
            })
        except ValidationError as e:
            return AgentState(index=index, name=str(status.get("name", f"Agent {index}")), ip=str(status.get("ip", "")),
                              mac=str(mac), checked_at=now, last_seen=old.last_seen if old else None,
                              error=f"Agent 回傳的狀態格式不正確（{_first_problem(e)}）")

    def refresh_ptero(self):
        now = time.time()
        if not self.drivers.ptero_configured():
            self.state.update("ptero", configured=False, ok=None, servers=[], nodes=[], updated_at=now,
                              error="PteroApi_Url / PteroApi_AppKey / PteroApi_ClientKey 未設定")
            return
        try:
            listed = self.drivers.ptero_list_servers()
        except DriverError as e:
            self.state.update("ptero", configured=True, ok=False, error=str(e), updated_at=now)
            if self._ptero_ok is not False:
                log(f"❌ Pterodactyl 面板讀取失敗: {e}", source="ptero")
            self._ptero_ok = False
            return
        try:
            nodes = [self._node_state(node) for node in self.drivers.ptero_list_nodes()]
        except DriverError:
            nodes = []
        node_names = {node.id: node.name for node in nodes}

        def load(server):
            try:
                server = {**server, **self.drivers.ptero_server_resources(server["identifier"]), "error": ""}
            except DriverError as e:
                server = {**server, "state": "unknown", "error": str(e)}
            return self._server_state({**server, "node_name": node_names.get(server.get("node_id"), "")})

        servers = []
        if listed:
            with ThreadPoolExecutor(max_workers=min(8, len(listed))) as pool:
                servers = list(pool.map(load, listed))
        if self._ptero_ok is False:
            log("✅ Pterodactyl 面板連線恢復", source="ptero")
        self._ptero_ok = True

        ptero_info, _ = self.drivers.ptero_info()

        def apply(data):
            ptero = data.ptero
            ptero.configured, ptero.ok, ptero.error = True, True, ""
            ptero.servers, ptero.nodes, ptero.updated_at = servers, nodes, now
            link_topology(data, ptero_info)

        self.state.mutate(apply)

    @staticmethod
    def _server_state(server):
        try:
            return ServerState.model_validate(server)
        except ValidationError as e:
            return ServerState(identifier=str(server.get("identifier", "?")), name=str(server.get("name", "")),
                               node_id=server.get("node_id"), error=f"面板回傳的資料格式不正確（{_first_problem(e)}）")

    @staticmethod
    def _node_state(node):
        try:
            return PteroNode.model_validate(node)
        except ValidationError:
            return PteroNode(id=node.get("id"), name=str(node.get("name", "")))

    def set_server_state(self, identifier, server_state):
        """關機流程等待伺服器停止時，把最新狀態同步到介面。"""
        def apply(data):
            for server in data.ptero.servers:
                if server.identifier == identifier:
                    server.state = str(server_state)

        self.state.mutate(apply)
