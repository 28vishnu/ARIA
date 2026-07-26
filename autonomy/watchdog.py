import logging

logger = logging.getLogger("aria")

class SystemWatchdog:
    def __init__(self, monitor, policy_engine):
        self.monitor = monitor
        self.policies = policy_engine

    def inspect_system_health(self) -> bool:
        """Inspects for stuck tasks, loops, or policy violations."""
        stalled = self.monitor.check_stalled_tasks()
        if stalled:
            logger.warning("[Watchdog] Detected stalled execution IDs: %s", stalled)
            return False
        return True
