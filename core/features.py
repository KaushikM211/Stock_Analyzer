# ─────────────────────────────────────────────
# features.py — Technical indicators + feature engineering
# ─────────────────────────────────────────────

import numpy as np
import pandas as pd

from .config import MACRO_MONTH_WEIGHTS

# Day-of-week return bias on NSE (empirically observed)
# Used as a feature signal for XGBoost — not extrapolated forward
DOW_WEIGHTS = {
    0: -0.01,  # Monday   — weak open, digesting weekend global news
    1: 0.01,  # Tuesday  — recovery begins
    2: 0.02,  # Wednesday — mid-week strength
    3: 0.02,  # Thursday  — pre-expiry momentum (NSE F&O expiry is Thursday)
    4: -0.01,  # Friday   — profit booking before weekend
}


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal).mean()
    return macd, signal_line


def compute_bollinger(series: pd.Series, period: int = 20):
    ma = series.rolling(period).mean()
    std = series.rolling(period).std()
    return ma + 2 * std, ma - 2 * std  # upper, lower


def compute_atr(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average True Range — measures volatility.
    High ATR = high daily swings = higher risk.
    Used by XGBoost to distinguish trending vs choppy stocks.
    """
    high_low = close.rolling(2).max() - close.rolling(2).min()
    high_close = (close - close.shift(1)).abs()
    tr = pd.concat([high_low, high_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    On-Balance Volume — cumulative volume flow.
    Rising OBV with rising price = strong trend confirmation.
    Falling OBV with rising price = distribution (weak signal).
    """
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def build_features(close: pd.Series, volume: pd.Series) -> pd.DataFrame:
    """
    Builds a rich feature DataFrame for XGBoost training.

    Feature groups:
        1. Price returns & log returns          — core price signal
        2. Moving averages + distance           — trend position
        3. RSI                                  — momentum overbought/oversold
        4. MACD                                 — trend direction + crossovers
        5. Bollinger Bands                      — volatility + mean reversion
        6. ATR                                  — volatility regime
        7. OBV                                  — volume-price confirmation
        8. Volume ratio                         — unusual volume detection
        9. Day-of-week bias                     — NSE intraweek patterns
                                                  (Thursday F&O expiry effect)
       10. Macro month weight                   — India calendar effects
       11. Momentum 1m / 3m                     — medium-term trend strength

    All windows are adaptive to available data length — handles
    post-merger stocks with as few as 60 days of history.
    """
    n = len(close)
    df = pd.DataFrame({"close": close, "volume": volume})

    # ── 1. Returns ──
    df["returns"] = df["close"].pct_change()
    df["log_returns"] = np.log(df["close"] / df["close"].shift(1))

    # ── 2. Moving averages ──
    for w in [5, 10, 20, 50]:
        if n >= w * 2:
            df[f"ma{w}"] = df["close"].rolling(w).mean()
            df[f"ma{w}_dist"] = (df["close"] - df[f"ma{w}"]) / df[f"ma{w}"]

    # MA crossover signal — 1 if short MA > long MA (uptrend), -1 otherwise
    if n >= 40:
        ma10 = df["close"].rolling(10).mean()
        ma20 = df["close"].rolling(20).mean()
        df["ma_cross"] = np.where(ma10 > ma20, 1, -1)

    # ── 3. RSI ──
    rsi_period = min(14, n // 4)
    if rsi_period >= 3:
        df["rsi"] = compute_rsi(df["close"], period=rsi_period)
        # RSI zone encoding — oversold/neutral/overbought
        df["rsi_zone"] = pd.cut(
            df["rsi"],
            bins=[0, 25, 45, 55, 75, 100],
            labels=[-1, 0, 0.5, 1, 2],
        ).astype(float)

    # ── 4. MACD ──
    if n >= 40:
        df["macd"], df["macd_signal"] = compute_macd(df["close"])
        df["macd_hist"] = df["macd"] - df["macd_signal"]
        df["macd_cross"] = np.where(df["macd"] > df["macd_signal"], 1, -1)

    # ── 5. Bollinger Bands ──
    bb_period = min(20, n // 3)
    if bb_period >= 5:
        df["bb_upper"], df["bb_lower"] = compute_bollinger(
            df["close"], period=bb_period
        )
        df["bb_position"] = (df["close"] - df["bb_lower"]) / (
            df["bb_upper"] - df["bb_lower"] + 1e-9
        )
        # Width = volatility proxy
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["close"]

    # ── 6. ATR (volatility) ──
    atr_period = min(14, n // 4)
    if atr_period >= 3:
        df["atr"] = compute_atr(df["close"], period=atr_period)
        df["atr_pct"] = df["atr"] / df["close"]  # Normalised ATR

    # ── 7. OBV (volume-price confirmation) ──
    if n >= 10:
        obv = compute_obv(df["close"], df["volume"])
        df["obv_norm"] = obv / (obv.abs().max() + 1e-9)  # Normalise to [-1, 1]
        # OBV trend — is volume confirming price direction?
        obv_ma = obv.rolling(min(10, n // 5)).mean()
        df["obv_trend"] = np.where(obv > obv_ma, 1, -1)

    # ── 8. Volume ratio ──
    vol_window = min(20, n // 3)
    if vol_window >= 5:
        df["volume_ma"] = df["volume"].rolling(vol_window).mean()
        df["volume_ratio"] = df["volume"] / (df["volume_ma"] + 1e-9)
        # Volume spike flag — unusual activity often precedes big moves
        df["volume_spike"] = (df["volume_ratio"] > 3.0).astype(int)

    # ── 9. Day-of-week ──
    # NSE-specific: Thursday is F&O expiry — tends to have directional moves
    # Monday tends to be weak (global overnight gap digestion)
    df["day_of_week"] = df.index.dayofweek  # 0=Mon, 4=Fri
    df["dow_weight"] = df["day_of_week"].map(DOW_WEIGHTS)  # directional bias
    df["is_expiry_day"] = (df["day_of_week"] == 3).astype(int)  # Thursday F&O expiry
    df["is_monday"] = (df["day_of_week"] == 0).astype(int)  # Monday gap risk

    # ── 10. Macro month weight ──
    df["month"] = df.index.month
    df["macro_weight"] = df["month"].map(MACRO_MONTH_WEIGHTS)

    # ── 11. Momentum ──
    mom_1m = min(21, n // 3)
    mom_3m = min(63, n // 2)
    if mom_1m >= 5:
        df["mom_1m"] = df["close"].pct_change(mom_1m)
    if mom_3m >= 10:
        df["mom_3m"] = df["close"].pct_change(mom_3m)
        # Momentum acceleration — is trend speeding up or slowing?
        df["mom_acceleration"] = df["mom_1m"] - df["mom_3m"] / 3

    # ── Final cleanup ──
    # Only require core columns — optional indicators filled with median
    core_cols = ["returns", "log_returns", "macro_weight", "dow_weight"]
    df = df.dropna(subset=core_cols)
    df = df.fillna(df.median(numeric_only=True))

    if df.empty:
        raise ValueError(f"No usable feature rows after cleaning ({n} raw rows input)")

    return df
