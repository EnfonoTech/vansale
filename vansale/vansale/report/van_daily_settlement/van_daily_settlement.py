"""Van Daily Settlement — the evening reconciliation sheet.

One row per van per day: what was sold, what came back, what was collected in
cash at the point of sale, and what is still owed. This is the report the
office uses to check a driver's cash-in against the system before releasing
them for the next day.

Returns are NOT subtracted twice: ERPNext stores a credit note with a negative
`base_grand_total`, so `SUM(base_grand_total)` over all invoices is already the
net figure. `gross_sales` and `returns_value` split that sum for readability
and always satisfy `net_sales = gross_sales - returns_value`.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from vansale.vansale.report.vansale_report_utils import (
    company_scope,
    date_range,
    van_scope,
)


def execute(filters=None):
    filters = frappe._dict(filters or {})

    where = ""
    values: dict = {}
    for fragment, binds in (
        date_range(filters, "posting_date"),
        van_scope(filters),
        company_scope(filters),
    ):
        where += fragment
        values.update(binds)

    rows = frappe.db.sql(
        f"""
        SELECT
            doc.posting_date                                          AS posting_date,
            vcu.parent                                                AS van,
            doc.owner                                                 AS user,
            COUNT(DISTINCT CASE WHEN doc.is_return = 0 THEN doc.name END) AS invoices,
            COUNT(DISTINCT CASE WHEN doc.is_return = 1 THEN doc.name END) AS credit_notes,
            SUM(CASE WHEN doc.is_return = 0 THEN doc.base_grand_total ELSE 0 END)  AS gross_sales,
            SUM(CASE WHEN doc.is_return = 1 THEN -doc.base_grand_total ELSE 0 END) AS returns_value,
            SUM(doc.base_grand_total)                                 AS net_sales,
            SUM(doc.base_paid_amount)                                 AS collected_at_sale,
            SUM(doc.outstanding_amount)                               AS outstanding
        FROM `tabSales Invoice` doc
        LEFT JOIN `tabVansale Configuration User` vcu ON vcu.user = doc.owner
        WHERE doc.docstatus = 1 {where}
        GROUP BY doc.posting_date, vcu.parent, doc.owner
        ORDER BY doc.posting_date DESC, vcu.parent ASC
        """,
        values,
        as_dict=True,
    )

    for r in rows:
        # Credit sales = what the driver did not bring back as cash.
        r["credit_sales"] = flt(r.net_sales) - flt(r.collected_at_sale)

    return _columns(), rows


def _columns() -> list[dict]:
    return [
        {"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
        {
            "fieldname": "van",
            "label": _("Van"),
            "fieldtype": "Link",
            "options": "Vansale Configuration",
            "width": 150,
        },
        {
            "fieldname": "user",
            "label": _("Driver"),
            "fieldtype": "Link",
            "options": "User",
            "width": 180,
        },
        {"fieldname": "invoices", "label": _("Invoices"), "fieldtype": "Int", "width": 90},
        {"fieldname": "credit_notes", "label": _("Returns"), "fieldtype": "Int", "width": 90},
        {
            "fieldname": "gross_sales",
            "label": _("Gross Sales"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "returns_value",
            "label": _("Returns Value"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "net_sales",
            "label": _("Net Sales"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "collected_at_sale",
            "label": _("Cash Collected"),
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "fieldname": "credit_sales",
            "label": _("On Credit"),
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "fieldname": "outstanding",
            "label": _("Outstanding"),
            "fieldtype": "Currency",
            "width": 130,
        },
    ]
