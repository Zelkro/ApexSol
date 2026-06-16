import base58
import aiohttp
import logging
from typing import List, Dict, Any, Optional
from solders.system_program import transfer, TransferParams
from solders.transaction import VersionedTransaction
from solders.instruction import Instruction
from solders.pubkey import Pubkey

logger = logging.getLogger("MMCoin.Jito")

class JitoBundleClient:
    """
    Interfaces with Jito Block Engines to send atomic bundles of transactions.
    """
    def __init__(self, block_engine_url: str, tip_account: str, default_tip_lamports: int = 1_000_000):
        self.block_engine_url = block_engine_url
        self.tip_account = Pubkey.from_string(tip_account)
        self.default_tip_lamports = default_tip_lamports

    def build_tip_instruction(self, payer: Pubkey, tip_lamports: Optional[int] = None) -> Instruction:
        """
        Creates the transfer instruction to pay the Jito validator tip.
        """
        lamports = tip_lamports if tip_lamports is not None else self.default_tip_lamports
        return transfer(
            TransferParams(
                from_pubkey=payer,
                to_pubkey=self.tip_account,
                lamports=lamports
            )
        )

    async def get_tip_recommendations(self) -> Dict[str, Any]:
        """
        Fetches current Jito tip recommendations to dynamic tip adjustments.
        """
        url = f"{self.block_engine_url}/api/v1/tips"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.error(f"Failed fetching Jito tips recommendations: {e}")
        return {}

    async def send_bundle(self, transactions: List[VersionedTransaction]) -> Optional[str]:
        """
        Sends an array of transactions as a Jito bundle.
        """
        # Serialize versioned transactions to base58 or base64 strings
        serialized_txs = []
        for tx in transactions:
            serialized_txs.append(base58.b58encode(bytes(tx)).decode("utf-8"))

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [serialized_txs]
        }

        url = f"{self.block_engine_url}/api/v1/bundles"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        bundle_id = res_json.get("result")
                        logger.info(f"Bundle successfully sent to Jito. Bundle ID: {bundle_id}")
                        return bundle_id
                    else:
                        body = await resp.text()
                        logger.error(f"Failed to submit bundle to Jito: Status {resp.status}, Body: {body}")
                        return None
        except Exception as e:
            logger.error(f"Exception sending Jito bundle: {e}")
            return None
