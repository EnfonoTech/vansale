// apps/vansale/vansale/sf_trading/page/payment_advice_builder/payment_advice_builder.js
// Payment Advice Builder — sweep outstanding vouchers, group them by party, tick what to
// pay, and raise one Payment Advice per party in a single action.
//
// Every figure shown here comes from the server (ERPNext's Payment Entry outstanding
// engine), so what you tick is what gets allocated. Nothing is submitted: advices are
// created as drafts unless "Submit created advices" is ticked, and submission still obeys
// the advice's approver rule.

frappe.pages["payment-advice-builder"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Payment Advice Builder"),
		single_column: true,
	});
	new PaymentAdviceBuilder(page);
};

class PaymentAdviceBuilder {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.selected = new Map(); // party -> Set(reference_record)
		this.make_filters();
		this.make_actions();
		this.body = $('<div class="pab-body">').appendTo(this.page.main);
		this.render_empty(__("Set your filters and hit Fetch Outstanding."));
	}

	// ── filters ──────────────────────────────────────────────────────────────────
	make_filters() {
		this.filters = {};
		const add = (df) => {
			this.filters[df.fieldname] = this.page.add_field(df);
		};

		add({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
			change: () => this.render_empty(__("Filters changed — fetch again.")),
		});
		add({
			fieldname: "party_type",
			label: __("Party Type"),
			fieldtype: "Select",
			options: ["Supplier", "Customer"].join("\n"),
			default: "Supplier",
			change: () => {
				if (this.filters.party) this.filters.party.set_value("");
				this.render_empty(__("Party type changed — fetch again."));
			},
		});
		// A Dynamic Link outside a form has no doc to read `options` from, so it must be told
		// which doctype to query. frappe's ControlDynamicLink calls df.get_options(this) when
		// present — without it the party picker returned nothing at all.
		add({
			fieldname: "party",
			label: __("Party"),
			fieldtype: "Dynamic Link",
			get_options: () => this.filters.party_type.get_value() || "Supplier",
		});
		add({
			fieldname: "due_before",
			label: __("Due On or Before"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		});
		add({ fieldname: "min_ageing", label: __("Ageing Over (days)"), fieldtype: "Int" });
		add({
			fieldname: "minimum_total",
			label: __("Min Advice Total"),
			fieldtype: "Currency",
			default: 1,
			description: __("Parties whose total falls below this are skipped as rounding residue."),
		});
		add({
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
		});
		add({ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" });
		add({ fieldname: "ignore_on_hold", label: __("Include On-Hold Parties"), fieldtype: "Check" });
	}

	get_filters() {
		const values = {};
		Object.keys(this.filters).forEach((key) => {
			const value = this.filters[key].get_value();
			if (value) values[key] = value;
		});
		return values;
	}

	// ── toolbar ──────────────────────────────────────────────────────────────────
	make_actions() {
		this.page.set_primary_action(__("Fetch Outstanding"), () => this.fetch(), "refresh");
		this.page.add_menu_item(__("Select All Payable"), () => this.select_all(true));
		this.page.add_menu_item(__("Clear Selection"), () => this.select_all(false));
	}

	// ── data ─────────────────────────────────────────────────────────────────────
	fetch() {
		const filters = this.get_filters();
		if (!filters.company) {
			frappe.msgprint(__("Pick a company first."));
			return;
		}

		frappe.call({
			method: "vansale.sf_trading.api.payment_advice_builder.get_builder_data",
			args: { filters: filters },
			freeze: true,
			freeze_message: __("Sweeping outstanding vouchers…"),
			callback: (r) => {
				this.data = r.message;
				this.selected.clear();
				this.render();
			},
		});
	}

	select_all(on) {
		if (!this.data) return;
		this.data.groups.forEach((group) => {
			if (group.skip) return;
			if (on) {
				this.selected.set(group.party, new Set(group.rows.map((row) => String(row.reference_record))));
			} else {
				this.selected.delete(group.party);
			}
		});
		this.render();
	}

	// ── render ───────────────────────────────────────────────────────────────────
	render_empty(message) {
		this.body.html(
			`<div class="text-muted" style="padding:2rem;text-align:center">${frappe.utils.escape_html(
				message
			)}</div>`
		);
	}

	render() {
		if (!this.data || !this.data.groups.length) {
			this.render_empty(__("Nothing outstanding for these filters."));
			return;
		}

		const payable = this.data.groups.filter((g) => !g.skip);
		const skipped = this.data.groups.filter((g) => g.skip);

		this.body.empty();
		this.render_summary(payable, skipped);
		payable.forEach((group) => this.render_group(group));
		if (skipped.length) this.render_skipped(skipped);
		this.render_footer();
		this.bind_events();
		this.update_totals();
	}

	render_summary(payable, skipped) {
		$(`
			<div class="pab-summary" style="display:flex;gap:2rem;flex-wrap:wrap;padding:1rem 0;border-bottom:1px solid var(--border-color)">
				<div><div class="text-muted small">${__("Parties")}</div><div class="h5">${payable.length}</div></div>
				<div><div class="text-muted small">${__("Vouchers")}</div><div class="h5">${this.data.totals.vouchers}</div></div>
				<div><div class="text-muted small">${__("Outstanding")}</div><div class="h5">${format_currency(
			this.data.totals.outstanding,
			this.data.currency
		)}</div></div>
				<div><div class="text-muted small">${__("Skipped")}</div><div class="h5">${skipped.length}</div></div>
			</div>
		`).appendTo(this.body);
	}

	render_group(group) {
		const rows = group.rows
			.map(
				(row) => `
			<tr>
				<td><input type="checkbox" class="pab-row" data-party="${frappe.utils.escape_html(
					group.party
				)}" data-ref="${frappe.utils.escape_html(row.reference_record)}"></td>
				<td>${frappe.utils.escape_html(row.reference_doctype)}</td>
				<td><a href="/app/${frappe.router.slug(row.reference_doctype)}/${encodeURIComponent(
					row.reference_record
				)}" target="_blank">${frappe.utils.escape_html(row.reference_record)}</a></td>
				<td>${frappe.utils.escape_html(row.bill_no || "")}</td>
				<td>${frappe.datetime.str_to_user(row.date) || ""}</td>
				<td class="text-right ${row.ageing > 90 ? "text-danger" : ""}">${row.ageing}</td>
				<td>${frappe.utils.escape_html(row.reference_status || "")}</td>
				<td class="text-right">${format_currency(row.net_payable_amount, row.currency)}</td>
			</tr>`
			)
			.join("");

		$(`
			<div class="pab-group" style="margin:1rem 0;border:1px solid var(--border-color);border-radius:var(--border-radius-md)">
				<div style="display:flex;align-items:center;gap:.75rem;padding:.75rem 1rem;background:var(--fg-color)">
					<input type="checkbox" class="pab-group-check" data-party="${frappe.utils.escape_html(group.party)}">
					<b>${frappe.utils.escape_html(group.party_name)}</b>
					<span class="text-muted small">${frappe.utils.escape_html(group.party)}</span>
					${group.on_hold ? `<span class="indicator-pill orange">${__("On Hold")}</span>` : ""}
					${
						group.bank_account
							? ""
							: `<span class="indicator-pill gray" title="${__(
									"No party bank account on file"
							  )}">${__("No bank account")}</span>`
					}
					<span style="margin-left:auto" class="text-muted small">${group.voucher_count} ${__(
			"voucher(s)"
		)} · ${__("oldest")} ${group.oldest_ageing}${__("d")}</span>
					<b>${format_currency(group.total_outstanding, this.data.currency)}</b>
				</div>
				<table class="table table-sm" style="margin:0">
					<thead><tr class="text-muted small">
						<th style="width:32px"></th><th>${__("Type")}</th><th>${__("Document")}</th>
						<th>${__("Party Doc No")}</th><th>${__("Date")}</th>
						<th class="text-right">${__("Ageing")}</th><th>${__("Status")}</th>
						<th class="text-right">${__("Outstanding")}</th>
					</tr></thead>
					<tbody>${rows}</tbody>
				</table>
			</div>
		`).appendTo(this.body);
	}

	render_skipped(skipped) {
		const items = skipped
			.map(
				(group) =>
					`<li>${frappe.utils.escape_html(group.party_name)} — <span class="text-muted">${
						frappe.utils.escape_html(group.skip_label || group.skip)
					}</span></li>`
			)
			.join("");
		$(`
			<div style="margin:1.5rem 0;padding:1rem;border:1px dashed var(--border-color);border-radius:var(--border-radius-md)">
				<div class="text-muted" style="margin-bottom:.5rem">${__("Skipped")} (${skipped.length})</div>
				<ul style="margin:0;padding-left:1.2rem">${items}</ul>
			</div>
		`).appendTo(this.body);
	}

	render_footer() {
		this.footer = $(`
			<div class="pab-footer" style="position:sticky;bottom:0;background:var(--fg-color);border-top:1px solid var(--border-color);padding:1rem;display:flex;align-items:center;gap:1rem">
				<div class="pab-selection text-muted"></div>
				<div style="margin-left:auto;display:flex;gap:.5rem">
					<button class="btn btn-default btn-sm pab-options">${__("Advice Options")}</button>
					<button class="btn btn-primary btn-sm pab-create" disabled>${__("Create Advices")}</button>
				</div>
			</div>
		`).appendTo(this.body);
		this.options = {};
	}

	bind_events() {
		// .attr(), never .data(): jQuery coerces a numeric-looking attribute to a Number, so a
		// voucher named 20020000006 came back as the number 20020000006 while the selection Set
		// holds the string. Nothing matched, the footer read "0 voucher(s)", and create() dropped
		// those rows from the advice without saying so.
		this.body.find(".pab-group-check").on("change", (e) => {
			const party = String($(e.currentTarget).attr("data-party"));
			const on = e.currentTarget.checked;
			const group = this.data.groups.find((g) => g.party === party);
			if (!group) return;
			if (on) {
				this.selected.set(party, new Set(group.rows.map((r) => String(r.reference_record))));
			} else {
				this.selected.delete(party);
			}
			e.currentTarget.indeterminate = false;
			this.body.find(".pab-row").filter((_i, el) => $(el).attr("data-party") === party)
				.prop("checked", on);
			this.update_totals();
		});

		this.body.find(".pab-row").on("change", (e) => {
			const el = $(e.currentTarget);
			const party = String(el.attr("data-party"));
			const ref = String(el.attr("data-ref"));
			if (!this.selected.has(party)) this.selected.set(party, new Set());
			const set = this.selected.get(party);
			e.currentTarget.checked ? set.add(ref) : set.delete(ref);
			if (!set.size) this.selected.delete(party);
			this.sync_group_check(party);
			this.update_totals();
		});

		this.body.find(".pab-options").on("click", () => this.edit_options());
		this.body.find(".pab-create").on("click", () => this.create());
	}

	sync_group_check(party) {
		// A party header that stays ticked while only some of its rows are ticked reads as though
		// everything is selected. Show the true state instead: ticked when all rows are in, dashed
		// when only some are.
		const group = this.data.groups.find((g) => g.party === party);
		if (!group) return;
		const set = this.selected.get(party) || new Set();
		const box = this.body.find(".pab-group-check")
			.filter((_i, el) => $(el).attr("data-party") === party)
			.get(0);
		if (!box) return;
		box.checked = set.size === group.rows.length && group.rows.length > 0;
		box.indeterminate = set.size > 0 && set.size < group.rows.length;
	}

	update_totals() {
		let parties = 0;
		let vouchers = 0;
		let amount = 0;

		this.selected.forEach((refs, party) => {
			const group = this.data.groups.find((g) => g.party === party);
			if (!group) return;
			// count the party only once it actually contributes a voucher, so a stale or unmatched
			// entry can never show as "1 party(ies), 0 voucher(s)" again
			let party_vouchers = 0;
			group.rows.forEach((row) => {
				if (refs.has(String(row.reference_record))) {
					party_vouchers += 1;
					amount += flt(row.net_payable_amount);
				}
			});
			if (party_vouchers) {
				parties += 1;
				vouchers += party_vouchers;
			}
		});

		this.body
			.find(".pab-selection")
			.html(
				parties
					? __("{0} party(ies), {1} voucher(s) — {2}", [
							parties,
							vouchers,
							`<b>${format_currency(amount, this.data.currency)}</b>`,
					  ])
					: __("Nothing selected")
			);
		this.body.find(".pab-create").prop("disabled", !parties);
	}

	edit_options() {
		const d = new frappe.ui.Dialog({
			title: __("Advice Options"),
			fields: [
				{
					fieldname: "mode_of_payment",
					label: __("Mode of Payment"),
					fieldtype: "Link",
					options: "Mode of Payment",
					default: this.options.mode_of_payment,
				},
				{
					fieldname: "bank_account",
					label: __("Company Bank Account"),
					fieldtype: "Link",
					options: "Bank Account",
					default: this.options.bank_account,
					get_query: () => ({
						filters: {
							company: this.get_filters().company,
							is_company_account: 1,
						},
					}),
				},
				{
					fieldname: "approver",
					label: __("Approver"),
					fieldtype: "Link",
					options: "User",
					get_query: () => ({ filters: { enabled: 1 } }),
					default: this.options.approver,
				},
				{
					fieldname: "cost_center",
					label: __("Cost Center"),
					fieldtype: "Link",
					options: "Cost Center",
					default: this.options.cost_center,
				},
				{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text", default: this.options.remarks },
				{
					fieldname: "submit",
					label: __("Submit created advices"),
					fieldtype: "Check",
					description: __("Submission still requires you to be the selected Approver."),
					default: this.options.submit,
				},
			],
			primary_action_label: __("Save Options"),
			primary_action: (values) => {
				this.options = values;
				d.hide();
				frappe.show_alert({ message: __("Options saved"), indicator: "green" }, 3);
			},
		});
		d.show();
	}

	create() {
		const filters = this.get_filters();
		const selections = [];

		this.selected.forEach((refs, party) => {
			const group = this.data.groups.find((g) => g.party === party);
			if (!group) return;
			const references = group.rows.filter((row) => refs.has(String(row.reference_record)));
			if (references.length) {
				selections.push({ party: party, references: references, bank_account: group.bank_account });
			}
		});

		const total = selections.reduce(
			(sum, s) => sum + s.references.reduce((rs, r) => rs + flt(r.net_payable_amount), 0),
			0
		);

		frappe.confirm(
			__("Create {0} Payment Advice(s) totalling {1}?", [
				selections.length,
				format_currency(total, this.data.currency),
			]),
			() => {
				frappe.call({
					method: "vansale.sf_trading.api.payment_advice_builder.create_advices",
					args: {
						selections: selections,
						options: Object.assign(
							{
								company: filters.company,
								party_type: filters.party_type || "Supplier",
							},
							this.options || {}
						),
					},
					freeze: true,
					freeze_message: __("Creating Payment Advices…"),
					callback: (r) => this.show_result(r.message),
				});
			}
		);
	}

	show_result(result) {
		if (!result) return;

		if (result.queued) {
			frappe.msgprint({ title: __("Queued"), message: result.message, indicator: "blue" });
			return;
		}

		const created = (result.created || [])
			.map(
				(row) =>
					`<li><a href="/app/payment-advice/${encodeURIComponent(row.advice)}" target="_blank">${
						row.advice
					}</a> — ${frappe.utils.escape_html(row.party)} — ${format_currency(row.amount)}</li>`
			)
			.join("");
		const failed = (result.failed || [])
			.map(
				(row) =>
					`<li>${frappe.utils.escape_html(row.party)} — <span class="text-danger">${
						frappe.utils.escape_html(row.error)
					}</span></li>`
			)
			.join("");

		frappe.msgprint({
			title: __("Payment Advices"),
			indicator: failed ? "orange" : "green",
			message: `
				<p>${__("Created")}: <b>${(result.created || []).length}</b> — ${format_currency(
				result.total_amount
			)}</p>
				${created ? `<ul>${created}</ul>` : ""}
				${failed ? `<p>${__("Failed")}:</p><ul>${failed}</ul>` : ""}
			`,
		});

		this.fetch(); // re-sweep so what was just advised drops out of the list
	}
}
