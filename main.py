import Api.PteroAPI as PteroAPI
import Api.NutClient as NutClient
import Api.AgentAPI as AgentAPI
import Api.WakeOnLan as WakeOnLan
import time, json, datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table

BASE_DIR = Path(__file__).resolve().parent
POWER_STATE_PATH = BASE_DIR / "Data" / "powerState.json"
console = Console()

def _format_uptime(uptime_seconds):
    if uptime_seconds is None:
        return "-"
    uptime_seconds = int(uptime_seconds)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"

def showStatus(upsSnapshot, expectedPowerState):
    upsTable = Table(
        title=f"UPS / NUT 狀態 - {datetime.datetime.now().strftime('%H:%M:%S')}",
        show_header=True,
        header_style="bold cyan",
    )
    upsTable.add_column("NUT 連線")
    upsTable.add_column("UPS 狀態")
    upsTable.add_column("市電")
    upsTable.add_column("電量")
    upsTable.add_column("訊息")

    nutConnection = "[green]Connected[/green]" if upsSnapshot["ok"] == True else "[red]Disconnected[/red]"
    if upsSnapshot["power"] is True:
        powerLabel = "[green]Online[/green]"
    elif upsSnapshot["power"] is False:
        powerLabel = "[red]On Battery[/red]"
    else:
        powerLabel = "[yellow]Unknown[/yellow]"
    batteryLabel = "-" if upsSnapshot["battery"] is None else f"{upsSnapshot['battery']}%"
    upsTable.add_row(
        nutConnection,
        upsSnapshot["status"],
        powerLabel,
        batteryLabel,
        upsSnapshot["error"] or "OK",
    )
    console.print(upsTable)

    statuses = AgentAPI.getAgentStatuses()
    table = Table(
        title=f"Agent 狀態 - {datetime.datetime.now().strftime('%H:%M:%S')}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Agent", style="bold")
    table.add_column("IP")
    table.add_column("Port")
    table.add_column("MAC")
    table.add_column("預期")
    table.add_column("連線")
    table.add_column("Hostname")
    table.add_column("Uptime")
    table.add_column("延遲")
    table.add_column("訊息")

    expectedLabel = "開機" if expectedPowerState == True else "關機"
    for status in statuses:
        online = status["online"] == True
        connectionLabel = "[green]Online[/green]" if online else "[red]Offline[/red]"
        latency = "-" if status["latency_ms"] is None else f"{status['latency_ms']} ms"
        message = "OK" if online else status["error"]
        table.add_row(
            status["name"],
            status["ip"],
            status["port"],
            status["mac"],
            expectedLabel,
            connectionLabel,
            status["hostname"] or "-",
            _format_uptime(status["uptime_seconds"]),
            latency,
            message or "-",
        )

    if len(statuses) == 0:
        table.add_row("-", "-", "-", "-", expectedLabel, "[yellow]Unknown[/yellow]", "-", "-", "-", "AgentInfo 未設定或沒有 Agent")

    console.print(table)

if __name__ == "__main__":
    while True:
        # 讀取目前狀態
        with open(POWER_STATE_PATH, "r") as f:
            data = json.load(f)
        upsSnapshot = NutClient.getUpsSnapshot()
        if upsSnapshot["ok"] == False:
            print(f"⚠️ 無法讀取 UPS 狀態，略過本輪控制流程: {upsSnapshot['error']}")
            showStatus(upsSnapshot, data["AgentPowerState"])
            time.sleep(30)
            continue
        # 如果節點都是開機狀態
        if data["AgentPowerState"] == True:
            if upsSnapshot["power"] == False and upsSnapshot["battery"] is not None and upsSnapshot["battery"] <= 50:
                    print("正在執行關機程序")
                    # 取得 Pterodactyl 所有伺服器 UUID
                    allServersUUID = PteroAPI.getAllServerUUID()
                    if len(allServersUUID) == 0:
                        print("⚠️ 未取得任何 Pterodactyl 伺服器 UUID，跳過節點關機流程")
                        time.sleep(30)
                        continue
                    PteroAPI.sendPowerSignal(allServersUUID, "stop")
                    # 檢查 Pterodactyl 所有伺服器是否皆以關閉
                    allServersShutdown = False
                    for attempt in range(20):
                        notHasShutdownServers = []
                        for id in allServersUUID:
                            currentState = PteroAPI.getServerPowerState(id)
                            if currentState != "offline":
                                print(
                                    f"⌛ 正在等待伺服器 {id} 關機，目前狀態 {currentState}"
                                )
                                notHasShutdownServers.append(id)
                        # 若沒有還沒關機的伺服器就退出檢查
                        if len(notHasShutdownServers) == 0:
                            print("✅ 面板伺服器皆已關機，開始進入節點關機流程")
                            allServersShutdown = True
                            break
                        # 給予伺服器關機緩衝時間
                        time.sleep(5)
                    if allServersShutdown == False:
                        print("⚠️ 等待面板伺服器關機逾時，跳過節點關機流程")
                        time.sleep(30)
                        continue
                    # 節點關機程序
                    agentShutdownAccepted = AgentAPI.sendAgentShutdownRequest()
                    if agentShutdownAccepted == False:
                        print("⚠️ 部分或全部節點未接受關機請求，暫不更新節點關機狀態")
                        time.sleep(30)
                        continue
                    # 將目前節點狀態寫到powerState
                    data["AgentPowerState"] = False
                    with open(POWER_STATE_PATH, "w") as f:
                        json.dump(data, f, indent=4)
        # 如果節點是關機狀態則確認UPS狀態開機節點
        else:
            if upsSnapshot["power"] == True:
                wolPacketSent = False
                for attempt in range(20):
                    if WakeOnLan.sendWakeOnLan() == True:
                        wolPacketSent = True
                    time.sleep(1)
                if wolPacketSent == True:
                    # 將目前節點狀態寫到powerState
                    data["AgentPowerState"] = True
                    with open(POWER_STATE_PATH, "w") as f:
                        json.dump(data, f, indent=4)
                else:
                    print("⚠️ 未成功送出 Wake-on-LAN 封包，暫不更新節點開機狀態")
        # 定時執行檢查UPS
        if data["AgentPowerState"] == True:
            print(f"{datetime.datetime.now().strftime("%H:%M:%S")} 目前節點皆為開機狀態")
        else:
            print(f"{datetime.datetime.now().strftime("%H:%M:%S")} 目前節點皆為關機狀態，正在持續檢測UPS狀態，若上電則開機節點")
        showStatus(upsSnapshot, data["AgentPowerState"])
        time.sleep(30)
