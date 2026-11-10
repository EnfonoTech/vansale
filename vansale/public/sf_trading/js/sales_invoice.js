// sf_trading — Sales Invoice bundle
// Loaded only when a Sales Invoice form opens (doctype_js).
// Combines: customer/credit filter, warehouse stock popup, barcode scanner,
//           inter-company branch, POS/payment popup, sales person, warehouse qty validation.

frappe.provide("sf_trading");

// ═══════════════════════════════════════════════════════════════════════════════
// Customer filter & Credit validation
// ═══════════════════════════════════════════════════════════════════════════════

function sf_apply_customer_credit_filter(frm) {
	frm.set_query("customer", function (doc) {
		if (doc.custom_payment_mode === "Credit") {
			return {
				query: "vansale.sf_trading.customer_permission.customer_query_credit_branch",
				filters: { branch: doc.branch || "", company: doc.company || "" },
			};
		}
		if (doc.company) {
			return { filters: { custom_company: doc.company } };
		}
		return {};
	});
}

function sf_get_customer_credit_limit(customer, company) {
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
		if (frm.doc.docstatus === 0 && frm.doc.customer) {
			sf_check_overdue_on_customer(frm);
		}
	},
	refresh: function (frm) {
		sf_apply_customer_credit_filter(frm);
	},
	custom_payment_mode: function (frm) {
		sf_apply_customer_credit_filter(frm);
		if (frm.doc.custom_payment_mode !== "Cash" && frm.doc.custom_driver) {
			frm.set_value("custom_driver", "");
		}
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

// ═══════════════════════════════════════════════════════════════════════════════
// Warehouse Stock Popup
// ═══════════════════════════════════════════════════════════════════════════════

sf_trading.stock_displays = {};
sf_trading.current_selected_row = null;

sf_trading.show_warehouse_stock = function(frm, item_row, load_all) {
	load_all = load_all || false;
	if (!item_row || !item_row.item_code) { sf_trading.hide_stock_display(frm); return; }
	if (!frappe.meta.has_field(item_row.doctype, "warehouse")) { sf_trading.hide_stock_display(frm); return; }
	if (!frm.doc.company) { sf_trading.hide_stock_display(frm); return; }

	let current_row = locals[item_row.doctype][item_row.name];
	let warehouse = current_row ? (current_row.warehouse || "") : "";
	let api_args = { item_code: item_row.item_code, company: frm.doc.company, target_warehouse: warehouse || null };
	if (!load_all) api_args.limit = 5;

	frappe.call({
		method: "vansale.sf_trading.api.warehouse_stock.get_item_warehouse_stock",
		args: api_args,
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				sf_trading.render_stock_display(frm, item_row.item_code, r.message, warehouse, item_row.name, load_all);
			} else {
				sf_trading.hide_stock_display(frm);
			}
		},
		error: function() { sf_trading.hide_stock_display(frm); }
	});
};

sf_trading.render_stock_display = function(frm, item_code, stock_data, target_warehouse, item_row_name, is_all_loaded) {
	is_all_loaded = is_all_loaded || false;
	if (!frm.fields_dict.items || !frm.fields_dict.items.grid) return;

	const grid = frm.fields_dict.items.grid;
	const grid_wrapper = grid.wrapper;
	sf_trading.hide_stock_display(frm);

	let $container = grid_wrapper.find(".sf-trading-stock-display");
	if (!$container.length) {
		$container = $('<div class="sf-trading-stock-display" style="margin-top:8px;padding:8px;background:#f9f9f9;border:1px solid #d1d8dd;border-radius:4px;"></div>');
		grid_wrapper.append($container);
	}

	let target_warehouse_name = "";
	if (target_warehouse) {
		let tw = stock_data.find(function(i) { return i.warehouse === target_warehouse; });
		target_warehouse_name = tw ? (tw.warehouse_name || target_warehouse) : target_warehouse;
	}

	let visible_data, hidden_data, has_more;
	if (is_all_loaded) {
		visible_data = stock_data.slice(0, 5);
		hidden_data = stock_data.slice(5);
		has_more = hidden_data.length > 0;
	} else {
		visible_data = stock_data;
		hidden_data = [];
		has_more = stock_data.length >= 5;
	}

	let display_id = "sf_stock_" + Date.now() + "_" + Math.random().toString(36).substr(2, 9);
	let show_toggle_button = false, button_text = "", button_action = "";

	if (has_more && !is_all_loaded) {
		show_toggle_button = true; button_text = __("Show All"); button_action = "load_all";
	} else if (is_all_loaded && stock_data.length > 5) {
		show_toggle_button = true; button_text = __("Show Less"); button_action = "toggle_view";
	}

	let html = `
		<div style="margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">
			<div>
				<strong style="font-size:14px;">${__("Stock Availability - {0}", [item_code])}</strong>
				${target_warehouse ? `<span style="font-size:12px;color:#666;margin-left:8px;">→ ${target_warehouse_name}</span>` : ''}
			</div>
			${show_toggle_button ? `
			<button class="btn btn-xs btn-link ${display_id}_toggle_btn" data-action="${button_action}"
				style="padding:2px 6px;font-size:12px;color:#007bff;text-decoration:none;margin-left:auto;">
				${button_text}
			</button>` : ''}
		</div>
		<div style="max-height:300px;overflow-y:auto;">
		<table class="table table-bordered" style="margin:0;background:white;font-size:13px;">
			<thead>
				<tr style="background:#f5f5f5;">
					<th style="padding:6px 8px;width:50%;font-size:13px;">${__("Warehouse")}</th>
					<th style="padding:6px 8px;text-align:right;width:30%;font-size:13px;">${__("Stock Qty")}</th>
					<th style="padding:6px 8px;text-align:center;width:20%;font-size:13px;">${__("Action")}</th>
				</tr>
			</thead>
			<tbody id="${display_id}_tbody">`;

	function render_row(item, extra_class) {
		let sc = item.stock_qty > 0 ? "#28a745" : "#6c757d";
		let si = item.stock_qty > 0 ? "●" : "○";
		let is_target = item.warehouse === target_warehouse;
		let bg = is_target ? "#e3f2fd" : "white";
		return `<tr class="${display_id}_row${extra_class || ''}" style="background:${bg};">
			<td style="padding:6px 8px;">
				<span style="color:${sc};margin-right:5px;font-size:12px;">${si}</span>
				<span style="font-size:13px;">${item.warehouse_name || item.warehouse}</span>
				${is_target ? '<span style="color:#2196f3;margin-left:5px;font-size:12px;">(Target)</span>' : ''}
			</td>
			<td style="padding:6px 8px;text-align:right;">
				<span style="color:${sc};font-weight:bold;font-size:13px;">${format_number(item.stock_qty, null, {precision: 2})}</span>
			</td>
			<td style="padding:6px 8px;text-align:center;">
				${is_target ? '<span style="color:#999;font-size:12px;">-</span>' :
				`<button class="btn btn-xs btn-primary request-item-btn"
					data-item-code="${item_code.replace(/"/g, '&quot;')}"
					data-from-warehouse="${item.warehouse.replace(/"/g, '&quot;')}"
					data-from-warehouse-name="${(item.warehouse_name || item.warehouse).replace(/"/g, '&quot;')}"
					data-to-warehouse="${target_warehouse.replace(/"/g, '&quot;')}"
					data-to-warehouse-name="${target_warehouse_name.replace(/"/g, '&quot;')}"
					data-item-row-name="${item_row_name.replace(/"/g, '&quot;')}"
					style="padding:3px 10px;font-size:12px;">${__("Request Items")}</button>`}
			</td>
		</tr>`;
	}

	if (stock_data.length === 0) {
		html += `<tr><td colspan="3" style="padding:10px;text-align:center;color:#999;font-size:13px;">${__("No warehouses with stock available")}</td></tr>`;
	} else {
		visible_data.forEach(function(item) { html += render_row(item); });
		if (is_all_loaded && hidden_data.length > 0) {
			hidden_data.forEach(function(item) { html += render_row(item, " " + display_id + "_hidden_row"); });
		}
	}

	html += `</tbody></table></div>`;
	$container.html(html).show();
	sf_trading.stock_displays[frm.doctype + "_" + frm.docname] = $container;

	let $toggle_btn = $container.find(`.${display_id}_toggle_btn`);
	if ($toggle_btn.length) {
		let _action = $toggle_btn.data("action");
		let is_expanded = (_action === "toggle_view");
		$toggle_btn.on("click", function() {
			if (_action === "load_all") {
				let item_row = locals["Sales Invoice Item"] && locals["Sales Invoice Item"][item_row_name];
				if (item_row && item_row.item_code) {
					$toggle_btn.prop("disabled", true).html(__("Loading..."));
					sf_trading.show_warehouse_stock(frm, item_row, true);
				}
			} else if (_action === "toggle_view") {
				let $hidden = $container.find(`.${display_id}_hidden_row`);
				if (is_expanded) { $hidden.hide(); $toggle_btn.html(__("Show All")); is_expanded = false; }
				else { $hidden.show(); $toggle_btn.html(__("Show Less")); is_expanded = true; }
			}
		});
	}

	$container.find(".request-item-btn").on("click", function() {
		let $b = $(this);
		sf_trading.create_material_request(frm, $b.data("item-code"), $b.data("from-warehouse"),
			$b.data("from-warehouse-name"), $b.data("to-warehouse"), $b.data("to-warehouse-name"));
	});
};

sf_trading.hide_stock_display = function(frm) {
	let $d = sf_trading.stock_displays[frm.doctype + "_" + frm.docname];
	if ($d && $d.length) $d.hide();
};

sf_trading.create_material_request = function(frm, item_code, from_warehouse, from_warehouse_name, to_warehouse, to_warehouse_name) {
	let dialog = new frappe.ui.Dialog({
		title: __("Create Material Transfer Request"),
		fields: [
			{ fieldtype: "Data", fieldname: "item_code", label: __("Item Code"), default: item_code, read_only: 1 },
			{ fieldtype: "Data", fieldname: "from_warehouse", label: __("From Warehouse"), default: from_warehouse_name || from_warehouse, read_only: 1 },
			{ fieldtype: "Data", fieldname: "to_warehouse", label: __("To Warehouse"), default: to_warehouse_name || to_warehouse, read_only: 1 },
			{ fieldtype: "Float", fieldname: "qty", label: __("Quantity"), default: 1, reqd: 1 },
			{ fieldtype: "Date", fieldname: "schedule_date", label: __("Required Date"), default: frappe.datetime.add_days(frappe.datetime.get_today(), 7), reqd: 1 },
		],
		primary_action_label: __("Create"),
		primary_action: function() {
			let vals = dialog.get_values();
			if (!vals) return;
			frappe.call({
				method: "vansale.sf_trading.api.material_request.create_material_request",
				args: { item_code: vals.item_code, from_warehouse, to_warehouse, qty: vals.qty, schedule_date: vals.schedule_date, material_request_type: "Material Transfer", company: frm.doc.company },
				callback: function(r) {
					if (r.message) {
						let current_route = frappe.get_route();
						frappe.show_alert({ message: __("Material Request {0} created and submitted ", [r.message]), indicator: "green" });
						setTimeout(function() { frappe.set_route(current_route); }, 300);
					}
					dialog.hide();
				},
				error: function() { frappe.show_alert({ message: __("Error creating Material Request"), indicator: "red" }); }
			});
		}
	});
	dialog.show();
};

frappe.ui.form.on("Sales Invoice Item", {
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		sf_trading.current_selected_row = row;
		if (row.item_code && frappe.meta.has_field(row.doctype, "warehouse") && frm.doc.company) {
			clearTimeout(row._sf_stock_timeout);
			row._sf_stock_timeout = setTimeout(function() { sf_trading.show_warehouse_stock(frm, row); }, 300);
		} else { sf_trading.hide_stock_display(frm); }
	},
	item_name: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		sf_trading.current_selected_row = row;
		if (row.item_code && frappe.meta.has_field(row.doctype, "warehouse") && frm.doc.company) {
			clearTimeout(row._sf_stock_timeout);
			row._sf_stock_timeout = setTimeout(function() { sf_trading.show_warehouse_stock(frm, row); }, 100);
		}
	},
	item_code_focus: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row && row.item_code && frappe.meta.has_field(row.doctype, "warehouse") && frm.doc.company) {
			sf_trading.current_selected_row = row;
			clearTimeout(row._sf_stock_timeout);
			row._sf_stock_timeout = setTimeout(function() { sf_trading.show_warehouse_stock(frm, row); }, 100);
		}
	},
	warehouse: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		sf_trading.current_selected_row = row;
		if (row.item_code && frappe.meta.has_field(row.doctype, "warehouse") && frm.doc.company) {
			clearTimeout(row._sf_stock_timeout);
			row._sf_stock_timeout = setTimeout(function() { sf_trading.show_warehouse_stock(frm, row); }, 300);
		}
	},
	form_render: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row && row.item_code) {
			sf_trading.current_selected_row = row;
			if (frm.doc.company && frappe.meta.has_field(row.doctype, "warehouse")) {
				clearTimeout(row._sf_stock_timeout);
				row._sf_stock_timeout = setTimeout(function() { sf_trading.show_warehouse_stock(frm, row); }, 200);
			}
		}
	},
});

frappe.ui.form.on("Sales Invoice", {
	refresh: function(frm) {
		if (!frm.fields_dict.items || !frm.fields_dict.items.grid) return;
		sf_trading.hide_stock_display(frm);
		const grid = frm.fields_dict.items.grid;
		grid.wrapper.on("click focus", "[data-fieldname='item_code'] input, [data-fieldname='item_code'] .link-field", function() {
			let idx = $(this).closest(".grid-row").attr("data-idx");
			if (idx && frm.doc.items) {
				let row = frm.doc.items.find(function(i) { return i.idx == idx; });
				if (row && row.item_code && frm.doc.company && frappe.meta.has_field(row.doctype, "warehouse")) {
					sf_trading.current_selected_row = row;
					clearTimeout(row._sf_stock_timeout);
					row._sf_stock_timeout = setTimeout(function() { sf_trading.show_warehouse_stock(frm, row); }, 100);
				}
			}
		});
		const $gw = grid.wrapper;
		$gw.off("focusout.sf_stock");
		if (frm.wrapper) $(frm.wrapper).off("click.sf_stock");
		$gw.on("focusout.sf_stock", function() {
			setTimeout(function() {
				const a = document.activeElement;
				if (!a || !$gw[0].contains(a)) sf_trading.hide_stock_display(frm);
			}, 150);
		});
		if (frm.wrapper) {
			$(frm.wrapper).on("click.sf_stock", function(e) {
				if (!$gw[0].contains(e.target)) sf_trading.hide_stock_display(frm);
			});
		}
	}
});

// ═══════════════════════════════════════════════════════════════════════════════
// Per-Item Price List
// ═══════════════════════════════════════════════════════════════════════════════
// Each row can override the invoice's Price List (custom_price_list). When set
// (or left blank, in which case the invoice's own Price List applies), the row's
// rate is looked up from that price list — same resolution ERPNext itself uses
// (party pricing, qty breaks, uom fallback, currency conversion).

function sf_apply_row_price_list(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || !row.item_code) return;
	const price_list = row.custom_price_list || frm.doc.selling_price_list;
	if (!price_list) return;

	frappe.call({
		method: "vansale.sf_trading.api.item_row_price_list.get_row_price_list_rate",
		args: {
			item_code: row.item_code,
			price_list: price_list,
			doctype: frm.doc.doctype,
			uom: row.uom,
			stock_uom: row.stock_uom,
			qty: row.qty || 1,
			transaction_date: frm.doc.posting_date || frappe.datetime.get_today(),
			customer: frm.doc.customer,
			company: frm.doc.company,
			conversion_rate: frm.doc.conversion_rate || 1,
		},
		callback: function (r) {
			if (!r.message || !flt(r.message.rate)) return;
			frappe.model.set_value(cdt, cdn, "price_list_rate", r.message.rate);
			frappe.model.set_value(cdt, cdn, "rate", r.message.rate);
		},
	});
}

frappe.ui.form.on("Sales Invoice Item", {
	custom_price_list: function (frm, cdt, cdn) { sf_apply_row_price_list(frm, cdt, cdn); },
	item_code: function (frm, cdt, cdn) {
		// ERPNext's own item_code handler re-rates the row from the invoice's
		// price list a moment later — reapply the row's own price list (if any)
		// afterwards so it isn't clobbered by that.
		const row = locals[cdt][cdn];
		if (row && row.custom_price_list) {
			setTimeout(function () { sf_apply_row_price_list(frm, cdt, cdn); }, 800);
		}
	},
	items_add: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row && !row.custom_price_list && frm.doc.selling_price_list) {
			frappe.model.set_value(cdt, cdn, "custom_price_list", frm.doc.selling_price_list);
		}
	},
});

frappe.ui.form.on("Sales Invoice", {
	selling_price_list: function (frm) {
		// ERPNext's own price-list-change handler re-rates every row against
		// the invoice's price list a moment later — reapply row-level
		// overrides afterwards so they aren't clobbered by that.
		setTimeout(function () {
			(frm.doc.items || []).forEach(function (row) {
				if (row.item_code && row.custom_price_list) {
					sf_apply_row_price_list(frm, row.doctype, row.name);
				}
			});
		}, 700);
	},
});

// ═══════════════════════════════════════════════════════════════════════════════
// Barcode Scanner
// ═══════════════════════════════════════════════════════════════════════════════

const SF_SCAN_FLAG = "sf_trading_barcode_scan";

function sf_get_matching_row(frm, data, exclude_name) {
	return (frm.doc.items || []).find(function(d) {
		if (d.name === exclude_name) return false;
		if (d.item_code !== data.item_code) return false;
		if (data.uom && d.uom !== data.uom) return false;
		if (data.batch_no && d.batch_no !== data.batch_no) return false;
		if (d.has_item_scanned) return false;
		return true;
	});
}

function sf_focus_grid_cell(frm, grid, docname, fieldname) {
	if (!grid || !docname) return;
	fieldname = fieldname || "qty";
	setTimeout(function() {
		const grid_row = grid.grid_rows_by_docname && grid.grid_rows_by_docname[docname];
		if (!grid_row || !grid_row.row) return;
		if (typeof grid_row.toggle_editable_row === "function") grid_row.toggle_editable_row(true);
		setTimeout(function() {
			const col = grid_row.columns && grid_row.columns[fieldname];
			if (col && col.field && col.field.$input && col.field.$input.length) { col.field.$input.focus(); return; }
			const $cell = grid_row.row.find('[data-fieldname="' + fieldname + '"]');
			const $input = $cell.find("input");
			if ($input.length && $input.first().is(":visible")) { $input.first().focus(); return; }
			if (typeof grid.set_focus_on_row === "function") {
				const idx = grid_row.doc && grid_row.doc.idx;
				if (idx != null) grid.set_focus_on_row(idx - 1);
			}
		}, 100);
	}, 350);
}

function sf_apply_barcode_scan(frm, cdt, cdn, data, row) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return Promise.resolve();

	if (data.batch_no || data.serial_no) {
		frappe.flags.trigger_from_barcode_scanner = true;
		frappe.flags.hide_serial_batch_dialog = true;
	}
	const revert = function() {
		frappe.flags.trigger_from_barcode_scanner = false;
		frappe.flags.hide_serial_batch_dialog = false;
	};

	const existing = sf_get_matching_row(frm, data, row.name);
	const clear_scan_row = function() {
		return frappe.model.set_value(cdt, cdn, { item_code: "", qty: 0, barcode: "" }).then(function() { refresh_field("items"); });
	};
	const focus_qty = function(docname) { sf_focus_grid_cell(frm, grid, docname, "qty"); };

	if (existing) {
		return frappe.model.set_value(existing.doctype, existing.name, "qty", flt(existing.qty) + 1)
			.then(clear_scan_row)
			.then(function() {
				focus_qty(existing.name);
				frappe.show_alert({ message: __("Row #{0}: Qty increased by 1", [existing.idx]), indicator: "green" }, 3);
			})
			.finally(revert);
	}

	const target = frappe.model.add_child(frm.doc, "Sales Invoice Item", "items");
	frm.script_manager.trigger("items_add", target.doctype, target.name);

	return frappe.model.set_value(target.doctype, target.name, "item_code", data.item_code)
		.then(function() {
			const updates = { qty: 1 };
			if (data.uom) updates.uom = data.uom;
			if (data.batch_no) updates.batch_no = data.batch_no;
			if (data.serial_no) updates.serial_no = data.serial_no;
			return frappe.model.set_value(target.doctype, target.name, updates);
		})
		.then(clear_scan_row)
		.then(function() {
			focus_qty(target.name);
			frappe.show_alert({ message: __("Row #{0}: Item added", [target.idx]), indicator: "green" }, 3);
		})
		.finally(revert);
}

frappe.ui.form.on("Sales Invoice", {
	before_save: function(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.items) return;
		const kept = frm.doc.items.filter(function(r) { return r.item_code; });
		if (kept.length !== frm.doc.items.length) {
			frm.doc.items = kept;
			kept.forEach(function(r, i) { r.idx = i + 1; });
			frm.refresh_field("items");
		}
	},
	scan_barcode: function(frm) {
		if (frm.doc.docstatus !== 0) return;
		const raw = (frm.doc.scan_barcode || "").toString().trim();
		if (!raw) return;
		if (typeof erpnext !== "undefined" && erpnext.utils && erpnext.utils.BarcodeScanner) {
			frappe.flags.dialog_set = false;
			new erpnext.utils.BarcodeScanner({ frm: frm }).process_scan();
		}
	},
});

frappe.ui.form.on("Sales Invoice Item", {
	barcode: function(frm, cdt, cdn) {
		if (frm.doc.docstatus !== 0 || frappe.flags[SF_SCAN_FLAG]) return;
		const row = frappe.get_doc(cdt, cdn);
		const raw = (row.barcode || "").toString().trim();
		if (!raw) return;
		frappe.flags[SF_SCAN_FLAG] = true;
		frappe.model.set_value(cdt, cdn, "barcode", "");
		refresh_field("items");
		frappe.call({
			method: "erpnext.stock.utils.scan_barcode",
			args: { search_value: raw },
			callback: function(r) {
				if (!r || r.exc || !r.message || !r.message.item_code) {
					frappe.flags[SF_SCAN_FLAG] = false;
					frappe.show_alert({ message: __("Cannot find Item with this Barcode"), indicator: "red" }, 3);
					return;
				}
				sf_apply_barcode_scan(frm, cdt, cdn, r.message, row)
					.catch(function(err) {
						console.error("sf_trading barcode scan error:", err);
						frappe.show_alert({ message: __("Could not add scanned item"), indicator: "red" }, 3);
					})
					.finally(function() { frappe.flags[SF_SCAN_FLAG] = false; });
			},
		});
	},
});

// ═══════════════════════════════════════════════════════════════════════════════
// Inter-Company Branch filter
// ═══════════════════════════════════════════════════════════════════════════════

frappe.ui.form.on("Sales Invoice", {
	onload: function(frm) {
		frm.set_query("inter_company_branch", function() {
			if (!frm.doc.represents_company) return { filters: { name: "" } };
			return {
				query: "vansale.sf_trading.doctype.inter_company_branch.inter_company_branch.get_branches_for_company",
				filters: { company: frm.doc.represents_company },
			};
		});
	},
});

// ═══════════════════════════════════════════════════════════════════════════════
// POS Total / Payment Popup
// ═══════════════════════════════════════════════════════════════════════════════

function sf_trading_open_invoice_print(frm, format_override) {
	if (!frm || !frm.doc || !frm.doc.name) return;
	const format = encodeURIComponent(
		format_override !== undefined ? (format_override || "") : (frm.meta.default_print_format || "")
	);
	const url = `${window.location.origin}/printview?doctype=Sales%20Invoice&name=${encodeURIComponent(frm.doc.name)}&trigger_print=1&format=${format}&no_letterhead=0&settings=%7B%7D&_lang=${frappe.boot.lang}`;
	const a = document.createElement("a");
	a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
	document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

frappe.ui.form.on("Sales Invoice", {
	setup: function(frm) {
		frm.set_query("custom_driver", function(doc) {
			if (doc.branch) return { filters: { custom_branch: doc.branch } };
			return {};
		});
	},
	refresh: function(frm) {
		if (!frm._sf_savesubmit_wrapped) {
			frm._sf_savesubmit_wrapped = true;
			frm.savesubmit = function(btn, callback, on_error) {
				var me = this;
				me.validate_form_action("Submit");
				frappe.validated = true;
				me.script_manager.trigger("before_submit").then(function() {
					if (!frappe.validated) return me.handle_save_fail(btn, on_error);
					me.save("Submit", function(r) {
						if (r.exc) { me.handle_save_fail(btn, on_error); }
						else {
							frappe.utils.play_sound("submit");
							callback && callback();
							me.script_manager.trigger("on_submit").then(function() {
								if (frappe.route_hooks.after_submit) {
									var cb = frappe.route_hooks.after_submit;
									delete frappe.route_hooks.after_submit;
									cb(me);
								}
							});
						}
					}, btn, function() { me.handle_save_fail(btn, on_error); });
				});
			};
		}

		if (frm.is_new() && frm.doc.is_return && frm.doc.custom_payment_mode === "Cheque") {
			frappe.msgprint({ title: __("Cheque Return"), message: __("This is a return for a Cheque invoice. Confirm the payment with accounts before submitting."), indicator: "orange" });
		}

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Print Invoice"), function() {
				sf_trading.get_company_print_format(frm.doc.company, frm.doctype, function(company_format) {
					sf_trading_open_invoice_print(frm, company_format || frm.meta.default_print_format || "");
				});
			});
			frm.add_custom_button(__("Print DN"), function() {
				frappe.xcall("frappe.client.get_value", { doctype: "Company", filters: { name: frm.doc.company }, fieldname: "custom_delivery_note_print_format" })
					.then(function(result) {
						var dn_format = result && result.custom_delivery_note_print_format;
						if (!dn_format) { frappe.msgprint({ title: __("Not Configured"), message: __("No Delivery Note print format set on company {0}.", [frm.doc.company]), indicator: "orange" }); return; }
						sf_trading_open_invoice_print(frm, dn_format);
					});
			});
			if (Math.abs(flt(frm.doc.outstanding_amount)) > 0) {
				frm.add_custom_button(__("Receive Payment"), function() {
					if (frm.doc.custom_payment_mode === "Cheque") {
						sf_trading_show_pdc_popup(frm);
					} else {
						sf_trading_show_pos_total_popup(frm);
					}
				}).addClass("btn-primary");
			}
		}

		if (frm.doc.docstatus === 0 || frm.doc.docstatus === 1) {
			const $btn = frm.add_custom_button(__("New Invoice"), function() { frappe.new_doc("Sales Invoice"); });
			if ($btn) {
				$btn.html('<a href="/app/sales-invoice/new" style="color:inherit;text-decoration:none">' + __("New Invoice") + "</a>");
				$btn.find("a").on("click", function(e) { e.stopPropagation(); });
			}
		}
	},
	before_submit: function(frm) {
		if (frm.doc.custom_payment_mode === "Cheque") {
			frappe.validated = false;
			if (Math.abs(flt(frm.doc.grand_total)) > 0 && Math.abs(flt(frm.doc.outstanding_amount)) > 0) {
				sf_trading_show_pdc_popup(frm);
			} else {
				frm.save("Submit").then(function() {
					if (frm.doc.docstatus === 1) { sf_trading_open_invoice_print(frm); frm.reload_doc(); }
				});
			}
			return;
		}
		if (frm.doc.custom_payment_mode !== "Credit" && frm.doc.custom_driver) {
			frappe.validated = false;
			frappe.db.get_value("Driver", frm.doc.custom_driver, "full_name").then(function(r) {
				var label = (r && r.message && r.message.full_name) || frm.doc.custom_driver;
				frappe.confirm(__("Delivery Person {0} is assigned. Invoice will be submitted without collecting payment now. Continue?", [label]), function() {
					frm.save("Submit").then(function() {
						if (frm.doc.docstatus === 1) { sf_trading_open_invoice_print(frm); frm.reload_doc(); }
					});
				});
			});
			return;
		}
		if (frm.doc.custom_payment_mode !== "Credit") {
			frappe.validated = false;
			if (Math.abs(flt(frm.doc.grand_total)) > 0 && Math.abs(flt(frm.doc.outstanding_amount)) > 0) {
				sf_trading_show_pos_total_popup(frm);
			} else {
				frm.save("Submit").then(function() {
					if (frm.doc.docstatus === 1) { sf_trading_open_invoice_print(frm); frm.reload_doc(); }
				});
			}
			return;
		}
		frappe.validated = false;
		frappe.confirm(__("Do you want to Submit this Sales Invoice?"), function() {
			frappe.flags.sf_trading_submitting_credit = true;
			frm.save("Submit").then(function() {
				if (frm.doc.docstatus === 1) { sf_trading_open_invoice_print(frm); frm.reload_doc(); }
			}).finally(function() { delete frappe.flags.sf_trading_submitting_credit; });
		});
	},
	after_save: function(frm) {
		if (frappe.flags.sf_trading_skip_payment_popup || frappe.flags.sf_trading_popup_showing) return;
		if (frm.doc.docstatus !== 0 || !frm.doc.name || frm.doc.name.startsWith("new-")) return;

		if (frm.doc.custom_payment_mode === "Credit") {
			if (frappe.flags.sf_trading_credit_confirm_open) return;
			frappe.flags.sf_trading_credit_confirm_open = true;
			const d = frappe.confirm(__("Do you want to Submit this Sales Invoice now?"), function() {
				frappe.flags.sf_trading_skip_payment_popup = true;
				frappe.flags.sf_trading_submitting_credit = true;
				frm.save("Submit").then(function() {
					if (frm.doc.docstatus === 1) { sf_trading_open_invoice_print(frm); frm.reload_doc(); }
				}).finally(function() {
					delete frappe.flags.sf_trading_submitting_credit;
					setTimeout(function() { delete frappe.flags.sf_trading_skip_payment_popup; }, 500);
				});
			}, function() {});
			if (d) d.onhide = function() { delete frappe.flags.sf_trading_credit_confirm_open; };
			return;
		}
		if (frm.doc.custom_payment_mode === "Cheque") {
			if (Math.abs(flt(frm.doc.grand_total)) > 0 && Math.abs(flt(frm.doc.outstanding_amount)) > 0) sf_trading_show_pdc_popup(frm);
			return;
		}
		if (frm.doc.custom_driver) {
			if (frappe.flags.sf_trading_driver_confirm_open) return;
			frappe.flags.sf_trading_driver_confirm_open = true;
			frappe.db.get_value("Driver", frm.doc.custom_driver, "full_name").then(function(r) {
				var label = (r && r.message && r.message.full_name) || frm.doc.custom_driver;
				const d = frappe.confirm(__("Delivery Person {0} is assigned. Submit without collecting payment now?", [label]), function() {
					frappe.flags.sf_trading_skip_payment_popup = true;
					frm.save("Submit").then(function() {
						if (frm.doc.docstatus === 1) { sf_trading_open_invoice_print(frm); frm.reload_doc(); }
					}).finally(function() { setTimeout(function() { delete frappe.flags.sf_trading_skip_payment_popup; }, 500); });
				}, function() {});
				if (d) d.onhide = function() { delete frappe.flags.sf_trading_driver_confirm_open; };
			});
			return;
		}
		if (!frm.doc.grand_total || Math.abs(flt(frm.doc.grand_total)) <= 0) return;
		if (Math.abs(flt(frm.doc.outstanding_amount)) <= 0) return;
		sf_trading_show_pos_total_popup(frm);
	},
});

frappe.ui.form.on("Sales Invoice", {
	custom_payment_mode: function(frm) { sf_set_credit_limit(frm); },
	customer: function(frm) { sf_set_credit_limit(frm); },
	company: function(frm) { sf_set_credit_limit(frm); },
});

function sf_set_credit_limit(frm) {
	if (frm.doc.custom_payment_mode !== "Credit" || !frm.doc.customer) {
		frm.doc.custom_credit_limit = 0; frm.refresh_field("custom_credit_limit"); return;
	}
	var company = frm.doc.company || frappe.defaults.get_default("company");
	frappe.db.get_doc("Customer", frm.doc.customer).then(function(cust) {
		var credit_limit = 0;
		if (cust.credit_limits && cust.credit_limits.length) {
			var row = cust.credit_limits.find(function(r) { return r.company === company; });
			credit_limit = flt(row ? row.credit_limit : cust.credit_limits[0].credit_limit);
		}
		if (!credit_limit) { frm.doc.custom_credit_limit = 0; frm.refresh_field("custom_credit_limit"); return; }
		frappe.db.get_list("Sales Invoice", {
			filters: { customer: frm.doc.customer, company, custom_payment_mode: "Credit", docstatus: 1 },
			fields: ["grand_total"], limit: 500,
		}).then(function(invoices) {
			var used = 0;
			(invoices || []).forEach(function(inv) { used += flt(inv.grand_total); });
			frm.doc.custom_credit_limit = Math.max(0, flt(credit_limit - used, 2));
			frm.refresh_field("custom_credit_limit");
		});
	});
}

function sf_trading_show_pos_total_popup(frm) {
	if (frappe.flags.sf_trading_popup_showing || !frm || !frm.doc) return;
	frappe.flags.sf_trading_popup_showing = true;

	function ensure_payments_then_show() {
		if (frm.doc.payments && frm.doc.payments.length > 0) { sf_trading_render_dialog(frm); return; }
		frappe.call({
			method: "vansale.sf_trading.api.sales_invoice_payment.get_payment_modes_with_account",
			args: { company: frm.doc.company, is_return: frm.doc.is_return ? 1 : 0, branch: frm.doc.branch || undefined },
			callback: function(r) {
				const modes = r.message || [];
				if (!modes.length) {
					frappe.flags.sf_trading_popup_showing = false;
					frappe.msgprint(__("No enabled Mode of Payment with default Cash or Bank account for this company. Please set default account in Mode of Payment."));
					return;
				}
				if (frm.doc.docstatus === 1) {
					// Receive Payment on a submitted invoice: build the dialog rows
					// locally — touching frm.doc.payments would mark the form Not Saved.
					sf_trading_render_dialog(frm, modes.map(function(name) {
						return { mode_of_payment: name, amount: 0 };
					}));
					return;
				}
				frm.clear_table("payments");
				modes.forEach(function(name) { const row = frm.add_child("payments"); row.mode_of_payment = name; });
				frm.refresh_field("payments");
				frappe.call({
					method: "vansale.sf_trading.api.sales_invoice_payment.get_accounts_for_modes",
					args: { company: frm.doc.company, modes: JSON.stringify(modes) },
					callback: function(ar) {
						const accounts = ar.message || {};
						(frm.doc.payments || []).forEach(function(p) { p.account = accounts[p.mode_of_payment] || ""; });
						frm.refresh_field("payments");
						sf_trading_render_dialog(frm);
					},
					error: function() { frappe.flags.sf_trading_popup_showing = false; frappe.msgprint(__("Error loading payment accounts. Please try again.")); }
				});
			},
			error: function() { frappe.flags.sf_trading_popup_showing = false; frappe.msgprint(__("Error loading payment modes. Please try again.")); }
		});
	}
	ensure_payments_then_show();
}

function sf_trading_get_currency_precision(currency_code) {
	var doc = frappe.model.get_doc(":Currency", currency_code);
	if (doc && doc.number_format) return get_number_format_info(doc.number_format).precision;
	return cint(frappe.boot.sysdefaults.currency_precision) || 2;
}

function sf_trading_render_dialog(frm, payments_list) {
	if (!frm || !frm.doc) { frappe.flags.sf_trading_popup_showing = false; return; }
	const payments = payments_list || frm.doc.payments || [];
	if (!payments.length) { frappe.flags.sf_trading_popup_showing = false; return; }

	const currency = frm.doc.currency || "";
	const curr_precision = sf_trading_get_currency_precision(currency);
	const invoice_total = flt(Math.abs(flt(
		(frm.doc.outstanding_amount > 0 ? frm.doc.outstanding_amount : null) ||
		frm.doc.rounded_total || frm.doc.grand_total || 0
	)), curr_precision);

	if (invoice_total <= 0) { frappe.flags.sf_trading_popup_showing = false; frappe.msgprint(__("Invoice total must be greater than zero.")); return; }

	// Opened on an already-submitted invoice (Receive Payment button) — the
	// Payment Entry is dated today; the submit-time flow keeps the invoice date.
	const is_registering = frm.doc.docstatus === 1;
	const fields = [
		{ fieldname: "invoice_total", fieldtype: "Currency", label: __("Amount to Pay"), default: invoice_total, read_only: 1, options: "currency", precision: curr_precision },
		{ fieldtype: "Section Break", label: __("Enter Payment Amounts") },
	];
	payments.forEach(function(payment, idx) {
		const mode = payment.mode_of_payment || "Payment " + (idx + 1);
		fields.push(
			{ fieldtype: "Section Break", fieldname: "row_" + idx, label: "", hide_border: 1 },
			{ fieldname: "pay_" + idx, fieldtype: "Currency", label: mode, default: payment.amount || 0, options: "currency", precision: curr_precision },
			{ fieldtype: "Column Break", fieldname: "cb_" + idx },
			{ fieldtype: "Button", fieldname: "fill_" + idx, label: mode, click: (function(fi) { return function() { payments.forEach(function(_, i) { d.set_value("pay_" + i, i === idx ? invoice_total : 0); }); if (allow_write_off) d.set_value("write_off", 0); }; })("pay_" + idx) }
		);
	});

	// Loyalty / small balance write-off: books the unpaid remainder as a
	// deduction on the last Payment Entry so the invoice closes fully paid.
	const allow_write_off = !frm.doc.is_return;
	let wo_config = null;
	if (allow_write_off) {
		frappe.db.get_value("Company", frm.doc.company, ["write_off_account", "custom_max_payment_write_off"])
			.then(function(r) { wo_config = (r && r.message) || {}; });
		fields.push(
			{ fieldtype: "Section Break", fieldname: "row_wo", label: "", hide_border: 1 },
			{ fieldname: "write_off", fieldtype: "Currency", label: __("Write Off"), default: 0, options: "currency", precision: curr_precision },
			{ fieldtype: "Column Break", fieldname: "cb_wo" }
		);
	}

	function validate_write_off(write_off) {
		if (write_off < 0) {
			frappe.msgprint({ title: __("Error"), message: __("Write off amount cannot be negative."), indicator: "red" });
			return false;
		}
		if (!write_off) return true;
		if (!wo_config || !wo_config.write_off_account) {
			frappe.msgprint({ title: __("Write Off Not Configured"), message: __("Set 'Write Off Account' on company {0}.", [frm.doc.company]), indicator: "red" });
			return false;
		}
		const wo_limit = flt(wo_config.custom_max_payment_write_off);
		if (!wo_limit) {
			frappe.msgprint({ title: __("Write Off Not Configured"), message: __("Set 'Max Payment Write Off' on company {0} to allow write off in payments.", [frm.doc.company]), indicator: "red" });
			return false;
		}
		if (write_off - wo_limit > 0.0001) {
			frappe.msgprint({ title: __("Write Off Limit Exceeded"), message: __("Write off amount {0} exceeds the company limit of {1}.", [format_currency(write_off, currency), format_currency(wo_limit, currency)]), indicator: "red" });
			return false;
		}
		return true;
	}

	function apply_payments_and_close(vals, submit) {
		if (!vals) { frappe.msgprint({ title: __("Error"), message: __("Please enter payment amounts."), indicator: "red" }); return; }
		let total = 0;
		const payload = [];
		payments.forEach(function(p, i) {
			const amt = flt(vals["pay_" + i]) || 0;
			if (amt > 0) { payload.push({ mode_of_payment: p.mode_of_payment, amount: amt }); total += amt; }
		});
		if (!payload.length) { frappe.msgprint({ title: __("Error"), message: __("Please enter at least one payment amount."), indicator: "red" }); return; }
		const write_off = allow_write_off ? flt(vals.write_off) || 0 : 0;
		if (!validate_write_off(write_off)) return;
		const total_rounded = flt(total + write_off, curr_precision);
		if (total_rounded - invoice_total > 0.0001) { frappe.msgprint({ title: __("Error"), message: __("Total payment amount {0} cannot be greater than amount to pay {1}.", [format_currency(total_rounded, currency), format_currency(invoice_total, currency)]), indicator: "red" }); return; }
		if (invoice_total - total_rounded > 0.0001) { frappe.msgprint({ title: __("Incomplete"), message: __("{0} still to be allocated", [format_currency(invoice_total - total_rounded, currency)]), indicator: "red" }); return; }

		const finalize_payments = function() {
			const actual_os = flt(Math.abs(flt(frm.doc.outstanding_amount || 0)), curr_precision);
			if (actual_os > 0 && flt(total_rounded - actual_os) > 0.0001) {
				frappe.msgprint({ title: __("Payment Error"), message: __("Payment total ({0}) exceeds outstanding amount ({1}). The invoice may have advance payments already applied. Please create the payment manually for the correct outstanding amount.", [format_currency(total, currency), format_currency(actual_os, currency)]), indicator: "red" });
				return;
			}
			d.hide(); frappe.flags.sf_trading_popup_showing = false;
			frappe.call({
				method: "vansale.sf_trading.api.sales_invoice_payment.create_pos_payments_for_invoice",
				args: { sales_invoice: frm.doc.name, payments: JSON.stringify(payload), posting_date: is_registering ? frappe.datetime.get_today() : undefined, write_off_amount: write_off || undefined },
				freeze: true, freeze_message: __("Creating payments..."),
				callback: function(r) {
					if (r && r.message && r.message.length) { frappe.show_alert({ message: __("Created {0} Payment Entries for this invoice", [r.message.length]), indicator: "green" }, 5); frm.reload_doc(); }
				},
			});
		};

		if (submit && frm.doc.docstatus === 0) {
			frappe.flags.sf_trading_skip_payment_popup = true;
			frm.save("Submit").then(function() {
				if (frm.doc.docstatus !== 1) return;
				sf_trading_open_invoice_print(frm); finalize_payments();
			}).finally(function() { setTimeout(function() { delete frappe.flags.sf_trading_skip_payment_popup; }, 500); });
		} else if (frm.doc.docstatus === 1) {
			finalize_payments();
		} else {
			d.hide(); frappe.flags.sf_trading_popup_showing = false;
			frappe.show_alert({ message: __("Invoice saved. Submit the invoice when ready to add payments."), indicator: "blue" }, 4);
		}
	}

	const dialog_opts = {
		title: __("Enter Payment Amounts"), fields,
		primary_action_label: is_registering ? __("Receive Payment") : __("Save & Submit"),
		primary_action: function(vals) { if (vals) apply_payments_and_close(vals, true); },
		onhide: function() { frappe.flags.sf_trading_popup_showing = false; }
	};
	if (!is_registering) {
		dialog_opts.secondary_action_label = __("Save");
		dialog_opts.secondary_action = function() {
			const vals = d.get_values();
			if (frm.doc.docstatus === 0) {
				d.hide(); frappe.flags.sf_trading_popup_showing = false;
				frappe.show_alert({ message: __("Invoice saved. Submit the invoice when ready to add payments."), indicator: "blue" }, 4);
				frm.reload_doc(); return;
			}
			if (vals) apply_payments_and_close(vals, false);
		};
	}
	const d = new frappe.ui.Dialog(dialog_opts);
	d.show();

	frappe.utils.sleep(100).then(function() {
		d.$wrapper.find(".section-body").css({ display: "flex", alignItems: "flex-end" });
		payments.forEach(function(_, idx) {
			const field = d.fields_dict["pay_" + idx];
			if (!field || !field.$wrapper) return;
			field.$wrapper.find("input").off("click.sf_fill_balance").on("click.sf_fill_balance", function() {
				let other = allow_write_off ? flt(d.get_value("write_off")) || 0 : 0;
				payments.forEach(function(__, i) { if (i !== idx) other += flt(d.get_value("pay_" + i)) || 0; });
				d.set_value("pay_" + idx, Math.max(0, flt(invoice_total - other)));
			});
		});
		if (allow_write_off && d.fields_dict.write_off && d.fields_dict.write_off.$wrapper) {
			d.fields_dict.write_off.$wrapper.find("input").off("click.sf_fill_balance").on("click.sf_fill_balance", function() {
				let other = 0;
				payments.forEach(function(__, i) { other += flt(d.get_value("pay_" + i)) || 0; });
				d.set_value("write_off", Math.max(0, flt(invoice_total - other)));
			});
		}
	});
}

function sf_trading_show_pdc_popup(frm) {
	if (frappe.flags.sf_trading_popup_showing || !frm || !frm.doc) return;
	frappe.flags.sf_trading_popup_showing = true;

	const currency = frm.doc.currency || "";
	const precision = sf_trading_get_currency_precision(currency);
	const invoice_total = flt(Math.abs(flt(
		(frm.doc.outstanding_amount > 0 ? frm.doc.outstanding_amount : null) ||
		frm.doc.rounded_total || frm.doc.grand_total || 0
	)), precision);
	const base_args = { company: frm.doc.company, is_return: frm.doc.is_return ? 1 : 0, branch: frm.doc.branch || "" };

	frappe.call({
		method: "vansale.sf_trading.api.sales_invoice_payment.get_payment_modes_with_account",
		args: Object.assign({}, base_args, { is_pdc: 1 }),
		callback: function(r1) {
			const cheque_modes = r1.message || [];
			frappe.call({
				method: "vansale.sf_trading.api.sales_invoice_payment.get_payment_modes_with_account",
				args: Object.assign({}, base_args, { is_pdc: 0 }),
				callback: function(r2) {
					const cash_modes = r2.message || [];
					if (!cheque_modes.length && !cash_modes.length) {
						frappe.flags.sf_trading_popup_showing = false;
						frappe.msgprint(__("No payment modes configured for this branch."));
						return;
					}
					show_cheque_dialog(cheque_modes, cash_modes);
				},
				error: function() { frappe.flags.sf_trading_popup_showing = false; frappe.msgprint(__("Error loading Cheque payment modes. Please try again.")); },
			});
		},
		error: function() { frappe.flags.sf_trading_popup_showing = false; frappe.msgprint(__("Error loading Cheque payment modes. Please try again.")); },
	});

	const allow_write_off = !frm.doc.is_return;
	let wo_config = null;
	if (allow_write_off) {
		frappe.db.get_value("Company", frm.doc.company, ["write_off_account", "custom_max_payment_write_off"])
			.then(function(r) { wo_config = (r && r.message) || {}; });
	}

	function validate_write_off(write_off) {
		if (write_off < 0) {
			frappe.msgprint({ title: __("Error"), message: __("Write off amount cannot be negative."), indicator: "red" });
			return false;
		}
		if (!write_off) return true;
		if (!wo_config || !wo_config.write_off_account) {
			frappe.msgprint({ title: __("Write Off Not Configured"), message: __("Set 'Write Off Account' on company {0}.", [frm.doc.company]), indicator: "red" });
			return false;
		}
		const wo_limit = flt(wo_config.custom_max_payment_write_off);
		if (!wo_limit) {
			frappe.msgprint({ title: __("Write Off Not Configured"), message: __("Set 'Max Payment Write Off' on company {0} to allow write off in payments.", [frm.doc.company]), indicator: "red" });
			return false;
		}
		if (write_off - wo_limit > 0.0001) {
			frappe.msgprint({ title: __("Write Off Limit Exceeded"), message: __("Write off amount {0} exceeds the company limit of {1}.", [format_currency(write_off, currency), format_currency(wo_limit, currency)]), indicator: "red" });
			return false;
		}
		return true;
	}

	function show_cheque_dialog(cheque_modes, cash_modes) {
		const all_fns = [
			...cheque_modes.map(function(_, i) { return "chq_" + i; }),
			...cash_modes.map(function(_, i) { return "csh_" + i; }),
		];
		if (allow_write_off) all_fns.push("write_off");
		const fields = [
			{ fieldname: "invoice_total", fieldtype: "Currency", label: __("Amount to Pay"), default: invoice_total, read_only: 1, options: "currency", precision },
			{ fieldtype: "Section Break", label: __("Cheque Details") },
			{ fieldname: "cheque_date", fieldtype: "Date", label: __("Cheque Date"), reqd: 1, default: frappe.datetime.get_today() },
			{ fieldname: "cheque_no", fieldtype: "Data", label: __("Cheque No"), reqd: 1 },
		];
		if (cheque_modes.length) {
			fields.push({ fieldtype: "Section Break", label: __("Cheque Payments") });
			cheque_modes.forEach(function(mode, idx) {
				fields.push(
					{ fieldtype: "Section Break", fieldname: "chq_row_" + idx, label: "", hide_border: 1 },
					{ fieldname: "chq_" + idx, fieldtype: "Currency", label: mode, default: idx === 0 ? invoice_total : 0, options: "currency", precision },
					{ fieldtype: "Column Break" },
					{ fieldtype: "Button", fieldname: "fill_chq_" + idx, label: mode, click: (function(fi) { return function() { all_fns.forEach(function(fn) { d.set_value(fn, 0); }); d.set_value(fi, invoice_total); }; })("chq_" + idx) }
				);
			});
		}
		if (cash_modes.length) {
			fields.push({ fieldtype: "Section Break", label: __("Other Payments") });
			cash_modes.forEach(function(mode, idx) {
				fields.push(
					{ fieldtype: "Section Break", fieldname: "csh_row_" + idx, label: "", hide_border: 1 },
					{ fieldname: "csh_" + idx, fieldtype: "Currency", label: mode, default: 0, options: "currency", precision },
					{ fieldtype: "Column Break" },
					{ fieldtype: "Button", fieldname: "fill_csh_" + idx, label: mode, click: (function(fi) { return function() { all_fns.forEach(function(fn) { d.set_value(fn, 0); }); d.set_value(fi, invoice_total); }; })("csh_" + idx) }
				);
			});
		}
		if (allow_write_off) {
			fields.push(
				{ fieldtype: "Section Break", fieldname: "wo_row", label: "", hide_border: 1 },
				{ fieldname: "write_off", fieldtype: "Currency", label: __("Write Off"), default: 0, options: "currency", precision },
				{ fieldtype: "Column Break" }
			);
		}

		function apply_and_close(vals, submit) {
			if (!vals) return;
			let cheque_total = 0, cash_total = 0;
			const cheque_payments = [], cash_payments = [];
			cheque_modes.forEach(function(mode, i) { const amt = flt(vals["chq_" + i]) || 0; if (amt > 0) { cheque_payments.push({ mode_of_payment: mode, amount: amt }); cheque_total += amt; } });
			cash_modes.forEach(function(mode, i) { const amt = flt(vals["csh_" + i]) || 0; if (amt > 0) { cash_payments.push({ mode_of_payment: mode, amount: amt }); cash_total += amt; } });
			if (!cheque_payments.length && !cash_payments.length) { frappe.msgprint({ title: __("Error"), message: __("Please enter at least one payment amount."), indicator: "red" }); return; }
			const write_off = allow_write_off ? flt(vals.write_off) || 0 : 0;
			if (!validate_write_off(write_off)) return;
			const cheque_date = vals.cheque_date, cheque_no = (vals.cheque_no || "").trim();
			const total_rounded = flt(cheque_total + cash_total + write_off, precision);
			if (total_rounded - invoice_total > 0.0001) { frappe.msgprint({ title: __("Error"), message: __("Total payment {0} exceeds amount to pay {1}.", [format_currency(total_rounded, currency), format_currency(invoice_total, currency)]), indicator: "red" }); return; }
			if (invoice_total - total_rounded > 0.0001) { frappe.msgprint({ title: __("Incomplete"), message: __("{0} still to be allocated.", [format_currency(invoice_total - total_rounded, currency)]), indicator: "red" }); return; }

			const finalize = function() {
				const actual_os = flt(Math.abs(flt(frm.doc.outstanding_amount || 0)), precision);
				if (actual_os > 0 && flt(total_rounded - actual_os) > 0.0001) {
					frappe.msgprint({ title: __("Payment Error"), message: __("Payment total ({0}) exceeds outstanding amount ({1}). The invoice may have advance payments already applied. Please create the payment manually.", [format_currency(total_rounded, currency), format_currency(actual_os, currency)]), indicator: "red" });
					return;
				}
				d.hide(); frappe.flags.sf_trading_popup_showing = false;
				// The write-off rides on the last API call so the final Payment
				// Entry closes the invoice: the cash call when present, else the cheque call.
				function create_cash(created) {
					if (!cash_payments.length) { frappe.show_alert({ message: __("Cheque Payment Entry created."), indicator: "green" }, 5); frm.reload_doc(); return; }
					frappe.call({
						method: "vansale.sf_trading.api.sales_invoice_payment.create_pos_payments_for_invoice",
						args: { sales_invoice: frm.doc.name, payments: JSON.stringify(cash_payments), write_off_amount: write_off || undefined },
						freeze: true, freeze_message: __("Creating Cheque payment..."),
						callback: function(r) {
							const n = (created || 0) + ((r && r.message) ? r.message.length : 0);
							if (n) { frappe.show_alert({ message: __("Cheque Payment Entry created."), indicator: "green" }, 5); frm.reload_doc(); }
						},
					});
				}
				if (cheque_payments.length) {
					frappe.call({
						method: "vansale.sf_trading.api.sales_invoice_payment.create_pos_payments_for_invoice",
						args: { sales_invoice: frm.doc.name, payments: JSON.stringify(cheque_payments), cheque_date, cheque_no, write_off_amount: cash_payments.length ? undefined : (write_off || undefined) },
						freeze: true, freeze_message: __("Creating Cheque payment..."),
						callback: function(r) { create_cash((r && r.message) ? r.message.length : 0); },
					});
				} else { create_cash(0); }
			};

			if (submit && frm.doc.docstatus === 0) {
				frappe.flags.sf_trading_skip_payment_popup = true;
				frm.save("Submit").then(function() {
					if (frm.doc.docstatus !== 1) return;
					sf_trading_open_invoice_print(frm); finalize();
				}).finally(function() { setTimeout(function() { delete frappe.flags.sf_trading_skip_payment_popup; }, 500); });
			} else if (frm.doc.docstatus === 1) {
				finalize();
			} else {
				frappe.show_alert({ message: __("Invoice saved. Submit when ready to record the Cheque payment."), indicator: "blue" }, 4);
			}
		}

		const d = new frappe.ui.Dialog({
			title: __("Cheque Payment"), fields,
			primary_action_label: __("Save & Submit"),
			primary_action: function(vals) { if (vals) apply_and_close(vals, true); },
			secondary_action_label: __("Save"),
			secondary_action: function() {
				if (frm.doc.docstatus === 0) {
					d.hide(); frappe.flags.sf_trading_popup_showing = false;
					frappe.show_alert({ message: __("Invoice saved. Submit when ready to record the Cheque payment."), indicator: "blue" }, 4);
					frm.reload_doc(); return;
				}
				const vals = d.get_values();
				if (vals) apply_and_close(vals, false);
			},
			onhide: function() { frappe.flags.sf_trading_popup_showing = false; },
		});
		d.show();
		frappe.utils.sleep(100).then(function() {
			d.$wrapper.find(".section-body").css({ display: "flex", alignItems: "flex-end" });
			all_fns.forEach(function(fn, idx) {
				const field = d.fields_dict[fn];
				if (!field || !field.$wrapper) return;
				field.$wrapper.find("input").off("click.sf_cheque").on("click.sf_cheque", function() {
					let other = 0;
					all_fns.forEach(function(ofn, oi) { if (oi !== idx) other += flt(d.get_value(ofn)) || 0; });
					d.set_value(fn, Math.max(0, flt(invoice_total - other)));
				});
			});
		});
	}
}

// ═══════════════════════════════════════════════════════════════════════════════
// Sales Person auto-populate
// ═══════════════════════════════════════════════════════════════════════════════

// The field has ignore_user_permissions=1, so frappe won't auto-default it
// from the User Permission — do it ourselves (dropdown stays unrestricted).
function set_sales_person_from_user_permission(frm) {
	if (frm.doc.custom_sales_person) return;
	const user_permissions = frappe.defaults.get_user_permissions();
	if (!user_permissions || $.isEmptyObject(user_permissions)) return;
	const { allowed_records, default_doc } = frappe.perm.filter_allowed_docs_for_doctype(
		user_permissions["Sales Person"],
		frm.doc.doctype
	);
	const sales_person =
		default_doc || (allowed_records && allowed_records.length === 1 ? allowed_records[0] : null);
	if (sales_person) frm.set_value("custom_sales_person", sales_person);
}

frappe.ui.form.on("Sales Invoice", {
	onload: function(frm) {
		if (frm.is_new()) {
			set_sales_person_from_user_permission(frm);
		}
	},
	customer: function(frm) {
		if (!frm.doc.customer) return;
		frappe.db.get_doc("Customer", frm.doc.customer).then(function(doc) {
			// Customer has no sales team → keep the sales person already on the invoice
			if (!doc.sales_team || !doc.sales_team.length) return;
			frm.set_value("custom_sales_person", "");
			frm.clear_table("sales_team");
			frm.refresh_field("sales_team");
			frm.set_value("custom_sales_person", doc.sales_team[0].sales_person);
			doc.sales_team.forEach(function(d) {
				const row = frm.add_child("sales_team");
				row.sales_person = d.sales_person;
				row.allocated_percentage = d.allocated_percentage || 100;
			});
			frm.refresh_field("sales_team");
		});
	},
	custom_sales_person: function(frm) {
		if (!frm.doc.custom_sales_person) return;
		frm.clear_table("sales_team");
		const row = frm.add_child("sales_team");
		row.sales_person = frm.doc.custom_sales_person;
		row.allocated_percentage = 100;
		frm.refresh_field("sales_team");
	},
});

// ═══════════════════════════════════════════════════════════════════════════════
// Warehouse Qty Realtime validation
// ═══════════════════════════════════════════════════════════════════════════════

(function () {
	function get_available_qty(item_code, warehouse) {
		return frappe.call({
			method: "vansale.sf_trading.api.warehouse_stock.get_available_qty",
			args: { item_code: item_code, warehouse: warehouse },
		}).then(function(r) { return flt(r.message); });
	}

	// Resolves to true if the row's qty fits in available stock. When it doesn't,
	// shows the shortfall, zeroes the qty, and flags the row so a save stays
	// blocked even after the qty has been reset to 0 (it would otherwise look
	// "valid" again and slip through).
	function validate_row_qty(cdt, cdn, reset_on_fail) {
		var row = locals[cdt][cdn];
		if (!row || !row.item_code || !row.warehouse || !(flt(row.qty) > 0)) return Promise.resolve(true);
		return get_available_qty(row.item_code, row.warehouse).then(function(available) {
			var qty_in_stock_uom = flt(row.qty) * flt(row.conversion_factor || 1);
			if (qty_in_stock_uom > available) {
				var available_in_row_uom = flt(row.conversion_factor || 1) > 0
					? available / flt(row.conversion_factor) : available;
				frappe.msgprint({
					title: __("Insufficient Stock"),
					indicator: "red",
					message: __("Available qty for {0} in {1} is {2} {3}. Quantity has been reset to 0 — this row will block saving until fixed.", [
						row.item_code, row.warehouse,
						format_number(available_in_row_uom, null, 3), row.uom || "",
					]),
				});
				row._sf_insufficient_stock = true;
				if (reset_on_fail) frappe.model.set_value(cdt, cdn, "qty", 0);
				return false;
			}
			row._sf_insufficient_stock = false;
			return true;
		});
	}

	function check_warehouse_qty(frm, cdt, cdn) {
		if (!frm.doc.update_stock) return;
		validate_row_qty(cdt, cdn, true);
	}

	frappe.ui.form.on("Sales Invoice Item", {
		qty: check_warehouse_qty,
		warehouse: check_warehouse_qty,
		item_code: function(frm, cdt, cdn) {
			setTimeout(function() { check_warehouse_qty(frm, cdt, cdn); }, 1000);
		},
	});

	frappe.ui.form.on("Sales Invoice", {
		validate: function(frm) {
			if (!frm.doc.update_stock) return;
			if (!frm.doc.items || !frm.doc.items.length) return;
			var blocked_items = [];
			var checks = frm.doc.items.map(function(row) {
				return validate_row_qty(row.doctype, row.name, true).then(function(ok) {
					if (!ok || row._sf_insufficient_stock) {
						frappe.validated = false;
						blocked_items.push(row.item_code);
					}
				});
			});
			return Promise.all(checks).then(function() {
				if (!frappe.validated && blocked_items.length) {
					frappe.msgprint({
						title: __("Cannot Save"),
						indicator: "red",
						message: __("Cannot save: insufficient warehouse stock for {0}. Fix the quantity or remove the item.", [blocked_items.join(", ")]),
					});
				}
			});
		},
	});
})();

// ═══════════════════════════════════════════════════════════════════════════════
// Real-time credit limit popup (Credit mode)
// Watches item changes and warns the moment outstanding + this invoice
// exceeds the customer's credit limit. Also re-warns on save.
// ═══════════════════════════════════════════════════════════════════════════════

(function() {
	function credit_check_applies(frm) {
		return frm.doc.docstatus === 0
			&& !frm.doc.is_return
			&& frm.doc.custom_payment_mode === "Credit"
			&& frm.doc.customer
			&& frm.doc.company;
	}

	function fetch_credit_status(frm) {
		var key = frm.doc.customer + "::" + frm.doc.company;
		if (frm._sf_credit_status && frm._sf_credit_status.key === key) {
			return Promise.resolve(frm._sf_credit_status);
		}
		return frappe.call({
			method: "vansale.sf_trading.api.sales_invoice_override.get_credit_limit_status",
			args: { customer: frm.doc.customer, company: frm.doc.company },
		}).then(function(r) {
			var status = r.message || {};
			status.key = key;
			frm._sf_credit_status = status;
			return status;
		});
	}

	function run_credit_check(frm) {
		if (!credit_check_applies(frm)) return;
		fetch_credit_status(frm).then(function(status) {
			if (!flt(status.credit_limit)) return;

			var invoice_total = flt(frm.doc.base_grand_total || frm.doc.grand_total);
			var projected = flt(status.outstanding) + invoice_total;
			var limit = flt(status.credit_limit);
			var currency = status.currency;

			// Warn on every change (and on save) while the total stays over the limit
			if (projected > limit) {
				frappe.msgprint({
					title: __("Credit Limit Exceeded"),
					indicator: "red",
					message: __(
						"Customer {0}<br>Credit Limit: <b>{1}</b><br>Current Outstanding: <b>{2}</b><br>"
						+ "This Invoice: <b>{3}</b><br>Exceeds limit by: <b>{4}</b>",
						[frm.doc.customer, format_currency(limit, currency),
						 format_currency(status.outstanding, currency), format_currency(invoice_total, currency),
						 format_currency(projected - limit, currency)]
					),
				});
			}
		});
	}

	function schedule_credit_check(frm) {
		// Debounce: let ERPNext finish recalculating totals (rate fetch is async)
		if (frm._sf_credit_check_timer) clearTimeout(frm._sf_credit_check_timer);
		frm._sf_credit_check_timer = setTimeout(function() { run_credit_check(frm); }, 600);
	}

	frappe.ui.form.on("Sales Invoice Item", {
		item_code: function(frm) { schedule_credit_check(frm); },
		qty: function(frm) { schedule_credit_check(frm); },
		rate: function(frm) { schedule_credit_check(frm); },
		items_remove: function(frm) { schedule_credit_check(frm); },
	});

	frappe.ui.form.on("Sales Invoice", {
		refresh: function(frm) {
			if (credit_check_applies(frm) && (frm.doc.items || []).length) {
				schedule_credit_check(frm);
			}
		},
		customer: function(frm) {
			frm._sf_credit_status = null;
			schedule_credit_check(frm);
		},
		custom_payment_mode: function(frm) { schedule_credit_check(frm); },
		discount_amount: function(frm) { schedule_credit_check(frm); },
		additional_discount_percentage: function(frm) { schedule_credit_check(frm); },
		validate: function(frm) {
			// Warn on save too
			run_credit_check(frm);
		},
	});
})();
