# ─────────────────────────────────────────────
# models/ridge_model.py — Ridge Regression on log prices
# ─────────────────────────────────────────────

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


# Maximum annualised return Ridge is allowed to imply
# Based on realistic NSE large/mid cap historical performance
_MAX_ANNUAL_RETURN = 0.30  # 30% annualised cap
_MIN_ANNUAL_RETURN = -0.20  # -20% annualised floor


def ridge_forecast(
    close: pd.Series,
    horizon: int = 252,
) -> pd.Series:
    """
    Fits Ridge Regression on log prices using only a linear time trend.
    The implied annualised return is capped at realistic bounds before
    extrapolating — prevents runaway compounding on strong historical trends.

    Key design decisions:
        - NO quadratic term — it extrapolates wildly beyond training range
        - NO day-of-week — adds noise without signal at monthly horizon
        - Annualised return derived from slope and clamped to ±30%/20%
        - This makes Ridge a conservative anchor in the ensemble
    """
    n = len(close)
    log_prices = np.log(close.values)

    # Normalised time index [0, 1] — prevents scale issues in Ridge
    t_hist = np.arange(n) / n
    X_hist = t_hist.reshape(-1, 1)

    scaler = StandardScaler()
    X_hist_scaled = scaler.fit_transform(X_hist)

    model = Ridge(alpha=10.0)
    model.fit(X_hist_scaled, log_prices)

    # Extract implied daily return from slope
    # slope in log-price per normalised unit → convert to per-day
    raw_slope = model.coef_[0] / (scaler.scale_[0] * n)  # log return per day

    # Cap slope to realistic annualised return bounds
    max_daily = np.log(1 + _MAX_ANNUAL_RETURN) / 252
    min_daily = np.log(1 + _MIN_ANNUAL_RETURN) / 252
    capped_slope = np.clip(raw_slope, min_daily, max_daily)

    # Rebuild forecast using capped slope from last known log price
    last_log_price = log_prices[-1]
    future_index = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]
    future_steps = np.arange(1, horizon + 1)

    log_forecast = last_log_price + capped_slope * future_steps
    price_path = np.exp(log_forecast)

    return pd.Series(price_path, index=future_index)
