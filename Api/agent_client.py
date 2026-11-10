"""UPS_Agent：查詢節點狀態，並以 Ed25519 簽章送出關機 / 驗證請求。"""
import base64
import json
import time
import uuid

import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from Api.event_log import log

_AGENT_REQUEST_TIMEOUT = 5


class AgentClient:
    def __init__(self, private_key_path):
        self.private_key_path = private_key_path
        self._private_key = None

    def load_private_key(self):
        """讀取 Controller 端的私鑰，第一次使用時才載入。"""
        if self._private_key is None:
            with open(self.private_key_path, "rb") as f:
                self._private_key = load_pem_private_key(f.read(), password=None)
        return self._private_key

    def _signed_payload(self, action):
        payload = {
            "action": action,
            "timestamp": int(time.time()),
            "nonce": str(uuid.uuid4()),
        }
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = self.load_private_key().sign(payload_bytes)  # type: ignore
        return {"payload": payload, "signature": base64.b64encode(signature).decode()}

    def status(self, agent, index=1):
        """查詢一台節點的 /status。不拋出例外，連不上時 online=False 並帶 error。"""
        ip = agent.get("ip", "")
        port = agent.get("port")
        status = {
            "name": agent.get("name", f"Agent {index}"),
            "ip": ip,
            "port": str(port) if port is not None else "",
            "mac": agent.get("mac", ""),
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
            data = response.json()
            if response.status_code == 200 and data.get("ok") is True:
                status["online"] = True
                status["hostname"] = data.get("hostname", "")
                status["uptime_seconds"] = data.get("uptime_seconds")
                # 舊版 Agent 沒有以下欄位
                status["capabilities"] = data.get("capabilities", ["status", "shutdown"])
                status["system"] = data.get("system")
            else:
                status["error"] = data.get("reason", f"HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            status["error"] = str(e)
        except ValueError:
            status["error"] = "invalid json response"
        return status

    def _send_signed(self, agent, endpoint, action):
        """送出簽章請求，回傳 (ok, message)。"""
        if "ip" not in agent:
            return False, f"AgentInfo 缺少 ip 欄位: {agent}"
        if "port" not in agent:
            return False, f"AgentInfo 缺少 port 欄位: {agent}"
        url = f"http://{agent['ip']}:{agent['port']}/{endpoint}"
        try:
            response = requests.post(url, json=self._signed_payload(action), timeout=_AGENT_REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            return False, f"發送到 {agent['ip']} 發生錯誤: {e}"
        if response.status_code == 404:
            return False, "Agent 不支援此端點（請更新 Agent 版本）"
        try:
            data = response.json()
        except ValueError:
            return False, f"回應不是 JSON。狀態碼: {response.status_code}, 回應: {response.text}"
        if data.get("ok") is not True:
            return False, f"回應錯誤: {data.get('reason', 'unknown')}"
        return True, data.get("message", "")

    def shutdown(self, agent):
        ok, message = self._send_signed(agent, "shutdown", "shutdown")
        if ok:
            log(f"✅ 節點 {agent['ip']} 已收到 且回應開始執行關機 訊息: {message}", source="agent")
        else:
            log(f"❌ 節點 {agent.get('ip', '?')} 關機請求失敗: {message}", source="agent")
        return ok, message

    def verify(self, agent):
        """測試用：送出 action=verify 的簽章請求，Agent 只驗證不執行任何動作。"""
        return self._send_signed(agent, "verify", "verify")
