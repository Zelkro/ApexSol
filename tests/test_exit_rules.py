# pyrefly: ignore [missing-import]
"""
test_exit_rules.py — Unit tests for exit_rules.py.

Each exit condition is tested in isolation using a minimal
StrategyInput + StrategyContext pair.
"""

from __future__ import annotations

import time
import pytest

from src.engine.exit_rules import evaluate_exit
from src.engine.strategy_models import (
    DEFAULT_CONFIG,
    ExitReason,
    StrategyConfig,
    StrategyContext,
    StrategyInput,
    Verdict,
)
from src.ingestion.models import AuditVerdict


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _in_position_input(**overrides) -> StrategyInput:
    now = time.time()
    base = dict(
        mint="POS_MINT",
        slot=9_999_999,
        timestamp=now,
        first_seen_at=now - 60,
        last_seen_at=now,
        token_age_seconds=60.0,
        audit_status=AuditVerdict.ALLOW.value,
        in_position=True,
        cooldown_remaining_seconds=0.0,
        recent_trade_count=30,
        trade_velocity=3.0,
        buy_volume_sol=1.0,
        sell_volume_sol=0.2,
        buy_sell_imbalance=0.70,
        ofi=2_000.0,
        rolling_price=0.00110,       # entry_price=0.00100 → +10 %
        short_return=0.10,
        price_acceleration=0.01,
        unrealized_pnl=0.10,
        data_staleness_ms=100.0,
        system_slot_lag=2,
        queue_pressure=0.15,
        bundle_success_rate_recent=0.90,
    )
    base.update(overrides)
    return StrategyInput(**base)


def _position_ctx(
    entry_price: float = 0.00100,
    entry_time_offset: float = 30.0,     # seconds ago
    entry_velocity: float = 3.0,
    entry_imbalance: float = 0.70,
    entry_ofi: float = 2_000.0,
    partial_done: bool = False,
    **overrides,
) -> StrategyContext:
    now = time.time()
    base = dict(
        current_open_positions=1,
        total_exposure_sol=0.5,
        entry_price=entry_price,
        entry_time=now - entry_time_offset,
        entry_velocity=entry_velocity,
        entry_imbalance=entry_imbalance,
        entry_ofi=entry_ofi,
        partial_exit_done=partial_done,
    )
    base.update(overrides)
    return StrategyContext(**base)


# ---------------------------------------------------------------------------
# Stop loss
# ---------------------------------------------------------------------------

class TestStopLoss:

    def test_exit_on_stop_loss(self):
        # price dropped to 0.00094 → -6 % → below -5 % stop
        inp = _in_position_input(rolling_price=0.00094)
        ctx = _position_ctx(entry_price=0.00100)
        decision = evaluate_exit(inp, ctx, DEFAULT_CONFIG)
        assert decision.verdict == Verdict.EXIT
        assert decision.reason == ExitReason.STOP_LOSS

    def test_no_exit_on_small_loss(self):
        # price dropped to 0.00097 → -3 % → above stop
        inp = _in_position_input(rolling_price=0.00097)
        ctx = _position_ctx(entry_price=0.00100)
        decision = evaluate_exit(inp, ctx, DEFAULT_CONFIG)
        assert decision.reason != ExitReason.STOP_LOSS


# ---------------------------------------------------------------------------
# Take profit
# ---------------------------------------------------------------------------

class TestTakeProfit:

    def test_partial_take_profit(self):
        # +12 % → above partial TP (+10 %)
        inp = _in_position_input(rolling_price=0.00112)
        ctx = _position_ctx(entry_price=0.00100, partial_done=False)
        decision = evaluate_exit(inp, ctx, DEFAULT_CONFIG)
        assert decision.verdict == Verdict.REDUCE
        assert decision.reason == ExitReason.TAKE_PROFIT_PARTIAL

    def test_no_partial_if_already_done(self):
        inp = _in_position_input(rolling_price=0.00112)
        ctx = _position_ctx(entry_price=0.00100, partial_done=True)
        decision = evaluate_exit(inp, ctx, DEFAULT_CONFIG)
        # Should not be partial TP (already done) — may be HOLD or final TP
        assert decision.reason != ExitReason.TAKE_PROFIT_PARTIAL

    def test_final_take_profit(self):
        # +22 % → above final TP (+20 %)
        inp = _in_position_input(rolling_price=0.00122)
        ctx = _position_ctx(entry_price=0.00100)
        decision = evaluate_exit(inp, ctx, DEFAULT_CONFIG)
        assert decision.verdict == Verdict.EXIT
        assert decision.reason == ExitReason.TAKE_PROFIT_FINAL


# ---------------------------------------------------------------------------
# Time stop
# ---------------------------------------------------------------------------

class TestTimeStop:

    def test_exit_on_time_stop(self):
        cfg = StrategyConfig(time_stop_seconds=60.0)
        inp = _in_position_input(rolling_price=0.00100)  # flat
        ctx = _position_ctx(entry_price=0.00100, entry_time_offset=90.0)  # held 90 s > 60 s
        decision = evaluate_exit(inp, ctx, cfg)
        assert decision.verdict == Verdict.EXIT
        assert decision.reason == ExitReason.TIME_STOP

    def test_no_time_stop_early(self):
        cfg = StrategyConfig(time_stop_seconds=60.0)
        inp = _in_position_input(rolling_price=0.00100)
        ctx = _position_ctx(entry_price=0.00100, entry_time_offset=10.0)  # only 10 s
        decision = evaluate_exit(inp, ctx, cfg)
        assert decision.reason != ExitReason.TIME_STOP


# ---------------------------------------------------------------------------
# Momentum failure
# ---------------------------------------------------------------------------

class TestMomentumFailure:

    def test_exit_on_momentum_failure_post_confirmation(self):
        cfg = StrategyConfig(
            confirmation_window_seconds=15.0,
            time_stop_seconds=300.0,
            momentum_failure_velocity_drop=0.40,
            momentum_failure_imbalance_drop=0.20,
            momentum_failure_ofi_drop=0.50,
        )
        # Position held for 30 s (past confirmation window of 15 s)
        # All three signals degraded
        inp = _in_position_input(
            rolling_price=0.00101,    # barely positive, not hitting any TP
            trade_velocity=0.5,       # was 3.0, dropped 83 % → > 40 % threshold
            buy_sell_imbalance=0.40,  # was 0.70, dropped 0.30 → > 0.20 threshold
            ofi=500.0,               # was 2000, dropped 75 % → > 50 % threshold
        )
        ctx = _position_ctx(
            entry_price=0.00100,
            entry_time_offset=30.0,  # past confirmation window
            entry_velocity=3.0,
            entry_imbalance=0.70,
            entry_ofi=2_000.0,
        )
        decision = evaluate_exit(inp, ctx, cfg)
        assert decision.verdict in (Verdict.EXIT, Verdict.REDUCE)
        assert decision.reason == ExitReason.MOMENTUM_FAILURE


# ---------------------------------------------------------------------------
# Stale data
# ---------------------------------------------------------------------------

class TestStaleDataExit:

    def test_exit_on_stale_data(self):
        cfg = StrategyConfig(max_data_staleness_ms=2_000.0)
        inp = _in_position_input(data_staleness_ms=5_000.0)
        ctx = _position_ctx()
        decision = evaluate_exit(inp, ctx, cfg)
        assert decision.verdict == Verdict.EXIT
        assert decision.reason == ExitReason.DATA_STALE


# ---------------------------------------------------------------------------
# Hold — healthy position
# ---------------------------------------------------------------------------

class TestHold:

    def test_hold_on_healthy_position(self):
        cfg = StrategyConfig(
            stop_loss_pct=-0.05,
            take_profit_partial_pct=0.10,
            take_profit_final_pct=0.20,
            time_stop_seconds=300.0,
            confirmation_window_seconds=15.0,
        )
        # price at +2 % (no TP, no SL), position is 30 s old
        inp = _in_position_input(
            rolling_price=0.00102,
            trade_velocity=3.0,
            buy_sell_imbalance=0.70,
            ofi=2_000.0,
            data_staleness_ms=80.0,
            system_slot_lag=2,
            queue_pressure=0.15,
            bundle_success_rate_recent=0.92,
        )
        ctx = _position_ctx(
            entry_price=0.00100,
            entry_time_offset=30.0,
            entry_velocity=2.8,
            entry_imbalance=0.68,
            entry_ofi=1_900.0,
            partial_done=False,
        )
        decision = evaluate_exit(inp, ctx, cfg)
        assert decision.verdict == Verdict.HOLD
        assert decision.reason == ExitReason.HOLD
