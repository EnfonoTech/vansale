# apps/vansale/vansale/sf_trading/report/reorder_recommendation/reorder_recommendation.py
"""Reorder Recommendation - what each item's reorder level and quantity should be, read from
what actually sold and what was actually purchased between two dates.

Nothing on this site has a reorder level set: `Item Reorder` is empty, and lead_time_days,
safety_stock and min_order_qty are zero on every item. So this report does not check work
against a configured plan - it proposes the plan, per item and per warehouse, from the
transactions themselves.

    Demand           = quantity that left the warehouse to a customer (Sales Invoice, Delivery
                       Note) net of returns, plus Material Issue consumption if that box is
                       ticked
    Average Daily    = demand / every day in the window, not only the days it moved
    Variability      = standard deviation of the daily demand, counting quiet days as zero
    Lead Time        = days from Purchase Order to Purchase Receipt for that item where the
                       history shows it, otherwise the item's own lead time, otherwise the
                       Default Lead Time filter
    Safety Stock     = Z x Variability x sqrt(Lead Time)      Z comes from the Service Level
    Reorder Level    = Average Daily x Lead Time + Safety Stock
    Order Up To      = Reorder Level + Average Daily x Coverage Days
    Reorder Qty      = Order Up To - Projected Qty, never below zero

Transfers between the company's own warehouses are left out of both sides. On this site they
move more quantity than sales do - 274,782 units out and the same 274,782 back in over ninety
days - so counting them would make every branch look like it were selling several times what it
sells, and would order stock that is already in the building.

Projected Qty, not Actual Qty, drives the recommendation: stock already on a purchase order is
coming, and stock already reserved against a sales order is spoken for. Ordering against actual
qty orders twice whatever is in transit.
"""

import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

# Z-multiplier per service level: how much cover to hold for demand that arrives faster than
# average. 95% means being short in roughly one replenishment cycle in twenty.
SERVICE_LEVEL_Z = {
    "85%": 1.04,
    "90%": 1.28,
    "95%": 1.65,
    "99%": 2.33,
}

# A window shorter than this cannot say anything useful about a daily average.
MIN_WINDOW_DAYS = 7

ROW_CAP = 5000

# Every by-name lookup is fetched in slices of this size. A single `IN` list of several thousand
# item codes is enough to make the query parser give up with "Maximum number of tokens exceeded",
# which is a failure that only shows up on the widest selections - exactly the ones management
# asks for.
LOOKUP_BATCH = 500

# Days of cover, as a multiple of lead time plus coverage, past which stock counts as excess.
OVERSTOCK_MULTIPLE = 2

ACTION_ORDER = {
    "Out of Stock": 0,
    "Order Now": 1,
    "Below Level": 2,
    "Watch": 3,
    "OK": 4,
    "Overstocked": 5,
    "Dead Stock": 6,
    "No Demand": 7,
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    company = filters.company or frappe.defaults.get_user_default("Company")
    if not company:
        frappe.throw(_("Please choose a company."))

    to_date = getdate(filters.to_date or nowdate())
    from_date = getdate(filters.from_date or add_days(to_date, -90))
    if from_date > to_date:
        frappe.throw(_("From Date is after To Date."))

    days = (to_date - from_date).days + 1
    if days < MIN_WINDOW_DAYS:
        frappe.throw(
            _("Choose a window of at least %s days. Anything shorter cannot give a daily "
              "average worth ordering against.") % MIN_WINDOW_DAYS
        )

    warehouses = _warehouses(company, filters.get("warehouse"))
    if not warehouses:
        frappe.msgprint(_("No stock warehouses found for %s.") % company)
        return _columns(company), []

    scope = _item_scope(filters)

    movement = _movement(company, warehouses, scope, from_date, to_date)
    demand = _daily_demand(company, warehouses, scope, from_date, to_date, filters)
    bins = _bins(warehouses, scope)

    pairs = set(movement) | set(demand)
    if cint(filters.get("include_no_demand")):
        pairs |= set(bins)
    if not pairs:
        frappe.msgprint(_("Nothing moved in this window for the selection made."))
        return _columns(company), []

    codes = {code for code, _wh in pairs}
    meta = _item_meta(codes)
    lead_times = _observed_lead_times(company, codes)
    configured = _configured_reorder(codes)

    default_lead = cint(filters.get("lead_time_days")) or 7
    coverage = cint(filters.get("coverage_days")) or 30
    z = SERVICE_LEVEL_Z.get(filters.get("service_level") or "95%", 1.65)
    min_demand = flt(filters.get("min_demand_qty"))
    only_action = cint(filters.get("only_action_needed"))

    data = []
    for key in pairs:
        row = _build_row(
            key, meta, movement, demand, bins, configured, lead_times, scope,
            days=days, default_lead=default_lead, coverage=coverage, z=z,
        )
        if not row:
            continue
        if min_demand and flt(row["demand_qty"]) < min_demand and row["action"] != "Dead Stock":
            continue
        if only_action and row["action"] not in ("Out of Stock", "Order Now", "Below Level"):
            continue
        data.append(row)

    data.sort(key=lambda r: (
        ACTION_ORDER.get(r["action"], 9), -flt(r["reorder_value"]), r["item_code"]
    ))

    # The figures at the top describe the whole selection, and are taken before the table is
    # capped. A capped table that quietly also capped its own totals would read as the truth.
    summary = _summary(data)

    truncated = len(data) - ROW_CAP
    if truncated > 0:
        data = data[:ROW_CAP]

    return (
        _columns(company),
        data,
        _message(filters, days, default_lead, coverage, z, truncated),
        _chart(data),
        summary,
    )


# ── scope ─────────────────────────────────────────────────────────────────────

def _warehouses(company, warehouse=None):
    """Leaf warehouses in scope. A group warehouse stands for everything beneath it, so picking
    a branch gives that branch's stores without naming each one."""
    if warehouse:
        row = frappe.db.get_value(
            "Warehouse", warehouse, ["name", "company", "is_group", "lft", "rgt"], as_dict=True
        )
        if not row or row.company != company:
            frappe.throw(_("%(wh)s is not a warehouse of %(company)s.")
                         % {"wh": warehouse, "company": company})
        if not cint(row.is_group):
            return [row.name]
        return frappe.get_all(
            "Warehouse",
            filters={"company": company, "is_group": 0,
                     "lft": [">", row.lft], "rgt": ["<", row.rgt]},
            pluck="name",
        )
    return frappe.get_all(
        "Warehouse", filters={"company": company, "is_group": 0, "disabled": 0}, pluck="name"
    )


def _item_scope(filters):
    """Which items are in scope, expressed as an item code and/or a list of item groups.

    Deliberately *not* expanded into a list of item codes. An item group here holds thousands of
    items, and a `WHERE item_code IN (...)` of that length is long enough that the query parser
    gives up on it - "Maximum number of tokens exceeded". A group is a handful of names, so the
    scope travels as groups and the database resolves the membership through `tabItem`.
    """
    scope = frappe._dict(item_code=filters.get("item_code") or None, groups=None)

    if filters.get("item_group"):
        group = frappe.db.get_value(
            "Item Group", filters.get("item_group"), ["name", "is_group", "lft", "rgt"],
            as_dict=True,
        )
        if not group:
            frappe.throw(_("%s is not an item group.") % filters.get("item_group"))
        if cint(group.is_group):
            scope.groups = frappe.get_all(
                "Item Group", filters={"lft": [">=", group.lft], "rgt": ["<=", group.rgt]},
                pluck="name",
            )
        else:
            scope.groups = [group.name]

    return scope


# ── what moved ────────────────────────────────────────────────────────────────

# Stock Entry rows have to be read with their purpose, because one voucher type is a transfer, an
# issue or a receipt depending on it.
STOCK_ENTRY_JOIN = (" LEFT JOIN `tabStock Entry` se"
                    "   ON se.name = sle.voucher_no AND sle.voucher_type = 'Stock Entry'")

# Joining the item lets the item group and the stock/disabled tests happen in the database, so
# rows nobody can order are dropped before they are ever summed.
ITEM_JOIN = " INNER JOIN `tabItem` it ON it.name = sle.item_code"


def _item_clause(scope):
    """Fixed SQL fragments chosen here; the item code and group names travel as parameters."""
    clause = " AND it.is_stock_item = 1 AND it.disabled = 0"
    if scope.item_code:
        clause += " AND sle.item_code = %(item_code)s"
    if scope.groups:
        clause += " AND it.item_group IN %(groups)s"
    return clause


def _demand_clause(filters):
    """The voucher types that count as demand. Every fragment here is a fixed string chosen in
    this file; user input travels as a bound parameter only."""
    parts = ["sle.voucher_type IN ('Sales Invoice', 'Delivery Note')"]
    if cint(filters.get("include_material_issue")):
        parts.append("(sle.voucher_type = 'Stock Entry' AND se.purpose = 'Material Issue')")
    return " AND (" + " OR ".join(parts) + ")"


def _scope_params(company, warehouses, scope, from_date, to_date):
    params = {
        "company": company,
        "warehouses": tuple(warehouses),
        "from_date": from_date,
        "to_date": to_date,
    }
    if scope.item_code:
        params["item_code"] = scope.item_code
    if scope.groups:
        params["groups"] = tuple(scope.groups)
    return params


def _movement(company, warehouses, scope, from_date, to_date):
    """Totals per item and warehouse: sold, consumed, purchased, otherwise received.

    Quantities are summed signed rather than filtered by sign, so a credit note reduces the
    demand it reversed instead of counting as a receipt.
    """
    params = _scope_params(company, warehouses, scope, from_date, to_date)

    rows = frappe.db.sql(
        "SELECT sle.item_code, sle.warehouse,"
        "  ROUND(SUM(CASE WHEN sle.voucher_type IN ('Sales Invoice', 'Delivery Note')"
        "                 THEN -sle.actual_qty ELSE 0 END), 3) AS sold_qty,"
        "  ROUND(SUM(CASE WHEN sle.voucher_type = 'Stock Entry'"
        "                  AND se.purpose = 'Material Issue'"
        "                 THEN -sle.actual_qty ELSE 0 END), 3) AS issued_qty,"
        "  ROUND(SUM(CASE WHEN sle.voucher_type IN ('Purchase Receipt', 'Purchase Invoice')"
        "                 THEN sle.actual_qty ELSE 0 END), 3) AS purchased_qty,"
        "  ROUND(SUM(CASE WHEN sle.voucher_type = 'Stock Entry'"
        "                  AND se.purpose = 'Material Receipt'"
        "                 THEN sle.actual_qty ELSE 0 END), 3) AS received_qty,"
        "  MAX(sle.posting_date) AS last_movement"
        " FROM `tabStock Ledger Entry` sle"
        + ITEM_JOIN + STOCK_ENTRY_JOIN +
        " WHERE sle.is_cancelled = 0 AND sle.company = %(company)s"
        "   AND sle.warehouse IN %(warehouses)s"
        "   AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s"
        # Material Transfer is deliberately in none of the buckets above: it is the company
        # moving its own stock, and belongs to neither demand nor supply.
        + _item_clause(scope) +
        " GROUP BY sle.item_code, sle.warehouse",
        params,
        as_dict=True,
    )
    return {(r.item_code, r.warehouse): r for r in rows}


def _daily_demand(company, warehouses, scope, from_date, to_date, filters):
    """The shape of daily demand per item and warehouse.

    The inner query totals each day that moved; the outer one keeps the sum and the sum of
    squares. Those two are all the variance needs, and they let the quiet days count as zero in
    Python without asking the database for a row per calendar day.
    """
    params = _scope_params(company, warehouses, scope, from_date, to_date)

    rows = frappe.db.sql(
        "SELECT d.item_code, d.warehouse,"
        "  SUM(d.qty) AS sum_qty, SUM(d.qty * d.qty) AS sum_sq,"
        "  COUNT(*) AS active_days, MAX(d.qty) AS peak_day"
        " FROM ("
        "   SELECT sle.item_code, sle.warehouse, sle.posting_date,"
        "          SUM(-sle.actual_qty) AS qty"
        "   FROM `tabStock Ledger Entry` sle"
        + ITEM_JOIN + STOCK_ENTRY_JOIN +
        "   WHERE sle.is_cancelled = 0 AND sle.company = %(company)s"
        "     AND sle.warehouse IN %(warehouses)s"
        "     AND sle.posting_date BETWEEN %(from_date)s AND %(to_date)s"
        + _demand_clause(filters) + _item_clause(scope) +
        "   GROUP BY sle.item_code, sle.warehouse, sle.posting_date"
        " ) d"
        " GROUP BY d.item_code, d.warehouse",
        params,
        as_dict=True,
    )
    return {(r.item_code, r.warehouse): r for r in rows}


def _bins(warehouses, scope):
    conditions = {"warehouse": ["in", warehouses]}
    if scope.item_code:
        conditions["item_code"] = scope.item_code
    # A Bin carries no item group, so a group selection is applied per row once the item is
    # known, in _build_row.
    rows = frappe.get_all(
        "Bin",
        filters=conditions,
        fields=["item_code", "warehouse", "actual_qty", "projected_qty", "ordered_qty",
                "indented_qty", "reserved_qty", "valuation_rate"],
    )
    return {(r.item_code, r.warehouse): r for r in rows}


# ── item side ─────────────────────────────────────────────────────────────────

def _batches(codes):
    codes = list(codes)
    for start in range(0, len(codes), LOOKUP_BATCH):
        yield codes[start:start + LOOKUP_BATCH]


def _item_meta(codes):
    if not codes:
        return {}
    whole = set(frappe.get_all("UOM", filters={"must_be_whole_number": 1}, pluck="name"))
    out = {}
    for batch in _batches(codes):
        rows = frappe.get_all(
            "Item",
            filters={"name": ["in", batch]},
            fields=["name", "item_name", "item_group", "stock_uom", "lead_time_days",
                    "safety_stock", "min_order_qty", "last_purchase_rate", "disabled",
                    "is_stock_item"],
        )
        for r in rows:
            r["whole_number"] = r.stock_uom in whole
            out[r.name] = r
    return out


def _observed_lead_times(company, codes):
    """Days from ordering an item to receiving it, per item, from the receipts that name their
    purchase order. Only a minority of receipts on this site do, so this is a bonus where the
    history has it rather than the main source."""
    if not codes:
        return {}
    out = {}
    for batch in _batches(codes):
        rows = frappe.db.sql(
            "SELECT pri.item_code,"
            "  ROUND(AVG(DATEDIFF(pr.posting_date, po.transaction_date)), 1) AS lead_days,"
            "  COUNT(*) AS receipts"
            " FROM `tabPurchase Receipt Item` pri"
            " INNER JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent"
            " INNER JOIN `tabPurchase Order` po ON po.name = pri.purchase_order"
            " WHERE pr.docstatus = 1 AND pr.company = %(company)s"
            "   AND pri.item_code IN %(items)s"
            # A receipt dated before its order, or half a year after it, is a data entry
            # accident and would poison the average.
            "   AND DATEDIFF(pr.posting_date, po.transaction_date) BETWEEN 0 AND 180"
            " GROUP BY pri.item_code",
            {"company": company, "items": tuple(batch)},
            as_dict=True,
        )
        for r in rows:
            out[r.item_code] = r
    return out


def _configured_reorder(codes):
    """Whatever reorder rows already exist, so a recommendation can be read against the current
    setting instead of quietly replacing it."""
    if not codes:
        return {}
    out = {}
    for batch in _batches(codes):
        rows = frappe.get_all(
            "Item Reorder",
            filters={"parent": ["in", batch]},
            fields=["parent", "warehouse", "warehouse_reorder_level", "warehouse_reorder_qty"],
        )
        for r in rows:
            out[(r.parent, r.warehouse)] = r
    return out


# ── the recommendation ────────────────────────────────────────────────────────

def _build_row(key, meta, movement, demand, bins, configured, lead_times, scope,
               days, default_lead, coverage, z):
    code, warehouse = key
    item = meta.get(code)
    if not item or not cint(item.is_stock_item) or cint(item.disabled):
        return None
    # Pairs that came in from Bin were never filtered by group, so check it here.
    if scope.groups and item.item_group not in scope.groups:
        return None

    move = movement.get(key) or frappe._dict()
    dem = demand.get(key) or frappe._dict()
    bin_row = bins.get(key) or frappe._dict()
    conf = configured.get(key) or frappe._dict()

    demand_qty = flt(dem.sum_qty)
    avg_daily = flt(demand_qty / days, 4) if demand_qty > 0 else 0.0

    # Variance over every day in the window, not only the days that moved. A quiet day is a day
    # of zero demand and has to count, or an item that sells hard once a month looks steady.
    sd = 0.0
    if demand_qty > 0 and days > 1:
        variance = (flt(dem.sum_sq) - (demand_qty * demand_qty / days)) / (days - 1)
        sd = math.sqrt(variance) if variance > 0 else 0.0

    observed = lead_times.get(code)
    if observed and flt(observed.lead_days) > 0:
        lead_days = flt(observed.lead_days)
        lead_source = _("Purchase history (%s)") % cint(observed.receipts)
    elif cint(item.lead_time_days):
        lead_days = cint(item.lead_time_days)
        lead_source = _("Item master")
    else:
        lead_days = default_lead
        lead_source = _("Filter default")

    safety = flt(z * sd * math.sqrt(lead_days), 3) if sd else 0.0
    if flt(item.safety_stock) > safety:
        # A safety stock typed on the item master is a decision someone made. Never propose less.
        safety = flt(item.safety_stock, 3)

    reorder_level = flt(avg_daily * lead_days + safety, 3)
    order_up_to = flt(reorder_level + avg_daily * coverage, 3)

    actual = flt(bin_row.actual_qty)
    projected = flt(bin_row.projected_qty)
    reorder_qty = flt(order_up_to - projected, 3)
    if reorder_qty < 0:
        reorder_qty = 0.0

    min_order = flt(item.min_order_qty)
    if reorder_qty > 0 and min_order and reorder_qty < min_order:
        reorder_qty = min_order
    if reorder_qty > 0 and item.get("whole_number"):
        reorder_qty = float(math.ceil(reorder_qty))

    rate = flt(bin_row.valuation_rate) or flt(item.last_purchase_rate)
    days_cover = flt(actual / avg_daily, 1) if avg_daily > 0 else None

    action = _action(avg_daily, actual, projected, reorder_level, days_cover, lead_days, coverage)
    if action in ("No Demand", "Dead Stock", "Overstocked"):
        reorder_qty = 0.0

    return {
        "item_code": code,
        "item_name": item.item_name,
        "item_group": item.item_group,
        "warehouse": warehouse,
        "stock_uom": item.stock_uom,
        "sold_qty": flt(move.sold_qty, 3),
        "issued_qty": flt(move.issued_qty, 3),
        "purchased_qty": flt(move.purchased_qty, 3),
        "received_qty": flt(move.received_qty, 3),
        "demand_qty": flt(demand_qty, 3),
        "active_days": cint(dem.active_days),
        "avg_daily": avg_daily,
        "peak_day": flt(dem.peak_day, 3),
        "variability": flt(sd, 3),
        "lead_days": lead_days,
        "lead_source": lead_source,
        "actual_qty": actual,
        "projected_qty": projected,
        "days_cover": days_cover,
        "existing_level": flt(conf.warehouse_reorder_level) if conf else None,
        "safety_stock": safety,
        "reorder_level": reorder_level,
        "order_up_to": order_up_to,
        "reorder_qty": reorder_qty,
        "reorder_value": flt(reorder_qty * rate, 2),
        "stock_value": flt(actual * rate, 2),
        "last_movement": move.get("last_movement"),
        "action": action,
    }


def _action(avg_daily, actual, projected, reorder_level, days_cover, lead_days, coverage):
    if avg_daily <= 0:
        return "Dead Stock" if actual > 0 else "No Demand"
    if actual <= 0:
        return "Out of Stock"
    if projected <= reorder_level * 0.5:
        return "Order Now"
    if projected <= reorder_level:
        return "Below Level"
    # Holding more than twice the lead time plus the coverage an order would be placed for is
    # money sitting on a shelf.
    if days_cover is not None and days_cover > (lead_days + coverage) * OVERSTOCK_MULTIPLE:
        return "Overstocked"
    if projected <= reorder_level * 1.25:
        return "Watch"
    return "OK"


# ── presentation ──────────────────────────────────────────────────────────────

def _columns(company):
    currency = frappe.db.get_value("Company", company, "default_currency")
    return [
        {"label": _("Action"), "fieldname": "action", "fieldtype": "Data", "width": 120},
        {"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item",
         "width": 160},
        {"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
        {"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link",
         "options": "Warehouse", "width": 150},
        {"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Link",
         "options": "Item Group", "width": 140},
        {"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM",
         "width": 80},

        {"label": _("Sold"), "fieldname": "sold_qty", "fieldtype": "Float", "width": 100},
        {"label": _("Consumed"), "fieldname": "issued_qty", "fieldtype": "Float", "width": 105},
        {"label": _("Purchased"), "fieldname": "purchased_qty", "fieldtype": "Float",
         "width": 105},
        {"label": _("Received"), "fieldname": "received_qty", "fieldtype": "Float", "width": 100},

        {"label": _("Demand"), "fieldname": "demand_qty", "fieldtype": "Float", "width": 100},
        {"label": _("Avg / Day"), "fieldname": "avg_daily", "fieldtype": "Float",
         "precision": 3, "width": 100},
        {"label": _("Busiest Day"), "fieldname": "peak_day", "fieldtype": "Float", "width": 110},
        {"label": _("Days Moved"), "fieldname": "active_days", "fieldtype": "Int", "width": 105},
        {"label": _("Variability"), "fieldname": "variability", "fieldtype": "Float",
         "precision": 3, "width": 105},

        {"label": _("Lead Days"), "fieldname": "lead_days", "fieldtype": "Float",
         "precision": 1, "width": 95},
        {"label": _("Lead From"), "fieldname": "lead_source", "fieldtype": "Data", "width": 160},

        {"label": _("In Stock"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 100},
        {"label": _("Projected"), "fieldname": "projected_qty", "fieldtype": "Float",
         "width": 100},
        {"label": _("Days Cover"), "fieldname": "days_cover", "fieldtype": "Float",
         "precision": 1, "width": 105},

        {"label": _("Current Level"), "fieldname": "existing_level", "fieldtype": "Float",
         "width": 115},
        {"label": _("Safety Stock"), "fieldname": "safety_stock", "fieldtype": "Float",
         "width": 110},
        {"label": _("Suggested Level"), "fieldname": "reorder_level", "fieldtype": "Float",
         "width": 130},
        {"label": _("Order Up To"), "fieldname": "order_up_to", "fieldtype": "Float",
         "width": 110},
        {"label": _("Suggested Qty"), "fieldname": "reorder_qty", "fieldtype": "Float",
         "width": 125},
        {"label": _("Order Value"), "fieldname": "reorder_value", "fieldtype": "Currency",
         "options": "currency", "width": 130},
        {"label": _("Stock Value"), "fieldname": "stock_value", "fieldtype": "Currency",
         "options": "currency", "width": 125},
        {"label": _("Last Moved"), "fieldname": "last_movement", "fieldtype": "Date",
         "width": 110},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 1,
         "hidden": 1, "default": currency},
    ]


def _message(filters, days, default_lead, coverage, z, truncated):
    level = filters.get("service_level") or "95%"
    bits = [
        _("<b>Suggested Level</b> = Avg/Day &times; Lead Days + Safety Stock. "
          "<b>Safety Stock</b> = %(z)s &times; Variability &times; &radic;Lead Days, "
          "at a %(level)s service level. <b>Suggested Qty</b> = (Suggested Level + Avg/Day "
          "&times; %(coverage)s coverage days) &minus; Projected Qty."
          ) % {"z": z, "level": level, "coverage": coverage},
        _("Read over %s days. Avg/Day divides by every day in the window, including the days an "
          "item did not move, so a slow seller is never mistaken for a steady one.") % days,
        _("Transfers between your own warehouses are excluded from demand and from supply. Lead "
          "time comes from purchase history where it exists, then the item master, then the "
          "%s-day filter default.") % default_lead,
    ]
    if not cint(filters.get("include_material_issue")):
        bits.append(_("Material Issue consumption is <b>not</b> counted as demand. Tick the box "
                      "to include it."))
    bits.append(
        _("<b>Out of Stock</b> nothing on hand and it sells &nbsp;&middot;&nbsp; "
          "<b>Order Now</b> under half the suggested level &nbsp;&middot;&nbsp; "
          "<b>Below Level</b> under it &nbsp;&middot;&nbsp; "
          "<b>Watch</b> within a quarter of it &nbsp;&middot;&nbsp; "
          "<b>Overstocked</b> more than %(mult)s&times; lead time plus coverage on hand "
          "&nbsp;&middot;&nbsp; <b>Dead Stock</b> holds stock, sold none "
          "&nbsp;&middot;&nbsp; <b>No Demand</b> neither.")
        % {"mult": OVERSTOCK_MULTIPLE}
    )
    bits.append(
        _("An item that sells in occasional large lots gets a large Safety Stock, because one "
          "busy day is what Variability measures. Drop the service level to 85% to order for "
          "the average rather than the peak.")
    )
    if truncated > 0:
        bits.append(
            _("<b>The table shows the first %(cap)s rows, most urgent first; %(rest)s quieter "
              "rows are not listed.</b> The figures above still count all of them. Narrow the "
              "warehouse or item group, or raise Minimum Demand, to see the rest.")
            % {"cap": ROW_CAP, "rest": truncated}
        )
    return ("<div style='padding:8px 10px;border-left:3px solid #1f6f54;background:#f4f9f7'>"
            + "<br>".join(bits) + "</div>")


def _chart(data):
    points = [d for d in data if flt(d["reorder_value"]) > 0][:10]
    if not points:
        return None
    return {
        "data": {
            "labels": [d["item_code"] for d in points],
            "datasets": [{"name": _("Order Value"),
                          "values": [flt(d["reorder_value"]) for d in points]}],
        },
        "type": "bar",
        "colors": ["#1f6f54"],
        "fieldtype": "Currency",
    }


def _summary(data):
    urgent = [d for d in data if d["action"] in ("Out of Stock", "Order Now", "Below Level")]
    idle = [d for d in data if d["action"] in ("Dead Stock", "Overstocked")]
    return [
        {"label": _("Needs Ordering"), "value": len(urgent), "datatype": "Int",
         "indicator": "Red" if urgent else "Green"},
        {"label": _("Out of Stock"),
         "value": len([d for d in data if d["action"] == "Out of Stock"]),
         "datatype": "Int", "indicator": "Red"},
        {"label": _("Suggested Order Value"),
         "value": flt(sum(flt(d["reorder_value"]) for d in data), 2),
         "datatype": "Currency", "indicator": "Blue"},
        {"label": _("Idle Stock Value"),
         "value": flt(sum(flt(d["stock_value"]) for d in idle), 2),
         "datatype": "Currency", "indicator": "Orange"},
        {"label": _("Item / Warehouse Rows"), "value": len(data), "datatype": "Int",
         "indicator": "Grey"},
    ]
