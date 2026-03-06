# ─────────────────────────────────────────────
# config.py — Central configuration
# ─────────────────────────────────────────────

# Stock price filter (overall bounds)
LOWER_LIMIT = 150
UPPER_LIMIT = 6000

# Price band buckets — ₹500 windows within lower/upper limits
# Each bucket gets its own top-N picks in the final output
PRICE_BANDS = [
    (150, 500),
    (500, 1000),
    (1000, 1500),
    (1500, 2000),
    (2000, 2500),
    (2500, 3000),
    (3000, 3500),
    (3500, 4000),
    (4000, 4500),
    (4500, 5000),
    (5000, 6000),
]

# Top N picks per price band (instead of top 20 overall)
TOP_N_PER_BAND = 5

# Minimum trading days required to run any model
MIN_DAYS = 60

# Forecast horizon (trading days)
FORECAST_HORIZON = 252  # ~1 year

# Target window within forecast (months 8–12)
TARGET_WINDOW_START = 168  # trading day ~8 months
TARGET_WINDOW_END = 252  # trading day ~12 months

# ROI thresholds
MIN_WEIGHTED_ROI = 12.0  # Minimum weighted ensemble ROI to qualify

# Minimum average daily turnover to be considered liquid enough to trade
MIN_AVG_DAILY_TURNOVER = 1e7  # ₹1 Crore/day

# Ensemble model weights
MODEL_WEIGHTS = {
    "prophet": 0.40,  # Long-term trend + macro seasonality
    "xgb": 0.35,  # Near-term directional signal
    "ridge": 0.25,  # Conservative anchor — capped annualised return
}

# Per-model annualised return caps (applied inside each model)
# These are the single most important numbers for realistic output
# NSE large/mid cap realistic 1yr return range: -20% to +35%
MAX_ANNUAL_RETURN = 0.35
MIN_ANNUAL_RETURN = -0.20

# Momentum pre-filter tolerance (skip if short MA is below long MA by this %)
MOMENTUM_TOLERANCE = 0.97

# ─────────────────────────────────────────────
# MACRO SEASONALITY CALENDAR (India-specific)
# positive = historically bullish, negative = bearish
# ─────────────────────────────────────────────
MACRO_MONTH_WEIGHTS = {
    1: -0.02,  # Jan:  Historically poor — FII selling, global uncertainty
    2: 0.03,  # Feb:  Budget rally — real but often priced in advance
    3: -0.04,  # Mar:  Worst month statistically — FY end selling, tax loss booking
    4: -0.02,  # Apr:  Negative returns confirmed by NSE research
    5: -0.02,  # May:  Geopolitical risk, global "sell in May" effect
    6: -0.02,  # Jun:  One of 3 historically poorest months on NSE
    7: 0.01,  # Jul:  Monsoon sentiment, Q1 results — slight positive
    8: -0.01,  # Aug:  Geopolitical risk window, flat to negative
    9: -0.03,  # Sep:  Historically challenging — FII rebalancing, quarter end
    10: 0.01,  # Oct:  Slight dip before festive rally — not as strong as expected
    11: 0.05,  # Nov:  Strongest month on NSE — 8.55% avg, Diwali momentum
    12: 0.04,  # Dec:  Strong — 3.1% avg Nifty50, 74% of years positive
}

# ─────────────────────────────────────────────
# SECTOR ETF MAPPING (NSE sector indices)
# ─────────────────────────────────────────────
SECTOR_ETFS = {
    "NIFTYIT": "^CNXIT",
    "NIFTYBANK": "^NSEBANK",
    "NIFTYPHARMA": "^CNXPHARMA",
    "NIFTYAUTO": "^CNXAUTO",
    "NIFTYFMCG": "^CNXFMCG",
    "NIFTYMETAL": "^CNXMETAL",
    "NIFTYENERGY": "^CNXENERGY",
    "NIFTYREALTY": "^CNXREALTY",
}

# Top N sectors to report in summary
TOP_SECTORS_COUNT = 3

# Data fetch periods to try (longest first)
FETCH_PERIODS = ["2y", "1y", "6mo", "5mo", "4mo", "3mo", "2mo"]
