import os, time
from pathlib import Path
from dotenv import load_dotenv
from nut2 import PyNUTClient, PyNUTError  # type: ignore
from Api.Logger import log

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

_REQUEST_TIMEOUT = 5
NUT_ERRORS = (PyNUTError, OSError, ValueError, AttributeError)

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

def getNutTarget():
    """回傳 NUT 連線目標（不含密碼），供介面顯示。"""
    return {
        "host": os.getenv("NUT_ServerIP") or "",
        "port": os.getenv("NUT_ServerPort") or "",
        "ups_name": os.getenv("NUT_UPS_NAME") or "",
        "auth": bool(_get_optional_env("NUT_Login")),
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

def getUpsVariables():
    """讀取 UPS 全部 NUT 變數，失敗時拋出 NUT_ERRORS。"""
    return dict(_list_ups_vars())

def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def buildUpsSnapshot(vars):
    """由 NUT 變數組出控制流程使用的快照（判斷邏輯與原本相同）。"""
    ups_status = vars.get("ups.status", "UNKNOWN")
    status_tokens = ups_status.split()
    battery_charge = vars.get("battery.charge")
    return {
        "ok": True,
        "power": "OB" not in status_tokens,
        "status": ups_status,
        "battery": int(float(battery_charge)) if battery_charge is not None else None,
        "error": "",
        "runtime": _to_float(vars.get("battery.runtime")),
        "load": _to_float(vars.get("ups.load")),
        "input_voltage": _to_float(vars.get("input.voltage")),
        "output_voltage": _to_float(vars.get("output.voltage")),
        "input_frequency": _to_float(vars.get("input.frequency")),
        "battery_voltage": _to_float(vars.get("battery.voltage")),
        "temperature": _to_float(vars.get("ups.temperature")),
    }

def errorSnapshot(error):
    return {
        "ok": False,
        "power": None,
        "status": "UNKNOWN",
        "battery": None,
        "error": str(error),
    }

def getUpsSnapshot():
    try:
        return buildUpsSnapshot(getUpsVariables())
    except NUT_ERRORS as e:
        log(f"❌ 讀取 UPS 狀態失敗: {e}", source="nut")
        return errorSnapshot(e)


def getUpsPower():
    return getUpsSnapshot()["power"]


def getUpsBetteryPercentage():
    return getUpsSnapshot()["battery"]

def getUpsBatteryPercentage():
    return getUpsBetteryPercentage()
