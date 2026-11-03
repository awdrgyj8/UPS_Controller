"""測試中心：系統自檢與停電演練（乾跑）。

兩者都不會造成任何副作用：
  * 不會送出伺服器 stop 訊號
  * 不會送出節點關機請求（改用 /verify 簽章驗證端點）
  * 不會送出 Wake-on-LAN 封包（只檢查 MAC 格式）
"""
import threading
import time

from Core.controller import decide
from Core.drivers import DriverError

REQUIRED_UPS_VARS = ["ups.status", "battery.charge"]
RECOMMENDED_UPS_VARS = ["battery.runtime", "ups.load", "input.voltage", "output.voltage"]


class CheckContext:
    """單一檢查項目的結果紀錄。"""

    def __init__(self, runner, check_id, group, label):
        self.runner = runner
        self.result = {"id": check_id, "group": group, "label": label, "status": "running",
                       "detail": "", "duration_ms": None, "dry_run": False}
        self._started = time.monotonic()
        runner._push(self.result)

    def finish(self, status, detail, dry_run=False):
        self.result.update(status=status, detail=detail, dry_run=dry_run,
                           duration_ms=round((time.monotonic() - self._started) * 1000))
        self.runner._push(self.result)
        return status


class DiagnosticsRunner:
    def __init__(self, service):
        self.service = service
        self.drivers = service.drivers
        self.state = service.state
        self.settings = service.settings
        self._lock = threading.Lock()
        self._running = False

    # ------------------------------------------------------------------ 執行
    def start(self, kind):
        runs = {"selftest": ("系統自檢", self._selftest), "drill": ("停電演練（乾跑）", self._drill)}
        if kind not in runs:
            raise ValueError(f"未知的測試類型: {kind}")
        with self._lock:
            if self._running:
                return False
            self._running = True
        title, fn = runs[kind]
        self.state.set("diagnostics", {"kind": kind, "title": title, "running": True, "started_at": time.time(),
                                       "finished_at": None, "summary": None, "results": []})
        threading.Thread(target=self._run, args=(fn,), name=f"diagnostics-{kind}", daemon=True).start()
        return True

    def run_sync(self, kind):
        """測試用：同步執行並回傳結果。"""
        if not self.start(kind):
            raise RuntimeError("已有測試正在執行")
        while self.state.get("diagnostics")["running"]:
            time.sleep(0.05)
        return self.state.get("diagnostics")

    def _run(self, fn):
        try:
            fn()
        except Exception as e:
            CheckContext(self, "internal", "內部", "測試執行").finish("fail", f"未預期錯誤: {e}")
        finally:
            def finish(data):
                diag = data["diagnostics"]
                counts = {}
                for result in diag["results"]:
                    counts[result["status"]] = counts.get(result["status"], 0) + 1
                diag.update(running=False, finished_at=time.time(), summary=counts)

            self.state.mutate(finish)
            summary = self.state.get("diagnostics")
            counts = summary["summary"]
            level = "error" if counts.get("fail") else ("warning" if counts.get("warn") else "success")
            icon = {"error": "❌", "warning": "⚠️", "success": "✅"}[level]
            self.service.log(
                f"{icon} {summary['title']}完成：通過 {counts.get('pass', 0)}、警告 {counts.get('warn', 0)}、"
                f"失敗 {counts.get('fail', 0)}、略過 {counts.get('skip', 0)}",
                source="test",
            )
            with self._lock:
                self._running = False

    def _push(self, result):
        def apply(data):
            results = data["diagnostics"]["results"]
            for index, existing in enumerate(results):
                if existing["id"] == result["id"]:
                    results[index] = dict(result)
                    return
            results.append(dict(result))

        self.state.mutate(apply)

    def check(self, check_id, group, label):
        return CheckContext(self, check_id, group, label)

    # ------------------------------------------------------------------ 共用檢查
    def _check_agent_config(self):
        ctx = self.check("config.agents", "設定", "AgentInfo 設定")
        agents, error = self.drivers.agent_configs()
        if error:
            ctx.finish("fail", error)
            return []
        if not agents:
            ctx.finish("warn", "AgentInfo 是空陣列，停電時不會關閉任何節點")
            return []
        problems = []
        seen = set()
        for index, agent in enumerate(agents, start=1):
            name = agent.get("name", f"Agent {index}")
            for field in ("ip", "port", "mac"):
                if field not in agent or agent[field] in ("", None):
                    problems.append(f"{name} 缺少 {field}")
            key = (agent.get("ip"), agent.get("port"))
            if key in seen:
                problems.append(f"{name} 的 ip:port 重複")
            seen.add(key)
        if problems:
            ctx.finish("fail", "；".join(problems))
        else:
            ctx.finish("pass", f"共 {len(agents)} 個 Agent，必要欄位齊全")
        return agents

    def _read_ups(self):
        ctx = self.check("nut.connect", "UPS / NUT", "NUT Server 連線")
        target = self.drivers.nut_target()
        where = f"{target['host']}:{target['port']} / UPS 名稱 {target['ups_name']}"
        started = time.monotonic()
        try:
            variables = self.drivers.ups_variables()
        except DriverError as e:
            ctx.finish("fail", f"{where} 連線失敗：{e}")
            return None
        latency = round((time.monotonic() - started) * 1000)
        ctx.finish("pass", f"{where}，讀取 {len(variables)} 個變數，耗時 {latency} ms")
        return variables

    # ------------------------------------------------------------------ 系統自檢
    def _selftest(self):
        threshold = self.settings.shutdown_battery_threshold

        # ---- 設定 ----
        agents = self._check_agent_config()
        ctx = self.check("config.nut", "設定", "NUT 設定")
        target = self.drivers.nut_target()
        missing = [name for name, value in (("NUT_ServerIP", target["host"]), ("NUT_ServerPort", target["port"]),
                                            ("NUT_UPS_NAME", target["ups_name"])) if not value]
        ctx.finish("fail" if missing else "pass",
                   f"缺少 {', '.join(missing)}" if missing else f"{target['host']}:{target['port']} ({target['ups_name']})")

        ctx = self.check("config.ptero", "設定", "Pterodactyl 設定")
        if self.drivers.ptero_configured():
            ctx.finish("pass", self.drivers.ptero_url())
        else:
            ctx.finish("fail", "PteroApi_Url / AppKey / ClientKey 未設定：停電時會因取不到伺服器清單而跳過節點關機")

        ctx = self.check("config.ptero_info", "設定", "PteroInfo（Pterodactyl node 對應主機）")
        ptero_info, error = self.drivers.ptero_info()
        problems = [error] if error else []
        names = {str(agent.get(key)) for agent in agents for key in ("name", "ip") if agent.get(key)}
        problems += [f"agent「{entry['agent']}」不在 AgentInfo 裡" for entry in ptero_info if str(entry["agent"]) not in names]
        legacy = [agent.get("name", agent.get("ip", "?")) for agent in agents if "ptero_node" in agent]
        if problems:
            ctx.finish("fail", "；".join(problems))
        elif legacy:
            ctx.finish("warn", f"AgentInfo 的 ptero_node 已不再使用（{'、'.join(legacy)}），請改寫到 PteroInfo")
        elif ptero_info:
            ctx.finish("pass", "、".join(f"node {entry['node']} → {entry['agent']}" for entry in ptero_info))
        else:
            ctx.finish("skip", "未設定，改用自動比對（node FQDN 等於 Agent IP / hostname，或名稱相同）")

        ctx = self.check("config.threshold", "設定", "關機電量門檻")
        if 10 <= threshold <= 95:
            ctx.finish("pass", f"電池供電且電量 ≤ {threshold}% 時啟動關機程序")
        else:
            ctx.finish("warn", f"門檻 {threshold}% 不在建議範圍 10–95% 內")

        ctx = self.check("key.private", "設定", "簽章私鑰")
        ok, detail = self.drivers.signing_key_check()
        ctx.finish("pass" if ok else "fail", detail)

        ctx = self.check("state.power_file", "設定", "電源狀態檔讀寫")
        try:
            data = self.service.power_store.read()
            state = str(data["AgentPowerState"]).lower()
            if self.service.power_store.writable():
                ctx.finish("pass", f"AgentPowerState = {state}（可讀寫）")
            else:
                ctx.finish("fail", f"AgentPowerState = {state}，但檔案沒有寫入權限：關機/喚醒後無法更新狀態")
        except (OSError, ValueError, KeyError) as e:
            ctx.finish("fail", f"讀取失敗：{e}")

        # ---- UPS ----
        variables = self._read_ups()
        ctx = self.check("nut.variables", "UPS / NUT", "UPS 必要數據")
        if variables is None:
            ctx.finish("skip", "NUT 無法連線")
        else:
            missing_required = [name for name in REQUIRED_UPS_VARS if name not in variables]
            missing_recommended = [name for name in RECOMMENDED_UPS_VARS if name not in variables]
            if missing_required:
                ctx.finish("fail", f"缺少必要變數 {', '.join(missing_required)}，控制流程無法判斷")
            elif missing_recommended:
                ctx.finish("warn", f"缺少建議變數 {', '.join(missing_recommended)}（介面部分數據無法顯示）")
            else:
                ctx.finish("pass", "ups.status、battery.charge、battery.runtime、ups.load、輸入/輸出電壓皆可讀取")

        ctx = self.check("nut.status", "UPS / NUT", "UPS 狀態判讀")
        if variables is None:
            ctx.finish("skip", "NUT 無法連線")
        else:
            tokens = variables.get("ups.status", "").split()
            status = variables.get("ups.status", "UNKNOWN")
            if "LB" in tokens or "FSD" in tokens or "OFF" in tokens:
                ctx.finish("fail", f"UPS 狀態 {status}：電量低或已強制關機")
            elif "OB" in tokens:
                ctx.finish("warn", f"UPS 狀態 {status}：目前為電池供電")
            elif any(token in tokens for token in ("RB", "OVER", "BYPASS", "ALARM")):
                ctx.finish("warn", f"UPS 狀態 {status}：請檢查 UPS（需換電池 / 過載 / 旁路 / 警報）")
            else:
                ctx.finish("pass", f"UPS 狀態 {status}")

        ctx = self.check("nut.runtime", "UPS / NUT", "關機時間餘裕評估")
        if variables is None:
            ctx.finish("skip", "NUT 無法連線")
        else:
            try:
                battery = float(variables["battery.charge"])
                runtime = float(variables["battery.runtime"])
                at_threshold = runtime * threshold / battery if battery > 0 else 0
                worst = (self.settings.server_stop_max_attempts * self.settings.server_stop_check_interval
                         + self.settings.poll_interval + 60)
                detail = (f"以目前負載估算，電量降到 {threshold}% 時約剩 {at_threshold / 60:.1f} 分鐘續航；"
                          f"關機程序最長約需 {worst / 60:.1f} 分鐘（含輪詢間隔與節點關機緩衝）")
                ctx.finish("pass" if at_threshold >= worst * 1.5 else "warn", detail)
            except (KeyError, ValueError):
                ctx.finish("skip", "缺少 battery.charge / battery.runtime")

        # ---- Pterodactyl ----
        servers = self._check_ptero()

        # ---- Agents ----
        for index, agent in enumerate(agents, start=1):
            name = agent.get("name", f"Agent {index}")
            group = f"節點 {name}"
            ctx = self.check(f"agent.{index}.status", group, "連線 (/status)")
            status = self.drivers.agent_status(agent, index)
            if status["online"]:
                extra = "" if "verify" in status.get("capabilities", []) else "；Agent 版本較舊，不支援 /verify"
                ctx.finish("pass" if not extra else "warn",
                           f"hostname={status['hostname']}，延遲 {status['latency_ms']} ms{extra}")
            else:
                ctx.finish("fail", status["error"] or "離線")

            ctx = self.check(f"agent.{index}.verify", group, "簽章驗證 (/verify)")
            if not status["online"]:
                ctx.finish("skip", "Agent 離線")
            else:
                ok, detail = self.drivers.agent_verify(agent)
                ctx.finish("pass" if ok else ("warn" if "不支援" in detail else "fail"),
                           "Agent 接受 Controller 簽章（時間戳與 nonce 檢查通過）" if ok else detail)

            ctx = self.check(f"agent.{index}.wol", group, "Wake-on-LAN 設定")
            mac = agent.get("mac", "")
            if self.drivers.valid_mac(mac):
                ctx.finish("pass", f"MAC {mac} 格式正確（未送出封包）")
            else:
                ctx.finish("fail", f"MAC 格式不正確：{mac!r}")

        # ---- 控制邏輯 ----
        ctx = self.check("logic.current", "控制邏輯", "目前判斷結果")
        if variables is None:
            ctx.finish("warn", "NUT 無法連線：控制器會略過每一輪控制流程")
        else:
            from Api.NutClient import buildUpsSnapshot
            snapshot = buildUpsSnapshot(variables)
            expected = self.service.power_store.expected()
            action = decide(snapshot, expected, threshold)
            labels = {
                "shutdown": ("warn", "條件成立：下一輪將執行關機程序"),
                "hold_on": ("pass", "維持開機（未達關機條件）"),
                "wake": ("warn", "節點預期為關機但市電正常：下一輪將發送 WOL"),
                "hold_off": ("pass", "節點關機中，等待市電恢復"),
            }
            status_value, detail = labels[action]
            ctx.finish(status_value, f"預期電源={'開機' if expected else '關機'}，"
                                     f"市電={'正常' if snapshot['power'] else '中斷'}，電量 {snapshot['battery']}% → {detail}")

        ctx = self.check("logic.consistency", "控制邏輯", "預期狀態與實際一致性")
        expected = self.service.power_store.expected()
        online = sum(1 for agent in self.state.get("agents") if agent["online"])
        total = len(agents)
        if total == 0:
            ctx.finish("skip", "沒有 Agent")
        elif expected and online < total:
            ctx.finish("warn", f"預期節點為開機，但只有 {online}/{total} 個 Agent 在線")
        elif not expected and online > 0:
            ctx.finish("warn", f"預期節點為關機，但有 {online} 個 Agent 在線")
        else:
            ctx.finish("pass", f"預期={'開機' if expected else '關機'}，在線 {online}/{total}")

    def _check_ptero(self):
        ctx = self.check("ptero.application", "Pterodactyl", "Application API（伺服器清單）")
        if not self.drivers.ptero_configured():
            ctx.finish("fail", "未設定")
            return []
        try:
            servers = self.drivers.ptero_list_servers()
        except DriverError as e:
            ctx.finish("fail", f"讀取失敗：{e}")
            return []
        if not servers:
            ctx.finish("warn", "面板沒有任何伺服器：依現行邏輯，停電時會跳過節點關機流程")
        else:
            ctx.finish("pass", f"共 {len(servers)} 台伺服器")

        ctx = self.check("ptero.nodes", "Pterodactyl", "Application API（節點清單）")
        try:
            nodes = self.drivers.ptero_list_nodes()
            ctx.finish("pass", f"共 {len(nodes)} 個 node：" + "、".join(node["name"] for node in nodes))
        except DriverError as e:
            nodes = []
            ctx.finish("warn", f"讀取失敗（拓撲圖無法對應節點）：{e}")

        ctx = self.check("ptero.client", "Pterodactyl", "Client API（伺服器狀態）")
        if not servers:
            ctx.finish("skip", "沒有伺服器")
        else:
            states = {}
            failed = []
            for server in servers:
                try:
                    state = self.drivers.ptero_server_resources(server["identifier"])["state"]
                    states[state] = states.get(state, 0) + 1
                except DriverError:
                    failed.append(server["identifier"])
            summary = "、".join(f"{key} {value} 台" for key, value in states.items())
            if failed:
                ctx.finish("fail", f"{len(failed)} 台讀取失敗（Client Key 權限不足？）：{', '.join(failed)}")
            else:
                ctx.finish("pass", summary)

        ctx = self.check("ptero.mapping", "Pterodactyl", "伺服器與 Agent 對應")
        agents = self.state.get("agents")
        if not nodes:
            ctx.finish("skip", "沒有 node 資料")
        else:
            from Core.controller import map_nodes_to_agents
            ptero_info, _ = self.drivers.ptero_info()
            mapping, problems = map_nodes_to_agents(agents, nodes, ptero_info)
            agent_names = {agent["index"]: agent["name"] for agent in agents}
            unmapped_nodes = [node for node in nodes if node["id"] not in mapping]
            unmapped = [server["name"] for server in servers if server.get("node_id") not in mapping]
            if problems or unmapped_nodes:
                parts = list(problems)
                if unmapped_nodes:
                    parts.append("未對應的 node：" + "、".join(f"#{node['id']} {node['name']}" for node in unmapped_nodes)
                                 + f"（{len(unmapped)} 台伺服器）。請在 PteroInfo 加上，例如 "
                                 + f'{{"node":{unmapped_nodes[0]["id"]},"agent":"主機名稱"}}')
                ctx.finish("warn", "；".join(parts))
            elif nodes:
                ctx.finish("pass", "、".join(f"#{node['id']} {node['name']} → {agent_names.get(mapping[node['id']], '?')}"
                                            for node in nodes))
            else:
                ctx.finish("pass", "所有伺服器都能對應到 Agent")
        return servers

    # ------------------------------------------------------------------ 停電演練（乾跑）
    def _drill(self):
        threshold = self.settings.shutdown_battery_threshold

        ctx = self.check("drill.trigger", "1. 停電判斷", "模擬：電池供電且電量達門檻")
        fake = {"ok": True, "power": False, "battery": threshold, "status": "OB DISCHRG", "error": ""}
        action = decide(fake, True, threshold)
        ctx.finish("pass" if action == "shutdown" else "fail",
                   f"輸入 OB / {threshold}% / 預期開機 → 判斷結果「{action}」", dry_run=True)
        fake_high = dict(fake, battery=min(threshold + 1, 100))
        ctx = self.check("drill.trigger_high", "1. 停電判斷", "模擬：電池供電但電量高於門檻")
        action = decide(fake_high, True, threshold)
        ctx.finish("pass" if action == "hold_on" else "fail",
                   f"輸入 OB / {fake_high['battery']}% → 判斷結果「{action}」（不應關機）", dry_run=True)

        ctx = self.check("drill.list_servers", "2. 關閉面板伺服器", "取得伺服器清單（實際讀取）")
        servers = []
        if not self.drivers.ptero_configured():
            ctx.finish("fail", "Pterodactyl 未設定：實際停電時會跳過節點關機流程")
        else:
            try:
                servers = self.drivers.ptero_list_servers()
                ctx.finish("pass" if servers else "fail",
                           f"取得 {len(servers)} 台伺服器" if servers else "清單為空：實際停電時會跳過節點關機流程")
            except DriverError as e:
                ctx.finish("fail", f"讀取失敗：{e}（實際停電時會跳過節點關機流程）")

        ctx = self.check("drill.stop_servers", "2. 關閉面板伺服器", "送出 stop 訊號")
        if servers:
            ctx.finish("pass", f"[乾跑] 將對 {len(servers)} 台伺服器送出 stop：" +
                       "、".join(server["name"] or server["identifier"] for server in servers[:10]), dry_run=True)
        else:
            ctx.finish("skip", "沒有伺服器", dry_run=True)

        ctx = self.check("drill.server_state", "2. 關閉面板伺服器", "讀取伺服器狀態（實際讀取）")
        if servers:
            failed = []
            for server in servers:
                try:
                    self.drivers.ptero_server_resources(server["identifier"])
                except DriverError:
                    failed.append(server["identifier"])
            if failed:
                ctx.finish("fail", f"{len(failed)} 台無法讀取狀態，實際停電時會一直等到逾時：{', '.join(failed)}")
            else:
                limit = self.settings.server_stop_max_attempts * self.settings.server_stop_check_interval
                ctx.finish("pass", f"全部可讀取；實際流程最多等待 {limit:.0f} 秒讓伺服器關機")
        else:
            ctx.finish("skip", "沒有伺服器")

        agents, error = self.drivers.agent_configs()
        if error:
            self.check("drill.agents", "3. 關閉節點", "讀取 AgentInfo").finish("fail", error)
        for index, agent in enumerate(agents, start=1):
            name = agent.get("name", f"Agent {index}")
            ctx = self.check(f"drill.agent.{index}", "3. 關閉節點", f"{name} 關機請求")
            ok, detail = self.drivers.agent_verify(agent)
            if ok:
                ctx.finish("pass", "[乾跑] 以 /verify 送出簽章請求，Agent 驗證通過；實際停電時會改送 /shutdown",
                           dry_run=True)
            else:
                ctx.finish("warn" if "不支援" in detail else "fail", f"[乾跑] {detail}", dry_run=True)

        ctx = self.check("drill.save_off", "3. 關閉節點", "更新 powerState 為關機")
        try:
            self.service.power_store.read()
            if self.service.power_store.writable():
                ctx.finish("pass", "[乾跑] powerState 可讀寫（未變更內容）", dry_run=True)
            else:
                ctx.finish("fail", "powerState 沒有寫入權限")
        except (OSError, ValueError) as e:
            ctx.finish("fail", f"讀取失敗：{e}")

        ctx = self.check("drill.wake_trigger", "4. 復電開機", "模擬：節點關機後市電恢復")
        action = decide({"ok": True, "power": True, "battery": threshold, "status": "OL CHRG", "error": ""},
                        False, threshold)
        ctx.finish("pass" if action == "wake" else "fail", f"判斷結果「{action}」", dry_run=True)

        for index, agent in enumerate(agents, start=1):
            name = agent.get("name", f"Agent {index}")
            ctx = self.check(f"drill.wol.{index}", "4. 復電開機", f"{name} Wake-on-LAN")
            mac = agent.get("mac", "")
            if self.drivers.valid_mac(mac):
                ctx.finish("pass", f"[乾跑] 將送出 {self.settings.wol_attempts} 輪 WOL 到 {mac}（未實際送出）",
                           dry_run=True)
            else:
                ctx.finish("fail", f"MAC 格式不正確：{mac!r}")
