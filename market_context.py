"""Causal market-regime and volatility diagnostics for HUGO-TRADER.

Only trailing closes are used. This module is descriptive: it does not place
orders or alter strategy parameters.
"""
from __future__ import annotations

import math
import statistics


def classify_market_context(
    closes: list[float],
    lookback: int = 20,
    high_volatility_threshold: float = 0.80,
) -> dict:
    """Classify the latest point using only the supplied trailing price history."""
    if lookback < 3:
        raise ValueError("lookback must be at least 3")
    if not 0 < high_volatility_threshold < 10:
        raise ValueError("high_volatility_threshold must be between 0 and 10")
    if len(closes) < lookback + 1:
        raise ValueError(f"Need at least {lookback + 1} closes")
    if any(not math.isfinite(float(x)) or float(x) <= 0 for x in closes):
        raise ValueError("Closes must be finite positive prices")

    window = [float(x) for x in closes[-(lookback + 1):]]
    returns = [math.log(window[i] / window[i - 1]) for i in range(1, len(window))]
    annualized_volatility = statistics.pstdev(returns) * math.sqrt(365)
    sma = sum(window[1:]) / lookback
    momentum = window[-1] / window[0] - 1.0

    if window[-1] > sma and momentum > 0:
        regime = "alcista"
    elif window[-1] < sma and momentum < 0:
        regime = "bajista"
    else:
        regime = "lateral"

    return {
        "regime": regime,
        "annualized_volatility": annualized_volatility,
        "volatility_state": (
            "alta" if annualized_volatility >= high_volatility_threshold else "normal"
        ),
        "lookback": lookback,
        "uses_future_data": False,
    }
