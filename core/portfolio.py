# ─────────────────────────────────────────────
# portfolio.py — Monthly ₹1,00,000 portfolio construction
#
# v2 CHANGE: Combinations are now risk-tier aware.
# Stocks carry Fundamental_Risk = "Low" / "Medium" / "High"
# assigned by score_fundamental_risk() in data.py.
#
# Combination strategy:
#   Conservative combos  → Low risk only
#   Balanced combos      → Low + Medium risk
#   Aggressive combos    → all tiers (Low + Medium + High)
#
# Risk label and score are shown in the email for each stock.
# ─────────────────────────────────────────────

import math
import pandas as pd
from datetime import datetime  # noqa: F401
from core.config import MAX_SECTOR_PER_PORTFOLIO

MONTHLY_BUDGET = 50_000
MAX_STOCKS = 7
MIN_ALLOCATION = 1_500
MAX_SINGLE_PCT = 0.18

ICICI_BROKERAGE_PCT = 0.0055

SMALL_CAP_BANDS = ["₹100–₹500", "₹500–₹1000", "₹1000–₹1500"]
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

SELL_MONTH_SCORES = {
    1: 2,
    2: 1,
    3: -3,
    4: -4,
    5: -3,
    6: -3,
    7: 1,
    8: 0,
    9: -2,
    10: 0,
    11: 4,
    12: 5,
}

# ─────────────────────────────────────────────
# Risk tier helpers
# ─────────────────────────────────────────────


def _by_risk(pool: pd.DataFrame, tiers: list[str]) -> pd.DataFrame:
    """Filter pool to stocks whose Fundamental_Risk is in tiers."""
    if "Fundamental_Risk" not in pool.columns:
        return pool  # backwards compat — no filtering if column absent
    return pool[pool["Fundamental_Risk"].isin(tiers)].copy()


def _flatten_all(results: dict) -> pd.DataFrame:
    frames = []
    for band_label, df in results.items():
        if band_label.startswith("_"):
            continue
        d = df.copy()
        d["Band"] = band_label
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    all_stocks = pd.concat(frames, ignore_index=True)

    all_stocks["Sell_Month"] = pd.to_datetime(
        all_stocks["Best_Sell_Date"], format="%d %b %Y"
    ).dt.month
    all_stocks["Sell_Month_Score"] = all_stocks["Sell_Month"].map(SELL_MONTH_SCORES)

    # Risk score penalty in composite score:
    # Low risk (score ~0–25) → no drag
    # Medium (26–50) → slight drag
    # High (51–100) → meaningful drag — ROI must compensate
    risk_score_col = all_stocks.get("Risk_Score", pd.Series(0, index=all_stocks.index))  # noqa: F841
    if "Risk_Score" in all_stocks.columns:
        risk_penalty = all_stocks["Risk_Score"] / 100 * 5  # max 5 pt drag
    else:
        risk_penalty = 0

    all_stocks["Score"] = (
        all_stocks["After_Tax_ROI_%"] * 0.60
        + all_stocks["Avg_Daily_Turnover_Cr"].clip(upper=500) / 500 * 10 * 0.20
        + all_stocks["Sell_Month_Score"] * 0.20
        - risk_penalty
    )
    return all_stocks.sort_values("Score", ascending=False).reset_index(drop=True)


def _compute_position(row: pd.Series, alloc_amount: float) -> dict | None:
    from core.config import LTCG_TAX_RATE, LTCG_EXEMPTION, CESS_RATE, STT_RATE

    price = row["Buy_Price"]
    buy_brokerage = alloc_amount * ICICI_BROKERAGE_PCT
    shares = math.floor((alloc_amount - buy_brokerage) / price)
    if shares < 1:
        return None

    buy_value = shares * price
    actual_invest = buy_value + buy_brokerage
    exit_value = shares * row["Exit_Target"]
    sell_brokerage = exit_value * ICICI_BROKERAGE_PCT
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
        "Predicted_Best_Buy_Date": row.get("Predicted_Best_Buy_Date", "N/A"),
        "Predicted_Best_Buy_Price": row.get("Predicted_Best_Buy_Price", "N/A"),
        "Turnover_Cr": row["Avg_Daily_Turnover_Cr"],
        # ── Risk columns pass through to portfolio output ──
        "Fundamental_Risk": row.get("Fundamental_Risk", "Unknown"),
        "Risk_Score": row.get("Risk_Score", 0),
    }


def _allocate(stocks: pd.DataFrame, budget: float) -> pd.DataFrame:
    if stocks.empty:
        return pd.DataFrame()

    stocks = stocks.copy().reset_index(drop=True)
    scores = stocks["Score"].clip(lower=0.1)
    weights = scores / scores.sum()
    weights = weights.clip(upper=MAX_SINGLE_PCT)
    weights = weights / weights.sum()

    positions = {}
    sector_count = {}
    spent = 0.0

    for i, row in stocks.iterrows():
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

    remaining = budget - spent
    sorted_stocks = stocks[stocks["Stock"].isin(positions.keys())].sort_values(
        "Score", ascending=False
    )

    max_passes = 10
    passes = 0
    while remaining >= MIN_ALLOCATION and passes < max_passes:
        improved = False
        for _, row in sorted_stocks.iterrows():
            ticker = row["Stock"]
            price = row["Buy_Price"]
            if remaining < price * (1 + ICICI_BROKERAGE_PCT):
                continue
            current_invested = positions[ticker]["pos"]["Invested"]
            max_allowed = budget * MAX_SINGLE_PCT
            if current_invested >= max_allowed:
                continue
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
            from core.config import LTCG_TAX_RATE, LTCG_EXEMPTION, CESS_RATE, STT_RATE

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
            break
        if not improved:
            break
        passes += 1

    rows = [v["pos"] for v in positions.values()]
    return pd.DataFrame(rows)


def _summarise(portfolio: pd.DataFrame) -> dict:
    if portfolio.empty:
        return {}
    total_invested = portfolio["Invested"].sum()
    total_net_profit = portfolio["Net_Profit"].sum()
    portfolio_roi = total_net_profit / total_invested * 100

    # Risk breakdown in summary
    risk_counts = {}
    if "Fundamental_Risk" in portfolio.columns:
        risk_counts = portfolio["Fundamental_Risk"].value_counts().to_dict()

    return {
        "Total_Invested": round(total_invested, 2),
        "Total_Net_Profit": round(total_net_profit, 2),
        "Portfolio_ROI_%": round(portfolio_roi, 2),
        "Earliest_Sell": portfolio["Best_Sell_Date"].min(),
        "Latest_Sell": portfolio["Best_Sell_Date"].max(),
        "Num_Stocks": len(portfolio),
        "Risk_Breakdown": risk_counts,  # e.g. {"Low": 7, "Medium": 3, "High": 2}
    }


def build_portfolios(results: dict, budget: float = MONTHLY_BUDGET) -> list[dict]:
    """
    Builds up to 12 portfolio combinations from the full results pool.

    DESIGN CHANGE: Risk label (Low/Medium/High) is shown on every stock
    as informational context — it does NOT gate inclusion in any combo.
    The user decides what risk they're comfortable with.

    Combinations are differentiated by strategy (timing, cap size, ROI target),
    not by risk tier. The composite Score already penalises High risk stocks
    slightly via the risk_penalty term, so they naturally rank lower when
    ROI is equal — but they're never excluded.

    Target mix across the full pool: ~55% Low, ~25% Medium, ~20% High.
    In practice this emerges naturally from the score-weighted allocation.
    """
    pool = _flatten_all(results)
    if pool.empty:
        return []

    combinations = []

    def _add(name: str, description: str, subset: pd.DataFrame):
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

    # ── 1. Best Overall (Composite Score) ──
    _add(
        "Best Overall (Composite Score)",
        "Highest composite score: ROI × liquidity × sell month × risk penalty — most well-rounded",
        pool.sort_values("Score", ascending=False),
    )

    # ── 2. Max After-Tax Return ──
    _add(
        "Max After-Tax Return",
        "Top stocks by after-tax ROI — highest yield, check Risk column for each stock",
        pool.sort_values("After_Tax_ROI_%", ascending=False),
    )

    # ── 3. Diwali & Year-End Rally ──
    nov_dec = pool[pool["Sell_Month"].isin([11, 12])]
    if len(nov_dec) >= 3:
        _add(
            "Diwali & Year-End Rally",
            "Peaks Nov/Dec — ride Diwali + year-end rally, best macro tailwind",
            nov_dec.sort_values("Score", ascending=False),
        )

    # ── 4. Balanced Cap Mix ──
    balanced_cap = pd.concat(
        [
            pool[pool["Band"].isin(SMALL_CAP_BANDS)].head(4),
            pool[pool["Band"].isin(MID_CAP_BANDS)].head(4),
            pool[pool["Band"].isin(LARGE_CAP_BANDS)].head(4),
        ]
    )
    _add(
        "Balanced Cap Mix",
        "4 each from small / mid / large cap — diversified across market cap segments",
        balanced_cap.sort_values("Score", ascending=False),
    )

    # ── 5. High Liquidity ──
    _add(
        "High Liquidity",
        "Top stocks by daily turnover — easiest to exit without moving the price",
        pool.sort_values("Avg_Daily_Turnover_Cr", ascending=False),
    )

    # ── 6. Conservative Steady (15–35% ROI range) ──
    steady = pool[(pool["After_Tax_ROI_%"] >= 15) & (pool["After_Tax_ROI_%"] <= 35)]
    if len(steady) >= 3:
        _add(
            "Conservative Steady (15–35% ROI)",
            "Moderate return targets — realistic forecasts, less downside if model is off",
            steady.sort_values("Score", ascending=False),
        )

    # ── 7. Mid-2027 Exit (Jul–Oct) ──
    pool["Sell_Date_dt"] = pd.to_datetime(pool["Best_Sell_Date"], format="%d %b %Y")
    early = pool[
        (pool["Sell_Date_dt"].dt.year == 2027)
        & (pool["Sell_Date_dt"].dt.month.between(7, 10))
    ]
    if len(early) >= 3:
        _add(
            "Mid-2027 Exit (Jul–Oct)",
            "Peaks Jul–Oct 2027 — exit before year-end, redeploy for next cycle early",
            early.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 8. Patient Hold (2028 exits) ──
    late = pool[pool["Sell_Date_dt"].dt.year >= 2028]
    if len(late) >= 3:
        _add(
            "Patient Hold (2028 exit)",
            "Peaks in 2028 — maximum LTCG window, full mean reversion cycle",
            late.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 9. Small Cap Focus ──
    small = pool[pool["Band"].isin(SMALL_CAP_BANDS)]
    if len(small) >= 3:
        _add(
            "Small Cap Focus",
            "₹100–₹1500 range — higher growth potential, higher volatility",
            small.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 10. Large Cap Focus ──
    large = pool[pool["Band"].isin(LARGE_CAP_BANDS)]
    if len(large) >= 3:
        _add(
            "Large Cap Focus",
            "₹3000+ stocks — lower volatility, institutional backing, easier exits",
            large.sort_values("After_Tax_ROI_%", ascending=False),
        )

    # ── 11. Low Risk Preference ──
    # Not a hard filter — just ranks Low risk stocks to the top within the pool
    # User still sees all risk levels; Low-scored stocks simply appear first
    low_first = pool.copy()
    risk_order = {"Low": 0, "Medium": 1, "High": 2}
    low_first["_risk_rank"] = low_first["Fundamental_Risk"].map(risk_order).fillna(1)
    low_first = low_first.sort_values(["_risk_rank", "Score"], ascending=[True, False])
    _add(
        "Low Risk Preference",
        "Same pool, sorted to show cleanest fundamentals first — Low risk stocks lead",
        low_first,
    )

    # ── 12. High ROI regardless of risk ──
    # Explicitly surfacing High risk / High ROI stocks so user can evaluate them
    high_roi = pool[pool["After_Tax_ROI_%"] >= 20].sort_values(
        "After_Tax_ROI_%", ascending=False
    )
    if len(high_roi) >= 3:
        _add(
            "High ROI (20%+ after-tax)",
            "All stocks forecasting 20%+ after-tax ROI — includes High risk; verify before investing",
            high_roi,
        )

    return combinations[:12]
