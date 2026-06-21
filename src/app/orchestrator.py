import asyncio
import time
import logging
import uuid
from typing import Dict, Any, Optional

from solana.rpc.async_api import AsyncClient
from src.config.settings import settings
from src.ingestion.grpc_client import YellowstoneGRPCClient
from src.ingestion.subscription import GeyserSubscriptionBuilder
from src.ingestion.parser_pumpfun import PumpFunParser
from src.ingestion.models import RawStreamEvent, ParsedTradeEvent, TokenCreationEvent, ExecutionIntent, AuditVerdict, TokenState
from src.security.audit import SecurityAuditor
from src.state.token_store import TokenStore
from src.engine.features import FeatureEngine
from src.engine.indicators import O1RSI, O1BollingerBands
from src.engine.signals import SignalEngine
from src.execution.jito_client import JitoClient
from src.execution.executor import Executor
from src.risk.guards import risk_guards
from src.observability.metrics import metrics
from src.app.lifecycle import LifecycleManager

logger = logging.getLogger("ApexSol.Orchestrator")

class PipelineOrchestrator:
    """
    Connects and runs the entire low-latency Solana trade pipeline.
    """
    def __init__(self):
        # 1. Initialize Clients
        self.rpc_client = AsyncClient(settings.solana_rpc_url)
        self.jito_client = JitoClient(settings.jito_block_engine_url)
        
        # 2. Ingestion
        sub_filter = GeyserSubscriptionBuilder.build_pumpfun_filter(
            commitment="confirmed",
            include_failed=False,
            replay_mode=settings.replay_from_slot
        )
        self.grpc_client = YellowstoneGRPCClient(
            grpc_url=settings.yellowstone_grpc_url,
            auth_token=settings.yellowstone_grpc_auth_token,
            subscription_filter=sub_filter
        )
        
        # 3. State & Analysis
        self.token_store = TokenStore()
        self.security_auditor = SecurityAuditor(self.rpc_client)
        self.feature_engine = FeatureEngine()
        self.signal_engine = SignalEngine()
        self.executor = Executor(self.rpc_client, self.jito_client)

        # Stateful O(1) indicators
        self.rsi_indicators: Dict[str, O1RSI] = {}
        self.bb_indicators: Dict[str, O1BollingerBands] = {}
        
        # Running tasks
        self._process_task: Optional[asyncio.Task] = None
        self._lifecycle_manager: Optional[LifecycleManager] = None

    async def start(self):
        logger.info("Initializing ApexSol trading orchestrator...")
        
        # Start state store TTL worker
        await self.token_store.start()

        # Connect gRPC client callback
        self.grpc_client.register_handler(self.handle_raw_event)
        
        # Start gRPC client tasks
        await self.grpc_client.start()
        
        # Start main ingestion processor loop
        self._process_task = asyncio.create_task(self._monitor_pipeline_status())
        
        # Setup lifecycle manager
        self._lifecycle_manager = LifecycleManager(
            tasks_to_cancel=[self._process_task],
            cleanup_callbacks=[
                self.grpc_client.stop,
                self.token_store.stop,
                self.rpc_client.close
            ]
        )
        logger.info("ApexSol orchestrator fully initialized.")

    async def stop(self):
        if self._lifecycle_manager:
            await self._lifecycle_manager.initiate_shutdown()

    async def handle_raw_event(self, event: RawStreamEvent):
        """
        Hot Path Callback: Triggered by gRPC reader dispatch task.
        Runs parsing, in-memory security check, indicator updating, signal generation, and execution.
        """
        t_received = time.time()
        metrics.increment("grpc_events_received_total")
        risk_guards.update_stream_heartbeat()

        # 1. Parse Event
        parsed = PumpFunParser.parse_transaction(event)
        t_parsed = time.time()
        metrics.record_latency("receive_to_parse_ms", (t_parsed - t_received) * 1000)

        if not parsed:
            return

        mint = parsed.mint
        # Retrieve or initialize TokenState
        token_state = await self.token_store.get_or_create(mint, event.slot)
        token_state.last_seen_at = time.time()
        token_state.last_slot = event.slot

        # 2. In-Memory Security Audit
        verdict = self.security_auditor.audit_in_memory(mint, event.payload)
        token_state.audit_status = verdict
        t_audit = time.time()
        metrics.record_latency("parse_to_audit_ms", (t_audit - t_parsed) * 1000)

        # Trigger background heavy RPC validation if pending
        if verdict == AuditVerdict.PENDING:
            asyncio.create_task(self._run_bg_audit(mint))

        # 3. Process Trades
        if isinstance(parsed, ParsedTradeEvent):
            # Update rolling features (OFI, cadence, volume)
            features = self.feature_engine.update(
                mint=mint,
                side=parsed.side,
                price=parsed.amount_sol / parsed.amount_token if parsed.amount_token > 0 else 0.0,
                amount_sol=parsed.amount_sol,
                amount_token=parsed.amount_token
            )
            
            token_state.ofi = features["ofi"]
            token_state.recent_trade_count += 1
            if parsed.side == "buy":
                token_state.total_buys += 1
                token_state.buy_volume_sol += parsed.amount_sol
            else:
                token_state.total_sells += 1
                token_state.sell_volume_sol += parsed.amount_sol

            price = parsed.amount_sol / parsed.amount_token if parsed.amount_token > 0 else 0.0
            if price > 0.0:
                token_state.rolling_price = price
                
                # Update O(1) indicators
                if mint not in self.rsi_indicators:
                    self.rsi_indicators[mint] = O1RSI(period=14)
                    self.bb_indicators[mint] = O1BollingerBands(period=20, num_std=2.0)
                
                token_state.rsi = self.rsi_indicators[mint].update(price)
                bb_val = self.bb_indicators[mint].update(price)
                if bb_val:
                    token_state.bollinger_lower, token_state.bollinger_mid, token_state.bollinger_upper = bb_val

        # Update modified state in memory store
        await self.token_store.update(mint, token_state)

        # 4. Evaluate Signal
        t_signal = time.time()
        entry_sig = self.signal_engine.evaluate_entry(token_state, event.slot)
        metrics.record_latency("audit_to_signal_ms", (t_signal - t_audit) * 1000)

        if entry_sig:
            metrics.increment("signal_generated_total")
            # Build ExecutionIntent
            intent = ExecutionIntent(
                intent_id=uuid.uuid4().hex,
                mint=mint,
                side="buy",
                amount_sol=0.05,  # Fixed buy size
                amount_token=0.0,
                max_slippage_bps=150,
                timestamp=time.time()
            )
            
            # 5. Trigger Execution (Async to avoid blocking hot path ingestion)
            asyncio.create_task(self._dispatch_execution(intent, event.slot, token_state))

    async def _run_bg_audit(self, mint: str):
        verdict = await self.security_auditor.run_full_async_audit(mint)
        token_state = await self.token_store.get(mint)
        if token_state:
            token_state.audit_status = verdict
            if verdict == AuditVerdict.ALLOW:
                metrics.increment("audit_allow_total")
            elif verdict == AuditVerdict.DENY:
                metrics.increment("audit_deny_total")
            await self.token_store.update(mint, token_state)

    async def _dispatch_execution(self, intent: ExecutionIntent, slot: int, state: TokenState):
        metrics.increment("execution_attempt_total")
        state.in_position = True
        
        t_submit = time.time()
        res = await self.executor.execute(intent, slot)
        t_result = time.time()
        
        metrics.record_latency("signal_to_submit_ms", (t_submit - intent.timestamp) * 1000)
        metrics.record_latency("submit_to_result_ms", (t_result - t_submit) * 1000)

        if res.status == "landed":
            metrics.increment("bundle_landed_total")
            state.last_signal = "buy"
        elif res.status == "failed":
            metrics.increment("bundle_failed_total")
            state.in_position = False
        else:
            metrics.increment("bundle_timeout_total")
            state.in_position = False
            
        await self.token_store.update(state.mint, state)

    async def _monitor_pipeline_status(self):
        """
        Background task logging metrics and system status periodically.
        """
        while True:
            try:
                await asyncio.sleep(10.0)
                # Sync health settings
                risk_guards.jito_healthy = True
                metrics.set_gauge("queue_depth", float(self.grpc_client.queue.qsize()))
                metrics.set_gauge("slot_lag", float(settings.max_slot_lag))
                metrics.log_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
