# Stock Analyzer - Nifty 500 Prescriptive Stock Predictor

A machine learning-based stock analysis and prediction tool for Indian NSE (National Stock Exchange) Nifty 500 stocks. This system uses an ensemble of forecasting models to identify high-potential stocks with favorable ROI projections.

## Overview

**Stock Analyzer** is an automated stock screening and prediction pipeline that:

- 📊 Analyzes Nifty 500 stocks for technical trends and predictability
- 🤖 Employs an ensemble of three ML models (Prophet, XGBoost, Ridge Regression) for robust forecasting
- 💰 Filters stocks by liquidity, price bands, and weighted ROI thresholds
- 📱 Sends curated stock recommendations via WhatsApp alerts
- 🔄 Integrates with GitHub Actions for automated daily/weekly execution

## Key Features

### Multi-Model Ensemble
- **Prophet** (40%): Captures long-term trends and seasonal patterns
- **XGBoost** (35%): Identifies near-term directional momentum
- **Ridge Regression** (25%): Conservative anchor for risk mitigation

### Smart Stock Screening
- ₹150–₹6,000 price range with 11 price bands (₹500 windows)
- Minimum ₹1 Crore daily trading volume requirement
- Top 5 stock picks per price band
- 12-month forecast horizon with 8–12 month target window

### Automated Workflow
- Fetches historical data from Yahoo Finance and NSE
- Runs predictive models on 60+ trading days of data
- Calculates weighted ensemble ROI for each stock
- Filters and ranks by composite score
- Sends alerts via WhatsApp

## Project Structure

```
Stock_Analyzer/
├── main.py                 # Entry point for the application
├── config.py               # Central configuration (thresholds, model weights)
├── data.py                 # Data fetching and preprocessing
├── features.py             # Feature engineering utilities
├── scanner.py              # Main analysis and prediction pipeline
├── ensemble.py             # Ensemble model orchestration
├── alerts.py               # WhatsApp alert sender
├── models/                 # Trained model modules
│   ├── prophet_model.py    # Prophet forecasting model
│   ├── xgboost_model.py    # XGBoost predictor
│   └── ridge_model.py      # Ridge Regression model
├── pyproject.toml          # Project dependencies and metadata
└── .env                    # Environment variables (not committed)
```

## Installation

### Prerequisites
- Python 3.8+
- `uv` (recommended) or `pip`

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/KaushikM211/Stock_Analyzer.git
   cd Stock_Analyzer
   ```

2. **Install dependencies:**
   ```bash
   uv pip install -e .
   ```
   Or with pip:
   ```bash
   pip install -e .
   ```

3. **Configure environment variables:**
   Create a `.env` file in the project root:
   ```env
   TWILIO_ACCOUNT_SID=your_account_sid
   TWILIO_AUTH_TOKEN=your_auth_token
   TWILIO_WHATSAPP_NUMBER=whatsapp:+1234567890
   RECIPIENT_WHATSAPP_NUMBER=whatsapp:+0987654321
   ```

## Configuration

Edit `config.py` to customize:
- **Price Bands:** PRICE_BANDS (stock price ranges)
- **ROI Threshold:** MIN_WEIGHTED_ROI (minimum 12% by default)
- **Model Weights:** MODEL_WEIGHTS (ensemble distribution)
- **Forecast Horizon:** FORECAST_HORIZON (252 trading days ≈ 1 year)
- **Liquidity Filter:** MIN_AVG_DAILY_TURNOVER (₹1 Crore/day)

## Usage

### Local Execution
```bash
python main.py
```

### Output
- Console display of top stock picks grouped by price band
- WhatsApp alert with summary and recommendations

### GitHub Actions Integration
Add workflow file `.github/workflows/stock-analysis.yml` to automate daily/weekly runs:
```yaml
name: Stock Analysis
on:
  schedule:
    - cron: '0 15 * * 1-5'  # 3:30 PM IST on weekdays
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: uv pip install -e .
      - run: python main.py
        env:
          TWILIO_ACCOUNT_SID: ${{ secrets.TWILIO_ACCOUNT_SID }}
          TWILIO_AUTH_TOKEN: ${{ secrets.TWILIO_AUTH_TOKEN }}
          TWILIO_WHATSAPP_NUMBER: ${{ secrets.TWILIO_WHATSAPP_NUMBER }}
          RECIPIENT_WHATSAPP_NUMBER: ${{ secrets.RECIPIENT_WHATSAPP_NUMBER }}
```

## Dependencies

- **Data:** `niftystocks`, `yfinance`
- **ML/Forecasting:** `prophet`, `xgboost`, `scikit-learn`
- **Utilities:** `pandas`, `numpy`, `tqdm`, `requests`
- **Environment:** `python-dotenv`

## Key Metrics & Filters

| Metric | Value |
|--------|-------|
| Minimum Trading Days | 60 |
| Forecast Horizon | 252 days (~1 year) |
| Target Window | Months 8–12 |
| Minimum Daily Turnover | ₹1 Crore |
| Minimum Weighted ROI | 12% |
| Top Picks per Band | 5 |

## Model Details

### Prophet
- Captures long-term trends, seasonality, and holidays
- Weight: 40% (trend-focused)

### XGBoost
- Gradient boosting for feature interactions and momentum
- Weight: 35% (directional signal)

### Ridge Regression
- Linear model with L2 regularization for stability
- Weight: 25% (conservative anchor)

**Ensemble Score:** Weighted average of normalized model predictions

## License

[Specify your license here, e.g., MIT, GPL, etc.]

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Commit changes with clear messages
4. Push and open a pull request

## Support

For issues, questions, or suggestions, please open an issue on GitHub.

---

**Disclaimer:** This tool is for educational and research purposes. It does not provide financial advice. Always conduct your own due diligence and consult with a financial advisor before making investment decisions.
