# pyrefly: ignore [missing-import]
"""
test_sizing.py — Unit tests for sizing.py.
"""

from __future__ import annotations

import time
import pytest

from src.engine.sizing import compute_position_size
from src.engine.strategy_models import (
    DEFAULT_CONFIG,
    NoTradeReason,
    SizingProfile,
    StrategyConfig,
    StrategyContext,
    StrategyInput,
    SIZING_CAPS,
)
from src.ingestion.models import AuditVerdict


def _inp(**overrides) -> StrategyInput:
    now = time.time()
    base = dict(
        mint="SIZE_MINT",
        slot=1000,
        timestamp=now,
        first_seen_at=now - 20,
        last_seen_at=now,
        token_age_seconds=20.0,
        audit_status=AuditVerdict.ALLOW.value,
        in_position=False,
        cooldown_remaining_seconds=0.0,
        recent_trade_count=20,
        trade_velocity=3.0,
        buy_volume_sol=1.0,
        sell_volume_sol=0.2,
        buy_sell_imbalance=0.72,
        ofi=2_000.0,
        rolling_price=0.001,
        short_return=0.05,
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


class TestSizingApproval:

    def test_approved_on_clean_input(self):
        result = compute_position_size(_inp(), _ctx(), DEFAULT_CONFIG, score=75.0)
        assert result.approved is True
        assert result.size_sol > 0

    def test_size_within_per_token_cap(self):
        # Use assertive profile which has higher base
        cfg = StrategyConfig(sizing_profile=SizingProfile.ASSERTIVE)
        result = compute_position_size(_inp(), _ctx(), cfg, score=90.0)
        assert result.size_sol <= SIZING_CAPS.max_position_sol

    def test_size_within_global_exposure(self):
        remaining = 0.30
        ctx = _ctx(total_exposure_sol=SIZING_CAPS.max_global_exposure_sol - remaining)
        result = compute_position_size(_inp(), _ctx(total_exposure_sol=SIZING_CAPS.max_global_exposure_sol - remaining), DEFAULT_CONFIG, score=80.0)
        assert result.size_sol <= remaining + 1e-9

    def test_refused_on_max_concurrent_positions(self):
        ctx = _ctx(current_open_positions=SIZING_CAPS.max_concurrent_positions)
        result = compute_position_size(_inp(), ctx, DEFAULT_CONFIG, score=80.0)
        assert result.approved is False
        assert result.rejection_reason == NoTradeReason.SIZE_TOO_SMALL

    def test_refused_when_global_exposure_full(self):
        ctx = _ctx(total_exposure_sol=SIZING_CAPS.max_global_exposure_sol)
        result = compute_position_size(_inp(), ctx, DEFAULT_CONFIG, score=80.0)
        assert result.approved is False


class TestSizingReduction:

    def test_size_reduced_on_queue_pressure(self):
        """Higher queue pressure → smaller position."""
        result_clean   = compute_position_size(_inp(queue_pressure=0.05), _ctx(), DEFAULT_CONFIG, score=80.0)
        result_crowded = compute_position_size(_inp(queue_pressure=0.70), _ctx(), DEFAULT_CONFIG, score=80.0)
        if result_clean.approved and result_crowded.approved:
            assert result_crowded.size_sol < result_clean.size_sol

    def test_size_reduced_on_low_bundle_rate(self):
        result_good = compute_position_size(_inp(bundle_success_rate_recent=0.99), _ctx(), DEFAULT_CONFIG, score=80.0)
        result_poor = compute_position_size(_inp(bundle_success_rate_recent=0.65), _ctx(), DEFAULT_CONFIG, score=80.0)
        if result_good.approved and result_poor.approved:
            assert result_poor.size_sol < result_good.size_sol

    def test_infra_multiplier_present_in_result(self):
        result = compute_position_size(_inp(queue_pressure=0.60), _ctx(), DEFAULT_CONFIG, score=70.0)
        assert result.infra_multiplier < 1.0

    def test_score_multiplier_at_min_score(self):
        """Score just at minimum → partial size."""
        cfg = StrategyConfig(min_score_to_enter=45.0)
        result = compute_position_size(_inp(), _ctx(), cfg, score=45.0)
        assert result.score_multiplier < 1.0

    def test_score_multiplier_above_ramp(self):
        """Score well above minimum → full size."""
        cfg = StrategyConfig(min_score_to_enter=30.0)
        result = compute_position_size(_inp(), _ctx(), cfg, score=80.0)
        assert result.score_multiplier == 1.0


class TestSizingProfiles:

    def test_assertive_larger_than_safe(self):
        result_safe      = compute_position_size(_inp(), _ctx(), DEFAULT_CONFIG, score=80.0, sizing_profile=SizingProfile.SAFE)
        result_assertive = compute_position_size(_inp(), _ctx(), DEFAULT_CONFIG, score=80.0, sizing_profile=SizingProfile.ASSERTIVE)
        assert result_assertive.size_sol > result_safe.size_sol
