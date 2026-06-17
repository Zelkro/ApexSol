from typing import Dict, Any, List

class GeyserSubscriptionBuilder:
    """
    Builds Yellowstone gRPC subscription filters dynamically.
    Allows toggling programs, failed tx inclusion, commitment level, and transaction/block stream mode.
    """
    @staticmethod
    def build_pumpfun_filter(
        commitment: str = "confirmed",
        include_failed: bool = False,
        replay_mode: bool = False
    ) -> Dict[str, Any]:
        # Pump.fun Program ID
        pump_fun_id = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
        
        # In a real Geyser subscription, this dict maps to the SubscribeRequest protobuf
        # For simplicity, we define a dictionary format that the grpc client maps to the actual protobuf request
        return {
            "transactions": {
                "pump_fun_trades": {
                    "vote": False,
                    "failed": include_failed,
                    "account_include": [pump_fun_id],
                }
            },
            "commitment": commitment,
            "replay_mode": replay_mode
        }
