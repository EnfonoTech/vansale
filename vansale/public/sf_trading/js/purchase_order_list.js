// apps/vansale/vansale/public/sf_trading/js/purchase_order_list.js
// "Create Payment Advice" action on the Purchase Order list — see payment_advice_list_action.js.
frappe.listview_settings["Purchase Order"] = Object.assign(
	frappe.listview_settings["Purchase Order"] || {},
	sf_payment_advice_list_action("Purchase Order", "supplier", "Supplier")
);
