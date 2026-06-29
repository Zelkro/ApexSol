# pyrefly: ignore [missing-import]
import pytest
import time
import base64
import asyncio
from typing import Dict, Any

from solders.instruction import Instruction
from solders.message import Message
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.keypair import Keypair

from src.ingestion.models import RawStreamEvent, ParsedTradeEvent, TokenCreationEvent, TokenState, AuditVerdict, ExecutionIntent
from src.ingestion.parser_pumpfun import PumpFunParser
from src.engine.indicators import O1RSI, O1BollingerBands
from src.engine.signals import SignalEngine
from src.risk.guards import risk_guards
from src.config.settings import settings
from src.security.authority import AuthorityValidator
from src.execution.jito_client import JitoClient
from src.execution.executor import Executor
from src.execution.sandwich import SandwichProtection

def test_pump_fun_trade_event_parsing():
    # Construct a mock Base64 Anchor event representing trade
    # TradeEvent discriminator is: [189, 219, 127, 211, 161, 10, 220, 246]
    dummy_event = (
        b"\xbd\xdb\x7f\xd3\xa1\x0a\xdc\xf6"  # Disc
        + b"\x00" * 32                       # Mint (System Program key fallback representation)
        + b"\xe8\x03\x00\x00\x00\x00\x00\x00" # 1000 sol_amount (u64) -> 0.000001 SOL
        + b"\x40\x42\x0f\x00\x00\x00\x00\x00" # 1000000 token_amount (u64)
        + b"\x01"                            # is_buy (True)
        + b"\x00" * 32                       # User
        + b"\x00" * 8                        # Timestamp
    )
    encoded = base64.b64encode(dummy_event)
    raw_event = RawStreamEvent(
        event_id="test_id",
        slot=100,
        signature="test_sig",
        payload=b"Program data: " + encoded,
        received_at=time.time(),
        provenance="yellowstone"
    )
    
    parsed = PumpFunParser.parse_transaction(raw_event)
    assert isinstance(parsed, ParsedTradeEvent)
    assert parsed.side == "buy"
    assert parsed.amount_sol == 0.000001
    assert parsed.amount_token == 1000000
    assert parsed.mint == "11111111111111111111111111111111"

def test_pump_fun_creation_event_parsing():
    # CreateEvent discriminator is: [27, 192, 101, 115, 38, 162, 135, 58] (b"\x1b\xc0\x65\x73\x26\xa2\x87\x3a")
    dummy_event = (
        b"\x1b\xc0\x65\x73\x26\xa2\x87\x3a"  # Disc
        + b"\x00" * 32                       # Mint
        + b"\x00" * 32                       # Creator
        + b"\xe8\x03\x00\x00\x00\x00\x00\x00" # Virtual token reserves
        + b"\xe8\x03\x00\x00\x00\x00\x00\x00" # Virtual sol reserves
        + b"\xe8\x03\x00\x00\x00\x00\x00\x00" # Real token reserves
        + b"\xe8\x03\x00\x00\x00\x00\x00\x00" # Real sol reserves
    )
    raw_event = RawStreamEvent(
        event_id="test_id",
        slot=101,
        signature="test_sig_create",
        payload=dummy_event,
        received_at=time.time(),
        provenance="yellowstone"
    )
    
    parsed = PumpFunParser.parse_transaction(raw_event)
    assert isinstance(parsed, TokenCreationEvent)
    assert parsed.mint == "11111111111111111111111111111111"
    assert parsed.creator == "11111111111111111111111111111111"

def test_o1_rsi_incremental():
    rsi_calc = O1RSI(period=5)
    prices = [10.0, 11.0, 12.0, 11.0, 12.0, 13.0, 14.0, 13.0, 12.0, 11.0]
    
    for price in prices[:-1]:
        rsi = rsi_calc.update(price)
    
    final_rsi = rsi_calc.update(prices[-1])
    assert final_rsi is not None
    assert 0.0 <= final_rsi <= 100.0

def test_o1_bollinger_bands_incremental():
    bb_calc = O1BollingerBands(period=5, num_std=2.0)
    prices = [10.0, 11.0, 12.0, 11.0, 12.0, 13.0, 14.0, 13.0, 12.0, 11.0]
    
    for price in prices[:-1]:
        bb_calc.update(price)
        
    res = bb_calc.update(prices[-1])
    assert res is not None
    lower, middle, upper = res
    assert lower < middle < upper

def test_signal_engine_deterministic_entry():
    engine = SignalEngine(
        entry_trade_count_threshold=2,
        entry_buy_sol_threshold=0.1,
        entry_ofi_threshold=100.0
    )
    
    state = TokenState(
        mint="TestMint11111111111111111111111111111111",
        first_seen_at=time.time(),
        last_seen_at=time.time(),
        first_slot=500,
        last_slot=500,
        audit_status=AuditVerdict.ALLOW,
        recent_trade_count=3,
        buy_volume_sol=0.5,
        ofi=200.0,
        rolling_price=0.001
    )
    
    sig = engine.evaluate_entry(state, current_slot=500)
    assert sig is not None
    assert sig.signal_type == "entry"

def test_risk_guard_circuit_breaker():
    risk_guards.stream_healthy = True
    risk_guards.jito_healthy = True
    risk_guards.last_stream_heartbeat = time.time()
    risk_guards.consecutive_bundle_failures = 0
    risk_guards.current_open_positions = 0
    
    assert risk_guards.is_trade_allowed(current_slot=100, last_seen_slot=100) is True
    
    # Trigger slot lag
    assert risk_guards.is_trade_allowed(current_slot=200, last_seen_slot=100) is False
    
    # Trigger heartbeat stream timeout
    risk_guards.last_stream_heartbeat = time.time() - 20.0
    assert risk_guards.is_trade_allowed(current_slot=100, last_seen_slot=100) is False

@pytest.mark.asyncio
async def test_paper_execution_simulated():
    settings.mode = "paper"
    risk_guards.update_stream_heartbeat()
    risk_guards.jito_healthy = True
    risk_guards.consecutive_bundle_failures = 0
    risk_guards.current_open_positions = 0
    
    from unittest.mock import AsyncMock
    mock_rpc = AsyncMock()
    mock_jito = AsyncMock()
    
    executor = Executor(mock_rpc, mock_jito)
    intent = ExecutionIntent(
        intent_id="intent_123",
        mint="Mint11111111111111111111111111111111",
        side="buy",
        amount_sol=0.05,
        amount_token=0.0,
        max_slippage_bps=100,
        timestamp=time.time()
    )
    
    res = await executor.execute(intent, current_slot=1000)
    assert res.status == "landed"
    assert "paper_bundle_" in res.bundle_id

@pytest.mark.asyncio
async def test_authority_in_memory_checks():
    validator = AuthorityValidator()
    
    # 1. empty bytes fails
    assert validator.verify_authorities_in_memory(b"") is False
    
    # 2. Mock valid transaction
    token_program = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    set_mint_auth = Instruction(
        program_id=token_program,
        data=bytes([6, 0, 0]),  # SetAuthority, type=0 (MintTokens), new_auth=None (0)
        accounts=[]
    )
    set_freeze_auth = Instruction(
        program_id=token_program,
        data=bytes([6, 1, 0]),  # SetAuthority, type=1 (FreezeAccount), new_auth=None (0)
        accounts=[]
    )
    
    payer = Keypair()
    msg = Message.new_with_blockhash(
        [set_mint_auth, set_freeze_auth],
        payer=payer.pubkey(),
        blockhash=Hash.default()
    )
    tx = VersionedTransaction(msg, [payer])
    tx_bytes = bytes(tx)
    
    assert validator.verify_authorities_in_memory(tx_bytes) is True
