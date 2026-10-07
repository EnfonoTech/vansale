"""Read access for the app's endpoints.

Endpoints load documents with `frappe.get_doc` / `frappe.get_all`, which do
not check permissions, so any logged-in user could read any invoice,
payment, statement or stock by name. These helpers apply Frappe's own
rules instead: role permissions plus the user's User Permissions (e.g. a
salesman limited to his Warehouse / Sales Person). The creator of a
document can always read it.
"""

from __future__ import annotations

import frappe
from frappe import _


def _deny(doctype: str, name: str):
    frappe.throw(
        _("You are not permitted to access {0} {1}").format(_(doctype), name),
        frappe.PermissionError,
    )


def readable_doc(doctype: str, name: str):
    """The document, if the user created it or may read it; else PermissionError."""
    doc = frappe.get_doc(doctype, name)
    if doc.owner != frappe.session.user and not frappe.has_permission(doctype, "read", doc=doc):
        _deny(doctype, name)
    return doc


def check_read(doctype: str, name: str) -> None:
    """PermissionError unless the user may read this record (e.g. a Customer or Warehouse)."""
    if not name:
        return
    if not frappe.has_permission(doctype, "read", doc=name):
        _deny(doctype, name)
