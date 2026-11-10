// sf_trading: Barcode scanner for Sales Invoice
// 1) Form-level "Scan Barcode" field: explicitly trigger ERPNext BarcodeScanner (add/increment items).
// 2) Row-level "Barcode" column: same behaviour when scanning in the items table.

frappe.provide("sf_trading");

const SCAN_FLAG = "sf_trading_barcode_scan";

function get_matching_row(frm, data, exclude_name) {
	const items = frm.doc.items || [];
	const uom = data.uom;
	const batch_no = data.batch_no;
	return items.find((d) => {
		if (d.name === exclude_name) return false;
		if (d.item_code !== data.item_code) return false;
		if (uom && d.uom !== uom) return false;
		if (batch_no && d.batch_no !== batch_no) return false;
		if (d.has_item_scanned) return false;
		return true;
	});
}

function set_barcode_scanner_flags(data) {
	if (data.batch_no || data.serial_no) {
		frappe.flags.trigger_from_barcode_scanner = true;
		frappe.flags.hide_serial_batch_dialog = true;
	}
}

function revert_barcode_scanner_flags() {
	frappe.flags.trigger_from_barcode_scanner = false;
	frappe.flags.hide_serial_batch_dialog = false;
}

function focus_grid_row(grid, idx) {
	if (grid && typeof grid.set_focus_on_row === "function") {
		setTimeout(() => grid.set_focus_on_row(idx), 150);
	}
}

// Focus qty (or rate) on the row with given doc name. Activates the row first so the control exists.
function focus_grid_cell(frm, grid, docname, fieldname) {
	if (!grid || !docname) return;
	fieldname = fieldname || "qty";
	// Wait for grid to finish rendering after refresh
	setTimeout(() => {
		const grid_row = grid.grid_rows_by_docname && grid.grid_rows_by_docname[docname];
		if (!grid_row || !grid_row.row) return;
		// Activate row so inline controls (and qty input) are created
		if (typeof grid_row.toggle_editable_row === "function") {
			grid_row.toggle_editable_row(true);
		}
		setTimeout(() => {
			// Prefer the control's $input (set when toggle_editable_row creates controls)
			const col = grid_row.columns && grid_row.columns[fieldname];
			if (col && col.field && col.field.$input && col.field.$input.length) {
				col.field.$input.focus();
				return;
			}
			// Fallback: find input in the cell by data-fieldname
			const $cell = grid_row.row.find('[data-fieldname="' + fieldname + '"]');
			const $input = $cell.find("input");
			if ($input.length && $input.first().is(":visible")) {
				$input.first().focus();
				return;
			}
			// Last resort: focus first input in row
			if (typeof grid.set_focus_on_row === "function") {
				const idx = grid_row.doc && grid_row.doc.idx;
				if (idx != null) grid.set_focus_on_row(idx - 1);
			}
		}, 100);
	}, 350);
}

function apply_barcode_scan(frm, cdt, cdn, data, row) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return Promise.resolve();

	set_barcode_scanner_flags(data);
	const existing = get_matching_row(frm, data, row.name);
	const done = () => revert_barcode_scanner_flags();

	// Clear scan row; then focus qty (or rate) on the row we updated so user can adjust immediately
	const clear_scan_row = () =>
		frappe.model
			.set_value(cdt, cdn, { item_code: "", qty: 0, barcode: "" })
			.then(() => refresh_field("items"));

	const focus_updated_row_qty = (docname) => {
		// Focus qty on the row we just updated/added so cursor goes there after scan
		focus_grid_cell(frm, grid, docname, "qty");
	};

	if (existing) {
		// Same item: add qty to existing row, clear scan row, focus qty on that row
		const new_qty = flt(existing.qty) + 1;
		return frappe.model
			.set_value(existing.doctype, existing.name, "qty", new_qty)
			.then(clear_scan_row)
			.then(() => {
				focus_updated_row_qty(existing.name);
				frappe.show_alert(
					{ message: __("Row #{0}: Qty increased by 1", [existing.idx]), indicator: "green" },
					3
				);
			})
			.finally(done);
	}

	// New item: add one new row, set item there, clear scan row, focus qty on new row
	const target = frappe.model.add_child(frm.doc, "Sales Invoice Item", "items");
	frm.script_manager.trigger("items_add", target.doctype, target.name);

	const set_item = () =>
		frappe.model.set_value(target.doctype, target.name, "item_code", data.item_code).then(() => {
			const updates = { qty: 1 };
			if (data.uom) updates.uom = data.uom;
			if (data.batch_no) updates.batch_no = data.batch_no;
			if (data.serial_no) updates.serial_no = data.serial_no;
			return frappe.model.set_value(target.doctype, target.name, updates);
		});

	return set_item()
		.then(clear_scan_row)
		.then(() => {
			focus_updated_row_qty(target.name);
			frappe.show_alert(
				{ message: __("Row #{0}: Item added", [target.idx]), indicator: "green" },
				3
			);
		})
		.finally(done);
}

// Remove empty item rows (scan row) before save - runs on client before validation
function remove_empty_item_rows(frm) {
	if (!frm.doc.items || frm.doc.items.length === 0) return;
	const kept = frm.doc.items.filter((row) => row.item_code);
	if (kept.length !== frm.doc.items.length) {
		frm.doc.items = kept;
		kept.forEach((row, i) => (row.idx = i + 1));
		frm.refresh_field("items");
	}
}

// ----- Form-level "Scan Barcode" field -----
// Ensures scanning in the form-level field triggers ERPNext BarcodeScanner (add/increment items).
frappe.ui.form.on("Sales Invoice", {
	before_save(frm) {
		if (frm.doc.docstatus === 0) remove_empty_item_rows(frm);
	},
	scan_barcode(frm) {
		if (frm.doc.docstatus !== 0) return;
		const raw = (frm.doc.scan_barcode || "").toString().trim();
		if (!raw) return;

		// Use ERPNext BarcodeScanner: reads from scan_barcode field, adds/updates items
		if (typeof erpnext !== "undefined" && erpnext.utils && erpnext.utils.BarcodeScanner) {
			frappe.flags.dialog_set = false;
			const scanner = new erpnext.utils.BarcodeScanner({ frm: frm });
			scanner.process_scan();
		}
	},
});

// ----- Row-level "Barcode" column (items table) -----
// Scan in Barcode column: resolve via API, add new row or add qty to existing. Clear barcode
// immediately so the default barcode handler no-ops.
frappe.ui.form.on("Sales Invoice Item", {
	barcode(frm, cdt, cdn) {
		if (frm.doc.docstatus !== 0) return;
		if (frappe.flags[SCAN_FLAG]) return;

		const row = frappe.get_doc(cdt, cdn);
		const raw = (row.barcode || "").toString().trim();
		if (!raw) return;

		// Set flag before clear so re-triggered handler (from set_value) exits immediately
		frappe.flags[SCAN_FLAG] = true;
		// Clear barcode so default handler skips; then resolve via API
		frappe.model.set_value(cdt, cdn, "barcode", "");
		refresh_field("items");

		frappe.call({
			method: "erpnext.stock.utils.scan_barcode",
			args: { search_value: raw },
			callback(r) {
				if (!r || r.exc || !r.message || !r.message.item_code) {
					frappe.flags[SCAN_FLAG] = false;
					frappe.show_alert(
						{ message: __("Cannot find Item with this Barcode"), indicator: "red" },
						3
					);
					return;
				}

				apply_barcode_scan(frm, cdt, cdn, r.message, row)
					.catch((err) => {
						console.error("sf_trading barcode scan error:", err);
						frappe.show_alert(
							{ message: __("Could not add scanned item"), indicator: "red" },
							3
						);
					})
					.finally(() => {
						frappe.flags[SCAN_FLAG] = false;
					});
			},
		});
	},
});
