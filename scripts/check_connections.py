"""Probe every upstream data source and print a status table.

Run with: `python scripts/check_connections.py` (or `make check-connections`).
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.table import Table

from spaceapps_core.api.v1.routers.health import (
    _probe_appeears,
    _probe_copernicus,
    _probe_earthdata,
    _probe_nex_gddp,
    _probe_open_meteo,
    _probe_power,
)


async def main() -> int:
    probes = [
        _probe_power(),
        _probe_open_meteo(),
        _probe_appeears(),
        _probe_earthdata(),
        _probe_nex_gddp(),
        _probe_copernicus(),
    ]
    results = await asyncio.gather(*probes, return_exceptions=True)

    console = Console()
    table = Table(title="Data source connectivity")
    table.add_column("Source", style="cyan")
    table.add_column("Status")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Message", overflow="fold")

    status_style = {"ok": "green", "error": "red", "not_configured": "yellow", "skipped": "white"}
    exit_code = 0
    for res in results:
        if isinstance(res, Exception):
            table.add_row("unknown", "[red]error[/red]", "-", str(res))
            exit_code = 1
            continue
        style = status_style.get(res.status, "white")
        latency = f"{res.latency_ms:.0f}" if res.latency_ms is not None else "-"
        table.add_row(res.name, f"[{style}]{res.status}[/{style}]", latency, res.message or "")
        if res.status == "error":
            exit_code = 1

    console.print(table)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
