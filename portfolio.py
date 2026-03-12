# ─────────────────────────────────────────────
# portfolio.py — Monthly ₹40,000 portfolio construction
# Builds 10 combinations from the full results pool
# (not just top 5 per band) optimised for LTCG returns
# ─────────────────────────────────────────────

import math
import pandas as pd
from datetime import datetime  # noqa: F401
from config import MAX_SECTOR_PER_PORTFOLIO

# ─────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────
MONTHLY_BUDGET = 1_00_000
MAX_STOCKS = 12  # max stocks per combination
MIN_ALLOCATION = 2_000  # ₹2,000 minimum per position
MAX_SINGLE_PCT = 0.30  # max 30% in any single stock

# ICICI Direct delivery brokerage — 0.55% on transaction value (both legs)
# Delivery trades held 12+ months — charged on buy and sell
ICICI_BROKERAGE_PCT = 0.0055  # 0.55% per transaction

SMALL_CAP_BANDS = ["₹150–₹500", "₹500–₹1000", "₹1000–₹1500"]
LARGE_CAP_BANDS = [
    "₹3000–₹3500",
    "₹3500–₹4000",
    "₹4000–₹4500",
    "₹4500–₹5000",
    "₹5000–₹6000",
    "₹6000–₹7000",
    "₹7000–₹15000",
]
MID_CAP_BANDS = ["₹1500–₹2000", "₹2000–₹2500", "₹2500–₹3000"]

# Sell month quality scores based on macro weights
# Higher = better month to have your peak fall in
SELL_MONTH_SCORES = {
    1: 2,  # Jan — mild positive
    2: 1,  # Feb — budget priced in
    3: -3,  # Mar — FY end selling
    4: -4,  # Apr — worst
    5: -3,  # May — panic exits
    6: -3,  # Jun — continued weakness
    7: 1,  # Jul — slight recovery
    8: 0,  # Aug — neutral
    9: -2,  # Sep — FII rebalancing
    10: 0,  # Oct — flat before diwali
    11: 4,  # Nov — Diwali rally — best
    12: 5,  # Dec — year-end rally — best
}


def _flatten_all(results: dict) -> pd.DataFrame:
    """
    Flattens all band results into one pool.
    Unlike the email output which shows top 5 per band,
    this uses ALL stocks that passed filters — giving us
    a larger pool to pick the best combinations from.
    """
    frames = []
    for band_label, df in results.items():
        d = df.copy()
        d["Band"] = band_label
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    all_stocks = pd.concat(frames, ignore_index=True)

    # Add sell month score for combination quality ranking
    all_stocks["Sell_Month"] = pd.to_datetime(
        all_stocks["Best_Sell_Date"], format="%d %b %Y"
    ).dt.month
    all_stocks["Sell_Month_Score"] = all_stocks["Sell_Month"].map(SELL_MONTH_SCORES)

    # Composite score — balances after-tax ROI, liquidity, sell month quality
    all_stocks["Score"] = (
        all_stocks["After_Tax_ROI_%"] * 0.60
        + all_stocks["Avg_Daily_Turnover_Cr"].clip(upper=500) / 500 * 10 * 0.20
        + all_stocks["Sell_Month_Score"] * 0.20
    )
    return all_stocks.sort_values("Score", ascending=False).reset_index(drop=True)


def _compute_position(row: pd.Series, alloc_amount: float) -> dict | None:
    """Compute a single stock position given an allocation amount."""
    from config import LTCG_TAX_RATE, LTCG_EXEMPTION, CESS_RATE, STT_RATE

    price = row["Buy_Price"]

    # ICICI Direct charges 0.55% on buy value (delivery trades)
    buy_brokerage = alloc_amount * ICICI_BROKERAGE_PCT
    shares = math.floor((alloc_amount - buy_brokerage) / price)
    if shares < 1:
        return None

    buy_value = shares * price
    actual_invest = buy_value + buy_brokerage  # actual cash out of account
    exit_value = shares * row["Exit_Target"]
    sell_brokerage = exit_value * ICICI_BROKERAGE_PCT  # 0.55% on sell value
    gross_profit = shares * (row["Exit_Target"] - price)
    stt = (buy_value + exit_value) * STT_RATE
    taxable = max(0, gross_profit - LTCG_EXEMPTION)
    tax = taxable * LTCG_TAX_RATE * (1 + CESS_RATE)
    net_profit = gross_profit - tax - stt - buy_brokerage - sell_brokerage
    net_roi = net_profit / actual_invest * 100
    return {
        "Stock": row["Stock"],
        "Company_Name": row.get("Company_Name", row["Stock"].replace(".NS", "")),
        "Band": row["Band"],
        "Buy_Price": round(price, 2),
        "Shares": shares,
        "Invested": round(actual_invest, 2),
        "Exit_Target": round(row["Exit_Target"], 2),
        "Exit_Value": round(exit_value, 2),
        "Gross_Profit": round(gross_profit, 2),
        "Net_Profit": round(net_profit, 2),
        "Net_ROI_%": round(net_roi, 2),
        "Best_Sell_Date": row["Best_Sell_Date"],
        "Forecast_Expires": row["Forecast_Expires"],
        "Turnover_Cr": row["Avg_Daily_Turnover_Cr"],
    }


def _allocate(stocks: pd.DataFrame, budget: float) -> pd.DataFrame:
    """
    Allocates budget across selected stocks targeting full ₹40,000 deployment.

    Phase 1 — Initial allocation:
        Weight by Score, cap at MAX_SINGLE_PCT, buy whole shares only.

    Phase 2 — Top-up pass:
        After initial allocation, redistribute remaining budget back into
        existing positions (highest score first) buying additional shares
        until remaining budget < cheapest stock price.
        Goal: deploy as close to ₹40,000 as possible.
    """
    if stocks.empty:
        return pd.DataFrame()

    stocks = stocks.copy().reset_index(drop=True)

    # ── Phase 1: Initial weighted allocation ──
    scores = stocks["Score"].clip(lower=0.1)
    weights = scores / scores.sum()
    weights = weights.clip(upper=MAX_SINGLE_PCT)
    weights = weights / weights.sum()

    positions = {}  # stock -> position dict
    sector_count = {}  # sector -> count of stocks already allocated
    spent = 0.0

    for i, row in stocks.iterrows():
        # Sector cap — skip if this sector already has MAX_SECTOR_PER_PORTFOLIO stocks
        sector = row.get("Sector", "Unknown")
        if sector_count.get(sector, 0) >= MAX_SECTOR_PER_PORTFOLIO:
            continue

        alloc = budget * weights[i]
        if alloc < MIN_ALLOCATION:
            continue
        pos = _compute_position(row, alloc)
        if pos is None:
            continue
        positions[row["Stock"]] = {"row": row, "pos": pos}
        sector_count[sector] = sector_count.get(sector, 0) + 1
        spent += pos["Invested"]

    if not positions:
        return pd.DataFrame()

    # ── Phase 2: Top-up pass — redistribute remaining budget ──
    # Sort stocks by score descending for top-up priority
    remaining = budget - spent
    sorted_stocks = stocks[stocks["Stock"].isin(positions.keys())].sort_values(
        "Score", ascending=False
    )

    max_passes = 10  # safety limit
    passes = 0
    while remaining >= MIN_ALLOCATION and passes < max_passes:
        improved = False
        for _, row in sorted_stocks.iterrows():
            ticker = row["Stock"]
            price = row["Buy_Price"]
            # Can we afford at least 1 more share?
            if remaining < price * (1 + ICICI_BROKERAGE_PCT):
                continue
            # Enforce MAX_SINGLE_PCT cap — check current allocation
            current_invested = positions[ticker]["pos"]["Invested"]
            max_allowed = budget * MAX_SINGLE_PCT
            if current_invested >= max_allowed:
                continue
            # How many extra shares can we buy within cap and remaining budget?
            headroom = max_allowed - current_invested
            affordable = min(remaining, headroom)
            extra_shares = math.floor(affordable / price)
            if extra_shares < 1:
                continue
            extra_cost = extra_shares * price
            if extra_cost > remaining:
                extra_shares = math.floor(remaining / price)
                extra_cost = extra_shares * price
            if extra_shares < 1:
                continue
            # Add shares to existing position and recompute
            from config import LTCG_TAX_RATE, LTCG_EXEMPTION, CESS_RATE, STT_RATE

            old_pos = positions[ticker]["pos"]
            new_shares = old_pos["Shares"] + extra_shares
            buy_value = new_shares * price
            buy_brokerage = buy_value * ICICI_BROKERAGE_PCT
            actual_invest = buy_value + buy_brokerage
            exit_value = new_shares * row["Exit_Target"]
            sell_brokerage = exit_value * ICICI_BROKERAGE_PCT
            gross_profit = new_shares * (row["Exit_Target"] - price)
            stt = (buy_value + exit_value) * STT_RATE
            taxable = max(0, gross_profit - LTCG_EXEMPTION)
            tax = taxable * LTCG_TAX_RATE * (1 + CESS_RATE)
            net_profit = gross_profit - tax - stt - buy_brokerage - sell_brokerage
            net_roi = net_profit / actual_invest * 100
            positions[ticker]["pos"] = {
                **old_pos,
                "Shares": new_shares,
                "Invested": round(actual_invest, 2),
                "Exit_Value": round(exit_value, 2),
                "Gross_Profit": round(gross_profit, 2),
                "Net_Profit": round(net_profit, 2),
                "Net_ROI_%": round(net_roi, 2),
            }
            remaining -= extra_cost
            improved = True
            break  # one stock per pass — then re-evaluate remaining
        if not improved:
            break
        passes += 1

    rows = [v["pos"] for v in positions.values()]
    return pd.DataFrame(rows)


def _summarise(portfolio: pd.DataFrame) -> dict:
    """Portfolio-level summary stats."""
    if portfolio.empty:
        return {}
    total_invested = portfolio["Invested"].sum()
    total_net_profit = portfolio["Net_Profit"].sum()
    portfolio_roi = total_net_profit / total_invested * 100
    earliest_sell = portfolio["Best_Sell_Date"].min()
    latest_sell = portfolio["Best_Sell_Date"].max()
    return {
        "Total_Invested": round(total_invested, 2),
        "Total_Net_Profit": round(total_net_profit, 2),
        "Portfolio_ROI_%": round(portfolio_roi, 2),
        "Earliest_Sell": earliest_sell,
        "Latest_Sell": latest_sell,
        "Num_Stocks": len(portfolio),
    }


def build_portfolios(results: dict, budget: float = MONTHLY_BUDGET) -> list[dict]:
    """
    Builds 10 portfolio combinations from the full results pool.
    Each combination has a different strategy — risk, timing, sector focus.

    Returns list of dicts, each with:
        name        — strategy label
        description — why this combination
        portfolio   — DataFrame with stock-by-stock allocation
        summary     — total invested, net profit, portfolio ROI
    """
    pool = _flatten_all(results)
    if pool.empty:
        return []

    combinations = []

    def _add(name: str, description: str, subset: pd.DataFrame):
        """Helper to build and add a combination."""
        subset = subset.head(MAX_STOCKS).copy()
        pf = _allocate(subset, budget)
        summary = _summarise(pf)
        if not pf.empty:
            combinations.append(
                {
                    "name": name,
                    "description": description,
                    "portfolio": pf,
                    "summary": summary,
                }
            )

    # ── 1. Maximum After-Tax Return ──
    _add(
        "Max After-Tax Return",
        "Top stocks purely by after-tax ROI — highest yield, higher concentration risk",
        pool.sort_values("After_Tax_ROI_%", ascending=False),
    )

    # ── 2. Best Sell Month (Nov/Dec peaks only) ──
    nov_dec = pool[pool["Sell_Month"].isin([11, 12])]
    if len(nov_dec) >= 3:
        _add(
            "Diwali & Year-End Rally",
            "Stocks peaking in Nov/Dec — ride Diwali + year-end rally, best macro tailwind",
            nov_dec.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 3. Balanced — one from each cap segment ──
    balanced = pd.concat(
        [
            pool[pool["Band"].isin(SMALL_CAP_BANDS)].head(2),
            pool[pool["Band"].isin(MID_CAP_BANDS)].head(2),
            pool[pool["Band"].isin(LARGE_CAP_BANDS)].head(2),
        ]
    )
    _add(
        "Balanced (Small + Mid + Large)",
        "2 stocks each from small, mid, large cap — diversified across market cap",
        balanced.sort_values("Score", ascending=False),
    )

    # ── 4. High Liquidity — easiest to exit ──
    _add(
        "High Liquidity",
        "Top stocks by daily turnover — exit anytime without moving the price",
        pool.sort_values("Avg_Daily_Turnover_Cr", ascending=False),
    )

    # ── 5. Conservative — steady 15–30% after-tax ROI ──
    conservative = pool[
        (pool["After_Tax_ROI_%"] >= 15) & (pool["After_Tax_ROI_%"] <= 35)
    ]
    _add(
        "Conservative (15–35% ROI)",
        "Moderate return targets — more realistic, less downside if model is off",
        conservative.sort_values("Score", ascending=False),
    )

    # ── 6. Early Exit (sell Jul–Oct 2027) ──
    # Specifically targets mid-2027 exits — different from max return which
    # also happens to peak in 2027 but is ROI-driven not timing-driven
    pool["Sell_Date_dt"] = pd.to_datetime(pool["Best_Sell_Date"], format="%d %b %Y")
    early = pool[
        (pool["Sell_Date_dt"].dt.year == 2027)
        & (pool["Sell_Date_dt"].dt.month.between(7, 10))  # Jul–Oct 2027 window
    ]
    _add(
        "Mid-2027 Exit (Jul–Oct 2027)",
        "Stocks peaking Jul–Oct 2027 — exit before year-end, redeploy for next cycle early",
        early.sort_values("After_Tax_ROI_%", ascending=False),
    )

    # ── 7. Late Exit (sell in 2028) ──
    late = pool[pool["Sell_Date_dt"].dt.year >= 2028]
    if len(late) >= 3:
        _add(
            "Patient Hold (2028 exit)",
            "Stocks with peaks in 2028 — maximum LTCG window, full mean reversion cycle",
            late.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 8. Small Cap Focus ──
    small = pool[pool["Band"].isin(SMALL_CAP_BANDS)]
    if len(small) >= 3:
        _add(
            "Small Cap Focus",
            "Higher growth potential from ₹150–₹1500 range — higher risk, higher reward",
            small.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 9. Large Cap Focus ──
    large = pool[pool["Band"].isin(LARGE_CAP_BANDS)]
    if len(large) >= 3:
        _add(
            "Large Cap Focus",
            "Stability from ₹3000+ stocks — lower volatility, institutional backing",
            large.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 10. Composite Score — best overall pick ──
    _add(
        "Best Overall (Composite Score)",
        "Balanced on ROI + liquidity + sell month quality — the most well-rounded combination",
        pool.sort_values("Score", ascending=False),
    )

    return combinations[:10]
