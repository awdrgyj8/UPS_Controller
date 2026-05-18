import os, json
from wakeonlan import send_magic_packet

def sendWakeOnLan():
    agentInfo = os.getenv("AgentInfo")
    if agentInfo is None:
        print("❌ AgentInfo 環境變數未設定")
        return False
    try:
        agent_ips = json.loads(agentInfo)
    except json.JSONDecodeError as e:
        print(f"❌ AgentInfo JSON 格式錯誤: {e}")
        return False

    sentPacket = False
    for agent in agent_ips:
        if "mac" not in agent:
            print(f"❌ AgentInfo 缺少 mac 欄位: {agent}")
            continue
        try:
            send_magic_packet(agent['mac'])
            sentPacket = True
        except Exception as e:
            print(f"❌ 發送 Wake-on-LAN 到 {agent['mac']} 發生錯誤: {e}")
    return sentPacket
