"""
entry_rules.py — Phase 1: eligibility gates + Phase 2: entry conditions + Phase 3: anti-FOMO filter.

Design principles:
- Eligibility is binary and strict. One failure → immediate NO_TRADE.
- Entry conditions score is cumulative but gated by minimum.
- Anti-FOMO is explicit and separate — evaluated AFTER entry conditions pass.
- No business logic in helper lambdas.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.engine.strategy_models import (
    EntryDecision,
    EntryThresholds,
    NoTradeReason,
    SetupProfile,
    StrategyConfig,
    StrategyInput,
    StrategyContext,
    ENTRY_THRESHOLDS,
)
from src.ingestion.models import AuditVerdict

logger = logging.getLogger("ApexSol.EntryRules")


# ---------------------------------------------------------------------------
# Phase 1 — Eligibility
# ---------------------------------------------------------------------------

def is_token_eligible(
    inp: StrategyInput,
    ctx: StrategyContext,
    cfg: StrategyConfig,
) -> tuple[bool, Optional[NoTradeReason], str]:
    """
    Hard gates: if any condition fails the token is completely ineligible.
    Returns (eligible, blocking_reason, human_readable_detail).

    Checks are ordered from cheapest to most specific.
    """

    # 1. Security audit must pass.
    if inp.audit_status == AuditVerdict.PENDING.value:
        return False, NoTradeReason.AUDIT_PENDING, "Audit is still pending"
    if inp.audit_status != AuditVerdict.ALLOW.value:
        return False, NoTradeReason.AUDIT_DENIED, f"Audit status={inp.audit_status}"

    # 2. Data must be fresh.
    if inp.data_staleness_ms > cfg.max_data_staleness_ms:
        return (
            False,
            NoTradeReason.DATA_STALE,
            f"data_staleness_ms={inp.data_staleness_ms:.0f} > max={cfg.max_data_staleness_ms:.0f}",
        )

    # 3. Slot lag must be acceptable.
    if inp.system_slot_lag > cfg.max_slot_lag:
        return (
            False,
            NoTradeReason.SLOT_LAG_TOO_HIGH,
            f"system_slot_lag={inp.system_slot_lag} > max={cfg.max_slot_lag}",
        )

    # 4. Queue must not be saturated.
    if inp.queue_pressure > cfg.max_queue_pressure:
        return (
            False,
            NoTradeReason.QUEUE_PRESSURE_HIGH,
            f"queue_pressure={inp.queue_pressure:.2f} > max={cfg.max_queue_pressure:.2f}",
        )

    # 5. Jito bundle success rate must be healthy.
    if inp.bundle_success_rate_recent < cfg.min_bundle_success_rate:
        return (
            False,
            NoTradeReason.BUNDLE_SUCCESS_LOW,
            f"bundle_success_rate={inp.bundle_success_rate_recent:.2f} < min={cfg.min_bundle_success_rate:.2f}",
        )

    # 6. Token must be young enough to be exploitable.
    if inp.token_age_seconds > cfg.max_token_age_seconds:
        return (
            False,
            NoTradeReason.TOKEN_TOO_OLD,
            f"token_age={inp.token_age_seconds:.0f}s > max={cfg.max_token_age_seconds:.0f}s",
        )

    # 7. Active cooldown on this token.
    if inp.cooldown_remaining_seconds > 0:
        return (
            False,
            NoTradeReason.COOLDOWN_ACTIVE,
            f"cooldown_remaining={inp.cooldown_remaining_seconds:.0f}s",
        )

    # 8. Minimum activity — avoid ghost tokens.
    if inp.recent_trade_count < cfg.min_trade_count:
        return (
            False,
            NoTradeReason.TRADE_COUNT_LOW,
            f"recent_trade_count={inp.recent_trade_count} < min={cfg.min_trade_count}",
        )

    return True, None, "eligible"


# ---------------------------------------------------------------------------
# Phase 3 — Anti-FOMO filter (called after entry conditions pass)
# ---------------------------------------------------------------------------

def is_overextended(
    inp: StrategyInput,
    thresholds: EntryThresholds,
    cfg: StrategyConfig,
) -> tuple[bool, str]:
    """
    Returns (overextended, reason).
    Buying an already-stretched move is the most common avoidable mistake.

    Checks:
    - short_return: how much the price has already moved since token birth.
    - price_acceleration: normalised rate of change — avoids parabolic entries.
    - Bollinger extension: price relative to band (secondary, skipped if data absent).
    """

    # Short return already high → we are late.
    if inp.short_return > thresholds.max_short_return_fomo:
        return (
            True,
            f"short_return={inp.short_return:.2%} > fomo_limit={thresholds.max_short_return_fomo:.2%}",
        )

    # Price accelerating too fast → parabolic phase.
    if inp.price_acceleration > thresholds.max_price_acceleration_fomo:
        return (
            True,
            f"price_acceleration={inp.price_acceleration:.3f} > fomo_limit={thresholds.max_price_acceleration_fomo:.3f}",
        )

    # Bollinger extension check — only if all three bands are available.
    if (
        inp.bollinger_mid is not None
        and inp.bollinger_upper is not None
        and inp.bollinger_lower is not None
    ):
        band_width = inp.bollinger_upper - inp.bollinger_mid
        if band_width > 0:
            extension = (inp.rolling_price - inp.bollinger_mid) / band_width
            if extension > cfg.max_bollinger_extension:
                return (
                    True,
                    f"bollinger_extension={extension:.2f} > max={cfg.max_bollinger_extension:.2f}",
                )

    return False, ""


# ---------------------------------------------------------------------------
# Phase 2 — Entry conditions
# ---------------------------------------------------------------------------

def check_entry_conditions(
    inp: StrategyInput,
    thresholds: EntryThresholds,
) -> tuple[bool, list[str]]:
    """
    Evaluates the four primary entry conditions.
    Returns (all_met, list_of_reasons).

    Each condition is individually logged so failures are traceable.
    """
    reasons: list[str] = []
    failures: list[str] = []

    # 1. Trade velocity.
    if inp.trade_velocity >= thresholds.min_trade_velocity:
        reasons.append(f"velocity={inp.trade_velocity:.2f} ✓ (>={thresholds.min_trade_velocity:.2f})")
    else:
        failures.append(f"velocity={inp.trade_velocity:.2f} < {thresholds.min_trade_velocity:.2f}")

    # 2. Buy volume in SOL.
    if inp.buy_volume_sol >= thresholds.min_buy_volume_sol:
        reasons.append(f"buy_volume_sol={inp.buy_volume_sol:.3f} ✓ (>={thresholds.min_buy_volume_sol:.3f})")
    else:
        failures.append(f"buy_volume_sol={inp.buy_volume_sol:.3f} < {thresholds.min_buy_volume_sol:.3f}")

    # 3. Buy/sell imbalance.
    if inp.buy_sell_imbalance >= thresholds.min_buy_sell_imbalance:
        reasons.append(f"imbalance={inp.buy_sell_imbalance:.2f} ✓ (>={thresholds.min_buy_sell_imbalance:.2f})")
    else:
        failures.append(f"imbalance={inp.buy_sell_imbalance:.2f} < {thresholds.min_buy_sell_imbalance:.2f}")

    # 4. Order Flow Imbalance.
    if inp.ofi >= thresholds.min_ofi:
        reasons.append(f"ofi={inp.ofi:.0f} ✓ (>={thresholds.min_ofi:.0f})")
    else:
        failures.append(f"ofi={inp.ofi:.0f} < {thresholds.min_ofi:.0f}")

    all_met = len(failures) == 0
    combined = reasons + ([f"FAIL: {f}" for f in failures] if failures else [])
    return all_met, combined


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def evaluate_entry(
    inp: StrategyInput,
    ctx: StrategyContext,
    cfg: StrategyConfig,
) -> EntryDecision:
    """
    Full entry evaluation pipeline:
      1. Already in position → block.
      2. Eligibility gates → block on first failure.
      3. Entry conditions → must all pass.
      4. Anti-FOMO filter → block if overextended.
    """

    # Guard: no double entry.
    if inp.in_position:
        return EntryDecision(
            eligible=False,
            conditions_met=False,
            blocking_reason=NoTradeReason.ALREADY_IN_POSITION,
            reasons=["Already in position"],
        )

    # Phase 1 — eligibility.
    eligible, block_reason, detail = is_token_eligible(inp, ctx, cfg)
    if not eligible:
        logger.debug("Eligibility FAILED %s | %s", inp.mint, detail)
        return EntryDecision(
            eligible=False,
            conditions_met=False,
            blocking_reason=block_reason,
            reasons=[detail],
        )

    # Resolve thresholds for the chosen setup.
    thresholds = ENTRY_THRESHOLDS[cfg.setup_profile]

    # Phase 2 — entry conditions.
    conditions_met, condition_reasons = check_entry_conditions(inp, thresholds)
    if not conditions_met:
        logger.debug("Entry conditions NOT met %s | %s", inp.mint, condition_reasons)
        return EntryDecision(
            eligible=True,
            conditions_met=False,
            blocking_reason=NoTradeReason.ACTIVITY_INSUFFICIENT,
            reasons=condition_reasons,
            setup_used=cfg.setup_profile,
        )

    # Phase 3 — anti-FOMO.
    overextended, fomo_reason = is_overextended(inp, thresholds, cfg)
    if overextended:
        logger.info("Anti-FOMO BLOCKED %s | %s", inp.mint, fomo_reason)
        return EntryDecision(
            eligible=True,
            conditions_met=True,
            blocking_reason=NoTradeReason.FOMO_OVEREXTENSION,
            reasons=[fomo_reason] + condition_reasons,
            setup_used=cfg.setup_profile,
        )

    logger.info("Entry APPROVED %s | setup=%s", inp.mint, cfg.setup_profile.value)
    return EntryDecision(
        eligible=True,
        conditions_met=True,
        blocking_reason=None,
        reasons=condition_reasons,
        setup_used=cfg.setup_profile,
    )
