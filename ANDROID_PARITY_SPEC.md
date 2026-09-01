# Android Parity Spec (Strict Contracts + Test Vectors)

## Purpose
This document is a strict implementation contract for building the Android version of the existing app with minimal ambiguity.

Use this together with [ANDROID_ONE_SHOT_ANDROID_PROMPT.md](ANDROID_ONE_SHOT_ANDROID_PROMPT.md).

---

## Module Mapping (Python -> Android)

| Python Module | Android Package | Android Class/File |
|---|---|---|
| app.py | feature.* | Screen composables + ViewModels + Nav graph |
| src/utils.py | core.math, core.config, core.format | OptionMath.kt, Greeks.kt, AppConfig.kt, Formatters.kt |
| src/data_provider.py | data.repository, data.datasource | MarketRepositoryImpl.kt, SyntheticDataSource.kt, RealDataSource.kt |
| src/real_data_loader.py | data.parser | NsePriceCsvParser.kt, NseOptionChainCsvParser.kt, NsePcrCsvParser.kt |
| src/institutional_view.py | domain.institutional | InstitutionalAnalyzer.kt |
| src/options_view.py | domain.options | OptionsAnalyzer.kt, StrategyCatalogue.kt |
| src/strategy_builder.py | domain.strategybuilder | StrategyBuilder.kt |
| src/option_buyer_strategies.py | domain.buyerhedge | BuyerStrategyEngine.kt |
| src/final_trade_decision.py | domain.finaldecision | FinalTradeDecisionEngine.kt |
| src/trade_tracker.py | data.local, domain.journal | TradeEntity.kt, TradeDao.kt, TradeJournalService.kt |
| src/backtesting.py | domain.backtest | BacktestEngine.kt |

---

## Kotlin Data Contracts

## Core market models
```kotlin
@Serializable
data class FuturesBar(
    val date: LocalDate,
    val open: Double,
    val high: Double,
    val low: Double,
    val close: Double,
    val volume: Long,
    val oi: Long
)

@Serializable
data class OptionChainRow(
    val date: LocalDate,
    val strike: Int,
    val ceLtp: Double,
    val ceIv: Double,
    val ceOi: Long,
    val ceVolume: Long,
    val peLtp: Double,
    val peIv: Double,
    val peOi: Long,
    val peVolume: Long,
    val spot: Double
)

@Serializable
data class PcrRow(
    val date: LocalDate,
    val pcrOi: Double,
    val pcrVol: Double,
    val totalCeOi: Long,
    val totalPeOi: Long
)
```

## Institutional outputs
```kotlin
data class OiConcentration(
    val ceWall: Double,
    val peWall: Double,
    val ceWallOi: Long,
    val peWallOi: Long,
    val itmCeOiPct: Double,
    val itmPeOiPct: Double
)

data class IvSkewResult(
    val atmIv: Double,
    val avgOtmPutIv: Double,
    val avgOtmCallIv: Double,
    val skew: Double,
    val skewLabel: String
)

data class SentimentResult(
    val score: Int,
    val label: String,
    val bullishFactors: List<String>,
    val bearishFactors: List<String>,
    val neutralFactors: List<String>,
    val keyLevels: Map<String, Double?>,
    val skewData: IvSkewResult?,
    val oiConcentration: OiConcentration?,
    val riskFactors: List<String>,
    val pcr5dAvg: Double?
)
```

## Options outputs
```kotlin
data class OptionLeg(
    val type: String,      // CE | PE | futures
    val action: String,    // buy | sell
    val strike: Double,
    val premium: Double,
    val qty: Int
)

data class Greeks(
    val delta: Double,
    val gamma: Double,
    val theta: Double,
    val vega: Double
)

data class StrategyGreeks(
    val aggregate: Greeks,
    val legBreakdown: List<Map<String, Any>>
)

data class RiskRewardSummary(
    val netPremium: Double,
    val maxProfitPts: Double,
    val maxLossPts: Double,
    val maxProfitInr: Double,
    val maxLossInr: Double,
    val breakevens: List<Double>,
    val riskRewardRatio: Double
)
```

## Final decision outputs
```kotlin
data class InstitutionalDecision(
    val logic: String,
    val direction: String,
    val instrument: String,
    val futuresEntry: String,
    val futuresSl: String,
    val futuresTarget1: String,
    val futuresTarget2: String,
    val futuresMargin: String,
    val futuresMarginIntraday: String,
    val optionType: String,
    val optionStrike: Int,
    val optionPremium: String,
    val optionIv: String,
    val optionSl: String,
    val optionTarget: String,
    val optionMargin: String,
    val riskReward: String,
    val riskLevel: String,
    val expectedTime: String,
    val reason: String,
    val invalidConditions: List<String>,
    val sentimentLabel: String,
    val sentimentScore: Int,
    val rawEntryPrice: Double,
    val rawSlPrice: Double,
    val rawTargetPrice: Double,
    val rawStrike: Int,
    val rawOptType: String,
    val rawDirection: String
)

data class OptionSellerDecision(
    val logic: String,
    val strategy: String,
    val description: String,
    val instrument: String,
    val shortCeStrike: Int,
    val shortPeStrike: Int,
    val buyCeStrike: Int?,
    val buyPeStrike: Int?,
    val cePremium: String,
    val pePremium: String,
    val totalCredit: String,
    val totalCreditLot: String,
    val slRule: String,
    val targetRule: String,
    val riskLevel: String,
    val expectedTime: String,
    val marginRequired: String,
    val reason: String,
    val fitConditions: String,
    val invalidConditions: List<String>,
    val profitRange: String,
    val rawEntryPrice: Double,
    val rawSlPrice: Double,
    val rawTargetPrice: Double,
    val rawStrikeCe: Int,
    val rawStrikePe: Int,
    val rawOptType: String,
    val rawDirection: String
)
```

## Journal persistence (Room)
```kotlin
@Entity(tableName = "trades")
data class TradeEntity(
    @PrimaryKey val id: String,
    val timestamp: String,
    val symbol: String,
    val instrument: String,
    val direction: String,
    val strike: String,
    val entryPrice: Double,
    val stopLoss: Double,
    val target: Double,
    val qtyLots: Int,
    val lotSize: Int,
    val strategyType: String,
    val regime: String,
    val structure: String,
    val reason: String,
    val expectedTime: String,
    val marginApprox: String,
    val status: String,
    val exitPrice: Double?,
    val pnlPerLot: Double?,
    val totalPnl: Double?,
    val suggestion: String,
    val suggestionReason: String,
    val notes: String
)
```

---

## Mandatory Service Interfaces

```kotlin
interface MarketRepository {
    suspend fun ensureSymbolData(symbol: String)
    suspend fun loadRealData(futuresPath: String, chainPath: String, pcrPath: String, symbol: String): RealLoadInfo
    suspend fun clearRealData()
    suspend fun getFuturesHistory(symbol: String, start: LocalDate?, end: LocalDate?): List<FuturesBar>
    suspend fun getOptionChain(symbol: String, date: LocalDate?): List<OptionChainRow>
    suspend fun getPcr(symbol: String, start: LocalDate?, end: LocalDate?): List<PcrRow>
    suspend fun getAvailableOptionDates(symbol: String): List<LocalDate>
}

interface InstitutionalAnalyzer {
    fun computeMovingAverages(data: List<FuturesBar>, windows: List<Int> = listOf(20, 50, 200)): List<Map<String, Any>>
    fun computeAtr(data: List<FuturesBar>, period: Int = 14): List<Map<String, Any>>
    fun computeVolumeOiAnalysis(data: List<FuturesBar>): List<Map<String, Any>>
    fun computeMaxPain(chain: List<OptionChainRow>): Double
    fun computeIvSkew(chain: List<OptionChainRow>): IvSkewResult
    fun computeOiConcentration(chain: List<OptionChainRow>): OiConcentration
    fun generateSentiment(futures: List<FuturesBar>, chain: List<OptionChainRow>, pcr: List<PcrRow>): SentimentResult
}

interface OptionsAnalyzer {
    fun buildLegs(strategyName: String, strikes: Map<String, Double>, chain: List<OptionChainRow>, tYears: Double): List<OptionLeg>
    fun computePayoff(legs: List<OptionLeg>, spotRange: DoubleArray): DoubleArray
    fun computeStrategyGreeks(legs: List<OptionLeg>, spot: Double, tYears: Double, sigma: Double): StrategyGreeks
    fun riskRewardSummary(legs: List<OptionLeg>, lotSize: Int, spot: Double): RiskRewardSummary
}

interface TradeJournalService {
    suspend fun addTrade(trade: TradeEntity): String
    suspend fun loadTrades(symbolFilter: String? = null): List<TradeEntity>
    suspend fun getOpenTrades(symbol: String? = null): List<TradeEntity>
    suspend fun updateAllOpen(chain: List<OptionChainRow>, futures: List<FuturesBar>): List<TradeEntity>
    suspend fun closeTrade(tradeId: String, exitPrice: Double, notes: String = ""): Boolean
    suspend fun deleteTrade(tradeId: String): Boolean
}
```

---

## Golden Parity Tests

## Test policy
- Use deterministic seeded synthetic data in tests.
- Assert with tolerance for floating-point operations.
- Suggested tolerance:
  - price outputs: absolute <= 0.05
  - percentages/ratios: absolute <= 0.01
  - portfolio metrics: absolute <= 0.1

## Vectors to include

## 1) Black-Scholes and Greeks
Input:
- S=20000, K=20000, T=30/365, r=0.07, sigma=0.16
- CE and PE

Assertions:
- CE and PE > 0
- Put-call parity approx holds: CE - PE ~= S - K*exp(-rT)
- Delta CE in (0,1), Delta PE in (-1,0)
- Gamma > 0

## 2) Institutional sentiment sanity
Given deterministic synthetic futures + chain + pcr:
- generateSentiment returns non-empty factor lists
- score maps to expected label bucket
- key levels include current_price, sma_20/50/200, atr_14

## 3) Options payoff shape
For Long Call single leg:
- PnL is monotonically non-decreasing with spot
- left tail approx = -premium

For Long Put single leg:
- PnL is monotonically non-increasing with spot

## 4) Risk-reward boundaries
For Bull Call Spread:
- max loss ~= net debit
- max profit ~= spread width - net debit
- breakeven near lower strike + net debit

## 5) Backtest execution timing
Construct tiny 6-row dataset with known crossover signal point.
Assert:
- entry executes at next bar open, not same bar close
- exit executes at next bar open

## 6) Journal update rules
Create mock open trades and current prices:
- target reached -> status Closed + suggestion EXIT — Target Reached
- SL reached -> status Closed + suggestion EXIT — Stop-Loss Hit
- 70% target -> EXIT (partial/full)
- 70% SL -> REVIEW — Near Stop-Loss

## 7) Final decision non-empty outputs
Given valid inputs:
- institutional decision has entry/sl/target/margin fields
- option seller decision has strikes, credit, target/sl rules

---

## UI Contract Checklist

Each screen must provide:
- loading state
- error state
- empty-data state
- computed metrics and charts
- educational disclaimer text

Shared top-level controls:
- instrument type and symbol
- date range
- real-data toggle + file pickers/import

---

## Minimum Test File List
- core/math/OptionMathTest.kt
- domain/institutional/InstitutionalAnalyzerTest.kt
- domain/options/OptionsAnalyzerTest.kt
- domain/backtest/BacktestEngineTest.kt
- domain/finaldecision/FinalTradeDecisionEngineTest.kt
- domain/journal/TradeJournalServiceTest.kt
- data/parser/NseCsvParserTest.kt

---

## Definition of Ready-to-Ship
- All tests above pass.
- Project builds in debug and release.
- Offline workflow verified end-to-end:
  - import or synthesize data
  - analyze
  - generate decisions
  - log and update journal
  - run backtests
- Numeric parity checked against Python baseline for at least one fixed dataset.
