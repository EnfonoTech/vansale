// Override item_code autocomplete on all major transaction doctypes so every
// item dropdown shows stock, rate, and is filtered by the form's company.
//
// ERPNext registers erpnext.controllers.queries.item_query via setup_queries()
// in its controller lifecycle. We patch in multiple lifecycle events AND set
// df.get_query directly to reliably win that race in both dev and production.

(function () {
	const CUSTOM_QUERY = "vansale.sf_trading.api.item_search.search_items_with_stock_and_rate";

	const SELLING_DOCTYPES = [
		"Sales Invoice", "Sales Order", "Quotation", "Delivery Note",
	];
	const BUYING_DOCTYPES = [
		"Purchase Invoice", "Purchase Order", "Purchase Receipt",
	];

	function build_filters(frm) {
		const is_buying = BUYING_DOCTYPES.indexOf(frm.doctype) !== -1;
		const filters = {
			has_variants: 0,
			disabled: 0,
			company: frm.doc.company || frappe.defaults.get_default("company"),
		};
		if (is_buying) {
			filters.is_purchase_item = 1;
			if (frm.doc.buying_price_list) {
				filters.price_list = frm.doc.buying_price_list;
			}
		} else {
			filters.is_sales_item = 1;
			if (frm.doc.selling_price_list) {
				filters.price_list = frm.doc.selling_price_list;
			}
			if (frm.doc.customer) {
				filters.customer = frm.doc.customer;
			}
		}
		return filters;
	}

	function apply_override(frm) {
		if (!frm || !frm.fields_dict || !frm.fields_dict.items) return;
		const grid = frm.fields_dict.items.grid;
		if (!grid) return;

		frm.set_query("item_code", "items", function () {
			return { query: CUSTOM_QUERY, filters: build_filters(frm) };
		});

		// Direct df.get_query patch — wins regardless of who registered last.
		const field = grid.get_field && grid.get_field("item_code");
		if (field && field.df) {
			field.df.get_query = function () {
				return { query: CUSTOM_QUERY, filters: build_filters(frm) };
			};
		}
	}

	function register(doctype, extra_triggers) {
		const handlers = {
			setup:   function (frm) { apply_override(frm); },
			onload:  function (frm) { apply_override(frm); },
			refresh: function (frm) { apply_override(frm); },
			company: function (frm) { apply_override(frm); },
		};
		(extra_triggers || []).forEach(function (f) {
			handlers[f] = function (frm) { apply_override(frm); };
		});
		frappe.ui.form.on(doctype, handlers);
	}

	SELLING_DOCTYPES.forEach(function (dt) {
		register(dt, ["customer", "selling_price_list"]);
	});
	BUYING_DOCTYPES.forEach(function (dt) {
		register(dt, ["supplier", "buying_price_list"]);
	});
})();
