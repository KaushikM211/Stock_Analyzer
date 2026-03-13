# ─────────────────────────────────────────────
# models/prophet_model.py — Prophet forecast with mean-reversion penalty
# ─────────────────────────────────────────────

import numpy as np
import pandas as pd
from prophet import Prophet

from core.config import MACRO_MONTH_WEIGHTS, MAX_ANNUAL_RETURN, MIN_ANNUAL_RETURN

# ─────────────────────────────────────────────
# MEAN REVERSION PARAMETERS
#
# Markets don't trend forever — after a strong run, stocks mean-revert.
# These parameters control how aggressively we pull the forecast back
# toward the historical mean price as we look further into the future.
#
# REVERSION_STRENGTH: how hard we pull back toward mean
#   0.0 = no reversion (Prophet trends forever — what we had before)
#   0.3 = moderate — peak forms naturally in the middle of window
#   0.5 = strong — forecast curves over quickly
#   0.7 = very strong — almost always peaks early
#
# REVERSION_SPEED: how quickly reversion kicks in
#   Lower = reversion starts immediately
#   Higher = reversion only kicks in toward end of window
# ─────────────────────────────────────────────
REVERSION_STRENGTH = 0.35
REVERSION_SPEED = 2.2  # higher exponent = reversion kicks in later
# gives more room for natural peak to form
# across the full 24 month window


def _apply_mean_reversion(
    yhat: np.ndarray,
    curr_price: float,
    hist_mean: float,
    horizon: int,
) -> np.ndarray:
    """
    Applies a progressive mean-reversion penalty to Prophet's forecast.

    Logic:
        - At day 1: no penalty — Prophet's near-term signal is trusted
        - At day horizon: maximum penalty — pull strongly toward hist_mean
        - In between: penalty grows as a power curve (REVERSION_SPEED controls shape)

    This forces the forecast to:
        1. Rise toward Prophet's predicted peak (near term)
        2. Curve over and return toward mean (long term)
        3. Create a natural peak somewhere in the window — not always at the end

    The peak location depends on:
        - How far the current price is from historical mean
        - REVERSION_STRENGTH
        - The shape of Prophet's underlying trend

    Stocks trading far above their historical mean get penalized more heavily
    (they have more to revert) — which is the correct real-world behavior.
    """
    t = np.arange(1, horizon + 1) / horizon  # normalised time 0→1

    # Penalty weight grows as power curve: 0 at t=0, 1 at t=1
    penalty_weight = t**REVERSION_SPEED * REVERSION_STRENGTH

    # Pull forecast toward historical mean price
    reverted = yhat * (1 - penalty_weight) + hist_mean * penalty_weight

    return reverted


def prophet_forecast(
    close: pd.Series,
    horizon: int = 252,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Fit Prophet with trend + weekly seasonality + macro month regressor.
    Mean-reversion penalty applied post-forecast to create natural peaks.

    Why mean reversion:
        Without it, Prophet extrapolates the recent trend forever →
        all stocks peak at the last day of the window (May 2027 clustering).
        With it, stocks trading above their historical mean curve back down,
        creating stock-specific peak dates based on how overextended they are.
    """
    if close.index.tz is not None:
        ds = close.index.tz_localize(None)
    else:
        ds = close.index

    # Historical mean — the level prices revert toward
    hist_mean = float(close.mean())
    curr_price = float(close.iloc[-1])

    df_p = pd.DataFrame({"ds": ds, "y": close.values})
    df_p["macro"] = df_p["ds"].dt.month.map(MACRO_MONTH_WEIGHTS)

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=False,  # weekly adds ~0.3s per fit, marginal value
        yearly_seasonality=len(close) >= 200,
        changepoint_prior_scale=0.03,
        seasonality_prior_scale=0.2,
        interval_width=0.80,
        stan_backend="CMDSTANPY",  # faster than default
        n_changepoints=25,  # default 25
    )
    model.add_regressor("macro")
    model.fit(df_p, iter=6000)  # default 6000 iter

    future_dates = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]
    future_df = pd.DataFrame({"ds": future_dates})
    future_df["macro"] = future_df["ds"].dt.month.map(MACRO_MONTH_WEIGHTS)

    forecast = model.predict(future_df)
    forecast = forecast.set_index("ds")

    # ── Hard return caps ──
    steps = np.arange(1, horizon + 1)
    max_daily = np.log(1 + MAX_ANNUAL_RETURN) / 252
    min_daily = np.log(1 + MIN_ANNUAL_RETURN) / 252
    max_path = curr_price * np.exp(max_daily * steps)
    min_path = curr_price * np.exp(min_daily * steps)

    yhat = np.clip(forecast["yhat"].values, min_path, max_path)
    yhat_upper = np.clip(forecast["yhat_upper"].values, min_path, max_path)
    yhat_lower = np.clip(forecast["yhat_lower"].values, min_path, max_path)

    # ── Mean reversion penalty ──
    # Only apply if stock is currently trading above its historical mean
    # (stocks below mean are already in reversion — don't double-penalize)
    if curr_price > hist_mean:
        yhat = _apply_mean_reversion(yhat, curr_price, hist_mean, horizon)
        yhat_upper = _apply_mean_reversion(yhat_upper, curr_price, hist_mean, horizon)
        yhat_lower = _apply_mean_reversion(yhat_lower, curr_price, hist_mean, horizon)

    # Re-clip after reversion to ensure floor is respected
    yhat = np.clip(yhat, min_path, max_path)
    yhat_upper = np.clip(yhat_upper, min_path, max_path)
    yhat_lower = np.clip(yhat_lower, min_path, max_path)

    idx = forecast.index
    return (
        pd.Series(yhat, index=idx),
        pd.Series(yhat_upper, index=idx),
        pd.Series(yhat_lower, index=idx),
    )
