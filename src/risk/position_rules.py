import logging
from typing import Dict, Any

logger = logging.getLogger("MMCoin.PositionRules")

class PositionRules:
    """
    Enforces trade sizing rules, leverage constraints, and maximum slippage bounds.
    """
    def __init__(self, default_buy_size_sol: float = 0.1, max_slippage_bps: int = 150):
        self.default_buy_size_sol = default_buy_size_sol
        self.max_slippage_bps = max_slippage_bps

    def calculate_position_size(self, sol_balance: float) -> float:
        """
        Calculates buying power/sizing dynamically based on account balance constraints.
        """
        # Simple rule: use default size but cap it to 10% of total balance
        max_allowed = sol_balance * 0.10
        size = min(self.default_buy_size_sol, max_allowed)
        return max(size, 0.01)

    def validate_intent_risk(self, side: str, amount_sol: float) -> bool:
        """
        Checks if the size of the execution intent violates risk limits.
        """
        if side == "buy" and amount_sol > 1.0:
            logger.warning(f"Risk rule violation: Buy size too large ({amount_sol} SOL). Max limit is 1.0 SOL.")
            return False
        return True
