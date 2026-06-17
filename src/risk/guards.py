import time
import logging
from typing import Dict, Any
from src.config.settings import settings

logger = logging.getLogger("ApexSol.RiskGuards")

class RiskGuards:
    """
    Global circuit breakers and risk checks.
    Transitions system to safe/no-trade mode when safety limits are breached.
    """
    def __init__(self):
        self.stream_healthy: bool = True
        self.jito_healthy: bool = True
        
        self.last_stream_heartbeat: float = time.time()
        self.consecutive_bundle_failures: int = 0
        self.max_consecutive_bundle_failures: int = 5
        
        self.latency_samples = []
        self.current_open_positions: int = 0

    def update_stream_heartbeat(self):
        self.last_stream_heartbeat = time.time()
        self.stream_healthy = True

    def report_bundle_failure(self):
        self.consecutive_bundle_failures += 1
        if self.consecutive_bundle_failures >= self.max_consecutive_bundle_failures:
            logger.critical(f"Circuit Breaker Triggered: {self.consecutive_bundle_failures} consecutive Jito bundle failures!")

    def report_bundle_success(self):
        self.consecutive_bundle_failures = 0

    def record_latency(self, latency_ms: float):
        self.latency_samples.append(latency_ms)
        if len(self.latency_samples) > 100:
            self.latency_samples.pop(0)

    def get_p99_latency(self) -> float:
        if not self.latency_samples:
            return 0.0
        sorted_samples = sorted(self.latency_samples)
        idx = int(len(sorted_samples) * 0.99)
        return sorted_samples[idx]

    def is_trade_allowed(self, current_slot: int, last_seen_slot: int) -> bool:
        """
        Runs checks to decide if trading is globally permitted.
        """
        # 1. Stream health (Time since last heartbeat)
        if time.time() - self.last_stream_heartbeat > 10.0:
            logger.warning("No-Trade Active: Stream down (heartbeat timeout).")
            self.stream_healthy = False
            return False

        if not self.stream_healthy:
            return False

        # 2. Jito connection health
        if not self.jito_healthy:
            logger.warning("No-Trade Active: Loss of Jito connectivity.")
            return False

        # 3. Slot lag check
        slot_lag = current_slot - last_seen_slot
        if slot_lag > settings.max_slot_lag:
            logger.warning(f"No-Trade Active: High slot lag detected ({slot_lag} slots).")
            return False

        # 4. Latency threshold guard
        p99 = self.get_p99_latency()
        if p99 > settings.p99_latency_threshold_ms:
            logger.warning(f"No-Trade Active: p99 latency ({p99:.1f}ms) exceeds limit ({settings.p99_latency_threshold_ms}ms).")
            return False

        # 5. Max positions guard
        if self.current_open_positions >= settings.max_open_positions:
            logger.warning(f"No-Trade Active: Max open positions limit reached ({self.current_open_positions}/{settings.max_open_positions}).")
            return False

        # 6. Consecutive failures threshold check
        if self.consecutive_bundle_failures >= self.max_consecutive_bundle_failures:
            logger.warning(f"No-Trade Active: Consecutive bundle failures limit reached.")
            return False

        return True
# Singleton instance
risk_guards = RiskGuards()
