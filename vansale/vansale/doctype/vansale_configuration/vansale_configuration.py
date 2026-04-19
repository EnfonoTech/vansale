"""Vansale Configuration — "one van" scoped to a warehouse + cost center + users.

Mirror of RMAX's Branch Configuration pattern. On `on_update`:
  - Creates User Permissions for Company (default=1), Warehouse×N (first=default),
    Cost Center×N (first=default), Branch (if set).
  - Auto-grants Company's default cost center (tax templates reference it).
  - Assigns the chosen role (Van User / Van Manager).

On `before_save` with user removed from the table:
  - Deletes the User Permissions we created.
  - Removes the role if the user is not in any other Vansale Configuration.

Reference: `rmax_custom/rmax_custom/doctype/branch_configuration/branch_configuration.py`.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

VAN_USER_ROLE = "Van User"


class VansaleConfiguration(Document):
    def validate(self):
        """Warehouses + cost centers must belong to the selected company."""
        if not self.company:
            return

        for w in self.warehouse or []:
            if not w.warehouse:
                continue
            wh_company = frappe.db.get_value("Warehouse", w.warehouse, "company")
            if wh_company and wh_company != self.company:
                frappe.throw(
                    _("Warehouse {0} belongs to company {1}, not {2}.").format(
                        frappe.bold(w.warehouse),
                        frappe.bold(wh_company),
                        frappe.bold(self.company),
                    )
                )

        for c in self.cost_center or []:
            if not c.cost_center:
                continue
            cc_company = frappe.db.get_value("Cost Center", c.cost_center, "company")
            if cc_company and cc_company != self.company:
                frappe.throw(
                    _("Cost Center {0} belongs to company {1}, not {2}.").format(
                        frappe.bold(c.cost_center),
                        frappe.bold(cc_company),
                        frappe.bold(self.company),
                    )
                )

        # Warn if more than one warehouse — the pattern works, but the user's
        # default is the FIRST row, so order matters.
        # (No hard error — RMAX allows multi-warehouse branches.)

    def before_save(self):
        """Clean up User Permissions for users removed from the table."""
        if self.is_new():
            return

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        old_users = {d.user for d in old_doc.user if d.user}
        new_users = {d.user for d in self.user if d.user}
        removed = old_users - new_users

        for user in removed:
            if old_doc.get("company"):
                _delete_permission(user, "Company", old_doc.company)
            if old_doc.get("branch"):
                _delete_permission(user, "Branch", old_doc.branch)
            for w in old_doc.warehouse or []:
                _delete_permission(user, "Warehouse", w.warehouse)
            for c in old_doc.cost_center or []:
                _delete_permission(user, "Cost Center", c.cost_center)

            old_role = next(
                (ou.role for ou in old_doc.user if ou.user == user and ou.role),
                VAN_USER_ROLE,
            )
            _maybe_remove_role(user, old_role, exclude_config=self.name)

        # Company change — remove old company permission for remaining users.
        old_company = old_doc.get("company")
        new_company = self.get("company")
        if old_company and old_company != new_company:
            for u in self.user or []:
                if u.user:
                    _delete_permission(u.user, "Company", old_company)

    def on_update(self):
        self._create_permissions()

    def _create_permissions(self) -> None:
        for u in self.user or []:
            if not u.user:
                continue

            if self.company:
                _create_permission(u.user, "Company", self.company, is_default=1)

            if self.branch:
                _create_permission(u.user, "Branch", self.branch)

            for idx, w in enumerate(self.warehouse or []):
                if not w.warehouse:
                    continue
                _create_permission(u.user, "Warehouse", w.warehouse, is_default=1 if idx == 0 else 0)

            for idx, c in enumerate(self.cost_center or []):
                if not c.cost_center:
                    continue
                _create_permission(u.user, "Cost Center", c.cost_center, is_default=1 if idx == 0 else 0)

            # Company default cost center — used by tax templates — granted
            # but NOT marked default so the van's cost center wins.
            if self.company:
                company_default_cc = frappe.db.get_value("Company", self.company, "cost_center")
                if company_default_cc:
                    _create_permission(u.user, "Cost Center", company_default_cc, is_default=0)

            selected_role = u.role or VAN_USER_ROLE
            _assign_role(u.user, selected_role)


# ----------------------------------------------------------------------------
# Helpers (module-level so they can be reused by the `setup.py` migrator).
# ----------------------------------------------------------------------------


def _create_permission(user: str, allow: str, value: str, is_default: int = 0) -> None:
    if not value:
        return

    existing = frappe.db.exists(
        "User Permission",
        {"user": user, "allow": allow, "for_value": value},
    )

    if existing:
        if is_default and not _has_existing_default(user, allow, exclude_value=value):
            frappe.db.set_value("User Permission", existing, "is_default", 1)
        return

    if is_default and _has_existing_default(user, allow):
        is_default = 0

    doc = frappe.new_doc("User Permission")
    doc.user = user
    doc.allow = allow
    doc.for_value = value
    doc.is_default = is_default
    doc.apply_to_all_doctypes = 1
    doc.insert(ignore_permissions=True)


def _has_existing_default(user: str, allow: str, exclude_value: str | None = None) -> bool:
    filters: dict = {"user": user, "allow": allow, "is_default": 1}
    if exclude_value:
        filters["for_value"] = ["!=", exclude_value]
    return bool(frappe.db.exists("User Permission", filters))


def _delete_permission(user: str, allow: str, value: str) -> None:
    if not value:
        return
    name = frappe.db.get_value(
        "User Permission",
        {"user": user, "allow": allow, "for_value": value},
        "name",
    )
    if name:
        frappe.delete_doc("User Permission", name, ignore_permissions=True)


def _assign_role(user: str, role: str) -> None:
    if not role or not user:
        return
    user_doc = frappe.get_doc("User", user)
    if role in [r.role for r in user_doc.roles]:
        return
    user_doc.append("roles", {"role": role})
    user_doc.flags.ignore_permissions = True
    user_doc.save(ignore_permissions=True)


def _maybe_remove_role(user: str, role: str, exclude_config: str) -> None:
    """Remove the role only if the user isn't assigned to any OTHER Vansale Configuration."""
    still_assigned = frappe.db.exists(
        "Vansale Configuration User",
        {"user": user, "parent": ["!=", exclude_config]},
    )
    if still_assigned:
        return
    user_doc = frappe.get_doc("User", user)
    user_doc.roles = [r for r in user_doc.roles if r.role != role]
    user_doc.flags.ignore_permissions = True
    user_doc.save(ignore_permissions=True)
