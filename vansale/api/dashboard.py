"""Dashboard aggregates — today's sales + collection + outstanding."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import frappe
from frappe.utils import getdate, nowdate

from vansale.api.datetime_util import naive_site_to_utc_iso


@frappe.whitelist(methods=["GET"])
def today_sales() -> dict:
    user = frappe.session.user
    today = getdate(nowdate())
    total = (
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(grand_total), 0), COUNT(name)
            FROM `tabSales Invoice`
            WHERE docstatus = 1 AND is_return = 0
              AND posting_date = %s AND owner = %s
            """,
            (today, user),
        )[0]
    )
    returned = (
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(ABS(grand_total)), 0)
            FROM `tabSales Invoice`
            WHERE docstatus = 1 AND is_return = 1
              AND posting_date = %s AND owner = %s
            """,
            (today, user),
        )[0][0]
    )
    return {
        "amount": float(total[0] or 0),
        "count": int(total[1] or 0),
        "returned": float(returned or 0),
    }


@frappe.whitelist(methods=["GET"])
def today_collection() -> dict:
    user = frappe.session.user
    today = getdate(nowdate())
    rows = frappe.db.sql(
        """
        SELECT mode_of_payment, COALESCE(SUM(paid_amount), 0) amt, COUNT(name) n
        FROM `tabPayment Entry`
        WHERE docstatus = 1 AND payment_type = 'Receive'
          AND posting_date = %s AND owner = %s
        GROUP BY mode_of_payment
        """,
        (today, user),
        as_dict=True,
    )
    total = sum(float(r.get("amt") or 0) for r in rows)
    return {
        "amount": total,
        "by_mode": [{"mode": r["mode_of_payment"], "amount": float(r["amt"] or 0), "count": int(r["n"] or 0)} for r in rows],
    }


@frappe.whitelist(methods=["GET"])
def month_summary(offset: int = 0) -> dict:
    """Aggregate for the current or previous months (``offset=0`` is current)."""
    today = getdate(nowdate())
    year, month = today.year, today.month
    while offset > 0:
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        offset -= 1
    first = date(year, month, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)

    user = frappe.session.user
    sales = frappe.db.sql(
        """
        SELECT COALESCE(SUM(grand_total), 0)
        FROM `tabSales Invoice`
        WHERE docstatus = 1 AND is_return = 0 AND owner = %s
          AND posting_date BETWEEN %s AND %s
        """,
        (user, first, last),
    )[0][0]
    collections = frappe.db.sql(
        """
        SELECT COALESCE(SUM(paid_amount), 0)
        FROM `tabPayment Entry`
        WHERE docstatus = 1 AND payment_type = 'Receive' AND owner = %s
          AND posting_date BETWEEN %s AND %s
        """,
        (user, first, last),
    )[0][0]
    return {
        "from": str(first),
        "to": str(last),
        "sales": float(sales or 0),
        "collections": float(collections or 0),
    }


@frappe.whitelist(methods=["GET"])
def recent_activity(limit: int = 10) -> list[dict]:
    """Last N sales invoices + payments for the current user."""
    user = frappe.session.user
    rows = frappe.db.sql(
        """
        SELECT 'invoice' AS kind, name, customer AS party, grand_total AS amount, posting_date, modified
        FROM `tabSales Invoice`
        WHERE docstatus = 1 AND is_return = 0 AND owner = %s
        UNION ALL
        SELECT 'payment' AS kind, name, party, paid_amount AS amount, posting_date, modified
        FROM `tabPayment Entry`
        WHERE docstatus = 1 AND payment_type = 'Receive' AND owner = %s
        ORDER BY modified DESC
        LIMIT %s
        """,
        (user, user, int(limit)),
        as_dict=True,
    )
    for r in rows:
        r["amount"] = float(r.get("amount") or 0)
        r["posting_date"] = str(r.get("posting_date") or "")
        r["modified"] = naive_site_to_utc_iso(r.get("modified"))
    return rows


@frappe.whitelist(methods=["GET"])
def warehouses(company: Optional[str] = None) -> list[dict]:
    """List stock warehouses. If the user has a Vansale Configuration
    (and therefore User Permissions for a subset of warehouses), return
    ONLY those — otherwise return all active warehouses for the company.
    """
    user = frappe.session.user
    # Van user path — restrict to configured warehouses.
    user_whs = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Warehouse"},
        pluck="for_value",
    )
    if user_whs:
        rows = frappe.get_all(
            "Warehouse",
            filters={"name": ["in", user_whs], "is_group": 0, "disabled": 0},
            fields=["name", "warehouse_name"],
            order_by="warehouse_name",
        )
        return rows

    company = (
        company
        or frappe.db.get_value(
            "User Permission",
            {"user": user, "allow": "Company", "is_default": 1},
            "for_value",
        )
        or frappe.defaults.get_user_default("Company", user)
        or frappe.db.get_single_value("Global Defaults", "default_company")
    )
    filters: dict = {"is_group": 0, "disabled": 0}
    if company:
        filters["company"] = company
    return frappe.get_all(
        "Warehouse",
        filters=filters,
        fields=["name", "warehouse_name"],
        limit=200,
        order_by="warehouse_name",
    )
