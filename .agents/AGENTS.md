# Project Agent Guidelines for ApexSol

- **Performance First**: Prioritize sub-millisecond execution latency and zero-copy data structures on all hot paths (`ingestion`, `engine`, `execution`, `security`).
- **Concurrent RPC Operations**: Never execute sequential RPC queries in trade execution callbacks; use `asyncio.gather` for parallel queries.
- **Stateful Memory Management**: Ensure rolling indicator calculations use stateful $O(1)$ updates and token state stores implement automatic TTL pruning.
