# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe import _

from vansale.sf_trading.open_items import billed_items_pending_receipt, report_columns


def execute(filters=None):
	filters = filters or {}
	columns = report_columns("Purchase Invoice", "Supplier", "received_qty", _("Received Qty"))
	data = billed_items_pending_receipt(filters)
	return columns, data
