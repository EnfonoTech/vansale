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
    """Search items by code / name / barcode.

    v15 Item has no top-level `barcode` column — barcodes live in the
    `Item Barcode` child table. Prior build used `or_filters={'barcode': ...}`
    which silently returned 0 rows and broke the catalog search.
    """
    filters: dict = {"disabled": 0, "has_variants": 0}
    or_filters = None
    if search:
        s = f"%{search}%"
        or_filters = {"item_name": ["like", s], "item_code": ["like", s]}
        # Barcode match → parent item_code.
        barcode_parents = [
            b.parent
            for b in frappe.get_all(
                "Item Barcode",
                filters={"barcode": ["like", s]},
                fields=["parent"],
                limit=int(limit),
            )
        ]
        if barcode_parents:
            or_filters["name"] = ["in", barcode_parents]
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


def _customer_price_list(customer: Optional[str]) -> Optional[str]:
    """Resolve the effective selling Price List for a customer.

    Priority: Customer.default_price_list → Customer Group.default_price_list →
    Selling Settings.selling_price_list.
    """
    if customer:
        cust_pl = frappe.db.get_value("Customer", customer, "default_price_list")
        if cust_pl:
            return cust_pl
        cg = frappe.db.get_value("Customer", customer, "customer_group")
        if cg:
            cg_pl = frappe.db.get_value("Customer Group", cg, "default_price_list")
            if cg_pl:
                return cg_pl
    return frappe.db.get_single_value("Selling Settings", "selling_price_list")


def _fetch_price(item_code: str, price_list: Optional[str], uom: Optional[str]) -> float:
    """Fetch Item Price for the (item_code, price_list, uom) triple with UOM fallback."""
    filters: dict = {"item_code": item_code, "selling": 1}
    if price_list:
        filters["price_list"] = price_list
    if uom:
        price = frappe.db.get_value(
            "Item Price",
            {**filters, "uom": uom},
            "price_list_rate",
            order_by="valid_from desc",
        )
        if price:
            return float(price)
    # Fallback — any UOM for this price list
    price = frappe.db.get_value(
        "Item Price", filters, "price_list_rate", order_by="valid_from desc",
    )
    return float(price or 0)


@frappe.whitelist(methods=["GET"])
def detail(item_code: str, customer: Optional[str] = None) -> dict:
    if not item_code:
        frappe.throw(_("Item code required"))
    doc = frappe.get_doc("Item", item_code)
    price_list = _customer_price_list(customer)
    stock_uom_rate = _fetch_price(item_code, price_list, doc.stock_uom)

    uoms = []
    for u in (doc.uoms or []):
        conv = float(u.conversion_factor or 1)
        rate = _fetch_price(item_code, price_list, u.uom) or (stock_uom_rate * conv)
        uoms.append({
            "uom": u.uom,
            "conversion_factor": conv,
            "price_list_rate": float(rate or 0),
        })
    if not uoms:
        uoms.append({
            "uom": doc.stock_uom,
            "conversion_factor": 1.0,
            "price_list_rate": float(stock_uom_rate or doc.standard_rate or 0),
        })

    return {
        "name": doc.name,
        "item_code": doc.item_code,
        "item_name": doc.item_name,
        "item_group": doc.item_group,
        "stock_uom": doc.stock_uom,
        "standard_rate": float(doc.standard_rate or 0),
        "price_list": price_list,
        "price_list_rate": float(stock_uom_rate or doc.standard_rate or 0),
        "uoms": uoms,
        "image": doc.image,
        "tax_template": doc.item_tax_template if hasattr(doc, "item_tax_template") else None,
        "customer": customer,
    }


@frappe.whitelist(methods=["GET"])
def price_for(item_code: str, customer: Optional[str] = None, uom: Optional[str] = None) -> dict:
    """Light-weight price lookup used when the user changes UOM on a line."""
    if not item_code:
        frappe.throw(_("Item code required"))
    price_list = _customer_price_list(customer)
    rate = _fetch_price(item_code, price_list, uom)
    if not rate:
        std = float(frappe.db.get_value("Item", item_code, "standard_rate") or 0)
        rate = std
    return {
        "item_code": item_code,
        "uom": uom,
        "price_list": price_list,
        "price_list_rate": float(rate or 0),
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
