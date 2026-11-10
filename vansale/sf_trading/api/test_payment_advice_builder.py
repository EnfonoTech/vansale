# apps/vansale/vansale/sf_trading/api/test_payment_advice_builder.py
"""Tests for the supplier-wise Payment Advice builder.

Nothing here creates advices against live data — the creation path is exercised through the
grouping and coercion helpers, which is where the bugs live. Whitelisted methods receive
their arguments as JSON strings from the browser, so the coercion helpers are tested first:
a silent failure there turns "create 12 advices" into a 500.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from vansale.sf_trading.api.payment_advice_builder import (
    DEFAULT_FLOOR,
    ENQUEUE_THRESHOLD,
    SKIP_ALREADY_ADVISED,
    SKIP_BELOW_FLOOR,
    SKIP_DISABLED,
    SKIP_LABELS,
    SKIP_NO_PARTY_ACCOUNT,
    SKIP_NO_ROWS,
    SKIP_ON_HOLD,
    _already_advised,
    _as_dict,
    _as_list,
    _party_field,
    _party_state,
    _source_doctype,
    create_advices,
    get_due_cutoff,
)


class TestBuilderHelpers(FrappeTestCase):
    def test_party_field_by_type(self):
        self.assertEqual(_party_field("Supplier"), "supplier")
        self.assertEqual(_party_field("Customer"), "customer")

    def test_source_doctype_by_type(self):
        self.assertEqual(_source_doctype("Supplier"), "Purchase Invoice")
        self.assertEqual(_source_doctype("Employee"), "Purchase Invoice")
        self.assertEqual(_source_doctype("Customer"), "Sales Invoice")

    def test_as_dict_accepts_json_string(self):
        """Whitelisted args arrive as strings from the browser."""
        self.assertEqual(_as_dict('{"company": "X"}'), {"company": "X"})
        self.assertEqual(_as_dict({"company": "X"}), {"company": "X"})
        self.assertEqual(_as_dict(None), {})
        self.assertEqual(_as_dict(""), {})

    def test_as_list_accepts_json_string(self):
        self.assertEqual(_as_list('[{"party": "A"}]'), [{"party": "A"}])
        self.assertEqual(_as_list([{"party": "A"}]), [{"party": "A"}])
        self.assertEqual(_as_list(None), [])
        self.assertEqual(_as_list(""), [])

    def test_every_skip_reason_has_a_label(self):
        for reason in (
            SKIP_NO_PARTY_ACCOUNT,
            SKIP_ALREADY_ADVISED,
            SKIP_BELOW_FLOOR,
            SKIP_ON_HOLD,
            SKIP_DISABLED,
            SKIP_NO_ROWS,
        ):
            self.assertIn(reason, SKIP_LABELS)
            self.assertTrue(SKIP_LABELS[reason])

    def test_floor_default_filters_rounding_residue(self):
        """Live data carries 0.005-outstanding invoices; the floor must exclude them."""
        self.assertGreaterEqual(DEFAULT_FLOOR, 1.0)

    def test_due_cutoff_offset(self):
        self.assertEqual(getdate(get_due_cutoff(0)), getdate(nowdate()))
        self.assertEqual(getdate(get_due_cutoff(7)), getdate(add_days(nowdate(), 7)))
        self.assertEqual(getdate(get_due_cutoff(-3)), getdate(add_days(nowdate(), -3)))

    def test_enqueue_threshold_is_sane(self):
        self.assertGreater(ENQUEUE_THRESHOLD, 1)

    def test_already_advised_empty_input(self):
        self.assertEqual(_already_advised([]), set())

    def test_already_advised_returns_a_set(self):
        result = _already_advised(["does-not-exist-xyz"])
        self.assertIsInstance(result, set)
        self.assertNotIn("does-not-exist-xyz", result)


class TestPartyState(FrappeTestCase):
    def test_state_shape_for_real_supplier(self):
        supplier = frappe.db.get_value("Supplier", {}, "name")
        if not supplier:
            self.skipTest("no suppliers on this site")
        state = _party_state("Supplier", supplier)
        for key in ("on_hold", "disabled", "release_date"):
            self.assertIn(key, state)
        self.assertIsInstance(state.on_hold, bool)
        self.assertIsInstance(state.disabled, bool)

    def test_expired_hold_is_not_a_hold(self):
        """ERPNext holds a supplier only until release_date; a past date must not block."""
        supplier = frappe.db.get_value("Supplier", {}, "name")
        if not supplier:
            self.skipTest("no suppliers on this site")

        original = frappe.db.get_value(
            "Supplier", supplier, ["on_hold", "release_date", "hold_type"], as_dict=True
        )
        try:
            frappe.db.set_value(
                "Supplier",
                supplier,
                {"on_hold": 1, "hold_type": "Payments", "release_date": add_days(nowdate(), -5)},
                update_modified=False,
            )
            self.assertFalse(_party_state("Supplier", supplier).on_hold)

            frappe.db.set_value(
                "Supplier",
                supplier,
                {"release_date": add_days(nowdate(), 5)},
                update_modified=False,
            )
            self.assertTrue(_party_state("Supplier", supplier).on_hold)
        finally:
            frappe.db.set_value("Supplier", supplier, original, update_modified=False)


class TestCreateGuards(FrappeTestCase):
    def test_create_advices_requires_a_selection(self):
        with self.assertRaises(frappe.ValidationError):
            create_advices(selections=[])

    def test_create_advices_accepts_json_payload_shape(self):
        """An empty JSON array must fail the same way an empty list does."""
        with self.assertRaises(frappe.ValidationError):
            create_advices(selections=json.dumps([]))
