# ─────────────────────────────────────────────
# ensemble.py — Weighted ensemble of all 3 models
# ─────────────────────────────────────────────

import pandas as pd

from config import FORECAST_HORIZON, MODEL_WEIGHTS
from models import xgboost_forecast, prophet_forecast, ridge_forecast


def ensemble_forecast(
    close: pd.Series,
    volume: pd.Series,
    horizon: int = FORECAST_HORIZON,
) -> tuple[pd.Series, pd.Series] | tuple[None, None]:
    """
    Runs all 3 models and returns:
        1. Weighted ensemble price path  — used for ROI calculation
        2. Prophet yhat series           — used exclusively for peak date selection

    Why separate date source:
        - Ridge has no calendar awareness — its peak is always the last forecast day
        - XGBoost holds flat after 63 days — peak date is unreliable beyond near term
        - Only Prophet models weekly + monthly seasonality and can meaningfully
          identify WHEN within the 8–12 month window the price is likely to peak
          (e.g. October festive rally vs March FY-end weakness)

    Weights (from config):
        Prophet : 40%  — long-term trend + macro seasonality
        XGBoost : 35%  — near-term directional signal
        Ridge   : 25%  — conservative annualised trend anchor

    Models that fail are dropped gracefully and weights renormalised.

    Returns (ensemble_series, prophet_series) or (None, None) if all fail.
    """
    forecasts = {}
    weights = {}
    prophet_yhat = None

    # ── Prophet ──
    try:
        p_yhat, _, _ = prophet_forecast(close, horizon)
        forecasts["prophet"] = p_yhat
        weights["prophet"] = MODEL_WEIGHTS["prophet"]
        prophet_yhat = p_yhat  # Keep separately for date picking
    except Exception as e:
        print(f"    [Prophet] failed: {e}")

    # ── XGBoost ──
    try:
        xgb_series = xgboost_forecast(close, volume, horizon)
        if xgb_series is not None:
            forecasts["xgb"] = xgb_series
            weights["xgb"] = MODEL_WEIGHTS["xgb"]
    except Exception as e:
        print(f"    [XGBoost] failed: {e}")

    # ── Ridge ──
    try:
        r_series = ridge_forecast(close, horizon)
        forecasts["ridge"] = r_series
        weights["ridge"] = MODEL_WEIGHTS["ridge"]
    except Exception as e:
        print(f"    [Ridge] failed: {e}")

    if not forecasts:
        return None, None

    # Renormalise weights for any models that failed
    total_weight = sum(weights[k] for k in forecasts)
    norm_weights = {k: weights[k] / total_weight for k in forecasts}

    # Align all forecasts to the same business day index
    base_index = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]
    combined = pd.Series(0.0, index=base_index)

    for k, series in forecasts.items():
        aligned = series.reindex(base_index).interpolate()
        combined += aligned * norm_weights[k]

    # If Prophet failed, fall back to ensemble for date too
    if prophet_yhat is None:
        prophet_yhat = combined

    return combined, prophet_yhat
