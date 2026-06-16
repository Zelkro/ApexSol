import pytest
import polars as pl
from src.ingestion.parsers import PumpFunParser
from src.engine.indicators import TechnicalIndicators
from src.engine.microstructure import MicrostructureEngine
from src.execution.sandwich import SandwichProtection
from solders.instruction import Instruction
from solders.pubkey import Pubkey

def test_pump_fun_parser_trade_log():
    # Program logs representing a base64 encoded Pump.fun trade event
    # TradeEvent discriminator is: [189, 219, 127, 211, 161, 10, 220, 246]
    # We construct a mock base64 event
    # Payload bytes: discriminator (8) + mint (32) + sol_amount (8) + token_amount (8) + is_buy (1) + user (32) + timestamp (8)
    dummy_event = (
        b"\xbd\xdb\x7f\xd3\xa1\x0a\xdc\xf6"  # Disc
        + b"\x00" * 32                       # Mint
        + b"\xe8\x03\x00\x00\x00\x00\x00\x00" # 1000 sol_amount (u64)
        + b"\x40\x42\x0f\x00\x00\x00\x00\x00" # 1000000 token_amount (u64)
        + b"\x01"                            # is_buy (True)
        + b"\x00" * 32                       # User
        + b"\x00" * 8                        # Timestamp
    )
    import base64
    encoded = base64.b64encode(dummy_event).decode()
    log_str = f"Program data: {encoded}"
    
    parsed = PumpFunParser.parse_trade_log(log_str)
    assert parsed is not None
    assert parsed["sol_amount"] == 1000
    assert parsed["token_amount"] == 1000000
    assert parsed["is_buy"] is True

def test_technical_indicators_rsi():
    prices = pl.Series([10.0, 11.0, 12.0, 11.0, 12.0, 13.0, 14.0, 13.0, 12.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0])
    rsi = TechnicalIndicators.calculate_rsi(prices, period=5)
    assert rsi is not None
    assert 0 <= rsi <= 100

def test_microstructure_ofi():
    engine = MicrostructureEngine(ofi_window_size=10)
    mint = "TestMint11111111111111111111111111111111"
    
    engine.append_trade(mint, True, 1.0, 100)
    engine.append_trade(mint, True, 1.1, 150)
    engine.append_trade(mint, False, 1.05, 50)
    
    ofi = engine.calculate_ofi(mint)
    # Price rises (1.0 -> 1.1) on Buy: +150 OFI
    # Price falls (1.1 -> 1.05) on Sell: -50 OFI
    # Expect OFI value calculated
    assert ofi != 0.0

def test_sandwich_injection():
    program_id = Pubkey.new_unique()
    instruction = Instruction(
        program_id=program_id,
        data=b"test",
        accounts=[]
    )
    protected = SandwichProtection.inject_protection(instruction)
    assert len(protected.accounts) == 1
    assert protected.accounts[0].pubkey == Pubkey.from_string("96gYZ2y6xtJ6nt6WUx44yKWcWXFn2Fc14D9wZ1Dkhm7K")
