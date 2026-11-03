"""UPS Controller 進入點。

    uv run main.py               # 實機模式：控制迴圈 + Web 介面
    uv run main.py --simulate    # 模擬模式：不連線任何真實設備，可在測試中心跑完整情境
    uv run main.py --no-web      # 只執行控制迴圈（與舊版行為相同）
"""
import argparse
import os

from Core.config import load_settings


def parse_args():
    parser = argparse.ArgumentParser(description="UPS Controller")
    parser.add_argument("--simulate", action="store_true", help="使用模擬的 UPS / Agent / Pterodactyl")
    parser.add_argument("--no-web", action="store_true", help="不啟動 Web 介面，只執行控制迴圈")
    parser.add_argument("--host", help="Web 介面綁定位址（預設讀取 WEB_HOST，否則 127.0.0.1）")
    parser.add_argument("--port", type=int, help="Web 介面埠號（預設讀取 WEB_PORT，否則 8080）")
    return parser.parse_args()


def build(settings):
    """建立控制服務、測試中心與（模擬模式下的）模擬環境。"""
    from Core.controller import ControllerService, PowerStateStore
    from Core.diagnostics import DiagnosticsRunner
    from Core.state import SystemState
    from Core import console_view

    simulator = None
    if settings.simulate:
        from Core.simulator import SimDrivers, SimEnvironment
        state = SystemState(settings, "simulation")
        simulator = SimEnvironment(
            on_change=lambda data: state.set("simulation", data),
            log=lambda level, message: state.add_event(level, "sim", message),
        )
        drivers = SimDrivers(simulator)
        power_store = PowerStateStore(None)
    else:
        from Core.drivers import RealDrivers
        state = SystemState(settings, "real")
        drivers = RealDrivers()
        power_store = PowerStateStore(settings.power_state_path)

    service = ControllerService(settings, drivers, state, power_store, console_view=console_view)
    diagnostics = DiagnosticsRunner(service)
    scenarios = None
    if simulator is not None:
        from Core.scenarios import ScenarioRunner
        state.set("simulation", simulator.to_dict())
        scenarios = ScenarioRunner(service, simulator)
    return service, diagnostics, simulator, scenarios


def main():
    args = parse_args()
    settings = load_settings(simulate=True if args.simulate else None)
    if args.no_web:
        settings.web_enabled = False
    if args.host:
        settings.web_host = args.host
    if args.port:
        settings.web_port = args.port

    service, diagnostics, simulator, scenarios = build(settings)
    if simulator is not None:
        simulator.start()
        print("🧪 模擬模式：所有 UPS / Agent / Pterodactyl 資料皆為模擬，不會對真實設備送出任何指令")

    if not settings.web_enabled:
        try:
            service.run_forever()
        except KeyboardInterrupt:
            pass
        return

    import uvicorn
    from Web.server import create_app

    app = create_app(service, diagnostics, simulator, scenarios)
    service.start()
    if settings.web_host not in ("127.0.0.1", "localhost") and not settings.web_token:
        print("⚠️ Web 介面對外開放但未設定 WEB_TOKEN，任何人都能操作測試與控制功能")
    print(f"🌐 Web 介面：http://{settings.web_host}:{settings.web_port}")
    try:
        uvicorn.run(app, host=settings.web_host, port=settings.web_port, log_level="warning", access_log=False)
    finally:
        service.stop()
        if simulator is not None:
            simulator.stop()


if __name__ == "__main__":
    main()
