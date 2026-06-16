import polars as pl
from typing import Dict, Any, Tuple, Optional

class TechnicalIndicators:
    """
    Computes rapid high-volatility technical indicators using Polars expressions.
    """
    
    @staticmethod
    def calculate_rsi(prices: pl.Series, period: int = 14) -> Optional[float]:
        """
        Calculates Relative Strength Index (RSI).
        """
        if len(prices) < period + 1:
            return None
            
        # Compute differences
        diffs = prices.diff().slice(1)
        
        # Extract gains and losses
        gains = diffs.map_elements(lambda x: x if x > 0 else 0.0, return_dtype=pl.Float64)
        losses = diffs.map_elements(lambda x: -x if x < 0 else 0.0, return_dtype=pl.Float64)
        
        # Calculate Wilder's MA
        avg_gain = gains.slice(0, period).mean()
        avg_loss = losses.slice(0, period).mean()
        
        if avg_loss == 0:
            return 100.0
            
        for i in range(period, len(diffs)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def calculate_bollinger_bands(prices: pl.Series, period: int = 20, num_std: float = 2.0) -> Optional[Tuple[float, float, float]]:
        """
        Calculates Middle, Upper, and Lower Bollinger Bands.
        Returns: (lower_band, middle_band, upper_band)
        """
        if len(prices) < period:
            return None
            
        window = prices.slice(len(prices) - period, period)
        middle_band = float(window.mean())
        std_dev = float(window.std())
        
        upper_band = middle_band + (num_std * std_dev)
        lower_band = middle_band - (num_std * std_dev)
        
        return lower_band, middle_band, upper_band

    @staticmethod
    def calculate_macd(prices: pl.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Tuple[float, float, float]]:
        """
        Calculates MACD, Signal line, and Histogram.
        """
        if len(prices) < slow + signal:
            return None
            
        # Fast/Slow EMAs
        ema_fast = prices.ewm_mean(span=fast, adjust=False)
        ema_slow = prices.ewm_mean(span=slow, adjust=False)
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm_mean(span=signal, adjust=False)
        macd_histogram = macd_line - signal_line
        
        return float(macd_line[-1]), float(signal_line[-1]), float(macd_histogram[-1])
