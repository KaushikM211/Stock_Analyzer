# ─────────────────────────────────────────────
# scanner.py — Main Nifty 500 scanning loop
#
# v2 CHANGE: Fundamental filter is no longer a hard gate.
# All stocks with valid price data run through the full model ensemble.
# score_fundamental_risk() assigns Low/Medium/High labels AFTER
# forecasting. Results include Fundamental_Risk and Risk_Score columns.
# portfolio.py uses these to build risk-tiered combinations.
# ─────────────────────────────────────────────

import gc
import warnings
import pandas as pd
from datetime import date
from tqdm import tqdm

from .config import (
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
    MAX_SECTOR_PER_BAND,
    STCG_TAX_RATE,
    LTCG_TAX_RATE,
    LTCG_EXEMPTION,
    CESS_RATE,
    STT_RATE,
    LTCG_HOLD_DAYS,
    BEST_BUY_LOOKFORWARD_DAYS,
)
from core.data import (
    get_nifty500_tickers,
    fetch_best_available,
    fetch_sector_momentum,
    get_top_sectors,
    fetch_fundamentals,
    score_fundamental_risk,  # NEW — replaces passes_fundamental_filter
)
from core.ensemble import ensemble_forecast

warnings.filterwarnings("ignore")

CONFIDENCE_THRESHOLD = 0.43

# Execution slippage buffer — 2% conservative entry assumption
SLIPPAGE_BUFFER = 0.02


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


def _calculate_after_tax_roi(
    buy_price: float,
    sell_price: float,
    best_sell_date: pd.Timestamp,
    quantity: int = 100,
) -> tuple[float, float, str]:
    today = date.today()
    hold_trade_days = len(
        pd.bdate_range(
            start=today.isoformat(),
            end=best_sell_date.date().isoformat(),
        )
    )
    gross_profit = (sell_price - buy_price) * quantity
    gross_roi = (sell_price - buy_price) / buy_price * 100
    stt = (buy_price * quantity * STT_RATE) + (sell_price * quantity * STT_RATE)
    if hold_trade_days >= LTCG_HOLD_DAYS:
        taxable_gain = max(0, gross_profit - LTCG_EXEMPTION)
        tax = taxable_gain * LTCG_TAX_RATE
        tax_label = "LTCG"
    else:
        tax = gross_profit * STCG_TAX_RATE
        tax_label = "STCG"
    total_tax = tax * (1 + CESS_RATE) + stt
    net_profit = gross_profit - total_tax
    after_tax_roi = net_profit / (buy_price * quantity) * 100
    return round(gross_roi, 2), round(after_tax_roi, 2), tax_label


def _get_confidence_expiry(
    prophet_yhat: pd.Series,
    prophet_conf_width: pd.Series,
    window_start_idx: int,
) -> str:
    try:
        base_index = pd.bdate_range(
            start=prophet_yhat.index[0], periods=len(prophet_yhat)
        )
        yhat_aligned = prophet_yhat.reindex(base_index).interpolate()
        width_aligned = prophet_conf_width.reindex(base_index).interpolate()
        yhat_window = yhat_aligned.iloc[window_start_idx:]
        width_window = width_aligned.iloc[window_start_idx:]
        rel_width = width_window / (yhat_window.abs() + 1e-9)
        uncertain = rel_width[rel_width > CONFIDENCE_THRESHOLD]
        if not uncertain.empty:
            return uncertain.index[0].strftime("%d %b %Y")
        return yhat_window.index[-1].strftime("%d %b %Y")
    except Exception:
        return prophet_yhat.index[-1].strftime("%d %b %Y")


def _get_best_buy_date(
    forecast_series: "pd.Series",
    lookforward_days: int = BEST_BUY_LOOKFORWARD_DAYS,
) -> tuple[str, float]:
    if forecast_series is None or forecast_series.empty:
        return "N/A", 0.0
    window = forecast_series.iloc[:lookforward_days]
    if window.empty:
        window = forecast_series.iloc[:1]
    trough_idx = window.idxmin()
    trough_price = float(window.min())
    return trough_idx.strftime("%d %b %Y"), round(trough_price, 2)


def analyze_and_predict(
    lower_limit: int = LOWER_LIMIT,
    upper_limit: int = UPPER_LIMIT,
) -> dict[str, pd.DataFrame]:
    """
    Scans all Nifty 500 stocks.

    v2 changes vs v1:
      - Fundamental filter NO LONGER gates model execution.
        All stocks with clean price data run the full ensemble.
      - score_fundamental_risk() called AFTER forecasting — adds
        Fundamental_Risk (Low/Medium/High) and Risk_Score (0–100)
        to every result row.
      - MIN_WEIGHTED_ROI filter still applies to after-tax ROI.
      - Results include all risk tiers; portfolio.py splits by tier.
      - Log line now shows risk label alongside ROI for transparency.
    """
    tickers = get_nifty500_tickers()
    recommendations = []

    print("Fetching sector momentum scores...")
    sector_momentum = fetch_sector_momentum()
    top_sectors = get_top_sectors(sector_momentum)
    print(f"Top sectors by momentum: {top_sectors}\n")

    def _process_ticker(ticker: str) -> dict | None:
        try:
            close, volume = fetch_best_available(ticker)
            if close is None or len(close) < 60:
                return None

            curr_price = float(close.iloc[-1])
            if not (lower_limit <= curr_price <= upper_limit):
                return None

            execution_price = curr_price * (1 + SLIPPAGE_BUFFER)

            # ── Company metadata — always fetched, no longer a gate ──
            fundamentals = fetch_fundamentals(ticker)
            company_name = (
                fundamentals.get("company_name", ticker.replace(".NS", ""))
                if fundamentals
                else ticker.replace(".NS", "")
            )
            sector = (
                fundamentals.get("sector", "Unknown") if fundamentals else "Unknown"
            )

            # ── Liquidity check ──
            lookback = min(20, len(close))
            avg_daily_turnover = float(
                (close.tail(lookback) * volume.tail(lookback)).mean()
            )
            if avg_daily_turnover < MIN_AVG_DAILY_TURNOVER:
                return None

            liquidity = _liquidity_label(avg_daily_turnover)

            # ── Momentum pre-filter ──
            ma_short = close.iloc[-min(20, len(close)) :].mean()
            ma_long = close.mean()
            if ma_short < ma_long * MOMENTUM_TOLERANCE:
                return None

            # ── Ensemble forecast — runs for ALL stocks now ──
            forecast_series, prophet_series, prophet_conf_width = ensemble_forecast(
                close, volume, horizon=FORECAST_HORIZON
            )
            if forecast_series is None:
                return None

            # ── Risk scoring — AFTER forecast, not before ──
            # Does NOT gate execution — only produces a label for the user
            risk_label, risk_score, risk_reasons = score_fundamental_risk(ticker)

            # ── Best buy date ──
            best_buy_date_str, best_buy_price = _get_best_buy_date(forecast_series)

            ensemble_window = forecast_series.iloc[
                TARGET_WINDOW_START:TARGET_WINDOW_END
            ]
            if ensemble_window.empty:
                return None

            exit_target = float(ensemble_window.max())
            prophet_window = prophet_series.iloc[TARGET_WINDOW_START:TARGET_WINDOW_END]

            min_hold_until = pd.Timestamp(
                pd.bdate_range(
                    start=date.today().isoformat(),
                    periods=LTCG_HOLD_DAYS + 1,
                )[-1]
            )

            forecast_expires = _get_confidence_expiry(
                prophet_series,
                prophet_conf_width
                if prophet_conf_width is not None
                else pd.Series(dtype=float),
                TARGET_WINDOW_START,
            )

            forecast_expires_dt = pd.Timestamp(
                pd.to_datetime(forecast_expires, format="%d %b %Y")
            )
            confident_window = prophet_window[
                prophet_window.index <= forecast_expires_dt
            ]
            best_sell_date = (
                confident_window.idxmax()
                if not confident_window.empty
                else prophet_window.idxmax()
            )

            min_hold_dt = prophet_window.index[0]
            confident_days = (forecast_expires_dt - min_hold_dt).days
            if confident_days < 30:
                print(
                    f"  {ticker} skipped: confident window only {confident_days} days"
                )
                return None

            gross_roi, after_tax_roi, tax_label = _calculate_after_tax_roi(
                buy_price=execution_price,
                sell_price=exit_target,
                best_sell_date=best_sell_date,
            )

            band_label = _get_band_label(curr_price)

            # ── Log line now shows risk label ──
            print(
                f"{ticker} | ₹{curr_price:.2f} [{band_label}] "
                f"| Net: {after_tax_roi:.1f}% ({tax_label}) "
                f"| Risk: {risk_label} ({risk_score:.0f}) "
                f"| Sell: {best_sell_date.strftime('%b %Y')} "
                f"| ₹{avg_daily_turnover / 1e7:.1f}Cr/day"
            )

            if after_tax_roi < MIN_WEIGHTED_ROI:
                return None

            return {
                "Price_Band": band_label,
                "Stock": ticker,
                "Company_Name": company_name,
                "Sector": sector,
                "Buy_Price": round(curr_price, 2),
                "Exit_Target": round(exit_target, 2),
                "Gross_ROI_%": gross_roi,
                "After_Tax_ROI_%": after_tax_roi,
                "Tax_Type": tax_label,
                "Min_Hold_Until": min_hold_until.strftime("%d %b %Y"),
                "Best_Sell_Date": best_sell_date.strftime("%d %b %Y"),
                "Forecast_Expires": forecast_expires,
                "Avg_Daily_Turnover_Cr": round(avg_daily_turnover / 1e7, 2),
                "Liquidity": liquidity,
                "Data_Days": len(close),
                "Predicted_Best_Buy_Date": best_buy_date_str,
                "Predicted_Best_Buy_Price": best_buy_price,
                # ── New risk columns ──
                "Fundamental_Risk": risk_label,  # "Low" / "Medium" / "High"
                "Risk_Score": risk_score,  # 0–100 float
                "Risk_Reasons": "; ".join(risk_reasons[:2]),  # top 2 reasons for email
            }

        except Exception as e:
            print(f"{ticker}: {type(e).__name__}: {e}")
            return None

    # Sequential scan — parallel caused yfinance data collisions
    for ticker in tqdm(tickers, desc="Scanning Nifty 500"):
        result = _process_ticker(ticker)
        if result is not None:
            recommendations.append(result)
    gc.collect()

    if not recommendations:
        return {}

    df_all = pd.DataFrame(recommendations)

    # Sort by after-tax ROI within each band, respecting sector cap
    # Band output includes ALL risk tiers — portfolio.py filters by tier
    results = {}
    for low, high in PRICE_BANDS:
        label = f"₹{low}–₹{high}"
        band_df = (
            df_all[df_all["Price_Band"] == label]
            .sort_values(by="After_Tax_ROI_%", ascending=False)
            .reset_index(drop=True)
        )
        if band_df.empty:
            continue

        # Sector-aware selection — sector cap applied within each risk tier
        # so a sector doesn't dominate even within a single band
        selected = []
        sector_count = {}
        for _, row in band_df.iterrows():
            s = row.get("Sector", "Unknown")
            if sector_count.get(s, 0) < MAX_SECTOR_PER_BAND:
                selected.append(row)
                sector_count[s] = sector_count.get(s, 0) + 1
            if len(selected) >= TOP_N_PER_BAND:
                break

        if selected:
            results[label] = pd.DataFrame(selected).reset_index(drop=True)

    # Summary log
    for tier in ["Low", "Medium", "High"]:
        n = (df_all["Fundamental_Risk"] == tier).sum()
        print(f"  Risk tier — {tier}: {n} stocks passed ROI threshold")
    print(
        f"  Full pool: {len(df_all)} stocks → band caps produce {sum(len(v) for v in results.values())} in email"
    )

    # Store the full pre-cap pool under _full_pool so log_predictions
    # logs ALL stocks that passed ROI, not just the top-N per band.
    results["_full_pool"] = df_all.reset_index(drop=True)

    return results


def get_full_pool(
    lower_limit: int = LOWER_LIMIT,
    upper_limit: int = UPPER_LIMIT,
) -> pd.DataFrame:
    results = analyze_and_predict(lower_limit, upper_limit)
    if not results:
        return pd.DataFrame()
    frames = []
    for band_label, df in results.items():
        if band_label.startswith("_"):
            continue
        d = df.copy()
        d["Band"] = band_label
        frames.append(d)
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values("After_Tax_ROI_%", ascending=False)
        .reset_index(drop=True)
    )
