"""終端機狀態表（原本 main.py 的 showStatus）。"""
import datetime
from rich.console import Console
from rich.table import Table

console = Console()


def _format_uptime(uptime_seconds):
    if uptime_seconds is None:
        return "-"
    uptime_seconds = int(uptime_seconds)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def show_status(upsSnapshot, expectedPowerState, statuses):
    upsTable = Table(
        title=f"UPS / NUT 狀態 - {datetime.datetime.now().strftime('%H:%M:%S')}",
        show_header=True,
        header_style="bold cyan",
    )
    upsTable.add_column("NUT 連線")
    upsTable.add_column("UPS 狀態")
    upsTable.add_column("市電")
    upsTable.add_column("電量")
    upsTable.add_column("訊息")

    nutConnection = "[green]Connected[/green]" if upsSnapshot["ok"] == True else "[red]Disconnected[/red]"
    if upsSnapshot["power"] is True:
        powerLabel = "[green]Online[/green]"
    elif upsSnapshot["power"] is False:
        powerLabel = "[red]On Battery[/red]"
    else:
        powerLabel = "[yellow]Unknown[/yellow]"
    batteryLabel = "-" if upsSnapshot["battery"] is None else f"{upsSnapshot['battery']}%"
    upsTable.add_row(
        nutConnection,
        upsSnapshot["status"],
        powerLabel,
        batteryLabel,
        upsSnapshot["error"] or "OK",
    )
    console.print(upsTable)

    table = Table(
        title=f"Agent 狀態 - {datetime.datetime.now().strftime('%H:%M:%S')}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Agent", style="bold")
    table.add_column("IP")
    table.add_column("Port")
    table.add_column("MAC")
    table.add_column("預期")
    table.add_column("連線")
    table.add_column("Hostname")
    table.add_column("Uptime")
    table.add_column("延遲")
    table.add_column("訊息")

    expectedLabel = "開機" if expectedPowerState == True else "關機"
    for status in statuses:
        online = status["online"] == True
        connectionLabel = "[green]Online[/green]" if online else "[red]Offline[/red]"
        latency = "-" if status["latency_ms"] is None else f"{status['latency_ms']} ms"
        message = "OK" if online else status["error"]
        table.add_row(
            status["name"],
            status["ip"],
            status["port"],
            status["mac"],
            expectedLabel,
            connectionLabel,
            status["hostname"] or "-",
            _format_uptime(status["uptime_seconds"]),
            latency,
            message or "-",
        )

    if len(statuses) == 0:
        table.add_row("-", "-", "-", "-", expectedLabel, "[yellow]Unknown[/yellow]", "-", "-", "-", "AgentInfo 未設定或沒有 Agent")

    console.print(table)
