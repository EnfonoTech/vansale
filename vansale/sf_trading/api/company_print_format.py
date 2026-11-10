import frappe


@frappe.whitelist()
def get_company_print_format(company, document_type):
	if not company or not document_type:
		return ""
	result = frappe.db.get_value(
		"Company Print Format",
		{"parent": company, "parenttype": "Company", "document_type": document_type},
		"print_format",
	)
	return result or ""
