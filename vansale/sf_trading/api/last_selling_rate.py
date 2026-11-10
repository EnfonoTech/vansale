import frappe
from frappe import _


def _permission_conditions():
	"""
	Build WHERE conditions and params for user-permitted Company and Cost Center.
	Returns (extra_where_parts list, extra_params dict).
	If user has no restrictions for a doctype, that filter is not added.
	"""
	from frappe.core.doctype.user_permission.user_permission import get_permitted_documents

	where_parts = []
	params = {}

	# Permitted companies (User Permission on Company)
	permitted_companies = get_permitted_documents("Company")
	if permitted_companies:
		where_parts.append("si.company IN %(permitted_companies)s")
		params["permitted_companies"] = permitted_companies

	# Permitted cost centers (User Permission on Cost Center)
	# Apply to invoice header cost_center and item row cost_center
	permitted_cost_centers = get_permitted_documents("Cost Center")
	if permitted_cost_centers:
		where_parts.append(
			"(sii.cost_center IN %(permitted_cost_centers)s "
			"OR (IFNULL(sii.cost_center, '') = '' AND si.cost_center IN %(permitted_cost_centers)s))"
		)
		params["permitted_cost_centers"] = permitted_cost_centers

	return where_parts, params


@frappe.whitelist()
def get_last_selling_rate(item_code, company=None):
	"""
	Get last selling rate for an item from submitted Sales Invoices.
	
	Args:
		item_code: Item code to get last selling rate for
		company: Company name (optional, will use default if not provided)
	
	Returns:
		Dictionary with last selling rate details or None
	"""
	if not item_code:
		frappe.throw(_("Item Code is required"))
	
	# Get company from context or use default
	if not company:
		company = frappe.defaults.get_user_default("company")
	
	# Build filters
	filters = {
		"item_code": item_code,
		"docstatus": 1  # Only submitted invoices
	}
	
	# Add company filter if provided
	if company:
		# Get sales invoices for the company
		sales_invoices = frappe.get_all(
			"Sales Invoice",
			filters={"company": company, "docstatus": 1},
			fields=["name"],
			pluck="name"
		)
		
		if not sales_invoices:
			return None
		
		filters["parent"] = ["in", sales_invoices]
	
	# Permission filters (permitted companies and cost centers)
	perm_where, perm_params = _permission_conditions()
	perm_sql = " AND " + " AND ".join(perm_where) if perm_where else ""
	sql_params = {"item_code": item_code, **perm_params}

	# Get last selling rate from Sales Invoice Items
	last_sale = frappe.db.sql("""
		SELECT
			sii.rate AS selling_rate,
			sii.base_rate AS base_selling_rate,
			sii.amount AS amount,
			sii.qty AS qty,
			sii.uom AS uom,
			si.posting_date AS posting_date,
			si.name AS sales_invoice,
			si.customer AS customer,
			si.customer_name AS customer_name,
			si.currency AS currency,
			si.company AS company
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.item_code = %(item_code)s
			AND si.docstatus = 1
			{perm_sql}
		ORDER BY si.posting_date DESC, si.name DESC, sii.idx ASC
		LIMIT 1
	""".format(perm_sql=perm_sql), sql_params, as_dict=True)
	
	if last_sale and len(last_sale) > 0:
		return last_sale[0]
	
	return None


@frappe.whitelist()
def get_item_selling_history(item_code=None, cost_center=None, customer=None, limit=20):
	"""Return selling history for an item. Requires cost_center. Optionally filter by customer."""
	if not cost_center:
		return []
	limit = int(limit or 20)
	where = ["si.docstatus = 1"]
	params = {"limit": limit}

	if item_code:
		where.append("sii.item_code = %(item_code)s")
		params["item_code"] = item_code

	if cost_center:
		where.append(
			"(sii.cost_center = %(cost_center)s OR si.cost_center = %(cost_center)s)"
		)
		params["cost_center"] = cost_center

	if customer:
		where.append("si.customer = %(customer)s")
		params["customer"] = customer

	# Restrict to user-permitted companies and cost centers
	perm_where, perm_params = _permission_conditions()
	where.extend(perm_where)
	params.update(perm_params)

	where_sql = " AND ".join(where)

	rows = frappe.db.sql("""
		SELECT
			si.posting_date,
			si.name AS sales_invoice,
			si.customer,
			si.customer_name,
			si.company,
			sii.item_code,
			sii.item_name,
			sii.qty,
			sii.uom,
			sii.rate AS selling_rate,
			sii.base_rate AS base_selling_rate,
			sii.amount AS selling_amount,
			si.currency
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE {where_sql}
		ORDER BY si.posting_date DESC, si.name DESC, sii.idx ASC
		LIMIT %(limit)s
	""".format(where_sql=where_sql), params, as_dict=True)

	return rows
