"""Pure helpers: parsing, caching, validation, indicators."""
from types import SimpleNamespace

import pytest

import financials as f
import main


def test_redact_secrets(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "ABCDEF123456")
    msg = "We have detected your API key as ABCDEF123456 and our standard rate limit is 25"
    assert "ABCDEF123456" not in main._redact_secrets(msg)


@pytest.mark.parametrize("raw,expected", [
    ("12.5", 12.5), ("3.4%", 3.4), ("None", None), ("-", None), ("", None),
    (None, None), (7, 7.0), ("nan", None), ("abc", None),
])
def test_av_number(raw, expected):
    assert main._av_number(raw) == expected


def test_safe_float():
    assert main.safe_float("1.5") == 1.5
    assert main.safe_float(None, 9) == 9
    assert main.safe_float("x") == 0.0


def test_lru_cache_ttl_eviction_and_stats(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(main.time, "time", lambda: now[0])
    c = main.LRUCache(max_size=2, ttl=10)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1          # "a" is now most recently used
    c.set("c", 3)                   # evicts "b", the least recently used
    assert c.get("b") is None and c.get("c") == 3
    now[0] += 11
    assert c.get("a") is None       # expired
    c.set("stock:AAPL", 1)
    c.set("chart:AAPL:1mo", 2)
    c.delete_pattern("AAPL")
    assert c.stats()["size"] == 0


@pytest.mark.parametrize("symbol,ok", [
    ("AAPL", True), ("brk-b", True), ("M&M.NS", True), ("BAJAJ-AUTO.NS", True),
    ("RELIANCE.BO", True), ("<script>", False), ("A" * 16, False), ("AAPL.TOOLONG", False),
])
def test_symbol_validation(symbol, ok):
    if ok:
        assert main.StockRequest(symbol=symbol).symbol == symbol.upper()
    else:
        with pytest.raises(Exception):
            main.StockRequest(symbol=symbol)


def _req(headers, host="10.0.0.5"):
    return SimpleNamespace(headers={k.lower(): v for k, v in headers.items()}, client=SimpleNamespace(host=host))


def test_client_ip_ignores_spoofed_and_proxy_hops():
    chain = {"X-Forwarded-For": "6.6.6.6, 49.36.10.20, 172.69.94.197, 10.0.0.1"}
    assert main.get_client_ip(_req(chain)) == "49.36.10.20"
    assert main.get_client_ip(_req({**chain, "CF-Connecting-IP": "49.36.99.1"})) == "49.36.99.1"
    assert main.get_client_ip(_req({})) == "10.0.0.5"
    assert main.get_client_ip(None) == "anonymous"


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Reliance Q2 profit rises 9% - Economic Times</title><source>Economic Times</source>
  <link>https://example.com/a</link><pubDate>Thu, 06 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Reliance Industries Share Price Today - Upstox</title><source>Upstox</source>
  <link>https://example.com/quote</link><pubDate>Fri, 07 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Reliance announces new energy plant - Mint</title><source>Mint</source>
  <link>https://example.com/b</link><pubDate>Fri, 07 Nov 2026 09:00:00 GMT</pubDate></item>
<item><title>Reliance announces new energy plant - Mint</title><source>Mint</source>
  <link>https://example.com/dup</link><pubDate>Fri, 07 Nov 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_google_news_parsing():
    items = main.parse_google_news_rss(RSS, max_news=5)
    # quote page and duplicate dropped, newest first, publisher suffix stripped
    assert [i["title"] for i in items] == ["Reliance announces new energy plant", "Reliance Q2 profit rises 9%"]
    assert items[0]["publisher"] == "Mint" and items[0]["published"].startswith("2026-11-07T09:00")
    assert main.parse_google_news_rss("not xml", 5) == []


def test_google_news_query():
    india = main._google_news_query("RELIANCE.NS", "Reliance Industries Limited")
    assert india["q"] == '"Reliance Industries" when:7d' and india["gl"] == "IN"
    us = main._google_news_query("AAPL")
    assert us["q"] == "AAPL stock when:7d" and us["gl"] == "US"


def test_indian_symbols():
    assert f.is_indian_stock("TCS.NS") and f.is_indian_stock("RELIANCE.BO")
    assert not f.is_indian_stock("AAPL")
    assert f.normalize_indian_symbol("TCS.NS") == "TCS"


def test_ratios():
    assert f.calculate_pe_ratio({"trailingPE": 25.5}) == 25.5
    assert f.calculate_pe_ratio({}) is None
    # Yahoo sends dividend yield both as a fraction and as a percent
    assert f.get_dividend_yield({"dividendYield": 0.005}) == f.get_dividend_yield({"dividendYield": 0.5}) == 0.5


def test_technical_indicators(hist):
    ti = f.calculate_technical_indicators(hist)
    for key in ("sma_20", "sma_50", "sma_200", "rsi", "macd", "trend"):
        assert key in ti
    assert 0 <= ti["rsi"] <= 100
    assert f.calculate_volatility(hist) > 0


def test_price_metrics(hist):
    m = main.calculate_price_metrics({"currentPrice": 110, "previousClose": 100}, hist)
    assert m["change"] == 10.0 and m["change_percent"] == 10.0
