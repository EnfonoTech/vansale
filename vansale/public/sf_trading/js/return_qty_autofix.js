// Auto-negate item quantities on return documents.
// ERPNext requires negative qty on returns. Users enter positive numbers;
// this converts them silently so the "quantity must be negative" error never appears.

(function () {
	var RETURN_DOCTYPES = [
		{ doctype: "Sales Invoice",    child: "Sales Invoice Item"    },
		{ doctype: "Purchase Invoice", child: "Purchase Invoice Item" },
		{ doctype: "Delivery Note",    child: "Delivery Note Item"    },
		{ doctype: "Purchase Receipt", child: "Purchase Receipt Item" },
	];

	function negate_if_positive(frm, cdt, cdn) {
		if (!frm.doc.is_return) return;
		var row = locals[cdt][cdn];
		if (flt(row.qty) > 0) {
			frappe.model.set_value(cdt, cdn, "qty", -Math.abs(flt(row.qty)));
		}
	}

	function negate_all_items(frm) {
		if (!frm.doc.is_return) return;
		(frm.doc.items || []).forEach(function (item) {
			if (flt(item.qty) > 0) {
				frappe.model.set_value(
					frm.doc.doctype + " Item", item.name, "qty", -Math.abs(flt(item.qty))
				);
			}
		});
	}

	RETURN_DOCTYPES.forEach(function (entry) {
		frappe.ui.form.on(entry.doctype, { validate: negate_all_items });
		frappe.ui.form.on(entry.child,   { qty: negate_if_positive   });
	});
})();
