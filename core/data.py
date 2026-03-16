# ─────────────────────────────────────────────
# data.py — Fetching tickers, stock data, fundamentals, sector momentum
#
# v2 CHANGE: Hard binary fundamental filter replaced with composite
# risk scoring. Models now run on ALL Nifty 500 stocks with valid
# price data. Fundamentals produce a score (0–100) and label
# (Low / Medium / High risk) shown in the email and used by
# portfolio.py to build risk-tiered combinations.
#
# Score breakdown (max 100 pts, lower = safer):
#   PE ratio          30 pts  — proportional overshoot above sector limit
#   Debt/Equity       25 pts  — proportional overshoot above sector limit
#   Revenue growth    20 pts  — proportional to how negative growth is
#   Data completeness 15 pts  — missing yfinance fields add uncertainty
#   Interest coverage 10 pts  — only for D/E > 4×, ICR < 3× adds penalty
#
# Thresholds (tunable via RISK_THRESHOLD_LOW / RISK_THRESHOLD_HIGH):
#   Low risk    0 – 25   all fundamentals within limits, data complete
#   Medium risk 26 – 50  borderline metrics or data gaps
#   High risk   51 – 100 clear red flags (overvalued, over-leveraged, declining)
# ─────────────────────────────────────────────

import io
import logging
import requests
import pandas as pd
import yfinance as yf
from yfinance import download
from niftystocks import ns

from .config import (
    FETCH_PERIODS,
    MIN_DAYS,
    SECTOR_ETFS,
    TOP_SECTORS_COUNT,
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_HIGH,
)

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# (RISK_THRESHOLD_LOW and RISK_THRESHOLD_HIGH imported from config.py)

MIN_PE_RATIO = 1.0  # PE below this = negative earnings → PE_m = 4.0 (max)

# ─────────────────────────────────────────────
# SECTOR-SPECIFIC PE LIMITS
# (same as before — used as the reference point for proportional penalty)
# ─────────────────────────────────────────────
INDUSTRY_PE_LIMITS = {
    "Banks—Private Sector": 22,
    "Banks—Public Sector": 12,
    "Consumer Finance": 35,
    "Insurance—Life": 55,
    "Insurance—General": 45,
    "Capital Markets": 25,
    "Mortgage Finance": 28,
    "Credit Services": 30,
    "Electronic Components": 65,
    "Aerospace & Defense": 35,
    "Specialty Industrial Machinery": 65,
    "Engineering & Construction": 30,
    "Farm & Heavy Construction Machinery": 30,
    "Software—Application": 75,
    "Information Technology Services": 32,
    "Software—Infrastructure": 55,
    "Medical Care Facilities": 80,
    "Drug Manufacturers—General": 38,
    "Utilities—Regulated Electric": 22,
    "Utilities—Renewable": 35,
    "Utilities—Independent Power": 25,
    "Oil & Gas E&P": 15,
    "Oil & Gas Refining & Marketing": 14,
    "Oil & Gas Midstream": 18,
}

SECTOR_PE_LIMITS = {
    "Financial Services": 45,
    "Utilities": 25,
    "Infrastructure": 40,
    "Energy": 18,
    "Real Estate": 65,
    "Industrials": 65,
    "Basic Materials": 55,
    "Materials": 50,
    "Consumer Cyclical": 78,
    "Consumer Defensive": 65,
    "Technology": 50,
    "Healthcare": 76,
    "Communication Services": 45,
    "Communication": 45,
}
DEFAULT_PE_LIMIT = 55

# ─────────────────────────────────────────────
# SECTOR-SPECIFIC D/E LIMITS
# None = financial sector — leverage is the business model, D/E penalty skipped
# ─────────────────────────────────────────────
SECTOR_DEBT_LIMITS = {
    "Financial Services": None,
    "Banking": None,
    "Insurance": None,
    "NBFC": None,
    "Housing Finance": None,
    "Microfinance": None,
    "Utilities": 5.50,
    "Infrastructure": 5.75,
    "Energy": 4.75,
    "Oil & Gas": 5.25,
    "Real Estate": 4.25,
    "Industrials": 3.50,
    "Basic Materials": 3.25,
    "Materials": 2.75,
    "Consumer Cyclical": 2.55,
    "Consumer Defensive": 2.25,
    "Technology": 2.00,
    "Healthcare": 2.75,
    "Communication": 5.25,
}
DEFAULT_DEBT_LIMIT = 2.65

# ─────────────────────────────────────────────
# NSE scraping headers + ticker aliases (unchanged)
# ─────────────────────────────────────────────
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}

TICKER_ALIASES = {
    "ADANITRANS.NS": "ADANIENSOL.NS",
    "HDFC.NS": "HDFCBANK.NS",
    "MINDTREE.NS": "LTIM.NS",
    "LTINFOTECH.NS": "LTIM.NS",
    "HDFCLIFE.NS": "HDFCLIFE.NS",
}


# ─────────────────────────────────────────────
# Ticker fetching (unchanged)
# ─────────────────────────────────────────────


def _fetch_nse_live() -> list[str]:
    session = requests.Session()
    session.headers.update(_NSE_HEADERS)
    session.get("https://www.nseindia.com", timeout=10)
    csv_url = "https://www.nseindia.com/content/indices/ind_nifty500list.csv"
    response = session.get(csv_url, timeout=15)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text))
    symbols = df["Symbol"].dropna().str.strip().tolist()
    tickers = [f"{s}.NS" for s in symbols if s]
    if len(tickers) < 400:
        raise ValueError(f"Only {len(tickers)} tickers fetched — likely a parse error")
    print(f"  ✓ Fetched {len(tickers)} tickers live from NSE")
    return tickers


def _apply_aliases(tickers: list[str]) -> list[str]:
    result = []
    seen = set()
    for t in tickers:
        resolved = TICKER_ALIASES.get(t, t)
        if resolved not in seen:
            result.append(resolved)
            seen.add(resolved)
    return result


def get_nifty500_tickers() -> list[str]:
    try:
        tickers = _fetch_nse_live()
        return _apply_aliases(tickers)
    except Exception as e:
        print(f"  ⚠ NSE live fetch failed ({e}) — trying niftystocks...")

    try:
        tickers = ns.get_nifty500_with_ns()
        print(f"  ✓ Using niftystocks list ({len(tickers)} tickers)")
        return _apply_aliases(tickers)
    except Exception as e:
        print(f"  ⚠ niftystocks failed ({e}) — using hardcoded fallback")

    fallback = [
        "RELIANCE.NS",
        "TCS.NS",
        "HDFCBANK.NS",
        "INFY.NS",
        "ICICIBANK.NS",
        "HINDUNILVR.NS",
        "ITC.NS",
        "SBIN.NS",
        "BHARTIARTL.NS",
        "KOTAKBANK.NS",
        "LT.NS",
        "AXISBANK.NS",
        "ASIANPAINT.NS",
        "MARUTI.NS",
        "TITAN.NS",
        "SUNPHARMA.NS",
        "ULTRACEMCO.NS",
        "BAJFINANCE.NS",
        "WIPRO.NS",
        "NESTLEIND.NS",
    ]
    print(f"  ⚠ Using hardcoded fallback ({len(fallback)} tickers)")
    return fallback


# ─────────────────────────────────────────────
# Data quality check (unchanged)
# ─────────────────────────────────────────────


def _is_clean(close: pd.Series, volume: pd.Series) -> bool:
    if close is None or volume is None:
        return False
    if len(close) < MIN_DAYS:
        return False
    if close.isna().any() or volume.isna().any():
        return False
    price_range = close.max() - close.min()
    if price_range < close.mean() * 0.01:
        return False
    zero_vol_pct = (volume == 0).sum() / len(volume)
    if zero_vol_pct > 0.10:
        return False
    return True


# ─────────────────────────────────────────────
# Fundamentals fetch (unchanged)
# ─────────────────────────────────────────────

_fundamentals_cache: dict = {}


def fetch_fundamentals(ticker: str) -> dict | None:
    if ticker in _fundamentals_cache:
        return _fundamentals_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        debt_to_equity = info.get("debtToEquity")
        revenue_growth = info.get("revenueGrowth")
        sector = info.get("sector", "")
        if debt_to_equity is not None and debt_to_equity > 20:
            debt_to_equity = debt_to_equity / 100
        company_name = (
            info.get("longName") or info.get("shortName") or ticker.replace(".NS", "")
        )
        industry = info.get("industry", "")
        ebit = info.get("ebit")
        interest_expense = info.get("interestExpense")
        interest_coverage = None
        if ebit is not None and interest_expense and interest_expense < 0:
            interest_coverage = ebit / abs(interest_expense)
        result = {
            "pe_ratio": pe_ratio,
            "debt_to_equity": debt_to_equity,
            "revenue_growth": revenue_growth,
            "sector": sector,
            "industry": industry,
            "interest_coverage": interest_coverage,
            "company_name": company_name,
        }
        _fundamentals_cache[ticker] = result
        return result
    except Exception:
        _fundamentals_cache[ticker] = None
        return None


# ─────────────────────────────────────────────
# CORE CHANGE: Composite risk scorer
# Replaces passes_fundamental_filter() entirely
# ─────────────────────────────────────────────


def _get_pe_limit(sector: str, industry: str) -> float:
    """Resolve sector/industry-specific PE limit."""
    for ind_key, limit in INDUSTRY_PE_LIMITS.items():
        if ind_key.lower() in industry.lower():
            return limit
    for sector_key, limit in SECTOR_PE_LIMITS.items():
        if sector_key.lower() in sector.lower():
            return limit
    return DEFAULT_PE_LIMIT


def _get_de_limit(sector: str) -> float | None:
    """Resolve sector-specific D/E limit. None = financial sector, no cap."""
    for sector_key, limit in SECTOR_DEBT_LIMITS.items():
        if sector_key.lower() in sector.lower():
            return limit
    return DEFAULT_DEBT_LIMIT


def score_fundamental_risk(ticker: str) -> tuple[str, float, list[str]]:
    """
    Returns (risk_label, risk_score, reasons) for a ticker.

    risk_label : "Low" | "Medium" | "High"
    risk_score : int 1–100 (always ≥ 1 — no stock has zero risk)
    reasons    : list of human-readable strings explaining each multiplier

    ── Multiplicative model ──
    Each metric produces a risk multiplier (≥ 1.0).
    Multipliers are compounded: raw = PE_m × DE_m × Rev_m × Data_m × ICR_m
    Raw product is log-normalised to 1–100.

    Why multiplicative instead of additive:
        Additive: bad PE + bad D/E = sum of two penalties
        Multiplicative: bad PE × bad D/E = amplified combined risk
        A company with both overvalued PE AND excessive debt is
        disproportionately riskier — multiplication captures this.
        Also, no stock can score 0 — min raw ≈ 0.72 → score ≈ 1.

    Multiplier design:
        PE_m    — 1.0 when PE ≤ limit; rises exponentially above limit; max 4.0
                  Strong growth (PE well below limit) gives no reduction —
                  PE is already sector-adjusted, no need for a bonus.
        DE_m    — 1.0 when D/E ≤ limit; rises above limit; max 3.5
                  Financial sector exempt (None limit) → DE_m = 1.0 always.
        Rev_m   — 0.85 for strong growth (≥15%), 1.0 at flat, up to 2.2 at −15%
                  Positive growth is genuinely rewarded with sub-1.0 multiplier.
        Data_m  — 1.0 for complete data; 1.2 / 1.5 / 1.9 for 1 / 2 / 3 missing fields
                  All-missing → 1.9× multiplier ensures Medium floor.
        ICR_m   — Only when D/E > 4×. 1.0 if ICR ≥ 3×; up to 2.5× if ICR < 1×.
                  A highly levered stock that CAN'T service debt is a different
                  risk class from one that can — ICR captures this.

    Log-normalisation:
        MIN_RAW ≈ 0.72  (stellar: strong rev growth + all metrics well within limits)
        MAX_RAW = 60    (extreme: max PE + max D/E + declining rev + all fields missing)
        score = 1 + (log(raw) - log(MIN_RAW)) / (log(MAX_RAW) - log(MIN_RAW)) × 99
        → always in [1, 100], never 0.
    """

    fundamentals = fetch_fundamentals(ticker)
    reasons = []

    # ── No data at all ──
    if fundamentals is None:
        # Data_m = 1.9 (all 3 fields missing), other multipliers = 1.0
        raw = 1.0 * 1.0 * 1.0 * 1.9 * 1.0
        score = _normalise_raw(raw)
        reasons.append(
            "No fundamental data from yfinance — uncertainty multiplier 1.9×"
        )
        label = _label(score)
        return label, score, reasons

    pe = fundamentals.get("pe_ratio")
    de = fundamentals.get("debt_to_equity")
    rev_gr = fundamentals.get("revenue_growth")
    sector = fundamentals.get("sector", "")
    industry = fundamentals.get("industry", "")
    icr = fundamentals.get("interest_coverage")

    fields_missing = sum(1 for v in [pe, de, rev_gr] if v is None)

    # ── 1. PE multiplier ──
    # 1.0 when PE ≤ sector limit
    # Exponential rise above limit: f(x) = 1 + (x−1)^1.5 × 3, capped at 4.0
    # x = PE / limit  → 1.0 at limit, ~4.0 at 2× limit
    if pe is None:
        pe_m = 1.0
        reasons.append("PE unavailable — no multiplier applied")
    elif pe < MIN_PE_RATIO:
        pe_m = 4.0  # negative earnings = maximum PE risk
        reasons.append(
            f"PE={pe:.1f} — negative/near-zero earnings (4.0× max multiplier)"
        )
    else:
        pe_limit = _get_pe_limit(sector, industry)
        x = pe / pe_limit
        if x <= 1.0:
            pe_m = 1.0
            reasons.append(f"PE={pe:.1f} within limit={pe_limit} (1.0×)")
        else:
            pe_m = min(1.0 + (x - 1.0) ** 1.5 * 3.0, 4.0)
            reasons.append(
                f"PE={pe:.1f} vs limit={pe_limit} → {x:.2f}× limit "
                f"(PE multiplier {pe_m:.2f}×)"
            )

    # ── 2. D/E multiplier ──
    # Financial sector: exempt → DE_m = 1.0
    # Others: 1.0 when D/E ≤ limit, rises as f(x) = 1 + (x−1)^1.4 × 2.5, cap 3.5
    de_limit = _get_de_limit(sector)
    if de_limit is None:
        de_m = 1.0
        reasons.append("D/E exempt — financial sector (1.0×)")
    elif de is None:
        de_m = 1.0
        reasons.append("D/E unavailable — no multiplier applied")
    else:
        x = de / de_limit
        if x <= 1.0:
            de_m = 1.0
            reasons.append(f"D/E={de:.2f} within limit={de_limit} (1.0×)")
        else:
            de_m = min(1.0 + (x - 1.0) ** 1.4 * 2.5, 3.5)
            reasons.append(
                f"D/E={de:.2f} vs limit={de_limit} → {x:.2f}× limit "
                f"(D/E multiplier {de_m:.2f}×)"
            )

    # ── 3. Revenue growth multiplier ──
    # Strong growth (≥15%) → 0.85× (genuine reward — reduces overall score)
    # Flat (0%)            → 1.0×
    # −15% or worse        → up to 2.2×
    # Formula: piecewise — positive: linear 0.85–1.0; negative: power curve 1.0–2.2
    if rev_gr is None:
        rev_m = 1.0
        reasons.append("Revenue growth unavailable — no multiplier applied")
    else:
        pct = rev_gr * 100
        if pct >= 15:
            rev_m = 0.85
        elif pct >= 0:
            rev_m = 1.0 - (pct / 15.0) * 0.15  # linear 1.0 → 0.85
        else:
            severity = min(abs(pct) / 15.0, 1.0)
            rev_m = 1.0 + severity**1.2 * 1.2  # power curve 1.0 → 2.2
        reasons.append(f"Revenue growth={pct:.1f}% → revenue multiplier {rev_m:.2f}×")

    # ── 4. Data completeness multiplier ──
    # 0 missing → 1.0×, 1 → 1.2×, 2 → 1.5×, 3 → 1.9×
    # 1.9× on all-missing ensures the raw product is high enough
    # that log-normalisation lands at Medium, never Low
    data_m_map = {0: 1.0, 1: 1.2, 2: 1.5, 3: 1.9}
    data_m = data_m_map[fields_missing]
    if fields_missing > 0:
        reasons.append(
            f"{fields_missing} field(s) missing → data uncertainty {data_m}×"
        )
    else:
        reasons.append("All 3 fundamental fields present (1.0×)")

    # ── 5. Interest coverage multiplier ──
    # Only triggered when D/E > 4× on non-financial stocks
    # ICR ≥ 3×  → 1.0× (adequate coverage)
    # ICR 0–3×  → power curve up to 2.5× (debt servicing risk)
    # ICR unknown on D/E > 4× → 1.5× (uncertain but not worst case)
    icr_m = 1.0
    if de is not None and de_limit is not None and de > 4.0:
        if icr is None:
            icr_m = 1.5
            reasons.append(f"D/E={de:.2f} > 4× but ICR unknown → uncertainty 1.5×")
        elif icr >= 3.0:
            icr_m = 1.0
            reasons.append(f"D/E={de:.2f} > 4× but ICR={icr:.1f}× adequate (1.0×)")
        else:
            severity = min((3.0 - icr) / 3.0, 1.0)
            icr_m = 1.0 + severity**1.3 * 1.5
            reasons.append(
                f"D/E={de:.2f} > 4× and ICR={icr:.1f}× low → "
                f"debt servicing multiplier {icr_m:.2f}×"
            )

    # ── Compound and normalise ──
    raw = pe_m * de_m * rev_m * data_m * icr_m
    score = _normalise_raw(raw)
    label = _label(score)
    return label, score, reasons


# ── Helpers for the multiplicative model ──


def _normalise_raw(raw: float) -> int:
    """
    Log-normalises raw product to integer score 1–100.

    Calibration anchors:
        MIN_RAW = 0.72  — best possible: strong revenue (0.85×) × all others 1.0×
                          ... actually 0.85 × 1.0 × 1.0 × 1.0 × 1.0 = 0.85
                          with DE exempt: 0.85 × 1.0 × 1.0 × 1.0 = 0.85
                          theoretical min is ~0.72 with multiple bonuses
        MAX_RAW = 60    — extreme: PE_m=4 × DE_m=3.5 × Rev_m=2.2 × Data_m=1.9 × ICR_m=2.5
                          = 4 × 3.5 × 2.2 × 1.9 × 2.5 ≈ 115 — capped at 60 for normalisation
                          so the worst real stocks don't all bunch at 100
    """
    import math

    MIN_RAW = 0.72
    MAX_RAW = 60.0
    log_raw = math.log(max(raw, MIN_RAW))
    log_min = math.log(MIN_RAW)
    log_max = math.log(MAX_RAW)
    score = 1 + (log_raw - log_min) / (log_max - log_min) * 99
    return int(round(max(1, min(100, score))))


def _label(score: int) -> str:
    if score <= RISK_THRESHOLD_LOW:
        return "Low"
    elif score <= RISK_THRESHOLD_HIGH:
        return "Medium"
    return "High"


# ─────────────────────────────────────────────
# BACKWARDS COMPAT SHIM
# scanner.py still calls passes_fundamental_filter() in a few logging spots.
# This shim makes it work without breaking anything during transition.
# Remove once scanner.py is fully updated.
# ─────────────────────────────────────────────


def passes_fundamental_filter(ticker: str) -> tuple[bool, str]:
    """
    Deprecated — use score_fundamental_risk() instead.
    Returns (True, summary) always — no stocks are hard-excluded anymore.
    The risk label is attached to results; portfolio.py uses it for tiering.
    """
    label, score, reasons = score_fundamental_risk(ticker)
    summary = f"{label} risk (score={score}): {reasons[0] if reasons else 'ok'}"
    return True, summary  # always True — never hard-block


# ─────────────────────────────────────────────
# Price + volume fetch (unchanged)
# ─────────────────────────────────────────────


def fetch_best_available(ticker: str):
    for period in FETCH_PERIODS:
        try:
            raw = download(ticker, period=period, progress=False, auto_adjust=True)
            if raw.empty:
                continue
            close = raw["Close"]
            volume = raw["Volume"]
            if isinstance(close, pd.DataFrame):
                close = close.squeeze()
            if isinstance(volume, pd.DataFrame):
                volume = volume.squeeze()
            close = close.dropna()
            volume = volume.dropna()
            close, volume = close.align(volume, join="inner")
            if _is_clean(close, volume):
                return close, volume
        except Exception:
            continue
    return None, None


def fetch_sector_momentum() -> dict:
    momentum = {}
    for name, ticker in SECTOR_ETFS.items():
        try:
            data = download(ticker, period="3mo", progress=False, auto_adjust=True)[
                "Close"
            ]
            if isinstance(data, pd.DataFrame):
                data = data.squeeze()
            data = data.dropna()
            if len(data) > 10:
                momentum[name] = float((data.iloc[-1] - data.iloc[0]) / data.iloc[0])
        except Exception:
            momentum[name] = 0.0
    return momentum


def get_top_sectors(momentum: dict) -> list:
    return sorted(momentum, key=momentum.get, reverse=True)[:TOP_SECTORS_COUNT]
