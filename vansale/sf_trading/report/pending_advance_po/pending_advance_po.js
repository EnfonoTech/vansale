// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Pending Advance PO"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		// The advance is always its balance right now -- the advance ledger carries no
		// posting date, so there is nothing to rebuild an "as on" answer from. These
		// two bound the order date instead, so a single period can be checked on its own.
		{
			fieldname: "from_date",
			label: __("PO From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("PO To Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// A remark on a row means the figures on it disagree with something, so it is
		// worth reading before anyone acts on the advance.
		if (column.fieldname === "remarks" && data && data.remarks) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}

		return value;
	},
};
