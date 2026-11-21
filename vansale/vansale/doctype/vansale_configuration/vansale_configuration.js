// Admin-side PIN reset.
//
// A driver who forgets their PIN cannot be helped over the phone — the hash
// is one-way. The office needs to clear it so the app asks the driver to set
// a new one on next login. `vansale.api.auth.reset_pin` re-checks the role
// server-side; this button is only the convenient path to it.
frappe.ui.form.on("Vansale Configuration", {
	setup(frm) {
		vansale_filter_print_formats(frm);
		vansale_filter_by_company(frm);
		// ERPNext rejects a group Customer Group on a Customer; offer leaves only.
		frm.set_query("default_customer_group", () => ({ filters: { is_group: 0 } }));
		frm.set_query("default_territory", () => ({ filters: { is_group: 0 } }));
	},

	refresh(frm) {
		if (frm.is_new()) return;

		const assigned = (frm.doc.user || []).map((r) => r.user).filter(Boolean);
		if (!assigned.length) return;

		frm.add_custom_button(
			__("Reset Driver PIN"),
			() => {
				const d = new frappe.ui.Dialog({
					title: __("Reset Driver PIN"),
					fields: [
						{
							fieldname: "user",
							fieldtype: "Select",
							label: __("Driver"),
							options: assigned.join("\n"),
							reqd: 1,
						},
						{
							fieldtype: "HTML",
							options: `<p class="text-muted small">${__(
								"Clears the PIN. The driver sets a new one the next time they log in. Their queued offline work is untouched.",
							)}</p>`,
						},
					],
					primary_action_label: __("Reset PIN"),
					primary_action(values) {
						frappe.call({
							method: "vansale.api.auth.reset_pin",
							args: { user: values.user },
							freeze: true,
							freeze_message: __("Resetting…"),
							callback(r) {
								d.hide();
								if (!r.message) return;
								frappe.show_alert({
									message: r.message.cleared
										? __("PIN cleared for {0}", [values.user])
										: __("{0} had no PIN set", [values.user]),
									indicator: "green",
								});
							},
						});
					},
				});
				d.show();
			},
			__("Actions"),
		);
	},
});

// Warehouse, cost center, branch and payment-mode pickers only offer what
// belongs to the van's company (validate() refuses the rest on save).
function vansale_filter_by_company(frm) {
	const company = () => frm.doc.company;
	const of_company = () => ({
		filters: company()
			? { company: company(), is_group: 0, disabled: 0 }
			: { is_group: 0, disabled: 0 },
	});
	frm.set_query("warehouse", "warehouse", of_company);
	frm.set_query("cost_center", "cost_center", of_company);
	frm.set_query("selling_price_list", () => ({ filters: { selling: 1, enabled: 1 } }));
	// A mode without an account for the company can't be posted by the app.
	frm.set_query("allowed_modes_of_payment", () => {
		const filters = [["Mode of Payment", "enabled", "=", 1]];
		if (company()) filters.push(["Mode of Payment Account", "company", "=", company()]);
		return { filters };
	});
	// Branch has no company in ERPNext; some sites add custom_company
	// (ksa_compliance). Branches with none set stay on offer.
	frappe.model.with_doctype("Branch", () => {
		if (!frappe.meta.has_field("Branch", "custom_company")) return;
		frm.set_query("branch", () => ({
			filters: company() ? [["Branch", "custom_company", "in", [company(), ""]]] : [],
		}));
	});
}

// Each print format picker only offers formats for its doctype.
// Vansale Settings has the same filter (vansale_settings.js).
function vansale_filter_print_formats(frm) {
	const fields = {
		invoice_print_format: "Sales Invoice",
		receipt_print_format: "Payment Entry",
		quotation_print_format: "Quotation",
		sales_order_print_format: "Sales Order",
	};
	for (const [field, doctype] of Object.entries(fields)) {
		frm.set_query(field, () => ({ filters: { doc_type: doctype, disabled: 0 } }));
	}
}
