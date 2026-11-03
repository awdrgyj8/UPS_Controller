import json, time, uuid, base64, requests, os
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from Api.Logger import log

_AGENT_REQUEST_TIMEOUT = 5
BASE_DIR = Path(__file__).resolve().parents[1]
PRIVATE_KEY_PATH = BASE_DIR / "Keys" / "private_key.pem"

_privkey = None

def loadPrivateKey():
    """讀取私鑰檔案（controller端的私鑰），第一次使用時才載入。"""
    global _privkey
    if _privkey is None:
        with open(PRIVATE_KEY_PATH, "rb") as f:
            _privkey = load_pem_private_key(f.read(), password=None)
    return _privkey

def _make_signed_payload(action="shutdown"):
    payload = {
        "action": action,
        "timestamp": int(time.time()),
        "nonce": str(uuid.uuid4()),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = loadPrivateKey().sign(payload_bytes) # type: ignore
    return {"payload": payload, "signature": base64.b64encode(signature).decode()}

def loadAgentInfo(verbose=True):
    agentInfo = os.getenv("AgentInfo")
    if agentInfo is None:
        if verbose:
            log("❌ AgentInfo 環境變數未設定", source="agent")
        return None
    try:
        return json.loads(agentInfo)
    except json.JSONDecodeError as e:
        if verbose:
            log(f"❌ AgentInfo JSON 格式錯誤: {e}", source="agent")
        return None

# 保留舊名稱
_load_agent_info = loadAgentInfo

def getAgentStatus(agent, index=1):
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
        "capabilities": [],
        "system": None,
    }

    if ip == "":
        status["error"] = "missing ip"
        return status
    if port is None:
        status["error"] = "missing port"
        return status

    started_at = time.monotonic()
    try:
        response = requests.get(f"http://{ip}:{port}/status", timeout=_AGENT_REQUEST_TIMEOUT)
        status["latency_ms"] = round((time.monotonic() - started_at) * 1000)
        response_data = response.json()
        if response.status_code == 200 and response_data.get("ok") is True:
            status["online"] = True
            status["hostname"] = response_data.get("hostname", "")
            status["uptime_seconds"] = response_data.get("uptime_seconds")
            # 舊版 Agent 沒有以下欄位
            status["capabilities"] = response_data.get("capabilities", ["status", "shutdown"])
            status["system"] = response_data.get("system")
        else:
            status["error"] = response_data.get("reason", f"HTTP {response.status_code}")
    except requests.exceptions.RequestException as e:
        status["error"] = str(e)
    except ValueError:
        status["error"] = "invalid json response"
    return status

def getAgentStatuses():
    agent_ips = loadAgentInfo()
    if agent_ips is None:
        return []
    return [getAgentStatus(agent, index) for index, agent in enumerate(agent_ips, start=1)]

def _send_signed(agent, endpoint, action):
    """送出簽章請求，回傳 (ok, message)。"""
    if "ip" not in agent:
        return False, f"AgentInfo 缺少 ip 欄位: {agent}"
    if "port" not in agent:
        return False, f"AgentInfo 缺少 port 欄位: {agent}"
    node_url = f"http://{agent['ip']}:{agent['port']}/{endpoint}"
    data = _make_signed_payload(action)
    try:
        response = requests.post(node_url, json=data, timeout=_AGENT_REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return False, f"發送到 {agent['ip']} 發生錯誤: {e}"
    if response.status_code == 404:
        return False, "Agent 不支援此端點（請更新 Agent 版本）"
    try:
        response_data = response.json()
    except ValueError:
        return False, f"回應不是 JSON。狀態碼: {response.status_code}, 回應: {response.text}"
    if response_data.get('ok') is not True:
        return False, f"回應錯誤: {response_data.get('reason', 'unknown')}"
    return True, response_data.get('message', '')

def sendShutdownToAgent(agent):
    ok, message = _send_signed(agent, "shutdown", "shutdown")
    if ok:
        log(f"✅ 節點 {agent['ip']} 已收到 且回應開始執行關機 訊息: {message}", source="agent")
    else:
        log(f"❌ 節點 {agent.get('ip', '?')} 關機請求失敗: {message}", source="agent")
    return ok, message

def sendVerifyToAgent(agent):
    """測試用：送出 action=verify 的簽章請求，Agent 只驗證不執行任何動作。"""
    return _send_signed(agent, "verify", "verify")

def sendAgentShutdownRequest():
    agent_ips = loadAgentInfo()
    if agent_ips is None:
        return False

    allAccepted = True
    # 發出節點關機請求
    for agent in agent_ips:
        ok, _ = sendShutdownToAgent(agent)
        if not ok:
            allAccepted = False
    return allAccepted
