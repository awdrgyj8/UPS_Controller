import requests
import os
import urllib3
from pathlib import Path
from typing import Literal, List
from dotenv import load_dotenv
from Api.Logger import log
urllib3.disable_warnings()

# 讀取.env
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
PteroApi_Url = os.getenv("PteroApi_Url")
_REQUEST_TIMEOUT = 10
_PAGE_SIZE = 100

# 初始化標頭檔
_ApplicationHeaders = {
    "Authorization": f"Bearer {os.getenv('PteroApi_AppKey')}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
_ClientHeaders = {
    "Authorization": f"Bearer {os.getenv('PteroApi_ClientKey')}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def isConfigured():
    return bool(PteroApi_Url) and bool(os.getenv("PteroApi_AppKey")) and bool(os.getenv("PteroApi_ClientKey"))

def _get_paginated(path):
    """讀取 Application API 的全部分頁資料，失敗時拋出例外。"""
    items = []
    page = 1
    while True:
        response = requests.get(
            f"{PteroApi_Url}{path}",
            headers=_ApplicationHeaders,
            params={"page": page, "per_page": _PAGE_SIZE},
            verify=False,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        items.extend(body.get("data", []))
        total_pages = body.get("meta", {}).get("pagination", {}).get("total_pages", 1)
        if page >= total_pages:
            return items
        page += 1

def getAllServers():
    """取得面板所有伺服器的詳細資訊（含所屬 node），失敗時拋出例外。"""
    servers = []
    for server in _get_paginated("/api/application/servers"):
        attributes = server["attributes"]
        servers.append({
            "identifier": attributes["uuid"][:8],
            "uuid": attributes["uuid"],
            "name": attributes.get("name", ""),
            "node_id": attributes.get("node"),
            "suspended": attributes.get("suspended", False),
        })
    return servers

def getNodes():
    """取得面板所有 node（Wings 節點），失敗時拋出例外。"""
    nodes = []
    for node in _get_paginated("/api/application/nodes"):
        attributes = node["attributes"]
        nodes.append({
            "id": attributes.get("id"),
            "name": attributes.get("name", ""),
            "fqdn": attributes.get("fqdn", ""),
            "maintenance_mode": attributes.get("maintenance_mode", False),
        })
    return nodes

def getAllServerUUID():
    try:
        return [server["identifier"] for server in getAllServers()]
    except requests.exceptions.RequestException as e:
        log(f"Request failed: {e}", level="error", source="ptero")
    except (ValueError, KeyError) as e:
        log(f"JSON format error: {e}", level="error", source="ptero")
    return []

def sendPowerSignalTo(serverID: str, action: Literal["start", "stop", "restart", "kill"]):
    try:
        response = requests.post(
            f"{PteroApi_Url}/api/client/servers/{serverID}/power",
            headers=_ClientHeaders,
            json={"signal": action},
            verify=False,
            timeout=_REQUEST_TIMEOUT,
        )
        if response.status_code == 204:
            log(f"✅ 已對 {serverID} 伺服器發送 '{action}' 發送成功。", source="ptero")
            return True
        log(
            f"⚠️ 無法發送電源訊號給伺服器 {serverID}。狀態碼: {response.status_code}, 回應: {response.text}",
            source="ptero",
        )
    except requests.exceptions.RequestException as e:
        log(f"❌ 發送 {serverID} 電源訊號時發生錯誤: {e}", source="ptero")
    return False

def sendPowerSignal(serverList: List[str], action: Literal["start", "stop", "restart", "kill"]):
    for serverID in serverList:
        sendPowerSignalTo(serverID, action)

def getServerResources(serverUUID: str):
    """取得伺服器即時資源（狀態、CPU、記憶體），失敗時拋出例外。"""
    response = requests.get(
        f"{PteroApi_Url}/api/client/servers/{serverUUID}/resources",
        headers=_ClientHeaders,
        verify=False,
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    attributes = response.json()["attributes"]
    resources = attributes.get("resources", {})
    return {
        "state": attributes["current_state"],  # running offline stopping starting
        "cpu_percent": resources.get("cpu_absolute"),
        "memory_bytes": resources.get("memory_bytes"),
        "uptime_ms": resources.get("uptime"),
    }

def getServerPowerState(serverUUID: str):
    try:
        return getServerResources(serverUUID)["state"]
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        log(f"❌ 取得 {serverUUID} 電源狀態時發生錯誤: {e}", source="ptero")
        return "unknown"
