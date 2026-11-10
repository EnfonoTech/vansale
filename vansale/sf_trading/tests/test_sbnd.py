"""Tests for Stock Billed But Not Delivered (vansale.sf_trading.sbnd).

Run on a scratch site, never on a client site:

    bench --site <scratch-site> run-tests --module vansale.sf_trading.tests.test_sbnd
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.sbnd import (
	ACCOUNT_FIELD,
	ENABLE_FIELD,
	RATE_FIELD,
	SBND_ACCOUNT_TYPE,
	create_sbnd_account,
)
from vansale.sf_trading.stock_billing_setup import setup
from vansale.sf_trading.tests.test_sdbnb import ABBR, COMPANY, get_test_company

class TestSBND(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		setup()
		cls.company = get_test_company()
		cls.account = create_sbnd_account(COMPANY)
		cls.company.db_set(ENABLE_FIELD, 1)
		cls.company.db_set(ACCOUNT_FIELD, cls.account)
		frappe.clear_cache(doctype="Company")
		cls.warehouse = "Stores - " + ABBR
		cls.cost_center = "Main - " + ABBR
		cls.item_code = cls.make_stocked_item()

	@classmethod
	def make_stocked_item(cls):
		from erpnext.stock.doctype.item.test_item import make_item
		from erpnext.stock.doctype.stock_entry.test_stock_entry import make_stock_entry

		item_code = make_item("SBND Test Item", properties={"is_stock_item": 1}).name
		make_stock_entry(
			item_code=item_code, target=cls.warehouse, qty=50, basic_rate=100, company=COMPANY
		)
		return item_code

	def make_invoice(self, qty=5, rate=150):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": COMPANY,
				"customer": "_Test Customer",
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
		si.insert()
		si.submit()
		return si

	def test_account_type_option_is_available(self):
		options = frappe.get_meta("Account").get_field("account_type").options.split("\n")
		self.assertIn(SBND_ACCOUNT_TYPE, options)

	def test_invoice_freezes_rate_and_credits_sbnd(self):
		si = self.make_invoice()

		self.assertGreater(si.items[0].get(RATE_FIELD), 0)

		entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": si.name, "is_cancelled": 0},
			fields=["account", "debit", "credit"],
		)
		sbnd_credit = sum(row.credit for row in entries if row.account == self.account)
		self.assertAlmostEqual(sbnd_credit, si.items[0].get(RATE_FIELD) * si.items[0].stock_qty, places=2)

	def test_delivery_clears_sbnd_to_zero(self):
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_delivery_note

		si = self.make_invoice()
		dn = make_delivery_note(si.name)
		dn.insert()
		dn.submit()

		self.assertEqual(dn.items[0].expense_account, self.account)

		balance = frappe.db.sql(
			"""select round(ifnull(sum(debit - credit), 0), 6) from `tabGL Entry`
			   where account = %s and voucher_no in (%s, %s) and is_cancelled = 0""",
			(self.account, si.name, dn.name),
		)[0][0]
		self.assertAlmostEqual(balance, 0, places=6)

	def test_update_stock_invoice_is_left_alone(self):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": COMPANY,
				"customer": "_Test Customer",
				"update_stock": 1,
				"cost_center": self.cost_center,
				"items": [
					{
						"item_code": self.item_code,
						"qty": 1,
						"rate": 150,
						"warehouse": self.warehouse,
						"cost_center": self.cost_center,
					}
				],
			}
		)
		si.insert()
		si.submit()

		self.assertFalse(si.items[0].get(RATE_FIELD))
		self.assertFalse(
			frappe.db.exists("GL Entry", {"voucher_no": si.name, "account": self.account, "is_cancelled": 0})
		)

	def test_zero_valuation_row_blocks_save_until_acknowledged(self):
		from erpnext.stock.doctype.item.test_item import make_item

		unvalued = make_item("SBND Unvalued Item", properties={"is_stock_item": 1}).name

		def build(allow_zero):
			return frappe.get_doc(
				{
					"doctype": "Sales Invoice",
					"company": COMPANY,
					"customer": "_Test Customer",
					"update_stock": 0,
					"cost_center": self.cost_center,
					"items": [
						{
							"item_code": unvalued,
							"qty": 1,
							"rate": 10,
							"warehouse": self.warehouse,
							"cost_center": self.cost_center,
							"allow_zero_valuation_rate": allow_zero,
						}
					],
				}
			)

		# no valuation anywhere and the row does not own up to it — refuse the save
		with self.assertRaises(frappe.ValidationError):
			build(0).insert()

		# ticking core's own checkbox is the acknowledgement, and the save goes through
		si = build(1)
		si.insert()
		self.assertFalse(si.items[0].get(RATE_FIELD))

		frappe.db.rollback()

	def test_enabling_without_account_throws(self):
		company = frappe.get_doc("Company", COMPANY)
		company.set(ACCOUNT_FIELD, None)
		company.set(ENABLE_FIELD, 1)

		with self.assertRaises(frappe.ValidationError):
			company.save()

		frappe.db.rollback()
