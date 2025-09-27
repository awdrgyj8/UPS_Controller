import Api.PteroAPI as PteroAPI
import Api.NutClient as NutClient
import Api.AgentAPI as AgentAPI
import Api.WakeOnLan as WakeOnLan
import time, json

if __name__ == "__main__":
    while True:
        # 讀取目前狀態
        with open("Data/powerState.json", "r") as f:
            data = json.load(f)
        # 如果節點都是開機狀態
        if data["AgentPowerState"] == True:
            if NutClient.getUpsPower() == False and NutClient.getUpsBetteryPercentage() <= 50:
                    print("正在執行關機程序")
                    # 取得 Pterodactyl 所有伺服器 UUID
                    allServersUUID = PteroAPI.getAllServerUUID()
                    PteroAPI.sendPowerSignal(allServersUUID, "stop")
                    # 檢查 Pterodactyl 所有伺服器是否皆以關閉
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
                            break
                        # 給予伺服器關機緩衝時間
                        time.sleep(5)
                    # 節點關機程序
                    AgentAPI.sendAgentShutdownRequest()
                    # 將目前節點狀態寫到powerState
                    data["AgentPowerState"] = False
                    with open("Data/powerState.json", "w") as f:
                        json.dump(data, f, indent=4)
        # 如果節點是關機狀態則確認UPS狀態開機節點
        else:
            if NutClient.getUpsPower() == True:
                for attempt in range(20):
                    WakeOnLan.send_magic_packet()
            # 將目前節點狀態寫到powerState
            data["AgentPowerState"] = True
            with open("Data/powerState.json", "w") as f:
                json.dump(data, f, indent=4)
        # 定時執行檢查UPS
        if data["AgentPowerState"] == True:
            print("目前節點皆為開機狀態")
        else:
            print("目前節點皆為關機狀態，正在持續檢測UPS狀態，若上電則開機節點")
        time.sleep(30)
