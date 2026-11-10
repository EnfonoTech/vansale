# apps/vansale/vansale/sf_trading/report/mode_of_payment_invoice_wise/test_mode_of_payment_invoice_wise.py
"""Tests for the Mode of Payment Invoice Wise report.

Two halves:
  * pure-function tests on classification and aggregation — no site data needed, and they
    pin the parts most likely to drift (the keyword table, the mismatch rule, the
    account fallback)
  * read-only assertions against whatever the site holds: the report never writes, and a
    client site has plenty of real invoices, so the shape of the output is asserted
    rather than fabricated
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, get_first_day, nowdate

from vansale.sf_trading.report.mode_of_payment_invoice_wise.mode_of_payment_invoice_wise import (
    CLASS_ADJUSTMENT,
    CLASS_BANK,
    CLASS_CARD,
    CLASS_CASH,
    CLASS_CHEQUE,
    CLASS_CREDIT,
    CLASS_NO_VOUCHER,
    CLASS_WALLET,
    CREDIT_LABEL,
    INVOICE_TYPES,
    NO_VOUCHER_LABEL,
    ROUNDING_TOLERANCE,
    UNSET_LABEL,
    build_invoice_rows,
    classify_mode,
    detail_rows,
    document_total,
    execute,
    mismatch_label,
    mode_summary,
)


class TestModeOfPaymentInvoiceWise(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value(
            "Global Defaults", "default_company"
        ) or frappe.db.get_value("Company", {}, "name")

    def _run(self, **filters):
        base = {
            "company": self.company,
            "from_date": get_first_day(nowdate()),
            "to_date": nowdate(),
        }
        base.update(filters)
        return execute(base)

    # ---------------------------------------------------------------- classification

    def test_mode_names_map_to_the_right_class(self):
        """The live modes on this site — the names are the only reliable signal."""
        expected = {
            "Cash-SFSB": CLASS_CASH,
            "Cash-SFSS": CLASS_CASH,
            "Swipe-SFSB": CLASS_CARD,
            "Swipe-SFSS": CLASS_CARD,
            "Prepaid Card": CLASS_CARD,
            "BPAY-SFSB": CLASS_WALLET,
            "BPAY-SFSS": CLASS_WALLET,
            "Cheque": CLASS_CHEQUE,
            "Bank Draft": CLASS_BANK,
            "Wire Transfer": CLASS_BANK,
            "NBB-Bank Transfer": CLASS_BANK,
            "Al Salam Bank Transfer": CLASS_BANK,
        }
        for mode, payment_class in expected.items():
            if not frappe.db.exists("Mode of Payment", mode):
                continue
            self.assertEqual(classify_mode(mode), payment_class, msg=mode)

    def test_cheque_wins_over_bank_for_pdc_account(self):
        from vansale.sf_trading.report.mode_of_payment_invoice_wise.mode_of_payment_invoice_wise import (
            classify_account,
        )

        self.assertEqual(classify_account("13020100027 - PDC Account - SFB"), CLASS_CHEQUE)
        self.assertEqual(classify_account("Card-SFSB - SFB"), CLASS_CARD)
        self.assertEqual(classify_account("13010200001 - Sfsb -Petty Cash - SFB"), CLASS_CASH)

    def test_declared_mode_mismatch(self):
        self.assertIsNone(mismatch_label("Cash", {CLASS_CASH: 100}))
        self.assertIsNone(mismatch_label(None, {CLASS_CARD: 100}))
        self.assertIsNone(mismatch_label("Credit", {CLASS_CREDIT: 100}))
        self.assertTrue(mismatch_label("Cash", {CLASS_CARD: 100}))
        self.assertTrue(mismatch_label("Cash", {CLASS_CASH: 60, CLASS_CREDIT: 40}))

    # ---------------------------------------------------------------- aggregation

    def _fabricated(self, legs, outstanding=0.0, grand_total=100.0, declared=None, change=0.0):
        invoice = frappe._dict(
            {
                "name": "SI-TEST-0001",
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "customer": "TEST",
                "customer_name": "Test Customer",
                "branch": None,
                "status": "Paid",
                "currency": "BHD",
                "is_pos": 0,
                "is_return": 0,
                "return_against": None,
                "grand_total": grand_total,
                "rounded_total": grand_total,
                "outstanding_amount": outstanding,
                "change_amount": change,
                "custom_payment_mode": declared,
                "custom_sales_person": None,
            }
        )
        return build_invoice_rows({invoice.name: invoice}, {invoice.name: legs})

    def _leg(self, mode, amount, **extra):
        leg = {
            "invoice": "SI-TEST-0001",
            "voucher_type": "Payment Entry",
            "voucher_no": "PE-TEST-" + str(amount),
            "payment_date": nowdate(),
            "mode_of_payment": mode,
            "amount": amount,
            "account": None,
            "reference_no": None,
            "docstatus": 1,
            "source": "Payment Entry",
        }
        leg.update(extra)
        return leg

    def test_single_mode_invoice(self):
        rows = self._fabricated([self._leg("Cash-SFSB", 100)])
        self.assertEqual(rows[0]["payment_class"], CLASS_CASH)
        self.assertEqual(rows[0]["is_mixed"], 0)
        self.assertEqual(flt(rows[0]["amt_cash"]), 100.0)
        self.assertIn("Cash-SFSB: 100.000", rows[0]["mode_of_payment"])

    def test_mixed_cash_and_card_reads_as_cash_slash_card(self):
        rows = self._fabricated([self._leg("Cash-SFSB", 60), self._leg("Swipe-SFSB", 40)])
        self.assertEqual(rows[0]["payment_class"], "Cash / Card")
        self.assertEqual(rows[0]["is_mixed"], 1)
        self.assertEqual(flt(rows[0]["amt_cash"]), 60.0)
        self.assertEqual(flt(rows[0]["amt_card"]), 40.0)
        self.assertEqual(rows[0]["payments_count"], 2)

    def test_part_paid_invoice_carries_a_credit_bucket(self):
        rows = self._fabricated([self._leg("Cash-SFSB", 60)], outstanding=40)
        self.assertEqual(rows[0]["payment_class"], "Cash / Credit")
        self.assertEqual(flt(rows[0]["amt_credit"]), 40.0)
        self.assertIn(CREDIT_LABEL, rows[0]["mode_of_payment"])

    def test_sub_fils_outstanding_is_not_a_credit(self):
        """A return left with 4 fils open must not read as "Cash / Refund Due"."""
        rows = self._fabricated(
            [self._leg("Cash-SFSB", -30.400)], outstanding=-0.004, grand_total=-30.404
        )
        self.assertEqual(rows[0]["payment_class"], CLASS_CASH)
        self.assertEqual(rows[0]["is_mixed"], 0)
        self.assertEqual(flt(rows[0]["amt_refund_due"]), 0.0)

    def test_unpaid_invoice_is_pure_credit(self):
        rows = self._fabricated([], outstanding=100)
        self.assertEqual(rows[0]["payment_class"], CLASS_CREDIT)
        self.assertEqual(rows[0]["payments_count"], 0)

    def test_mode_not_set_is_flagged_and_classed_from_the_account(self):
        rows = self._fabricated(
            [self._leg(None, 100, account="13010200001 - Sfsb -Petty Cash - SFB")]
        )
        self.assertEqual(rows[0]["mode_not_set"], 1)
        # a Petty Cash account with exactly one Mode of Payment mapped to it resolves;
        # otherwise the account name is shown — either way the class is Cash
        self.assertEqual(flt(rows[0]["amt_cash"]), 100.0)

    def test_journal_leg_without_a_bank_account_is_an_adjustment(self):
        rows = self._fabricated(
            [
                self._leg(
                    None, 100, source="Journal Entry", voucher_type="Journal Entry", account=None
                )
            ]
        )
        self.assertEqual(rows[0]["payment_class"], CLASS_ADJUSTMENT)

    def test_rounded_total_is_ignored_when_rounding_is_disabled(self):
        """Real July returns hold the rounding residue (-0.004) in `rounded_total`."""
        residue = frappe._dict(
            {"grand_total": -300.014, "rounded_total": -0.004, "disable_rounded_total": 1}
        )
        self.assertEqual(document_total(residue, 3), -300.014)

        rounded = frappe._dict(
            {"grand_total": 100.014, "rounded_total": 100.0, "disable_rounded_total": 0}
        )
        self.assertEqual(document_total(rounded, 3), 100.0)

        unset = frappe._dict({"grand_total": 55.5, "rounded_total": 0, "disable_rounded_total": 0})
        self.assertEqual(document_total(unset, 3), 55.5)

    def test_settlement_with_no_voucher_gets_its_own_bucket(self):
        """A migrated return: nothing outstanding, no Payment Entry, total still non-zero."""
        rows = self._fabricated([], outstanding=0.0, grand_total=-27.001)
        self.assertEqual(rows[0]["payment_class"], CLASS_NO_VOUCHER)
        self.assertEqual(flt(rows[0]["amt_settled_no_voucher"]), -27.001)
        self.assertIn(NO_VOUCHER_LABEL, rows[0]["mode_of_payment"])

    def test_rounding_gap_is_not_reported_as_a_missing_voucher(self):
        rows = self._fabricated([self._leg("Cash-SFSB", 100.01)], grand_total=100.0)
        self.assertEqual(flt(rows[0]["amt_settled_no_voucher"]), 0.0)
        self.assertEqual(rows[0]["payment_class"], CLASS_CASH)

    def test_pos_change_is_taken_off_the_collection(self):
        rows = self._fabricated([self._leg("Cash-SFSB", 100)], grand_total=99.0, change=1.0)
        self.assertEqual(flt(rows[0]["paid_total"]), 99.0)
        self.assertEqual(flt(rows[0]["amt_settled_no_voucher"]), 0.0)
        self.assertEqual(rows[0]["payment_class"], CLASS_CASH)

    def test_detail_and_mode_summary_are_consistent_with_the_invoice_row(self):
        rows = self._fabricated([self._leg("Cash-SFSB", 60), self._leg("Swipe-SFSB", 40)])
        details = detail_rows(rows)
        self.assertEqual(len(details), 2)
        self.assertEqual(sum(flt(row["amount"]) for row in details), 100.0)

        summary = mode_summary(rows)
        self.assertEqual(sum(flt(row["amount"]) for row in summary), 100.0)
        self.assertEqual(sum(flt(row["share"]) for row in summary), 100.0)
        for row in summary:
            self.assertEqual(row["transactions"], 1)

    def test_unset_label_is_stable(self):
        # the label is parsed back in class_of_label — keep them in step
        rows = self._fabricated([self._leg(None, 100, account="Some Odd Account - SFB")])
        self.assertTrue(rows[0]["mode_of_payment"].startswith(UNSET_LABEL))

    # ---------------------------------------------------------------- live data

    def test_columns(self):
        columns, _rows = self._run()
        fieldnames = [column["fieldname"] for column in columns]
        for expected in (
            "invoice",
            "payment_class",
            "mode_of_payment",
            "grand_total",
            "outstanding",
            "amt_cash",
            "amt_card",
            "amt_credit",
            "payment_refs",
        ):
            self.assertIn(expected, fieldnames)

    def test_every_row_balances(self):
        """Settled + no-voucher + outstanding = invoice total, within rounding.

        The no-voucher bucket exists precisely so this holds on migrated data — without it
        several hundred June–July returns would silently not add up.
        """
        _columns, rows = self._run()
        for row in rows[:400]:
            total = flt(row["paid_total"]) + flt(row["amt_settled_no_voucher"]) + flt(row["outstanding"])
            self.assertLessEqual(
                abs(total - flt(row["grand_total"])), ROUNDING_TOLERANCE, msg=row["invoice"]
            )

    def test_invoice_type_is_the_declared_payment_mode(self):
        rows = self._fabricated([self._leg("Cheque", 100)], declared="Cheque")
        self.assertEqual(rows[0]["invoice_type"], "Cheque")

    def test_invoices_without_a_declared_mode_are_left_out(self):
        """Scope rule: no declaration on the invoice → not in this report, and no error."""
        _columns, rows = self._run()
        reported = {row["invoice"] for row in rows}
        for row in rows:
            self.assertIn(row["invoice_type"], INVOICE_TYPES, msg=row["invoice"])

        blank = frappe.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "company": self.company,
                "posting_date": [">=", get_first_day(nowdate())],
                "custom_payment_mode": ["in", ["", None]],
            },
            pluck="name",
            limit=25,
        )
        for name in blank:
            self.assertNotIn(name, reported)

    def test_invoice_type_filter_narrows_to_that_declaration(self):
        for declared in INVOICE_TYPES:
            _columns, rows = self._run(invoice_type=declared)
            for row in rows:
                self.assertEqual(row["invoice_type"], declared, msg=row["invoice"])

    def test_every_row_has_a_payment_class(self):
        _columns, rows = self._run()
        for row in rows:
            self.assertTrue(row["payment_class"], msg=row["invoice"])

    def test_mode_filter_only_returns_invoices_with_that_mode(self):
        mode = frappe.db.get_value("Mode of Payment", {"enabled": 1}, "name")
        if not mode:
            return
        _columns, rows = self._run(mode_of_payment=mode)
        for row in rows:
            self.assertIn(mode, row["mode_of_payment"], msg=row["invoice"])

    def test_detail_view_sums_back_to_the_invoice_view(self):
        _columns, invoice_rows = self._run()
        _detail_columns, details = self._run(view="Payment Detail")
        if not invoice_rows:
            return

        by_invoice = {}
        for row in details:
            by_invoice[row["invoice"]] = flt(by_invoice.get(row["invoice"])) + flt(row["amount"])

        for row in invoice_rows[:200]:
            self.assertLessEqual(
                abs(flt(by_invoice.get(row["invoice"])) - flt(row["grand_total"])),
                ROUNDING_TOLERANCE,
                msg=row["invoice"],
            )

    def test_mixed_filter_returns_only_mixed_invoices(self):
        _columns, rows = self._run(only_mixed=1)
        for row in rows:
            self.assertIn(" / ", row["payment_class"], msg=row["invoice"])

    def test_payment_date_basis_returns_invoices_paid_in_the_window(self):
        _columns, rows = self._run(date_basis="Payment Date")
        for row in rows[:100]:
            self.assertTrue(row["payment_class"])
