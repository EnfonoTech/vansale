// Invoice / receipt print format pickers only offer formats for that doctype.
frappe.ui.form.on("Vansale Settings", {
	setup(frm) {
		frm.set_query("invoice_print_format", () => ({
			filters: { doc_type: "Sales Invoice", disabled: 0 },
		}));
		frm.set_query("receipt_print_format", () => ({
			filters: { doc_type: "Payment Entry", disabled: 0 },
		}));
	},
});
