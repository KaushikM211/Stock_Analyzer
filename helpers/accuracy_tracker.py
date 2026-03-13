# ─────────────────────────────────────────────
# accuracy_tracker.py — Tracks prediction accuracy over time
#
# Runs daily. For each stock where Predicted_Best_Buy_Date == yesterday:
#   1. Fetches actual closing price from yfinance
#   2. Compares vs Predicted_Best_Buy_Price
#   3. Appends result to accuracy_log.csv in repo
#   4. Emails a summary of the comparison
#
# Over months this builds a genuine model calibration scorecard.
# ─────────────────────────────────────────────

import os
import json
import glob
import subprocess
from datetime import date, timedelta
from .alerts import send_accuracy_email
import pandas as pd
import yfinance as yf


ACCURACY_LOG = "accuracy_log.csv"
LOG_COLUMNS = [
    "Date_Checked",
    "Stock",
    "Company_Name",
    "Predicted_Buy_Date",
    "Predicted_Buy_Price",
    "Actual_Close",
    "Error_Pct",
    "Direction",
    "Scan_Date",
    "After_Tax_ROI_Predicted",
]


def _load_accuracy_log() -> pd.DataFrame:
    """Loads existing accuracy log or creates empty one."""
    if os.path.exists(ACCURACY_LOG):
        try:
            return pd.read_csv(ACCURACY_LOG)
        except Exception:
            pass
    return pd.DataFrame(columns=LOG_COLUMNS)


def _save_accuracy_log(df: pd.DataFrame):
    """Saves accuracy log to CSV and commits to repo."""
    df.to_csv(ACCURACY_LOG, index=False)
    print(f"  ✓ Accuracy log saved → {ACCURACY_LOG} ({len(df)} records)")

    # Commit to repo if running in GitHub Actions
    if os.getenv("GITHUB_ACTIONS"):
        try:
            subprocess.run(
                ["git", "config", "user.email", "actions@github.com"], check=True
            )
            subprocess.run(["git", "config", "user.name", "GitHub Actions"], check=True)
            subprocess.run(["git", "add", ACCURACY_LOG], check=True)
            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"], capture_output=True
            )
            if result.returncode != 0:
                subprocess.run(
                    ["git", "commit", "-m", f"accuracy log update {date.today()}"],
                    check=True,
                )
                token = os.getenv("GITHUB_TOKEN", "")
                repo = os.getenv("GITHUB_REPOSITORY", "")
                branch = os.getenv("GITHUB_REF_NAME", "main")
                remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
                subprocess.run(
                    ["git", "push", remote_url, f"HEAD:{branch}"], check=True
                )
                print(f"  ✓ Accuracy log committed to {branch}")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ Git commit failed: {e}")


def _fetch_actual_price(ticker: str, target_date: date) -> float | None:
    """
    Fetches actual closing price for a ticker on a specific date.
    If market was closed that day, returns next available close.
    """
    try:
        start = target_date.isoformat()
        end = (target_date + timedelta(days=5)).isoformat()
        data = yf.download(
            ticker, start=start, end=end, progress=False, auto_adjust=True
        )
        if data.empty:
            return None
        return round(float(data["Close"].iloc[0]), 2)
    except Exception as e:
        print(f"  ⚠ Could not fetch {ticker} for {target_date}: {e}")
        return None


def _pull_scan_history() -> list[dict]:
    """
    Pulls all historical scan results from results-cache branch.
    Each scan JSON has Predicted_Best_Buy_Date for each stock.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    branch = "results-cache"

    if not token or not os.getenv("GITHUB_ACTIONS"):
        # Local — read from /tmp/scan_results
        files = sorted(glob.glob("/tmp/scan_results/scan_*.json"))
        records = []
        for f in files:
            try:
                with open(f) as fh:
                    records.append(json.load(fh))
            except Exception:
                pass
        return records

    try:
        remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        subprocess.run(
            ["git", "fetch", remote_url, branch], check=True, capture_output=True
        )
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD"],
            capture_output=True,
            text=True,
        )
        files = [f for f in result.stdout.splitlines() if f.startswith("cache/scan_")]

        records = []
        for f in files:
            content = subprocess.run(
                ["git", "show", f"FETCH_HEAD:{f}"], capture_output=True
            )
            try:
                records.append(json.loads(content.stdout))
            except Exception:
                pass
        return records

    except subprocess.CalledProcessError as e:
        print(f"  ⚠ Could not pull scan history: {e}")
        return []


def check_predictions(target_date: date | None = None) -> pd.DataFrame:
    """
    Main entry point.
    Checks all past scans for stocks where Predicted_Best_Buy_Date == target_date.
    Fetches actual prices and logs accuracy.

    target_date defaults to yesterday (the most recently completed trading day).
    """

    if target_date is None:
        target_date = date.today() - timedelta(days=1)
        # If yesterday was weekend, go back to Friday
        while target_date.weekday() >= 5:
            target_date -= timedelta(days=1)

    target_str = target_date.strftime("%d %b %Y")
    print(f"\n  📊 Accuracy check for predicted buy date: {target_str}")

    scan_history = _pull_scan_history()
    accuracy_log = _load_accuracy_log()
    new_records = []

    for scan in scan_history:
        scan_date = scan.get("date", "")
        results = scan.get("results", {})

        for band, stocks in results.items():
            for stock in stocks:
                predicted_date = stock.get("Predicted_Best_Buy_Date", "")
                if predicted_date != target_str:
                    continue

                ticker = stock.get("Stock", "")
                company = stock.get("Company_Name", "")
                pred_price = float(stock.get("Predicted_Best_Buy_Price", 0))
                pred_roi = float(stock.get("After_Tax_ROI_%", 0))

                if not ticker or not pred_price:
                    continue

                # Check if already logged
                already_logged = (
                    not accuracy_log.empty
                    and len(
                        accuracy_log[
                            (accuracy_log["Stock"] == ticker)
                            & (accuracy_log["Predicted_Buy_Date"] == target_str)
                        ]
                    )
                    > 0
                )
                if already_logged:
                    print(f"  ↩ {ticker} already logged for {target_str}")
                    continue

                # Fetch actual closing price
                actual_price = _fetch_actual_price(ticker, target_date)
                if actual_price is None:
                    print(f"  ⚠ {ticker}: no actual price found for {target_str}")
                    continue

                error_pct = (actual_price - pred_price) / pred_price * 100
                direction = "UNDER" if actual_price < pred_price else "OVER"

                record = {
                    "Date_Checked": date.today().isoformat(),
                    "Stock": ticker,
                    "Company_Name": company,
                    "Predicted_Buy_Date": target_str,
                    "Predicted_Buy_Price": pred_price,
                    "Actual_Close": actual_price,
                    "Error_Pct": round(error_pct, 2),
                    "Direction": direction,
                    "Scan_Date": scan_date,
                    "After_Tax_ROI_Predicted": pred_roi,
                }
                new_records.append(record)
                print(
                    f"  {ticker:20s} Predicted: ₹{pred_price} | "
                    f"Actual: ₹{actual_price} | "
                    f"Error: {error_pct:+.2f}% ({direction})"
                )

    if not new_records:
        print(f"  ℹ No stocks had predicted buy date of {target_str}")
        return accuracy_log

    new_df = pd.DataFrame(new_records)
    accuracy_log = pd.concat([accuracy_log, new_df], ignore_index=True)
    _save_accuracy_log(accuracy_log)

    # ── Summary stats ──
    mae = new_df["Error_Pct"].abs().mean()
    bias = new_df["Error_Pct"].mean()
    under = len(new_df[new_df["Direction"] == "UNDER"])
    over = len(new_df[new_df["Direction"] == "OVER"])

    print(f"\n  📈 Accuracy Summary for {target_str}:")
    print(f"     Stocks checked: {len(new_df)}")
    print(f"     MAE:            {mae:.2f}%")
    print(
        f"     Bias:           {bias:+.2f}% ({'overestimates' if bias > 0 else 'underestimates'} price)"
    )
    print(f"     Under predicted: {under} | Over predicted: {over}")

    # Send accuracy email
    send_accuracy_email(
        target_date=target_str,
        new_records=new_records,
        full_log=accuracy_log,
        mae=mae,
        bias=bias,
    )

    return accuracy_log
