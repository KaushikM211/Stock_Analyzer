from models.xgboost_model import xgboost_forecast
from models.prophet_model import prophet_forecast
from models.ridge_model import ridge_forecast

__all__ = ["xgboost_forecast", "prophet_forecast", "ridge_forecast"]
