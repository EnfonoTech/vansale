"""Tests for automatic PO advance allocation on Purchase Invoice.

Run on a scratch site, never on a client site — the suite creates its own company,
warehouse, item and supplier:

    bench --site <scratch-site> run-tests --module vansale.sf_trading.tests.test_advance_allocation
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from vansale.sf_trading.overrides.purchase_invoice import set_advance_allocation
from vansale.sf_trading.tests.test_sdbnb import ABBR, COMPANY, get_test_company

SUPPLIER = "_Test Advance Alloc Supplier"


class TestAdvanceAllocation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.warehouse = "Stores - " + ABBR
		cls.cost_center = "Main - " + ABBR
		cls.cash_account = "Cash - " + ABBR
		cls.item_code = cls.make_item()
		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": SUPPLIER,
					"supplier_group": "All Supplier Groups",
				}
			).insert()

	@classmethod
	def make_item(cls):
		from erpnext.stock.doctype.item.test_item import make_item

		return make_item(
			"Advance Alloc Test Item", properties={"is_stock_item": 1, "item_group": "Products"}
		).name

	def make_po(self, qty=10, rate=100):
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": COMPANY,
				"supplier": SUPPLIER,
				"transaction_date": nowdate(),
				"schedule_date": add_days(nowdate(), 1),
				"currency": "INR",
				"conversion_rate": 1,
				"items": [
					{
						"item_code": self.item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
						"schedule_date": add_days(nowdate(), 1),
					}
				],
			}
		)
		po.insert()
		po.submit()
		return po

	def pay_advance(self, po, amount):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		pe = get_payment_entry("Purchase Order", po.name, bank_account=self.cash_account)
		pe.references[0].allocated_amount = amount
		pe.paid_amount = amount
		pe.received_amount = amount
		pe.reference_no = "ADV-" + po.name
		pe.reference_date = nowdate()
		pe.insert()
		pe.submit()
		po.reload()
		return pe

	def invoice_from(self, po):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		pi = make_purchase_invoice(po.name)
		pi.bill_no = "BILL-" + po.name
		pi.insert()
		return pi

	def standalone_invoice(self):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": COMPANY,
				"supplier": SUPPLIER,
				"posting_date": nowdate(),
				"bill_no": "STANDALONE-1",
				"currency": "INR",
				"conversion_rate": 1,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 1,
						"rate": 50,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		pi.insert()
		return pi

	# ------------------------------------------------------------------

	def test_an_invoice_against_an_order_allocates_that_order_advance(self):
		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=400)

		pi = self.invoice_from(po)
		self.assertEqual(pi.allocate_advances_automatically, 1)
		self.assertEqual(pi.only_include_allocated_payments, 1)
		self.assertTrue(pi.advances, "the order's advance should have been picked up")
		self.assertEqual(flt(sum(row.allocated_amount for row in pi.advances)), 400)

	def test_the_allocation_is_capped_at_the_invoice_total(self):
		"""An advance larger than the bill cannot allocate more than the bill."""
		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=1000)

		pi = self.invoice_from(po)
		total = flt(pi.base_rounded_total or pi.base_grand_total)
		self.assertEqual(flt(sum(row.allocated_amount for row in pi.advances)), total)

	def test_a_standalone_invoice_has_the_switches_turned_back_off(self):
		"""The DocField default arrives as 1; an invoice naming no order must not keep it.

		get_advance_journal_entries applies no reference filter at all when nothing is
		unallocated and there is no order to match, so it would return every advance
		journal entry for the supplier. Turning the switches off avoids that path.
		"""
		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=400)

		pi = self.standalone_invoice()
		self.assertEqual(flt(pi.allocate_advances_automatically), 0)
		self.assertEqual(flt(pi.only_include_allocated_payments), 0)
		self.assertFalse(pi.advances)

	def test_the_switches_are_cleared_even_when_they_arrive_set(self):
		"""Simulates the shipped default of 1 landing on a non-order invoice."""
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": COMPANY,
				"supplier": SUPPLIER,
				"posting_date": nowdate(),
				"bill_no": "STANDALONE-DEFAULTED",
				"currency": "INR",
				"conversion_rate": 1,
				"allocate_advances_automatically": 1,
				"only_include_allocated_payments": 1,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 1,
						"rate": 50,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		# is_new() is bool(self.get("__islocal")) (base_document.py:464) and insert() is
		# what sets it, so a document built in memory and never inserted looks OLD to the
		# hook. Set it here or the hook returns early and the assertion below proves nothing.
		pi.set("__islocal", True)
		set_advance_allocation(pi)
		self.assertEqual(flt(pi.allocate_advances_automatically), 0)
		self.assertEqual(flt(pi.only_include_allocated_payments), 0)

	def test_a_hand_picked_advance_on_a_standalone_invoice_is_respected(self):
		"""Advance rows only exist because somebody asked, so do not undo their choice."""
		po = self.make_po(qty=10, rate=100)
		pe = self.pay_advance(po, amount=400)

		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": COMPANY,
				"supplier": SUPPLIER,
				"posting_date": nowdate(),
				"bill_no": "STANDALONE-MANUAL-ADVANCE",
				"currency": "INR",
				"conversion_rate": 1,
				"allocate_advances_automatically": 1,
				"only_include_allocated_payments": 1,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 1,
						"rate": 50,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
				"advances": [
					{
						"reference_type": "Payment Entry",
						"reference_name": pe.name,
						"advance_amount": 400,
						"allocated_amount": 50,
					}
				],
			}
		)
		# is_new() is bool(self.get("__islocal")) (base_document.py:464) and insert() is
		# what sets it, so a document built in memory and never inserted looks OLD to the
		# hook. Set it here or the hook returns early and the assertion below proves nothing.
		pi.set("__islocal", True)
		set_advance_allocation(pi)
		self.assertEqual(flt(pi.allocate_advances_automatically), 1)

	def test_a_paid_invoice_is_left_alone(self):
		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=400)

		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		pi = make_purchase_invoice(po.name)
		pi.is_paid = 1
		pi.allocate_advances_automatically = 0
		pi.only_include_allocated_payments = 0
		pi.advances = []
		# is_new() is bool(self.get("__islocal")) (base_document.py:464) and insert() is
		# what sets it, so a document built in memory and never inserted looks OLD to the
		# hook. Set it here or the hook returns early and the assertion below proves nothing.
		pi.set("__islocal", True)
		set_advance_allocation(pi)
		self.assertEqual(flt(pi.allocate_advances_automatically), 0)

	def test_unticking_survives_a_second_save(self):
		"""The hook only fires on a new document, so a deliberate choice sticks."""
		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=400)

		pi = self.invoice_from(po)
		pi.allocate_advances_automatically = 0
		pi.advances = []
		pi.save()

		pi.reload()
		self.assertEqual(flt(pi.allocate_advances_automatically), 0)
		self.assertFalse(pi.advances)

	def test_submitting_consumes_the_advance_and_clears_the_order(self):
		"""End to end: the advance is what settles the invoice, and the order is done."""
		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=1000)

		pi = self.invoice_from(po)
		pi.submit()
		pi.reload()

		self.assertEqual(flt(pi.outstanding_amount), 0)

		from vansale.sf_trading.report.pending_advance_po.pending_advance_po import (
			pending_advance_orders,
		)

		listed = [
			row["purchase_order"]
			for row in pending_advance_orders(frappe._dict(company=COMPANY))
		]
		self.assertNotIn(po.name, listed)
