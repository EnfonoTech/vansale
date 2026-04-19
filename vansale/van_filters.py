"""`permission_query_conditions` — list-view filters for Van Users.

Reference: `rmax_custom/branch_filters.py`.

A Van User's list views only show documents that touch their van's
warehouse(s). System/Van Managers see everything. Users not assigned
to any Vansale Configuration get normal Frappe permission behaviour.
"""

from __future__ import annotations

from typing import Iterable

import frappe


# ----------------------------------------------------------------------------


def _is_van_user(user: str) -> bool:
    """True iff the user is listed in any Vansale Configuration."""
    return bool(frappe.db.exists("Vansale Configuration User", {"user": user}))


def _is_unrestricted(user: str) -> bool:
    if not user or user == "Administrator":
        return True
    roles = frappe.get_roles(user)
    return "System Manager" in roles or "Van Manager" in roles


def _user_warehouses(user: str) -> list[str]:
    """Van warehouses from the user's Vansale Configuration(s)."""
    parents = frappe.get_all(
        "Vansale Configuration User",
        filters={"user": user},
        pluck="parent",
    )
    if not parents:
        return []
    return list(
        {
            r["warehouse"]
            for r in frappe.get_all(
                "Vansale Configuration Warehouse",
                filters={"parent": ["in", parents]},
                fields=["warehouse"],
            )
            if r.get("warehouse")
        }
    )


def _wh_list(warehouses: Iterable[str]) -> str:
    return ", ".join(frappe.db.escape(w) for w in warehouses)


# ----------------------------------------------------------------------------


def sales_invoice_query(user: str) -> str:
    if _is_unrestricted(user) or not _is_van_user(user):
        return ""
    warehouses = _user_warehouses(user)
    if not warehouses:
        # User is configured but has no warehouses yet — limit to own docs.
        return f"`tabSales Invoice`.`owner` = {frappe.db.escape(user)}"
    wl = _wh_list(warehouses)
    return f"""(
        `tabSales Invoice`.`set_warehouse` IN ({wl})
        OR `tabSales Invoice`.`name` IN (
            SELECT DISTINCT parent FROM `tabSales Invoice Item` WHERE warehouse IN ({wl})
        )
        OR `tabSales Invoice`.`owner` = {frappe.db.escape(user)}
    )"""


def payment_entry_query(user: str) -> str:
    if _is_unrestricted(user) or not _is_van_user(user):
        return ""
    warehouses = _user_warehouses(user)
    if not warehouses:
        return f"`tabPayment Entry`.`owner` = {frappe.db.escape(user)}"
    wl = _wh_list(warehouses)
    return f"""(
        `tabPayment Entry`.`owner` = {frappe.db.escape(user)}
        OR `tabPayment Entry`.`name` IN (
            SELECT DISTINCT per.parent
            FROM `tabPayment Entry Reference` per
            INNER JOIN `tabSales Invoice Item` sii ON sii.parent = per.reference_name
            WHERE per.reference_doctype = 'Sales Invoice'
              AND sii.warehouse IN ({wl})
        )
    )"""


def stock_entry_query(user: str) -> str:
    if _is_unrestricted(user) or not _is_van_user(user):
        return ""
    warehouses = _user_warehouses(user)
    if not warehouses:
        return f"`tabStock Entry`.`owner` = {frappe.db.escape(user)}"
    wl = _wh_list(warehouses)
    return f"""(
        `tabStock Entry`.`from_warehouse` IN ({wl})
        OR `tabStock Entry`.`to_warehouse` IN ({wl})
        OR `tabStock Entry`.`owner` = {frappe.db.escape(user)}
    )"""


def delivery_note_query(user: str) -> str:
    if _is_unrestricted(user) or not _is_van_user(user):
        return ""
    warehouses = _user_warehouses(user)
    if not warehouses:
        return f"`tabDelivery Note`.`owner` = {frappe.db.escape(user)}"
    wl = _wh_list(warehouses)
    return f"""(
        `tabDelivery Note`.`set_warehouse` IN ({wl})
        OR `tabDelivery Note`.`name` IN (
            SELECT DISTINCT parent FROM `tabDelivery Note Item` WHERE warehouse IN ({wl})
        )
        OR `tabDelivery Note`.`owner` = {frappe.db.escape(user)}
    )"""


def van_visit_log_query(user: str) -> str:
    if _is_unrestricted(user):
        return ""
    return f"`tabVan Visit Log`.`user` = {frappe.db.escape(user)}"


def van_route_plan_query(user: str) -> str:
    if _is_unrestricted(user):
        return ""
    return f"`tabVan Route Plan`.`user` = {frappe.db.escape(user)}"
