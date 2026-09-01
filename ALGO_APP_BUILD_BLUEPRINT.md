# Algo Trading App Build Blueprint (Separate Application)

## 1) Purpose

This document is a complete implementation blueprint to build a separate, production-grade algo trading application by reusing the analytics and decision logic already present in this repository.

Primary goals:

1. Keep current study app unchanged and stable.
2. Build a new real-time algo app as an independent codebase.
3. Reuse proven strategy logic from this project with minimal behavioral drift.
4. Add broker execution, risk controls, observability, and reliability needed for live deployment.


## 2) Current Application Knowledge to Reuse

The following modules contain reusable business logic and should be treated as source-of-truth for strategy behavior.

### 2.1 Data and Parsing

- `src/data_provider.py`
  - Unified data access interface.
  - Real-data cache + synthetic fallback behavior.
- `src/real_data_loader.py`
  - Parsers for futures history, option chain, PCR files.
  - Data normalization patterns to keep.

### 2.2 Analytics and Signals

- `src/institutional_view.py`
  - Moving averages, ATR, OI/price interpretation, sentiment scoring.
- `src/options_view.py`
  - Option leg modeling, payoff logic, Greeks aggregation.
- `src/strategy_builder.py`
  - Regime detection and strategy generation logic.
- `src/option_buyer_strategies.py`
  - Buyer and hedging logic.
- `src/market_microstructure.py`
  - Additional market behavior helpers.

### 2.3 Trade Decision and Tracking

- `src/final_trade_decision.py`
  - Rule-based entry, stop-loss, target, and margin estimation.
- `src/trade_tracker.py`
  - Trade state updates, PnL calculation, hold/exit suggestion.
- `src/auto_trade_engine.py`
  - Scheduled safety checks, strategy orchestration, and lifecycle updates.

### 2.4 Configuration and Runbook Inputs

- `config.yaml`
  - Symbols, lot sizes, strike intervals, risk defaults.
- `APP_FUNCTIONALITY_REFERENCE.md`
  - Full algorithmic and functional specification.
- `README.md`
  - Workflow and operational intent.


## 3) What Must Change for Live Algo Capability

Current app is batch and study oriented. A live algo app needs additional layers:

1. Real-time market data ingestion (WebSocket/event stream).
2. Broker order execution layer (REST/WebSocket with robust state tracking).
3. Central risk engine (hard limits + kill switch).
4. Reliable event-driven runtime (not page-refresh driven).
5. Production observability and incident handling.


## 4) Target Architecture (Separate App)

Use a service-oriented structure with strict boundaries.

```
market data feed -> normalizer -> signal engine -> risk engine -> execution engine -> broker adapter
       |                              |                |              |
       +------------ state store -----+----------------+--------------+
                                      |
                                  monitoring
```

Recommended components:

1. `feed_service`
   - Connects to broker/market stream.
   - Produces normalized ticks, OHLC bars, chain snapshots.
2. `signal_service`
   - Runs reused logic from institutional/strategy modules.
   - Produces trade intents (not orders).
3. `risk_service`
   - Enforces portfolio and strategy limits.
   - Allows/blocklists intents before execution.
4. `execution_service`
   - Converts approved intents into orders.
   - Handles retries, partial fills, rejections, and cancel flows.
5. `portfolio_service`
   - Maintains positions, realized/unrealized PnL, exposure.
6. `api_ui`
   - Operational dashboard and controls (start/stop strategies, kill switch, logs).


## 5) Broker Integration Model (Including Motilal)

Build broker-specific code behind one interface.

### 5.1 Common Broker Interface

```python
class BrokerClient(Protocol):
    def login(self) -> None: ...
    def subscribe_market_data(self, instruments: list[str]) -> None: ...
    def place_order(self, order: OrderRequest) -> OrderResponse: ...
    def modify_order(self, order_id: str, req: ModifyOrderRequest) -> OrderResponse: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_positions(self) -> list[Position]: ...
    def get_orders(self) -> list[OrderState]: ...
```

### 5.2 Motilal Adapter Notes

1. Confirm API plan includes live market data streaming and order APIs.
2. Implement a `MotilalBrokerClient` adapter that maps provider payloads to internal models.
3. If full option-chain API is not available, construct chain snapshots from streamed option ticks.
4. Keep all provider field mappings in one adapter file to avoid vendor leakage across app.


## 6) Reuse Plan: Logic Porting Matrix

| Current module | New app destination | Porting rule |
|---|---|---|
| `src/institutional_view.py` | `domain/signals/institutional.py` | Reuse formulas as-is; isolate IO |
| `src/strategy_builder.py` | `domain/signals/strategy_builder.py` | Reuse regime logic; replace data fetch hooks |
| `src/options_view.py` | `domain/options/analytics.py` | Reuse payoff and greeks math |
| `src/final_trade_decision.py` | `domain/decision/final_decision.py` | Keep decision rules; convert to intent output |
| `src/trade_tracker.py` | `domain/portfolio/trade_state.py` | Rebuild as event-sourced state machine |
| `src/auto_trade_engine.py` | `services/orchestrator.py` | Convert cron flow to event scheduler |

Porting rule:

1. Keep strategy logic deterministic and pure.
2. Move all external dependencies to adapters.
3. Add regression tests to prove parity with current outputs.


## 7) Data Model Required in New App

Minimum canonical models:

1. `Tick`: instrument, ts_exchange, ltp, bid, ask, volume, oi.
2. `OptionSnapshot`: symbol, expiry, strike, option_type, ltp, iv, oi, volume.
3. `Bar`: timeframe, open, high, low, close, volume, oi.
4. `SignalIntent`: strategy_id, side, instrument, confidence, entry_rule, sl_rule, target_rule.
5. `RiskDecision`: pass/fail + reason codes.
6. `OrderRequest/OrderState`: side, qty, type, price, status, broker_order_id.
7. `Position`: net_qty, avg_price, mtm, realized_pnl, margin_used.
8. `AuditEvent`: immutable event stream for every decision and order change.


## 8) Risk Engine Requirements (Mandatory)

Implement these controls before enabling real money:

1. Max daily loss per strategy and global account.
2. Max open positions and max notional exposure.
3. Max concurrent orders and max rejects per minute.
4. Slippage guardrail (block if expected slippage exceeds threshold).
5. News/event block windows (optional but recommended).
6. Trade cooldown after consecutive losses.
7. Circuit breaker and global kill switch.
8. Forced square-off by configured cutoff time.


## 9) Execution Engine Requirements

Execution quality determines real profitability.

Required behaviors:

1. Idempotent order placement with client-generated idempotency key.
2. Stateful order lifecycle:
   - `NEW -> SENT -> ACK -> PARTIAL_FILL -> FILLED`
   - error paths: `REJECTED`, `CANCELLED`, `EXPIRED`
3. Retry policy with backoff for transient errors.
4. No duplicate orders on reconnect.
5. Real-time reconciliation loop against broker order book and positions.
6. Protective stop handling and fail-safe cancellation workflow.


## 10) Suggested Tech Stack for Separate App

Python-first production stack:

1. Runtime: Python 3.12+.
2. API: FastAPI.
3. Stream transport: WebSocket clients + optional Redis Pub/Sub.
4. Queue/Event bus: Redis Streams or Kafka (based on scale).
5. State store:
   - PostgreSQL for durable order/trade state.
   - Redis for low-latency snapshots.
6. Scheduler:
   - APScheduler/Celery for timed tasks.
7. Monitoring:
   - Prometheus + Grafana.
   - Structured JSON logs.
8. Deployment:
   - Docker + process supervisor.


## 11) Project Structure for New Repo

```
algo_app/
  services/
    feed_service/
    signal_service/
    risk_service/
    execution_service/
    portfolio_service/
    api_ui/
  domain/
    signals/
    decision/
    options/
    risk/
    portfolio/
  adapters/
    brokers/
      motilal.py
      angel.py
      zerodha.py
    market_data/
  infra/
    db/
    cache/
    messaging/
  tests/
    unit/
    integration/
    replay/
  docs/
    runbooks/
```


## 12) Build Plan (Phased)

### Phase 0: Freeze and Baseline

1. Freeze strategy formulas from current app.
2. Create golden datasets from existing CSV/JSON snapshots.
3. Add parity tests: old outputs vs new domain outputs.

Acceptance:

- New domain logic matches baseline outputs within tolerated numeric drift.

### Phase 1: Domain Extraction

1. Port reusable modules into pure domain package.
2. Remove UI and file IO from strategy logic.
3. Add complete unit tests for indicators, regime detection, and decision functions.

Acceptance:

- 90%+ domain test coverage.
- Deterministic outputs for fixed inputs.

### Phase 2: Live Data Layer

1. Implement market feed adapter for chosen broker.
2. Build normalized snapshot cache and bar builder.
3. Add reconnect and sequence-gap handling.

Acceptance:

- Feed recovery works after disconnect.
- Snapshot lag stays within target latency.

### Phase 3: Paper Execution Layer

1. Build full order state machine in simulated mode.
2. Wire risk engine before execution acceptance.
3. Add strategy scheduler and control endpoints.

Acceptance:

- End-to-end paper runs for at least 2 weeks without state corruption.

### Phase 4: Broker Live Execution (Small Size)

1. Enable live broker adapter with strict limits.
2. Trade only one instrument and one strategy initially.
3. Monitor rejects/slippage/latency and tune execution.

Acceptance:

- No duplicate orders.
- Daily risk limits always enforced.

### Phase 5: Production Hardening

1. Add alerts, dashboards, runbooks, and DR plan.
2. Add reconciliation jobs and EOD reports.
3. Enable multi-strategy, multi-instrument roll-out.

Acceptance:

- Stable operations across sessions.
- Complete audit trail for every decision and order.


## 13) Functional Requirements Checklist

### Strategy and Signal

- Indicator parity with current app.
- Regime classification parity.
- Trade intent generation parity.

### Risk and Controls

- Pre-trade checks mandatory.
- Intraday and daily limits mandatory.
- Emergency stop and forced flatten mandatory.

### Execution and Portfolio

- Order status tracking in real time.
- Position and PnL update on every fill/tick.
- Retry and reconciliation loops.

### Observability

- Metrics for latency, rejects, fill ratio, slippage.
- Structured logs with trace ids.
- Alerting for disconnects and risk breaches.


## 14) Non-Functional Requirements

1. Reliability: no data loss during reconnect.
2. Correctness: no duplicate order side effects.
3. Performance: bounded signal-to-order latency.
4. Security: encrypted secrets and strict key handling.
5. Auditability: immutable event logs.
6. Operability: one-command start/stop + clear runbooks.


## 15) Testing Strategy (Required)

1. Unit tests for every formula and decision rule.
2. Regression tests against historical snapshots from this repo.
3. Simulation replay tests for volatile days.
4. Integration tests with mock broker and market feed.
5. Chaos tests for disconnect, delayed ack, partial fills, and rejects.

Minimum go-live gate:

- Paper mode stability for 10-15 market sessions.
- Zero duplicate orders in replay and paper runs.
- Risk controls triggered correctly in forced scenarios.


## 16) Operational Runbooks to Prepare

1. Market open startup checklist.
2. Mid-session health checklist.
3. Incident response (feed down, broker down, DB down).
4. Kill switch and recovery procedure.
5. End-of-day reconciliation and report generation.


## 17) Migration Guidance from This Repo

1. Treat this repository as logic reference, not deployment base.
2. Do not mix Streamlit UI process with live order execution process.
3. Keep strategy outputs identical first; optimize later.
4. Preserve all risk assumptions explicitly in config.
5. Make broker integration replaceable via adapters.


## 18) Initial Deliverables for New Separate App

Build these first artifacts:

1. `domain` package with ported strategy logic and tests.
2. `adapters/brokers/motilal.py` with auth, data subscribe, place/modify/cancel order stubs.
3. `execution_service` with idempotent order state machine.
4. `risk_service` with mandatory hard limits.
5. `docs/runbooks` with startup/shutdown/incident SOP.


## 19) Final Recommendation

Yes, a proficient algo app is possible by reusing this app's logic, but only if the new system is built as an event-driven production architecture with strict risk gates and execution reliability.

Use this sequence:

1. Parity first.
2. Paper stability second.
3. Small live rollout third.
4. Scale after operational confidence.
