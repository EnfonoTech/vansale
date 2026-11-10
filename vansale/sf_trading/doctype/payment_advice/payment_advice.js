// apps/vansale/vansale/sf_trading/doctype/payment_advice/payment_advice.js
// Payment Advice form: scope the pickers, pull outstanding documents in one click,
// keep the totals honest as rows change, and hand off to the Payment Entry.

// Payment Entry's own reference table, so an advice cannot hold something its Payment Entry
// would reject at submit.
function sf_valid_reference_doctypes(party_type) {
	// Payment Entry is deliberately absent: an advice authorises a payment, it does not pay
	// another payment. Orders are included and behave as Payment Request does — payable is the
	// order total less advance_paid.
	if (party_type === "Customer") {
		return ["Sales Order", "Sales Invoice", "Journal Entry", "Dunning"];
	}
	return ["Purchase Order", "Purchase Invoice", "Journal Entry"];
}

frappe.ui.form.on("Payment Advice", {
	setup(frm) {
		// party pickers stay inside the advice's own company
		frm.set_query("bank_account", () => ({
			filters: { company: frm.doc.company, is_company_account: 1 },
		}));
		frm.set_query("cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("project", () => ({ filters: { company: frm.doc.company } }));
		frm.set_query("branch", () => ({ filters: {} }));
		frm.set_query("mode_of_payment", () => ({ filters: { type: ["!=", "Phone"] } }));

		// references may only point at documents of the same company and party
		frm.set_query("reference_record", "payment_advice_reference", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const filters = { docstatus: 1 };
			if (doc.company) filters.company = doc.company;

			const party_field = { Supplier: "supplier", Customer: "customer" }[doc.party_type];
			const carries_party = [
				"Purchase Invoice",
				"Purchase Order",
				"Sales Invoice",
				"Sales Order",
				"Dunning",
			].includes(row.reference_doctype);
			if (party_field && carries_party && doc.party) filters[party_field] = doc.party;

			// a closed or completed order has nothing left to pay against, same as the
			// Payment Request selector
			if (["Sales Order", "Purchase Order"].includes(row.reference_doctype)) {
				filters.status = ["not in", ["Closed", "Completed"]];
			}

			return { filters };
		});

		// exactly Payment Entry's list, per party type
		// (PaymentEntry.get_valid_reference_doctypes in ERPNext)
		frm.set_query("reference_doctype", "payment_advice_reference", (doc) => ({
			filters: { name: ["in", sf_valid_reference_doctypes(doc.party_type)] },
		}));
	},

	onload(frm) {
		// the DocType carries no company default: ":Company" would make Frappe run
		// SELECT company FROM tabCompany, which fails every insert. Default it here instead.
		if (frm.is_new() && !frm.doc.company) {
			const company = frappe.defaults.get_user_default("Company");
			if (company) frm.set_value("company", company);
		}
	},

	refresh(frm) {
		frm.trigger("toggle_buttons");
		frm.trigger("show_allocation_summary");
	},

	// party_name is read-only and filled server-side in validate(), so before the first save the
	// field sat empty and the form showed only the supplier code. Fetch it on the spot instead.
	party_type(frm) {
		frm.trigger("fetch_party_name");
	},

	party(frm) {
		frm.trigger("fetch_party_name");
	},

	fetch_party_name(frm) {
		if (frm.doc.docstatus !== 0) return;
		const field = { Supplier: "supplier_name", Customer: "customer_name" }[frm.doc.party_type];
		if (!frm.doc.party || !field) {
			if (frm.doc.party_name) frm.set_value("party_name", "");
			return;
		}
		frappe.db.get_value(frm.doc.party_type, frm.doc.party, field).then((r) => {
			// falls back to the code, exactly as PaymentAdvice.set_party_name() does
			frm.set_value("party_name", (r.message && r.message[field]) || frm.doc.party);
		});
	},

	toggle_buttons(frm) {
		// Buttons are rebuilt from scratch: add_custom_button() alone would stack duplicates,
		// and on a new advice refresh() runs before company/party exist — which is why the
		// button never showed up until a reload. The field triggers below re-run this.
		frm.clear_custom_buttons();

		if (frm.doc.docstatus === 0 && frm.doc.party && frm.doc.company) {
			frm.add_custom_button(
				frm.doc.party_type === "Customer"
					? __("Get Outstanding Invoices")
					: __("Get Outstanding Documents"),
				() => frm.trigger("fetch_outstanding")
			).addClass(frm.doc.payment_advice_reference?.length ? "" : "btn-primary");
		}

		if (frm.doc.docstatus !== 1) return;

		if (!frm.doc.payment_entry) {
			frm.add_custom_button(__("Create Payment Entry"), () => frm.trigger("make_payment_entry"))
				.addClass("btn-primary");
		} else {
			frm.add_custom_button(__("View Payment Entry"), () =>
				frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry)
			);
		}
	},

	fetch_outstanding(frm) {
		// same filter set the Payment Entry form offers, so the two behave alike
		const d = new frappe.ui.Dialog({
			title: __("Get Outstanding Documents"),
			size: "large",
			fields: [
				{
					fieldtype: "Section Break",
					label: __("Posting Date"),
				},
				{ fieldname: "from_posting_date", fieldtype: "Date", label: __("From") },
				{ fieldtype: "Column Break" },
				{ fieldname: "to_posting_date", fieldtype: "Date", label: __("To") },
				{ fieldtype: "Section Break", label: __("Due Date") },
				{ fieldname: "from_due_date", fieldtype: "Date", label: __("From") },
				{ fieldtype: "Column Break" },
				{ fieldname: "to_due_date", fieldtype: "Date", label: __("To") },
				{ fieldtype: "Section Break", label: __("Outstanding Amount") },
				{ fieldname: "from_amount", fieldtype: "Currency", label: __("Greater Than") },
				{ fieldtype: "Column Break" },
				{ fieldname: "to_amount", fieldtype: "Currency", label: __("Less Than") },
				{ fieldtype: "Section Break" },
				{
					fieldname: "cost_center",
					fieldtype: "Link",
					label: __("Cost Center"),
					options: "Cost Center",
					get_query: () => ({ filters: { company: frm.doc.company, is_group: 0 } }),
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "get_outstanding_invoices",
					fieldtype: "Check",
					label: __("Outstanding Invoices"),
					default: 1,
				},
				{
					fieldname: "get_orders_to_be_billed",
					fieldtype: "Check",
					label: __("Orders To Be Billed"),
					default: 0,
				},
			],
			primary_action_label: __("Get Documents"),
			primary_action(values) {
				d.hide();
				frm.events.pull_outstanding(frm, values);
			},
		});
		d.show();
	},

	pull_outstanding(frm, filters) {
		frappe.call({
			method: "vansale.sf_trading.doctype.payment_advice.payment_advice.get_outstanding_documents",
			args: Object.assign(
				{
					company: frm.doc.company,
					party_type: frm.doc.party_type,
					party: frm.doc.party,
				},
				filters || {}
			),
			freeze: true,
			freeze_message: __("Fetching outstanding documents…"),
			callback(r) {
				if (!r.message || !r.message.length) {
					frappe.msgprint({
						message: __("No outstanding documents for {0}.", [frm.doc.party]),
						indicator: "orange",
					});
					return;
				}

				const existing = new Set(
					(frm.doc.payment_advice_reference || []).map((d) => d.reference_record)
				);
				let added = 0;
				r.message.forEach((ref) => {
					if (existing.has(ref.reference_record)) return;
					const row = frm.add_child("payment_advice_reference");
					Object.assign(row, ref);
					added += 1;
				});

				frm.refresh_field("payment_advice_reference");
				frappe.show_alert(
					{
						message: __("{0} reference(s) added", [added]),
						indicator: added ? "green" : "orange",
					},
					5
				);

				// branch + cost centre from the fetched rows, if the advice has none yet
				const first = (frm.doc.payment_advice_reference || []).find((d) => d.cost_center);
				if (first && !frm.doc.cost_center) frm.set_value("cost_center", first.cost_center);
				if (!frm.doc.branch) frm.trigger("pull_branch_from_references");

				// default the authorised amount to everything now outstanding
				if (!frm.doc.payment_amount) {
					const total = (frm.doc.payment_advice_reference || []).reduce(
						(sum, d) => sum + flt(d.net_payable_amount),
						0
					);
					frm.set_value("payment_amount", total);
				}
			},
		});
	},

	pull_branch_from_references(frm) {
		const row = (frm.doc.payment_advice_reference || []).find((d) => d.reference_record);
		if (!row) return;

		frappe.call({
			method: "vansale.sf_trading.doctype.payment_advice.payment_advice.get_reference_details",
			args: {
				reference_doctype: row.reference_doctype,
				reference_record: row.reference_record,
				company: frm.doc.company,
				party_type: frm.doc.party_type,
				party: frm.doc.party,
			},
			callback(r) {
				if (!r.message) return;
				if (r.message.parent_branch && !frm.doc.branch) {
					frm.set_value("branch", r.message.parent_branch);
				}
				if (r.message.parent_cost_center && !frm.doc.cost_center) {
					frm.set_value("cost_center", r.message.parent_cost_center);
				}
			},
		});
	},

	branch(frm) {
		// a branch change re-points the cost centre, unless one was chosen by hand
		if (!frm.doc.branch || frm.doc.cost_center) return;
		frappe.call({
			method: "vansale.sf_trading.doctype.payment_advice.payment_advice.get_branch_default_cost_center",
			args: { branch: frm.doc.branch, company: frm.doc.company },
			callback(r) {
				if (r.message) frm.set_value("cost_center", r.message);
			},
		});
	},

	make_payment_entry(frm) {
		frappe.confirm(
			__("Create a Payment Entry of {0} for {1}?", [
				format_currency(frm.doc.payment_amount),
				frm.doc.party_name || frm.doc.party,
			]),
			() => {
				frappe.call({
					method: "vansale.sf_trading.doctype.payment_advice.payment_advice.create_payment_entry",
					args: { payment_advice: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating Payment Entry…"),
					callback(r) {
						if (r.message) {
							frappe.set_route("Form", "Payment Entry", r.message);
						}
					},
				});
			}
		);
	},

	show_allocation_summary(frm) {
		if (!frm.doc.payment_advice_reference || !frm.doc.payment_advice_reference.length) {
			frm.dashboard.clear_headline();
			return;
		}

		const allocated = frm.doc.payment_advice_reference.reduce(
			(sum, d) => sum + flt(d.allocated_amount),
			0
		);
		const unallocated = flt(frm.doc.payment_amount) - allocated;
		const rows_paid = frm.doc.payment_advice_reference.filter(
			(d) => flt(d.allocated_amount) > 0
		).length;

		let msg = __("{0} of {1} allocated across {2} of {3} reference(s)", [
			format_currency(allocated),
			format_currency(frm.doc.payment_amount),
			rows_paid,
			frm.doc.payment_advice_reference.length,
		]);
		if (unallocated > 0.0005) {
			msg += " — " + __("{0} unallocated", [format_currency(unallocated)]);
		}
		frm.dashboard.set_headline(msg);
	},

	payment_advice_type(frm) {
		frm.trigger("toggle_buttons");
	},

	company(frm) {
		frm.trigger("toggle_buttons");
		// company drives every other picker; clear what no longer applies
		["bank_account", "cost_center", "project"].forEach((f) => frm.set_value(f, null));
		if (!frm.doc.transaction_currency) {
			frappe.db.get_value("Company", frm.doc.company, "default_currency").then((r) => {
				if (r && r.message) frm.set_value("transaction_currency", r.message.default_currency);
			});
		}
	},

	party_type(frm) {
		// the allowed reference doctypes change with the party type, so drop what no longer fits
		frm.clear_table("payment_advice_reference");
		frm.refresh_field("payment_advice_reference");

		// Outward pays suppliers, Inward collects from customers — keep the two in step so a
		// customer advice is never labelled Outward
		frm.set_value(
			"payment_advice_type",
			frm.doc.party_type === "Customer" ? "Inward" : "Outward"
		);
		frm.trigger("toggle_buttons");
		frm.set_value("party", null);
		frm.set_value("party_name", null);
		frm.clear_table("payment_advice_reference");
		frm.refresh_field("payment_advice_reference");
	},

	party(frm) {
		frm.clear_table("payment_advice_reference");
		frm.refresh_field("payment_advice_reference");
		frm.set_value("payment_amount", 0);
		frm.trigger("toggle_buttons");   // the button depends on party being set
	},

	mode_of_payment(frm) {
		// mirror Payment Entry: a Bank account demands a reference no and date
		if (!frm.doc.mode_of_payment || !frm.doc.company) return;
		frappe.call({
			method: "vansale.sf_trading.doctype.payment_advice.payment_advice.mode_needs_reference",
			args: { company: frm.doc.company, mode_of_payment: frm.doc.mode_of_payment },
			callback(r) {
				if (!r.message) return;
				frm.set_df_property("reference_no", "reqd", 1);
				frm.set_df_property("reference_date", "reqd", 1);
				if (!frm.doc.reference_date) frm.set_value("reference_date", frappe.datetime.get_today());
				frappe.show_alert(
					{ message: __("Bank payment — reference no and date are required"), indicator: "blue" },
					6
				);
			},
		});
	},

	payment_amount(frm) {
		frm.trigger("toggle_buttons");   // Payment Entry offers its fetch at this point too
		frm.trigger("show_allocation_summary");
	},

	recalculate_payment_amount(frm) {
		// while drafting, keep the authorised amount equal to what the rows now total, unless
		// the user has deliberately typed a smaller figure
		const payable = (frm.doc.payment_advice_reference || []).reduce(
			(sum, d) => sum + flt(d.net_payable_amount),
			0
		);
		if (!frm.doc.payment_amount || flt(frm.doc.payment_amount) > payable) {
			frm.set_value("payment_amount", payable);
		}
		frm.trigger("show_allocation_summary");
	},
});

frappe.ui.form.on("Payment Advice Reference", {
	// Manual entry, the way Payment Entry does it: choose the document and the row fills
	// itself — amount, outstanding, ageing, currency, cost centre, live status — with the
	// company/party/duplicate checks applied at the moment of picking.
	reference_record(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.reference_doctype || !row.reference_record) return;

		if (!frm.doc.company || !frm.doc.party) {
			frappe.msgprint(__("Set Company and Party before adding references."));
			frappe.model.set_value(cdt, cdn, "reference_record", null);
			return;
		}

		frappe.call({
			method: "vansale.sf_trading.doctype.payment_advice.payment_advice.get_reference_details",
			args: {
				reference_doctype: row.reference_doctype,
				reference_record: row.reference_record,
				company: frm.doc.company,
				party_type: frm.doc.party_type,
				party: frm.doc.party,
			},
			callback(r) {
				if (!r.message) return;

				// the parent hints travel alongside the row fields; apply them first, then
				// only the real row fields go onto the row
				const parent_branch = r.message.parent_branch;
				const parent_cost_center = r.message.parent_cost_center;
				delete r.message.parent_branch;
				delete r.message.parent_cost_center;

				Object.keys(r.message).forEach((field) => {
					frappe.model.set_value(cdt, cdn, field, r.message[field]);
				});

				// branch and cost centre follow the voucher, but never overwrite a choice
				if (parent_branch && !frm.doc.branch) frm.set_value("branch", parent_branch);
				if (parent_cost_center && !frm.doc.cost_center) {
					frm.set_value("cost_center", parent_cost_center);
				}

				frm.trigger("recalculate_payment_amount");
			},
			error() {
				// the server explained why; clear the pick so the row is not half-filled
				frappe.model.set_value(cdt, cdn, "reference_record", null);
			},
		});
	},

	reference_doctype(frm, cdt, cdn) {
		// changing the type invalidates whatever was picked
		frappe.model.set_value(cdt, cdn, "reference_record", null);
	},

	payment_advice_reference_remove(frm) {
		frm.trigger("recalculate_payment_amount");
		frm.trigger("show_allocation_summary");
	},

	net_payable_amount(frm) {
		frm.trigger("show_allocation_summary");
	},
});
