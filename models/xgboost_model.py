# ─────────────────────────────────────────────
# models/xgboost_model.py — XGBoost with Holt blended handoff
# ─────────────────────────────────────────────

import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.preprocessing import MinMaxScaler
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from core.features import build_features
from core.config import MAX_ANNUAL_RETURN, MIN_ANNUAL_RETURN, FORECAST_HORIZON
from .holt_model import DAMPING_FACTOR


def _holt_path(close: pd.Series, horizon: int) -> np.ndarray:
    """
    Compute Holt damped trend path for blending with XGBoost.
    Used as the long-term baseline XGBoost hands off to after day 63.
    """
    try:
        model = ExponentialSmoothing(
            close.values,
            trend="add",
            damped_trend=True,
            initialization_method="estimated",
        )
        result = model.fit(damping_trend=DAMPING_FACTOR, optimized=True)
        return result.forecast(horizon)
    except Exception:
        # Simple linear fallback
        log_prices = np.log(close.values)
        slope = np.clip(
            (log_prices[-1] - log_prices[0]) / len(log_prices),
            np.log(1 + MIN_ANNUAL_RETURN) / 252,
            np.log(1 + MAX_ANNUAL_RETURN) / 252,
        )
        return np.exp(log_prices[-1] + slope * np.arange(1, horizon + 1))


def xgboost_forecast(
    close: pd.Series,
    volume: pd.Series,
    horizon: int = FORECAST_HORIZON,
) -> pd.Series | None:
    """
    XGBoost predicts short-term direction (up to 63 days).
    Beyond 63 days it blends gracefully into Holt's damped trend
    rather than holding flat — giving a meaningful long-term path.

    Blend schedule:
        Day 1–63    : 100% XGBoost signal
        Day 63–126  : XGBoost weight linearly decays 1.0 → 0.0
                      Holt weight linearly grows  0.0 → 1.0
        Day 126–252 : 100% Holt damped trend

    This means:
        - Near term: XGBoost's momentum signal dominates
        - Medium term: gradual handoff during transition zone
        - Long term: Holt's realistic dampened trend takes over
    """
    df = build_features(close, volume)
    if df.empty:
        return None

    FEATURE_COLS = [c for c in df.columns if c not in ["close", "volume", "month"]]
    horizon_train = min(63, max(21, len(df) // 3))

    max_return = (1 + MAX_ANNUAL_RETURN) ** (horizon_train / 252) - 1
    min_return = (1 + MIN_ANNUAL_RETURN) ** (horizon_train / 252) - 1

    df["target"] = df["close"].shift(-horizon_train) / df["close"] - 1
    df_train = df.dropna(subset=["target"])
    df_train = df_train[df_train["target"].between(min_return, max_return)]

    if len(df_train) < 20:
        return None

    X = df_train[FEATURE_COLS].values
    y = df_train["target"].values
    scaler = MinMaxScaler()
    X_scaled = scaler.fit_transform(X)

    model = XGBRegressor(
        n_estimators=150,  # 200 → 150: marginal accuracy loss, 2x speed
        max_depth=3,
        learning_rate=0.0675,  # slightly higher lr compensates for fewer trees
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0,
        n_jobs=1,  # avoid thread contention in parallel runs
    )
    model.fit(X_scaled, y)

    latest_scaled = scaler.transform(df[FEATURE_COLS].iloc[[-1]].values)
    predicted_return = float(model.predict(latest_scaled)[0])
    predicted_return = np.clip(predicted_return, min_return, max_return)

    curr_price = float(close.iloc[-1])
    predicted_price = curr_price * (1 + predicted_return)
    future_index = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]

    # ── Holt baseline for the full horizon ──
    holt_path = _holt_path(close, horizon)
    holt_path = np.clip(
        holt_path,
        curr_price * (1 + MIN_ANNUAL_RETURN),
        curr_price * (1 + MAX_ANNUAL_RETURN),
    )

    price_path = np.zeros(horizon)

    # Zone 1: Day 1 → horizon_train — ramp from current to XGBoost target
    price_path[:horizon_train] = np.linspace(curr_price, predicted_price, horizon_train)

    # Zone 2: horizon_train → horizon_train*2 — blend XGBoost flat into Holt
    blend_end = min(horizon_train * 2, horizon)
    blend_len = blend_end - horizon_train
    if blend_len > 0:
        xgb_weights = np.linspace(1.0, 0.0, blend_len)
        holt_weights = np.linspace(0.0, 1.0, blend_len)
        price_path[horizon_train:blend_end] = (
            xgb_weights * predicted_price
            + holt_weights * holt_path[horizon_train:blend_end]
        )

    # Zone 3: blend_end → horizon — pure Holt damped trend
    if blend_end < horizon:
        price_path[blend_end:] = holt_path[blend_end:]

    return pd.Series(price_path, index=future_index)
