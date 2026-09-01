# Algo Trading App Master Roadmap (Derived from Current Application)

## 1. Objective

Build a separate, production-oriented algo trading application by reusing the existing analytics, strategy logic, and trade lifecycle concepts.

This roadmap is based on:
- End-user workflow and operating guides
- Existing algorithmic behaviors and rule definitions
- Current data pipeline behavior (scheduled snapshots + CSV/JSON normalization)

The current app remains unchanged and continues as a study/paper-trade system.

## 2. Source Knowledge Consolidation

## 2.1 Functional Knowledge Reviewed

1. Overall user journey and daily operation flow.
2. Full feature and module behavior reference.
3. Hold/exit/reassess decision framework.
4. Intraday and end-of-day PnL update lifecycle.
5. Data source assumptions and scheduling commands.
6. Platform migration contracts and parity expectations.
7. Prior architecture blueprint and implementation notes.
8. Feature change history and logic update trail.
9. Original product constraints (study-only, no live execution).

## 2.2 Core Logic Areas Reviewed

1. Data abstraction layer for futures, option chain, and PCR.
2. Real-data normalization and validation logic.
3. Institutional analytics engine (trend, ATR, OI/price, sentiment).
4. Options analytics engine (legs, payoff, Greeks, risk/reward).
5. Strategy generation engine (option seller regimes and ideas).
6. Buyer and hedging strategy engine.
7. Final trade decision synthesis engine.
8. Trade journal and PnL update engine.
9. Automated entry/update/eod orchestration logic.
10. Backtesting engine and metric generation.
11. Core pricing/math/config utility layer.
12. Market microstructure helper analytics.

## 3. What the Current App Already Gives You

1. Data model and loaders for futures, option chain, and PCR.
2. Institutional signal stack:
   - SMA 20/50/200
   - ATR logic
   - OI/price signal matrix
   - max pain and OI walls
   - sentiment scoring
3. Options analytics:
   - multi-leg strategy payoff
   - risk/reward summary
   - Greeks aggregation
4. Strategy generation:
   - option seller regime logic
   - option buyer and hedging idea generation
5. Final decision assembly:
   - entry, stop-loss, targets, expected time, margin estimate
6. Trade lifecycle concepts:
   - journal state updates
   - intraday PnL refresh
   - hold/exit/reassess suggestions
   - auto close on target/stop
7. Backtesting baseline framework:
   - MA crossover and PCR contrarian scaffolding

## 4. Current Gaps vs Real Algo Trading

To become a real algo execution system, these are missing:

1. Native real-time event ingestion (tick/websocket stream).
2. Broker execution API with order lifecycle reconciliation.
3. Production-grade risk engine with hard kill switches.
4. Durable low-latency state stores for orders/positions.
5. Observability, incident response, and recovery workflows.
6. Deployment/runtime controls for market-hours reliability.

## 5. Target System Design (Separate App)

## 5.1 High-Level Flow

1. Market feed service receives live ticks.
2. Normalizer builds canonical market snapshots and bars.
3. Signal engine runs reused strategy logic.
4. Risk engine validates each trade intent.
5. Execution engine submits allowed orders to broker adapter.
6. Portfolio service updates positions and PnL continuously.
7. Monitoring and alerts track health, risk, and execution quality.

## 5.2 Required Core Services

1. Feed Service
2. Signal Service
3. Risk Service
4. Execution Service
5. Portfolio Service
6. Control API + Ops Dashboard

## 6. Logic Porting Map

| Existing logic area | New app role | Porting rule |
|---|---|---|
| Institutional analytics logic | Signal analysis layer | Keep formulas unchanged; remove display-layer coupling |
| Options payoff and Greeks logic | Options analytics layer | Keep payoff and Greeks exact |
| Regime detection and strategy generation | Strategy intelligence layer | Preserve thresholds and decision rules |
| Buyer and hedging strategy logic | Directional and hedge idea layer | Preserve ranking and constraints |
| Final trade synthesis logic | Decision layer | Output execution-ready trade intents |
| Trade lifecycle and PnL logic | Portfolio state layer | Convert to event-driven state transitions |
| Timed orchestration logic | Runtime orchestration layer | Convert schedule flow to event + scheduler model |
| Data normalization logic | Ingestion and parsing layer | Keep schema normalization behavior |
| Pricing, Greeks, and helper utilities | Core quant and configuration layer | Keep formulas and defaults consistent |

## 7. Canonical Data Contracts for New App

Define and freeze these internal contracts early:

1. Live market update record.
2. Option market snapshot record.
3. Timeframe bar/candle record.
4. Strategy trade intent record.
5. Risk approval/denial record.
6. Order submission record.
7. Order status transition record.
8. Position state record.
9. Portfolio snapshot record.
10. Immutable audit trail record.

Minimum contract rules:

1. All timestamps in ISO format with timezone.
2. Every intent has unique id and idempotency key.
3. Every order event references intent id.
4. All state transitions are append-only in audit stream.

## 8. Broker Layer Strategy (Motilal + Multi-Broker Future)

Build one broker abstraction and provider-specific adapters.

### 8.1 Interface Requirements

1. login and session refresh
2. subscribe/unsubscribe market data
3. place/modify/cancel order
4. fetch orders and positions
5. map broker statuses to internal order states

### 8.2 Motilal-Specific Plan

1. Confirm package tier for:
   - live market stream
   - derivatives order placement
   - order/position query limits
2. Implement the Motilal integration in dry-run first.
3. Add production mapping for:
   - order types
   - product types
   - exchange segments
4. If no complete option-chain endpoint exists, derive chain snapshots from live option ticks.

## 9. Risk Engine Design (Mandatory Before Live)

Hard controls:

1. max daily loss (global and strategy-wise)
2. max open positions
3. max notional exposure per symbol and portfolio
4. max orders/minute and max rejects/minute
5. slippage guardrail
6. cooldown after consecutive losses
7. intraday force-exit cutoff
8. global kill switch

Risk decision outcome per intent:

- allow
- block with reason code
- allow with reduced quantity

## 10. Execution Engine Design

Order lifecycle flow:

1. Created -> submitted.
2. Submitted -> acknowledged or rejected or cancelled.
3. Acknowledged -> partially filled or fully filled or cancelled or rejected.
4. Partially filled -> fully filled or cancelled.

Critical execution guarantees:

1. No duplicate live orders for same intent.
2. Idempotent retries for transient failures.
3. Reconciliation loop with broker orderbook and positions.
4. Recovery after restart using persisted order states.

## 11. Improvements Over Current App (Priority)

## 11.1 Data and Signal Quality

1. Move from hourly snapshots to sub-second tick stream.
2. Build robust bar aggregator for 1s/1m/5m frames.
3. Add stale-feed detector and feed-failover logic.
4. Add exchange calendar awareness for holidays/special sessions.

## 11.2 Strategy Quality

1. Keep original deterministic rules as baseline strategy set.
2. Add feature flags for strategy versions.
3. Add signal confidence calibration from historical replay.
4. Add conflict resolver when multiple strategies trigger opposite intents.

## 11.3 Risk and Capital Management

1. Portfolio-level VaR proxy (simple first, advanced later).
2. Dynamic position sizing by volatility regime.
3. Hard cap on overnight carry unless explicitly allowed.
4. Strategy-level drawdown pause and auto-throttle.

## 11.4 Operations and Reliability

1. Structured JSON logs and trace ids.
2. Metrics for latency, fill ratio, slippage, rejection rates.
3. Alerts for disconnects, stale data, risk breaches.
4. One-click kill switch and restart runbook.

## 12. Build Roadmap with Milestones

## Phase 0: Freeze Baseline (Week 1)

Deliverables:

1. Snapshot test fixtures from current CSV/JSON files.
2. Golden expected outputs from current modules.
3. Parity test suite skeleton.

Exit criteria:

- Baseline outputs reproducible and versioned.

## Phase 1: Domain Extraction (Week 2-3)

Deliverables:

1. Pure business-logic layer with ported analytics and decision logic.
2. Unit tests for formulas and regime outputs.
3. Config-driven thresholds.

Exit criteria:

- 90%+ deterministic parity for known datasets.

## Phase 2: Live Feed Foundation (Week 4-5)

Deliverables:

1. Feed service and normalizer.
2. Tick-to-bar aggregator.
3. Cache/store for latest snapshots.

Exit criteria:

- Stable feed for full market session in paper mode.

## Phase 3: Risk + Execution Simulation (Week 6-7)

Deliverables:

1. Risk engine with hard controls.
2. Execution state machine in paper simulator.
3. Portfolio state service and PnL updater.

Exit criteria:

- End-to-end paper execution with no invalid transitions.

## Phase 4: Motilal Adapter Dry-Run (Week 8)

Deliverables:

1. Auth/session manager.
2. Market data subscription integration.
3. Dry-run order mapping and response parser.

Exit criteria:

- Stable adapter behavior and complete state mappings.

## Phase 5: Controlled Live Pilot (Week 9-10)

Deliverables:

1. Small-size live mode with strict caps.
2. Real-time reconciliation and alerts.
3. Incident runbooks and rollback controls.

Exit criteria:

- Zero duplicate orders.
- Daily risk controls always enforced.
- Clean audit trail across full sessions.

## Phase 6: Production Hardening (Week 11+)

Deliverables:

1. Multi-strategy scheduling and orchestration.
2. Enhanced analytics and post-trade reports.
3. Performance tuning and deployment automation.

Exit criteria:

- Reproducible stable operations for multiple weeks.

## 13. Testing and Validation Plan

## 13.1 Test Types

1. Unit tests for formulas and strategy rules.
2. Regression tests against frozen baseline outputs.
3. Replay tests on historical high-volatility days.
4. Integration tests with mock broker and simulated feed gaps.
5. Chaos tests for disconnect, delayed ack, partial fill, reject storms.

## 13.2 Go-Live Gate

All must pass:

1. Paper mode stability for 10 to 15 sessions.
2. No duplicate order incidents.
3. Risk controls verified by forced breach scenarios.
4. Reconciliation mismatch rate near zero.
5. Operator runbooks validated by dry drills.

## 14. Suggested Application Layout for New App

```
algo_trading_app/
  apps/
    control_api/
    ops_dashboard/
  services/
    feed_service/
    signal_service/
    risk_service/
    execution_service/
    portfolio_service/
  domain/
    signals/
    options/
    decision/
    risk/
    portfolio/
    models/
  adapters/
    brokers/
      motilal/
    data/
  infra/
    db/
    cache/
    queue/
  tests/
    unit/
    integration/
    replay/
    chaos/
  docs/
    runbooks/
    architecture/
```

## 15. Implementation Guardrails

1. Keep current app logic as baseline and do not mutate formulas casually.
2. Separate strategy logic from broker logic strictly.
3. Never couple UI process with live order submission process.
4. Use feature flags to stage rollout safely.
5. Keep full audit logging from signal to fill.

## 16. Practical First Sprint Checklist

1. Create a new standalone application workspace.
2. Copy and port the business logic from the current system.
3. Add baseline parity tests using current data snapshots.
4. Implement core business records and order lifecycle transitions.
5. Implement risk engine v1 controls.
6. Add Motilal adapter in dry-run mode.
7. Build minimal ops API: health, positions, open-orders, kill-switch.

## 17. Conclusion

Yes, this application provides a strong functional foundation for a separate algo trading system.

The fastest safe path is:

1. Preserve logic parity first.
2. Add robust risk and execution infrastructure second.
3. Start with paper and dry-run integration.
4. Move to controlled live pilot only after operational stability.

This roadmap is designed to get you from current study-grade architecture to production-grade algo operations with clear milestones and risk controls.
