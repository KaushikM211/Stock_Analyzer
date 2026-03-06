# ─────────────────────────────────────────────
# data.py — Fetching tickers, stock data, fundamentals, sector momentum
# ─────────────────────────────────────────────

import pandas as pd
import yfinance as yf
from yfinance import download
from niftystocks import ns

from config import FETCH_PERIODS, MIN_DAYS, SECTOR_ETFS, TOP_SECTORS_COUNT

# ─────────────────────────────────────────────
# FUNDAMENTAL FILTER THRESHOLDS
# These are conservative thresholds for NSE large/mid caps
# ─────────────────────────────────────────────
MAX_PE_RATIO = 80.0  # Exclude extremely overvalued stocks
MIN_PE_RATIO = 1.0  # Exclude negative earnings / shell companies
MAX_DEBT_TO_EQUITY = 2.0  # Exclude highly leveraged companies
# Exception: Banks/NBFCs (D/E naturally high)
MIN_PROMOTER_HOLDING = 25.0  # Promoter holding below 25% = low conviction
MAX_PROMOTER_PLEDGE = 50.0  # High pledge = distress risk
MIN_REVENUE_GROWTH = -0.10  # Exclude companies with >10% revenue decline

# Sectors where high D/E is normal — don't apply debt filter
HIGH_DEBT_SECTORS = {
    "Financial Services",
    "Banking",
    "Insurance",
    "NBFC",
    "Housing Finance",
    "Microfinance",
}


def get_nifty500_tickers():
    try:
        return ns.get_nifty500_with_ns()
    except Exception:
        return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]


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
    try:
        info = yf.Ticker(ticker).info

        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        debt_to_equity = info.get("debtToEquity")
        revenue_growth = info.get("revenueGrowth")
        sector = info.get("sector", "")

        # yfinance returns D/E as a percentage (e.g. 150 = 1.5x) — normalise
        if debt_to_equity is not None and debt_to_equity > 20:
            debt_to_equity = debt_to_equity / 100

        return {
            "pe_ratio": pe_ratio,
            "debt_to_equity": debt_to_equity,
            "revenue_growth": revenue_growth,
            "sector": sector,
        }

    except Exception:
        return None


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

    # ── Debt/Equity check (skip for financial sector) ──
    is_financial = any(s.lower() in sector.lower() for s in HIGH_DEBT_SECTORS)
    if de is not None and not is_financial:
        if de > MAX_DEBT_TO_EQUITY:
            return (
                False,
                f"D/E={de:.2f} — dangerously leveraged (>{MAX_DEBT_TO_EQUITY}x)",
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
