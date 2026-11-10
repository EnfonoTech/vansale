// apps/vansale/vansale/sf_trading/report/pdc_report/pdc_report.js
frappe.query_reports["PDC Report"] = {
    filters: [
        {
            fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
            default: frappe.defaults.get_user_default("Company"),
        },
        { fieldname: "from_date", label: __("Cheque Date From"), fieldtype: "Date" },
        { fieldname: "to_date", label: __("Cheque Date To"), fieldtype: "Date" },
        {
            fieldname: "payment_type", label: __("Payment Type"), fieldtype: "Select",
            options: ["", "Receive", "Pay", "Internal Transfer"].join("\n"),
        },
        {
            fieldname: "party_type", label: __("Party Type"), fieldtype: "Link", options: "DocType",
            get_query: () => ({ filters: { name: ["in", ["Customer", "Supplier", "Employee"]] } }),
        },
        {
            fieldname: "party", label: __("Party"), fieldtype: "Dynamic Link",
            get_options: function () {
                return frappe.query_report.get_filter_value("party_type");
            },
        },
        {
            fieldname: "status", label: __("Status"), fieldtype: "Select",
            options: ["", "Pending", "Cleared"].join("\n"), default: "",
        },
        { fieldname: "include_cancelled", label: __("Include Cancelled"), fieldtype: "Check", default: 0 },
    ],
    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (!data) return value;

        // the posting date is what the reminder notification counts back from — always red
        if (column.fieldname === "posting_date" && data.posting_date) {
            value = `<span style="color:var(--red-500)"><b>${value}</b></span>`;
        }

        // reminder day: red once it has passed, orange on the day itself
        if (column.fieldname === "reminder_date" && data.days_to_posting_date != null) {
            if (data.days_to_posting_date < 3) value = `<span style="color:var(--red-500)">${value}</span>`;
            else if (data.days_to_posting_date === 3) value = `<span style="color:var(--orange-500)"><b>${value}</b></span>`;
        }

        for (const field of ["days_to_posting_date", "days_to_cheque_date"]) {
            if (column.fieldname === field && data[field] != null) {
                if (data[field] < 0) value = `<span style="color:var(--red-500)">${value}</span>`;
                else if (data[field] === 0) value = `<span style="color:var(--orange-500)"><b>${value}</b></span>`;
            }
        }
        return value;
    },
};
