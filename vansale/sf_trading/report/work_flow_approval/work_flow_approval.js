

let wf_action = "";

frappe.query_reports["Work Flow Approval"] = {
    filters: [
        { fieldname: "user", label: "User", fieldtype: "Link", options: "User", default: frappe.session.user },
        { fieldname: "company", label: "Company", fieldtype: "Link", options: "Company" },

        {
            fieldname: "doctype", label: "Document Type", fieldtype: "Link", options: "DocType",
            get_query: function() {
                return {
                    query: "vansale.sf_trading.report.work_flow_approval.work_flow_approval.get_workflow_doctypes"
                };
            },
            on_change: function() {
                wf_action = "";
                $("#wf-action-select").val("");
                load_actions();
                frappe.query_report.refresh();
            }
        },
        { fieldname: "from_date", label: "From Date", fieldtype: "Date" },
        { fieldname: "to_date", label: "To Date", fieldtype: "Date" }
    ],

    after_datatable_render: function(dt) {
        $(dt.wrapper).find(".dt-cell--col-0").each(function(i) {
            if (i === 0) return;
            let $c = $(this).css({ "text-align": "center", "cursor": "pointer" });
            if (!$c.find('input[type="checkbox"]').length)
                $c.html('<input type="checkbox" class="row-check" style="width:16px;height:16px;cursor:pointer;">');
            $c.off("click").on("click", function(e) {
                if (!$(e.target).is("input"))
                    $c.find('input[type="checkbox"]').prop("checked", v => !v);
            });
        });
    },

    onload: function(report) {
        setTimeout(function() {
            if (report.page.page_form.length && !$("#wf-action-select").length) {
                report.page.page_form.append(`
                    <div style="display:inline-block;margin-left:8px;vertical-align:middle;">
                        <select id="wf-action-select" style="height:30px;border:none;border-radius:25px;
                            padding:0 14px;font-size:13px;font-family:inherit;color:#333;
                            background-color:#f4f5f6;min-width:160px;cursor:pointer;outline:none;">
                            <option value="">Workflow Action</option>
                        </select>
                    </div>`);
                $("#wf-action-select").on("change", function() { wf_action = $(this).val(); });
            }
            load_actions();
        }, 800);

        report.page.add_inner_button("Apply Workflow Action", function() {
            let docs = [];

            $(report.datatable.wrapper).find("input.row-check:checked").each(function() {
                let idx = parseInt($(this).closest(".dt-row").attr("data-row-index"));
                if (!isNaN(idx) && report.data[idx])
                    docs.push({ doctype: report.data[idx].doctype, name: report.data[idx].name });
            });

            if (!docs.length) {
                $(report.datatable.wrapper).find(".dt-row").each(function(i) {
                    if ($(this).find("input.row-check").prop("checked") && report.data[i])
                        docs.push({ doctype: report.data[i].doctype, name: report.data[i].name });
                });
            }

            if (!docs.length) return frappe.msgprint(__("Please select at least one document."));

            let action = $("#wf-action-select").val() || wf_action;
            if (!action) return frappe.msgprint(__("Please select a Workflow Action."));

            frappe.confirm(
                __("Apply <b>{0}</b> to {1} document(s)?", [action, docs.length]),
                () => frappe.call({
                    method: "vansale.sf_trading.report.work_flow_approval.work_flow_approval.apply_bulk_workflow",
                    args: { docs: JSON.stringify(docs), action },
                    freeze: true,
                    freeze_message: __("Applying..."),
                    callback: r => {
                        if (!r.exc) {
                            frappe.msgprint({ title: __("Result"), message: r.message, indicator: "green" });
                            frappe.query_report.refresh();
                        }
                    }
                })
            );
        });
    }
};

function load_actions() {
    let doctype = frappe.query_report.get_filter_value("doctype");
    let method = doctype
        ? "vansale.sf_trading.report.work_flow_approval.work_flow_approval.get_workflow_actions"
        : "vansale.sf_trading.report.work_flow_approval.work_flow_approval.get_all_workflow_actions";
    let args = doctype ? { doctype } : {};

    frappe.call({
        method: method,
        args: args,
        callback: r => {
            let $s = $("#wf-action-select").empty().append('<option value="">Workflow Action</option>');
            (r.message || []).forEach(a => $s.append(`<option value="${a}">${a}</option>`));
        }
    });
}