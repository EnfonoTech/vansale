"""Admin-only helpers.

These endpoints exist so a System Manager or Van Manager can set up a
Van User without leaving the Vansale Configuration form — Frappe's
default "new User" email flow often fails on demo tenants (email
queue unconfigured), which leaves the user stuck at the PWA login
with no password.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils.password import update_password


def _require_admin() -> None:
    roles = frappe.get_roles(frappe.session.user)
    if "System Manager" not in roles and "Van Manager" not in roles:
        frappe.throw(_("System Manager or Van Manager role required"), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def set_user_password(user: str, new_password: str) -> dict:
    """Set a password for a user listed in at least one Vansale Configuration.

    Restrictions:
      * Caller must be System Manager or Van Manager.
      * Target user must be listed in at least one Vansale Configuration
        (prevents using this endpoint as a general password reset).
      * Minimum password length: 6 characters.
    """
    _require_admin()

    if not user:
        frappe.throw(_("user required"))
    if not new_password or len(new_password) < 6:
        frappe.throw(_("Password must be at least 6 characters"))

    if not frappe.db.exists("User", user):
        frappe.throw(_("User not found"))

    if not frappe.db.exists("Vansale Configuration User", {"user": user}):
        frappe.throw(_("User is not in any Vansale Configuration — use the standard User form instead"))

    update_password(user, new_password)
    frappe.db.commit()
    return {"ok": True, "user": user}


@frappe.whitelist(methods=["GET"])
def users_without_password() -> list[dict]:
    """List Van Users who have no password yet (so the admin can reset them in bulk)."""
    _require_admin()

    users = frappe.get_all(
        "Vansale Configuration User",
        fields=["user", "parent"],
        limit=500,
    )
    result = []
    for row in users:
        pwd = frappe.db.get_value("__Auth", {"doctype": "User", "name": row["user"], "fieldname": "password"}, "password")
        if not pwd:
            result.append({"user": row["user"], "vansale_configuration": row["parent"]})
    return result
