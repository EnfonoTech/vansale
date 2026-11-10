// Customer filter: Credit mode shows only customers with credit_limit > 0
function sf_apply_customer_credit_filter(frm) {
	frm.set_query("customer", function (doc) {
		if (doc.custom_payment_mode === "Credit") {
			return {
				query: "vansale.sf_trading.customer_permission.customer_query_credit_branch",
				filters: { branch: doc.branch || "", company: doc.company || "" },
			};
		}
		// Cash / Cheque: only show customers whose company matches the invoice company
		if (doc.company) {
			return {
				filters: {
					custom_company: doc.company,
				},
			};
		}
		return {};
	});
}

function sf_get_customer_credit_limit(customer, company) {
	// credit_limits is a child table on the Customer master
	return frappe.call({
		method: "frappe.client.get",
		args: { doctype: "Customer", name: customer },
	}).then(function (r) {
		const rows = (r.message && r.message.credit_limits) || [];
		const row = rows.find(function (d) { return d.company === company; });
		return row ? flt(row.credit_limit) : 0;
	});
}

function sf_check_overdue_on_customer(frm) {
	if (frm.doc.is_return || frm.doc.custom_payment_mode !== "Credit" || !frm.doc.customer || !frm.doc.company) return;
	frappe.call({
		method: "vansale.sf_trading.api.sales_invoice_override.check_customer_credit_overdue",
		args: { customer: frm.doc.customer, company: frm.doc.company },
		callback: function (r) {
			if (r.message) {
				var inv = r.message;
				frappe.msgprint({
					title: __("Overdue Credit Invoice"),
					message: __(
						"Customer {0} has an overdue credit invoice <a href='/app/sales-invoice/{1}'>{1}</a> dated {2} "
						+ "with outstanding amount {3}. "
						+ "Saving this invoice will be blocked until it is settled.",
						[frm.doc.customer, inv.name, inv.posting_date,
						format_currency(inv.outstanding_amount, frm.doc.currency)]
					),
					indicator: "orange",
				});
			}
		},
	});
}

frappe.ui.form.on("Sales Invoice", {
	onload: function (frm) {
		sf_apply_customer_credit_filter(frm);
		// Warn once on initial load if draft already has a customer in Credit mode
		if (frm.doc.docstatus === 0 && frm.doc.customer) {
			sf_check_overdue_on_customer(frm);
		}
	},
	refresh: function (frm) {
		sf_apply_customer_credit_filter(frm);
	},
	custom_payment_mode: function (frm) {
		sf_apply_customer_credit_filter(frm);
		if (frm.doc.custom_payment_mode === "Cheque" && frm.doc.branch) {
			frappe.call({
				method: "vansale.sf_trading.api.sales_invoice_payment.branch_has_pdc_modes",
				args: { branch: frm.doc.branch },
				callback: function (r) {
					if (!r.message) {
						frappe.msgprint({
							title: __("Cheque Not Available"),
							message: __("Branch {0} has no Cheque (PDC) payment modes configured. Please use Cash or Credit.", [frm.doc.branch]),
							indicator: "red",
						});
						frm.set_value("custom_payment_mode", "Cash");
					}
				},
			});
			return;
		}
		if (frm.doc.custom_payment_mode === "Credit" && frm.doc.customer) {
			sf_get_customer_credit_limit(frm.doc.customer, frm.doc.company).then(function (limit) {
				if (limit <= 0) {
					frappe.msgprint({
						title: __("No Credit Limit"),
						message: __("Customer {0} has no credit limit set for this company. Set a credit limit or use Cash payment mode.", [frm.doc.customer]),
						indicator: "red",
					});
					frm.set_value("custom_payment_mode", "Cash");
					return;
				}
				sf_check_overdue_on_customer(frm);
			});
		}
	},
	customer: function (frm) {
		if (frm.doc.custom_payment_mode !== "Credit" || !frm.doc.customer) return;
		sf_get_customer_credit_limit(frm.doc.customer, frm.doc.company).then(function (limit) {
			if (limit <= 0) {
				frappe.msgprint({
					title: __("No Credit Limit"),
					message: __("Customer {0} has no credit limit set for this company. Set a credit limit or use Cash payment mode.", [frm.doc.customer]),
					indicator: "red",
				});
				frm.set_value("customer", "");
				return;
			}
			sf_check_overdue_on_customer(frm);
		});
	},
});
