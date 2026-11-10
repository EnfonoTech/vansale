// apps/vansale/vansale/sf_trading/report/invoice_due_and_overdue_report/invoice_due_and_overdue_report.js
frappe.query_reports["Invoice Due and Overdue Report"] = {
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
            fieldname: "invoice_type",
            label: __("Invoice Type"),
            fieldtype: "Select",
            options: ["Both", "Sales", "Purchase"].join("\n"),
            default: "Both",
        },
        {
            fieldname: "party",
            label: __("Party"),
            fieldtype: "Dynamic Link",
            get_options: function () {
                const t = frappe.query_report.get_filter_value("invoice_type");
                return t === "Purchase" ? "Supplier" : "Customer";
            },
        },
        {
            fieldname: "as_on_date",
            label: __("As On Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 1,
        },
        {
            fieldname: "overdue_only",
            label: __("Overdue Only"),
            fieldtype: "Check",
            default: 1,
        },
        {
            fieldname: "ageing_bucket",
            label: __("Ageing"),
            fieldtype: "Select",
            options: ["", "Not Due", "0-30", "31-60", "61-90", "90+"].join("\n"),
        },
        { fieldname: "due_from", label: __("Due Date From"), fieldtype: "Date" },
        { fieldname: "due_to", label: __("Due Date To"), fieldtype: "Date" },
        {
            fieldname: "branch",
            label: __("Branch"),
            fieldtype: "Link",
            options: "Branch",
        },
        {
            fieldname: "min_outstanding",
            label: __("Min Outstanding"),
            fieldtype: "Currency",
        },
    ],

    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (!data) return value;

        if (column.fieldname === "invoice_type") {
            const colour = data.invoice_type === "Sales" ? "var(--blue-500)" : "var(--purple-500)";
            value = `<span style="color:${colour}"><b>${value}</b></span>`;
        }

        if (column.fieldname === "overdue_days" && data.overdue_days > 0) {
            const colour = data.overdue_days > 90 ? "var(--red-600)" : "var(--orange-500)";
            value = `<span style="color:${colour}"><b>${value}</b></span>`;
        }

        if (column.fieldname === "outstanding_amount" && data.overdue_days > 0) {
            value = `<span style="color:var(--red-500)">${value}</span>`;
        }

        return value;
    },

    onload: function (report) {
        report.page.add_inner_button(__("Notify Me Now"), function () {
            frappe.call({
                method: "vansale.sf_trading.api.overdue_notifications.check_overdue_now",
                callback: function (r) {
                    if (!r.message) return;
                    const m = r.message;

                    // Say which channels actually fired, so "no email" is never a mystery.
                    let channels = __("chime + bell");
                    if (m.emailed) {
                        channels = __("chime + bell + email");
                    } else if (m.count && !m.email_configured) {
                        channels = __("chime + bell (no outgoing email account set)");
                    }

                    frappe.show_alert(
                        {
                            message: m.count
                                ? __("{0} overdue invoice(s), {1} outstanding — {2}", [
                                      m.count,
                                      format_currency(m.outstanding, m.currency),
                                      channels,
                                  ])
                                : __("Nothing overdue right now"),
                            indicator: m.count ? "orange" : "green",
                        },
                        7
                    );
                },
            });
        });
    },
};
