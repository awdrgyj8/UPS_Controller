"""系統自檢：逐項檢查設定、UPS、面板、每台節點與控制邏輯，只讀取與驗證，不影響任何設備。

每個函式負責一組檢查；runner 是 DiagnosticsRunner，用 runner.check(id, 分組, 名稱) 建立一列結果。
"""
import time

from Api.nut_client import build_ups_snapshot
from Core.controller import decide
from Core.drivers import DriverError
from Core.monitor import map_nodes_to_agents

REQUIRED_UPS_VARS = ["ups.status", "battery.charge"]
RECOMMENDED_UPS_VARS = ["battery.runtime", "ups.load", "input.voltage", "output.voltage"]


def run_selftest(runner):
    agents = check_agent_config(runner)
    check_nut_config(runner)
    check_ptero_config(runner)
    check_ptero_info(runner, agents)
    check_threshold(runner)
    check_signing_key(runner)
    check_power_state_file(runner)

    variables = read_ups(runner)
    check_ups_variables(runner, variables)
    check_ups_status(runner, variables)
    check_runtime_margin(runner, variables)

    check_ptero(runner)
    for index, agent in enumerate(agents, start=1):
        check_agent(runner, index, agent)

    check_current_decision(runner, variables)
    check_expected_vs_actual(runner, len(agents))


# ---------------------------------------------------------------------- 設定
def check_agent_config(runner):
    """檢查 AgentInfo，回傳節點設定清單（有問題時回傳空清單，後面的節點檢查就不會跑）。"""
    ctx = runner.check("config.agents", "設定", "AgentInfo 設定")
    agents, error = runner.drivers.agent_configs()
    if error:
        ctx.finish("fail", error)
        return []
    if not agents:
        ctx.finish("warn", "AgentInfo 是空陣列，停電時不會關閉任何節點")
        return []
    problems = []
    seen = set()
    for index, agent in enumerate(agents, start=1):
        name = agent.get("name", f"Agent {index}")
        for field in ("ip", "port", "mac"):
            if field not in agent or agent[field] in ("", None):
                problems.append(f"{name} 缺少 {field}")
        key = (agent.get("ip"), agent.get("port"))
        if key in seen:
            problems.append(f"{name} 的 ip:port 重複")
        seen.add(key)
    if problems:
        ctx.finish("fail", "；".join(problems))
    else:
        ctx.finish("pass", f"共 {len(agents)} 個 Agent，必要欄位齊全")
    return agents


def check_nut_config(runner):
    ctx = runner.check("config.nut", "設定", "NUT 設定")
    target = runner.drivers.nut_target()
    missing = [name for name, value in (("NUT_ServerIP", target["host"]), ("NUT_ServerPort", target["port"]),
                                        ("NUT_UPS_NAME", target["ups_name"])) if not value]
    if missing:
        ctx.finish("fail", f"缺少 {', '.join(missing)}")
    else:
        ctx.finish("pass", f"{target['host']}:{target['port']} ({target['ups_name']})")


def check_ptero_config(runner):
    ctx = runner.check("config.ptero", "設定", "Pterodactyl 設定")
    if runner.drivers.ptero_configured():
        ctx.finish("pass", runner.drivers.ptero_url())
    else:
        ctx.finish("fail", "PteroApi_Url / AppKey / ClientKey 未設定：停電時會因取不到伺服器清單而跳過節點關機")


def check_ptero_info(runner, agents):
    ctx = runner.check("config.ptero_info", "設定", "PteroInfo（Pterodactyl node 對應主機）")
    ptero_info, error = runner.drivers.ptero_info()
    problems = [error] if error else []
    names = {str(agent.get(key)) for agent in agents for key in ("name", "ip") if agent.get(key)}
    problems += [f"agent「{entry['agent']}」不在 AgentInfo 裡" for entry in ptero_info if str(entry["agent"]) not in names]
    legacy = [agent.get("name", agent.get("ip", "?")) for agent in agents if "ptero_node" in agent]
    if problems:
        ctx.finish("fail", "；".join(problems))
    elif legacy:
        ctx.finish("warn", f"AgentInfo 的 ptero_node 已不再使用（{'、'.join(legacy)}），請改寫到 PteroInfo")
    elif ptero_info:
        ctx.finish("pass", "、".join(f"node {entry['node']} → {entry['agent']}" for entry in ptero_info))
    else:
        ctx.finish("skip", "未設定，改用自動比對（node FQDN 等於 Agent IP / hostname，或名稱相同）")


def check_threshold(runner):
    ctx = runner.check("config.threshold", "設定", "關機電量門檻")
    threshold = runner.settings.shutdown_battery_threshold
    if 10 <= threshold <= 95:
        ctx.finish("pass", f"電池供電且電量 ≤ {threshold}% 時啟動關機程序")
    else:
        ctx.finish("warn", f"門檻 {threshold}% 不在建議範圍 10–95% 內")


def check_signing_key(runner):
    ctx = runner.check("key.private", "設定", "簽章私鑰")
    ok, detail = runner.drivers.signing_key_check()
    ctx.finish("pass" if ok else "fail", detail)


def check_power_state_file(runner):
    ctx = runner.check("state.power_file", "設定", "電源狀態檔讀寫")
    try:
        state = str(runner.power_store.read()["AgentPowerState"]).lower()
        if runner.power_store.writable():
            ctx.finish("pass", f"AgentPowerState = {state}（可讀寫）")
        else:
            ctx.finish("fail", f"AgentPowerState = {state}，但檔案沒有寫入權限：關機/喚醒後無法更新狀態")
    except (OSError, ValueError, KeyError) as e:
        ctx.finish("fail", f"讀取失敗：{e}")


# ---------------------------------------------------------------------- UPS
def read_ups(runner):
    """實際連線讀一次 UPS，回傳全部變數；連不上時回傳 None，後面的 UPS 檢查會略過。"""
    ctx = runner.check("nut.connect", "UPS / NUT", "NUT Server 連線")
    target = runner.drivers.nut_target()
    where = f"{target['host']}:{target['port']} / UPS 名稱 {target['ups_name']}"
    started = time.monotonic()
    try:
        variables = runner.drivers.ups_variables()
    except DriverError as e:
        ctx.finish("fail", f"{where} 連線失敗：{e}")
        return None
    latency = round((time.monotonic() - started) * 1000)
    ctx.finish("pass", f"{where}，讀取 {len(variables)} 個變數，耗時 {latency} ms")
    return variables


def check_ups_variables(runner, variables):
    ctx = runner.check("nut.variables", "UPS / NUT", "UPS 必要數據")
    if variables is None:
        return ctx.finish("skip", "NUT 無法連線")
    missing_required = [name for name in REQUIRED_UPS_VARS if name not in variables]
    missing_recommended = [name for name in RECOMMENDED_UPS_VARS if name not in variables]
    if missing_required:
        ctx.finish("fail", f"缺少必要變數 {', '.join(missing_required)}，控制流程無法判斷")
    elif missing_recommended:
        ctx.finish("warn", f"缺少建議變數 {', '.join(missing_recommended)}（介面部分數據無法顯示）")
    else:
        ctx.finish("pass", "ups.status、battery.charge、battery.runtime、ups.load、輸入/輸出電壓皆可讀取")


def check_ups_status(runner, variables):
    ctx = runner.check("nut.status", "UPS / NUT", "UPS 狀態判讀")
    if variables is None:
        return ctx.finish("skip", "NUT 無法連線")
    status = variables.get("ups.status", "UNKNOWN")
    tokens = variables.get("ups.status", "").split()
    if "LB" in tokens or "FSD" in tokens or "OFF" in tokens:
        ctx.finish("fail", f"UPS 狀態 {status}：電量低或已強制關機")
    elif "OB" in tokens:
        ctx.finish("warn", f"UPS 狀態 {status}：目前為電池供電")
    elif any(token in tokens for token in ("RB", "OVER", "BYPASS", "ALARM")):
        ctx.finish("warn", f"UPS 狀態 {status}：請檢查 UPS（需換電池 / 過載 / 旁路 / 警報）")
    else:
        ctx.finish("pass", f"UPS 狀態 {status}")


def check_runtime_margin(runner, variables):
    """電量降到門檻時剩下的續航，夠不夠跑完整個關機程序。"""
    ctx = runner.check("nut.runtime", "UPS / NUT", "關機時間餘裕評估")
    if variables is None:
        return ctx.finish("skip", "NUT 無法連線")
    settings = runner.settings
    threshold = settings.shutdown_battery_threshold
    try:
        battery = float(variables["battery.charge"])
        runtime = float(variables["battery.runtime"])
    except (KeyError, ValueError):
        return ctx.finish("skip", "缺少 battery.charge / battery.runtime")
    at_threshold = runtime * threshold / battery if battery > 0 else 0
    worst = settings.server_stop_max_attempts * settings.server_stop_check_interval + settings.poll_interval + 60
    detail = (f"以目前負載估算，電量降到 {threshold}% 時約剩 {at_threshold / 60:.1f} 分鐘續航；"
              f"關機程序最長約需 {worst / 60:.1f} 分鐘（含輪詢間隔與節點關機緩衝）")
    ctx.finish("pass" if at_threshold >= worst * 1.5 else "warn", detail)


# ---------------------------------------------------------------------- Pterodactyl
def check_ptero(runner):
    drivers = runner.drivers
    ctx = runner.check("ptero.application", "Pterodactyl", "Application API（伺服器清單）")
    if not drivers.ptero_configured():
        return ctx.finish("fail", "未設定")
    try:
        servers = drivers.ptero_list_servers()
    except DriverError as e:
        return ctx.finish("fail", f"讀取失敗：{e}")
    if servers:
        ctx.finish("pass", f"共 {len(servers)} 台伺服器")
    else:
        ctx.finish("warn", "面板沒有任何伺服器：依現行邏輯，停電時會跳過節點關機流程")

    ctx = runner.check("ptero.nodes", "Pterodactyl", "Application API（節點清單）")
    try:
        nodes = drivers.ptero_list_nodes()
        ctx.finish("pass", f"共 {len(nodes)} 個 node：" + "、".join(node["name"] for node in nodes))
    except DriverError as e:
        nodes = []
        ctx.finish("warn", f"讀取失敗（拓撲圖無法對應節點）：{e}")

    _check_server_states(runner, servers)
    _check_node_mapping(runner, servers, nodes)


def _check_server_states(runner, servers):
    ctx = runner.check("ptero.client", "Pterodactyl", "Client API（伺服器狀態）")
    if not servers:
        return ctx.finish("skip", "沒有伺服器")
    states = {}
    failed = []
    for server in servers:
        try:
            state = runner.drivers.ptero_server_resources(server["identifier"])["state"]
            states[state] = states.get(state, 0) + 1
        except DriverError:
            failed.append(server["identifier"])
    if failed:
        ctx.finish("fail", f"{len(failed)} 台讀取失敗（Client Key 權限不足？）：{', '.join(failed)}")
    else:
        ctx.finish("pass", "、".join(f"{key} {value} 台" for key, value in states.items()))


def _check_node_mapping(runner, servers, nodes):
    ctx = runner.check("ptero.mapping", "Pterodactyl", "伺服器與 Agent 對應")
    if not nodes:
        return ctx.finish("skip", "沒有 node 資料")
    agents = [agent.model_dump(include={"index", "name", "ip", "hostname"}) for agent in runner.state.get("agents")]
    ptero_info, _ = runner.drivers.ptero_info()
    mapping, problems = map_nodes_to_agents(agents, nodes, ptero_info)
    agent_names = {agent["index"]: agent["name"] for agent in agents}
    unmapped_nodes = [node for node in nodes if node["id"] not in mapping]
    if not problems and not unmapped_nodes:
        return ctx.finish("pass", "、".join(f"#{node['id']} {node['name']} → {agent_names.get(mapping[node['id']], '?')}"
                                           for node in nodes))
    parts = list(problems)
    if unmapped_nodes:
        unmapped_servers = [server for server in servers if server.get("node_id") not in mapping]
        parts.append("未對應的 node：" + "、".join(f"#{node['id']} {node['name']}" for node in unmapped_nodes)
                     + f"（{len(unmapped_servers)} 台伺服器）。請在 PteroInfo 加上，例如 "
                     + f'{{"node":{unmapped_nodes[0]["id"]},"agent":"主機名稱"}}')
    ctx.finish("warn", "；".join(parts))


# ---------------------------------------------------------------------- 節點
def check_agent(runner, index, agent):
    drivers = runner.drivers
    group = f"節點 {agent.get('name', f'Agent {index}')}"

    ctx = runner.check(f"agent.{index}.status", group, "連線 (/status)")
    status = drivers.agent_status(agent, index)
    if status["online"]:
        extra = "" if "verify" in status.get("capabilities", []) else "；Agent 版本較舊，不支援 /verify"
        ctx.finish("warn" if extra else "pass", f"hostname={status['hostname']}，延遲 {status['latency_ms']} ms{extra}")
    else:
        ctx.finish("fail", status["error"] or "離線")

    ctx = runner.check(f"agent.{index}.verify", group, "簽章驗證 (/verify)")
    if not status["online"]:
        ctx.finish("skip", "Agent 離線")
    else:
        ok, detail = drivers.agent_verify(agent)
        if ok:
            ctx.finish("pass", "Agent 接受 Controller 簽章（時間戳與 nonce 檢查通過）")
        else:
            ctx.finish("warn" if "不支援" in detail else "fail", detail)

    ctx = runner.check(f"agent.{index}.wol", group, "Wake-on-LAN 設定")
    mac = agent.get("mac", "")
    if drivers.valid_mac(mac):
        ctx.finish("pass", f"MAC {mac} 格式正確（未送出封包）")
    else:
        ctx.finish("fail", f"MAC 格式不正確：{mac!r}")


# ---------------------------------------------------------------------- 控制邏輯
def check_current_decision(runner, variables):
    """用剛讀到的 UPS 數據跑一次控制器的判斷，說明下一輪會做什麼。"""
    ctx = runner.check("logic.current", "控制邏輯", "目前判斷結果")
    if variables is None:
        return ctx.finish("warn", "NUT 無法連線：控制器會略過每一輪控制流程")
    snapshot = build_ups_snapshot(variables)
    expected = runner.power_store.expected()
    action = decide(snapshot, expected, runner.settings.shutdown_battery_threshold)
    status, detail = {
        "shutdown": ("warn", "條件成立：下一輪將執行關機程序"),
        "hold_on": ("pass", "維持開機（未達關機條件）"),
        "wake": ("warn", "節點預期為關機但市電正常：下一輪將發送 WOL"),
        "hold_off": ("pass", "節點關機中，等待市電恢復"),
    }[action]
    ctx.finish(status, f"預期電源={'開機' if expected else '關機'}，"
                       f"市電={'正常' if snapshot['power'] else '中斷'}，電量 {snapshot['battery']}% → {detail}")


def check_expected_vs_actual(runner, total):
    ctx = runner.check("logic.consistency", "控制邏輯", "預期狀態與實際一致性")
    expected = runner.power_store.expected()
    online = sum(1 for agent in runner.state.get("agents") if agent.online)
    if total == 0:
        ctx.finish("skip", "沒有 Agent")
    elif expected and online < total:
        ctx.finish("warn", f"預期節點為開機，但只有 {online}/{total} 個 Agent 在線")
    elif not expected and online > 0:
        ctx.finish("warn", f"預期節點為關機，但有 {online} 個 Agent 在線")
    else:
        ctx.finish("pass", f"預期={'開機' if expected else '關機'}，在線 {online}/{total}")
