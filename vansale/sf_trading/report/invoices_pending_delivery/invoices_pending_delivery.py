# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from vansale.sf_trading.open_items import invoices_pending_delivery, pending_delivery_columns


def execute(filters=None):
	filters = filters or {}
	return pending_delivery_columns(), invoices_pending_delivery(filters)
