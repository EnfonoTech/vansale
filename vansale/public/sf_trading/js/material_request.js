// Material Request enhancements for sf_trading
// - Priority field colour indicator in the form header
// - Transfer Status inline section below items table (submitted Material Transfer MRs)

frappe.provide("sf_trading");

const _MR_PRIORITY_COLOR = {
	High:   { bg: "#fde8e8", text: "#c0392b", border: "#e74c3c" },
	Medium: { bg: "#fff8e1", text: "#b7770d", border: "#f39c12" },
	Low:    { bg: "#e8f5e9", text: "#1e7e34", border: "#27ae60" },
};

sf_trading.mr_show_priority_badge = function(frm) {
	frm.toolbar.page.inner_toolbar.find(".sf-priority-badge").remove();
	const priority = frm.doc.custom_priority;
	if (!priority) return;
	const c = _MR_PRIORITY_COLOR[priority] || {};
	const badge = $(
		`<span class="sf-priority-badge" style="
			display:inline-block; padding:2px 10px; border-radius:10px; font-size:12px;
			font-weight:600; margin-left:8px;
			background:${c.bg || "#eee"}; color:${c.text || "#333"};
			border:1px solid ${c.border || "#ccc"};">${__(priority)}</span>`
	);
	frm.toolbar.page.inner_toolbar.find(".title-area").append(badge);
};

sf_trading.mr_show_transfer_status = function(frm) {
	if (frm.fields_dict.items) {
		frm.fields_dict.items.$wrapper.parent().find(".sf-transfer-status").remove();
	}

	if (frm.doc.docstatus !== 1 || frm.doc.material_request_type !== "Material Transfer") return;
	if (!frm.fields_dict.items) return;

	frappe.call({
		method: "vansale.sf_trading.api.material_request_progress.get_transfer_progress",
		args: { material_request: frm.doc.name },
		callback: function(r) {
			const rows = r.message || [];
			if (!rows.length) return;

			let html = '<div class="sf-transfer-status" style="margin-top:15px; padding:12px; border:1px solid #d1d8dd; border-radius:8px; background:#fafbfc;">';
			html += '<h6 style="margin-bottom:10px; font-weight:600; color:#333;">' + __("Transfer Status") + '</h6>';
			html += '<table class="table table-bordered table-sm" style="margin-bottom:0; font-size:12px;">';
			html += '<thead style="background:#f5f7fa;"><tr>';
			html += '<th>' + __("Item") + '</th>';
			html += '<th style="text-align:right">' + __("Requested") + '</th>';
			html += '<th style="text-align:right">' + __("Transferred") + '</th>';
			html += '<th style="text-align:right">' + __("Pending") + '</th>';
			html += '<th style="text-align:center">' + __("Status") + '</th>';
			html += '</tr></thead><tbody>';

			rows.forEach(function(row) {
				const requested   = flt(row.required_qty);
				const transferred = flt(row.transferred_qty);
				const pending     = flt(row.pending_qty);

				let status_badge;
				if (pending <= 0) {
					status_badge = '<span class="indicator-pill green" style="font-size:11px">' + __("Completed") + '</span>';
				} else if (transferred > 0) {
					status_badge = '<span class="indicator-pill orange" style="font-size:11px">' + __("Partial") + '</span>';
				} else {
					status_badge = '<span class="indicator-pill red" style="font-size:11px">' + __("Pending") + '</span>';
				}

				html += '<tr>';
				html += '<td>' + frappe.utils.escape_html(row.item_code || '') +
					' — <span style="color:#888">' + frappe.utils.escape_html(row.item_name || '') + '</span></td>';
				html += '<td style="text-align:right">' + requested + '</td>';
				html += '<td style="text-align:right; color:#10b981; font-weight:600">' + transferred + '</td>';
				html += '<td style="text-align:right; color:' + (pending > 0 ? '#e94560' : '#10b981') + '; font-weight:600">' + pending + '</td>';
				html += '<td style="text-align:center">' + status_badge + '</td>';
				html += '</tr>';
			});

			html += '</tbody></table></div>';

			frm.fields_dict.items.$wrapper.parent().append(html);
		},
	});
};

// Purchase MR: show a headline banner pointing back to the Transfer MR —
// but only while the Transfer MR is still pending (hide once transferred/stopped).
sf_trading.mr_show_source_transfer = function (frm) {
	frm.dashboard.clear_headline();
	if (frm.doc.material_request_type !== "Purchase") return;

	var sources = {};
	(frm.doc.items || []).forEach(function (row) {
		if (row.custom_source_mr) sources[row.custom_source_mr] = true;
	});
	var source_list = Object.keys(sources);
	if (!source_list.length) return;

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Material Request",
			filters: [["name", "in", source_list]],
			fields: ["name", "status", "docstatus"],
		},
		callback: function (r) {
			var mrs = (r.message || []).filter(function (mr) { return mr.docstatus !== 2; });
			if (!mrs.length) return;

			var parts = mrs.map(function (mr) {
				var is_done = mr.status === "Transferred" || mr.status === "Stopped";
				var color = is_done ? "#16a34a" : "#d97706";
				var icon = is_done ? "&#10003;" : "&#9888;";
				return '<span style="color:' + color + '; font-weight:600;">' + icon + ' '
					+ '<a href="/app/material-request/' + encodeURIComponent(mr.name) + '" style="color:' + color + ';">'
					+ frappe.utils.escape_html(mr.name) + '</a>'
					+ ' (' + __(mr.status) + ')</span>';
			});

			frm.dashboard.set_headline(
				__("Transfer Request: {0}", [parts.join("&nbsp;&nbsp;")])
			);
		},
	});
};

// Transfer MR: show linked Purchase MRs below the items table, and show
// "Create → Purchase Request" only when at least one item has no PR yet.
sf_trading.mr_show_purchase_connections = function (frm) {
	if (frm.fields_dict.items) {
		frm.fields_dict.items.$wrapper.parent().find(".sf-purchase-connections").remove();
	}
	if (frm.doc.docstatus !== 1 || frm.doc.material_request_type !== "Material Transfer") return;

	frappe.call({
		method: "vansale.sf_trading.api.material_request.get_mr_purchase_connections",
		args: { transfer_mr: frm.doc.name },
		callback: function (r) {
			var data = r.message || {};
			var purchase_mrs = data.purchase_mrs || [];
			var covered = data.covered_item_codes || [];
			var all_items = (frm.doc.items || []).map(function (row) { return row.item_code; });
			var all_covered = all_items.length > 0
				&& all_items.every(function (code) { return covered.indexOf(code) !== -1; });

			if (!all_covered) {
				frm.add_custom_button(__("Purchase Request"), function () {
					frappe.model.open_mapped_doc({
						method: "vansale.sf_trading.api.material_request.make_purchase_request_from_mr",
						frm: frm,
					});
				}, __("Create"));
			}

			if (!purchase_mrs.length) return;

			var html = '<div class="sf-purchase-connections" style="margin-top:15px; padding:12px; border:1px solid #d1d8dd; border-radius:8px; background:#fafbfc;">';
			html += '<h6 style="margin-bottom:10px; font-weight:600; color:#333;">' + __("Purchase Requests") + '</h6>';
			html += '<table class="table table-bordered table-sm" style="margin-bottom:0; font-size:12px;">';
			html += '<thead style="background:#f5f7fa;"><tr>';
			html += '<th>' + __("Purchase Request") + '</th>';
			html += '<th>' + __("Date") + '</th>';
			html += '<th style="text-align:center">' + __("Status") + '</th>';
			html += '</tr></thead><tbody>';

			purchase_mrs.forEach(function (mr) {
				var color = mr.docstatus === 2 ? "red"
					: mr.status === "Ordered" ? "green"
					: mr.status === "Partially Ordered" ? "orange"
					: mr.status === "Stopped" ? "red"
					: "blue";
				html += '<tr>';
				html += '<td><a href="/app/material-request/' + encodeURIComponent(mr.name) + '">'
					+ frappe.utils.escape_html(mr.name) + '</a></td>';
				html += '<td>' + frappe.utils.escape_html(
					frappe.datetime.str_to_user(mr.transaction_date || "")) + '</td>';
				html += '<td style="text-align:center"><span class="indicator-pill ' + color
					+ '" style="font-size:11px">' + __(mr.status || "Draft") + '</span></td>';
				html += '</tr>';
			});

			html += '</tbody></table></div>';

			if (frm.fields_dict.items) {
				frm.fields_dict.items.$wrapper.parent().append(html);
			}
		},
	});
};

frappe.ui.form.on("Material Request", {
	refresh: function(frm) {
		sf_trading.mr_show_priority_badge(frm);
		sf_trading.mr_show_transfer_status(frm);
		sf_trading.mr_show_source_transfer(frm);
		sf_trading.mr_show_purchase_connections(frm);
	},

	custom_priority: function(frm) {
		sf_trading.mr_show_priority_badge(frm);
	},
});
