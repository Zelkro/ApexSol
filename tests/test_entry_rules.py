"""
test_entry_rules.py — Unit tests for entry_rules.py.

Tests each eligibility gate and entry condition independently.
"""

from __future__ import annotations

import time
import pytest

from src.engine.entry_rules import (
    check_entry_conditions,
    evaluate_entry,
    is_overextended,
    is_token_eligible,
)
from src.engine.strategy_models import (
    DEFAULT_CONFIG,
    ENTRY_THRESHOLDS,
    NoTradeReason,
    SetupProfile,
    StrategyConfig,
    StrategyContext,
    StrategyInput,
)
from src.ingestion.models import AuditVerdict


def _inp(**overrides) -> StrategyInput:
    now = time.time()
    base = dict(
        mint="TEST_MINT",
        slot=1000,
        timestamp=now,
        first_seen_at=now - 20,
        last_seen_at=now,
        token_age_seconds=20.0,
        audit_status=AuditVerdict.ALLOW.value,
        in_position=False,
        cooldown_remaining_seconds=0.0,
        recent_trade_count=10,
        trade_velocity=2.5,
        buy_volume_sol=0.6,
        sell_volume_sol=0.1,
        buy_sell_imbalance=0.75,
        ofi=2_000.0,
        rolling_price=0.001,
        short_return=0.04,
        price_acceleration=0.02,
        data_staleness_ms=50.0,
        system_slot_lag=1,
        queue_pressure=0.10,
        bundle_success_rate_recent=0.95,
    )
    base.update(overrides)
    return StrategyInput(**base)


def _ctx(**overrides) -> StrategyContext:
    base = dict(current_open_positions=0, total_exposure_sol=0.0)
    base.update(overrides)
    return StrategyContext(**base)


def _cfg(setup=SetupProfile.CONSERVATIVE) -> StrategyConfig:
    return StrategyConfig(setup_profile=setup)


# ---------------------------------------------------------------------------
# is_token_eligible
# ---------------------------------------------------------------------------

class TestIsTokenEligible:

    def test_eligible_on_clean_input(self):
        eligible, reason, _ = is_token_eligible(_inp(), _ctx(), _cfg())
        assert eligible is True
        assert reason is None

    def test_blocks_audit_denied(self):
        eligible, reason, _ = is_token_eligible(_inp(audit_status=AuditVerdict.DENY.value), _ctx(), _cfg())
        assert eligible is False
        assert reason == NoTradeReason.AUDIT_DENIED

    def test_blocks_audit_pending(self):
        eligible, reason, _ = is_token_eligible(_inp(audit_status=AuditVerdict.PENDING.value), _ctx(), _cfg())
        assert eligible is False
        assert reason == NoTradeReason.AUDIT_PENDING

    def test_blocks_stale_data(self):
        cfg = StrategyConfig(max_data_staleness_ms=500.0)
        eligible, reason, _ = is_token_eligible(_inp(data_staleness_ms=1_000.0), _ctx(), cfg)
        assert eligible is False
        assert reason == NoTradeReason.DATA_STALE

    def test_blocks_slot_lag(self):
        cfg = StrategyConfig(max_slot_lag=5)
        eligible, reason, _ = is_token_eligible(_inp(system_slot_lag=20), _ctx(), cfg)
        assert eligible is False
        assert reason == NoTradeReason.SLOT_LAG_TOO_HIGH

    def test_blocks_queue_pressure(self):
        eligible, reason, _ = is_token_eligible(_inp(queue_pressure=0.99), _ctx(), _cfg())
        assert eligible is False
        assert reason == NoTradeReason.QUEUE_PRESSURE_HIGH

    def test_blocks_bundle_success_rate(self):
        eligible, reason, _ = is_token_eligible(_inp(bundle_success_rate_recent=0.20), _ctx(), _cfg())
        assert eligible is False
        assert reason == NoTradeReason.BUNDLE_SUCCESS_LOW

    def test_blocks_token_too_old(self):
        eligible, reason, _ = is_token_eligible(_inp(token_age_seconds=500.0), _ctx(), _cfg())
        assert eligible is False
        assert reason == NoTradeReason.TOKEN_TOO_OLD

    def test_blocks_cooldown(self):
        eligible, reason, _ = is_token_eligible(_inp(cooldown_remaining_seconds=30.0), _ctx(), _cfg())
        assert eligible is False
        assert reason == NoTradeReason.COOLDOWN_ACTIVE

    def test_blocks_low_trade_count(self):
        cfg = StrategyConfig(min_trade_count=10)
        eligible, reason, _ = is_token_eligible(_inp(recent_trade_count=3), _ctx(), cfg)
        assert eligible is False
        assert reason == NoTradeReason.TRADE_COUNT_LOW


# ---------------------------------------------------------------------------
# is_overextended
# ---------------------------------------------------------------------------

class TestIsOverextended:

    def test_not_overextended_on_normal_input(self):
        thresholds = ENTRY_THRESHOLDS[SetupProfile.BALANCED]
        overextended, _ = is_overextended(_inp(short_return=0.10), thresholds, _cfg(SetupProfile.BALANCED))
        assert overextended is False

    def test_overextended_on_high_short_return(self):
        thresholds = ENTRY_THRESHOLDS[SetupProfile.BALANCED]
        overextended, reason = is_overextended(_inp(short_return=0.80), thresholds, _cfg(SetupProfile.BALANCED))
        assert overextended is True
        assert "short_return" in reason

    def test_overextended_on_high_acceleration(self):
        thresholds = ENTRY_THRESHOLDS[SetupProfile.CONSERVATIVE]
        overextended, reason = is_overextended(_inp(price_acceleration=0.50), thresholds, _cfg())
        assert overextended is True
        assert "price_acceleration" in reason


# ---------------------------------------------------------------------------
# check_entry_conditions
# ---------------------------------------------------------------------------

class TestCheckEntryConditions:

    def test_all_conditions_met(self):
        thresholds = ENTRY_THRESHOLDS[SetupProfile.BALANCED]
        met, reasons = check_entry_conditions(_inp(), thresholds)
        assert met is True
        # All reasons should be success markers
        assert all("FAIL" not in r for r in reasons)

    def test_fails_on_low_velocity(self):
        thresholds = ENTRY_THRESHOLDS[SetupProfile.CONSERVATIVE]
        met, reasons = check_entry_conditions(_inp(trade_velocity=0.1), thresholds)
        assert met is False
        assert any("FAIL" in r and "velocity" in r for r in reasons)

    def test_fails_on_low_ofi(self):
        thresholds = ENTRY_THRESHOLDS[SetupProfile.CONSERVATIVE]
        met, reasons = check_entry_conditions(_inp(ofi=10.0), thresholds)
        assert met is False
        assert any("FAIL" in r and "ofi" in r for r in reasons)


# ---------------------------------------------------------------------------
# evaluate_entry (full pipeline)
# ---------------------------------------------------------------------------

class TestEvaluateEntry:

    def test_approve_on_valid_input(self):
        cfg = _cfg(SetupProfile.BALANCED)
        decision = evaluate_entry(_inp(), _ctx(), cfg)
        assert decision.eligible is True
        assert decision.conditions_met is True
        assert decision.blocking_reason is None

    def test_block_on_already_in_position(self):
        decision = evaluate_entry(_inp(in_position=True), _ctx(), _cfg())
        assert decision.blocking_reason == NoTradeReason.ALREADY_IN_POSITION

    def test_block_on_fomo(self):
        cfg = _cfg(SetupProfile.CONSERVATIVE)
        # short_return > CONSERVATIVE fomo limit (0.25)
        decision = evaluate_entry(_inp(short_return=0.40), _ctx(), cfg)
        assert decision.blocking_reason == NoTradeReason.FOMO_OVEREXTENSION
        assert decision.conditions_met is True   # conditions passed, FOMO blocked it
