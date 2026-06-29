# pyrefly: ignore [missing-import]
import asyncio
import logging
from typing import AsyncGenerator, Callable, Dict, Any, Optional
import grpc

logger = logging.getLogger("MMCoin.Geyser")

# We attempt to import the generated proto files. If they don't exist yet, we define a fallback structure or log a warning.
try:
    from src.ingestion.proto import geyser_pb2, geyser_pb2_grpc
    PROTO_AVAILABLE = True
except ImportError:
    PROTO_AVAILABLE = False
    logger.warning("Geyser Protobuf stubs not found. Run the compilation script to generate them.")

class GeyserStreamer:
    """
    gRPC Yellowstone Geyser client for low-latency streaming of Solana transactions.
    """
    def __init__(self, grpc_url: str, auth_token: str):
        self.grpc_url = grpc_url
        self.auth_token = auth_token
        self.running = False
        self._handlers = []

    def register_handler(self, handler: Callable[[Dict[str, Any]], Any]):
        self._handlers.append(handler)

    async def start_streaming(self):
        if not PROTO_AVAILABLE:
            logger.error("Cannot start Geyser streaming: Protobuf stubs are missing.")
            return

        self.running = True
        backoff = 1.0

        # Jito/Yellowstone Geyser endpoint options (e.g. keepalive)
        options = [
            ("grpc.keepalive_time_ms", 30000),
            ("grpc.keepalive_timeout_ms", 10000),
            ("grpc.keepalive_permit_without_calls", 1),
            ("grpc.http2.max_pings_without_data", 0),
        ]

        while self.running:
            try:
                logger.info(f"Connecting to Yellowstone Geyser gRPC: {self.grpc_url}")
                
                # Check if we should use secure channel
                if self.grpc_url.endswith(":443") or "https" in self.grpc_url:
                    credentials = grpc.ssl_channel_credentials()
                    channel = grpc.aio.secure_channel(self.grpc_url, credentials, options=options)
                else:
                    channel = grpc.aio.insecure_channel(self.grpc_url, options=options)

                async with channel:
                    stub = geyser_pb2_grpc.GeyserStub(channel)
                    metadata = []
                    if self.auth_token:
                        metadata.append(("x-token", self.auth_token))

                    # Configure filters (e.g. Pump.fun program)
                    # Filter specifically for pump.fun: 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
                    subscription_request = geyser_pb2.SubscribeRequest(
                        transactions={
                            "pump_fun": geyser_pb2.SubscribeRequestFilterTransactions(
                                account_include=["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"]
                            )
                        },
                        commitment=geyser_pb2.CommitmentLevel.CONFIRMED
                    )

                    async def request_iterator():
                        # Yield the initial subscription request
                        yield subscription_request
                        # Keep-alive loop (Ping/Pong)
                        while self.running:
                            await asyncio.sleep(20)
                            yield geyser_pb2.SubscribeRequest(
                                ping=geyser_pb2.SubscribeRequestPing()
                            )

                    # Call Subscribe
                    stream = stub.Subscribe(request_iterator(), metadata=metadata)
                    backoff = 1.0 # Reset backoff on successful connection

                    async for response in stream:
                        if not self.running:
                            break
                        
                        # Handle pong responses or dispatch transaction data
                        if response.HasField("pong"):
                            logger.debug("Geyser connection Keep-Alive: Pong received.")
                            continue
                        
                        if response.HasField("transaction"):
                            tx_info = response.transaction
                            await self._dispatch(tx_info)

            except grpc.RpcError as e:
                logger.warning(f"Geyser gRPC connection lost (Code: {e.code()}): {e.details()}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except Exception as e:
                logger.error(f"Error in GeyserStreamer: {e}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _dispatch(self, tx_info):
        # Dispatch to registered handlers
        tasks = []
        for handler in self._handlers:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(handler(tx_info))
            else:
                handler(tx_info)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self):
        self.running = False
        logger.info("Stopping Geyser streamer...")
