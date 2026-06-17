import time
import logging
from typing import Dict
from src.state.windows import SlidingTradeWindow

logger = logging.getLogger("MMCoin.FeatureEngine")

class FeatureEngine:
    """
    Computes real-time streaming trade features (OFI, Trade Cadence, Buy/Sell volume imbalance)
    by leveraging stateful sliding windows.
    """
    def __init__(self, window_size: int = 50):
        self.window_size = window_size
        self._trade_windows: Dict[str, SlidingTradeWindow] = {}
        # OFI tracks cumulative price impact of order flows
        self._last_prices: Dict[str, float] = {}
        self._ofi_values: Dict[str, float] = {}

    def update(self, mint: str, side: str, price: float, amount_sol: float, amount_token: float) -> Dict[str, float]:
        """
        Appends trade and updates features.
        Returns computed features.
        """
        now = time.time()
        
        # 1. Initialize sliding window
        if mint not in self._trade_windows:
            self._trade_windows[mint] = SlidingTradeWindow(self.window_size)
            self._ofi_values[mint] = 0.0

        window = self._trade_windows[mint]
        window.add(now, side, amount_sol, amount_token)

        # 2. Incremental OFI calculation
        ofi = self._ofi_values[mint]
        if mint in self._last_prices:
            last_price = self._last_prices[mint]
            price_change = price - last_price
            
            if side == "buy":
                # Buy volume positive contribution if price didn't decrease
                ofi += amount_token if price_change >= 0 else -amount_token
            else:
                # Sell volume negative contribution if price didn't increase
                ofi -= amount_token if price_change <= 0 else -amount_token
        
        self._last_prices[mint] = price
        self._ofi_values[mint] = ofi

        # 3. Retrieve cadence & imbalances from window
        cadence = window.get_cadence()
        imbalance = window.get_imbalance()

        return {
            "ofi": ofi,
            "cadence": cadence,
            "imbalance": imbalance,
            "volume_sol": amount_sol
        }
