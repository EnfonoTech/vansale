// apps/vansale/vansale/public/sf_trading/js/payment_advice_form_action.js
// "Payment Advice" under the form's Create menu on Purchase Order and Purchase Invoice.
//
// The visibility rules are lifted from ERPNext's own Payment Request button so the two entries
// appear and disappear together:
//
//   Purchase Invoice — erpnext/accounts/doctype/purchase_invoice/purchase_invoice.js
//                      docstatus 1, outstanding_amount > 0, not a return, not on hold
//   Purchase Order   — erpnext/buying/doctype/purchase_order/purchase_order.js
//                      docstatus 1, status not "On Hold", per_billed < 100
//
// Amounts are never computed here. create_advices_from_documents() reads them through
// get_reference_amounts(), so an order nets off advance_paid and a foreign document is read in
// company currency — the same figures the Payment Advice form itself would produce. A document
// already sitting on a live advice, or with nothing left to pay, is rejected by the server with a
// message naming it rather than being silently skipped.

(function () {
	const BUILDER = "vansale.sf_trading.api.payment_advice_builder.create_advices_from_documents";

	function can_raise(frm) {
		const doc = frm.doc;
		if (doc.docstatus !== 1) return false;
		if (!frappe.model.can_create("Payment Advice")) return false;

		if (doc.doctype === "Purchase Invoice") {
			return flt(doc.outstanding_amount) > 0 && !cint(doc.is_return) && !doc.on_hold;
		}
		// Purchase Order
		return doc.status !== "On Hold" && flt(doc.per_billed) < 100;
	}

	function open_dialog(frm) {
		const dialog = new frappe.ui.Dialog({
			title: __("Create Payment Advice"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${__(
						"One draft advice will be raised for {0} from this {1}. Approver, bank account and remarks are optional and can be set on the advice later.",
						[frappe.utils.escape_html(frm.doc.supplier_name || frm.doc.supplier), __(frm.doctype)]
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
						filters: { company: frm.doc.company, is_company_account: 1 },
					}),
				},
				{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" },
			],
			primary_action_label: __("Create"),
			primary_action(values) {
				dialog.hide();
				frappe.call({
					method: BUILDER,
					args: {
						documents: [frm.doc.name],
						options: Object.assign({ doctype: frm.doctype }, values),
					},
					freeze: true,
					freeze_message: __("Creating Payment Advice…"),
					callback(r) {
						show_result(r.message);
					},
				});
			},
		});
		dialog.show();
	}

	function show_result(result) {
		if (!result) return;

		const created = result.created || [];
		const failed = result.failed || [];

		if (failed.length) {
			frappe.msgprint({
				title: __("Payment Advice not created"),
				indicator: "red",
				message: failed
					.map(
						(row) =>
							`${frappe.utils.escape_html(row.party)} — ${frappe.utils.escape_html(row.error)}`
					)
					.join("<br>"),
			});
		}

		if (!created.length) return;

		const advice = created[0].advice;
		frappe.show_alert({
			message: __("Payment Advice {0} created", [advice]),
			indicator: "green",
		});
		frappe.set_route("Form", "Payment Advice", advice);
	}

	["Purchase Invoice", "Purchase Order"].forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (!can_raise(frm)) return;
				frm.add_custom_button(__("Payment Advice"), () => open_dialog(frm), __("Create"));
			},
		});
	});
})();
