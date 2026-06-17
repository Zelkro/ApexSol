# ⚡ ApexSol

ApexSol is a production-grade, ultra-low-latency event-driven algorithmic trading pipeline designed for Solana, focusing on real-time Pump.fun token creation and trade dynamics.

It connects securely to a **Yellowstone Geyser gRPC** node for instant pre-execution block/transaction streaming, performs local in-memory security audits, computes O(1) indicators, filters opportunities through risk circuit breakers, and executes transactions atomically using **Jito block engine bundles** with dynamic tipfloor adjustments.

---

## 🏛 Architecture Layout

```text
src/
├── config/
│   └── settings.py          # Environment configuration loader
├── ingestion/
│   ├── grpc_client.py       # Yellowstone gRPC subscriber and bounded queue manager
│   ├── subscription.py      # Stream filtering settings (Pump.fun program filters)
│   ├── parser_pumpfun.py    # Fast trade and token creation parser
│   └── models.py            # Strongly typed Dataclasses
├── security/
│   ├── audit.py             # In-memory and background RPC orchestrator
│   ├── authority.py         # SPL Token authority auditor (revoked Mint/Freeze checks)
│   └── concentration.py     # Top-holders & Dev wallet cluster concentration validator
├── state/
│   ├── token_store.py       # Task-safe memory store with background TTL eviction
│   └── windows.py           # Stateful sliding window buffers
├── engine/
│   ├── features.py          # Real-time incremental OFI, cadence and volume metrics
│   ├── indicators.py        # O(1) mathematical RSI & Bollinger Bands calculators
│   └── signals.py           # Configurable deterministic entry/exit signal rules
├── execution/
│   ├── tx_builder.py        # Transaction assembly and sandwich protection injection
│   ├── fees.py              # Percentile-based priority fee estimators
│   ├── jito_client.py       # Jito block engine client and bundle tracker
│   └── executor.py          # Execution coordinator (Paper, Shadow, Live modes)
├── risk/
│   ├── guards.py            # Global circuit breakers (slot lag, stream health, latency)
│   └── position_rules.py    # Sizing constraints & slippage bounds
├── observability/
│   ├── logging.py           # Structured JSON logging with trace correlation
│   ├── metrics.py           # Performance metrics counters, gauges, and latency stats
│   └── health.py            # Liveness and readiness endpoints
└── main.py                  # Entry point
```

---

## 🚀 Key Features

* **Yellowstone Geyser gRPC Ingestion**: Streams transactions with low latency. Connects to Yellowstone gRPC, monitors slot gaps, and buffers items into a bounded queue with configurable overflow policies (`drop_oldest`, `drop_newest`, `fail_closed`).
* **Zero-RPC Authority Audits**: Audits token creation transactions in-memory using local byte deserialization to instantly verify if `MintAuthority` and `FreezeAuthority` are revoked, preventing RPC roundtrips.
* **$O(1)$ Real-Time Metrics**: Computes indicators (Order Flow Imbalance, RSI, and Bollinger Bands) in constant time $O(1)$ using sliding sums and Wilder's lissage formulas.
* **MEV Front-Run Protection**: Injects the special `jitodontfront111111111111111111111111111111` read-only key to instruct block engines to automatically reject sandwiching.
* **Jito Bundle Execution**: Combines trade instructions and validator tip transfers into single atomic transactions, requesting recommendations dynamically from the Jito Tip Floor API.
* **Global Risk Guards**: Active monitors measuring slot lag, stream heartbeats, open position counts, and p99 pipeline latencies to instantly toggle off trading if thresholds are crossed.

---

## ⚙️ Configuration Variables (`.env`)

Copy the configuration template:
```bash
cp .env.example .env
```

Key parameters inside `.env`:
* `MODE`: Trading mode (`paper`, `shadow`, or `live`).
* `YELLOWSTONE_GRPC_URL`: Address to Geyser endpoint.
* `YELLOWSTONE_GRPC_AUTH_TOKEN`: Geyser credentials.
* `QUEUE_OVERFLOW_POLICY`: Behavior when bounded queue is full (`drop_oldest`, `drop_newest`, or `fail_closed`).
* `MAX_SLOT_LAG`: Permitted slot lag threshold before circuit breaking.

---

## 🛠 Installation & Usage

### Prerequisites
- Python >= 3.11
- Pytest (for running unit tests)

### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/Zelkro/ApexSol.git
   cd ApexSol
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt python-dotenv
   ```
3. Run unit tests to check functionality:
   ```bash
   python -m pytest
   ```
4. Start the pipeline:
   ```bash
   python src/main.py
   ```

---

## 📊 Observability & Monitoring

Logs are generated as structured JSON to facilitate ingestion into indexers like Elasticsearch or Loki.

Example trace format:
```json
{"timestamp": "2026-06-17T09:13:08Z", "level": "WARNING", "logger": "ApexSol.SignalEngine", "message": "🚨 ENTRY SIGNAL TRIGGERED for Mint111... | OFI: 1250.0, Trades: 6", "mint": "Mint111..."}
```

The system prints latency stats every 10 seconds, tracking processing intervals:
- `receive_to_parse_ms`: Time elapsed between network receipt and parsing.
- `parse_to_audit_ms`: Auditing delay.
- `submit_to_result_ms`: Time taken for Jito bundle confirmation.
