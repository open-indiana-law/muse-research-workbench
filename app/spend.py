"""Fail-closed local grant ledger; account balance must be verified separately.

Reserve a fresh ID immediately before *each* HTTP dispatch. Never retry a
reserved ID: a lost response may already have incurred its full charge. Leave
reservations untouched on cancellation, timeout, missing usage or restart.
Only settle lower with known usage and verified pricing; otherwise settle the
full reserved bound. This ledger does not discover account balance or pricing.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import os
from pathlib import Path
import sqlite3

CREDIT_CAP_USD = 150
_MICRO = 1_000_000


class SpendClosed(RuntimeError):
    """No provider dispatch is authorized by this ledger operation."""


def _micros(value, *, allow_zero=False, round_down=False):
    try:
        if isinstance(value, bool):
            raise ValueError("Boolean is not a dollar amount")
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > CREDIT_CAP_USD:
            raise ValueError("Dollar amount must be finite and within the $150 cap")
        result = int((amount * _MICRO).to_integral_value(
            rounding=ROUND_FLOOR if round_down else ROUND_CEILING))
        if result == 0 and not allow_zero:
            raise ValueError("Reservation must be positive")
        return result
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid dollar amount") from exc


def _unknown(note):
    return dict(cap_usd=CREDIT_CAP_USD, reserved_usd=None, spent_usd=None,
                prior_spent_usd=None, available_usd=None, spark_closed=True,
                note=note)


class SpendLedger:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def _transaction(self):
        connection = None
        try:
            # rw deliberately refuses to manufacture a missing ledger on read.
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError) as exc:
            raise SpendClosed("Ledger unavailable; no provider request permitted") from exc
        finally:
            if connection is not None:
                connection.close()  # rolls back any interrupted transaction

    def configure(self, remaining_usd, *, no_overage_verified, evidence):
        """Initialize once from a nonsecret, verified account receipt.

        remaining_usd is the actual remaining grant, not the advertised award.
        This does not configure account settings or establish that the receipt
        is true. Reconfiguration cannot erase liabilities.
        """
        remaining = _micros(remaining_usd, allow_zero=True, round_down=True)
        if no_overage_verified is not True or not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("Verified no-overage setup and nonsecret evidence required")
        try:
            connection = sqlite3.connect(self.path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE IF NOT EXISTS grant_state "
                                   "(id INTEGER PRIMARY KEY CHECK(id=1), remaining INTEGER NOT NULL, "
                                   "evidence TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0)")
                if connection.execute("SELECT 1 FROM grant_state").fetchone():
                    raise SpendClosed("Existing ledger cannot be reset or reconfigured")
                connection.execute("CREATE TABLE requests (id TEXT PRIMARY KEY, "
                                   "reserved INTEGER NOT NULL, actual INTEGER)")
                connection.execute("INSERT INTO grant_state(id,remaining,evidence) VALUES(1,?,?)",
                                   (remaining, evidence.strip()))
                connection.commit()
            finally:
                connection.close()
        except (sqlite3.Error, OSError) as exc:
            raise SpendClosed("Cannot initialize durable ledger") from exc

    @staticmethod
    def _totals(connection):
        grant = connection.execute("SELECT remaining, blocked FROM grant_state WHERE id=1").fetchone()
        if grant is None:
            raise SpendClosed("Verified grant remaining is unknown")
        reserved, spent = connection.execute(
            "SELECT COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0), "
            "COALESCE(SUM(actual),0) FROM requests").fetchone()
        return grant[0], bool(grant[1]), reserved, spent

    def status(self):
        try:
            with self._transaction() as connection:
                grant, blocked, reserved, spent = self._totals(connection)
            available = max(0, grant - reserved - spent)
            return dict(cap_usd=CREDIT_CAP_USD, reserved_usd=reserved / _MICRO,
                        spent_usd=spent / _MICRO, prior_spent_usd=None,
                        available_usd=available / _MICRO,
                        spark_closed=blocked or available == 0,
                        note=("Ledger blocked: accounting bound exceeded; account reconciliation required."
                              if blocked else "Local accounting since verified grant receipt; prior use unknown. "
                              "Outstanding requests retain their full reservation."))
        except SpendClosed as exc:
            return _unknown(str(exc))

    def reserve_request(self, request_id, max_cost_usd):
        """Commit upper bound before dispatch; duplicate IDs never authorize retry."""
        bound = _micros(max_cost_usd)
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("Nonempty unique request ID required")
        with self._transaction() as connection:
            grant, blocked, reserved, spent = self._totals(connection)
            if blocked or bound > grant - reserved - spent:
                raise SpendClosed("Grant unavailable or insufficient for request upper bound")
            if connection.execute("SELECT 1 FROM requests WHERE id=?", (request_id,)).fetchone():
                raise SpendClosed("Request ID already reserved; do not redispatch")
            connection.execute("INSERT INTO requests(id,reserved) VALUES(?,?)", (request_id, bound))
        return {"request_id": request_id, "reserved_usd": bound / _MICRO}

    def settle_request(self, request_id, actual_cost_usd):
        """Reconcile known cost (or pessimistic full bound); never invent usage."""
        actual = _micros(actual_cost_usd, allow_zero=True)
        exceeded = False
        with self._transaction() as connection:
            row = connection.execute("SELECT reserved,actual FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise SpendClosed("No reservation exists for this request")
            bound, previous = row
            if previous is not None:
                if previous != actual:
                    raise SpendClosed("Conflicting settlement requires reconciliation")
            elif actual > bound:
                # Commit this stop before raising: a restart must remain closed.
                connection.execute("UPDATE grant_state SET blocked=1 WHERE id=1")
                exceeded = True
            else:
                connection.execute("UPDATE requests SET actual=? WHERE id=?", (actual, request_id))
        if exceeded:
            raise SpendClosed("Actual cost exceeded reservation; ledger persistently blocked")


def _configured_ledger():
    path = os.environ.get("MUSE_SPEND_LEDGER_PATH", "").strip()
    if not path:
        raise SpendClosed("Verified remaining grant and no-overage ledger not configured; prior use unknown")
    return SpendLedger(path)


def spend_status():
    try:
        return _configured_ledger().status()
    except SpendClosed as exc:
        return _unknown(str(exc))


def reserve_request(request_id, max_cost_usd):
    return _configured_ledger().reserve_request(request_id, max_cost_usd)


def settle_request(request_id, actual_cost_usd):
    return _configured_ledger().settle_request(request_id, actual_cost_usd)
