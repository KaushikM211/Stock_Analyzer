# ─────────────────────────────────────────────
# alerts.py — Email notification via Gmail SMTP
#
# v2 CHANGE: Risk label (Low / Medium / High) shown in all three emails:
#   Email 1 (band picks)   — Risk column in Section A, Risk_Reasons in tooltip
#   Email 2 (portfolios)   — Risk badge on every stock row + breakdown in header bar
#   Email 3 (alert)        — Risk badge on dipped stocks + combo rows
# ─────────────────────────────────────────────

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ─────────────────────────────────────────────
# Shared risk badge helper
# ─────────────────────────────────────────────


def _risk_badge(risk_label: str, score: float = None) -> str:
    """
    Inline HTML badge. Score is always 1–100 (int) with multiplicative model.
    Shows score in parentheses when provided — gives users a sense of margin.
    """
    styles = {
        "Low": "background:#dcfce7; color:#166534; border:1px solid #86efac;",
        "Medium": "background:#fef9c3; color:#854d0e; border:1px solid #fde047;",
        "High": "background:#fee2e2; color:#991b1b; border:1px solid #fca5a5;",
    }
    label = risk_label or "Unknown"
    style = styles.get(
        label, "background:#f3f4f6; color:#374151; border:1px solid #d1d5db;"
    )
    score_str = f" ({int(score)})" if score is not None else ""
    return (
        f'<span style="display:inline-block; padding:2px 7px; border-radius:10px; '
        f'font-size:10px; font-weight:bold; white-space:nowrap; {style}">'
        f"{label}{score_str}</span>"
    )


def _risk_legend() -> str:
    """One-line legend shown at the bottom of every email."""
    return (
        '<p style="color:#6b7280; font-size:11px; margin-top:0;">'
        "<strong>Risk labels</strong> (fundamental score 0–100, lower = safer): &nbsp;"
        + _risk_badge("Low")
        + " all metrics clean &nbsp;|&nbsp; "
        + _risk_badge("Medium")
        + " borderline or data gaps &nbsp;|&nbsp; "
        + _risk_badge("High")
        + " PE/D/E/revenue red flag"
        + "</p>"
    )


# ─────────────────────────────────────────────
# Email 1 — Band-wise picks table
# ─────────────────────────────────────────────


def _band_table(results: dict) -> str:
    """
    Band-wise top picks.
    Section A: ticker, company, buy, target, ROI, tax, liquidity, RISK
    Section B: min hold, best sell, forecast expires, best buy date, predicted price
    """
    html = ""
    for band_label, df in results.items():
        if band_label.startswith("_"):  # skip internal keys like _full_pool
            continue
        html += f"""
        <h3 style="color:#0f3460; border-bottom:2px solid #0f3460;
                   padding-bottom:4px; margin-top:28px;">{band_label}</h3>

        <table style="width:100%; border-collapse:collapse; font-size:11px; margin-bottom:0;">
            <thead>
                <tr style="background:#0f3460; color:white; text-align:left;">
                    <th style="padding:5px 7px;">#</th>
                    <th style="padding:5px 7px;">Ticker</th>
                    <th style="padding:5px 7px;">Company</th>
                    <th style="padding:5px 7px;">Buy At</th>
                    <th style="padding:5px 7px;">Target</th>
                    <th style="padding:5px 7px;">Gross ROI</th>
                    <th style="padding:5px 7px;">After-Tax ROI</th>
                    <th style="padding:5px 7px;">Tax</th>
                    <th style="padding:5px 7px;">Turnover</th>
                    <th style="padding:5px 7px;">Liquidity</th>
                    <th style="padding:5px 7px;">Risk</th>
                </tr>
            </thead>
            <tbody>
        """
        for i, row in df.iterrows():
            bg = "#f5f5f5" if i % 2 == 0 else "#ffffff"
            tax_color = "#16a34a" if row["Tax_Type"] == "LTCG" else "#d97706"
            liq_color = "#16a34a" if row.get("Liquidity") == "High" else "#d97706"
            risk_label = row.get("Fundamental_Risk", "Unknown")
            risk_score = row.get("Risk_Score", None)
            # Truncate reasons to fit cell — full text in title tooltip
            reasons_tip = str(row.get("Risk_Reasons", "")).replace('"', "'")
            html += f"""
            <tr style="background:{bg};">
                <td style="padding:5px 7px; color:#999;">{i + 1}</td>
                <td style="padding:5px 7px; font-weight:bold; white-space:nowrap;">
                    {row["Stock"].replace(".NS", "")}
                </td>
                <td style="padding:5px 7px; color:#555; font-size:10px;">
                    {row.get("Company_Name", "")[:24]}
                </td>
                <td style="padding:5px 7px; white-space:nowrap;">&#8377;{row["Buy_Price"]}</td>
                <td style="padding:5px 7px; white-space:nowrap;">&#8377;{row["Exit_Target"]}</td>
                <td style="padding:5px 7px; color:#555;">+{row["Gross_ROI_%"]}%</td>
                <td style="padding:5px 7px; color:#16a34a; font-weight:bold;">
                    +{row["After_Tax_ROI_%"]}%
                </td>
                <td style="padding:5px 7px; color:{tax_color}; font-weight:bold;">
                    {row["Tax_Type"]}
                </td>
                <td style="padding:5px 7px; white-space:nowrap;">
                    &#8377;{row["Avg_Daily_Turnover_Cr"]}Cr
                </td>
                <td style="padding:5px 7px; color:{liq_color}; font-weight:bold;">
                    {row.get("Liquidity", "—")}
                </td>
                <td style="padding:5px 7px;" title="{reasons_tip}">
                    {_risk_badge(risk_label, risk_score)}
                </td>
            </tr>
            """
        html += "</tbody></table>"

        # Section B — timing
        html += """
        <table style="width:100%; border-collapse:collapse; font-size:11px;
                      border-top:2px solid #e5e7eb; margin-bottom:20px;">
            <thead>
                <tr style="background:#eef2f7; text-align:left; color:#333;">
                    <th style="padding:5px 7px;">Ticker</th>
                    <th style="padding:5px 7px;">Min Hold Until</th>
                    <th style="padding:5px 7px;">Best Sell Date</th>
                    <th style="padding:5px 7px;">Forecast Expires</th>
                    <th style="padding:5px 7px;">&#128197; Best Buy Date</th>
                    <th style="padding:5px 7px;">&#128176; Predicted Buy Price</th>
                </tr>
            </thead>
            <tbody>
        """
        for i, row in df.iterrows():
            bg = "#ffffff" if i % 2 == 0 else "#f0f4ff"
            html += f"""
            <tr style="background:{bg};">
                <td style="padding:5px 7px; font-weight:bold; white-space:nowrap;">
                    {row["Stock"].replace(".NS", "")}
                </td>
                <td style="padding:5px 7px; white-space:nowrap;">{row["Min_Hold_Until"]}</td>
                <td style="padding:5px 7px; font-weight:bold; white-space:nowrap;">
                    {row["Best_Sell_Date"]}
                </td>
                <td style="padding:5px 7px; color:#dc2626; white-space:nowrap;">
                    {row["Forecast_Expires"]}
                </td>
                <td style="padding:5px 7px; color:#0f3460; font-weight:bold; white-space:nowrap;">
                    {row.get("Predicted_Best_Buy_Date", "N/A")}
                </td>
                <td style="padding:5px 7px; color:#0f3460; white-space:nowrap;">
                    &#8377;{row.get("Predicted_Best_Buy_Price", "N/A")}
                </td>
            </tr>
            """
        html += "</tbody></table>"
    return html


# ─────────────────────────────────────────────
# Email 2 — Portfolio combinations tables
# ─────────────────────────────────────────────


def _risk_breakdown_bar(summary: dict) -> str:
    """
    Renders a small inline risk breakdown pill row from summary["Risk_Breakdown"].
    e.g.  Low: 7   Medium: 3   High: 2
    """
    breakdown = summary.get("Risk_Breakdown", {})
    if not breakdown:
        return ""
    parts = []
    for tier in ["Low", "Medium", "High"]:
        n = breakdown.get(tier, 0)
        if n:
            parts.append(f"{_risk_badge(tier)} {n}")
    if not parts:
        return ""
    return "&nbsp;|&nbsp; <strong>Risk mix:</strong> " + " &nbsp; ".join(parts)


def _portfolio_tables(portfolios: list) -> str:
    """
    All portfolio combinations.
    Section A: ticker, company, band, buy, qty, invested, exit, profit, ROI, RISK
    Section B: best sell, forecast expires, best buy date, predicted buy price
    """
    if not portfolios:
        return "<p style='color:#999;'>No portfolio combinations generated.</p>"

    html = ""
    colors = [
        "#0f3460",
        "#1a5276",
        "#154360",
        "#0e6655",
        "#1b4f72",
        "#212f3d",
        "#4a235a",
        "#78281f",
        "#1a5276",
        "#0b5345",
        "#1a3c4a",
        "#2c3e50",
    ]

    for i, combo in enumerate(portfolios):
        s = combo["summary"]
        pf = combo["portfolio"]
        color = colors[i % len(colors)]
        risk_tier_label = s.get("Risk_Tier", "")
        tier_display = (
            f" &nbsp;&#183;&nbsp; <span style='font-size:11px; opacity:0.9;'>{risk_tier_label} strategy</span>"
            if risk_tier_label
            else ""
        )

        html += f"""
        <div style="margin-top:28px; border:1px solid #ddd; border-radius:6px;
                    overflow:hidden;">
            <div style="background:{color}; color:white; padding:12px 16px;">
                <span style="font-size:15px; font-weight:bold;">
                    #{i + 1} &mdash; {combo["name"]}
                </span>{tier_display}<br/>
                <span style="font-size:12px; opacity:0.85;">{combo["description"]}</span>
            </div>
            <div style="background:#f9f9f9; padding:10px 16px; font-size:13px;">
                &#128176; <strong>Invested:</strong> &#8377;{s["Total_Invested"]:,.0f}
                &nbsp;|&nbsp;
                &#128200; <strong>Net Profit:</strong> &#8377;{s["Total_Net_Profit"]:,.0f}
                &nbsp;|&nbsp;
                &#127919; <strong>ROI:</strong>
                    <strong style="color:#16a34a;">{s["Portfolio_ROI_%"]}%</strong>
                &nbsp;|&nbsp;
                &#128197; <strong>Sell Window:</strong>
                    {s["Earliest_Sell"]} &rarr; {s["Latest_Sell"]}
                {_risk_breakdown_bar(s)}
            </div>

            <!-- Section A: Trading Info -->
            <table style="width:100%; border-collapse:collapse; font-size:11px;">
                <thead>
                    <tr style="background:#eef2f7; text-align:left; color:#333;">
                        <th style="padding:5px 7px;">Ticker</th>
                        <th style="padding:5px 7px;">Company</th>
                        <th style="padding:5px 7px;">Band</th>
                        <th style="padding:5px 7px;">Buy At</th>
                        <th style="padding:5px 7px;">Qty</th>
                        <th style="padding:5px 7px;">Invested</th>
                        <th style="padding:5px 7px;">Exit Target</th>
                        <th style="padding:5px 7px;">Exit Value</th>
                        <th style="padding:5px 7px;">Net Profit</th>
                        <th style="padding:5px 7px;">Net ROI</th>
                        <th style="padding:5px 7px;">Risk</th>
                    </tr>
                </thead>
                <tbody>
        """
        for j, row in pf.iterrows():
            bg = "#ffffff" if j % 2 == 0 else "#f5f5f5"
            risk_label = row.get("Fundamental_Risk", "Unknown")
            risk_score = row.get("Risk_Score", None)
            html += f"""
                    <tr style="background:{bg};">
                        <td style="padding:5px 7px; font-weight:bold; white-space:nowrap;">
                            {row["Stock"].replace(".NS", "")}
                        </td>
                        <td style="padding:5px 7px; color:#555; font-size:10px;">
                            {row.get("Company_Name", "")[:22]}
                        </td>
                        <td style="padding:5px 7px; font-size:10px; color:#777;">
                            {row["Band"]}
                        </td>
                        <td style="padding:5px 7px; white-space:nowrap;">
                            &#8377;{row["Buy_Price"]}
                        </td>
                        <td style="padding:5px 7px; font-weight:bold; text-align:center;">
                            {int(row["Shares"])}
                        </td>
                        <td style="padding:5px 7px; white-space:nowrap;">
                            &#8377;{row["Invested"]:,.0f}
                        </td>
                        <td style="padding:5px 7px; white-space:nowrap;">
                            &#8377;{row["Exit_Target"]}
                        </td>
                        <td style="padding:5px 7px; white-space:nowrap;">
                            &#8377;{row["Exit_Value"]:,.0f}
                        </td>
                        <td style="padding:5px 7px; color:#16a34a; font-weight:bold;
                                   white-space:nowrap;">
                            &#8377;{row["Net_Profit"]:,.0f}
                        </td>
                        <td style="padding:5px 7px; color:#16a34a; font-weight:bold;
                                   white-space:nowrap;">
                            +{row["Net_ROI_%"]}%
                        </td>
                        <td style="padding:5px 7px;">
                            {_risk_badge(risk_label, risk_score)}
                        </td>
                    </tr>
            """
        html += "</tbody></table>"

        # Section B — timing
        html += """
            <table style="width:100%; border-collapse:collapse; font-size:11px;
                          border-top:2px solid #e5e7eb;">
                <thead>
                    <tr style="background:#fef9ec; text-align:left; color:#333;">
                        <th style="padding:5px 7px;">Ticker</th>
                        <th style="padding:5px 7px;">Best Sell Date</th>
                        <th style="padding:5px 7px;">Forecast Expires</th>
                        <th style="padding:5px 7px;">&#128197; Best Buy Date</th>
                        <th style="padding:5px 7px;">&#128176; Predicted Buy Price</th>
                    </tr>
                </thead>
                <tbody>
        """
        for j, row in pf.iterrows():
            bg = "#ffffff" if j % 2 == 0 else "#fffdf0"
            html += f"""
                    <tr style="background:{bg};">
                        <td style="padding:5px 7px; font-weight:bold; white-space:nowrap;">
                            {row["Stock"].replace(".NS", "")}
                        </td>
                        <td style="padding:5px 7px; font-weight:bold; white-space:nowrap;">
                            {row["Best_Sell_Date"]}
                        </td>
                        <td style="padding:5px 7px; color:#dc2626; white-space:nowrap;">
                            {row["Forecast_Expires"]}
                        </td>
                        <td style="padding:5px 7px; color:#0f3460; font-weight:bold;
                                   white-space:nowrap;">
                            {row.get("Predicted_Best_Buy_Date", "N/A")}
                        </td>
                        <td style="padding:5px 7px; color:#0f3460; white-space:nowrap;">
                            &#8377;{row.get("Predicted_Best_Buy_Price", "N/A")}
                        </td>
                    </tr>
            """
        html += "</tbody></table></div>"
    return html


# ─────────────────────────────────────────────
# Email 1 builder
# ─────────────────────────────────────────────


def _build_picks_html(results: dict) -> str:
    today = datetime.today().strftime("%B %Y")
    html = f"""
    <html><body style="font-family:Arial,sans-serif; max-width:1000px;
                        margin:auto; color:#1a1a1a;">
    <h2 style="color:#1a1a2e; margin-bottom:4px;">
        &#128202; Nifty 500 &mdash; Top Picks by Price Band
    </h2>
    <p style="color:#555; margin-top:0;">
        &#128197; {today} &nbsp;|&nbsp; Min hold: 12 months (LTCG) &nbsp;|&nbsp;
        All ROI is <strong>after tax</strong> (LTCG 12.5% + 4% cess + STT)
    </p>
    <p style="color:#777; font-size:13px;">
        &#128231; This is email 1 of 2. Portfolio combinations follow in the next email.
    </p>
    {_risk_legend()}
    <hr style="border:1px solid #ddd;"/>
    """
    if not results:
        html += "<p>&#9888;&#65039; No stocks matched the criteria this month.</p>"
    else:
        html += _band_table(results)
    html += """
    <hr style="border:1px solid #ddd; margin-top:24px;"/>
    <p style="color:#999; font-size:11px;">
        LTCG 12.5% + 4% cess + 0.1% STT. Min hold 12 months.
        Model-based screener &mdash; not financial advice.
    </p>
    </body></html>"""
    return html


# ─────────────────────────────────────────────
# Email 2 builder
# ─────────────────────────────────────────────


def _build_portfolio_html(portfolios: list) -> str:
    today = datetime.today().strftime("%B %Y")
    html = f"""
    <html><body style="font-family:Arial,sans-serif; max-width:1000px;
                        margin:auto; color:#1a1a1a;">
    <h2 style="color:#1a1a2e; margin-bottom:4px;">
        &#128188; Nifty 500 &mdash; &#8377;1,00,000 Portfolio Combinations
    </h2>
    <p style="color:#555; margin-top:0;">
        &#128197; {today} &nbsp;|&nbsp;
        &#128231; This is email 2 of 2. Band-wise picks are in the previous email.
    </p>
    <p style="color:#777; font-size:13px; margin-top:0;">
        {len(portfolios)} ways to deploy &#8377;1,00,000 this month. Exact share quantities —
        place directly as market orders. Pick the strategy that fits your risk appetite and timeline.
    </p>
    {_risk_legend()}
    <hr style="border:1px solid #ddd;"/>
    {_portfolio_tables(portfolios)}
    <hr style="border:1px solid #ddd; margin-top:24px;"/>
    <p style="color:#999; font-size:11px;">
        After-tax: LTCG 12.5% + 4% cess + 0.1% STT both legs.
        &#8377;1.25L LTCG exemption applied per combination.
        Brokerage 0.55% (ICICI Direct). Not financial advice &mdash; verify with your CA.
    </p>
    </body></html>"""
    return html


# ─────────────────────────────────────────────
# Email 3 — Intraday improvement alert
# ─────────────────────────────────────────────


def _build_improvement_html(
    run_label: str,
    current_roi: float,
    previous_roi: float,
    improvement: float,
    best_combo: dict,
    improved_stocks: list,
) -> str:
    now = datetime.now().strftime("%I:%M %p")
    today = datetime.today().strftime("%d %b %Y")
    s = best_combo.get("summary", {})
    pf = best_combo.get("portfolio", [])

    # Dipped stocks table — includes risk badge
    improved_rows = ""
    for i, st in enumerate(improved_stocks):
        bg = "#fffbeb" if i % 2 == 0 else "#ffffff"
        risk_label = st.get("risk_label", "Unknown")
        risk_score = st.get("risk_score", None)
        improved_rows += f"""
        <tr style="background:{bg};">
            <td style="padding:8px; font-weight:bold;">{st["ticker"].replace(".NS", "")}</td>
            <td style="padding:8px; color:#555;">{st["company"]}</td>
            <td style="padding:8px; color:#6b7280;">&#8377;{st["prev_price"]}</td>
            <td style="padding:8px; color:#16a34a; font-weight:bold;">&#8377;{st["curr_price"]}</td>
            <td style="padding:8px; color:#dc2626; font-weight:bold;">&#9660; {st["pct_drop"]}%</td>
            <td style="padding:8px;">{_risk_badge(risk_label, risk_score)}</td>
        </tr>"""

    improved_section = ""
    if improved_stocks:
        improved_section = f"""
        <h3 style="color:#b45309; margin-top:24px; border-bottom:2px solid #f59e0b;
                   padding-bottom:4px;">&#128202; Stocks With Better Entry Price Now</h3>
        <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:16px;">
            <thead>
                <tr style="background:#fef3c7; text-align:left;">
                    <th style="padding:8px;">Ticker</th>
                    <th style="padding:8px;">Company</th>
                    <th style="padding:8px;">Previous Price</th>
                    <th style="padding:8px;">Current Price</th>
                    <th style="padding:8px;">Drop</th>
                    <th style="padding:8px;">Risk</th>
                </tr>
            </thead>
            <tbody>{improved_rows}</tbody>
        </table>"""

    # Best combo rows — includes risk badge
    combo_rows = ""
    for i, row in enumerate(pf if isinstance(pf, list) else pf.to_dict("records")):
        bg = "#f9fafb" if i % 2 == 0 else "#ffffff"
        risk_label = row.get("Fundamental_Risk", "Unknown")
        risk_score = row.get("Risk_Score", None)
        combo_rows += f"""
        <tr style="background:{bg};">
            <td style="padding:7px; font-weight:bold;">{str(row.get("Stock", "")).replace(".NS", "")}</td>
            <td style="padding:7px; color:#555;">{row.get("Company_Name", "")}</td>
            <td style="padding:7px;">&#8377;{row.get("Buy_Price", "")}</td>
            <td style="padding:7px; font-weight:bold;">{int(row.get("Shares", 0))}</td>
            <td style="padding:7px;">&#8377;{float(row.get("Invested", 0)):,.0f}</td>
            <td style="padding:7px; color:#16a34a; font-weight:bold;">
                +{row.get("Net_ROI_%", "")}%
            </td>
            <td style="padding:7px;">{row.get("Best_Sell_Date", "")}</td>
            <td style="padding:7px;">{_risk_badge(risk_label, risk_score)}</td>
        </tr>"""

    return f"""
    <html><body style="font-family:Arial,sans-serif; max-width:900px;
                        margin:auto; color:#1a1a1a;">

    <div style="background:#dc2626; color:white; padding:16px 20px;
                border-radius:6px 6px 0 0;">
        <h2 style="margin:0; font-size:18px;">
            &#128680; Better Entry Alert &mdash; {run_label}
        </h2>
        <p style="margin:4px 0 0; font-size:13px; opacity:0.9;">
            {today} at {now} &nbsp;|&nbsp; Act now &mdash; prices may recover
        </p>
    </div>

    <div style="background:#fef2f2; border:1px solid #fca5a5;
                padding:14px 20px; margin-bottom:20px; border-radius:0 0 4px 4px;">
        <table style="width:100%; font-size:14px;">
            <tr>
                <td style="padding:6px 12px 6px 0;">
                    &#128200; <strong>Previous Best ROI:</strong>
                    <span style="color:#6b7280; font-weight:bold;"> {previous_roi:.2f}%</span>
                </td>
                <td style="padding:6px 12px;">
                    &#127919; <strong>Current Best ROI:</strong>
                    <span style="color:#16a34a; font-weight:bold; font-size:16px;"> {current_roi:.2f}%</span>
                </td>
                <td style="padding:6px 0 6px 12px;">
                    &#11014;&#65039; <strong>Improvement:</strong>
                    <span style="color:#dc2626; font-weight:bold;"> +{improvement:.2f}%</span>
                </td>
            </tr>
        </table>
    </div>

    {improved_section}

    <h3 style="color:#0f3460; margin-top:24px; border-bottom:2px solid #0f3460;
               padding-bottom:4px;">
        &#128188; Best Combination Now &mdash; {best_combo.get("name", "")}
    </h3>
    <p style="color:#555; font-size:13px;">{best_combo.get("description", "")}</p>
    <div style="background:#f0fdf4; border:1px solid #86efac;
                padding:10px 16px; border-radius:4px; margin-bottom:12px;">
        &#128176; <strong>Invested:</strong> &#8377;{s.get("Total_Invested", 0):,}
        &nbsp;|&nbsp;
        &#128200; <strong>Net Profit:</strong> &#8377;{s.get("Total_Net_Profit", 0):,}
        &nbsp;|&nbsp;
        &#127919; <strong>Portfolio ROI:</strong>
        <strong style="color:#16a34a; font-size:15px;"> {s.get("Portfolio_ROI_%", 0)}%</strong>
        &nbsp;|&nbsp;
        &#128197; <strong>Sell Window:</strong>
        {s.get("Earliest_Sell", "")} &rarr; {s.get("Latest_Sell", "")}
        {_risk_breakdown_bar(s)}
    </div>

    <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:20px;">
        <thead>
            <tr style="background:#0f3460; color:white; text-align:left;">
                <th style="padding:7px;">Ticker</th>
                <th style="padding:7px;">Company</th>
                <th style="padding:7px;">Buy At</th>
                <th style="padding:7px;">Shares</th>
                <th style="padding:7px;">Invested</th>
                <th style="padding:7px;">Net ROI</th>
                <th style="padding:7px;">Best Sell</th>
                <th style="padding:7px;">Risk</th>
            </tr>
        </thead>
        <tbody>{combo_rows}</tbody>
    </table>

    {_risk_legend()}
    <hr style="border:1px solid #ddd;"/>
    <p style="color:#999; font-size:11px;">
        1.5% dip = stock is cheaper than the morning baseline — your entry price improved.<br/>
        Improvement threshold: 1.5% | Run: {run_label} at {now}<br/>
        Model-based screener &mdash; not financial advice. Verify before investing.
    </p>
    </body></html>"""


# ─────────────────────────────────────────────
# Send helpers (unchanged)
# ─────────────────────────────────────────────


def _send_single(
    sender: str,
    password: str,
    recipient: str,
    subject: str,
    html: str,
    label: str,
) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        size_kb = len(html.encode("utf-8")) / 1024
        print(f"  ✅ {label} sent ({size_kb:.1f} KB)")
        return True
    except smtplib.SMTPAuthenticationError:
        print(
            "  ❌ Gmail auth failed — use App Password from myaccount.google.com/apppasswords"
        )
        return False
    except Exception as e:
        print(f"  ❌ Failed to send {label}: {e}")
        return False


def _get_credentials() -> tuple[str, str, str]:
    sender = os.getenv("GMAIL_SENDER", "").strip().strip('"').strip("'")
    password = os.getenv("GMAIL_PASSWORD", "").strip().strip('"').strip("'")
    recipient = os.getenv("GMAIL_RECIPIENT", "").strip().strip('"').strip("'")
    return sender, password, recipient


# ─────────────────────────────────────────────
# Public API (unchanged signatures)
# ─────────────────────────────────────────────


def send_email_alert(
    results: dict,
    portfolios: list = None,
    debug: bool = False,
) -> None:
    sender, password, recipient = _get_credentials()
    if not all([sender, password, recipient]):
        print("  ❌ Email credentials missing.")
        return
    if debug:
        print(f"  Sender    : {sender}")
        print(f"  Recipient : {recipient}")
        print(f"  Password  : {'*' * len(password)}")
    today = datetime.today().strftime("%B %Y")
    _send_single(
        sender,
        password,
        recipient,
        subject=f"📊 [1/2] Nifty 500 Top Picks — {today}",
        html=_build_picks_html(results),
        label="Email 1/2 (Band Picks)",
    )
    _send_single(
        sender,
        password,
        recipient,
        subject=f"💼 [2/2] Nifty 500 Portfolio Combinations — {today}",
        html=_build_portfolio_html(portfolios or []),
        label="Email 2/2 (Portfolios)",
    )


def send_improvement_alert(
    run_label: str,
    current_roi: float,
    previous_roi: float,
    improvement: float,
    best_combo: dict,
    improved_stocks: list,
    current_results: dict,
    current_portfolios: list,
) -> None:
    sender, password, recipient = _get_credentials()
    if not all([sender, password, recipient]):
        print("  ❌ Email credentials missing.")
        return
    now = datetime.now().strftime("%I:%M %p")
    today = datetime.today().strftime("%d %b %Y")
    subject = (
        f"🚨 Better Entry Alert ({run_label}) — "
        f"ROI {previous_roi:.1f}% → {current_roi:.1f}% "
        f"(+{improvement:.1f}%) — {today} {now}"
    )
    html = _build_improvement_html(
        run_label=run_label,
        current_roi=current_roi,
        previous_roi=previous_roi,
        improvement=improvement,
        best_combo=best_combo,
        improved_stocks=improved_stocks,
    )
    _send_single(
        sender,
        password,
        recipient,
        subject=subject,
        html=html,
        label=f"Improvement Alert ({run_label})",
    )


# ─────────────────────────────────────────────
# Accuracy email (unchanged)
# ─────────────────────────────────────────────


def _build_accuracy_html(
    target_date: str,
    new_records: list,
    full_log,
    mae: float,
    bias: float,
    summary: list | None = None,
) -> str:
    today = __import__("datetime").datetime.today().strftime("%d %b %Y")
    rows = ""
    for i, r in enumerate(new_records):
        bg = "#f9fafb" if i % 2 == 0 else "#ffffff"
        err = r["Error_Pct"]
        err_color = (
            "#16a34a" if abs(err) <= 2 else "#d97706" if abs(err) <= 5 else "#dc2626"
        )
        dir_icon = "&#9660;" if r["Direction"] == "UNDER" else "&#9650;"
        rows += f"""
        <tr style="background:{bg};">
            <td style="padding:7px; font-weight:bold;">{r["Stock"]}</td>
            <td style="padding:7px; color:#555;">{r["Company_Name"]}</td>
            <td style="padding:7px;">&#8377;{r["Predicted_Buy_Price"]}</td>
            <td style="padding:7px; font-weight:bold;">&#8377;{r["Actual_Open"]}</td>
            <td style="padding:7px; color:{err_color}; font-weight:bold;">
                {dir_icon} {err:+.2f}%
            </td>
            <td style="padding:7px; color:#6b7280;">{r["Scan_Date"]}</td>
        </tr>"""

    total = len(full_log) if hasattr(full_log, "__len__") else 0
    all_mae = round(full_log["Error_Pct"].abs().mean(), 2) if total > 0 else 0
    all_bias = round(full_log["Error_Pct"].mean(), 2) if total > 0 else 0
    within_2 = len(full_log[full_log["Error_Pct"].abs() <= 2]) if total > 0 else 0
    within_5 = len(full_log[full_log["Error_Pct"].abs() <= 5]) if total > 0 else 0
    pct_2 = round(within_2 / total * 100, 1) if total > 0 else 0
    pct_5 = round(within_5 / total * 100, 1) if total > 0 else 0

    return f"""
    <html><body style="font-family:Arial,sans-serif; max-width:900px;
                        margin:auto; color:#1a1a1a;">
    <div style="background:#1a5276; color:white; padding:16px 20px;
                border-radius:6px 6px 0 0;">
        <h2 style="margin:0; font-size:18px;">
            &#127919; Prediction Accuracy Report — {target_date}
        </h2>
        <p style="margin:4px 0 0; font-size:13px; opacity:0.9;">
            Checked today ({today}) — Predicted vs Actual closing price
        </p>
    </div>
    <div style="background:#eef2f7; border:1px solid #ddd;
                padding:14px 20px; margin-bottom:20px;">
        <table style="width:100%; font-size:14px;">
            <tr>
                <td style="padding:6px 16px 6px 0;">
                    &#128202; <strong>Today's MAE:</strong>
                    <span style="color:#1a5276; font-weight:bold;"> {mae:.2f}%</span>
                </td>
                <td style="padding:6px 16px;">
                    &#127919; <strong>Bias:</strong>
                    <span style="color:{
        "#dc2626" if bias > 0 else "#16a34a"
    }; font-weight:bold;">
                        {bias:+.2f}% ({
        "overestimates" if bias > 0 else "underestimates"
    })
                    </span>
                </td>
                <td style="padding:6px 0;">
                    &#128202; <strong>Stocks checked:</strong>
                    <span style="font-weight:bold;"> {len(new_records)}</span>
                </td>
            </tr>
        </table>
    </div>
    <h3 style="color:#0f3460; border-bottom:2px solid #0f3460; padding-bottom:4px;">
        &#128200; Predicted vs Actual — {target_date}
    </h3>
    <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:24px;">
        <thead>
            <tr style="background:#0f3460; color:white; text-align:left;">
                <th style="padding:7px;">Ticker</th>
                <th style="padding:7px;">Company</th>
                <th style="padding:7px;">Predicted Price</th>
                <th style="padding:7px;">Actual Open</th>
                <th style="padding:7px;">Error %</th>
                <th style="padding:7px;">Scan Date</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    <h3 style="color:#0f3460; border-bottom:2px solid #0f3460; padding-bottom:4px;">
        &#128200; All-Time Accuracy ({total} predictions)
    </h3>
    <div style="background:#f0fdf4; border:1px solid #86efac;
                padding:12px 16px; border-radius:4px; margin-bottom:20px;">
        <table style="width:100%; font-size:13px;">
            <tr>
                <td style="padding:4px 16px 4px 0;">
                    &#127919; <strong>All-time MAE:</strong> {all_mae}%
                </td>
                <td style="padding:4px 16px;">
                    &#127919; <strong>Bias:</strong> {all_bias:+.2f}%
                </td>
                <td style="padding:4px 16px;">
                    &#9989; <strong>Within 2%:</strong> {within_2}/{total} ({pct_2}%)
                </td>
                <td style="padding:4px 0;">
                    &#9989; <strong>Within 5%:</strong> {within_5}/{total} ({pct_5}%)
                </td>
            </tr>
        </table>
    </div>
    <h3 style="color:#0f3460; border-bottom:2px solid #0f3460; padding-bottom:4px;">
        &#127919; Per-Stock Signal (Convergence + Historical Accuracy)
    </h3>
    <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:24px;">
        <thead>
            <tr style="background:#0f3460; color:white; text-align:left;">
                <th style="padding:7px;">Stock</th>
                <th style="padding:7px;">Best Buy Date</th>
                <th style="padding:7px;">Price Range</th>
                <th style="padding:7px;">Convergence</th>
                <th style="padding:7px;">Runs Agree</th>
                <th style="padding:7px;">Hist. Accuracy</th>
                <th style="padding:7px;">Signal</th>
            </tr>
        </thead>
        <tbody>
        {
        "".join(
            [
                f'''<tr style="background:{"#f9fafb" if i % 2 == 0 else "#ffffff"};">
            <td style="padding:7px; font-weight:bold;">{s["stock"]}</td>
            <td style="padding:7px;">{s["conv"].get("Best_Buy_Date", "N/A")}</td>
            <td style="padding:7px;">&#8377;{s["conv"].get("Price_Min", "?")} – &#8377;{s["conv"].get("Price_Max", "?")}</td>
            <td style="padding:7px;">{s["conv"].get("Convergence_Label", "N/A")} {s["conv"].get("Convergence_Pct", "?")}%</td>
            <td style="padding:7px;">{s["conv"].get("Runs_Agreeing", "?")} / {s["conv"].get("Total_Runs", "?")}</td>
            <td style="padding:7px;">{"N/A (new)" if s["acc"].get("Total", 0) < 3 else f"{s['acc'].get('Hit_Rate_Pct', '?')}% ({s['acc'].get('Total', 0)} of last 20)"}</td>
            <td style="padding:7px; font-weight:bold;">{s["signal"]}</td>
        </tr>'''
                for i, s in enumerate(summary or [])
            ]
        )
    }
        </tbody>
    </table>
    <hr style="border:1px solid #ddd;"/>
    <p style="color:#999; font-size:11px;">
        Error % = (Actual &#8722; Predicted) / Predicted &times; 100<br/>
        Negative = model overestimated price (actual was lower = better entry)<br/>
        Positive = model underestimated price (actual was higher)<br/>
        Model-based tracker &#8212; not financial advice.
    </p>
    </body></html>"""


def send_accuracy_email(
    target_date: str,
    new_records: list,
    full_log,
    mae: float,
    bias: float,
    summary: list | None = None,
) -> None:
    sender, password, recipient = _get_credentials()
    if not all([sender, password, recipient]):
        print("  ❌ Email credentials missing.")
        return
    subject = (
        f"🎯 Prediction Accuracy — {target_date} | "
        f"MAE: {mae:.2f}% | {len(new_records)} stocks checked"
    )
    html = _build_accuracy_html(
        target_date=target_date,
        new_records=new_records,
        full_log=full_log,
        mae=mae,
        bias=bias,
        summary=summary,
    )
    _send_single(
        sender,
        password,
        recipient,
        subject=subject,
        html=html,
        label=f"Accuracy Report ({target_date})",
    )
