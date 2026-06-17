"""
sizing.py — Phase 5: position sizing.

Design:
- Start from a fixed base size (profile-dependent).
- Apply two independent multipliers: infrastructure health + score quality.
- Enforce hard absolute caps regardless of multipliers.
- Refuse the trade if the final size falls below the minimum useful threshold.
- Never increase size on a losing position (caller responsibility — sizing never reads PnL).
"""

from __future__ import annotations

import logging
from typing import Optional

from src.engine.strategy_models import (
    NoTradeReason,
    PositionSizingDecision,
    SignalQualityBreakdown,
    SizingProfile,
    StrategyConfig,
    StrategyContext,
    StrategyInput,
    SIZING_BASE,
    SIZING_CAPS,
)

logger = logging.getLogger("ApexSol.Sizing")


# ---------------------------------------------------------------------------
# Multiplier helpers — each returns a float in (0, 1].
# ---------------------------------------------------------------------------

def _infra_multiplier(inp: StrategyInput, cfg: StrategyConfig) -> tuple[float, list[str]]:
    """
    Reduces size progressively as infrastructure degrades.
    All three axes (queue, lag, bundle rate) independently contribute.
    """
    notes: list[str] = []
    mult = 1.0

    # Queue pressure: above 50 % of limit → start reducing.
    if inp.queue_pressure > cfg.max_queue_pressure * 0.50:
        factor = 1.0 - 0.40 * (
            (inp.queue_pressure - cfg.max_queue_pressure * 0.50)
            / (cfg.max_queue_pressure * 0.50)
        )
        factor = max(0.40, factor)
        mult *= factor
        notes.append(f"queue_pressure={inp.queue_pressure:.2f} → factor={factor:.2f}")

    # Slot lag: above 50 % of limit → start reducing.
    lag_ratio = inp.system_slot_lag / max(cfg.max_slot_lag, 1)
    if lag_ratio > 0.50:
        factor = 1.0 - 0.40 * ((lag_ratio - 0.50) / 0.50)
        factor = max(0.40, factor)
        mult *= factor
        notes.append(f"slot_lag={inp.system_slot_lag} → factor={factor:.2f}")

    # Bundle success rate below 80 % → penalise.
    if inp.bundle_success_rate_recent < 0.80:
        factor = max(0.50, inp.bundle_success_rate_recent / 0.80)
        mult *= factor
        notes.append(f"bundle_success={inp.bundle_success_rate_recent:.2f} → factor={factor:.2f}")

    return round(max(0.30, mult), 3), notes


def _score_multiplier(score: float, cfg: StrategyConfig) -> tuple[float, str]:
    """
    Reduces size if the score is only marginally above the entry minimum.
    Trades scoring between min and min+15 get 60-100 % of base size.
    Trades scoring above min+15 get full size.
    """
    headroom = score - cfg.min_score_to_enter
    if headroom <= 0:
        return 0.60, f"score={score:.1f} just at minimum"
    if headroom < 15:
        mult = 0.60 + 0.40 * (headroom / 15)
        return round(mult, 3), f"score={score:.1f} in ramp zone → mult={mult:.2f}"
    return 1.0, f"score={score:.1f} above ramp zone"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def compute_position_size(
    inp: StrategyInput,
    ctx: StrategyContext,
    cfg: StrategyConfig,
    score: float,
    sizing_profile: Optional[SizingProfile] = None,
) -> PositionSizingDecision:
    """
    Compute the approved position size in SOL.

    Steps:
      1. Pick base size from profile.
      2. Apply infrastructure multiplier.
      3. Apply score multiplier.
      4. Clamp to per-token cap.
      5. Clamp to remaining global exposure headroom.
      6. Enforce minimum useful size — refuse if below threshold.
      7. Enforce max concurrent positions cap.
    """
    profile = sizing_profile or cfg.sizing_profile
    base    = SIZING_BASE[profile].base_sol
    notes: list[str] = [f"base={base:.3f} SOL (profile={profile.value})"]

    # 1. Infrastructure multiplier.
    infra_mult, infra_notes = _infra_multiplier(inp, cfg)
    notes.extend(infra_notes)

    # 2. Score multiplier.
    score_mult, score_note = _score_multiplier(score, cfg)
    notes.append(score_note)

    # 3. Raw computed size.
    raw_size = base * infra_mult * score_mult

    # 4. Per-token cap.
    size = min(raw_size, SIZING_CAPS.max_position_sol)
    if size < raw_size:
        notes.append(f"capped at max_position_sol={SIZING_CAPS.max_position_sol:.2f}")

    # 5. Global exposure headroom.
    remaining_exposure = SIZING_CAPS.max_global_exposure_sol - ctx.total_exposure_sol
    if remaining_exposure <= 0:
        logger.warning("Global exposure cap reached — refusing trade for %s", inp.mint)
        return PositionSizingDecision(
            approved=False,
            size_sol=0.0,
            raw_size_sol=raw_size,
            infra_multiplier=infra_mult,
            score_multiplier=score_mult,
            rejection_reason=NoTradeReason.SIZE_TOO_SMALL,
            notes=notes + ["Global exposure cap reached"],
        )
    size = min(size, remaining_exposure)
    if size < raw_size:
        notes.append(f"trimmed to remaining_exposure={remaining_exposure:.3f}")

    # 6. Minimum useful size.
    if size < SIZING_CAPS.min_useful_size_sol:
        logger.warning(
            "Computed size=%.4f SOL below minimum=%.4f — refusing %s",
            size, SIZING_CAPS.min_useful_size_sol, inp.mint,
        )
        return PositionSizingDecision(
            approved=False,
            size_sol=0.0,
            raw_size_sol=raw_size,
            infra_multiplier=infra_mult,
            score_multiplier=score_mult,
            rejection_reason=NoTradeReason.SIZE_TOO_SMALL,
            notes=notes + [f"size={size:.4f} < min={SIZING_CAPS.min_useful_size_sol:.4f}"],
        )

    # 7. Concurrent positions cap.
    if ctx.current_open_positions >= SIZING_CAPS.max_concurrent_positions:
        logger.warning(
            "Max concurrent positions=%d reached — refusing %s",
            SIZING_CAPS.max_concurrent_positions, inp.mint,
        )
        return PositionSizingDecision(
            approved=False,
            size_sol=0.0,
            raw_size_sol=raw_size,
            infra_multiplier=infra_mult,
            score_multiplier=score_mult,
            rejection_reason=NoTradeReason.SIZE_TOO_SMALL,
            notes=notes + ["Max concurrent positions reached"],
        )

    logger.info(
        "Sizing APPROVED %s | %.4f SOL (infra×%.2f score×%.2f)",
        inp.mint, size, infra_mult, score_mult,
    )
    return PositionSizingDecision(
        approved=True,
        size_sol=round(size, 6),
        raw_size_sol=round(raw_size, 6),
        infra_multiplier=infra_mult,
        score_multiplier=score_mult,
        notes=notes,
    )
