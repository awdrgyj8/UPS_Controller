"""測試中心：系統自檢與停電演練（乾跑）的執行與結果記錄。

兩者都不會造成任何副作用：
  * 不會送出伺服器 stop 訊號
  * 不會送出節點關機請求（改用 /verify 簽章驗證端點）
  * 不會送出 Wake-on-LAN 封包（只檢查 MAC 格式）

檢查項目本身在 selftest.py 與 drill.py。
"""
import threading
import time

from Core.drill import run_drill
from Core.models import CheckResult, DiagnosticsState
from Core.selftest import run_selftest

RUNS = {
    "selftest": ("系統自檢", run_selftest),
    "drill": ("停電演練（乾跑）", run_drill),
}


class CheckContext:
    """單一檢查項目：建立時在介面上顯示為執行中，finish() 填入結果。"""

    def __init__(self, runner, check_id, group, label):
        self.runner = runner
        self.result = CheckResult(id=check_id, group=group, label=label)
        self._started = time.monotonic()
        runner._push(self.result)

    def finish(self, status, detail, dry_run=False):
        self.result.status, self.result.detail, self.result.dry_run = status, detail, dry_run
        self.result.duration_ms = round((time.monotonic() - self._started) * 1000)
        self.runner._push(self.result)
        return status


class DiagnosticsRunner:
    def __init__(self, service):
        self.service = service
        self.drivers = service.drivers
        self.state = service.state
        self.settings = service.settings
        self.power_store = service.power_store
        self._lock = threading.Lock()
        self._running = False

    def start(self, kind):
        """在背景開始一次測試；已有測試在跑時回傳 False。"""
        if kind not in RUNS:
            raise ValueError(f"未知的測試類型: {kind}")
        with self._lock:
            if self._running:
                return False
            self._running = True
        title, fn = RUNS[kind]
        self.state.set("diagnostics", DiagnosticsState(kind=kind, title=title, started_at=time.time()))
        threading.Thread(target=self._run, args=(fn,), name=f"diagnostics-{kind}", daemon=True).start()
        return True

    def run_sync(self, kind):
        """測試用：同步執行並回傳結果（DiagnosticsState）。"""
        if not self.start(kind):
            raise RuntimeError("已有測試正在執行")
        while self.state.get("diagnostics").running:
            time.sleep(0.05)
        return self.state.get("diagnostics")

    def _run(self, fn):
        try:
            fn(self)
        except Exception as e:
            self.check("internal", "內部", "測試執行").finish("fail", f"未預期錯誤: {e}")
        finally:
            def finish(data):
                diag = data.diagnostics
                counts = {}
                for result in diag.results:
                    counts[result.status] = counts.get(result.status, 0) + 1
                diag.running, diag.finished_at, diag.summary = False, time.time(), counts
                return diag.title, counts

            title, counts = self.state.mutate(finish)
            level = "error" if counts.get("fail") else ("warning" if counts.get("warn") else "success")
            icon = {"error": "❌", "warning": "⚠️", "success": "✅"}[level]
            self.service.log(
                f"{icon} {title}完成：通過 {counts.get('pass', 0)}、警告 {counts.get('warn', 0)}、"
                f"失敗 {counts.get('fail', 0)}、略過 {counts.get('skip', 0)}",
                source="test",
            )
            with self._lock:
                self._running = False

    def _push(self, result):
        """把一筆結果寫進共享狀態（同一個 id 會覆蓋，所以執行中 → 完成是同一列）。"""
        def apply(data):
            results = data.diagnostics.results
            snapshot = result.model_copy()
            for index, existing in enumerate(results):
                if existing.id == result.id:
                    results[index] = snapshot
                    return
            results.append(snapshot)

        self.state.mutate(apply)

    def check(self, check_id, group, label):
        return CheckContext(self, check_id, group, label)
