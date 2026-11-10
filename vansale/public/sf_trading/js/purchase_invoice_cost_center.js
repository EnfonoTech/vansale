// Push header cost_center to tax rows and item rows client-side before save.
// Prevents permission errors when rows inherit a cost center the user can't access
// (e.g. 'Main - SF' from a tax template). Applies to all transactional doctypes
// that have a taxes table and a header-level cost_center field.

(function () {
    var DOCTYPES = [
        "Sales Invoice",
        "Purchase Invoice",
        "Purchase Order",
        "Purchase Receipt",
        "Sales Order",
        "Quotation",
        "Delivery Note",
        "Supplier Quotation",
    ];

    function push_cost_center(frm) {
        var cc = frm.doc.cost_center;
        if (!cc) return;
        (frm.doc.taxes || []).forEach(function (row) {
            row.cost_center = cc;
        });
        (frm.doc.items || []).forEach(function (row) {
            row.cost_center = cc;
        });
    }

    DOCTYPES.forEach(function (dt) {
        frappe.ui.form.on(dt, {
            cost_center: push_cost_center,
            before_save: push_cost_center,
        });
    });
})();

// Purchase Receipt: clear rejected_warehouse on item rows when Frappe's set_defaults
// auto-fills it with the same value as warehouse (user default warehouse applied to
// all Warehouse link fields, causing "cannot be same" validation error).

function sf_clear_same_rejected_warehouse(frm) {
    (frm.doc.items || []).forEach(function (row) {
        if (row.rejected_warehouse && row.rejected_warehouse === row.warehouse) {
            row.rejected_warehouse = "";
        }
    });
}

frappe.ui.form.on("Purchase Receipt", {
    refresh: sf_clear_same_rejected_warehouse,
    before_save: sf_clear_same_rejected_warehouse,
});

frappe.ui.form.on("Purchase Receipt Item", {
    warehouse: function (frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.rejected_warehouse && row.rejected_warehouse === row.warehouse) {
            frappe.model.set_value(cdt, cdn, "rejected_warehouse", "");
        }
    },
    rejected_warehouse: function (frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.rejected_warehouse && row.rejected_warehouse === row.warehouse) {
            frappe.model.set_value(cdt, cdn, "rejected_warehouse", "");
        }
    },
});
