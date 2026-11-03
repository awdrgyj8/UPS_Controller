"""情境測試（僅模擬模式）：自動操作模擬環境，驗證控制器在各種情況下的實際行為。"""
import threading
import time


class ScenarioFailed(Exception):
    pass


class ScenarioCancelled(Exception):
    pass


class ScenarioRunner:
    SCENARIOS = {
        "full_outage": {
            "title": "完整停電 → 自動關機 → 復電開機",
            "description": "市電中斷、電量降至門檻後，驗證控制器依序關閉面板伺服器與節點，"
                           "市電恢復後送出 Wake-on-LAN 並讓所有節點重新上線。",
        },
        "power_blip": {
            "title": "短暫停電（未達門檻）",
            "description": "市電中斷數秒後恢復，電量未降到門檻，驗證控制器不會執行任何關機動作。",
        },
        "stuck_server": {
            "title": "伺服器無法關閉 → 逾時",
            "description": "其中一台遊戲伺服器卡在 stopping，驗證控制器等待逾時後跳過節點關機、不更新電源狀態。",
        },
        "agent_reject": {
            "title": "Agent 拒絕簽章",
            "description": "其中一個 Agent 回應 invalid signature，觀察控制器對部分節點關機失敗的處理方式。",
        },
        "ptero_down": {
            "title": "停電時面板無法連線",
            "description": "Pterodactyl 面板故障時發生停電，觀察控制器是否仍能保護節點。",
        },
        "nut_down": {
            "title": "NUT Server 斷線",
            "description": "NUT 無回應時，驗證控制器略過控制流程且不做任何動作，恢復後回到監控狀態。",
        },
    }

    def __init__(self, service, env):
        self.service = service
        self.env = env
        self.state = service.state
        self.settings = service.settings
        self._lock = threading.Lock()
        self._running = False
        self._cancel = threading.Event()
        self._started_at = 0.0

    def list(self):
        return [{"id": key, **value} for key, value in self.SCENARIOS.items()]

    # ------------------------------------------------------------------ 執行
    def start(self, name):
        if name not in self.SCENARIOS:
            raise KeyError(f"未知的情境: {name}")
        with self._lock:
            if self._running:
                return False
            self._running = True
        self._cancel.clear()
        self._started_at = time.time()
        self.state.set("scenario", {
            "id": name, "title": self.SCENARIOS[name]["title"], "running": True, "result": "running",
            "started_at": self._started_at, "finished_at": None, "detail": "", "steps": [],
        })
        threading.Thread(target=self._run, args=(name,), name=f"scenario-{name}", daemon=True).start()
        return True

    def cancel(self):
        self._cancel.set()

    def _run(self, name):
        self.service.log(f"▶ 開始情境測試：{self.SCENARIOS[name]['title']}", level="info", source="test")
        result, detail = "pass", "全部步驟通過"
        try:
            if self.service.paused:
                raise ScenarioFailed("自動控制已暫停，請先恢復自動控制")
            getattr(self, f"_scenario_{name}")()
            steps = self.state.get("scenario")["steps"]
            if any(step["status"] == "warn" for step in steps):
                result, detail = "warn", "流程完成，但發現需要注意的行為（見黃色步驟）"
        except ScenarioFailed as e:
            result, detail = "fail", str(e)
        except ScenarioCancelled:
            result, detail = "cancelled", "已手動停止"
        except Exception as e:
            result, detail = "fail", f"未預期錯誤: {e}"
        finally:
            self._cleanup()

            def finish(data):
                scenario = data["scenario"]
                scenario.update(running=False, result=result, detail=detail, finished_at=time.time())
                for step in scenario["steps"]:
                    if step["status"] in ("running", "pending"):
                        step["status"] = "fail" if result == "fail" else "skip"

            self.state.mutate(finish)
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "cancelled": "⚠️"}[result]
            self.service.log(f"{icon} 情境測試結束：{self.SCENARIOS[name]['title']} — {detail}", source="test")
            with self._lock:
                self._running = False

    def _cleanup(self):
        """解除所有故障注入並恢復市電，讓環境回到可用狀態。"""
        self.env.set_speed(10)
        if not self.env.nut_reachable:
            self.env.set_nut_reachable(True)
        if not self.env.ptero_reachable:
            self.env.set_ptero_reachable(True)
        for agent in self.env.agents:
            if agent.fault != "none":
                self.env.set_agent_fault(agent.index, "none")
        for server in self.env.servers:
            if server.stuck:
                self.env.set_server_stuck(server.identifier, False)
        if not self.env.grid_online:
            self.env.set_grid(True)
        self.service.trigger_poll()

    # ------------------------------------------------------------------ 步驟工具
    def _add_step(self, label):
        step = {"label": label, "status": "running", "detail": "", "started_at": time.time(), "duration_ms": None}

        def apply(data):
            data["scenario"]["steps"].append(step)
            return len(data["scenario"]["steps"]) - 1

        return self.state.mutate(apply)

    def _finish_step(self, index, status, detail=""):
        def apply(data):
            step = data["scenario"]["steps"][index]
            step.update(status=status, detail=detail,
                        duration_ms=round((time.time() - step["started_at"]) * 1000))

        self.state.mutate(apply)

    def action(self, label, fn, detail=""):
        self._check_cancel()
        index = self._add_step(label)
        fn()
        self.service.trigger_poll()
        self._finish_step(index, "pass", detail)

    def wait_for(self, label, predicate, timeout, describe=None):
        self._check_cancel()
        index = self._add_step(label)
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_cancel()
            if predicate():
                self._finish_step(index, "pass", describe() if describe else "")
                return
            time.sleep(0.2)
        detail = f"等待逾時（{timeout:.0f} 秒）" + (f"：{describe()}" if describe else "")
        self._finish_step(index, "fail", detail)
        raise ScenarioFailed(f"{label} — {detail}")

    def expect(self, label, condition, detail_ok="", detail_fail="", warn=False):
        """立即檢查條件；warn=True 時條件不成立只標記為警告（代表發現值得注意的行為）。"""
        self._check_cancel()
        index = self._add_step(label)
        if condition:
            self._finish_step(index, "pass", detail_ok)
            return True
        self._finish_step(index, "warn" if warn else "fail", detail_fail)
        if not warn:
            raise ScenarioFailed(f"{label} — {detail_fail}")
        return False

    def note(self, label, detail, status="warn"):
        index = self._add_step(label)
        self._finish_step(index, status, detail)

    def pause(self, label, seconds):
        self._check_cancel()
        index = self._add_step(label)
        if self._cancel.wait(seconds):
            raise ScenarioCancelled()
        self._finish_step(index, "pass")

    def _check_cancel(self):
        if self._cancel.is_set():
            raise ScenarioCancelled()

    # ------------------------------------------------------------------ 狀態查詢
    def _agents(self):
        return self.state.get("agents")

    def _all_agents_online(self):
        agents = self._agents()
        return bool(agents) and all(agent["online"] for agent in agents)

    def _online_count(self):
        return f"在線 {sum(1 for a in self._agents() if a['online'])}/{len(self._agents())}"

    def _controller(self):
        return self.state.get("controller")

    def _sequence(self, kind=None):
        sequence = self._controller()["sequence"]
        if sequence is None or sequence["started_at"] < self._started_at:
            return None
        if kind and sequence["kind"] != kind:
            return None
        return sequence

    def _sequence_step(self, step_id):
        sequence = self._sequence()
        if sequence is None:
            return None
        for step in sequence["steps"]:
            if step["id"] == step_id:
                return step
        return None

    def _sim_agents_power(self, power):
        return all(agent.power == power for agent in self.env.agents)

    def _threshold(self):
        return self.settings.shutdown_battery_threshold

    # ------------------------------------------------------------------ 共同前置
    def _prepare(self):
        def reset():
            self.env.reset()
            self.service.power_store.set_expected(True)
            self.state.update("controller", expected_power_state=True)

        self.action("重設模擬環境（市電正常、電量 100%、節點全部開機）", reset)
        self.wait_for("控制器確認所有節點在線", self._all_agents_online, 20, self._online_count)
        self._started_at = time.time()

    def _outage_at_threshold(self, label="切斷市電，並將電量設為關機門檻"):
        threshold = self._threshold()

        def outage():
            self.env.set_grid(False)
            self.env.set_battery(threshold)

        self.action(label, outage, f"電量 {threshold}%")

    # ------------------------------------------------------------------ 情境
    def _scenario_full_outage(self):
        threshold = self._threshold()
        self._prepare()
        self.action("切斷市電", lambda: self.env.set_grid(False))
        self.wait_for("控制器偵測到 UPS 改由電池供電", lambda: self.state.get("ups")["power"] is False, 10,
                      lambda: f"UPS 狀態 {self.state.get('ups')['status']}")
        self.wait_for("電量高於門檻：控制器持續監控、不動作", lambda: self._controller()["phase"] == "on_battery", 10,
                      lambda: self._controller()["decision"])

        def fast_forward():
            self.env.set_battery(threshold + 2)
            self.env.set_speed(20)

        self.action(f"時間快轉：電量降到 {threshold + 2}%、放電速度 ×20", fast_forward)
        self.wait_for(f"電量降至 {threshold}% 以下，控制器啟動關機程序",
                      lambda: self._sequence("shutdown") is not None, 40,
                      lambda: f"電量 {self.state.get('ups')['battery']}%")
        self.env.set_speed(10)
        self.wait_for("面板伺服器全部關閉", lambda: all(s.state == "offline" for s in self.env.servers), 40,
                      lambda: "、".join(f"{s.name}:{s.state}" for s in self.env.servers))
        self.wait_for("所有節點收到簽章關機請求並關機", lambda: self._sim_agents_power("off"), 30,
                      lambda: "、".join(f"{a.name}:{a.power}" for a in self.env.agents))
        self.wait_for("powerState 更新為「關機」", lambda: self.service.power_store.expected() is False, 10)
        self.wait_for("控制器進入「節點已關機，等待市電恢復」", lambda: self._controller()["phase"] == "nodes_off", 10,
                      lambda: self._controller()["phase_label"])
        self.action("恢復市電", lambda: self.env.set_grid(True))
        self.wait_for("控制器送出 Wake-on-LAN",
                      lambda: (self._sequence("wake") or {}).get("result") == "success", 30,
                      lambda: f"已送出 {self.env.wol_packets} 個封包")
        self.wait_for("powerState 更新為「開機」", lambda: self.service.power_store.expected() is True, 10)
        self.wait_for("所有節點開機並重新上線", self._all_agents_online, 40, self._online_count)

    def _scenario_power_blip(self):
        self._prepare()
        self.action("切斷市電", lambda: self.env.set_grid(False))
        self.wait_for("控制器偵測到電池供電並持續監控", lambda: self._controller()["phase"] == "on_battery", 10,
                      lambda: self._controller()["decision"])
        self.pause("維持停電 4 秒", 4)
        self.action("恢復市電", lambda: self.env.set_grid(True))
        self.wait_for("控制器回到「監控中」", lambda: self._controller()["phase"] == "monitoring"
                      and self.state.get("ups")["power"] is True, 10)
        self.expect("沒有執行任何關機程序", self._sequence() is None,
                    "電量未達門檻，控制器未動作", "控制器不應啟動關機程序")
        self.expect("所有節點維持在線", self._all_agents_online(), self._online_count(), self._online_count())

    def _scenario_stuck_server(self):
        self._prepare()
        server = self.env.servers[0]
        self.action(f"故障注入：伺服器「{server.name}」無法關閉",
                    lambda: self.env.set_server_stuck(server.identifier, True))
        self._outage_at_threshold()
        self.wait_for("控制器啟動關機程序", lambda: self._sequence("shutdown") is not None, 15)
        timeout = self.settings.server_stop_max_attempts * self.settings.server_stop_check_interval + 20
        self.wait_for("等待伺服器關機逾時 → 跳過節點關機",
                      lambda: (self._sequence_step("wait_servers") or {}).get("status") == "failed", timeout,
                      lambda: (self._sequence_step("wait_servers") or {}).get("detail", ""))
        self.expect("沒有送出節點關機請求", all(agent.shutdown_requests == 0 for agent in self.env.agents),
                    "所有 Agent 皆未收到 /shutdown", "有 Agent 收到關機請求")
        self.expect("powerState 維持「開機」", self.service.power_store.expected() is True,
                    "下一輪會重新嘗試關機程序", "powerState 不應被更新")

    def _scenario_agent_reject(self):
        self._prepare()
        target = self.env.agents[0]
        self.action(f"故障注入：{target.name} 拒絕簽章", lambda: self.env.set_agent_fault(target.index, "reject"))
        self._outage_at_threshold()
        self.wait_for("控制器送出節點關機請求後回報失敗",
                      lambda: (self._sequence_step("shutdown_agents") or {}).get("status") == "failed", 40,
                      lambda: (self._sequence_step("shutdown_agents") or {}).get("detail", ""))
        self.expect("powerState 維持「開機」", self.service.power_store.expected() is True,
                    "依現行邏輯不更新電源狀態", "powerState 不應被更新")
        others = [agent for agent in self.env.agents if agent.index != target.index]
        if others:
            self.wait_for("其他節點仍收到關機請求", lambda: all(agent.shutdown_requests > 0 for agent in others), 10)
            self.note("發現：部分節點已關機但 powerState 仍為「開機」",
                      "現行邏輯在部分節點失敗時不更新 powerState；市電恢復後控制器判斷為「維持開機」，"
                      "已關機的節點不會收到 WOL，需要手動喚醒。")
        self.action("解除故障並恢復市電", self._cleanup)
        self.pause("等待 6 秒觀察復電後狀態", 6)
        offline = [agent.name for agent in self.env.agents if agent.power != "on"]
        self.expect("復電後所有節點恢復運作", not offline, "全部節點在線",
                    f"{'、'.join(offline)} 仍為關機狀態（未被 WOL 喚醒）", warn=True)

    def _scenario_ptero_down(self):
        self._prepare()
        self.action("故障注入：Pterodactyl 面板無法連線", lambda: self.env.set_ptero_reachable(False))
        self._outage_at_threshold()
        self.wait_for("控制器嘗試關機程序但取不到伺服器清單",
                      lambda: (self._sequence_step("list_servers") or {}).get("status") == "failed", 15,
                      lambda: (self._sequence() or {}).get("detail", ""))
        self.expect("節點未被關機", self._sim_agents_power("on"), "所有節點仍在運作", "有節點被關機")
        self.note("發現：面板故障時節點不會被關機",
                  "依現行邏輯，取不到伺服器清單就跳過節點關機；若停電持續，UPS 電量耗盡時節點會直接斷電。"
                  "可考慮在面板無法連線時仍繼續關閉節點。")

    def _scenario_nut_down(self):
        self._prepare()
        self.action("故障注入：NUT Server 斷線", lambda: self.env.set_nut_reachable(False))
        self.wait_for("控制器進入「UPS 讀取失敗」並略過控制流程",
                      lambda: self._controller()["phase"] == "nut_error", 10,
                      lambda: self._controller()["decision"])
        self.expect("沒有執行任何關機或喚醒", self._sequence() is None, "控制器未動作", "不應執行任何程序")
        self.action("恢復 NUT 連線", lambda: self.env.set_nut_reachable(True))
        self.wait_for("控制器回到「監控中」", lambda: self._controller()["phase"] == "monitoring", 10)
