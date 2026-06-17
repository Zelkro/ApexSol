import logging
from typing import List, Dict, Any
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

logger = logging.getLogger("ApexSol.ConcentrationAnalyzer")

class HolderConcentrationAnalyzer:
    """
    Analyzes the concentration of tokens held by developers or top wallets
    to detect potential rug-pull/dump risks.
    """
    def __init__(self, max_concentration: float = 0.15):
        self.max_concentration = max_concentration

    async def get_top_holders(self, client: AsyncClient, mint_address: str) -> List[Dict[str, Any]]:
        """
        Fetches the largest token accounts for a given mint.
        """
        try:
            pubkey = Pubkey.from_string(mint_address)
            # Fetch largest token accounts from chain
            response = await client.get_token_largest_accounts(pubkey)
            if not response or not response.value:
                return []
            
            holders = []
            for item in response.value:
                holders.append({
                    "address": str(item.address),
                    "amount": float(item.amount.ui_amount) if item.amount.ui_amount else 0.0
                })
            return holders
        except Exception as e:
            logger.debug(f"Failed to fetch largest token accounts for {mint_address}: {e}")
            return []

    def analyze_concentration(self, holders: List[Dict[str, Any]], total_supply: float) -> Dict[str, Any]:
        """
        Analyzes concentration risk of top holders.
        Returns check passed/failed status and reason.
        """
        if not holders or total_supply == 0.0:
            return {"passed": True, "reason": "No holders data or supply is zero"}

        # Exclude known pool address or system accounts if identified.
        # Check if the single largest holder owns more than the configured ratio
        largest_holder = holders[0]
        ratio = largest_holder["amount"] / total_supply
        
        if ratio > self.max_concentration:
            return {
                "passed": False,
                "reason": f"Top holder {largest_holder['address']} owns {ratio:.2%} of supply (limit={self.max_concentration:.2%})"
            }

        return {"passed": True, "reason": "Concentration within acceptable limits"}
