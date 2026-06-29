# pyrefly: ignore [missing-import]
import logging
from typing import Dict, Any, Optional
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from src.security.authority import AuthorityValidator
from src.security.concentration import HolderConcentrationAnalyzer
from src.security.rugcheck import RugCheckClient

logger = logging.getLogger("MMCoin.Gatekeeper")

class SecurityGatekeeper:
    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.authority_validator = AuthorityValidator()
        self.concentration_analyzer = HolderConcentrationAnalyzer(
            max_concentration=settings["security"].get("max_dev_holder_concentration", 0.15)
        )
        self.rugcheck_client = RugCheckClient(
            api_url=settings["security"].get("rugcheck_api_url", "https://api.rugcheck.xyz/v1")
        )

    async def validate_token(self, client: AsyncClient, mint_address: str) -> Dict[str, Any]:
        """
        Coordinates the complete safety checks of Layer 2.
        Returns validation status and reason details.
        """
        # 1. Authority Validation
        if self.settings["security"].get("check_mint_authority", True):
            authorities_ok = await self.authority_validator.verify_authorities(client, mint_address)
            if not authorities_ok:
                return {"safe": False, "reason": "Failed Mint/Freeze Authority safety check"}

        # 2. Holder Concentration & Dev Wallet Clusters
        holders = await self.concentration_analyzer.get_top_holders(client, mint_address)
        if holders:
            # Estimate total supply from token metadata or sum of accounts
            # In a real pipeline, we fetch mint info supply first. As a fail-safe, we sum holders or fetch mint.
            mint_info = await client.get_token_supply(Pubkey.from_string(mint_address))
            total_supply = float(mint_info.value.ui_amount) if mint_info.value else 0.0
            
            if total_supply > 0:
                concentration_report = self.concentration_analyzer.analyze_concentration(holders, total_supply)
                if not concentration_report["passed"]:
                    return {"safe": False, "reason": concentration_report["reason"]}

        # 3. RugCheck Scan
        if self.settings["security"].get("rugcheck_enabled", True):
            report = await self.rugcheck_client.check_token(mint_address)
            rugcheck_ok = self.rugcheck_client.evaluate_rugcheck_report(report)
            if not rugcheck_ok:
                return {"safe": False, "reason": "RugCheck flagged token as dangerous"}

        return {"safe": True, "reason": "Passed all safety checks"}
