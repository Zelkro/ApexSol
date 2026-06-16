import logging
from typing import Dict, Any, Optional
from solana.rpc.async_api import AsyncClient
from solders.transaction import VersionedTransaction

logger = logging.getLogger("MMCoin.Fees")

class FeeManager:
    """
    Handles dynamic priority fee calculation and simulation safety gates.
    """
    def __init__(self, max_fee_lamports: int = 5_000_000):
        self.max_fee_lamports = max_fee_lamports

    async def estimate_priority_fee(self, client: AsyncClient, addresses: list) -> int:
        """
        Queries the Solana node for recent prioritization fees for specific accounts.
        """
        try:
            # Fetch recent priorization fees for target accounts (e.g. Pump.fun program, LP)
            response = await client.get_recent_prioritization_fees(addresses)
            if not response.value:
                return 10_000 # Default fallback base micro-lamports priority fee
                
            # Compute percentile-based fee to ensure top block placement
            fees = [item.prioritization_fee for item in response.value]
            if not fees:
                return 10_000
                
            fees.sort()
            # Select 75th percentile fee
            idx = int(len(fees) * 0.75)
            estimated = fees[idx]
            
            # Cap the maximum safety fee
            return min(estimated, self.max_fee_lamports)
        except Exception as e:
            logger.error(f"Failed to estimate priority fee: {e}")
            return 10_000

    async def simulate_and_validate(self, client: AsyncClient, tx: VersionedTransaction) -> bool:
        """
        Simulates the transaction on-chain prior to dispatch.
        Aborts execution if pre-simulation fails or flags errors.
        """
        try:
            sim_resp = await client.simulate_transaction(tx)
            if sim_resp.value.err:
                logger.error(f"Pre-simulation failed: {sim_resp.value.err}")
                return False
                
            logger.info("Pre-simulation passed successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed simulating transaction: {e}")
            return False
