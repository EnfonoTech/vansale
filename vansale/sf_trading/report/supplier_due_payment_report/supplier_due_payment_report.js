// apps/vansale/vansale/sf_trading/report/supplier_due_payment_report/supplier_due_payment_report.js
frappe.query_reports["Supplier Due Payment Report"] = {
    filters: [
        {
            fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        { fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
        {
            fieldname: "as_on_date", label: __("As On Date"), fieldtype: "Date",
            default: frappe.datetime.get_today(),
        },
        { fieldname: "due_from", label: __("Due Date From"), fieldtype: "Date" },
        { fieldname: "due_to", label: __("Due Date To"), fieldtype: "Date" },
        { fieldname: "overdue_only", label: __("Overdue Only"), fieldtype: "Check", default: 0 },
        {
            fieldname: "ageing_bucket", label: __("Ageing"), fieldtype: "Select",
            options: ["", "Not Due", "0-30", "31-60", "61-90", "90+"].join("\n"),
        },
    ],
    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (column.fieldname === "overdue_days" && data && data.overdue_days > 0) {
            value = `<span style="color:var(--red-500)"><b>${value}</b></span>`;
        }
        return value;
    },
};
