# apps/vansale/vansale/sf_trading/report/customer_statement_of_account/test_customer_statement_of_account.py
"""Tests for Customer Statement of Account — shape, reconciliation and ageing.

The statement is what Steel Force sends a customer, so the things that must never
break are: the footer agreeing with the last running balance, the ageing band
adding up to the closing balance, the document codes on the legend, and the
guards on the filters. Pure helpers are tested directly; the full report is run
against whatever the site holds so it also proves the ERPNext report calls still
answer with the shape this module expects.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from vansale.sf_trading.report.customer_statement_of_account.customer_statement_of_account import (
    DEFAULT_RANGES,
    execute,
    get_bucket_index,
    get_range_labels,
    get_ranges,
    get_type_code,
)


class TestCustomerStatementOfAccount(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
            "Company", {}, "name"
        )
        cls.customer = frappe.db.get_value(
            "GL Entry",
            {"party_type": "Customer", "is_cancelled": 0, "company": cls.company},
            "party",
        )

    def statement(self, **overrides):
        filters = {
            "company": self.company,
            "customer": self.customer,
            "from_date": "2000-01-01",
            "to_date": frappe.utils.today(),
        }
        filters.update(overrides)
        return execute(filters)

    # --- filters -----------------------------------------------------------

    def test_customer_is_mandatory(self):
        with self.assertRaises(frappe.ValidationError):
            execute({"company": self.company, "from_date": "2026-01-01", "to_date": "2026-01-31"})

    def test_reversed_period_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            execute(
                {
                    "company": self.company,
                    "customer": self.customer,
                    "from_date": "2026-08-01",
                    "to_date": "2026-01-01",
                }
            )

    # --- ageing buckets ----------------------------------------------------

    def test_ranges_fall_back_to_the_statement_defaults(self):
        self.assertEqual(get_ranges(frappe._dict()), DEFAULT_RANGES)

    def test_ranges_are_sorted_and_deduplicated(self):
        ranges = get_ranges(frappe._dict({"range1": 60, "range2": 30, "range3": 30}))
        self.assertEqual(ranges[:2], [30, 60])
        self.assertEqual(len(ranges), len(set(ranges)))

    def test_labels_cover_every_bucket_plus_the_tail(self):
        labels = get_range_labels([30, 60])
        self.assertEqual(len(labels), 3)
        self.assertTrue(labels[0].startswith("0-30"))
        self.assertTrue(labels[1].startswith("31-60"))
        self.assertIn("60", labels[2])

    def test_bucket_index_puts_an_age_in_the_first_range_it_fits(self):
        ranges = [30, 60, 90]
        self.assertEqual(get_bucket_index(0, ranges), 0)
        self.assertEqual(get_bucket_index(30, ranges), 0)
        self.assertEqual(get_bucket_index(31, ranges), 1)
        self.assertEqual(get_bucket_index(91, ranges), 3)

    # --- document codes on the legend --------------------------------------

    def test_invoice_codes(self):
        self.assertEqual(get_type_code("Sales Invoice", frappe._dict()), "IN")
        self.assertEqual(get_type_code("Sales Invoice", frappe._dict(is_return=1)), "CR")
        self.assertEqual(get_type_code("Sales Invoice", frappe._dict(is_debit_note=1)), "DB")

    def test_payment_and_journal_codes(self):
        self.assertEqual(get_type_code("Payment Entry", frappe._dict()), "PY")
        self.assertEqual(get_type_code("Journal Entry", frappe._dict(journal_type="Credit Note")), "CR")
        self.assertEqual(get_type_code("Journal Entry", frappe._dict(journal_type="Debit Note")), "DB")
        self.assertEqual(get_type_code("Journal Entry", frappe._dict(journal_type="Journal Entry")), "AD")

    # --- the statement itself ----------------------------------------------

    def test_statement_opens_and_closes_with_its_marker_rows(self):
        if not self.customer:
            self.skipTest("no customer ledger on this site")

        _columns, data, *_rest = self.statement()
        self.assertEqual(data[0]["row_type"], "opening")
        self.assertEqual(data[-1]["row_type"], "total")

    def test_footer_agrees_with_the_last_running_balance(self):
        if not self.customer:
            self.skipTest("no customer ledger on this site")

        _columns, data, *_rest = self.statement()
        entries = [row for row in data if row["row_type"] == "entry"]
        if not entries:
            self.skipTest("customer has no movement")

        self.assertAlmostEqual(flt(data[-1]["balance"]), flt(entries[-1]["balance"]), places=2)

    def test_footer_equals_opening_plus_movement(self):
        if not self.customer:
            self.skipTest("no customer ledger on this site")

        _columns, data, *_rest = self.statement()
        total = data[-1]
        self.assertAlmostEqual(
            flt(total["balance"]),
            flt(total["opening_balance"]) + flt(total["debit"]) - flt(total["credit"]),
            places=2,
        )

    def test_ageing_band_ties_to_the_closing_balance(self):
        if not self.customer:
            self.skipTest("no customer ledger on this site")

        # Over the whole ledger every open item is aged, so the band and the
        # closing balance are two views of the same number.
        _columns, data, *_rest = self.statement()
        total = data[-1]
        self.assertAlmostEqual(flt(sum(total["ageing_values"])), flt(total["balance"]), places=2)

    def test_ageing_band_matches_the_requested_ranges(self):
        if not self.customer:
            self.skipTest("no customer ledger on this site")

        _columns, data, *_rest = self.statement(range1=15, range2=30, range3=45, range4=60, range5=90, range6=120)
        labels = data[-1]["ageing_labels"]
        self.assertEqual(len(labels), 7)
        self.assertTrue(labels[0].startswith("0-15"))

    def test_a_quiet_period_still_produces_a_printable_statement(self):
        if not self.customer:
            self.skipTest("no customer ledger on this site")

        _columns, data, *_rest = self.statement(from_date="1990-01-01", to_date="1990-01-31")
        self.assertEqual([row["row_type"] for row in data], ["opening", "total"])
        self.assertEqual(flt(data[-1]["debit"]), 0.0)
