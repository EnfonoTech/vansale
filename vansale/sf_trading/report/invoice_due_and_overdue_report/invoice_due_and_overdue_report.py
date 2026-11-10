# apps/vansale/vansale/sf_trading/report/invoice_due_and_overdue_report/invoice_due_and_overdue_report.py
"""Invoice Due & Overdue Report — combined Sales + Purchase outstanding by due date.

One row per submitted Sales Invoice / Purchase Invoice with ``outstanding_amount > 0``.
Overdue days and ageing buckets are computed as-on a chosen date (default today).

Currency note (verified against prod on 2026-07-25): ``outstanding_amount`` is stored
in ``party_account_currency``, which on this company is the company currency (BHD),
even when the invoice itself is raised in SAR/USD. It must therefore NOT be multiplied
by ``conversion_rate``. ``grand_total`` stays in the invoice currency; ``base_grand_total``
is the company-currency value of the same total.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

BUCKETS = ("Not Due", "0-30", "31-60", "61-90", "90+")

DOCTYPES = {
    "Sales": {
        "doctype": "Sales Invoice",
        "party_field": "customer",
        "party_name_field": "customer_name",
    },
    "Purchase": {
        "doctype": "Purchase Invoice",
        "party_field": "supplier",
        "party_name_field": "supplier_name",
    },
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns, data = get_columns(), get_data(filters)
    attach_payment_advice(data)
    return columns, data


def attach_payment_advice(rows):
    """Flag rows already covered by a Payment Advice, so chasing effort is not duplicated."""
    from vansale.sf_trading.doctype.payment_advice.payment_advice import get_advice_map

    advice_map = get_advice_map([r.get("invoice") for r in rows if r.get("invoice")])
    for row in rows:
        entry = advice_map.get(row.get("invoice")) or {}
        row["payment_advice"] = entry.get("advice")
        row["advice_status"] = entry.get("status")


def _bucket(days):
    """Ageing bucket for a given number of overdue days."""
    if days <= 0:
        return "Not Due"
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def _build_conditions(filters, meta):
    conditions = {"docstatus": 1, "outstanding_amount": [">", 0]}

    if filters.get("company"):
        conditions["company"] = filters.get("company")
    if filters.get("branch"):
        conditions["branch"] = filters.get("branch")
    if filters.get("party"):
        conditions[meta["party_field"]] = filters.get("party")

    due_from = getdate(filters.get("due_from")) if filters.get("due_from") else None
    due_to = getdate(filters.get("due_to")) if filters.get("due_to") else None
    if due_from and due_to:
        conditions["due_date"] = ["between", [due_from, due_to]]
    elif due_from:
        conditions["due_date"] = [">=", due_from]
    elif due_to:
        conditions["due_date"] = ["<=", due_to]

    return conditions


def _fetch(kind, filters, as_on):
    """Return report rows for one invoice kind ("Sales" / "Purchase")."""
    meta = DOCTYPES[kind]
    fields = [
        "name",
        "posting_date",
        "due_date",
        "company",
        "branch",
        "currency",
        "grand_total",
        "base_grand_total",
        "outstanding_amount",
        "status",
        "is_return",
        "epromise_vr_no",
        f"{meta['party_field']} as party",
        f"{meta['party_name_field']} as party_name",
    ]

    rows = []
    min_outstanding = flt(filters.get("min_outstanding"))

    for row in frappe.get_all(
        meta["doctype"],
        filters=_build_conditions(filters, meta),
        fields=fields,
        order_by="due_date asc, name asc",
        ignore_permissions=False,
    ):
        outstanding = flt(row.outstanding_amount)
        if min_outstanding and outstanding < min_outstanding:
            continue

        # due_date is mandatory in ERPNext; fall back to posting_date defensively.
        reference_date = getdate(row.due_date or row.posting_date)
        overdue_days = date_diff(as_on, reference_date)
        bucket = _bucket(overdue_days)

        if filters.get("overdue_only") and overdue_days <= 0:
            continue
        if filters.get("ageing_bucket") and bucket != filters.get("ageing_bucket"):
            continue

        rows.append(
            {
                "invoice_type": kind,
                "invoice": row.name,
                "invoice_doctype": meta["doctype"],
                "posting_date": row.posting_date,
                "due_date": row.due_date,
                "party": row.party,
                "party_name": row.party_name,
                "currency": row.currency,
                "grand_total": flt(row.grand_total),
                "base_grand_total": flt(row.base_grand_total),
                "outstanding_amount": outstanding,
                "overdue_days": overdue_days if overdue_days > 0 else 0,
                "ageing_bucket": bucket,
                "status": row.status,
                "is_return": row.is_return,
                "branch": row.branch,
                "company": row.company,
                "epromise_vr_no": row.epromise_vr_no,
            }
        )

    return rows


def get_data(filters):
    as_on = getdate(filters.get("as_on_date") or nowdate())
    wanted = filters.get("invoice_type") or "Both"

    data = []
    if wanted in ("Both", "Sales"):
        data += _fetch("Sales", filters, as_on)
    if wanted in ("Both", "Purchase"):
        data += _fetch("Purchase", filters, as_on)

    # Worst offenders first: most overdue, then largest outstanding.
    data.sort(key=lambda r: (-r["overdue_days"], -r["outstanding_amount"]))
    return data


def get_columns():
    return [
        {
            "fieldname": "invoice_type",
            "label": _("Type"),
            "fieldtype": "Data",
            "width": 90,
        },
        {
            "fieldname": "invoice",
            "label": _("Invoice"),
            "fieldtype": "Dynamic Link",
            "options": "invoice_doctype",
            "width": 180,
        },
        {
            "fieldname": "invoice_doctype",
            "label": _("Invoice DocType"),
            "fieldtype": "Data",
            "hidden": 1,
            "width": 1,
        },
        {
            "fieldname": "party",
            "label": _("Party"),
            "fieldtype": "Data",
            "width": 130,
        },
        {
            "fieldname": "party_name",
            "label": _("Party Name"),
            "fieldtype": "Data",
            "width": 220,
        },
        {
            "fieldname": "posting_date",
            "label": _("Posting Date"),
            "fieldtype": "Date",
            "width": 105,
        },
        {
            "fieldname": "due_date",
            "label": _("Due Date"),
            "fieldtype": "Date",
            "width": 105,
        },
        {
            "fieldname": "overdue_days",
            "label": _("Overdue Days"),
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "fieldname": "ageing_bucket",
            "label": _("Ageing"),
            "fieldtype": "Data",
            "width": 90,
        },
        {
            "fieldname": "outstanding_amount",
            "label": _("Outstanding"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "currency",
            "label": _("Invoice Currency"),
            "fieldtype": "Link",
            "options": "Currency",
            "width": 80,
        },
        {
            "fieldname": "grand_total",
            "label": _("Grand Total (Invoice Ccy)"),
            "fieldtype": "Currency",
            "options": "currency",
            "width": 150,
        },
        {
            "fieldname": "base_grand_total",
            "label": _("Grand Total"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "status",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "fieldname": "branch",
            "label": _("Branch"),
            "fieldtype": "Link",
            "options": "Branch",
            "width": 90,
        },
        {
            "fieldname": "epromise_vr_no",
            "label": _("ePromise VR"),
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "fieldname": "payment_advice",
            "label": _("Payment Advice"),
            "fieldtype": "Link",
            "options": "Payment Advice",
            "width": 140,
        },
        {
            "fieldname": "advice_status",
            "label": _("Advice Status"),
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "fieldname": "company",
            "label": _("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "width": 160,
        },
    ]
