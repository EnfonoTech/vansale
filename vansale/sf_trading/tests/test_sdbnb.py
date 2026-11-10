"""Tests for the Stock Delivered But Not Billed backport (vansale.sf_trading.sdbnb).

Run on a scratch site, never on a client site — the suite creates its own
company, warehouse and items:

    bench --site <scratch-site> run-tests --module vansale.sf_trading.tests.test_sdbnb
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.sdbnb import (
	ACCOUNT_FIELD,
	DISABLE_IN_SR_FIELD,
	ENABLE_FIELD,
	SDBNB_ACCOUNT_TYPE,
	create_sdbnb_account,
	setup_sdbnb,
)

COMPANY = "_Test SDBNB Company"
ABBR = "_TSDBNB"


def get_test_company():
	if frappe.db.exists("Company", COMPANY):
		return frappe.get_doc("Company", COMPANY)

	return frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": COMPANY,
			"abbr": ABBR,
			"country": "India",
			"default_currency": "INR",
			"enable_perpetual_inventory": 1,
		}
	).insert()


def enable_sdbnb(company):
	account = create_sdbnb_account(company.name)
	company.db_set(ENABLE_FIELD, 1)
	company.db_set(ACCOUNT_FIELD, account)
	frappe.clear_cache(doctype="Company")
	return account


class TestSDBNB(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		setup_sdbnb()
		cls.company = get_test_company()
		cls.sdbnb_account = enable_sdbnb(cls.company)
		cls.warehouse = "Stores - " + ABBR
		cls.cost_center = "Main - " + ABBR
		cls.item_code = cls.make_stocked_item()

	@classmethod
	def make_stocked_item(cls):
		from erpnext.stock.doctype.item.test_item import make_item
		from erpnext.stock.doctype.stock_entry.test_stock_entry import make_stock_entry

		item_code = make_item("SDBNB Test Item", properties={"is_stock_item": 1}).name

		make_stock_entry(
			item_code=item_code,
			target=cls.warehouse,
			qty=50,
			basic_rate=100,
			company=COMPANY,
		)
		return item_code

	def make_delivery_note(self, qty=5, rate=150):
		from erpnext.stock.doctype.delivery_note.test_delivery_note import create_delivery_note

		return create_delivery_note(
			item_code=self.item_code,
			qty=qty,
			rate=rate,
			company=COMPANY,
			warehouse=self.warehouse,
			cost_center=self.cost_center,
		)

	def test_account_type_option_is_available(self):
		options = frappe.get_meta("Account").get_field("account_type").options.split("\n")
		self.assertIn(SDBNB_ACCOUNT_TYPE, options)

	def test_enabling_without_account_throws(self):
		company = frappe.get_doc("Company", COMPANY)
		company.set(ACCOUNT_FIELD, None)
		company.set(ENABLE_FIELD, 1)

		with self.assertRaises(frappe.ValidationError):
			company.save()

		frappe.db.rollback()

	def test_delivery_note_books_cost_to_sdbnb(self):
		dn = self.make_delivery_note()

		self.assertEqual(dn.items[0].expense_account, self.sdbnb_account)

		debit = frappe.db.get_value(
			"GL Entry",
			{"voucher_no": dn.name, "account": self.sdbnb_account, "is_cancelled": 0},
			"sum(debit)",
		)
		self.assertGreater(debit, 0)

	def test_sales_invoice_moves_sdbnb_to_cogs(self):
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

		dn = self.make_delivery_note()

		si = make_sales_invoice(dn.name)
		si.insert()
		si.submit()

		gl_entries = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": si.name, "is_cancelled": 0},
			fields=["account", "debit", "credit"],
		)

		sdbnb_credit = sum(row.credit for row in gl_entries if row.account == self.sdbnb_account)
		cogs_debit = sum(
			row.debit
			for row in gl_entries
			if frappe.db.get_value("Account", row.account, "account_type") == "Cost of Goods Sold"
		)

		self.assertGreater(sdbnb_credit, 0)
		self.assertAlmostEqual(sdbnb_credit, cogs_debit, places=2)

	def test_cannot_disable_with_outstanding_delivery_note(self):
		self.make_delivery_note()

		company = frappe.get_doc("Company", COMPANY)
		company.set(ENABLE_FIELD, 0)

		with self.assertRaises(frappe.ValidationError):
			company.save()

		frappe.db.rollback()

	def test_disabled_company_keeps_default_expense_account(self):
		company = frappe.get_doc("Company", COMPANY)
		company.db_set(ENABLE_FIELD, 0)
		frappe.clear_cache(doctype="Company")

		try:
			dn = self.make_delivery_note(qty=1)
			self.assertNotEqual(dn.items[0].expense_account, self.sdbnb_account)
		finally:
			company.db_set(ENABLE_FIELD, 1)
			frappe.clear_cache(doctype="Company")

	def test_sales_return_respects_disable_flag(self):
		company = frappe.get_doc("Company", COMPANY)
		company.db_set(DISABLE_IN_SR_FIELD, 1)
		frappe.clear_cache(doctype="Company")

		try:
			dn = self.make_delivery_note(qty=2)
			self.assertEqual(dn.items[0].expense_account, self.sdbnb_account)
		finally:
			company.db_set(DISABLE_IN_SR_FIELD, 0)
			frappe.clear_cache(doctype="Company")
