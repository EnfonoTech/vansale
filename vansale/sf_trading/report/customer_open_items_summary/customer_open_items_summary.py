# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt

from frappe import _

from vansale.sf_trading.open_items import summary_columns, customer_open_items_summary


def execute(filters=None):
	filters = filters or {}
	columns = summary_columns(
		"Customer",
		[
			("to_deliver_value", _("To Deliver Value"), "Invoiced Items To Be Delivered"),
			("unbilled_delivery_value", _("Unbilled Deliveries Value"), "Delivered Items Pending Billing"),
		],
		filters,
	)
	data = customer_open_items_summary(filters)
	return columns, data
