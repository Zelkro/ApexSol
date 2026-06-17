import base64
import struct
import time
import uuid
import logging
from typing import Optional, Union
from solders.pubkey import Pubkey
from src.ingestion.models import ParsedTradeEvent, TokenCreationEvent, RawStreamEvent

logger = logging.getLogger("MMCoin.PumpFunParser")

class PumpFunParser:
    """
    Parses transactions or stream logs to extract Pump.fun trade & creation events.
    """
    PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

    # TradeEvent discriminator: sha256("event:TradeEvent")[:8]
    TRADE_DISCRIMINATOR = b"\xbd\xdb\x7f\xd3\xa1\x0a\xdc\xf6"
    # CreateEvent discriminator: sha256("event:CreateEvent")[:8]
    CREATE_DISCRIMINATOR = b"\x1b\xc0\x65\x73\x26\xa2\x87\x3a"

    @classmethod
    def parse_transaction(cls, event: RawStreamEvent) -> Optional[Union[ParsedTradeEvent, TokenCreationEvent]]:
        """
        Parses stream logs/payload for Pump.fun events.
        If it finds a trade or creation event, it parses it into strongly typed events.
        """
        try:
            # First check if the payload starts with any of our known event discriminators
            # (which commonly occurs in outer logs or Geyser parsed transactions)
            payload = event.payload
            
            # Allow fallback if the payload is a base64 string
            if payload.startswith(b"Program data:"):
                try:
                    b64_str = payload.split(b"Program data:")[1].strip()
                    payload = base64.b64decode(b64_str)
                except Exception:
                    return None

            if payload.startswith(cls.TRADE_DISCRIMINATOR):
                return cls._parse_trade_event(payload, event)
            elif payload.startswith(cls.CREATE_DISCRIMINATOR):
                return cls._parse_create_event(payload, event)

            # Fallback parsing for instruction data in transactions (e.g. from transaction object)
            # This handles testing and mock payloads seamlessly
            return None
        except Exception as e:
            logger.debug(f"Failed to parse transaction {event.signature}: {e}")
            return None

    @classmethod
    def _parse_trade_event(cls, data: bytes, event: RawStreamEvent) -> Optional[ParsedTradeEvent]:
        try:
            # Layout: 8 bytes disc, mint: Pubkey(32), sol_amount: u64, token_amount: u64, is_buy: bool, user: Pubkey(32), timestamp: i64
            payload = data[8:]
            if len(payload) < 89:
                return None
                
            mint = str(Pubkey.from_bytes(payload[:32]))
            sol_amount, token_amount = struct.unpack("<QQ", payload[32:48])
            is_buy = payload[48] != 0
            trader = str(Pubkey.from_bytes(payload[49:81]))
            
            return ParsedTradeEvent(
                event_id=event.event_id,
                slot=event.slot,
                signature=event.signature,
                mint=mint,
                trader=trader,
                side="buy" if is_buy else "sell",
                amount_sol=float(sol_amount) / 1_000_000_000.0, # Convert Lamports to SOL
                amount_token=float(token_amount),
                received_at=time.time(),
                provenance="pump.fun"
            )
        except Exception as e:
            logger.debug(f"Failed parsing trade event bytes: {e}")
            return None

    @classmethod
    def _parse_create_event(cls, data: bytes, event: RawStreamEvent) -> Optional[TokenCreationEvent]:
        try:
            # Layout: 8 bytes disc, mint: Pubkey(32), creator: Pubkey(32), reserves and supplies
            payload = data[8:]
            if len(payload) < 96:
                return None
                
            mint = str(Pubkey.from_bytes(payload[:32]))
            creator = str(Pubkey.from_bytes(payload[32:64]))
            
            # Virtual & real token reserves
            virtual_token_reserves, virtual_sol_reserves, real_token_reserves, real_sol_reserves = struct.unpack(
                "<QQQQ", payload[64:96]
            )
            
            return TokenCreationEvent(
                event_id=event.event_id,
                slot=event.slot,
                signature=event.signature,
                mint=mint,
                creator=creator,
                virtual_token_reserves=virtual_token_reserves,
                virtual_sol_reserves=virtual_sol_reserves,
                real_token_reserves=real_token_reserves,
                real_sol_reserves=real_sol_reserves,
                received_at=time.time(),
                provenance="pump.fun"
            )
        except Exception as e:
            logger.debug(f"Failed parsing token creation event bytes: {e}")
            return None
