"""Tests for the selling price floor (vansale.sf_trading.api.selling_price_validation).

Focused on the thing that is easy to get wrong and invisible when wrong: three
different currencies meet in this calculation, and the figure is compared against
a rate held in a fourth place.

    Item.last_purchase_rate / Bin.valuation_rate -> COMPANY currency
    Item Price.price_list_rate                   -> PRICE LIST currency
    Sales Invoice Item.rate                      -> TRANSACTION currency
    Sales Invoice Item.base_net_rate             -> COMPANY currency

Run on a scratch site, never on a client site:

    bench --site <scratch-site> run-tests --module vansale.sf_trading.tests.test_selling_price
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from vansale.sf_trading.api.selling_price_validation import get_min_selling_price

ENFORCING_PRICE_LIST = "_Test SP Enforcing SAR"
PLAIN_PRICE_LIST = "_Test SP Plain"


class TestSellingPriceFloor(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.item_code = cls.make_item()
		cls.make_price_lists()

	@classmethod
	def make_item(cls):
		from erpnext.stock.doctype.item.test_item import make_item

		# last_purchase_rate is company currency per stock UOM
		item = make_item("_Test SP Item", properties={"is_stock_item": 1})
		frappe.db.set_value("Item", item.name, "last_purchase_rate", 10.0)
		return item.name

	@classmethod
	def make_price_lists(cls):
		for name, currency, enforce in (
			(ENFORCING_PRICE_LIST, "SAR", 1),
			(PLAIN_PRICE_LIST, "SAR", 0),
		):
			if not frappe.db.exists("Price List", name):
				frappe.get_doc(
					{
						"doctype": "Price List",
						"price_list_name": name,
						"selling": 1,
						"currency": currency,
						"enabled": 1,
					}
				).insert()
			frappe.db.set_value("Price List", name, "custom_enforce_min_price", enforce)
			if not frappe.db.exists("Item Price", {"item_code": cls.item_code, "price_list": name}):
				frappe.get_doc(
					{
						"doctype": "Item Price",
						"item_code": cls.item_code,
						"price_list": name,
						"selling": 1,
						"price_list_rate": 100.0,
					}
				).insert()

	# ------------------------------------------------------------------
	# cost + margin branch
	# ------------------------------------------------------------------

	def test_cost_floor_is_company_currency_when_rates_match(self):
		res = get_min_selling_price(self.item_code, conversion_rate=1.0)
		self.assertAlmostEqual(res["min_price"], 10.0, places=4)

	def test_cost_floor_converts_company_to_transaction_currency(self):
		"""A transaction billed in a currency worth 0.1 of the company's must see a
		floor ten times larger in its own units, not the raw company figure."""
		res = get_min_selling_price(self.item_code, conversion_rate=0.1)
		self.assertAlmostEqual(res["min_price"], 100.0, places=4)

	def test_cost_floor_scales_with_uom_conversion_factor(self):
		res = get_min_selling_price(self.item_code, conversion_rate=1.0, uom_cf=12)
		self.assertAlmostEqual(res["min_price"], 120.0, places=4)

	# ------------------------------------------------------------------
	# price list branch — the currency gap this test file exists for
	# ------------------------------------------------------------------

	def test_price_list_floor_converts_price_list_currency_to_company(self):
		"""Item Price is in the price list's currency, so it has to be taken to
		company currency before it can stand next to a company-currency rate."""
		res = get_min_selling_price(
			self.item_code, price_list=ENFORCING_PRICE_LIST,
			conversion_rate=1.0, plc_conversion_rate=0.1,
		)
		# 100 SAR at 0.1 = 10 in company currency, and the transaction is in company
		# currency, so 10 is what the row rate is measured against.
		self.assertAlmostEqual(res["min_price"], 10.0, places=4)

	def test_price_list_floor_round_trips_to_its_own_currency(self):
		"""Billing in the same currency as the price list must give the price list
		rate straight back — the two conversions have to cancel."""
		res = get_min_selling_price(
			self.item_code, price_list=ENFORCING_PRICE_LIST,
			conversion_rate=0.1, plc_conversion_rate=0.1,
		)
		self.assertAlmostEqual(res["min_price"], 100.0, places=4)

	def test_price_list_branch_replaces_the_cost_check(self):
		"""An enforcing price list is the whole answer, so a cost far above it must
		not leak through."""
		frappe.db.set_value("Item", self.item_code, "last_purchase_rate", 9999.0)
		try:
			res = get_min_selling_price(
				self.item_code, price_list=ENFORCING_PRICE_LIST,
				conversion_rate=1.0, plc_conversion_rate=1.0,
			)
			self.assertAlmostEqual(res["min_price"], 100.0, places=4)
		finally:
			frappe.db.set_value("Item", self.item_code, "last_purchase_rate", 10.0)

	def test_non_enforcing_price_list_falls_back_to_cost(self):
		res = get_min_selling_price(
			self.item_code, price_list=PLAIN_PRICE_LIST,
			conversion_rate=1.0, plc_conversion_rate=1.0,
		)
		self.assertAlmostEqual(res["min_price"], 10.0, places=4)

	# ------------------------------------------------------------------
	# degenerate inputs
	# ------------------------------------------------------------------

	def test_zero_rates_do_not_divide_by_zero(self):
		for kwargs in ({"conversion_rate": 0}, {"plc_conversion_rate": 0}, {"uom_cf": 0}):
			res = get_min_selling_price(self.item_code, price_list=ENFORCING_PRICE_LIST, **kwargs)
			self.assertGreaterEqual(res["min_price"], 0)

	def test_item_with_no_cost_and_no_price_has_no_floor(self):
		from erpnext.stock.doctype.item.test_item import make_item

		bare = make_item("_Test SP Item No Cost", properties={"is_stock_item": 1}).name
		frappe.db.set_value("Item", bare, "last_purchase_rate", 0)
		self.assertEqual(get_min_selling_price(bare)["min_price"], 0.0)
