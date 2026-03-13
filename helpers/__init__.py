"""
Helper utilities for stock analysis alerts and tracking.

Exports:
  - Alerts: Email notification system
  - Accuracy Tracker: Prediction accuracy tracking
  - Consolidate: Results consolidation and caching
"""

# Alerts exports
from .alerts import (
    send_email_alert,
    send_improvement_alert,
    send_accuracy_email,
)

# Accuracy tracker exports
from .accuracy_tracker import check_predictions

# Consolidate exports
from .consolidate import save_run_results, check_and_alert

__all__ = [
    # Alerts
    "send_email_alert",
    "send_improvement_alert",
    "send_accuracy_email",
    # Accuracy tracker
    "check_predictions",
    # Consolidate
    "save_run_results",
    "check_and_alert",
]
