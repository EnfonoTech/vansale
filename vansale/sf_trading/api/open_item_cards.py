"""Number Card backends for the open item reports.

A workspace shortcut only draws its red count badge when the shortcut points at a
DocType — `shortcut_widget.js` gates the count on `type == "DocType"` and then
counts `link_to` as a DocType. A shortcut aimed at a Script Report therefore has
nothing to count, and no filter or `format` string changes that.

A Report-type Number Card cannot stand in either: its `report_function` offers
only Sum, Average, Minimum and Maximum, so it can total a column but never count
the rows. Counting needs a Custom card, which calls the method named on the card
with the card's own filters and reads `value` off the result
(`number_card_widget.js` -> `get_number_for_custom_card`).
"""

import frappe
from frappe import _

from vansale.sf_trading.open_items import invoices_pending_delivery

REPORT = "Invoices Pending Delivery"


def _card_filters(filters):
	"""Normalise whatever the dashboard hands us into the engine's filter dict.

	Number Card filters arrive as the card's `filters_json` (a dict for these
	cards), but dashboard filters can also arrive as a list of
	[doctype, fieldname, operator, value] rows, so accept both rather than break
	the card the first time someone adds a filter in the UI.
	"""
	filters = frappe.parse_json(filters) if filters else {}

	if isinstance(filters, list):
		parsed = {}
		for row in filters:
			if isinstance(row, (list, tuple)) and len(row) >= 4:
				parsed[row[1]] = row[3]
		filters = parsed

	if not isinstance(filters, dict):
		filters = {}

	if not filters.get("company"):
		filters["company"] = frappe.defaults.get_user_default("Company")

	return frappe._dict(filters)


@frappe.whitelist()
def pending_delivery_invoice_count(filters=None):
	"""How many Sales Invoices still owe a delivery.

	Counts invoices, not item rows, and nets returns the way the report does, so a
	fully credited invoice is not counted and a partly credited one is.
	"""
	frappe.has_permission("Sales Invoice", "read", throw=True)

	card_filters = _card_filters(filters)
	rows = invoices_pending_delivery(card_filters)

	return {
		# fieldtype travels with the value: the widget passes this whole object to
		# frappe.format as the df, so without it the count renders as a float
		"value": len(rows),
		"fieldtype": "Int",
		"label": _("Invoices Pending Delivery"),
		# a Custom card routes to whatever `route` its method returns — see
		# set_route_for_custom_card in number_card_widget.js — so clicking the count
		# lands on the report the count was taken from rather than doing nothing
		"route": ["query-report", REPORT],
		"route_options": {"company": card_filters.get("company")},
	}
