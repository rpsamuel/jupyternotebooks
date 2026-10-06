# Stock Stars V2

## Purpose
Evaluate the combined S&P 500, Nasdaq-100, and Dow 30 universe and assign 1-5 stars based only on:

1. **Stock returns / market performance**
2. **Company strength / business quality**

No 13F, WhaleWisdom, institutional-ownership, or leveraged-ETF logic is part of this system.

## Flow

```
S&P 500 + Nasdaq-100 + Dow 30
              ↓
      Clean / deduplicate
              ↓
      Price-history metrics
              ↓
      Company-strength metrics
              ↓
       Returns Score (0-100)
              +
      Strength Score (0-100)
              ↓
        Final Score (0-100)
              ↓
          1-5 Stars
              ↓
       Ranked stock list
```

## Returns Score — 50% of Final Score

The original notebook emphasized returns, relative strength, Sharpe, volatility and beta. V2 keeps that idea but groups it clearly.

Suggested internal weights:
- 1-year return: 30%
- 3-year annualized return: 25%
- 5-year annualized return: 20%
- 12-month relative strength vs S&P 500: 10%
- Sharpe ratio: 10%
- volatility/beta risk adjustment: 5%

All components are ranked cross-sectionally across the current universe.

## Company Strength Score — 50% of Final Score

The original notebook emphasized earnings growth, revenue growth, ROE and ROIC. V2 keeps those as the heart of the business-quality score.

Suggested internal weights:
- ROIC: 25%
- ROE: 20%
- earnings growth: 20%
- revenue growth: 15%
- profit margin: 10%
- cash-flow / leverage health: 10%

Missing values remain missing; they are not silently replaced with good values.

## Final Score

```
Final Score = 0.50 * Returns Score + 0.50 * Strength Score
```

The equal split is intentional: a stock must both **perform well** and represent a **strong company**.

## Star Assignment

Stars are relative to the full combined universe:

- ★★★★★ = top 10%
- ★★★★ = next 15% (10th-25th percentile)
- ★★★ = next 25% (25th-50th percentile)
- ★★ = next 25% (50th-75th percentile)
- ★ = bottom 25%

This preserves the ranking spirit of the original notebook while making the result easier to interpret.

## Output

The final report should show:

| Rank | Ticker | Index Membership | Return Score | Strength Score | Final Score | Stars | 1Y | 3Y Ann. | 5Y Ann. | ROIC | ROE | Earnings Growth | Revenue Growth |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|

Primary selection set:
- ★★★★★ stocks
- optionally ★★★★ stocks for a broader candidate list

## Excluded from this system

- 13F holdings
- Whale / hedge-fund ownership
- Black-Litterman
- leveraged ETFs
- Turtle trading
- day trading
- old manual stock lists
- one-off experiments
- hard-coded API credentials
