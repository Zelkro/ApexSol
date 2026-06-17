from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List

class AuditVerdict(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    PENDING = "PENDING"

@dataclass
class RawStreamEvent:
    event_id: str
    slot: int
    signature: str
    payload: bytes
    received_at: float
    provenance: str  # e.g., "yellowstone" or "fallback_ws"

@dataclass
class ParsedTradeEvent:
    event_id: str
    slot: int
    signature: str
    mint: str
    trader: str
    side: str  # "buy" or "sell"
    amount_sol: float
    amount_token: float
    received_at: float
    provenance: str = "pump.fun"

@dataclass
class TokenCreationEvent:
    event_id: str
    slot: int
    signature: str
    mint: str
    creator: str
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    received_at: float
    provenance: str = "pump.fun"

@dataclass
class TokenState:
    mint: str
    first_seen_at: float
    last_seen_at: float
    first_slot: int
    last_slot: int
    audit_status: AuditVerdict = AuditVerdict.PENDING
    total_buys: int = 0
    total_sells: int = 0
    buy_volume_sol: float = 0.0
    sell_volume_sol: float = 0.0
    recent_trade_count: int = 0
    rolling_price: float = 0.0
    ofi: float = 0.0
    rsi: Optional[float] = None
    bollinger_mid: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_lower: Optional[float] = None
    in_position: bool = False
    last_signal: Optional[str] = None
    stale: bool = False

@dataclass
class SignalEvent:
    event_id: str
    mint: str
    signal_type: str  # "entry" or "exit"
    reason: str
    price: float
    slot: int
    timestamp: float

@dataclass
class ExecutionIntent:
    intent_id: str
    mint: str
    side: str  # "buy" or "sell"
    amount_sol: float
    amount_token: float
    max_slippage_bps: int
    timestamp: float

@dataclass
class BundleResult:
    bundle_id: str
    status: str  # "landed", "failed", or "timeout"
    slot_landed: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: float = 0.0
