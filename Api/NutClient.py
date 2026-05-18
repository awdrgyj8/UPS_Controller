import os
from pathlib import Path
from dotenv import load_dotenv
from nut2 import PyNUTClient, PyNUTError  # type: ignore

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

_REQUEST_TIMEOUT = 5

def _get_required_env(name):
    value = os.getenv(name)
    if value is None or value == "":
        raise ValueError(f"{name} 環境變數未設定")
    return value

def _get_optional_env(name):
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return value

def _get_nut_config():
    return {
        "host": _get_required_env("NUT_ServerIP"),
        "port": int(_get_required_env("NUT_ServerPort")),
        "ups_name": _get_required_env("NUT_UPS_NAME"),
        "login": _get_optional_env("NUT_Login"),
        "password": _get_optional_env("NUT_Password"),
    }

def _list_ups_vars():
    config = _get_nut_config()
    client = PyNUTClient(
        config["host"],
        port=config["port"],
        login=config["login"],
        password=config["password"],
        timeout=_REQUEST_TIMEOUT,
    )
    try:
        return client.list_vars(config["ups_name"])
    finally:
        handler = getattr(client, "_srv_handler", None)
        if handler is not None:
            handler.close()

def getUpsSnapshot():
    try:
        vars = _list_ups_vars()
        ups_status = vars.get("ups.status", "UNKNOWN")
        status_tokens = ups_status.split()
        battery_charge = vars.get("battery.charge")
        return {
            "ok": True,
            "power": "OB" not in status_tokens,
            "status": ups_status,
            "battery": int(battery_charge) if battery_charge is not None else None,
            "error": "",
        }
    except (PyNUTError, OSError, ValueError, AttributeError) as e:
        print(f"❌ 讀取 UPS 狀態失敗: {e}")
        return {
            "ok": False,
            "power": None,
            "status": "UNKNOWN",
            "battery": None,
            "error": str(e),
        }


def getUpsPower():
    return getUpsSnapshot()["power"]


def getUpsBetteryPercentage():
    return getUpsSnapshot()["battery"]

def getUpsBatteryPercentage():
    return getUpsBetteryPercentage()
