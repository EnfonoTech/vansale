"""Tests for the header expense account on a Material Issue.

    bench --site <scratch-site> run-tests --module vansale.sf_trading.tests.test_stock_entry_expense
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.stock_entry_expense import HEADER_FIELD, MATERIAL_ISSUE, apply_expense_account


def make_doc(purpose, header_account, row_accounts):
	doc = frappe._dict(
		{
			"purpose": purpose,
			HEADER_FIELD: header_account,
			"items": [frappe._dict({"expense_account": account}) for account in row_accounts],
		}
	)
	doc.get = lambda key, default=None: doc.__dict__.get(key, default)
	return doc


class TestStockEntryExpenseAccount(FrappeTestCase):
	def test_header_account_reaches_every_row(self):
		doc = make_doc(MATERIAL_ISSUE, "Write Off - X", [None, "Something Else - X", None])
		apply_expense_account(doc)
		self.assertEqual(
			[row.expense_account for row in doc["items"]],
			["Write Off - X"] * 3,
			"one account on the header must settle every row, including one already filled",
		)

	def test_blank_header_leaves_the_rows_alone(self):
		doc = make_doc(MATERIAL_ISSUE, None, ["Kept - X", None])
		apply_expense_account(doc)
		self.assertEqual([row.expense_account for row in doc["items"]], ["Kept - X", None])

	def test_other_purposes_are_untouched(self):
		# a transfer keeps stock in stock, and manufacture derives its accounts elsewhere;
		# overwriting either would be wrong
		for purpose in ("Material Transfer", "Manufacture", "Material Receipt", "Repack"):
			doc = make_doc(purpose, "Write Off - X", ["Original - X", None])
			apply_expense_account(doc)
			self.assertEqual(
				[row.expense_account for row in doc["items"]],
				["Original - X", None],
				f"{purpose} must not be rewritten",
			)

	def test_entry_with_no_rows_does_not_raise(self):
		doc = make_doc(MATERIAL_ISSUE, "Write Off - X", [])
		apply_expense_account(doc)   # must simply do nothing

	def test_field_is_provisioned_and_scoped_to_material_issue(self):
		from vansale.sf_trading.stock_entry_expense import ensure_custom_fields

		ensure_custom_fields()
		frappe.clear_cache(doctype="Stock Entry")
		meta = frappe.get_meta("Stock Entry")
		self.assertTrue(meta.has_field(HEADER_FIELD))
		field = meta.get_field(HEADER_FIELD)
		self.assertEqual(field.fieldtype, "Link")
		self.assertEqual(field.options, "Account")
		self.assertIn(MATERIAL_ISSUE, field.depends_on or "")
