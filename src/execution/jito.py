# pyrefly: ignore [missing-import]
import base64
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
        Fetches current Jito tip recommendations for dynamic tip adjustments.
        Queries the Jito Bundles Tip Floor API.
        """
        url = "https://bundles.jito.wtf/api/v1/bundles/tip_floor"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # If data is a list, retrieve the first element
                        if isinstance(data, list) and len(data) > 0:
                            data = data[0]
                        
                        # Convert SOL percentiles to lamports (1 SOL = 1,000,000,000 lamports)
                        recommendations = {}
                        for k, v in data.items():
                            if "percentile" in k and isinstance(v, (int, float)):
                                recommendations[k] = int(v * 1_000_000_000)
                        return recommendations
        except Exception as e:
            logger.error(f"Failed fetching Jito tips recommendations: {e}")
        return {}


    async def send_bundle(self, transactions: List[VersionedTransaction]) -> Optional[str]:
        """
        Sends an array of transactions as a Jito bundle.
        """
        # Serialize versioned transactions to base64 strings (faster and recommended by Jito)
        serialized_txs = []
        for tx in transactions:
            serialized_txs.append(base64.b64encode(bytes(tx)).decode("utf-8"))

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [
                serialized_txs,
                {"encoding": "base64"}
            ]
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
