// Warehouse Stock Display for sf_trading
// Shows warehouse stock at bottom of item table and button to request items

frappe.provide("sf_trading");

// Store stock display element per form
sf_trading.stock_displays = {};

sf_trading.show_warehouse_stock = function(frm, item_row, load_all = false) {
	// Check if item_code is set
	if (!item_row || !item_row.item_code) {
		sf_trading.hide_stock_display(frm);
		return;
	}

	// Check if warehouse field exists
	if (!frappe.meta.has_field(item_row.doctype, "warehouse")) {
		sf_trading.hide_stock_display(frm);
		return;
	}

	// Get company from form
	let company = frm.doc.company;
	if (!company) {
		sf_trading.hide_stock_display(frm);
		return;
	}

	// Get current warehouse if set
	let current_row = locals[item_row.doctype][item_row.name];
	let warehouse = current_row ? (current_row.warehouse || "") : "";

	// Prepare API args - limit to 5 if not loading all
	let api_args = {
		item_code: item_row.item_code,
		company: company,
		target_warehouse: warehouse || null
	};

	if (!load_all) {
		api_args.limit = 5;
	}

	// Fetch warehouse stock data
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
		error: function(r) {
			sf_trading.hide_stock_display(frm);
		}
	});
};

sf_trading.render_stock_display = function(frm, item_code, stock_data, target_warehouse, item_row_name, is_all_loaded = false) {
	// Get items grid
	if (!frm.fields_dict.items || !frm.fields_dict.items.grid) {
		return;
	}

	const grid = frm.fields_dict.items.grid;
	const grid_wrapper = grid.wrapper;

	// Remove existing stock display if any
	sf_trading.hide_stock_display(frm);

	// Find the grid footer or create container after grid
	let $container = grid_wrapper.find(".sf-trading-stock-display");
	if (!$container.length) {
		// Create container after grid body - reduced padding
		$container = $('<div class="sf-trading-stock-display" style="margin-top: 8px; padding: 8px; background-color: #f9f9f9; border: 1px solid #d1d8dd; border-radius: 4px;"></div>');
		grid_wrapper.append($container);
	}

	// Data is already filtered and sorted by backend
	// Get target warehouse name
	let target_warehouse_name = "";
	if (target_warehouse) {
		let target_wh = stock_data.find(function(item) {
			return item.warehouse === target_warehouse;
		});
		target_warehouse_name = target_wh ? (target_wh.warehouse_name || target_warehouse) : target_warehouse;
	}

	// If all data is loaded, show all; otherwise only show loaded data (max 5)
	let sorted_stock_data = stock_data;
	let visible_data, hidden_data, has_more;

	if (is_all_loaded) {
		// All data loaded - split into visible (first 5) and hidden (rest) for collapse functionality
		visible_data = sorted_stock_data.slice(0, 5);
		hidden_data = sorted_stock_data.slice(5);
		has_more = hidden_data.length > 0;
	} else {
		// Only 5 loaded - show all of them (no hidden rows)
		visible_data = sorted_stock_data;
		hidden_data = [];
		// If we got exactly 5 items, there might be more to load
		has_more = sorted_stock_data.length >= 5;
	}

	// Generate unique ID for this display
	let display_id = "sf_stock_" + Date.now() + "_" + Math.random().toString(36).substr(2, 9);

	// Determine button text and visibility
	let show_toggle_button = false;
	let button_text = "";
	let button_action = ""; // "load_all" or "toggle_view"
	let initial_collapsed = false; // Start collapsed (show only 5) when all loaded

	if (has_more && !is_all_loaded) {
		// Not all loaded - show "Show All" button to fetch more
		show_toggle_button = true;
		button_text = __("Show All");
		button_action = "load_all";
	} else if (is_all_loaded && sorted_stock_data.length > 5) {
		// All loaded and more than 5 - show toggle to collapse/expand
		show_toggle_button = true;
		button_text = __("Show Less"); // Will toggle to "Show All" when collapsed
		button_action = "toggle_view";
		initial_collapsed = false; // Start expanded (show all)
	}

	let html = `
		<div style="margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
			<div>
				<strong style="font-size: 14px;">${__("Stock Availability - {0}", [item_code])}</strong>
				${target_warehouse ? `<span style="font-size: 12px; color: #666; margin-left: 8px;">→ ${target_warehouse_name}</span>` : ''}
			</div>
			${show_toggle_button ? `
			<button class="btn btn-xs btn-link ${display_id}_toggle_btn"
				data-action="${button_action}"
				style="padding: 2px 6px; font-size: 12px; color: #007bff; text-decoration: none; margin-left: auto;">
				${button_text}
			</button>
			` : ''}
		</div>
		<div style="max-height: 300px; overflow-y: auto;">
			<table class="table table-bordered" style="margin: 0; background-color: white; font-size: 13px;">
				<thead>
					<tr style="background-color: #f5f5f5;">
						<th style="padding: 6px 8px; width: 50%; font-size: 13px;">${__("Warehouse")}</th>
						<th style="padding: 6px 8px; text-align: right; width: 30%; font-size: 13px;">${__("Stock Qty")}</th>
						<th style="padding: 6px 8px; text-align: center; width: 20%; font-size: 13px;">${__("Action")}</th>
					</tr>
				</thead>
				<tbody id="${display_id}_tbody">
	`;

	if (sorted_stock_data.length === 0) {
		html += `
			<tr>
				<td colspan="3" style="padding: 10px; text-align: center; color: #999; font-size: 13px;">
					${__("No warehouses with stock available")}
				</td>
			</tr>
		`;
	} else {
		// Render visible rows (first 5)
		visible_data.forEach(function(item, index) {
			let stock_color = item.stock_qty > 0 ? "#28a745" : "#6c757d";
			let stock_indicator = item.stock_qty > 0 ? "●" : "○";
			let is_target = item.warehouse === target_warehouse;
			let row_bg = is_target ? "#e3f2fd" : "white";
			let row_class = `${display_id}_row`;

			html += `
				<tr class="${row_class}" style="background-color: ${row_bg};">
					<td style="padding: 6px 8px;">
						<span style="color: ${stock_color}; margin-right: 5px; font-size: 12px;">${stock_indicator}</span>
						<span style="font-size: 13px;">${item.warehouse_name || item.warehouse}</span>
						${is_target ? '<span style="color: #2196f3; margin-left: 5px; font-size: 12px;">(Target)</span>' : ''}
					</td>
					<td style="padding: 6px 8px; text-align: right;">
						<span style="color: ${stock_color}; font-weight: bold; font-size: 13px;">
							${format_number(item.stock_qty, null, {precision: 2})}
						</span>
					</td>
					<td style="padding: 6px 8px; text-align: center;">
						${is_target ? '<span style="color: #999; font-size: 12px;">-</span>' : `
						<button class="btn btn-xs btn-primary request-item-btn"
							data-item-code="${item_code.replace(/"/g, '&quot;')}"
							data-from-warehouse="${item.warehouse.replace(/"/g, '&quot;')}"
							data-from-warehouse-name="${(item.warehouse_name || item.warehouse).replace(/"/g, '&quot;')}"
							data-to-warehouse="${target_warehouse.replace(/"/g, '&quot;')}"
							data-to-warehouse-name="${target_warehouse_name.replace(/"/g, '&quot;')}"
							data-item-row-name="${item_row_name.replace(/"/g, '&quot;')}"
							style="padding: 3px 10px; font-size: 12px;">
							${__("Request Items")}
						</button>
						`}
					</td>
				</tr>
			`;
		});

		// Render hidden rows (rest, initially hidden) - only if all data is loaded
		if (has_more && is_all_loaded && hidden_data.length > 0) {
			hidden_data.forEach(function(item, index) {
				let stock_color = item.stock_qty > 0 ? "#28a745" : "#6c757d";
				let stock_indicator = item.stock_qty > 0 ? "●" : "○";
				let is_target = item.warehouse === target_warehouse;
				let row_bg = is_target ? "#e3f2fd" : "white";
				let row_class = `${display_id}_row ${display_id}_hidden_row`;

				html += `
					<tr class="${row_class}" style="display: table-row; background-color: ${row_bg};">
						<td style="padding: 6px 8px;">
							<span style="color: ${stock_color}; margin-right: 5px; font-size: 12px;">${stock_indicator}</span>
							<span style="font-size: 13px;">${item.warehouse_name || item.warehouse}</span>
							${is_target ? '<span style="color: #2196f3; margin-left: 5px; font-size: 12px;">(Target)</span>' : ''}
						</td>
						<td style="padding: 6px 8px; text-align: right;">
							<span style="color: ${stock_color}; font-weight: bold; font-size: 13px;">
								${format_number(item.stock_qty, null, {precision: 2})}
							</span>
						</td>
						<td style="padding: 6px 8px; text-align: center;">
							${is_target ? '<span style="color: #999; font-size: 12px;">-</span>' : `
							<button class="btn btn-xs btn-primary request-item-btn"
								data-item-code="${item_code.replace(/"/g, '&quot;')}"
								data-from-warehouse="${item.warehouse.replace(/"/g, '&quot;')}"
								data-from-warehouse-name="${(item.warehouse_name || item.warehouse).replace(/"/g, '&quot;')}"
								data-to-warehouse="${target_warehouse.replace(/"/g, '&quot;')}"
								data-to-warehouse-name="${target_warehouse_name.replace(/"/g, '&quot;')}"
								data-item-row-name="${item_row_name.replace(/"/g, '&quot;')}"
								style="padding: 3px 10px; font-size: 12px;">
								${__("Request Items")}
							</button>
							`}
						</td>
					</tr>
				`;
			});
		}
	}

	html += `
				</tbody>
			</table>
		</div>
	`;

	$container.html(html);
	$container.show();

	// Store reference
	sf_trading.stock_displays[frm.doctype + "_" + frm.docname] = $container;

	// Add toggle button handler
	let $toggle_btn = $container.find(`.${display_id}_toggle_btn`);
	if ($toggle_btn.length) {
		let button_action = $toggle_btn.data("action");
		// Store expanded state - start expanded (show all) when all data is loaded
		let is_expanded = (button_action === "toggle_view");

		$toggle_btn.on("click", function() {
			if (button_action === "load_all") {
				// Fetch all warehouses when "Show All" is clicked
				let item_doctype = "Sales Invoice Item";
				let item_row = locals[item_doctype] && locals[item_doctype][item_row_name];
				if (item_row && item_row.item_code) {
					// Show loading state
					$toggle_btn.prop("disabled", true).html(__("Loading..."));

					// Fetch all warehouses (load_all = true)
					sf_trading.show_warehouse_stock(frm, item_row, true);
				}
			} else if (button_action === "toggle_view") {
				// Toggle between showing 5 and showing all
				let $hidden_rows = $container.find(`.${display_id}_hidden_row`);

				if (is_expanded) {
					// Collapse: hide rows beyond first 5
					$hidden_rows.hide();
					$toggle_btn.html(__("Show All"));
					is_expanded = false;
				} else {
					// Expand: show all rows
					$hidden_rows.show();
					$toggle_btn.html(__("Show Less"));
					is_expanded = true;
				}
			}
		});
	}

	// Add click handlers for request buttons
	$container.find(".request-item-btn").on("click", function() {
		let $btn = $(this);
		let item_code = $btn.data("item-code");
		let from_warehouse = $btn.data("from-warehouse");
		let from_warehouse_name = $btn.data("from-warehouse-name");
		let to_warehouse = $btn.data("to-warehouse");
		let to_warehouse_name = $btn.data("to-warehouse-name");

		sf_trading.create_material_request(frm, item_code, from_warehouse, from_warehouse_name, to_warehouse, to_warehouse_name);
	});
};

sf_trading.hide_stock_display = function(frm) {
	let key = frm.doctype + "_" + frm.docname;
	let $display = sf_trading.stock_displays[key];
	if ($display && $display.length) {
		$display.hide();
	}
};

sf_trading.create_material_request = function(frm, item_code, from_warehouse, from_warehouse_name, to_warehouse, to_warehouse_name) {
	// Create Material Request dialog
	let dialog = new frappe.ui.Dialog({
		title: __("Create Material Transfer Request"),
		fields: [
			{
				fieldtype: "Data",
				fieldname: "item_code",
				label: __("Item Code"),
				default: item_code,
				read_only: 1
			},
			{
				fieldtype: "Data",
				fieldname: "from_warehouse",
				label: __("From Warehouse"),
				default: from_warehouse_name || from_warehouse,
				read_only: 1
			},
			{
				fieldtype: "Data",
				fieldname: "to_warehouse",
				label: __("To Warehouse"),
				default: to_warehouse_name || to_warehouse,
				read_only: 1
			},
			{
				fieldtype: "Float",
				fieldname: "qty",
				label: __("Quantity"),
				default: 1,
				reqd: 1
			},
			{
				fieldtype: "Date",
				fieldname: "schedule_date",
				label: __("Required Date"),
				default: frappe.datetime.add_days(frappe.datetime.get_today(), 7),
				reqd: 1
			}
		],
		primary_action_label: __("Create"),
		primary_action: function() {
			let values = dialog.get_values();
			if (!values) {
				return;
			}

			// Create Material Request (always Material Transfer)
			frappe.call({
				method: "vansale.sf_trading.api.material_request.create_material_request",
				args: {
					item_code: values.item_code,
					from_warehouse: from_warehouse,
					to_warehouse: to_warehouse,
					qty: values.qty,
					schedule_date: values.schedule_date,
					material_request_type: "Material Transfer",
					company: frm.doc.company
				},
				callback: function(r) {
					if (r.message) {
						let current_route = frappe.get_route();
						frappe.show_alert({
							message: __("Material Request {0} created and submitted ", [r.message]),
							indicator: "green"
						});
						setTimeout(function() {
						frappe.set_route(current_route);
						}, 300);
						}
					dialog.hide();
				},
				error: function(r) {
					frappe.show_alert({
						message: __("Error creating Material Request"),
						indicator: "red"
					});
				}
			});
		}
	});

	dialog.show();
};

// Hook into item_code and warehouse onchange - Only for Sales Invoice
let item_doctypes = [
	"Sales Invoice Item"
];

// Track currently selected row
sf_trading.current_selected_row = null;

item_doctypes.forEach(function(child_doctype) {
	frappe.ui.form.on(child_doctype, {
		item_code: function(frm, cdt, cdn) {
			let item_row = locals[cdt][cdn];

			// Track selected row
			sf_trading.current_selected_row = item_row;

			if (item_row.item_code &&
				frappe.meta.has_field(item_row.doctype, "warehouse") &&
				frm.doc.company) {

				clearTimeout(item_row._sf_trading_stock_timeout);
				item_row._sf_trading_stock_timeout = setTimeout(function() {
					sf_trading.show_warehouse_stock(frm, item_row);
				}, 300);
			} else {
				sf_trading.hide_stock_display(frm);
			}
		},

		// ERPNext calls refresh_field("items") after fetching item details, which
		// removes our appended stock display div. Re-show once item_name is set
		// (that event fires after the item fetch + grid refresh completes).
		item_name: function(frm, cdt, cdn) {
			let item_row = locals[cdt][cdn];
			sf_trading.current_selected_row = item_row;
			if (item_row.item_code &&
				frappe.meta.has_field(item_row.doctype, "warehouse") &&
				frm.doc.company) {
				clearTimeout(item_row._sf_trading_stock_timeout);
				item_row._sf_trading_stock_timeout = setTimeout(function() {
					sf_trading.show_warehouse_stock(frm, item_row);
				}, 100);
			}
		},

		item_code_focus: function(frm, cdt, cdn) {
			// When item_code field is focused/clicked, show stock for that row
			let item_row = locals[cdt][cdn];
			if (item_row && item_row.item_code &&
				frappe.meta.has_field(item_row.doctype, "warehouse") &&
				frm.doc.company) {
				sf_trading.current_selected_row = item_row;
				clearTimeout(item_row._sf_trading_stock_timeout);
				item_row._sf_trading_stock_timeout = setTimeout(function() {
					sf_trading.show_warehouse_stock(frm, item_row);
				}, 100);
			}
		},

		warehouse: function(frm, cdt, cdn) {
			let item_row = locals[cdt][cdn];

			// Track selected row
			sf_trading.current_selected_row = item_row;

			if (item_row.item_code &&
				frappe.meta.has_field(item_row.doctype, "warehouse") &&
				frm.doc.company) {

				// Update stock display when warehouse changes
				clearTimeout(item_row._sf_trading_stock_timeout);
				item_row._sf_trading_stock_timeout = setTimeout(function() {
					sf_trading.show_warehouse_stock(frm, item_row);
				}, 300);
			}
		},

		// Detect when row is selected/clicked
		form_render: function(frm, cdt, cdn) {
			let item_row = locals[cdt][cdn];
			if (item_row && item_row.item_code) {
				sf_trading.current_selected_row = item_row;
				if (frm.doc.company && frappe.meta.has_field(item_row.doctype, "warehouse")) {
					clearTimeout(item_row._sf_trading_stock_timeout);
					item_row._sf_trading_stock_timeout = setTimeout(function() {
						sf_trading.show_warehouse_stock(frm, item_row);
					}, 200);
				}
			}
		}
	});
});

// Listen to item_code field clicks/focus for all doctypes
function setup_item_code_field_listeners(frm) {
	if (!frm.fields_dict.items || !frm.fields_dict.items.grid) {
		return;
	}

	const grid = frm.fields_dict.items.grid;

	// Listen for clicks on item_code field in grid rows
	grid.wrapper.on("click focus", "[data-fieldname='item_code'] input, [data-fieldname='item_code'] .link-field", function() {
		let $field = $(this);
		let $row = $field.closest(".grid-row");
		let idx = $row.attr("data-idx");

		if (idx && frm.doc.items) {
			let item_row = frm.doc.items.find(function(item) {
				return item.idx == idx;
			});

			if (item_row && item_row.item_code) {
				sf_trading.current_selected_row = item_row;
				if (frm.doc.company && frappe.meta.has_field(item_row.doctype, "warehouse")) {
					clearTimeout(item_row._sf_trading_stock_timeout);
					item_row._sf_trading_stock_timeout = setTimeout(function() {
						sf_trading.show_warehouse_stock(frm, item_row);
					}, 100);
				}
			}
		}
	});
}

// Hide stock availability when user clicks or focuses outside the items grid
function setup_hide_stock_on_click_outside(frm) {
	if (!frm.fields_dict.items || !frm.fields_dict.items.grid) {
		return;
	}

	const grid = frm.fields_dict.items.grid;
	const $grid_wrapper = grid.wrapper;

	// Remove previous handlers to avoid duplicates on refresh
	$grid_wrapper.off("focusout.sf_trading_stock");
	if (frm.wrapper) {
		$(frm.wrapper).off("click.sf_trading_stock");
	}

	// When focus leaves the grid, hide stock if focus did not move to another element inside the grid
	$grid_wrapper.on("focusout.sf_trading_stock", function() {
		setTimeout(function() {
			const active = document.activeElement;
			if (!active || !$grid_wrapper[0].contains(active)) {
				sf_trading.hide_stock_display(frm);
			}
		}, 150);
	});

	// When user clicks anywhere on the form, hide stock if click was outside the items grid
	if (frm.wrapper) {
		$(frm.wrapper).on("click.sf_trading_stock", function(e) {
			if (!$grid_wrapper.length || !$grid_wrapper[0].contains(e.target)) {
				sf_trading.hide_stock_display(frm);
			}
		});
	}
}

// Sales Invoice only
frappe.ui.form.on("Sales Invoice", {
	refresh: function(frm) {
		setup_item_code_field_listeners(frm);
		// Always hide stock on load/refresh until user clicks an item
		sf_trading.hide_stock_display(frm);

		// Hide stock when user clicks or focuses outside the items grid
		setup_hide_stock_on_click_outside(frm);
	}
});
