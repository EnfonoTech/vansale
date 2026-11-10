// apps/vansale/vansale/sf_trading/report/reorder_recommendation/reorder_recommendation.js

const SF_ACTION_COLOURS = {
	"Out of Stock": "#b71c1c",
	"Order Now": "#c62828",
	"Below Level": "#ef6c00",
	Watch: "#f9a825",
	OK: "#2e7d32",
	Overstocked: "#6a1b9a",
	"Dead Stock": "#455a64",
	"No Demand": "#90a4ae",
};

frappe.query_reports["Reorder Recommendation"] = {
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
			// three months reads the season the business is actually in
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			// a group warehouse covers everything beneath it
			get_query: function () {
				return {
					filters: { company: frappe.query_report.get_filter_value("company") },
				};
			},
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function () {
				return { filters: { is_stock_item: 1 } };
			},
		},
		{
			fieldname: "lead_time_days",
			label: __("Default Lead Time (Days)"),
			fieldtype: "Int",
			default: 7,
			description: __("Used when purchase history and the item master have none"),
		},
		{
			fieldname: "coverage_days",
			label: __("Coverage Days"),
			fieldtype: "Int",
			default: 30,
			description: __("How many days each order should cover"),
		},
		{
			fieldname: "service_level",
			label: __("Service Level"),
			fieldtype: "Select",
			options: ["85%", "90%", "95%", "99%"].join("\n"),
			default: "95%",
			description: __("Higher means more safety stock"),
		},
		{
			fieldname: "min_demand_qty",
			label: __("Minimum Demand"),
			fieldtype: "Float",
			default: 0,
			description: __("Skip items that barely moved"),
		},
		{
			fieldname: "include_material_issue",
			label: __("Count Material Issue as demand"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "only_action_needed",
			label: __("Only items to order"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "include_no_demand",
			label: __("Show idle stock too"),
			fieldtype: "Check",
			default: 0,
			description: __("Adds items holding stock that did not sell in the window"),
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === "action") {
			const colour = SF_ACTION_COLOURS[data.action] || "#616161";
			return `<span style="background:${colour};color:#fff;padding:2px 8px;
				border-radius:10px;font-size:11px;white-space:nowrap">${__(data.action)}</span>`;
		}

		// the two numbers a buyer acts on
		if (column.fieldname === "reorder_qty" && flt(data.reorder_qty)) {
			value = `<b style="color:#1f6f54">${value}</b>`;
		}
		if (column.fieldname === "reorder_level" && flt(data.reorder_level)) {
			value = `<b>${value}</b>`;
		}

		if (column.fieldname === "actual_qty" && flt(data.actual_qty) <= 0) {
			value = `<span style="color:#b71c1c;font-weight:600">${value}</span>`;
		}
		// stock below what is being recommended is the whole point of the report
		if (
			column.fieldname === "projected_qty" &&
			flt(data.projected_qty) < flt(data.reorder_level)
		) {
			value = `<span style="color:#c62828">${value}</span>`;
		}
		if (column.fieldname === "days_cover" && data.days_cover !== null) {
			const d = flt(data.days_cover);
			if (d < flt(data.lead_days)) {
				value = `<span style="color:#c62828">${value}</span>`;
			} else if (d > 180) {
				value = `<span style="color:#6a1b9a">${value}</span>`;
			}
		}
		if (column.fieldname === "existing_level" && !flt(data.existing_level)) {
			value = `<span style="color:#9e9e9e">${__("not set")}</span>`;
		}
		return value;
	},
};
