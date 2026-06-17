import base64
import struct
from typing import Dict, Any, Optional
from solders.pubkey import Pubkey

class PumpFunParser:
    """
    Decodes events and bonding curve states for the Pump.fun program:
    6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
    """
    # Discriminators for Pump.fun events / instruction data (e.g. Buy, Sell, Create)
    # E.g. Anchor event discriminators are SHA256 hashes of the struct name
    # We define layout formats for unpack operations.
    
    @staticmethod
    def parse_bonding_curve_state(data: bytes) -> Optional[Dict[str, Any]]:
        """
        Parses Pump.fun bonding curve account state.
        Layout of Pump.fun bonding curve state (8 bytes discriminator + struct data):
        - virtual_token_reserves: u64
        - virtual_sol_reserves: u64
        - real_token_reserves: u64
        - real_sol_reserves: u64
        - token_total_supply: u64
        - complete: bool
        """
        if len(data) < 41: # 8 (disc) + 5 * 8 (u64) + 1 (bool) = 49 bytes typical
            return None
        try:
            # Skip 8 bytes Anchor discriminator
            disc = data[:8]
            payload = data[8:]
            
            virtual_token_reserves, virtual_sol_reserves, real_token_reserves, real_sol_reserves, token_total_supply = struct.unpack(
                "<QQQQQ", payload[:40]
            )
            complete = payload[40] != 0
            
            return {
                "virtual_token_reserves": virtual_token_reserves,
                "virtual_sol_reserves": virtual_sol_reserves,
                "real_token_reserves": real_token_reserves,
                "real_sol_reserves": real_sol_reserves,
                "token_total_supply": token_total_supply,
                "complete": complete
            }
        except Exception:
            return None

    @staticmethod
    def parse_trade_log(log_str: str) -> Optional[Dict[str, Any]]:
        """
        Parses program execution logs looking for trade events.
        """
        # Search for program log signals or base64-encoded Anchor events
        if "Program log: Instruction:" in log_str:
            return None
        # Anchor logs typically output events as base64 strings:
        # e.g., "Program data: <base64>"
        if "Program data:" in log_str:
            try:
                base64_data = log_str.split("Program data:")[1].strip()
                event_bytes = base64.b64decode(base64_data)
                # Parse event structure (e.g., TradeEvent, CreateEvent)
                # TradeEvent discriminator is: [189, 219, 127, 211, 161, 10, 220, 246]
                if event_bytes.startswith(b"\xbd\xdb\x7f\xd3\xa1\x0a\xdc\xf6"):
                    # Layout: 8 bytes disc, mint: Pubkey(32), sol_amount: u64, token_amount: u64, is_buy: bool, user: Pubkey(32), timestamp: i64, ...
                    payload = event_bytes[8:]
                    mint = payload[:32]
                    sol_amount, token_amount = struct.unpack("<QQ", payload[32:48])
                    is_buy = payload[48] != 0
                    user = payload[49:81]
                    timestamp = struct.unpack("<q", payload[81:89])[0]
                    
                    return {
                        "event_type": "trade",
                        "mint": str(Pubkey.from_bytes(mint)),
                        "sol_amount": sol_amount,
                        "token_amount": token_amount,
                        "is_buy": is_buy,
                        "user": str(Pubkey.from_bytes(user)),
                        "timestamp": timestamp,
                        "platform": "pump.fun"
                    }
            except Exception:
                pass
        return None


class MoonshotParser:
    """
    Decodes events and states for Moonshot program.
    """
    @staticmethod
    def parse_bonding_curve_state(data: bytes) -> Optional[Dict[str, Any]]:
        # Mock/Skeletal layout for Moonshot state parsing
        # Real-world decodes will map the exact struct parameters defined by the Moonshot IDL.
        if len(data) < 32:
            return None
        try:
            # Skeleton mapping of Moonshot reserves and completion status
            virtual_token_reserves, virtual_sol_reserves = struct.unpack("<QQ", data[:16])
            complete = data[16] != 0
            return {
                "virtual_token_reserves": virtual_token_reserves,
                "virtual_sol_reserves": virtual_sol_reserves,
                "complete": complete,
                "platform": "moonshot"
            }
        except Exception:
            return None

    @staticmethod
    def parse_trade_log(log_str: str) -> Optional[Dict[str, Any]]:
        # Decode Moonshot program logs for Buy / Sell / Trade execution events
        if "Moonshot" in log_str and "Trade" in log_str:
            # Placeholder for exact regex/hex parsing corresponding to the Moonshot event layouts
            pass
        return None
