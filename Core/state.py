"""執行期共享狀態：控制迴圈、監控執行緒與 Web API 共用，所有存取都經過鎖。

資料的形狀定義在 Core/models.py。
"""
import copy
import socket
import threading
import time
from collections import deque

from Core.models import AppState, ControllerState, Event, Sample, StatusFlag

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
        flags.append(StatusFlag(code=token, label=label, level=level))
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
        self._data = AppState(
            mode=mode,
            started_at=time.time(),
            controller=ControllerState(
                hostname=socket.gethostname(),
                phase_label=PHASE_LABELS["starting"],
                decision="等待第一次輪詢",
            ),
        )

    # ---- 讀寫 ----
    def _bump(self):
        self.version += 1

    def update(self, section, **values):
        """更新某一區的幾個欄位，例如 update("ups", battery=78)。欄位名稱寫錯會報錯。"""
        with self._lock:
            target = getattr(self._data, section)
            for name, value in values.items():
                setattr(target, name, value)
            self._bump()

    def set(self, section, value):
        """整個換掉某一區，例如 set("diagnostics", DiagnosticsState(...))。"""
        with self._lock:
            setattr(self._data, section, value)
            self._bump()

    def get(self, section):
        """取得某一區的複本（可以放心讀，改它不會影響共享狀態）。"""
        with self._lock:
            return copy.deepcopy(getattr(self._data, section))

    def mutate(self, fn):
        """在鎖內直接修改資料：fn 收到整份 AppState，回傳值會原樣傳回。"""
        with self._lock:
            result = fn(self._data)
            self._bump()
            return result

    # ---- 事件與歷史 ----
    def add_event(self, level, source, message):
        with self._lock:
            self._event_seq += 1
            self._events.append(Event(id=self._event_seq, ts=time.time(), level=level, source=source,
                                      message=str(message)))
            self._bump()

    def events(self, limit=200, level=None):
        with self._lock:
            items = list(self._events)
        if level:
            items = [item for item in items if item.level == level]
        return items[-limit:]

    def add_sample(self, **reading):
        """記錄一次 UPS 讀數（t、battery、load…），回傳加上序號的 Sample。"""
        with self._lock:
            self._history_seq += 1
            sample = Sample(seq=self._history_seq, **reading)
            self._history.append(sample)
            return sample

    def history(self, since_seq=0, since_ts=None):
        with self._lock:
            items = list(self._history)
        if since_ts is not None:
            items = [item for item in items if item.t >= since_ts]
        return [item for item in items if item.seq > since_seq]

    @property
    def history_seq(self):
        with self._lock:
            return self._history_seq

    def snapshot(self, event_limit=80, strict=False):
        """整份狀態轉成可以直接輸出 JSON 的 dict（形狀見 models.Snapshot）。

        strict=True 時，欄位的值與宣告的型別不符會拋出例外，供測試使用；平常只輸出，不因此失敗。
        """
        warnings = "error" if strict else False
        with self._lock:
            data = self._data.model_dump(mode="json", warnings=warnings)
            data["events"] = [event.model_dump() for event in list(self._events)[-event_limit:]]
            data["version"] = self.version
        data["server_time"] = time.time()
        data["settings"] = self.settings.public_dict()
        return data
