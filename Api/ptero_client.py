"""Pterodactyl 面板：Application API 列出伺服器與 node，Client API 讀取狀態與送出電源訊號。"""
import requests
import urllib3

from Api.event_log import log

# 面板常用自簽憑證，請求一律不驗證憑證；關掉 urllib3 對此的警告
urllib3.disable_warnings()

_REQUEST_TIMEOUT = 10
_PAGE_SIZE = 100


class PteroClient:
    def __init__(self, url, app_key, client_key):
        self.url = url or ""
        self._app_key = app_key
        self._client_key = client_key

    @property
    def configured(self):
        return bool(self.url) and bool(self._app_key) and bool(self._client_key)

    @staticmethod
    def _headers(key):
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"}

    def _get_paginated(self, path):
        """讀取 Application API 的全部分頁資料，失敗時拋出例外。"""
        items = []
        page = 1
        while True:
            response = requests.get(
                f"{self.url}{path}",
                headers=self._headers(self._app_key),
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

    def list_servers(self):
        """取得面板所有伺服器（含所屬 node），失敗時拋出例外。"""
        servers = []
        for server in self._get_paginated("/api/application/servers"):
            attributes = server["attributes"]
            servers.append({
                "identifier": attributes["uuid"][:8],
                "uuid": attributes["uuid"],
                "name": attributes.get("name", ""),
                "node_id": attributes.get("node"),
                "suspended": attributes.get("suspended", False),
            })
        return servers

    def list_nodes(self):
        """取得面板所有 node（Wings 節點），失敗時拋出例外。"""
        nodes = []
        for node in self._get_paginated("/api/application/nodes"):
            attributes = node["attributes"]
            nodes.append({
                "id": attributes.get("id"),
                "name": attributes.get("name", ""),
                "fqdn": attributes.get("fqdn", ""),
                "maintenance_mode": attributes.get("maintenance_mode", False),
            })
        return nodes

    def server_resources(self, identifier):
        """取得伺服器即時資源（狀態、CPU、記憶體），失敗時拋出例外。"""
        response = requests.get(
            f"{self.url}/api/client/servers/{identifier}/resources",
            headers=self._headers(self._client_key),
            verify=False,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        attributes = response.json()["attributes"]
        resources = attributes.get("resources", {})
        return {
            "state": attributes["current_state"],  # running / offline / stopping / starting
            "cpu_percent": resources.get("cpu_absolute"),
            "memory_bytes": resources.get("memory_bytes"),
            "uptime_ms": resources.get("uptime"),
        }

    def send_power(self, identifier, action):
        """送出電源訊號（start / stop / restart / kill），回傳是否成功；失敗只記錄不拋出例外。"""
        try:
            response = requests.post(
                f"{self.url}/api/client/servers/{identifier}/power",
                headers=self._headers(self._client_key),
                json={"signal": action},
                verify=False,
                timeout=_REQUEST_TIMEOUT,
            )
            if response.status_code == 204:
                log(f"✅ 已對 {identifier} 伺服器發送 '{action}' 發送成功。", source="ptero")
                return True
            log(
                f"⚠️ 無法發送電源訊號給伺服器 {identifier}。狀態碼: {response.status_code}, 回應: {response.text}",
                source="ptero",
            )
        except requests.exceptions.RequestException as e:
            log(f"❌ 發送 {identifier} 電源訊號時發生錯誤: {e}", source="ptero")
        return False
