"""
test_strategy.py — Integration-level tests for the Strategy orchestrator.

Tests validate the full pipeline: entry → score → sizing → decision.
All tests use isolated, minimal StrategyInput / StrategyContext fixtures.
"""

from __future__ import annotations

import time
import pytest

from src.engine.strategy import Strategy
from src.engine.strategy_models import (
    DEFAULT_CONFIG,
    SetupProfile,
    SizingProfile,
    StrategyConfig,
    StrategyContext,
    StrategyInput,
    Verdict,
    NoTradeReason,
    ExitReason,
    SIZING_CAPS,
)
from src.ingestion.models import AuditVerdict


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_input(**overrides) -> StrategyInput:
    """
    Returns a valid StrategyInput that should produce ENTER under BALANCED setup.
    Override specific fields to test boundary conditions.
    """
    now = time.time()
    defaults = dict(
        mint="TOKEN_ABC",
        slot=12_345_678,
        timestamp=now,
        first_seen_at=now - 30,
        last_seen_at=now - 0.1,
        token_age_seconds=30.0,
        audit_status=AuditVerdict.ALLOW.value,
        in_position=False,
        cooldown_remaining_seconds=0.0,
        recent_trade_count=20,
        trade_velocity=3.0,
        buy_volume_sol=0.8,
        sell_volume_sol=0.2,
        buy_sell_imbalance=0.72,
        ofi=1_200.0,
        rolling_price=0.001,
        short_return=0.05,
        price_acceleration=0.03,
        unrealized_pnl=0.0,
        data_staleness_ms=100.0,
        system_slot_lag=2,
        queue_pressure=0.20,
        bundle_success_rate_recent=0.90,
    )
    defaults.update(overrides)
    return StrategyInput(**defaults)


def _base_ctx(**overrides) -> StrategyContext:
    defaults = dict(
        current_open_positions=0,
        total_exposure_sol=0.0,
    )
    defaults.update(overrides)
    return StrategyContext(**defaults)


def _balanced_strategy() -> Strategy:
    cfg = StrategyConfig(
        setup_profile=SetupProfile.BALANCED,
        sizing_profile=SizingProfile.NORMAL,
        min_score_to_enter=30.0,
    )
    return Strategy(config=cfg)


# ---------------------------------------------------------------------------
# NO_TRADE — eligibility gates
# ---------------------------------------------------------------------------

class TestEligibilityGates:

    def test_no_trade_if_audit_denied(self):
        strategy = _balanced_strategy()
        inp = _base_input(audit_status=AuditVerdict.DENY.value)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.AUDIT_DENIED

    def test_no_trade_if_audit_pending(self):
        strategy = _balanced_strategy()
        inp = _base_input(audit_status=AuditVerdict.PENDING.value)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.AUDIT_PENDING

    def test_no_trade_if_data_stale(self):
        strategy = _balanced_strategy()
        inp = _base_input(data_staleness_ms=5_000.0)   # above 2 000 ms default
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.DATA_STALE

    def test_no_trade_if_slot_lag_high(self):
        strategy = _balanced_strategy()
        inp = _base_input(system_slot_lag=50)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.SLOT_LAG_TOO_HIGH

    def test_no_trade_if_queue_pressure_high(self):
        strategy = _balanced_strategy()
        inp = _base_input(queue_pressure=0.95)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.QUEUE_PRESSURE_HIGH

    def test_no_trade_if_bundle_success_rate_low(self):
        strategy = _balanced_strategy()
        inp = _base_input(bundle_success_rate_recent=0.30)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.BUNDLE_SUCCESS_LOW

    def test_no_trade_if_token_too_old(self):
        strategy = _balanced_strategy()
        inp = _base_input(token_age_seconds=300.0)  # above 120 s default
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.TOKEN_TOO_OLD

    def test_no_trade_if_cooldown_active(self):
        strategy = _balanced_strategy()
        inp = _base_input(cooldown_remaining_seconds=15.0)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.COOLDOWN_ACTIVE


# ---------------------------------------------------------------------------
# NO_TRADE — position & FOMO
# ---------------------------------------------------------------------------

class TestPositionAndFomo:

    def test_no_trade_if_already_in_position(self):
        strategy = _balanced_strategy()
        inp = _base_input(in_position=True)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.ALREADY_IN_POSITION

    def test_no_trade_if_overextended_short_return(self):
        strategy = _balanced_strategy()
        # BALANCED fomo limit = 0.35; short_return=0.50 > limit
        inp = _base_input(short_return=0.50)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.FOMO_OVEREXTENSION

    def test_no_trade_if_overextended_acceleration(self):
        strategy = _balanced_strategy()
        # BALANCED fomo limit = 0.20; acceleration=0.25 > limit
        inp = _base_input(price_acceleration=0.25)
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.NO_TRADE
        assert decision.no_trade_reason == NoTradeReason.FOMO_OVEREXTENSION


# ---------------------------------------------------------------------------
# ENTER — happy path
# ---------------------------------------------------------------------------

class TestEnterHappyPath:

    def test_enter_on_valid_balanced_setup(self):
        strategy = _balanced_strategy()
        inp = _base_input()
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.verdict == Verdict.ENTER
        assert decision.score > 0
        assert decision.sizing is not None
        assert decision.sizing.approved
        assert decision.sizing.size_sol > 0

    def test_enter_decision_is_fully_populated(self):
        strategy = _balanced_strategy()
        inp = _base_input()
        decision = strategy.evaluate_opportunity(inp, _base_ctx())
        assert decision.mint == "TOKEN_ABC"
        assert decision.slot == 12_345_678
        assert decision.timestamp > 0
        assert decision.score_breakdown is not None
        assert len(decision.reasons) > 0


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

class TestSizing:

    def test_sizing_reduced_on_infra_degradation(self):
        strategy = _balanced_strategy()

        # Good infra
        inp_good = _base_input(queue_pressure=0.10, system_slot_lag=1, bundle_success_rate_recent=0.99)
        d_good = strategy.evaluate_opportunity(inp_good, _base_ctx())

        # Degraded infra (just below gate thresholds, but enough to reduce)
        inp_bad = _base_input(queue_pressure=0.70, system_slot_lag=8, bundle_success_rate_recent=0.65)
        d_bad = strategy.evaluate_opportunity(inp_bad, _base_ctx())

        if d_good.verdict == Verdict.ENTER and d_bad.verdict == Verdict.ENTER:
            assert d_bad.sizing.size_sol < d_good.sizing.size_sol

    def test_no_trade_if_max_positions_reached(self):
        strategy = _balanced_strategy()
        inp = _base_input()
        ctx = _base_ctx(
            current_open_positions=SIZING_CAPS.max_concurrent_positions,
            total_exposure_sol=0.5,
        )
        decision = strategy.evaluate_opportunity(inp, ctx)
        assert decision.verdict == Verdict.NO_TRADE
