// One expense account for a whole Material Issue. The server stamps it onto every row
// before validation; this mirrors it into the grid straight away so the account the
// accountant is about to save is the one on screen, rather than a surprise after saving.
const SF_MATERIAL_ISSUE = "Material Issue";

function sf_apply_expense_account(frm) {
    if (frm.doc.purpose !== SF_MATERIAL_ISSUE || !frm.doc.custom_expense_account) {
        return;
    }
    (frm.doc.items || []).forEach((row) => {
        frappe.model.set_value(row.doctype, row.name, "expense_account", frm.doc.custom_expense_account);
    });
    frm.refresh_field("items");
}

frappe.ui.form.on("Stock Entry", {
    setup: function (frm) {
        frm._wh_cleared = false;

        // a write-off account of this company, and never a group
        frm.set_query("custom_expense_account", function () {
            return {
                filters: {
                    company: frm.doc.company,
                    is_group: 0,
                },
            };
        });
    },

    custom_expense_account: function (frm) {
        sf_apply_expense_account(frm);
    },

    purpose: function (frm) {
        sf_apply_expense_account(frm);
    },
    refresh: function (frm) {
        if (frm.doc.__islocal && !frm._wh_cleared) {
            frm._wh_cleared = true;
            frm.set_value("from_warehouse", "");
            frm.set_value("to_warehouse", "");
        }
    },
});

frappe.ui.form.on("Stock Entry Detail", {
    items_add: function (frm) {
        sf_apply_expense_account(frm);
    },
});
