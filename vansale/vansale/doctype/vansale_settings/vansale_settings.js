// Each print format picker only offers formats for its doctype.
// Vansale Configuration has the same filter (vansale_configuration.js).
const VANSALE_PRINT_FORMAT_FIELDS = {
	invoice_print_format: "Sales Invoice",
	receipt_print_format: "Payment Entry",
	quotation_print_format: "Quotation",
	sales_order_print_format: "Sales Order",
};

frappe.ui.form.on("Vansale Settings", {
	setup(frm) {
		for (const [field, doctype] of Object.entries(VANSALE_PRINT_FORMAT_FIELDS)) {
			frm.set_query(field, () => ({ filters: { doc_type: doctype, disabled: 0 } }));
		}
	},
	// "PDF same as browser print": Chromium + fonts on the server (vansale/pdf_engine.py).
	refresh(frm) {
		frm.add_custom_button(__("Check PDF setup"), () => {
			frappe.call("vansale.pdf_engine.check").then((r) => {
				frappe.msgprint({ title: __("PDF engine"), message: r.message.html, wide: true });
			});
		}, __("PDF engine"));
		frm.add_custom_button(__("Set up PDF engine"), () => {
			frappe.call("vansale.pdf_engine.setup").then((r) => frappe.show_alert(r.message, 10));
		}, __("PDF engine"));
		// Setup runs in the background; its result comes back as a short notice.
		frappe.realtime.off("vansale_pdf_setup");
		frappe.realtime.on("vansale_pdf_setup", (data) => {
			frappe.show_alert({ message: data.message, indicator: data.ready ? "green" : "orange" }, 15);
		});
	},
});
