# apps/vansale/vansale/sf_trading/doctype/payment_advice/test_payment_advice.py
"""Tests for Payment Advice — allocation, totals, guards and the Payment Entry builder.

These cover the defects carried over from the original payment_advice app, so a regression
would fail here rather than in production: allocation stopping at the authorised amount,
flt() safety on nulls, company coming from the document, and the exchange-rate call shape.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate

from vansale.sf_trading.doctype.payment_advice.payment_advice import (
    ALLOWED_REFERENCE_DOCTYPES,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_PENDING,
    get_company_account,
    get_payment_type,
    shape_reference_rows,
)


class TestPaymentAdvice(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
            "Company", {}, "name"
        )

    # ── pure helpers ─────────────────────────────────────────────────────────────
    def test_payment_type_by_party(self):
        self.assertEqual(get_payment_type("Supplier"), "Pay")
        self.assertEqual(get_payment_type("Customer"), "Receive")

    def test_payment_type_rejects_employee(self):
        # party_type offers only Supplier and Customer; Employee was never wired up
        with self.assertRaises(frappe.ValidationError):
            get_payment_type("Employee")

    def test_payment_type_rejects_unknown_party(self):
        with self.assertRaises(frappe.ValidationError):
            get_payment_type("Shareholder")

    def test_company_account_falls_back(self):
        # never raises; either an account or None, but always company-scoped
        account = get_company_account(self.company, None)
        if account:
            self.assertEqual(frappe.db.get_value("Account", account, "company"), self.company)

    def test_approver_links_to_a_user_not_an_employee(self):
        # an Employee with no User ID could be picked and then nobody could submit the advice
        for doctype in ("Payment Advice", "Payment Automation Settings"):
            self.assertEqual(frappe.get_meta(doctype).get_field("approver").options, "User")

    def test_party_name_is_filled_from_the_party(self):
        for party_type, title_field in (("Supplier", "supplier_name"), ("Customer", "customer_name")):
            party = frappe.db.get_value(party_type, {"disabled": 0}, ["name", title_field], as_dict=True)
            if not party:
                continue
            advice = frappe.new_doc("Payment Advice")
            advice.party_type, advice.party = party_type, party.name
            advice.set_party_name()
            self.assertEqual(advice.party_name, party.get(title_field) or party.name)

    def test_party_name_left_alone_without_a_party(self):
        advice = frappe.new_doc("Payment Advice")
        advice.party_type = "Supplier"
        advice.set_party_name()
        self.assertFalse(advice.party_name)

    # ── allocation ───────────────────────────────────────────────────────────────
    def _advice(self, payables, payment_amount):
        """Build an unsaved advice with synthetic reference rows."""
        advice = frappe.new_doc("Payment Advice")
        advice.update(
            {
                "company": self.company,
                "party_type": "Supplier",
                "transaction_date": nowdate(),
                "payment_amount": payment_amount,
            }
        )
        for payable in payables:
            advice.append("payment_advice_reference", {"net_payable_amount": payable})
        return advice

    def test_allocation_stops_at_authorised_amount(self):
        advice = self._advice([100, 200, 300], 250)
        advice.allocate_payment()
        allocations = [flt(r.allocated_amount) for r in advice.payment_advice_reference]
        self.assertEqual(allocations, [100.0, 150.0, 0.0])
        self.assertEqual(sum(allocations), 250.0)

    def test_allocation_never_exceeds_a_row(self):
        advice = self._advice([50, 50], 500)
        advice.allocate_payment()
        for row in advice.payment_advice_reference:
            self.assertLessEqual(flt(row.allocated_amount), flt(row.net_payable_amount))

    def test_allocation_handles_null_amounts(self):
        """The original app raised TypeError here — nulls must simply allocate zero."""
        advice = self._advice([None, 100], 60)
        advice.allocate_payment()
        allocations = [flt(r.allocated_amount) for r in advice.payment_advice_reference]
        self.assertEqual(allocations, [0.0, 60.0])

    def test_allocation_zero_payment(self):
        advice = self._advice([100], 0)
        advice.allocate_payment()
        self.assertEqual(flt(advice.payment_advice_reference[0].allocated_amount), 0.0)

    # ── totals + guards ──────────────────────────────────────────────────────────
    def test_totals_from_rows(self):
        advice = self._advice([], 10)
        for amount, settled in ((100, 40), (50, 0)):
            advice.append(
                "payment_advice_reference",
                {"amount": amount, "settled_amount": settled, "net_payable_amount": amount - settled},
            )
        advice.compute_totals()
        self.assertEqual(flt(advice.amount), 150.0)
        self.assertEqual(flt(advice.amount_paid), 40.0)
        self.assertEqual(flt(advice.amount_to_be_settled), 110.0)
        self.assertEqual(flt(advice.pending_amount), 100.0)

    def test_payment_amount_must_be_positive(self):
        advice = self._advice([100], 0)
        advice.compute_totals()
        with self.assertRaises(frappe.ValidationError):
            advice.validate_payment_amount()

    def test_payment_amount_cannot_exceed_payable(self):
        advice = self._advice([100], 250)
        advice.compute_totals()
        with self.assertRaises(frappe.ValidationError):
            advice.validate_payment_amount()

    def test_status_lifecycle(self):
        advice = self._advice([100], 100)
        advice.docstatus = 0
        advice.set_status()
        self.assertEqual(advice.status, STATUS_DRAFT)

        advice.approver = "Administrator"
        advice.set_status()
        self.assertEqual(advice.status, STATUS_PENDING)

        advice.docstatus = 1
        advice.payment_entry = None
        advice.set_status()
        self.assertEqual(advice.status, STATUS_APPROVED)

    # ── schema expectations the automation layer depends on ──────────────────────
    def test_fields_the_automation_needs_exist(self):
        meta = frappe.get_meta("Payment Advice")
        for fieldname in ("status", "auto_generated", "payment_entry", "bank_account", "company"):
            self.assertTrue(meta.has_field(fieldname), fieldname)

    def test_payment_entry_link_is_a_link_not_data(self):
        """The original stored the PE as free text, so nothing could be joined to it."""
        df = frappe.get_meta("Payment Advice").get_field("payment_entry")
        self.assertEqual(df.fieldtype, "Link")
        self.assertEqual(df.options, "Payment Entry")
        self.assertTrue(df.allow_on_submit)

    def test_reference_child_has_allocated_amount(self):
        meta = frappe.get_meta("Payment Advice Reference")
        self.assertTrue(meta.has_field("allocated_amount"))
        self.assertTrue(meta.has_field("ageing"))  # was misspelled "aeging" upstream


class TestOutstandingMapping(FrappeTestCase):
    """shape_reference_rows() maps ERPNext's outstanding rows onto advice references.

    Key shapes verified against live data: the engine returns voucher_type, voucher_no,
    bill_no, currency, due_date, exchange_rate, invoice_amount, outstanding_amount,
    posting_date — but NOT payment_term (unless term-allocated) and NOT total_amount.
    """

    def _voucher(self, **kw):
        row = {
            "voucher_type": "Purchase Invoice",
            "voucher_no": "PINV-TEST-001",
            "invoice_amount": 1000.0,
            "outstanding_amount": 400.0,
            "posting_date": "2026-01-01",
            "due_date": "2026-01-31",
            "currency": "BHD",
            "exchange_rate": 1.0,
            "bill_no": "SUP-77",
        }
        row.update(kw)
        return row

    def test_maps_core_fields(self):
        rows = shape_reference_rows([self._voucher()])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["reference_doctype"], "Purchase Invoice")
        self.assertEqual(row["reference_record"], "PINV-TEST-001")
        self.assertEqual(row["net_payable_amount"], 400.0)
        self.assertEqual(row["amount"], 1000.0)
        self.assertEqual(row["settled_amount"], 600.0)
        self.assertEqual(row["bill_no"], "SUP-77")
        self.assertEqual(row["currency"], "BHD")

    def test_missing_payment_term_and_total_amount_are_safe(self):
        """The engine omits both for ordinary invoices — mapping must not raise."""
        voucher = self._voucher()
        voucher.pop("bill_no")
        rows = shape_reference_rows([voucher])
        self.assertIsNone(rows[0]["payment_term"])
        self.assertEqual(rows[0]["amount"], 1000.0)

    def test_total_amount_used_when_invoice_amount_absent(self):
        voucher = self._voucher(invoice_amount=None, total_amount=750.0)
        rows = shape_reference_rows([voucher])
        self.assertEqual(rows[0]["amount"], 750.0)

    def test_zero_outstanding_dropped(self):
        rows = shape_reference_rows([self._voucher(outstanding_amount=0)])
        self.assertEqual(rows, [])

    def test_disallowed_doctype_dropped(self):
        rows = shape_reference_rows([self._voucher(voucher_type="Delivery Note")])
        self.assertEqual(rows, [])
        self.assertNotIn("Delivery Note", ALLOWED_REFERENCE_DOCTYPES)

    def test_amount_window(self):
        vouchers = [
            self._voucher(voucher_no="A", outstanding_amount=50),
            self._voucher(voucher_no="B", outstanding_amount=300),
            self._voucher(voucher_no="C", outstanding_amount=900),
        ]
        rows = shape_reference_rows(vouchers, from_amount=100, to_amount=500)
        self.assertEqual([r["reference_record"] for r in rows], ["B"])

    def test_sorted_worst_first(self):
        vouchers = [
            self._voucher(voucher_no="NEW", due_date="2026-07-01", outstanding_amount=100),
            self._voucher(voucher_no="OLD", due_date="2024-01-01", outstanding_amount=100),
        ]
        rows = shape_reference_rows(vouchers)
        self.assertEqual(rows[0]["reference_record"], "OLD")
        self.assertGreater(rows[0]["ageing"], rows[1]["ageing"])

    def test_ageing_never_negative_for_future_due_dates(self):
        rows = shape_reference_rows([self._voucher(due_date="2099-01-01")])
        self.assertEqual(rows[0]["ageing"], 0)


class TestReferenceIntegrity(FrappeTestCase):
    """Dynamic Link guards: the form filters the pickers, the server enforces the rules."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
            "Company", {}, "name"
        )

    def _advice_with(self, rows):
        advice = frappe.new_doc("Payment Advice")
        advice.update(
            {
                "company": self.company,
                "party_type": "Supplier",
                "party": frappe.db.get_value("Supplier", {}, "name"),
                "transaction_date": nowdate(),
                "payment_amount": 1,
            }
        )
        for row in rows:
            advice.append("payment_advice_reference", row)
        return advice

    def test_rejects_unknown_reference_doctype(self):
        advice = self._advice_with(
            [{"reference_doctype": "Delivery Note", "reference_record": "DN-0001"}]
        )
        with self.assertRaises(frappe.ValidationError):
            advice.validate_references()

    def test_rejects_blank_reference(self):
        advice = self._advice_with([{"reference_doctype": "Purchase Invoice"}])
        with self.assertRaises(frappe.ValidationError):
            advice.validate_references()

    def test_rejects_duplicate_reference_rows(self):
        pinv = frappe.db.get_value(
            "Purchase Invoice", {"docstatus": 1, "outstanding_amount": [">", 0]}, "name"
        )
        if not pinv:
            self.skipTest("no outstanding Purchase Invoice on this site")
        supplier, company = frappe.db.get_value("Purchase Invoice", pinv, ["supplier", "company"])
        advice = self._advice_with(
            [
                {"reference_doctype": "Purchase Invoice", "reference_record": pinv},
                {"reference_doctype": "Purchase Invoice", "reference_record": pinv},
            ]
        )
        advice.party = supplier
        advice.company = company
        with self.assertRaises(frappe.ValidationError):
            advice.validate_references()

    def test_rejects_reference_of_another_party(self):
        rows = frappe.get_all(
            "Purchase Invoice",
            filters={"docstatus": 1, "outstanding_amount": [">", 0]},
            fields=["name", "supplier", "company"],
            limit=20,
        )
        pair = None
        for row in rows:
            other = next((r for r in rows if r.supplier != row.supplier), None)
            if other:
                pair = (row, other)
                break
        if not pair:
            self.skipTest("need invoices from two different suppliers")

        mine, theirs = pair
        advice = self._advice_with(
            [{"reference_doctype": "Purchase Invoice", "reference_record": theirs.name}]
        )
        advice.party = mine.supplier
        advice.company = mine.company
        with self.assertRaises(frappe.ValidationError):
            advice.validate_references()


class TestCreateAdvicesFromDocuments(FrappeTestCase):
    """The endpoint behind the "Payment Advice" entry in the Create menu of Purchase Order and
    Purchase Invoice (public/js/payment_advice_form_action.js) and behind the list-view action.

    Note: create_advices_from_documents() commits per advice, so anything it creates outlives the
    test transaction. Every test that lets it succeed removes what it made — and it has to cope with
    the advice having been submitted in the meantime, because the site's own
    payment_automation.run_due_automations tick stamps an approver and approves fresh drafts. A
    submitted document cannot be deleted even with force=True, so cancel comes first.
    """

    def _call(self, documents, doctype):
        from vansale.sf_trading.api.payment_advice_builder import create_advices_from_documents

        return create_advices_from_documents(documents, {"doctype": doctype})

    def _cleanup(self, result):
        for row in (result or {}).get("created", []):
            name = row["advice"]
            if not frappe.db.exists("Payment Advice", name):
                continue
            if frappe.db.get_value("Payment Advice", name, "docstatus") == 1:
                doc = frappe.get_doc("Payment Advice", name)
                doc.flags.ignore_permissions = True
                doc.cancel()
            frappe.delete_doc("Payment Advice", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    # ── contract guards ──────────────────────────────────────────────────────────
    def test_empty_selection_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._call([], "Purchase Invoice")

    def test_doctype_without_a_party_field_is_rejected(self):
        # UOM carries neither supplier nor customer, so it can never be paid. The guard has to fire
        # before the query is built, otherwise the missing columns surface as a raw 1054.
        with self.assertRaises(frappe.ValidationError):
            self._call(["Nos"], "UOM")

    def test_unsubmitted_or_missing_documents_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._call(["PI-does-not-exist-0001"], "Purchase Invoice")

    # ── the two Create-menu sources ──────────────────────────────────────────────
    def test_purchase_order_raises_a_supplier_advice(self):
        from vansale.sf_trading.doctype.payment_advice.payment_advice import get_reference_amounts

        po = frappe.db.get_value(
            "Purchase Order",
            {"docstatus": 1, "status": ["not in", ["On Hold", "Closed"]], "per_billed": ["<", 100]},
            ["name", "supplier", "company"],
            as_dict=True,
        )
        if not po:
            self.skipTest("need a submitted Purchase Order with per_billed < 100")

        _total, payable = get_reference_amounts("Purchase Order", po.name)
        if payable <= 0:
            self.skipTest("the candidate Purchase Order has nothing left to pay")

        result = self._call([po.name], "Purchase Order")
        self.addCleanup(self._cleanup, result)

        self.assertEqual(len(result["created"]), 1)
        self.assertFalse(result["failed"])
        advice = frappe.get_doc("Payment Advice", result["created"][0]["advice"])
        self.assertEqual(advice.docstatus, 0)
        self.assertEqual(advice.party_type, "Supplier")
        self.assertEqual(advice.party, po.supplier)
        self.assertEqual(advice.company, po.company)
        rows = advice.payment_advice_reference
        self.assertEqual([r.reference_doctype for r in rows], ["Purchase Order"])
        self.assertEqual(rows[0].reference_record, po.name)
        self.assertEqual(flt(rows[0].net_payable_amount, 3), flt(payable, 3))

        # a document already on a live advice cannot be advised twice
        with self.assertRaises(frappe.ValidationError):
            self._call([po.name], "Purchase Order")

    def test_purchase_invoice_raises_a_supplier_advice(self):
        pi = frappe.db.get_value(
            "Purchase Invoice",
            {"docstatus": 1, "outstanding_amount": [">", 0], "is_return": 0, "on_hold": 0},
            ["name", "supplier", "company"],
            as_dict=True,
        )
        if not pi:
            self.skipTest("need a submitted Purchase Invoice with an outstanding amount")

        result = self._call([pi.name], "Purchase Invoice")
        self.addCleanup(self._cleanup, result)

        self.assertEqual(len(result["created"]), 1)
        advice = frappe.get_doc("Payment Advice", result["created"][0]["advice"])
        self.assertEqual(advice.party, pi.supplier)
        self.assertEqual(
            [r.reference_doctype for r in advice.payment_advice_reference], ["Purchase Invoice"]
        )
        self.assertGreater(flt(advice.payment_amount), 0)

    # ── the amount rules live in the workflow conditions, not in Python ─────────────

    def _sends(self):
        from vansale.sf_trading.api import payment_advice_workflow as wf

        return [
            t for t in wf._transitions("Steel Force Trading WLL")
            if t["action"] == "Send for Approval" and t["state"] == "Draft"
        ]

    def test_the_accountant_can_raise_an_advice(self):
        """The role appears on both sides of the chain."""
        from vansale.sf_trading.api import payment_advice_workflow as wf

        self.assertIn(wf.ROLE_APPROVER, wf.PREPARER_ROLES)
        raisers = {t["allowed"] for t in self._sends()}
        self.assertIn(wf.ROLE_APPROVER, raisers)

    def test_the_accountants_direct_route_is_capped_at_the_limit(self):
        """Their own straight-through row only applies at or below the limit."""
        from vansale.sf_trading.api import payment_advice_workflow as wf

        rows = [
            t for t in self._sends()
            if t["allowed"] == wf.ROLE_APPROVER and t["next_state"] == "Pending Accountant"
        ]
        self.assertEqual(len(rows), 1)
        self.assertIn("<= 500", rows[0]["condition"])
        self.assertIn('doc.approval_route == "Accountant"', rows[0]["condition"])

    def test_the_accountants_large_direct_advice_goes_to_finance(self):
        """Over the limit somebody else approves before it reaches their own desk."""
        from vansale.sf_trading.api import payment_advice_workflow as wf

        rows = [
            t for t in self._sends()
            if t["allowed"] == wf.ROLE_APPROVER
            and t["next_state"] == "Pending Finance"
            and "Accountant" in (t["condition"] or "")
        ]
        self.assertEqual(len(rows), 1)
        self.assertIn("> 500", rows[0]["condition"])

    def test_the_other_preparers_are_not_capped(self):
        """The limit is about who raised it; Branch Head and Purchase Assistant are unaffected."""
        from vansale.sf_trading.api import payment_advice_workflow as wf

        for role in (wf.ROLE_BRANCH_HEAD, wf.ROLE_PURCHASE_ASSISTANT):
            rows = [
                t for t in self._sends()
                if t["allowed"] == role and t["next_state"] == "Pending Accountant"
            ]
            self.assertEqual(len(rows), 1, role)
            self.assertNotIn("payment_amount", rows[0]["condition"], role)

    def test_the_limit_comes_from_one_place(self):
        """The conditions are generated from the controller constant, not retyped."""
        from vansale.sf_trading.api import payment_advice_workflow as wf
        from vansale.sf_trading.doctype.payment_advice.payment_advice import (
            FINANCE_APPROVAL_LIMIT,
        )

        self.assertEqual(wf.FINANCE_APPROVAL_LIMIT, FINANCE_APPROVAL_LIMIT)

    # ── the amount decides for orders too, not just invoices ───────────────────

    def _route(self, rows, amount):
        import vansale.sf_trading.doctype.payment_advice.payment_advice as pa

        advice = frappe._dict({
            "payment_amount": amount,
            "payment_advice_reference": [frappe._dict(r) for r in rows],
        })
        return pa.compute_approval_route(advice)

    def test_single_order_within_the_limit_goes_direct(self):
        rows = [{"reference_doctype": "Purchase Order", "reference_record": "PO-1"}]
        self.assertEqual(self._route(rows, 500), "Accountant")

    def test_single_order_over_the_limit_goes_to_the_purchase_manager(self):
        """A single large order takes the same route as several: Purchase Manager first.

        It used to bypass the limit entirely, which is how BHD 6,364 was released on one
        signature.
        """
        rows = [{"reference_doctype": "Purchase Order", "reference_record": "PO-1"}]
        self.assertEqual(self._route(rows, 6364.458), "Purchase Manager")

    def test_a_large_invoice_still_goes_to_finance_not_purchase(self):
        """Orders and invoices part company above the limit: the order was already approved."""
        rows = [{"reference_doctype": "Purchase Invoice", "reference_record": "PI-1"}]
        self.assertEqual(self._route(rows, 6364.458), "Finance")

    def test_single_invoice_is_unchanged(self):
        rows = [{"reference_doctype": "Purchase Invoice", "reference_record": "PI-1"}]
        self.assertEqual(self._route(rows, 500), "Accountant")
        self.assertEqual(self._route(rows, 500.001), "Finance")

    def test_several_orders_still_go_to_the_purchase_manager(self):
        """The order count is tested before the amount, so a small multi-order advice still
        takes the longer route."""
        rows = [
            {"reference_doctype": "Purchase Order", "reference_record": "PO-1"},
            {"reference_doctype": "Purchase Order", "reference_record": "PO-2"},
        ]
        self.assertEqual(self._route(rows, 10), "Purchase Manager")


class TestPaymentAdviceStaleReferences(FrappeTestCase):
	"""A reference settled after the advice was raised must be caught, and named."""

	def test_refresh_names_the_row_that_moved(self):
		from vansale.sf_trading.doctype.payment_advice.payment_advice import PaymentAdvice

		advice = frappe.get_doc({"doctype": "Payment Advice"})
		advice.docstatus = 0
		advice._payable_changes = [
			{"idx": 3, "reference": "PINV-0009", "was": 656.691, "now": 653.890}
		]
		messages = []
		original = frappe.msgprint
		frappe.msgprint = lambda msg, **kwargs: messages.append(msg)
		try:
			PaymentAdvice.report_payable_changes(advice)
		finally:
			frappe.msgprint = original

		self.assertTrue(messages, "a moved reference must be announced")
		body = messages[0]
		self.assertIn("Row #3", body)
		self.assertIn("PINV-0009", body)

	def test_over_allocation_error_points_at_the_row(self):
		from vansale.sf_trading.doctype.payment_advice.payment_advice import PaymentAdvice

		advice = frappe.get_doc({"doctype": "Payment Advice"})
		advice.payment_amount = 656.691
		advice.amount_to_be_settled = 653.890
		advice._payable_changes = [
			{"idx": 2, "reference": "PINV-0042", "was": 656.691, "now": 653.890}
		]
		advice.append("payment_advice_reference",
			{"reference_doctype": "Purchase Invoice", "reference_record": "PINV-0042",
			 "net_payable_amount": 653.890})

		with self.assertRaises(frappe.ValidationError) as caught:
			PaymentAdvice.validate_payment_amount(advice)
		text = frappe.utils.strip_html(str(caught.exception))
		# the reader must be able to see WHICH reference moved, not just two totals
		self.assertIn("Row #2", text)
		self.assertIn("PINV-0042", text)
