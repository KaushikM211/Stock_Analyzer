# ─────────────────────────────────────────────
# consolidate.py — Compare runs, alert on improvements
#
# Called at end of each run (Runs 2, 3, 4)
# Compares current run against all previous runs today
# If best portfolio ROI improved by >= 1.5% → send alert immediately
# ─────────────────────────────────────────────

import os
import json
import glob
from datetime import datetime, date

ROI_IMPROVEMENT_THRESHOLD = 1.5   # % — minimum improvement to trigger alert


def save_run_results(
    results: dict,
    portfolios: list,
    run_label: str,
    results_dir: str = "/tmp/scan_results",
) -> str:
    """
    Saves current run to a JSON file for comparison by later runs.
    Returns file path written.
    """
    os.makedirs(results_dir, exist_ok=True)
    now      = datetime.now()
    filename = os.path.join(results_dir, f"scan_{now.strftime('%H%M')}.json")

    # Serialise results — DataFrames → list of dicts
    serialised_results = {}
    for band, df in results.items():
        serialised_results[band] = df.to_dict(orient="records")

    # Serialise portfolios
    serialised_portfolios = []
    for combo in portfolios:
        serialised_portfolios.append({
            "name":        combo["name"],
            "description": combo["description"],
            "summary":     combo["summary"],
            "portfolio":   combo["portfolio"].to_dict(orient="records"),
        })

    data = {
        "date":       date.today().isoformat(),
        "run_label":  run_label,
        "run_time":   now.strftime("%H:%M"),
        "results":    serialised_results,
        "portfolios": serialised_portfolios,
    }

    with open(filename, "w") as fh:
        json.dump(data, fh, indent=2, default=str)

    print(f"  ✓ Run results saved → {filename}")
    return filename


def load_previous_runs(results_dir: str = "/tmp/scan_results") -> list[dict]:
    """
    Loads all JSON result files saved today (excluding current run).
    Returns list of run dicts sorted by time ascending.
    """
    today   = date.today().isoformat()
    pattern = os.path.join(results_dir, "scan_*.json")
    files   = sorted(glob.glob(pattern))

    runs = []
    for f in files:
        try:
            with open(f) as fh:
                data = json.load(fh)
            if data.get("date") == today:
                runs.append(data)
        except Exception as e:
            print(f"  ⚠ Could not load {f}: {e}")
    return runs


def _iter_portfolio_rows(portfolio) -> list[dict]:
    """
    Normalises portfolio to a list of dicts regardless of source.
    - From build_portfolios() → pandas DataFrame → convert via to_dict
    - From JSON load         → already list of dicts
    """
    import pandas as pd
    if isinstance(portfolio, pd.DataFrame):
        return portfolio.to_dict(orient="records")
    if isinstance(portfolio, list):
        return portfolio
    return []


def _best_combo_roi(portfolios: list) -> tuple[float, dict | None]:
    """Returns (best_roi, best_combo) from a portfolio list."""
    best_roi   = -999.0
    best_combo = None
    for combo in portfolios:
        roi = combo["summary"].get("Portfolio_ROI_%", 0)
        if roi > best_roi:
            best_roi   = roi
            best_combo = combo
    return best_roi, best_combo


def _lowest_prices(portfolios: list) -> dict[str, float]:
    """Returns {ticker: lowest_buy_price} across all combos."""
    prices = {}
    for combo in portfolios:
        rows = _iter_portfolio_rows(combo.get("portfolio", []))
        for stock in rows:
            ticker = stock.get("Stock")
            price  = stock.get("Buy_Price")
            if ticker and price:
                if ticker not in prices or price < prices[ticker]:
                    prices[ticker] = price
    return prices


def check_and_alert(
    current_results: dict,
    current_portfolios: list,
    run_label: str,
    results_dir: str = "/tmp/scan_results",
) -> bool:
    """
    Compares current run against all previous runs today.
    Sends alert if portfolio ROI improved by >= ROI_IMPROVEMENT_THRESHOLD.
    Returns True if alert was sent.
    """
    from alerts import send_improvement_alert

    previous_runs = load_previous_runs(results_dir)

    if not previous_runs:
        print(f"  ℹ {run_label} is first run today — saved as baseline, no alert.")
        return False

    # Best ROI and lowest prices across ALL previous runs today
    best_prev_roi    = -999.0
    best_prev_combo  = None
    best_prev_prices = {}

    for run in previous_runs:
        roi, combo = _best_combo_roi(run["portfolios"])
        if roi > best_prev_roi:
            best_prev_roi   = roi
            best_prev_combo = combo
        for ticker, price in _lowest_prices(run["portfolios"]).items():
            if ticker not in best_prev_prices or price < best_prev_prices[ticker]:
                best_prev_prices[ticker] = price

    # Current run best
    curr_roi, curr_best_combo = _best_combo_roi(current_portfolios)
    curr_prices               = _lowest_prices(current_portfolios)
    improvement               = curr_roi - best_prev_roi

    print(f"\n  📊 ROI Comparison ({run_label})")
    print(f"     Previous best: {best_prev_roi:.2f}%")
    print(f"     Current best:  {curr_roi:.2f}%")
    print(f"     Improvement:   {improvement:+.2f}%")

    if improvement < ROI_IMPROVEMENT_THRESHOLD:
        print(f"  ℹ Below {ROI_IMPROVEMENT_THRESHOLD}% threshold — no alert sent.")
        return False

    # Find stocks with better (lower) entry price vs previous runs
    improved_stocks = []
    for ticker, curr_price in curr_prices.items():
        prev_price = best_prev_prices.get(ticker)
        if prev_price is not None and curr_price < prev_price:
            pct_drop = (prev_price - curr_price) / prev_price * 100
            # Find company name
            company = ticker.replace(".NS", "")
            for combo in current_portfolios:
                for s in _iter_portfolio_rows(combo.get("portfolio", [])):
                    if s.get("Stock") == ticker:
                        company = s.get("Company_Name", company)
                        break
            improved_stocks.append({
                "ticker":     ticker,
                "company":    company,
                "prev_price": prev_price,
                "curr_price": curr_price,
                "pct_drop":   round(pct_drop, 2),
            })

    improved_stocks.sort(key=lambda x: x["pct_drop"], reverse=True)

    print(f"  🚨 Improvement {improvement:+.2f}% >= {ROI_IMPROVEMENT_THRESHOLD}% — sending alert!")
    send_improvement_alert(
        run_label          = run_label,
        current_roi        = curr_roi,
        previous_roi       = best_prev_roi,
        improvement        = improvement,
        best_combo         = curr_best_combo,
        improved_stocks    = improved_stocks,
        current_results    = current_results,
        current_portfolios = current_portfolios,
    )
    return True
