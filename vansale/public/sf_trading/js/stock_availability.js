// Stock Availability button for sf_trading
// Adds a "Stock Availability" button to the items grid toolbar on all transaction
// doctypes (except Sales Invoice, which uses the inline warehouse_stock_popup).
// Clicking the button opens a dialog showing per-warehouse stock for a selected item.

frappe.provide("sf_trading");

sf_trading.add_stock_availability_button = function(frm) {
	if (!frm.fields_dict.items || !frm.fields_dict.items.grid) return;

	const grid = frm.fields_dict.items.grid;

	// Track the last clicked / focused row by reference (cdt + name), NOT by
	// item_code. Reading item_code from locals at button-click time ensures we
	// always get the current value even after the user changed the item in that row.
	if (!grid.wrapper.data("sf_stock_avail_click_bound")) {
		const remember = function(e) {
			const $body = grid.wrapper.find(".grid-body");
			if (!$body.length || !$body[0].contains(e.target)) return;
			const $row = $(e.target).closest(".grid-row");
			if (!$row.length) return;
			const grid_row = $row.data("grid_row");
			if (grid_row && grid_row.doc) {
				frm._sf_stock_avail_row_cdt = grid_row.doc.doctype;
				frm._sf_stock_avail_row_cdn = grid_row.doc.name;
			}
		};
		grid.wrapper[0].addEventListener("click", remember, true);
		grid.wrapper[0].addEventListener("focusin", remember, true);
		grid.wrapper.data("sf_stock_avail_click_bound", true);
	}

	let $toolbar = grid.wrapper.find(".grid-buttons");
	if (!$toolbar.length) $toolbar = grid.wrapper.find(".grid-footer .grid-buttons");
	if (!$toolbar.length) return;

	if ($toolbar.find("button:contains('Stock Availability')").length > 0) return;

	let $target = $toolbar.find("button:contains('Add Multiple')").last();
	if (!$target.length) $target = $toolbar.find("button:contains('Add Row')").last();

	const btn = $(
		`<button type="button" class="btn btn-secondary btn-xs" style="margin-left: 10px;">${__(
			"Stock Availability"
		)}</button>`
	);
	btn.on("click", function() {
		const default_item = sf_trading.get_default_item_for_stock_availability(frm);
		sf_trading.open_stock_availability_dialog(frm, default_item);
	});

	if ($target.length > 0 && $target.parent().is($toolbar)) {
		btn.insertAfter($target);
	} else {
		$toolbar.append(btn);
	}
};

sf_trading.get_default_item_for_stock_availability = function(frm) {
	if (!frm || !frm.fields_dict.items || !frm.fields_dict.items.grid) return null;
	const items_grid = frm.fields_dict.items.grid;

	// 1. Row form currently open — live doc reference, always up-to-date.
	const open_row = frappe.ui.form.get_open_grid_form();
	if (open_row && open_row.grid === items_grid && open_row.doc && open_row.doc.item_code) {
		return open_row.doc.item_code;
	}
	// 2. Last focused row — read from locals (current value, not cached item_code).
	if (frm._sf_stock_avail_row_cdt && frm._sf_stock_avail_row_cdn) {
		const current = (locals[frm._sf_stock_avail_row_cdt] || {})[frm._sf_stock_avail_row_cdn];
		if (current && current.item_code) return current.item_code;
	}
	// 3. Fallback: last row in the table.
	if (frm.doc.items && frm.doc.items.length) {
		const last = frm.doc.items[frm.doc.items.length - 1];
		if (last && last.item_code) return last.item_code;
	}
	return null;
};

sf_trading.open_stock_availability_dialog = function(frm, default_item_code) {
	const company = frm.doc.company || frappe.defaults.get_default("company");

	const d = new frappe.ui.Dialog({
		title: __("Stock Availability"),
		fields: [
			{
				fieldname: "item_code",
				label: __("Item Code"),
				fieldtype: "Link",
				options: "Item",
				default: default_item_code,
				get_query: function() {
					return {
						query: "erpnext.controllers.queries.item_query",
						filters: { "company": company }
					};
				},
			},
			{
				fieldname: "item_name",
				label: __("Item Name"),
				fieldtype: "Data",
				read_only: 1,
			},
			{ fieldname: "results", fieldtype: "HTML" },
		],
		size: "extra-large",
		primary_action_label: __("Close"),
		primary_action: function() { d.hide(); },
	});

	d.show();

	const _load = function(item_code) {
		if (!item_code) {
			d.set_value("item_name", "");
			d.fields_dict.results.$wrapper.html("");
			return;
		}
		frappe.db.get_value("Item", item_code, "item_name", function(r) {
			d.set_value("item_name", (r && r.item_name) || "");
		});
		sf_trading.fetch_stock_availability(item_code, company, d);
	};

	setTimeout(() => {
		if (d.fields_dict.item_code) {
			d.fields_dict.item_code.df.onchange = function() {
				_load(d.get_value("item_code"));
			};
			d.fields_dict.item_code.refresh();
		}
		if (default_item_code) {
			_load(default_item_code);
		}
	}, 200);
};

sf_trading.fetch_stock_availability = function(item_code, company, dialog) {
	dialog.fields_dict.results.$wrapper.html(
		'<div class="text-muted">' + __("Loading…") + "</div>"
	);

	frappe.call({
		method: "vansale.sf_trading.api.warehouse_stock.get_item_warehouse_stock",
		args: { item_code: item_code, company: company },
		callback: function(r) {
			const rows = r.message || [];
			if (!rows.length) {
				dialog.fields_dict.results.$wrapper.html(
					'<div class="text-muted">' + __("No stock found for this item.") + "</div>"
				);
				return;
			}
			dialog.fields_dict.results.$wrapper.html(
				sf_trading.render_stock_availability_table(rows)
			);
			setTimeout(() => sf_trading.setupStockAvailabilityFilters(dialog), 100);
		},
		error: function(err) {
			dialog.fields_dict.results.$wrapper.html(
				'<div class="text-danger">' +
					__("Error fetching stock: {0}", [err.message || err]) +
					"</div>"
			);
		},
	});
};

sf_trading.render_stock_availability_table = function(rows) {
	var out = [
		'<div class="mt-3">',
		'<table class="table table-bordered table-sm" id="stock-avail-table">',
		"<thead>",
		"<tr>",
		"<th>" + __("Warehouse") + "</th>",
		'<th class="text-right">' + __("Stock Qty") + "</th>",
		"<th>" + __("UOM") + "</th>",
		"</tr>",
		'<tr class="filter-row">',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __("Filter Warehouse") + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __("Filter Qty") + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __("Filter UOM") + '"></th>',
		"</tr>",
		"</thead>",
		"<tbody>",
	].join("");

	rows.forEach(function(r) {
		const wh_name = frappe.utils.escape_html(r.warehouse_name || r.warehouse || "");
		const qty = format_number(r.stock_qty || 0, null, { precision: 2 });
		const uom = frappe.utils.escape_html(r.uom || "");
		const color = r.stock_qty > 0 ? "#28a745" : "#6c757d";
		const indicator = r.stock_qty > 0 ? "●" : "○";

		out += [
			"<tr>",
			`<td><span style="color:${color};margin-right:5px;font-size:12px;">${indicator}</span>${wh_name}</td>`,
			`<td class="text-right"><strong style="color:${color};">${qty}</strong></td>`,
			`<td>${uom}</td>`,
			"</tr>",
		].join("");
	});

	out += "</tbody></table></div>";
	return out;
};

sf_trading.setupStockAvailabilityFilters = function(dialog) {
	const table = dialog.fields_dict.results.$wrapper.find("#stock-avail-table")[0];
	if (!table) return;
	const inputs = table.querySelectorAll(".filter-row input");
	inputs.forEach(function(input) {
		if (input._filterHandler) input.removeEventListener("input", input._filterHandler);
		input._filterHandler = function() { sf_trading.applyAllStockAvailabilityFilters(dialog); };
		input.addEventListener("input", input._filterHandler);
	});
};

sf_trading.applyAllStockAvailabilityFilters = function(dialog) {
	const table = dialog.fields_dict.results.$wrapper.find("#stock-avail-table")[0];
	if (!table) return;
	const rows = table.querySelectorAll("tbody tr");
	const inputs = table.querySelectorAll(".filter-row input");
	rows.forEach(function(row) {
		let show = true;
		inputs.forEach(function(input, j) {
			const val = input.value.toLowerCase().trim();
			if (!val) return;
			const cell = row.cells[j];
			if (cell && (cell.textContent || "").toLowerCase().indexOf(val) === -1) show = false;
		});
		row.style.display = show ? "" : "none";
	});
};

// All transaction doctypes with items tables.
// Sales Invoice is excluded — it uses the inline warehouse_stock_popup instead.
const _sf_stock_avail_doctypes = [
	"Sales Order",
	"Quotation",
	"Delivery Note",
	"Purchase Invoice",
	"Purchase Order",
	"Purchase Receipt",
	"Supplier Quotation",
	"Material Request",
	"Stock Entry",
];

_sf_stock_avail_doctypes.forEach(function(doctype) {
	frappe.ui.form.on(doctype, {
		refresh: function(frm) {
			let attempts = 0;
			const maxAttempts = 8;
			const tryAddButton = function() {
				attempts++;
				if (frm.fields_dict.items && frm.fields_dict.items.grid) {
					sf_trading.add_stock_availability_button(frm);
					const $toolbar = frm.fields_dict.items.grid.wrapper.find(".grid-buttons");
					if ($toolbar.find("button:contains('Stock Availability')").length > 0) return;
				}
				if (attempts < maxAttempts) setTimeout(tryAddButton, 400);
			};
			setTimeout(tryAddButton, 800);
		},
		items_add: function(frm) {
			setTimeout(function() {
				sf_trading.add_stock_availability_button(frm);
			}, 800);
		},
	});
});
