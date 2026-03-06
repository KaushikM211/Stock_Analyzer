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
    passes_fundamental_filter,
)
from ensemble import ensemble_forecast

warnings.filterwarnings("ignore")

# Confidence interval width threshold — if Prophet's (yhat_upper - yhat_lower)
# exceeds this fraction of the forecast price, the model is too uncertain
# e.g. 0.40 means: if the band is wider than 40% of the predicted price, stop trusting it
CONFIDENCE_THRESHOLD = 0.40


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


def _get_confidence_expiry(
    prophet_yhat: pd.Series,
    prophet_conf_width: pd.Series,
    window_start_idx: int,
) -> str:
    """
    Returns the first date after window_start where Prophet's confidence
    interval width exceeds CONFIDENCE_THRESHOLD × forecast price.

    This is stock-specific — volatile stocks lose confidence sooner,
    stable stocks maintain confidence longer into the forecast window.

    Falls back to the last day of the forecast window if always confident.
    """
    try:
        base_index = pd.bdate_range(
            start=prophet_yhat.index[0], periods=len(prophet_yhat)
        )
        yhat_aligned = prophet_yhat.reindex(base_index).interpolate()
        width_aligned = prophet_conf_width.reindex(base_index).interpolate()

        # Only look from window_start onward
        yhat_window = yhat_aligned.iloc[window_start_idx:]
        width_window = width_aligned.iloc[window_start_idx:]

        # Relative confidence width = band width / forecast price
        rel_width = width_window / (yhat_window.abs() + 1e-9)

        # First date where uncertainty exceeds threshold
        uncertain = rel_width[rel_width > CONFIDENCE_THRESHOLD]
        if not uncertain.empty:
            return uncertain.index[0].strftime("%d %b %Y")

        # Model stays confident through entire window — return last date
        return yhat_window.index[-1].strftime("%d %b %Y")

    except Exception:
        return prophet_yhat.index[-1].strftime("%d %b %Y")


def analyze_and_predict(
    lower_limit: int = LOWER_LIMIT,
    upper_limit: int = UPPER_LIMIT,
) -> dict[str, pd.DataFrame]:
    """
    Scans all Nifty 500 stocks and returns picks organised by price band.

    Forecast_Expires is now stock-specific:
        - Derived from Prophet's confidence interval width
        - Wider band = model is less certain = earlier expiry
        - Volatile stocks expire sooner, stable stocks expire later
        - Not a fixed date for all stocks
    """
    tickers = get_nifty500_tickers()
    recommendations = []

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

            # ── Fundamental filter (Layer 1 — before any model runs) ──
            passed, reason = passes_fundamental_filter(ticker)
            if not passed:
                print(f"  {ticker} filtered: {reason}")
                continue

            # ── Liquidity check ──
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
            forecast_series, prophet_series, prophet_conf_width = ensemble_forecast(
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

            adjusted_peak = float(ensemble_window.max())
            weighted_roi = ((adjusted_peak - curr_price) / curr_price) * 100

            # ── Dates from Prophet ──
            prophet_window = prophet_series.iloc[TARGET_WINDOW_START:TARGET_WINDOW_END]
            min_hold_until = prophet_window.index[0]
            best_sell_date = prophet_window.idxmax()

            # Stock-specific expiry — when Prophet loses confidence
            forecast_expires = _get_confidence_expiry(
                prophet_series,
                prophet_conf_width
                if prophet_conf_width is not None
                else pd.Series(dtype=float),
                TARGET_WINDOW_START,
            )

            band_label = _get_band_label(curr_price)

            print(
                f"{ticker} | ₹{curr_price:.2f} [{band_label}] "
                f"| ROI: {weighted_roi:.1f}% "
                f"| Best sell: {best_sell_date.strftime('%b %Y')} "
                f"| Expires: {forecast_expires} "
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
                        "Forecast_Expires": forecast_expires,
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
