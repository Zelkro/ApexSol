import struct
from typing import Optional, Dict
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

class AuthorityValidator:
    """
    Validates SPL Token mint properties:
    - Mint Authority must be revoked (None/Null).
    - Freeze Authority must be disabled (None/Null).
    """
    
    # SPL Token Mint Layout:
    # Option<Pubkey> (4 + 32 bytes) -> mint_authority
    # u64 (8 bytes) -> supply
    # u8 (1 byte) -> decimals
    # bool (1 byte) -> is_initialized
    # Option<Pubkey> (4 + 32 bytes) -> freeze_authority
    MINT_LAYOUT_SIZE = 82

    @staticmethod
    def parse_mint_info(data: bytes) -> Dict[str, Any]:
        """
        Parses SPL Token Mint account raw data.
        """
        # Option<Pubkey> structure in Rust/Borsh serialization:
        # 4 bytes tag (0 = None, 1 = Some), followed by 32 bytes Pubkey if Some.
        mint_auth = None
        offset = 0
        
        has_mint_auth = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4
        if has_mint_auth == 1:
            mint_auth = Pubkey(data[offset:offset+32])
            offset += 32
        else:
            offset += 32 # Skip anyway if fixed padding
            
        supply = struct.unpack("<Q", data[offset:offset+8])[0]
        offset += 8
        decimals = data[offset]
        is_initialized = data[offset+1] != 0
        offset += 2
        
        freeze_auth = None
        has_freeze_auth = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4
        if has_freeze_auth == 1:
            freeze_auth = Pubkey(data[offset:offset+32])
            
        return {
            "mint_authority": mint_auth,
            "supply": supply,
            "decimals": decimals,
            "is_initialized": is_initialized,
            "freeze_authority": freeze_auth
        }

    async def verify_authorities(self, client: AsyncClient, mint_address: str) -> bool:
        """
        Fetches the mint account from chain and validates both authorities.
        """
        try:
            pubkey = Pubkey.from_string(mint_address)
            resp = await client.get_account_info(pubkey)
            if not resp.value:
                return False
                
            data = resp.value.data
            if len(data) < self.MINT_LAYOUT_SIZE:
                return False
                
            parsed = self.parse_mint_info(data)
            
            # Risk condition: Must have both revoked/disabled for complete safety.
            safe = (parsed["mint_authority"] is None) and (parsed["freeze_authority"] is None)
            return safe
        except Exception:
            return False
