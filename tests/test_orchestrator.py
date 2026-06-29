# pyrefly: ignore [missing-import]
import pytest
from unittest.mock import MagicMock, patch
from src.app.orchestrator import PipelineOrchestrator

@pytest.mark.asyncio
async def test_orchestrator_initialization():
    # Mock settings to prevent loading real configuration env vars
    with patch("src.app.orchestrator.settings") as mock_settings:
        mock_settings.solana_rpc_url = "https://api.mainnet-beta.solana.com"
        mock_settings.jito_block_engine_url = "https://tokyo.mainnet.block-engine.jito.wtf"
        mock_settings.yellowstone_grpc_url = "http://localhost:10000"
        mock_settings.yellowstone_grpc_auth_token = "dummy_token"
        mock_settings.replay_from_slot = None
        mock_settings.max_slot_lag = 10
        mock_settings.check_mint_authority = True
        mock_settings.check_freeze_authority = True
        mock_settings.max_dev_concentration = 0.15

        # Mock dependencies that attempt network IO on init
        with patch("src.app.orchestrator.AsyncClient") as mock_rpc_client, \
             patch("src.app.orchestrator.JitoClient") as mock_jito_client, \
             patch("src.app.orchestrator.YellowstoneGRPCClient") as mock_grpc_client:
            
            orchestrator = PipelineOrchestrator()
            
            assert orchestrator.rpc_client is not None
            assert orchestrator.jito_client is not None
            assert orchestrator.grpc_client is not None
            assert orchestrator.token_store is not None
            assert orchestrator.security_auditor is not None
