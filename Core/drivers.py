"""硬體/外部服務的存取介面。

RealDrivers 包裝原本的 Api 模組；SimDrivers（見 simulator.py）提供同樣的方法，
讓控制流程在實機與模擬模式下執行完全相同的程式碼。
"""
import os
import time


class DriverError(Exception):
    pass


class RealDrivers:
    mode = "real"

    def __init__(self):
        import requests
        from Api import NutClient, PteroAPI, AgentAPI, WakeOnLan
        self._requests = requests
        self.nut = NutClient
        self.ptero = PteroAPI
        self.agent_api = AgentAPI
        self.wol_api = WakeOnLan

    # ---- NUT ----
    def nut_target(self):
        return self.nut.getNutTarget()

    def ups_variables(self):
        try:
            return self.nut.getUpsVariables()
        except self.nut.NUT_ERRORS as e:
            raise DriverError(str(e)) from e

    # ---- Pterodactyl ----
    def ptero_configured(self):
        return self.ptero.isConfigured()

    def ptero_url(self):
        return self.ptero.PteroApi_Url or ""

    def _ptero_call(self, fn, *args):
        try:
            return fn(*args)
        except (self._requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            raise DriverError(str(e)) from e

    def ptero_info(self):
        from Core.config import load_ptero_info
        return load_ptero_info()

    def ptero_list_servers(self):
        return self._ptero_call(self.ptero.getAllServers)

    def ptero_list_nodes(self):
        return self._ptero_call(self.ptero.getNodes)

    def ptero_server_resources(self, identifier):
        return self._ptero_call(self.ptero.getServerResources, identifier)

    def ptero_send_power(self, identifier, action):
        return self.ptero.sendPowerSignalTo(identifier, action)

    # ---- Agents ----
    def agent_configs(self):
        """回傳 (agent 設定清單, 錯誤訊息)。"""
        if os.getenv("AgentInfo") is None:
            return [], "AgentInfo 環境變數未設定"
        agents = self.agent_api.loadAgentInfo(verbose=False)
        if agents is None:
            return [], "AgentInfo JSON 格式錯誤"
        if not isinstance(agents, list):
            return [], "AgentInfo 必須是 JSON 陣列"
        return agents, ""

    def agent_status(self, agent, index):
        return self.agent_api.getAgentStatus(agent, index)

    def agent_shutdown(self, agent):
        return self.agent_api.sendShutdownToAgent(agent)

    def agent_verify(self, agent):
        return self.agent_api.sendVerifyToAgent(agent)

    def signing_key_check(self):
        try:
            self.agent_api.loadPrivateKey()
            return True, f"已載入 {self.agent_api.PRIVATE_KEY_PATH.name}"
        except FileNotFoundError:
            return False, f"找不到私鑰 {self.agent_api.PRIVATE_KEY_PATH}，請執行 Tools/gen_keys.py"
        except Exception as e:
            return False, f"私鑰載入失敗: {e}"

    # ---- Wake-on-LAN ----
    def wol(self, mac):
        return self.wol_api.sendWakeOnLanTo(mac)

    def valid_mac(self, mac):
        return self.wol_api.isValidMac(mac)


def measure(fn, *args):
    """執行 fn 並回傳 (結果, 花費毫秒)。"""
    started = time.monotonic()
    result = fn(*args)
    return result, round((time.monotonic() - started) * 1000)
