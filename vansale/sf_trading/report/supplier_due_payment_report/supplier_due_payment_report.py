# apps/vansale/vansale/sf_trading/report/supplier_due_payment_report/supplier_due_payment_report.py
"""Supplier Due Payment Report — outstanding supplier payables by due date.

Submitted Purchase Invoices with outstanding_amount > 0, with overdue-days and
ageing buckets computed as-on a chosen date. Robust against null due dates.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, nowdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns, data = get_columns(), get_data(filters)
    attach_payment_advice(data)
    return columns, data


def attach_payment_advice(rows):
    """Show which invoices are already sitting on a Payment Advice.

    Answers the question this report always raised but could not: "have we already told
    someone we would pay this?" Silently skipped on a site where Payment Advice is not
    installed yet.
    """
    from vansale.sf_trading.doctype.payment_advice.payment_advice import get_advice_map

    advice_map = get_advice_map([r.get("purchase_invoice") for r in rows if r.get("purchase_invoice")])
    for row in rows:
        entry = advice_map.get(row.get("purchase_invoice")) or {}
        row["payment_advice"] = entry.get("advice")
        row["advice_status"] = entry.get("status")


def _bucket(days):
    if days <= 0:
        return "Not Due"
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def get_data(filters):
    as_on = getdate(filters.get("as_on_date") or nowdate())

    conds = [
        ["Purchase Invoice", "docstatus", "=", 1],
        ["Purchase Invoice", "outstanding_amount", ">", 0],
    ]
    if filters.get("company"):
        conds.append(["Purchase Invoice", "company", "=", filters.company])
    if filters.get("supplier"):
        conds.append(["Purchase Invoice", "supplier", "=", filters.supplier])
    if filters.get("due_from"):
        conds.append(["Purchase Invoice", "due_date", ">=", getdate(filters.due_from)])
    if filters.get("due_to"):
        conds.append(["Purchase Invoice", "due_date", "<=", getdate(filters.due_to)])

    rows = frappe.get_all(
        "Purchase Invoice",
        filters=conds,
        fields=[
            "name", "supplier", "supplier_name", "bill_no", "bill_date", "posting_date",
            "due_date", "grand_total", "outstanding_amount", "currency", "status",
            "on_hold", "company",
        ],
        order_by="due_date asc, name asc",
    )

    overdue_only = cint(filters.get("overdue_only"))
    want_bucket = filters.get("ageing_bucket")
    out = []
    for r in rows:
        due = getdate(r.due_date) if r.due_date else None
        overdue_days = date_diff(as_on, due) if due else 0
        if overdue_days < 0:
            overdue_days = 0
        if overdue_only and overdue_days <= 0:
            continue
        bucket = _bucket(overdue_days)
        if want_bucket and bucket != want_bucket:
            continue
        out.append({
            "supplier": r.supplier,
            "supplier_name": r.supplier_name,
            "purchase_invoice": r.name,
            "bill_no": r.bill_no,
            "bill_date": r.bill_date,
            "posting_date": r.posting_date,
            "due_date": due,
            "overdue_days": overdue_days,
            "ageing": bucket,
            "grand_total": flt(r.grand_total),
            "outstanding_amount": flt(r.outstanding_amount),
            "currency": r.currency,
            "on_hold": "Yes" if r.on_hold else "No",
            "status": r.status,
            "company": r.company,
        })
    return out


def get_columns():
    return [
        {"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 140},
        {"label": _("Supplier Name"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 180},
        {"label": _("Purchase Invoice"), "fieldname": "purchase_invoice", "fieldtype": "Link", "options": "Purchase Invoice", "width": 160},
        {"label": _("Supplier Bill No"), "fieldname": "bill_no", "fieldtype": "Data", "width": 120},
        {"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
        {"label": _("Overdue Days"), "fieldname": "overdue_days", "fieldtype": "Int", "width": 90},
        {"label": _("Ageing"), "fieldname": "ageing", "fieldtype": "Data", "width": 80},
        {"label": _("Grand Total"), "fieldname": "grand_total", "fieldtype": "Currency", "options": "currency", "width": 120},
        {"label": _("Outstanding"), "fieldname": "outstanding_amount", "fieldtype": "Currency", "options": "currency", "width": 120},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 70},
        {"label": _("On Hold"), "fieldname": "on_hold", "fieldtype": "Data", "width": 70},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Payment Advice"), "fieldname": "payment_advice", "fieldtype": "Link",
         "options": "Payment Advice", "width": 140},
        {"label": _("Advice Status"), "fieldname": "advice_status", "fieldtype": "Data", "width": 110},
        {"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 150},
    ]
