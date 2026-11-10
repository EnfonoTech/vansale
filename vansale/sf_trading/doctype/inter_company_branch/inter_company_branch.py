# Copyright (c) 2026, Sf Trading and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class InterCompanyBranch(Document):
	def validate(self):
		companies = [row.company for row in self.company_cost_centers]
		if len(companies) != len(set(companies)):
			frappe.throw(frappe._("Duplicate company in Company Cost Centers"))


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_branches_for_company(doctype, txt, searchfield, start, page_len, filters):
	"""Return Inter Company Branch names that have cost center for the given company."""
	company = filters.get("company") if isinstance(filters, dict) and filters else None
	if not company:
		return []
	txt = txt or ""
	# Return (name, name) for link field value and description
	return frappe.db.sql(
		"""
		SELECT DISTINCT parent, parent FROM `tabInter Company Branch Cost Center`
		WHERE company = %(company)s AND parent LIKE %(txt)s
		ORDER BY parent
		LIMIT %(start)s, %(page_len)s
		""",
		{"company": company, "txt": f"%%{txt}%%", "start": int(start), "page_len": int(page_len)},
	)
