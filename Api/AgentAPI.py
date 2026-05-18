import json, time, uuid, base64, requests, os
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key

_AGENT_REQUEST_TIMEOUT = 5
BASE_DIR = Path(__file__).resolve().parents[1]
PRIVATE_KEY_PATH = BASE_DIR / "Keys" / "private_key.pem"

# 讀取私鑰檔案（controller端的私鑰）
with open(PRIVATE_KEY_PATH, "rb") as f:
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

def _load_agent_info():
    agentInfo = os.getenv("AgentInfo")
    if agentInfo is None:
        print("❌ AgentInfo 環境變數未設定")
        return None
    try:
        return json.loads(agentInfo)
    except json.JSONDecodeError as e:
        print(f"❌ AgentInfo JSON 格式錯誤: {e}")
        return None

def getAgentStatuses():
    agent_ips = _load_agent_info()
    if agent_ips is None:
        return []

    statuses = []
    for index, agent in enumerate(agent_ips, start=1):
        ip = agent.get("ip", "")
        port = agent.get("port")
        mac = agent.get("mac", "")
        status = {
            "name": agent.get("name", f"Agent {index}"),
            "ip": ip,
            "port": str(port) if port is not None else "",
            "mac": mac,
            "online": False,
            "hostname": "",
            "uptime_seconds": None,
            "latency_ms": None,
            "error": "",
        }

        if ip == "":
            status["error"] = "missing ip"
            statuses.append(status)
            continue
        if port is None:
            status["error"] = "missing port"
            statuses.append(status)
            continue

        started_at = time.monotonic()
        try:
            response = requests.get(f"http://{ip}:{port}/status", timeout=_AGENT_REQUEST_TIMEOUT)
            status["latency_ms"] = round((time.monotonic() - started_at) * 1000)
            response_data = response.json()
            if response.status_code == 200 and response_data.get("ok") is True:
                status["online"] = True
                status["hostname"] = response_data.get("hostname", "")
                status["uptime_seconds"] = response_data.get("uptime_seconds")
            else:
                status["error"] = response_data.get("reason", f"HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            status["error"] = str(e)
        except ValueError:
            status["error"] = "invalid json response"

        statuses.append(status)
    return statuses


def sendAgentShutdownRequest():
    agent_ips = _load_agent_info()
    if agent_ips is None:
        return False

    allAccepted = True
    # 發出節點關機請求
    for agent in agent_ips:
        if "ip" not in agent:
            print(f"❌ AgentInfo 缺少 ip 欄位: {agent}")
            allAccepted = False
            continue
        if "port" not in agent:
            print(f"❌ AgentInfo 缺少 port 欄位: {agent}")
            allAccepted = False
            continue
        node_url = f"http://{agent['ip']}:{agent['port']}/shutdown"
        data = _make_signed_payload()
        try:
            response = requests.post(node_url, json=data, timeout=_AGENT_REQUEST_TIMEOUT)
            try:
                response_data = response.json()
            except ValueError:
                print(f"❌ 節點 {agent['ip']} 回應不是 JSON。狀態碼: {response.status_code}, 回應: {response.text}")
                allAccepted = False
                continue

            if response_data.get('ok') is not True:
                print(f"❌ 節點 {agent['ip']} 回應錯誤: {response_data.get('reason', 'unknown')}")
                allAccepted = False
            else:
                print(f"✅ 節點 {agent['ip']} 已收到 且回應開始執行關機 訊息: {response_data.get('message', '')}")
        except requests.exceptions.RequestException as e:
            print(f"❌ 發送節點關機指令到 {agent['ip']} 發生錯誤: {e}")
            allAccepted = False
    return allAccepted
