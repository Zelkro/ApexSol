# pyrefly: ignore [missing-import]
import aiohttp
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("MMCoin.RugCheck")

class RugCheckClient:
    """
    Connects to the RugCheck API to fetch safety metrics and evaluations.
    """
    def __init__(self, api_url: str = "https://api.rugcheck.xyz/v1"):
        self.api_url = api_url

    async def check_token(self, mint_address: str) -> Optional[Dict[str, Any]]:
        """
        Queries the RugCheck API for a given mint address.
        """
        url = f"{self.api_url}/tokens/{mint_address}/report"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 404:
                        logger.warning(f"Token {mint_address} not found on RugCheck API.")
                        return None
                    else:
                        logger.error(f"RugCheck API returned error status: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Failed to query RugCheck API: {e}")
            return None

    def evaluate_rugcheck_report(self, report: Optional[Dict[str, Any]]) -> bool:
        """
        Parses report for critical vulnerabilities (Rug score, risky conditions).
        """
        if not report:
            # Fallback policy: if RugCheck is offline, pass but log warning, or fail conservatively.
            # Here we default to returning True (allowing other checks to catch rug conditions)
            # but noting the failure.
            return True
            
        score = report.get("score", 0)
        # If score is > 1000, RugCheck flags the token as high risk/danger
        if score > 1000:
            return False
            
        risks = report.get("risks", [])
        for risk in risks:
            # Check for critical danger flags
            if risk.get("level") == "danger":
                return False
                
        return True
