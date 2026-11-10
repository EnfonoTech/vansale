import frappe
from frappe.utils import today, flt


@frappe.whitelist()
def make_sales_invoice_from_quotation(source_name):
	"""Map a Quotation to a new (unsaved) Sales Invoice and return the doc dict.
	Called via frappe.model.open_mapped_doc — the client opens the form without saving.
	"""
	frappe.has_permission("Quotation", "read", source_name, throw=True)
	frappe.has_permission("Sales Invoice", "create", throw=True)

	# Block duplicate: any non-cancelled SI already linked to this quotation
	existing = frappe.get_all(
		"Sales Invoice Item",
		filters={"custom_quotation": source_name, "docstatus": ["!=", 2]},
		fields=["parent", "docstatus"],
		ignore_permissions=True,
		limit=1,
	)
	if existing:
		si_name = existing[0].parent
		status = "Draft" if existing[0].docstatus == 0 else "Submitted"
		frappe.throw(
			frappe._("A Sales Invoice <b>{0}</b> ({1}) already exists for Quotation {2}.").format(
				si_name, status, source_name
			),
			title=frappe._("Duplicate Invoice"),
		)

	qot = frappe.get_doc("Quotation", source_name)

	si = frappe.new_doc("Sales Invoice")
	si.customer = qot.party_name
	si.company = qot.company
	si.posting_date = today()
	si.currency = qot.currency
	si.conversion_rate = qot.conversion_rate
	si.selling_price_list = qot.selling_price_list
	si.price_list_currency = qot.price_list_currency
	si.plc_conversion_rate = qot.plc_conversion_rate
	si.ignore_pricing_rule = qot.ignore_pricing_rule
	si.taxes_and_charges = qot.taxes_and_charges
	si.letter_head = qot.letter_head
	si.tc_name = qot.tc_name
	si.terms = qot.terms

	# Accounting dimensions
	for dim in ("branch", "cost_center", "project"):
		val = qot.get(dim)
		if val and frappe.db.has_column("Sales Invoice", dim):
			si.set(dim, val)

	# Items
	for q in qot.items:
		si_item = si.append("items", {
			"item_code": q.item_code,
			"item_name": q.item_name,
			"description": q.description,
			"qty": q.qty,
			"uom": q.uom,
			"conversion_factor": q.conversion_factor or 1,
			"rate": q.rate,
			"amount": q.amount,
			"discount_percentage": q.discount_percentage,
			"custom_quotation": source_name,
		})
		for dim in ("warehouse", "branch", "cost_center", "project"):
			val = q.get(dim)
			if val and frappe.db.has_column("Sales Invoice Item", dim):
				si_item.set(dim, val)

	# Taxes
	for tax in qot.taxes:
		si.append("taxes", {
			"charge_type": tax.charge_type,
			"account_head": tax.account_head,
			"rate": tax.rate,
			"description": tax.description,
			"cost_center": tax.cost_center,
		})

	si.run_method("set_missing_values")
	si.run_method("calculate_taxes_and_totals")

	return si.as_dict()


def get_dashboard_data(data):
	"""Add Sales Invoice to the Quotation "Connections" dashboard.

	Sales Invoices here are created directly from Quotation (Sales Order is
	skipped), so the link lives on Sales Invoice Item.custom_quotation instead
	of the standard prevdoc_docname fieldname.
	"""
	data = frappe._dict(data)
	data.setdefault("non_standard_fieldnames", {})["Sales Invoice"] = "custom_quotation"
	data.setdefault("transactions", []).append(
		{"label": frappe._("Sales Invoice"), "items": ["Sales Invoice"]}
	)
	return data


def update_quotation_status_from_invoice(doc, method=None):
	"""On Sales Invoice submit/cancel: update status of linked Quotations."""
	quotations = {item.custom_quotation for item in doc.items if item.get("custom_quotation")}

	for qot_name in quotations:
		_recalculate_quotation_status(qot_name)


def _recalculate_quotation_status(quotation_name):
	qot = frappe.get_doc("Quotation", quotation_name)
	if qot.docstatus != 1:
		return

	quoted = {}
	for item in qot.items:
		quoted[item.item_code] = quoted.get(item.item_code, 0) + flt(item.qty)

	si_items = frappe.get_all(
		"Sales Invoice Item",
		filters={"custom_quotation": quotation_name, "docstatus": 1},
		fields=["item_code", "qty"],
		ignore_permissions=True,
	)
	invoiced = {}
	for row in si_items:
		invoiced[row.item_code] = invoiced.get(row.item_code, 0) + flt(row.qty)

	total_quoted = sum(quoted.values())
	total_invoiced = sum(invoiced.get(k, 0) for k in quoted)

	if total_invoiced <= 0:
		status = "Open"
	elif total_invoiced >= total_quoted:
		status = "Ordered"
	else:
		status = "Partially Ordered"

	frappe.db.set_value("Quotation", quotation_name, "status", status)
	frappe.db.commit()
