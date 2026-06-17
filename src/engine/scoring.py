"""
scoring.py — Phase 4: opportunity quality scoring (0-100).

The score classifies quality — it does NOT decide alone.
Sub-scores are linear, bounded, and individually explainable.

Score layout (max points):
  activity_score   : 25  (velocity + trade count)
  imbalance_score  : 25  (buy/sell imbalance + buy volume)
  ofi_score        : 20  (order flow imbalance)
  freshness_score  : 15  (data staleness + token age)
  infra_score      : 15  (slot lag + queue pressure + bundle rate)
  extension_penalty: -20 (over-extension subtraction)
  ─────────────────────
  Total max          100 (before penalty) → capped [0, 100]
"""

from __future__ import annotations

import logging

from src.engine.strategy_models import (
    SignalQualityBreakdown,
    StrategyConfig,
    StrategyInput,
    ENTRY_THRESHOLDS,
)

logger = logging.getLogger("ApexSol.Scoring")


# ---------------------------------------------------------------------------
# Helper: normalise a value into [0, 1] given a soft reference range.
# Values at `ref_min` → 0.0, at `ref_max` → 1.0, clamped at both ends.
# ---------------------------------------------------------------------------

def _norm(value: float, ref_min: float, ref_max: float) -> float:
    if ref_max <= ref_min:
        return 0.0
    return max(0.0, min(1.0, (value - ref_min) / (ref_max - ref_min)))


# ---------------------------------------------------------------------------
# Sub-score functions — each returns a float in [0, max_points].
# ---------------------------------------------------------------------------

def _activity_score(inp: StrategyInput, cfg: StrategyConfig) -> float:
    """
    25 pts: rewards strong velocity and trade count.
    Reference ceiling = 5× the threshold for full score.
    """
    max_pts = 25.0
    thresholds = ENTRY_THRESHOLDS[cfg.setup_profile]

    vel_pts   = _norm(inp.trade_velocity,    thresholds.min_trade_velocity, thresholds.min_trade_velocity * 5) * (max_pts * 0.60)
    count_pts = _norm(inp.recent_trade_count, cfg.min_trade_count,          cfg.min_trade_count * 4)            * (max_pts * 0.40)
    return vel_pts + count_pts


def _imbalance_score(inp: StrategyInput, cfg: StrategyConfig) -> float:
    """
    25 pts: rewards strong buy-side dominance and absolute buy volume.
    """
    max_pts = 25.0
    thresholds = ENTRY_THRESHOLDS[cfg.setup_profile]

    imb_pts = _norm(inp.buy_sell_imbalance, thresholds.min_buy_sell_imbalance, 0.90) * (max_pts * 0.60)
    vol_pts = _norm(inp.buy_volume_sol,     thresholds.min_buy_volume_sol,      thresholds.min_buy_volume_sol * 6) * (max_pts * 0.40)
    return imb_pts + vol_pts


def _ofi_score(inp: StrategyInput, cfg: StrategyConfig) -> float:
    """
    20 pts: rewards high positive order flow imbalance.
    """
    max_pts = 20.0
    thresholds = ENTRY_THRESHOLDS[cfg.setup_profile]
    return _norm(inp.ofi, thresholds.min_ofi, thresholds.min_ofi * 5) * max_pts


def _freshness_score(inp: StrategyInput, cfg: StrategyConfig) -> float:
    """
    15 pts: rewards low staleness and young token age.
    Penalty is progressive — stale data loses points fast.
    """
    max_pts = 15.0

    # Staleness: 0 ms → full points; at max staleness → 0 pts.
    staleness_pts = (1.0 - _norm(inp.data_staleness_ms, 0.0, cfg.max_data_staleness_ms)) * (max_pts * 0.60)

    # Token age: very young is better; half max age → half points.
    age_pts = (1.0 - _norm(inp.token_age_seconds, 0.0, cfg.max_token_age_seconds)) * (max_pts * 0.40)

    return staleness_pts + age_pts


def _infra_score(inp: StrategyInput, cfg: StrategyConfig) -> float:
    """
    15 pts: rewards healthy infrastructure.
    Any degradation immediately reduces the score.
    """
    max_pts = 15.0

    lag_pts    = (1.0 - _norm(inp.system_slot_lag,           0, cfg.max_slot_lag))            * (max_pts * 0.35)
    queue_pts  = (1.0 - _norm(inp.queue_pressure,            0.0, cfg.max_queue_pressure))     * (max_pts * 0.35)
    bundle_pts = _norm(inp.bundle_success_rate_recent, cfg.min_bundle_success_rate, 1.0)       * (max_pts * 0.30)

    return lag_pts + queue_pts + bundle_pts


def _extension_penalty(inp: StrategyInput, cfg: StrategyConfig) -> float:
    """
    0-20 pts penalty for over-extension.
    Applied for high short_return or high price_acceleration.
    Bollinger band extension adds an additional penalty if data is present.
    """
    max_penalty = 20.0
    thresholds  = ENTRY_THRESHOLDS[cfg.setup_profile]

    # Short return penalty (half weight).
    return_pen = _norm(
        inp.short_return,
        thresholds.max_short_return_fomo * 0.5,   # starts penalising at 50 % of FOMO limit
        thresholds.max_short_return_fomo,
    ) * (max_penalty * 0.50)

    # Acceleration penalty (half weight).
    accel_pen = _norm(
        inp.price_acceleration,
        thresholds.max_price_acceleration_fomo * 0.5,
        thresholds.max_price_acceleration_fomo,
    ) * (max_penalty * 0.50)

    penalty = return_pen + accel_pen

    # Bollinger additional penalty (up to +5 pts extra, capped).
    if (
        inp.bollinger_mid is not None
        and inp.bollinger_upper is not None
        and inp.bollinger_lower is not None
    ):
        band_width = inp.bollinger_upper - inp.bollinger_mid
        if band_width > 0:
            ext = (inp.rolling_price - inp.bollinger_mid) / band_width
            bb_pen = _norm(ext, 0.8, cfg.max_bollinger_extension) * 5.0
            penalty = min(max_penalty, penalty + bb_pen)

    return penalty


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def compute_score(
    inp: StrategyInput,
    cfg: StrategyConfig,
) -> SignalQualityBreakdown:
    """
    Compute the full quality score breakdown.
    The `total` property on the returned object gives the 0-100 score.

    Example explanation for a 74-point trade:
      "Activity 18/25, Imbalance 20/25, OFI 14/20, Freshness 12/15,
       Infra 13/15, Extension penalty 3/20 → total 74"
    """
    activity  = _activity_score(inp, cfg)
    imbalance = _imbalance_score(inp, cfg)
    ofi       = _ofi_score(inp, cfg)
    freshness = _freshness_score(inp, cfg)
    infra     = _infra_score(inp, cfg)
    penalty   = _extension_penalty(inp, cfg)

    breakdown = SignalQualityBreakdown(
        activity_score=round(activity,  2),
        imbalance_score=round(imbalance, 2),
        ofi_score=round(ofi,       2),
        freshness_score=round(freshness, 2),
        infra_score=round(infra,     2),
        extension_penalty=round(penalty,   2),
    )

    logger.debug(
        "Score %s | activity=%.1f imbalance=%.1f ofi=%.1f "
        "freshness=%.1f infra=%.1f penalty=%.1f → total=%.1f",
        inp.mint,
        breakdown.activity_score,
        breakdown.imbalance_score,
        breakdown.ofi_score,
        breakdown.freshness_score,
        breakdown.infra_score,
        breakdown.extension_penalty,
        breakdown.total,
    )

    return breakdown
