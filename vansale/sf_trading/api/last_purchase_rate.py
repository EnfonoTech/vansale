import frappe
from frappe import _


def _permission_conditions():
	"""Build WHERE conditions + params for user-permitted Company and Cost Center.

	Mirrors last_selling_rate but against the Purchase Invoice aliases
	(pi = Purchase Invoice, pii = Purchase Invoice Item).
	"""
	from frappe.core.doctype.user_permission.user_permission import get_permitted_documents

	where_parts = []
	params = {}

	permitted_companies = get_permitted_documents("Company")
	if permitted_companies:
		where_parts.append("pi.company IN %(permitted_companies)s")
		params["permitted_companies"] = permitted_companies

	permitted_cost_centers = get_permitted_documents("Cost Center")
	if permitted_cost_centers:
		where_parts.append(
			"(pii.cost_center IN %(permitted_cost_centers)s "
			"OR (IFNULL(pii.cost_center, '') = '' AND pi.cost_center IN %(permitted_cost_centers)s))"
		)
		params["permitted_cost_centers"] = permitted_cost_centers

	return where_parts, params


@frappe.whitelist()
def get_last_purchase_rate(item_code, company=None):
	"""Return the most recent purchase rate for an item from submitted Purchase Invoices."""
	if not item_code:
		frappe.throw(_("Item Code is required"))

	if not company:
		company = frappe.defaults.get_user_default("company")

	perm_where, perm_params = _permission_conditions()
	where = ["pii.item_code = %(item_code)s", "pi.docstatus = 1"]
	params = {"item_code": item_code}

	if company:
		where.append("pi.company = %(company)s")
		params["company"] = company

	where.extend(perm_where)
	params.update(perm_params)
	where_sql = " AND ".join(where)

	last_purchase = frappe.db.sql(
		"""
		SELECT
			pii.rate AS purchase_rate,
			pii.base_rate AS base_purchase_rate,
			pii.amount AS amount,
			pii.qty AS qty,
			pii.uom AS uom,
			pi.posting_date AS posting_date,
			pi.name AS purchase_invoice,
			pi.supplier AS supplier,
			pi.supplier_name AS supplier_name,
			pi.currency AS currency,
			pi.company AS company
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE {where_sql}
		ORDER BY pi.posting_date DESC, pi.name DESC, pii.idx ASC
		LIMIT 1
		""".format(where_sql=where_sql),
		params,
		as_dict=True,
	)

	return last_purchase[0] if last_purchase else None


@frappe.whitelist()
def get_item_purchase_history(item_code=None, cost_center=None, limit=20):
	"""Return purchase history (rates) for an item. Requires cost_center."""
	if not cost_center:
		return []
	limit = int(limit or 20)
	where = ["pi.docstatus = 1"]
	params = {"limit": limit}

	if item_code:
		where.append("pii.item_code = %(item_code)s")
		params["item_code"] = item_code

	if cost_center:
		where.append(
			"(pii.cost_center = %(cost_center)s OR pi.cost_center = %(cost_center)s)"
		)
		params["cost_center"] = cost_center

	perm_where, perm_params = _permission_conditions()
	where.extend(perm_where)
	params.update(perm_params)
	where_sql = " AND ".join(where)

	rows = frappe.db.sql(
		"""
		SELECT
			pi.posting_date,
			pi.name AS purchase_invoice,
			pi.supplier,
			pi.supplier_name,
			pi.company,
			pii.item_code,
			pii.item_name,
			pii.qty,
			pii.uom,
			pii.rate AS purchase_rate,
			pii.base_rate AS base_purchase_rate,
			pii.amount AS purchase_amount,
			pi.currency
		FROM `tabPurchase Invoice Item` pii
		INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE {where_sql}
		ORDER BY pi.posting_date DESC, pi.name DESC, pii.idx ASC
		LIMIT %(limit)s
		""".format(where_sql=where_sql),
		params,
		as_dict=True,
	)

	return rows
