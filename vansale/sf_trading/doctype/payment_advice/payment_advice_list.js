// apps/vansale/vansale/sf_trading/doctype/payment_advice/payment_advice_list.js
// Payment Advice list: colour by status and surface what still needs a human.

frappe.listview_settings["Payment Advice"] = {
	add_fields: ["status", "payment_amount", "party_name", "auto_generated", "payment_entry"],

	get_indicator(doc) {
		const map = {
			Draft: ["Draft", "gray", "status,=,Draft"],
			"Pending Approval": ["Pending Approval", "orange", "status,=,Pending Approval"],
			Approved: ["Approved", "blue", "status,=,Approved"],
			"Partly Paid": ["Partly Paid", "yellow", "status,=,Partly Paid"],
			Paid: ["Paid", "green", "status,=,Paid"],
			Cancelled: ["Cancelled", "red", "status,=,Cancelled"],
		};
		return map[doc.status] || [doc.status, "gray", "status,=," + doc.status];
	},

	formatters: {
		party_name(value, df, doc) {
			// mark the ones the scheduler raised, so a human knows what to review
			return doc.auto_generated
				? `${frappe.utils.escape_html(value || "")} <span class="indicator-pill gray" title="${__(
						"Raised by payment automation"
				  )}">${__("auto")}</span>`
				: frappe.utils.escape_html(value || "");
		},
	},

	onload(listview) {
		listview.page.add_inner_button(__("Awaiting Payment Entry"), () => {
			listview.filter_area.clear();
			listview.filter_area.add([
				["Payment Advice", "status", "=", "Approved"],
				["Payment Advice", "payment_entry", "is", "not set"],
			]);
		});
	},
};
