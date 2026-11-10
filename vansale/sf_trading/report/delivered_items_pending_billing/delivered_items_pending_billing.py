# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe import _

from vansale.sf_trading.open_items import delivered_items_pending_billing, report_columns


def execute(filters=None):
	filters = filters or {}
	columns = report_columns("Delivery Note", "Customer", "billed_qty", _("Billed Qty"))
	data = delivered_items_pending_billing(filters)
	return columns, data
