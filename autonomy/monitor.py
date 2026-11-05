import logging
from typing import Dict, Any

logger = logging.getLogger("aria")

class ExecutionMonitor:
    def __init__(self):
        self.active_executions: Dict[str, Dict[str, Any]] = {}

    def track_start(self, execution_id: str, name: str):
        self.active_executions[execution_id] = {"name": name, "status": "running"}

    def track_completion(self, execution_id: str, success: bool):
        if execution_id in self.active_executions:
            self.active_executions[execution_id]["status"] = "completed" if success else "failed"

    def check_stalled_tasks(self) -> list[str]:
        """Detects stalled or timed-out executions."""
        return [eid for eid, info in self.active_executions.items() if info["status"] == "running"]
