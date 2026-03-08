# ─────────────────────────────────────────────
# ensemble.py — Weighted ensemble of all 3 models
# ─────────────────────────────────────────────

import pandas as pd

from config import FORECAST_HORIZON, MODEL_WEIGHTS
from models import xgboost_forecast, prophet_forecast, holt_forecast, vpr_forecast


def ensemble_forecast(
    close: pd.Series,
    volume: pd.Series,
    horizon: int = FORECAST_HORIZON,
) -> tuple[pd.Series, pd.Series, pd.Series | None] | tuple[None, None, None]:
    """
    Runs all 3 models and returns:
        1. Weighted ensemble price path   — used for ROI calculation
        2. Prophet yhat series            — used for peak date selection
        3. Prophet confidence width series — used for stock-specific expiry date

    Forecast_Expires is derived from when Prophet's confidence interval width
    exceeds 40% of the forecast price — beyond this point the model is too
    uncertain to be actionable. This is stock-specific, not a fixed date.

    Returns (ensemble_series, prophet_yhat, prophet_conf_width) or (None, None, None)
    """
    forecasts = {}
    weights = {}
    prophet_yhat = None
    prophet_conf_width = None

    # ── Prophet ──
    try:
        p_yhat, p_upper, p_lower = prophet_forecast(close, horizon)
        forecasts["prophet"] = p_yhat
        weights["prophet"] = MODEL_WEIGHTS["prophet"]
        prophet_yhat = p_yhat
        prophet_conf_width = p_upper - p_lower  # wider = less confident
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

    # ── Holt Damped Trend ──
    try:
        h_series = holt_forecast(close, horizon)
        forecasts["holt"] = h_series
        weights["holt"] = MODEL_WEIGHTS["holt"]
    except Exception as e:
        print(f"    [Holt] failed: {e}")

    # ── VPR — Volatility Penalised Return ──
    try:
        v_series = vpr_forecast(close, horizon)
        if v_series is not None:
            forecasts["vpr"] = v_series
            weights["vpr"] = MODEL_WEIGHTS["vpr"]
    except Exception as e:
        print(f"    [VPR] failed: {e}")

    if not forecasts:
        return None, None, None

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

    return combined, prophet_yhat, prophet_conf_width
