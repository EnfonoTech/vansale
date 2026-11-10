// apps/vansale/vansale/public/sf_trading/js/payment_advice_list_action.js
// "Create Payment Advice" list action, shared by Purchase Invoice, Sales Invoice,
// Purchase Order and Sales Order.
//
// One advice per party, however many documents are ticked. Amounts come from the server
// (get_reference_amounts), so an order nets off advance_paid and a foreign invoice is read in
// company currency — the list never does its own arithmetic.

window.sf_payment_advice_list_action = function (doctype, party_field, party_label) {
	return {
		onload(listview) {
			listview.page.add_actions_menu_item(
				__("Create Payment Advice (by {0})", [party_label]),
				() => {
					const selected = listview.get_checked_items();
					if (!selected.length) {
						frappe.msgprint(__("Tick the documents to pay first."));
						return;
					}

					const submitted = selected.filter((d) => d.docstatus === 1);
					if (!submitted.length) {
						frappe.msgprint(__("None of the ticked documents are submitted."));
						return;
					}

					const parties = Array.from(new Set(submitted.map((d) => d[party_field])));
					const dialog = new frappe.ui.Dialog({
						title: __("Create Payment Advice"),
						fields: [
							{
								fieldtype: "HTML",
								options: `<p>${__(
									"{0} {1} document(s) across {2} {3}(s). One advice per {3} will be created as a draft. Anything already advised, or with nothing left to pay, is reported back.",
									[submitted.length, __(doctype), parties.length, party_label.toLowerCase()]
								)}</p>`,
							},
							{
								fieldname: "approver",
								label: __("Approver"),
								fieldtype: "Link",
								options: "User",
								get_query: () => ({ filters: { enabled: 1 } }),
							},
							{
								fieldname: "bank_account",
								label: __("Company Bank Account"),
								fieldtype: "Link",
								options: "Bank Account",
								get_query: () => ({
									filters: { company: submitted[0].company, is_company_account: 1 },
								}),
							},
							{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" },
						],
						primary_action_label: __("Create"),
						primary_action(values) {
							dialog.hide();
							frappe.call({
								method: "vansale.sf_trading.api.payment_advice_builder.create_advices_from_documents",
								args: {
									documents: submitted.map((row) => row.name),
									options: Object.assign({ doctype: doctype }, values),
								},
								freeze: true,
								freeze_message: __("Creating Payment Advices…"),
								callback(r) {
									sf_show_advice_result(r.message);
									listview.clear_checked_items();
									listview.refresh();
								},
							});
						},
					});
					dialog.show();
				}
			);
		},
	};
};

window.sf_show_advice_result = function (result) {
	if (!result) return;

	const list = (rows, render) =>
		rows && rows.length ? `<ul>${rows.map(render).join("")}</ul>` : "";

	const created = list(
		result.created,
		(row) =>
			`<li><a href="/app/payment-advice/${encodeURIComponent(row.advice)}" target="_blank">${
				row.advice
			}</a> — ${frappe.utils.escape_html(row.party)} — ${format_currency(row.amount)}</li>`
	);
	const advised = (result.skipped_already_advised || []).length
		? `<p>${__("Skipped, already on a live advice")}: ${result.skipped_already_advised
				.map(frappe.utils.escape_html)
				.join(", ")}</p>`
		: "";
	const nothing_due = (result.skipped_nothing_due || []).length
		? `<p>${__("Skipped, nothing left to pay (fully advanced or settled)")}: ${result.skipped_nothing_due
				.map(frappe.utils.escape_html)
				.join(", ")}</p>`
		: "";
	const failed = list(
		result.failed,
		(row) =>
			`<li>${frappe.utils.escape_html(row.party)} — <span class="text-danger">${frappe.utils.escape_html(
				row.error
			)}</span></li>`
	);

	frappe.msgprint({
		title: __("Payment Advices"),
		indicator: failed ? "orange" : "green",
		message: `${created}${advised}${nothing_due}${
			failed ? `<p>${__("Failed")}:</p>${failed}` : ""
		}`,
	});
};
