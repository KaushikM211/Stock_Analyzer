# ─────────────────────────────────────────────
# data.py — Fetching tickers, stock data, fundamentals, sector momentum
# ─────────────────────────────────────────────

import io
import logging
import requests
import pandas as pd
import yfinance as yf
from yfinance import download
from niftystocks import ns

from config import FETCH_PERIODS, MIN_DAYS, SECTOR_ETFS, TOP_SECTORS_COUNT

# Suppress noisy yfinance download warnings (delisted tickers etc.)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


# ─────────────────────────────────────────────
# FUNDAMENTAL FILTER THRESHOLDS
# These are conservative thresholds for NSE large/mid caps
# ─────────────────────────────────────────────
MAX_PE_RATIO = 63.0  # Exclude extremely overvalued stocks
MIN_PE_RATIO = 1.0  # Exclude negative earnings / shell companies
MIN_PROMOTER_HOLDING = 25.0  # Promoter holding below 25% = low conviction
MAX_PROMOTER_PLEDGE = 40.0  # High pledge = distress risk
MIN_REVENUE_GROWTH = -0.10  # Exclude companies with >10% revenue decline

# Sector-specific D/E thresholds — a blanket limit is wrong
# Each sector has a different natural capital structure
# None = no cap applied (financial sector — leverage is their business model)
SECTOR_DEBT_LIMITS = {
    # Financial — leverage IS the business model, no cap
    "Financial Services": None,
    "Banking": None,
    "Insurance": None,
    "NBFC": None,
    "Housing Finance": None,
    "Microfinance": None,
    # Infrastructure & Utilities — long gestation, asset-heavy, project debt normal
    # NSE P75: Utilities~2.9, Infrastructure~4.5 — buffer above P75
    "Utilities": 5.00,
    "Infrastructure": 5.50,
    "Energy": 4.50,  # ONGC/HPCL/BPCL — P75~2.8, buffer for refiners
    "Oil & Gas": 5.00,
    # Real Estate — project financing temporarily inflates D/E
    # NSE P75: ~2.8 — DLF, Prestige, Sobha
    "Real Estate": 4.00,
    # Industrials — L&T, Ashok Leyland, BEML — P75~1.9 but outliers at 2.8
    "Industrials": 3.25,
    # Materials — cement (Ultratech~0.4) vs steel (JSW~1.9, Tata~1.8)
    # P75~1.8 — buffer for steel/aluminium cycles
    "Basic Materials": 2.50,
    "Materials": 2.50,
    # Consumer Cyclical — auto, retail, durables — P75~1.9
    # Apollo Tyres(1.8), TVS Motor(1.9), Titan(1.7) — all legitimate
    "Consumer Cyclical": 2.25,
    # Consumer Defensive — FMCG largely debt-free, P75~0.8
    # Slightly higher buffer for regional FMCG with distribution debt
    "Consumer Defensive": 1.50,
    # Technology — asset-light, TCS/Infy/Wipro near zero debt — P75~0.2
    # Generous buffer for mid-cap IT with some capex debt
    "Technology": 1.00,
    # Healthcare — pharma capex, hospital chains — P75~0.8
    # Fortis/NH hospitals go higher — buffer for hospital capex
    "Healthcare": 2.00,
    # Communication — Airtel(4.2), Indus Towers(2.1), spectrum debt
    # P75~4.5 — telecom is infra-like
    "Communication": 5.00,
}
DEFAULT_DEBT_LIMIT = 1.85  # fallback — conservative but not blocking

# NSE headers required to bypass anti-scraping block
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

# Known ticker renames/mergers — keeps scan clean when NSE list has old names
TICKER_ALIASES = {
    "ADANITRANS.NS": "ADANIENSOL.NS",  # Adani Transmission → Adani Energy Solutions
    "HDFC.NS": "HDFCBANK.NS",  # HDFC merged into HDFC Bank
    "MINDTREE.NS": "LTIM.NS",  # MindTree → LTIMindtree
    "LTINFOTECH.NS": "LTIM.NS",  # L&T Infotech → LTIMindtree
    "HDFCLIFE.NS": "HDFCLIFE.NS",  # unchanged — just a safety entry
}


def _fetch_nse_live() -> list[str]:
    """
    Fetches the latest Nifty 500 constituent list directly from NSE.

    NSE publishes a CSV at a stable URL — this is the authoritative source.
    Always reflects the latest index rebalancing (happens twice a year).

    Steps:
        1. GET nseindia.com homepage to obtain session cookies
        2. Use those cookies + headers to fetch the CSV
        3. Parse Symbol column, append .NS suffix

    Returns list of tickers like ["RELIANCE.NS", "TCS.NS", ...]
    Raises exception if either request fails — caller handles fallback.
    """
    session = requests.Session()
    session.headers.update(_NSE_HEADERS)

    # Step 1 — get cookies by hitting homepage first (NSE requires this)
    session.get("https://www.nseindia.com", timeout=10)

    # Step 2 — fetch the Nifty 500 CSV
    csv_url = "https://www.nseindia.com/content/indices/ind_nifty500list.csv"
    response = session.get(csv_url, timeout=15)
    response.raise_for_status()

    # Step 3 — parse Symbol column
    df = pd.read_csv(io.StringIO(response.text))
    symbols = df["Symbol"].dropna().str.strip().tolist()
    tickers = [f"{s}.NS" for s in symbols if s]

    if len(tickers) < 400:
        # Sanity check — Nifty 500 should have ~500 stocks
        raise ValueError(f"Only {len(tickers)} tickers fetched — likely a parse error")

    print(f"  ✓ Fetched {len(tickers)} tickers live from NSE")
    return tickers


def _apply_aliases(tickers: list[str]) -> list[str]:
    """Replace known stale/renamed tickers with their current equivalents."""
    result = []
    seen = set()
    for t in tickers:
        resolved = TICKER_ALIASES.get(t, t)
        if resolved not in seen:
            result.append(resolved)
            seen.add(resolved)
    return result


def get_nifty500_tickers() -> list[str]:
    """
    Returns the current Nifty 500 ticker list.

    Priority:
        1. Live fetch from NSE (always latest — reflects rebalancing)
        2. niftystocks static list (fallback if NSE blocks/times out)
        3. Hardcoded minimal list (last resort — GitHub Actions won't fail)

    Aliases applied in all cases to handle known mergers/renames.
    """
    # ── Try 1: Live NSE fetch ──
    try:
        tickers = _fetch_nse_live()
        return _apply_aliases(tickers)
    except Exception as e:
        print(f"  ⚠ NSE live fetch failed ({e}) — trying niftystocks...")

    # ── Try 2: niftystocks static list ──
    try:
        tickers = ns.get_nifty500_with_ns()
        print(f"  ✓ Using niftystocks list ({len(tickers)} tickers)")
        return _apply_aliases(tickers)
    except Exception as e:
        print(f"  ⚠ niftystocks failed ({e}) — using hardcoded fallback")

    # ── Try 3: Hardcoded fallback — top 20 Nifty 50 stocks ──
    # GitHub Actions won't fail completely — partial scan is better than nothing
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


def _is_clean(close: pd.Series, volume: pd.Series) -> bool:
    """
    Validates that a price/volume series is usable by all models.
    Rejects series with internal NaN gaps, flat prices, or illiquid stocks.
    """
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


def fetch_fundamentals(ticker: str) -> dict | None:
    """
    Fetches fundamental data via yfinance for a single ticker.

    Returns a dict with:
        pe_ratio         — trailing PE ratio
        debt_to_equity   — total debt / total equity
        promoter_holding — % held by promoters (India specific)
        revenue_growth   — YoY revenue growth
        sector           — sector string for D/E filter exception

    Returns None if fundamental data is unavailable or stock fails filters.

    Why each metric matters for real money:
        PE ratio        — overpaying for earnings is the #1 mistake retail investors make
        Debt/Equity     — high debt kills companies in rate hike cycles (2022 lesson)
        Promoter holding— promoters selling = insiders don't believe in the stock
        Revenue growth  — a stock can have great momentum but shrinking business
    """
    # Return cached result if already fetched this run
    if ticker in _fundamentals_cache:
        return _fundamentals_cache[ticker]

    try:
        info = yf.Ticker(ticker).info

        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        debt_to_equity = info.get("debtToEquity")
        revenue_growth = info.get("revenueGrowth")
        sector = info.get("sector", "")

        # yfinance returns D/E as a percentage (e.g. 150 = 1.5x) — normalise
        if debt_to_equity is not None and debt_to_equity > 20:
            debt_to_equity = debt_to_equity / 100

        # Full company name for display in results and email
        company_name = (
            info.get("longName") or info.get("shortName") or ticker.replace(".NS", "")
        )

        result = {
            "pe_ratio": pe_ratio,
            "debt_to_equity": debt_to_equity,
            "revenue_growth": revenue_growth,
            "sector": sector,
            "company_name": company_name,
        }
        _fundamentals_cache[ticker] = result
        return result

    except Exception:
        _fundamentals_cache[ticker] = None
        return None


# Simple in-memory cache — avoids fetching fundamentals twice per stock
# (once in passes_fundamental_filter, once to get company_name/sector)
_fundamentals_cache: dict = {}


def passes_fundamental_filter(ticker: str) -> tuple[bool, str]:
    """
    Returns (True, "") if stock passes all fundamental checks.
    Returns (False, reason) if it fails — reason logged for transparency.

    Checks:
        1. PE ratio — not astronomically overvalued
        2. Debt/Equity — not dangerously leveraged (except financial sector)
        3. Revenue growth — business not in structural decline

    Promoter holding is not available via yfinance for NSE —
    would need NSE API or screener.in scraping. Skipped for now.
    """
    fundamentals = fetch_fundamentals(ticker)

    if fundamentals is None:
        # If we can't fetch fundamentals, let the stock through
        # Better to include uncertain than exclude valid stocks
        return True, ""

    pe = fundamentals["pe_ratio"]
    de = fundamentals["debt_to_equity"]
    rev_gr = fundamentals["revenue_growth"]
    sector = fundamentals["sector"]

    # ── PE ratio check ──
    if pe is not None:
        if pe < MIN_PE_RATIO:
            return False, f"PE={pe:.1f} — negative or near-zero earnings"
        if pe > MAX_PE_RATIO:
            return False, f"PE={pe:.1f} — extremely overvalued (>{MAX_PE_RATIO}x)"

    # ── Debt/Equity check — sector-specific limit ──
    # Look up this sector's D/E limit; None means no cap (financial sector)
    de_limit = DEFAULT_DEBT_LIMIT
    for sector_key, limit in SECTOR_DEBT_LIMITS.items():
        if sector_key.lower() in sector.lower():
            de_limit = limit
            break
    if de is not None and de_limit is not None:
        if de > de_limit:
            return (
                False,
                f"D/E={de:.2f} — too high for {sector} sector (limit={de_limit}x)",
            )

    # ── Revenue growth check ──
    if rev_gr is not None:
        if rev_gr < MIN_REVENUE_GROWTH:
            return False, f"Revenue growth={rev_gr * 100:.1f}% — business declining"

    return True, ""


def fetch_best_available(ticker: str):
    """
    Try progressively shorter periods and return the longest clean dataset.
    Returns (close, volume) or (None, None).
    """
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
