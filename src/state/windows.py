import collections
from typing import Optional, Tuple

class SlidingPriceWindow:
    """
    Stateful rolling price window that maintains sums and squared sums
    to calculate rolling mean and variance in O(1) time.
    """
    def __init__(self, size: int):
        self.size = size
        self.prices = collections.deque(maxlen=size)
        self.sum = 0.0
        self.sum_squares = 0.0

    def add(self, price: float):
        if len(self.prices) == self.size:
            old = self.prices.popleft()
            self.sum -= old
            self.sum_squares -= old ** 2
            
        self.prices.append(price)
        self.sum += price
        self.sum_squares += price ** 2

    @property
    def count(self) -> int:
        return len(self.prices)

    @property
    def is_full(self) -> bool:
        return len(self.prices) == self.size

    def get_stats(self) -> Optional[Tuple[float, float]]:
        """
        Returns (mean, variance).
        """
        n = len(self.prices)
        if n < 2:
            return None
        mean = self.sum / n
        variance = (self.sum_squares / n) - (mean ** 2)
        return mean, max(0.0, variance)


class SlidingTradeWindow:
    """
    Tracks trade cadence and volumes over a sliding window.
    """
    def __init__(self, size: int):
        self.size = size
        self.trades = collections.deque(maxlen=size)

    def add(self, timestamp: float, side: str, amount_sol: float, amount_token: float):
        self.trades.append({
            "timestamp": timestamp,
            "side": side,
            "amount_sol": amount_sol,
            "amount_token": amount_token
        })

    def get_cadence(self) -> float:
        """
        Returns number of trades per second in the window.
        """
        n = len(self.trades)
        if n < 2:
            return 0.0
        duration = self.trades[-1]["timestamp"] - self.trades[0]["timestamp"]
        return n / duration if duration > 0.0 else 0.0

    def get_imbalance(self) -> float:
        """
        Returns ratio of buy sol volume to total sol volume.
        """
        buys = sum(t["amount_sol"] for t in self.trades if t["side"] == "buy")
        sells = sum(t["amount_sol"] for t in self.trades if t["side"] == "sell")
        total = buys + sells
        return buys / total if total > 0.0 else 0.5
