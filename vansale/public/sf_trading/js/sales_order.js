// sf_trading — Sales Order: Receive Payment
// Mirrors the Sales Invoice "Receive Payment" popup (public/js/sales_invoice.js),
// creating advance Payment Entries against the order. Sales Order has no
// custom_payment_mode field, so Cash/Bank and Cheque modes are offered together
// in one dialog instead of two separate popups.

frappe.provide("sf_trading");

function sf_trading_so_get_currency_precision(currency_code) {
	var doc = frappe.model.get_doc(":Currency", currency_code);
	if (doc && doc.number_format) return get_number_format_info(doc.number_format).precision;
	return cint(frappe.boot.sysdefaults.currency_precision) || 2;
}

frappe.ui.form.on("Sales Order", {
	refresh: function (frm) {
		if (frm.doc.docstatus !== 1) return;
		var outstanding = flt(frm.doc.grand_total) - flt(frm.doc.advance_paid);
		if (outstanding > 0.0001 && flt(frm.doc.per_billed || 0, 2) < 100) {
			frm.add_custom_button(__("Receive Payment"), function () {
				sf_trading_so_show_receive_payment_popup(frm);
			}).addClass("btn-primary");
		}
	},
});

function sf_trading_so_show_receive_payment_popup(frm) {
	if (frappe.flags.sf_trading_so_popup_showing || !frm || !frm.doc) return;
	frappe.flags.sf_trading_so_popup_showing = true;

	const currency = frm.doc.currency || "";
	const precision = sf_trading_so_get_currency_precision(currency);
	const order_total = flt(Math.abs(flt(frm.doc.grand_total) - flt(frm.doc.advance_paid)), precision);

	if (order_total <= 0) {
		frappe.flags.sf_trading_so_popup_showing = false;
		frappe.msgprint(__("Nothing outstanding to receive on this order."));
		return;
	}

	const base_args = { company: frm.doc.company, is_return: 0, branch: frm.doc.branch || "" };

	frappe.call({
		method: "vansale.sf_trading.api.sales_invoice_payment.get_payment_modes_with_account",
		args: Object.assign({}, base_args, { is_pdc: 0 }),
		callback: function (r1) {
			const cash_modes = r1.message || [];
			frappe.call({
				method: "vansale.sf_trading.api.sales_invoice_payment.get_payment_modes_with_account",
				args: Object.assign({}, base_args, { is_pdc: 1 }),
				callback: function (r2) {
					const cheque_modes = r2.message || [];
					if (!cash_modes.length && !cheque_modes.length) {
						frappe.flags.sf_trading_so_popup_showing = false;
						frappe.msgprint(__("No payment modes configured for this branch."));
						return;
					}
					sf_trading_so_render_dialog(frm, currency, precision, order_total, cash_modes, cheque_modes);
				},
				error: function () { frappe.flags.sf_trading_so_popup_showing = false; frappe.msgprint(__("Error loading Cheque payment modes. Please try again.")); },
			});
		},
		error: function () { frappe.flags.sf_trading_so_popup_showing = false; frappe.msgprint(__("Error loading payment modes. Please try again.")); },
	});
}

function sf_trading_so_render_dialog(frm, currency, precision, order_total, cash_modes, cheque_modes) {
	let wo_config = null;
	frappe.db.get_value("Company", frm.doc.company, ["write_off_account", "custom_max_payment_write_off"])
		.then(function (r) { wo_config = (r && r.message) || {}; });

	const all_fns = [
		...cash_modes.map(function (_, i) { return "csh_" + i; }),
		...cheque_modes.map(function (_, i) { return "chq_" + i; }),
	];

	const fields = [
		{ fieldname: "order_total", fieldtype: "Currency", label: __("Amount to Pay"), default: order_total, read_only: 1, options: "currency", precision },
	];

	// Only label the groups when both types are on offer — otherwise this
	// should look exactly like the plain Sales Invoice payment popup.
	const show_group_headers = cash_modes.length > 0 && cheque_modes.length > 0;

	if (cash_modes.length) {
		if (show_group_headers) fields.push({ fieldtype: "Section Break", label: __("Cash / Bank") });
		cash_modes.forEach(function (mode, idx) {
			fields.push(
				{ fieldtype: "Section Break", fieldname: "csh_row_" + idx, label: "", hide_border: 1 },
				{ fieldname: "csh_" + idx, fieldtype: "Currency", label: mode, default: idx === 0 ? order_total : 0, options: "currency", precision },
				{ fieldtype: "Column Break" },
				{ fieldtype: "Button", fieldname: "fill_csh_" + idx, label: mode, click: (function (fi) { return function () { all_fns.forEach(function (fn) { d.set_value(fn, 0); }); d.set_value(fi, order_total); if (d.fields_dict.write_off) d.set_value("write_off", 0); }; })("csh_" + idx) }
			);
		});
	}

	if (cheque_modes.length) {
		const cheque_header = show_group_headers ? [{ fieldtype: "Section Break", label: __("Cheque") }] : [{ fieldtype: "Section Break", label: "" }];
		fields.push(
			...cheque_header,
			{ fieldname: "cheque_date", fieldtype: "Date", label: __("Cheque Date"), default: frappe.datetime.get_today() },
			{ fieldname: "cheque_no", fieldtype: "Data", label: __("Cheque No") }
		);
		cheque_modes.forEach(function (mode, idx) {
			fields.push(
				{ fieldtype: "Section Break", fieldname: "chq_row_" + idx, label: "", hide_border: 1 },
				{ fieldname: "chq_" + idx, fieldtype: "Currency", label: mode, default: 0, options: "currency", precision },
				{ fieldtype: "Column Break" },
				{ fieldtype: "Button", fieldname: "fill_chq_" + idx, label: mode, click: (function (fi) { return function () { all_fns.forEach(function (fn) { d.set_value(fn, 0); }); d.set_value(fi, order_total); if (d.fields_dict.write_off) d.set_value("write_off", 0); }; })("chq_" + idx) }
			);
		});
	}

	fields.push(
		{ fieldtype: "Section Break", fieldname: "row_wo", label: "", hide_border: 1 },
		{ fieldname: "write_off", fieldtype: "Currency", label: __("Write Off"), default: 0, options: "currency", precision },
		{ fieldtype: "Column Break", fieldname: "cb_wo" }
	);

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

	function apply_and_close(vals) {
		if (!vals) return;
		let cash_total = 0, cheque_total = 0;
		const cash_payments = [], cheque_payments = [];
		cash_modes.forEach(function (mode, i) { const amt = flt(vals["csh_" + i]) || 0; if (amt > 0) { cash_payments.push({ mode_of_payment: mode, amount: amt }); cash_total += amt; } });
		cheque_modes.forEach(function (mode, i) { const amt = flt(vals["chq_" + i]) || 0; if (amt > 0) { cheque_payments.push({ mode_of_payment: mode, amount: amt }); cheque_total += amt; } });
		if (!cash_payments.length && !cheque_payments.length) { frappe.msgprint({ title: __("Error"), message: __("Please enter at least one payment amount."), indicator: "red" }); return; }
		if (cheque_payments.length && (!vals.cheque_date || !(vals.cheque_no || "").trim())) {
			frappe.msgprint({ title: __("Error"), message: __("Cheque Date and Cheque No are required for a Cheque payment."), indicator: "red" });
			return;
		}
		const write_off = flt(vals.write_off) || 0;
		if (!validate_write_off(write_off)) return;
		const total_rounded = flt(cash_total + cheque_total + write_off, precision);
		if (total_rounded - order_total > 0.0001) { frappe.msgprint({ title: __("Error"), message: __("Total payment {0} exceeds amount to receive {1}.", [format_currency(total_rounded, currency), format_currency(order_total, currency)]), indicator: "red" }); return; }
		if (order_total - total_rounded > 0.0001) { frappe.msgprint({ title: __("Incomplete"), message: __("{0} still to be allocated.", [format_currency(order_total - total_rounded, currency)]), indicator: "red" }); return; }

		d.hide(); frappe.flags.sf_trading_so_popup_showing = false;

		// Write-off rides on the last call made: cheque call when there's no cash, else the cash call.
		function do_cash(created_count) {
			if (!cash_payments.length) {
				if (created_count) { frappe.show_alert({ message: __("Created {0} Payment Entries for this order", [created_count]), indicator: "green" }, 5); frm.reload_doc(); }
				return;
			}
			frappe.call({
				method: "vansale.sf_trading.api.sales_order_payment.create_pos_payments_for_order",
				args: { sales_order: frm.doc.name, payments: JSON.stringify(cash_payments), write_off_amount: write_off || undefined },
				freeze: true, freeze_message: __("Creating payments..."),
				callback: function (r) {
					const n = (created_count || 0) + ((r && r.message) ? r.message.length : 0);
					if (n) { frappe.show_alert({ message: __("Created {0} Payment Entries for this order", [n]), indicator: "green" }, 5); frm.reload_doc(); }
				},
			});
		}

		if (cheque_payments.length) {
			frappe.call({
				method: "vansale.sf_trading.api.sales_order_payment.create_pos_payments_for_order",
				args: {
					sales_order: frm.doc.name,
					payments: JSON.stringify(cheque_payments),
					cheque_date: vals.cheque_date,
					cheque_no: (vals.cheque_no || "").trim(),
					write_off_amount: cash_payments.length ? undefined : (write_off || undefined),
				},
				freeze: true, freeze_message: __("Creating Cheque payment..."),
				callback: function (r) { do_cash((r && r.message) ? r.message.length : 0); },
			});
		} else {
			do_cash(0);
		}
	}

	const d = new frappe.ui.Dialog({
		title: __("Enter Payment Amounts"),
		fields,
		primary_action_label: __("Receive Payment"),
		primary_action: function (vals) { if (vals) apply_and_close(vals); },
		onhide: function () { frappe.flags.sf_trading_so_popup_showing = false; },
	});
	d.show();

	frappe.utils.sleep(100).then(function () {
		d.$wrapper.find(".section-body").css({ display: "flex", alignItems: "flex-end" });
		const all_fields = all_fns.concat(["write_off"]);
		all_fns.forEach(function (fn) {
			const field = d.fields_dict[fn];
			if (!field || !field.$wrapper) return;
			field.$wrapper.find("input").off("click.sf_so_fill").on("click.sf_so_fill", function () {
				let other = 0;
				all_fields.forEach(function (ofn) { if (ofn !== fn) other += flt(d.get_value(ofn)) || 0; });
				d.set_value(fn, Math.max(0, flt(order_total - other)));
			});
		});
		if (d.fields_dict.write_off && d.fields_dict.write_off.$wrapper) {
			d.fields_dict.write_off.$wrapper.find("input").off("click.sf_so_fill").on("click.sf_so_fill", function () {
				let other = 0;
				all_fns.forEach(function (fn) { other += flt(d.get_value(fn)) || 0; });
				d.set_value("write_off", Math.max(0, flt(order_total - other)));
			});
		}
	});
}
