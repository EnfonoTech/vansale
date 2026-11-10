"""
Override frappe.defaults.get_defaults to exclude warehouse-related keys when creating
inter-company Purchase Invoice. Prevents session defaults from being applied.
"""

import frappe

_original_get_defaults = None


def _patched_get_defaults(user=None):
	"""Exclude default_warehouse and warehouse when in inter-company PI creation."""
	global _original_get_defaults
	defaults = _original_get_defaults(user)
	if not getattr(frappe.flags, "in_inter_company_pi_creation", False):
		return defaults
	# Remove warehouse-related keys so no code gets session default warehouse
	for key in ("default_warehouse", "warehouse"):
		defaults.pop(key, None)
	return defaults


def apply_defaults_patch():
	"""Patch get_defaults to exclude warehouse when flag is set."""
	global _original_get_defaults
	import frappe.defaults as defaults_mod

	if _original_get_defaults is None:
		_original_get_defaults = defaults_mod.get_defaults
	defaults_mod.get_defaults = _patched_get_defaults


def restore_defaults_patch():
	"""Restore original get_defaults."""
	global _original_get_defaults
	import frappe.defaults as defaults_mod

	if _original_get_defaults is not None:
		defaults_mod.get_defaults = _original_get_defaults
