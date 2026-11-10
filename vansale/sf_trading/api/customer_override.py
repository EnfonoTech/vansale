"""
Customer overrides: require attachment when VAT Registration Number is set.
"""

from __future__ import annotations

import frappe
from frappe import _


def validate(doc, _method=None):
	"""Require at least one attachment when the customer has a VAT Registration Number."""
	vat_number = frappe.utils.cstr(doc.get("custom_vat_registration_number") or "").strip()
	if not vat_number or vat_number == "0":
		return

	# Skip on first save — attachment section only appears after the doc exists
	if doc.flags.get("in_insert"):
		return

	attachments = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Customer", "attached_to_name": doc.name},
		limit=1,
	)
	if not attachments:
		frappe.throw(
			_(
				"Customer {0} has a VAT Registration Number ({1}). "
				"Please attach the required VAT document before saving."
			).format(doc.customer_name or doc.name, vat_number)
		)
