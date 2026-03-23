# ─────────────────────────────────────────────
# ensemble.py — Weighted ensemble of all 3 models
# ─────────────────────────────────────────────

import pandas as pd

from .config import FORECAST_HORIZON, MODEL_WEIGHTS
from models import xgboost_forecast, prophet_forecast, holt_forecast, vpr_forecast


def ensemble_forecast(
    close: pd.Series,
    volume: pd.Series,
    horizon: int = FORECAST_HORIZON,
    weights: dict | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series | None] | tuple[None, None, None]:
    """
    Runs all 4 models and returns:
        1. Weighted ensemble price path   — used for ROI calculation
        2. Prophet yhat series            — used for peak date selection
        3. Prophet confidence width series — used for stock-specific expiry date

    weights — optional dict with keys prophet/holt/xgb/vpr.
        If None, uses MODEL_WEIGHTS from config (base weights).
        If provided, uses these instead — allows scanner.py to pass
        fundamentally-adjusted weights for weak stocks (confidence reducer).
        Weights are renormalised after any model failures.
    """
    base_weights = weights if weights is not None else MODEL_WEIGHTS
    forecasts = {}
    w = {}
    prophet_yhat = None
    prophet_conf_width = None

    # ── Prophet ──
    try:
        p_yhat, p_upper, p_lower = prophet_forecast(close, horizon)
        forecasts["prophet"] = p_yhat
        w["prophet"] = base_weights.get("prophet", MODEL_WEIGHTS["prophet"])
        prophet_yhat = p_yhat
        prophet_conf_width = p_upper - p_lower
    except Exception as e:
        print(f"    [Prophet] failed: {e}")

    # ── XGBoost ──
    try:
        xgb_series = xgboost_forecast(close, volume, horizon)
        if xgb_series is not None:
            forecasts["xgb"] = xgb_series
            w["xgb"] = base_weights.get("xgb", MODEL_WEIGHTS["xgb"])
    except Exception as e:
        print(f"    [XGBoost] failed: {e}")

    # ── Holt Damped Trend ──
    try:
        h_series = holt_forecast(close, horizon)
        forecasts["holt"] = h_series
        w["holt"] = base_weights.get("holt", MODEL_WEIGHTS["holt"])
    except Exception as e:
        print(f"    [Holt] failed: {e}")

    # ── VPR ──
    try:
        v_series = vpr_forecast(close, horizon)
        if v_series is not None:
            forecasts["vpr"] = v_series
            w["vpr"] = base_weights.get("vpr", MODEL_WEIGHTS["vpr"])
    except Exception as e:
        print(f"    [VPR] failed: {e}")

    if not forecasts:
        return None, None, None

    # Renormalise for any failed models
    total_weight = sum(w[k] for k in forecasts)
    norm_weights = {k: w[k] / total_weight for k in forecasts}

    base_index = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]
    combined = pd.Series(0.0, index=base_index)

    for k, series in forecasts.items():
        aligned = series.reindex(base_index).interpolate()
        combined += aligned * norm_weights[k]

    if prophet_yhat is None:
        prophet_yhat = combined

    return combined, prophet_yhat, prophet_conf_width
