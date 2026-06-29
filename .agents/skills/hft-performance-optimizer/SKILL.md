---
name: hft-performance-optimizer
description: Conduct high-performance low-latency code audits, memory profiling, zero-copy optimizations, and concurrency tuning for Solana trading bots. Use when asked to optimize code, analyze execution speed, tune memory efficiency, or review HFT bot performance.
---

# HFT Performance Optimizer Agent Skill

This skill provides specialized instructions and workflows for auditing, micro-benchmarking, and optimizing Python-based high-frequency Solana trading applications (like ApexSol).

## Optimization Workflow

### Phase 1: Critical Hot-Path Audit
When auditing a module or file for performance:
1. **Identify Network RTTs**: Locate any blocking or sequential `await rpc_client.call()` invocations in trade processing callbacks. Refactor sequential RPC calls into parallel `asyncio.gather` tasks.
2. **Inspect Object Allocation**: Check tight loop code for unnecessary string concatenations, dictionary instantiation, or array copies.
3. **Verify Data Structures**: Ensure stateful classes maintain $O(1)$ lookup time and rolling statistics calculations.

### Phase 2: Memory & Layout Tuning
1. **`__slots__` Attribute Optimization**:
   For core event data models (e.g., trade events, order intents, token state wrappers), define `__slots__` to remove dynamic `__dict__` overhead, reducing object memory footprint by up to 60% and speeding up attribute access.
2. **Zero-Copy Byte Processing**:
   When parsing binary instruction payloads from gRPC streams or WebSocket feeds, utilize `memoryview` or binary struct unpacked views rather than copying sub-bytes.

### Phase 3: Event Loop & Asynchronous Scheduling
1. **`uvloop` Integration**: Ensure `uvloop.install()` is active in the main entry point to maximize socket throughput and minimize task scheduling latency.
2. **Non-Blocking Locks**: Avoid acquiring global async locks on hot paths unless mutating shared memory state. Prefer lockless atomic pointer/state swaps or queue-based producer-consumer patterns.

### Phase 4: Blockhash & Fee Pre-Fetching
1. Maintain cached recent blockhashes in memory with a short TTL (e.g., 2 seconds) to avoid querying the Solana RPC cluster at transaction signing time.
