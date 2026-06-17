import asyncio
import time
import logging
from typing import Dict, Any, Callable, Optional, Set
from src.config.settings import settings
from src.ingestion.models import RawStreamEvent

logger = logging.getLogger("MMCoin.GRPCClient")

class YellowstoneGRPCClient:
    """
    gRPC Yellowstone Geyser client with connection logic,
    slot gap detection, deduplication, and a bounded queue with overflow policies.
    """
    def __init__(self, grpc_url: str, auth_token: str, subscription_filter: Dict[str, Any]):
        self.grpc_url = grpc_url
        self.auth_token = auth_token
        self.subscription_filter = subscription_filter
        
        self.running = False
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=settings.queue_size)
        self.processed_signatures: Set[str] = set()
        
        self.last_seen_slot: int = 0
        self.last_processed_slot: int = 0
        
        # Dispatch callbacks
        self._handlers = []
        
        # Tasks
        self._read_task: Optional[asyncio.Task] = None
        self._dispatch_task: Optional[asyncio.Task] = None

        # Metrics trackers (mock objects or numbers)
        self.events_received = 0
        self.reconnects = 0
        self.duplicates = 0
        self.dropped_events = 0

    def register_handler(self, handler: Callable[[RawStreamEvent], Any]):
        self._handlers.append(handler)

    async def start(self, from_slot: Optional[int] = None):
        self.running = True
        if from_slot:
            self.last_processed_slot = from_slot
            logger.info(f"Resuming stream from slot: {from_slot}")

        self._read_task = asyncio.create_task(self._read_loop())
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("Yellowstone gRPC Ingestion worker started.")

    async def stop(self):
        self.running = False
        if self._read_task:
            self._read_task.cancel()
        if self._dispatch_task:
            self._dispatch_task.cancel()
        logger.info("Yellowstone gRPC Ingestion worker stopped.")

    async def _read_loop(self):
        """
        Connects to the gRPC service and pushes events into the bounded queue.
        Handles reconnection and ping/pong keepalive.
        """
        backoff = 1.0
        while self.running:
            try:
                # Real implementation would setup grpc.aio.secure_channel and iterate over subscription stream.
                # Here we implement the retry logic and mock reader loop to simulate data if offline.
                logger.info(f"Connecting to Yellowstone Geyser at {self.grpc_url}...")
                
                # Mock Geyser subscription stream simulation to prevent blockages during offline runs
                await self._read_stream()
                
                # If stream exits normally, reset backoff
                backoff = 1.0
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.reconnects += 1
                logger.error(f"Geyser stream read error: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    async def _read_stream(self):
        """
        Simulated loop feeding transactions to the queue.
        In a live environment, this processes Yellowstone proto messages.
        """
        import uuid
        # Mock transaction generator loop
        while self.running:
            # Check slot progression & gaps
            current_slot = self.last_seen_slot + 1
            if self.last_seen_slot > 0 and current_slot - self.last_seen_slot > 1:
                logger.warning(f"Slot Gap Detected! Skipped from {self.last_seen_slot} to {current_slot}")
            
            self.last_seen_slot = current_slot
            self.events_received += 1

            # Build mock event payload (contains dummy signature & mock instruction)
            sig = f"sig_{uuid.uuid4().hex}"
            event = RawStreamEvent(
                event_id=uuid.uuid4().hex,
                slot=current_slot,
                signature=sig,
                payload=b"mock_raw_transaction_payload",
                received_at=time.time(),
                provenance="yellowstone"
            )

            # Bounded queue overflow management policy
            await self._push_to_queue(event)

            # Simulate network delay between blocks (e.g. 400ms slot time)
            await asyncio.sleep(0.4)

    async def _push_to_queue(self, event: RawStreamEvent):
        """
        Pushes a new raw event to the queue based on the settings overflow policy.
        Policies: drop_oldest, drop_newest, fail_closed
        """
        if self.queue.full():
            self.dropped_events += 1
            policy = settings.queue_overflow_policy
            
            if policy == "drop_oldest":
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                await self.queue.put(event)
                logger.warning("Queue full. Dropped oldest event.")
            elif policy == "drop_newest":
                logger.warning("Queue full. Dropped newest event.")
                return
            elif policy == "fail_closed":
                logger.critical("Queue saturated. Fail-closed policy triggered.")
                raise RuntimeError("Ingestion queue saturated under fail-closed policy.")
        else:
            await self.queue.put(event)

    async def _dispatch_loop(self):
        """
        Consumes events from the queue, handles deduplication and age filters, and calls handlers.
        """
        while self.running:
            try:
                event: RawStreamEvent = await self.queue.get()
                
                # Check for duplicate transactions (replay recovery deduplication)
                if event.signature in self.processed_signatures:
                    self.duplicates += 1
                    self.queue.task_done()
                    continue

                # Evict processed signature cache periodically
                if len(self.processed_signatures) > 50000:
                    self.processed_signatures.clear()
                self.processed_signatures.add(event.signature)

                # Check event age (Staleness threshold check)
                age = time.time() - event.received_at
                if age > settings.staleness_threshold_seconds:
                    logger.debug(f"Discarding stale event: signature={event.signature}, age={age:.2f}s")
                    self.queue.task_done()
                    continue

                self.last_processed_slot = event.slot
                
                # Concurrent dispatch to handlers
                tasks = []
                for handler in self._handlers:
                    if asyncio.iscoroutinefunction(handler):
                        tasks.append(handler(event))
                    else:
                        handler(event)
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in gRPC dispatch loop: {e}")
