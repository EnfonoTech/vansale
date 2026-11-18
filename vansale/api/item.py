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


def warehouse_stock(warehouse: str, item_codes: list[str] | None = None) -> dict[str, dict]:
    """item_code → {"qty", "value"} in `warehouse`, from Vansale Settings
    "Stock figures from":

      * Bin: ERPNext's running totals (fast; what the Item page shows).
      * Stock Ledger: the movements added up to now — what the Stock Balance
        report and ERPNext's submit check use. Bin can drift from it (a
        stock repost that failed or is stuck), so the app showed stock the
        invoice then could not submit.

    The ledger is read per item through its (item_code, warehouse, …) index;
    the van's items come from its Bin rows (one per item ever moved there),
    so a large ledger is never scanned by warehouse."""
    from vansale.vansale.doctype.vansale_settings.vansale_settings import global_flags

    bin_filters: dict = {"warehouse": warehouse}
    if item_codes is not None:
        if not item_codes:
            return {}
        bin_filters["item_code"] = ["in", list(item_codes)]
    bins = frappe.get_all(
        "Bin", filters=bin_filters, fields=["item_code", "actual_qty", "stock_value"], limit_page_length=0
    )
    if global_flags().get("stock_source") != "Stock Ledger":
        return {b.item_code: {"qty": flt(b.actual_qty), "value": flt(b.stock_value)} for b in bins}
    codes = list(item_codes) if item_codes is not None else [b.item_code for b in bins]
    if not codes:
        return {}
    out = {c: {"qty": 0.0, "value": 0.0} for c in codes}
    for r in frappe.db.sql(
        """SELECT item_code, SUM(actual_qty) AS qty, SUM(stock_value_difference) AS value
           FROM `tabStock Ledger Entry`
           WHERE item_code IN %(codes)s AND warehouse = %(wh)s AND is_cancelled = 0
             AND posting_datetime <= %(now)s
           GROUP BY item_code""",
        {"codes": tuple(codes), "wh": warehouse, "now": frappe.utils.now_datetime()},
        as_dict=True,
    ):
        out[r.item_code] = {"qty": flt(r.qty), "value": flt(r.value)}
    return out


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
        allowed = {code for code, st in warehouse_stock(warehouse).items() if st["qty"] > 0}
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
        balances = warehouse_stock(warehouse, codes)
        for r in rows:
            r["stock_qty"] = balances.get(r["item_code"], {}).get("qty", 0.0)
        add_sales_units(rows)
    return rows


def sales_units(item_codes: list[str]) -> dict[str, tuple[str, float]]:
    """Item → (Sales UOM, conversion factor) where the item sells in a unit
    other than its stock unit, so stock can also be shown in that unit."""
    if not item_codes:
        return {}
    items = frappe.get_all(
        "Item", {"name": ["in", item_codes]}, ["name", "stock_uom", "sales_uom"], limit_page_length=0
    )
    wanted = {i.name: i.sales_uom for i in items if i.sales_uom and i.sales_uom != i.stock_uom}
    if not wanted:
        return {}
    out = {}
    for r in frappe.get_all(
        "UOM Conversion Detail",
        {"parent": ["in", list(wanted)], "parenttype": "Item"},
        ["parent", "uom", "conversion_factor"],
    ):
        if wanted.get(r.parent) == r.uom and flt(r.conversion_factor) > 0:
            out[r.parent] = (r.uom, flt(r.conversion_factor))
    return out


def add_sales_units(rows: list[dict]) -> None:
    """Annotate stock rows with `sales_uom` / `sales_cf` (see `sales_units`)."""
    units = sales_units([r["item_code"] for r in rows])
    for r in rows:
        uom, cf = units.get(r["item_code"], (None, None))
        r["sales_uom"], r["sales_cf"] = uom, cf


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
    _add_min_rates(item_code, uoms, price_list)

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
    row = {"uom": uom, "conversion_factor": conv}
    _add_min_rates(item_code, [row], price_list)
    return {
        "item_code": item_code,
        "uom": uom,
        "price_list": price_list,
        "price_list_rate": flt(rate),
        "customer_specific": is_customer,
        "min_rate": row.get("min_rate"),
    }


def _add_min_rates(item_code: str, uoms: list[dict], price_list: Optional[str]) -> None:
    """The lowest rate the site accepts per UOM (`min_rate`), where it has such
    a rule (Steel Force: sf_trading's minimum selling price). Unset elsewhere."""
    from vansale import steelforce
    from vansale.api.me import van_default

    if not steelforce.is_active():
        return
    warehouse, branch = van_default("Warehouse"), van_default("Branch")
    for row in uoms:
        floor = steelforce.min_rate(item_code, row.get("conversion_factor") or 1, price_list, warehouse, branch)
        if floor:
            row["min_rate"] = floor


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
    stock = warehouse_stock(warehouse, [r["item_code"] for r in rows])
    for r in rows:
        r["actual_qty"] = stock.get(r["item_code"], {}).get("qty", 0.0)
    add_sales_units(rows)
    return rows


# ─── Selling help on a line: last price, stock (the desk's Last Selling Rate
#     and Stock Availability, for the salesman) ─────────────────────────────


def _codes(item_codes) -> list[str]:
    if not item_codes:
        return []
    if isinstance(item_codes, str):
        item_codes = frappe.parse_json(item_codes)
    return [str(c) for c in item_codes if c][:200]


def _sale_scope() -> tuple[list[str], dict, Optional[str]]:
    """The invoices a salesman may learn prices from: submitted sales (no
    returns) of the user's company, within the companies / cost centres their
    User Permissions allow. On Steel Force, as the desk's Last Selling Rate:
    the salesman's branch (cost centre) only. Third value: that cost centre,
    or None for the whole company."""
    from vansale import steelforce
    from vansale.api.invoice import _user_company

    where = ["si.docstatus = 1", "si.is_return = 0", "si.company = %(company)s"]
    params: dict = {"company": _user_company()}
    sf = steelforce.sale_history_conditions()
    extra = (*_permitted_sale_conditions(), None) if sf is None else sf
    where.extend(extra[0])
    params.update(extra[1])
    return where, params, extra[2]


def _permitted_sale_conditions() -> tuple[list[str], dict]:
    from frappe.core.doctype.user_permission.user_permission import get_permitted_documents

    where: list[str] = []
    params: dict = {}
    companies = get_permitted_documents("Company")
    if companies:
        where.append("si.company IN %(permitted_companies)s")
        params["permitted_companies"] = tuple(companies)
    cost_centers = get_permitted_documents("Cost Center")
    if cost_centers:
        where.append(
            "(sii.cost_center IN %(permitted_cost_centers)s "
            "OR (IFNULL(sii.cost_center, '') = '' AND si.cost_center IN %(permitted_cost_centers)s))"
        )
        params["permitted_cost_centers"] = tuple(cost_centers)
    return where, params


_SALE_COLUMNS = """sii.item_code, sii.rate, sii.uom, sii.qty, sii.conversion_factor,
    si.posting_date, si.name AS invoice, si.customer, si.customer_name"""


def _sale_row(r) -> dict:
    return {
        "rate": flt(r.rate),
        "uom": r.uom,
        "qty": flt(r.qty),
        "conversion_factor": flt(r.conversion_factor) or 1.0,
        "posting_date": str(r.posting_date),
        "invoice": r.invoice,
        "customer": r.customer,
        "customer_name": r.customer_name or r.customer,
    }


@frappe.whitelist(methods=["GET"])
def last_sales(customer: str, item_codes=None) -> dict:
    """Item → the last sale of it to this customer (rate, unit, qty, date)."""
    codes = _codes(item_codes)
    if not customer or not codes:
        return {}
    check_read("Customer", customer)
    where, params, _scope = _sale_scope()
    where += ["si.customer = %(customer)s", "sii.item_code IN %(codes)s"]
    params.update(customer=customer, codes=tuple(codes))
    rows = frappe.db.sql(
        f"""SELECT * FROM (
              SELECT {_SALE_COLUMNS},
                ROW_NUMBER() OVER (PARTITION BY sii.item_code
                  ORDER BY si.posting_date DESC, si.posting_time DESC, si.name DESC, sii.idx ASC) AS rn
              FROM `tabSales Invoice Item` sii
              JOIN `tabSales Invoice` si ON si.name = sii.parent
              WHERE {" AND ".join(where)}
            ) t WHERE t.rn = 1""",
        params,
        as_dict=True,
    )
    return {r.item_code: _sale_row(r) for r in rows}


@frappe.whitelist(methods=["GET"])
def stock_levels(item_codes=None, warehouse: Optional[str] = None) -> dict:
    """Item → stock in the salesman's warehouse (stock unit), and whether the
    item keeps stock at all — for the "only N in stock" warning on a line."""
    from vansale.api.invoice import _get_default_warehouse, _user_company

    codes = _codes(item_codes)
    wh = warehouse or _get_default_warehouse(_user_company())
    if not codes or not wh:
        return {}
    balances = warehouse_stock(wh, codes)
    stocked = set(frappe.get_all("Item", {"name": ["in", codes], "is_stock_item": 1}, pluck="name"))
    return {
        c: {"qty": balances.get(c, {}).get("qty", 0.0), "is_stock_item": int(c in stocked)}
        for c in codes
    }


@frappe.whitelist(methods=["GET"])
def insight(item_code: str, customer: Optional[str] = None) -> dict:
    """One item, on tap: its last sales to this customer, its recent sales to
    anyone (a year back), and its stock in every warehouse of the company."""
    if not item_code:
        frappe.throw(_("Item required"))
    check_item_allowed(item_code)
    if customer:
        check_read("Customer", customer)
    where, params, scope = _sale_scope()
    params["item"] = item_code
    order = "ORDER BY si.posting_date DESC, si.posting_time DESC, si.name DESC LIMIT %(n)s"

    def sales(extra: list[str], extra_params: dict, n: int) -> list[dict]:
        rows = frappe.db.sql(
            f"""SELECT {_SALE_COLUMNS}
                FROM `tabSales Invoice Item` sii
                JOIN `tabSales Invoice` si ON si.name = sii.parent
                WHERE {" AND ".join(where + ["sii.item_code = %(item)s"] + extra)} {order}""",
            {**params, **extra_params, "n": n},
            as_dict=True,
        )
        return [_sale_row(r) for r in rows]

    to_customer = sales(["si.customer = %(customer)s"], {"customer": customer}, 5) if customer else []
    others = ["si.posting_date >= %(since)s"] + (["si.customer != %(customer)s"] if customer else [])
    recent = sales(others, {"since": frappe.utils.add_days(nowdate(), -365), "customer": customer}, 6)

    item = frappe.db.get_value("Item", item_code, ["stock_uom", "is_stock_item"], as_dict=True) or {}
    unit = sales_units([item_code]).get(item_code)
    return {
        "item_code": item_code,
        "stock_uom": item.get("stock_uom"),
        "sales_uom": unit[0] if unit else None,
        "sales_cf": unit[1] if unit else None,
        "is_stock_item": cint(item.get("is_stock_item")),
        # Sales shown are this cost centre's (the branch) only; None = the whole company.
        "sales_scope": scope,
        "to_customer": to_customer,
        "recent": recent,
        "warehouses": _stock_by_warehouse(item_code) if cint(item.get("is_stock_item")) else [],
    }


def _stock_by_warehouse(item_code: str) -> list[dict]:
    """Stock in each warehouse of the company holding some, the salesman's own
    first (always listed). Steel Force: sf_trading's Stock Availability."""
    from vansale import steelforce
    from vansale.api.invoice import _get_default_warehouse, _user_company

    company = _user_company()
    own = _get_default_warehouse(company)
    rows = steelforce.warehouse_stock(item_code, company, own)
    if rows is None:
        rows = [
            {"warehouse": r.warehouse, "warehouse_name": r.warehouse_name, "qty": flt(r.actual_qty)}
            for r in frappe.db.sql(
                """SELECT b.warehouse, w.warehouse_name, b.actual_qty
                   FROM `tabBin` b JOIN `tabWarehouse` w ON w.name = b.warehouse
                   WHERE b.item_code = %(item)s AND w.company = %(company)s
                     AND w.is_group = 0 AND w.disabled = 0
                     AND (b.actual_qty > 0 OR b.warehouse = %(own)s)""",
                {"item": item_code, "company": company, "own": own or ""},
                as_dict=True,
            )
        ]
    if own:
        # The salesman's own figure as the catalog shows it ("Stock figures from").
        own_qty = warehouse_stock(own, [item_code]).get(item_code, {}).get("qty", 0.0)
        rows = [r for r in rows if r["warehouse"] != own]
        rows.insert(0, {
            "warehouse": own,
            "warehouse_name": frappe.db.get_value("Warehouse", own, "warehouse_name") or own,
            "qty": own_qty,
        })
    for r in rows:
        r["own"] = r["warehouse"] == own
    rest = sorted(rows[1:] if own else rows, key=lambda r: -r["qty"])
    return (rows[:1] if own else []) + rest[:15]
