// apps/vansale/vansale/sf_trading/report/mode_of_payment_invoice_wise/mode_of_payment_invoice_wise.js
frappe.query_reports["Mode of Payment Invoice Wise"] = {
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
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
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
			fieldname: "date_basis",
			label: __("Date Basis"),
			fieldtype: "Select",
			options: ["Invoice Date", "Payment Date"].join("\n"),
			default: "Invoice Date",
		},
		{
			fieldname: "view",
			label: __("View"),
			fieldtype: "Select",
			options: ["Invoice Summary", "Payment Detail", "Mode Summary"].join("\n"),
			default: "Invoice Summary",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "sales_invoice",
			label: __("Sales Invoice"),
			fieldtype: "Link",
			options: "Sales Invoice",
			get_query: function () {
				return { filters: { docstatus: 1, company: frappe.query_report.get_filter_value("company") } };
			},
		},
		{
			fieldname: "mode_of_payment",
			label: __("Mode of Payment"),
			fieldtype: "Link",
			options: "Mode of Payment",
		},
		{
			fieldname: "payment_class",
			label: __("Payment Type"),
			fieldtype: "Select",
			options: [
				"",
				"Cash",
				"Card",
				"BenefitPay",
				"Cheque",
				"Bank Transfer",
				"Other",
				"Adjustment",
				"Settled (no voucher)",
				"Credit",
				"Refund Due",
				"Mixed",
			].join("\n"),
		},
		{
			// the counter's declaration on the invoice (custom_payment_mode)
			fieldname: "invoice_type",
			label: __("Invoice Type"),
			fieldtype: "Select",
			options: ["", "Cash", "Credit", "Cheque"].join("\n"),
		},
		{
			fieldname: "status",
			label: __("Invoice Status"),
			fieldtype: "Select",
			options: [
				"",
				"Paid",
				"Partly Paid",
				"Unpaid",
				"Overdue",
				"Return",
				"Credit Note Issued",
			].join("\n"),
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person"),
			fieldtype: "Data",
		},
		{
			fieldname: "only_mixed",
			label: __("Mixed Mode Only"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "only_unset_mode",
			label: __("Mode Not Set Only"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "include_draft_payments",
			label: __("Include Draft Payments"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		const colours = {
			Cash: "var(--green-600)",
			Card: "var(--blue-600)",
			BenefitPay: "var(--purple-600)",
			Cheque: "var(--orange-600)",
			"Bank Transfer": "var(--cyan-600)",
			Credit: "var(--red-500)",
			"Refund Due": "var(--red-500)",
			Adjustment: "var(--text-muted)",
			"Settled (no voucher)": "var(--orange-600)",
		};

		// The headline column: single class gets its colour, a mix is called out.
		if (column.fieldname === "payment_class" && data.payment_class) {
			const parts = String(data.payment_class).split(" / ");
			if (parts.length > 1) {
				value = '<span style="color:var(--orange-600)"><b>' + value + "</b></span>";
			} else if (colours[parts[0]]) {
				value = '<span style="color:' + colours[parts[0]] + '"><b>' + value + "</b></span>";
			}
		}

		// An inferred mode is a data-quality problem on the voucher, not on the invoice.
		if (column.fieldname === "mode_of_payment" && data.mode_not_set) {
			value = '<span style="color:var(--red-500)">' + value + "</span>";
		}

		if (column.fieldname === "mode_mismatch" && data.mode_mismatch) {
			value = '<span style="color:var(--red-500)"><b>' + value + "</b></span>";
		}

		if (column.fieldname === "outstanding" && flt(data.outstanding) > 0) {
			value = '<span style="color:var(--red-500)">' + value + "</span>";
		}

		if (column.fieldname === "amt_credit" && flt(data.amt_credit) > 0) {
			value = '<span style="color:var(--red-500)">' + value + "</span>";
		}

		return value;
	},

	onload: function (report) {
		report.page.add_inner_button(__("Payment Detail"), function () {
			report.set_filter_value("view", "Payment Detail");
		});
		report.page.add_inner_button(__("Mode Summary"), function () {
			report.set_filter_value("view", "Mode Summary");
		});
		report.page.add_inner_button(__("Mixed Mode Only"), function () {
			report.set_filter_value({ view: "Invoice Summary", only_mixed: 1, only_unset_mode: 0 });
		});
		report.page.add_inner_button(__("Credit Only"), function () {
			report.set_filter_value({
				view: "Invoice Summary",
				payment_class: "Credit",
				only_mixed: 0,
			});
		});
		report.page.add_inner_button(__("Today's Collection"), function () {
			report.set_filter_value({
				date_basis: "Payment Date",
				from_date: frappe.datetime.get_today(),
				to_date: frappe.datetime.get_today(),
				view: "Mode Summary",
			});
		});
	},
};
