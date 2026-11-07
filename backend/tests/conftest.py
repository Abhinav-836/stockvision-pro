"""
No test touches the network: API keys are blanked, and API tests use a
TestClient WITHOUT `with`, so the startup background updaters (which poll
live market data) never start.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for key in ("ALPHA_VANTAGE_API_KEY", "FINNHUB_API_KEY", "OPENROUTER_API_KEY", "REDIS_URL", "YFINANCE_PROXY_URL"):
    os.environ[key] = ""

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    main.request_counts.clear()
    main.stock_cache.clear()
    main.last_good_stock_cache.clear()
    return TestClient(main.app)


@pytest.fixture
def no_network(monkeypatch):
    """Every live data source fails, as if the providers were down."""
    async def nothing(*args, **kwargs):
        return (None, None, None), []

    monkeypatch.setattr(main, "fetch_stock_and_news", nothing)


@pytest.fixture
def hist():
    """One year of synthetic daily bars."""
    idx = pd.date_range("2025-01-01", periods=260, freq="B")
    close = pd.Series(100 + np.cumsum(np.sin(np.arange(260) / 5)), index=idx)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000})
