"""Item endpoints for the invoice picker + stock view."""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from vansale.api.access import check_read
from vansale.api.me import customer_price_enabled, rate_precision


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


def permitted_item_groups() -> set[str] | None:
    """Item Groups the user may sell, from "Item Group" User Permissions
    (sub-groups included); None when the user has none (no restriction).

    Only Item Group is applied — Frappe's full Item permission check also
    applies e.g. a Warehouse permission to the Item Defaults table, which hid
    items from drivers whose van isn't an item's default warehouse.
    """
    from frappe.utils.nestedset import get_descendants_of

    perms = frappe.get_all(
        "User Permission",
        filters={"user": frappe.session.user, "allow": "Item Group"},
        fields=["for_value", "applicable_for", "apply_to_all_doctypes", "hide_descendants"],
    )
    perms = [p for p in perms if p.apply_to_all_doctypes or p.applicable_for in (None, "", "Item")]
    if not perms:
        return None
    groups: set[str] = set()
    for p in perms:
        groups.add(p.for_value)
        if not p.hide_descendants:
            groups.update(get_descendants_of("Item Group", p.for_value, ignore_permissions=True))
    return groups


def check_item_allowed(item_code: str) -> None:
    groups = permitted_item_groups()
    if groups is not None and frappe.db.get_value("Item", item_code, "item_group") not in groups:
        frappe.throw(_("You are not permitted to sell item {0}").format(item_code), frappe.PermissionError)


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
    filters: dict = {"disabled": 0, "has_variants": 0, "is_sales_item": 1}
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
                filters={"is_stock_item": 0, "disabled": 0, "has_variants": 0, "is_sales_item": 1},
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
    groups = permitted_item_groups()
    if groups is not None:
        if not groups:
            return []
        filters["item_group"] = ["in", list(groups)]
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


def _item_price(
    item_code: str, price_list: str, uom: str, stock_uom: str, customer: str = ""
) -> Optional[float]:
    """Latest Item Price valid today for (item, price list, uom, customer).

    ``customer=""`` matches only rows with no customer, so one customer's
    negotiated price never leaks into another customer's invoice. A row
    without a UOM counts as the stock UOM.
    """
    rows = frappe.db.sql(
        """
        SELECT price_list_rate FROM `tabItem Price`
        WHERE item_code = %(item_code)s
          AND price_list = %(price_list)s
          AND selling = 1
          AND IFNULL(NULLIF(uom, ''), %(stock_uom)s) = %(uom)s
          AND IFNULL(customer, '') = %(customer)s
          AND IFNULL(valid_from, '1900-01-01') <= %(today)s
          AND IFNULL(valid_upto, '2999-12-31') >= %(today)s
        ORDER BY valid_from DESC, modified DESC
        LIMIT 1
        """,
        {
            "item_code": item_code,
            "price_list": price_list,
            "uom": uom,
            "stock_uom": stock_uom,
            "customer": customer or "",
            "today": nowdate(),
        },
    )
    return flt(rows[0][0]) if rows else None


def _fetch_price(
    item_code: str,
    price_list: Optional[str],
    uom: str,
    stock_uom: str,
    conversion_factor: float,
    customer: Optional[str] = None,
) -> tuple[float, bool]:
    """Price for one UOM → (rate, is_customer_specific).

    Per price source: the row for this UOM, else the stock UOM row ×
    conversion factor (as ERPNext does). Never another UOM's rate unconverted.
    Customer-specific rows are only used when the van's setting allows it.
    No Item Price → 0, as in ERPNext; the driver types the rate.
    """
    if not price_list:
        return 0.0, False
    sources = [customer] if customer and customer_price_enabled() else []
    sources.append("")
    for source in sources:
        rate = _item_price(item_code, price_list, uom, stock_uom, source)
        if rate is None and uom != stock_uom:
            stock_rate = _item_price(item_code, price_list, stock_uom, stock_uom, source)
            if stock_rate is not None:
                rate = stock_rate * flt(conversion_factor or 1)
        if rate is not None:
            return flt(rate, rate_precision()), bool(source)
    return 0.0, False


def _item_uoms(doc) -> list[tuple[str, float]]:
    """(uom, conversion factor) pairs, the item's Sales UOM first."""
    uoms = [(u.uom, flt(u.conversion_factor) or 1.0) for u in (doc.uoms or []) if u.uom]
    if doc.stock_uom not in [u for u, _cf in uoms]:
        uoms.insert(0, (doc.stock_uom, 1.0))
    default_uom = doc.get("sales_uom") if doc.get("sales_uom") in [u for u, _cf in uoms] else doc.stock_uom
    uoms.sort(key=lambda u: u[0] != default_uom)
    return uoms


@frappe.whitelist(methods=["GET"])
def detail(item_code: str, customer: Optional[str] = None) -> dict:
    if not item_code:
        frappe.throw(_("Item code required"))
    doc = frappe.get_doc("Item", item_code)
    price_list = _customer_price_list(customer)

    uoms = []
    customer_specific = False
    stock_uom_rate = 0.0
    for uom, conv in _item_uoms(doc):
        rate, is_customer = _fetch_price(item_code, price_list, uom, doc.stock_uom, conv, customer)
        customer_specific = customer_specific or is_customer
        if uom == doc.stock_uom:
            stock_uom_rate = rate
        uoms.append({"uom": uom, "conversion_factor": conv, "price_list_rate": flt(rate)})

    return {
        "name": doc.name,
        "item_code": doc.item_code,
        "item_name": doc.item_name,
        "item_group": doc.item_group,
        "stock_uom": doc.stock_uom,
        "sales_uom": uoms[0]["uom"],
        "standard_rate": float(doc.standard_rate or 0),
        "price_list": price_list,
        "price_list_rate": flt(stock_uom_rate),
        "uoms": uoms,
        "customer_specific": customer_specific,
        "image": doc.image,
        "tax_template": doc.item_tax_template if hasattr(doc, "item_tax_template") else None,
        "customer": customer,
    }


@frappe.whitelist(methods=["GET"])
def price_for(item_code: str, customer: Optional[str] = None, uom: Optional[str] = None) -> dict:
    """Light-weight price lookup used when the user changes UOM on a line."""
    if not item_code:
        frappe.throw(_("Item code required"))
    doc = frappe.get_doc("Item", item_code)
    uom = uom or doc.stock_uom
    conv = dict(_item_uoms(doc)).get(uom, 1.0)
    price_list = _customer_price_list(customer)
    rate, is_customer = _fetch_price(item_code, price_list, uom, doc.stock_uom, conv, customer)
    return {
        "item_code": item_code,
        "uom": uom,
        "price_list": price_list,
        "price_list_rate": flt(rate),
        "customer_specific": is_customer,
    }


@frappe.whitelist(methods=["GET"])
def stock_balance(warehouse: str, limit: int = 500) -> list[dict]:
    if not warehouse:
        frappe.throw(_("Warehouse required"))
    check_read("Warehouse", warehouse)
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
