"""Branch Accounting Dimension for sf_trading.

Enables Branch as an Accounting Dimension so every transaction doctype
carries a `branch` Link field, and auto-fills it from the document's
warehouse mapping.
"""
import frappe
from frappe import _


def ensure_branch_accounting_dimension() -> None:
    """Create/update the Branch Accounting Dimension and fix read permissions.

    Adds the `branch` field to all transaction doctypes via ERPNext's
    Accounting Dimension system. Dimension defaults are NOT set to
    mandatory so existing documents without a branch are not blocked.

    Also grants read access on the Branch DocType to all authenticated
    users — Frappe validates Link fields on save, so any user who saves
    a document with a `branch` value must be able to read Branch records.

    Idempotent — safe to re-run from after_migrate.
    """
    dim_name = frappe.db.get_value("Accounting Dimension", {"document_type": "Branch"})
    if dim_name:
        dim = frappe.get_doc("Accounting Dimension", dim_name)
    else:
        dim = frappe.new_doc("Accounting Dimension")
        dim.document_type = "Branch"
        dim.disabled = 0
        dim.insert(ignore_permissions=True)
        frappe.db.commit()

    if dim.disabled:
        dim.disabled = 0
        dim.save(ignore_permissions=True)
        frappe.db.commit()

    _ensure_branch_read_permission()


def _ensure_branch_read_permission() -> None:
    """Grant read-only access on Branch to all authenticated users.

    Without this, regular users (Sales User, Accounts User, etc.) hit
    "does not have doctype access via role permission for document Branch"
    whenever Frappe validates the branch Link field on a transaction doc.
    Branch is a reference/lookup table so read-only for everyone is safe.

    Uses frappe.permissions.add_permission, which first copies the standard
    role permissions into Custom DocPerm (via setup_custom_perms) so they are
    preserved — inserting a Custom DocPerm directly would REPLACE every
    standard Branch permission and leave only this one. Idempotent.
    """
    from frappe.permissions import add_permission, reset_perms, update_permission_property

    custom_roles = set(
        frappe.get_all("Custom DocPerm", filters={"parent": "Branch"}, pluck="role")
    )

    # Recover from the earlier destructive version: if the only Custom DocPerm
    # left is our injected "All" row, the standard Branch permissions were wiped.
    # reset_perms deletes all Custom DocPerm so Branch falls back to its standard
    # (doctype JSON) permissions, then we re-add read-for-all the safe way.
    if custom_roles and custom_roles == {"All"}:
        reset_perms("Branch")
        custom_roles = set()

    if frappe.db.exists("Custom DocPerm", {"parent": "Branch", "role": "All", "read": 1}):
        return

    add_permission("Branch", "All", 0)
    update_permission_property("Branch", "All", 0, "read", 1)
    frappe.clear_cache(doctype="Branch")
    frappe.db.commit()


def resolve_warehouse_branch(warehouse: str) -> str | None:
    """Return the Branch Configuration name whose warehouse list contains `warehouse`."""
    if not warehouse:
        return None
    return frappe.db.get_value(
        "Branch Configuration Warehouse",
        {"warehouse": warehouse},
        "parent",
    )


def auto_set_branch_from_warehouse(doc, method=None) -> None:
    """Populate `branch` on transaction docs from their warehouse.

    Resolves: header `set_warehouse` → first item `warehouse` / `s_warehouse`.
    Only sets branch when the field is blank (does not override operator input).
    Skips if the `branch` field doesn't exist on the doctype (dimension not yet
    set up) to avoid AttributeError on sites that haven't run after_migrate yet.
    Bypass: Administrator and System Manager.
    """
    if not doc.meta.has_field("branch"):
        return

    if doc.get("branch"):
        return

    user = frappe.session.user
    if user == "Administrator":
        return
    if "System Manager" in frappe.get_roles(user):
        return

    wh = (
        doc.get("set_warehouse")
        or doc.get("from_warehouse")
        or next(
            (
                (item.get("warehouse") or item.get("s_warehouse"))
                for item in (doc.get("items") or [])
                if item.get("warehouse") or item.get("s_warehouse")
            ),
            None,
        )
    )

    resolved = resolve_warehouse_branch(wh)
    if resolved:
        doc.branch = resolved
