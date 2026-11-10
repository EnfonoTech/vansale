# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe import _

from vansale.sf_trading.open_items import summary_columns, supplier_open_items_summary


def execute(filters=None):
	filters = filters or {}
	columns = summary_columns(
		"Supplier",
		[
			("unbilled_receipt_value", _("Unbilled Receipts Value"), "Received Items Pending Billing"),
			("pending_receipt_value", _("Pending Receipt Value"), "Billed Items Pending Receipt"),
		],
		filters,
	)
	data = supplier_open_items_summary(filters)
	return columns, data
