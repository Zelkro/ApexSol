import collections
import math
from typing import Tuple, Optional

class O1BollingerBands:
    """
    Stateful O(1) calculator for Bollinger Bands.
    """
    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period = period
        self.num_std = num_std
        self.prices = collections.deque()
        self.sum_x = 0.0
        self.sum_x2 = 0.0

    def update(self, price: float) -> Optional[Tuple[float, float, float]]:
        if len(self.prices) == self.period:
            old_p = self.prices.popleft()
            self.sum_x -= old_p
            self.sum_x2 -= old_p ** 2

        self.prices.append(price)
        self.sum_x += price
        self.sum_x2 += price ** 2

        if len(self.prices) < self.period:
            return None

        mu = self.sum_x / self.period
        variance = (self.sum_x2 / self.period) - (mu ** 2)
        std_dev = math.sqrt(max(0.0, variance))

        lower = mu - (self.num_std * std_dev)
        upper = mu + (self.num_std * std_dev)
        return lower, mu, upper


class O1RSI:
    """
    Stateful O(1) calculator for Relative Strength Index (RSI) using Wilder's smoothed MA.
    """
    def __init__(self, period: int = 14):
        self.period = period
        self.last_price = None
        self.gains_history = collections.deque(maxlen=period)
        self.losses_history = collections.deque(maxlen=period)
        self.avg_gain = None
        self.avg_loss = None
        self.count = 0

    def update(self, price: float) -> Optional[float]:
        if self.last_price is None:
            self.last_price = price
            return None

        diff = price - self.last_price
        self.last_price = price

        gain = max(0.0, diff)
        loss = max(0.0, -diff)

        self.count += 1

        if self.count < self.period:
            self.gains_history.append(gain)
            self.losses_history.append(loss)
            return None
        
        elif self.count == self.period:
            self.gains_history.append(gain)
            self.losses_history.append(loss)
            self.avg_gain = sum(self.gains_history) / self.period
            self.avg_loss = sum(self.losses_history) / self.period
        else:
            # Wilder's smoothing EMA formula:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period

        if self.avg_loss == 0.0:
            return 100.0

        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
