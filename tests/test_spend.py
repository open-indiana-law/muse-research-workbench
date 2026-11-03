from decimal import Decimal

import pytest

from app import spend


def test_default_unknown_closed(monkeypatch):
    monkeypatch.delenv("MUSE_SPEND_LEDGER_PATH", raising=False)
    status = spend.spend_status()
    assert status["spark_closed"] is True
    assert status["spent_usd"] is None
    assert status["available_usd"] is None
    assert status["reserved_usd"] is None


def ledger(tmp_path, amount="1"):
    result = spend.SpendLedger(tmp_path / "ledger.sqlite")
    result.configure(amount, no_overage_verified=True, evidence="fixture receipt")
    return result


def test_missing_ledger_closed_without_creating_file(tmp_path):
    path = tmp_path / "missing.sqlite"
    result = spend.SpendLedger(path)
    assert result.status()["spark_closed"] is True
    with pytest.raises(spend.SpendClosed):
        result.reserve_request("r", ".1")
    assert not path.exists()


def test_configure_requires_verified_remaining_and_no_overage(tmp_path):
    result = spend.SpendLedger(tmp_path / "ledger.sqlite")
    with pytest.raises(ValueError):
        result.configure("151", no_overage_verified=True, evidence="receipt")
    with pytest.raises(ValueError):
        result.configure("1", no_overage_verified=False, evidence="receipt")
    with pytest.raises(ValueError):
        result.configure("1", no_overage_verified=True, evidence="")
    assert result.status()["spark_closed"] is True


def test_reserve_atomic_exhaustion_and_restart(tmp_path):
    result = ledger(tmp_path)
    result.reserve_request("first", ".7")
    restarted = spend.SpendLedger(result.path)
    assert restarted.status()["reserved_usd"] == .7
    with pytest.raises(spend.SpendClosed):
        restarted.reserve_request("second", ".4")
    restarted.reserve_request("second", ".3")
    assert restarted.status()["available_usd"] == 0
    assert restarted.status()["spark_closed"] is True


def test_retry_id_never_authorizes_second_dispatch(tmp_path):
    result = ledger(tmp_path)
    result.reserve_request("lost-response", ".6")
    with pytest.raises(spend.SpendClosed):
        spend.SpendLedger(result.path).reserve_request("lost-response", ".6")
    assert result.status()["reserved_usd"] == .6


def test_settle_releases_only_verified_difference_idempotently(tmp_path):
    result = ledger(tmp_path)
    result.reserve_request("r", ".6")
    result.settle_request("r", ".2")
    result.settle_request("r", ".2")
    status = result.status()
    assert status["spent_usd"] == .2
    assert status["reserved_usd"] == 0
    assert status["available_usd"] == .8
    assert status["prior_spent_usd"] is None
    with pytest.raises(spend.SpendClosed):
        result.settle_request("r", ".1")
    with pytest.raises(spend.SpendClosed):
        result.reserve_request("r", ".6")


def test_overreservation_settlement_persistently_closes(tmp_path):
    result = ledger(tmp_path)
    result.reserve_request("r", ".1")
    with pytest.raises(spend.SpendClosed):
        result.settle_request("r", ".2")
    restarted = spend.SpendLedger(result.path)
    assert restarted.status()["spark_closed"] is True
    assert restarted.status()["reserved_usd"] == .1
    with pytest.raises(spend.SpendClosed):
        restarted.reserve_request("new", ".1")


def test_cannot_reconfigure_and_erase_prior_reservations(tmp_path):
    result = ledger(tmp_path)
    result.reserve_request("r", ".9")
    with pytest.raises(spend.SpendClosed):
        result.configure("1", no_overage_verified=True, evidence="new receipt")
    assert result.status()["available_usd"] == .1


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", True, "0", "1e1000000"])
def test_reject_invalid_reservation_amount(tmp_path, amount):
    result = ledger(tmp_path)
    with pytest.raises(ValueError):
        result.reserve_request("r", amount)
    assert result.status()["available_usd"] == 1


def test_round_up_fractional_microusd(tmp_path):
    result = ledger(tmp_path)
    result.reserve_request("r", Decimal("0.0000001"))
    assert result.status()["reserved_usd"] == .000001


def test_corrupt_ledger_fails_closed(tmp_path):
    path = tmp_path / "broken.sqlite"
    path.write_text("broken")
    assert spend.SpendLedger(path).status()["spark_closed"] is True
    with pytest.raises(spend.SpendClosed):
        spend.SpendLedger(path).reserve_request("r", ".1")


def test_module_wrappers_share_durable_ledger(tmp_path, monkeypatch):
    result = ledger(tmp_path)
    monkeypatch.setenv("MUSE_SPEND_LEDGER_PATH", str(result.path))
    spend.reserve_request("wrapped", ".5")
    spend.settle_request("wrapped", ".3")
    assert spend.spend_status()["available_usd"] == .7


def test_concurrent_reservations_cannot_overbook(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    result = ledger(tmp_path)

    def attempt(request_id):
        try:
            spend.SpendLedger(result.path).reserve_request(request_id, ".6")
            return True
        except spend.SpendClosed:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["a", "b"]))
    assert outcomes.count(True) == 1
    assert result.status()["reserved_usd"] == .6


def test_zero_grant_and_invalid_request_id_never_open_dispatch(tmp_path):
    result = ledger(tmp_path, "0")
    assert result.status()["spark_closed"] is True
    with pytest.raises(spend.SpendClosed):
        result.reserve_request("r", ".1")
    with pytest.raises(ValueError):
        result.reserve_request("", ".1")
