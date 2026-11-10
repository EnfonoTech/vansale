"""Provisioning for the two stock-billing timing features.

`vansale.sf_trading.sdbnb` (deliver then bill) and `vansale.sf_trading.sbnd` (bill then deliver)
both need an extra option on `Account.account_type`. One writer owns that
Property Setter, otherwise each feature would rebuild the option list from the
shipped DocField and drop the other one's entry.

Wired to `after_migrate`, so a plain `bench migrate` provisions everything. On a
code-only deploy run it directly:

    bench --site <site> execute vansale.sf_trading.stock_billing_setup.setup
"""

import frappe

from vansale.sf_trading import sbnd, sdbnb

ACCOUNT_TYPES = (sdbnb.SDBNB_ACCOUNT_TYPE, sbnd.SBND_ACCOUNT_TYPE)


def setup():
	sdbnb.ensure_custom_fields()
	sbnd.ensure_custom_fields()
	ensure_account_type_options()


def ensure_account_type_options():
	"""Add our Account Types without freezing the core list.

	The options are re-derived from the shipped DocField every time, so an
	option added by a future ERPNext release is picked up rather than dropped,
	and an option core starts shipping itself stops being duplicated here.
	"""
	core_options = frappe.db.get_value(
		"DocField", {"parent": "Account", "fieldname": "account_type"}, "options"
	)
	if not core_options:
		return

	options = core_options.split("\n")
	missing = [account_type for account_type in ACCOUNT_TYPES if account_type not in options]

	existing = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Account", "field_name": "account_type", "property": "options"},
		"name",
	)

	if not missing:
		# core ships every option we need — drop our override so the shipped list wins
		if existing:
			frappe.db.delete("Property Setter", {"name": existing})
			frappe.clear_cache(doctype="Account")
		return

	value = "\n".join(options + missing)

	if existing:
		if frappe.db.get_value("Property Setter", existing, "value") != value:
			frappe.db.set_value("Property Setter", existing, "value", value)
	else:
		frappe.get_doc(
			{
				"doctype": "Property Setter",
				"doctype_or_field": "DocField",
				"doc_type": "Account",
				"field_name": "account_type",
				"property": "options",
				"property_type": "Text",
				"value": value,
			}
		).insert(ignore_permissions=True)

	frappe.clear_cache(doctype="Account")
