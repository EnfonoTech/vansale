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
