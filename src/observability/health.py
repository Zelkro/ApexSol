import time
from src.risk.guards import risk_guards

class HealthChecker:
    """
    Exposes readiness and liveness status of the pipeline.
    """
    @staticmethod
    def is_alive() -> bool:
        """
        Liveness check: returns True if stream is not experiencing deadlocks.
        """
        # If the stream hasn't received anything in over 30 seconds, it's considered dead
        if time.time() - risk_guards.last_stream_heartbeat > 30.0:
            return False
        return True

    @staticmethod
    def is_ready() -> bool:
        """
        Readiness check: returns True if the system is capable of trading.
        """
        # Ready if stream is healthy and Jito connection is active
        return risk_guards.stream_healthy and risk_guards.jito_healthy
