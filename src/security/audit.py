# pyrefly: ignore [missing-import]
import logging
from typing import Dict, Any, Optional
from solana.rpc.async_api import AsyncClient
from src.config.settings import settings
from src.ingestion.models import AuditVerdict
from src.security.authority import AuthorityValidator
from src.security.concentration import HolderConcentrationAnalyzer

logger = logging.getLogger("ApexSol.SecurityAuditor")

class SecurityAuditor:
    """
    Coordinates fast security audits for Solana memecoins in the hot path.
    Verdicts: ALLOW, DENY, PENDING.
    """
    def __init__(self, rpc_client: AsyncClient):
        self.rpc_client = rpc_client
        self.authority_validator = AuthorityValidator()
        self.concentration_analyzer = HolderConcentrationAnalyzer(
            max_concentration=settings.max_dev_concentration
        )
        self.audit_cache: Dict[str, AuditVerdict] = {}

    def get_verdict(self, mint: str) -> AuditVerdict:
        """
        Returns cached verdict instantly.
        """
        return self.audit_cache.get(mint, AuditVerdict.PENDING)

    def audit_in_memory(self, mint: str, tx_data: bytes) -> AuditVerdict:
        """
        Runs very fast checks on the transaction payload itself.
        No blocking networking calls allowed here.
        """
        # Audit in-memory
        if settings.check_mint_authority:
            passed = self.authority_validator.verify_authorities_in_memory(tx_data)
            if not passed:
                # If we parsed creation transaction and authorities are NOT revoked, deny immediately
                logger.info(f"Token {mint} flagged UNSAFE in-memory: authorities not revoked.")
                self.audit_cache[mint] = AuditVerdict.DENY
                return AuditVerdict.DENY

        # If in-memory checks passed or are disabled, mark as PENDING until full RPC audit finishes
        if mint not in self.audit_cache or self.audit_cache[mint] == AuditVerdict.PENDING:
            self.audit_cache[mint] = AuditVerdict.PENDING
        return self.audit_cache[mint]

    async def run_full_async_audit(self, mint: str) -> AuditVerdict:
        """
        Performs background RPC checks to verify authorities & holder concentration on-chain concurrently.
        Updates internal cache when complete.
        """
        try:
            import asyncio
            from solders.pubkey import Pubkey

            check_auth = settings.check_mint_authority or settings.check_freeze_authority

            async def fetch_supply():
                try:
                    mint_info = await self.rpc_client.get_token_supply(Pubkey.from_string(mint))
                    return float(mint_info.value.ui_amount) if mint_info and mint_info.value else 0.0
                except Exception:
                    return 0.0

            # Execute RPC queries concurrently for minimal latency
            if check_auth:
                auth_ok, holders, total_supply = await asyncio.gather(
                    self.authority_validator.verify_authorities(self.rpc_client, mint),
                    self.concentration_analyzer.get_top_holders(self.rpc_client, mint),
                    fetch_supply(),
                    return_exceptions=True
                )
                if isinstance(auth_ok, Exception) or not auth_ok:
                    self.audit_cache[mint] = AuditVerdict.DENY
                    return AuditVerdict.DENY
            else:
                holders, total_supply = await asyncio.gather(
                    self.concentration_analyzer.get_top_holders(self.rpc_client, mint),
                    fetch_supply(),
                    return_exceptions=True
                )

            if isinstance(holders, Exception):
                holders = []
            if isinstance(total_supply, Exception):
                total_supply = 0.0

            if total_supply > 0.0 and holders:
                report = self.concentration_analyzer.analyze_concentration(holders, total_supply)
                if not report["passed"]:
                    logger.info(f"Token {mint} flagged UNSAFE via concentration: {report['reason']}")
                    self.audit_cache[mint] = AuditVerdict.DENY
                    return AuditVerdict.DENY

            # All checks passed
            self.audit_cache[mint] = AuditVerdict.ALLOW
            logger.info(f"Token {mint} passed all security audits concurrently. Marked ALLOW.")
            return AuditVerdict.ALLOW
        except Exception as e:
            logger.error(f"Error executing full async audit for {mint}: {e}")
            self.audit_cache[mint] = AuditVerdict.DENY
            return AuditVerdict.DENY
