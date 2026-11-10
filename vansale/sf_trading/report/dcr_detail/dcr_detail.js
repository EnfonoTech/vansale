// Copyright (c) 2025, sf_trading and contributors
// For license information, please see license.txt

function sf_dcr_detail_default_cost_center() {
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

frappe.query_reports["DCR Detail"] = {
	filters: [
		{
			fieldname: "report_type",
			label: __("Type"),
			fieldtype: "Select",
			options: [
				"Opening Cash Balance",
				"Total Sales",
				"Cash Sales",
				"Bank Sales",
				"Cheque Sales",
				"Credit Sales",
				"Home Credit (Delivery)",
				"Sales Return - Cash",
				"Sales Return - Bank",
				"Sales Return - Cheque",
				"Sales Return - Credit",
				"VAT Collected on Cash Sales",
				"VAT Collected on Bank Sales",
				"VAT Collected on Cheque Sales",
				"VAT Applied on Credit Sales",
				"VAT Applied on Home Credit",
				"VAT Refund on Sales Return",
				"Loyalty / Write Off",
				"Credit Purchase - DIRECT PURCHASE",
				"Cash Received : Credit Sales",
				"Payments-Petty Cash (Approved)",
				"Payments-Petty Cash (UnApproved)",
				"Payments-Petty Cash (Total Payments)",
				"Total Receipt-Petty Cash",
				"Net Cash Movement",
				"Closing Cash Balance",
				"Cash Receipts (Cash Sales)",
				"Bank Sales Receipts",
				"Bank Sales Payments",
				"Internal Transfer (Cash Out)",
				"Internal Transfer (Cash In)",
			],
			default: "Cash Sales",
			reqd: 1,
		},
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
			default: sf_dcr_detail_default_cost_center(),
			get_query: function () {
				const company = frappe.query_report.get_filter_value("company");
				return { filters: company ? { company: company } : {} };
			},
		},
	],
};
