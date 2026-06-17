# ApexSol: Low-Latency Solana Algorithmic Pipeline

A modular, production-grade Python algorithmic trading pipeline designed for Solana and targeting pump.fun, using Yellowstone gRPC (Geyser) for ingestion and Jito for MEV-resistant bundle execution.

## Features
- **Low Latency Ingestion**: Yellowstone gRPC client with connection tracking, gap detection, bounded task queueing, and overflow policies (`drop_oldest`, `drop_newest`, `fail_closed`).
- **In-Memory Security Audits**: Fast verification of Mint and Freeze authorities directly parsed from the gRPC stream.
- **Stateful $O(1)$ Indictators**: Real-time incremental Bollinger Bands, RSI, OFI, and trade cadence updates.
- **Dynamic Tip Management**: Auto-adjusts Jito validator tips from the Jito Tip Floor API.
- **MEV Rejection**: Implements the special `jitodontfront111111111111111111111111111111` account as MEV protection.
- **Execution Modes**: Paper, Shadow, and Live trading modes.

## Installation & Setup
1. Clone the repository and configure dependencies using `pyproject.toml`.
2. Setup environment settings in a `.env` file (copied from `.env.example`).
3. Run tests via `python -m pytest`.
4. Run the orchestrator: `python src/main.py`.
