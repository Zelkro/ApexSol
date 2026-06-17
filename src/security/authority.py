import struct
import logging
from typing import Dict, Any, Optional
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

logger = logging.getLogger("ApexSol.AuthorityValidator")

class AuthorityValidator:
    """
    Validates SPL Token mint properties:
    - Mint Authority must be revoked (None/Null).
    - Freeze Authority must be disabled (None/Null).
    """
    MINT_LAYOUT_SIZE = 82

    @staticmethod
    def parse_mint_info(data: bytes) -> Dict[str, Any]:
        """
        Parses SPL Token Mint account raw data.
        """
        mint_auth = None
        offset = 0
        
        has_mint_auth = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4
        if has_mint_auth == 1:
            mint_auth = Pubkey(data[offset:offset+32])
            offset += 32
        else:
            offset += 32
            
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
            if not resp or not resp.value:
                return False
                
            data = resp.value.data
            if len(data) < self.MINT_LAYOUT_SIZE:
                return False
                
            parsed = self.parse_mint_info(data)
            safe = (parsed["mint_authority"] is None) and (parsed["freeze_authority"] is None)
            return safe
        except Exception as e:
            logger.debug(f"RPC Authority validation failed for {mint_address}: {e}")
            return False

    def verify_authorities_in_memory(self, tx_data: bytes) -> bool:
        """
        Deserializes a transaction locally and checks SPL Token instructions
        to see if MintAuthority and FreezeAuthority are revoked/None.
        """
        try:
            tx = VersionedTransaction.from_bytes(tx_data)
            message = tx.message
            
            token_program_id = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            account_keys = message.account_keys
            if token_program_id not in account_keys:
                return False
                
            token_program_index = account_keys.index(token_program_id)
            
            mint_auth_revoked = False
            freeze_auth_revoked = False
            initialized_mint = False
            
            for instruction in message.instructions:
                if instruction.program_id_index != token_program_index:
                    continue
                    
                data = instruction.data
                if not data:
                    continue
                    
                inst_type = data[0]
                
                # 0 = InitializeMint, 20 = InitializeMint2
                if inst_type in (0, 20):
                    initialized_mint = True
                    if len(data) >= 35:
                        freeze_option_idx = 34
                        freeze_auth_option = data[freeze_option_idx]
                        if freeze_auth_option == 0:
                            freeze_auth_revoked = True
                
                # 6 = SetAuthority
                elif inst_type == 6:
                    if len(data) >= 3:
                        auth_type = data[1]
                        new_auth_option = data[2]
                        
                        if auth_type == 0 and new_auth_option == 0:
                            mint_auth_revoked = True
                        elif auth_type == 1 and new_auth_option == 0:
                            freeze_auth_revoked = True
                            
            if initialized_mint:
                return mint_auth_revoked and freeze_auth_revoked
            
            return mint_auth_revoked and freeze_auth_revoked
        except Exception:
            return False
