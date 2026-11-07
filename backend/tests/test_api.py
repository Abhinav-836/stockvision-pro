"""API behaviour with every data provider offline."""
import main


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"


def test_search(client):
    r = client.get("/api/search/rel").json()["results"]
    assert r[0]["symbol"] == "RELIANCE.NS"
    exact = client.get("/api/search/TCS.NS").json()["results"]
    assert exact[0]["symbol"] == "TCS.NS"
    assert client.get("/api/search/a").json() == {"results": []}


def test_compare_validation(client):
    assert client.post("/api/compare", json={"symbols": ["AAPL"]}).status_code == 422
    assert client.post("/api/compare", json={"symbols": ["AAPL", "aapl"]}).status_code == 422
    assert client.post("/api/compare", json={"symbols": ["AAPL", "<script>"]}).status_code == 422
    six = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]
    assert client.post("/api/compare", json={"symbols": six}).status_code == 422


def test_stock_falls_back_when_providers_are_down(client, no_network):
    r = client.get("/api/stock/aapl")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AAPL" and body["is_fallback_data"] is True


def test_last_good_real_data_beats_fallback(client, no_network):
    """A provider hiccup serves the last real quote (marked stale), not demo numbers."""
    main.last_good_stock_cache.set("MSFT", {"symbol": "MSFT", "current_price": 412.5})
    body = client.get("/api/stock/MSFT", params={"use_cache": "false"}).json()
    assert body == {"symbol": "MSFT", "current_price": 412.5, "is_stale": True}


def test_rate_limit(client):
    for _ in range(60):
        assert client.get("/health").status_code == 200
    r = client.get("/health")
    assert r.status_code == 429


def test_spoofed_forwarded_for_cannot_bypass_rate_limit(client):
    """Before the fix, a new made-up X-Forwarded-For per request meant no limit at all."""
    real_chain = "8.8.4.4, 104.23.160.38, 10.0.0.1"  # visitor, Cloudflare edge, Render internal
    for i in range(60):
        spoofed = f"1.2.3.{i}, {real_chain}"
        assert client.get("/health", headers={"X-Forwarded-For": spoofed}).status_code == 200
    r = client.get("/health", headers={"X-Forwarded-For": f"9.9.9.9, {real_chain}"})
    assert r.status_code == 429
    # A different real visitor is unaffected
    other = client.get("/health", headers={"X-Forwarded-For": "8.8.8.8, 104.23.160.38, 10.0.0.1"})
    assert other.status_code == 200


def test_debug_endpoints_are_off_by_default(client, monkeypatch):
    called = []

    async def spy(*args, **kwargs):
        called.append(args)
        return None

    monkeypatch.setattr(main.hybrid_engine, "get_quote", spy)
    monkeypatch.delenv("ENABLE_DEBUG_ENDPOINTS", raising=False)
    assert client.get("/api/debug/AAPL").status_code == 404
    assert client.get("/api/cache/invalidate/AAPL").status_code == 404
    assert called == []  # no provider call was made

    monkeypatch.setenv("ENABLE_DEBUG_ENDPOINTS", "true")
    assert client.get("/api/cache/invalidate/AAPL").json()["status"] == "ok"
