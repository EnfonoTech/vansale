"""
Override get_item_warehouse to skip session/default warehouse when creating
inter-company Purchase Invoice. Ensures PI only gets warehouse from Inter Company Branch.
"""

import frappe
from erpnext.setup.doctype.brand.brand import get_brand_defaults
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.stock.doctype.item.item import get_item_defaults


def _patched_get_item_warehouse(item, args, overwrite_warehouse, defaults=None):
	if not defaults:
		defaults = frappe._dict(
			{
				"item_defaults": get_item_defaults(item.name, args.company),
				"item_group_defaults": get_item_group_defaults(item.name, args.company),
				"brand_defaults": get_brand_defaults(item.name, args.company),
			}
		)

	if overwrite_warehouse or not args.warehouse:
		warehouse = (
			args.get("set_warehouse")
			or defaults.item_defaults.get("default_warehouse")
			or defaults.item_group_defaults.get("default_warehouse")
			or defaults.brand_defaults.get("default_warehouse")
			or args.get("warehouse")
		)

		# Skip session/user defaults and Stock Settings when creating inter-company PI
		if not warehouse and not getattr(frappe.flags, "in_inter_company_pi_creation", False):
			_defaults = frappe.defaults.get_defaults() or {}
			warehouse_exists = frappe.db.exists(
				"Warehouse", {"name": _defaults.get("default_warehouse"), "company": args.company}
			)
			if _defaults.get("default_warehouse") and warehouse_exists:
				warehouse = _defaults.default_warehouse

	else:
		warehouse = args.get("warehouse")

	# Skip Stock Settings default when creating inter-company PI
	if not warehouse and not getattr(frappe.flags, "in_inter_company_pi_creation", False):
		default_warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
		if default_warehouse and frappe.db.get_value("Warehouse", default_warehouse, "company") == args.company:
			return default_warehouse

	return warehouse


def apply_patch():
	"""Replace get_item_warehouse so session/default warehouse is skipped when flag is set."""
	from erpnext.stock import get_item_details as gid

	if not hasattr(gid, "_original_get_item_warehouse"):
		gid._original_get_item_warehouse = gid.get_item_warehouse
	gid.get_item_warehouse = _patched_get_item_warehouse


def restore_patch():
	"""Restore original get_item_warehouse."""
	from erpnext.stock import get_item_details as gid

	if hasattr(gid, "_original_get_item_warehouse"):
		gid.get_item_warehouse = gid._original_get_item_warehouse
