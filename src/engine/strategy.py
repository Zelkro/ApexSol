"""
strategy.py — Orchestrator: assembles entry, scoring, sizing, and exit layers.

The strategy itself contains NO business logic.
It routes inputs through the specialised modules and aggregates the result
into a single StrategyDecision that is fully loggable and auditable.

Public API:
    evaluate_opportunity(input, context) -> StrategyDecision
    evaluate_exit(input, context)        -> StrategyDecision
    compute_position_size(input, context)-> PositionSizingDecision
"""

from __future__ import annotations

import logging
import time

from src.engine.entry_rules import evaluate_entry
from src.engine.exit_rules import evaluate_exit as _evaluate_exit
from src.engine.scoring import compute_score
from src.engine.sizing import compute_position_size as _compute_size
from src.engine.strategy_models import (
    DEFAULT_CONFIG,
    ExitReason,
    NoTradeReason,
    PositionSizingDecision,
    StrategyConfig,
    StrategyContext,
    StrategyDecision,
    StrategyInput,
    Verdict,
)

logger = logging.getLogger("ApexSol.Strategy")


class Strategy:
    """
    Stateless strategy orchestrator.

    The object is stateless by design: all state lives in StrategyInput
    and StrategyContext, which are injected by the caller (the app layer).
    This makes the strategy fully testable without mocking internal state.
    """

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.cfg = config or DEFAULT_CONFIG
        logger.info(
            "Strategy initialised | setup=%s sizing=%s min_score=%.0f",
            self.cfg.setup_profile.value,
            self.cfg.sizing_profile.value,
            self.cfg.min_score_to_enter,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def evaluate_opportunity(
        self,
        inp: StrategyInput,
        ctx: StrategyContext,
    ) -> StrategyDecision:
        """
        Evaluate whether to enter a new position.

        Flow:
          1. Run entry rules (eligibility + conditions + anti-FOMO).
          2. If blocked → return NO_TRADE with structured reason.
          3. Compute score.
          4. Gate on minimum score.
          5. Compute sizing.
          6. If sizing refused → return NO_TRADE.
          7. Return ENTER with full decision payload.
        """
        # Step 1 — entry rules.
        entry = evaluate_entry(inp, ctx, self.cfg)

        if not entry.conditions_met or entry.blocking_reason is not None:
            return StrategyDecision.no_trade(
                mint=inp.mint,
                slot=inp.slot,
                reason=entry.blocking_reason or NoTradeReason.ACTIVITY_INSUFFICIENT,
                details=" | ".join(entry.reasons),
                input_snapshot=inp,
            )

        # Step 2 — scoring.
        breakdown = compute_score(inp, self.cfg)
        score     = breakdown.total

        # Step 3 — score gate.
        if score < self.cfg.min_score_to_enter:
            return StrategyDecision(
                verdict=Verdict.NO_TRADE,
                mint=inp.mint,
                slot=inp.slot,
                timestamp=time.time(),
                score=score,
                score_breakdown=breakdown,
                no_trade_reason=NoTradeReason.ACTIVITY_INSUFFICIENT,
                reasons=[
                    f"Score {score:.1f} below minimum {self.cfg.min_score_to_enter:.0f}",
                    *entry.reasons,
                ],
                metrics=inp.to_log_dict(),
            )

        # Step 4 — sizing.
        sizing = _compute_size(inp, ctx, self.cfg, score)

        if not sizing.approved:
            return StrategyDecision(
                verdict=Verdict.NO_TRADE,
                mint=inp.mint,
                slot=inp.slot,
                timestamp=time.time(),
                score=score,
                score_breakdown=breakdown,
                no_trade_reason=sizing.rejection_reason,
                reasons=[f"Sizing refused: {sizing.notes}"],
                sizing=sizing,
                setup_used=entry.setup_used,
                metrics=inp.to_log_dict(),
            )

        # Step 5 — ENTER.
        logger.info(
            "ENTER | mint=%s score=%.1f size=%.4f SOL setup=%s",
            inp.mint, score, sizing.size_sol, self.cfg.setup_profile.value,
        )
        return StrategyDecision(
            verdict=Verdict.ENTER,
            mint=inp.mint,
            slot=inp.slot,
            timestamp=time.time(),
            score=score,
            score_breakdown=breakdown,
            reasons=entry.reasons,
            setup_used=entry.setup_used,
            sizing=sizing,
            metrics=inp.to_log_dict(),
        )

    def evaluate_exit(
        self,
        inp: StrategyInput,
        ctx: StrategyContext,
    ) -> StrategyDecision:
        """
        Evaluate whether to exit or reduce an existing position.
        Translates ExitDecision → StrategyDecision for uniform output format.
        """
        exit_decision = _evaluate_exit(inp, ctx, self.cfg)

        verdict = exit_decision.verdict
        reason  = exit_decision.reason

        return StrategyDecision(
            verdict=verdict,
            mint=inp.mint,
            slot=inp.slot,
            timestamp=time.time(),
            score=0.0,  # score is not computed for exit path
            exit_reason=reason,
            reasons=[exit_decision.details],
            metrics={
                **inp.to_log_dict(),
                "price_return": exit_decision.price_return,
                "entry_price": ctx.entry_price,
            },
        )

    def compute_position_size(
        self,
        inp: StrategyInput,
        ctx: StrategyContext,
        score: float,
    ) -> PositionSizingDecision:
        """
        Standalone sizing — useful when re-evaluating size mid-position
        (e.g., for a partial reduce order).
        """
        return _compute_size(inp, ctx, self.cfg, score)
