# ─────────────────────────────────────────────
# alerts.py — WhatsApp notification via Meta Cloud API
# ─────────────────────────────────────────────

import os
import requests
from datetime import datetime


def _build_message(results: dict) -> str:
    today = datetime.today().strftime("%B %Y")
    header = f"📊 *Nifty 500 — Monthly Top Picks*\n📅 {today} | Min hold: 8 months\n\n"

    if not results:
        return header + "⚠️ No stocks matched the criteria this month."

    body = ""
    for band_label, df in results.items():
        body += f"━━━ *{band_label}* ━━━\n"
        for i, row in df.iterrows():
            body += (
                f"*{i + 1}. {row['Stock']}*\n"
                f"  • Buy At:          ₹{row['Buy_Price']}\n"
                f"  • Target:          ₹{row['Exit_Target']} (+{row['Weighted_ROI_%']}%)\n"
                f"  • Hold Until:      {row['Min_Hold_Until']} (minimum)\n"
                f"  • Best Sell Date:  {row['Best_Sell_Date']} 📌\n"
                f"  • Don't Hold Past: {row['Forecast_Expires']} ⚠️\n"
                f"  • Turnover:        ₹{row['Avg_Daily_Turnover_Cr']}Cr/day ({row['Liquidity']})\n\n"
            )

    return header + body.strip()


def send_whatsapp_alert(results: dict) -> None:
    """
    Sends price-band bucketed stock picks to WhatsApp via Meta Cloud API.

    Required environment variables:
        WHATSAPP_TOKEN    — Bearer token from Meta developer console
        PHONE_NUMBER_ID   — WhatsApp Business phone number ID
        RECIPIENT_PHONE   — Recipient in format 91XXXXXXXXXX
    """
    access_token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("PHONE_NUMBER_ID")
    recipient = os.getenv("RECIPIENT_PHONE")

    if not all([access_token, phone_number_id, recipient]):
        print(
            "❌ WhatsApp credentials missing. Set WHATSAPP_TOKEN, PHONE_NUMBER_ID, RECIPIENT_PHONE."
        )
        return

    message = _build_message(results)

    # Split into 4000 char chunks — WhatsApp has a 4096 char limit per message
    chunks = [message[i : i + 4000] for i in range(0, len(message), 4000)]

    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    for idx, chunk in enumerate(chunks):
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": chunk},
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                print(f"✅ WhatsApp message {idx + 1}/{len(chunks)} sent!")
            else:
                print(f"❌ WhatsApp API error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"❌ Failed to reach WhatsApp API: {e}")
