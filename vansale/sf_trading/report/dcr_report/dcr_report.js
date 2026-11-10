// Copyright (c) 2025, sf_trading and contributors
// For license information, please see license.txt

function sf_dcr_default_cost_center() {
	// User Permission first (marked default, or the only permitted one),
	// then the session default
	const perms = frappe.defaults.get_user_permissions();
	const cc = perms && perms["Cost Center"];
	if (cc && cc.length) {
		const def = cc.find(function (d) { return d.is_default; });
		if (def) return def.doc;
		if (cc.length === 1) return cc[0].doc;
	}
	return frappe.defaults.get_user_default("Cost Center") || "";
}

function sf_dcr_cost_center_query() {
	const company = frappe.query_report.get_filter_value("company");
	return { filters: company ? { company: company } : {} };
}

frappe.query_reports["DCR Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			default: sf_dcr_default_cost_center(),
			get_query: sf_dcr_cost_center_query,
		},
	],
};
