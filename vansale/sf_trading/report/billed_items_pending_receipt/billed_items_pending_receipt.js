// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Billed Items Pending Receipt"] = {
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
		// Optional posting-date window for the source documents. Left empty it
		// reports every document, which is what the workspace number cards do, so
		// their totals do not move because these exist. As On Date still governs
		// how much billing is counted against whatever falls inside the window.
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
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
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
