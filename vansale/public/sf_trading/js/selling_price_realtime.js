// Real-time selling price validation for sf_trading.
// Fires on rate change in any selling item row and warns immediately if the
// entered rate is below the minimum (price list floor OR cost + margin%).
// The hard block still happens at save via the Python validate hook.

(function () {
	var SELLING_ITEM_DOCTYPES = [
		"Sales Invoice Item",
		"Sales Order Item",
		"Quotation Item",
		"Delivery Note Item",
	];

	function check_min_price(frm, cdt, cdn) {
		var row = locals[cdt][cdn];
		if (!row || !row.item_code || !(flt(row.rate) > 0)) return;

		frappe.call({
			method: "vansale.sf_trading.api.selling_price_validation.get_min_selling_price",
			args: {
				item_code: row.item_code,
				warehouse: row.warehouse || "",
				price_list: row.custom_price_list || frm.doc.selling_price_list || "",
				conversion_rate: frm.doc.conversion_rate || 1,
				uom_cf: row.conversion_factor || 1,
				// Item Price is held in the price list's own currency; without this the
				// warning would compare a foreign number against the row rate and label
				// it with the transaction currency.
				plc_conversion_rate: frm.doc.plc_conversion_rate || 1,
			},
			callback: function (r) {
				if (!r.message) return;
				var min_price = flt(r.message.min_price);
				if (!min_price) return;
				if (flt(row.rate) < min_price) {
					frappe.msgprint({
						title: __("Selling Price Warning"),
						indicator: "red",
						message: __("Minimum selling price for {0} is {1}", [
							row.item_code,
							format_currency(min_price, frm.doc.currency),
						]),
					});
				}
			},
		});
	}

	SELLING_ITEM_DOCTYPES.forEach(function (child_dt) {
		frappe.ui.form.on(child_dt, { rate: check_min_price });
	});
})();
