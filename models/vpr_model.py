# ─────────────────────────────────────────────
# models/vpr_model.py — Volatility Penalised Return (VPR) model
#
# Works in log-return space (mathematically correct for stocks)
# Penalises high-volatility stocks — same ROI on a calmer stock
# is always preferable to a volatile one.
#
# Core idea:
#   1. Compute historical daily log returns
#   2. Estimate mean log return (expected drift)
#   3. Estimate volatility (std dev of log returns)
#   4. Apply Sharpe-style penalty: drift - λ * volatility
#   5. Build forecast price path from penalised drift
#   6. Apply return caps as safety net
#
# Why log returns, not simple returns:
#   Simple returns: +50% then -50% = -25% total (misleading)
#   Log returns:    +0.405 then -0.693 = -0.288 total (correct)
#   Stock returns are multiplicative — log space makes them additive
#
# Why penalise volatility:
#   Two stocks, same 15% expected return:
#     Stock A: daily vol = 1%  → Sharpe-adjusted drift is high  → preferred
#     Stock B: daily vol = 3%  → Sharpe-adjusted drift is lower → punished
#   This naturally filters out momentum/meme stocks with erratic paths
# ─────────────────────────────────────────────

import numpy as np
import pandas as pd

from core.config import MAX_ANNUAL_RETURN, MIN_ANNUAL_RETURN

# ─────────────────────────────────────────────
# TUNABLE PARAMETERS
# ─────────────────────────────────────────────

# How hard to penalise volatility
# 0.0  = no penalty  (same as plain log-return model)
# 0.5  = mild        (slight preference for stable stocks)
# 1.0  = standard    (Sharpe-ratio equivalent)
# 2.0  = aggressive  (strongly punishes volatile stocks)
VOLATILITY_PENALTY = 0.65  # between mild and standard — good for NSE mid/large caps

# Lookback window for estimating mean return and volatility
# 252 = 1 year — captures recent regime without overfitting to distant history
# 504 = 2 years — more stable estimate, less reactive to recent moves
LOOKBACK_DAYS = 420  # 20 months — balances recency and stability

# Minimum data required for a reliable estimate
MIN_RETURN_DAYS = 60


def vpr_forecast(
    close: pd.Series,
    horizon: int = 252,
) -> pd.Series | None:
    """
    Volatility Penalised Return forecast.

    Returns a price path Series indexed to future business days,
    or None if insufficient data.

    The forecast represents: "if this stock continues its historical
    drift, penalised by how volatile that ride was, where does it end up?"

    High volatility stocks get a conservative forecast even if their
    raw mean return looks attractive — rewarding consistency over spikes.
    """
    if len(close) < MIN_RETURN_DAYS:
        return None

    try:
        # ── Step 1: Log returns ──
        log_returns = np.log(close / close.shift(1)).dropna()

        # Use lookback window — don't overweight ancient history
        lookback = min(LOOKBACK_DAYS, len(log_returns))
        recent_rets = log_returns.iloc[-lookback:]

        # ── Step 2: Mean and volatility ──
        mean_log_return = float(recent_rets.mean())  # daily expected drift
        volatility = float(recent_rets.std())  # daily std dev

        if volatility <= 0 or np.isnan(mean_log_return) or np.isnan(volatility):
            return None

        # ── Step 3: Volatility penalty ──
        # Reduces drift proportionally to volatility
        # High vol stock: mean=0.001, vol=0.03 → penalty=0.0225 → adjusted=-0.0215
        # Low vol stock:  mean=0.001, vol=0.01 → penalty=0.0075 → adjusted=-0.0065
        # Net effect: calmer stocks get a more optimistic forecast
        penalty = VOLATILITY_PENALTY * volatility
        adjusted_drift = mean_log_return - penalty

        # ── Step 4: Cap adjusted drift to return limits ──
        max_daily = np.log(1 + MAX_ANNUAL_RETURN) / 252
        min_daily = np.log(1 + MIN_ANNUAL_RETURN) / 252
        adjusted_drift = np.clip(adjusted_drift, min_daily, max_daily)

        # ── Step 5: Build forecast price path ──
        curr_log_price = np.log(float(close.iloc[-1]))
        future_steps = np.arange(1, horizon + 1)
        forecast_log = curr_log_price + adjusted_drift * future_steps
        forecast_prices = np.exp(forecast_log)

        # ── Step 6: Final price caps as safety net ──
        curr_price = float(close.iloc[-1])
        max_price = curr_price * (1 + MAX_ANNUAL_RETURN) ** (horizon / 252)
        min_price = curr_price * (1 + MIN_ANNUAL_RETURN) ** (horizon / 252)
        forecast_prices = np.clip(forecast_prices, min_price, max_price)

        # ── Index to future business days ──
        future_index = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]

        return pd.Series(forecast_prices, index=future_index)

    except Exception:
        return None
