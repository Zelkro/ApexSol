import asyncio
import os
import yaml
import logging
from typing import Dict, Any

from solana.rpc.async_api import AsyncClient
from src.utils.logger import setup_logger
from src.ingestion.stream import SolanaStreamer
from src.ingestion.parsers import PumpFunParser
from src.security.gatekeeper import SecurityGatekeeper
from src.engine.microstructure import MicrostructureEngine
from src.engine.indicators import TechnicalIndicators

import polars as pl

logger = setup_logger("MMCoin.Main")

class MarketAnalysisEngine:
    def __init__(self, settings_path: str):
        with open(settings_path, 'r') as f:
            self.settings = yaml.safe_load(f)

        self.rpc_client = AsyncClient(self.settings["rpc"]["http_url"])
        self.streamer = SolanaStreamer(
            ws_url=self.settings["rpc"]["ws_url"],
            http_url=self.settings["rpc"]["http_url"]
        )
        self.gatekeeper = SecurityGatekeeper(self.settings)
        self.micro_engine = MicrostructureEngine(
            ofi_window_size=self.settings["indicators"].get("ofi_window_size", 50)
        )
        
        # Keep track of active tokens and their price histories as lightweight lists
        self.monitored_prices: Dict[str, list] = {}
        # Cache for audited token states: {mint: {"safe": bool, "reason": str}}
        self.validation_cache: Dict[str, Dict[str, Any]] = {}
        # Track background tasks running token validation to avoid blocking ingestion
        self.validation_tasks: Dict[str, asyncio.Task] = {}

    async def _validate_and_cache(self, mint: str):
        """
        Runs the security validation in the background and stores the result.
        """
        try:
            result = await self.gatekeeper.validate_token(self.rpc_client, mint)
            self.validation_cache[mint] = result
            if not result["safe"]:
                logger.info(f"Token {mint} flagged UNSAFE | Reason: {result['reason']}")
            else:
                logger.info(f"Token {mint} passed initial audits and is marked SAFE.")
        except Exception as e:
            logger.error(f"Error validating token {mint} in background: {e}")
        finally:
            self.validation_tasks.pop(mint, None)

    async def handle_log_update(self, log_info: Dict[str, Any]):
        """
        Main pipeline callback triggered by streaming updates (Layer 1).
        """
        logs = log_info.get("logs", [])
        for log in logs:
            # Parse trade logs using Pump.fun parser
            trade = PumpFunParser.parse_trade_log(log)
            if not trade:
                continue

            mint = trade["mint"]
            is_buy = trade["is_buy"]
            amount = float(trade["token_amount"])
            sol_amount = float(trade["sol_amount"])
            
            # Simple price calculation based on transaction ratio
            price = sol_amount / amount if amount > 0 else 0.0
            if price == 0.0:
                continue

            # Layer 2: Security Gatekeeper validation with caching
            if mint in self.validation_cache:
                validation_result = self.validation_cache[mint]
                if not validation_result["safe"]:
                    continue
            else:
                # If not cached and not currently being validated, spawn background task
                if mint not in self.validation_tasks:
                    self.validation_tasks[mint] = asyncio.create_task(
                        self._validate_and_cache(mint)
                    )
                # Skip the trade signal update while the token is under initial validation
                continue

            # Layer 3: Calculate Microstructure metrics
            self.micro_engine.append_trade(mint, is_buy, price, amount)
            ofi = self.micro_engine.calculate_ofi(mint)
            
            # Update price history for indicators (lightweight Python lists)
            if mint not in self.monitored_prices:
                self.monitored_prices[mint] = [price]
            else:
                self.monitored_prices[mint].append(price)
                if len(self.monitored_prices[mint]) > 200:
                    self.monitored_prices[mint].pop(0)

            # Compute technical indicators (convert list to Polars Series just-in-time)
            prices = pl.Series("price", self.monitored_prices[mint])
            rsi = TechnicalIndicators.calculate_rsi(prices)
            
            # Print Signal logs when threshold meets criteria
            if rsi and rsi < 30 and ofi > 10_000:
                logger.warning(
                    f"🚨 SIGNAL ALERT! High-Probability BUY on Mint: {mint}\n"
                    f"   RSI: {rsi:.2f} (Oversold) | OFI: {ofi:,.0f} (Bullish Order Flow Imbalance)"
                )

    async def run(self):
        logger.info("Initializing Solana Memecoin Analysis Pipeline...")
        self.streamer.register_handler(self.handle_log_update)
        
        # Run event loop stream
        await self.streamer.start_streaming()

    async def close(self):
        self.streamer.stop()
        # Clean up any remaining background tasks
        for task in self.validation_tasks.values():
            task.cancel()
        await self.rpc_client.close()

if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
    engine = MarketAnalysisEngine(config_path)
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        logger.info("Engine shutdown received.")
        asyncio.run(engine.close())
