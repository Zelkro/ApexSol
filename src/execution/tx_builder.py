# pyrefly: ignore [missing-import]
import logging
from typing import List, Optional
from solders.pubkey import Pubkey
from solders.instruction import AccountMeta, Instruction
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.system_program import transfer, TransferParams
from src.config.settings import settings

logger = logging.getLogger("MMCoin.TransactionBuilder")

class TransactionBuilder:
    """
    Constructs purchase/sale transactions for Pump.fun tokens.
    Automatically injects MEV sandwich protection and priority fees.
    """
    PUMP_FUN_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
    JITO_DONT_FRONT_PUBKEY = Pubkey.from_string("jitodontfront111111111111111111111111111111")

    @classmethod
    def build_pumpfun_trade_instruction(
        cls,
        payer: Pubkey,
        mint: Pubkey,
        amount_sol: float,
        side: str
    ) -> Instruction:
        """
        Builds the mock instruction representing a Pump.fun trade.
        Injects the 'jitodontfront' pubkey as a read-only meta for searcher rejection.
        """
        # Mock layout for trade: side, amount (u64)
        is_buy = 1 if side == "buy" else 0
        lamports = int(amount_sol * 1_000_000_000)
        
        # Serialization: [is_buy (u8), lamports (u64)]
        import struct
        data = struct.pack("<BQ", is_buy, lamports)

        # Inject Jito sandwich protection account as the very first read-only key
        accounts = [
            AccountMeta(pubkey=cls.JITO_DONT_FRONT_PUBKEY, is_signer=False, is_writable=False),
            AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=mint, is_signer=False, is_writable=True),
        ]

        return Instruction(
            program_id=cls.PUMP_FUN_PROGRAM,
            data=data,
            accounts=accounts
        )

    @classmethod
    def build_jito_tip_instruction(cls, payer: Pubkey, tip_account: Pubkey, tip_lamports: int) -> Instruction:
        """
        Creates the transfer instruction to pay the Jito validator tip.
        """
        return transfer(
            TransferParams(
                from_pubkey=payer,
                to_pubkey=tip_account,
                lamports=tip_lamports
            )
        )

    @classmethod
    def build_versioned_transaction(
        cls,
        payer: Pubkey,
        instructions: List[Instruction],
        blockhash
    ) -> VersionedTransaction:
        """
        Assembles a list of instructions into a VersionedTransaction.
        """
        # Compile V0 Message
        from solders.message import Message
        msg = Message.new_with_blockhash(
            instructions,
            payer=payer,
            blockhash=blockhash
        )
        return VersionedTransaction(msg, [])
