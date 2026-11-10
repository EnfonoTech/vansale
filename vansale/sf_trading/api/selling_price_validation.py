import frappe
from frappe import _
from frappe.utils import flt


def _get_margin_pct(item_code):
	"""Walk up the Item Group tree; return first non-zero custom_min_margin_pct."""
	item_group = frappe.db.get_value("Item", item_code, "item_group")
	visited = set()
	while item_group and item_group not in visited:
		visited.add(item_group)
		pct = flt(frappe.db.get_value("Item Group", item_group, "custom_min_margin_pct"))
		if pct:
			return pct
		item_group = frappe.db.get_value("Item Group", item_group, "parent_item_group")
	return 0.0


@frappe.whitelist()
def get_min_selling_price(item_code, warehouse=None, price_list=None,
                           conversion_rate=1.0, uom_cf=1.0, plc_conversion_rate=1.0):
	"""
	Return the minimum allowed selling rate for an item in *transaction* currency.
	Used for real-time client-side validation (rate field onchange).

	minimum = max(
	    price_list_rate × plc_conversion_rate         [if the price list enforces]
	    last_purchase_rate × uom_cf × (1 + margin%)  [always]
	    bin.valuation_rate × uom_cf × (1 + margin%)  [stock items with warehouse]
	) all converted to transaction currency via conversion_rate.

	Currencies, because three different ones meet here:
	  * `last_purchase_rate` (Item) and `valuation_rate` (Bin) are COMPANY currency
	    per stock UOM — see erpnext/buying/utils.py, which stores base_net_rate.
	  * `price_list_rate` (Item Price) is the PRICE LIST's currency, which need not
	    be the company's or the transaction's.
	  * `rate` on the row, which this figure is compared against, is TRANSACTION
	    currency.
	So company-currency inputs are divided by `conversion_rate`, and the price list
	is first taken to company currency by `plc_conversion_rate` — the same rate the
	save-time validator uses — before the same division.
	"""
	conversion_rate = flt(conversion_rate) or 1.0
	uom_cf = flt(uom_cf) or 1.0
	plc_conversion_rate = flt(plc_conversion_rate) or 1.0

	# When the price list has "Enforce Minimum Selling Price" ticked, it REPLACES the
	# cost checks — only validate that the rate is >= the price list rate.
	if price_list and frappe.db.get_value("Price List", price_list, "custom_enforce_min_price"):
		pl_rate = flt(frappe.db.get_value(
			"Item Price",
			{"item_code": item_code, "price_list": price_list, "selling": 1},
			"price_list_rate",
		))
		if not pl_rate:
			return {"min_price": 0.0}
		return {"min_price": pl_rate * plc_conversion_rate / conversion_rate}

	# Normal cost + margin checks
	margin_pct = _get_margin_pct(item_code)
	multiplier = 1 + margin_pct / 100.0
	candidates = []

	purchase_rate = flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))
	if purchase_rate:
		candidates.append(purchase_rate * uom_cf * multiplier / conversion_rate)

	if warehouse:
		is_stock = frappe.db.get_value("Item", item_code, "is_stock_item")
		if is_stock:
			val_rate = flt(frappe.db.get_value(
				"Bin",
				{"item_code": item_code, "warehouse": warehouse},
				"valuation_rate",
			))
			if val_rate:
				candidates.append(val_rate * uom_cf * multiplier / conversion_rate)

	return {"min_price": max(candidates) if candidates else 0.0}


def validate_selling_price(doc, method=None):
	"""
	Save-time validation: each item's base_net_rate must be >= the minimum allowed
	rate (computed in base/company currency).

	Runs independently — not gated on Selling Settings.
	Does not reveal cost components; shows only the minimum price.
	"""
	is_internal = bool(
		doc.get("customer")
		and frappe.db.get_value("Customer", doc.customer, "is_internal_customer")
	)

	company_currency = doc.get("company_currency") or ""
	plc_conversion_rate = flt(doc.get("plc_conversion_rate")) or 1.0

	errors = []

	for item in doc.items:
		if not item.item_code or not flt(item.base_net_rate):
			continue

		cf = flt(item.conversion_factor) or 1.0
		rate = flt(item.base_net_rate)

		# A row's own Price List (if set) takes precedence over the invoice's.
		effective_price_list = item.get("custom_price_list") or doc.get("selling_price_list")

		# When the price list enforces minimum price, it REPLACES the cost checks.
		enforce_pl = (
			not is_internal
			and effective_price_list
			and frappe.db.get_value("Price List", effective_price_list, "custom_enforce_min_price")
		)

		if enforce_pl:
			pl_rate = flt(frappe.db.get_value(
				"Item Price",
				{"item_code": item.item_code, "price_list": effective_price_list, "selling": 1},
				"price_list_rate",
			))
			if not pl_rate:
				continue
			min_rate = pl_rate * plc_conversion_rate
		else:
			margin_pct = _get_margin_pct(item.item_code)
			multiplier = 1 + margin_pct / 100.0
			candidates = []

			purchase_rate = flt(frappe.db.get_value("Item", item.item_code, "last_purchase_rate"))
			if purchase_rate:
				candidates.append(purchase_rate * cf * multiplier)

			if not is_internal:
				is_stock = frappe.db.get_value("Item", item.item_code, "is_stock_item")
				warehouse = item.get("warehouse")
				if is_stock and warehouse:
					val_rate = flt(frappe.db.get_value(
						"Bin",
						{"item_code": item.item_code, "warehouse": warehouse},
						"valuation_rate",
					))
					if val_rate:
						candidates.append(val_rate * cf * multiplier)

			if not candidates:
				continue
			min_rate = max(candidates)
		if rate < min_rate:
			errors.append(
				_("Row {0} ({1}): Minimum selling price is {2}.").format(
					item.idx,
					item.item_code,
					frappe.utils.fmt_money(min_rate, currency=company_currency),
				)
			)

	if errors:
		frappe.throw(
			_("Selling price validation failed:<br><br>") + "<br>".join(errors),
			title=_("Invalid Selling Price"),
		)
