"""Item endpoints for the invoice picker + stock view."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import cint


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
def list_mine(
    limit: int = 100,
    search: Optional[str] = None,
    warehouse: Optional[str] = None,
    only_in_stock: int = 0,
) -> list[dict]:
    """Search items by code / name / barcode.

    v15 Item has no top-level `barcode` column — barcodes live in the
    `Item Barcode` child table. Prior build used `or_filters={'barcode': ...}`
    which silently returned 0 rows and broke the catalog search.

    ``only_in_stock`` restricts results to items with a positive Bin
    balance in ``warehouse``. A van can only sell what it carries, and an
    item with no incoming stock transaction also has no valuation rate —
    ERPNext then rejects the invoice at submit time with "Valuation Rate
    for the Item ... is required to do accounting entries", which for an
    offline-queued invoice surfaces days later as an unfixable sync error.
    Filtering the picker is the only place that failure can be prevented.

    The Bin restriction is applied as a *filter*, not a post-fetch
    annotation: annotating after the `limit` means a stocked item outside
    the first N rows of `modified desc` never appears in the results.
    """
    filters: dict = {"disabled": 0, "has_variants": 0}
    if warehouse and cint(only_in_stock):
        allowed = set(
            frappe.get_all(
                "Bin",
                filters={"warehouse": warehouse, "actual_qty": [">", 0]},
                pluck="item_code",
                limit_page_length=0,
            )
        )
        # Non-stock items (delivery charge, service lines) have no Bin row
        # and no valuation requirement — excluding them would hide
        # legitimate sellables. Union them in rather than adding a second
        # or_filters group, which `get_all` cannot express alongside the
        # search group below.
        allowed.update(
            frappe.get_all(
                "Item",
                filters={"is_stock_item": 0, "disabled": 0, "has_variants": 0},
                pluck="name",
                limit_page_length=0,
            )
        )
        if not allowed:
            return []
        filters["name"] = ["in", list(allowed)]
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

    Priority (first hit wins):
      1. ``Customer.default_price_list`` — customer-specific override.
      2. ``Vansale Configuration.selling_price_list`` — van-level default
         set by the Van Manager (e.g. different route pricing tiers).
      3. ``Customer Group.default_price_list``.
      4. ``Selling Settings.selling_price_list`` — site-wide fallback.

    The van PL sits ABOVE Customer Group so a route operating on a
    discounted tier doesn't get the group's sticker price when it hits
    an unclassified customer.
    """
    from vansale.api.me import current_user_van_price_list

    if customer:
        cust_pl = frappe.db.get_value("Customer", customer, "default_price_list")
        if cust_pl:
            return cust_pl

    van_pl = current_user_van_price_list()
    if van_pl:
        return van_pl

    if customer:
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
