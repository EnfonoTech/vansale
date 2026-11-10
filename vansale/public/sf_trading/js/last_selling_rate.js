// Last Selling Rate feature for sf_trading
// Shows a button to view last selling rate of items

frappe.provide("sf_trading");

sf_trading.add_last_selling_rate_button = function(frm) {
	if (!frm.fields_dict.items) return;
	if (!frm.fields_dict.items.grid) return;

	const grid = frm.fields_dict.items.grid;

	// Track last clicked row in items grid for default item in Last Selling Rate dialog.
	// Use capture phase so we run before the row's click handler (which stops propagation).
	if (!grid.wrapper.data('last_selling_rate_click_bound')) {
		const capture_handler = function (e) {
			const $body = grid.wrapper.find('.grid-body');
			if (!$body.length || !$body[0].contains(e.target)) return;
			const $row = $(e.target).closest('.grid-row');
			if (!$row.length) return;
			const grid_row = $row.data('grid_row');
			if (grid_row && grid_row.doc && grid_row.doc.item_code) {
				frm._last_selling_rate_clicked_item_code = grid_row.doc.item_code;
			}
		};
		grid.wrapper[0].addEventListener('click', capture_handler, true);
		// Track which row had focus so "add row + select item" works without clicking the row
		function update_focused_item(e) {
			const $body = grid.wrapper.find('.grid-body');
			if (!$body.length || !$body[0].contains(e.target)) return;
			const $row = $(e.target).closest('.grid-row');
			if (!$row.length) return;
			const grid_row = $row.data('grid_row');
			if (grid_row && grid_row.doc && grid_row.doc.item_code) {
				frm._last_selling_rate_focused_item_code = grid_row.doc.item_code;
			}
		}
		grid.wrapper[0].addEventListener('focusin', update_focused_item, true);
		// On focusout we read the row's current item (so after selecting from dropdown we still get it)
		grid.wrapper[0].addEventListener('focusout', update_focused_item, true);
		grid.wrapper.data('last_selling_rate_click_bound', true);
		grid.wrapper.data('last_selling_rate_capture_handler', capture_handler);
	}
	
	// Try multiple ways to find the toolbar
	let $toolbar = grid.wrapper.find(".grid-buttons");
	
	// If not found, try finding it in the grid footer
	if (!$toolbar.length) {
		$toolbar = grid.wrapper.find(".grid-footer .grid-buttons");
	}
	
	// If still not found, try finding the footer first
	if (!$toolbar.length) {
		const $footer = grid.wrapper.find(".grid-footer");
		if ($footer.length) {
			$toolbar = $footer.find(".grid-buttons");
		}
	}
	
	// Alternative: try to find it by looking for "Add Row" button
	if (!$toolbar.length) {
		const $addRowBtn = grid.wrapper.find("button:contains('Add Row')");
		if ($addRowBtn.length) {
			$toolbar = $addRowBtn.closest(".grid-buttons");
		}
	}
	
	if (!$toolbar.length) return;
	
	// Check if button already exists
	if ($toolbar.find("button:contains('Last Selling Rate')").length > 0) {
		return;
	}

	// Find a good position for the button (after Price Assist, Add Multiple, or Add Row)
	let $target = $toolbar.find("button:contains('Price Assist')").last();
	
	if ($target.length === 0) {
		$target = $toolbar.find("button:contains('Add Multiple')").last();
	}
	
	if ($target.length === 0) {
		$target = $toolbar.find("button:contains('Add Row')").last();
	}
	
	if ($target.length === 0) {
		$target = $toolbar.children().first();
	}

	// Create the button
	let last_selling_rate_btn = $(`<button type="button" class="btn btn-secondary btn-xs" style="margin-left: 10px;">
		${__('Last Selling Rate')}
	</button>`);

	last_selling_rate_btn.on('click', function () {
		let default_item_code = sf_trading.get_default_item_for_last_selling_rate(frm);
		sf_trading.open_last_selling_rate_dialog(frm, default_item_code);
	});

	// Insert after target button, or append if no target
	if ($target.length > 0 && $target.parent().is($toolbar)) {
		last_selling_rate_btn.insertAfter($target);
	} else {
		$toolbar.append(last_selling_rate_btn);
	}
};

sf_trading.add_customer_last_selling_rate_button = function(frm) {
	if (!frm.fields_dict.items) return;
	if (!frm.fields_dict.items.grid) return;

	const grid = frm.fields_dict.items.grid;

	// Try multiple ways to find the toolbar
	let $toolbar = grid.wrapper.find(".grid-buttons");

	if (!$toolbar.length) {
		$toolbar = grid.wrapper.find(".grid-footer .grid-buttons");
	}

	if (!$toolbar.length) {
		const $footer = grid.wrapper.find(".grid-footer");
		if ($footer.length) {
			$toolbar = $footer.find(".grid-buttons");
		}
	}

	if (!$toolbar.length) {
		const $addRowBtn = grid.wrapper.find("button:contains('Add Row')");
		if ($addRowBtn.length) {
			$toolbar = $addRowBtn.closest(".grid-buttons");
		}
	}

	if (!$toolbar.length) return;

	// Check if button already exists
	if ($toolbar.find("button:contains('Customer Last Selling Rate')").length > 0) {
		return;
	}

	// Position right after the plain "Last Selling Rate" button when present
	let $target = $toolbar.find("button").filter(function () {
		return $(this).text().trim() === __('Last Selling Rate');
	}).last();

	if ($target.length === 0) {
		$target = $toolbar.find("button:contains('Price Assist')").last();
	}

	if ($target.length === 0) {
		$target = $toolbar.find("button:contains('Add Multiple')").last();
	}

	if ($target.length === 0) {
		$target = $toolbar.find("button:contains('Add Row')").last();
	}

	if ($target.length === 0) {
		$target = $toolbar.children().first();
	}

	// Create the button
	let customer_last_selling_rate_btn = $(`<button type="button" class="btn btn-secondary btn-xs" style="margin-left: 10px;">
		${__('Customer Last Selling Rate')}
	</button>`);

	customer_last_selling_rate_btn.on('click', function () {
		let default_item_code = sf_trading.get_default_item_for_last_selling_rate(frm);
		sf_trading.open_customer_last_selling_rate_dialog(frm, default_item_code);
	});

	// Insert after target button, or append if no target
	if ($target.length > 0 && $target.parent().is($toolbar)) {
		customer_last_selling_rate_btn.insertAfter($target);
	} else {
		$toolbar.append(customer_last_selling_rate_btn);
	}
};

// Get default item: from the currently open/expanded row in items grid, or from the last row
sf_trading.get_default_item_for_last_selling_rate = function(frm) {
	if (!frm || !frm.fields_dict.items || !frm.fields_dict.items.grid) {
		return null;
	}
	const items_grid = frm.fields_dict.items.grid;

	// 1. Prefer the row that is currently open/expanded (last clicked row that opened the form)
	const open_row = frappe.ui.form.get_open_grid_form();
	if (open_row && open_row.grid === items_grid && open_row.doc && open_row.doc.item_code) {
		return open_row.doc.item_code;
	}

	// 2. Else the row that last had focus (covers: add row, select item, then click button)
	if (frm._last_selling_rate_focused_item_code) {
		return frm._last_selling_rate_focused_item_code;
	}

	// 3. Else the last clicked row in the items grid
	if (frm._last_selling_rate_clicked_item_code) {
		return frm._last_selling_rate_clicked_item_code;
	}

	// 4. Fallback: use the last row's item in the items table
	if (frm.doc.items && frm.doc.items.length) {
		const last_row = frm.doc.items[frm.doc.items.length - 1];
		if (last_row && last_row.item_code) {
			return last_row.item_code;
		}
	}

	return null;
};

sf_trading.open_last_selling_rate_dialog = function(frm, default_item_code) {
	let company = frm.doc.company || frappe.defaults.get_default("company");
	let cost_center = frm.doc.cost_center || null;

	// Create dialog
	let d = new frappe.ui.Dialog({
		title: __('Last Selling Rate'),
		fields: [
			{ 
				fieldname: 'item_code', 
				label: __('Item Code'), 
				fieldtype: 'Link', 
				options: 'Item', 
				default: default_item_code,
				get_query: function() {
					return {
						query: "erpnext.controllers.queries.item_query",
						filters: { "is_sales_item": 1, "company": company }
					};
				}
			},
			{ fieldname: 'results', fieldtype: 'HTML' }
		],
		size: 'extra-large',
		primary_action_label: __('Close'),
		primary_action: function () {
			d.hide();
		}
	});

	d._cost_center = cost_center;
	d.show();

	setTimeout(() => {
		// Bind onchange for the Link field
		if (d.fields_dict.item_code) {
			d.fields_dict.item_code.df.onchange = function () {
				const item_code = d.get_value('item_code');
				if (item_code) {
					sf_trading.fetch_last_selling_rate(item_code, company, d);
				}
			};
			d.fields_dict.item_code.refresh();
		}

		// Auto-fetch if dialog opened with default item
		if (default_item_code) {
			sf_trading.fetch_last_selling_rate(default_item_code, company, d);
		}
	}, 200);
};

sf_trading.open_customer_last_selling_rate_dialog = function(frm, default_item_code) {
	let company = frm.doc.company || frappe.defaults.get_default("company");
	let cost_center = frm.doc.cost_center || null;
	let customer = frm.doc.customer || null;

	// Create dialog
	let d = new frappe.ui.Dialog({
		title: __('Customer Last Selling Rate'),
		fields: [
			{
				fieldname: 'item_code',
				label: __('Item Code'),
				fieldtype: 'Link',
				options: 'Item',
				default: default_item_code,
				get_query: function() {
					return {
						query: "erpnext.controllers.queries.item_query",
						filters: { "is_sales_item": 1, "company": company }
					};
				}
			},
			{ fieldname: 'results', fieldtype: 'HTML' }
		],
		size: 'extra-large',
		primary_action_label: __('Close'),
		primary_action: function () {
			d.hide();
		}
	});

	d._cost_center = cost_center;
	d._customer = customer;
	d.show();

	setTimeout(() => {
		// Bind onchange for the Link field
		if (d.fields_dict.item_code) {
			d.fields_dict.item_code.df.onchange = function () {
				const item_code = d.get_value('item_code');
				if (item_code) {
					sf_trading.fetch_customer_last_selling_rate(item_code, company, d);
				}
			};
			d.fields_dict.item_code.refresh();
		}

		// Auto-fetch if dialog opened with default item
		if (default_item_code) {
			sf_trading.fetch_customer_last_selling_rate(default_item_code, company, d);
		}
	}, 200);
};

sf_trading.fetch_last_selling_rate = function(item_code, company, dialog) {
	sf_trading._fetch_selling_history(item_code, company, dialog, {});
};

sf_trading.fetch_customer_last_selling_rate = function(item_code, company, dialog) {
	if (!dialog._customer) {
		dialog.fields_dict.results.$wrapper.html(
			'<div class="text-muted">' + __('Please select a Customer on the document first.') + '</div>'
		);
		return;
	}
	sf_trading._fetch_selling_history(item_code, company, dialog, { customer: dialog._customer });
};

sf_trading._fetch_selling_history = function(item_code, company, dialog, extra_args) {
	if (!dialog._cost_center) {
		dialog.fields_dict.results.$wrapper.html(
			'<div class="text-muted">' + __('Please select a Cost Center on the document first.') + '</div>'
		);
		return;
	}
	dialog.fields_dict.results.$wrapper.html('<div class="text-muted">' + __('Loading…') + '</div>');

	frappe.call({
		method: 'vansale.sf_trading.api.last_selling_rate.get_item_selling_history',
		args: Object.assign({ item_code: item_code, cost_center: dialog._cost_center, limit: 20 }, extra_args || {}),
		callback: function (r) {
			const rows = r.message || [];
			if (!rows.length) {
				dialog.fields_dict.results.$wrapper.html('<div class="text-muted">' + __('No selling history found.') + '</div>');
				return;
			}

			dialog.fields_dict.results.$wrapper.html(sf_trading.render_selling_history_table(rows));

			// Enable invoice links
			dialog.fields_dict.results.$wrapper.find('[data-doctype][data-name]').on('click', function () {
				frappe.set_route('Form', this.getAttribute('data-doctype'), this.getAttribute('data-name'));
			});

			// Setup table filters
			setTimeout(() => {
				sf_trading.setupTableFilters(dialog);
			}, 100);
		},
		error: function (err) {
			dialog.fields_dict.results.$wrapper.html('<div class="text-danger">' + __('Error fetching data: {0}', [err.message || err]) + '</div>');
		}
	});
};

sf_trading.render_selling_history_table = function(rows) {
	var out = [
		'<div class="mt-3">',
		'<table class="table table-bordered table-sm" id="selling-history-table">',
		'<thead>',
		'<tr>',
		'<th>' + __('Date') + '</th>',
		'<th>' + __('Sales Invoice') + '</th>',
		'<th>' + __('Customer') + '</th>',
		'<th>' + __('Item Code') + '</th>',
		'<th>' + __('Item Name') + '</th>',
		'<th class="text-right">' + __('Qty') + '</th>',
		'<th class="text-right">' + __('UOM') + '</th>',
		'<th class="text-right">' + __('Selling Rate') + '</th>',
		'<th class="text-right">' + __('Amount') + '</th>',
		'</tr>',
		'<tr class="filter-row">',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Date') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Invoice') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Customer') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Item Code') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Item Name') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Qty') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter UOM') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Rate') + '"></th>',
		'<th><input type="text" class="form-control input-sm" placeholder="' + __('Filter Amount') + '"></th>',
		'</tr>',
		'</thead>',
		'<tbody>'
	].join('');

	rows.forEach(function (r) {
		var posting_date = frappe.utils.escape_html(frappe.datetime.str_to_user(r.posting_date || ''));
		var sales_invoice = frappe.utils.escape_html(r.sales_invoice || '');
		// Always use customer_name (display name), fallback to customer ID only if name is not available
		var customer = frappe.utils.escape_html(r.customer_name || r.customer || '');
		var item_code = frappe.utils.escape_html(r.item_code || '');
		var item_name = frappe.utils.escape_html(r.item_name || '');
		var qty = format_number(r.qty || 0, null, {precision: 2});
		var uom = frappe.utils.escape_html(r.uom || '');
		var selling_rate = format_currency(r.selling_rate || 0, r.currency || '');
		var amount = format_currency(r.selling_amount || 0, r.currency || '');
		
		out += [
			'<tr>',
			`<td>${posting_date}</td>`,
			`<td><a href="#" data-doctype="Sales Invoice" data-name="${sales_invoice}" class="text-primary">${sales_invoice}</a></td>`,
			`<td>${customer}</td>`,
			`<td>${item_code}</td>`,
			`<td>${item_name}</td>`,
			`<td class="text-right">${qty}</td>`,
			`<td class="text-right">${uom}</td>`,
			`<td class="text-right"><strong>${selling_rate}</strong></td>`,
			`<td class="text-right">${amount}</td>`,
			'</tr>'
		].join('');
	});

	out += '</tbody></table></div>';
	return out;
};

sf_trading.setupTableFilters = function(dialog) {
	const table = dialog.fields_dict.results.$wrapper.find('#selling-history-table')[0];
	if (!table) return;

	const filterInputs = table.querySelectorAll('.filter-row input');
	const tbody = table.querySelector('tbody');
	if (!tbody || !filterInputs.length) return;

	// Remove old handlers
	filterInputs.forEach(input => {
		if (input._filterHandler) {
			input.removeEventListener('input', input._filterHandler);
			delete input._filterHandler;
		}
	});

	// Attach new handlers
	filterInputs.forEach((input, index) => {
		input._filterHandler = function () {
			sf_trading.applyAllFilters(dialog);
		};
		input.addEventListener('input', input._filterHandler);
	});
};

sf_trading.applyAllFilters = function(dialog) {
	const table = dialog.fields_dict.results.$wrapper.find('#selling-history-table')[0];
	if (!table) return;

	const rows = table.querySelectorAll('tbody tr');
	const filterInputs = table.querySelectorAll('.filter-row input');

	rows.forEach(row => {
		let shouldShow = true;

		filterInputs.forEach((input, j) => {
			const val = input.value.toLowerCase().trim();
			if (!val) return;

			const cell = row.cells[j];
			if (cell) {
				const cellText = (cell.textContent || '').toLowerCase();
				if (cellText.indexOf(val) === -1) {
					shouldShow = false;
				}
			}
		});

		row.style.display = shouldShow ? '' : 'none';
	});
};

// Hook into common doctypes with item tables
let selling_rate_doctypes = [
	"Sales Order", "Sales Invoice", "Quotation", "Delivery Note"
];

selling_rate_doctypes.forEach(function(doctype) {
	frappe.ui.form.on(doctype, {
		refresh: function(frm) {
			// Try multiple times with increasing delays to ensure grid is ready
			let attempts = 0;
			let maxAttempts = 8;
			
			let tryAddButton = function() {
				attempts++;
				if (frm.fields_dict.items && frm.fields_dict.items.grid) {
					sf_trading.add_last_selling_rate_button(frm);
					sf_trading.add_customer_last_selling_rate_button(frm);
					// If both buttons were added successfully, stop trying
					const grid = frm.fields_dict.items.grid;
					const $toolbar = grid.wrapper.find(".grid-buttons");
					if ($toolbar.find("button:contains('Customer Last Selling Rate')").length > 0) return;
				}

				if (attempts < maxAttempts) {
					setTimeout(tryAddButton, 400);
				}
			};

			// Start trying after initial delay
			setTimeout(tryAddButton, 800);
		},

		items_add: function(frm, cdt, cdn) {
			setTimeout(function () {
				sf_trading.add_last_selling_rate_button(frm);
				sf_trading.add_customer_last_selling_rate_button(frm);
			}, 800);
		}
	});
});

// Also hook into item_code onchange to show quick last selling rate (optional)
// Note: This section is optional and can be removed if not needed
let selling_rate_item_doctypes = [
	"Sales Order Item", "Sales Invoice Item", "Quotation Item", "Delivery Note Item"
];

selling_rate_item_doctypes.forEach(function(child_doctype) {
	frappe.ui.form.on(child_doctype, {
		item_code: function(frm, cdt, cdn) {
			let item_row = locals[cdt][cdn];
			
			// Show quick info in console or as a tooltip (optional)
			if (item_row.item_code && frm.doc.company) {
				// You can add quick display here if needed
			}
		}
	});
});
