import os, json, re
from wakeonlan import send_magic_packet
from Api.Logger import log

_MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$|^[0-9A-Fa-f]{12}$")

def isValidMac(mac):
    return isinstance(mac, str) and _MAC_PATTERN.match(mac.strip()) is not None

def sendWakeOnLanTo(mac):
    try:
        send_magic_packet(mac)
        return True
    except Exception as e:
        log(f"❌ 發送 Wake-on-LAN 到 {mac} 發生錯誤: {e}", source="wol")
        return False

def sendWakeOnLan():
    agentInfo = os.getenv("AgentInfo")
    if agentInfo is None:
        log("❌ AgentInfo 環境變數未設定", source="wol")
        return False
    try:
        agent_ips = json.loads(agentInfo)
    except json.JSONDecodeError as e:
        log(f"❌ AgentInfo JSON 格式錯誤: {e}", source="wol")
        return False

    sentPacket = False
    for agent in agent_ips:
        if "mac" not in agent:
            log(f"❌ AgentInfo 缺少 mac 欄位: {agent}", source="wol")
            continue
        if sendWakeOnLanTo(agent['mac']):
            sentPacket = True
    return sentPacket
