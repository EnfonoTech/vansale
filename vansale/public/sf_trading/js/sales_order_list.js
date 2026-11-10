// apps/vansale/vansale/public/sf_trading/js/sales_order_list.js
// "Create Payment Advice" action on the Sales Order list — see payment_advice_list_action.js.
frappe.listview_settings["Sales Order"] = Object.assign(
	frappe.listview_settings["Sales Order"] || {},
	sf_payment_advice_list_action("Sales Order", "customer", "Customer")
);
