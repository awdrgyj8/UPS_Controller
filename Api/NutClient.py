"""NUT（Network UPS Tools）：讀取 UPS 的全部變數，並整理成控制流程使用的快照。"""
from nut2 import PyNUTClient, PyNUTError  # type: ignore

_REQUEST_TIMEOUT = 5
NUT_ERRORS = (PyNUTError, OSError, ValueError, AttributeError)


class NutClient:
    def __init__(self, host, port, ups_name, login=None, password=None):
        self.host = host
        self.port = port
        self.ups_name = ups_name
        self.login = login or None
        self.password = password or None

    def target(self):
        """連線目標（不含密碼），供介面顯示。"""
        return {
            "host": self.host or "",
            "port": str(self.port) if self.port is not None else "",
            "ups_name": self.ups_name or "",
            "auth": bool(self.login),
        }

    def variables(self):
        """讀取 UPS 全部 NUT 變數，失敗時拋出 NUT_ERRORS。"""
        for name, value in (("NUT_ServerIP", self.host), ("NUT_ServerPort", self.port), ("NUT_UPS_NAME", self.ups_name)):
            if value in (None, ""):
                raise ValueError(f"{name} 環境變數未設定")
        client = PyNUTClient(self.host, port=self.port, login=self.login, password=self.password,
                             timeout=_REQUEST_TIMEOUT)
        try:
            return dict(client.list_vars(self.ups_name))
        finally:
            handler = getattr(client, "_srv_handler", None)
            if handler is not None:
                handler.close()


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_ups_snapshot(variables):
    """由 NUT 變數組出控制流程使用的快照。ups.status 含 OB 代表改由電池供電。"""
    ups_status = variables.get("ups.status", "UNKNOWN")
    battery_charge = variables.get("battery.charge")
    return {
        "ok": True,
        "power": "OB" not in ups_status.split(),
        "status": ups_status,
        "battery": int(float(battery_charge)) if battery_charge is not None else None,
        "error": "",
        "runtime": _to_float(variables.get("battery.runtime")),
        "load": _to_float(variables.get("ups.load")),
        "input_voltage": _to_float(variables.get("input.voltage")),
        "output_voltage": _to_float(variables.get("output.voltage")),
        "input_frequency": _to_float(variables.get("input.frequency")),
        "battery_voltage": _to_float(variables.get("battery.voltage")),
        "temperature": _to_float(variables.get("ups.temperature")),
    }


def error_snapshot(error):
    return {
        "ok": False,
        "power": None,
        "status": "UNKNOWN",
        "battery": None,
        "error": str(error),
    }
