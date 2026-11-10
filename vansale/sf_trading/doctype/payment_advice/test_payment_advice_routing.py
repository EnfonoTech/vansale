# apps/vansale/vansale/sf_trading/doctype/payment_advice/test_payment_advice_routing.py
"""Which approvers an advice needs, decided from what it pays for.

The rules under test:
  * any overdue Purchase Invoice   → HO Accounts route
  * more than one Purchase Order   → Purchase Manager route
  * exactly one Purchase Order     → straight to the Accountant
  * invoices, none overdue         → Accountant at BHD 500 or less, Finance above it

Nothing is saved. Each test builds an unsaved advice and calls compute_approval_route directly,
so a client site's advices and approvals are untouched. Real Purchase Invoices are borrowed
from the site to exercise the overdue lookup, and the test skips when the site has none.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from vansale.sf_trading.doctype.payment_advice.payment_advice import (
    FINANCE_APPROVAL_LIMIT,
    ROUTE_ACCOUNTANT,
    ROUTE_FINANCE,
    ROUTE_HO_ACCOUNTS,
    ROUTE_PURCHASE_MANAGER,
    compute_approval_route,
)


def _advice(rows, payment_amount=100.0):
    advice = frappe.new_doc("Payment Advice")
    advice.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
        "Company", {}, "name"
    )
    advice.party_type = "Supplier"
    advice.payment_amount = payment_amount
    for row in rows:
        advice.append("payment_advice_reference", row)
    return advice


def _invoice(overdue):
    """A submitted Purchase Invoice from this site, overdue or not, or None."""
    today = nowdate()
    filters = {"docstatus": 1, "outstanding_amount": [">", 0]}
    filters["due_date"] = ["<", today] if overdue else [">=", today]
    return frappe.db.get_value("Purchase Invoice", filters, "name")


class TestPaymentAdviceRouting(FrappeTestCase):
    def test_two_orders_go_to_the_purchase_manager(self):
        orders = frappe.get_all("Purchase Order", filters={"docstatus": 1}, pluck="name", limit=2)
        if len(orders) < 2:
            self.skipTest("fewer than two submitted Purchase Orders on this site")
        advice = _advice([
            {"reference_doctype": "Purchase Order", "reference_record": orders[0]},
            {"reference_doctype": "Purchase Order", "reference_record": orders[1]},
        ])
        self.assertEqual(compute_approval_route(advice), ROUTE_PURCHASE_MANAGER)

    def test_one_order_goes_straight_to_the_accountant(self):
        order = frappe.db.get_value("Purchase Order", {"docstatus": 1}, "name")
        if not order:
            self.skipTest("no submitted Purchase Order on this site")
        advice = _advice([{"reference_doctype": "Purchase Order", "reference_record": order}])
        self.assertEqual(compute_approval_route(advice), ROUTE_ACCOUNTANT)

    def test_one_order_skips_the_accountant_route_even_when_large(self):
        """The order rule is about how many, not how much."""
        order = frappe.db.get_value("Purchase Order", {"docstatus": 1}, "name")
        if not order:
            self.skipTest("no submitted Purchase Order on this site")
        advice = _advice(
            [{"reference_doctype": "Purchase Order", "reference_record": order}],
            payment_amount=FINANCE_APPROVAL_LIMIT * 100,
        )
        self.assertEqual(compute_approval_route(advice), ROUTE_ACCOUNTANT)

    def test_an_overdue_invoice_goes_to_ho_accounts(self):
        invoice = _invoice(overdue=True)
        if not invoice:
            self.skipTest("no overdue Purchase Invoice on this site")
        advice = _advice([{"reference_doctype": "Purchase Invoice", "reference_record": invoice}])
        self.assertEqual(compute_approval_route(advice), ROUTE_HO_ACCOUNTS)

    def test_an_overdue_invoice_wins_over_the_amount_rule(self):
        invoice = _invoice(overdue=True)
        if not invoice:
            self.skipTest("no overdue Purchase Invoice on this site")
        advice = _advice(
            [{"reference_doctype": "Purchase Invoice", "reference_record": invoice}],
            payment_amount=1.0,
        )
        self.assertEqual(compute_approval_route(advice), ROUTE_HO_ACCOUNTS)

    def test_a_current_invoice_under_the_limit_goes_to_the_accountant(self):
        invoice = _invoice(overdue=False)
        if not invoice:
            self.skipTest("no Purchase Invoice due today or later on this site")
        advice = _advice(
            [{"reference_doctype": "Purchase Invoice", "reference_record": invoice}],
            payment_amount=FINANCE_APPROVAL_LIMIT - 0.001,
        )
        self.assertEqual(compute_approval_route(advice), ROUTE_ACCOUNTANT)

    def test_a_current_invoice_over_the_limit_needs_finance(self):
        invoice = _invoice(overdue=False)
        if not invoice:
            self.skipTest("no Purchase Invoice due today or later on this site")
        advice = _advice(
            [{"reference_doctype": "Purchase Invoice", "reference_record": invoice}],
            payment_amount=FINANCE_APPROVAL_LIMIT + 0.001,
        )
        self.assertEqual(compute_approval_route(advice), ROUTE_FINANCE)

    def test_exactly_the_limit_goes_straight_through(self):
        """The rule reads 'more than 500 needs Finance', so 500 itself does not."""
        invoice = _invoice(overdue=False)
        if not invoice:
            self.skipTest("no Purchase Invoice due today or later on this site")
        advice = _advice(
            [{"reference_doctype": "Purchase Invoice", "reference_record": invoice}],
            payment_amount=FINANCE_APPROVAL_LIMIT,
        )
        self.assertEqual(compute_approval_route(advice), ROUTE_ACCOUNTANT)

    def test_no_references_falls_back_to_the_amount_rule(self):
        self.assertEqual(compute_approval_route(_advice([], payment_amount=10.0)), ROUTE_ACCOUNTANT)
        self.assertEqual(
            compute_approval_route(_advice([], payment_amount=FINANCE_APPROVAL_LIMIT + 10)),
            ROUTE_FINANCE,
        )

    def test_rows_without_a_record_are_ignored(self):
        advice = _advice([{"reference_doctype": "Purchase Order", "reference_record": None}])
        self.assertEqual(compute_approval_route(advice), ROUTE_ACCOUNTANT)

    def test_a_future_due_invoice_is_not_overdue(self):
        """Guard the boundary directly rather than trusting the site's data mix."""
        from vansale.sf_trading.doctype.payment_advice.payment_advice import _has_overdue_invoice

        invoice = frappe.db.get_value(
            "Purchase Invoice",
            {"docstatus": 1, "due_date": [">", add_days(nowdate(), 1)], "outstanding_amount": [">", 0]},
            "name",
        )
        if not invoice:
            self.skipTest("no Purchase Invoice due after tomorrow on this site")
        self.assertFalse(_has_overdue_invoice([invoice]))

    def test_a_settled_overdue_invoice_is_not_overdue(self):
        """Past its date but paid — nothing to chase, so no extra approval."""
        from vansale.sf_trading.doctype.payment_advice.payment_advice import _has_overdue_invoice

        invoice = frappe.db.get_value(
            "Purchase Invoice",
            {"docstatus": 1, "due_date": ["<", nowdate()], "outstanding_amount": ["<=", 0]},
            "name",
        )
        if not invoice:
            self.skipTest("no settled overdue Purchase Invoice on this site")
        self.assertFalse(_has_overdue_invoice([invoice]))
