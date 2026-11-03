import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# 測試一律使用內建的模擬節點，不讀取本機 .env 的 AgentInfo
os.environ.pop("AgentInfo", None)

from Core.config import load_settings  # noqa: E402
from Core.controller import ControllerService, PowerStateStore  # noqa: E402
from Core.diagnostics import DiagnosticsRunner  # noqa: E402
from Core.simulator import SimDrivers, SimEnvironment  # noqa: E402
from Core.state import SystemState  # noqa: E402


class Harness:
    def __init__(self):
        self.settings = load_settings(simulate=True)
        self.settings.server_stop_max_attempts = 20
        self.settings.server_stop_check_interval = 0.3
        self.settings.wol_attempts = 2
        self.settings.wol_interval = 0.05
        self.state = SystemState(self.settings, "simulation")
        self.env = SimEnvironment(log=lambda level, message: self.state.add_event(level, "sim", message))
        self.drivers = SimDrivers(self.env)
        self.power_store = PowerStateStore(None)
        self.service = ControllerService(self.settings, self.drivers, self.state, self.power_store)
        self.diagnostics = DiagnosticsRunner(self.service)

    def outage(self, battery):
        self.env.set_grid(False)
        self.env.set_battery(battery)

    def advance(self, seconds):
        """不啟動背景執行緒，直接推進模擬時間。"""
        steps = int(seconds / 0.25) + 1
        for _ in range(steps):
            self.env.tick(0.25)


@pytest.fixture
def harness():
    h = Harness()
    h.env.start()
    yield h
    h.service.stop()
    h.env.stop()
