"""Post-migration setup.

Called via the `after_migrate` hook. Ensures:
  * `Van User` + `Van Manager` roles exist.
  * A curated set of DocPerm rows for `Van User` covering the day-to-day
    flow (Sales Invoice, Payment Entry, Customer, Item lookups, etc.).
  * Vansale Configuration rows re-apply their User Permissions so admins
    can add a user on a config and have permissions materialise without
    having to open + save the row manually.

Mirror of `rmax_custom/setup.py` — adapted to Van Sale's narrower scope.
"""

from __future__ import annotations

import frappe

VAN_USER_ROLE = "Van User"
VAN_MANAGER_ROLE = "Van Manager"


# Minimum permissions for Van User. Read-only where the van doesn't need to edit.
VAN_USER_PERMISSIONS: list[dict] = [
    # Core sales flow — van users write these.
    {"parent": "Sales Invoice", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 0, "delete": 0, "print": 1, "email": 1, "report": 1, "export": 1, "share": 1},
    {"parent": "Payment Entry", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 0, "delete": 0, "print": 1, "email": 1, "report": 1, "export": 1, "share": 1},
    {"parent": "Customer", "read": 1, "write": 1, "create": 1, "submit": 0, "cancel": 0, "delete": 0, "print": 1, "email": 1, "report": 1, "export": 1, "share": 0},
    {"parent": "Address", "read": 1, "write": 1, "create": 1, "submit": 0, "cancel": 0, "delete": 0, "print": 1, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Contact", "read": 1, "write": 1, "create": 1, "submit": 0, "cancel": 0, "delete": 0, "print": 1, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Stock Entry", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 0, "delete": 0, "print": 1, "email": 0, "report": 1, "export": 0, "share": 0},
    # Van Sale domain — read/write own.
    {"parent": "Van Route Plan", "read": 1, "write": 1, "create": 1, "submit": 0, "cancel": 0, "delete": 0, "print": 1, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Van Visit Log", "read": 1, "write": 1, "create": 1, "submit": 0, "cancel": 0, "delete": 0, "print": 1, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Vansale Outbox", "read": 1, "write": 0, "create": 1, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    # Read-only reference data.
    {"parent": "Item", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 1, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Item Price", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Price List", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Item Group", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "UOM", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Warehouse", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Cost Center", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Company", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Mode of Payment", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Territory", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Customer Group", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Account", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 1, "export": 0, "share": 0},
    {"parent": "Sales Taxes and Charges Template", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    # Settings (read-only; needed for opening SI form etc.)
    {"parent": "Selling Settings", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Stock Settings", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "Accounts Settings", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
    {"parent": "User Permission", "read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0, "delete": 0, "print": 0, "email": 0, "report": 0, "export": 0, "share": 0},
]


def after_migrate() -> None:
    _ensure_role(VAN_USER_ROLE)
    _ensure_role(VAN_MANAGER_ROLE)
    _apply_role_permissions(VAN_USER_ROLE, VAN_USER_PERMISSIONS)
    _reapply_user_permissions()
    frappe.db.commit()


def _ensure_role(role: str, desk_access: int = 1) -> None:
    if frappe.db.exists("Role", role):
        return
    doc = frappe.new_doc("Role")
    doc.role_name = role
    doc.desk_access = desk_access
    doc.insert(ignore_permissions=True)


def _apply_role_permissions(role: str, perms: list[dict]) -> None:
    for perm in perms:
        filters = {"parent": perm["parent"], "role": role, "permlevel": 0}
        existing = frappe.db.get_value("Custom DocPerm", filters, "name")
        if existing:
            frappe.db.set_value("Custom DocPerm", existing, perm)
            continue
        doc = frappe.new_doc("Custom DocPerm")
        doc.parent = perm["parent"]
        doc.parenttype = "DocType"
        doc.parentfield = "permissions"
        doc.role = role
        doc.permlevel = 0
        for k, v in perm.items():
            if k == "parent":
                continue
            setattr(doc, k, v)
        try:
            doc.insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            pass


def _reapply_user_permissions() -> None:
    """Re-run `_create_permissions` on every Vansale Configuration so that
    fresh installs / migrations materialise the User Permissions even if
    the rows were saved before the controller existed."""
    if not frappe.db.exists("DocType", "Vansale Configuration"):
        return
    for name in frappe.get_all("Vansale Configuration", pluck="name"):
        try:
            doc = frappe.get_doc("Vansale Configuration", name)
            doc._create_permissions()  # type: ignore[attr-defined]
        except Exception as exc:
            frappe.log_error(
                message=str(exc),
                title=f"vansale: re-apply permissions failed for {name}",
            )
