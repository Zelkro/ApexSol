import asyncio
import logging
from typing import List

logger = logging.getLogger("MMCoin.Lifecycle")

class LifecycleManager:
    """
    Coordinates graceful startup and shutdown of all pipeline tasks.
    """
    def __init__(self, tasks_to_cancel: List[asyncio.Task], cleanup_callbacks: list):
        self.tasks_to_cancel = tasks_to_cancel
        self.cleanup_callbacks = cleanup_callbacks
        self.shutdown_initiated = False

    async def initiate_shutdown(self):
        if self.shutdown_initiated:
            return
        
        self.shutdown_initiated = True
        logger.warning("🚨 SHUTDOWN SIGNAL RECEIVED! Commencing graceful stop...")

        # 1. Cancel background execution workers first to stop new submissions
        for task in self.tasks_to_cancel:
            if not task.done():
                logger.info(f"Cancelling task: {task.get_name()}")
                task.cancel()

        # Wait for cancellations to complete
        if self.tasks_to_cancel:
            await asyncio.gather(*self.tasks_to_cancel, return_exceptions=True)

        # 2. Execute cleanup callbacks (e.g. close client sessions, stop clients)
        logger.info("Executing client and resource cleanup callbacks...")
        for callback in self.cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in cleanup callback: {e}")

        logger.warning("Shutdown complete. MMCoin process exited cleanly.")
