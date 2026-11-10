"""Web 介面後端：提供 REST API、SSE 即時串流，並直接送出 Web/static 裡的前端檔案（不需要編譯）。"""
import asyncio
import hmac
import json
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).resolve().parent / "static"


class FrontendFiles(StaticFiles):
    """前端是未打包的原始檔，檔名不帶版本：要求瀏覽器每次都先向伺服器確認，更新後才不會用到舊檔。"""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class PowerStateBody(BaseModel):
    state: bool


class BoolBody(BaseModel):
    value: bool


class NumberBody(BaseModel):
    value: float


class FaultBody(BaseModel):
    fault: str


class AgentPowerBody(BaseModel):
    power: str


def create_app(service, diagnostics, simulator=None, scenarios=None):
    settings = service.settings
    state = service.state
    app = FastAPI(title="UPS Controller", docs_url="/api/docs", openapi_url="/api/openapi.json")

    # ---- 驗證（設定 WEB_TOKEN 才啟用）----
    def require_token(request: Request):
        if not settings.web_token:
            return
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
        if not hmac.compare_digest(token, settings.web_token):
            raise HTTPException(status_code=401, detail="需要有效的 WEB_TOKEN")

    auth = [Depends(require_token)]

    def require_sim():
        if simulator is None:
            raise HTTPException(status_code=409, detail="此功能僅在模擬模式（--simulate）下可用")

    # ---- 狀態 ----
    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": service.drivers.mode, "auth_required": bool(settings.web_token)}

    @app.get("/api/state", dependencies=auth)
    def get_state():
        return state.snapshot()

    @app.get("/api/history", dependencies=auth)
    def get_history(minutes: float = 60):
        return {"samples": state.history(since_ts=time.time() - minutes * 60)}

    @app.get("/api/events", dependencies=auth)
    def get_events(limit: int = 500, level: str | None = None):
        return {"events": state.events(limit=min(limit, 1000), level=level)}

    @app.get("/api/stream", dependencies=auth)
    async def stream(request: Request):
        async def generator():
            last_version = -1
            last_seq = state.history_seq
            last_beat = 0.0
            while not await request.is_disconnected():
                if state.version != last_version:
                    last_version = state.version
                    yield f"event: state\ndata: {json.dumps(state.snapshot(), ensure_ascii=False)}\n\n"
                samples = state.history(since_seq=last_seq)
                if samples:
                    last_seq = samples[-1]["seq"]
                    yield f"event: samples\ndata: {json.dumps(samples)}\n\n"
                if time.time() - last_beat > 15:
                    last_beat = time.time()
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(generator(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- 控制 ----
    @app.post("/api/control/poll", dependencies=auth)
    def control_poll():
        service.trigger_poll()
        return {"ok": True}

    @app.post("/api/control/refresh", dependencies=auth)
    def control_refresh():
        service.read_ups()
        service.refresh_status()
        return {"ok": True}

    @app.post("/api/control/pause", dependencies=auth)
    def control_pause(body: BoolBody):
        service.set_paused(body.value)
        return {"ok": True, "paused": service.paused}

    @app.post("/api/control/expected-state", dependencies=auth)
    def control_expected(body: PowerStateBody):
        service.set_expected_power_state(body.state)
        return {"ok": True}

    # ---- Agent 操作 ----
    @app.post("/api/agents/{index}/{action}", dependencies=auth)
    def agent_action(index: int, action: str):
        if action not in ("status", "verify", "wol"):
            raise HTTPException(status_code=404, detail="未知的操作")
        try:
            return service.agent_action(index, action)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # ---- 測試中心 ----
    @app.post("/api/diagnostics/{kind}", dependencies=auth)
    def run_diagnostics(kind: str):
        try:
            started = diagnostics.start(kind)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        if not started:
            raise HTTPException(status_code=409, detail="已有測試正在執行")
        return {"ok": True}

    # ---- 模擬器 ----
    @app.get("/api/sim/scenarios", dependencies=auth)
    def list_scenarios():
        require_sim()
        return {"scenarios": scenarios.list()}

    @app.post("/api/sim/scenarios/{name}", dependencies=auth)
    def run_scenario(name: str):
        require_sim()
        if name == "cancel":
            scenarios.cancel()
            return {"ok": True}
        try:
            started = scenarios.start(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        if not started:
            raise HTTPException(status_code=409, detail="已有情境測試正在執行")
        return {"ok": True}

    @app.post("/api/sim/grid", dependencies=auth)
    def sim_grid(body: BoolBody):
        require_sim()
        simulator.set_grid(body.value)
        service.trigger_poll()
        return {"ok": True}

    @app.post("/api/sim/battery", dependencies=auth)
    def sim_battery(body: NumberBody):
        require_sim()
        simulator.set_battery(body.value)
        return {"ok": True}

    @app.post("/api/sim/speed", dependencies=auth)
    def sim_speed(body: NumberBody):
        require_sim()
        simulator.set_speed(body.value)
        return {"ok": True}

    @app.post("/api/sim/nut", dependencies=auth)
    def sim_nut(body: BoolBody):
        require_sim()
        simulator.set_nut_reachable(body.value)
        return {"ok": True}

    @app.post("/api/sim/ptero", dependencies=auth)
    def sim_ptero(body: BoolBody):
        require_sim()
        simulator.set_ptero_reachable(body.value)
        return {"ok": True}

    @app.post("/api/sim/agents/{index}/fault", dependencies=auth)
    def sim_agent_fault(index: int, body: FaultBody):
        require_sim()
        try:
            simulator.set_agent_fault(index, body.fault)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"ok": True}

    @app.post("/api/sim/agents/{index}/power", dependencies=auth)
    def sim_agent_power(index: int, body: AgentPowerBody):
        require_sim()
        try:
            simulator.set_agent_power(index, body.power)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"ok": True}

    @app.post("/api/sim/servers/{identifier}/stuck", dependencies=auth)
    def sim_server_stuck(identifier: str, body: BoolBody):
        require_sim()
        try:
            simulator.set_server_stuck(identifier, body.value)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"ok": True}

    @app.post("/api/sim/reset", dependencies=auth)
    def sim_reset():
        require_sim()
        simulator.reset()
        service.power_store.set_expected(True)
        state.update("controller", expected_power_state=True)
        service.log("[模擬] 模擬環境已重設", level="info", source="web")
        service.trigger_poll()
        return {"ok": True}

    # ---- 前端 ----
    app.mount("/", FrontendFiles(directory=STATIC_DIR, html=True), name="frontend")

    return app
