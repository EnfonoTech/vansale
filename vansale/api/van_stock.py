"""Van (truck-local) stock view. Uses ERPNext's existing Bin table so a
van is just a Warehouse tagged as the user's default — no parallel
ledger to maintain. Stock movements happen via Stock Entry transfers.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _

from vansale.api.datetime_util import naive_site_to_utc_iso


def _user_van_warehouse() -> Optional[str]:
    user = frappe.session.user
    return (
        frappe.db.get_value("Sales Person", {"user": user}, "custom_van_warehouse")
        or frappe.defaults.get_user_default("Warehouse", user)
    )


@frappe.whitelist(methods=["GET"])
def my_warehouse() -> dict:
    wh = _user_van_warehouse()
    return {"warehouse": wh}


@frappe.whitelist(methods=["GET"])
def list_stock(warehouse: Optional[str] = None, limit: int = 500) -> dict:
    wh = warehouse or _user_van_warehouse()
    if not wh:
        frappe.throw(_("No van warehouse set. Assign one on your Sales Person profile."))
    rows = frappe.db.sql(
        """
        SELECT b.item_code, i.item_name, i.stock_uom, b.actual_qty,
               b.stock_value, i.image
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE b.warehouse = %s AND i.disabled = 0 AND b.actual_qty > 0
        ORDER BY i.item_name ASC
        LIMIT %s
        """,
        (wh, int(limit)),
        as_dict=True,
    )
    for r in rows:
        r["actual_qty"] = float(r.get("actual_qty") or 0)
        r["stock_value"] = float(r.get("stock_value") or 0)
    return {"warehouse": wh, "items": rows}


@frappe.whitelist(methods=["POST"])
def transfer_in(
    from_warehouse: str,
    items: list[dict],
    to_warehouse: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """Create a Material Transfer Stock Entry from ``from_warehouse`` to the user's van."""
    target = to_warehouse or _user_van_warehouse()
    if not target:
        frappe.throw(_("No destination warehouse"))
    if not from_warehouse:
        frappe.throw(_("Source warehouse required"))
    if not items:
        frappe.throw(_("At least one item required"))

    doc = frappe.new_doc("Stock Entry")
    doc.stock_entry_type = "Material Transfer"
    doc.from_warehouse = from_warehouse
    doc.to_warehouse = target
    doc.remarks = reason or "Van replenishment"

    for item in items:
        row = doc.append("items", {})
        row.item_code = item["item_code"]
        row.qty = float(item.get("qty") or 0)
        row.s_warehouse = from_warehouse
        row.t_warehouse = target

    doc.insert(ignore_permissions=False)
    doc.submit()
    frappe.db.commit()
    return {"name": doc.name, "modified": naive_site_to_utc_iso(doc.modified)}
