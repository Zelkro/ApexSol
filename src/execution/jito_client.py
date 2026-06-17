import asyncio
import time
import base64
import random
import logging
import aiohttp
from typing import List, Dict, Any, Optional
from solders.transaction import VersionedTransaction
from src.config.settings import settings

logger = logging.getLogger("MMCoin.JitoClient")

class JitoClient:
    """
    Submits versioned transactions as atomic bundles to Jito Block Engines,
    queries tip recommendations, and tracks bundle landing statuses.
    """
    def __init__(self, block_engine_url: str):
        self.block_engine_url = block_engine_url
        self.tip_accounts: List[str] = [
            "Cw8CFyM92ocnFYCHkuTFA3bCw58AgqESzb4C236qRBdB",
            "DttWaC7TY1Tu2kgUJe6gBjykYFsWZsPpWv51KmX7DZ1T",
            "3AVR1814EB2EPKY2SFh9wJRAjyk4ja8eT37aM5uJ1n2T"
        ]
        self.last_tip_update: float = 0.0

    async def get_tip_accounts(self) -> List[str]:
        """
        Retrieves active tip accounts from Jito block engine.
        Returns cached list on failures or timeouts.
        """
        # Cache for 10 minutes
        if time.time() - self.last_tip_update < 600.0:
            return self.tip_accounts

        url = f"{self.block_engine_url}/api/v1/tipAccounts"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=2.0) as resp:
                    if resp.status == 200:
                        accounts = await resp.json()
                        if accounts:
                            self.tip_accounts = accounts
                            self.last_tip_update = time.time()
        except Exception as e:
            logger.debug(f"Failed fetching Jito tip accounts: {e}. Using cached list.")
        return self.tip_accounts

    def select_tip_account(self) -> str:
        """
        Returns a random tip account from cache.
        """
        return random.choice(self.tip_accounts)

    async def send_bundle(self, transactions: List[VersionedTransaction]) -> Optional[str]:
        """
        Submits serialized transaction payload to Jito block engine.
        """
        serialized_txs = []
        for tx in transactions:
            serialized_txs.append(base64.b64encode(bytes(tx)).decode("utf-8"))

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [serialized_txs]
        }

        url = f"{self.block_engine_url}/api/v1/bundles"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=3.0) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        bundle_id = res_json.get("result")
                        logger.info(f"Bundle submitted to Jito. Bundle ID: {bundle_id}")
                        return bundle_id
                    else:
                        body = await resp.text()
                        logger.error(f"Jito bundle submission rejected: Status {resp.status}, Body: {body}")
        except Exception as e:
            logger.error(f"Jito bundle submission error: {e}")
        return None

    async def track_bundle(self, bundle_id: str, timeout_seconds: float = 15.0) -> str:
        """
        Polls the Jito Block Engine to verify if the bundle successfully landed.
        Returns "landed", "failed", or "timeout".
        """
        start_time = time.time()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBundleStatuses",
            "params": [[bundle_id]]
        }
        
        url = f"{self.block_engine_url}/api/v1/bundles"

        while time.time() - start_time < timeout_seconds:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=2.0) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result = data.get("result", {})
                            value = result.get("value", [])
                            
                            if value:
                                status_info = value[0]
                                status = status_info.get("status")
                                if status in ("landed", "processed"):
                                    logger.info(f"Jito bundle {bundle_id} landed successfully.")
                                    return "landed"
                                elif status == "failed":
                                    logger.warning(f"Jito bundle {bundle_id} execution failed.")
                                    return "failed"
            except Exception as e:
                logger.debug(f"Error checking Jito bundle status: {e}")

            await asyncio.sleep(1.0)

        logger.warning(f"Jito bundle {bundle_id} status tracking timed out.")
        return "timeout"
