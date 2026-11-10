"""硬體/外部服務的存取介面。

RealDrivers 把 Api/ 的各個客戶端組起來；SimDrivers（見 simulator.py）提供同樣的方法，
讓控制流程在實機與模擬模式下執行完全相同的程式碼。
"""
import requests

from Api import WakeOnLan
from Api.AgentAPI import AgentClient
from Api.NutClient import NUT_ERRORS, NutClient
from Api.PteroAPI import PteroClient


class DriverError(Exception):
    pass


class RealDrivers:
    mode = "real"

    def __init__(self, settings):
        self.settings = settings
        self.nut = NutClient(settings.nut_host, settings.nut_port, settings.nut_ups_name,
                             settings.nut_login, settings.nut_password)
        self.ptero = PteroClient(settings.ptero_url, settings.ptero_app_key, settings.ptero_client_key)
        self.agents = AgentClient(settings.private_key_path)

    # ---- NUT ----
    def nut_target(self):
        return self.nut.target()

    def ups_variables(self):
        try:
            return self.nut.variables()
        except NUT_ERRORS as e:
            raise DriverError(str(e)) from e

    # ---- Pterodactyl ----
    def ptero_configured(self):
        return self.ptero.configured

    def ptero_url(self):
        return self.ptero.url

    def ptero_info(self):
        return self.settings.ptero_info()

    def _ptero_call(self, fn, *args):
        try:
            return fn(*args)
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
            raise DriverError(str(e)) from e

    def ptero_list_servers(self):
        return self._ptero_call(self.ptero.list_servers)

    def ptero_list_nodes(self):
        return self._ptero_call(self.ptero.list_nodes)

    def ptero_server_resources(self, identifier):
        return self._ptero_call(self.ptero.server_resources, identifier)

    def ptero_send_power(self, identifier, action):
        return self.ptero.send_power(identifier, action)

    # ---- Agents ----
    def agent_configs(self):
        """回傳 (agent 設定清單, 錯誤訊息)。"""
        return self.settings.agent_info()

    def agent_status(self, agent, index):
        return self.agents.status(agent, index)

    def agent_shutdown(self, agent):
        return self.agents.shutdown(agent)

    def agent_verify(self, agent):
        return self.agents.verify(agent)

    def signing_key_check(self):
        path = self.agents.private_key_path
        try:
            self.agents.load_private_key()
            return True, f"已載入 {path.name}"
        except FileNotFoundError:
            return False, f"找不到私鑰 {path}，請執行 Tools/gen_keys.py"
        except Exception as e:
            return False, f"私鑰載入失敗: {e}"

    # ---- Wake-on-LAN ----
    def wol(self, mac):
        return WakeOnLan.send_wake_on_lan(mac)

    def valid_mac(self, mac):
        return WakeOnLan.is_valid_mac(mac)
