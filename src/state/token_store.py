import asyncio
import time
import logging
from typing import Dict, Optional, List
from src.ingestion.models import TokenState, AuditVerdict

logger = logging.getLogger("MMCoin.TokenStore")

class TokenStore:
    """
    Task-safe memory store for active token states.
    Supports TTL eviction to limit memory growth.
    """
    def __init__(self, ttl_seconds: float = 3600.0):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, TokenState] = {}
        # Track when each mint was last modified/seen for TTL purge
        self._last_accessed: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Token store cleanup task started.")

    async def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("Token store cleanup task stopped.")

    async def get(self, mint: str) -> Optional[TokenState]:
        async with self._lock:
            state = self._store.get(mint)
            if state:
                self._last_accessed[mint] = time.time()
            return state

    async def get_or_create(self, mint: str, slot: int) -> TokenState:
        async with self._lock:
            now = time.time()
            self._last_accessed[mint] = now
            if mint not in self._store:
                self._store[mint] = TokenState(
                    mint=mint,
                    first_seen_at=now,
                    last_seen_at=now,
                    first_slot=slot,
                    last_slot=slot
                )
            return self._store[mint]

    async def update(self, mint: str, state: TokenState):
        async with self._lock:
            self._store[mint] = state
            self._last_accessed[mint] = time.time()

    async def delete(self, mint: str):
        async with self._lock:
            self._store.pop(mint, None)
            self._last_accessed.pop(mint, None)

    async def _cleanup_loop(self):
        """
        Periodically purges tokens that have not been updated within the TTL.
        """
        while True:
            try:
                await asyncio.sleep(60.0)
                now = time.time()
                to_delete = []
                
                async with self._lock:
                    for mint, last_seen in self._last_accessed.items():
                        if now - last_seen > self.ttl_seconds:
                            to_delete.append(mint)
                            
                    for mint in to_delete:
                        self._store.pop(mint, None)
                        self._last_accessed.pop(mint, None)
                        
                if to_delete:
                    logger.info(f"Purged {len(to_delete)} stale tokens from store.")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in token store cleanup loop: {e}")
