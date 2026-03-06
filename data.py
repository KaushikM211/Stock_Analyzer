# ─────────────────────────────────────────────
# data.py — Fetching tickers, stock data, sector momentum
# ─────────────────────────────────────────────

import pandas as pd
from yfinance import download
from niftystocks import ns

from config import FETCH_PERIODS, MIN_DAYS, SECTOR_ETFS, TOP_SECTORS_COUNT


def get_nifty500_tickers():
    try:
        return ns.get_nifty500_with_ns()
    except Exception:
        return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]  # Fallback


def _is_clean(close: pd.Series, volume: pd.Series) -> bool:
    """
    Validates that a price/volume series is usable by all models.
    Rejects series with:
      - internal NaN gaps (causes Prophet/SARIMA all-NA errors)
      - flat/suspended prices (less than 1% movement)
      - excessive zero-volume days (illiquid/suspended stock)
    """
    if close is None or volume is None:
        return False

    if len(close) < MIN_DAYS:
        return False

    # Internal NaN gaps — dropna() only cleans edges, not middle gaps
    # These cause Prophet and SARIMA to throw "Encountered all NA values"
    if close.isna().any() or volume.isna().any():
        return False

    # Flat/suspended stock — less than 1% price movement across entire period
    price_range = close.max() - close.min()
    if price_range < close.mean() * 0.01:
        return False

    # Illiquid stock — more than 10% of trading days have zero volume
    zero_vol_pct = (volume == 0).sum() / len(volume)
    if zero_vol_pct > 0.10:
        return False

    return True


def fetch_best_available(ticker: str):
    """
    Try progressively shorter periods and return the longest clean dataset.
    Handles post-merger/demerger stocks that only have recent history.
    Applies strict quality checks before returning — ensures no model
    receives a series that will produce all-NA errors.

    Returns:
        (close: pd.Series, volume: pd.Series) or (None, None)
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

            # Remove edge NaNs and align both to common dates
            close = close.dropna()
            volume = volume.dropna()
            close, volume = close.align(volume, join="inner")

            if _is_clean(close, volume):
                return close, volume

        except Exception:
            continue

    return None, None


def fetch_sector_momentum() -> dict:
    """
    Returns a dict of sector -> 3-month return (momentum score).
    Used to identify which sectors are hot before scanning.
    """
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
