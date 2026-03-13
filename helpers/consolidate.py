# ─────────────────────────────────────────────
# consolidate.py — Compare runs, alert on improvements
#
# Trigger logic (stock-wise, not combination-wise):
#   Any stock in current run has a lower Buy_Price than seen today
#   AND that drop is >= STOCK_DROP_THRESHOLD (1.5%)
#   → send alert immediately with all improved stocks + best combo
#
# Artifact fix:
#   GitHub Actions artifacts are per-run — can't share across runs
#   Solution: commit results JSON to a dedicated branch (results-cache)
#   Each run pushes its JSON, next run pulls and compares
# ─────────────────────────────────────────────

import os
import json
import glob
import subprocess
from datetime import datetime, date

STOCK_DROP_THRESHOLD  = 1.5   # % drop in individual stock price to trigger alert
ROI_IMPROVEMENT_THRESHOLD = 1.5  # kept for backwards compat / logging


# ─────────────────────────────────────────────
# Normalise portfolio rows
# ─────────────────────────────────────────────

def _iter_portfolio_rows(portfolio) -> list[dict]:
    """Handles both DataFrame (live run) and list of dicts (JSON-loaded)."""
    import pandas as pd
    if isinstance(portfolio, pd.DataFrame):
        return portfolio.to_dict(orient="records")
    if isinstance(portfolio, list):
        return portfolio
    return []


# ─────────────────────────────────────────────
# Extract stock-level data from portfolios
# ─────────────────────────────────────────────

def _extract_stock_data(portfolios: list) -> dict[str, dict]:
    """
    Returns {ticker: {price, roi, company, best_sell}} 
    keeping the LOWEST price seen across all combos.
    """
    stocks = {}
    for combo in portfolios:
        for row in _iter_portfolio_rows(combo.get("portfolio", [])):
            ticker  = row.get("Stock")
            price   = row.get("Buy_Price")
            roi     = row.get("Net_ROI_%", 0)
            company = row.get("Company_Name", ticker.replace(".NS", "") if ticker else "")
            sell    = row.get("Best_Sell_Date", "")
            if not ticker or not price:
                continue
            if ticker not in stocks or price < stocks[ticker]["price"]:
                stocks[ticker] = {
                    "price":   price,
                    "roi":     roi,
                    "company": company,
                    "sell":    sell,
                }
    return stocks


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


# ─────────────────────────────────────────────
# Save / load via results cache dir
# ─────────────────────────────────────────────

def save_run_results(
    results: dict,
    portfolios: list,
    run_label: str,
    results_dir: str = "/tmp/scan_results",
) -> str:
    """Saves current run to JSON. Returns file path."""
    os.makedirs(results_dir, exist_ok=True)
    now      = datetime.now()
    filename = os.path.join(results_dir, f"scan_{now.strftime('%H%M')}.json")

    serialised_results = {}
    for band, df in results.items():
        import pandas as pd
        if isinstance(df, pd.DataFrame):
            serialised_results[band] = df.to_dict(orient="records")
        else:
            serialised_results[band] = df

    serialised_portfolios = []
    for combo in portfolios:
        serialised_portfolios.append({
            "name":        combo["name"],
            "description": combo["description"],
            "summary":     combo["summary"],
            "portfolio":   _iter_portfolio_rows(combo.get("portfolio", [])),
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

    # ── Push to results-cache branch so later runs can download ──
    _push_to_cache_branch(filename, now)

    return filename


def _push_to_cache_branch(filepath: str, now: datetime):
    """
    Commits the result JSON to the results-cache branch on GitHub.
    Later runs pull this branch to get today's baselines.
    Only runs in GitHub Actions (GITHUB_ACTIONS env var set).
    """
    if not os.getenv("GITHUB_ACTIONS"):
        print("  ℹ Not in GitHub Actions — skipping cache branch push.")
        return

    repo      = os.getenv("GITHUB_REPOSITORY", "")
    token     = os.getenv("GITHUB_TOKEN", "")
    workspace = os.getenv("GITHUB_WORKSPACE", "/home/runner/work")

    if not token:
        print("  ⚠ GITHUB_TOKEN not set — skipping cache push.")
        return

    branch    = "results-cache"
    dest_file = f"cache/scan_{now.strftime('%Y%m%d_%H%M')}.json"

    try:
        # Configure git
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "config", "user.name",  "GitHub Actions"],     check=True)

        # Fetch or create results-cache branch
        result = subprocess.run(
            ["git", "fetch", "origin", branch],
            capture_output=True
        )
        if result.returncode == 0:
            subprocess.run(["git", "checkout", branch], check=True)
        else:
            # Branch doesn't exist yet — create it as orphan
            subprocess.run(["git", "checkout", "--orphan", branch], check=True)
            subprocess.run(["git", "rm", "-rf", "."],
                           capture_output=True)  # clean slate

        # Write the file
        os.makedirs("cache", exist_ok=True)
        import shutil
        shutil.copy(filepath, dest_file)

        # Clean up files older than today
        today_str = date.today().strftime("%Y%m%d")
        for f in glob.glob("cache/scan_*.json"):
            if today_str not in f:
                os.remove(f)
                print(f"  🗑 Removed stale cache: {f}")

        subprocess.run(["git", "add", "cache/"], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"scan cache {now.strftime('%Y-%m-%d %H:%M')}"],
            check=True
        )
        remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        subprocess.run(
            ["git", "push", remote_url, f"HEAD:{branch}", "--force"],
            check=True
        )
        print(f"  ✓ Cache pushed to branch '{branch}' → {dest_file}")

        # Return to main branch
        main_branch = os.getenv("GITHUB_REF_NAME", "main")
        subprocess.run(["git", "checkout", main_branch], check=True)

    except subprocess.CalledProcessError as e:
        print(f"  ⚠ Cache push failed: {e} — intraday comparison will still work within same run")


def _pull_from_cache_branch(results_dir: str):
    """
    Pulls today's scan JSONs from results-cache branch.
    Called at start of intraday runs to get previous baselines.
    """
    if not os.getenv("GITHUB_ACTIONS"):
        print("  ℹ Not in GitHub Actions — skipping cache pull.")
        return

    token  = os.getenv("GITHUB_TOKEN", "")
    repo   = os.getenv("GITHUB_REPOSITORY", "")
    branch = "results-cache"

    if not token:
        print("  ⚠ GITHUB_TOKEN not set — skipping cache pull.")
        return

    try:
        remote_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        subprocess.run(
            ["git", "fetch", remote_url, branch],
            check=True, capture_output=True
        )
        # Extract only today's cache files
        today_str = date.today().strftime("%Y%m%d")
        result    = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", f"FETCH_HEAD"],
            capture_output=True, text=True
        )
        files = [f for f in result.stdout.splitlines()
                 if f.startswith("cache/scan_") and today_str in f]

        if not files:
            print(f"  ℹ No cache files found for today ({today_str}) — first run of day.")
            return

        os.makedirs(results_dir, exist_ok=True)
        for f in files:
            content = subprocess.run(
                ["git", "show", f"FETCH_HEAD:{f}"],
                capture_output=True
            )
            dest = os.path.join(results_dir, os.path.basename(f).replace(f"{today_str}_", ""))
            with open(dest, "wb") as fh:
                fh.write(content.stdout)
            print(f"  ✓ Pulled cache: {f} → {dest}")

    except subprocess.CalledProcessError as e:
        print(f"  ⚠ Cache pull failed: {e} — proceeding without previous baseline.")


def load_previous_runs(results_dir: str = "/tmp/scan_results") -> list[dict]:
    """Loads all JSON result files saved today."""
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


# ─────────────────────────────────────────────
# Main comparison logic
# ─────────────────────────────────────────────

def check_and_alert(
    current_results: dict,
    current_portfolios: list,
    run_label: str,
    results_dir: str = "/tmp/scan_results",
) -> bool:
    """
    Compares current run stock prices against all previous runs today.
    Alert triggered if ANY stock dropped >= STOCK_DROP_THRESHOLD vs previous runs.
    Returns True if alert was sent.
    """
    from alerts import send_improvement_alert

    # Pull previous runs from cache branch first
    _pull_from_cache_branch(results_dir)

    previous_runs = load_previous_runs(results_dir)

    if not previous_runs:
        print(f"  ℹ {run_label} — no previous runs today, saved as baseline.")
        return False

    # Best prices seen across ALL previous runs today (stock-wise)
    best_prev_prices: dict[str, dict] = {}
    best_prev_roi                     = -999.0
    best_prev_combo                   = None

    for run in previous_runs:
        roi, combo = _best_combo_roi(run["portfolios"])
        if roi > best_prev_roi:
            best_prev_roi   = roi
            best_prev_combo = combo
        for ticker, data in _extract_stock_data(run["portfolios"]).items():
            if ticker not in best_prev_prices or data["price"] < best_prev_prices[ticker]["price"]:
                best_prev_prices[ticker] = data

    # Current run stock data
    curr_stocks                       = _extract_stock_data(current_portfolios)
    curr_roi, curr_best_combo         = _best_combo_roi(current_portfolios)

    # ── Stock-wise comparison ──
    improved_stocks = []
    for ticker, curr in curr_stocks.items():
        prev = best_prev_prices.get(ticker)
        if prev is None:
            continue
        pct_drop = (prev["price"] - curr["price"]) / prev["price"] * 100
        if pct_drop >= STOCK_DROP_THRESHOLD:
            improved_stocks.append({
                "ticker":     ticker,
                "company":    curr["company"],
                "prev_price": round(prev["price"], 2),
                "curr_price": round(curr["price"], 2),
                "pct_drop":   round(pct_drop, 2),
                "curr_roi":   curr["roi"],
                "sell":       curr["sell"],
            })

    improved_stocks.sort(key=lambda x: x["pct_drop"], reverse=True)

    combo_improvement = curr_roi - best_prev_roi

    print(f"\n  📊 Stock-wise Comparison ({run_label})")
    print(f"     Stocks monitored:   {len(curr_stocks)}")
    print(f"     Stocks dipped 1.5%+: {len(improved_stocks)}")
    print(f"     Combo ROI:  {best_prev_roi:.2f}% → {curr_roi:.2f}% ({combo_improvement:+.2f}%)")

    if not improved_stocks:
        print(f"  ℹ No stock dropped {STOCK_DROP_THRESHOLD}%+ — no alert sent.")
        return False

    print(f"  🚨 {len(improved_stocks)} stock(s) dipped — sending alert!")
    for s in improved_stocks:
        print(f"     {s['ticker']:20s} ₹{s['prev_price']} → ₹{s['curr_price']} ({s['pct_drop']:+.2f}%)")

    send_improvement_alert(
        run_label          = run_label,
        current_roi        = curr_roi,
        previous_roi       = best_prev_roi,
        improvement        = combo_improvement,
        best_combo         = curr_best_combo,
        improved_stocks    = improved_stocks,
        current_results    = current_results,
        current_portfolios = current_portfolios,
    )
    return True
