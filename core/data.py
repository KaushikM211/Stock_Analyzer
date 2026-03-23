# ─────────────────────────────────────────────
# data.py — Fetching tickers, stock data, fundamentals, sector momentum
#
# v2 CHANGE: Hard binary fundamental filter replaced with composite
# risk scoring. Models now run on ALL Nifty 500 stocks with valid
# price data. Fundamentals produce a score (0–100) and label
# (Low / Medium / High risk) shown in the email and used by
# portfolio.py to build risk-tiered combinations.
# ─────────────────────────────────────────────

import logging
import pandas as pd
import yfinance as yf
from yfinance import download
from nsepython import nsefetch

from .config import (
    FETCH_PERIODS,
    MIN_DAYS,
    SECTOR_ETFS,
    TOP_SECTORS_COUNT,
    RISK_THRESHOLD_LOW,
    RISK_THRESHOLD_HIGH,
)

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

MIN_PE_RATIO = 1.0  # PE below this = negative earnings → PE_m = 4.0 (max)

# ─────────────────────────────────────────────
# INDUSTRY PE LIMITS
# Keys match ACTUAL yfinance industry strings (hyphen, not em-dash)
# Verified against live yfinance data for NSE stocks
# ─────────────────────────────────────────────
INDUSTRY_PE_LIMITS = {
    # Banks — yfinance returns these exact strings for Indian banks
    "Banks - Regional": 22,  # SBI, Axis, IDBI, J&K Bank
    "Banks - Diversified": 28,  # HDFC Bank, ICICI, Kotak
    # Financial services
    "Consumer Finance": 45,  # Bajaj Finance, Chola, M&M Fin
    "Insurance - Life": 65,  # HDFC Life, SBI Life, Max Life
    "Insurance - Diversified": 55,  # Star Health, ICICI Lombard
    "Capital Markets": 40,  # Motilal Oswal, Angel One, CDSL, BSE
    "Mortgage Finance": 38,  # Can Fin Homes, LIC Housing, PNB Housing
    "Credit Services": 45,  # CreditAccess, Ujjivan
    "Financial Conglomerates": 35,  # Bajaj Holdings
    # Industrials
    "Electronic Components": 79,  # Dixon, Amber — PLI/EMS
    "Aerospace & Defense": 48,  # HAL, BEL, GRSE
    "Specialty Industrial Machinery": 75,  # Siemens, ABB, Cummins
    "Engineering & Construction": 45,  # L&T, NCC, KNR
    "Farm & Heavy Construction Machinery": 45,  # Escorts, BEML
    "Electrical Equipment & Parts": 60,  # Polycab, KEI, Havells
    # Technology
    "Software - Application": 85,  # KPIT, Tata Elxsi, Persistent
    "Information Technology Services": 50,  # TCS, Infosys, Wipro
    "Software - Infrastructure": 65,
    # Healthcare
    "Medical Care Facilities": 85,  # Apollo, Narayana, Max
    "Drug Manufacturers - General": 54,  # Sun Pharma, Dr Reddy, Cipla
    "Drug Manufacturers - Specialty & Generic": 50,
    "Medical Devices": 60,
    # Utilities
    "Utilities - Regulated Electric": 38,  # NTPC, Power Grid
    "Utilities - Renewable": 53,  # Tata Power
    "Utilities - Independent Power Producers": 45,
    # Energy
    "Oil & Gas E&P": 25,  # ONGC, Oil India
    "Oil & Gas Refining & Marketing": 20,  # BPCL, HPCL, IOC
    "Oil & Gas Midstream": 25,  # GAIL, Petronet
    # Auto
    "Auto Manufacturers": 25,  # Maruti, Tata Motors, M&M
    "Auto Parts": 30,  # Motherson, Bosch, Minda
    # Telecom
    "Telecom Services": 50,  # Airtel, Indus Towers
    # Retail
    "Specialty Retail": 60,  # Trent, DMart
}

SECTOR_PE_LIMITS = {
    "Financial Services": 45,
    "Utilities": 25,
    "Infrastructure": 40,
    "Energy": 18,
    "Real Estate": 65,
    "Industrials": 65,
    "Basic Materials": 55,
    "Materials": 50,
    "Consumer Cyclical": 78,
    "Consumer Defensive": 65,
    "Technology": 50,
    "Healthcare": 76,
    "Communication Services": 45,
    "Communication": 45,
}
DEFAULT_PE_LIMIT = 55

# ─────────────────────────────────────────────
# SECTOR D/E LIMITS
# None = financial sector exempt
# ─────────────────────────────────────────────
SECTOR_DEBT_LIMITS = {
    "Financial Services": None,
    "Banking": None,
    "Insurance": None,
    "NBFC": None,
    "Housing Finance": None,
    "Microfinance": None,
    "Utilities": 5.50,
    "Infrastructure": 5.75,
    "Energy": 4.75,
    "Oil & Gas": 5.25,
    "Real Estate": 4.25,
    "Industrials": 3.50,
    "Basic Materials": 3.25,
    "Materials": 2.75,
    "Consumer Cyclical": 2.55,
    "Consumer Defensive": 2.25,
    "Technology": 2.00,
    "Healthcare": 2.75,
    "Communication Services": 5.25,  # Airtel — yfinance uses this exact string
    "Communication": 5.25,  # fallback for older mappings
}
DEFAULT_DEBT_LIMIT = 2.65

# ─────────────────────────────────────────────
# TICKER ALIASES — known mergers/renames
# ─────────────────────────────────────────────
TICKER_ALIASES = {
    "ADANITRANS.NS": "ADANIENSOL.NS",
    "HDFC.NS": "HDFCBANK.NS",
    "MINDTREE.NS": "LTIM.NS",
    "LTINFOTECH.NS": "LTIM.NS",
    "HDFCLIFE.NS": "HDFCLIFE.NS",
}

# ─────────────────────────────────────────────
# COMPANY NAME MAP
# yfinance returns ticker symbol instead of name for many NSE mid/small caps
# This map ensures clean display names in emails
# ─────────────────────────────────────────────
_COMPANY_NAME_MAP = {
    "GPPL": "Gujarat Pipavav Port Ltd",
    "JYOTICNC": "Jyoti CNC Automation Ltd",
    "VARROC": "Varroc Engineering Ltd",
    "JAMNAAUTO": "Jamna Auto Industries Ltd",
    "APLAPOLLO": "APL Apollo Tubes Ltd",
    "SYRMA": "Syrma SGS Technology Ltd",
    "KAYNES": "Kaynes Technology India Ltd",
    "SENCO": "Senco Gold Ltd",
    "UPDATER": "Updater Services Ltd",
    "RVNL": "Rail Vikas Nigam Ltd",
    "INOXWIND": "Inox Wind Ltd",
    "EMCURE": "Emcure Pharmaceuticals Ltd",
    "CELLO": "Cello World Ltd",
    "NYKAA": "FSN E-Commerce Ventures Ltd",
    "PAYTM": "One 97 Communications Ltd",
    "KALYANKJIL": "Kalyan Jewellers India Ltd",
    "JBMA": "JBM Auto Ltd",
    "JTEKTINDIA": "JTEKT India Ltd",
    "MAHSEAMLES": "Maharashtra Seamless Ltd",
    "SHYAMMETL": "Shyam Metalics and Energy Ltd",
    "NSLNISP": "NMDC Steel Ltd",
    "HLEGLAS": "HLE Glascoat Ltd",
    "HSCL": "Himadri Speciality Chemical Ltd",
    "LATENTVIEW": "LatentView Analytics Ltd",
    "TEJASNET": "Tejas Networks Ltd",
    "BALAMINES": "Balaji Amines Ltd",
    "ALKYLAMINE": "Alkyl Amines Chemicals Ltd",
    "FLUOROCHEM": "Gujarat Fluorochemicals Ltd",
    "VINATIORGA": "Vinati Organics Ltd",
    "DEEPAKNTR": "Deepak Nitrite Ltd",
    "NAVINFLUOR": "Navin Fluorine International Ltd",
    "DATAMATICS": "Datamatics Global Services Ltd",
    "IONGRID": "Ion Exchange India Ltd",
    "SAMMAANCAP": "Sammaan Capital Ltd",
    "NAM-INDIA": "Nippon India Mutual Fund",
    "CREDITACC": "CreditAccess Grameen Ltd",
    "GRAPHITE": "Graphite India Ltd",
    "ASAHIINDIA": "Asahi India Glass Ltd",
}


# ─────────────────────────────────────────────
# TICKER FETCHING — nsepython primary source
# ─────────────────────────────────────────────


def get_nifty500_tickers():
    """
    Fetches the Nifty 500 stock list via NSE API using nsepython.
    nsepython handles session cookies and headers automatically.
    """
    try:
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
        payload = nsefetch(url)

        if "data" not in payload:
            print("Error: Could not find 'data' key in NSE response.")
            return []

        yf_tickers = [
            f"{stock['symbol']}.NS"
            for stock in payload["data"]
            if stock["symbol"] != "NIFTY 500"
        ]

        # Apply known ticker aliases
        result = []
        seen = set()
        for t in yf_tickers:
            resolved = TICKER_ALIASES.get(t, t)
            if resolved not in seen:
                result.append(resolved)
                seen.add(resolved)

        print(f"  ✓ Fetched {len(result)} tickers via nsepython")
        return result

    except Exception as e:
        print(f"Error fetching Nifty 500 tickers: {e}")
        return []


# ─────────────────────────────────────────────
# DATA QUALITY CHECK
# ─────────────────────────────────────────────


def _is_clean(close: pd.Series, volume: pd.Series) -> bool:
    if close is None or volume is None:
        return False
    if len(close) < MIN_DAYS:
        return False
    if close.isna().any() or volume.isna().any():
        return False
    price_range = close.max() - close.min()
    if price_range < close.mean() * 0.01:
        return False
    zero_vol_pct = (volume == 0).sum() / len(volume)
    if zero_vol_pct > 0.10:
        return False
    return True


# ─────────────────────────────────────────────
# FUNDAMENTALS FETCH
# ─────────────────────────────────────────────

_fundamentals_cache: dict = {}


def fetch_fundamentals(ticker: str) -> dict | None:
    if ticker in _fundamentals_cache:
        return _fundamentals_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        debt_to_equity = info.get("debtToEquity")
        revenue_growth = info.get("revenueGrowth")
        sector = info.get("sector", "")
        # yfinance returns D/E as percentage × 100 (e.g. 150 = 1.5x D/E)
        # Normalise by always dividing by 100 — the raw value is never
        # a meaningful ratio directly (a D/E of 15 means 0.15x, not 15x)
        if debt_to_equity is not None:
            debt_to_equity = debt_to_equity / 100

        # Company name — use yfinance first, fall back to known map, then ticker
        company_name = info.get("longName") or info.get("shortName")
        if not company_name:
            symbol = ticker.replace(".NS", "")
            company_name = _COMPANY_NAME_MAP.get(symbol, symbol)

        industry = info.get("industry", "")
        ebit = info.get("ebit")
        interest_expense = info.get("interestExpense")
        interest_coverage = None
        if ebit is not None and interest_expense and interest_expense < 0:
            interest_coverage = ebit / abs(interest_expense)

        # ── Additional quality metrics ──
        roe = info.get("returnOnEquity")  # Net Income / Equity — capital efficiency
        ev_to_ebitda = info.get("enterpriseToEbitda")  # Valuation vs operating profit
        operating_cashflow = info.get("operatingCashflow")
        net_income = info.get("netIncomeToCommon") or info.get("netIncome")
        # Earnings quality: cash flow / net income — ratio < 0.8 = earnings not backed by cash
        earnings_quality = None
        if operating_cashflow and net_income and net_income != 0:
            earnings_quality = operating_cashflow / abs(net_income)

        # Net Debt / EBITDA — more accurate leverage than D/E for capital-heavy sectors
        total_debt = info.get("totalDebt")
        cash = info.get("totalCash") or info.get("cash")
        ebitda = info.get("ebitda")
        net_debt_to_ebitda = None
        if total_debt is not None and ebitda and ebitda > 0:
            net_debt = total_debt - (cash or 0)
            net_debt_to_ebitda = net_debt / ebitda

        result = {
            "pe_ratio": pe_ratio,
            "debt_to_equity": debt_to_equity,
            "revenue_growth": revenue_growth,
            "sector": sector,
            "industry": industry,
            "interest_coverage": interest_coverage,
            "company_name": company_name,
            "roe": roe,
            "ev_to_ebitda": ev_to_ebitda,
            "earnings_quality": earnings_quality,
            "net_debt_to_ebitda": net_debt_to_ebitda,
        }
        _fundamentals_cache[ticker] = result
        return result
    except Exception:
        _fundamentals_cache[ticker] = None
        return None


# ─────────────────────────────────────────────
# PE / D/E LIMIT HELPERS
# ─────────────────────────────────────────────


def _get_pe_limit(sector: str, industry: str) -> float:
    """Resolve PE limit — industry first, sector fallback, bidirectional match."""
    industry_lower = industry.lower()
    for ind_key, limit in INDUSTRY_PE_LIMITS.items():
        ind_key_lower = ind_key.lower()
        # Bidirectional match handles yfinance string variations
        if ind_key_lower in industry_lower or industry_lower in ind_key_lower:
            return limit
    for sector_key, limit in SECTOR_PE_LIMITS.items():
        if sector_key.lower() in sector.lower():
            return limit
    return DEFAULT_PE_LIMIT


def _get_de_limit(sector: str) -> float | None:
    """Resolve D/E limit. None = financial sector, no cap."""
    for sector_key, limit in SECTOR_DEBT_LIMITS.items():
        if sector_key.lower() in sector.lower():
            return limit
    return DEFAULT_DEBT_LIMIT


# ─────────────────────────────────────────────
# COMPOSITE RISK SCORER
# Replaces passes_fundamental_filter() entirely.
# Every stock gets a score — nothing is excluded.
# Risk is informational, shown in email, used by portfolio tiering.
# ─────────────────────────────────────────────


def score_fundamental_risk(ticker: str) -> tuple[str, float, list[str]]:
    """
    Returns (risk_label, risk_score, reasons).

    risk_label : "Low" | "Medium" | "High"
    risk_score : int 1–100 (lower = safer)
    reasons    : human-readable explanation per multiplier

    Multiplicative model:
        raw = PE_m × DE_m × Rev_m × Data_m × ICR_m
        Log-normalised to 1–100.

    Multipliers:
        PE_m   — 1.0 within limit, up to 4.0× at 2× limit
        DE_m   — 1.0 within limit, up to 3.5×; financial sector always 1.0×
        Rev_m  — 0.85× for ≥15% growth, 1.0× flat, up to 2.2× at −15% decline
        Data_m — 1.0× complete, 1.2/1.5/1.9× for 1/2/3 missing fields
        ICR_m  — only when D/E>4×; 1.0× if ICR≥3×, up to 2.5× if ICR<1×
    """
    fundamentals = fetch_fundamentals(ticker)
    reasons = []

    if fundamentals is None:
        raw = 1.0 * 1.0 * 1.0 * 1.9 * 1.0
        score = _normalise_raw(raw)
        reasons.append("No fundamental data — uncertainty multiplier 1.9×")
        return _label(score), score, reasons

    pe = fundamentals.get("pe_ratio")
    de = fundamentals.get("debt_to_equity")
    rev_gr = fundamentals.get("revenue_growth")
    sector = fundamentals.get("sector", "")
    industry = fundamentals.get("industry", "")
    icr = fundamentals.get("interest_coverage")
    roe = fundamentals.get("roe")
    ev_to_ebitda = fundamentals.get("ev_to_ebitda")
    earnings_quality = fundamentals.get("earnings_quality")
    net_debt_ebitda = fundamentals.get("net_debt_to_ebitda")

    fields_missing = sum(1 for v in [pe, de, rev_gr] if v is None)

    # ── PE multiplier ──
    if pe is None:
        pe_m = 1.0
        reasons.append("PE unavailable — no multiplier")
    elif pe < MIN_PE_RATIO:
        pe_m = 4.0
        reasons.append(f"PE={pe:.1f} — negative earnings (4.0×)")
    else:
        pe_limit = _get_pe_limit(sector, industry)
        x = pe / pe_limit
        if x <= 1.0:
            pe_m = 1.0
            reasons.append(f"PE={pe:.1f} within limit={pe_limit} (1.0×)")
        else:
            pe_m = min(1.0 + (x - 1.0) ** 1.5 * 3.0, 4.0)
            reasons.append(f"PE={pe:.1f} vs limit={pe_limit} → {x:.2f}× ({pe_m:.2f}×)")

    # ── D/E multiplier ──
    de_limit = _get_de_limit(sector)
    if de_limit is None:
        de_m = 1.0
        reasons.append("D/E exempt — financial sector (1.0×)")
    elif de is None:
        de_m = 1.0
        reasons.append("D/E unavailable — no multiplier")
    else:
        x = de / de_limit
        if x <= 1.0:
            de_m = 1.0
            reasons.append(f"D/E={de:.2f} within limit={de_limit} (1.0×)")
        else:
            de_m = min(1.0 + (x - 1.0) ** 1.4 * 2.5, 3.5)
            reasons.append(f"D/E={de:.2f} vs limit={de_limit} → {x:.2f}× ({de_m:.2f}×)")

    # ── Revenue growth multiplier ──
    if rev_gr is None:
        rev_m = 1.0
        reasons.append("Revenue growth unavailable — no multiplier")
    else:
        pct = rev_gr * 100
        if pct >= 15:
            rev_m = 0.85
        elif pct >= 0:
            rev_m = 1.0 - (pct / 15.0) * 0.15
        else:
            severity = min(abs(pct) / 15.0, 1.0)
            rev_m = 1.0 + severity**1.2 * 1.2
        reasons.append(f"Revenue growth={pct:.1f}% → {rev_m:.2f}×")

    # ── Data completeness multiplier ──
    data_m = {0: 1.0, 1: 1.2, 2: 1.5, 3: 1.9}[fields_missing]
    if fields_missing > 0:
        reasons.append(f"{fields_missing} field(s) missing → {data_m}×")
    else:
        reasons.append("All 3 fields present (1.0×)")

    # ── Interest coverage multiplier (only D/E > 4× non-financial) ──
    icr_m = 1.0
    if de is not None and de_limit is not None and de > 4.0:
        if icr is None:
            icr_m = 1.5
            reasons.append(f"D/E={de:.2f}>4× ICR unknown (1.5×)")
        elif icr >= 3.0:
            icr_m = 1.0
            reasons.append(f"D/E={de:.2f}>4× ICR={icr:.1f}× adequate (1.0×)")
        else:
            severity = min((3.0 - icr) / 3.0, 1.0)
            icr_m = 1.0 + severity**1.3 * 1.5
            reasons.append(f"D/E={de:.2f}>4× ICR={icr:.1f}× low ({icr_m:.2f}×)")

    # ── 6. ROE multiplier ──
    # Low ROE = poor capital allocation = shareholder value being destroyed
    # Sector-adjusted: utilities/infra accept lower ROE due to regulated returns
    # Financial sector: ROE above 12% is strong, below 8% is concerning
    roe_m = 1.0
    if roe is not None:
        is_financial = _get_de_limit(sector) is None
        is_utility = "utilit" in sector.lower() or "infrastructure" in sector.lower()
        roe_pct = roe * 100
        if is_financial:
            # Banks/NBFCs: ROE < 8% is poor, ROE > 15% is strong
            if roe_pct < 8:
                roe_m = 1.0 + min((8 - roe_pct) / 8, 1.0) ** 1.2 * 1.8
                reasons.append(
                    f"ROE={roe_pct:.1f}% — low for financial sector ({roe_m:.2f}×)"
                )
            else:
                reasons.append(f"ROE={roe_pct:.1f}% — acceptable (1.0×)")
        elif is_utility:
            # Utilities: ROE < 6% is poor (regulated returns are inherently lower)
            if roe_pct < 6:
                roe_m = 1.0 + min((6 - roe_pct) / 6, 1.0) ** 1.2 * 1.2
                reasons.append(
                    f"ROE={roe_pct:.1f}% — low for utility sector ({roe_m:.2f}×)"
                )
            else:
                reasons.append(f"ROE={roe_pct:.1f}% — acceptable for utility (1.0×)")
        else:
            # All others: ROE < 10% is poor capital allocation
            if roe_pct < 10:
                roe_m = 1.0 + min((10 - roe_pct) / 10, 1.0) ** 1.2 * 1.8
                reasons.append(
                    f"ROE={roe_pct:.1f}% — poor capital allocation ({roe_m:.2f}×)"
                )
            elif roe_pct >= 20:
                roe_m = 0.90  # strong ROE gives a small reward
                reasons.append(f"ROE={roe_pct:.1f}% — strong (0.90×)")
            else:
                reasons.append(f"ROE={roe_pct:.1f}% — adequate (1.0×)")
    else:
        reasons.append("ROE unavailable — no multiplier")

    # ── 7. EV/EBITDA multiplier ──
    # High EV/EBITDA = expensive relative to operating profit
    # Sector-adjusted limits — growth sectors command higher multiples
    ev_m = 1.0
    if ev_to_ebitda is not None and ev_to_ebitda > 0:
        is_financial = _get_de_limit(sector) is None
        if is_financial:
            ev_m = 1.0  # EV/EBITDA not meaningful for banks
            reasons.append("EV/EBITDA exempt — financial sector (1.0×)")
        else:
            # Sector-specific EV/EBITDA limits
            ev_lim = (
                30
                if "technology" in sector.lower() or "software" in industry.lower()
                else 25
                if "healthcare" in sector.lower()
                else 18
                if "consumer" in sector.lower()
                else 15
                if "energy" in sector.lower() or "utility" in sector.lower()
                else 22
            )  # default
            if ev_to_ebitda > ev_lim:
                x = ev_to_ebitda / ev_lim
                ev_m = min(1.0 + (x - 1.0) ** 1.3 * 1.5, 3.0)
                reasons.append(
                    f"EV/EBITDA={ev_to_ebitda:.1f}x vs limit={ev_lim}x ({ev_m:.2f}×)"
                )
            else:
                reasons.append(
                    f"EV/EBITDA={ev_to_ebitda:.1f}x within limit={ev_lim}x (1.0×)"
                )
    else:
        reasons.append("EV/EBITDA unavailable — no multiplier")

    # ── 8. Earnings quality multiplier ──
    # Operating cash flow / Net income — ratio < 0.8 means earnings not backed by cash
    # Very common in infrastructure/solar where revenue is booked but cash arrives later
    eq_m = 1.0
    if earnings_quality is not None:
        if earnings_quality < 0:
            eq_m = (
                1.8  # negative operating cashflow despite positive earnings = red flag
            )
            reasons.append(
                f"Earnings quality={earnings_quality:.2f} — negative operating cashflow (1.8×)"
            )
        elif earnings_quality < 0.5:
            eq_m = 1.4
            reasons.append(
                f"Earnings quality={earnings_quality:.2f} — very low cash backing (1.4×)"
            )
        elif earnings_quality < 0.7:
            eq_m = 1.25
            reasons.append(
                f"Earnings quality={earnings_quality:.2f} — below 0.8 threshold (1.25×)"
            )
        else:
            reasons.append(f"Earnings quality={earnings_quality:.2f} — adequate (1.0×)")
    else:
        reasons.append("Earnings quality unavailable — no multiplier")

    # ── 9. Net Debt/EBITDA multiplier ──
    # More meaningful than D/E for capital-heavy sectors (infra, solar, telecom)
    # Net Debt = Total Debt - Cash. High ratio = takes many years to repay debt
    ndeb_m = 1.0
    if net_debt_ebitda is not None:
        is_utility_or_infra = (
            "utilit" in sector.lower() or "infrastructure" in sector.lower()
        )
        nd_lim = 6.0 if is_utility_or_infra else 3.5
        if net_debt_ebitda > nd_lim:
            x = net_debt_ebitda / nd_lim
            ndeb_m = min(1.0 + (x - 1.0) ** 1.3 * 1.5, 2.5)
            reasons.append(
                f"Net Debt/EBITDA={net_debt_ebitda:.1f}x vs limit={nd_lim}x ({ndeb_m:.2f}×)"
            )
        elif net_debt_ebitda < 0:
            ndeb_m = 0.95  # net cash position — small reward
            reasons.append(
                f"Net Debt/EBITDA={net_debt_ebitda:.1f}x — net cash position (0.95×)"
            )
        else:
            reasons.append(
                f"Net Debt/EBITDA={net_debt_ebitda:.1f}x within limit={nd_lim}x (1.0×)"
            )
    else:
        reasons.append("Net Debt/EBITDA unavailable — no multiplier")

    raw = pe_m * de_m * rev_m * data_m * icr_m * roe_m * ev_m * eq_m * ndeb_m
    score = _normalise_raw(raw)
    return _label(score), score, reasons


def _normalise_raw(raw: float) -> int:
    import math

    # Calibration:
    #   MIN_RAW = 0.72  — best case: strong growth (0.85×) × all others 1.0×
    #   MAX_RAW = 12.0  — realistic worst case for Nifty 500 stocks
    #   raw=0.85 → ~7   (great: strong growth, all metrics clean)
    #   raw=1.0  → ~13  (decent: flat growth, all metrics within limits)
    #   raw=2.0  → ~37  (concern: one or two borderline metrics)
    #   raw=3.0  → ~51  (multiple flags)
    #   raw=5.0  → ~69  (serious: PE + D/E + declining revenue)
    #   raw=8.0+ → ~86+ (extreme — rare in Nifty 500)
    MIN_RAW = 0.72
    MAX_RAW = 12.0
    log_raw = math.log(max(raw, MIN_RAW))
    log_min = math.log(MIN_RAW)
    log_max = math.log(MAX_RAW)
    score = 1 + (log_raw - log_min) / (log_max - log_min) * 99
    return int(round(max(1, min(100, score))))


def _label(score: int) -> str:
    if score <= RISK_THRESHOLD_LOW:
        return "Low"
    elif score <= RISK_THRESHOLD_HIGH:
        return "Medium"
    return "High"


def passes_fundamental_filter(ticker: str) -> tuple[bool, str]:
    """
    Backwards-compat shim — always returns True.
    Risk scoring is now done via score_fundamental_risk().
    Kept so __init__.py and any old callers don't break.
    """
    label, score, reasons = score_fundamental_risk(ticker)
    return True, f"{label} risk (score={score})"


def fundamental_quality_score(ticker: str) -> float:
    """
    Returns a quality score 0.0–1.0 used to adjust ensemble weights.

    1.0 = excellent fundamentals → base weights unchanged
    0.0 = terrible fundamentals → Prophet/Holt reduced, VPR increased

    Three factors:
        ROE (40%)              — capital efficiency
        Earnings quality (35%) — cash backing of profits
        Net Debt/EBITDA (25%)  — leverage sustainability
    """
    fundamentals = fetch_fundamentals(ticker)
    if fundamentals is None:
        return 0.5  # unknown — neutral weights

    roe = fundamentals.get("roe")
    earnings_quality = fundamentals.get("earnings_quality")
    net_debt_ebitda = fundamentals.get("net_debt_to_ebitda")
    sector = fundamentals.get("sector", "")

    is_utility = "utilit" in sector.lower() or "infrastructure" in sector.lower()

    # ROE score
    roe_score = 1.0
    if roe is not None:
        roe_pct = roe * 100
        thresh = 6.0 if is_utility else 10.0
        if roe_pct >= thresh * 2:
            roe_score = 1.0
        elif roe_pct >= thresh:
            roe_score = 0.7
        elif roe_pct >= 0:
            roe_score = max(0.0, roe_pct / thresh)
        else:
            roe_score = 0.0

    # Earnings quality score
    eq_score = 1.0
    if earnings_quality is not None:
        if earnings_quality >= 1.0:
            eq_score = 1.0
        elif earnings_quality >= 0.8:
            eq_score = 0.8
        elif earnings_quality >= 0.5:
            eq_score = 0.5
        elif earnings_quality >= 0:
            eq_score = 0.2
        else:
            eq_score = 0.0

    # Net Debt/EBITDA score
    nd_score = 1.0
    if net_debt_ebitda is not None:
        lim = 6.0 if is_utility else 3.5
        if net_debt_ebitda <= 0:
            nd_score = 1.0
        elif net_debt_ebitda <= lim:
            nd_score = 0.8
        elif net_debt_ebitda <= lim * 1.5:
            nd_score = 0.4
        else:
            nd_score = 0.0

    return round(roe_score * 0.40 + eq_score * 0.35 + nd_score * 0.25, 4)


# ─────────────────────────────────────────────
# PRICE + VOLUME FETCH
# ─────────────────────────────────────────────


def fetch_best_available(ticker: str):
    for period in FETCH_PERIODS:
        try:
            raw = download(ticker, period=period, progress=False, auto_adjust=True)
            if raw.empty:
                continue
            close = raw["Close"]
            volume = raw["Volume"]
            if isinstance(close, pd.DataFrame):
                close = close.squeeze()
            if isinstance(volume, pd.DataFrame):
                volume = volume.squeeze()
            close = close.dropna()
            volume = volume.dropna()
            close, volume = close.align(volume, join="inner")
            if _is_clean(close, volume):
                return close, volume
        except Exception:
            continue
    return None, None


def fetch_sector_momentum() -> dict:
    momentum = {}
    for name, ticker in SECTOR_ETFS.items():
        try:
            data = download(ticker, period="3mo", progress=False, auto_adjust=True)[
                "Close"
            ]
            if isinstance(data, pd.DataFrame):
                data = data.squeeze()
            data = data.dropna()
            if len(data) > 10:
                momentum[name] = float((data.iloc[-1] - data.iloc[0]) / data.iloc[0])
        except Exception:
            momentum[name] = 0.0
    return momentum


def get_top_sectors(momentum: dict) -> list:
    return sorted(momentum, key=momentum.get, reverse=True)[:TOP_SECTORS_COUNT]
