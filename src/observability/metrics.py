import logging
from typing import Dict, Any, List

logger = logging.getLogger("ApexSol.Metrics")

class MetricsManager:
    """
    Manages and exposes in-memory execution pipeline metrics.
    """
    def __init__(self):
        self._counters: Dict[str, int] = {
            "grpc_events_received_total": 0,
            "grpc_reconnects_total": 0,
            "grpc_duplicates_total": 0,
            "queue_dropped_total": 0,
            "parse_failures_total": 0,
            "audit_allow_total": 0,
            "audit_deny_total": 0,
            "audit_pending_total": 0,
            "signal_generated_total": 0,
            "execution_attempt_total": 0,
            "bundle_landed_total": 0,
            "bundle_failed_total": 0,
            "bundle_timeout_total": 0
        }
        
        self._gauges: Dict[str, float] = {
            "queue_depth": 0.0,
            "slot_lag": 0.0
        }
        
        # Histograms store latency sample lists
        self._histograms: Dict[str, List[float]] = {
            "receive_to_parse_ms": [],
            "parse_to_audit_ms": [],
            "audit_to_signal_ms": [],
            "signal_to_submit_ms": [],
            "submit_to_result_ms": []
        }

    def increment(self, name: str, value: int = 1):
        if name in self._counters:
            self._counters[name] += value
        else:
            self._counters[name] = value

    def set_gauge(self, name: str, value: float):
        self._gauges[name] = value

    def record_latency(self, name: str, duration_ms: float):
        if name in self._histograms:
            self._histograms[name].append(duration_ms)
            if len(self._histograms[name]) > 1000:
                self._histograms[name].pop(0)

    def get_summary(self) -> Dict[str, Any]:
        """
        Returns average values for histrograms and final values for counters/gauges.
        """
        summary = {}
        for k, v in self._counters.items():
            summary[k] = v
        for k, v in self._gauges.items():
            summary[k] = v
        for k, samples in self._histograms.items():
            avg = sum(samples) / len(samples) if samples else 0.0
            summary[f"{k}_avg"] = avg
        return summary

    def log_metrics(self):
        summary = self.get_summary()
        logger.info(f"📊 SYSTEM METRICS REPORT: {summary}")

# Singleton instance
metrics = MetricsManager()
