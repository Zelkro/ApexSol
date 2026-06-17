"""
strategy_models.py — Typed models for the ApexSol strategy layer.

All models are plain dataclasses: strongly typed, serialisable (asdict),
and directly loggable as structured JSON.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    NO_TRADE = "NO_TRADE"
    WATCH    = "WATCH"
    ENTER    = "ENTER"
    HOLD     = "HOLD"
    REDUCE   = "REDUCE"
    EXIT     = "EXIT"


class SetupProfile(str, Enum):
    """Entry aggressiveness profile."""
    CONSERVATIVE = "conservative"
    BALANCED     = "balanced"
    AGGRESSIVE   = "aggressive"


class SizingProfile(str, Enum):
    """Capital allocation aggressiveness."""
    SAFE      = "safe"
    NORMAL    = "normal"
    ASSERTIVE = "assertive"


class NoTradeReason(str, Enum):
    AUDIT_DENIED          = "AUDIT_DENIED"
    AUDIT_PENDING         = "AUDIT_PENDING"
    DATA_STALE            = "DATA_STALE"
    SLOT_LAG_TOO_HIGH     = "SLOT_LAG_TOO_HIGH"
    QUEUE_PRESSURE_HIGH   = "QUEUE_PRESSURE_HIGH"
    BUNDLE_SUCCESS_LOW    = "BUNDLE_SUCCESS_LOW"
    TOKEN_TOO_OLD         = "TOKEN_TOO_OLD"
    COOLDOWN_ACTIVE       = "COOLDOWN_ACTIVE"
    TRADE_COUNT_LOW       = "TRADE_COUNT_LOW"
    ALREADY_IN_POSITION   = "ALREADY_IN_POSITION"
    FOMO_OVEREXTENSION    = "FOMO_OVEREXTENSION"
    ACTIVITY_INSUFFICIENT = "ACTIVITY_INSUFFICIENT"
    SIZE_TOO_SMALL        = "SIZE_TOO_SMALL"


class ExitReason(str, Enum):
    STOP_LOSS           = "STOP_LOSS"
    TAKE_PROFIT_PARTIAL = "TAKE_PROFIT_PARTIAL"
    TAKE_PROFIT_FINAL   = "TAKE_PROFIT_FINAL"
    TIME_STOP           = "TIME_STOP"
    MOMENTUM_FAILURE    = "MOMENTUM_FAILURE"
    INFRA_DEGRADATION   = "INFRA_DEGRADATION"
    DATA_STALE          = "DATA_STALE"
    SLOT_LAG            = "SLOT_LAG"
    HOLD                = "HOLD"


# ---------------------------------------------------------------------------
# Strategy configuration
# ---------------------------------------------------------------------------

@dataclass
class EntryThresholds:
    """Numeric thresholds for a single entry setup."""
    min_trade_velocity: float    # trades/second
    min_buy_volume_sol: float    # SOL
    min_buy_sell_imbalance: float  # ratio [0, 1]
    min_ofi: float               # raw OFI units
    max_short_return_fomo: float # max % return before FOMO block
    max_price_acceleration_fomo: float  # normalised acceleration


# Pre-built setups — conservative is the default.
ENTRY_THRESHOLDS: dict[SetupProfile, EntryThresholds] = {
    SetupProfile.CONSERVATIVE: EntryThresholds(
        min_trade_velocity=2.0,
        min_buy_volume_sol=0.5,
        min_buy_sell_imbalance=0.60,
        min_ofi=1_500.0,
        max_short_return_fomo=0.25,    # block if +25 % already
        max_price_acceleration_fomo=0.15,
    ),
    SetupProfile.BALANCED: EntryThresholds(
        min_trade_velocity=1.5,
        min_buy_volume_sol=0.3,
        min_buy_sell_imbalance=0.55,
        min_ofi=800.0,
        max_short_return_fomo=0.35,
        max_price_acceleration_fomo=0.20,
    ),
    SetupProfile.AGGRESSIVE: EntryThresholds(
        min_trade_velocity=1.0,
        min_buy_volume_sol=0.15,
        min_buy_sell_imbalance=0.50,
        min_ofi=400.0,
        max_short_return_fomo=0.50,
        max_price_acceleration_fomo=0.30,
    ),
}


@dataclass
class SizingLimits:
    """Absolute caps that apply across all sizing profiles."""
    max_position_sol: float         # max SOL per single token
    max_global_exposure_sol: float  # max SOL across all open positions
    max_concurrent_positions: int
    min_useful_size_sol: float      # refuse trade if computed size < this


SIZING_CAPS = SizingLimits(
    max_position_sol=2.0,
    max_global_exposure_sol=6.0,
    max_concurrent_positions=3,
    min_useful_size_sol=0.05,
)


@dataclass
class SizingBase:
    """Base trade size per sizing profile."""
    base_sol: float


SIZING_BASE: dict[SizingProfile, SizingBase] = {
    SizingProfile.SAFE:      SizingBase(base_sol=0.25),
    SizingProfile.NORMAL:    SizingBase(base_sol=0.50),
    SizingProfile.ASSERTIVE: SizingBase(base_sol=1.00),
}


@dataclass
class StrategyConfig:
    """
    Single source of truth for all strategy parameters.
    Change values here — never hardcode them elsewhere.
    """
    # Profiles
    setup_profile: SetupProfile   = SetupProfile.CONSERVATIVE
    sizing_profile: SizingProfile = SizingProfile.NORMAL

    # Eligibility gates
    min_trade_count: int          = 5
    max_data_staleness_ms: float  = 2_000.0    # ms
    max_slot_lag: int             = 10
    max_queue_pressure: float     = 0.80       # 0-1 fraction
    min_bundle_success_rate: float= 0.60       # 0-1
    max_token_age_seconds: float  = 120.0

    # Bollinger over-extension gate (secondary filter only)
    max_bollinger_extension: float= 1.5        # (price - mid) / (upper - mid)

    # Exit levels
    stop_loss_pct: float          = -0.05      # -5 %
    take_profit_partial_pct: float=  0.10      # +10 %
    take_profit_final_pct: float  =  0.20      # +20 %
    time_stop_seconds: float      = 180.0
    confirmation_window_seconds: float = 15.0  # time to validate entry momentum

    # Momentum failure thresholds (post-entry degradation)
    momentum_failure_velocity_drop: float = 0.40   # 40 % drop vs entry
    momentum_failure_imbalance_drop: float = 0.20  # absolute drop in imbalance
    momentum_failure_ofi_drop: float       = 0.50  # 50 % drop vs entry

    # Cooldowns
    cooldown_after_loss_seconds: float    = 60.0
    cooldown_after_failure_seconds: float = 30.0

    # Scoring gate
    min_score_to_enter: float     = 45.0       # out of 100


# Default singleton — override in tests or by env injection.
DEFAULT_CONFIG = StrategyConfig()


# ---------------------------------------------------------------------------
# Input / Context models
# ---------------------------------------------------------------------------

@dataclass
class StrategyInput:
    """
    Snapshot of all features consumed by the strategy.
    All fields come from the ingestion + feature pipeline.
    Missing optional fields are None — never invented.
    """
    mint: str
    slot: int
    timestamp: float                      # unix epoch, seconds

    # Identity / lifecycle
    first_seen_at: float
    last_seen_at: float
    token_age_seconds: float
    audit_status: str                     # AuditVerdict.value string

    # Position state
    in_position: bool
    cooldown_remaining_seconds: float

    # Activity
    recent_trade_count: int
    trade_velocity: float                 # trades/second
    buy_volume_sol: float
    sell_volume_sol: float
    buy_sell_imbalance: float             # [0, 1]
    ofi: float

    # Price
    rolling_price: float
    short_return: float                   # return since entry (or 0)
    price_acceleration: float            # normalised Δvelocity

    # Secondary technical (optional — used only as filters, never as primary signal)
    rsi: Optional[float] = None
    bollinger_mid: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None

    # Position tracking (populated when in_position=True)
    unrealized_pnl: float = 0.0

    # Infrastructure health
    data_staleness_ms: float  = 0.0
    system_slot_lag: int      = 0
    queue_pressure: float     = 0.0      # [0, 1]
    bundle_success_rate_recent: float = 1.0  # [0, 1]

    def to_log_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategyContext:
    """
    Runtime context: what the system knows about its own state.
    Injected externally — strategy does not mutate this.
    """
    current_open_positions: int = 0
    total_exposure_sol: float   = 0.0

    # Entry snapshot — populated when in_position=True
    entry_price: float          = 0.0
    entry_time: float           = 0.0
    entry_velocity: float       = 0.0
    entry_imbalance: float      = 0.0
    entry_ofi: float            = 0.0
    partial_exit_done: bool     = False


# ---------------------------------------------------------------------------
# Decision models
# ---------------------------------------------------------------------------

@dataclass
class SignalQualityBreakdown:
    """Sub-scores that compose the final opportunity score."""
    activity_score: float    # 0-25 : velocity + trade count
    imbalance_score: float   # 0-25 : buy/sell imbalance + buy volume
    ofi_score: float         # 0-20 : order flow imbalance
    freshness_score: float   # 0-15 : data staleness + token age
    infra_score: float       # 0-15 : slot lag + queue pressure + bundle rate
    extension_penalty: float # 0-20 : subtracted for over-extension

    @property
    def total(self) -> float:
        raw = (
            self.activity_score
            + self.imbalance_score
            + self.ofi_score
            + self.freshness_score
            + self.infra_score
            - self.extension_penalty
        )
        return max(0.0, min(100.0, raw))


@dataclass
class EntryDecision:
    eligible: bool
    conditions_met: bool
    reasons: list[str] = field(default_factory=list)
    blocking_reason: Optional[NoTradeReason] = None
    setup_used: Optional[SetupProfile] = None


@dataclass
class ExitDecision:
    verdict: Verdict
    reason: ExitReason
    details: str
    price_return: float = 0.0


@dataclass
class PositionSizingDecision:
    approved: bool
    size_sol: float
    raw_size_sol: float          # before adjustments
    infra_multiplier: float
    score_multiplier: float
    rejection_reason: Optional[NoTradeReason] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class StrategyDecision:
    """
    The canonical output of the strategy layer.
    Everything needed to log, audit, or act on a decision.
    """
    verdict: Verdict
    mint: str
    slot: int
    timestamp: float

    score: float                                  # 0-100
    score_breakdown: Optional[SignalQualityBreakdown] = None
    reasons: list[str]                            = field(default_factory=list)
    no_trade_reason: Optional[NoTradeReason]      = None
    exit_reason: Optional[ExitReason]             = None
    setup_used: Optional[SetupProfile]            = None
    sizing: Optional[PositionSizingDecision]      = None

    # Metrics snapshot (loggable)
    metrics: dict                                 = field(default_factory=dict)

    def to_log_dict(self) -> dict:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d

    @staticmethod
    def no_trade(
        mint: str,
        slot: int,
        reason: NoTradeReason,
        details: str,
        input_snapshot: Optional[StrategyInput] = None,
    ) -> "StrategyDecision":
        return StrategyDecision(
            verdict=Verdict.NO_TRADE,
            mint=mint,
            slot=slot,
            timestamp=time.time(),
            score=0.0,
            no_trade_reason=reason,
            reasons=[details],
            metrics=input_snapshot.to_log_dict() if input_snapshot else {},
        )
