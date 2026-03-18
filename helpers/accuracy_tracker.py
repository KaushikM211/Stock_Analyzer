# ─────────────────────────────────────────────
# accuracy_tracker.py — Tracks prediction accuracy and convergence
#
# Design:
#   Every 30-min run logs its Predicted_Best_Buy_Date + Price per stock
#   When the predicted date arrives → fetch actual price → compute error
#
#   Two things tracked:
#     1. Accuracy     — how close predicted price was to actual price
#     2. Convergence  — how many runs agreed on the same predicted date
#
#   Over months this builds per-stock confidence scores:
#     "IIFL: 80% accuracy + 90% convergence → strong buy signal"
#     "UPL:  45% accuracy + 50% convergence → do more research"
#
#   Convergence shown in monthly email as 🟢 / 🟡 / 🔴
#   Accuracy shown as historical hit rate (within 3% threshold)
# ─────────────────────────────────────────────

import os
import json
import glob
import subprocess
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

ACCURACY_LOG = "accuracy_log.csv"
PREDICTION_LOG = "prediction_log.csv"  # all run predictions before actuals known
ACCURACY_THRESHOLD = 3.0  # % error considered accurate
CONVERGENCE_HIGH = 0.75  # 75%+ runs agree → 🟢
CONVERGENCE_MED = 0.50  # 50%+ runs agree → 🟡
# below 50%       → 🔴

LOG_COLUMNS = [
    "Scan_Date",
    "Run_Time",
    "Run_Label",
    "Stock",
    "Company_Name",
    "Predicted_Buy_Date",
    "Predicted_Buy_Price",
    "Actual_Open",  # day's Low on predicted buy date — achievable intraday entry
    "Actual_Price_Date",
    "Error_Pct",
    "Direction",
    "Within_Threshold",  # True if abs(error) <= ACCURACY_THRESHOLD
    "Note",
]

PRED_COLUMNS = [
    "Scan_Date",
    "Run_Time",
    "Run_Label",
    "Stock",
    "Company_Name",
    "Predicted_Buy_Date",
    "Predicted_Buy_Price",
]


# ─────────────────────────────────────────────
# Storage helpers
# ─────────────────────────────────────────────


def _load_csv(path: str, columns: list) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            # Handle column renames gracefully — migrate old names to new ones
            rename_map = {
                "Actual_Close": "Actual_Open",  # renamed when switched from close to open
                "Actual_Low": "Actual_Open",  # renamed when switched from low to open
            }
            df = df.rename(
                columns={k: v for k, v in rename_map.items() if k in df.columns}
            )
            # Add any missing columns with empty values
            for col in columns:
                if col not in df.columns:
                    df[col] = ""
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=columns)


def _save_csv(df: pd.DataFrame, path: str, label: str):
    df.to_csv(path, index=False)
    print(f"  ✓ {label} saved → {path} ({len(df)} records)")


def _commit_logs():
    """Commits accuracy_log.csv and prediction_log.csv to repo."""
    if not os.getenv("GITHUB_ACTIONS"):
        return
    try:
        token = os.getenv("GITHUB_TOKEN", "")
        repo = os.getenv("GITHUB_REPOSITORY", "")
        branch = os.getenv("GITHUB_REF_NAME", "main")
        subprocess.run(
            ["git", "config", "user.email", "actions@github.com"], check=True
        )
        subprocess.run(["git", "config", "user.name", "GitHub Actions"], check=True)
        subprocess.run(["git", "add", ACCURACY_LOG, PREDICTION_LOG], check=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], capture_output=True
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", f"accuracy + prediction log {date.today()}"],
                check=True,
            )
            remote = f"https://x-access-token:{token}@github.com/{repo}.git"
            subprocess.run(["git", "push", remote, f"HEAD:{branch}"], check=True)
            print(f"  ✓ Logs committed to {branch}")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠ Git commit failed: {e}")


# ─────────────────────────────────────────────
# Fetch actual price
# ─────────────────────────────────────────────


def _fetch_actual_price(ticker: str, target_date: date) -> tuple[float | None, str]:
    """
    Fetches the day's OPEN price on target_date (or next available trading day).

    Why Open instead of Low or Close:
        The accuracy check runs at 9:20 AM IST — 5 mins after market opens.
        The opening price is:
          1. Available immediately at market open
          2. The actual price you'd pay if you act on the accuracy signal now
          3. A clean, unambiguous reference — not a moving target like intraday Low
          4. Reflects overnight sentiment and gap ups/downs

        If predicted price ≈ open price → model was right, buy now.
        If open is significantly higher → stock gapped up, entry may have passed.
        If open is significantly lower → stock gapped down, even better entry.

    Fetches up to 5 days forward to handle holidays and weekends.
    """
    try:
        start = target_date.isoformat()
        end = (target_date + timedelta(days=5)).isoformat()

        data = yf.Ticker(ticker).history(
            start=start,
            end=end,
            auto_adjust=True,
        )

        if data.empty:
            return None, ""

        # Strip timezone
        if data.index.tz is not None:
            data.index = data.index.tz_localize(None)

        # Handle multi-level columns
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Use the first available trading day's OPEN price
        open_price = data["Open"]
        if isinstance(open_price, pd.DataFrame):
            open_price = open_price.iloc[:, 0]
        open_price = open_price.dropna()

        if open_price.empty:
            return None, ""

        actual_price = round(float(open_price.iloc[0]), 2)
        actual_date = open_price.index[0].strftime("%Y-%m-%d")
        return actual_price, actual_date

    except Exception as e:
        print(f"  ⚠ Could not fetch {ticker} for {target_date}: {e}")
        return None, ""


# ─────────────────────────────────────────────
# Pull scan history from results-cache branch
# ─────────────────────────────────────────────


def _pull_scan_history() -> list[dict]:
    """Pulls all scan JSONs from results-cache branch."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    branch = "results-cache"

    if not token or not os.getenv("GITHUB_ACTIONS"):
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
        remote = f"https://x-access-token:{token}@github.com/{repo}.git"
        subprocess.run(
            ["git", "fetch", remote, branch], check=True, capture_output=True
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


# ─────────────────────────────────────────────
# Step 1 — Log predictions from current run
# ─────────────────────────────────────────────


def log_predictions(results: dict, run_label: str) -> None:
    """
    Logs each stock's Predicted_Best_Buy_Date + Price to prediction_log.csv.

    Uses results["_full_pool"] when available — the complete set of stocks
    that passed ROI threshold BEFORE per-band top-N cap. This means we
    log all ~100-200 passing stocks, not just the ~45-70 in the email.

    Falls back to iterating band keys if _full_pool absent (backwards compat).
    """
    today = date.today().isoformat()
    run_time = __import__("datetime").datetime.now().strftime("%H:%M")

    pred_log = _load_csv(PREDICTION_LOG, PRED_COLUMNS)
    new_rows = []

    # ── Build stock_list from full pool or band keys ──
    if "_full_pool" in results:
        full = results["_full_pool"]
        stock_list = (
            full.to_dict(orient="records")
            if isinstance(full, pd.DataFrame)
            else list(full)
        )
        source = f"full pool ({len(stock_list)} stocks)"
    else:
        stock_list = []
        for band, stocks in results.items():
            if band.startswith("_"):
                continue
            rows = (
                stocks.to_dict(orient="records")
                if isinstance(stocks, pd.DataFrame)
                else list(stocks)
            )
            stock_list.extend(rows)
        source = f"band keys ({len(stock_list)} stocks)"

    # ── Build log rows ──
    for stock in stock_list:
        pred_date = stock.get("Predicted_Best_Buy_Date", "")
        pred_price = stock.get("Predicted_Best_Buy_Price", "")
        ticker = stock.get("Stock", "")
        company = stock.get("Company_Name", "")
        if not ticker or not pred_date or pred_date == "N/A":
            continue
        new_rows.append(
            {
                "Scan_Date": today,
                "Run_Time": run_time,
                "Run_Label": run_label,
                "Stock": ticker,
                "Company_Name": company,
                "Predicted_Buy_Date": pred_date,
                "Predicted_Buy_Price": pred_price,
            }
        )

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        pred_log = pd.concat([pred_log, new_df], ignore_index=True)
        # Deduplicate — same stock from same run should never appear twice
        pred_log = pred_log.drop_duplicates(
            subset=["Scan_Date", "Run_Time", "Stock"], keep="last"
        )
        _save_csv(pred_log, PREDICTION_LOG, "Prediction log")
        print(
            f"  📝 Logged {len(new_rows)} predictions from {run_label} (source: {source})"
        )
    else:
        print(f"  ℹ No predictions to log from {run_label}")


# ─────────────────────────────────────────────
# Step 2 — Compute convergence per stock
# ─────────────────────────────────────────────


def get_convergence(
    pred_log: pd.DataFrame,
    stock: str,
    as_of_date: str | None = None,
) -> dict:
    """
    For a given stock, computes:
      - Most predicted buy date (mode across all DISTINCT runs)
      - Convergence score (% of distinct runs that agree on that date)
      - Convergence label 🟢 / 🟡 / 🔴
      - Predicted price range (min/max across runs)

    Distinct run = unique (Scan_Date, Run_Time) combination.
    Deduplicates before counting so a stock logged twice in one run
    doesn't inflate convergence artificially.
    """
    df = pred_log[pred_log["Stock"] == stock].copy()
    if as_of_date:
        df = df[df["Scan_Date"] <= as_of_date]
    if df.empty:
        return {}

    # Deduplicate — keep one row per distinct run per stock
    df = df.drop_duplicates(subset=["Scan_Date", "Run_Time", "Stock"])

    total_runs = len(df)
    date_counts = df["Predicted_Buy_Date"].value_counts()
    top_date = date_counts.index[0]
    top_count = int(date_counts.iloc[0])
    convergence = top_count / total_runs

    if convergence >= CONVERGENCE_HIGH:
        label = "🟢 High"
    elif convergence >= CONVERGENCE_MED:
        label = "🟡 Medium"
    else:
        label = "🔴 Low"

    top_df = df[df["Predicted_Buy_Date"] == top_date]
    prices = pd.to_numeric(top_df["Predicted_Buy_Price"], errors="coerce").dropna()

    return {
        "Stock": stock,
        "Best_Buy_Date": top_date,
        "Convergence_Pct": round(convergence * 100, 1),
        "Convergence_Label": label,
        "Runs_Agreeing": top_count,
        "Total_Runs": total_runs,
        "Price_Min": round(float(prices.min()), 2) if not prices.empty else None,
        "Price_Max": round(float(prices.max()), 2) if not prices.empty else None,
        "Price_Median": round(float(prices.median()), 2) if not prices.empty else None,
    }


def get_all_convergence(pred_log: pd.DataFrame) -> dict[str, dict]:
    """Returns convergence data for all stocks in prediction log."""
    return {
        stock: get_convergence(pred_log, stock) for stock in pred_log["Stock"].unique()
    }


# ─────────────────────────────────────────────
# Step 3 — Historical accuracy per stock
# ─────────────────────────────────────────────


def get_historical_accuracy(acc_log: pd.DataFrame, stock: str) -> dict:
    """
    Returns historical accuracy stats for a stock:
      - Total predictions checked
      - Hit rate (within ACCURACY_THRESHOLD %)
      - Average error
      - Bias (positive = model underestimates price)
    """
    df = acc_log[acc_log["Stock"] == stock] if not acc_log.empty else pd.DataFrame()
    if df.empty:
        return {
            "Stock": stock,
            "Total": 0,
            "Hit_Rate_Pct": None,
            "Avg_Error_Pct": None,
            "Bias_Pct": None,
        }

    total = len(df)
    hits = len(df[df["Within_Threshold"]])
    avg_err = round(df["Error_Pct"].abs().mean(), 2)
    bias = round(df["Error_Pct"].mean(), 2)

    return {
        "Stock": stock,
        "Total": total,
        "Hit_Rate_Pct": round(hits / total * 100, 1),
        "Avg_Error_Pct": avg_err,
        "Bias_Pct": bias,
    }


# ─────────────────────────────────────────────
# Step 4 — Build combined signal per stock
# ─────────────────────────────────────────────


def get_signal(convergence: dict, accuracy: dict) -> str:
    """
    Combines convergence + historical accuracy into a single signal:
      STRONG  → high convergence + good historical accuracy
      MODERATE → medium convergence or moderate accuracy
      WEAK    → low convergence or poor accuracy
      NEW     → not enough history yet (< 3 data points)
    """
    total = accuracy.get("Total", 0)
    if total < 3:
        return "🆕 NEW — insufficient history"

    conv = convergence.get("Convergence_Pct", 0)
    hit = accuracy.get("Hit_Rate_Pct", 0)

    if conv >= 75 and hit >= 70:
        return "🟢 STRONG — high confidence"
    elif conv >= 50 and hit >= 50:
        return "🟡 MODERATE — verify on Groww/news"
    else:
        return "🔴 WEAK — low confidence, research before investing"


# ─────────────────────────────────────────────
# Step 5 — Check predictions on due date + send email
# ─────────────────────────────────────────────


def check_predictions(
    target_date: date | None = None,
) -> pd.DataFrame:
    """
    Runs at 9:20 AM IST on the first job of the day.

    Finds all predictions in prediction_log.csv whose Predicted_Buy_Date
    is TODAY (or the last 2 business days as a safety net for any missed runs),
    fetches the day's Low price on that predicted date,
    computes error vs predicted price, and sends accuracy email.

    Why today's Low:
        The accuracy check runs at 9:20 AM — market has been open 5 mins.
        The model said "best buy today at ₹X". We check: was ₹X achievable
        today? The day's Low is the cheapest intraday price — if predicted ≈ Low,
        the model correctly identified today as the entry day and price.
        You still have the full trading day ahead to place your order.
    """
    from helpers.alerts import send_accuracy_email

    if target_date is None:
        target_date = date.today()

    # Check today + last 2 business days as safety net for missed/weekend runs
    check_dates = set()
    d = target_date
    for _ in range(3):
        check_dates.add(d.strftime("%d %b %Y"))
        d = d - timedelta(days=1)
        while d.weekday() >= 5:
            d = d - timedelta(days=1)

    print(f"\n  📊 Accuracy check — predictions due: {sorted(check_dates)}")

    pred_log = _load_csv(PREDICTION_LOG, PRED_COLUMNS)
    acc_log = _load_csv(ACCURACY_LOG, LOG_COLUMNS)
    new_records = []

    if pred_log.empty:
        print("  ℹ No prediction log yet — nothing to check.")
        return acc_log

    due = pred_log[pred_log["Predicted_Buy_Date"].isin(check_dates)]
    if due.empty:
        print(f"  ℹ No predictions due in window {sorted(check_dates)}")
        return acc_log

    print(f"  📋 Found {len(due)} prediction records due for accuracy check")

    for _, row in due.iterrows():
        ticker = row["Stock"]
        pred_date = row["Predicted_Buy_Date"]
        pred_price = float(row["Predicted_Buy_Price"])
        scan_date = row["Scan_Date"]
        run_time = row["Run_Time"]
        run_label = row["Run_Label"]
        company = row["Company_Name"]

        # Skip if already checked
        if not acc_log.empty:
            already = acc_log[
                (acc_log["Stock"] == ticker)
                & (acc_log["Predicted_Buy_Date"] == pred_date)
                & (acc_log["Scan_Date"] == scan_date)
                & (acc_log["Run_Time"] == run_time)
            ]
            if not already.empty:
                continue

        # Fetch day's Low on the PREDICTED date (not today if looking back)
        pred_date_obj = pd.to_datetime(pred_date, format="%d %b %Y").date()
        actual_price, actual_date = _fetch_actual_price(ticker, pred_date_obj)
        if actual_price is None:
            print(f"  ⚠ {ticker}: no price found for {pred_date}")
            continue

        error_pct = (actual_price - pred_price) / pred_price * 100
        direction = "UNDER" if actual_price < pred_price else "OVER"
        within = abs(error_pct) <= ACCURACY_THRESHOLD

        note = ""
        if actual_date and actual_date != pred_date_obj.strftime("%Y-%m-%d"):
            note = f"Checked on {actual_date} (next trading day after {pred_date})"

        new_records.append(
            {
                "Scan_Date": scan_date,
                "Run_Time": run_time,
                "Run_Label": run_label,
                "Stock": ticker,
                "Company_Name": company,
                "Predicted_Buy_Date": pred_date,
                "Predicted_Buy_Price": pred_price,
                "Actual_Open": actual_price,  # renamed from Actual_Close
                "Actual_Price_Date": actual_date,
                "Error_Pct": round(error_pct, 2),
                "Direction": direction,
                "Within_Threshold": within,
                "Note": note,
            }
        )

        status = "✓" if within else "✗"
        print(
            f"  {status} {ticker:20s} "
            f"Pred: ₹{pred_price} ({pred_date}) | "
            f"Actual Low: ₹{actual_price} | "
            f"Error: {error_pct:+.2f}%"
        )

    if not new_records:
        print("  ℹ All due predictions already checked or no prices available.")
        return acc_log

    new_df = pd.DataFrame(new_records)
    acc_log = pd.concat([acc_log, new_df], ignore_index=True)
    _save_csv(acc_log, ACCURACY_LOG, "Accuracy log")

    # Convergence + accuracy summary
    conv_data = get_all_convergence(pred_log)
    summary = []
    for stock in new_df["Stock"].unique():
        conv = conv_data.get(stock, {})
        acc = get_historical_accuracy(acc_log, stock)
        sig = get_signal(conv, acc)
        summary.append({"stock": stock, "conv": conv, "acc": acc, "signal": sig})

    mae = new_df["Error_Pct"].abs().mean()
    bias = new_df["Error_Pct"].mean()
    hits = len(new_df[new_df["Within_Threshold"]])
    total = len(new_df)

    print(
        f"\n  📈 Summary: {hits}/{total} within {ACCURACY_THRESHOLD}% | "
        f"MAE: {mae:.2f}% | Bias: {bias:+.2f}%"
    )

    _commit_logs()

    send_accuracy_email(
        target_date=target_date.strftime("%d %b %Y"),
        new_records=new_records,
        full_log=acc_log,
        mae=mae,
        bias=bias,
        summary=summary,
    )

    return acc_log
