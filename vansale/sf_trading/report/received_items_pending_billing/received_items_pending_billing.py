# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe import _

from vansale.sf_trading.open_items import received_items_pending_billing, report_columns


def execute(filters=None):
	filters = filters or {}
	columns = report_columns("Purchase Receipt", "Supplier", "billed_qty", _("Billed Qty"))
	data = received_items_pending_billing(filters)
	return columns, data
