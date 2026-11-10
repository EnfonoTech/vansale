// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

window.sfOpenItemsDrill = function (report, party) {
	frappe.route_options = {
		company: frappe.query_report.get_filter_value("company"),
		as_on: frappe.query_report.get_filter_value("as_on"),
		range: frappe.query_report.get_filter_value("range"),
		party: decodeURIComponent(party),
	};
	frappe.set_route("query-report", decodeURIComponent(report));
};

frappe.query_reports["Supplier Open Items Summary"] = {
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
			fieldname: "party_group",
			label: __("Supplier Group"),
			fieldtype: "Link",
			options: "Supplier Group",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
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
		if (data && column.drill_report && flt(data[column.fieldname])) {
			const report = encodeURIComponent(column.drill_report);
			const party = encodeURIComponent(data.party);
			value = `<a href="#" onclick="sfOpenItemsDrill('${report}','${party}'); return false;">${value}</a>`;
		}
		const threshold = frappe.query_report.get_filter_value("overdue_after");
		if (
			threshold > 0 &&
			data &&
			data.oldest > threshold &&
			["oldest", "total_value"].includes(column.fieldname)
		) {
			value = `<span style="color: var(--red-600); font-weight: 600">${value}</span>`;
		}
		return value;
	},
};
