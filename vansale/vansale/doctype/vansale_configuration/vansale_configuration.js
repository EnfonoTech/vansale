// Admin-side PIN reset.
//
// A driver who forgets their PIN cannot be helped over the phone — the hash
// is one-way. The office needs to clear it so the app asks the driver to set
// a new one on next login. `vansale.api.auth.reset_pin` re-checks the role
// server-side; this button is only the convenient path to it.
frappe.ui.form.on("Vansale Configuration", {
	setup(frm) {
		vansale_filter_print_formats(frm);
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

// Invoice / receipt print format pickers only offer formats for that doctype.
// Vansale Settings has the same filter (vansale_settings.js).
function vansale_filter_print_formats(frm) {
	frm.set_query("invoice_print_format", () => ({
		filters: { doc_type: "Sales Invoice", disabled: 0 },
	}));
	frm.set_query("receipt_print_format", () => ({
		filters: { doc_type: "Payment Entry", disabled: 0 },
	}));
}
