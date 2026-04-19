"""Item endpoints for the invoice picker + stock view."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _


_ITEM_FIELDS = [
    "name",
    "item_code",
    "item_name",
    "item_group",
    "stock_uom",
    "standard_rate",
    "image",
    "disabled",
    "is_stock_item",
    "has_variants",
]


@frappe.whitelist(methods=["GET"])
def list_mine(limit: int = 100, search: Optional[str] = None, warehouse: Optional[str] = None) -> list[dict]:
    filters: dict = {"disabled": 0, "has_variants": 0}
    or_filters = None
    if search:
        s = f"%{search}%"
        or_filters = {"item_name": ["like", s], "item_code": ["like", s], "barcode": ["like", s]}
    rows = frappe.get_all(
        "Item",
        filters=filters,
        or_filters=or_filters,
        fields=_ITEM_FIELDS,
        limit=int(limit),
        order_by="modified desc",
    )
    if warehouse and rows:
        codes = [r["item_code"] for r in rows]
        balances = {
            b.item_code: float(b.actual_qty or 0)
            for b in frappe.get_all(
                "Bin",
                filters={"warehouse": warehouse, "item_code": ["in", codes]},
                fields=["item_code", "actual_qty"],
            )
        }
        for r in rows:
            r["stock_qty"] = balances.get(r["item_code"], 0.0)
    return rows


@frappe.whitelist(methods=["GET"])
def detail(item_code: str, customer: Optional[str] = None) -> dict:
    if not item_code:
        frappe.throw(_("Item code required"))
    doc = frappe.get_doc("Item", item_code)
    price = frappe.db.get_value(
        "Item Price",
        {"item_code": item_code, "selling": 1},
        "price_list_rate",
        order_by="valid_from desc",
    )
    return {
        "name": doc.name,
        "item_code": doc.item_code,
        "item_name": doc.item_name,
        "item_group": doc.item_group,
        "stock_uom": doc.stock_uom,
        "standard_rate": float(doc.standard_rate or 0),
        "price_list_rate": float(price or doc.standard_rate or 0),
        "image": doc.image,
        "tax_template": doc.item_tax_template if hasattr(doc, "item_tax_template") else None,
        "customer": customer,
    }


@frappe.whitelist(methods=["GET"])
def stock_balance(warehouse: str, limit: int = 500) -> list[dict]:
    if not warehouse:
        frappe.throw(_("Warehouse required"))
    rows = frappe.db.sql(
        """
        SELECT b.item_code, i.item_name, i.stock_uom, b.actual_qty
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE b.warehouse = %s AND i.disabled = 0
        ORDER BY i.item_name ASC
        LIMIT %s
        """,
        (warehouse, int(limit)),
        as_dict=True,
    )
    for r in rows:
        r["actual_qty"] = float(r.get("actual_qty") or 0)
    return rows
