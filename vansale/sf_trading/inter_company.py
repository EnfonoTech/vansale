"""
Auto-create draft Inter Company Purchase Invoice (from Sales Invoice) on submit.
Uses built-in methods, avoids duplicates.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


def sales_invoice_on_submit(doc, method=None):
	"""Auto-create draft Inter Company Purchase Invoice on SI submit (no duplicate)."""
	if not doc.is_internal_customer or not doc.represents_company:
		return
	if frappe.db.exists(
		"Purchase Invoice",
		{"inter_company_invoice_reference": doc.name},
	):
		return

	try:
		import erpnext
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import (
			make_inter_company_purchase_invoice,
		)

		# Bypass session/default warehouse so PI only gets values from Inter Company Branch
		frappe.flags.in_inter_company_pi_creation = True
		from vansale.sf_trading.overrides.get_item_details import apply_patch, restore_patch
		from vansale.sf_trading.overrides.defaults import apply_defaults_patch, restore_defaults_patch

		apply_patch()
		apply_defaults_patch()
		try:
			pi = make_inter_company_purchase_invoice(doc.name)
			# Fetch Supplier Invoice No & Date from source Sales Invoice (built-in does not set these)
			pi.bill_no = doc.name
			pi.bill_date = doc.posting_date
			# Cost center & warehouse: from Inter Company Branch if selected, else company default
			branch_data = _get_branch_data(doc, pi.company)
			frappe.flags._inter_company_pi_branch_data = branch_data
			if branch_data.get("cost_center"):
				pi.cost_center = branch_data["cost_center"]
				for item in pi.items:
					if hasattr(item, "cost_center"):
						item.cost_center = branch_data["cost_center"]
			# Warehouse: ONLY from Inter Company Branch when update_stock; never use item/company default
			if cint(pi.update_stock):
				warehouse = branch_data.get("warehouse")
				if warehouse and _warehouse_belongs_to_company(warehouse, pi.company):
					pi.set_warehouse = warehouse
					for item in pi.items:
						if hasattr(item, "warehouse"):
							item.warehouse = warehouse
				else:
					# Don't use item default – clear any warehouse set by make_inter_company
					pi.set_warehouse = None
					for item in pi.items:
						if hasattr(item, "warehouse"):
							item.warehouse = None
					branch_name = doc.get("inter_company_branch") or ""
					frappe.throw(
						_(
							"Configure Warehouse in Inter Company Branch {0} for company {1} to create Purchase Invoice with stock update."
						).format(branch_name, pi.company),
					)
			# Fetch default Purchase Taxes and Charges Template and fill taxes table
			_apply_default_purchase_taxes(pi, branch_data)
			# Strip any warehouse/cost_center from session defaults that don't belong to PI company
			_clear_invalid_session_defaults(pi)
			pi.insert(ignore_permissions=True)
			frappe.msgprint(
				_("Inter Company Purchase Invoice {0} created as draft.").format(pi.name),
				alert=True,
			)
		finally:
			restore_patch()
			restore_defaults_patch()
			frappe.flags.in_inter_company_pi_creation = False
			frappe.flags.pop("_inter_company_pi_branch_data", None)
	except Exception as e:
		frappe.log_error(title="Inter Company PI auto-create", message=frappe.get_traceback())
		frappe.msgprint(
			_("Could not auto-create Inter Company Purchase Invoice: {0}").format(str(e)),
			indicator="orange",
			alert=True,
		)


def _apply_default_purchase_taxes(pi, branch_data: dict) -> None:
	"""Fetch the Purchase Taxes and Charges Template (currency + supplier tax-id
	aware, same rule as manual Purchase Invoices — see purchase_tax_template.py)
	and fill the taxes table."""
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	from vansale.sf_trading.purchase_tax_template import get_expected_template

	template = get_expected_template(pi.company, pi.currency, pi.supplier)
	if not template:
		return
	pi.taxes_and_charges = template
	taxes = get_taxes_and_charges("Purchase Taxes and Charges Template", template)
	if taxes:
		for row in list(pi.taxes or []):
			pi.remove(row)
		pi.extend("taxes", taxes)
		# Set cost center on tax rows from branch if applicable
		if branch_data.get("cost_center"):
			for row in pi.taxes or []:
				if hasattr(row, "cost_center") and not row.cost_center:
					row.cost_center = branch_data["cost_center"]


def _get_branch_data(doc, buying_company: str) -> dict:
	"""Get cost_center and warehouse for PI from Inter Company Branch, else company defaults."""
	import erpnext

	result = {}
	branch = doc.get("inter_company_branch")
	if branch and buying_company:
		row = frappe.db.get_value(
			"Inter Company Branch Cost Center",
			{"parent": branch, "company": buying_company},
			["cost_center", "warehouse"],
			as_dict=True,
		)
		if row:
			if row.cost_center:
				result["cost_center"] = row.cost_center
			if row.warehouse:
				result["warehouse"] = row.warehouse
	if "cost_center" not in result:
		result["cost_center"] = erpnext.get_default_cost_center(buying_company)
	return result


def purchase_invoice_before_validate(doc, method=None):
	"""When creating inter-company PI, strip warehouse/cost_center from session defaults and re-apply branch values."""
	if not getattr(frappe.flags, "in_inter_company_pi_creation", False):
		return
	_clear_invalid_session_defaults(doc)
	# Re-apply branch values in case session defaults overwrote them during insert flow
	_branch_data = getattr(frappe.flags, "_inter_company_pi_branch_data", None)
	if _branch_data:
		company = doc.company
		if _branch_data.get("cost_center") and _cost_center_belongs_to_company(_branch_data["cost_center"], company):
			doc.cost_center = _branch_data["cost_center"]
			for item in doc.items or []:
				if hasattr(item, "cost_center"):
					item.cost_center = _branch_data["cost_center"]
		if cint(doc.update_stock) and _branch_data.get("warehouse") and _warehouse_belongs_to_company(_branch_data["warehouse"], company):
			doc.set_warehouse = _branch_data["warehouse"]
			for item in doc.items or []:
				if hasattr(item, "warehouse"):
					item.warehouse = _branch_data["warehouse"]


def _clear_invalid_session_defaults(pi) -> None:
	"""Clear any warehouse/cost_center from session defaults that don't belong to PI company."""
	company = pi.company
	for attr in ("set_warehouse", "set_from_warehouse", "rejected_warehouse"):
		val = pi.get(attr)
		if val and not _warehouse_belongs_to_company(val, company):
			pi.set(attr, None)
	if pi.get("cost_center") and not _cost_center_belongs_to_company(pi.cost_center, company):
		pi.cost_center = None
	for item in pi.items or []:
		for attr in ("warehouse", "from_warehouse", "target_warehouse", "rejected_warehouse"):
			if hasattr(item, attr) and item.get(attr) and not _warehouse_belongs_to_company(item.get(attr), company):
				item.set(attr, None)
		if hasattr(item, "cost_center") and item.get("cost_center") and not _cost_center_belongs_to_company(item.cost_center, company):
			item.cost_center = None


def _cost_center_belongs_to_company(cost_center: str, company: str) -> bool:
	if not cost_center or not company:
		return False
	cc_company = frappe.db.get_value("Cost Center", cost_center, "company", cache=True)
	return cc_company == company


def _warehouse_belongs_to_company(warehouse: str, company: str) -> bool:
	"""Ensure warehouse belongs to company (avoids cross-company mismatch in production)."""
	if not warehouse or not company:
		return False
	wh_company = frappe.db.get_value("Warehouse", warehouse, "company", cache=True)
	return wh_company == company
