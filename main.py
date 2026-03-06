# ─────────────────────────────────────────────
# main.py — Entry point for GitHub Actions workflow
# ─────────────────────────────────────────────

from dotenv import load_dotenv

load_dotenv()  # Loads .env locally — no-op on GitHub Actions

import sys
from datetime import date
import pandas_market_calendars as mcal

from scanner import analyze_and_predict
from alerts import send_email_alert


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
        first_trading_day = schedule.index[0].date()
        return today == first_trading_day
    except Exception as e:
        print(f"⚠️ Calendar check failed ({e}) — falling back to weekday check")
        return today.day == 1 and today.weekday() < 5


def run_analysis():
    """Runs the full analysis and sends email alert."""
    print("=" * 55)
    print("  Nifty 500 — Prescriptive Stock Analyzer")
    print("=" * 55 + "\n")

    results = analyze_and_predict()

    if not results:
        print("\nNo stocks met the criteria this month.")
    else:
        for band_label, df in results.items():
            print(f"\n{'─' * 45}")
            print(f"  {band_label}  —  Top {len(df)} picks")
            print(f"{'─' * 45}")
            print(df.to_string(index=False))

    send_email_alert(results)


def main():
    args = sys.argv[1:]
    today = date.today()

    # ── --test-email: send a dummy email to verify credentials ──
    if "--test-email" in args:
        print(f"[{today}] Testing email connection...")
        import pandas as pd

        dummy = {
            "₹150–₹500": pd.DataFrame(
                [
                    {
                        "Price_Band": "₹150–₹500",
                        "Stock": "TEST.NS",
                        "Buy_Price": 100.00,
                        "Exit_Target": 120.00,
                        "Weighted_ROI_%": 20.00,
                        "Min_Hold_Until": "01 Nov 2026",
                        "Best_Sell_Date": "15 Jan 2027",
                        "Forecast_Expires": "23 Feb 2027",
                        "Avg_Daily_Turnover_Cr": 50.00,
                        "Liquidity": "High",
                        "Data_Days": 495,
                    }
                ]
            )
        }
        send_email_alert(dummy, debug=True)
        return

    # ── --force: bypass date guard and run full analysis ──
    if "--force" in args:
        print(f"[{today}] Force run — bypassing date guard.")
        run_analysis()
        return

    # ── Normal scheduled run ──
    if not is_first_nse_trading_day_of_month(today):
        print(f"[{today}] Not the first NSE trading day of the month — skipping.")
        sys.exit(0)

    print(f"[{today}] First NSE trading day of the month — running analysis.")
    run_analysis()


if __name__ == "__main__":
    main()
