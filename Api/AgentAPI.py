import json, time, uuid, base64, requests, os
from cryptography.hazmat.primitives.serialization import load_pem_private_key

# 讀取私鑰檔案（controller端的私鑰）
with open("Keys/private_key.pem", "rb") as f:
    privkey = load_pem_private_key(f.read(), password=None)

def _make_signed_payload():
    payload = {
        "action": "shutdown",
        "timestamp": int(time.time()),
        "nonce": str(uuid.uuid4()),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = privkey.sign(payload_bytes) # type: ignore
    return {"payload": payload, "signature": base64.b64encode(signature).decode()}


def sendAgentShutdownRequest():
    agentInfo = os.getenv("AgentInfo")
    agent_ips = json.loads(agentInfo) # type: ignore
    # 發出節點關機請求
    for agent in agent_ips:    
        node_url = f"http://{agent['ip']}:5858/shutdown"
        data = _make_signed_payload()
        try:
            response = requests.post(node_url, json=data, timeout=5)
            if response.json()['ok'] == False:
                print(f"❌ 節點 {agent['ip']} 回應錯誤: {response.json()['reason']}")
            else:
                print(f"✅ 節點 {agent['ip']} 已收到 且回應開始執行關機 訊息: {response.json()['message']}")
        except requests.exceptions.RequestException as e:
            print(f"❌ 發送節點關機指令到 {agent['ip']} 發生錯誤: {e}")
