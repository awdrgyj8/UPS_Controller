import requests
import os
import urllib3
from pathlib import Path
from typing import Literal, List
from dotenv import load_dotenv
urllib3.disable_warnings()

# 讀取.env
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
PteroApi_Url = os.getenv("PteroApi_Url")
_REQUEST_TIMEOUT = 10

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

def getAllServerUUID():
    try:
        response = requests.get(
            f"{PteroApi_Url}/api/application/servers",
            headers=_ApplicationHeaders,
            verify=False,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        return [server["attributes"]["uuid"][:8] for server in data]
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
    except (ValueError, KeyError) as e:
        print(f"JSON format error: {e}")
    return []

def sendPowerSignal(serverList: List[str], action: Literal["start", "stop", "restart", "kill"]):
    for serverID in serverList:
        try:
            response = requests.post(
                f"{PteroApi_Url}/api/client/servers/{serverID}/power",
                headers=_ClientHeaders,
                json={"signal": action},
                verify=False,
                timeout=_REQUEST_TIMEOUT,
            )
            if response.status_code == 204:
                print(f"✅ 已對 {serverID} 伺服器發送 '{action}' 發送成功。")
            else:
                print(
                    f"⚠️ 無法發送電源訊號給伺服器 {serverID}。狀態碼: {response.status_code}, 回應: {response.text}"
                )
        except requests.exceptions.RequestException as e:
            print(f"❌ 發送 {serverID} 電源訊號時發生錯誤: {e}")

def getServerPowerState(serverUUID: str):
    try:
        state_response = requests.get(
            f"{PteroApi_Url}/api/client/servers/{serverUUID}/resources",
            headers=_ClientHeaders,
            verify=False,
            timeout=_REQUEST_TIMEOUT,
        )
        state_response.raise_for_status()
        return state_response.json()["attributes"]["current_state"] # running offline stopping
    except (requests.exceptions.RequestException, ValueError, KeyError) as e:
        print(f"❌ 取得 {serverUUID} 電源狀態時發生錯誤: {e}")
        return "unknown"
