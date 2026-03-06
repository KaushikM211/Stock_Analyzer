# ─────────────────────────────────────────────
# scanner.py — Main Nifty 500 scanning loop
# ─────────────────────────────────────────────

import gc
import warnings
import pandas as pd
from tqdm import tqdm

from config import (
    LOWER_LIMIT,
    UPPER_LIMIT,
    MACRO_MONTH_WEIGHTS,
    MIN_WEIGHTED_ROI,
    MIN_AVG_DAILY_TURNOVER,
    MOMENTUM_TOLERANCE,
    TARGET_WINDOW_START,
    TARGET_WINDOW_END,
    FORECAST_HORIZON,
    PRICE_BANDS,
    TOP_N_PER_BAND,
)
from data import (
    get_nifty500_tickers,
    fetch_best_available,
    fetch_sector_momentum,
    get_top_sectors,
)
from ensemble import ensemble_forecast

warnings.filterwarnings("ignore")

RESULT_COLUMNS = [
    "Price_Band",
    "Stock",
    "Buy_Price",
    "Exit_Target",
    "Weighted_ROI_%",
    "Min_Hold_Until",  # 8 months from today — don't sell before this
    "Best_Sell_Date",  # Prophet's natural peak within the window
    "Forecast_Expires",  # 12 months from today — beyond this is unreliable
    "Avg_Daily_Turnover_Cr",
    "Liquidity",
    "Data_Days",
]


def _liquidity_label(avg_daily_turnover: float) -> str:
    if avg_daily_turnover >= 5e7:
        return "High"
    elif avg_daily_turnover >= 1e7:
        return "Medium"
    return "Low"


def _get_band_label(price: float) -> str:
    for low, high in PRICE_BANDS:
        if low <= price < high:
            return f"₹{low}–₹{high}"
    return "Other"


def analyze_and_predict(
    lower_limit: int = LOWER_LIMIT,
    upper_limit: int = UPPER_LIMIT,
) -> dict[str, pd.DataFrame]:
    """
    Scans all Nifty 500 stocks and returns picks organised by price band.

    Tenure logic:
        - Minimum hold is 8 months (TARGET_WINDOW_START = trading day 168)
        - Forecast reliability ends at 12 months (TARGET_WINDOW_END = day 252)
        - Beyond 12 months the models are extrapolating too far — not reported
        - Best_Sell_Date is wherever Prophet naturally peaks in the 8–12mo window
          It could be month 8, month 10, or month 12 — not forced to the end

    ROI  : weighted ensemble price (all 3 models)
    Dates: Prophet exclusively — only model with calendar awareness
           Ridge always peaks at end of window (no calendar sense)
           XGBoost is flat after 63 days (unreliable for dating)
    """
    tickers = get_nifty500_tickers()
    recommendations = []

    # ── Sector momentum pre-scan ──
    print("Fetching sector momentum scores...")
    sector_momentum = fetch_sector_momentum()
    top_sectors = get_top_sectors(sector_momentum)
    print(f"Top sectors by momentum: {top_sectors}\n")

    for ticker in tqdm(tickers, desc="Scanning Nifty 500"):
        try:
            close, volume = fetch_best_available(ticker)

            if close is None or len(close) < 60:
                continue

            curr_price = float(close.iloc[-1])
            if not (lower_limit <= curr_price <= upper_limit):
                continue

            # ── Liquidity check (before models — cheap filter) ──
            lookback = min(20, len(close))
            avg_daily_turnover = float(
                (close.tail(lookback) * volume.tail(lookback)).mean()
            )
            if avg_daily_turnover < MIN_AVG_DAILY_TURNOVER:
                continue

            liquidity = _liquidity_label(avg_daily_turnover)

            # ── Momentum pre-filter ──
            ma_short = close.iloc[-min(20, len(close)) :].mean()
            ma_long = close.mean()
            if ma_short < ma_long * MOMENTUM_TOLERANCE:
                continue

            # ── Ensemble forecast ──
            # Returns (ensemble_price_path, prophet_price_path)
            forecast_series, prophet_series = ensemble_forecast(
                close, volume, horizon=FORECAST_HORIZON
            )
            if forecast_series is None:
                continue

            # ── ROI from ensemble price in 8–12 month window ──
            ensemble_window = forecast_series.iloc[
                TARGET_WINDOW_START:TARGET_WINDOW_END
            ]
            if ensemble_window.empty:
                continue

            peak_price = float(ensemble_window.max())
            macro_adj = 1 + MACRO_MONTH_WEIGHTS.get(ensemble_window.idxmax().month, 0)
            adjusted_peak = peak_price * macro_adj
            weighted_roi = ((adjusted_peak - curr_price) / curr_price) * 100

            # ── Dates from Prophet in 8–12 month window ──
            prophet_window = prophet_series.iloc[TARGET_WINDOW_START:TARGET_WINDOW_END]

            min_hold_until = prophet_window.index[0]  # earliest allowed sell date
            best_sell_date = prophet_window.idxmax()  # Prophet's natural peak
            forecast_expires = prophet_window.index[-1]  # reliability cutoff

            band_label = _get_band_label(curr_price)

            print(
                f"{ticker} | ₹{curr_price:.2f} [{band_label}] "
                f"| ROI: {weighted_roi:.1f}% "
                f"| Best sell: {best_sell_date.strftime('%b %Y')} "
                f"| ₹{avg_daily_turnover / 1e7:.1f}Cr/day"
            )

            if weighted_roi >= MIN_WEIGHTED_ROI:
                recommendations.append(
                    {
                        "Price_Band": band_label,
                        "Stock": ticker,
                        "Buy_Price": round(curr_price, 2),
                        "Exit_Target": round(adjusted_peak, 2),
                        "Weighted_ROI_%": round(weighted_roi, 2),
                        "Min_Hold_Until": min_hold_until.strftime("%d %b %Y"),
                        "Best_Sell_Date": best_sell_date.strftime("%d %b %Y"),
                        "Forecast_Expires": forecast_expires.strftime("%d %b %Y"),
                        "Avg_Daily_Turnover_Cr": round(avg_daily_turnover / 1e7, 2),
                        "Liquidity": liquidity,
                        "Data_Days": len(close),
                    }
                )

            del forecast_series, prophet_series, ensemble_window, prophet_window
            gc.collect()

        except Exception as e:
            print(f"{ticker}: {type(e).__name__}: {e}")
            continue

    if not recommendations:
        return {}

    df_all = pd.DataFrame(recommendations)

    # ── Split into price bands, top N per band by ROI% ──
    results = {}
    for low, high in PRICE_BANDS:
        label = f"₹{low}–₹{high}"
        band_df = (
            df_all[df_all["Price_Band"] == label]
            .sort_values(by="Weighted_ROI_%", ascending=False)
            .reset_index(drop=True)
            .head(TOP_N_PER_BAND)
        )
        if not band_df.empty:
            results[label] = band_df

    return results
