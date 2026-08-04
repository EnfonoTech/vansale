"""Van Stock Position — what is on board each van right now.

Attribution here is by **warehouse**, not by owner: stock belongs to the van's
warehouse regardless of who moved it, and `Vansale Configuration Warehouse`
maps warehouse → van. That makes this the one report that stays correct when
the office loads a van on the driver's behalf.

`Bin` is the live balance, so this is a "now" snapshot with no date filter —
for a historical view use the standard Stock Balance report against the van
warehouse.

Items with a zero balance are hidden by default; a van's item list would
otherwise be the whole catalogue. `Include Zero Balance` shows them, which is
how you spot an item that has sold out mid-route.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from vansale.vansale.report.vansale_report_utils import is_manager, user_van


def execute(filters=None):
    filters = frappe._dict(filters or {})

    where = ""
    values: dict = {}

    # A driver sees only their own van, whatever the filter panel says.
    if not is_manager():
        own = user_van()
        if not own:
            return _columns(), []
        where += " AND vcw.parent = %(own_van)s"
        values["own_van"] = own
    elif filters.get("van"):
        where += " AND vcw.parent = %(van)s"
        values["van"] = filters["van"]

    if filters.get("warehouse"):
        where += " AND b.warehouse = %(warehouse)s"
        values["warehouse"] = filters["warehouse"]

    if filters.get("item_group"):
        where += " AND i.item_group = %(item_group)s"
        values["item_group"] = filters["item_group"]

    if not cint(filters.get("include_zero_balance")):
        where += " AND b.actual_qty != 0"

    rows = frappe.db.sql(
        f"""
        SELECT
            vcw.parent          AS van,
            b.warehouse         AS warehouse,
            b.item_code         AS item_code,
            i.item_name         AS item_name,
            i.item_group        AS item_group,
            i.stock_uom         AS uom,
            b.actual_qty        AS actual_qty,
            b.reserved_qty      AS reserved_qty,
            b.valuation_rate    AS valuation_rate,
            b.stock_value       AS stock_value
        FROM `tabBin` b
        INNER JOIN `tabVansale Configuration Warehouse` vcw ON vcw.warehouse = b.warehouse
        INNER JOIN `tabItem` i ON i.name = b.item_code
        WHERE i.disabled = 0 {where}
        ORDER BY vcw.parent ASC, i.item_group ASC, b.item_code ASC
        """,
        values,
        as_dict=True,
    )

    for r in rows:
        # A stocked item with no valuation cannot be invoiced — ERPNext rejects
        # the COGS entry. Flagging it here is how the office finds the cause of
        # a driver's "Needs admin" sync error before the driver hits it.
        r["needs_valuation"] = 1 if flt(r.actual_qty) > 0 and not flt(r.valuation_rate) else 0

    return _columns(), rows


def _columns() -> list[dict]:
    return [
        {
            "fieldname": "van",
            "label": _("Van"),
            "fieldtype": "Link",
            "options": "Vansale Configuration",
            "width": 150,
        },
        {
            "fieldname": "warehouse",
            "label": _("Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 160,
        },
        {
            "fieldname": "item_code",
            "label": _("Item"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 150,
        },
        {"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 200},
        {
            "fieldname": "item_group",
            "label": _("Item Group"),
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 140,
        },
        {"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 70},
        {"fieldname": "actual_qty", "label": _("Qty"), "fieldtype": "Float", "width": 90},
        {
            "fieldname": "reserved_qty",
            "label": _("Reserved"),
            "fieldtype": "Float",
            "width": 90,
        },
        {
            "fieldname": "valuation_rate",
            "label": _("Valuation Rate"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "stock_value",
            "label": _("Stock Value"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "needs_valuation",
            "label": _("No Valuation"),
            "fieldtype": "Check",
            "width": 110,
        },
    ]
