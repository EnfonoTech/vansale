"""Tests for the Pending Advance PO report.

Run on a scratch site, never on a client site — the suite creates its own company,
warehouse, item and supplier:

    bench --site <scratch-site> run-tests --module vansale.sf_trading.tests.test_pending_advance_po
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from vansale.sf_trading.report.pending_advance_po.pending_advance_po import (
	advance_ledger_balances,
	build_row,
	pending_advance_orders,
)
from vansale.sf_trading.tests.test_sdbnb import ABBR, COMPANY, get_test_company

SUPPLIER = "_Test Advance PO Supplier"
OTHER_SUPPLIER = "_Test Advance PO Supplier 2"


class TestPendingAdvancePO(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.warehouse = "Stores - " + ABBR
		cls.cost_center = "Main - " + ABBR
		cls.cash_account = "Cash - " + ABBR
		cls.item_code = cls.make_item()
		cls.make_suppliers()

	@classmethod
	def make_item(cls):
		from erpnext.stock.doctype.item.test_item import make_item

		return make_item(
			"Advance PO Test Item", properties={"is_stock_item": 1, "item_group": "Products"}
		).name

	@classmethod
	def make_suppliers(cls):
		for name in (SUPPLIER, OTHER_SUPPLIER):
			if not frappe.db.exists("Supplier", name):
				frappe.get_doc(
					{
						"doctype": "Supplier",
						"supplier_name": name,
						"supplier_group": "All Supplier Groups",
					}
				).insert()

	# ------------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------------

	def filters(self, **overrides):
		base = {"company": COMPANY}
		base.update(overrides)
		return frappe._dict(base)

	def make_po(self, qty=10, rate=100, supplier=SUPPLIER, transaction_date=None):
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": COMPANY,
				"supplier": supplier,
				"transaction_date": transaction_date or nowdate(),
				"schedule_date": add_days(transaction_date or nowdate(), 1),
				"currency": "INR",
				"conversion_rate": 1,
				"items": [
					{
						"item_code": self.item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
						"schedule_date": add_days(transaction_date or nowdate(), 1),
					}
				],
			}
		)
		po.insert()
		po.submit()
		return po

	def pay_advance(self, po, amount=None):
		"""A real supplier advance against the order, the way the desk raises one."""
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		pe = get_payment_entry("Purchase Order", po.name, bank_account=self.cash_account)
		if amount is not None:
			pe.references[0].allocated_amount = amount
			pe.paid_amount = amount
			pe.received_amount = amount
		pe.reference_no = "ADV-" + po.name
		pe.reference_date = nowdate()
		pe.insert()
		pe.submit()
		po.reload()
		return pe

	def invoice(self, po, submit=True):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		pi = make_purchase_invoice(po.name)
		pi.bill_no = "BILL-" + po.name
		# the advance is the subject of this report, so never let the invoice quietly
		# consume it and change what is being asserted
		pi.allocate_advances_automatically = 0
		pi.advances = []
		pi.insert()
		if submit:
			pi.submit()
		po.reload()
		return pi

	def row_for(self, po, **overrides):
		rows = pending_advance_orders(self.filters(**overrides))
		matches = [row for row in rows if row["purchase_order"] == po.name]
		return matches[0] if matches else None

	# ------------------------------------------------------------------
	# what belongs in the report
	# ------------------------------------------------------------------

	def test_order_without_an_advance_is_absent(self):
		po = self.make_po()
		self.assertIsNone(self.row_for(po))

	def test_order_with_an_advance_is_listed_with_that_advance(self):
		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=400)

		row = self.row_for(po)
		self.assertIsNotNone(row)
		self.assertEqual(row["advance_paid"], 400)
		self.assertEqual(row["supplier"], SUPPLIER)
		self.assertEqual(row["transaction_date"], po.transaction_date)

	def test_the_advance_matches_the_ledger(self):
		"""The stored field and the advance ledger have to agree, or Remarks says so."""
		po = self.make_po()
		self.pay_advance(po, amount=250)

		self.assertEqual(advance_ledger_balances(COMPANY).get(po.name), 250)
		self.assertEqual(self.row_for(po)["remarks"], "")

	def test_order_drops_out_once_an_invoice_is_submitted(self):
		po = self.make_po()
		self.pay_advance(po, amount=300)
		self.assertIsNotNone(self.row_for(po))

		self.invoice(po)
		self.assertIsNone(self.row_for(po))

	def test_a_draft_invoice_leaves_the_order_pending_but_names_it(self):
		"""Nothing is booked until submit, so a draft does not settle the advance."""
		po = self.make_po()
		self.pay_advance(po, amount=300)
		pi = self.invoice(po, submit=False)

		row = self.row_for(po)
		self.assertIsNotNone(row)
		self.assertEqual(row["draft_invoice"], pi.name)

	def test_an_invoice_naming_only_the_receipt_still_settles_the_order(self):
		"""The route that would otherwise hold a billed order open forever.

		An invoice raised from a Purchase Receipt can end up naming only the receipt
		row. The order has genuinely been billed, so it must leave the report even
		though nothing on the invoice points at the order.
		"""
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
			make_purchase_invoice as invoice_from_receipt,
		)

		po = self.make_po()
		self.pay_advance(po, amount=300)

		pr = make_purchase_receipt(po.name)
		pr.insert()
		pr.submit()

		pi = invoice_from_receipt(pr.name)
		pi.bill_no = "BILL-PR-" + po.name
		pi.allocate_advances_automatically = 0
		pi.advances = []
		pi.insert()
		pi.submit()

		# strip the order links the mapper carried over, leaving only pr_detail
		for row in pi.items:
			frappe.db.set_value(
				"Purchase Invoice Item",
				row.name,
				{"purchase_order": None, "po_detail": None},
				update_modified=False,
			)
		self.assertIsNone(self.row_for(po))

	def test_a_cancelled_invoice_does_not_settle_the_order(self):
		"""Only a submitted invoice counts, so cancelling one reopens the order."""
		po = self.make_po()
		self.pay_advance(po, amount=300)
		pi = self.invoice(po)
		self.assertIsNone(self.row_for(po))

		pi.reload()
		pi.cancel()
		self.assertIsNotNone(self.row_for(po))

	def test_a_closed_order_is_still_listed_and_flagged(self):
		"""Money paid on an abandoned order is the most urgent row, not one to hide."""
		po = self.make_po()
		self.pay_advance(po, amount=200)
		po.db_set("status", "Closed")

		row = self.row_for(po)
		self.assertIsNotNone(row)
		self.assertEqual(row["advance_paid"], 200)
		self.assertIn("closed", row["remarks"])

	def test_the_date_window_bounds_the_order_date(self):
		old = self.make_po(transaction_date=add_days(nowdate(), -20))
		self.pay_advance(old, amount=100)
		recent = self.make_po(transaction_date=nowdate())
		self.pay_advance(recent, amount=100)

		names = [
			row["purchase_order"]
			for row in pending_advance_orders(
				self.filters(from_date=add_days(nowdate(), -5), to_date=nowdate())
			)
		]
		self.assertIn(recent.name, names)
		self.assertNotIn(old.name, names)

	def test_the_supplier_filter_narrows_the_answer(self):
		mine = self.make_po(supplier=SUPPLIER)
		self.pay_advance(mine, amount=100)
		theirs = self.make_po(supplier=OTHER_SUPPLIER)
		self.pay_advance(theirs, amount=100)

		names = [row["purchase_order"] for row in pending_advance_orders(self.filters(supplier=SUPPLIER))]
		self.assertIn(mine.name, names)
		self.assertNotIn(theirs.name, names)

	# ------------------------------------------------------------------
	# the figures on the row
	# ------------------------------------------------------------------

	def test_receipt_state_tracks_the_goods(self):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		po = self.make_po(qty=10, rate=100)
		self.pay_advance(po, amount=500)
		self.assertEqual(self.row_for(po)["received"], "No")

		pr = make_purchase_receipt(po.name)
		pr.items[0].qty = 4
		pr.items[0].received_qty = 4
		pr.insert()
		pr.submit()
		self.assertEqual(self.row_for(po)["received"], "Partial")

		rest = make_purchase_receipt(po.name)
		rest.insert()
		rest.submit()
		self.assertEqual(self.row_for(po)["received"], "Yes")

	def test_balance_and_percentage_are_taken_against_the_company_currency_value(self):
		"""advance_paid is in the party account's currency, grand_total is not.

		An order billed in something other than the company's currency has to be
		compared against its converted value, or a full prepayment reads as a fraction
		of one.
		"""
		order = frappe._dict(
			purchase_order="PO-FX",
			company=COMPANY,
			supplier=SUPPLIER,
			supplier_name=SUPPLIER,
			transaction_date=nowdate(),
			status="To Bill",
			currency="USD",
			base_grand_total=80000.0,
			advance_paid=80000.0,
			per_billed=0.0,
			ordered_qty=10.0,
			received_qty=0.0,
		)

		row = build_row(
			order,
			ledger={"PO-FX": 80000.0},
			drafts=[],
			company_currency="INR",
		)

		self.assertEqual(row["advance_pct"], 100)
		self.assertEqual(row["balance_amount"], 0)
		self.assertEqual(row["base_grand_total"], 80000.0)
		self.assertEqual(row["remarks"], "")

	def test_a_zero_value_order_does_not_divide_by_zero(self):
		order = frappe._dict(
			purchase_order="PO-ZERO",
			company=COMPANY,
			supplier=SUPPLIER,
			supplier_name=SUPPLIER,
			transaction_date=nowdate(),
			status="To Bill",
			currency="INR",
			base_grand_total=0.0,
			advance_paid=50.0,
			per_billed=0.0,
			ordered_qty=1.0,
			received_qty=0.0,
		)

		row = build_row(order, ledger={"PO-ZERO": 50.0}, drafts=[], company_currency="INR")
		self.assertEqual(row["advance_pct"], 0)

	# ------------------------------------------------------------------
	# the field and the ledger disagreeing
	# ------------------------------------------------------------------

	def test_a_stale_stored_advance_is_flagged_not_trusted_silently(self):
		po = self.make_po()
		self.pay_advance(po, amount=300)
		# what a cancelled-and-amended payment leaves behind: the field keeps a figure
		# the advance ledger no longer backs
		po.db_set("advance_paid", 5000)

		row = self.row_for(po)
		self.assertIsNotNone(row)
		self.assertIn("advance ledger holds", row["remarks"])

	def test_an_advance_the_ledger_knows_about_is_reported_even_if_the_field_is_zero(self):
		"""The field is a cache. The ledger is the record, so it decides membership."""
		po = self.make_po()
		self.pay_advance(po, amount=300)
		po.db_set("advance_paid", 0)

		row = self.row_for(po)
		self.assertIsNotNone(row)
		self.assertIn("advance ledger holds", row["remarks"])

	def test_fully_billed_with_nothing_linking_the_invoice_is_flagged(self):
		"""Otherwise such an order sits in the report for good with no way to clear it."""
		po = self.make_po()
		self.pay_advance(po, amount=300)
		po.db_set("per_billed", 100)

		self.assertIn("no purchase invoice names this order", self.row_for(po)["remarks"])

	# ------------------------------------------------------------------
	# permissions
	# ------------------------------------------------------------------

	def test_user_permission_narrows_rows_to_the_permitted_branch(self):
		"""frappe.qb applies no permissions, so the report has to apply them itself."""
		other_cc = frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": "_Test Advance PO Other Branch",
				"parent_cost_center": "All Cost Centers - " + ABBR,
				"company": COMPANY,
				"is_group": 0,
			}
		).insert(ignore_if_duplicate=True)

		mine = self.make_po()
		self.pay_advance(mine, amount=150)
		theirs = self.make_po()
		self.pay_advance(theirs, amount=150)
		frappe.db.set_value("Purchase Order Item", theirs.items[0].name, "cost_center", other_cc.name)

		email = "_test_advance_po_user@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Branch",
					"send_welcome_email": 0,
					"roles": [{"role": "Accounts User"}, {"role": "Purchase User"}],
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists(
			"User Permission",
			{"user": email, "allow": "Cost Center", "for_value": self.cost_center},
		):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": email,
					"allow": "Cost Center",
					"for_value": self.cost_center,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)

		frappe.set_user(email)
		try:
			names = [row["purchase_order"] for row in pending_advance_orders(self.filters())]
			self.assertIn(mine.name, names)
			self.assertNotIn(theirs.name, names)
		finally:
			frappe.set_user("Administrator")

		# an unrestricted user keeps seeing both
		names = [row["purchase_order"] for row in pending_advance_orders(self.filters())]
		self.assertIn(mine.name, names)
		self.assertIn(theirs.name, names)
