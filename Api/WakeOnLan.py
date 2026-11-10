"""Wake-on-LAN：送出 magic packet 喚醒節點。"""
import re

from wakeonlan import send_magic_packet

from Api.Logger import log

_MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$|^[0-9A-Fa-f]{12}$")


def is_valid_mac(mac):
    return isinstance(mac, str) and _MAC_PATTERN.match(mac.strip()) is not None


def send_wake_on_lan(mac):
    try:
        send_magic_packet(mac)
        return True
    except Exception as e:  # 喚醒流程不能因為單一封包失敗而中斷
        log(f"❌ 發送 Wake-on-LAN 到 {mac} 發生錯誤: {e}", source="wol")
        return False
