"""停電演練（乾跑）：照著真正的關機與復電流程走一遍，讀取類操作實際執行，
會動到設備的操作（stop 訊號、節點關機、WOL）只驗證、不送出。

runner 是 DiagnosticsRunner，用 runner.check(id, 分組, 名稱) 建立一列結果。
"""
from Core.controller import decide
from Core.drivers import DriverError


def run_drill(runner):
    drill_trigger(runner)
    servers = drill_list_servers(runner)
    drill_stop_servers(runner, servers)
    drill_server_states(runner, servers)
    agents = drill_shutdown_agents(runner)
    drill_save_state(runner)
    drill_wake(runner, agents)


def _fake_ups(power, battery, status):
    return {"ok": True, "power": power, "battery": battery, "status": status, "error": ""}


def drill_trigger(runner):
    threshold = runner.settings.shutdown_battery_threshold
    ctx = runner.check("drill.trigger", "1. 停電判斷", "模擬：電池供電且電量達門檻")
    action = decide(_fake_ups(False, threshold, "OB DISCHRG"), True, threshold)
    ctx.finish("pass" if action == "shutdown" else "fail",
               f"輸入 OB / {threshold}% / 預期開機 → 判斷結果「{action}」", dry_run=True)

    above = min(threshold + 1, 100)
    ctx = runner.check("drill.trigger_high", "1. 停電判斷", "模擬：電池供電但電量高於門檻")
    action = decide(_fake_ups(False, above, "OB DISCHRG"), True, threshold)
    ctx.finish("pass" if action == "hold_on" else "fail",
               f"輸入 OB / {above}% → 判斷結果「{action}」（不應關機）", dry_run=True)


def drill_list_servers(runner):
    ctx = runner.check("drill.list_servers", "2. 關閉面板伺服器", "取得伺服器清單（實際讀取）")
    if not runner.drivers.ptero_configured():
        ctx.finish("fail", "Pterodactyl 未設定：實際停電時會跳過節點關機流程")
        return []
    try:
        servers = runner.drivers.ptero_list_servers()
    except DriverError as e:
        ctx.finish("fail", f"讀取失敗：{e}（實際停電時會跳過節點關機流程）")
        return []
    if servers:
        ctx.finish("pass", f"取得 {len(servers)} 台伺服器")
    else:
        ctx.finish("fail", "清單為空：實際停電時會跳過節點關機流程")
    return servers


def drill_stop_servers(runner, servers):
    ctx = runner.check("drill.stop_servers", "2. 關閉面板伺服器", "送出 stop 訊號")
    if not servers:
        return ctx.finish("skip", "沒有伺服器", dry_run=True)
    names = "、".join(server["name"] or server["identifier"] for server in servers[:10])
    ctx.finish("pass", f"[乾跑] 將對 {len(servers)} 台伺服器送出 stop：{names}", dry_run=True)


def drill_server_states(runner, servers):
    ctx = runner.check("drill.server_state", "2. 關閉面板伺服器", "讀取伺服器狀態（實際讀取）")
    if not servers:
        return ctx.finish("skip", "沒有伺服器")
    failed = []
    for server in servers:
        try:
            runner.drivers.ptero_server_resources(server["identifier"])
        except DriverError:
            failed.append(server["identifier"])
    if failed:
        ctx.finish("fail", f"{len(failed)} 台無法讀取狀態，實際停電時會一直等到逾時：{', '.join(failed)}")
    else:
        limit = runner.settings.server_stop_max_attempts * runner.settings.server_stop_check_interval
        ctx.finish("pass", f"全部可讀取；實際流程最多等待 {limit:.0f} 秒讓伺服器關機")


def drill_shutdown_agents(runner):
    """以 /verify 代替 /shutdown 對每台節點送出簽章請求，回傳節點設定清單。"""
    agents, error = runner.drivers.agent_configs()
    if error:
        runner.check("drill.agents", "3. 關閉節點", "讀取 AgentInfo").finish("fail", error)
    for index, agent in enumerate(agents, start=1):
        ctx = runner.check(f"drill.agent.{index}", "3. 關閉節點", f"{agent.get('name', f'Agent {index}')} 關機請求")
        ok, detail = runner.drivers.agent_verify(agent)
        if ok:
            ctx.finish("pass", "[乾跑] 以 /verify 送出簽章請求，Agent 驗證通過；實際停電時會改送 /shutdown", dry_run=True)
        else:
            ctx.finish("warn" if "不支援" in detail else "fail", f"[乾跑] {detail}", dry_run=True)
    return agents


def drill_save_state(runner):
    ctx = runner.check("drill.save_off", "3. 關閉節點", "更新 powerState 為關機")
    try:
        runner.power_store.read()
    except (OSError, ValueError) as e:
        return ctx.finish("fail", f"讀取失敗：{e}")
    if runner.power_store.writable():
        ctx.finish("pass", "[乾跑] powerState 可讀寫（未變更內容）", dry_run=True)
    else:
        ctx.finish("fail", "powerState 沒有寫入權限")


def drill_wake(runner, agents):
    threshold = runner.settings.shutdown_battery_threshold
    ctx = runner.check("drill.wake_trigger", "4. 復電開機", "模擬：節點關機後市電恢復")
    action = decide(_fake_ups(True, threshold, "OL CHRG"), False, threshold)
    ctx.finish("pass" if action == "wake" else "fail", f"判斷結果「{action}」", dry_run=True)

    for index, agent in enumerate(agents, start=1):
        ctx = runner.check(f"drill.wol.{index}", "4. 復電開機", f"{agent.get('name', f'Agent {index}')} Wake-on-LAN")
        mac = agent.get("mac", "")
        if runner.drivers.valid_mac(mac):
            ctx.finish("pass", f"[乾跑] 將送出 {runner.settings.wol_attempts} 輪 WOL 到 {mac}（未實際送出）", dry_run=True)
        else:
            ctx.finish("fail", f"MAC 格式不正確：{mac!r}")
