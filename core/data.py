# ─────────────────────────────────────────────
# data.py — Fetching tickers, stock data, fundamentals, sector momentum
# ─────────────────────────────────────────────

import io
import logging
import requests
import pandas as pd
import yfinance as yf
from yfinance import download
from niftystocks import ns

from .config import FETCH_PERIODS, MIN_DAYS, SECTOR_ETFS, TOP_SECTORS_COUNT

# Suppress noisy yfinance download warnings (delisted tickers etc.)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


# ─────────────────────────────────────────────
# FUNDAMENTAL FILTER THRESHOLDS
# ─────────────────────────────────────────────
MIN_PE_RATIO = 1.0  # Exclude negative earnings / shell companies
MIN_PROMOTER_HOLDING = 25.0  # Promoter holding below 25% = low conviction
MAX_PROMOTER_PLEDGE = 35.0  # High pledge = distress risk
MIN_REVENUE_GROWTH = -0.08  # Exclude companies with >8% revenue decline

# ─────────────────────────────────────────────
# SECTOR-SPECIFIC PE LIMITS
# Blanket PE cap is wrong — different sectors trade at structurally
# different multiples based on growth profile and capital intensity
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# PE and D/E limits are looked up using BOTH sector AND industry
# from yfinance — industry gives granular distinction within a sector
#
# yfinance exact sector strings:
#   "Financial Services", "Utilities", "Industrials", "Technology",
#   "Communication Services", "Basic Materials", "Consumer Cyclical",
#   "Consumer Defensive", "Healthcare", "Energy", "Real Estate"
#
# industry strings give granularity within sector e.g.:
#   Financial Services → "Banks—Private Sector" / "Consumer Finance" /
#                        "Insurance—Life" / "Credit Services" / "Capital Markets"
#   Industrials        → "Electronic Components" (EMS/PLI) vs "Aerospace & Defense"
#   Technology         → "Software—Application" (high-growth) vs "Information Technology Services"
# ─────────────────────────────────────────────

# Industry-level PE overrides — checked FIRST before sector-level
# Keys match exact yfinance industry strings
INDUSTRY_PE_LIMITS = {
    # Financial — granular by sub-type
    "Banks—Private Sector": 22,  # HDFC Bank(18), ICICI(18), Axis(16)
    "Banks—Public Sector": 12,  # SBI(9), Bank of Baroda(7) — PSU discount
    "Consumer Finance": 35,  # Bajaj Finance(28), Chola(30) — NBFC
    "Insurance—Life": 55,  # HDFC Life(45), SBI Life(40)
    "Insurance—General": 45,  # Star Health(35)
    "Capital Markets": 25,  # Motilal Oswal(18), Angel One(20)
    "Mortgage Finance": 28,  # Can Fin Homes(12), LIC Housing(8)
    "Credit Services": 30,  # CreditAccess(18), Ujjivan(12) — MFI
    # Industrials — wide range, granular limits prevent PLI moonshots
    "Electronic Components": 65,  # Amber(157)✗ Dixon(190)✗ — still too high
    "Aerospace & Defense": 35,  # HAL(30), BEL(25), GRSE(20)
    "Specialty Industrial Machinery": 65,  # Siemens(60), ABB(70), Cummins(45)
    "Engineering & Construction": 30,  # L&T(25), NCC(15)
    "Farm & Heavy Construction Machinery": 30,  # Escorts(25), BEML(20)
    # Technology — high-growth product cos get more room
    "Software—Application": 75,  # KPIT(55), Tata Elxsi(50), Persistent(45)
    "Information Technology Services": 32,  # TCS(28), Infosys(25), Wipro(22)
    "Software—Infrastructure": 55,
    # Healthcare — hospitals justify higher PE than pharma
    "Medical Care Facilities": 80,  # Apollo Hospitals(70), Narayana(60)
    "Drug Manufacturers—General": 38,  # Sun Pharma(35), Dr Reddy(20), Cipla(25)
    # Utilities — regulated is low growth, renewables excluded at sector level
    "Utilities—Regulated Electric": 22,  # NTPC(15), Power Grid(18)
    "Utilities—Renewable": 35,  # Tata Power(30) — capped, Adani Green(99)✗
    "Utilities—Independent Power": 25,
    # Energy granular
    "Oil & Gas E&P": 15,  # ONGC(8), Oil India(10)
    "Oil & Gas Refining & Marketing": 14,  # BPCL(12), HPCL(10), IOC(8)
    "Oil & Gas Midstream": 18,  # GAIL(14), Petronet(12)
}

# Sector-level PE limits — fallback when industry key not matched
SECTOR_PE_LIMITS = {
    "Financial Services": 45,  # broad fallback for financial sector
    "Utilities": 25,  # regulated utilities — low growth
    "Infrastructure": 40,
    "Energy": 18,  # commodity — low PE norm
    "Real Estate": 65,
    "Industrials": 65,  # capital goods, defence — quality plays
    "Basic Materials": 55,  # Specialty Chem(50), Steel(15), Cement(35)
    "Materials": 50,
    "Consumer Cyclical": 78,
    "Consumer Defensive": 65,
    "Technology": 50,  # mature IT — mid-cap modest premium
    "Healthcare": 76,  # pharma + hospital blend
    "Communication Services": 45,
    "Communication": 45,
}
DEFAULT_PE_LIMIT = 55  # fallback for unrecognised sectors

# ─────────────────────────────────────────────
# SECTOR-SPECIFIC D/E LIMITS
# None = no cap (financial sector — leverage is their business model)
# ─────────────────────────────────────────────
SECTOR_DEBT_LIMITS = {
    # Financial — leverage IS the business model, no cap
    "Financial Services": None,
    "Banking": None,
    "Insurance": None,
    "NBFC": None,
    "Housing Finance": None,
    "Microfinance": None,
    # Infrastructure & Utilities — long gestation, asset-heavy, project debt normal
    # NSE P75: Utilities~2.9, Infrastructure~4.5 — buffer above P75
    "Utilities": 5.50,
    "Infrastructure": 5.75,
    "Energy": 4.75,  # ONGC/HPCL/BPCL — P75~2.8, buffer for refiners
    "Oil & Gas": 5.25,
    # Real Estate — project financing temporarily inflates D/E
    # NSE P75: ~2.8 — DLF, Prestige, Sobha
    "Real Estate": 4.25,
    # Industrials — L&T, Ashok Leyland, BEML — P75~1.9 but outliers at 2.8
    "Industrials": 3.50,
    # Materials — cement (Ultratech~0.4) vs steel (JSW~1.9, Tata~1.8)
    # P75~1.8 — buffer for steel/aluminium cycles
    "Basic Materials": 3.25,
    "Materials": 2.75,
    # Consumer Cyclical — auto, retail, durables — P75~1.9
    # Apollo Tyres(1.8), TVS Motor(1.9), Titan(1.7) — all legitimate
    "Consumer Cyclical": 2.55,
    # Consumer Defensive — FMCG largely debt-free, P75~0.8
    # Slightly higher buffer for regional FMCG with distribution debt
    "Consumer Defensive": 2.25,
    # Technology — asset-light, TCS/Infy/Wipro near zero debt — P75~0.2
    # Generous buffer for mid-cap IT with some capex debt
    "Technology": 2.00,
    # Healthcare — pharma capex, hospital chains — P75~0.8
    # Fortis/NH hospitals go higher — buffer for hospital capex
    "Healthcare": 2.75,
    # Communication — Airtel(4.2), Indus Towers(2.1), spectrum debt
    # P75~4.5 — telecom is infra-like
    "Communication": 5.25,
}
DEFAULT_DEBT_LIMIT = 2.65  # fallback — conservative but not blocking

# NSE headers required to bypass anti-scraping block
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
}

# Known ticker renames/mergers — keeps scan clean when NSE list has old names
TICKER_ALIASES = {
    "ADANITRANS.NS": "ADANIENSOL.NS",  # Adani Transmission → Adani Energy Solutions
    "HDFC.NS": "HDFCBANK.NS",  # HDFC merged into HDFC Bank
    "MINDTREE.NS": "LTIM.NS",  # MindTree → LTIMindtree
    "LTINFOTECH.NS": "LTIM.NS",  # L&T Infotech → LTIMindtree
    "HDFCLIFE.NS": "HDFCLIFE.NS",  # unchanged — just a safety entry
}


def _fetch_nse_live() -> list[str]:
    """
    Fetches the latest Nifty 500 constituent list directly from NSE.

    NSE publishes a CSV at a stable URL — this is the authoritative source.
    Always reflects the latest index rebalancing (happens twice a year).

    Steps:
        1. GET nseindia.com homepage to obtain session cookies
        2. Use those cookies + headers to fetch the CSV
        3. Parse Symbol column, append .NS suffix

    Returns list of tickers like ["RELIANCE.NS", "TCS.NS", ...]
    Raises exception if either request fails — caller handles fallback.
    """
    session = requests.Session()
    session.headers.update(_NSE_HEADERS)

    # Step 1 — get cookies by hitting homepage first (NSE requires this)
    session.get("https://www.nseindia.com", timeout=10)

    # Step 2 — fetch the Nifty 500 CSV
    csv_url = "https://www.nseindia.com/content/indices/ind_nifty500list.csv"
    response = session.get(csv_url, timeout=15)
    response.raise_for_status()

    # Step 3 — parse Symbol column
    df = pd.read_csv(io.StringIO(response.text))
    symbols = df["Symbol"].dropna().str.strip().tolist()
    tickers = [f"{s}.NS" for s in symbols if s]

    if len(tickers) < 400:
        # Sanity check — Nifty 500 should have ~500 stocks
        raise ValueError(f"Only {len(tickers)} tickers fetched — likely a parse error")

    print(f"  ✓ Fetched {len(tickers)} tickers live from NSE")
    return tickers


def _apply_aliases(tickers: list[str]) -> list[str]:
    """Replace known stale/renamed tickers with their current equivalents."""
    result = []
    seen = set()
    for t in tickers:
        resolved = TICKER_ALIASES.get(t, t)
        if resolved not in seen:
            result.append(resolved)
            seen.add(resolved)
    return result


def get_nifty500_tickers() -> list[str]:
    """
    Returns the current Nifty 500 ticker list.

    Priority:
        1. Live fetch from NSE (always latest — reflects rebalancing)
        2. niftystocks static list (fallback if NSE blocks/times out)
        3. Hardcoded minimal list (last resort — GitHub Actions won't fail)

    Aliases applied in all cases to handle known mergers/renames.
    """
    # ── Try 1: Live NSE fetch ──
    try:
        tickers = _fetch_nse_live()
        return _apply_aliases(tickers)
    except Exception as e:
        print(f"  ⚠ NSE live fetch failed ({e}) — trying niftystocks...")

    # ── Try 2: niftystocks static list ──
    try:
        tickers = ns.get_nifty500_with_ns()
        print(f"  ✓ Using niftystocks list ({len(tickers)} tickers)")
        return _apply_aliases(tickers)
    except Exception as e:
        print(f"  ⚠ niftystocks failed ({e}) — using hardcoded fallback")

    # ── Try 3: Hardcoded fallback — top 20 Nifty 50 stocks ──
    # GitHub Actions won't fail completely — partial scan is better than nothing
    fallback = [
        "RELIANCE.NS",
        "TCS.NS",
        "HDFCBANK.NS",
        "INFY.NS",
        "ICICIBANK.NS",
        "HINDUNILVR.NS",
        "ITC.NS",
        "SBIN.NS",
        "BHARTIARTL.NS",
        "KOTAKBANK.NS",
        "LT.NS",
        "AXISBANK.NS",
        "ASIANPAINT.NS",
        "MARUTI.NS",
        "TITAN.NS",
        "SUNPHARMA.NS",
        "ULTRACEMCO.NS",
        "BAJFINANCE.NS",
        "WIPRO.NS",
        "NESTLEIND.NS",
    ]
    print(f"  ⚠ Using hardcoded fallback ({len(fallback)} tickers)")
    return fallback


def _is_clean(close: pd.Series, volume: pd.Series) -> bool:
    """
    Validates that a price/volume series is usable by all models.
    Rejects series with internal NaN gaps, flat prices, or illiquid stocks.
    """
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


def fetch_fundamentals(ticker: str) -> dict | None:
    """
    Fetches fundamental data via yfinance for a single ticker.

    Returns a dict with:
        pe_ratio         — trailing PE ratio
        debt_to_equity   — total debt / total equity
        revenue_growth   — YoY revenue growth
        sector           — sector string for PE/D/E filter lookup
        company_name     — display name for email output

    Why each metric matters:
        PE ratio        — overpaying for earnings is the #1 mistake retail investors make
        Debt/Equity     — high debt kills companies in rate hike cycles (2022 lesson)
        Revenue growth  — a stock can have great momentum but shrinking business
    """
    if ticker in _fundamentals_cache:
        return _fundamentals_cache[ticker]

    try:
        info = yf.Ticker(ticker).info

        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        debt_to_equity = info.get("debtToEquity")
        revenue_growth = info.get("revenueGrowth")
        sector = info.get("sector", "")

        # yfinance returns D/E as a percentage (e.g. 150 = 1.5x) — normalise
        if debt_to_equity is not None and debt_to_equity > 20:
            debt_to_equity = debt_to_equity / 100

        company_name = (
            info.get("longName") or info.get("shortName") or ticker.replace(".NS", "")
        )

        industry = info.get("industry", "")

        # Interest coverage ratio — earningsBeforeInterestAndTaxes / interestExpense
        # Used as secondary check for high-debt infrastructure stocks
        ebit = info.get("ebit")
        interest_expense = info.get("interestExpense")
        interest_coverage = None
        if ebit is not None and interest_expense and interest_expense < 0:
            interest_coverage = ebit / abs(interest_expense)

        result = {
            "pe_ratio": pe_ratio,
            "debt_to_equity": debt_to_equity,
            "revenue_growth": revenue_growth,
            "sector": sector,
            "industry": industry,
            "interest_coverage": interest_coverage,
            "company_name": company_name,
        }
        _fundamentals_cache[ticker] = result
        return result

    except Exception:
        _fundamentals_cache[ticker] = None
        return None


# Simple in-memory cache — avoids fetching fundamentals twice per stock
_fundamentals_cache: dict = {}


def passes_fundamental_filter(ticker: str) -> tuple[bool, str]:
    """
    Returns (True, "") if stock passes all fundamental checks.
    Returns (False, reason) if it fails — reason logged for transparency.

    Checks:
        1. PE ratio  — industry-specific first, sector-level fallback
        2. D/E ratio — sector-specific limit (financial sector exempt)
                       D/E scaling: yfinance returns percentage (250 = 2.5x) — normalised in fetch
        3. Revenue growth — business not in structural decline
        4. Interest coverage — secondary check for high-debt infra stocks (D/E > 4.0)

    Promoter holding not available via yfinance for NSE — skipped.
    """
    fundamentals = fetch_fundamentals(ticker)

    if fundamentals is None:
        # Can't fetch fundamentals — let through rather than exclude valid stocks
        return True, ""

    pe = fundamentals["pe_ratio"]
    de = fundamentals["debt_to_equity"]
    rev_gr = fundamentals["revenue_growth"]
    sector = fundamentals["sector"]
    industry = fundamentals.get("industry", "")
    icr = fundamentals.get("interest_coverage")

    # ── PE ratio check — industry-level first, sector-level fallback ──
    if pe is not None:
        if pe < MIN_PE_RATIO:
            return False, f"PE={pe:.1f} — negative or near-zero earnings"

        # Step 1: check industry-level limit (most granular)
        pe_limit = None
        for ind_key, limit in INDUSTRY_PE_LIMITS.items():
            if ind_key.lower() in industry.lower():
                pe_limit = limit
                break

        # Step 2: fall back to sector-level if no industry match
        if pe_limit is None:
            pe_limit = DEFAULT_PE_LIMIT
            for sector_key, limit in SECTOR_PE_LIMITS.items():
                if sector_key.lower() in sector.lower():
                    pe_limit = limit
                    break

        if pe > pe_limit:
            return False, (
                f"PE={pe:.1f} — overvalued for {industry or sector} (limit={pe_limit}x)"
            )

    # ── D/E ratio check — sector-specific limit ──
    # D/E is already normalised in fetch_fundamentals (divided by 100 if >20)
    de_limit = DEFAULT_DEBT_LIMIT
    for sector_key, limit in SECTOR_DEBT_LIMITS.items():
        if sector_key.lower() in sector.lower():
            de_limit = limit
            break

    if de is not None and de_limit is not None:
        if de > de_limit:
            return False, (
                f"D/E={de:.2f} — too high for {sector} sector (limit={de_limit}x)"
            )

        # ── Interest coverage secondary check for high-debt stocks ──
        # D/E > 4.0 for non-financial stocks warrants extra scrutiny
        # ICR < 2.0 means debt servicing is at risk — filter out
        if de > 4.0 and de_limit is not None:
            if icr is not None and icr < 2.0:
                return False, (
                    f"D/E={de:.2f} is high and ICR={icr:.1f}x — "
                    f"debt servicing at risk (need ICR >= 2.0)"
                )

    # ── Revenue growth check ──
    if rev_gr is not None:
        if rev_gr < MIN_REVENUE_GROWTH:
            return False, f"Revenue growth={rev_gr * 100:.1f}% — business declining"

    return True, ""


def fetch_best_available(ticker: str):
    """
    Try progressively shorter periods and return the longest clean dataset.
    Returns (close, volume) or (None, None).
    """
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
