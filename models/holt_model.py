# ─────────────────────────────────────────────
# models/holt_model.py — Holt's Damped Trend (replaces Ridge)
# ─────────────────────────────────────────────

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from core.config import MAX_ANNUAL_RETURN, MIN_ANNUAL_RETURN

# Damping factor — controls how quickly the trend fades over time.
# On a 24-month horizon (504 trading days), trend contribution = φ^504
#   φ=0.91 → 0.91^504 ≈ 0% — fully dampened by month 24 ✓
#   φ=0.88 → dampens slightly faster — better for volatile NSE stocks
#             where trends are less persistent than developed markets
#   φ=0.80 → too conservative — trend vanishes in ~6 months
#   φ=1.00 → no damping (Holt's without damping — too aggressive)
# 0.88 chosen: dampens within 18 months, giving Holt a realistic
# long-term anchor without trend extrapolation running too far.
DAMPING_FACTOR = 0.88


def holt_forecast(
    close: pd.Series,
    horizon: int = 252,
) -> pd.Series:
    """
    Holt's Damped Trend exponential smoothing — long-term price anchor.

    Why Holt Damped over Ridge:
        Ridge says: "stock grew 30%/yr → will grow 30%/yr forever"
        Holt Damped: "stock grew 30%/yr → growth gradually slows to ~8%
                      as we look further out" — far more realistic

    The damping factor φ=0.82 means:
        - Month 1: trend contributes ~82% of its original strength
        - Month 6: trend contributes ~82^6 ≈ 30% of original strength
        - Month 12: trend nearly fully dampened — converges to a level

    Return caps from config are still applied as a safety net.
    """
    future_index = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]

    try:
        model = ExponentialSmoothing(
            close.values,
            trend="add",
            damped_trend=True,
            seasonal="add",
            seasonal_periods=21,  # monthly seasonality (21 trading days)
            initialization_method="estimated",
        )
        result = model.fit(
            damping_trend=DAMPING_FACTOR,
            optimized=True,
            remove_bias=True,
        )
        forecast = result.forecast(horizon)

    except Exception:
        # Fallback to simple linear extrapolation if Holt fails
        log_prices = np.log(close.values)
        slope = (log_prices[-1] - log_prices[0]) / len(log_prices)
        max_daily = np.log(1 + MAX_ANNUAL_RETURN) / 252
        min_daily = np.log(1 + MIN_ANNUAL_RETURN) / 252
        slope = np.clip(slope, min_daily, max_daily)
        future_steps = np.arange(1, horizon + 1)
        forecast = np.exp(log_prices[-1] + slope * future_steps)

    # Apply return caps as safety net
    curr_price = float(close.iloc[-1])
    max_price = curr_price * (1 + MAX_ANNUAL_RETURN)
    min_price = curr_price * (1 + MIN_ANNUAL_RETURN)
    forecast = np.clip(forecast, min_price, max_price)

    return pd.Series(forecast, index=future_index)
