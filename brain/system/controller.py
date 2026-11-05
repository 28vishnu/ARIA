from __future__ import annotations

import psutil
from typing import Dict, Any


def get_system_telemetry() -> Dict[str, Any]:
    """Read host system resource stats."""
    battery = psutil.sensors_battery()
    return {
        "cpu_usage_percent": psutil.cpu_percent(interval=0.5),
        "ram_usage_percent": psutil.virtual_memory().percent,
        "ram_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
        "battery_percent": battery.percent if battery else "N/A",
        "power_plugged": battery.power_plugged if battery else "N/A"
    }
