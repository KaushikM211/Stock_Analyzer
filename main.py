# ─────────────────────────────────────────────
# main.py — Entry point for GitHub Actions workflow
# ─────────────────────────────────────────────

from dotenv import load_dotenv

load_dotenv()  # Loads .env locally — no-op on GitHub Actions

import sys
from datetime import date
import pandas_market_calendars as mcal

from scanner import analyze_and_predict
from alerts import send_whatsapp_alert


def is_first_nse_trading_day_of_month(today: date) -> bool:
    """
    Dynamically checks if today is the first NSE trading day of the month
    using pandas_market_calendars — no hardcoded holiday list needed.
    Holidays update automatically when the package updates.

    GitHub Actions runs this on the 1st, 2nd, and 3rd via cron.
    Only one of those runs will pass this check and actually execute.
    """
    # Only bother checking the first 4 calendar days
    if today.day > 4:
        return False

    try:
        nse = mcal.get_calendar("NSE")

        # Get all valid trading sessions in this month up to today
        month_start = today.replace(day=1)
        schedule = nse.schedule(
            start_date=month_start.isoformat(),
            end_date=today.isoformat(),
        )

        if schedule.empty:
            return False

        # First trading day of the month is the first row in the schedule
        first_trading_day = schedule.index[0].date()
        return today == first_trading_day

    except Exception as e:
        # If calendar check fails for any reason, fall back to simple weekday check
        print(f"⚠️ Calendar check failed ({e}) — falling back to weekday check")
        return today.day == 1 and today.weekday() < 5


def main():
    today = date.today()

    # ── First business day guard ──
    # GitHub Actions runs on 1st, 2nd, 3rd of month
    # Only proceed if today is actually the first NSE trading day
    if not is_first_nse_trading_day_of_month(today):
        print(f"[{today}] Not the first NSE trading day of the month — skipping.")
        sys.exit(0)

    print(f"[{today}] First NSE trading day of the month — running analysis.")
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

    send_whatsapp_alert(results)


if __name__ == "__main__":
    main()
