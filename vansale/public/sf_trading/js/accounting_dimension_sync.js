// sf_trading: keep accounting dimensions consistent across transaction docs
//
//  1. Changing the Branch pulls that branch's default cost center + warehouse.
//  2. Changing any accounting dimension on the header (branch, cost_center,
//     project) pushes it to every item row.
//  3. Newly added item rows inherit the header's current dimensions.
//
// Registered for all sales & purchase transaction doctypes.

// Accounting dimension fieldnames present on both the parent and the item table.
const SF_DIMENSIONS = ["branch", "cost_center", "project"];

// Transaction doctypes that carry accounting dimensions + an `items` table.
const SF_DIM_DOCTYPES = [
	"Sales Invoice",
	"Sales Order",
	"Quotation",
	"Delivery Note",
	"Purchase Invoice",
	"Purchase Order",
	"Purchase Receipt",
	"Supplier Quotation",
];

function sf_push_dimension_to_items(frm, fieldname) {
	const val = frm.doc[fieldname];
	if (val === undefined) return;
	(frm.doc.items || []).forEach(function (row) {
		if (frappe.meta.has_field(row.doctype, fieldname)) {
			row[fieldname] = val;
		}
	});
	frm.refresh_field("items");
}

function sf_apply_branch_defaults(frm) {
	if (!frm.doc.branch) return;
	frappe.call({
		method: "vansale.sf_trading.branch_defaults.get_branch_dimension_defaults",
		args: { branch: frm.doc.branch },
		callback: function (r) {
			const d = r.message || {};
			if (d.letter_head && frm.fields_dict.letter_head) {
				frm.set_value("letter_head", d.letter_head);
			}
			if (d.cost_center && frm.fields_dict.cost_center) {
				frm.set_value("cost_center", d.cost_center);
			}
			if (d.set_warehouse && frm.fields_dict.set_warehouse) {
				frm.set_value("set_warehouse", d.set_warehouse);
			}
			// Forms without set_warehouse (e.g. Quotation): push warehouse to item rows
			if (d.set_warehouse && !frm.fields_dict.set_warehouse) {
				(frm.doc.items || []).forEach(function (row) {
					if (frappe.meta.has_field(row.doctype, "warehouse")) {
						row.warehouse = d.set_warehouse;
					}
				});
				frm.refresh_field("items");
			}
		},
	});
}

SF_DIM_DOCTYPES.forEach(function (dt) {
	frappe.ui.form.on(dt, {
		branch: function (frm) {
			// Pull this branch's cost center + warehouse, then sync branch to items.
			sf_apply_branch_defaults(frm);
			sf_push_dimension_to_items(frm, "branch");
		},
		cost_center: function (frm) {
			sf_push_dimension_to_items(frm, "cost_center");
		},
		project: function (frm) {
			sf_push_dimension_to_items(frm, "project");
		},
		items_add: function (frm, cdt, cdn) {
			// New item row inherits the header's current accounting dimensions.
			const row = locals[cdt][cdn];
			SF_DIMENSIONS.forEach(function (f) {
				if (frm.doc[f] && frappe.meta.has_field(cdt, f)) {
					row[f] = frm.doc[f];
				}
			});
			frm.refresh_field("items");
		},
	});
});
