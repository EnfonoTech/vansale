frappe.ui.form.on("Inter Company Branch", {
	onload: function (frm) {
		frm.set_query("cost_center", "company_cost_centers", function (doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			if (!row.company) return { filters: { name: "" } };
			return {
				filters: [
					["Cost Center", "company", "=", row.company],
					["Cost Center", "is_group", "=", 0],
				],
			};
		});
		frm.set_query("warehouse", "company_cost_centers", function (doc, cdt, cdn) {
			let row = locals[cdt][cdn];
			if (!row.company) return { filters: { name: "" } };
			return {
				filters: [["Warehouse", "company", "=", row.company]],
			};
		});
	},
});

frappe.ui.form.on("Inter Company Branch Cost Center", {
	company: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.company) {
			frappe.model.set_value(cdt, cdn, "cost_center", "");
			frappe.model.set_value(cdt, cdn, "warehouse", "");
		}
	},
});
