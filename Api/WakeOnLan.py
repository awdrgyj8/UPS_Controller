import os, json
from wakeonlan import send_magic_packet

def sendWakeOnLan():
    agentInfo = os.getenv("AgentInfo")
    agent_ips = json.loads(agentInfo) # type: ignore
    for agent in agent_ips:
        send_magic_packet(agent['mac'])
