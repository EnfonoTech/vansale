// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Invoices Pending Delivery"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "as_on",
			label: __("As On Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		// Optional posting-date window for the invoices themselves. Left empty it
		// reports every invoice. As On Date still governs how much delivery and
		// how many returns are counted against whatever falls inside the window.
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "party",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => {
				return { filters: { company: frappe.query_report.get_filter_value("company") } };
			},
		},
		{
			fieldname: "cost_center",
			label: __("Branch (Cost Center)"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: () => {
				return { filters: { company: frappe.query_report.get_filter_value("company") } };
			},
		},
		{
			fieldname: "range",
			label: __("Ageing Range"),
			fieldtype: "Data",
			default: "30, 60, 90",
		},
		{
			fieldname: "overdue_after",
			label: __("Highlight Older Than (Days)"),
			fieldtype: "Int",
			default: 0,
		},
	],

	// Puts a tick box on every row so an invoice can be picked and turned into a
	// Delivery Note without leaving the report.
	get_datatable_options: function (options) {
		return Object.assign({}, options, { checkboxColumn: true });
	},

	onload: function (report) {
		report.page.add_inner_button(__("Create Delivery Note"), function () {
			// the total row comes back as a plain array, so it has no `document`
			const picked = (frappe.query_report.get_checked_items() || []).filter(
				(row) => row && row.document
			);

			if (!picked.length) {
				frappe.msgprint({
					title: __("Nothing Selected"),
					indicator: "orange",
					message: __("Tick the invoice you want to deliver, then press the button again."),
				});
				return;
			}

			if (picked.length > 1) {
				frappe.msgprint({
					title: __("One Invoice at a Time"),
					indicator: "orange",
					message: __(
						"A Delivery Note is mapped from a single Sales Invoice, so please tick one row. Deliver them one after another, or raise the Delivery Note first and pull several invoices into it from the Delivery Note itself."
					),
				});
				return;
			}

			// The same mapper the Create > Delivery Note button on the invoice uses,
			// so the quantities it carries over are decided by ERPNext, not by us.
			frappe.model.open_mapped_doc({
				method: "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_delivery_note",
				source_name: picked[0].document,
				freeze_message: __("Creating Delivery Note..."),
			});
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		const threshold = frappe.query_report.get_filter_value("overdue_after");
		if (
			threshold > 0 &&
			data &&
			data.age > threshold &&
			["age", "bucket", "pending_qty", "pending_amount"].includes(column.fieldname)
		) {
			value = `<span style="color: var(--red-600); font-weight: 600">${value}</span>`;
		}
		return value;
	},
};
