// apps/vansale/vansale/sf_trading/report/cash_flow_detail/cash_flow_detail.js
//
// Opened by clicking a period on Cash Flow Money In vs Money Out, which passes its dates,
// direction and any account or mode filter through the URL. Also runs on its own.

frappe.query_reports["Cash Flow Detail"] = {
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
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: [
				"Transactions",
				"By Party",
				"By Voucher Type",
				"By Account",
				"By Mode of Payment",
			].join("\n"),
			default: "Transactions",
		},
		{
			fieldname: "direction",
			label: __("Direction"),
			fieldtype: "Select",
			options: ["", "Money In", "Money Out"].join("\n"),
		},
		{
			fieldname: "account",
			label: __("Cash / Bank Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: function () {
				return {
					filters: {
						company: frappe.query_report.get_filter_value("company"),
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
		if (column.fieldname === "net" && data) {
			const n = flt(data.net);
			if (n) value = `<span style="color:${n < 0 ? "#c62828" : "#2e7d32"}">${value}</span>`;
		}
		if (column.fieldname === "running" && data && flt(data.running) < 0) {
			value = `<span style="color:#c62828;font-weight:600">${value}</span>`;
		}
		return value;
	},
};
