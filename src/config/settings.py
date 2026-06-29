# pyrefly: ignore [missing-import]
import os
from dotenv import load_dotenv

# Load dot env file at module load time
load_dotenv()

class Settings:
    def __init__(self):
        # General & Modes
        self.mode = os.getenv("MODE", "paper")  # paper, shadow, or live
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        # RPC & gRPC
        self.solana_rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.solana_ws_url = os.getenv("SOLANA_WS_URL", "wss://api.mainnet-beta.solana.com")
        self.yellowstone_grpc_url = os.getenv("YELLOWSTONE_GRPC_URL", "yellowstone-grpc.helius-rpc.com:443")
        self.yellowstone_grpc_auth_token = os.getenv("YELLOWSTONE_GRPC_AUTH_TOKEN", "")

        # Ingestion Bounded Queue
        self.queue_size = int(os.getenv("QUEUE_SIZE", "10000"))
        self.queue_overflow_policy = os.getenv("QUEUE_OVERFLOW_POLICY", "drop_oldest")  # drop_oldest, drop_newest, fail_closed

        # Replay
        self.replay_from_slot = os.getenv("REPLAY_FROM_SLOT", "False").lower() in ("true", "1", "yes")
        
        # Thresholds
        self.max_slot_lag = int(os.getenv("MAX_SLOT_LAG", "10"))
        self.staleness_threshold_seconds = float(os.getenv("STALENESS_THRESHOLD_SECONDS", "5.0"))
        self.metrics_port = int(os.getenv("METRICS_PORT", "8000"))

        # Risk Guards
        self.max_open_positions = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
        self.p99_latency_threshold_ms = float(os.getenv("P99_LATENCY_THRESHOLD_MS", "150.0"))

        # Security Auditing
        self.check_mint_authority = os.getenv("CHECK_MINT_AUTHORITY", "True").lower() in ("true", "1", "yes")
        self.check_freeze_authority = os.getenv("CHECK_FREEZE_AUTHORITY", "True").lower() in ("true", "1", "yes")
        self.max_dev_concentration = float(os.getenv("MAX_DEV_CONCENTRATION", "0.15"))

        # Jito & Execution
        self.jito_block_engine_url = os.getenv("JITO_BLOCK_ENGINE_URL", "https://mainnet.block-engine.jito.wtf")
        self.jito_tip_account = os.getenv("JITO_TIP_ACCOUNT", "Cw8CFyM92ocnFYCHkuTFA3bCw58AgqESzb4C236qRBdB")
        self.default_jito_tip_sol = float(os.getenv("DEFAULT_JITO_TIP_SOL", "0.001"))
        self.priority_fee_strategy = os.getenv("PRIORITY_FEE_STRATEGY", "percentile")  # fixed, percentile, adaptive
        self.jito_tip_strategy = os.getenv("JITO_TIP_STRATEGY", "median")  # fixed, minimum, median, high

# Global singleton
settings = Settings()
