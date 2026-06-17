import asyncio
import os
import sys
import logging
from src.observability.logging import setup_logging
from src.app.orchestrator import PipelineOrchestrator

# Setup structured logger
logger = setup_logging()

async def main():
    logger.info("Initializing ApexSol Low-Latency Solana Pipeline...")
    
    orchestrator = PipelineOrchestrator()
    
    try:
        await orchestrator.start()
        
        # Keep running until cancelled or interrupted
        while True:
            await asyncio.sleep(3600)
            
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown signal received via process exception.")
    finally:
        await orchestrator.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
