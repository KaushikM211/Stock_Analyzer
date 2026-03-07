# ─────────────────────────────────────────────
# main.py — Entry point for GitHub Actions workflow
# ─────────────────────────────────────────────

from dotenv import load_dotenv

import sys
import pandas as pd
from datetime import date
import pandas_market_calendars as mcal

from scanner import analyze_and_predict
from portfolio import build_portfolios, MONTHLY_BUDGET
from alerts import send_email_alert

load_dotenv()


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


def run_analysis():
    print("=" * 60)
    print("  Nifty 500 — Prescriptive Stock Analyzer")
    print("=" * 60 + "\n")

    # ── Band-wise top 5 picks ──
    results = analyze_and_predict()

    if not results:
        print("\nNo stocks met the criteria this month.")
        send_email_alert(results, portfolios=[])
        return

    for band_label, df in results.items():
        print(f"\n{'─' * 50}")
        print(f"  {band_label}  —  Top {len(df)} picks")
        print(f"{'─' * 50}")
        print(df.to_string(index=False))

    # ── Portfolio combinations ──
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
        print(
            combo["portfolio"][
                [
                    "Stock",
                    "Shares",
                    "Invested",
                    "Exit_Value",
                    "Net_Profit",
                    "Net_ROI_%",
                    "Best_Sell_Date",
                ]
            ].to_string(index=False)
        )

    send_email_alert(results, portfolios=portfolios)


def main():
    args = sys.argv[1:]
    today = date.today()

    if "--test-email" in args:
        print(f"[{today}] Testing email connection...")
        dummy_results = {
            "₹150–₹500": pd.DataFrame(
                [
                    {
                        "Price_Band": "₹150–₹500",
                        "Stock": "TEST.NS",
                        "Buy_Price": 100.0,
                        "Exit_Target": 130.0,
                        "Gross_ROI_%": 30.0,
                        "After_Tax_ROI_%": 27.5,
                        "Tax_Type": "LTCG",
                        "Min_Hold_Until": "24 Feb 2027",
                        "Best_Sell_Date": "15 Nov 2027",
                        "Forecast_Expires": "01 Mar 2028",
                        "Avg_Daily_Turnover_Cr": 50.0,
                        "Liquidity": "High",
                        "Data_Days": 495,
                    }
                ]
            )
        }
        dummy_portfolios = build_portfolios(dummy_results)
        send_email_alert(dummy_results, portfolios=dummy_portfolios, debug=True)
        return

    if "--force" in args:
        print(f"[{today}] Force run — bypassing date guard.")
        run_analysis()
        return

    if not is_first_nse_trading_day_of_month(today):
        print(f"[{today}] Not the first NSE trading day of the month — skipping.")
        sys.exit(0)

    print(f"[{today}] First NSE trading day of the month — running analysis.")
    run_analysis()


if __name__ == "__main__":
    main()
