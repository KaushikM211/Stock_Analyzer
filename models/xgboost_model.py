# ─────────────────────────────────────────────
# models/xgboost_model.py — XGBoost forecast
# ─────────────────────────────────────────────

import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.preprocessing import MinMaxScaler

from features import build_features


def xgboost_forecast(
    close: pd.Series,
    volume: pd.Series,
    horizon: int = 252,
) -> pd.Series | None:
    """
    XGBoost predicts short-term forward return (1–3 months max),
    then holds that signal flat for the rest of the horizon.

    Why not predict full 252 days directly:
        With 60–120 days of training data, predicting 252 days ahead
        and linearly scaling is statistically invalid — it inflates ROI wildly.
        Instead, XGBoost acts as a directional signal for the near term,
        and Prophet carries the long-term trend extrapolation.

    Returns a price path Series indexed by future business dates,
    or None if insufficient data to train.
    """
    df = build_features(close, volume)

    FEATURE_COLS = [c for c in df.columns if c not in ["close", "volume", "month"]]

    # Cap training horizon at 3 months (63 days) — never extrapolate beyond what data supports
    horizon_train = min(63, max(21, len(df) // 3))

    # Target: actual forward return over horizon_train days
    df["target"] = df["close"].shift(-horizon_train) / df["close"] - 1
    df_train = df.dropna(subset=["target"])

    if len(df_train) < 20:
        return None

    X = df_train[FEATURE_COLS].values
    y = df_train["target"].values

    scaler = MinMaxScaler()
    X_scaled = scaler.fit_transform(X)

    model = XGBRegressor(
        n_estimators=200,
        max_depth=3,  # Shallower — less overfit on small datasets
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_scaled, y)

    # Predict on latest feature row
    latest_features = df[FEATURE_COLS].iloc[[-1]].values
    latest_scaled = scaler.transform(latest_features)
    predicted_return = float(model.predict(latest_scaled)[0])

    curr_price = float(close.iloc[-1])
    predicted_price = curr_price * (1 + predicted_return)

    future_index = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]

    # Ramp from current price to predicted price over horizon_train days,
    # then hold flat — XGBoost only speaks to the near term
    price_path = np.full(horizon, predicted_price)
    price_path[:horizon_train] = np.linspace(curr_price, predicted_price, horizon_train)

    return pd.Series(price_path, index=future_index)
