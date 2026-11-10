import re

import frappe


def _natural_key(s):
	"""Sort key that treats embedded decimal numbers as floats.

	Plain alphabetical sort puts '2.6MM' before '2MM' because '.' < 'M' in ASCII.
	This key compares the numeric parts as floats so 2 < 2.6 gives the right order.
	"""
	parts = re.split(r"(\d+(?:\.\d+)?|\.\d+)", s or "")
	result = []
	for part in parts:
		try:
			result.append(float(part))
		except ValueError:
			result.append(part.lower())
	return result


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_items_with_stock_and_rate(doctype, txt, searchfield, start, page_len, filters, as_dict=False, **kwargs):
	"""
	Global item Link-field search — used by ALL item_code fields across all doctypes.

	Wraps ``erpnext.controllers.queries.item_query`` (standard ERPNext behaviour
	preserved) and appends two extra columns:

		- Stock: <total qty across the user's permitted warehouses>
		- Rate: <selling rate from the form's price list>

	Frappe's autocomplete joins everything after the first column with ", ",
	so the dropdown ends up looking like:

		ITEM-001
		Item Name, Item Group, Brand, Stock: 12, Rate: SAR 100

	Custom kwargs consumed by us (popped before delegating):
		- company   : used for stock + company-default filtering; falls back to user default
		- price_list: used for selling rate lookup
	"""
	from erpnext.controllers.queries import item_query
	from frappe.core.doctype.user_permission.user_permission import get_permitted_documents

	if not isinstance(filters, dict):
		filters = {}

	# Pop our custom filters before passing to ERPNext's item_query (it would
	# otherwise try to apply them as Item field filters and either fail or
	# return zero rows).
	company = filters.pop("company", None)
	price_list = filters.pop("price_list", None)

	# Pre-filter by Item Default for this company BEFORE calling item_query,
	# so ERPNext's pagination operates on the already-restricted item set.
	# Doing this post-pagination caused items to disappear: item_query returns
	# the first N items alphabetically, and the company-specific items may not
	# be in that first page at all.
	if company:
		allowed_codes = frappe.get_all(
			"Item Default",
			filters={"company": company},
			pluck="parent",
			ignore_permissions=True,
		)
		if not allowed_codes:
			return []
		filters["name"] = ["in", allowed_codes]

	# Delegate to ERPNext's standard item search. We pass as_dict=False so we
	# get tuples in the exact format Frappe's autosuggest expects.
	base_rows = item_query(
		doctype, txt, searchfield, start, page_len, filters, as_dict=False
	) or []

	if not base_rows:
		return []

	# Collect item codes (always the first column of each ERPNext row)
	item_codes = [row[0] for row in base_rows if row and row[0]]
	if not item_codes:
		return list(base_rows)

	# Natural sort by item_name: numeric parts compared as floats so
	# "2MM" (2.0) sorts before "2.6MM" (2.6), not after it.
	base_rows = sorted(base_rows, key=lambda r: _natural_key(r[1] or r[0] or ""))

	# --- Resolve "the logged user's warehouse(s)" ---
	# Priority:
	#   1. User Permission on Warehouse (matches Quick Entry's behaviour).
	#   2. The user's default warehouse (User Defaults).
	# If neither is set we show nothing rather than leaking stock for every
	# warehouse — that was the source of the "showing all warehouses" issue
	# when the logged-in user has no warehouse-specific configuration.
	user_warehouses = list(get_permitted_documents("Warehouse") or [])
	if not user_warehouses:
		default_wh = (
			frappe.defaults.get_user_default("Warehouse")
			or frappe.defaults.get_user_default("warehouse")
		)
		if default_wh:
			user_warehouses = [default_wh]

	stock_map = {}  # item_code -> [(warehouse_label, qty), ...] sorted by qty desc
	stock_unknown = not user_warehouses  # flag: cannot determine user's warehouse
	if company and user_warehouses:
		warehouses = frappe.get_all(
			"Warehouse",
			filters={
				"company": company,
				"is_group": 0,
				"disabled": 0,
				"name": ["in", user_warehouses],
			},
			fields=["name", "warehouse_name"],
		)

		if warehouses:
			warehouse_names = [w.name for w in warehouses]
			wh_label = {w.name: (w.warehouse_name or w.name) for w in warehouses}

			bin_rows = frappe.db.sql(
				"""
				SELECT item_code, warehouse, actual_qty
				FROM `tabBin`
				WHERE item_code IN %(items)s
				  AND warehouse IN %(warehouses)s
				  AND actual_qty > 0
				ORDER BY actual_qty DESC
				""",
				{"items": item_codes, "warehouses": warehouse_names},
				as_dict=True,
			)
			for row in bin_rows:
				stock_map.setdefault(row.item_code, []).append(
					(wh_label.get(row.warehouse, row.warehouse), row.actual_qty or 0)
				)

	# --- Rate: from Item Price for the form's selling price list ---
	price_map = {}
	if price_list:
		prices = frappe.get_all(
			"Item Price",
			filters={
				"item_code": ["in", item_codes],
				"price_list": price_list,
				"selling": 1,
			},
			fields=["item_code", "price_list_rate", "currency"],
		)
		price_map = {p.item_code: (p.price_list_rate, p.currency) for p in prices}

	def _fmt_qty(q):
		return ("{0:.2f}".format(float(q))).rstrip("0").rstrip(".") or "0"

	# --- Append the two extra columns to each row ---
	results = []
	for row in base_rows:
		new_row = list(row)
		item_code = new_row[0]

		stock_list = stock_map.get(item_code) or []
		if stock_unknown:
			# No User Permission on Warehouse and no user default — we cannot
			# resolve "the user's warehouse" so we don't display a stock figure.
			stock_str = "Stock: -"
		elif not stock_list:
			stock_str = "Stock: 0"
		elif len(stock_list) == 1:
			# One warehouse for this user — keep it compact.
			wh_label, qty = stock_list[0]
			stock_str = "Stock: {0} ({1})".format(_fmt_qty(qty), wh_label)
		else:
			# Multiple warehouses — show all so transfers are visible.
			parts = ["{0}: {1}".format(label, _fmt_qty(qty)) for label, qty in stock_list]
			stock_str = "Stock: " + ", ".join(parts)
		new_row.append(stock_str)

		rate_info = price_map.get(item_code)
		if rate_info:
			rate, currency = rate_info
			new_row.append("Rate: {0} {1}".format(currency or "", _fmt_qty(rate)).strip())
		else:
			new_row.append("Rate: -")

		results.append(tuple(new_row))

	return results


def redirect_item_query_before_request():
	"""before_request hook: redirect every erpnext item_query call to our rich version.

	search_link POSTs query= directly, bypassing override_whitelisted_methods, so
	swapping here is the only reliable server-side interception point.

	We also inject company from user defaults when the caller hasn't supplied one so
	that all item link fields (not just Sales Invoice) get the company-filtered,
	stock/rate-enriched dropdown.
	"""
	if frappe.form_dict.get("query") != "erpnext.controllers.queries.item_query":
		return

	frappe.form_dict["query"] = "vansale.sf_trading.api.item_search.search_items_with_stock_and_rate"



@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	"""Global override of erpnext.controllers.queries.item_query.
	Delegates entirely to ERPNext's standard search, then re-sorts results
	by item_name so all item Link fields show items in alphabetical name order.
	"""
	from erpnext.controllers.queries import item_query as _erpnext_item_query

	rows = _erpnext_item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=as_dict) or []
	if as_dict:
		return sorted(rows, key=lambda r: _natural_key(r.get("item_name") or r.get("name") or ""))
	return sorted(rows, key=lambda r: _natural_key(r[1] if len(r) > 1 else r[0] or ""))
