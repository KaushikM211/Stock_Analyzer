# ─────────────────────────────────────────────
# alerts.py — Email notification via Gmail SMTP
# ─────────────────────────────────────────────

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ─────────────────────────────────────────────
# Helpers — HTML builders
# ─────────────────────────────────────────────


def _band_table(results: dict) -> str:
    """Builds band-wise top picks HTML tables."""
    html = ""
    for band_label, df in results.items():
        html += f"""
        <h3 style="color:#0f3460; border-bottom:2px solid #0f3460;
                   padding-bottom:4px; margin-top:28px;">{band_label}</h3>
        <table style="width:100%; border-collapse:collapse; font-size:12px; margin-bottom:16px;">
            <thead>
                <tr style="background:#0f3460; color:white; text-align:left;">
                    <th style="padding:7px;">#</th>
                    <th style="padding:7px;">Ticker</th>
                    <th style="padding:7px;">Company</th>
                    <th style="padding:7px;">Buy At</th>
                    <th style="padding:7px;">Target</th>
                    <th style="padding:7px;">Gross ROI</th>
                    <th style="padding:7px;">After-Tax ROI</th>
                    <th style="padding:7px;">Tax</th>
                    <th style="padding:7px;">Min Hold Until</th>
                    <th style="padding:7px;">Best Sell Date</th>
                    <th style="padding:7px;">Expires</th>
                    <th style="padding:7px;">Best Buy Date</th>
                    <th style="padding:7px;">Predicted Buy Price</th>
                    <th style="padding:7px;">Turnover</th>
                </tr>
            </thead>
            <tbody>
        """
        for i, row in df.iterrows():
            bg = "#f5f5f5" if i % 2 == 0 else "#ffffff"
            tax_color = "#16a34a" if row["Tax_Type"] == "LTCG" else "#d97706"
            html += f"""
            <tr style="background:{bg};">
                <td style="padding:7px;">{i + 1}</td>
                <td style="padding:7px; font-weight:bold;">{row["Stock"]}</td>
                <td style="padding:7px; color:#555;">{row.get("Company_Name", "")}</td>
                <td style="padding:7px;">&#8377;{row["Buy_Price"]}</td>
                <td style="padding:7px;">&#8377;{row["Exit_Target"]}</td>
                <td style="padding:7px; color:#555;">+{row["Gross_ROI_%"]}%</td>
                <td style="padding:7px; color:#16a34a; font-weight:bold;">+{row["After_Tax_ROI_%"]}%</td>
                <td style="padding:7px; color:{tax_color}; font-weight:bold;">{row["Tax_Type"]}</td>
                <td style="padding:7px;">{row["Min_Hold_Until"]}</td>
                <td style="padding:7px; font-weight:bold;">{row["Best_Sell_Date"]}</td>
                <td style="padding:7px; color:#dc2626;">{row["Forecast_Expires"]}</td>
                <td style="padding:7px;">&#8377;{row["Avg_Daily_Turnover_Cr"]}Cr</td>
            </tr>
            """
        html += "</tbody></table>"
    return html


def _portfolio_tables(portfolios: list) -> str:
    """Builds HTML for all 10 portfolio combinations."""
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
    ]

    for i, combo in enumerate(portfolios):
        s = combo["summary"]
        pf = combo["portfolio"]
        color = colors[i % len(colors)]

        html += f"""
        <div style="margin-top:28px; border:1px solid #ddd; border-radius:6px;
                    overflow:hidden;">
            <div style="background:{color}; color:white; padding:12px 16px;">
                <span style="font-size:15px; font-weight:bold;">
                    #{i + 1} — {combo["name"]}
                </span><br/>
                <span style="font-size:12px; opacity:0.85;">{combo["description"]}</span>
            </div>
            <div style="background:#f9f9f9; padding:10px 16px;">
                &#128176; <strong>Invested:</strong> &#8377;{s["Total_Invested"]:,} &nbsp;|&nbsp;
                &#128200; <strong>Net Profit:</strong> &#8377;{s["Total_Net_Profit"]:,} &nbsp;|&nbsp;
                &#127919; <strong>Portfolio ROI:</strong>
                    <strong style="color:#16a34a;">{s["Portfolio_ROI_%"]}%</strong>
                &nbsp;|&nbsp;
                &#128197; <strong>Sell Window:</strong> {s["Earliest_Sell"]} &rarr; {s["Latest_Sell"]}
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:12px;">
                <thead>
                    <tr style="background:#eef2f7; text-align:left;">
                        <th style="padding:7px;">Ticker</th>
                        <th style="padding:7px;">Company</th>
                        <th style="padding:7px;">Band</th>
                        <th style="padding:7px;">Buy At</th>
                        <th style="padding:7px;">Shares</th>
                        <th style="padding:7px;">Invested</th>
                        <th style="padding:7px;">Exit Target</th>
                        <th style="padding:7px;">Exit Value</th>
                        <th style="padding:7px;">Net Profit</th>
                        <th style="padding:7px;">Net ROI %</th>
                        <th style="padding:7px;">Best Sell Date</th>
                        <th style="padding:7px;">Expires</th>
                    </tr>
                </thead>
                <tbody>
        """
        for j, row in pf.iterrows():
            bg = "#ffffff" if j % 2 == 0 else "#f5f5f5"
            html += f"""
                <tr style="background:{bg};">
                    <td style="padding:7px; font-weight:bold;">{row["Stock"]}</td>
                    <td style="padding:7px; color:#555;">{row.get("Company_Name", "")}</td>
                    <td style="padding:7px; font-size:11px; color:#555;">{row["Band"]}</td>
                    <td style="padding:7px;">&#8377;{row["Buy_Price"]}</td>
                    <td style="padding:7px; font-weight:bold;">{int(row["Shares"])}</td>
                    <td style="padding:7px;">&#8377;{row["Invested"]:,.0f}</td>
                    <td style="padding:7px;">&#8377;{row["Exit_Target"]}</td>
                    <td style="padding:7px;">&#8377;{row["Exit_Value"]:,.0f}</td>
                    <td style="padding:7px; color:#16a34a; font-weight:bold;">
                        &#8377;{row["Net_Profit"]:,.0f}
                    </td>
                    <td style="padding:7px; color:#16a34a; font-weight:bold;">
                        +{row["Net_ROI_%"]}%
                    </td>
                    <td style="padding:7px; font-weight:bold;">{row["Best_Sell_Date"]}</td>
                    <td style="padding:7px; color:#dc2626;">{row["Forecast_Expires"]}</td>
                </tr>
            """
        html += "</tbody></table></div>"
    return html


# ─────────────────────────────────────────────
# Email 1 — Band-wise picks
# ─────────────────────────────────────────────


def _build_picks_html(results: dict) -> str:
    """Email 1 — Band-wise top picks only. Stays well under 102KB."""
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
# Email 2 — Portfolio combinations
# ─────────────────────────────────────────────


def _build_portfolio_html(portfolios: list) -> str:
    """Email 2 — Portfolio combinations only. Stays well under 102KB."""
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
        10 ways to deploy &#8377;1,00,000 this month. Exact share quantities &mdash;
        place directly as market orders. Pick the strategy that fits your timeline.
    </p>
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
    """Builds improvement alert email HTML."""
    now = datetime.now().strftime("%I:%M %p")
    today = datetime.today().strftime("%d %b %Y")
    s = best_combo.get("summary", {})
    pf = best_combo.get("portfolio", [])

    # ── Stocks with better entry price ──
    improved_rows = ""
    for i, st in enumerate(improved_stocks):
        bg = "#fffbeb" if i % 2 == 0 else "#ffffff"
        improved_rows += f"""
        <tr style="background:{bg};">
            <td style="padding:8px; font-weight:bold;">{st["ticker"]}</td>
            <td style="padding:8px; color:#555;">{st["company"]}</td>
            <td style="padding:8px; color:#6b7280;">&#8377;{st["prev_price"]}</td>
            <td style="padding:8px; color:#16a34a; font-weight:bold;">&#8377;{st["curr_price"]}</td>
            <td style="padding:8px; color:#dc2626; font-weight:bold;">&#9660; {st["pct_drop"]}%</td>
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
                </tr>
            </thead>
            <tbody>{improved_rows}</tbody>
        </table>"""

    # ── Best combo table ──
    combo_rows = ""
    for i, row in enumerate(pf):
        bg = "#f9fafb" if i % 2 == 0 else "#ffffff"
        combo_rows += f"""
        <tr style="background:{bg};">
            <td style="padding:7px; font-weight:bold;">{row.get("Stock", "")}</td>
            <td style="padding:7px; color:#555;">{row.get("Company_Name", "")}</td>
            <td style="padding:7px;">&#8377;{row.get("Buy_Price", "")}</td>
            <td style="padding:7px; font-weight:bold;">{int(row.get("Shares", 0))}</td>
            <td style="padding:7px;">&#8377;{float(row.get("Invested", 0)):,.0f}</td>
            <td style="padding:7px; color:#16a34a; font-weight:bold;">
                +{row.get("Net_ROI_%", "")}%
            </td>
            <td style="padding:7px;">{row.get("Best_Sell_Date", "")}</td>
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
            </tr>
        </thead>
        <tbody>{combo_rows}</tbody>
    </table>

    <hr style="border:1px solid #ddd;"/>
    <p style="color:#999; font-size:11px;">
        Improvement threshold: 1.5% | Run: {run_label} at {now}<br/>
        Model-based screener &mdash; not financial advice. Verify before investing.
    </p>
    </body></html>"""


# ─────────────────────────────────────────────
# Send helpers
# ─────────────────────────────────────────────


def _send_single(
    sender: str,
    password: str,
    recipient: str,
    subject: str,
    html: str,
    label: str,
) -> bool:
    """Send one email. Returns True on success."""
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
# Public API
# ─────────────────────────────────────────────


def send_email_alert(
    results: dict,
    portfolios: list = None,
    debug: bool = False,
) -> None:
    """
    Monthly full report — sends two emails:
        Email 1 — Band-wise top picks
        Email 2 — 10 portfolio combinations
    """
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
    """
    Intraday improvement alert — single email.
    Fired when best portfolio ROI improves by >= 1.5% vs previous runs today.
    """
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


def _build_accuracy_html(
    target_date: str,
    new_records: list,
    full_log,
    mae: float,
    bias: float,
) -> str:
    """Builds accuracy report email HTML."""
    today = __import__("datetime").datetime.today().strftime("%d %b %Y")

    # ── New records table ──
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
            <td style="padding:7px; font-weight:bold;">&#8377;{r["Actual_Close"]}</td>
            <td style="padding:7px; color:{err_color}; font-weight:bold;">
                {dir_icon} {err:+.2f}%
            </td>
            <td style="padding:7px; color:#6b7280;">{r["Scan_Date"]}</td>
        </tr>"""

    # ── All-time accuracy stats ──
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
                    <span style="color:{"#dc2626" if bias > 0 else "#16a34a"}; font-weight:bold;">
                        {bias:+.2f}% ({"overestimates" if bias > 0 else "underestimates"})
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
                <th style="padding:7px;">Actual Close</th>
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
) -> None:
    """Sends prediction accuracy report email."""
    sender, password, recipient = _get_credentials()
    if not all([sender, password, recipient]):
        print("  ❌ Email credentials missing.")
        return

    subject = (
        f"&#127919; Prediction Accuracy — {target_date} | "
        f"MAE: {mae:.2f}% | {len(new_records)} stocks checked"
    )

    html = _build_accuracy_html(
        target_date=target_date,
        new_records=new_records,
        full_log=full_log,
        mae=mae,
        bias=bias,
    )

    _send_single(
        sender,
        password,
        recipient,
        subject=subject,
        html=html,
        label=f"Accuracy Report ({target_date})",
    )
