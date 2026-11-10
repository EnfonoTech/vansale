# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe import _

from vansale.sf_trading.open_items import invoiced_items_to_be_delivered, report_columns


def execute(filters=None):
	filters = filters or {}
	columns = report_columns("Sales Invoice", "Customer", "delivered_qty", _("Delivered Qty"))
	data = invoiced_items_to_be_delivered(filters)
	return columns, data
