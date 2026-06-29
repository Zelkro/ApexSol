# pyrefly: ignore [missing-import]
import asyncio
import json
import logging
import websockets
from typing import AsyncGenerator, Callable, Dict, Any

logger = logging.getLogger("MMCoin.Stream")

class SolanaStreamer:
    def __init__(self, ws_url: str, http_url: str):
        self.ws_url = ws_url
        self.http_url = http_url
        self.running = False
        self._handlers = []

    def register_handler(self, handler: Callable[[Dict[str, Any]], Any]):
        self._handlers.append(handler)

    async def start_streaming(self):
        """
        Starts the real-time WebSocket connection to Solana RPC logsSubscribe.
        Subscribes to transactions touching Pump.fun and Moonshot program addresses.
        """
        self.running = True
        backoff = 1.0
        
        # Target programs
        pump_fun_id = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
        
        while self.running:
            try:
                logger.info(f"Connecting to Solana WS node: {self.ws_url}")
                async with websockets.connect(self.ws_url) as websocket:
                    backoff = 1.0 # Reset backoff upon successful connection
                    
                    # Send logsSubscribe subscription message
                    subscribe_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [pump_fun_id]},
                            {"commitment": "confirmed"}
                        ]
                    }
                    await websocket.send(json.dumps(subscribe_payload))
                    logger.info(f"Subscribed to logs containing Pump.fun Program ID: {pump_fun_id}")
                    
                    while self.running:
                        response = await websocket.recv()
                        data = json.loads(response)
                        
                        if "params" in data:
                            log_info = data["params"]["result"]
                            await self._dispatch(log_info)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"WebSocket connection lost. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except Exception as e:
                logger.error(f"Error in SolanaStreamer: {e}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _dispatch(self, log_info: Dict[str, Any]):
        # Run logs through all registered handlers concurrently
        tasks = []
        for handler in self._handlers:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(handler(log_info))
            else:
                handler(log_info)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self):
        self.running = False
        logger.info("Stopping streamer...")
