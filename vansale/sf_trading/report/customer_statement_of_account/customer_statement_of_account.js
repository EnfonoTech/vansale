// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

// The soa_* filters are hidden: they carry the customer block and the
// letterhead artwork that the print template prints above the ledger. They are
// filled from the server whenever the customer or company changes.
const HEADER_FILTERS = [
	"soa_customer_name",
	"soa_customer_name_ar",
	"soa_customer_id",
	"soa_address",
	"soa_vat_no",
	"soa_cr_no",
	"soa_payment_terms",
	"soa_credit_limit",
	"soa_collector",
	"soa_company_name",
	"soa_header_image",
	"soa_footer_image",
];

function load_statement_header() {
	const company = frappe.query_report.get_filter_value("company");
	const customer = frappe.query_report.get_filter_value("customer");

	if (!company || !customer) {
		return;
	}

	frappe.call({
		method: "vansale.sf_trading.api.statement_of_account.get_statement_header",
		args: { customer: customer, company: company },
		callback: function (r) {
			if (!r.message) {
				return;
			}

			// Object form sets every value and refreshes the report once.
			frappe.query_report.set_filter_value(r.message);
		},
	});
}

function hidden_filter(fieldname) {
	return {
		fieldname: fieldname,
		label: __(fieldname),
		fieldtype: "Data",
		hidden: 1,
	};
}

frappe.query_reports["Customer Statement of Account"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
			on_change: load_statement_header,
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
			reqd: 1,
			on_change: load_statement_header,
		},
		{
			fieldname: "from_date",
			label: __("Period From"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.year_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Period"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "account",
			label: __("Receivable Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: function () {
				return {
					filters: {
						company: frappe.query_report.get_filter_value("company"),
						account_type: "Receivable",
						is_group: 0,
					},
				};
			},
		},
		{
			fieldname: "ageing_based_on",
			label: __("Ageing Based On"),
			fieldtype: "Select",
			options: ["Due Date", "Posting Date"],
			default: "Due Date",
		},
		{
			fieldname: "finance_book",
			label: __("Finance Book"),
			fieldtype: "Link",
			options: "Finance Book",
		},
		{
			fieldname: "ignore_exchange_rate_revaluation_journals",
			label: __("Ignore Exchange Rate Revaluation Journals"),
			fieldtype: "Check",
			default: 0,
		},
		{ fieldname: "range1", label: __("Ageing Range 1"), fieldtype: "Int", default: 30 },
		{ fieldname: "range2", label: __("Ageing Range 2"), fieldtype: "Int", default: 60 },
		{ fieldname: "range3", label: __("Ageing Range 3"), fieldtype: "Int", default: 90 },
		{ fieldname: "range4", label: __("Ageing Range 4"), fieldtype: "Int", default: 120 },
		{ fieldname: "range5", label: __("Ageing Range 5"), fieldtype: "Int", default: 180 },
		{ fieldname: "range6", label: __("Ageing Range 6"), fieldtype: "Int", default: 360 },
		...HEADER_FILTERS.map(hidden_filter),
	],

	onload: function () {
		load_statement_header();
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (data && (data.row_type === "opening" || data.row_type === "total")) {
			value = "<b>" + value + "</b>";
		}

		return value;
	},
};
