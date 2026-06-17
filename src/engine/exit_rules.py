"""
exit_rules.py — Phase 6: exit conditions.

Exit rules are evaluated in strict priority order:
  1. Hard stop loss         — capital protection, no override.
  2. Stale data             — we can't see the market, get out.
  3. Slot lag               — execution would be blind, get out.
  4. Take profit (partial)  — lock gains, reduce exposure.
  5. Take profit (final)    — full exit at upper target.
  6. Time stop              — refuse to hold a stagnant position.
  7. Entry confirmation     — exit if no follow-through after entry.
  8. Momentum failure       — exit on sustained degradation.
  9. Infrastructure         — exit on infra degradation mid-trade.
 10. Hold                   — all checks passed, stay in.

Only one exit reason is emitted per evaluation cycle.
"""

from __future__ import annotations

import logging
import time

from src.engine.strategy_models import (
    ExitDecision,
    ExitReason,
    StrategyConfig,
    StrategyContext,
    StrategyInput,
    Verdict,
)

logger = logging.getLogger("ApexSol.ExitRules")


# ---------------------------------------------------------------------------
# Individual exit checks — each returns (should_exit, reason, details, return).
# ---------------------------------------------------------------------------

def _compute_return(current_price: float, entry_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return (current_price - entry_price) / entry_price


def _check_stop_loss(inp: StrategyInput, ctx: StrategyContext, cfg: StrategyConfig) -> ExitDecision | None:
    ret = _compute_return(inp.rolling_price, ctx.entry_price)
    if ret <= cfg.stop_loss_pct:
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.STOP_LOSS,
            details=f"return={ret:.2%} ≤ stop_loss={cfg.stop_loss_pct:.2%}",
            price_return=ret,
        )
    return None


def _check_stale_data(inp: StrategyInput, cfg: StrategyConfig) -> ExitDecision | None:
    if inp.data_staleness_ms > cfg.max_data_staleness_ms:
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.DATA_STALE,
            details=f"data_staleness_ms={inp.data_staleness_ms:.0f} > max={cfg.max_data_staleness_ms:.0f}",
        )
    return None


def _check_slot_lag(inp: StrategyInput, cfg: StrategyConfig) -> ExitDecision | None:
    if inp.system_slot_lag > cfg.max_slot_lag:
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.SLOT_LAG,
            details=f"system_slot_lag={inp.system_slot_lag} > max={cfg.max_slot_lag}",
        )
    return None


def _check_take_profit_partial(
    inp: StrategyInput, ctx: StrategyContext, cfg: StrategyConfig
) -> ExitDecision | None:
    if ctx.partial_exit_done:
        return None
    ret = _compute_return(inp.rolling_price, ctx.entry_price)
    if ret >= cfg.take_profit_partial_pct:
        return ExitDecision(
            verdict=Verdict.REDUCE,
            reason=ExitReason.TAKE_PROFIT_PARTIAL,
            details=f"return={ret:.2%} ≥ tp_partial={cfg.take_profit_partial_pct:.2%}",
            price_return=ret,
        )
    return None


def _check_take_profit_final(
    inp: StrategyInput, ctx: StrategyContext, cfg: StrategyConfig
) -> ExitDecision | None:
    ret = _compute_return(inp.rolling_price, ctx.entry_price)
    if ret >= cfg.take_profit_final_pct:
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.TAKE_PROFIT_FINAL,
            details=f"return={ret:.2%} ≥ tp_final={cfg.take_profit_final_pct:.2%}",
            price_return=ret,
        )
    return None


def _check_time_stop(
    inp: StrategyInput, ctx: StrategyContext, cfg: StrategyConfig
) -> ExitDecision | None:
    now = inp.timestamp
    age = now - ctx.entry_time
    if age > cfg.time_stop_seconds:
        ret = _compute_return(inp.rolling_price, ctx.entry_price)
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.TIME_STOP,
            details=f"position_age={age:.0f}s > time_stop={cfg.time_stop_seconds:.0f}s",
            price_return=ret,
        )
    return None


def _check_entry_confirmation(
    inp: StrategyInput, ctx: StrategyContext, cfg: StrategyConfig
) -> ExitDecision | None:
    """
    If after `confirmation_window_seconds` the price hasn't moved up AND
    the primary momentum signals have weakened, the entry thesis is invalid.

    Conditions (ALL must be true to trigger):
    - We are still within the confirmation window.
    - Return is negative (price didn't follow through).
    - imbalance dropped below the entry value.
    - velocity dropped by more than momentum_failure_velocity_drop.
    """
    now = inp.timestamp
    age = now - ctx.entry_time

    # Only fire during the confirmation window.
    if age > cfg.confirmation_window_seconds:
        return None

    # Minimum age to avoid spurious signals at t+0.
    if age < 3.0:
        return None

    ret = _compute_return(inp.rolling_price, ctx.entry_price)

    price_not_up     = ret < 0
    imbalance_fell   = inp.buy_sell_imbalance < ctx.entry_imbalance - cfg.momentum_failure_imbalance_drop
    velocity_dropped = (
        ctx.entry_velocity > 0
        and inp.trade_velocity < ctx.entry_velocity * (1.0 - cfg.momentum_failure_velocity_drop)
    )

    if price_not_up and imbalance_fell and velocity_dropped:
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.MOMENTUM_FAILURE,
            details=(
                f"No confirmation after {age:.0f}s: "
                f"return={ret:.2%}, "
                f"imbalance={inp.buy_sell_imbalance:.2f}↓{ctx.entry_imbalance:.2f}, "
                f"velocity={inp.trade_velocity:.2f}↓{ctx.entry_velocity:.2f}"
            ),
            price_return=ret,
        )
    return None


def _check_momentum_failure(
    inp: StrategyInput, ctx: StrategyContext, cfg: StrategyConfig
) -> ExitDecision | None:
    """
    Post-confirmation momentum degradation check.
    Fires outside the confirmation window when all three momentum signals
    deteriorate simultaneously.
    """
    now = inp.timestamp
    age = now - ctx.entry_time

    if age <= cfg.confirmation_window_seconds:
        return None

    velocity_failed = (
        ctx.entry_velocity > 0
        and inp.trade_velocity < ctx.entry_velocity * (1.0 - cfg.momentum_failure_velocity_drop)
    )
    imbalance_failed = inp.buy_sell_imbalance < ctx.entry_imbalance - cfg.momentum_failure_imbalance_drop
    ofi_failed       = (
        ctx.entry_ofi > 0
        and inp.ofi < ctx.entry_ofi * (1.0 - cfg.momentum_failure_ofi_drop)
    )

    if velocity_failed and imbalance_failed and ofi_failed:
        ret = _compute_return(inp.rolling_price, ctx.entry_price)
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.MOMENTUM_FAILURE,
            details=(
                f"Triple momentum failure: "
                f"velocity={inp.trade_velocity:.2f}↓, "
                f"imbalance={inp.buy_sell_imbalance:.2f}↓, "
                f"ofi={inp.ofi:.0f}↓"
            ),
            price_return=ret,
        )

    # Partial degradation → reduce position, don't exit fully.
    if velocity_failed and (imbalance_failed or ofi_failed):
        ret = _compute_return(inp.rolling_price, ctx.entry_price)
        return ExitDecision(
            verdict=Verdict.REDUCE,
            reason=ExitReason.MOMENTUM_FAILURE,
            details=(
                f"Partial momentum degradation: "
                f"velocity={'↓' if velocity_failed else 'ok'}, "
                f"imbalance={'↓' if imbalance_failed else 'ok'}, "
                f"ofi={'↓' if ofi_failed else 'ok'}"
            ),
            price_return=ret,
        )

    return None


def _check_infra_degradation(inp: StrategyInput, cfg: StrategyConfig) -> ExitDecision | None:
    """
    Exit if infrastructure degrades significantly mid-trade.
    We use a more lenient threshold than eligibility (80 % of the gate).
    """
    # Queue at 90 % of max → exit now before we can't.
    if inp.queue_pressure > cfg.max_queue_pressure * 0.90:
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.INFRA_DEGRADATION,
            details=f"queue_pressure={inp.queue_pressure:.2f} critically high",
        )

    # Bundle rate collapsed.
    if inp.bundle_success_rate_recent < cfg.min_bundle_success_rate * 0.70:
        return ExitDecision(
            verdict=Verdict.EXIT,
            reason=ExitReason.INFRA_DEGRADATION,
            details=f"bundle_success_rate={inp.bundle_success_rate_recent:.2f} collapsed",
        )

    return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def evaluate_exit(
    inp: StrategyInput,
    ctx: StrategyContext,
    cfg: StrategyConfig,
) -> ExitDecision:
    """
    Evaluate all exit conditions in priority order.
    Returns the FIRST triggered condition, or HOLD if none fires.
    """
    if not inp.in_position:
        # Not in position — caller should not call this, but return HOLD gracefully.
        return ExitDecision(verdict=Verdict.HOLD, reason=ExitReason.HOLD, details="Not in position")

    checks = [
        _check_stop_loss(inp, ctx, cfg),
        _check_stale_data(inp, cfg),
        _check_slot_lag(inp, cfg),
        _check_take_profit_final(inp, ctx, cfg),
        _check_take_profit_partial(inp, ctx, cfg),
        _check_time_stop(inp, ctx, cfg),
        _check_entry_confirmation(inp, ctx, cfg),
        _check_momentum_failure(inp, ctx, cfg),
        _check_infra_degradation(inp, cfg),
    ]

    for decision in checks:
        if decision is not None:
            logger.info(
                "Exit %s | mint=%s reason=%s details=%s",
                decision.verdict.value, inp.mint, decision.reason.value, decision.details,
            )
            return decision

    return ExitDecision(verdict=Verdict.HOLD, reason=ExitReason.HOLD, details="Position healthy")
