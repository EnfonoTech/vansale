"""Idempotency contract tests.

The offline drain engine retries every queued operation until the server
confirms. That means every whitelisted endpoint the PWA calls MUST be
safe to invoke twice with the same `client_id` — the second call is
supposed to return the first call's result without creating a duplicate
document. These tests lock that behaviour in place so future refactors
don't silently break it.

Run with ``bench --site <site> run-tests --app vansale``.

Kept in a single module because the assertions are nearly identical
across endpoints (dedup key, outbox row, no duplicate doc). The
per-endpoint test classes share a lightweight harness that creates the
minimum fixtures each endpoint needs.

IMPORTANT: these are integration tests — they hit the real Frappe ORM.
If a dependency (Item, Customer, Warehouse) isn't present on the test
site the test will raise a setUpClass failure rather than pretending
to pass. Fail loud = trust the green bar.
"""
from __future__ import annotations

import unittest
import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.api.customer import create as create_customer


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class IdempotencyBase(FrappeTestCase):
    """Shared helpers. Concrete test classes pick one endpoint each."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Ensure "customer" is a valid outbox event_type on the test
        # site. Sites created before the v3 migration will fail the
        # Select validation on _record_customer_outbox otherwise.
        meta = frappe.get_meta("Vansale Outbox")
        field = meta.get_field("event_type")
        opts = (field.options or "").split("\n")
        if "customer" not in opts:
            raise AssertionError(
                "Vansale Outbox event_type is missing 'customer' option — "
                "run `bench migrate` or add the option to "
                "vansale_outbox.json before running these tests."
            )

    def assert_outbox_unique(self, client_id: str, expected_event_type: str) -> None:
        rows = frappe.get_all(
            "Vansale Outbox",
            filters={"client_id": client_id},
            fields=["name", "event_type", "ref_doctype", "ref_name"],
        )
        self.assertEqual(
            len(rows), 1,
            f"Expected exactly 1 Vansale Outbox row for client_id={client_id}, got {len(rows)}",
        )
        self.assertEqual(rows[0]["event_type"], expected_event_type)


class TestCustomerCreateIdempotency(IdempotencyBase):
    """`vansale.api.customer.create` dedups on client_id.

    Two calls with the same client_id must:
      1. Return the SAME Customer.name.
      2. Leave exactly one Vansale Outbox row.
      3. Leave exactly one Customer document in the database (no dupes
         even if the customer_name happens to collide with an existing
         record).
    """

    def test_same_client_id_returns_same_customer(self) -> None:
        cid = _unique("cid")
        name1 = _unique("Acme-Test")

        first = create_customer(
            customer_name=name1,
            customer_type="b2c",
            mobile_no="+966500000001",
            client_id=cid,
        )
        self.assertTrue(first["name"])
        self.assertNotIn("idempotent_replay", first)  # first call is fresh

        # Second call with the SAME client_id but DIFFERENT customer_name
        # must still return the original Customer — the client_id is
        # king, the payload is ignored when a replay is detected.
        second = create_customer(
            customer_name="DIFFERENT-NAME-SHOULD-BE-IGNORED",
            customer_type="b2c",
            client_id=cid,
        )
        self.assertEqual(first["name"], second["name"])
        self.assertTrue(second.get("idempotent_replay"))

        self.assert_outbox_unique(cid, "customer")

        # The "different name" must NOT have been persisted.
        self.assertFalse(
            frappe.db.exists("Customer", {"customer_name": "DIFFERENT-NAME-SHOULD-BE-IGNORED"}),
            "Replay should not create a second Customer with the replayed payload's name",
        )

    def test_no_client_id_creates_each_time(self) -> None:
        """Calls without client_id are NOT deduped — each creates its own doc.

        The offline queue always supplies a client_id, but the same
        endpoint is called directly from online UI flows without one.
        Dedup must NOT kick in there or online-created customers would
        collide with anyone else calling at the same time.
        """
        name1 = _unique("NoCid-A")
        name2 = _unique("NoCid-B")
        a = create_customer(customer_name=name1, customer_type="b2c")
        b = create_customer(customer_name=name2, customer_type="b2c")
        self.assertNotEqual(a["name"], b["name"])


class TestInvoiceSaveIdempotency(IdempotencyBase):
    """`vansale.api.invoice.save` dedups on client_id.

    Not yet fully fixtured — skipped by default because building a real
    invoice requires a Customer + Item + Warehouse + Company that this
    test suite doesn't seed. Documented here so the contract is
    visible, and ready to be fleshed out once the site-setup helper
    lands.
    """

    @classmethod
    def setUpClass(cls) -> None:
        raise unittest.SkipTest(
            "TODO: seed Customer + Item + Warehouse before enabling",
        )


class TestPaymentSaveIdempotency(IdempotencyBase):
    """`vansale.api.payment.save` dedups on client_id."""

    @classmethod
    def setUpClass(cls) -> None:
        raise unittest.SkipTest(
            "TODO: seed Customer + submitted Sales Invoice before enabling",
        )


class TestSalesReturnSaveIdempotency(IdempotencyBase):
    """`vansale.api.sales_return.save` dedups on client_id."""

    @classmethod
    def setUpClass(cls) -> None:
        raise unittest.SkipTest(
            "TODO: seed original Sales Invoice before enabling",
        )


class TestVisitLogIdempotency(IdempotencyBase):
    """`vansale.api.route.log_visit` dedups on client_id."""

    @classmethod
    def setUpClass(cls) -> None:
        raise unittest.SkipTest(
            "TODO: seed Van Route + Route Stop before enabling",
        )


class TestStockEntryTransferInIdempotency(IdempotencyBase):
    """`vansale.api.van_stock.transfer_in` dedups on client_id."""

    @classmethod
    def setUpClass(cls) -> None:
        raise unittest.SkipTest(
            "TODO: seed source + destination Warehouse + Item with stock "
            "before enabling",
        )


