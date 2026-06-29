# pyrefly: ignore [missing-import]
import logging
from typing import List, Optional
from solana.rpc.async_api import AsyncClient
from src.config.settings import settings

logger = logging.getLogger("MMCoin.FeeManager")

class FeeManager:
    """
    Computes priority fees dynamically depending on configured strategy (fixed, percentile, adaptive).
    """
    def __init__(self, max_fee_lamports: int = 5_000_000):
        self.max_fee_lamports = max_fee_lamports

    async def estimate_priority_fee(self, client: AsyncClient, addresses: List[str]) -> int:
        strategy = settings.priority_fee_strategy
        
        if strategy == "fixed":
            return 10_000  # Default base micro-lamports priority fee
            
        try:
            # Query recent prioritization fees for specified accounts on chain
            response = await client.get_recent_prioritization_fees(addresses)
            if not response or not response.value:
                return 10_000
                
            fees = [item.prioritization_fee for item in response.value]
            if not fees:
                return 10_000
                
            fees.sort()
            
            if strategy == "percentile":
                # Take the 75th percentile to ensure fast slot placement
                idx = int(len(fees) * 0.75)
                estimated = fees[idx]
            elif strategy == "adaptive":
                # Take 95th percentile under heavy congestion
                idx = int(len(fees) * 0.95)
                estimated = fees[idx]
            else:
                estimated = 10_000
                
            return min(estimated, self.max_fee_lamports)
        except Exception as e:
            logger.debug(f"Failed to query prioritization fees: {e}. Falling back to 10000.")
            return 10_000
