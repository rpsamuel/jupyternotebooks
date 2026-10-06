# WhaleWisdom 2.0 Architecture

## Purpose
Build a disciplined, auditable long-term stock-selection system that starts with high-conviction ideas, independently validates them, ranks them, and turns the best candidates into a diversified portfolio.

The legacy notebook remains unchanged and is treated as an experiment archive.

## Core design principle
Whale/13F ownership is an **idea and conviction signal**, not proof that a stock should be bought.

Pipeline:

```
IDEA SOURCES
   ↓
UNIVERSE + DATA VALIDATION
   ↓
FINANCIAL HEALTH GATES
   ↓
QUALITY SCORE
   ↓
VALUATION SCORE
   ↓
MOMENTUM / TREND SCORE
   ↓
WHALE / INSTITUTIONAL CONVICTION SCORE
   ↓
RISK PENALTIES
   ↓
FINAL CONVICTION SCORE
   ↓
PORTFOLIO CONSTRUCTION
   ↓
AUDITABLE REPORT
```

## 1. Idea Sources
Keep multiple sources but label every ticker with provenance.

Initial source buckets:
- Whale / 13F candidates
- Seeking Alpha / Alpha list
- Renaissance-style institutional list
- S&P 500 / Nasdaq-100 universe
- User watchlist

Do not merge these into one anonymous list. Preserve source tags so the final report can explain *why* a ticker entered the system.

## 2. Universe and Data Validation
Normalize tickers once (for example BRK.B → BRK-B for Yahoo Finance).

Reject or quarantine candidates with:
- Missing price history
- Missing or obviously stale market data
- Insufficient financial-statement history for the metric being used
- Non-operating securities when a company model is expected
- Duplicate share classes unless intentionally allowed

No silent substitution of zeros for missing fundamental data.

## 3. Financial Health Gates
These are safety gates, not ranking factors.

Use:
- Piotroski F-Score
- Altman Z-Score where applicable
- Beneish M-Score
- Debt / liquidity checks
- Positive operating cash flow
- Market-cap floor

A candidate that fails a hard risk gate can remain in the research report but should not enter the portfolio candidate set.

Suggested initial policy:
- Piotroski >= 5
- Beneish M-Score below manipulation-risk threshold when calculable
- Altman above distress zone when model is applicable
- Positive operating cash flow
- No unresolved accounting-data errors

## 4. Quality Score (0-100)
Measure the business, not the stock price.

Candidate metrics:
- ROIC
- ROE
- Operating margin / profit margin
- Free-cash-flow margin
- Revenue growth
- EPS / net-income growth
- FCF growth
- Balance-sheet strength
- Earnings consistency

Suggested weight:
- ROIC: 25%
- FCF quality/growth: 20%
- Revenue growth: 15%
- Earnings growth: 15%
- Margin quality: 10%
- ROE: 10%
- Balance-sheet quality: 5%

Use percentile ranks within the current candidate universe rather than arbitrary raw-value addition.

## 5. Valuation Score (0-100)
Ask whether a good company is available at a reasonable price.

Possible inputs:
- FCF yield
- EV/EBITDA
- Forward P/E
- PEG
- Price / FCF
- Graham Number only when it is economically meaningful
- DCF margin of safety as a secondary model

Do not let one DCF dominate the decision.

Suggested interpretation:
- 80-100: unusually attractive
- 60-79: reasonable
- 40-59: fair / neutral
- <40: expensive

## 6. Momentum / Trend Score (0-100)
Used as entry-timing confirmation, not as the fundamental thesis.

Inputs:
- 6-month relative strength vs S&P 500
- 12-month relative strength
- Price above 50DMA
- Price above 200DMA
- 50DMA > 200DMA
- MACD direction
- RSI as a bounded momentum input
- Volume confirmation where reliable

Avoid rejecting an excellent long-term company solely because RSI is high.

## 7. Whale / Institutional Conviction Score (0-100)
This replaces the static `whale_wisdom = [...]` list.

Desired future inputs:
- Number of selected funds holding the stock
- New positions this quarter
- Position increases
- Position reductions
- Portfolio weight / concentration
- Quarter-over-quarter change in institutional ownership
- Number of high-conviction managers owning it

This score should be timestamped by filing quarter because 13F data is delayed.

Until live 13F ingestion is implemented, manual Whale lists may be used only as a clearly labeled temporary source.

## 8. Risk Penalties
Apply explicit penalties after positive scores.

Examples:
- Excess leverage
- Extreme valuation
- Very high beta
- High realized volatility
- Negative FCF
- Accounting-quality warning
- Single-customer / single-product concentration where known
- Earnings-event proximity for short-term entry decisions
- Data-quality uncertainty

Risk penalties should be visible in the report.

## 9. Final Conviction Score
Initial weighting:

- Quality: 35%
- Valuation: 25%
- Whale / institutional conviction: 20%
- Momentum / trend: 15%
- Financial-health bonus: 5%
- Risk penalties: subtract after weighted score

Formula:

```
Base Score =
    0.35 * Quality
  + 0.25 * Valuation
  + 0.20 * Whale
  + 0.15 * Momentum
  + 0.05 * FinancialHealth

Final Score = Base Score - RiskPenalty
```

Score bands:
- 85+: Strong Buy Candidate
- 75-84: Buy Candidate
- 65-74: Watch / wait for price
- 50-64: Research only
- <50: Reject

These thresholds must later be validated by backtesting.

## 10. Portfolio Construction
Only stocks above a minimum conviction threshold enter portfolio construction.

Rules:
- 10-20 holdings
- Maximum position size: 10%
- Typical position: 4-8%
- Sector cap: 25%
- No position solely because an optimizer assigns it weight
- Keep cash if too few candidates pass
- Do not use leveraged ETFs in this long-term portfolio notebook

Portfolio optimization is secondary to conviction and diversification.

Recommended first implementation:
1. Rank by Final Score
2. Select top candidates subject to sector caps
3. Weight by conviction with position caps
4. Compare against equal-weight benchmark
5. Add optimizer only after the deterministic method works

## 11. Output Report
Every run should produce one final table:

| Rank | Ticker | Sources | Quality | Value | Whale | Momentum | Health | Risk Penalty | Final Score | Decision |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|

And a portfolio table:

| Ticker | Weight | Dollar Allocation | Thesis | Main Risk |
|---|---:|---:|---|---|

Also produce:
- Rejected candidates and exact rejection reason
- Data-quality warnings
- Run date
- Source filing quarter for 13F data
- Benchmark comparison

## 12. Notebook Structure
The new notebook should contain only these sections:

1. Configuration
2. Imports and secrets
3. Idea-source ingestion
4. Data normalization and validation
5. Financial data collection
6. Health gates
7. Quality / valuation / momentum / whale scoring
8. Risk penalties and final ranking
9. Portfolio construction
10. Final report and export

## What is removed from WhaleWisdom 2.0
Move these out of the main flow:
- Leveraged ETF strategy
- TQQQ / SOXL / UPRO trading signals
- Turtle trading logic
- Multiple duplicate Beneish implementations
- Multiple duplicate Black-Litterman implementations
- Old test lists with no provenance
- Arbitrary fixed dates from experiments
- Cells requiring variables created manually in an earlier Colab session
- Hard-coded credentials
- Experimental models that cannot explain how they affect the final decision

## Migration map from the legacy notebook

### Keep / refactor
- Index-universe collection
- Fundamental growth metrics
- ROE / ROIC
- Piotroski
- Beneish
- Altman
- Graham/value concepts
- DCF as secondary valuation evidence
- Relative strength
- Moving averages / MACD
- Portfolio allocation concepts

### Archive only
- Duplicate implementations
- Failed optimizer attempts
- Undefined-variable cells
- one-off test ticker cells
- leveraged ETF sections
- old static result outputs

## Security
The legacy notebook contains a hard-coded API credential. Rotate/revoke that credential and use Colab Secrets or environment variables. Do not copy it into WhaleWisdom 2.0.

## Phase plan

### Phase 1 — Clean deterministic engine
- Static/manual source lists
- Reliable Yahoo Finance collection
- Data-quality validation
- Health gates
- Four component scores
- Final ranking
- Simple capped portfolio
- CSV/XLSX output

### Phase 2 — Real Whale ingestion
- SEC 13F or licensed/API source
- Quarter-aware position history
- Fund conviction and change metrics
- Whale score

### Phase 3 — Validation
- Point-in-time backtest
- Avoid survivorship/look-ahead bias
- Compare against SPY
- Tune score weights only after out-of-sample tests

### Phase 4 — Scheduled research report
- Run weekly for market/fundamental updates
- Refresh 13F score when new filings arrive
- Store historical rankings for accountability
