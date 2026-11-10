"""執行期共享狀態：控制迴圈、監控執行緒與 Web API 共用，所有存取都經過鎖。"""
import copy
import socket
import threading
import time
from collections import deque

# NUT ups.status 旗標說明（level 對應介面的狀態色：good / neutral / warning / serious / critical）
UPS_STATUS_FLAGS = {
    "OL": ("市電供電", "good"),
    "OB": ("電池供電", "serious"),
    "LB": ("電量低", "critical"),
    "HB": ("電量高", "neutral"),
    "RB": ("需更換電池", "serious"),
    "CHRG": ("充電中", "neutral"),
    "DISCHRG": ("放電中", "warning"),
    "BYPASS": ("旁路供電", "serious"),
    "CAL": ("校正中", "neutral"),
    "OFF": ("UPS 輸出關閉", "critical"),
    "OVER": ("過載", "critical"),
    "TRIM": ("降壓調節", "neutral"),
    "BOOST": ("升壓調節", "neutral"),
    "FSD": ("強制關機", "critical"),
    "ALARM": ("警報", "serious"),
    "TEST": ("自我測試中", "neutral"),
}

PHASE_LABELS = {
    "starting": "啟動中",
    "monitoring": "監控中",
    "on_battery": "電池供電中",
    "shutdown": "執行關機程序",
    "nodes_off": "節點已關機",
    "waking": "喚醒節點中",
    "nut_error": "UPS 讀取失敗",
    "paused": "自動控制已暫停",
}


def describe_status_flags(status):
    flags = []
    for token in (status or "").split():
        label, level = UPS_STATUS_FLAGS.get(token, (token, "neutral"))
        flags.append({"code": token, "label": label, "level": level})
    return flags


class SystemState:
    EVENT_LIMIT = 1000
    HISTORY_LIMIT = 3600

    def __init__(self, settings, mode):
        self._lock = threading.RLock()
        self.settings = settings
        self.version = 0
        self._history = deque(maxlen=self.HISTORY_LIMIT)
        self._history_seq = 0
        self._events = deque(maxlen=self.EVENT_LIMIT)
        self._event_seq = 0
        now = time.time()
        self._data = {
            "mode": mode,
            "started_at": now,
            "controller": {
                "hostname": socket.gethostname(),
                "phase": "starting",
                "phase_label": PHASE_LABELS["starting"],
                "decision": "等待第一次輪詢",
                "expected_power_state": None,
                "paused": False,
                "cycle_count": 0,
                "last_cycle_at": None,
                "next_cycle_at": None,
                "sequence": None,
                "last_sequence": None,
            },
            "nut": {"host": "", "port": "", "ups_name": "", "connected": None, "latency_ms": None,
                     "error": "", "last_update": None},
            "ups": {"ok": None, "power": None, "status": "UNKNOWN", "status_flags": [], "battery": None,
                    "error": "", "variables": {}, "updated_at": None, "on_battery_since": None},
            "agents": [],
            "agent_config_error": "",
            "agents_updated_at": None,
            "ptero": {"configured": None, "url": "", "ok": None, "error": "", "servers": [], "nodes": [],
                      "updated_at": None},
            "diagnostics": None,
            "scenario": None,
            "simulation": None,
        }

    # ---- 一般更新 ----
    def _bump(self):
        self.version += 1

    def update(self, section, **values):
        with self._lock:
            self._data[section].update(values)
            self._bump()

    def set(self, section, value):
        with self._lock:
            self._data[section] = value
            self._bump()

    def get(self, section):
        with self._lock:
            return copy.deepcopy(self._data[section])

    def mutate(self, fn):
        """在鎖內直接修改資料（fn 收到內部 dict）。"""
        with self._lock:
            result = fn(self._data)
            self._bump()
            return result

    # ---- 事件與歷史 ----
    def add_event(self, level, source, message):
        with self._lock:
            self._event_seq += 1
            self._events.append({
                "id": self._event_seq,
                "ts": time.time(),
                "level": level,
                "source": source,
                "message": message,
            })
            self._bump()

    def events(self, limit=200, level=None):
        with self._lock:
            items = list(self._events)
        if level:
            items = [item for item in items if item["level"] == level]
        return items[-limit:]

    def add_sample(self, sample):
        with self._lock:
            self._history_seq += 1
            sample = dict(sample, seq=self._history_seq)
            self._history.append(sample)
            return sample

    def history(self, since_seq=0, since_ts=None):
        with self._lock:
            items = list(self._history)
        if since_ts is not None:
            items = [item for item in items if item["t"] >= since_ts]
        return [item for item in items if item["seq"] > since_seq]

    @property
    def history_seq(self):
        with self._lock:
            return self._history_seq

    def snapshot(self, event_limit=80):
        with self._lock:
            data = copy.deepcopy(self._data)
            data["events"] = list(self._events)[-event_limit:]
            data["version"] = self.version
        data["server_time"] = time.time()
        data["settings"] = self.settings.public_dict()
        return data
