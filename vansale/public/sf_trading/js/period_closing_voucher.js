// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

// Open item census on the Period Closing Voucher form. Saved drafts only —
// the numbers are live (recomputed on every refresh), so an unsaved form has
// nothing committed to judge yet, and a submitted voucher's census would no
// longer describe the moment it was submitted. Renders through `refresh`
// alone: field edits do not redraw until the document is saved.

frappe.ui.form.on("Period Closing Voucher", {
	refresh(frm) {
		render_open_items(frm);
	},
});

function render_open_items(frm) {
	if (
		frm.doc.docstatus !== 0 ||
		frm.is_new() ||
		!frm.doc.company ||
		!frm.doc.period_end_date
	) {
		return;
	}

	// stale-response guard: only the latest request may draw
	const seq = (frm._sf_open_items_seq = (frm._sf_open_items_seq || 0) + 1);

	frappe.call({
		method: "vansale.sf_trading.period_closing.pending_open_items",
		args: {
			company: frm.doc.company,
			period_end_date: frm.doc.period_end_date,
		},
		callback(r) {
			if (!r.message || seq !== frm._sf_open_items_seq) return;

			// replace, never stack — an earlier section may survive a partial refresh
			if (frm._sf_open_items_section) {
				frm._sf_open_items_section.remove();
				frm._sf_open_items_section = null;
			}

			const rows = r.message.rows || [];
			const enforced = !!r.message.enforced;
			const total_items = rows.reduce((sum, row) => sum + row.items, 0);
			const currency = frappe.get_doc(":Company", frm.doc.company)?.default_currency;

			let html;
			if (!total_items) {
				html = `<div class="text-muted">
					${frappe.utils.icon("check", "sm")}
					${__("No open items up to {0} — clear to submit.", [
						frappe.datetime.str_to_user(frm.doc.period_end_date),
					])}
				</div>`;
			} else {
				const body = rows
					.filter((row) => row.items)
					.map(
						(row) => `<tr>
							<td><a href="#" data-report="${encodeURIComponent(row.report)}"
								class="sf-open-items-link">${__(row.report)}</a></td>
							<td class="text-right">${row.documents}</td>
							<td class="text-right">${row.items}</td>
							<td class="text-right">${row.qty}</td>
							<td class="text-right">${format_currency(row.value, currency)}</td>
						</tr>`
					)
					.join("");
				// the same list either blocks or informs, depending on the company switch
				const intro = enforced
					? `<p class="text-danger">${__(
							"These must be cleared before this voucher can be submitted:"
						)}</p>`
					: `<p class="text-muted">${__(
							"Open items in this period. Submission is not blocked — turn on {0} on the Company to enforce it.",
							[__("Block Period Closing on Open Items")]
						)}</p>`;
				html = `<div>
					${intro}
					<table class="table table-bordered table-sm">
						<thead><tr>
							<th>${__("Pending")}</th>
							<th class="text-right">${__("Documents")}</th>
							<th class="text-right">${__("Items")}</th>
							<th class="text-right">${__("Qty")}</th>
							<th class="text-right">${__("Value")}</th>
						</tr></thead>
						<tbody>${body}</tbody>
					</table>
				</div>`;
			}

			const section = frm.dashboard.add_section(html, __("Open Items"));
			frm._sf_open_items_section = section;
			section.on("click", ".sf-open-items-link", function (e) {
				e.preventDefault();
				frappe.route_options = {
					company: frm.doc.company,
					as_on: frappe.datetime.get_today(),
				};
				frappe.set_route(
					"query-report",
					decodeURIComponent($(this).attr("data-report"))
				);
			});
			frm.dashboard.show();
		},
	});
}
