"""終端機狀態表。"""
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


def show_status(ups_snapshot, expected_power_state, agents):
    """ups_snapshot 是控制流程的 UPS 快照（dict），agents 是共享狀態裡的 AgentState 清單。"""
    ups_table = Table(
        title=f"UPS / NUT 狀態 - {datetime.datetime.now().strftime('%H:%M:%S')}",
        show_header=True,
        header_style="bold cyan",
    )
    ups_table.add_column("NUT 連線")
    ups_table.add_column("UPS 狀態")
    ups_table.add_column("市電")
    ups_table.add_column("電量")
    ups_table.add_column("訊息")

    nut_connection = "[green]Connected[/green]" if ups_snapshot["ok"] is True else "[red]Disconnected[/red]"
    if ups_snapshot["power"] is True:
        power_label = "[green]Online[/green]"
    elif ups_snapshot["power"] is False:
        power_label = "[red]On Battery[/red]"
    else:
        power_label = "[yellow]Unknown[/yellow]"
    battery_label = "-" if ups_snapshot["battery"] is None else f"{ups_snapshot['battery']}%"
    ups_table.add_row(
        nut_connection,
        ups_snapshot["status"],
        power_label,
        battery_label,
        ups_snapshot["error"] or "OK",
    )
    console.print(ups_table)

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

    expected_label = "開機" if expected_power_state is True else "關機"
    for agent in agents:
        connection_label = "[green]Online[/green]" if agent.online else "[red]Offline[/red]"
        latency = "-" if agent.latency_ms is None else f"{agent.latency_ms} ms"
        message = "OK" if agent.online else agent.error
        table.add_row(
            agent.name,
            agent.ip,
            agent.port,
            agent.mac,
            expected_label,
            connection_label,
            agent.hostname or "-",
            _format_uptime(agent.uptime_seconds),
            latency,
            message or "-",
        )

    if len(agents) == 0:
        table.add_row("-", "-", "-", "-", expected_label, "[yellow]Unknown[/yellow]", "-", "-", "-", "AgentInfo 未設定或沒有 Agent")

    console.print(table)
