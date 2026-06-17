import asyncio
import time
import uuid
import logging
from typing import Dict, Optional, Set
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.hash import Hash
from solana.rpc.async_api import AsyncClient

from src.config.settings import settings
from src.ingestion.models import ExecutionIntent, BundleResult, TokenState
from src.risk.guards import risk_guards
from src.execution.tx_builder import TransactionBuilder
from src.execution.jito_client import JitoClient

logger = logging.getLogger("MMCoin.Executor")

class Executor:
    """
    Executes transaction intents.
    Prevents double-sends and supports: paper, shadow, and live modes.
    """
    def __init__(self, rpc_client: AsyncClient, jito_client: JitoClient):
        self.rpc_client = rpc_client
        self.jito_client = jito_client
        
        # Keypair to sign trades
        self.wallet = Keypair()
        
        # Concurrency protection to prevent double buying
        self.active_executions: Set[str] = set()

    async def execute(self, intent: ExecutionIntent, current_slot: int) -> BundleResult:
        mint = intent.mint
        
        # 1. Double-send check
        if mint in self.active_executions:
            logger.warning(f"Aborting execution: active trade already processing for {mint}")
            return BundleResult(bundle_id="", status="failed", error_message="Double-send protection triggered", timestamp=time.time())

        # 2. Risk guards verification
        if not risk_guards.is_trade_allowed(current_slot, current_slot):
            logger.warning(f"Aborting execution: risk guards blocked execution for {mint}")
            return BundleResult(bundle_id="", status="failed", error_message="Risk guards blocked execution", timestamp=time.time())

        self.active_executions.add(mint)
        logger.info(f"Initiating execution: intent_id={intent.intent_id}, mode={settings.mode.upper()}")
        
        try:
            # Paper mode: simulate success
            if settings.mode == "paper":
                await asyncio.sleep(0.5)
                logger.info(f"[PAPER MODE] Simulated execution SUCCESS for {mint}")
                risk_guards.report_bundle_success()
                return BundleResult(
                    bundle_id=f"paper_bundle_{uuid.uuid4().hex}",
                    status="landed",
                    slot_landed=current_slot + 1,
                    timestamp=time.time()
                )

            # Shadow mode: build and sign transaction, but do not send
            # Fetch blockhash
            try:
                blockhash_resp = await self.rpc_client.get_latest_blockhash()
                blockhash = blockhash_resp.value.blockhash if blockhash_resp and blockhash_resp.value else Hash.default()
            except Exception:
                blockhash = Hash.default()

            # Build Jito Tip instruction
            tip_account = Pubkey.from_string(self.jito_client.select_tip_account())
            tip_lamports = int(settings.default_jito_tip_sol * 1_000_000_000)
            
            tip_ix = TransactionBuilder.build_jito_tip_instruction(
                payer=self.wallet.pubkey(),
                tip_account=tip_account,
                tip_lamports=tip_lamports
            )

            # Build Trade instruction
            trade_ix = TransactionBuilder.build_pumpfun_trade_instruction(
                payer=self.wallet.pubkey(),
                mint=Pubkey.from_string(mint),
                amount_sol=intent.amount_sol,
                side=intent.side
            )

            # Compile into transaction
            tx = TransactionBuilder.build_versioned_transaction(
                payer=self.wallet.pubkey(),
                instructions=[trade_ix, tip_ix],
                blockhash=blockhash
            )
            # Sign transaction
            tx.sign([self.wallet])

            if settings.mode == "shadow":
                logger.info(f"[SHADOW MODE] Transaction signed. Size: {len(bytes(tx))} bytes. Execution aborted (not sent).")
                return BundleResult(
                    bundle_id=f"shadow_bundle_{uuid.uuid4().hex}",
                    status="landed",
                    timestamp=time.time()
                )

            # Live mode: Send bundle to Jito
            bundle_id = await self.jito_client.send_bundle([tx])
            if not bundle_id:
                risk_guards.report_bundle_failure()
                return BundleResult(bundle_id="", status="failed", error_message="Jito rejected bundle submission", timestamp=time.time())

            # Track status
            status = await self.jito_client.track_bundle(bundle_id)
            if status == "landed":
                risk_guards.report_bundle_success()
            else:
                risk_guards.report_bundle_failure()

            return BundleResult(
                bundle_id=bundle_id,
                status=status,
                timestamp=time.time()
            )

        except Exception as e:
            logger.error(f"Executor exception for {mint}: {e}")
            risk_guards.report_bundle_failure()
            return BundleResult(bundle_id="", status="failed", error_message=str(e), timestamp=time.time())
        finally:
            self.active_executions.discard(mint)
