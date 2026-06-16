import collections
import polars as pl
from typing import Dict, Any, List, Optional

class MicrostructureEngine:
    """
    Calculates low-latency microstructure metrics from incoming trade streams.
    """
    def __init__(self, ofi_window_size: int = 50):
        self.ofi_window_size = ofi_window_size
        # Buffers for holding streaming trade events per mint
        self._trade_buffers: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=1000)
        )

    def append_trade(self, mint: str, is_buy: bool, price: float, amount: float):
        """
        Appends a tick update to the rolling buffers.
        """
        self._trade_buffers[mint].append({
            "is_buy": is_buy,
            "price": price,
            "amount": amount
        })

    def calculate_ofi(self, mint: str) -> float:
        """
        Order Flow Imbalance (OFI) measures the net supply/demand imbalance.
        OFI = Sum(Buy Volume * Price Change) - Sum(Sell Volume * Price Change)
        Simplified tick-level OFI over the configured sliding window.
        """
        trades = self._trade_buffers[mint]
        if len(trades) < 2:
            return 0.0
            
        # Select rolling window
        window = list(trades)[-self.ofi_window_size:]
        
        # Construct Polars Dataframe for fast calculation
        df = pl.DataFrame(window)
        
        # Convert to lists for element-wise calculation
        prices = df["price"].to_list()
        volumes = df["amount"].to_list()
        buys = df["is_buy"].to_list()
        
        ofi = 0.0
        for i in range(1, len(prices)):
            price_change = prices[i] - prices[i - 1]
            if buys[i]:
                # If buy pressure, positive contribution
                ofi += volumes[i] if price_change >= 0 else -volumes[i]
            else:
                # If sell pressure, negative contribution
                ofi -= volumes[i] if price_change <= 0 else -volumes[i]
                
        return float(ofi)

    def calculate_vpvr(self, mint: str, num_bins: int = 10) -> List[Dict[str, Any]]:
        """
        Volume Profile Visible Range (VPVR) nodes.
        Groups trading volume into price bins to locate High Volume Nodes (HVN).
        """
        trades = self._trade_buffers[mint]
        if not trades:
            return []
            
        df = pl.DataFrame(list(trades))
        prices = df["price"]
        volumes = df["amount"]
        
        min_p = prices.min()
        max_p = prices.max()
        
        if min_p == max_p:
            return [{"price_bin": min_p, "volume": volumes.sum()}]
            
        # Segment into price intervals and calculate total volume per bin
        bin_width = (max_p - min_p) / num_bins
        bins = []
        for i in range(num_bins):
            bin_start = min_p + i * bin_width
            bin_end = bin_start + bin_width
            
            # Filter volume in range
            mask = (prices >= bin_start) & (prices < bin_end)
            bin_vol = df.filter(mask)["amount"].sum()
            
            bins.append({
                "bin_start": float(bin_start),
                "bin_end": float(bin_end),
                "volume": float(bin_vol) if bin_vol else 0.0
            })
            
        return bins
