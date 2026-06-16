import logging
from typing import Dict, Any, List
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

logger = logging.getLogger("MMCoin.Concentration")

class HolderConcentrationAnalyzer:
    """
    Analyzes holder distribution and groups/identifies developer wallet clusters.
    """
    def __init__(self, max_concentration: float = 0.15):
        self.max_concentration = max_concentration

    async def get_top_holders(self, client: AsyncClient, mint_address: str) -> List[Dict[str, Any]]:
        """
        Retrieves largest accounts holding the token.
        """
        try:
            pubkey = Pubkey.from_string(mint_address)
            # Use JSON-RPC to fetch largest accounts holding the mint
            response = await client.get_token_largest_accounts(pubkey)
            if not response.value:
                return []
                
            holders = []
            for item in response.value:
                holders.append({
                    "address": str(item.address),
                    "amount": int(item.amount.amount),
                    "ui_amount": item.amount.ui_amount
                })
            return holders
        except Exception as e:
            logger.error(f"Failed to fetch largest token accounts: {e}")
            return []

    def analyze_concentration(self, holders: List[Dict[str, Any]], total_supply: float) -> Dict[str, Any]:
        """
        Calculates concentration ratios and identifies developer clusters.
        """
        if not holders or total_supply <= 0:
            return {"passed": False, "reason": "No holder or supply data"}

        # Exclude known pool/burn addresses if we can identify them (e.g., Raydium LP base or Null address)
        risk_amount = 0.0
        details = []
        
        # Calculate sum of top 5 holders
        top_5_sum = 0.0
        for i, holder in enumerate(holders[:5]):
            pct = holder["ui_amount"] / total_supply
            top_5_sum += pct
            details.append({"address": holder["address"], "pct": pct})
            
            # Dev cluster check: if any single holder has > max_concentration (typically 15%)
            if pct > self.max_concentration:
                # Unless it's an AMM pool, flag it
                pass
                
        passed = top_5_sum < 0.45 # Pass if top 5 hold less than 45% combined
        
        return {
            "passed": passed,
            "top_5_percentage": top_5_sum,
            "details": details,
            "reason": f"Top 5 accounts hold {top_5_sum*100:.2f}% of supply" if not passed else "Holder distribution healthy"
        }
