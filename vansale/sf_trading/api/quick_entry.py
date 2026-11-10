import re

import frappe
from frappe import _


def _natural_sort_key(row):
	"""Sort key that treats decimal numbers inside strings numerically.

	e.g. 'GI PIPE 1"' < 'GI PIPE 1.25"' < 'GI PIPE 2"' instead of
	lexicographic order which puts 1.25 before 1 due to '.' < '"'.
	"""
	s = str(row.get("item_name") or "")
	# \d+\.?\d*  → normal numbers with optional decimal  e.g. "1", "1.25", "2.6"
	# \.\d+      → leading-decimal numbers              e.g. ".50", ".75"
	parts = re.split(r"(\d+\.?\d*|\.\d+)", s)
	result = []
	for part in parts:
		try:
			result.append(float(part))
		except ValueError:
			result.append(part.lower())
	return result


@frappe.whitelist()
def get_items_with_stock(company=None, price_list=None, warehouse=None, item_code=None, limit=500):
	"""
	Return all sales items for the company, with their stock qty for the given
	warehouse (0 when no Bin entry exists). Items are always shown regardless of
	stock level. ORDER BY item_name to match the standard item search order.
	"""
	if not company:
		company = frappe.defaults.get_user_default("company")
	if not company:
		return []

	limit = frappe.utils.cint(limit) or 500

	params = {"company": company, "limit": limit}

	# Bin LEFT JOIN — only for the specific warehouse passed from the form
	if warehouse:
		params["warehouse"] = warehouse
		bin_join = "LEFT JOIN `tabBin` bin ON bin.item_code = item.name AND bin.warehouse = %(warehouse)s"
		stock_select = "COALESCE(bin.actual_qty, 0) AS stock_qty, %(warehouse)s AS warehouse"
	else:
		bin_join = ""
		stock_select = "0 AS stock_qty, NULL AS warehouse"

	price_join = ""
	price_select = "NULL AS selling_rate, NULL AS price_currency"
	if price_list:
		params["price_list"] = price_list
		price_join = (
			"LEFT JOIN `tabItem Price` ip "
			"ON ip.item_code = item.name "
			"AND ip.price_list = %(price_list)s "
			"AND ip.selling = 1"
		)
		price_select = "ip.price_list_rate AS selling_rate, ip.currency AS price_currency"

	rows = frappe.db.sql(
		"""
		SELECT
			item.name        AS item_code,
			item.item_name,
			item.stock_uom,
			{stock_select},
			{price_select}
		FROM `tabItem` item
		INNER JOIN `tabItem Default` idef
			ON idef.parent = item.name AND idef.company = %(company)s
		{bin_join}
		{price_join}
		WHERE item.is_sales_item = 1
		  AND item.disabled = 0
		GROUP BY item.name
		ORDER BY item.item_name ASC
		LIMIT %(limit)s
		""".format(
			stock_select=stock_select,
			price_select=price_select,
			bin_join=bin_join,
			price_join=price_join,
		),
		params,
		as_dict=True,
	)

	rows.sort(key=_natural_sort_key)
	return rows
