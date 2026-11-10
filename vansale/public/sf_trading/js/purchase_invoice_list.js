// apps/vansale/vansale/public/sf_trading/js/purchase_invoice_list.js
// "Create Payment Advice" action on the Purchase Invoice list — see payment_advice_list_action.js.
frappe.listview_settings["Purchase Invoice"] = Object.assign(
	frappe.listview_settings["Purchase Invoice"] || {},
	sf_payment_advice_list_action("Purchase Invoice", "supplier", "Supplier")
);
