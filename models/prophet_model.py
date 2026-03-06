# ─────────────────────────────────────────────
# models/prophet_model.py — Prophet forecast
# ─────────────────────────────────────────────

import pandas as pd
from prophet import Prophet

from config import MACRO_MONTH_WEIGHTS


def prophet_forecast(
    close: pd.Series,
    horizon: int = 252,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Fit Prophet with trend + weekly seasonality + macro month regressor.

    - Weekly seasonality: captures Mon-Fri NSE trading patterns
    - Yearly seasonality: only enabled if 200+ days of data available
    - Macro regressor: India-specific calendar effects (budget, earnings, festive)
    - changepoint_prior_scale=0.1: moderate flexibility, won't overfit recent spikes
    - seasonality_prior_scale=0.5: dampened to avoid overfitting short history

    Returns:
        (yhat, yhat_lower, yhat_upper) — all as pd.Series indexed by future business dates
    """
    # Safe timezone handling — yfinance sometimes returns tz-aware, sometimes tz-naive
    if close.index.tz is not None:
        ds = close.index.tz_localize(None)
    else:
        ds = close.index

    df_p = pd.DataFrame(
        {
            "ds": ds,
            "y": close.values,
        }
    )

    # Macro month weight as external regressor (budget month, earnings season etc.)
    df_p["macro"] = df_p["ds"].dt.month.map(MACRO_MONTH_WEIGHTS)

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,  # Weekly NSE patterns
        yearly_seasonality=len(close) >= 200,  # Only with enough history
        changepoint_prior_scale=0.1,  # Moderate trend flexibility
        seasonality_prior_scale=0.5,  # Dampened — avoid overfitting
        interval_width=0.80,
    )
    model.add_regressor("macro")
    model.fit(df_p)

    future_dates = pd.bdate_range(start=close.index[-1], periods=horizon + 1)[1:]
    future_df = pd.DataFrame({"ds": future_dates})
    future_df["macro"] = future_df["ds"].dt.month.map(MACRO_MONTH_WEIGHTS)

    forecast = model.predict(future_df)
    forecast = forecast.set_index("ds")

    return forecast["yhat"], forecast["yhat_lower"], forecast["yhat_upper"]
