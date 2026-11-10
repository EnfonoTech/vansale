// apps/vansale/vansale/sf_trading/report/cash_flow_money_in_vs_money_out/cash_flow_money_in_vs_money_out.js

frappe.query_reports["Cash Flow Money In vs Money Out"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -6),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "periodicity",
			label: __("Periodicity"),
			fieldtype: "Select",
			options: ["Daily", "Weekly", "Monthly", "Quarterly", "Yearly"].join("\n"),
			default: "Monthly",
		},
		{
			fieldname: "account",
			label: __("Cash / Bank Account"),
			fieldtype: "Link",
			options: "Account",
			// leave blank for every money account of the company
			get_query: function () {
				const company = frappe.query_report.get_filter_value("company");
				return {
					filters: {
						company: company,
						is_group: 0,
						account_type: ["in", ["Cash", "Bank"]],
					},
				};
			},
		},
		{
			fieldname: "mode_of_payment",
			label: __("Mode of Payment"),
			fieldtype: "Link",
			options: "Mode of Payment",
		},
		{
			fieldname: "exclude_internal_transfers",
			label: __("Exclude internal transfers"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (data && (data.is_total || data.is_opening)) {
			value = `<b>${value}</b>`;
		}
		if (column.fieldname === "money_in" && data && flt(data.money_in)) {
			value = `<span style="color:#2e7d32">${value}</span>`;
		}
		if (column.fieldname === "money_out" && data && flt(data.money_out)) {
			value = `<span style="color:#c62828">${value}</span>`;
		}
		if (column.fieldname === "net" && data && flt(data.net) < 0) {
			value = `<span style="color:#c62828">${value}</span>`;
		}
		// a negative running balance is an overdraft and should be impossible to miss
		if (column.fieldname === "net" && data && flt(data.net) > 0) {
			value = `<span style="color:#2e7d32">${value}</span>`;
		}
		if (column.fieldname === "running" && data && flt(data.running) < 0) {
			value = `<span style="color:#c62828;font-weight:600">${value}</span>`;
		}
		return value;
	},
};
