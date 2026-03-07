# ─────────────────────────────────────────────
# alerts.py — Email notification via Gmail SMTP
# ─────────────────────────────────────────────

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


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
                    <th style="padding:7px;">Stock</th>
                    <th style="padding:7px;">Buy At</th>
                    <th style="padding:7px;">Target</th>
                    <th style="padding:7px;">Gross ROI</th>
                    <th style="padding:7px;">After-Tax ROI</th>
                    <th style="padding:7px;">Tax</th>
                    <th style="padding:7px;">Min Hold Until</th>
                    <th style="padding:7px;">Best Sell Date</th>
                    <th style="padding:7px;">Expires</th>
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
                <td style="padding:7px;">₹{row["Buy_Price"]}</td>
                <td style="padding:7px;">₹{row["Exit_Target"]}</td>
                <td style="padding:7px; color:#555;">+{row["Gross_ROI_%"]}%</td>
                <td style="padding:7px; color:#16a34a; font-weight:bold;">+{row["After_Tax_ROI_%"]}%</td>
                <td style="padding:7px; color:{tax_color}; font-weight:bold;">{row["Tax_Type"]}</td>
                <td style="padding:7px;">{row["Min_Hold_Until"]}</td>
                <td style="padding:7px; font-weight:bold;">{row["Best_Sell_Date"]}</td>
                <td style="padding:7px; color:#dc2626;">{row["Forecast_Expires"]}</td>
                <td style="padding:7px;">₹{row["Avg_Daily_Turnover_Cr"]}Cr</td>
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
                💰 <strong>Invested:</strong> ₹{s["Total_Invested"]:,} &nbsp;|&nbsp;
                📈 <strong>Net Profit:</strong> ₹{s["Total_Net_Profit"]:,} &nbsp;|&nbsp;
                🎯 <strong>Portfolio ROI:</strong>
                    <strong style="color:#16a34a;">{s["Portfolio_ROI_%"]}%</strong>
                &nbsp;|&nbsp;
                📅 <strong>Sell Window:</strong> {s["Earliest_Sell"]} → {s["Latest_Sell"]}
            </div>
            <table style="width:100%; border-collapse:collapse; font-size:12px;">
                <thead>
                    <tr style="background:#eef2f7; text-align:left;">
                        <th style="padding:7px;">Stock</th>
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
                    <td style="padding:7px; font-size:11px; color:#555;">{row["Band"]}</td>
                    <td style="padding:7px;">₹{row["Buy_Price"]}</td>
                    <td style="padding:7px; font-weight:bold;">{int(row["Shares"])}</td>
                    <td style="padding:7px;">₹{row["Invested"]:,.0f}</td>
                    <td style="padding:7px;">₹{row["Exit_Target"]}</td>
                    <td style="padding:7px;">₹{row["Exit_Value"]:,.0f}</td>
                    <td style="padding:7px; color:#16a34a; font-weight:bold;">
                        ₹{row["Net_Profit"]:,.0f}
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


def _build_picks_html(results: dict) -> str:
    """Email 1 — Band-wise top picks only. Stays well under 102KB."""
    today = datetime.today().strftime("%B %Y")
    html = f"""
    <html><body style="font-family:Arial,sans-serif; max-width:1000px;
                        margin:auto; color:#1a1a1a;">
    <h2 style="color:#1a1a2e; margin-bottom:4px;">
        📊 Nifty 500 — Top Picks by Price Band
    </h2>
    <p style="color:#555; margin-top:0;">
        📅 {today} &nbsp;|&nbsp; Min hold: 12 months (LTCG) &nbsp;|&nbsp;
        All ROI is <strong>after tax</strong> (LTCG 12.5% + 4% cess + STT)
    </p>
    <p style="color:#777; font-size:13px;">
        📧 This is email 1 of 2. Portfolio combinations follow in the next email.
    </p>
    <hr style="border:1px solid #ddd;"/>
    """
    if not results:
        html += "<p>⚠️ No stocks matched the criteria this month.</p>"
    else:
        html += _band_table(results)
    html += """
    <hr style="border:1px solid #ddd; margin-top:24px;"/>
    <p style="color:#999; font-size:11px;">
        LTCG 12.5% + 4% cess + 0.1% STT. Min hold 12 months.
        Model-based screener — not financial advice.
    </p>
    </body></html>"""
    return html


def _build_portfolio_html(portfolios: list) -> str:
    """Email 2 — Portfolio combinations only. Stays well under 102KB."""
    today = datetime.today().strftime("%B %Y")
    html = f"""
    <html><body style="font-family:Arial,sans-serif; max-width:1000px;
                        margin:auto; color:#1a1a1a;">
    <h2 style="color:#1a1a2e; margin-bottom:4px;">
        💼 Nifty 500 — ₹40,000 Portfolio Combinations
    </h2>
    <p style="color:#555; margin-top:0;">
        📅 {today} &nbsp;|&nbsp;
        📧 This is email 2 of 2. Band-wise picks are in the previous email.
    </p>
    <p style="color:#777; font-size:13px; margin-top:0;">
        10 ways to deploy ₹40,000 this month. Exact share quantities —
        place directly as market orders. Pick the strategy that fits your timeline.
    </p>
    <hr style="border:1px solid #ddd;"/>
    {_portfolio_tables(portfolios)}
    <hr style="border:1px solid #ddd; margin-top:24px;"/>
    <p style="color:#999; font-size:11px;">
        After-tax: LTCG 12.5% + 4% cess + 0.1% STT both legs.
        ₹1.25L LTCG exemption applied per combination.
        Brokerage ₹20/trade (Zerodha). Not financial advice — verify with your CA.
    </p>
    </body></html>"""
    return html


def _build_html(results: dict, portfolios: list) -> str:
    """Legacy combined builder — kept for reference only. Not used."""
    return _build_picks_html(results) + _build_portfolio_html(portfolios)


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
        print(f"✅ {label} sent ({size_kb:.1f} KB)")
        return True
    except smtplib.SMTPAuthenticationError:
        print(
            "❌ Gmail auth failed — use App Password from myaccount.google.com/apppasswords"
        )
        return False
    except Exception as e:
        print(f"❌ Failed to send {label}: {e}")
        return False


def send_email_alert(
    results: dict,
    portfolios: list = None,
    debug: bool = False,
) -> None:
    """
    Sends two separate emails to stay under Gmail 102KB clip limit:
        Email 1 — Part 1: Band-wise top picks
        Email 2 — Part 2: 10 portfolio combinations

    Each email is self-contained so neither gets clipped.
    """
    sender = os.getenv("GMAIL_SENDER", "").strip().strip('"').strip("'")
    password = os.getenv("GMAIL_PASSWORD", "").strip().strip('"').strip("'")
    recipient = os.getenv("GMAIL_RECIPIENT", "").strip().strip('"').strip("'")

    if not all([sender, password, recipient]):
        print("❌ Email credentials missing.")
        return

    if debug:
        print(f"  Sender    : {sender}")
        print(f"  Recipient : {recipient}")
        print(f"  Password  : {'*' * len(password)}")

    today = datetime.today().strftime("%B %Y")

    # ── Email 1: Band-wise picks ──
    _send_single(
        sender,
        password,
        recipient,
        subject=f"📊 [1/2] Nifty 500 Top Picks — {today}",
        html=_build_picks_html(results),
        label="Email 1/2 (Band Picks)",
    )

    # ── Email 2: Portfolio combinations ──
    _send_single(
        sender,
        password,
        recipient,
        subject=f"💼 [2/2] Nifty 500 Portfolio Combinations — {today}",
        html=_build_portfolio_html(portfolios or []),
        label="Email 2/2 (Portfolios)",
    )
