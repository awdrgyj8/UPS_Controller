import os
from nut2 import PyNUTClient  # type: ignore

client = PyNUTClient(os.getenv("NUT_ServerIP"))


def getUpsPower():
    if client.list_vars("ups")["ups.status"] == "OB DISCHRG":
        # 斷電狀態
        return False
    else:
        return True


def getUpsBetteryPercentage():
    return int(client.list_vars("ups")["battery.charge"])
