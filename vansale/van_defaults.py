"""`before_validate` handlers that force Van User documents onto the user's
default cost center and warehouse, so they can't accidentally post to
a cost center they don't have permission for.

Reference: `rmax_custom/branch_defaults.py`.

Attached in `hooks.doc_events` for:
    Sales Invoice, Payment Entry, Stock Entry, Delivery Note.
"""

from __future__ import annotations

import frappe


def override_cost_center_from_van(doc, method=None):
    """Replace cost_center on header + items + taxes with the user's default
    whenever the user lacks User Permission for the existing value."""
    if frappe.session.user == "Administrator":
        return

    user_cc = _get_user_default("Cost Center")
    if not user_cc:
        return

    # Header cost_center — replace or default.
    if doc.get("cost_center"):
        if not _user_can_access("Cost Center", doc.cost_center):
            doc.cost_center = user_cc
    else:
        doc.cost_center = user_cc

    # Item-level cost_center.
    for item in doc.get("items") or []:
        if not hasattr(item, "cost_center"):
            continue
        if item.cost_center and not _user_can_access("Cost Center", item.cost_center):
            item.cost_center = user_cc
        elif not item.cost_center:
            item.cost_center = user_cc

    # Tax-level cost_center.
    for tax in doc.get("taxes") or []:
        if not hasattr(tax, "cost_center"):
            continue
        if tax.cost_center and not _user_can_access("Cost Center", tax.cost_center):
            tax.cost_center = user_cc
        elif not tax.cost_center:
            tax.cost_center = user_cc


def override_warehouse_from_van(doc, method=None):
    """Fallback: if `set_warehouse` is empty on a stock-affecting doc,
    use the user's default warehouse. Don't REPLACE an explicit choice —
    that's user intent. Sales Invoice / Delivery Note respect this.
    """
    if frappe.session.user == "Administrator":
        return

    user_wh = _get_user_default("Warehouse")
    if not user_wh:
        return

    if not doc.get("set_warehouse"):
        doc.set_warehouse = user_wh

    for item in doc.get("items") or []:
        if hasattr(item, "warehouse") and not item.warehouse:
            item.warehouse = user_wh


def _get_user_default(allow: str) -> str | None:
    return frappe.db.get_value(
        "User Permission",
        {"user": frappe.session.user, "allow": allow, "is_default": 1},
        "for_value",
    )


def _user_can_access(allow: str, value: str) -> bool:
    if not value:
        return True
    # If the user has no explicit restriction for this allow type, they
    # have access (Frappe default behaviour).
    has_any = frappe.db.exists(
        "User Permission", {"user": frappe.session.user, "allow": allow}
    )
    if not has_any:
        return True
    return bool(
        frappe.db.exists(
            "User Permission",
            {"user": frappe.session.user, "allow": allow, "for_value": value},
        )
    )
