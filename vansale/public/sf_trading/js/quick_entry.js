// Quick Entry feature for sf_trading
// Adds a button to the items grid that opens a dialog listing items with stock,
// allowing the user to select items via checkboxes and add them to the items table.

frappe.provide("sf_trading");

sf_trading.add_quick_entry_button = function (frm) {
	if (!frm.fields_dict.items || !frm.fields_dict.items.grid) return;

	const grid = frm.fields_dict.items.grid;

	let $toolbar = grid.wrapper.find(".grid-buttons");
	if (!$toolbar.length) {
		const $footer = grid.wrapper.find(".grid-footer");
		if ($footer.length) $toolbar = $footer.find(".grid-buttons");
	}
	if (!$toolbar.length) {
		const $addRowBtn = grid.wrapper.find("button:contains('Add Row')");
		if ($addRowBtn.length) $toolbar = $addRowBtn.closest(".grid-buttons");
	}
	if (!$toolbar.length) return;

	if ($toolbar.find("button:contains('Quick Entry')").length > 0) return;

	// Position after Last Selling Rate button if present
	let $target = $toolbar.find("button:contains('Last Selling Rate')").last();
	if ($target.length === 0) $target = $toolbar.find("button:contains('Add Row')").last();

	const btn = $(`<button type="button" class="btn btn-secondary btn-xs" style="margin-left: 10px;">
		${__('Quick Entry')}
	</button>`);

	btn.on('click', function () {
		sf_trading.open_quick_entry_dialog(frm);
	});

	if ($target.length > 0 && $target.parent().is($toolbar)) {
		btn.insertAfter($target);
	} else {
		$toolbar.append(btn);
	}
};

sf_trading.open_quick_entry_dialog = function (frm) {
	const company   = frm.doc.company || frappe.defaults.get_default("company");
	const price_list = frm.doc.selling_price_list || frappe.defaults.get_default("selling_price_list");
	const warehouse  = frm.doc.set_warehouse || "";

	if (!warehouse) {
		frappe.msgprint({
			title: __("Warehouse Required"),
			message: __("Please set a Warehouse on the invoice before using Quick Entry."),
			indicator: "orange",
		});
		return;
	}

	const d = new frappe.ui.Dialog({
		title: __('Quick Entry') + ' — ' + warehouse,
		size: 'extra-large',
		fields: [
			{
				fieldname: 'search',
				label: __('Search'),
				fieldtype: 'Data',
				placeholder: __('Type item code or name to filter…'),
			},
			{ fieldname: 'results', fieldtype: 'HTML' },
		],
		primary_action_label: __('Add Selected'),
		primary_action: function () {
			sf_trading.add_quick_entry_selection(frm, d);
		},
		secondary_action_label: __('Close'),
		secondary_action: function () { d.hide(); },
	});

	d._frm = frm;
	d._company = company;
	d._price_list = price_list;
	d._warehouse = warehouse;

	d.show();

	sf_trading.fetch_quick_entry_items(d);

	// Auto-focus only; event binding happens inside bind_quick_entry_table
	// after the table is actually rendered.
	setTimeout(function () {
		const $input = d.fields_dict.search && d.fields_dict.search.$input;
		if ($input) $input.focus();
	}, 300);
};

sf_trading.filter_quick_entry_table = function (dialog, txt) {
	const term = String(txt || '').trim().toLowerCase();
	const $tbody = dialog.$wrapper.find('#quick-entry-table tbody');

	// Remove any separator rows from a previous filter pass
	$tbody.find('.qe-separator').remove();

	if (!term) {
		$tbody.find('tr').show();
		const total = $tbody.find('tr').length;
		dialog.$wrapper.find('.qe-item-count').text(__('Showing {0} items', [total]));
		return;
	}

	let matchCount = 0, selectedCount = 0;
	const $selected = [], $matched = [];

	$tbody.find('tr').each(function () {
		const $row = $(this);
		const code      = String($row.attr('data-item-code') || '').toLowerCase();
		const name      = String($row.attr('data-item-name') || '').toLowerCase();
		const isChecked = $row.find('.qe-row-check').prop('checked');
		const textMatch = code.includes(term) || name.includes(term);

		if (isChecked && !textMatch) {
			$row.show();
			$selected.push($row);
			selectedCount++;
		} else if (textMatch) {
			$row.show();
			$matched.push($row);
			matchCount++;
		} else {
			$row.hide();
		}
	});

	// Insert separator rows to visually split groups
	const cols = 8; // number of columns in the table
	if (matchCount > 0 && selectedCount > 0) {
		// Search Results first, then Selected Items at the bottom
		const $sepResults = $(`<tr class="qe-separator"><td colspan="${cols}">${__('— Search Results —')}</td></tr>`);
		$tbody.prepend($sepResults);
		// Move matched rows right after the header (maintains their order)
		let $anchor = $sepResults;
		$matched.forEach(function ($r) { $anchor.after($r); $anchor = $r; });
		// Selected items header + rows at the bottom
		const $sepSelected = $(`<tr class="qe-separator"><td colspan="${cols}">${__('— Selected Items —')}</td></tr>`);
		$tbody.append($sepSelected);
		$selected.forEach(function ($r) { $tbody.append($r); });
	} else if (selectedCount > 0 && matchCount === 0) {
		// Nothing matched — show "no results" then the retained selected items
		const $noRes = $(`<tr class="qe-separator"><td colspan="${cols}" style="color:#dc3545;">${__('No items found for "{0}"', [txt])}</td></tr>`);
		const $sep = $(`<tr class="qe-separator"><td colspan="${cols}">${__('— Selected Items —')}</td></tr>`);
		$tbody.prepend($sep);
		$tbody.prepend($noRes);
	}

	const total = $tbody.find('tr[data-item-code]').length;
	dialog.$wrapper.find('.qe-item-count').text(
		__('Showing {0} of {1}', [matchCount + selectedCount, total])
	);
};

sf_trading.fetch_quick_entry_items = function (dialog) {
	const $wrap = dialog.fields_dict.results.$wrapper;
	$wrap.html('<div class="text-muted">' + __('Loading…') + '</div>');

	frappe.call({
		method: 'vansale.sf_trading.api.quick_entry.get_items_with_stock',
		args: {
			company: dialog._company,
			price_list: dialog._price_list,
			warehouse: dialog._warehouse || '',
			limit: 500,
		},
		callback: function (r) {
			const rows = r.message || [];
			if (!rows.length) {
				$wrap.html('<div class="text-muted">' + __('No items with stock found.') + '</div>');
				return;
			}
			$wrap.html(sf_trading.render_quick_entry_table(rows));
			sf_trading.bind_quick_entry_table(dialog);
		},
		error: function (err) {
			$wrap.html('<div class="text-danger">' + __('Error: {0}', [err.message || err]) + '</div>');
		}
	});
};

sf_trading.render_quick_entry_table = function (rows) {
	const th = 'border-top:1px solid #d1d8dd;border-bottom:1px solid #d1d8dd;background:#f8f9fa;padding:6px 8px;white-space:nowrap;';
	let out = [
		'<style>',
		'  .qe-row-qty::-webkit-outer-spin-button,',
		'  .qe-row-qty::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}',
		'  .qe-row-qty{-moz-appearance:textfield;width:70px!important;}',
		'  #quick-entry-table tbody tr{outline:none;}',
		'  #quick-entry-table tbody tr:hover{background:#f0f4ff;cursor:pointer;}',
		'  #quick-entry-table tbody tr.qe-selected{background:#e8f4ff;}',
		'  #quick-entry-table tbody tr.qe-focused{outline:2px solid #5e64ff;outline-offset:-2px;}',
		'  #quick-entry-table tbody tr.qe-no-stock td{color:#aaa;}',
		'  .qe-separator td{background:#f8f9fa;color:#8d99ae;font-size:11px;padding:3px 8px!important;border-top:1px solid #d1d8dd;}',
		'</style>',
		`<div class="text-muted small mb-1 qe-item-count">${__('Showing {0} items', [rows.length])}</div>`,
		'<div style="max-height:420px;overflow-y:auto;border:1px solid #d1d8dd;border-radius:4px;">',
		'<table class="table table-sm mb-0" id="quick-entry-table" style="border-collapse:collapse;">',
		'<thead style="position:sticky;top:0;z-index:1;">',
		'<tr>',
		`<th style="width:36px;${th}"><input type="checkbox" id="qe-check-all" title="${__('Select all')}"></th>`,
		`<th style="${th}">${__('Item Code')}</th>`,
		`<th style="${th}">${__('Item Name')}</th>`,
		`<th style="${th}">${__('Warehouse')}</th>`,
		`<th class="text-right" style="${th}">${__('Stock')}</th>`,
		`<th style="${th}">${__('UOM')}</th>`,
		`<th class="text-right" style="${th}">${__('Rate')}</th>`,
		`<th class="text-right" style="width:80px;${th}">${__('Qty')}</th>`,
		'</tr>',
		'</thead>',
		'<tbody>',
	].join('');

	rows.forEach(function (r, idx) {
		const item_code  = frappe.utils.escape_html(r.item_code  || '');
		const item_name  = frappe.utils.escape_html(r.item_name  || '');
		const warehouse  = frappe.utils.escape_html(r.warehouse  || '');
		const stock_raw  = Number(r.stock_qty    || 0);
		const stock_disp = format_number(stock_raw, null, { precision: 2 });
		const uom        = frappe.utils.escape_html(r.stock_uom  || '');
		const rate_val   = Number(r.selling_rate || 0);
		const rate_disp  = rate_val ? format_currency(rate_val, r.price_currency || '') : '<span class="text-muted">-</span>';
		const no_stock   = stock_raw <= 0 ? ' qe-no-stock' : '';
		const stock_color = stock_raw <= 0 ? '#dc3545' : (stock_raw < 5 ? '#fd7e14' : '#28a745');
		out += [
			`<tr tabindex="0" class="${no_stock}" data-item-code="${item_code}" data-item-name="${item_name}" data-warehouse="${warehouse}" data-rate="${rate_val}" data-stock="${stock_raw}">`,
			`<td style="padding:4px 8px;"><input type="checkbox" class="qe-row-check" data-idx="${idx}"></td>`,
			`<td style="padding:4px 8px;font-weight:500;">${item_code}</td>`,
			`<td style="padding:4px 8px;">${item_name}</td>`,
			`<td style="padding:4px 8px;font-size:12px;">${warehouse}</td>`,
			`<td class="text-right" style="padding:4px 8px;color:${stock_color};font-weight:600;">${stock_disp}</td>`,
			`<td style="padding:4px 8px;">${uom}</td>`,
			`<td class="text-right" style="padding:4px 8px;">${rate_disp}</td>`,
			`<td style="padding:4px 6px;text-align:right;"><input type="number" class="form-control input-sm qe-row-qty" min="0" step="any" value="" data-idx="${idx}"></td>`,
			'</tr>',
		].join('');
	});

	out += '</tbody></table></div>';
	return out;
};

sf_trading.bind_quick_entry_table = function (dialog) {
	const $wrap = dialog.fields_dict.results.$wrapper;
	if (!$wrap.find('#quick-entry-table').length) return;

	const $tbody = $wrap.find('#quick-entry-table tbody');

	function visibleRows() { return $tbody.find('tr:visible').not('.qe-separator'); }
	function nextRow($row) { return $row.nextAll('tr:visible').not('.qe-separator').first(); }
	function prevRow($row) { return $row.prevAll('tr:visible').not('.qe-separator').first(); }
	function focusRow($row) {
		$tbody.find('tr').removeClass('qe-focused');
		$row.addClass('qe-focused').focus();
	}
	function toggleRow($row) {
		const $chk = $row.find('.qe-row-check');
		const now = !$chk.prop('checked');
		$chk.prop('checked', now);
		$row.toggleClass('qe-selected', now);
	}

	// ── Check-all ──────────────────────────────────────────────────────────
	$wrap.find('#qe-check-all').off('change').on('change', function () {
		const checked = this.checked;
		visibleRows().each(function () {
			$(this).find('.qe-row-check').prop('checked', checked);
			$(this).toggleClass('qe-selected', checked);
		});
	});

	// ── Row: click to toggle, focus ring ───────────────────────────────────
	$tbody.off('click.qe').on('click.qe', 'tr', function (e) {
		if ($(e.target).is('input')) return;
		toggleRow($(this));
		focusRow($(this));
	});
	$tbody.off('focus.qe', 'tr').on('focus.qe', 'tr', function () {
		$tbody.find('tr').removeClass('qe-focused');
		$(this).addClass('qe-focused');
	});
	$tbody.off('blur.qe', 'tr').on('blur.qe', 'tr', function () {
		$(this).removeClass('qe-focused');
	});

	// ── Row: keyboard navigation ───────────────────────────────────────────
	// Space  → toggle checkbox
	// Enter  → focus qty field
	// ↓ / ↑ → move to next/prev visible row
	// digit  → pre-fill qty and jump to qty input
	$tbody.off('keydown.qe', 'tr').on('keydown.qe', 'tr', function (e) {
		const $row = $(this);
		if (e.key === ' ') {
			e.preventDefault();
			toggleRow($row);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			$row.find('.qe-row-check').prop('checked', true);
			$row.addClass('qe-selected');
			$row.find('.qe-row-qty').focus().select();
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			const $next = nextRow($row);
			if ($next.length) focusRow($next);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			const $prev = prevRow($row);
			if ($prev.length) {
				focusRow($prev);
			} else {
				// Back to search box when going above first row
				const $inp = dialog.fields_dict.search && dialog.fields_dict.search.$input;
				if ($inp) $inp.focus();
			}
		} else if ((e.key >= '0' && e.key <= '9') || e.key === '.') {
			// Digit/decimal key: jump into qty field only when the row itself is focused,
			// not when the event bubbled up from the qty input already being edited.
			if ($(e.target).is('input')) return;
			e.preventDefault();
			$row.find('.qe-row-check').prop('checked', true);
			$row.addClass('qe-selected');
			const $qty = $row.find('.qe-row-qty');
			$qty.val(e.key).focus();
		}
	});

	// ── Checkbox: sync row highlight ──────────────────────────────────────
	$wrap.find('.qe-row-check').off('change.qe').on('change.qe', function () {
		$(this).closest('tr').toggleClass('qe-selected', this.checked);
	});

	// ── Qty input: select row + warn via alert if over stock ──────────────
	let _qtyWarnTimer = null;
	$wrap.find('.qe-row-qty').off('input.qe').on('input.qe', function () {
		const $row = $(this).closest('tr');
		$row.find('.qe-row-check').prop('checked', true);
		$row.addClass('qe-selected');
		const stock = parseFloat($row.attr('data-stock'));
		const entered = parseFloat(this.value);
		if (!isNaN(entered) && !isNaN(stock) && entered > stock) {
			clearTimeout(_qtyWarnTimer);
			_qtyWarnTimer = setTimeout(function () {
				const item_code = $row.attr('data-item-code') || '';
				frappe.show_alert({
					message: __('Qty {0} exceeds warehouse stock {1} for {2}', [entered, stock, item_code]),
					indicator: 'orange',
				}, 4);
			}, 600);
		}
	});
	$wrap.find('.qe-row-qty').off('keydown.qe').on('keydown.qe', function (e) {
		const $row = $(this).closest('tr');
		if (e.key === 'Enter') {
			e.preventDefault();
			const $nextRow = nextRow($row);
			if ($nextRow.length) {
				focusRow($nextRow);
				$nextRow.find('.qe-row-qty').focus().select();
			} else {
				// Last row → submit
				sf_trading.add_quick_entry_selection(dialog._frm, dialog);
			}
		} else if (e.key === 'Escape') {
			e.preventDefault();
			focusRow($row);
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			const $next = nextRow($row);
			if ($next.length) { focusRow($next); $next.find('.qe-row-qty').focus().select(); }
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			const $prev = prevRow($row);
			if ($prev.length) { focusRow($prev); $prev.find('.qe-row-qty').focus().select(); }
		}
	});

	// ── Ctrl+Enter anywhere in dialog → Add Selected ──────────────────────
	dialog.$wrapper.off('keydown.qe-submit').on('keydown.qe-submit', function (e) {
		if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
			e.preventDefault();
			sf_trading.add_quick_entry_selection(dialog._frm, dialog);
		}
	});

	// ── Search input ──────────────────────────────────────────────────────
	const $input = dialog.fields_dict.search && dialog.fields_dict.search.$input;
	if ($input && !$input.data('qe-search-bound')) {
		$input.data('qe-search-bound', true);
		$input.off('input.qe').on('input.qe', function () {
			sf_trading.filter_quick_entry_table(dialog, this.value);
		});
		// ↓ from search → jump to first visible row
		$input.off('keydown.qe').on('keydown.qe', function (e) {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				const $first = visibleRows().first();
				if ($first.length) focusRow($first);
			}
		});
		$input.focus();
	}
	if ($input && $input.val()) {
		sf_trading.filter_quick_entry_table(dialog, $input.val());
	}
};

sf_trading.add_quick_entry_selection = function (frm, dialog) {
	const $wrap = dialog.fields_dict.results.$wrapper;
	const $checks = $wrap.find('.qe-row-check:checked');

	if (!$checks.length) {
		frappe.show_alert({ message: __('Please select at least one item.'), indicator: 'orange' });
		return;
	}

	// Re-fetch the data we rendered to read item_code, warehouse, rate from current rows
	const rows_to_add = [];
	let invalid_row = null;
	$checks.each(function () {
		const $row = $(this).closest('tr');
		const item_code = $row.attr('data-item-code') || '';
		const warehouse = $row.attr('data-warehouse') || '';
		const rate = parseFloat($row.attr('data-rate')) || 0;
		const stock = parseFloat($row.attr('data-stock')) || 0;
		const qty = parseFloat($row.find('.qe-row-qty').val()) || 0;

		if (qty <= 0) {
			invalid_row = invalid_row || { reason: __('Qty must be greater than 0 for {0}', [item_code]) };
			return;
		}
		if (qty > stock) {
			invalid_row = invalid_row || { reason: __('Qty {0} exceeds warehouse stock {1} for {2}', [qty, stock, item_code]) };
			return;
		}
		rows_to_add.push({ item_code, warehouse, rate, qty });
	});

	if (invalid_row) {
		frappe.show_alert({ message: invalid_row.reason, indicator: 'red' });
		return;
	}
	if (!rows_to_add.length) {
		frappe.show_alert({ message: __('Nothing to add.'), indicator: 'orange' });
		return;
	}

	(async function () {
		for (const row of rows_to_add) {
			const child = frm.add_child('items');
			await frappe.model.set_value(child.doctype, child.name, 'item_code', row.item_code);
			if (row.warehouse) {
				await frappe.model.set_value(child.doctype, child.name, 'warehouse', row.warehouse);
			}
			await frappe.model.set_value(child.doctype, child.name, 'qty', row.qty);
			if (row.rate) {
				await frappe.model.set_value(child.doctype, child.name, 'rate', row.rate);
			}
		}
		frm.refresh_field('items');
		dialog.hide();
		frappe.show_alert({
			message: __('Added {0} item(s)', [rows_to_add.length]),
			indicator: 'green'
		});
	})();
};

// Hook into common doctypes with item tables
const quick_entry_doctypes = ["Sales Order", "Sales Invoice", "Quotation", "Delivery Note"];

quick_entry_doctypes.forEach(function (doctype) {
	frappe.ui.form.on(doctype, {
		refresh: function (frm) {
			let attempts = 0;
			const maxAttempts = 8;
			const tryAddButton = function () {
				attempts++;
				if (frm.fields_dict.items && frm.fields_dict.items.grid) {
					sf_trading.add_quick_entry_button(frm);
					const $toolbar = frm.fields_dict.items.grid.wrapper.find(".grid-buttons");
					if ($toolbar.find("button:contains('Quick Entry')").length > 0) return;
				}
				if (attempts < maxAttempts) setTimeout(tryAddButton, 400);
			};
			setTimeout(tryAddButton, 800);
		},

		items_add: function (frm) {
			setTimeout(function () {
				sf_trading.add_quick_entry_button(frm);
			}, 800);
		}
	});
});
