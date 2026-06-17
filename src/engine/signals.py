import time
import uuid
import logging
from typing import Optional
from src.ingestion.models import TokenState, SignalEvent, AuditVerdict
from src.config.settings import settings

logger = logging.getLogger("MMCoin.SignalEngine")

class SignalEngine:
    """
    Deterministic rule-based entry and exit signals engine.
    Does not use black-box ML algorithms; relies strictly on configurable metrics thresholds.
    """
    def __init__(self, entry_trade_count_threshold: int = 5, entry_buy_sol_threshold: float = 0.5, entry_ofi_threshold: float = 1000.0):
        self.entry_trade_count_threshold = entry_trade_count_threshold
        self.entry_buy_sol_threshold = entry_buy_sol_threshold
        self.entry_ofi_threshold = entry_ofi_threshold

    def evaluate_entry(self, state: TokenState, current_slot: int) -> Optional[SignalEvent]:
        """
        Evaluates rules to decide whether to trigger an entry/buy order.
        """
        # 1. Reject if already in position
        if state.in_position:
            return None

        # 2. Reject if security audit failed or is pending
        if state.audit_status != AuditVerdict.ALLOW:
            return None

        # 3. Check slot lag
        slot_lag = current_slot - state.last_slot
        if slot_lag > settings.max_slot_lag:
            logger.debug(f"Entry rejected for {state.mint}: Slot lag too high ({slot_lag} slots)")
            return None

        # 4. Check data staleness
        if time.time() - state.last_seen_at > settings.staleness_threshold_seconds:
            logger.debug(f"Entry rejected for {state.mint}: state data is stale")
            return None

        # 5. Check thresholds (OFI, Trade count, Buy volume)
        if (state.recent_trade_count >= self.entry_trade_count_threshold and 
            state.buy_volume_sol >= self.entry_buy_sol_threshold and 
            state.ofi >= self.entry_ofi_threshold):
            
            logger.info(f"🚨 ENTRY SIGNAL TRIGGERED for {state.mint} | OFI: {state.ofi:.1f}, Trades: {state.recent_trade_count}")
            return SignalEvent(
                event_id=uuid.uuid4().hex,
                mint=state.mint,
                signal_type="entry",
                reason=f"OFI={state.ofi:.1f}, Trades={state.recent_trade_count}, BuyVolSol={state.buy_volume_sol:.2f}",
                price=state.rolling_price,
                slot=current_slot,
                timestamp=time.time()
            )

        return None

    def evaluate_exit(self, state: TokenState, entry_price: float, entry_time: float, current_slot: int) -> Optional[SignalEvent]:
        """
        Evaluates exit rules (Stop-loss, Take-profit, Timeout, Risk guards).
        """
        if not state.in_position:
            return None

        now = time.time()
        current_price = state.rolling_price
        
        # Calculate return
        price_return = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

        # 1. Stop-Loss (e.g., -5%)
        if price_return <= -0.05:
            logger.info(f"🚨 EXIT SIGNAL (Stop Loss) for {state.mint} | Return: {price_return:.2%}")
            return SignalEvent(
                event_id=uuid.uuid4().hex,
                mint=state.mint,
                signal_type="exit",
                reason=f"Stop Loss triggered: return={price_return:.2%}",
                price=current_price,
                slot=current_slot,
                timestamp=now
            )

        # 2. Take-Profit (e.g., +15%)
        if price_return >= 0.15:
            logger.info(f"🚨 EXIT SIGNAL (Take Profit) for {state.mint} | Return: {price_return:.2%}")
            return SignalEvent(
                event_id=uuid.uuid4().hex,
                mint=state.mint,
                signal_type="exit",
                reason=f"Take Profit triggered: return={price_return:.2%}",
                price=current_price,
                slot=current_slot,
                timestamp=now
            )

        # 3. Position Timeout (e.g., 300 seconds)
        position_age = now - entry_time
        if position_age > 300.0:
            logger.info(f"🚨 EXIT SIGNAL (Position Timeout) for {state.mint} | Age: {position_age:.1f}s")
            return SignalEvent(
                event_id=uuid.uuid4().hex,
                mint=state.mint,
                signal_type="exit",
                reason=f"Position timeout: age={position_age:.1f}s",
                price=current_price,
                slot=current_slot,
                timestamp=now
            )

        # 4. Momentum loss: RSI indicates overbought divergence (e.g. RSI > 80)
        if state.rsi and state.rsi > 80.0:
            logger.info(f"🚨 EXIT SIGNAL (RSI Overbought) for {state.mint} | RSI: {state.rsi:.1f}")
            return SignalEvent(
                event_id=uuid.uuid4().hex,
                mint=state.mint,
                signal_type="exit",
                reason=f"RSI overbought: RSI={state.rsi:.1f}",
                price=current_price,
                slot=current_slot,
                timestamp=now
            )

        return None
