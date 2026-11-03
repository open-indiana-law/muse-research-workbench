import httpx
import pytest

from app.muse_client import CreditNotReady, spark_turn
from app.spend import SpendLedger


@pytest.mark.asyncio
async def test_key_alone_never_dispatches_without_verified_ledger(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "offline-key")
    monkeypatch.delenv("MUSE_SPEND_LEDGER_PATH", raising=False)
    def forbidden(**_):
        raise AssertionError("HTTP dispatch must remain closed")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(CreditNotReady, match="[Ll]edger"):
        await spark_turn([{"role": "user", "content": "Public test"}])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_reservation_is_durable_before_http_and_retained_if_usage_unknown(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("MODEL_API_KEY", "offline-key")
    path = tmp_path / "spend.sqlite"
    ledger = SpendLedger(path)
    ledger.configure("1", no_overage_verified=True, evidence="Synthetic offline test")
    monkeypatch.setenv("MUSE_SPEND_LEDGER_PATH", str(path))
    original = httpx.AsyncClient
    def receive(request):
        assert SpendLedger(path).status()["reserved_usd"] > 0
        if failure:
            raise httpx.ReadTimeout("Synthetic lost response")
        return httpx.Response(200, json={"choices": [{"message": {"content": "Public test"}}]})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(receive), **kw))
    if failure:
        with pytest.raises(httpx.ReadTimeout):
            await spark_turn([{"role": "user", "content": "Public test"}])
    else:
        await spark_turn([{"role": "user", "content": "Public test"}])
    assert SpendLedger(path).status()["reserved_usd"] > 0
