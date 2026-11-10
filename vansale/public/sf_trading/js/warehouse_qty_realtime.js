// Real-time warehouse qty validation for Sales Invoice.
// Fires on qty or warehouse change and warns immediately if the entered qty
// exceeds the available stock in the selected warehouse.
// The comparison uses stock UOM (row.qty * conversion_factor vs bin.actual_qty).

(function () {
	function check_warehouse_qty(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (!row || !row.item_code || !row.warehouse || !(flt(row.qty) > 0)) return;

		frappe.call({
			method: "vansale.sf_trading.api.warehouse_stock.get_available_qty",
			args: { item_code: row.item_code, warehouse: row.warehouse },
			callback: function (r) {
				var available = flt(r.message);
				var qty_in_stock_uom = flt(row.qty) * flt(row.conversion_factor || 1);
				if (qty_in_stock_uom > available) {
					var available_in_row_uom = flt(row.conversion_factor || 1) > 0
						? available / flt(row.conversion_factor)
						: available;
					frappe.msgprint({
						title: __("Insufficient Stock"),
						indicator: "orange",
						message: __("Available qty for {0} in {1} is {2} {3}", [
							row.item_code,
							row.warehouse,
							format_number(available_in_row_uom, null, 3),
							row.uom || "",
						]),
					});
				}
			},
		});
	}

	frappe.ui.form.on("Sales Invoice Item", {
		qty: check_warehouse_qty,
		warehouse: check_warehouse_qty,
		// On item add, warehouse is set asynchronously after item details load.
		// Delay so the warehouse default is available when the check runs.
		item_code: function (frm, cdt, cdn) {
			setTimeout(function () { check_warehouse_qty(frm, cdt, cdn); }, 1000);
		},
	});
})();
