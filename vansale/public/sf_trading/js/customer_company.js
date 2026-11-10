// Customer form — auto-fill custom_company when a new Customer is created.
// - Created from a form (Sales Invoice, Sales Order, etc.): use that form's company.
// - Created directly (not from a form): auto-fill default company only for System Manager.

frappe.ui.form.on("Customer", {
	refresh: function(frm) {
		if (!frm.is_new() || frm.doc.custom_company) return;

		// Try to get company from the referring form via route history
		const history = frappe.route_history || [];
		if (history.length >= 2) {
			const prev = history[history.length - 2];
			// prev format: ["Form", "Sales Invoice", "ACC-SINV-2026-00001"]
			if (prev && prev[0] === "Form" && prev[1] && prev[2]) {
				const dt = prev[1], dn = prev[2];

				// Read from in-memory model cache first — works for unsaved forms
				const company_in_memory = frappe.model.get_value(dt, dn, "company");
				if (company_in_memory) {
					frm.set_value("custom_company", company_in_memory);
					return;
				}

				// Fallback to server for saved forms not currently in memory
				frappe.db.get_value(dt, dn, "company", function(r) {
					if (r && r.company && !frm.doc.custom_company) {
						frm.set_value("custom_company", r.company);
					}
				});
				return;
			}
		}

		// No referring form — auto-fill default company only for System Manager
		if (frappe.user.has_role("System Manager")) {
			const default_company = frappe.defaults.get_default("company");
			if (default_company) {
				frm.set_value("custom_company", default_company);
			}
		}
	},
});
