# apps/vansale/vansale/sf_trading/report/invoice_due_and_overdue_report/test_invoice_due_and_overdue_report.py
"""Tests for the Invoice Due and Overdue Report.

Read-only against existing data — the report never writes, so the tests assert
bucket maths, filter behaviour and column/row shape rather than creating invoices
(this site carries migrated ePromise data; creating invoices here is undesirable).
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from vansale.sf_trading.report.invoice_due_and_overdue_report.invoice_due_and_overdue_report import (
    _bucket,
    execute,
)


class TestInvoiceDueOverdueReport(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
            "Company", {}, "name"
        )

    def _run(self, **filters):
        base = {"company": self.company, "as_on_date": nowdate(), "overdue_only": 0}
        base.update(filters)
        return execute(base)

    def test_bucket_boundaries(self):
        self.assertEqual(_bucket(-5), "Not Due")
        self.assertEqual(_bucket(0), "Not Due")
        self.assertEqual(_bucket(1), "0-30")
        self.assertEqual(_bucket(30), "0-30")
        self.assertEqual(_bucket(31), "31-60")
        self.assertEqual(_bucket(60), "31-60")
        self.assertEqual(_bucket(61), "61-90")
        self.assertEqual(_bucket(90), "61-90")
        self.assertEqual(_bucket(91), "90+")

    def test_columns_present(self):
        columns, _rows = self._run()
        fieldnames = [c["fieldname"] for c in columns]
        for expected in (
            "invoice_type",
            "invoice",
            "invoice_doctype",
            "party",
            "due_date",
            "overdue_days",
            "ageing_bucket",
            "outstanding_amount",
            "base_grand_total",
        ):
            self.assertIn(expected, fieldnames)

    def test_rows_are_open_invoices_only(self):
        _columns, rows = self._run()
        for row in rows[:50]:
            self.assertGreater(row["outstanding_amount"], 0)
            self.assertIn(row["invoice_type"], ("Sales", "Purchase"))
            self.assertIn(row["invoice_doctype"], ("Sales Invoice", "Purchase Invoice"))

    def test_overdue_only_filter(self):
        _columns, rows = self._run(overdue_only=1)
        for row in rows:
            self.assertGreater(row["overdue_days"], 0)
            self.assertNotEqual(row["ageing_bucket"], "Not Due")

    def test_invoice_type_filter(self):
        _columns, sales = self._run(invoice_type="Sales")
        _columns, purchase = self._run(invoice_type="Purchase")
        self.assertTrue(all(r["invoice_type"] == "Sales" for r in sales))
        self.assertTrue(all(r["invoice_type"] == "Purchase" for r in purchase))

        _columns, both = self._run(invoice_type="Both")
        self.assertEqual(len(both), len(sales) + len(purchase))

    def test_ageing_bucket_filter(self):
        _columns, rows = self._run(ageing_bucket="90+")
        for row in rows:
            self.assertEqual(row["ageing_bucket"], "90+")
            self.assertGreater(row["overdue_days"], 90)

    def test_min_outstanding_filter(self):
        _columns, rows = self._run(min_outstanding=100)
        for row in rows:
            self.assertGreaterEqual(row["outstanding_amount"], 100)

    def test_future_as_on_date_moves_rows_overdue(self):
        """Nothing is 'Not Due' when we look from far enough in the future."""
        far = add_days(nowdate(), 3650)
        _columns, rows = self._run(as_on_date=far, overdue_only=1)
        for row in rows[:50]:
            self.assertGreater(row["overdue_days"], 0)

    def test_sorted_worst_first(self):
        _columns, rows = self._run()
        if len(rows) > 1:
            self.assertGreaterEqual(rows[0]["overdue_days"], rows[-1]["overdue_days"])
