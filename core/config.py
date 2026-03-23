# ─────────────────────────────────────────────
# config.py — Central configuration
# ─────────────────────────────────────────────

# Stock price filter (overall bounds)
LOWER_LIMIT = 100
UPPER_LIMIT = 15000

# Max stocks from same sector per price band (Email 1)
# Raised from 2 to 3 — with 10 picks per band, allowing 3 per sector
# still gives good diversity (max 30% from one sector) while not over-constraining
MAX_SECTOR_PER_BAND = 3

# Max stocks from same sector per portfolio combination (Email 2)
MAX_SECTOR_PER_PORTFOLIO = 3

# Price band buckets — ₹500 windows within lower/upper limits
# Each bucket gets its own top-N picks in the final output
PRICE_BANDS = [
    (100, 500),
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
    (6000, 7000),
    (7000, 15000),
]

# Top N picks per price band shown in email
# Raised from 7 to 10 — 7 was discarding valid stocks from results entirely,
# meaning accuracy tracker and portfolio builder had a smaller pool than necessary
TOP_N_PER_BAND = 10

# Minimum trading days required to run any model
MIN_DAYS = 60

# ─────────────────────────────────────────────
# FORECAST HORIZON — 24 months
#
# Why 24 months (504 trading days):
#   - LTCG kicks in after 12 months — same 12.5% rate applies whether
#     you hold 13 months or 24 months — no benefit to capping at 15
#   - If model finds a natural peak at Oct 2027 (Diwali) or Dec 2027
#     that's a better exit than forcing a May 2027 sell
#   - Mean reversion penalty in Prophet ensures forecast curves over
#     naturally — it won't just trend forever to month 24
#   - Holt damped trend also decays naturally over longer horizon
#   - Beyond 24 months models are too unreliable — hard cap here
# ─────────────────────────────────────────────
FORECAST_HORIZON = 504  # ~24 months of trading days

# ─────────────────────────────────────────────
# BEST BUY DATE PREDICTION
# Trading days forward to scan for predicted price trough
# 50 days = ~10 weeks — actionable near-term entry window
# ─────────────────────────────────────────────

BEST_BUY_LOOKFORWARD_DAYS = 50

# Target window: start AFTER 12 months (LTCG threshold), no upper cap
# Let the model find the natural peak anywhere from month 12 to month 24
TARGET_WINDOW_START = 252  # trading day ~12 months (LTCG threshold)
TARGET_WINDOW_END = 504  # trading day ~24 months — full window

# ─────────────────────────────────────────────
# TAX CONSTANTS — FY 2025-26 (AY 2026-27)
# ─────────────────────────────────────────────
STCG_TAX_RATE = 0.20  # 20% on gains if held < 12 months
LTCG_TAX_RATE = 0.125  # 12.5% on gains if held > 12 months
LTCG_EXEMPTION = 125000  # ₹1.25 lakh annual exemption on LTCG
CESS_RATE = 0.04  # 4% Health & Education Cess on tax
STT_RATE = 0.001  # 0.1% Securities Transaction Tax (buy + sell)
LTCG_HOLD_DAYS = 252  # Trading days to cross 12-month LTCG threshold

# Minimum average daily turnover
# Raised from ₹1Cr to ₹2Cr — ₹1Cr is too thin for reliable LTCG exit
# on a ₹1L position. ₹2Cr/day ensures you can exit without moving the price.
MIN_AVG_DAILY_TURNOVER = 2e7  # ₹2 Crore/day

# Ensemble model weights — must sum to 1.0
# XGBoost weight reduced from 0.225 to 0.18 — XGB is only reliable for 63 days
# then blends into Holt anyway. Overweighting it on a 24-month forecast
# was giving near-term noise too much influence on the final ROI number.
# Redistributed to Prophet (+0.025) and VPR (+0.02) which are more honest
# about long-horizon uncertainty.
MODEL_WEIGHTS = {
    "prophet": 0.370,
    "xgb": 0.180,
    "holt": 0.275,
    "vpr": 0.175,
}

# Per-model annualised return caps
# Brought back from 0.50 to 0.42 — 0.50 over 24 months = 125% total cap,
# which is too permissive for mid/large caps. 0.42 (42%/yr) is exceptional
# but achievable for genuine small-cap outperformers, while keeping
# mid/large cap forecasts grounded.
MAX_ANNUAL_RETURN = 0.35
MIN_ANNUAL_RETURN = -0.175

# Momentum pre-filter tolerance
MOMENTUM_TOLERANCE = 0.90

# Minimum after-tax ROI to qualify
# Raised from 6.5% to 7.5% — 6.5% barely beats FD rates and adds noise.
# With 2% slippage already baked in, 7.5% after-tax is a meaningful hurdle.
MIN_WEIGHTED_ROI = 7.5

# ─────────────────────────────────────────────
# FUNDAMENTAL RISK SCORE THRESHOLDS
# score_fundamental_risk() produces a multiplicative 1–100 score.
#   score ≤ LOW   → "Low"    clean stocks naturally score 5–28
#   score ≤ HIGH  → "Medium" borderline or data gaps
#   score >  HIGH → "High"   PE/D/E/revenue red flags
# ─────────────────────────────────────────────
RISK_THRESHOLD_LOW = 33
RISK_THRESHOLD_HIGH = 60


# ─────────────────────────────────────────────
# MACRO SEASONALITY CALENDAR (India-specific)
# ─────────────────────────────────────────────
MACRO_MONTH_WEIGHTS = {
    1: 0.01,  # Jan:  FII selling
    2: -0.02,  # Feb:  Budget priced in
    3: -0.07,  # Mar:  FY end + active oil crisis right now
    4: -0.09,  # Apr:  Oil impact peaks, inflation data arrives
    5: -0.06,  # May:  Sustained oil pressure
    6: -0.07,  # Jun:  Slight easing expected
    7: -0.03,  # Jul:  Monsoon + Q1 results
    8: -0.02,  # Aug:  Geopolitical risk
    9: -0.05,  # Sep:  FII rebalancing + oil still elevated
    10: -0.01,  # Oct:  Dip before Diwali
    11: 0.02,  # Nov:  Diwali rally
    12: 0.05,  # Dec:  Year end rally
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

TOP_SECTORS_COUNT = 4
FETCH_PERIODS = ["3y", "2y", "1y", "6mo", "5mo", "4mo", "3mo"]
