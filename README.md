# Nifty 500 — Prescriptive Stock Analyzer

An automated stock screening and prediction pipeline for NSE Nifty 500 stocks. Uses a four-model ensemble to identify high-potential LTCG opportunities, predict near-term entry points, and track prediction accuracy over time.

> **Disclaimer:** This tool is for research and decision-support purposes only. It does not constitute financial advice. Always conduct your own due diligence and consult a SEBI-registered advisor before investing.

---

## What it does

- Scans all Nifty 500 stocks daily across 9 scheduled runs (9:00 AM – 3:00 PM IST)
- Forecasts price paths 24 months forward using a weighted ensemble of four models
- Identifies the best near-term entry date (predicted price trough within 30 days)
- Calculates after-tax ROI including LTCG (12.5%), STT, cess, and ICICI Direct brokerage
- Scores fundamental risk (Low / Medium / High) using a multiplicative model across PE, D/E, revenue growth, and data completeness
- Builds 12 portfolio combinations from ₹1,00,000/month budget across different strategies
- Sends email reports on the first trading day of each month and intraday alerts when stock prices dip ≥1.5% from the morning baseline
- Tracks prediction accuracy daily and reports MAE, bias, and convergence signals per stock

---

## Model architecture

### Ensemble (four models, weights sum to 1.0)

| Model | Weight | Role |
|---|---|---|
| Prophet | 37.0% | Long-term trend + seasonality + India macro regressor |
| Holt Damped Trend | 27.5% | Realistic long-horizon anchor with trend dampening (φ=0.88) |
| XGBoost | 18.0% | Short-term momentum (reliable up to 63 days, then blends into Holt) |
| VPR (Volatility Penalised Return) | 17.5% | Conservatism anchor — penalises high-volatility stocks |

### Key design decisions

- **Forecast horizon:** 24 months (504 trading days). All picks target the 12–24 month window so every exit qualifies for LTCG.
- **Mean reversion:** Prophet applies a progressive reversion penalty pulling forecasts toward historical mean price — prevents forever-trending outputs.
- **XGBoost handoff:** XGBoost signal dominates days 1–63, then linearly blends into Holt by day 126. Beyond day 126 it's pure Holt — honest about the limits of tree models on long horizons.
- **Return caps:** MAX 42%/year, MIN −17.5%/year applied to all models before ensemble.
- **Slippage buffer:** 2% added to entry price — ROI shown is already conservative.

---

## Fundamental risk scoring

Replaces the old binary pass/fail filter. Every stock that has valid price data runs through the full model ensemble. Fundamentals produce a risk score (1–100) assigned **after** forecasting.

**Multiplicative model:** `score = normalise(PE_m × DE_m × Rev_m × Data_m × ICR_m)`

Each multiplier is ≥ 1.0 (violations compound, good metrics reduce score):

| Component | Clean | Worst case |
|---|---|---|
| PE vs sector limit | 1.0× | 4.0× (negative earnings) |
| D/E vs sector limit | 1.0× | 3.5× |
| Revenue growth | 0.85× (≥15% growth) | 2.2× (−15% decline) |
| Data completeness | 1.0× (all present) | 1.9× (all missing) |
| Interest coverage | 1.0× (ICR ≥ 3×, D/E > 4×) | 2.5× (ICR < 1×) |

**Thresholds:** Low ≤ 33 · Medium 34–60 · High > 60

Risk label is shown on every stock in every email. No stocks are excluded based on risk — it is information for you to act on, not a gate.

---

## Scanning pipeline

```
Nifty 500 (~500 tickers)
    ↓ price range ₹100–₹15,000
    ↓ data quality (≥60 trading days, no gaps)
    ↓ liquidity ≥ ₹2Cr/day turnover
    ↓ momentum: 20d MA ≥ 90% of all-time average
    ↓ ensemble forecast (Prophet + XGBoost + Holt + VPR)
    ↓ after-tax ROI ≥ 10%
    ↓ confident window ≥ 30 days (Prophet interval width check)
    → Full pool (~80–150 stocks) logged for accuracy tracking
    → Top 10 per price band shown in email (13 bands)
    → 12 portfolio combinations built from full pool
```

---

## Portfolio combinations

All 12 combinations see all stocks — risk label is a column, not a filter. Strategies differ by timing, cap size, and ROI target:

1. Best Overall (composite score)
2. Max After-Tax Return
3. Diwali & Year-End Rally (Nov/Dec peaks)
4. Balanced Cap Mix (small + mid + large)
5. High Liquidity
6. Conservative Steady (15–35% ROI range)
7. Mid-2027 Exit (Jul–Oct 2027)
8. Patient Hold (2028 exits)
9. Small Cap Focus
10. Large Cap Focus
11. Low Risk Preference (same pool, Low-risk stocks ranked first)
12. High ROI 20%+ (explicitly surfaces high-return / high-risk picks)

---

## Accuracy tracking

Every scan logs `Predicted_Best_Buy_Date` and `Predicted_Best_Buy_Price` per stock to `prediction_log.csv`. When a predicted date falls within the current check window, the tracker:

1. Fetches the **minimum actual close in a ±2 trading day window** around the predicted date (fair comparison — the model predicts a price level, not a pinpoint date)
2. Computes error %, direction (OVER/UNDER), within-3% threshold
3. Builds convergence score: how many intraday runs agreed on the same predicted date
4. Sends accuracy email with MAE, bias, hit rate, and per-stock convergence signal

**Convergence signal interpretation:**
- 🟢 STRONG — ≥75% of runs agree + ≥70% historical accuracy → high confidence buy
- 🟡 MODERATE — ≥50% runs agree + ≥50% accuracy → verify on news/charts
- 🔴 WEAK — low agreement → model uncertain, research before acting
- 🆕 NEW — fewer than 3 data points, insufficient history

**First-run accuracy (18 Mar 2026, 39 unique stocks):**
- MAE: 2.85% · Bias: +2.67% · Within 3%: 69% · Within 5%: 79%
- Bias is a measurement artifact (exact-date close vs predicted trough) — corrected to ±2 day window from v2 onwards, expected MAE ~1.5%, bias ~0%

---

## Email alerts

| Email | When | Contents |
|---|---|---|
| Band picks (1/2) | First NSE trading day of month | Top 10 stocks per price band with risk badge, ROI, timing |
| Portfolio combos (2/2) | Same day | 12 combinations with allocation, net profit, risk breakdown |
| Intraday dip alert | Any run where stock price dropped ≥1.5% vs morning | Stocks with better entry, best combo at current prices |
| Accuracy report | 15:00 IST run only (post-market) | MAE, bias, hit rate, convergence signal per stock |

---

## Workflow schedule

Runs Mon–Fri via GitHub Actions cron:

| Time (IST) | UTC cron | Type |
|---|---|---|
| 09:00 | `30 3 * * 1-5` | Daily baseline (full email on 1st trading day of month) |
| 09:45 | `15 4 * * 1-5` | Intraday — alert if improved |
| 10:30 | `0 5 * * 1-5` | Intraday |
| 11:15 | `45 5 * * 1-5` | Intraday |
| 12:00 | `30 6 * * 1-5` | Intraday |
| 12:45 | `15 7 * * 1-5` | Intraday |
| 13:30 | `0 8 * * 1-5` | Intraday |
| 14:15 | `45 8 * * 1-5` | Intraday |
| 15:00 | `30 9 * * 1-5` | Intraday + EOD accuracy check |

`main.py` checks the NSE calendar before running — exits cleanly on holidays.

---

## Project structure

```
Stock_Analyzer/
├── main.py                        # Entry point — --daily / --intraday / --force / --eod
├── core/
│   ├── config.py                  # All tunable parameters
│   ├── data.py                    # Ticker fetching, fundamentals, risk scoring
│   ├── scanner.py                 # Full scan loop, ROI calculation
│   ├── ensemble.py                # Model orchestration
│   ├── features.py                # Technical indicators for XGBoost
│   └── portfolio.py               # Portfolio combination builder
├── models/
│   ├── prophet_model.py           # Prophet + mean reversion
│   ├── xgboost_model.py           # XGBoost + Holt handoff
│   ├── holt_model.py              # Holt damped trend (φ=0.88)
│   └── vpr_model.py               # Volatility penalised return
├── helpers/
│   ├── alerts.py                  # Email builder and sender
│   ├── consolidate.py             # Intraday comparison and dip alerts
│   └── accuracy_tracker.py        # Prediction logging and validation
├── .github/
│   └── workflows/
│       └── nse_stock_analysis.yml # GitHub Actions schedule
└── pyproject.toml
```

---

## Configuration reference (`core/config.py`)

| Parameter | Value | Notes |
|---|---|---|
| `LOWER_LIMIT` | ₹100 | Min stock price |
| `UPPER_LIMIT` | ₹15,000 | Max stock price |
| `MIN_AVG_DAILY_TURNOVER` | ₹2Cr | Liquidity floor |
| `MOMENTUM_TOLERANCE` | 0.90 | 20d MA / all-time avg floor |
| `MIN_WEIGHTED_ROI` | 10% | After-tax ROI threshold |
| `MAX_ANNUAL_RETURN` | 42% | Model forecast cap |
| `FORECAST_HORIZON` | 504 days | ~24 months |
| `TARGET_WINDOW_START` | 252 days | LTCG threshold (12 months) |
| `BEST_BUY_LOOKFORWARD_DAYS` | 30 | Near-term trough search window |
| `TOP_N_PER_BAND` | 10 | Max picks shown per price band |
| `MAX_SECTOR_PER_BAND` | 3 | Sector diversity cap per band |
| `RISK_THRESHOLD_LOW` | 33 | Score ≤ 33 → Low risk |
| `RISK_THRESHOLD_HIGH` | 60 | Score > 60 → High risk |
| `MONTHLY_BUDGET` | ₹1,00,000 | Portfolio allocation budget |

---

## Setup

### Prerequisites
- Python 3.12+
- `uv` (recommended)

### Installation

```bash
git clone https://github.com/KaushikM211/Stock_Analyzer.git
cd Stock_Analyzer
uv sync
```

### Environment variables (GitHub Secrets)

```
GMAIL_SENDER        sender Gmail address
GMAIL_PASSWORD      Gmail App Password (not account password)
GMAIL_RECIPIENT     recipient email address
GITHUB_TOKEN        auto-provided by Actions — no setup needed
```

### Manual runs

```bash
uv run python main.py --force       # Full scan + email (bypasses calendar check)
uv run python main.py --daily       # First trading day of month → full email, else baseline
uv run python main.py --intraday "Live 10:30 IST"   # Intraday comparison run
uv run python main.py --eod         # Post-market accuracy check (run after 3:30 PM IST)
uv run python main.py --accuracy    # Manual accuracy check (any time)
uv run python main.py --test-email  # Send test email with dummy data
```

---

## Dependencies

| Category | Packages |
|---|---|
| Data | `nsepython`, `yfinance`, `niftystocks` |
| Forecasting | `prophet`, `cmdstanpy` |
| ML | `xgboost`, `scikit-learn` |
| Stats | `statsmodels` |
| Utilities | `pandas`, `numpy`, `tqdm`, `pandas-market-calendars` |
| Environment | `python-dotenv` |