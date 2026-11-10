// SF Trading — Quotation enhancements
// 1. set_warehouse change → push to all item rows
// 2. "Create → Sales Invoice" button: opens a pre-filled SI without saving

frappe.ui.form.on("Quotation", {
	refresh: function (frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status !== "Ordered") {
			frm.add_custom_button(__("Sales Invoice"), function () {
				frappe.model.open_mapped_doc({
					method: "vansale.sf_trading.api.quotation.make_sales_invoice_from_quotation",
					frm: frm,
				});
			}, __("Create"));

		}
	},

	set_warehouse: function (frm) {
		if (!frm.doc.set_warehouse) return;
		(frm.doc.items || []).forEach(function (row) {
			frappe.model.set_value("Quotation Item", row.name, "warehouse", frm.doc.set_warehouse);
		});
	},
});
