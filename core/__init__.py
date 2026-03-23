"""
Core module for stock analysis.

Primary exports:
  - Scanner: Main analysis and prediction functions
  - Portfolio: Portfolio construction and optimization
  - Data: Data fetching, filtering and risk scoring
  - Features: Technical indicator calculations
  - Ensemble: Model ensemble forecasting
"""

# Scanner exports (main entry point)
from .scanner import analyze_and_predict, get_full_pool

# Portfolio exports
from .portfolio import build_portfolios, MONTHLY_BUDGET

# Data exports
from .data import (
    get_nifty500_tickers,
    fetch_fundamentals,
    passes_fundamental_filter,  # backwards-compat shim — always returns True
    score_fundamental_risk,  # new: multiplicative risk scorer (1–100)
    fundamental_quality_score,  # new: ensemble weight adjuster (0.0–1.0)
    fetch_best_available,
    fetch_sector_momentum,
    get_top_sectors,
)

# Features exports
from .features import (
    compute_rsi,
    compute_macd,
    compute_bollinger,
    compute_atr,
    compute_obv,
    build_features,
)

# Ensemble exports
from .ensemble import ensemble_forecast

# Configuration exports
from .config import (
    LOWER_LIMIT,
    UPPER_LIMIT,
    PRICE_BANDS,
    FORECAST_HORIZON,
    MODEL_WEIGHTS,
)

__all__ = [
    # Scanner
    "analyze_and_predict",
    "get_full_pool",
    # Portfolio
    "build_portfolios",
    "MONTHLY_BUDGET",
    # Data
    "get_nifty500_tickers",
    "fetch_fundamentals",
    "passes_fundamental_filter",
    "score_fundamental_risk",
    "fundamental_quality_score",
    "fetch_best_available",
    "fetch_sector_momentum",
    "get_top_sectors",
    # Features
    "compute_rsi",
    "compute_macd",
    "compute_bollinger",
    "compute_atr",
    "compute_obv",
    "build_features",
    # Ensemble
    "ensemble_forecast",
    # Config
    "LOWER_LIMIT",
    "UPPER_LIMIT",
    "PRICE_BANDS",
    "FORECAST_HORIZON",
    "MODEL_WEIGHTS",
]
