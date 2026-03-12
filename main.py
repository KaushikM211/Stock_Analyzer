# ─────────────────────────────────────────────
# main.py — Entry point for GitHub Actions workflow
# ─────────────────────────────────────────────

import os
import sys
import pandas as pd
from datetime import date
import pandas_market_calendars as mcal

from scanner import analyze_and_predict
from portfolio import build_portfolios, MONTHLY_BUDGET
from alerts import send_email_alert
from consolidate import save_run_results, check_and_alert
from dotenv import load_dotenv

load_dotenv()


def is_nse_trading_day(today: date) -> bool:
    """Returns True if today is an NSE trading day."""
    try:
        nse = mcal.get_calendar("NSE")
        schedule = nse.schedule(
            start_date=today.isoformat(),
            end_date=today.isoformat(),
        )
        return not schedule.empty
    except Exception as e:
        print(f"⚠️ Calendar check failed ({e}) — assuming trading day")
        return today.weekday() < 5


def is_first_nse_trading_day_of_month(today: date) -> bool:
    if today.day > 5:
        return False
    try:
        nse = mcal.get_calendar("NSE")
        month_start = today.replace(day=1)
        schedule = nse.schedule(
            start_date=month_start.isoformat(),
            end_date=today.isoformat(),
        )
        if schedule.empty:
            return False
        return today == schedule.index[0].date()
    except Exception as e:
        print(f"⚠️ Calendar check failed ({e}) — falling back to weekday check")
        return today.day == 1 and today.weekday() < 5


def run_analysis(run_label: str = "manual", send_full_email: bool = True):
    """
    Runs the full scan, builds portfolios, saves results.

    run_label       — e.g. "Pre-Market 09:00", "Live-1 10:30" etc.
    send_full_email — if True, sends the full band picks + portfolio email
                      if False, only checks for improvement and alerts if needed
    """
    print("=" * 60)
    print(f"  Nifty 500 — Prescriptive Stock Analyzer [{run_label}]")
    print("=" * 60 + "\n")

    results = analyze_and_predict()

    if not results:
        print("\nNo stocks met the criteria this run.")
        if send_full_email:
            send_email_alert(results, portfolios=[])
        return

    for band_label, df in results.items():
        print(f"\n{'─' * 50}")
        print(f"  {band_label}  —  Top {len(df)} picks")
        print(f"{'─' * 50}")
        print(df.to_string(index=False))

    print(f"\n{'=' * 60}")
    print(f"  Building 10 Portfolio Combinations (₹{MONTHLY_BUDGET:,}/month)")
    print(f"{'=' * 60}\n")

    portfolios = build_portfolios(results)

    for i, combo in enumerate(portfolios):
        s = combo["summary"]
        print(f"\n{'─' * 50}")
        print(f"  #{i + 1} {combo['name']}")
        print(f"  {combo['description']}")
        print(f"{'─' * 50}")
        print(
            f"  Invested: ₹{s['Total_Invested']:,}  |  "
            f"Net Profit: ₹{s['Total_Net_Profit']:,}  |  "
            f"Portfolio ROI: {s['Portfolio_ROI_%']}%"
        )
        cols = [
            c
            for c in [
                "Stock",
                "Company_Name",
                "Shares",
                "Invested",
                "Exit_Value",
                "Net_Profit",
                "Net_ROI_%",
                "Best_Sell_Date",
            ]
            if c in combo["portfolio"].columns
        ]
        print(combo["portfolio"][cols].to_string(index=False))

    # ── Save results for intraday comparison ──
    results_dir = os.getenv("SCAN_RESULTS_DIR", "/tmp/scan_results")
    save_run_results(results, portfolios, run_label, results_dir)

    # ── Send full email (Run 1 / monthly runs) ──
    if send_full_email:
        send_email_alert(results, portfolios=portfolios)

    # ── Check for improvement vs previous runs today (Run 2, 3, 4) ──
    else:
        check_and_alert(results, portfolios, run_label, results_dir)


def main():
    args = sys.argv[1:]
    today = date.today()

    # ── Test email ──
    if "--test-email" in args:
        print(f"[{today}] Testing email connection...")
        dummy_results = {
            "₹150–₹500": pd.DataFrame(
                [
                    {
                        "Price_Band": "₹150–₹500",
                        "Stock": "TEST.NS",
                        "Company_Name": "Test Company Ltd",
                        "Buy_Price": 100.0,
                        "Exit_Target": 130.0,
                        "Gross_ROI_%": 30.0,
                        "After_Tax_ROI_%": 27.5,
                        "Tax_Type": "LTCG",
                        "Min_Hold_Until": "10 Mar 2027",
                        "Best_Sell_Date": "15 Nov 2027",
                        "Forecast_Expires": "01 Mar 2028",
                        "Avg_Daily_Turnover_Cr": 50.0,
                        "Liquidity": "High",
                        "Data_Days": 495,
                        "Sector": "Technology",
                    }
                ]
            )
        }
        dummy_portfolios = build_portfolios(dummy_results)
        send_email_alert(dummy_results, portfolios=dummy_portfolios, debug=True)
        return

    # ── Force full run ──
    if "--force" in args:
        print(f"[{today}] Force run — bypassing date guard.")
        run_analysis(run_label="Force Run", send_full_email=True)
        return

    # ── Intraday improvement run (Run 2, 3, 4) ──
    # Passed as: python main.py --intraday "Live-1 10:30"
    if "--intraday" in args:
        idx = args.index("--intraday")
        label = args[idx + 1] if idx + 1 < len(args) else "Intraday"
        if not is_nse_trading_day(today):
            print(f"[{today}] Not an NSE trading day — skipping intraday run.")
            sys.exit(0)
        print(f"[{today}] Intraday run — {label}")
        run_analysis(run_label=label, send_full_email=False)
        return

    # ── Default: first NSE trading day of month (full email) ──
    if not is_nse_trading_day(today):
        print(f"[{today}] Not an NSE trading day — skipping.")
        sys.exit(0)

    if not is_first_nse_trading_day_of_month(today):
        print(f"[{today}] Not the first NSE trading day of the month — skipping.")
        sys.exit(0)

    print(f"[{today}] First NSE trading day of the month — running full analysis.")
    run_analysis(run_label="Monthly Run", send_full_email=True)


if __name__ == "__main__":
    main()
