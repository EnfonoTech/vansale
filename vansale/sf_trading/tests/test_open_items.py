"""Tests for the open item engine (vansale.sf_trading.open_items).

Run on a scratch site, never on a client site — the suite creates its own
company, warehouse, items and parties:

    bench --site <scratch-site> run-tests --module vansale.sf_trading.tests.test_open_items
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from vansale.sf_trading.open_items import (
	ageing_bucket,
	billed_items_pending_receipt,
	delivered_items_pending_billing,
	invoiced_items_to_be_delivered,
	invoices_pending_delivery,
	received_items_pending_billing,
)
from vansale.sf_trading.tests.test_sdbnb import ABBR, COMPANY, get_test_company

CUSTOMER = "_Test Open Items Customer"
OTHER_CUSTOMER = "_Test Open Items Customer 2"
SUPPLIER = "_Test Open Items Supplier"


class TestOpenItems(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = get_test_company()
		cls.warehouse = "Stores - " + ABBR
		cls.cost_center = "Main - " + ABBR
		cls.item_code = cls.make_stocked_item()
		cls.make_parties()

	@classmethod
	def make_stocked_item(cls):
		from erpnext.stock.doctype.item.test_item import make_item
		from erpnext.stock.doctype.stock_entry.test_stock_entry import make_stock_entry

		item_code = make_item(
			"Open Items Test Item", properties={"is_stock_item": 1, "item_group": "Products"}
		).name
		make_stock_entry(
			item_code=item_code, target=cls.warehouse, qty=500, basic_rate=100, company=COMPANY
		)
		return item_code

	@classmethod
	def make_parties(cls):
		for name in (CUSTOMER, OTHER_CUSTOMER):
			if not frappe.db.exists("Customer", name):
				frappe.get_doc(
					{
						"doctype": "Customer",
						"customer_name": name,
						"customer_group": "All Customer Groups",
						"territory": "All Territories",
					}
				).insert()
		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": SUPPLIER,
					"supplier_group": "All Supplier Groups",
				}
			).insert()

	# ------------------------------------------------------------------
	# document helpers
	# ------------------------------------------------------------------

	def filters(self, **overrides):
		base = {"company": COMPANY, "as_on": nowdate()}
		base.update(overrides)
		return frappe._dict(base)

	def rows_for(self, data, docname):
		return [row for row in data if row.document == docname]

	def make_si(self, qty=5, rate=150, update_stock=0, customer=CUSTOMER, posting_date=None):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": COMPANY,
				"customer": customer,
				"update_stock": update_stock,
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		if posting_date:
			si.set_posting_time = 1
			si.posting_date = posting_date
		si.insert()
		si.submit()
		return si

	def make_dn_from_si(self, si, qty=None):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_delivery_note

		dn = make_delivery_note(si.name)
		if qty is not None:
			dn.items[0].qty = qty
		dn.insert()
		dn.submit()
		return dn

	def make_dn(self, qty=4, rate=150, customer=CUSTOMER):
		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": COMPANY,
				"customer": customer,
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		dn.insert()
		dn.submit()
		return dn

	def make_si_from_dn(self, dn, qty=None):
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

		si = make_sales_invoice(dn.name)
		si.update_stock = 0
		if qty is not None:
			si.items[0].qty = qty
		si.insert()
		si.submit()
		return si

	def make_pr(self, qty=6, rate=90, supplier=SUPPLIER, posting_date=None):
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"company": COMPANY,
				"supplier": supplier,
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		if posting_date:
			pr.set_posting_time = 1
			pr.posting_date = posting_date
		pr.insert()
		pr.submit()
		return pr

	def make_pi_from_pr(self, pr, qty=None):
		from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

		pi = make_purchase_invoice(pr.name)
		if qty is not None:
			pi.items[0].qty = qty
		pi.insert()
		pi.submit()
		return pi

	def make_pi(self, qty=3, rate=90, supplier=SUPPLIER):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": COMPANY,
				"supplier": supplier,
				"update_stock": 0,
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item_code,
						"qty": qty,
						"rate": rate,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		pi.insert()
		pi.submit()
		return pi

	def make_pr_from_pi(self, pi, qty=None):
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_purchase_receipt

		pr = make_purchase_receipt(pi.name)
		if qty is not None:
			pr.items[0].qty = qty
		pr.insert()
		pr.submit()
		return pr

	# ------------------------------------------------------------------
	# sales: invoice first, deliver later
	# ------------------------------------------------------------------

	def test_invoice_stays_open_until_delivered(self):
		si = self.make_si(qty=5)

		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters()), si.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].pending_qty, 5)
		self.assertEqual(rows[0].pending_amount, 750)

		self.make_dn_from_si(si, qty=2)
		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters()), si.name)
		self.assertEqual(rows[0].pending_qty, 3)
		self.assertEqual(rows[0].delivered_qty, 2)

		self.make_dn_from_si(si, qty=3)
		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters()), si.name)
		self.assertEqual(rows, [])

	def test_update_stock_invoice_is_never_open(self):
		si = self.make_si(qty=1, update_stock=1)
		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters()), si.name)
		self.assertEqual(rows, [])

	def test_as_on_uses_counterpart_posting_dates(self):
		yesterday = add_days(nowdate(), -1)
		si = self.make_si(qty=5, posting_date=yesterday)
		self.make_dn_from_si(si, qty=5)

		# fully delivered today, but yesterday the whole invoice was open
		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters(as_on=yesterday)), si.name)
		self.assertEqual(rows[0].pending_qty, 5)
		self.assertEqual(rows[0].age, 0)

		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters()), si.name)
		self.assertEqual(rows, [])

	def test_zero_rate_row_still_shows(self):
		si = self.make_si(qty=2, rate=0)
		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters()), si.name)
		self.assertEqual(rows[0].pending_qty, 2)
		self.assertEqual(rows[0].pending_amount, 0)

	# ------------------------------------------------------------------
	# sales: deliver first, bill later
	# ------------------------------------------------------------------

	def test_delivery_stays_open_until_billed(self):
		dn = self.make_dn(qty=4)

		rows = self.rows_for(delivered_items_pending_billing(self.filters()), dn.name)
		self.assertEqual(rows[0].pending_qty, 4)

		self.make_si_from_dn(dn, qty=1)
		rows = self.rows_for(delivered_items_pending_billing(self.filters()), dn.name)
		self.assertEqual(rows[0].pending_qty, 3)
		self.assertEqual(rows[0].billed_qty, 1)

	def test_delivery_return_reduces_pending(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		dn = self.make_dn(qty=4)
		return_dn = make_return_doc("Delivery Note", dn.name)
		return_dn.items[0].qty = -1
		return_dn.insert()
		return_dn.submit()

		rows = self.rows_for(delivered_items_pending_billing(self.filters()), dn.name)
		self.assertEqual(rows[0].pending_qty, 3)
		self.assertEqual(rows[0].returned_qty, 1)

		# the return itself must never appear as an open item
		self.assertEqual(
			self.rows_for(delivered_items_pending_billing(self.filters()), return_dn.name), []
		)

	# ------------------------------------------------------------------
	# purchase: receive first, bill later
	# ------------------------------------------------------------------

	def test_receipt_stays_open_until_billed(self):
		pr = self.make_pr(qty=6)

		rows = self.rows_for(received_items_pending_billing(self.filters()), pr.name)
		self.assertEqual(rows[0].pending_qty, 6)

		self.make_pi_from_pr(pr)
		rows = self.rows_for(received_items_pending_billing(self.filters()), pr.name)
		self.assertEqual(rows, [])

	def test_receipt_part_billed_shows_only_the_remainder(self):
		"""A receipt billed in part is open for the part still unbilled."""
		pr = self.make_pr(qty=6, rate=90)

		# invoice 2 of the 6 received
		self.make_pi_from_pr(pr, qty=2)
		rows = self.rows_for(received_items_pending_billing(self.filters()), pr.name)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].billed_qty, 2)
		self.assertEqual(rows[0].pending_qty, 4)
		# the value follows the quantity, not the whole line
		self.assertEqual(rows[0].pending_amount, 360)

		# invoice the remaining 4 and it closes
		self.make_pi_from_pr(pr, qty=4)
		self.assertEqual(self.rows_for(received_items_pending_billing(self.filters()), pr.name), [])

	# ------------------------------------------------------------------
	# purchase: bill first, receive later
	# ------------------------------------------------------------------

	def test_bill_stays_open_until_received(self):
		pi = self.make_pi(qty=3)

		rows = self.rows_for(billed_items_pending_receipt(self.filters()), pi.name)
		self.assertEqual(rows[0].pending_qty, 3)

		self.make_pr_from_pi(pi)
		rows = self.rows_for(billed_items_pending_receipt(self.filters()), pi.name)
		self.assertEqual(rows, [])

	# ------------------------------------------------------------------
	# filters and ageing
	# ------------------------------------------------------------------

	def test_row_level_filters(self):
		si = self.make_si(qty=2, customer=OTHER_CUSTOMER)

		report = invoiced_items_to_be_delivered
		self.assertEqual(len(self.rows_for(report(self.filters(party=OTHER_CUSTOMER)), si.name)), 1)
		self.assertEqual(self.rows_for(report(self.filters(party=CUSTOMER)), si.name), [])
		self.assertEqual(
			len(self.rows_for(report(self.filters(warehouse=self.warehouse)), si.name)), 1
		)
		self.assertEqual(
			self.rows_for(report(self.filters(warehouse="Work In Progress - " + ABBR)), si.name), []
		)
		self.assertEqual(
			len(self.rows_for(report(self.filters(item_code=self.item_code)), si.name)), 1
		)
		self.assertEqual(
			len(self.rows_for(report(self.filters(cost_center=self.cost_center)), si.name)), 1
		)

	# ------------------------------------------------------------------
	# invoice-wise pending delivery
	# ------------------------------------------------------------------

	def test_pending_delivery_is_one_row_per_invoice(self):
		si = self.make_si(qty=5)
		rows = [r for r in invoices_pending_delivery(self.filters()) if r.document == si.name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].pending_qty, 5)
		self.assertEqual(rows[0].items_pending, 1)

	def test_pending_delivery_drops_a_fully_credited_invoice(self):
		"""The bug the list view had: a fully returned invoice needs no delivery.

		`is_return = 0` only excludes the credit note itself, never the invoice it
		was raised against, so the list view kept showing these.
		"""
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		si = self.make_si(qty=4)
		credit = make_return_doc("Sales Invoice", si.name)
		credit.items[0].qty = -4
		credit.insert()
		credit.submit()

		docs = [r.document for r in invoices_pending_delivery(self.filters())]
		self.assertNotIn(si.name, docs)
		# and the credit note is never an open item of its own
		self.assertNotIn(credit.name, docs)

	def test_pending_delivery_keeps_the_balance_of_a_part_credited_invoice(self):
		"""20 invoiced, 3 credited, so 17 still have to be delivered."""
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		si = self.make_si(qty=20)
		credit = make_return_doc("Sales Invoice", si.name)
		credit.items[0].qty = -3
		credit.insert()
		credit.submit()

		rows = [r for r in invoices_pending_delivery(self.filters()) if r.document == si.name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].pending_qty, 17)
		self.assertEqual(rows[0].returned_qty, 3)

	def test_pending_delivery_totals_match_the_item_level_report(self):
		"""The summary must never disagree with the detail it is built from."""
		self.make_si(qty=7)
		detail = invoiced_items_to_be_delivered(self.filters())
		summary = invoices_pending_delivery(self.filters())
		self.assertEqual(
			round(sum(r.pending_qty for r in detail), 3),
			round(sum(r.pending_qty for r in summary), 3),
		)
		self.assertEqual(
			round(sum(r.pending_amount for r in detail), 2),
			round(sum(r.pending_amount for r in summary), 2),
		)
		self.assertEqual(len({r.document for r in detail}), len(summary))

	def test_pending_delivery_closes_once_delivered(self):
		si = self.make_si(qty=6)
		self.make_dn_from_si(si)
		docs = [r.document for r in invoices_pending_delivery(self.filters())]
		self.assertNotIn(si.name, docs)

	# ------------------------------------------------------------------
	# user permissions
	# ------------------------------------------------------------------

	def make_restricted_user(self, email, cost_center):
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Branch",
					"send_welcome_email": 0,
					"roles": [{"role": "Accounts User"}, {"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists(
			"User Permission", {"user": email, "allow": "Cost Center", "for_value": cost_center}
		):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": email,
					"allow": "Cost Center",
					"for_value": cost_center,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)
		return email

	def test_user_permission_narrows_rows_to_the_permitted_branch(self):
		"""frappe.qb applies no permissions, so base_rows has to apply them itself."""
		other_cc = frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": "_Test Open Items Other Branch",
				"parent_cost_center": "All Cost Centers - " + ABBR,
				"company": COMPANY,
				"is_group": 0,
			}
		).insert(ignore_if_duplicate=True)

		mine = self.make_si(qty=2)
		theirs = self.make_si(qty=3)
		# move the second invoice's row to a branch the user may not see
		frappe.db.set_value("Sales Invoice Item", theirs.items[0].name, "cost_center", other_cc.name)

		user = self.make_restricted_user("_test_branch_user@example.com", self.cost_center)
		frappe.set_user(user)
		try:
			docs = [row.document for row in invoiced_items_to_be_delivered(self.filters())]
			self.assertIn(mine.name, docs)
			self.assertNotIn(theirs.name, docs)
		finally:
			frappe.set_user("Administrator")

		# unrestricted users keep seeing everything
		docs = [row.document for row in invoiced_items_to_be_delivered(self.filters())]
		self.assertIn(mine.name, docs)
		self.assertIn(theirs.name, docs)

	def test_no_user_permissions_means_no_restriction(self):
		si = self.make_si(qty=1)
		docs = [row.document for row in invoiced_items_to_be_delivered(self.filters())]
		self.assertIn(si.name, docs)

	def test_posting_range_bounds_the_source_document(self):
		old = self.make_pr(qty=1, posting_date=add_days(nowdate(), -40))
		recent = self.make_pr(qty=1, posting_date=add_days(nowdate(), -5))

		window = self.filters(from_date=add_days(nowdate(), -10), to_date=nowdate())
		rows = received_items_pending_billing(window)
		self.assertEqual(self.rows_for(rows, old.name), [])
		self.assertEqual(len(self.rows_for(rows, recent.name)), 1)

		# no window at all means every document, so the number cards keep their totals
		everything = received_items_pending_billing(self.filters())
		self.assertEqual(len(self.rows_for(everything, old.name)), 1)
		self.assertEqual(len(self.rows_for(everything, recent.name)), 1)

	def test_posting_range_applies_to_the_sales_side_too(self):
		"""The window lives in base_rows, so every flow gets it."""
		si = self.make_si(qty=1, posting_date=add_days(nowdate(), -40))
		window = self.filters(from_date=add_days(nowdate(), -10), to_date=nowdate())
		self.assertEqual(self.rows_for(invoiced_items_to_be_delivered(window), si.name), [])

	def test_posting_range_includes_both_ends(self):
		posting = add_days(nowdate(), -7)
		pr = self.make_pr(qty=1, posting_date=posting)
		rows = received_items_pending_billing(self.filters(from_date=posting, to_date=posting))
		self.assertEqual(len(self.rows_for(rows, pr.name)), 1)

	def test_posting_range_does_not_clip_the_invoice_side(self):
		"""A receipt invoiced after the window closed is billed, not open.

		Guards the false positive that bounding both sides would create.
		"""
		posting = add_days(nowdate(), -20)
		pr = self.make_pr(qty=3, posting_date=posting)
		self.make_pi_from_pr(pr)  # invoiced today, outside the window below

		window = self.filters(from_date=add_days(posting, -1), to_date=add_days(posting, 1))
		self.assertEqual(self.rows_for(received_items_pending_billing(window), pr.name), [])

	def test_posting_range_rejects_a_backwards_window(self):
		with self.assertRaises(frappe.ValidationError):
			received_items_pending_billing(
				self.filters(from_date=nowdate(), to_date=add_days(nowdate(), -1))
			)

	def test_ageing_buckets(self):
		ranges = [30, 60, 90]
		self.assertEqual(ageing_bucket(0, ranges), "0-30")
		self.assertEqual(ageing_bucket(30, ranges), "0-30")
		self.assertEqual(ageing_bucket(31, ranges), "31-60")
		self.assertEqual(ageing_bucket(90, ranges), "61-90")
		self.assertTrue(ageing_bucket(91, ranges).startswith("91-"))

	def test_age_and_bucket_on_rows(self):
		posting = add_days(nowdate(), -45)
		si = self.make_si(qty=1, posting_date=posting)

		rows = self.rows_for(invoiced_items_to_be_delivered(self.filters()), si.name)
		self.assertEqual(rows[0].age, 45)
		self.assertEqual(rows[0].bucket, "31-60")

	# ------------------------------------------------------------------
	# party-wise summaries
	# ------------------------------------------------------------------

	def summary_row(self, data, party):
		rows = [row for row in data if row.party == party]
		return rows[0] if rows else None

	def test_customer_summary_reconciles_with_detail(self):
		from vansale.sf_trading.open_items import customer_open_items_summary

		si = self.make_si(qty=5)          # bill-first: 750 to deliver
		dn = self.make_dn(qty=4)          # deliver-first
		self.make_si_from_dn(dn, qty=1)   # 3 qty / 450 left unbilled

		filters = self.filters()
		detail_1 = invoiced_items_to_be_delivered(filters)
		detail_2 = delivered_items_pending_billing(filters)
		to_deliver = sum(r.pending_amount for r in detail_1 if r.party == CUSTOMER)
		unbilled = sum(r.pending_amount for r in detail_2 if r.party == CUSTOMER)

		row = self.summary_row(customer_open_items_summary(filters), CUSTOMER)
		self.assertIsNotNone(row)
		self.assertAlmostEqual(row.to_deliver_value, to_deliver, places=2)
		self.assertAlmostEqual(row.unbilled_delivery_value, unbilled, places=2)
		self.assertAlmostEqual(row.total_value, to_deliver + unbilled, places=2)

		detail_rows = [r for r in detail_1 + detail_2 if r.party == CUSTOMER]
		self.assertEqual(row.open_items, len(detail_rows))
		self.assertEqual(row.open_docs, len({r.document for r in detail_rows}))
		self.assertEqual(row.oldest, max(r.age for r in detail_rows))

		bucket_sum = sum(row.get(f"range{i}") or 0 for i in range(1, 6))
		self.assertAlmostEqual(bucket_sum, row.total_value, places=2)

	def test_supplier_summary_reconciles_with_detail(self):
		from vansale.sf_trading.open_items import supplier_open_items_summary

		pr = self.make_pr(qty=6)
		self.make_pi_from_pr(pr, qty=2)   # 4 qty left unbilled
		self.make_pi(qty=3)               # bill-first: 3 qty to receive

		filters = self.filters()
		unbilled = sum(
			r.pending_amount for r in received_items_pending_billing(filters) if r.party == SUPPLIER
		)
		to_receive = sum(
			r.pending_amount for r in billed_items_pending_receipt(filters) if r.party == SUPPLIER
		)

		row = self.summary_row(supplier_open_items_summary(filters), SUPPLIER)
		self.assertIsNotNone(row)
		self.assertAlmostEqual(row.unbilled_receipt_value, unbilled, places=2)
		self.assertAlmostEqual(row.pending_receipt_value, to_receive, places=2)
		self.assertAlmostEqual(row.total_value, unbilled + to_receive, places=2)

	def test_summary_party_group_filter(self):
		from vansale.sf_trading.open_items import customer_open_items_summary

		self.make_si(qty=1)
		group = frappe.db.get_value("Customer", CUSTOMER, "customer_group")

		matching = customer_open_items_summary(self.filters(party_group=group))
		self.assertIsNotNone(self.summary_row(matching, CUSTOMER))

		other_group = frappe.get_all(
			"Customer Group", filters={"name": ["!=", group], "is_group": 0}, limit=1, pluck="name"
		)
		if other_group:
			non_matching = customer_open_items_summary(self.filters(party_group=other_group[0]))
			self.assertIsNone(self.summary_row(non_matching, CUSTOMER))

	# ------------------------------------------------------------------
	# period closing gate
	# ------------------------------------------------------------------

	def arm_gate(self, on=1):
		from vansale.sf_trading.period_closing import ENFORCE_FIELD

		frappe.db.set_value("Company", COMPANY, ENFORCE_FIELD, on)
		frappe.clear_cache(doctype="Company")

	def test_period_closing_gate_is_off_by_default(self):
		from vansale.sf_trading.period_closing import ensure_custom_fields, validate_open_items

		ensure_custom_fields()
		self.arm_gate(0)
		self.make_si(qty=2)

		# open items exist, but this company never asked for them to block
		validate_open_items(frappe._dict(company=COMPANY, period_end_date=nowdate()))

	def test_period_closing_gate(self):
		from vansale.sf_trading.period_closing import (
			ensure_custom_fields,
			pending_open_items,
			validate_open_items,
		)

		ensure_custom_fields()
		self.arm_gate(1)
		si = self.make_si(qty=2)

		voucher = frappe._dict(company=COMPANY, period_end_date=nowdate())
		with self.assertRaises(frappe.ValidationError):
			validate_open_items(voucher)

		result = pending_open_items(COMPANY, nowdate())
		self.assertTrue(result["enforced"])
		census = {row["report"]: row for row in result["rows"]}
		self.assertGreaterEqual(census["Invoiced Items To Be Delivered"]["items"], 1)

		# clearing today unblocks the period even though the delivery is
		# dated after items created earlier in it
		self.make_dn_from_si(si)
		remaining = [
			row
			for row in pending_open_items(COMPANY, nowdate())["rows"]
			if row["items"] and row["report"] == "Invoiced Items To Be Delivered"
		]
		before = census["Invoiced Items To Be Delivered"]["items"]
		after = remaining[0]["items"] if remaining else 0
		self.assertEqual(after, before - 1)

		self.arm_gate(0)

	def test_period_closing_ignores_items_after_period_end(self):
		from vansale.sf_trading.period_closing import pending_open_items

		yesterday = add_days(nowdate(), -1)
		baseline = {
			row["report"]: row["items"] for row in pending_open_items(COMPANY, yesterday)["rows"]
		}
		self.make_si(qty=1)  # dated today — outside a period ending yesterday
		census = {
			row["report"]: row["items"] for row in pending_open_items(COMPANY, yesterday)["rows"]
		}
		self.assertEqual(census, baseline)

	# ------------------------------------------------------------------
	# Purchase Register Extended
	# ------------------------------------------------------------------

	def run_register(self, **overrides):
		from vansale.sf_trading.report.purchase_register_extended.purchase_register_extended import (
			execute,
		)

		filters = frappe._dict(
			{
				"company": COMPANY,
				"from_date": add_days(nowdate(), -5),
				"to_date": nowdate(),
				"include_unbilled_receipts": 1,
			}
		)
		filters.update(overrides)
		_columns, rows = execute(filters)
		return rows

	def register_row(self, rows, voucher_no):
		found = [row for row in rows if row["voucher_no"] == voucher_no]
		return found[0] if found else None

	def test_register_adds_only_the_unbilled_part_of_a_receipt(self):
		pr = self.make_pr(qty=6, rate=90)          # 540 received
		self.make_pi_from_pr(pr, qty=2)            # 180 billed

		rows = self.run_register()
		receipt = self.register_row(rows, pr.name)
		self.assertIsNotNone(receipt, "a partly billed receipt must appear")
		self.assertEqual(receipt["voucher_type"], "Purchase Receipt")
		# only the remainder, never the whole receipt
		self.assertAlmostEqual(receipt["net_amount"], 360, places=2)
		self.assertAlmostEqual(receipt["pending_qty"], 4, places=3)

		# and the invoice carries the billed part on its own line
		invoices = [r for r in rows if r["voucher_type"] == "Purchase Invoice"]
		self.assertTrue(invoices)

	def test_register_drops_a_fully_billed_receipt(self):
		pr = self.make_pr(qty=6, rate=90)
		self.make_pi_from_pr(pr)                   # billed in full

		rows = self.run_register()
		self.assertIsNone(self.register_row(rows, pr.name))

	def test_register_never_lists_a_voucher_twice(self):
		pr = self.make_pr(qty=4, rate=50)
		self.make_pi_from_pr(pr, qty=1)

		rows = self.run_register()
		keys = [(row["voucher_type"], row["voucher_no"]) for row in rows]
		self.assertEqual(len(keys), len(set(keys)))

	def test_register_keeps_a_receipt_invoiced_after_the_period_end(self):
		"""The whole point of measuring as of the period end rather than today."""
		pr = self.make_pr(qty=3, rate=100)
		yesterday = add_days(nowdate(), -1)
		frappe.db.set_value("Purchase Receipt", pr.name, "posting_date", yesterday)

		# invoiced today, i.e. after a period that closed yesterday
		self.make_pi_from_pr(pr)

		rows = self.run_register(from_date=add_days(nowdate(), -5), to_date=yesterday)
		receipt = self.register_row(rows, pr.name)
		self.assertIsNotNone(receipt, "a receipt unbilled at period end must stay in the period")
		self.assertAlmostEqual(receipt["net_amount"], 300, places=2)

		# and once the period includes the invoice, the receipt drops out
		rows_today = self.run_register()
		self.assertIsNone(self.register_row(rows_today, pr.name))

	def test_register_can_exclude_receipts_entirely(self):
		pr = self.make_pr(qty=2, rate=75)
		rows = self.run_register(include_unbilled_receipts=0)
		self.assertIsNone(self.register_row(rows, pr.name))
		self.assertFalse([r for r in rows if r["voucher_type"] == "Purchase Receipt"])

	def test_register_scope_select_switches_the_sides(self):
		pr = self.make_pr(qty=3, rate=40)
		self.make_pi(qty=1, rate=40)

		invoices_only = self.run_register(scope="Invoices Only")
		self.assertFalse([r for r in invoices_only if r["voucher_type"] == "Purchase Receipt"])

		receipts_only = self.run_register(scope="Unbilled Receipts Only")
		self.assertFalse([r for r in receipts_only if r["voucher_type"] == "Purchase Invoice"])
		self.assertIsNotNone(self.register_row(receipts_only, pr.name))

		both = self.run_register(scope="Invoices and Unbilled Receipts")
		self.assertTrue([r for r in both if r["voucher_type"] == "Purchase Invoice"])
		self.assertTrue([r for r in both if r["voucher_type"] == "Purchase Receipt"])

	def test_register_shows_an_unbilled_return_as_a_reduction(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		pr = self.make_pr(qty=5, rate=60)          # 300 received
		return_pr = make_return_doc("Purchase Receipt", pr.name)
		return_pr.items[0].qty = -2                # 120 sent back
		return_pr.insert()
		return_pr.submit()

		rows = self.run_register()
		back = self.register_row(rows, return_pr.name)
		self.assertIsNotNone(back, "a return with no debit note must show as its own line")
		self.assertEqual(back["status"], "Unbilled Purchase Return")
		self.assertLess(back["net_amount"], 0)
		self.assertAlmostEqual(back["net_amount"], -120, places=2)

		# the receipt keeps its full unbilled value; the return does the reducing,
		# so the two together are the 180 actually purchased
		receipt = self.register_row(rows, pr.name)
		self.assertAlmostEqual(receipt["net_amount"], 300, places=2)
		self.assertAlmostEqual(receipt["net_amount"] + back["net_amount"], 180, places=2)

	def test_register_reports_a_foreign_currency_receipt_in_company_currency(self):
		pr = frappe.get_doc(
			{
				"doctype": "Purchase Receipt",
				"company": COMPANY,
				"supplier": SUPPLIER,
				"currency": "USD",
				"conversion_rate": 80,
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 2,
						"rate": 10,          # 20 USD -> 1600 company currency
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		pr.insert()
		pr.submit()

		row = self.register_row(self.run_register(), pr.name)
		self.assertIsNotNone(row)
		self.assertAlmostEqual(row["net_amount"], 1600, places=2)

	def test_register_item_type_filters_both_halves(self):
		from erpnext.stock.doctype.item.test_item import make_item

		service = make_item("Open Items Service Item", properties={"is_stock_item": 0}).name

		# a service-only bill, and a receipt line for the same service
		si = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": COMPANY,
				"supplier": SUPPLIER,
				"update_stock": 0,
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": service,
						"qty": 1,
						"rate": 90,
						"cost_center": self.cost_center,
						"expense_account": frappe.db.get_value(
							"Company", COMPANY, "default_expense_account"
						),
					}
				],
			}
		)
		si.insert()
		si.submit()

		# default is goods only: the service bill is not a purchase for the
		# trading account and must not be listed
		goods = self.run_register()
		self.assertIsNone(self.register_row(goods, si.name))

		# widening includes it, and both halves widen together
		everything = self.run_register(item_type="All Items")
		self.assertIsNotNone(self.register_row(everything, si.name))
		self.assertGreaterEqual(
			sum(row["net_amount"] for row in everything),
			sum(row["net_amount"] for row in goods),
		)

	def test_register_keeps_disabled_items(self):
		"""Disabling an item stops new transactions; it does not un-purchase old ones."""
		pr = self.make_pr(qty=2, rate=55)
		frappe.db.set_value("Item", self.item_code, "disabled", 1)
		frappe.clear_cache(doctype="Item")
		try:
			row = self.register_row(self.run_register(), pr.name)
			self.assertIsNotNone(row, "a receipt of a now-disabled item is still a purchase")
			self.assertAlmostEqual(row["net_amount"], 110, places=2)
		finally:
			frappe.db.set_value("Item", self.item_code, "disabled", 0)
			frappe.clear_cache(doctype="Item")

	def make_landed_cost(self, receipt, amount):
		lcv = frappe.get_doc(
			{
				"doctype": "Landed Cost Voucher",
				"company": COMPANY,
				"distribute_charges_based_on": "Amount",
				"purchase_receipts": [
					{
						"receipt_document_type": "Purchase Receipt",
						"receipt_document": receipt.name,
						"supplier": receipt.supplier,
						"grand_total": receipt.grand_total,
					}
				],
				"taxes": [
					{
						"expense_account": frappe.db.get_value(
							"Company", COMPANY, "default_expense_account"
						),
						"description": "Freight",
						"amount": amount,
					}
				],
			}
		)
		lcv.get_items_from_purchase_receipts()
		lcv.insert()
		lcv.submit()
		return lcv

	def test_landed_cost_follows_the_goods_onto_the_invoice(self):
		pr = self.make_pr(qty=5, rate=100)
		lcv = self.make_landed_cost(pr, 250)

		# unbilled: the receipt carries the whole charge
		receipt_row = self.register_row(self.run_register(), pr.name)
		self.assertAlmostEqual(receipt_row["landed_cost_amount"], 250, places=2)
		self.assertIn(lcv.name, receipt_row["landed_cost_voucher"])

		# billed in full: the receipt is gone and the invoice carries it instead
		pi = self.make_pi_from_pr(pr)
		rows = self.run_register()
		self.assertIsNone(self.register_row(rows, pr.name))
		invoice_row = self.register_row(rows, pi.name)
		self.assertIsNotNone(invoice_row)
		self.assertAlmostEqual(invoice_row["landed_cost_amount"], 250, places=2)
		self.assertAlmostEqual(
			invoice_row["total_with_landed_cost"],
			invoice_row["total_amount"] + 250,
			places=2,
		)

	def test_landed_cost_splits_across_a_part_billed_receipt(self):
		pr = self.make_pr(qty=10, rate=10)
		lcv = self.make_landed_cost(pr, 200)
		self.make_pi_from_pr(pr, qty=4)              # 40 per cent billed

		rows = self.run_register()
		allocated = sum(
			row["landed_cost_amount"]
			for row in rows
			if lcv.name in (row["landed_cost_voucher"] or "")
		)
		# the halves add back to the voucher: neither side is charged twice
		self.assertAlmostEqual(allocated, 200, places=1)
		self.assertAlmostEqual(self.register_row(rows, pr.name)["landed_cost_amount"], 120, places=1)
