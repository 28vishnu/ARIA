import logging
from autonomy.models import RuntimeMetrics

logger = logging.getLogger("aria")

class TelemetryCollector:
    def __init__(self):
        self.metrics = RuntimeMetrics()

    def record_planner_latency(self, latency_ms: float):
        self.metrics.planner_latency_ms = latency_ms

    def record_skill_latency(self, latency_ms: float):
        self.metrics.skill_latency_ms = latency_ms

    def record_success(self, confidence: float):
        self.metrics.success_count += 1
        self._update_confidence(confidence)

    def record_failure(self):
        self.metrics.failure_count += 1

    def record_retry(self):
        self.metrics.retry_count += 1

    def record_llm_avoided(self):
        self.metrics.llm_calls_avoided += 1

    def _update_confidence(self, new_conf: float):
        total = self.metrics.success_count + self.metrics.failure_count
        if total == 1:
            self.metrics.average_confidence = new_conf
        else:
            self.metrics.average_confidence = ((self.metrics.average_confidence * (total - 1)) + new_conf) / total

    def report(self) -> RuntimeMetrics:
        return self.metrics
